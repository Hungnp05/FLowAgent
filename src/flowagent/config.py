from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["gemini", "groq"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: LlmProvider = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_fallback_model: str = "gemini-3.5-flash-lite"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = 0.0
    llm_max_retries: int = 1
    llm_timeout_seconds: float = 60.0
    database_url: str = "sqlite:///data/flowagent.db"
    secret_key_path: str = "data/secret.key"
    chat_history_path: str = "data/chat_history.db"
    public_mode: bool = False
    priority_model_path: str = "models/priority_classifier.joblib"
    timezone: str = "Asia/Ho_Chi_Minh"


@lru_cache
def get_settings() -> Settings:
    """Load settings from environment variables and .env once per process."""
    return Settings()
