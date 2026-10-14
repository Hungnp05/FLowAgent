from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import Engine

from flowagent.agent.llm import plan_model_chain
from flowagent.agent.llm_config import LlmConfig, load_llm_config, save_llm_config
from flowagent.config import Settings
from flowagent.db.app_settings import SettingKey, get_setting
from flowagent.db.session import session_scope
from flowagent.errors import MissingApiKeyError
from flowagent.security.secret_box import SecretBox

ENV_SETTINGS = Settings(
    _env_file=None,
    llm_provider="gemini",
    gemini_api_key="env-gemini-key",
    gemini_model="gemini-main",
    gemini_fallback_model="gemini-backup",
    groq_api_key="",
    groq_model="groq-model",
)
BASE_CONFIG = LlmConfig(
    llm_provider="gemini",
    gemini_api_key="gemini-key",
    gemini_model="gemini-main",
    gemini_fallback_model="gemini-backup",
    groq_api_key="groq-key",
    groq_model="groq-model",
)


@pytest.fixture
def box() -> SecretBox:
    """Provide an encryption box with a throwaway key."""
    return SecretBox(Fernet.generate_key())


def test_load_uses_env_values_when_nothing_saved(engine: Engine, box: SecretBox) -> None:
    """Without saved settings the .env values are used."""
    with session_scope(engine) as session:
        config = load_llm_config(session, ENV_SETTINGS, box)
    assert config.gemini_api_key == "env-gemini-key"
    assert config.gemini_model == "gemini-main"


def test_saved_keys_are_encrypted_and_override_env(engine: Engine, box: SecretBox) -> None:
    """Saved keys are stored encrypted and take priority over .env."""
    with session_scope(engine) as session:
        save_llm_config(session, replace(BASE_CONFIG, gemini_api_key="app-key"), box)
    with session_scope(engine) as session:
        stored = get_setting(session, SettingKey.GEMINI_API_KEY)
        config = load_llm_config(session, ENV_SETTINGS, box)
    assert stored != "app-key"
    assert config.gemini_api_key == "app-key"


def test_blank_key_falls_back_to_env(engine: Engine, box: SecretBox) -> None:
    """Saving an empty key removes it so the .env key applies again."""
    with session_scope(engine) as session:
        save_llm_config(session, replace(BASE_CONFIG, gemini_api_key="app-key"), box)
        save_llm_config(session, replace(BASE_CONFIG, gemini_api_key=""), box)
    with session_scope(engine) as session:
        assert load_llm_config(session, ENV_SETTINGS, box).gemini_api_key == "env-gemini-key"


def test_config_repr_hides_api_keys() -> None:
    """API keys never appear in the config's repr, so they cannot leak into logs."""
    assert "gemini-key" not in repr(BASE_CONFIG)


def test_model_chain_puts_primary_provider_first() -> None:
    """Gemini primary is followed by its fallback model and then Groq."""
    labels = [spec.label for spec in plan_model_chain(BASE_CONFIG)]
    assert labels == ["gemini / gemini-main", "gemini / gemini-backup", "groq / groq-model"]


def test_model_chain_with_groq_primary() -> None:
    """Choosing Groq as primary moves it to the front."""
    chain = plan_model_chain(replace(BASE_CONFIG, llm_provider="groq"))
    assert chain[0].label == "groq / groq-model"


def test_model_chain_skips_providers_without_keys() -> None:
    """Providers without a key are left out of the chain."""
    chain = plan_model_chain(replace(BASE_CONFIG, groq_api_key=""))
    assert all(spec.provider == "gemini" for spec in chain)


def test_model_chain_without_any_key_raises() -> None:
    """With no keys at all the user is told to add one."""
    with pytest.raises(MissingApiKeyError):
        plan_model_chain(replace(BASE_CONFIG, gemini_api_key="", groq_api_key=""))
