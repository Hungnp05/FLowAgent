import calendar
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from flowagent.db.models import (
    MINUTES_PER_DAY,
    Priority,
    Recurrence,
    ScheduleEvent,
    Task,
    TaskStatus,
)
from flowagent.planning.scheduler import DEFAULT_TASK_MINUTES, TimeSlot

TASK_KEY_PREFIX = "task:"
DEADLINE_KEY_SUFFIX = "#deadline"
WORK_KEY_SUFFIX = "#work"
EVENT_KEY_PREFIX = "event:"
END_OF_DAY = time(hour=23, minute=59)
DEADLINE_MARKER_MINUTES = 30
MIN_WORK_BLOCK_MINUTES = 15
MIN_DRAWN_MINUTES = 30
ALL_DAY_NOTIFY_HOUR = 7
MAX_OCCURRENCE_ITERATIONS = 100_000
DAYS_PER_WEEK = 7
MONTH_GRID_DAYS = 42
MONTHS_PER_YEAR = 12
DONE_PREFIX = "[Xong] "
EN_DASH = chr(0x2013)
PERIOD_SEPARATOR = f" {EN_DASH} "
WORK_PREFIX = "Làm: "
DEADLINE_PREFIX = "Hạn: "
SHORT_WEEKDAYS = ("T2", "T3", "T4", "T5", "T6", "T7", "CN")
FULL_WEEKDAYS = ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật")
LONGEST_PERIOD = {
    Recurrence.DAILY: timedelta(days=1, hours=1),
    Recurrence.WEEKLY: timedelta(days=7, hours=1),
    Recurrence.MONTHLY: timedelta(days=31, hours=1),
    Recurrence.YEARLY: timedelta(days=366, hours=1),
}


class CalendarMode(StrEnum):
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    DAY = "day"


class EntrySource(StrEnum):
    EVENT = "event"
    TASK = "task"


@dataclass(frozen=True)
class CalendarEntry:
    key: str
    source: EntrySource
    source_id: int
    title: str
    start: datetime
    duration_minutes: int
    all_day: bool = False
    recurrence: Recurrence = Recurrence.NONE
    reminder_minutes: int = 0
    priority: Priority = Priority.MEDIUM
    note: str = ""


@dataclass(frozen=True)
class Occurrence:
    entry: CalendarEntry
    start: datetime

    @property
    def end(self) -> datetime:
        """Return when this occurrence finishes."""
        return self.start + timedelta(minutes=self.entry.duration_minutes)


def add_months(moment: datetime, months: int) -> datetime:
    """Add whole months, clamping the day to the target month's length (31 Jan + 1 → 28/29 Feb)."""
    month_index = moment.month - 1 + months
    year, month = moment.year + month_index // MONTHS_PER_YEAR, month_index % MONTHS_PER_YEAR + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def nth_occurrence(start: datetime, recurrence: Recurrence, index: int) -> datetime:
    """Return the index-th repetition, always counted from the original start to avoid drift."""
    if recurrence == Recurrence.DAILY:
        return start + timedelta(days=index)
    if recurrence == Recurrence.WEEKLY:
        return start + timedelta(weeks=index)
    if recurrence == Recurrence.MONTHLY:
        return add_months(start, index)
    if recurrence == Recurrence.YEARLY:
        return add_months(start, index * MONTHS_PER_YEAR)
    return start


def occurrence_starts(
    entry: CalendarEntry, window_start: datetime, window_end: datetime
) -> list[datetime]:
    """List the entry's start times falling in [window_start, window_end)."""
    if entry.recurrence == Recurrence.NONE:
        return [entry.start] if window_start <= entry.start < window_end else []
    first_index = 0
    if window_start > entry.start:
        first_index = max(0, (window_start - entry.start) // LONGEST_PERIOD[entry.recurrence] - 1)
    starts = []
    for index in range(first_index, first_index + MAX_OCCURRENCE_ITERATIONS):
        moment = nth_occurrence(entry.start, entry.recurrence, index)
        if moment >= window_end:
            break
        if moment >= window_start:
            starts.append(moment)
    return starts


def occurrences_by_day(
    entries: Iterable[CalendarEntry], first_day: date, last_day: date
) -> dict[date, list[Occurrence]]:
    """Group every occurrence between two days (inclusive), all-day entries first, then by time."""
    window_start = datetime.combine(first_day, time.min)
    window_end = datetime.combine(last_day + timedelta(days=1), time.min)
    occurrences = [
        Occurrence(entry, moment)
        for entry in entries
        for moment in occurrence_starts(entry, window_start, window_end)
    ]
    occurrences.sort(key=lambda occurrence: (not occurrence.entry.all_day, occurrence.start))
    by_day: dict[date, list[Occurrence]] = defaultdict(list)
    for occurrence in occurrences:
        by_day[occurrence.start.date()].append(occurrence)
    return dict(by_day)


def assign_lanes(occurrences: Sequence[Occurrence]) -> dict[Occurrence, int]:
    """Place overlapping timed occurrences side by side, each in the first free lane."""
    lane_ends: list[datetime] = []
    lanes: dict[Occurrence, int] = {}
    for occurrence in sorted(occurrences, key=lambda item: item.start):
        drawn_end = occurrence.start + timedelta(
            minutes=max(occurrence.entry.duration_minutes, MIN_DRAWN_MINUTES)
        )
        free_lane = next(
            (index for index, end in enumerate(lane_ends) if end <= occurrence.start), None
        )
        if free_lane is None:
            lane_ends.append(drawn_end)
            free_lane = len(lane_ends) - 1
        else:
            lane_ends[free_lane] = drawn_end
        lanes[occurrence] = free_lane
    return lanes


def event_to_entry(event: ScheduleEvent) -> CalendarEntry:
    """Wrap a stored calendar event as a drawable calendar entry."""
    return CalendarEntry(
        key=event_entry_key(event.id or 0),
        source=EntrySource.EVENT,
        source_id=event.id or 0,
        title=event.title,
        start=event.start_at,
        duration_minutes=event.duration_minutes,
        all_day=event.all_day,
        recurrence=event.recurrence,
        reminder_minutes=event.reminder_minutes,
        priority=event.priority,
        note=event.note,
    )


def work_entry_key(task_id: int) -> str:
    """Return the calendar key of a task's work block."""
    return f"{TASK_KEY_PREFIX}{task_id}{WORK_KEY_SUFFIX}"


def event_entry_key(event_id: int) -> str:
    """Return the calendar key of a stored event."""
    return f"{EVENT_KEY_PREFIX}{event_id}"


def work_block_minutes(task: Task) -> int:
    """Size a task's work block: until a same-day deadline, else its estimate or the default."""
    start, deadline = task.planned_start, task.deadline
    if start and deadline and deadline.date() == start.date() and deadline > start:
        minutes = int((deadline - start).total_seconds() // 60)
    else:
        minutes = task.estimated_minutes or DEFAULT_TASK_MINUTES
    return max(MIN_WORK_BLOCK_MINUTES, min(minutes, MINUTES_PER_DAY))


def deadline_entry(task: Task, mark: str) -> CalendarEntry | None:
    """Build the deadline marker, unless the deadline already ends a same-day work block."""
    deadline = task.deadline
    if deadline is None or (task.planned_start and task.planned_start.date() == deadline.date()):
        return None
    is_date_only = deadline.time() == END_OF_DAY
    return CalendarEntry(
        key=f"{TASK_KEY_PREFIX}{task.id}{DEADLINE_KEY_SUFFIX}",
        source=EntrySource.TASK,
        source_id=task.id or 0,
        title=f"{mark}{DEADLINE_PREFIX}{task.title}",
        start=datetime.combine(deadline.date(), time.min) if is_date_only else deadline,
        duration_minutes=MINUTES_PER_DAY if is_date_only else DEADLINE_MARKER_MINUTES,
        all_day=is_date_only,
        priority=task.priority,
    )


def task_to_entries(task: Task) -> list[CalendarEntry]:
    """Show a task on the calendar as a work block from its start and a deadline marker."""
    mark = DONE_PREFIX if task.status == TaskStatus.DONE else ""
    entries = []
    if task.planned_start:
        entries.append(
            CalendarEntry(
                key=work_entry_key(task.id or 0),
                source=EntrySource.TASK,
                source_id=task.id or 0,
                title=f"{mark}{WORK_PREFIX}{task.title}",
                start=task.planned_start,
                duration_minutes=work_block_minutes(task),
                priority=task.priority,
                note=task.description,
            )
        )
    marker = deadline_entry(task, mark)
    return [*entries, marker] if marker else entries


def build_calendar_entries(
    events: Iterable[ScheduleEvent], tasks: Iterable[Task]
) -> list[CalendarEntry]:
    """Combine stored events and task-derived entries into one list for drawing."""
    return [event_to_entry(event) for event in events] + [
        entry for task in tasks for entry in task_to_entries(task)
    ]


def blocks_time(entry: CalendarEntry) -> bool:
    """Report whether an entry occupies clock time (timed events and work blocks, not markers)."""
    return not entry.all_day and not entry.key.endswith(DEADLINE_KEY_SUFFIX)


def busy_periods(
    entries: Iterable[CalendarEntry], first_day: date, last_day: date
) -> list[TimeSlot]:
    """List the time ranges already taken by events and planned work between two days."""
    by_day = occurrences_by_day(
        [entry for entry in entries if blocks_time(entry)], first_day, last_day
    )
    return [
        TimeSlot(occurrence.start, occurrence.end)
        for day_occurrences in by_day.values()
        for occurrence in day_occurrences
    ]


def reminder_time(occurrence: Occurrence) -> datetime:
    """Return when to remind: 07:00 for all-day events, else start minus the reminder offset."""
    if occurrence.entry.all_day:
        return occurrence.start.replace(hour=ALL_DAY_NOTIFY_HOUR, minute=0)
    return occurrence.start - timedelta(minutes=occurrence.entry.reminder_minutes)


def upcoming_reminders(
    entries: Iterable[CalendarEntry], now: datetime, horizon: timedelta
) -> list[Occurrence]:
    """List future event occurrences whose reminder time falls before now + horizon."""
    event_entries = [entry for entry in entries if entry.source == EntrySource.EVENT]
    by_day = occurrences_by_day(
        event_entries, now.date(), (now + horizon).date() + timedelta(days=1)
    )
    return [
        occurrence
        for day_occurrences in by_day.values()
        for occurrence in day_occurrences
        if occurrence.start >= now and reminder_time(occurrence) <= now + horizon
    ]


def week_start(anchor: date) -> date:
    """Return the Monday of the anchor's week (Vietnamese weeks start on Monday)."""
    return anchor - timedelta(days=anchor.weekday())


def month_grid_start(anchor: date) -> date:
    """Return the Monday on or before the first day of the anchor's month."""
    return week_start(anchor.replace(day=1))


def format_day(day: date) -> str:
    """Render a date as dd/mm/yyyy."""
    return day.strftime("%d/%m/%Y")


def period_label(mode: CalendarMode, anchor: date) -> str:
    """Describe the period shown for a mode, e.g. 'Tháng 10, 2026' or 'Năm 2026'."""
    if mode == CalendarMode.WEEK:
        monday = week_start(anchor)
        return f"{monday:%d/%m}{PERIOD_SEPARATOR}{format_day(monday + timedelta(days=6))}"
    if mode == CalendarMode.MONTH:
        return f"Tháng {anchor.month}, {anchor.year}"
    if mode == CalendarMode.YEAR:
        return f"Năm {anchor.year}"
    return f"{FULL_WEEKDAYS[anchor.weekday()]}, {format_day(anchor)}"


def shift_anchor(mode: CalendarMode, anchor: date, steps: int) -> date:
    """Move the anchor by whole weeks, months, years or days depending on the mode."""
    if mode == CalendarMode.WEEK:
        return anchor + timedelta(weeks=steps)
    if mode == CalendarMode.MONTH:
        return add_months(datetime.combine(anchor, time.min), steps).date()
    if mode == CalendarMode.YEAR:
        return add_months(datetime.combine(anchor, time.min), steps * MONTHS_PER_YEAR).date()
    return anchor + timedelta(days=steps)
