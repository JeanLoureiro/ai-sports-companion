"""Everything a request needs, built once per process."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.config import Settings
from coach.core.db import Pool, create_pool
from coach.core.graph import CoachGraph, build_graph
from coach.core.llm import get_chat_model
from coach.core.registry import Registry, default_registry
from coach.core.telegram import TelegramClient


@dataclass(frozen=True, slots=True)
class Deps:
    """Process-wide dependencies shared by the webhook and long polling."""

    settings: Settings
    pool: Pool
    registry: Registry
    graph: CoachGraph
    telegram: TelegramClient


@asynccontextmanager
async def build_deps(settings: Settings) -> AsyncIterator[Deps]:
    """Open the pool and HTTP client, build the graph, close everything on exit."""
    pool = create_pool(settings.database_url.get_secret_value())
    await pool.open()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http:
            registry = default_registry()
            graph = build_graph(
                get_chat_model(settings),
                registry,
                AsyncPostgresSaver(pool),
                history_messages=settings.history_messages,
            )
            telegram = TelegramClient(settings.telegram_bot_token.get_secret_value(), http)
            yield Deps(
                settings=settings, pool=pool, registry=registry, graph=graph, telegram=telegram
            )
    finally:
        await pool.close()
