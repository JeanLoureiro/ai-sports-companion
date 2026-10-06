import pytest

from coach.core.config import Settings
from coach.core.db import Pool
from coach.core.deps import build_deps
from coach.core.handler import UNSUPPORTED_REPLY, handle_update
from coach.core.models import Athlete
from coach.core.telegram import TelegramClient, TelegramError, Update, split_message
from tests.conftest import TEST_DATABASE_URL
from tests.factories import new_chat_id, new_update_id
from tests.fakes import TEST_TOKEN, TelegramRecorder, make_deps, scripted, text_update

pytestmark = pytest.mark.anyio


def test_split_message_keeps_every_chunk_under_the_limit() -> None:
    text = "x" * 10_000

    chunks = split_message(text)

    assert [len(c) for c in chunks] == [4096, 4096, 1808]
    assert "".join(chunks) == text


def test_split_message_prefers_line_breaks() -> None:
    text = "a" * 3000 + "\n" + "b" * 3000

    assert split_message(text) == ["a" * 3000, "b" * 3000]


async def test_api_errors_raise_without_leaking_the_token() -> None:
    recorder = TelegramRecorder(fail_on="sendMessage")

    with pytest.raises(TelegramError) as raised:
        await recorder.client().send_message(1, "hi")

    assert TEST_TOKEN not in str(raised.value)


async def test_get_updates_omits_a_missing_offset() -> None:
    recorder = TelegramRecorder()

    await recorder.client().get_updates(None)

    assert "offset" not in recorder.calls[0][1]


async def test_replies_to_an_allowlisted_athlete(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("Hey!"), recorder, allowed=[athlete.telegram_chat_id])

    update = Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))
    await handle_update(deps, update)

    assert recorder.methods() == ["sendChatAction", "sendMessage"]
    assert recorder.sent_texts() == ["Hey!"]


async def test_ignores_chats_outside_the_allowlist(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("never")
    deps = make_deps(pool, model, recorder, allowed=[])
    update_id = new_update_id()

    await handle_update(
        deps, Update.model_validate(text_update(update_id, athlete.telegram_chat_id))
    )

    assert recorder.calls == []
    assert model.seen == []
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select 1 from processed_updates where update_id = %s", (update_id,)
        )
        assert await cur.fetchone() is None


async def test_handles_a_repeated_update_once(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("Once.", "Twice?")
    deps = make_deps(pool, model, recorder, allowed=[athlete.telegram_chat_id])
    update = Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))

    await handle_update(deps, update)
    await handle_update(deps, update)

    assert recorder.sent_texts() == ["Once."]
    assert len(model.seen) == 1


async def test_text_less_messages_get_a_short_explanation(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("never")
    deps = make_deps(pool, model, recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps,
        Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id, text=None)),
    )

    assert recorder.sent_texts() == [UNSUPPORTED_REPLY]
    assert model.seen == []


async def test_non_message_updates_are_ignored(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("never"), recorder, allowed=[athlete.telegram_chat_id])
    edited = {
        "update_id": new_update_id(),
        "edited_message": {
            "message_id": 1,
            "chat": {"id": athlete.telegram_chat_id},
            "text": "edit",
        },
    }

    await handle_update(deps, Update.model_validate(edited))

    assert recorder.calls == []


async def test_allowlisted_chat_without_an_athlete_gets_nothing(pool: Pool) -> None:
    chat_id = new_chat_id()
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("never"), recorder, allowed=[chat_id])

    await handle_update(deps, Update.model_validate(text_update(new_update_id(), chat_id)))

    assert recorder.calls == []


async def test_long_replies_are_split(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("y" * 5000), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps, Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))
    )

    assert [len(t) for t in recorder.sent_texts()] == [4096, 904]


async def test_build_deps_wires_the_real_stack_without_network_calls() -> None:
    settings = Settings.model_validate(
        {
            "database_url": TEST_DATABASE_URL,
            "telegram_bot_token": TEST_TOKEN,
            "telegram_webhook_secret": "s",
            "anthropic_api_key": "sk-test",
        }
    )

    async with build_deps(settings) as deps:
        assert [m.name for m in deps.registry.modules] == ["gym"]
        assert isinstance(deps.telegram, TelegramClient)
        assert deps.graph.checkpointer is not None


async def test_a_failed_typing_indicator_does_not_cost_the_reply(
    pool: Pool, athlete: Athlete
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder(fail_on="sendChatAction")
    deps = make_deps(pool, scripted("Still here."), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps, Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))
    )

    assert recorder.sent_texts() == ["Still here."]


async def test_webhook_delivers_one_update_at_a_time() -> None:
    # Concurrent turns on the one thread would make the coach forget a message.
    recorder = TelegramRecorder()

    await recorder.client().set_webhook("https://coach.example/telegram", "s3cret")

    [(method, payload)] = recorder.calls
    assert method == "setWebhook"
    assert payload["max_connections"] == 1
    assert payload["secret_token"] == "s3cret"
