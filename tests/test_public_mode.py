import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from flowagent.agent.llm import plan_model_chain
from flowagent.agent.llm_config import build_visitor_llm_config
from flowagent.config import Settings
from flowagent.db import crud
from flowagent.db.models import TaskStatus
from flowagent.db.session import IN_MEMORY_SQLITE_URL, create_db_engine, session_scope
from flowagent.demo_data import DEMO_PROJECT_NAME, DEMO_PROJECT_STEPS, seed_demo_data
from flowagent.errors import MissingApiKeyError
from flowagent.planning.alerts import find_at_risk_tasks, find_conflicts
from flowagent.schedule_queries import read_calendar_entries
from tests.conftest import FIXED_NOW

SERVER_SETTINGS = Settings(gemini_api_key="server-gemini", groq_api_key="server-groq")


def test_demo_data_has_tasks_project_events_and_memories(session: Session) -> None:
    """The sample data covers every page: statuses, a scheduled project, events and memories."""
    seed_demo_data(session, FIXED_NOW)
    tasks = crud.list_tasks(session)
    project = crud.get_project_by_name(session, DEMO_PROJECT_NAME)
    steps = [task for task in tasks if task.project_id == project.id]
    assert len(steps) == len(DEMO_PROJECT_STEPS)
    assert all(step.planned_start and step.deadline for step in steps)
    assert {task.status for task in tasks} == set(TaskStatus)
    assert len(crud.list_events(session)) == 4
    assert len(crud.list_memories(session)) == 2


def test_demo_data_shows_one_clash_and_one_overdue_task(session: Session) -> None:
    """The sample calendar demonstrates the warnings: one pinned clash and one overdue task."""
    seed_demo_data(session, FIXED_NOW)
    entries = read_calendar_entries(session, include_done=False)
    conflicts = find_conflicts(entries, FIXED_NOW.date(), FIXED_NOW.date().replace(day=21))
    assert [(c.first.entry.title, c.second.entry.title) for c in conflicts] == [
        ("Làm: Ôn thi giải tích", "Họp khoa")
    ]
    overdue = find_at_risk_tasks(crud.list_tasks(session), FIXED_NOW)
    assert [risk.task.title for risk in overdue] == ["Đóng tiền điện tháng này"]


def test_visitor_config_never_uses_server_keys() -> None:
    """A visitor without keys gets no usable model even when the server has keys configured."""
    config = build_visitor_llm_config(SERVER_SETTINGS, "gemini", "", "")
    assert (config.gemini_api_key, config.groq_api_key) == ("", "")
    with pytest.raises(MissingApiKeyError):
        plan_model_chain(config)


def test_visitor_config_uses_their_keys_and_default_models() -> None:
    """A visitor's own key drives the chain, with the deployment's default model names."""
    config = build_visitor_llm_config(SERVER_SETTINGS, "groq", "", "  visitor-groq  ")
    chain = plan_model_chain(config)
    assert [(spec.provider, spec.model_name, spec.api_key) for spec in chain] == [
        ("groq", SERVER_SETTINGS.groq_model, "visitor-groq")
    ]


def test_each_demo_engine_is_isolated(engine: Engine) -> None:
    """Two visitors' in-memory databases never see each other's rows."""
    other = create_db_engine(IN_MEMORY_SQLITE_URL)
    with session_scope(engine) as session:
        seed_demo_data(session, FIXED_NOW)
    with session_scope(other) as session:
        assert list(crud.list_tasks(session)) == []
