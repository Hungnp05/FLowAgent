from enum import StrEnum

from sqlmodel import Session

from flowagent.db.models import AppSetting


class SettingKey(StrEnum):
    PIN_HASH = "pin_hash"
    PIN_FAILED_ATTEMPTS = "pin_failed_attempts"
    PIN_LOCKED_UNTIL = "pin_locked_until"
    LLM_PROVIDER = "llm_provider"
    GEMINI_API_KEY = "gemini_api_key"
    GEMINI_MODEL = "gemini_model"
    GEMINI_FALLBACK_MODEL = "gemini_fallback_model"
    GROQ_API_KEY = "groq_api_key"
    GROQ_MODEL = "groq_model"
    CHAT_THREAD_ID = "chat_thread_id"


def get_setting(session: Session, key: SettingKey) -> str | None:
    """Return the stored value for a setting, or None when it was never saved."""
    setting = session.get(AppSetting, key.value)
    return setting.value if setting else None


def set_setting(session: Session, key: SettingKey, value: str) -> None:
    """Insert or overwrite a setting value."""
    setting = session.get(AppSetting, key.value) or AppSetting(key=key.value, value=value)
    setting.value = value
    session.add(setting)
    session.flush()


def delete_setting(session: Session, key: SettingKey) -> None:
    """Remove a setting so its default applies again."""
    setting = session.get(AppSetting, key.value)
    if setting is not None:
        session.delete(setting)
        session.flush()
