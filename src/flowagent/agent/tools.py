import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time

from langchain.agents.middleware import ToolCallRequest
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from flowagent.agent.formatting import (
    format_daily_plan,
    format_projects,
    format_task,
    format_tasks,
)
from flowagent.db import crud
from flowagent.db.models import Priority, TaskStatus
from flowagent.db.schemas import TaskCreate, TaskFilter, TaskUpdate
from flowagent.db.session import session_scope
from flowagent.errors import (
    FlowAgentError,
    InvalidDateError,
    NoChangesError,
    PriorityModelUnavailableError,
)
from flowagent.ml.labels import PriorityPrediction
from flowagent.planning.scheduler import (
    DEFAULT_DAILY_WORK_MINUTES,
    WORKDAY_START,
    build_timeline,
    rank_tasks_for_today,
)

logger = logging.getLogger(__name__)

DEPS_CONFIG_KEY = "flowagent_deps"
DATE_ONLY_LENGTH = len("YYYY-MM-DD")
END_OF_DAY = time(hour=23, minute=59)
MAX_STEP_MINUTES = 2400
DELETE_CANCELLED_MESSAGE = "Người dùng đã huỷ thao tác xoá."


PriorityPredictorFn = Callable[[str], PriorityPrediction]


@dataclass(frozen=True)
class ToolDeps:
    engine: Engine
    clock: Callable[[], datetime]
    predict_priority: PriorityPredictorFn | None = None


class PlanStep(BaseModel):
    title: str = Field(description="Tên ngắn gọn của bước, bắt đầu bằng động từ")
    estimated_minutes: int = Field(gt=0, le=MAX_STEP_MINUTES, description="Thời lượng ước tính")
    priority: Priority = Priority.MEDIUM


def get_deps(config: RunnableConfig) -> ToolDeps:
    """Read the database engine and clock that the agent service put into the run config."""
    return config["configurable"][DEPS_CONFIG_KEY]


def parse_local_datetime(value: str, date_only_time: time = END_OF_DAY) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM', or a bare 'YYYY-MM-DD' at date_only_time, into a datetime."""
    text = value.strip()
    try:
        if len(text) == DATE_ONLY_LENGTH:
            return datetime.combine(date.fromisoformat(text), date_only_time)
        return datetime.fromisoformat(text).replace(tzinfo=None, second=0, microsecond=0)
    except ValueError as error:
        raise InvalidDateError(
            f"Ngày giờ '{value}' không hợp lệ, hãy dùng định dạng YYYY-MM-DD HH:MM."
        ) from error


def parse_optional_datetime(
    value: str | None, date_only_time: time = END_OF_DAY
) -> datetime | None:
    """Parse a datetime string, treating None or blank as no value."""
    return parse_local_datetime(value, date_only_time) if value and value.strip() else None


def suggest_priority(deps: ToolDeps, title: str, description: str) -> tuple[Priority, str]:
    """Ask the ML model for a priority, falling back to medium when it is unavailable or fails."""
    if deps.predict_priority is None:
        return Priority.MEDIUM, ""
    try:
        prediction = deps.predict_priority(f"{title}. {description}".strip(". "))
    except Exception:
        logger.exception("Priority model failed; using medium")
        return Priority.MEDIUM, ""
    return (
        prediction.priority,
        f" (độ ưu tiên do mô hình gợi ý, tin cậy {prediction.confidence:.0%})",
    )


def format_tool_error(error: Exception, request: ToolCallRequest) -> str | None:
    """Return domain errors to the model as readable messages and let other errors propagate."""
    if isinstance(error, FlowAgentError):
        return f"Lỗi khi chạy {request.tool_call['name']}: {error}"
    return None


@tool
def create_task(
    title: str,
    config: RunnableConfig,
    description: str = "",
    priority: Priority | None = None,
    planned_start: str | None = None,
    deadline: str | None = None,
    estimated_minutes: int | None = None,
    project_name: str | None = None,
) -> str:
    """Tạo công việc mới; bỏ trống priority nếu người dùng không nói để mô hình tự gợi ý."""
    deps = get_deps(config)
    suggestion_note = ""
    if priority is None:
        priority, suggestion_note = suggest_priority(deps, title, description)
    with session_scope(deps.engine) as session:
        project_id = crud.get_project_by_name(session, project_name).id if project_name else None
        task = crud.create_task(
            session,
            TaskCreate(
                title=title,
                description=description,
                priority=priority,
                planned_start=parse_optional_datetime(planned_start, WORKDAY_START),
                deadline=parse_optional_datetime(deadline),
                estimated_minutes=estimated_minutes,
                project_id=project_id,
            ),
        )
        return f"Đã tạo: {format_task(task)}{suggestion_note}"


@tool
def list_tasks(
    config: RunnableConfig,
    status: TaskStatus | None = None,
    priority: Priority | None = None,
    due_before: str | None = None,
    keyword: str | None = None,
    include_done: bool | None = None,
) -> str:
    """Tìm việc theo trạng thái, ưu tiên, hạn hoặc từ khoá (bỏ qua dấu, gồm cả việc đã xong)."""
    deps = get_deps(config)
    task_filter = TaskFilter(
        status=status,
        priority=priority,
        due_before=parse_optional_datetime(due_before),
        keyword=keyword,
        include_done=bool(keyword) if include_done is None else include_done,
    )
    with session_scope(deps.engine) as session:
        return format_tasks(crud.list_tasks(session, task_filter))


@tool
def update_task(
    task_id: int,
    config: RunnableConfig,
    title: str | None = None,
    description: str | None = None,
    priority: Priority | None = None,
    status: TaskStatus | None = None,
    planned_start: str | None = None,
    deadline: str | None = None,
    estimated_minutes: int | None = None,
) -> str:
    """Sửa việc có sẵn theo id: hạn, bắt đầu, thời lượng, ưu tiên, trạng thái, tên."""
    deps = get_deps(config)
    provided_changes = {
        "title": title,
        "description": description,
        "priority": priority,
        "status": status,
        "planned_start": parse_optional_datetime(planned_start, WORKDAY_START),
        "deadline": parse_optional_datetime(deadline),
        "estimated_minutes": estimated_minutes,
    }
    given_changes = {field: value for field, value in provided_changes.items() if value is not None}
    if not given_changes:
        raise NoChangesError(
            "Không có trường nào để cập nhật; chỉ gọi update_task khi cần đổi giá trị."
        )
    changes = TaskUpdate(**given_changes)
    with session_scope(deps.engine) as session:
        return f"Đã cập nhật: {format_task(crud.update_task(session, task_id, changes))}"


@tool
def delete_task(task_id: int, config: RunnableConfig) -> str:
    """Xoá công việc theo id; hệ thống sẽ hỏi người dùng xác nhận trước khi xoá."""
    deps = get_deps(config)
    with session_scope(deps.engine) as session:
        summary = format_task(crud.get_task(session, task_id))
    is_approved = interrupt({"action": "delete_task", "task_id": task_id, "summary": summary})
    if not is_approved:
        return DELETE_CANCELLED_MESSAGE
    with session_scope(deps.engine) as session:
        crud.delete_task(session, task_id)
    return f"Đã xoá: {summary}"


@tool
def plan_my_day(config: RunnableConfig, available_minutes: int = DEFAULT_DAILY_WORK_MINUTES) -> str:
    """Đề xuất các công việc nên làm hôm nay, xếp theo độ ưu tiên và hạn chót."""
    deps = get_deps(config)
    with session_scope(deps.engine) as session:
        open_tasks = crud.list_tasks(session, TaskFilter(include_done=False))
        plan = rank_tasks_for_today(open_tasks, deps.clock(), available_minutes)
    return format_daily_plan(plan)


@tool
def create_project_plan(
    project_name: str, goal: str, steps: list[PlanStep], config: RunnableConfig
) -> str:
    """Chỉ khi người dùng nhờ lập kế hoạch/chia nhỏ mục tiêu lớn: tạo dự án 3-10 bước."""
    deps = get_deps(config)
    slots = build_timeline([step.estimated_minutes for step in steps], deps.clock())
    with session_scope(deps.engine) as session:
        project = crud.create_project(session, project_name, goal)
        tasks = [
            crud.create_task(
                session,
                TaskCreate(
                    title=step.title,
                    priority=step.priority,
                    estimated_minutes=step.estimated_minutes,
                    planned_start=slot.start,
                    deadline=slot.end,
                    project_id=project.id,
                ),
            )
            for step, slot in zip(steps, slots, strict=True)
        ]
        return f"Đã tạo dự án '{project.name}' với {len(tasks)} bước:\n{format_tasks(tasks)}"


@tool
def predict_priority(text: str, config: RunnableConfig) -> str:
    """Chỉ khi người dùng hỏi một việc nên ưu tiên mức nào: gợi ý từ mô hình học máy."""
    deps = get_deps(config)
    if deps.predict_priority is None:
        raise PriorityModelUnavailableError("Mô hình dự đoán độ ưu tiên chưa được cài đặt.")
    prediction = deps.predict_priority(text)
    return f"Gợi ý: {prediction.priority.value} (độ tin cậy {prediction.confidence:.0%})"


@tool
def list_projects(config: RunnableConfig) -> str:
    """Liệt kê tất cả dự án hiện có."""
    deps = get_deps(config)
    with session_scope(deps.engine) as session:
        return format_projects(crud.list_projects(session))


ALL_TOOLS: list[BaseTool] = [
    create_task,
    list_tasks,
    update_task,
    delete_task,
    plan_my_day,
    create_project_plan,
    predict_priority,
    list_projects,
]
