from dataclasses import dataclass, field, fields

from sqlmodel import Session

from flowagent.config import LlmProvider, Settings
from flowagent.db.app_settings import SettingKey, delete_setting, get_setting, set_setting
from flowagent.security.secret_box import SecretBox

SECRET_KEYS = frozenset({SettingKey.GEMINI_API_KEY, SettingKey.GROQ_API_KEY})


@dataclass(frozen=True)
class LlmConfig:
    llm_provider: LlmProvider
    gemini_api_key: str = field(repr=False)
    gemini_model: str
    gemini_fallback_model: str
    groq_api_key: str = field(repr=False)
    groq_model: str


def read_stored_value(session: Session, key: SettingKey, box: SecretBox) -> str | None:
    """Read one saved setting, decrypting it when it is a secret."""
    stored = get_setting(session, key)
    if stored is None or key not in SECRET_KEYS:
        return stored
    return box.decrypt(stored)


def load_llm_config(session: Session, settings: Settings, box: SecretBox) -> LlmConfig:
    """Merge values saved in the app over the .env defaults."""
    values = {
        config_field.name: read_stored_value(session, SettingKey(config_field.name), box)
        or getattr(settings, config_field.name)
        for config_field in fields(LlmConfig)
    }
    return LlmConfig(**values)


def save_llm_config(session: Session, config: LlmConfig, box: SecretBox) -> None:
    """Persist every field, encrypting secrets and clearing blanks so .env applies again."""
    for config_field in fields(LlmConfig):
        key = SettingKey(config_field.name)
        value = getattr(config, config_field.name).strip()
        if not value:
            delete_setting(session, key)
            continue
        set_setting(session, key, box.encrypt(value) if key in SECRET_KEYS else value)


def is_saved_in_app(session: Session, key: SettingKey) -> bool:
    """Report whether a setting comes from the app rather than from .env."""
    return get_setting(session, key) is not None


def build_visitor_llm_config(
    settings: Settings, provider: LlmProvider, gemini_api_key: str, groq_api_key: str
) -> LlmConfig:
    """Combine a visitor's own API keys with the default model names, ignoring server keys."""
    return LlmConfig(
        llm_provider=provider,
        gemini_api_key=gemini_api_key.strip(),
        gemini_model=settings.gemini_model,
        gemini_fallback_model=settings.gemini_fallback_model,
        groq_api_key=groq_api_key.strip(),
        groq_model=settings.groq_model,
    )
