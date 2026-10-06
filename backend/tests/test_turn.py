from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import CoachGraph, build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.turn import FALLBACK_REPLY, run_turn
from tests.factories import insert_session
from tests.fakes import BrokenChatModel, ExplodingChatModel, FakeChatModel, FakeModule, scripted

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


@tool
async def crashing_tool(query: str) -> str:
    """Always fails, like a database blip."""
    raise RuntimeError("database blip")


def assert_every_tool_call_is_answered(messages: list[BaseMessage]) -> None:
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                assert call["id"] in answered, f"tool call {call['id']} has no result"


async def test_a_crashing_tool_does_not_break_the_thread(pool: Pool, athlete: Athlete) -> None:
    registry = Registry([FakeModule(module_tools=[crashing_tool])])
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[{"name": "crashing_tool", "args": {"query": "x"}, "id": "t1"}],
        ),
        "Sorry, that failed.",
        "Next reply.",
    )
    graph = build_graph(model, registry, AsyncPostgresSaver(pool))
    turn_ctx = CoachContext(athlete=athlete, pool=pool, registry=registry, now=lambda: NOW)

    first = await run_turn(graph, turn_ctx, "log my session", model_name="m")
    second = await run_turn(graph, turn_ctx, "next msg", model_name="m")

    assert (first.reply, second.reply) == ("Sorry, that failed.", "Next reply.")
    assert_every_tool_call_is_answered(model.seen[-1])


async def test_a_turn_killed_mid_tool_call_does_not_break_the_next_one(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted("Back on track.")
    graph = build_graph(model, Registry([]), InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": str(athlete.id)}}
    # The function died after the model asked for a tool and before the tool ran.
    await graph.aupdate_state(
        config,
        {
            "messages": [
                HumanMessage("how much this week?"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "query_history", "args": {"kind": "weekly_load"}, "id": "k1"}
                    ],
                ),
            ]
        },
        as_node="agent",
    )

    result = await run_turn(graph, ctx(athlete, pool), "hello?", model_name="m")

    assert result.reply == "Back on track."
    assert_every_tool_call_is_answered(model.seen[0])


async def test_any_other_failure_still_gets_the_fallback_and_a_record(
    pool: Pool, athlete: Athlete
) -> None:
    graph = graph_for(BrokenChatModel(messages=iter([])), pool)

    result = await run_turn(graph, ctx(athlete, pool), "hello", model_name="m")

    assert result.reply == FALLBACK_REPLY
    assert result.error == "RuntimeError: boom"
