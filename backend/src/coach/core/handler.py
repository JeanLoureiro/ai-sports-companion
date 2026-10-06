"""One Telegram update in, one reply out. Shared by the webhook and long polling."""

import logging

import httpx

from coach.core.context import CoachContext
from coach.core.deps import Deps
from coach.core.repo import claim_update, get_athlete_by_chat_id
from coach.core.telegram import TelegramError, Update
from coach.core.turn import run_turn

logger = logging.getLogger(__name__)

UNSUPPORTED_REPLY = "I can only read text messages for now. Voice notes and photos are coming soon."


async def handle_update(deps: Deps, update: Update) -> None:
    """Allowlist, dedupe, run one agent turn and reply."""
    message = update.message
    if message is None:
        return
    chat_id = message.chat.id
    if chat_id not in deps.settings.telegram_allowed_chat_ids:
        logger.warning("ignoring update %s: chat %s is not allowlisted", update.update_id, chat_id)
        return
    async with deps.pool.connection() as conn:
        if not await claim_update(conn, update.update_id):
            return
        athlete = await get_athlete_by_chat_id(conn, chat_id)
    if athlete is None:
        logger.warning(
            "chat %s is allowlisted but has no athlete; run `coach add-athlete`", chat_id
        )
        return
    if not message.text:
        await deps.telegram.send_message(chat_id, UNSUPPORTED_REPLY)
        return
    try:
        await deps.telegram.send_typing(chat_id)
    except (TelegramError, httpx.HTTPError) as err:
        logger.warning("typing indicator failed (%s); answering anyway", type(err).__name__)
    ctx = CoachContext(athlete=athlete, pool=deps.pool, registry=deps.registry)
    result = await run_turn(deps.graph, ctx, message.text, model_name=deps.settings.agent_model)
    await deps.telegram.send_message(chat_id, result.reply)
