import logging
import sqlite3
import uuid
from pathlib import Path

import streamlit as st
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import Engine

from flowagent.agent.factory import create_flow_agent
from flowagent.agent.llm_config import LlmConfig, build_visitor_llm_config, load_llm_config
from flowagent.agent.service import FlowAgent
from flowagent.agent.tools import PriorityPredictorFn
from flowagent.clock import now_local
from flowagent.config import LlmProvider, get_settings
from flowagent.db import crud
from flowagent.db.app_settings import SettingKey, get_setting, set_setting
from flowagent.db.models import MemoryNote, Priority, Task, TaskStatus
from flowagent.db.schemas import TaskFilter, TaskUpdate
from flowagent.db.session import IN_MEMORY_SQLITE_URL, create_db_engine, session_scope
from flowagent.demo_data import seed_demo_data
from flowagent.ml.predictor import load_priority_predictor
from flowagent.security.secret_box import SecretBox, load_or_create_secret_box

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    TaskStatus.TODO: "Cần làm",
    TaskStatus.IN_PROGRESS: "Đang làm",
    TaskStatus.DONE: "Hoàn thành",
}
PRIORITY_LABELS = {
    Priority.LOW: "Thấp",
    Priority.MEDIUM: "Trung bình",
    Priority.HIGH: "Cao",
    Priority.URGENT: "Khẩn cấp",
}
STATUS_ORDER = list(STATUS_LABELS)
SESSION_ENGINE_KEY = "public_session_engine"
SESSION_CHECKPOINTER_KEY = "public_session_checkpointer"
SESSION_AGENT_KEY = "public_session_agent"
VISITOR_KEYS_KEY = "public_visitor_keys"
DEFAULT_VISITOR_PROVIDER: LlmProvider = "gemini"


def is_public_mode() -> bool:
    """Report whether this deployment is a public demo where visitors bring their own keys."""
    return get_settings().public_mode


@st.cache_resource
def get_shared_engine() -> Engine:
    """Create the database engine once per Streamlit server process."""
    return create_db_engine(get_settings().database_url)


def create_demo_engine() -> Engine:
    """Create a private in-memory database filled with sample data for one visitor."""
    engine = create_db_engine(IN_MEMORY_SQLITE_URL)
    with session_scope(engine) as session:
        seed_demo_data(session, now_local())
    return engine


def get_engine() -> Engine:
    """Return this browser session's private demo database in public mode, else the shared one."""
    if not is_public_mode():
        return get_shared_engine()
    if SESSION_ENGINE_KEY not in st.session_state:
        st.session_state[SESSION_ENGINE_KEY] = create_demo_engine()
    return st.session_state[SESSION_ENGINE_KEY]


@st.cache_resource
def get_secret_box() -> SecretBox:
    """Load the key that encrypts API keys stored in the database."""
    return load_or_create_secret_box(Path(get_settings().secret_key_path))


@st.cache_resource
def get_checkpointer() -> BaseCheckpointSaver:
    """Store conversations in SQLite so they survive agent rebuilds and server restarts."""
    history_path = Path(get_settings().chat_history_path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(history_path, check_same_thread=False))


def get_conversation_store() -> BaseCheckpointSaver:
    """Return the shared chat history store, or a private in-memory one per public visitor."""
    if not is_public_mode():
        return get_checkpointer()
    if SESSION_CHECKPOINTER_KEY not in st.session_state:
        st.session_state[SESSION_CHECKPOINTER_KEY] = InMemorySaver()
    return st.session_state[SESSION_CHECKPOINTER_KEY]


def get_chat_thread_id() -> str:
    """Return the saved id of the current conversation, creating one on first use."""
    with session_scope(get_engine()) as session:
        thread_id = get_setting(session, SettingKey.CHAT_THREAD_ID)
    return thread_id or start_new_chat_thread()


def start_new_chat_thread() -> str:
    """Begin a fresh conversation; earlier ones stay in the history database."""
    thread_id = str(uuid.uuid4())
    with session_scope(get_engine()) as session:
        set_setting(session, SettingKey.CHAT_THREAD_ID, thread_id)
    return thread_id


def load_memories() -> list[MemoryNote]:
    """Read the facts the assistant remembers about the user."""
    with session_scope(get_engine()) as session:
        return list(crud.list_memories(session))


def add_memory(content: str) -> None:
    """Save a fact for the assistant to remember."""
    with session_scope(get_engine()) as session:
        crud.add_memory(session, content)


def forget_memory(memory_id: int) -> None:
    """Delete one remembered fact."""
    with session_scope(get_engine()) as session:
        crud.delete_memory(session, memory_id)


def get_visitor_keys() -> tuple[LlmProvider, str, str]:
    """Return the provider and API keys a public visitor entered in this browser session."""
    return st.session_state.get(VISITOR_KEYS_KEY, (DEFAULT_VISITOR_PROVIDER, "", ""))


def set_visitor_keys(provider: LlmProvider, gemini_api_key: str, groq_api_key: str) -> None:
    """Keep a public visitor's API keys in this browser session only, never in the database."""
    st.session_state[VISITOR_KEYS_KEY] = (provider, gemini_api_key.strip(), groq_api_key.strip())


def load_current_llm_config() -> LlmConfig:
    """Use a public visitor's own keys, or the settings saved in the app over the .env values."""
    if is_public_mode():
        return build_visitor_llm_config(get_settings(), *get_visitor_keys())
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


def get_visitor_agent(config: LlmConfig) -> FlowAgent:
    """Build and keep one agent per public visitor, on their own data, history and keys."""
    fingerprint = hash(config)
    cached = st.session_state.get(SESSION_AGENT_KEY)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    agent = create_flow_agent(
        config, get_settings(), get_engine(), get_conversation_store(), get_priority_predictor()
    )
    st.session_state[SESSION_AGENT_KEY] = (fingerprint, agent)
    return agent


def get_agent() -> FlowAgent:
    """Return the agent for the current settings; raises MissingApiKeyError without any key."""
    config = load_current_llm_config()
    if is_public_mode():
        return get_visitor_agent(config)
    return build_agent_for_config(hash(config), config)


def load_tasks(task_filter: TaskFilter | None = None) -> list[Task]:
    """Fetch tasks from the database for rendering."""
    with session_scope(get_engine()) as session:
        return list(crud.list_tasks(session, task_filter))


def change_task_priority(task_id: int, priority: Priority) -> None:
    """Persist a new priority for a task."""
    with session_scope(get_engine()) as session:
        crud.update_task(session, task_id, TaskUpdate(priority=priority))


def change_task_status(task_id: int, status: TaskStatus) -> None:
    """Persist a new status for a task."""
    with session_scope(get_engine()) as session:
        crud.update_task(session, task_id, TaskUpdate(status=status))
