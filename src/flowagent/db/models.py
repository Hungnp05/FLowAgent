from enum import StrEnum

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel

from flowagent.clock import now_local


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


PRIORITY_ORDER: tuple[Priority, ...] = (
    Priority.LOW,
    Priority.MEDIUM,
    Priority.HIGH,
    Priority.URGENT,
)


def shift_priority(priority: Priority, steps: int) -> Priority:
    """Move a priority up (positive steps) or down, stopping at the lowest and highest levels."""
    position = PRIORITY_ORDER.index(priority) + steps
    return PRIORITY_ORDER[max(0, min(position, len(PRIORITY_ORDER) - 1))]


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Recurrence(StrEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


MINUTES_PER_DAY = 24 * 60
MAX_MEMORY_LENGTH = 300


class Project(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    goal: str = ""
    created_at: NaiveDatetime = Field(default_factory=now_local)


class TaskFields(SQLModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    priority: Priority = Priority.MEDIUM
    deadline: NaiveDatetime | None = None
    planned_start: NaiveDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, foreign_key="project.id")


class Task(TaskFields, table=True):
    id: int | None = Field(default=None, primary_key=True)
    status: TaskStatus = Field(default=TaskStatus.TODO, index=True)
    created_at: NaiveDatetime = Field(default_factory=now_local)
    completed_at: NaiveDatetime | None = None


class ScheduleEventFields(SQLModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = ""
    start_at: NaiveDatetime
    duration_minutes: int = Field(default=60, gt=0, le=MINUTES_PER_DAY)
    all_day: bool = False
    recurrence: Recurrence = Recurrence.NONE
    reminder_minutes: int = Field(default=0, ge=0)
    priority: Priority = Priority.MEDIUM


class ScheduleEvent(ScheduleEventFields, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: NaiveDatetime = Field(default_factory=now_local)


class MemoryNote(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    content: str = Field(min_length=1, max_length=MAX_MEMORY_LENGTH)
    created_at: NaiveDatetime = Field(default_factory=now_local)


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
