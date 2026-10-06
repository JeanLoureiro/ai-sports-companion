"""Application settings loaded from the environment."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TIMEZONE = "Australia/Brisbane"


class Settings(BaseSettings):
    """Runtime configuration. Every variable is prefixed with ``COACH_``."""

    model_config = SettingsConfigDict(env_prefix="COACH_", env_file=".env", extra="ignore")

    database_url: SecretStr
    telegram_bot_token: SecretStr
    telegram_webhook_secret: SecretStr
    telegram_allowed_chat_ids: list[int] = Field(default_factory=list)
    anthropic_api_key: SecretStr
    agent_model: str = "claude-haiku-4-5-20251001"
    history_messages: int = Field(default=30, ge=4)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()
