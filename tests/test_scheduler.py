from datetime import datetime, timedelta

from flowagent.db.models import Priority, Task, TaskStatus
from flowagent.planning.scheduler import (
    build_timeline,
    classify_urgency,
    rank_tasks_for_today,
)
from tests.conftest import FIXED_NOW


def make_task(
    task_id: int,
    priority: Priority = Priority.MEDIUM,
    deadline: datetime | None = None,
    minutes: int = 60,
    status: TaskStatus = TaskStatus.TODO,
) -> Task:
    """Build an unsaved task with the fields the scheduler reads."""
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        priority=priority,
        deadline=deadline,
        estimated_minutes=minutes,
        status=status,
    )


def test_classify_urgency_buckets() -> None:
    """Overdue beats due-today, which beats due-this-week and no deadline."""
    overdue = classify_urgency(FIXED_NOW - timedelta(hours=1), FIXED_NOW)
    due_soon = classify_urgency(FIXED_NOW + timedelta(hours=5), FIXED_NOW)
    this_week = classify_urgency(FIXED_NOW + timedelta(days=5), FIXED_NOW)
    no_deadline = classify_urgency(None, FIXED_NOW)
    multipliers = [urgency.multiplier for urgency in (overdue, due_soon, this_week, no_deadline)]
    assert multipliers == sorted(multipliers, reverse=True)


def test_rank_prefers_urgent_deadlines_and_skips_done() -> None:
    """An overdue high-priority task ranks first and finished tasks are ignored."""
    tasks = [
        make_task(1, Priority.LOW),
        make_task(2, Priority.HIGH, deadline=FIXED_NOW - timedelta(hours=2)),
        make_task(3, Priority.URGENT, status=TaskStatus.DONE),
    ]
    plan = rank_tasks_for_today(tasks, FIXED_NOW, available_minutes=240)
    assert [item.task_id for item in plan.selected] == [2, 1]


def test_rank_defers_tasks_that_do_not_fit() -> None:
    """Tasks exceeding the remaining time are deferred instead of selected."""
    tasks = [make_task(1, Priority.HIGH, minutes=180), make_task(2, Priority.MEDIUM, minutes=120)]
    plan = rank_tasks_for_today(tasks, FIXED_NOW, available_minutes=200)
    assert [item.task_id for item in plan.selected] == [1]
    assert [item.task_id for item in plan.deferred] == [2]
    assert plan.planned_minutes == 180


def test_build_timeline_spans_working_days() -> None:
    """Sequential steps fill 4-hour workdays starting at the next 9:00."""
    slots = build_timeline([180, 120], start_after=FIXED_NOW, daily_work_minutes=240)
    tomorrow_nine = datetime(2026, 10, 15, 9, 0)
    assert slots[0].start == tomorrow_nine
    assert slots[0].end == tomorrow_nine + timedelta(minutes=180)
    assert slots[1].start == tomorrow_nine + timedelta(minutes=180)
    assert slots[1].end == tomorrow_nine + timedelta(days=1, minutes=60)


def test_build_timeline_ends_exactly_at_day_boundary() -> None:
    """A step that fills the whole day ends that day, not at 9:00 the next morning."""
    slots = build_timeline([240], start_after=datetime(2026, 10, 14, 8, 0), daily_work_minutes=240)
    assert slots[0].end == datetime(2026, 10, 14, 13, 0)
