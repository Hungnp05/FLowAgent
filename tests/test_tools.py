from datetime import datetime

import pytest
from sqlalchemy import Engine

from flowagent.agent.tools import (
    DEPS_CONFIG_KEY,
    ToolDeps,
    create_project_plan,
    create_task,
    list_tasks,
    parse_local_datetime,
    plan_my_day,
    predict_priority,
    update_task,
)
from flowagent.db import crud
from flowagent.db.models import Priority, TaskStatus
from flowagent.db.session import session_scope
from flowagent.errors import (
    InvalidDateError,
    InvalidScheduleError,
    PriorityModelUnavailableError,
)
from flowagent.ml.labels import PriorityPrediction
from tests.conftest import fixed_clock


def test_parse_date_only_means_end_of_day() -> None:
    """A bare date is interpreted as 23:59 on that day."""
    assert parse_local_datetime("2026-10-17") == datetime(2026, 10, 17, 23, 59)


def test_parse_datetime_with_time() -> None:
    """A date with time keeps the given hour and minute."""
    assert parse_local_datetime("2026-10-17 14:30") == datetime(2026, 10, 17, 14, 30)


def test_parse_invalid_datetime_raises() -> None:
    """Unparseable input raises InvalidDateError with a format hint."""
    with pytest.raises(InvalidDateError):
        parse_local_datetime("thứ sáu")


def test_create_task_tool_persists_task(engine, tool_config: dict) -> None:
    """The create_task tool stores the task with a parsed deadline."""
    result = create_task.invoke(
        {"title": "Nộp báo cáo", "priority": "high", "deadline": "2026-10-17 17:00"}, tool_config
    )
    assert "Nộp báo cáo" in result
    with session_scope(engine) as session:
        task = crud.list_tasks(session)[0]
    assert task.priority == Priority.HIGH
    assert task.deadline == datetime(2026, 10, 17, 17, 0)


def test_update_task_tool_changes_only_given_fields(engine, tool_config: dict) -> None:
    """Fields not passed to update_task keep their previous values."""
    create_task.invoke({"title": "Ôn thi", "priority": "high"}, tool_config)
    update_task.invoke({"task_id": 1, "status": "done"}, tool_config)
    with session_scope(engine) as session:
        task = crud.get_task(session, 1)
    assert task.status == TaskStatus.DONE
    assert task.priority == Priority.HIGH


def test_list_tasks_tool_reports_empty_result(tool_config: dict) -> None:
    """An empty search returns a readable message rather than an empty string."""
    assert "Không có" in list_tasks.invoke({}, tool_config)


def test_plan_my_day_tool_lists_open_tasks(tool_config: dict) -> None:
    """plan_my_day includes open tasks with their reasons."""
    create_task.invoke({"title": "Gửi email", "estimated_minutes": 30}, tool_config)
    assert "Gửi email" in plan_my_day.invoke({}, tool_config)


def test_create_project_plan_schedules_steps(engine, tool_config: dict) -> None:
    """create_project_plan creates a project whose steps get planned start times."""
    steps = [
        {"title": "Thiết kế giao diện", "estimated_minutes": 120},
        {"title": "Viết backend", "estimated_minutes": 240},
    ]
    create_project_plan.invoke(
        {"project_name": "Website", "goal": "Làm website bán hàng", "steps": steps}, tool_config
    )
    with session_scope(engine) as session:
        project = crud.get_project_by_name(session, "Website")
        tasks = crud.list_tasks(session)
    assert all(task.project_id == project.id for task in tasks)
    assert tasks[0].planned_start == datetime(2026, 10, 15, 9, 0)
    assert tasks[1].planned_start == tasks[0].deadline


def test_create_task_tool_sets_start_at_workday_start(engine, tool_config: dict) -> None:
    """A bare start date is interpreted as 09:00 while a bare deadline stays at 23:59."""
    create_task.invoke(
        {"title": "Làm slide", "planned_start": "2026-10-20", "deadline": "2026-10-22"},
        tool_config,
    )
    with session_scope(engine) as session:
        task = crud.list_tasks(session)[0]
    assert task.planned_start == datetime(2026, 10, 20, 9, 0)
    assert task.deadline == datetime(2026, 10, 22, 23, 59)


def test_create_task_tool_reports_start_after_deadline(tool_config: dict) -> None:
    """An inverted schedule raises a domain error that the agent middleware returns to the model."""
    with pytest.raises(InvalidScheduleError):
        create_task.invoke(
            {"title": "Sai", "planned_start": "2026-10-22", "deadline": "2026-10-20"}, tool_config
        )


def config_with_predictor(engine, prediction: PriorityPrediction) -> dict:
    """Build a tool config whose priority model always returns the given prediction."""
    deps = ToolDeps(engine=engine, clock=fixed_clock, predict_priority=lambda text: prediction)
    return {"configurable": {DEPS_CONFIG_KEY: deps}}


def test_create_task_uses_model_when_priority_missing(engine) -> None:
    """Without an explicit priority the model's suggestion is stored and mentioned."""
    config = config_with_predictor(engine, PriorityPrediction(Priority.URGENT, 0.81))
    result = create_task.invoke({"title": "Server sập"}, config)
    assert "81%" in result
    with session_scope(engine) as session:
        assert crud.list_tasks(session)[0].priority == Priority.URGENT


def test_create_task_keeps_explicit_priority(engine) -> None:
    """An explicit priority from the user always wins over the model."""
    config = config_with_predictor(engine, PriorityPrediction(Priority.URGENT, 0.81))
    create_task.invoke({"title": "Đọc sách", "priority": "low"}, config)
    with session_scope(engine) as session:
        assert crud.list_tasks(session)[0].priority == Priority.LOW


def test_create_task_falls_back_to_medium_when_model_fails(engine) -> None:
    """A crashing model must not block task creation."""

    def broken_predictor(text: str) -> PriorityPrediction:
        """Simulate a model failure."""
        raise RuntimeError("model file corrupted")

    deps = ToolDeps(engine=engine, clock=fixed_clock, predict_priority=broken_predictor)
    create_task.invoke({"title": "Đi chợ"}, {"configurable": {DEPS_CONFIG_KEY: deps}})
    with session_scope(engine) as session:
        assert crud.list_tasks(session)[0].priority == Priority.MEDIUM


def test_predict_priority_tool_reports_confidence(engine) -> None:
    """The predict_priority tool returns the level and confidence."""
    config = config_with_predictor(engine, PriorityPrediction(Priority.HIGH, 0.6))
    assert predict_priority.invoke({"text": "Sửa lỗi thanh toán"}, config) == (
        "Gợi ý: high (độ tin cậy 60%)"
    )


def test_predict_priority_tool_without_model_raises(tool_config: dict) -> None:
    """Without a trained model the tool raises a domain error the agent can explain."""
    with pytest.raises(PriorityModelUnavailableError):
        predict_priority.invoke({"text": "x"}, tool_config)


def test_list_tasks_keyword_search_includes_done_tasks(tool_config: dict) -> None:
    """Searching by keyword finds finished tasks so they can be reopened."""
    create_task.invoke({"title": "Viết blog cá nhân"}, tool_config)
    update_task.invoke({"task_id": 1, "status": "done"}, tool_config)
    assert "Viết blog" in list_tasks.invoke({"keyword": "viet blog"}, tool_config)
    assert "Viết blog" not in list_tasks.invoke({}, tool_config)


def test_update_task_without_changes_is_a_calm_no_op(engine: Engine, tool_config: dict) -> None:
    """An empty update leaves the task untouched and tells the model nothing more is needed."""
    create_task.invoke({"title": "Nộp học phí", "priority": "high"}, tool_config)
    result = update_task.invoke({"task_id": 1, "priority": None}, tool_config)
    assert "Không có gì thay đổi" in result and "không cần gọi thêm" in result
    with session_scope(engine) as session:
        assert crud.get_task(session, 1).priority == Priority.HIGH


def test_create_task_uses_medium_when_model_is_unsure(engine) -> None:
    """A low-confidence suggestion is not applied; the task gets medium and says why."""
    unsure = PriorityPrediction(Priority.HIGH, 0.54, is_confident=False)
    result = create_task.invoke({"title": "Ôn thi"}, config_with_predictor(engine, unsure))
    assert "chưa đủ chắc chắn" in result
    with session_scope(engine) as session:
        assert crud.list_tasks(session)[0].priority == Priority.MEDIUM
