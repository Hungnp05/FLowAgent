from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ToolErrorMiddleware,
    dynamic_prompt,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy import Engine

from flowagent.agent.prompts import build_system_prompt
from flowagent.agent.tools import (
    ALL_TOOLS,
    DEPS_CONFIG_KEY,
    PriorityPredictorFn,
    ToolDeps,
    format_tool_error,
)
from flowagent.clock import now_local

CONFIRMATION_REQUIRED_MESSAGE = "Bạn có chắc muốn thực hiện thao tác này không?"
MAX_MODEL_CALLS_PER_TURN = 8


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class AgentReply:
    text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    pending_confirmation: dict[str, Any] | None = None
    model_name: str | None = None


def build_agent_graph(
    chat_model: BaseChatModel,
    fallback_models: Sequence[BaseChatModel],
    clock: Callable[[], datetime],
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """Assemble the agent with a dated prompt, model fallback, error handling and a loop guard."""

    @dynamic_prompt
    def dated_system_prompt(request: ModelRequest) -> str:
        """Build the system prompt with the current time for every model call."""
        return build_system_prompt(clock())

    middleware: list[AgentMiddleware] = [
        dated_system_prompt,
        ToolErrorMiddleware(format_tool_error),
        ModelCallLimitMiddleware(run_limit=MAX_MODEL_CALLS_PER_TURN),
    ]
    if fallback_models:
        middleware.append(ModelFallbackMiddleware(*fallback_models))
    return create_agent(chat_model, ALL_TOOLS, middleware=middleware, checkpointer=checkpointer)


def messages_since_last_human(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return the messages produced after the most recent user turn."""
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def find_answering_model(messages: list[AnyMessage]) -> str | None:
    """Return the model name reported by the latest AI message, if the provider sent one."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message.response_metadata.get("model_name")
    return None


def collect_tool_calls(messages: list[AnyMessage]) -> list[ToolCallRecord]:
    """List every tool call the model requested in the given messages."""
    return [
        ToolCallRecord(name=call["name"], args=call["args"])
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


class FlowAgent:
    def __init__(
        self,
        chat_model: BaseChatModel,
        engine: Engine,
        clock: Callable[[], datetime] = now_local,
        checkpointer: BaseCheckpointSaver | None = None,
        fallback_models: Sequence[BaseChatModel] = (),
        predict_priority: PriorityPredictorFn | None = None,
    ) -> None:
        """Wire the agent to a database, clock, conversation store, backup models and ML model."""
        self._deps = ToolDeps(engine=engine, clock=clock, predict_priority=predict_priority)
        self._graph = build_agent_graph(
            chat_model, fallback_models, clock, checkpointer or InMemorySaver()
        )

    def send(self, thread_id: str, user_text: str) -> AgentReply:
        """Send a user message in a conversation thread and return the agent's reply."""
        return self._run({"messages": [HumanMessage(user_text)]}, thread_id)

    def resolve_confirmation(self, thread_id: str, is_approved: bool) -> AgentReply:
        """Resume a paused conversation with the user's answer to a confirmation request."""
        return self._run(Command(resume=is_approved), thread_id)

    def _run_config(self, thread_id: str) -> RunnableConfig:
        """Build the run config carrying the thread id and tool dependencies."""
        return {"configurable": {"thread_id": thread_id, DEPS_CONFIG_KEY: self._deps}}

    def _run(self, graph_input: dict[str, Any] | Command, thread_id: str) -> AgentReply:
        """Invoke the graph and translate its final state into an AgentReply."""
        config = self._run_config(thread_id)
        self._graph.invoke(graph_input, config)
        snapshot = self._graph.get_state(config)
        turn_messages = messages_since_last_human(snapshot.values["messages"])
        tool_calls = collect_tool_calls(turn_messages)
        model_name = find_answering_model(turn_messages)
        if snapshot.interrupts:
            return AgentReply(
                text=CONFIRMATION_REQUIRED_MESSAGE,
                tool_calls=tool_calls,
                pending_confirmation=snapshot.interrupts[0].value,
                model_name=model_name,
            )
        return AgentReply(
            text=turn_messages[-1].text if turn_messages else "",
            tool_calls=tool_calls,
            model_name=model_name,
        )
