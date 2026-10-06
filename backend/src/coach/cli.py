"""Command line: ``coach migrate | add-athlete | set-webhook | poll``."""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from coach.core.config import DEFAULT_TIMEZONE, Settings, get_settings
from coach.core.db import Pool, create_pool
from coach.core.deps import build_deps
from coach.core.migrations import migrate_all
from coach.core.models import Athlete
from coach.core.polling import run_polling
from coach.core.registry import default_registry
from coach.core.repo import create_athlete, get_athlete_by_chat_id


async def add_athlete(
    pool: Pool, *, name: str, chat_id: int, timezone: str
) -> tuple[Athlete, bool]:
    """Create the athlete for a chat, or return the existing one. True when created."""
    ZoneInfo(timezone)  # raises ZoneInfoNotFoundError for a typo before anything is written
    async with pool.connection() as conn:
        existing = await get_athlete_by_chat_id(conn, chat_id)
        if existing:
            return existing, False
        created = await create_athlete(conn, name=name, telegram_chat_id=chat_id, timezone=timezone)
        return created, True


async def _with_pool(settings: Settings, args: argparse.Namespace) -> None:
    pool = create_pool(settings.database_url.get_secret_value())
    await pool.open()
    try:
        if args.command == "migrate":
            applied = await migrate_all(pool, default_registry().migration_dirs())
            print(f"Applied {len(applied)} migration(s): {', '.join(applied) or 'none'}")
        else:
            athlete, created = await add_athlete(
                pool, name=args.name, chat_id=args.chat_id, timezone=args.timezone
            )
            print(f"{'Created' if created else 'Already exists'}: {athlete.name} ({athlete.id})")
    finally:
        await pool.close()


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.command in {"migrate", "add-athlete"}:
        await _with_pool(settings, args)
        return
    async with build_deps(settings) as deps:
        if args.command == "set-webhook":
            await deps.telegram.set_webhook(
                args.url, settings.telegram_webhook_secret.get_secret_value()
            )
            print(f"Webhook set to {args.url}")
        else:
            print("Long polling. Press Ctrl+C to stop.")
            await run_polling(deps)


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for the ``coach`` script."""
    parser = argparse.ArgumentParser(prog="coach")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply core and module migrations")
    add = commands.add_parser("add-athlete", help="link a Telegram chat to a new athlete")
    add.add_argument("--name", required=True)
    add.add_argument("--chat-id", type=int, required=True)
    add.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    hook = commands.add_parser("set-webhook", help="point Telegram at the deployed webhook")
    hook.add_argument("--url", required=True, help="https://<backend domain>/telegram")
    commands.add_parser("poll", help="long polling for local development")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_run(args))
