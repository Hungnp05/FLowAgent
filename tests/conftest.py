from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from flowagent.agent.tools import DEPS_CONFIG_KEY, ToolDeps
from flowagent.db.session import IN_MEMORY_SQLITE_URL, create_db_engine, session_scope

FIXED_NOW = datetime(2026, 10, 14, 10, 0)


def fixed_clock() -> datetime:
    """Return a constant 'now' so time-dependent tests are deterministic."""
    return FIXED_NOW


@pytest.fixture
def engine() -> Engine:
    """Provide a fresh in-memory database for each test."""
    return create_db_engine(IN_MEMORY_SQLITE_URL)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Provide a transactional session on the test database."""
    with session_scope(engine) as db_session:
        yield db_session


@pytest.fixture
def tool_config(engine: Engine) -> dict:
    """Provide the run config that tools expect when invoked directly."""
    return {"configurable": {DEPS_CONFIG_KEY: ToolDeps(engine=engine, clock=fixed_clock)}}
