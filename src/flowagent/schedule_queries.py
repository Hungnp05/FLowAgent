from collections.abc import Collection
from datetime import date, datetime, timedelta

from sqlmodel import Session

from flowagent.db import crud
from flowagent.db.schemas import TaskFilter
from flowagent.planning.alerts import Conflict, conflicts_involving, find_conflicts
from flowagent.planning.calendar import CalendarEntry, build_calendar_entries, busy_periods
from flowagent.planning.scheduler import TimeSlot

PLANNING_HORIZON_DAYS = 60
CONFLICT_CHECK_DAYS = 14


def read_calendar_entries(
    session: Session, excluded_task_ids: Collection[int] = (), include_done: bool = True
) -> list[CalendarEntry]:
    """Load stored events plus task-derived entries, leaving out the given tasks."""
    tasks = [
        task
        for task in crud.list_tasks(session, TaskFilter(include_done=include_done))
        if task.id not in excluded_task_ids
    ]
    return build_calendar_entries(crud.list_events(session), tasks)


def read_busy_periods(
    session: Session, now: datetime, excluded_task_ids: Collection[int] = ()
) -> list[TimeSlot]:
    """Return the times already taken by events and other open tasks over the planning horizon."""
    entries = read_calendar_entries(session, excluded_task_ids, include_done=False)
    return busy_periods(entries, now.date(), now.date() + timedelta(days=PLANNING_HORIZON_DAYS))


def read_conflicts_for(session: Session, entry_key: str, first_day: date) -> list[Conflict]:
    """List the clashes of one event or work block over the next two weeks from first_day."""
    entries = read_calendar_entries(session, include_done=False)
    last_day = first_day + timedelta(days=CONFLICT_CHECK_DAYS)
    return conflicts_involving(find_conflicts(entries, first_day, last_day), entry_key)
