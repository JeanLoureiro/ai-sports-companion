from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import CoachGraph, build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.turn import FALLBACK_REPLY, run_turn
from tests.factories import insert_session
from tests.fakes import ExplodingChatModel, FakeChatModel, scripted

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def usage(input_tokens: int, output_tokens: int) -> UsageMetadata:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def ctx(athlete: Athlete, pool: Pool) -> CoachContext:
    return CoachContext(athlete=athlete, pool=pool, registry=Registry([]), now=lambda: NOW)


def graph_for(model: FakeChatModel, pool: Pool) -> CoachGraph:
    return build_graph(model, Registry([]), AsyncPostgresSaver(pool))


async def test_records_the_turn_with_tool_calls_and_tokens(pool: Pool, athlete: Athlete) -> None:
    async with pool.connection() as conn:
        await insert_session(conn, athlete, started_at=NOW - timedelta(days=2))
    model = scripted(
        AIMessage(
            content="",
            usage_metadata=usage(100, 10),
            tool_calls=[{"name": "query_history", "args": {"kind": "weekly_load"}, "id": "c1"}],
        ),
        AIMessage(content="One session this week.", usage_metadata=usage(150, 20)),
    )

    result = await run_turn(
        graph_for(model, pool), ctx(athlete, pool), "this week?", model_name="test-model"
    )

    assert result.reply == "One session this week."
    assert result.error is None
    async with pool.connection() as conn:
        cur = await conn.execute("select * from agent_runs where id = %s", (result.run_id,))
        row = await cur.fetchone()
    assert row is not None
    assert row["trigger"] == "message"
    assert row["model"] == "test-model"
    assert (row["input_tokens"], row["output_tokens"]) == (250, 30)
    [tool_call] = row["tool_calls"]
    assert (tool_call["tool"], tool_call["module"], tool_call["status"]) == (
        "query_history",
        "core",
        "success",
    )
    assert "2026-" in tool_call["result_summary"]


async def test_the_thread_remembers_the_previous_turn(pool: Pool, athlete: Athlete) -> None:
    model = scripted("Nice.", "You said you surfed.")
    graph = graph_for(model, pool)

    await run_turn(graph, ctx(athlete, pool), "I surfed this morning", model_name="m")
    await run_turn(graph, ctx(athlete, pool), "what did I say?", model_name="m")

    second_prompt = " ".join(m.text for m in model.seen[1])
    assert "I surfed this morning" in second_prompt


async def test_model_failure_returns_the_fallback_and_records_the_error(
    pool: Pool, athlete: Athlete
) -> None:
    graph = graph_for(ExplodingChatModel(messages=iter([])), pool)

    result = await run_turn(graph, ctx(athlete, pool), "hello", model_name="m")

    assert result.reply == FALLBACK_REPLY
    assert result.error is not None and result.error.startswith("APIConnectionError")
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select error, output from agent_runs where id = %s", (result.run_id,)
        )
        row = await cur.fetchone()
    assert row is not None
    assert row["error"].startswith("APIConnectionError")
    assert row["output"] == FALLBACK_REPLY
