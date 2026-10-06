"""The LangGraph agent: load_context -> agent <-> tools."""

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, RemoveMessage, SystemMessage, trim_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime

from coach.core.context import CoachContext
from coach.core.prompt import system_prompt
from coach.core.registry import Registry
from coach.core.tools import CORE_TOOLS

type CoachGraph = CompiledStateGraph[Any, Any, Any, Any]


class CoachState(MessagesState):
    """Conversation messages plus the module context loaded at the start of the turn."""

    context: str


def trim_history(messages: Sequence[BaseMessage], max_messages: int) -> list[BaseMessage]:
    """Keep the newest messages, starting on a human turn so tool calls keep their results."""
    return trim_messages(
        messages, max_tokens=max_messages, token_counter=len, strategy="last", start_on="human"
    )


def build_graph(
    model: BaseChatModel,
    registry: Registry,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    history_messages: int = 30,
) -> CoachGraph:
    """Bind core and module tools to the model and wire the agent loop."""
    tools = [*CORE_TOOLS, *registry.tools()]
    names = [t.name for t in tools]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"tool names used twice: {duplicates}")
    bound = model.bind_tools(tools)

    async def load_context(state: CoachState, runtime: Runtime[CoachContext]) -> dict[str, Any]:
        ctx = runtime.context
        async with ctx.pool.connection() as conn:
            return {"context": await ctx.registry.context(conn, ctx.athlete)}

    async def agent(state: CoachState, runtime: Runtime[CoachContext]) -> dict[str, Any]:
        ctx = runtime.context
        history = trim_history(state["messages"], history_messages)
        system = SystemMessage(
            system_prompt(ctx.athlete, ctx.registry, state.get("context", ""), ctx.now())
        )
        reply = await bound.ainvoke([system, *history])
        # Drop what fell out of the window so the checkpointed thread stays bounded.
        kept = {m.id for m in history}
        stale = [RemoveMessage(id=m.id) for m in state["messages"] if m.id and m.id not in kept]
        return {"messages": [*stale, reply]}

    graph = StateGraph(CoachState, context_schema=CoachContext)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
