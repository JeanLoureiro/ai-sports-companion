import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from coach.core.db import Pool
from coach.core.deps import Deps
from coach.core.models import Athlete
from coach.main import create_app
from tests.factories import new_update_id
from tests.fakes import WEBHOOK_SECRET, TelegramRecorder, make_deps, scripted, text_update

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def serve(deps: Deps) -> AsyncIterator[httpx.AsyncClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Deps]:
        yield deps

    app = create_app(factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


def headers(secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    return {"X-Telegram-Bot-Api-Secret-Token": secret}


async def test_health(pool: Pool) -> None:
    async with serve(make_deps(pool, scripted(), TelegramRecorder(), allowed=[])) as client:
        response = await client.get("/health")

    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("sent", [None, "wrong-secret"])
async def test_rejects_a_missing_or_wrong_secret(pool: Pool, sent: str | None) -> None:
    deps = make_deps(pool, scripted(), TelegramRecorder(), allowed=[])
    async with serve(deps) as client:
        response = await client.post(
            "/telegram", json=text_update(new_update_id(), 1), headers=headers(sent) if sent else {}
        )

    assert response.status_code == 401


async def test_rejects_a_malformed_update(pool: Pool) -> None:
    async with serve(make_deps(pool, scripted(), TelegramRecorder(), allowed=[])) as client:
        response = await client.post("/telegram", json={"nope": 1}, headers=headers())

    assert response.status_code == 422


async def test_replies_and_deduplicates_retried_deliveries(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(
        pool, scripted("Hi Jean.", "again?"), recorder, allowed=[athlete.telegram_chat_id]
    )
    update = text_update(new_update_id(), athlete.telegram_chat_id)

    async with serve(deps) as client:
        first = await client.post("/telegram", json=update, headers=headers())
        retry = await client.post("/telegram", json=update, headers=headers())

    assert (first.status_code, retry.status_code) == (200, 200)
    assert recorder.sent_texts() == ["Hi Jean."]


async def test_a_failing_update_still_returns_200_and_is_logged(
    pool: Pool, athlete: Athlete, caplog: pytest.LogCaptureFixture
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder(fail_on="sendMessage")
    deps = make_deps(pool, scripted("unsendable"), recorder, allowed=[athlete.telegram_chat_id])
    update_id = new_update_id()

    with caplog.at_level(logging.ERROR):
        async with serve(deps) as client:
            response = await client.post(
                "/telegram",
                json=text_update(update_id, athlete.telegram_chat_id),
                headers=headers(),
            )

    assert response.status_code == 200
    assert f"update {update_id} failed" in caplog.text
