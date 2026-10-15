from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum

from flowagent.db.models import Task, TaskStatus

UPCOMING_DAYS = 7


class ReportPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"


@dataclass(frozen=True)
class ProgressReport:
    period: ReportPeriod
    period_start: datetime
    generated_at: datetime
    completed: list[Task]
    in_progress: list[Task]
    overdue: list[Task]
    upcoming: list[Task]
    created_count: int

    @property
    def on_time_count(self) -> int:
        """Count completed tasks that were finished no later than their deadline."""
        return sum(
            task.deadline is None or (task.completed_at or task.deadline) <= task.deadline
            for task in self.completed
        )


def report_period_start(period: ReportPeriod, now: datetime) -> datetime:
    """Return midnight today for a daily report, or midnight on Monday for a weekly one."""
    midnight = datetime.combine(now.date(), time.min)
    return midnight if period == ReportPeriod.DAY else midnight - timedelta(days=now.weekday())


def is_completed_since(task: Task, since: datetime) -> bool:
    """Report whether a task was marked done at or after the given moment."""
    return (
        task.status == TaskStatus.DONE
        and task.completed_at is not None
        and (task.completed_at >= since)
    )


def is_open(task: Task) -> bool:
    """Report whether a task still needs work."""
    return task.status != TaskStatus.DONE


def build_progress_report(
    tasks: Sequence[Task], period: ReportPeriod, now: datetime
) -> ProgressReport:
    """Summarise what was finished in the period, what is in progress, overdue and due soon."""
    since = report_period_start(period, now)
    upcoming_limit = now + timedelta(days=UPCOMING_DAYS)
    open_tasks = [task for task in tasks if is_open(task)]
    return ProgressReport(
        period=period,
        period_start=since,
        generated_at=now,
        completed=[task for task in tasks if is_completed_since(task, since)],
        in_progress=[task for task in open_tasks if task.status == TaskStatus.IN_PROGRESS],
        overdue=[task for task in open_tasks if task.deadline and task.deadline < now],
        upcoming=[
            task for task in open_tasks if task.deadline and now <= task.deadline <= upcoming_limit
        ],
        created_count=sum(task.created_at >= since for task in tasks),
    )
