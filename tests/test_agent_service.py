from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import Engine

from flowagent.agent.service import FlowAgent
from flowagent.db import crud
from flowagent.db.schemas import TaskCreate
from flowagent.db.session import session_scope
from flowagent.errors import TaskNotFoundError
from tests.conftest import fixed_clock

THREAD_ID = "test-thread"


class ScriptedChatModel(GenericFakeChatModel):
    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        """Ignore tool binding because replies are scripted in advance."""
        return self


def tool_call_message(name: str, args: dict[str, Any]) -> AIMessage:
    """Build a model reply that requests a single tool call."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


def make_agent(engine: Engine, replies: list[AIMessage]) -> FlowAgent:
    """Create a FlowAgent whose model plays back the given replies in order."""
    return FlowAgent(ScriptedChatModel(messages=iter(replies)), engine, clock=fixed_clock)


def test_send_runs_tool_and_returns_final_text(engine: Engine) -> None:
    """A tool-calling turn executes the tool and returns the model's closing message."""
    agent = make_agent(
        engine,
        [tool_call_message("create_task", {"title": "Đi chợ"}), AIMessage("Đã thêm việc đi chợ.")],
    )
    reply = agent.send(THREAD_ID, "Thêm việc đi chợ")
    assert reply.text == "Đã thêm việc đi chợ."
    assert [call.name for call in reply.tool_calls] == ["create_task"]
    with session_scope(engine) as session:
        assert crud.list_tasks(session)[0].title == "Đi chợ"


def test_tool_error_is_returned_to_model_instead_of_crashing(engine: Engine) -> None:
    """A domain error inside a tool becomes a tool message and the turn still completes."""
    agent = make_agent(
        engine,
        [tool_call_message("update_task", {"task_id": 42}), AIMessage("Không tìm thấy việc #42.")],
    )
    assert agent.send(THREAD_ID, "Sửa việc 42").text == "Không tìm thấy việc #42."


@pytest.mark.parametrize(("is_approved", "should_exist"), [(True, False), (False, True)])
def test_delete_waits_for_confirmation(
    engine: Engine, is_approved: bool, should_exist: bool
) -> None:
    """Deleting pauses for confirmation and only removes the task when approved."""
    with session_scope(engine) as session:
        task_id = crud.create_task(session, TaskCreate(title="Việc cũ")).id
    agent = make_agent(
        engine, [tool_call_message("delete_task", {"task_id": task_id}), AIMessage("Xong.")]
    )
    paused = agent.send(THREAD_ID, "Xoá việc cũ")
    assert paused.pending_confirmation["task_id"] == task_id
    assert agent.resolve_confirmation(THREAD_ID, is_approved).pending_confirmation is None
    with session_scope(engine) as session:
        if should_exist:
            assert crud.get_task(session, task_id)
        else:
            with pytest.raises(TaskNotFoundError):
                crud.get_task(session, task_id)


class FailingChatModel(ScriptedChatModel):
    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        """Simulate a provider outage on every call."""
        raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand")


def test_fallback_model_answers_when_primary_fails(engine: Engine) -> None:
    """When the primary model errors, the backup model answers and is reported in the reply."""
    backup_reply = AIMessage("Xin chào!", response_metadata={"model_name": "backup-model"})
    agent = FlowAgent(
        FailingChatModel(messages=iter([])),
        engine,
        clock=fixed_clock,
        fallback_models=[ScriptedChatModel(messages=iter([backup_reply]))],
    )
    reply = agent.send(THREAD_ID, "Chào")
    assert reply.text == "Xin chào!"
    assert reply.model_name == "backup-model"
