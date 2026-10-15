from datetime import datetime

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import Engine

from flowagent.agent.prompts import build_system_prompt
from flowagent.agent.service import FlowAgent
from flowagent.agent.tools import create_event, create_project_plan, create_task
from flowagent.agent.workflow_tools import check_schedule, progress_report, remember_fact
from flowagent.db import crud
from flowagent.db.models import Priority, Task, TaskStatus
from flowagent.db.schemas import TaskCreate, TaskUpdate
from flowagent.db.session import session_scope
from tests.conftest import FIXED_NOW, fixed_clock
from tests.test_agent_service import ScriptedChatModel, tool_call_message

THREAD_ID = "workflow-thread"
MEETING_ITEMS = [
    {"title": "Gửi slide cho khách", "owner": "Lan", "deadline": "2026-10-16 17:00"},
    {"title": "Cập nhật tài liệu API", "priority": "high"},
]


def make_agent(engine: Engine, replies: list[AIMessage]) -> FlowAgent:
    """Create an agent that plays back scripted replies."""
    return FlowAgent(ScriptedChatModel(messages=iter(replies)), engine, clock=fixed_clock)


def stored_tasks(engine: Engine) -> list[Task]:
    """Read every stored task."""
    with session_scope(engine) as session:
        return list(crud.list_tasks(session))


def seed_task(engine: Engine, **fields: object) -> int:
    """Insert a task and return its id."""
    with session_scope(engine) as session:
        return crud.create_task(session, TaskCreate(**fields)).id


@pytest.mark.parametrize(("is_approved", "expected_count"), [(True, 2), (False, 0)])
def test_notes_to_tasks_asks_before_creating(
    engine: Engine, is_approved: bool, expected_count: int
) -> None:
    """Action items are previewed, then created with owner and source only when approved."""
    call = tool_call_message(
        "create_tasks_from_notes", {"meeting_title": "Họp sprint", "items": MEETING_ITEMS}
    )
    agent = make_agent(engine, [call, AIMessage("Xong.")])
    paused = agent.send(THREAD_ID, "Biên bản họp: ...")
    assert paused.pending_confirmation["action"] == "create_tasks_from_notes"
    assert "Gửi slide cho khách (Lan)" in paused.pending_confirmation["summary"]
    agent.resolve_confirmation(THREAD_ID, is_approved)
    tasks = stored_tasks(engine)
    assert len(tasks) == expected_count
    if is_approved:
        assert tasks[0].deadline == datetime(2026, 10, 16, 17, 0)
        assert "Người phụ trách: Lan" in tasks[0].description
        assert tasks[1].priority == Priority.HIGH


def test_reschedule_moves_overdue_tasks_after_confirmation(
    engine: Engine, tool_config: dict
) -> None:
    """Overdue work is moved to the next free working hours, around an existing meeting."""
    report_id = seed_task(
        engine, title="Viết báo cáo", deadline=datetime(2026, 10, 13, 23, 59), estimated_minutes=60
    )
    create_event.invoke({"title": "Họp", "start": "2026-10-15 09:00"}, tool_config)
    agent = make_agent(engine, [tool_call_message("reschedule_tasks", {}), AIMessage("Xong.")])
    paused = agent.send(THREAD_ID, "Xếp lại các việc bị trễ")
    assert paused.pending_confirmation["action"] == "reschedule_tasks"
    agent.resolve_confirmation(THREAD_ID, is_approved=True)
    with session_scope(engine) as session:
        task = crud.get_task(session, report_id)
    assert (task.planned_start, task.deadline) == (
        datetime(2026, 10, 15, 10, 0),
        datetime(2026, 10, 15, 11, 0),
    )


def test_project_plan_fits_target_date(engine: Engine, tool_config: dict) -> None:
    """A plan with a tight target date uses longer working days and says so."""
    steps = [{"title": f"Bước {index}", "estimated_minutes": 240} for index in range(3)]
    result = create_project_plan.invoke(
        {"project_name": "Web", "goal": "Làm web", "steps": steps, "finish_by": "2026-10-16"},
        tool_config,
    )
    assert "Để kịp hạn 2026-10-16 23:59: làm 6 giờ/ngày." in result
    assert max(task.deadline for task in stored_tasks(engine)) <= datetime(2026, 10, 16, 23, 59)


def test_create_event_warns_about_clash(engine: Engine, tool_config: dict) -> None:
    """Creating an event over a planned work block returns a clash warning."""
    create_task.invoke(
        {"title": "Code", "planned_start": "2026-10-15 09:00", "estimated_minutes": 120},
        tool_config,
    )
    result = create_event.invoke({"title": "Họp nhóm", "start": "2026-10-15 10:00"}, tool_config)
    assert "Trùng giờ" in result and "Code" in result


def test_check_schedule_lists_risks(engine: Engine, tool_config: dict) -> None:
    """The schedule check reports overdue tasks, and says all is well when nothing is wrong."""
    assert "Không có lịch trùng giờ" in check_schedule.invoke({}, tool_config)
    seed_task(engine, title="Nộp thuế", deadline=datetime(2026, 10, 13, 23, 59))
    assert "Nộp thuế: đã quá hạn" in check_schedule.invoke({}, tool_config)


def test_progress_report_tool_counts_completed_work(engine: Engine, tool_config: dict) -> None:
    """The weekly report counts tasks finished this week."""
    task_id = seed_task(engine, title="Làm slide")
    with session_scope(engine) as session:
        crud.update_task(session, task_id, TaskUpdate(status=TaskStatus.DONE))
        crud.get_task(session, task_id).completed_at = FIXED_NOW
    report = progress_report.invoke({"period": "week"}, tool_config)
    assert "Đã hoàn thành: 1" in report and "Làm slide" in report


def test_remembered_facts_reach_the_system_prompt(engine: Engine, tool_config: dict) -> None:
    """A remembered habit is stored once and injected into later prompts."""
    remember_fact.invoke({"fact": "Thích làm việc khó vào buổi sáng"}, tool_config)
    remember_fact.invoke({"fact": "thich lam viec kho vao buoi sang"}, tool_config)
    agent = make_agent(engine, [])
    assert agent._read_memories() == ["Thích làm việc khó vào buổi sáng"]
    prompt = build_system_prompt(FIXED_NOW, agent._read_memories())
    assert "- Thích làm việc khó vào buổi sáng" in prompt


def test_history_and_pending_confirmation_survive_in_checkpointer(engine: Engine) -> None:
    """The visible conversation and an unanswered confirmation are read back from the store."""
    task_id = seed_task(engine, title="Đi chợ")
    agent = make_agent(
        engine,
        [AIMessage("Chào bạn!"), tool_call_message("delete_task", {"task_id": task_id})],
    )
    agent.send(THREAD_ID, "Xin chào")
    agent.send(THREAD_ID, "Xoá việc đi chợ")
    history = agent.history(THREAD_ID)
    assert [(message.role, message.text) for message in history] == [
        ("user", "Xin chào"),
        ("assistant", "Chào bạn!"),
        ("user", "Xoá việc đi chợ"),
    ]
    assert agent.pending_confirmation(THREAD_ID)["action"] == "delete_task"
