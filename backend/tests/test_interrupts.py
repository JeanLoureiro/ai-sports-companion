import json
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.handler import handle_update
from coach.core.models import Athlete, Location
from coach.core.registry import Registry
from coach.core.telegram import Update
from coach.core.text import make_canonicalizer, normalize
from coach.core.turn import run_turn
from tests.factories import new_update_id
from tests.fakes import (
    FakeModule,
    TelegramRecorder,
    ask_tool,
    location_update,
    make_deps,
    scripted,
)

pytestmark = pytest.mark.anyio

ASK = Registry([FakeModule(module_tools=[ask_tool], context_text="")])


def ask(question: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "ask_tool", "args": {"question": question}, "id": "a1"}]
    )


def test_normalize_lives_in_core() -> None:
    assert normalize("D'Bah ") == "d bah"


def test_canonicalizer_uses_the_first_resolver_that_knows_the_name() -> None:
    canonical = make_canonicalizer([lambda s: "Duranbah" if normalize(s) == "dbah" else None])

    assert canonical("dbah") == "duranbah"
    assert canonical("Burleigh") == "burleigh"


async def test_an_interrupt_question_is_the_reply_and_the_next_message_answers_it(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted(ask("Where was that?"), "Logged at Burleigh.")
    graph = build_graph(model, ASK, InMemorySaver())
    ctx = CoachContext(athlete=athlete, pool=pool, registry=ASK)

    first = await run_turn(graph, ctx, "surfed this morning", model_name="m")
    second = await run_turn(graph, ctx, "Burleigh", model_name="m")

    assert first.reply == "Where was that?"
    assert second.reply == "Logged at Burleigh."
    tool_result = next(m for m in model.seen[-1] if isinstance(m, ToolMessage))
    answer = json.loads(tool_result.text.removeprefix("answer: "))
    assert (answer["text"], answer["location"]) == ("Burleigh", None)
    assert answer["asked_at"]  # when the question was asked, so logs keep that time


async def test_a_location_pin_answers_a_pending_question(pool: Pool, athlete: Athlete) -> None:
    model = scripted(ask("Send me a pin"), "Saved.")
    graph = build_graph(model, ASK, InMemorySaver())
    ctx = CoachContext(athlete=athlete, pool=pool, registry=ASK)

    await run_turn(graph, ctx, "surfed at the secret spot", model_name="m")
    await run_turn(
        graph, ctx, "(shared a location)", model_name="m", location=Location(-28.1, 153.5)
    )

    tool_result = next(m for m in model.seen[-1] if isinstance(m, ToolMessage))
    assert json.loads(tool_result.text.removeprefix("answer: "))["location"] == {
        "latitude": -28.1,
        "longitude": 153.5,
    }


async def test_a_location_without_a_question_is_an_ordinary_message(
    pool: Pool, athlete: Athlete
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("Nice spot.")
    deps = make_deps(pool, model, recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps,
        Update.model_validate(
            location_update(new_update_id(), athlete.telegram_chat_id, -28.1, 153.5)
        ),
    )

    assert recorder.sent_texts() == ["Nice spot."]
    assert model.seen[0][-1].text == "(shared a location)"


async def test_a_stale_question_does_not_capture_a_new_message(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted(ask("Where was that?"), "Here is your week.")
    graph = build_graph(model, ASK, InMemorySaver())
    asked = CoachContext(athlete=athlete, pool=pool, registry=ASK)
    later = CoachContext(
        athlete=athlete,
        pool=pool,
        registry=ASK,
        now=lambda: datetime.now(UTC) + timedelta(hours=7),
    )

    await run_turn(graph, asked, "surfed this morning", model_name="m")
    result = await run_turn(graph, later, "how much did I train this week?", model_name="m")

    assert result.reply == "Here is your week."
    last_prompt = model.seen[-1]
    assert isinstance(last_prompt[-1], HumanMessage)
    assert last_prompt[-1].text == "how much did I train this week?"


async def test_the_resumed_turn_records_the_tool_call_it_completed(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted(ask("Where was that?"), "Logged.")
    graph = build_graph(model, ASK, InMemorySaver())
    ctx = CoachContext(athlete=athlete, pool=pool, registry=ASK)

    await run_turn(graph, ctx, "surfed", model_name="m")
    resumed = await run_turn(graph, ctx, "Burleigh", model_name="m")

    async with pool.connection() as conn:
        cur = await conn.execute(
            "select tool_calls from agent_runs where id = %s", (resumed.run_id,)
        )
        row = await cur.fetchone()
    assert row is not None
    [call] = row["tool_calls"]
    assert (call["tool"], call["status"]) == ("ask_tool", "success")
