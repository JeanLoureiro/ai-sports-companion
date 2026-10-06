from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from coach.core.db import Pool
from coach.core.handler import NOTHING_TO_UNDO, handle_update
from coach.core.models import Athlete, ReplyButton
from coach.core.registry import Registry
from coach.core.repo import create_athlete, create_session
from coach.core.telegram import ALLOWED_UPDATES, Update
from tests.factories import new_chat_id, new_update_id
from tests.fakes import (
    FakeModule,
    TelegramRecorder,
    button_tool,
    callback_update,
    make_deps,
    scripted,
    text_update,
)

pytestmark = pytest.mark.anyio

STARTED = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)


async def a_logged_session(pool: Pool, athlete: Athlete) -> str:
    async with pool.connection() as conn:
        session_id = await create_session(
            conn, athlete, discipline="testsport", started_at=STARTED, summary="Test session"
        )
    return str(session_id)


async def session_exists(pool: Pool, session_id: str) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute("select 1 from sessions where id = %s", (session_id,))
        return await cur.fetchone() is not None


def answers(recorder: TelegramRecorder) -> list[str]:
    return [str(p["text"]) for m, p in recorder.calls if m == "answerCallbackQuery"]


def test_both_update_types_are_requested() -> None:
    assert ALLOWED_UPDATES == ["message", "callback_query"]


async def test_buttons_go_on_the_last_chunk_only() -> None:
    recorder = TelegramRecorder()

    await recorder.client().send_message(1, "x" * 5000, [ReplyButton("Undo", "undo:1")])

    payloads = [p for m, p in recorder.calls if m == "sendMessage"]
    assert "reply_markup" not in payloads[0]
    assert payloads[1]["reply_markup"] == {
        "inline_keyboard": [[{"text": "Undo", "callback_data": "undo:1"}]]
    }


async def test_a_tool_can_put_a_button_under_the_reply(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[{"name": "button_tool", "args": {"label": "Undo"}, "id": "b1"}],
        ),
        "Logged.",
    )
    deps = make_deps(
        pool,
        model,
        recorder,
        allowed=[athlete.telegram_chat_id],
        registry=Registry([FakeModule(module_tools=[button_tool])]),
    )

    await handle_update(
        deps, Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))
    )

    [reply] = [p for m, p in recorder.calls if m == "sendMessage"]
    assert reply["text"] == "Logged."
    assert reply["reply_markup"]["inline_keyboard"][0][0]["text"] == "Undo"


async def test_undo_deletes_the_session_and_tells_the_thread(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    session_id = await a_logged_session(pool, athlete)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps,
        Update.model_validate(
            callback_update(new_update_id(), athlete.telegram_chat_id, f"undo:{session_id}")
        ),
    )

    assert not await session_exists(pool, session_id)
    assert answers(recorder) == ["Undone."]
    assert recorder.sent_texts() == ["Undone: Test session."]
    config: RunnableConfig = {"configurable": {"thread_id": str(athlete.id)}}
    state = await deps.graph.aget_state(config)
    assert state.values["messages"][-1].text == "Undone: Test session."


async def test_undo_twice_only_deletes_once(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    session_id = await a_logged_session(pool, athlete)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    for _ in range(2):
        await handle_update(
            deps,
            Update.model_validate(
                callback_update(new_update_id(), athlete.telegram_chat_id, f"undo:{session_id}")
            ),
        )

    assert answers(recorder) == ["Undone.", NOTHING_TO_UNDO]


@pytest.mark.parametrize("data", ["undo:not-a-uuid", "something-else"])
async def test_garbage_callback_data_undoes_nothing(
    pool: Pool, athlete: Athlete, data: str
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps,
        Update.model_validate(callback_update(new_update_id(), athlete.telegram_chat_id, data)),
    )

    assert answers(recorder) == [NOTHING_TO_UNDO]
    assert recorder.sent_texts() == []


async def test_cannot_undo_someone_elses_session(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    async with pool.connection() as conn:
        other = await create_athlete(conn, name="Other", telegram_chat_id=new_chat_id())
    session_id = await a_logged_session(pool, other)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps,
        Update.model_validate(
            callback_update(new_update_id(), athlete.telegram_chat_id, f"undo:{session_id}")
        ),
    )

    assert await session_exists(pool, session_id)
    assert answers(recorder) == [NOTHING_TO_UNDO]


async def test_callbacks_from_other_chats_are_ignored(pool: Pool, athlete: Athlete) -> None:
    session_id = await a_logged_session(pool, athlete)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[])

    await handle_update(
        deps,
        Update.model_validate(
            callback_update(new_update_id(), new_chat_id(), f"undo:{session_id}")
        ),
    )

    assert recorder.calls == []
    assert await session_exists(pool, session_id)
