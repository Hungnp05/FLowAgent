from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session

from flowagent.db import crud
from flowagent.db.models import Priority, Recurrence, Task, TaskStatus
from flowagent.db.schemas import ScheduleEventCreate
from flowagent.errors import EventNotFoundError
from flowagent.planning.calendar import (
    EN_DASH,
    CalendarEntry,
    CalendarMode,
    EntrySource,
    Occurrence,
    assign_lanes,
    occurrence_starts,
    occurrences_by_day,
    period_label,
    reminder_time,
    shift_anchor,
    task_to_entries,
    upcoming_reminders,
)


def make_entry(
    start: datetime,
    recurrence: Recurrence = Recurrence.NONE,
    duration_minutes: int = 60,
    all_day: bool = False,
    key: str = "event:1",
    reminder_minutes: int = 0,
) -> CalendarEntry:
    """Build a calendar entry for scheduling tests."""
    return CalendarEntry(
        key=key,
        source=EntrySource.EVENT,
        source_id=1,
        title="Họp",
        start=start,
        duration_minutes=duration_minutes,
        all_day=all_day,
        recurrence=recurrence,
        reminder_minutes=reminder_minutes,
    )


def test_monthly_recurrence_does_not_drift_after_short_months() -> None:
    """An event on the 31st falls on the last day of short months and returns to the 31st after."""
    entry = make_entry(datetime(2026, 1, 31, 9, 0), Recurrence.MONTHLY)
    starts = occurrence_starts(entry, datetime(2026, 1, 1), datetime(2026, 4, 1))
    assert [moment.date() for moment in starts] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
    ]


def test_weekly_recurrence_inside_a_late_window() -> None:
    """Weekly events are found far after their first occurrence without iterating from the start."""
    entry = make_entry(datetime(2020, 1, 6, 8, 0), Recurrence.WEEKLY)
    starts = occurrence_starts(entry, datetime(2026, 10, 12), datetime(2026, 10, 19))
    assert starts == [datetime(2026, 10, 12, 8, 0)]


def test_occurrences_by_day_puts_all_day_first() -> None:
    """Within a day, all-day entries come before timed ones, which are ordered by start."""
    timed = make_entry(datetime(2026, 10, 15, 8, 0), key="event:1")
    all_day = make_entry(datetime(2026, 10, 15), all_day=True, duration_minutes=1440, key="event:2")
    by_day = occurrences_by_day([timed, all_day], date(2026, 10, 12), date(2026, 10, 18))
    assert [occurrence.entry.key for occurrence in by_day[date(2026, 10, 15)]] == [
        "event:2",
        "event:1",
    ]


def test_assign_lanes_splits_overlaps_and_reuses_free_lanes() -> None:
    """Overlapping events get different lanes; a later event reuses the first free lane."""
    first = Occurrence(
        make_entry(datetime(2026, 10, 15, 9, 0), key="a"), datetime(2026, 10, 15, 9, 0)
    )
    overlapping = Occurrence(
        make_entry(datetime(2026, 10, 15, 9, 30), key="b"), datetime(2026, 10, 15, 9, 30)
    )
    later = Occurrence(
        make_entry(datetime(2026, 10, 15, 10, 0), key="c"), datetime(2026, 10, 15, 10, 0)
    )
    lanes = assign_lanes([first, overlapping, later])
    assert (lanes[first], lanes[overlapping], lanes[later]) == (0, 1, 0)


def test_task_with_start_and_date_only_deadline_gives_block_and_all_day_marker() -> None:
    """A task shows a work block at its start and an all-day deadline marker on another day."""
    task = Task(
        id=7,
        title="Báo cáo",
        planned_start=datetime(2026, 10, 15, 9, 0),
        deadline=datetime(2026, 10, 17, 23, 59),
        estimated_minutes=90,
    )
    work, deadline = task_to_entries(task)
    assert (work.title, work.duration_minutes) == ("Làm: Báo cáo", 90)
    assert (deadline.all_day, deadline.start, deadline.title) == (
        True,
        datetime(2026, 10, 17),
        "Hạn: Báo cáo",
    )


def test_same_day_deadline_ends_the_work_block_and_done_tasks_are_marked() -> None:
    """A deadline on the start day becomes the end of the block, and done tasks are marked."""
    task = Task(
        id=8,
        title="Ôn tập",
        status=TaskStatus.DONE,
        planned_start=datetime(2026, 10, 14, 14, 0),
        deadline=datetime(2026, 10, 14, 17, 0),
    )
    entries = task_to_entries(task)
    assert len(entries) == 1
    assert (entries[0].title, entries[0].duration_minutes) == ("[Xong] Làm: Ôn tập", 180)


def test_reminders_use_offset_and_seven_am_for_all_day() -> None:
    """Timed events remind before their start; all-day events remind at 07:00."""
    timed = Occurrence(
        make_entry(datetime(2026, 10, 15, 9, 0), reminder_minutes=30), datetime(2026, 10, 15, 9, 0)
    )
    all_day = Occurrence(make_entry(datetime(2026, 10, 16), all_day=True), datetime(2026, 10, 16))
    assert reminder_time(timed) == datetime(2026, 10, 15, 8, 30)
    assert reminder_time(all_day) == datetime(2026, 10, 16, 7, 0)


def test_upcoming_reminders_ignore_tasks_and_far_events() -> None:
    """Only events whose reminder is within the horizon are listed."""
    now = datetime(2026, 10, 15, 8, 0)
    soon = make_entry(now + timedelta(hours=2), key="event:1")
    far = make_entry(now + timedelta(days=3), key="event:2")
    task_entry = CalendarEntry(
        "task:1#work", EntrySource.TASK, 1, "Việc", now + timedelta(hours=1), 60
    )
    reminders = upcoming_reminders([soon, far, task_entry], now, timedelta(hours=24))
    assert [occurrence.entry.key for occurrence in reminders] == ["event:1"]


@pytest.mark.parametrize(
    ("mode", "expected_label"),
    [
        (CalendarMode.WEEK, f"12/10 {EN_DASH} 18/10/2026"),
        (CalendarMode.MONTH, "Tháng 10, 2026"),
        (CalendarMode.YEAR, "Năm 2026"),
        (CalendarMode.DAY, "Thứ 5, 15/10/2026"),
    ],
)
def test_period_label(mode: CalendarMode, expected_label: str) -> None:
    """Each mode shows its period the way MobiAssistant does."""
    assert period_label(mode, date(2026, 10, 15)) == expected_label


def test_shift_anchor_clamps_month_end() -> None:
    """Moving one month from 31 October lands on 30 November."""
    assert shift_anchor(CalendarMode.MONTH, date(2026, 10, 31), 1) == date(2026, 11, 30)
    assert shift_anchor(CalendarMode.WEEK, date(2026, 10, 15), -1) == date(2026, 10, 8)


def test_event_crud_round_trip(session: Session) -> None:
    """Events can be created, replaced, re-prioritised and deleted."""
    event_in = ScheduleEventCreate(title="Học nhóm", start_at=datetime(2026, 10, 16, 19, 0))
    event = crud.create_event(session, event_in)
    replaced = crud.replace_event(
        session,
        event.id,
        event_in.model_copy(update={"title": "Học nhóm AI", "recurrence": Recurrence.WEEKLY}),
    )
    assert (replaced.title, replaced.recurrence) == ("Học nhóm AI", Recurrence.WEEKLY)
    assert (
        crud.change_event_priority(session, event.id, Priority.URGENT).priority == Priority.URGENT
    )
    crud.delete_event(session, event.id)
    with pytest.raises(EventNotFoundError):
        crud.get_event(session, event.id)
