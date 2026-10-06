"""One Telegram update in, one reply out. Shared by the webhook and long polling."""

import logging
from uuid import UUID

import httpx

from coach.core.context import CoachContext
from coach.core.deps import Deps
from coach.core.repo import claim_update, get_athlete_by_chat_id, undo_session
from coach.core.telegram import CallbackQuery, TelegramError, Update
from coach.core.turn import note_in_thread, run_turn

logger = logging.getLogger(__name__)

UNSUPPORTED_REPLY = "I can only read text messages for now. Voice notes and photos are coming soon."


async def handle_update(deps: Deps, update: Update) -> None:
    """Allowlist, dedupe, run one agent turn and reply; button taps go to the callback path."""
    if update.callback_query is not None:
        await _handle_callback(deps, update.update_id, update.callback_query)
        return
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
    await deps.telegram.send_message(chat_id, result.reply, ctx.reply_buttons)


UNDO_PREFIX = "undo:"
NOTHING_TO_UNDO = "Nothing to undo."


async def _handle_callback(deps: Deps, update_id: int, query: CallbackQuery) -> None:
    """Undo buttons: delete the athlete's own session once, then say so in chat and thread."""
    if query.message is None:
        return
    chat_id = query.message.chat.id
    if chat_id not in deps.settings.telegram_allowed_chat_ids:
        return
    summary: str | None = None
    async with deps.pool.connection() as conn:
        if not await claim_update(conn, update_id):
            return
        athlete = await get_athlete_by_chat_id(conn, chat_id)
        session_id = _undo_target(query.data)
        if athlete is not None and session_id is not None:
            summary = await undo_session(conn, athlete, session_id)
    if athlete is None or summary is None:
        await deps.telegram.answer_callback(query.id, NOTHING_TO_UNDO)
        return
    note = f"Undone: {summary}."
    await deps.telegram.answer_callback(query.id, "Undone.")
    await deps.telegram.send_message(chat_id, note)
    await note_in_thread(deps.graph, athlete, note)


def _undo_target(data: str | None) -> UUID | None:
    if not data or not data.startswith(UNDO_PREFIX):
        return None
    try:
        return UUID(data.removeprefix(UNDO_PREFIX))
    except ValueError:
        return None
