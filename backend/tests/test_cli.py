from zoneinfo import ZoneInfoNotFoundError

import pytest

from coach.cli import add_athlete, main
from coach.core.db import Pool
from coach.core.models import Athlete
from coach.core.polling import poll_once
from tests.factories import new_chat_id, new_update_id
from tests.fakes import TelegramRecorder, make_deps, scripted, text_update

pytestmark = pytest.mark.anyio


async def test_add_athlete_is_idempotent(pool: Pool) -> None:
    chat_id = new_chat_id()

    first, created = await add_athlete(
        pool, name="Jean", chat_id=chat_id, timezone="Australia/Brisbane"
    )
    again, created_again = await add_athlete(
        pool, name="Other", chat_id=chat_id, timezone="Australia/Brisbane"
    )

    assert (created, created_again) == (True, False)
    assert again == first


async def test_add_athlete_rejects_an_unknown_time_zone(pool: Pool) -> None:
    with pytest.raises(ZoneInfoNotFoundError):
        await add_athlete(pool, name="Jean", chat_id=new_chat_id(), timezone="Mars/Olympus")


async def test_poll_once_handles_the_batch_and_advances_the_offset(
    pool: Pool, athlete: Athlete
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    first, second = new_update_id(), new_update_id()
    recorder.update_batches.append(
        [
            text_update(first, athlete.telegram_chat_id, "hello"),
            {
                "update_id": second,
                "edited_message": {"message_id": 2, "chat": {"id": athlete.telegram_chat_id}},
            },
        ]
    )
    deps = make_deps(pool, scripted("Hi!"), recorder, allowed=[athlete.telegram_chat_id])

    offset = await poll_once(deps, None, poll_seconds=0)

    assert offset == second + 1
    assert recorder.sent_texts() == ["Hi!"]


async def test_poll_once_keeps_the_offset_when_nothing_arrives(pool: Pool) -> None:
    deps = make_deps(pool, scripted(), TelegramRecorder(), allowed=[])

    assert await poll_once(deps, 42, poll_seconds=0) == 42


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])
