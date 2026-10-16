from datetime import date, datetime, timedelta

import pytest

from flowagent.db.models import Priority, Recurrence, ScheduleEvent, Task, TaskStatus
from flowagent.errors import InvalidScheduleError
from flowagent.planning.alerts import (
    RiskKind,
    find_at_risk_tasks,
    find_conflicts,
    work_minutes_between,
)
from flowagent.planning.calendar import build_calendar_entries, busy_periods
from flowagent.planning.progress import ReportPeriod, build_progress_report, report_period_start
from flowagent.planning.scheduler import (
    TimeSlot,
    build_timeline,
    needs_rescheduling,
    order_for_rescheduling,
    plan_within_deadline,
)
from tests.conftest import FIXED_NOW

THURSDAY_NINE = datetime(2026, 10, 15, 9, 0)


def make_task(task_id: int, **fields: object) -> Task:
    """Build an unsaved task with an id for pure planning tests."""
    return Task(id=task_id, title=f"Việc {task_id}", **fields)


def test_build_timeline_skips_busy_periods() -> None:
    """A meeting in the working window pushes work around it and splits a long step."""
    meeting = TimeSlot(THURSDAY_NINE + timedelta(hours=1), THURSDAY_NINE + timedelta(hours=2))
    slots = build_timeline([60, 120], FIXED_NOW, busy=[meeting])
    assert slots[0] == TimeSlot(THURSDAY_NINE, THURSDAY_NINE + timedelta(hours=1))
    assert slots[1] == TimeSlot(meeting.end, meeting.end + timedelta(hours=2))


def test_build_timeline_without_free_time_raises() -> None:
    """A schedule that is busy every day for a year cannot be planned."""
    busy = [TimeSlot(THURSDAY_NINE, THURSDAY_NINE + timedelta(days=400))]
    with pytest.raises(InvalidScheduleError):
        build_timeline([60], FIXED_NOW, busy=busy)


def test_plan_within_deadline_uses_longer_days_only_when_needed() -> None:
    """Twelve hours of work fit by Friday evening only with six-hour days."""
    plan = plan_within_deadline([720], FIXED_NOW, finish_by=datetime(2026, 10, 16, 23, 59))
    assert (plan.daily_work_minutes, plan.fits_deadline) == (360, True)
    assert plan_within_deadline([720], FIXED_NOW).daily_work_minutes == 240


def test_plan_within_deadline_reports_a_miss() -> None:
    """Work that cannot finish even with eight-hour days is flagged as not fitting."""
    plan = plan_within_deadline([2000], FIXED_NOW, finish_by=datetime(2026, 10, 15, 23, 59))
    assert plan.fits_deadline is False
    assert plan.daily_work_minutes == 480


def test_needs_rescheduling_flags_overdue_and_missed_starts() -> None:
    """Overdue and not-yet-started past work need a new slot; done or future work does not."""
    overdue = make_task(1, deadline=FIXED_NOW - timedelta(days=1))
    missed = make_task(2, planned_start=FIXED_NOW - timedelta(hours=2))
    started = make_task(
        3, planned_start=FIXED_NOW - timedelta(hours=2), status=TaskStatus.IN_PROGRESS
    )
    finished = make_task(4, deadline=FIXED_NOW - timedelta(days=1), status=TaskStatus.DONE)
    assert [
        needs_rescheduling(task, FIXED_NOW) for task in (overdue, missed, started, finished)
    ] == [
        True,
        True,
        False,
        False,
    ]


def test_order_for_rescheduling_puts_urgent_first() -> None:
    """Higher priority overdue work is rescheduled first."""
    low = make_task(1, priority=Priority.LOW, deadline=FIXED_NOW - timedelta(days=1))
    urgent = make_task(2, priority=Priority.URGENT, deadline=FIXED_NOW - timedelta(days=1))
    assert [task.id for task in order_for_rescheduling([low, urgent], FIXED_NOW)] == [2, 1]


def test_find_conflicts_detects_recurring_clash() -> None:
    """A daily gym session clashes with a task's work block on one day only."""
    gym = ScheduleEvent(
        id=1,
        title="Tập gym",
        start_at=datetime(2026, 10, 14, 18, 0),
        duration_minutes=120,
        recurrence=Recurrence.DAILY,
    )
    task = make_task(5, planned_start=datetime(2026, 10, 16, 19, 0), estimated_minutes=60)
    entries = build_calendar_entries([gym], [task])
    conflicts = find_conflicts(entries, date(2026, 10, 14), date(2026, 10, 20))
    assert len(conflicts) == 1
    assert conflicts[0].first.start.date() == date(2026, 10, 16)


def test_deadline_markers_and_all_day_entries_never_conflict() -> None:
    """Deadline markers and all-day events do not occupy clock time."""
    birthday = ScheduleEvent(id=1, title="Sinh nhật", start_at=datetime(2026, 10, 15), all_day=True)
    due = make_task(2, deadline=datetime(2026, 10, 15, 10, 0))
    meeting = ScheduleEvent(id=3, title="Họp", start_at=datetime(2026, 10, 15, 10, 0))
    entries = build_calendar_entries([birthday, meeting], [due])
    assert find_conflicts(entries, date(2026, 10, 15), date(2026, 10, 15)) == []
    busy = busy_periods(entries, date(2026, 10, 15), date(2026, 10, 15))
    assert busy == [TimeSlot(datetime(2026, 10, 15, 10, 0), datetime(2026, 10, 15, 11, 0))]


def test_work_minutes_between_counts_only_working_windows() -> None:
    """From Wednesday 10:00 to Thursday 23:59 there are 3 + 4 working hours."""
    assert work_minutes_between(FIXED_NOW, datetime(2026, 10, 15, 23, 59)) == 420


def test_find_at_risk_tasks_flags_overdue_and_tight_deadlines() -> None:
    """Overdue work comes first, then work whose estimate exceeds the time left."""
    tight = make_task(1, deadline=datetime(2026, 10, 14, 23, 59), estimated_minutes=300)
    relaxed = make_task(2, deadline=datetime(2026, 10, 20, 23, 59), estimated_minutes=60)
    overdue = make_task(3, deadline=FIXED_NOW - timedelta(hours=1))
    risks = find_at_risk_tasks([tight, relaxed, overdue], FIXED_NOW)
    assert [(risk.task.id, risk.kind) for risk in risks] == [
        (3, RiskKind.OVERDUE),
        (1, RiskKind.NOT_ENOUGH_TIME),
    ]
    assert risks[1].work_minutes_left == 180


def test_report_period_starts_on_monday_for_weeks() -> None:
    """A weekly report on Wednesday covers Monday onwards; a daily one starts at midnight."""
    assert report_period_start(ReportPeriod.WEEK, FIXED_NOW) == datetime(2026, 10, 12)
    assert report_period_start(ReportPeriod.DAY, FIXED_NOW) == datetime(2026, 10, 14)


def test_build_progress_report_groups_tasks() -> None:
    """Tasks are split into finished this week, in progress, overdue and due soon."""
    done_on_time = make_task(
        1,
        status=TaskStatus.DONE,
        completed_at=datetime(2026, 10, 13, 15, 0),
        deadline=datetime(2026, 10, 13, 23, 59),
    )
    done_last_week = make_task(2, status=TaskStatus.DONE, completed_at=datetime(2026, 10, 9))
    doing = make_task(3, status=TaskStatus.IN_PROGRESS, deadline=datetime(2026, 10, 16, 23, 59))
    late = make_task(4, deadline=datetime(2026, 10, 13, 23, 59), created_at=datetime(2026, 10, 1))
    report = build_progress_report(
        [done_on_time, done_last_week, doing, late], ReportPeriod.WEEK, FIXED_NOW
    )
    assert [task.id for task in report.completed] == [1]
    assert report.on_time_count == 1
    assert [task.id for task in report.in_progress] == [3]
    assert [task.id for task in report.overdue] == [4]
    assert [task.id for task in report.upcoming] == [3]


def test_multi_day_and_slack_work_does_not_count_as_a_clash() -> None:
    """Work spread over days or with slack before its deadline never pins an exact time."""
    meeting = ScheduleEvent(id=1, title="Họp", start_at=datetime(2026, 10, 15, 10, 0))
    spread = make_task(
        2,
        planned_start=datetime(2026, 10, 15, 9, 0),
        deadline=datetime(2026, 10, 16, 13, 0),
        estimated_minutes=480,
    )
    slack = make_task(
        3,
        planned_start=datetime(2026, 10, 15, 9, 0),
        deadline=datetime(2026, 10, 15, 12, 0),
        estimated_minutes=120,
    )
    pinned = make_task(
        4, planned_start=datetime(2026, 10, 15, 9, 30), deadline=datetime(2026, 10, 15, 10, 30)
    )
    entries = build_calendar_entries([meeting], [spread, slack, pinned])
    conflicts = find_conflicts(entries, date(2026, 10, 15), date(2026, 10, 16))
    assert [(c.first.entry.source_id, c.second.entry.source_id) for c in conflicts] == [(4, 1)]
