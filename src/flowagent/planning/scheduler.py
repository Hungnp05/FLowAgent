from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from flowagent.db.models import Priority, Task, TaskStatus
from flowagent.errors import InvalidScheduleError

PRIORITY_WEIGHTS: dict[Priority, float] = {
    Priority.LOW: 1.0,
    Priority.MEDIUM: 2.0,
    Priority.HIGH: 3.0,
    Priority.URGENT: 5.0,
}
DEFAULT_TASK_MINUTES = 60
DEFAULT_DAILY_WORK_MINUTES = 240
WORKDAY_START = time(hour=9)
DAILY_WORK_MINUTE_OPTIONS = (240, 300, 360, 420, 480)
MAX_PLANNING_DAYS = 366


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


@dataclass(frozen=True)
class TimelinePlan:
    slots: list[TimeSlot]
    daily_work_minutes: int
    fits_deadline: bool


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


def needs_rescheduling(task: Task, now: datetime) -> bool:
    """Report whether an open task is overdue or its planned start passed before it was begun."""
    if task.status == TaskStatus.DONE:
        return False
    is_overdue = task.deadline is not None and task.deadline < now
    missed_start = (
        task.status == TaskStatus.TODO
        and task.planned_start is not None
        and task.planned_start < now
    )
    return is_overdue or missed_start


def order_for_rescheduling(tasks: Sequence[Task], now: datetime) -> list[Task]:
    """Order tasks to reschedule by the same priority-and-urgency score as the daily plan."""
    return sorted(tasks, key=lambda task: (-score_task(task, now), task.id or 0))


def first_work_start(after: datetime) -> datetime:
    """Return the next workday start time at or after the given moment."""
    today_start = datetime.combine(after.date(), WORKDAY_START)
    return today_start if after <= today_start else today_start + timedelta(days=1)


def subtract_busy(window: TimeSlot, busy: Sequence[TimeSlot]) -> list[TimeSlot]:
    """Cut the busy periods out of a window and return the free pieces in order."""
    free: list[TimeSlot] = []
    cursor = window.start
    for period in sorted(busy, key=lambda slot: slot.start):
        if period.end <= cursor or period.start >= window.end:
            continue
        if period.start > cursor:
            free.append(TimeSlot(cursor, period.start))
        cursor = max(cursor, period.end)
    if cursor < window.end:
        free.append(TimeSlot(cursor, window.end))
    return free


def free_work_segments(
    timeline_start: datetime, daily_work_minutes: int, busy: Sequence[TimeSlot]
) -> Iterator[TimeSlot]:
    """Yield the free parts of each day's working window, starting from timeline_start."""
    for day_index in range(MAX_PLANNING_DAYS):
        day_start = timeline_start + timedelta(days=day_index)
        window = TimeSlot(day_start, day_start + timedelta(minutes=daily_work_minutes))
        yield from subtract_busy(window, busy)


def allocate_durations(
    durations_minutes: Sequence[int], segments: Iterator[TimeSlot]
) -> list[TimeSlot]:
    """Fill free segments with sequential work, splitting a task across segments when needed."""
    slots: list[TimeSlot] = []
    segment = TimeSlot(datetime.min, datetime.min)
    cursor = segment.end
    for duration in durations_minutes:
        remaining, start = timedelta(minutes=duration), None
        while remaining > timedelta(0):
            if cursor >= segment.end:
                segment = next(segments, None)
                if segment is None:
                    raise InvalidScheduleError("Không tìm được đủ thời gian trống để xếp lịch.")
                cursor = segment.start
            start = start or cursor
            step = min(remaining, segment.end - cursor)
            cursor, remaining = cursor + step, remaining - step
        slots.append(TimeSlot(start=start or cursor, end=cursor))
    return slots


def build_timeline(
    durations_minutes: Sequence[int],
    start_after: datetime,
    daily_work_minutes: int = DEFAULT_DAILY_WORK_MINUTES,
    busy: Sequence[TimeSlot] = (),
) -> list[TimeSlot]:
    """Lay out sequential tasks across working days around busy periods, one slot per task."""
    segments = free_work_segments(first_work_start(start_after), daily_work_minutes, busy)
    return allocate_durations(durations_minutes, segments)


def plan_within_deadline(
    durations_minutes: Sequence[int],
    start_after: datetime,
    busy: Sequence[TimeSlot] = (),
    finish_by: datetime | None = None,
) -> TimelinePlan:
    """Use the shortest working day that still finishes by finish_by, else the longest one."""
    plan = TimelinePlan([], DEFAULT_DAILY_WORK_MINUTES, fits_deadline=True)
    for daily_minutes in DAILY_WORK_MINUTE_OPTIONS:
        slots = build_timeline(durations_minutes, start_after, daily_minutes, busy)
        fits = finish_by is None or not slots or slots[-1].end <= finish_by
        plan = TimelinePlan(slots, daily_minutes, fits_deadline=fits)
        if fits:
            return plan
    return plan
