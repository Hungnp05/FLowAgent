from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import Engine

from flowagent.agent.llm import build_chat_model, plan_model_chain
from flowagent.agent.llm_config import LlmConfig
from flowagent.agent.service import FlowAgent
from flowagent.agent.tools import PriorityPredictorFn
from flowagent.config import Settings


def create_flow_agent(
    config: LlmConfig,
    settings: Settings,
    engine: Engine,
    checkpointer: BaseCheckpointSaver,
    predict_priority: PriorityPredictorFn | None = None,
) -> FlowAgent:
    """Build an agent whose first usable model is primary and the rest are automatic fallbacks."""
    primary_model, *fallback_models = [
        build_chat_model(spec, settings) for spec in plan_model_chain(config)
    ]
    return FlowAgent(
        primary_model,
        engine,
        checkpointer=checkpointer,
        fallback_models=fallback_models,
        predict_priority=predict_priority,
    )
