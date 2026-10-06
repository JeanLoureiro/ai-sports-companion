"""One agent turn: run the graph on the athlete's thread and record it in agent_runs."""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from coach.core.context import CoachContext
from coach.core.graph import CoachGraph
from coach.core.models import AgentRun, Trigger
from coach.core.registry import Registry
from coach.core.repo import record_agent_run

FALLBACK_REPLY = (
    "Sorry, I couldn't reach the coach model just now. Your message arrived; try again in a minute."
)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What to send back, and where the turn was recorded."""

    reply: str
    run_id: UUID
    error: str | None


async def run_turn(
    graph: CoachGraph,
    ctx: CoachContext,
    text: str,
    *,
    model_name: str,
    trigger: Trigger = "message",
) -> TurnResult:
    """Run one turn on the athlete's single thread; any failure becomes the fallback reply."""
    config: RunnableConfig = {"configurable": {"thread_id": str(ctx.athlete.id)}}
    snapshot = await graph.aget_state(config)
    seen = {m.id for m in snapshot.values.get("messages", [])}
    started = time.perf_counter()
    new: list[BaseMessage] = []
    error: str | None = None
    try:
        out = await graph.ainvoke({"messages": [HumanMessage(content=text)]}, config, context=ctx)
        new = [m for m in out["messages"] if m.id not in seen]
        reply = _final_reply(new)
    except Exception as err:  # noqa: BLE001 - the athlete always gets an answer and a record
        error = f"{type(err).__name__}: {err}"
        reply = FALLBACK_REPLY
    usages = [m.usage_metadata for m in new if isinstance(m, AIMessage) and m.usage_metadata]
    run = AgentRun(
        athlete_id=ctx.athlete.id,
        trigger=trigger,
        input=text,
        output=reply,
        model=model_name,
        latency_ms=round((time.perf_counter() - started) * 1000),
        tool_calls=_tool_calls(new, ctx.registry),
        input_tokens=sum(u["input_tokens"] for u in usages),
        output_tokens=sum(u["output_tokens"] for u in usages),
        error=error,
    )
    async with ctx.pool.connection() as conn:
        run_id = await record_agent_run(conn, run)
    return TurnResult(reply=reply, run_id=run_id, error=error)


def _final_reply(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.text.strip():
            return message.text.strip()
    return "Done."


def _tool_calls(messages: list[BaseMessage], registry: Registry) -> list[dict[str, Any]]:
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            result = results.get(call["id"] or "")
            calls.append(
                {
                    "tool": call["name"],
                    "module": registry.tool_owner(call["name"]),
                    "args": call["args"],
                    "status": result.status if result else "missing",
                    "result_summary": result.text[:500] if result else "",
                }
            )
    return calls
