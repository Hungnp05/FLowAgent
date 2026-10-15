from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel

from flowagent.db.models import (
    MINUTES_PER_DAY,
    Priority,
    Recurrence,
    ScheduleEventFields,
    TaskFields,
    TaskStatus,
)


class TaskCreate(TaskFields):
    pass


class TaskUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    deadline: NaiveDatetime | None = None
    planned_start: NaiveDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)


class TaskFilter(SQLModel):
    status: TaskStatus | None = None
    priority: Priority | None = None
    project_id: int | None = None
    due_before: NaiveDatetime | None = None
    keyword: str | None = None
    include_done: bool = True


class ScheduleEventCreate(ScheduleEventFields):
    pass


class ScheduleEventUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = None
    start_at: NaiveDatetime | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=MINUTES_PER_DAY)
    all_day: bool | None = None
    recurrence: Recurrence | None = None
    reminder_minutes: int | None = Field(default=None, ge=0)
    priority: Priority | None = None
