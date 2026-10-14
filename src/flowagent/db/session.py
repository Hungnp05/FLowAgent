from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

SQLITE_PREFIX = "sqlite:///"
IN_MEMORY_SQLITE_URL = "sqlite://"


def create_db_engine(database_url: str) -> Engine:
    """Create an engine for the URL and make sure every table exists."""
    if database_url == IN_MEMORY_SQLITE_URL:
        engine = create_engine(
            database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    elif database_url.startswith(SQLITE_PREFIX):
        Path(database_url.removeprefix(SQLITE_PREFIX)).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(database_url, pool_pre_ping=True)
    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Yield a session that commits on success and rolls back on error."""
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
