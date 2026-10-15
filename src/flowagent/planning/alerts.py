from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from flowagent.db.models import Task, TaskStatus
from flowagent.planning.calendar import (
    CalendarEntry,
    Occurrence,
    blocks_time,
    occurrences_by_day,
)
from flowagent.planning.scheduler import (
    DEFAULT_DAILY_WORK_MINUTES,
    MAX_PLANNING_DAYS,
    WORKDAY_START,
    TimeSlot,
)

ALERT_HORIZON_DAYS = 7


class RiskKind(StrEnum):
    OVERDUE = "overdue"
    NOT_ENOUGH_TIME = "not_enough_time"


@dataclass(frozen=True)
class Conflict:
    first: Occurrence
    second: Occurrence


@dataclass(frozen=True)
class TaskRisk:
    task: Task
    kind: RiskKind
    work_minutes_left: int


def overlaps(first: Occurrence, second: Occurrence) -> bool:
    """Report whether two occurrences share any minute."""
    return first.start < second.end and second.start < first.end


def find_conflicts(
    entries: Iterable[CalendarEntry], first_day: date, last_day: date
) -> list[Conflict]:
    """List pairs of events or work blocks that overlap in time between two days."""
    by_day = occurrences_by_day(
        [entry for entry in entries if blocks_time(entry)], first_day, last_day
    )
    return [
        Conflict(first, second)
        for day_occurrences in by_day.values()
        for index, first in enumerate(day_occurrences)
        for second in day_occurrences[index + 1 :]
        if overlaps(first, second)
    ]


def conflicts_involving(conflicts: Sequence[Conflict], entry_key: str) -> list[Conflict]:
    """Keep only the conflicts in which the given entry takes part."""
    return [
        conflict
        for conflict in conflicts
        if entry_key in (conflict.first.entry.key, conflict.second.entry.key)
    ]


def overlap_minutes(first: TimeSlot, second: TimeSlot) -> int:
    """Return how many minutes two time ranges share."""
    shared = min(first.end, second.end) - max(first.start, second.start)
    return max(0, int(shared.total_seconds() // 60))


def work_minutes_between(
    start: datetime, end: datetime, daily_work_minutes: int = DEFAULT_DAILY_WORK_MINUTES
) -> int:
    """Count the working-window minutes between two moments."""
    if end <= start:
        return 0
    period = TimeSlot(start, end)
    day_count = min((end.date() - start.date()).days + 1, MAX_PLANNING_DAYS)
    total = 0
    for offset in range(day_count):
        window_start = datetime.combine(start.date() + timedelta(days=offset), WORKDAY_START)
        window = TimeSlot(window_start, window_start + timedelta(minutes=daily_work_minutes))
        total += overlap_minutes(period, window)
    return total


def assess_task_risk(
    task: Task, now: datetime, daily_work_minutes: int = DEFAULT_DAILY_WORK_MINUTES
) -> TaskRisk | None:
    """Flag an open task that is overdue or has less working time left than its estimate."""
    if task.status == TaskStatus.DONE or task.deadline is None:
        return None
    if task.deadline < now:
        return TaskRisk(task, RiskKind.OVERDUE, 0)
    minutes_left = work_minutes_between(now, task.deadline, daily_work_minutes)
    if task.estimated_minutes and minutes_left < task.estimated_minutes:
        return TaskRisk(task, RiskKind.NOT_ENOUGH_TIME, minutes_left)
    return None


def find_at_risk_tasks(
    tasks: Iterable[Task], now: datetime, daily_work_minutes: int = DEFAULT_DAILY_WORK_MINUTES
) -> list[TaskRisk]:
    """List the open tasks that are overdue or unlikely to finish on time, overdue first."""
    risks = [assess_task_risk(task, now, daily_work_minutes) for task in tasks]
    found = [risk for risk in risks if risk is not None]
    return sorted(found, key=lambda risk: (risk.kind != RiskKind.OVERDUE, risk.task.deadline))
