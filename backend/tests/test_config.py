import pytest
from pydantic import ValidationError

from coach.core.config import Settings

ENV = {
    "COACH_DATABASE_URL": "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    "COACH_TELEGRAM_BOT_TOKEN": "123:abc",
    "COACH_TELEGRAM_WEBHOOK_SECRET": "s3cret-hook",
    "COACH_TELEGRAM_ALLOWED_CHAT_IDS": "[111, 222]",
    "COACH_ANTHROPIC_API_KEY": "sk-ant-s3cret",
}


def test_reads_prefixed_env_and_parses_chat_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.telegram_allowed_chat_ids == [111, 222]
    assert settings.agent_model == "claude-haiku-4-5-20251001"
    assert settings.history_messages == 30
    assert settings.database_url.get_secret_value().startswith("postgresql://")


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert "s3cret" not in repr(settings)


def test_missing_required_value_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
