from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from flowagent.db.models import Priority, Task, TaskStatus

PRIORITY_WEIGHTS: dict[Priority, float] = {
    Priority.LOW: 1.0,
    Priority.MEDIUM: 2.0,
    Priority.HIGH: 3.0,
    Priority.URGENT: 5.0,
}
DEFAULT_TASK_MINUTES = 60
DEFAULT_DAILY_WORK_MINUTES = 240
WORKDAY_START = time(hour=9)


@dataclass(frozen=True)
class Urgency:
    multiplier: float
    label: str


URGENCY_RULES: tuple[tuple[timedelta, Urgency], ...] = (
    (timedelta(0), Urgency(3.0, "đã quá hạn")),
    (timedelta(days=1), Urgency(2.5, "hạn trong 24 giờ tới")),
    (timedelta(days=3), Urgency(1.8, "hạn trong 3 ngày tới")),
    (timedelta(days=7), Urgency(1.3, "hạn trong tuần này")),
)
NO_PRESSURE = Urgency(1.0, "chưa gấp")


@dataclass(frozen=True)
class PlannedTask:
    task_id: int
    title: str
    minutes: int
    score: float
    reason: str


@dataclass(frozen=True)
class DailyPlan:
    selected: list[PlannedTask]
    deferred: list[PlannedTask]
    available_minutes: int

    @property
    def planned_minutes(self) -> int:
        """Return the total minutes of the selected tasks."""
        return sum(item.minutes for item in self.selected)


@dataclass(frozen=True)
class TimeSlot:
    start: datetime
    end: datetime


def classify_urgency(deadline: datetime | None, now: datetime) -> Urgency:
    """Map the time left before a deadline to an urgency multiplier and label."""
    if deadline is None:
        return NO_PRESSURE
    time_left = deadline - now
    for threshold, urgency in URGENCY_RULES:
        if time_left <= threshold:
            return urgency
    return NO_PRESSURE


def score_task(task: Task, now: datetime) -> float:
    """Combine priority weight and deadline urgency into a single ranking score."""
    return PRIORITY_WEIGHTS[task.priority] * classify_urgency(task.deadline, now).multiplier


def to_planned_task(task: Task, now: datetime) -> PlannedTask:
    """Build the plan entry for a task, including a human-readable reason."""
    urgency = classify_urgency(task.deadline, now)
    return PlannedTask(
        task_id=task.id or 0,
        title=task.title,
        minutes=task.estimated_minutes or DEFAULT_TASK_MINUTES,
        score=score_task(task, now),
        reason=f"ưu tiên {task.priority.value}, {urgency.label}",
    )


def rank_tasks_for_today(
    tasks: Sequence[Task], now: datetime, available_minutes: int = DEFAULT_DAILY_WORK_MINUTES
) -> DailyPlan:
    """Pick the highest-scoring open tasks that fit into today's available minutes."""
    open_tasks = [task for task in tasks if task.status != TaskStatus.DONE]
    candidates = sorted(
        (to_planned_task(task, now) for task in open_tasks),
        key=lambda item: item.score,
        reverse=True,
    )
    selected: list[PlannedTask] = []
    deferred: list[PlannedTask] = []
    remaining_minutes = available_minutes
    for candidate in candidates:
        if candidate.minutes <= remaining_minutes:
            selected.append(candidate)
            remaining_minutes -= candidate.minutes
        else:
            deferred.append(candidate)
    return DailyPlan(selected=selected, deferred=deferred, available_minutes=available_minutes)


def first_work_start(after: datetime) -> datetime:
    """Return the next workday start time at or after the given moment."""
    today_start = datetime.combine(after.date(), WORKDAY_START)
    return today_start if after <= today_start else today_start + timedelta(days=1)


def work_offset_to_datetime(
    offset_minutes: int, timeline_start: datetime, daily_work_minutes: int, is_end: bool
) -> datetime:
    """Convert minutes of accumulated work into a calendar time inside working hours."""
    day_index, minute_of_day = divmod(offset_minutes, daily_work_minutes)
    if is_end and minute_of_day == 0 and day_index > 0:
        day_index -= 1
        minute_of_day = daily_work_minutes
    return timeline_start + timedelta(days=day_index, minutes=minute_of_day)


def build_timeline(
    durations_minutes: Sequence[int],
    start_after: datetime,
    daily_work_minutes: int = DEFAULT_DAILY_WORK_MINUTES,
) -> list[TimeSlot]:
    """Lay out sequential tasks across working days and return one slot per task."""
    timeline_start = first_work_start(start_after)
    slots: list[TimeSlot] = []
    offset_minutes = 0
    for duration in durations_minutes:
        start = work_offset_to_datetime(offset_minutes, timeline_start, daily_work_minutes, False)
        offset_minutes += duration
        end = work_offset_to_datetime(offset_minutes, timeline_start, daily_work_minutes, True)
        slots.append(TimeSlot(start=start, end=end))
    return slots
