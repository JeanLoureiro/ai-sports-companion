import json
from datetime import UTC, datetime, timedelta

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.config import Settings
from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph, trim_history
from coach.core.llm import get_chat_model
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_athlete
from tests.factories import insert_session, new_chat_id
from tests.fakes import FakeModule, fake_lookup, scripted

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def context(athlete: Athlete, pool: Pool, registry: Registry | None = None) -> CoachContext:
    return CoachContext(
        athlete=athlete, pool=pool, registry=registry or Registry([]), now=lambda: NOW
    )


def call(name: str, args: dict[str, object], call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


async def test_answers_from_query_history_for_the_context_athlete(
    pool: Pool, athlete: Athlete
) -> None:
    async with pool.connection() as conn:
        other = await create_athlete(conn, name="Other", telegram_chat_id=new_chat_id())
        await insert_session(conn, athlete, started_at=NOW - timedelta(days=1))
        await insert_session(conn, other, started_at=NOW - timedelta(days=1))
    model = scripted(
        call("query_history", {"kind": "per_discipline", "days": 30}), "You trained once."
    )
    graph = build_graph(model, Registry([]))

    out = await graph.ainvoke(
        {"messages": [HumanMessage("how much did I train?")]}, context=context(athlete, pool)
    )

    tool_message = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert json.loads(tool_message.text) == [
        {"discipline": "testsport", "sessions": 1, "minutes": 60}
    ]
    assert out["messages"][-1].text == "You trained once."


async def test_invalid_tool_arguments_come_back_as_a_tool_error(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted(call("query_history", {"kind": "weekly_load", "days": 0}), "Sorry.")
    graph = build_graph(model, Registry([]))

    out = await graph.ainvoke({"messages": [HumanMessage("load?")]}, context=context(athlete, pool))

    tool_message = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert tool_message.status == "error"


async def test_system_prompt_carries_module_prompt_context_and_local_time(
    pool: Pool, athlete: Athlete
) -> None:
    registry = Registry([FakeModule()])
    model = scripted("ok")
    graph = build_graph(model, registry)

    await graph.ainvoke(
        {"messages": [HumanMessage("hi")]}, context=context(athlete, pool, registry)
    )

    system = model.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "FAKE PROMPT" in system.text
    assert "fakesport: fake context line" in system.text
    assert "Test Athlete" in system.text
    assert "Tuesday 2026-10-06 19:00" in system.text  # 09:00 UTC in Brisbane


async def test_thread_history_stays_inside_the_window(pool: Pool, athlete: Athlete) -> None:
    model = scripted(*[f"reply {i}" for i in range(12)])
    graph = build_graph(model, Registry([]), InMemorySaver(), history_messages=6)
    config: RunnableConfig = {"configurable": {"thread_id": "window-test"}}

    for i in range(12):
        await graph.ainvoke(
            {"messages": [HumanMessage(f"message {i}")]}, config, context=context(athlete, pool)
        )

    state = await graph.aget_state(config)
    messages = state.values["messages"]
    assert len(messages) <= 7
    assert isinstance(messages[0], HumanMessage)
    assert len(model.seen[-1]) <= 7  # system prompt + at most 6 history messages


def test_trim_never_starts_on_an_orphaned_tool_result() -> None:
    messages = [
        HumanMessage("a", id="1"),
        call("query_history", {"kind": "weekly_load"}),
        ToolMessage("[]", tool_call_id="call-1", id="3"),
        AIMessage("b", id="4"),
        HumanMessage("c", id="5"),
        AIMessage("d", id="6"),
    ]

    assert trim_history(messages, 4) == messages[4:]


def test_rejects_a_module_tool_that_shadows_a_core_tool() -> None:
    shadow = fake_lookup.model_copy(update={"name": "query_history"})

    with pytest.raises(ValueError, match="query_history"):
        build_graph(scripted("x"), Registry([FakeModule(module_tools=[shadow])]))


def test_chat_model_uses_the_configured_claude_model() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql://x",
            "telegram_bot_token": "t",
            "telegram_webhook_secret": "s",
            "anthropic_api_key": "sk-test",
        }
    )

    model = get_chat_model(settings)

    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-haiku-4-5-20251001"
