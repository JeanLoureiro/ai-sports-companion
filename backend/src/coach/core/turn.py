"""One agent turn: run the graph on the athlete's thread and record it in agent_runs."""

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from coach.core.context import CoachContext
from coach.core.graph import CoachGraph
from coach.core.models import AgentRun, Athlete, Location, Trigger
from coach.core.registry import Registry
from coach.core.repo import record_agent_run

# A question left unanswered this long no longer captures the athlete's next message.
STALE_QUESTION = timedelta(hours=6)

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
    location: Location | None = None,
) -> TurnResult:
    """Run one turn on the athlete's single thread; a pending interrupt is resumed by this
    message (text or location pin) and any failure becomes the fallback reply."""
    config: RunnableConfig = {"configurable": {"thread_id": str(ctx.athlete.id)}}
    snapshot = await graph.aget_state(config)
    seen = {m.id for m in snapshot.values.get("messages", [])}
    pending = [i for task in snapshot.tasks for i in task.interrupts]
    asked_at = snapshot.created_at
    stale = asked_at is not None and ctx.now() - datetime.fromisoformat(asked_at) > STALE_QUESTION
    payload: Any
    if pending and not stale:
        answer = {
            "text": text,
            "location": asdict(location) if location else None,
            "asked_at": asked_at,
        }
        # Answer one question at a time; any other open question is asked again next turn.
        payload = Command(resume={pending[0].id: answer})
    else:
        payload = {"messages": [HumanMessage(content=text)]}
    started = time.perf_counter()
    new: list[BaseMessage] = []
    every: list[BaseMessage] = []
    error: str | None = None
    try:
        out = await graph.ainvoke(payload, config, context=ctx)
        every = list(out["messages"])
        new = [m for m in every if m.id not in seen]
        interrupts = out.get("__interrupt__") or []
        reply = _question(interrupts[0].value) if interrupts else _final_reply(new)
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
        tool_calls=_tool_calls(every, new, ctx.registry),
        input_tokens=sum(u["input_tokens"] for u in usages),
        output_tokens=sum(u["output_tokens"] for u in usages),
        error=error,
    )
    async with ctx.pool.connection() as conn:
        run_id = await record_agent_run(conn, run)
    return TurnResult(reply=reply, run_id=run_id, error=error)


def _question(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("question"), str):
        return str(value["question"])
    return str(value)


def _final_reply(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.text.strip():
            return message.text.strip()
    return "Done."


def _tool_calls(
    every: list[BaseMessage], new: list[BaseMessage], registry: Registry
) -> list[dict[str, Any]]:
    """Calls made this turn, plus earlier calls this turn finished (a resumed interrupt)."""
    new_ids = {m.id for m in new}
    results = {m.tool_call_id: m for m in new if isinstance(m, ToolMessage)}
    calls: list[dict[str, Any]] = []
    for message in every:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if message.id not in new_ids and (call["id"] or "") not in results:
                continue
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


async def note_in_thread(graph: CoachGraph, athlete: Athlete, text: str) -> None:
    """Add an assistant note to the athlete's thread, e.g. that a log was undone."""
    config: RunnableConfig = {"configurable": {"thread_id": str(athlete.id)}}
    await graph.aupdate_state(config, {"messages": [AIMessage(content=text)]}, as_node="agent")


async def has_pending_question(graph: CoachGraph, athlete: Athlete) -> bool:
    """Whether the athlete's thread is waiting for an answer to an interrupt."""
    config: RunnableConfig = {"configurable": {"thread_id": str(athlete.id)}}
    snapshot = await graph.aget_state(config)
    return any(task.interrupts for task in snapshot.tasks)
