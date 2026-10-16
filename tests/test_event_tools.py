from datetime import datetime

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import Engine

from flowagent.agent.service import FlowAgent
from flowagent.agent.tools import create_event, list_events, update_event
from flowagent.db import crud
from flowagent.db.models import Recurrence
from flowagent.db.schemas import ScheduleEventCreate
from flowagent.db.session import session_scope
from flowagent.errors import EventNotFoundError
from tests.conftest import fixed_clock
from tests.test_agent_service import ScriptedChatModel, tool_call_message


def stored_events(engine: Engine) -> list:
    """Read every stored calendar event."""
    with session_scope(engine) as session:
        return list(crud.list_events(session))


def test_create_event_stores_daily_recurrence(engine: Engine, tool_config: dict) -> None:
    """A daily gym session is stored as one recurring event with its time and duration."""
    result = create_event.invoke(
        {
            "title": "Tập gym",
            "start": "2026-10-15 18:00",
            "duration_minutes": 120,
            "recurrence": "daily",
        },
        tool_config,
    )
    assert "Hằng ngày" in result
    (event,) = stored_events(engine)
    assert (event.start_at, event.duration_minutes, event.recurrence) == (
        datetime(2026, 10, 15, 18, 0),
        120,
        Recurrence.DAILY,
    )


def test_create_all_day_event_starts_at_midnight(engine: Engine, tool_config: dict) -> None:
    """All-day events cover the whole date regardless of the time passed."""
    create_event.invoke(
        {"title": "Sinh nhật mẹ", "start": "2026-10-20", "all_day": True}, tool_config
    )
    (event,) = stored_events(engine)
    assert (event.start_at, event.duration_minutes) == (datetime(2026, 10, 20), 1440)


def test_list_events_by_day_includes_recurring_occurrences(
    engine: Engine, tool_config: dict
) -> None:
    """A daily event shows up on later days; a one-off event only on its own day."""
    create_event.invoke(
        {"title": "Đọc sách", "start": "2026-10-15 21:00", "recurrence": "daily"}, tool_config
    )
    create_event.invoke({"title": "Họp nhóm", "start": "2026-10-15 14:00"}, tool_config)
    later_day = list_events.invoke({"day": "2026-10-18"}, tool_config)
    assert "Đọc sách" in later_day and "Họp nhóm" not in later_day
    assert "Họp nhóm" in list_events.invoke({"keyword": "hop nhom"}, tool_config)


def test_update_event_changes_only_given_fields(engine: Engine, tool_config: dict) -> None:
    """Turning an event into a weekly one keeps its title and time."""
    create_event.invoke({"title": "Học tiếng Anh", "start": "2026-10-16 19:00"}, tool_config)
    update_event.invoke({"event_id": 1, "recurrence": "weekly"}, tool_config)
    (event,) = stored_events(engine)
    assert (event.title, event.start_at, event.recurrence) == (
        "Học tiếng Anh",
        datetime(2026, 10, 16, 19, 0),
        Recurrence.WEEKLY,
    )
    assert "Không có gì thay đổi" in update_event.invoke({"event_id": 1}, tool_config)


@pytest.mark.parametrize(("is_approved", "should_exist"), [(True, False), (False, True)])
def test_delete_event_waits_for_confirmation(
    engine: Engine, is_approved: bool, should_exist: bool
) -> None:
    """Deleting an event pauses for confirmation and only removes it when approved."""
    with session_scope(engine) as session:
        event_id = crud.create_event(
            session, ScheduleEventCreate(title="Họp", start_at=datetime(2026, 10, 16, 9, 0))
        ).id
    replies = [tool_call_message("delete_event", {"event_id": event_id}), AIMessage("Xong.")]
    agent = FlowAgent(ScriptedChatModel(messages=iter(replies)), engine, clock=fixed_clock)
    paused = agent.send("thread", "Xoá lịch họp")
    assert paused.pending_confirmation["action"] == "delete_event"
    agent.resolve_confirmation("thread", is_approved)
    with session_scope(engine) as session:
        if should_exist:
            assert crud.get_event(session, event_id)
        else:
            with pytest.raises(EventNotFoundError):
                crud.get_event(session, event_id)
