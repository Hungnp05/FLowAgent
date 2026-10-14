from enum import StrEnum

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel

from flowagent.clock import now_local


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


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


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str
