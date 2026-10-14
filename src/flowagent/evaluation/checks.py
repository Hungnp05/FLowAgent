from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from flowagent.agent.service import ToolCallRecord
from flowagent.db.models import Task
from flowagent.evaluation.cases import MUTATING_TOOLS, EvalCase, TaskExpectation
from flowagent.vietnamese import fold_text


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class CaseOutcome:
    tool_selection_ok: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed_checks(self) -> int:
        """Count the state and argument checks that passed."""
        return sum(check.passed for check in self.checks)

    @property
    def is_success(self) -> bool:
        """A case succeeds only when tool selection and every check are correct."""
        return self.tool_selection_ok and all(check.passed for check in self.checks)


def task_matches(task: Task, keywords: Sequence[str]) -> bool:
    """Report whether every keyword appears in the task title, ignoring case and accents."""
    title = fold_text(task.title)
    return all(fold_text(keyword) in title for keyword in keywords)


def is_tool_selection_correct(case: EvalCase, tool_calls: Sequence[ToolCallRecord]) -> bool:
    """Require every expected tool and forbid state-changing tools the case did not expect."""
    called = {call.name for call in tool_calls}
    called_mutations = called & MUTATING_TOOLS
    return set(case.expect.tools) <= called and called_mutations <= case.required_mutations


def format_minute(value: datetime | None) -> str | None:
    """Render a datetime as 'YYYY-MM-DD HH:MM' for comparison with case expectations."""
    return value.strftime("%Y-%m-%d %H:%M") if value else None


def check_task_fields(task: Task, expectation: TaskExpectation) -> list[CheckResult]:
    """Compare the expected fields of one matched task with its stored values."""
    label = "/".join(expectation.match)
    actual_values = {
        "deadline": format_minute(task.deadline),
        "planned_start": format_minute(task.planned_start),
        "priority": task.priority.value,
        "status": task.status.value,
        "estimated_minutes": task.estimated_minutes,
    }
    checks = []
    for field_name, actual in actual_values.items():
        expected = getattr(expectation, field_name)
        if expected is None:
            continue
        expected_value = getattr(expected, "value", expected)
        detail = f"expected {expected_value}, got {actual}"
        checks.append(CheckResult(f"{label}.{field_name}", actual == expected_value, detail))
    return checks


def check_task_expectation(
    tasks: Sequence[Task], expectation: TaskExpectation
) -> list[CheckResult]:
    """Check that a task matching the keywords exists (or not) and has the expected fields."""
    label = "/".join(expectation.match)
    matched = [task for task in tasks if task_matches(task, expectation.match)]
    if not expectation.exists:
        return [CheckResult(f"{label}.absent", not matched, f"found {len(matched)}")]
    if not matched:
        titles = [task.title for task in tasks]
        return [CheckResult(f"{label}.exists", False, f"no title matched; titles={titles}")]
    return [CheckResult(f"{label}.exists", True), *check_task_fields(matched[-1], expectation)]


def check_project_steps(case: EvalCase, project_task_count: int) -> list[CheckResult]:
    """Check that a generated project plan has a sensible number of steps."""
    if case.expect.project_steps is None:
        return []
    low, high = case.expect.project_steps
    detail = f"expected {low}-{high} steps, got {project_task_count}"
    return [CheckResult("project_steps", low <= project_task_count <= high, detail)]


def check_reply(case: EvalCase, reply_text: str) -> list[CheckResult]:
    """Check that the final answer mentions every required phrase."""
    folded = fold_text(reply_text)
    return [
        CheckResult(f"reply~{phrase}", fold_text(phrase) in folded)
        for phrase in case.expect.reply_contains
    ]


def evaluate_case(
    case: EvalCase,
    tool_calls: Sequence[ToolCallRecord],
    tasks: Sequence[Task],
    project_task_count: int,
    asked_confirmation: bool,
    reply_text: str,
) -> CaseOutcome:
    """Score one finished case against its expectations."""
    checks = [
        check
        for expectation in case.expect.tasks
        for check in check_task_expectation(tasks, expectation)
    ]
    if case.expect.task_count is not None:
        detail = f"expected {case.expect.task_count}, got {len(tasks)}"
        checks.append(CheckResult("task_count", len(tasks) == case.expect.task_count, detail))
    if case.expect.confirm is not None:
        checks.append(CheckResult("confirmation", asked_confirmation == case.expect.confirm))
    checks += check_project_steps(case, project_task_count) + check_reply(case, reply_text)
    return CaseOutcome(is_tool_selection_correct(case, tool_calls), checks)
