from datetime import datetime, time, timedelta

from sqlmodel import Session

from flowagent.db import crud
from flowagent.db.models import Priority, Recurrence, TaskStatus
from flowagent.db.schemas import ScheduleEventCreate, TaskCreate, TaskUpdate
from flowagent.planning.scheduler import build_timeline
from flowagent.schedule_queries import read_busy_periods

DEMO_PROJECT_NAME = "Website bán hàng"
DEMO_PROJECT_GOAL = "Làm website bán hàng trong 2 tuần"
DEMO_PROJECT_STEPS: tuple[tuple[str, int, Priority], ...] = (
    ("Nghiên cứu yêu cầu và đối thủ", 180, Priority.HIGH),
    ("Thiết kế giao diện", 360, Priority.HIGH),
    ("Lập trình trang sản phẩm và giỏ hàng", 600, Priority.HIGH),
    ("Tích hợp thanh toán", 300, Priority.MEDIUM),
    ("Kiểm thử và sửa lỗi", 240, Priority.MEDIUM),
)
DEMO_MEMORIES = ("Làm việc hiệu quả nhất vào buổi sáng", "Không xếp họp vào sáng thứ 2")


def at_day(now: datetime, days: int, hour: int, minute: int = 0) -> datetime:
    """Return the moment N days from today at the given clock time."""
    return datetime.combine(now.date() + timedelta(days=days), time(hour, minute))


def demo_tasks(now: datetime) -> list[tuple[TaskCreate, TaskStatus]]:
    """Describe the standalone sample tasks and the status each one should end up in."""
    return [
        (
            TaskCreate(
                title="Nộp báo cáo thực tập",
                priority=Priority.HIGH,
                deadline=at_day(now, 4, 23, 59),
                estimated_minutes=120,
            ),
            TaskStatus.TODO,
        ),
        (
            TaskCreate(
                title="Ôn thi giải tích", planned_start=at_day(now, 1, 9), estimated_minutes=120
            ),
            TaskStatus.TODO,
        ),
        (
            TaskCreate(
                title="Đóng tiền điện tháng này",
                priority=Priority.URGENT,
                deadline=at_day(now, -1, 17),
                estimated_minutes=15,
            ),
            TaskStatus.TODO,
        ),
        (
            TaskCreate(
                title="Mua quà sinh nhật mẹ",
                priority=Priority.LOW,
                deadline=at_day(now, 9, 23, 59),
                estimated_minutes=60,
            ),
            TaskStatus.TODO,
        ),
        (
            TaskCreate(
                title="Chuẩn bị slide thuyết trình",
                priority=Priority.HIGH,
                deadline=at_day(now, 5, 23, 59),
                estimated_minutes=180,
            ),
            TaskStatus.IN_PROGRESS,
        ),
        (
            TaskCreate(
                title="Viết blog về LangGraph",
                deadline=at_day(now, 0, 23, 59),
                estimated_minutes=90,
            ),
            TaskStatus.DONE,
        ),
    ]


def demo_events(now: datetime) -> list[ScheduleEventCreate]:
    """Describe sample calendar events, including recurring ones and one clash."""
    return [
        ScheduleEventCreate(
            title="Tập gym",
            start_at=at_day(now, -3, 18),
            duration_minutes=90,
            recurrence=Recurrence.DAILY,
            reminder_minutes=15,
            priority=Priority.LOW,
        ),
        ScheduleEventCreate(
            title="Đọc sách",
            start_at=at_day(now, -3, 21),
            duration_minutes=30,
            recurrence=Recurrence.DAILY,
            priority=Priority.LOW,
        ),
        ScheduleEventCreate(
            title="Họp nhóm đồ án",
            start_at=at_day(now, -now.weekday(), 14),
            recurrence=Recurrence.WEEKLY,
            reminder_minutes=30,
            priority=Priority.HIGH,
            note="Phòng 302",
        ),
        ScheduleEventCreate(title="Họp khoa", start_at=at_day(now, 1, 10), reminder_minutes=60),
    ]


def seed_demo_project(session: Session, now: datetime) -> None:
    """Create a sample project whose steps are scheduled like create_project_plan does."""
    project = crud.create_project(session, DEMO_PROJECT_NAME, DEMO_PROJECT_GOAL)
    durations = [minutes for _, minutes, _ in DEMO_PROJECT_STEPS]
    slots = build_timeline(durations, now, busy=read_busy_periods(session, now))
    for (title, minutes, priority), slot in zip(DEMO_PROJECT_STEPS, slots, strict=True):
        step = TaskCreate(
            title=title,
            priority=priority,
            estimated_minutes=minutes,
            planned_start=slot.start,
            deadline=slot.end,
            project_id=project.id,
        )
        crud.create_task(session, step)


def seed_demo_data(session: Session, now: datetime) -> None:
    """Fill an empty database with sample tasks, a planned project, events and memories."""
    for task_in, status in demo_tasks(now):
        task = crud.create_task(session, task_in)
        if status != TaskStatus.TODO:
            crud.update_task(session, task.id or 0, TaskUpdate(status=status))
    for event_in in demo_events(now):
        crud.create_event(session, event_in)
    seed_demo_project(session, now)
    for memory in DEMO_MEMORIES:
        crud.add_memory(session, memory)
