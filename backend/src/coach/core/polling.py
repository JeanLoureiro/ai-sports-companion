"""Local development: receive updates by long polling instead of the webhook."""

import asyncio
import logging

import httpx

from coach.core.deps import Deps
from coach.core.handler import handle_update
from coach.core.telegram import Update

logger = logging.getLogger(__name__)


async def poll_once(deps: Deps, offset: int | None, *, poll_seconds: int = 30) -> int | None:
    """Fetch one batch, handle each update, and return the next offset."""
    for raw in await deps.telegram.get_updates(offset, poll_seconds=poll_seconds):
        update = Update.model_validate(raw)
        offset = update.update_id + 1
        try:
            await handle_update(deps, update)
        except Exception:
            logger.exception("update %s failed", update.update_id)
    return offset


async def run_polling(deps: Deps) -> None:
    """Delete the webhook, then poll forever. Use a separate dev bot token for this."""
    await deps.telegram.delete_webhook()
    offset: int | None = None
    while True:
        try:
            offset = await poll_once(deps, offset)
        except httpx.HTTPError as err:
            logger.warning("polling failed (%s); retrying in 5s", type(err).__name__)
            await asyncio.sleep(5)
