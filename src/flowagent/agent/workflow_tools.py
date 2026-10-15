from datetime import datetime, timedelta
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from sqlmodel import Session

from flowagent.agent.formatting import (
    format_datetime,
    format_deadline_fit,
    format_progress_report,
    format_reschedule,
    format_schedule_alerts,
    format_tasks,
)
from flowagent.agent.tools import (
    MAX_STEP_MINUTES,
    ToolDeps,
    get_deps,
    parse_optional_datetime,
    suggest_priority,
)
from flowagent.db import crud
from flowagent.db.models import MAX_MEMORY_LENGTH, Priority, Task
from flowagent.db.schemas import TaskCreate, TaskFilter, TaskUpdate
from flowagent.db.session import session_scope
from flowagent.planning.alerts import ALERT_HORIZON_DAYS, find_at_risk_tasks, find_conflicts
from flowagent.planning.progress import ReportPeriod, build_progress_report
from flowagent.planning.scheduler import (
    DEFAULT_TASK_MINUTES,
    needs_rescheduling,
    order_for_rescheduling,
    plan_within_deadline,
)
from flowagent.schedule_queries import read_busy_periods, read_calendar_entries

CREATE_CANCELLED_MESSAGE = "Người dùng đã huỷ, chưa tạo công việc nào."
RESCHEDULE_CANCELLED_MESSAGE = "Người dùng đã huỷ, lịch giữ nguyên."
NOTHING_TO_RESCHEDULE_MESSAGE = "Không có công việc nào bị trễ hoặc lỡ lịch cần xếp lại."
MAX_ACTION_ITEMS = 20
MAX_ALERT_DAYS = 31


class ActionItem(BaseModel):
    title: str = Field(
        min_length=1, max_length=200, description="Việc cần làm, bắt đầu bằng động từ"
    )
    owner: str | None = Field(default=None, description="Người phụ trách nếu biên bản có ghi")
    deadline: str | None = Field(default=None, description="Hạn chót dạng YYYY-MM-DD HH:MM")
    priority: Priority | None = Field(default=None, description="Chỉ đặt khi biên bản nói rõ")
    estimated_minutes: int | None = Field(default=None, gt=0, le=MAX_STEP_MINUTES)


def describe_action_item(item: ActionItem, source: str) -> str:
    """Write the task description that records which meeting and owner an item came from."""
    owner_note = f" Người phụ trách: {item.owner}." if item.owner else ""
    return f"Từ biên bản: {source}.{owner_note}"


def preview_action_items(items: list[ActionItem]) -> str:
    """List the items to be created with their owners and parsed deadlines."""
    return "\n".join(
        f"- {item.title}"
        f"{f' ({item.owner})' if item.owner else ''}"
        f" | hạn {format_datetime(parse_optional_datetime(item.deadline))}"
        for item in items
    )


@tool
def create_tasks_from_notes(
    meeting_title: str,
    items: Annotated[list[ActionItem], Field(min_length=1, max_length=MAX_ACTION_ITEMS)],
    config: RunnableConfig,
) -> str:
    """Khi người dùng dán biên bản/ghi chú họp: tạo một lần mọi việc cần làm (action items)."""
    deps = get_deps(config)
    is_approved = interrupt(
        {"action": "create_tasks_from_notes", "summary": preview_action_items(items)}
    )
    if not is_approved:
        return CREATE_CANCELLED_MESSAGE
    with session_scope(deps.engine) as session:
        tasks = [create_action_item_task(session, item, meeting_title, deps) for item in items]
        return f"Đã tạo {len(tasks)} việc từ '{meeting_title}':\n{format_tasks(tasks)}"


def create_action_item_task(
    session: Session, item: ActionItem, source: str, deps: ToolDeps
) -> Task:
    """Store one action item as a task, letting the ML model pick a priority when none is given."""
    description = describe_action_item(item, source)
    priority = item.priority or suggest_priority(deps, item.title, description)[0]
    return crud.create_task(
        session,
        TaskCreate(
            title=item.title,
            description=description,
            priority=priority,
            deadline=parse_optional_datetime(item.deadline),
            estimated_minutes=item.estimated_minutes,
        ),
    )


def select_tasks_to_reschedule(
    session: Session, project_name: str | None, now: datetime
) -> list[Task]:
    """Pick a project's open tasks in their current order, or every overdue or missed task."""
    if project_name:
        project_id = crud.get_project_by_name(session, project_name).id
        tasks = crud.list_tasks(session, TaskFilter(project_id=project_id, include_done=False))
        return sorted(tasks, key=lambda task: (task.planned_start or datetime.max, task.id or 0))
    open_tasks = crud.list_tasks(session, TaskFilter(include_done=False))
    return order_for_rescheduling(
        [task for task in open_tasks if needs_rescheduling(task, now)], now
    )


@tool
def reschedule_tasks(
    config: RunnableConfig, project_name: str | None = None, finish_by: str | None = None
) -> str:
    """Xếp lại lịch việc chưa xong (cả dự án, hoặc mọi việc trễ/lỡ lịch) tránh giờ đã bận."""
    deps = get_deps(config)
    now, target_end = deps.clock(), parse_optional_datetime(finish_by)
    with session_scope(deps.engine) as session:
        tasks = select_tasks_to_reschedule(session, project_name, now)
        busy = read_busy_periods(session, now, {task.id for task in tasks if task.id})
    if not tasks:
        return NOTHING_TO_RESCHEDULE_MESSAGE
    durations = [task.estimated_minutes or DEFAULT_TASK_MINUTES for task in tasks]
    plan = plan_within_deadline(durations, now, busy, target_end)
    changes = list(zip(tasks, plan.slots, strict=True))
    summary = format_reschedule(changes) + format_deadline_fit(plan, target_end)
    if not interrupt({"action": "reschedule_tasks", "summary": summary}):
        return RESCHEDULE_CANCELLED_MESSAGE
    with session_scope(deps.engine) as session:
        for task, slot in changes:
            new_times = TaskUpdate(planned_start=slot.start, deadline=slot.end)
            crud.update_task(session, task.id or 0, new_times)
    return f"Đã xếp lại {len(changes)} việc:\n{summary}"


@tool
def check_schedule(
    config: RunnableConfig,
    days: Annotated[int, Field(ge=1, le=MAX_ALERT_DAYS)] = ALERT_HORIZON_DAYS,
) -> str:
    """Kiểm tra N ngày tới: lịch trùng giờ và việc đã trễ hoặc có nguy cơ trễ hạn."""
    deps = get_deps(config)
    now = deps.clock()
    with session_scope(deps.engine) as session:
        entries = read_calendar_entries(session, include_done=False)
        open_tasks = crud.list_tasks(session, TaskFilter(include_done=False))
    conflicts = find_conflicts(entries, now.date(), now.date() + timedelta(days=days))
    return format_schedule_alerts(conflicts, find_at_risk_tasks(open_tasks, now))


@tool
def progress_report(config: RunnableConfig, period: ReportPeriod = ReportPeriod.WEEK) -> str:
    """Báo cáo tiến độ hôm nay (day) hoặc tuần này (week): đã xong, đang làm, trễ, sắp đến hạn."""
    deps = get_deps(config)
    with session_scope(deps.engine) as session:
        tasks = crud.list_tasks(session)
    return format_progress_report(build_progress_report(tasks, period, deps.clock()))


@tool
def remember_fact(
    fact: Annotated[str, Field(min_length=1, max_length=MAX_MEMORY_LENGTH)],
    config: RunnableConfig,
) -> str:
    """Ghi nhớ lâu dài một thói quen/sở thích của người dùng cho các lần trò chuyện sau."""
    deps = get_deps(config)
    with session_scope(deps.engine) as session:
        note = crud.add_memory(session, fact)
        return f"Đã ghi nhớ (#{note.id}): {note.content}"
