import json
from pathlib import Path

from pydantic import BaseModel, Field

from flowagent.db.models import Priority, TaskStatus

DEFAULT_CASES_PATH = Path("evals/cases.jsonl")
MUTATING_TOOLS = frozenset({"create_task", "update_task", "delete_task", "create_project_plan"})


class SeedTask(BaseModel):
    title: str
    priority: Priority = Priority.MEDIUM
    status: TaskStatus = TaskStatus.TODO
    deadline: str | None = None
    planned_start: str | None = None
    estimated_minutes: int | None = None


class TaskExpectation(BaseModel):
    match: list[str] = Field(min_length=1)
    exists: bool = True
    deadline: str | None = None
    planned_start: str | None = None
    priority: Priority | None = None
    status: TaskStatus | None = None
    estimated_minutes: int | None = None


class Expectation(BaseModel):
    tools: list[str] = Field(default_factory=list)
    confirm: bool | None = None
    tasks: list[TaskExpectation] = Field(default_factory=list)
    task_count: int | None = None
    project_steps: tuple[int, int] | None = None
    reply_contains: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str
    category: str
    utterance: str
    seed_tasks: list[SeedTask] = Field(default_factory=list)
    expect: Expectation

    @property
    def required_mutations(self) -> set[str]:
        """Return the state-changing tools this case expects to be called."""
        return set(self.expect.tools) & MUTATING_TOOLS


def load_cases(cases_path: Path = DEFAULT_CASES_PATH) -> list[EvalCase]:
    """Read one JSON case per non-empty line and validate it."""
    lines = cases_path.read_text(encoding="utf-8").splitlines()
    return [EvalCase.model_validate(json.loads(line)) for line in lines if line.strip()]
