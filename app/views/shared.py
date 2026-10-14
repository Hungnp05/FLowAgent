import logging
from pathlib import Path

import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine

from flowagent.agent.factory import create_flow_agent
from flowagent.agent.llm_config import LlmConfig, load_llm_config
from flowagent.agent.service import FlowAgent
from flowagent.agent.tools import PriorityPredictorFn
from flowagent.config import get_settings
from flowagent.db import crud
from flowagent.db.models import Priority, Task, TaskStatus
from flowagent.db.schemas import TaskFilter, TaskUpdate
from flowagent.db.session import create_db_engine, session_scope
from flowagent.ml.predictor import load_priority_predictor
from flowagent.security.secret_box import SecretBox, load_or_create_secret_box

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    TaskStatus.TODO: "Cần làm",
    TaskStatus.IN_PROGRESS: "Đang làm",
    TaskStatus.DONE: "Hoàn thành",
}
PRIORITY_LABELS = {
    Priority.LOW: "🟢 Thấp",
    Priority.MEDIUM: "🟡 Trung bình",
    Priority.HIGH: "🟠 Cao",
    Priority.URGENT: "🔴 Khẩn cấp",
}
STATUS_ORDER = list(STATUS_LABELS)


@st.cache_resource
def get_engine() -> Engine:
    """Create the database engine once per Streamlit server process."""
    return create_db_engine(get_settings().database_url)


@st.cache_resource
def get_secret_box() -> SecretBox:
    """Load the key that encrypts API keys stored in the database."""
    return load_or_create_secret_box(Path(get_settings().secret_key_path))


@st.cache_resource
def get_checkpointer() -> InMemorySaver:
    """Keep conversation memory alive even when the agent is rebuilt with new settings."""
    return InMemorySaver()


def load_current_llm_config() -> LlmConfig:
    """Read the LLM settings saved in the app, falling back to .env values."""
    with session_scope(get_engine()) as session:
        return load_llm_config(session, get_settings(), get_secret_box())


@st.cache_resource
def get_priority_predictor() -> PriorityPredictorFn | None:
    """Load the trained priority model once, or return None when it has not been trained."""
    artifact_path = Path(get_settings().priority_model_path)
    if not artifact_path.exists():
        logger.warning("Priority model not found at %s; using medium by default", artifact_path)
        return None
    return load_priority_predictor(artifact_path).predict


@st.cache_resource(max_entries=1)
def build_agent_for_config(config_fingerprint: int, _config: LlmConfig) -> FlowAgent:
    """Build the agent once per distinct configuration; the fingerprint is the cache key."""
    return create_flow_agent(
        _config, get_settings(), get_engine(), get_checkpointer(), get_priority_predictor()
    )


def get_agent() -> FlowAgent:
    """Return the agent for the current settings; raises MissingApiKeyError without any key."""
    config = load_current_llm_config()
    return build_agent_for_config(hash(config), config)


def load_tasks(task_filter: TaskFilter | None = None) -> list[Task]:
    """Fetch tasks from the database for rendering."""
    with session_scope(get_engine()) as session:
        return list(crud.list_tasks(session, task_filter))


def change_task_status(task_id: int, status: TaskStatus) -> None:
    """Persist a new status for a task."""
    with session_scope(get_engine()) as session:
        crud.update_task(session, task_id, TaskUpdate(status=status))
