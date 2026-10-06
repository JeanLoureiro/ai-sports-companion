"""A minimal Telegram Bot API client and the update shapes the handler needs."""

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from coach.core.models import ReplyButton

TELEGRAM_TEXT_LIMIT = 4096
ALLOWED_UPDATES = ["message", "callback_query"]


class Chat(BaseModel):
    """The chat a message came from."""

    id: int


class Message(BaseModel):
    """A message; ``text`` is None for photos, voice notes and stickers."""

    message_id: int
    chat: Chat
    text: str | None = None


class CallbackQuery(BaseModel):
    """A tap on an inline button."""

    id: str
    data: str | None = None
    message: Message | None = None


class Update(BaseModel):
    """An incoming update; unknown update types leave both fields None."""

    update_id: int
    message: Message | None = None
    callback_query: CallbackQuery | None = None


class TelegramError(RuntimeError):
    """The Bot API answered ``ok: false``."""


class TelegramClient:
    """Calls the Bot API. Never log its URLs: they contain the bot token."""

    def __init__(self, token: str, http: httpx.AsyncClient) -> None:
        self._base = f"https://api.telegram.org/bot{token}/"
        self._http = http

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        """Call one Bot API method and return its ``result``."""
        response = await self._http.post(self._base + method, json=payload or {})
        data = response.json()
        if not data.get("ok"):
            description = data.get("description", f"HTTP {response.status_code}")
            raise TelegramError(f"{method} failed: {description}")
        return data["result"]

    async def send_message(
        self, chat_id: int, text: str, buttons: Sequence[ReplyButton] = ()
    ) -> None:
        """Send text split at Telegram's limit; buttons go under the last chunk."""
        chunks = split_message(text)
        for number, chunk in enumerate(chunks, start=1):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if buttons and number == len(chunks):
                payload["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": b.text, "callback_data": b.data}] for b in buttons
                    ]
                }
            await self.call("sendMessage", payload)

    async def answer_callback(self, callback_id: str, text: str) -> None:
        """Acknowledge a button tap with a short toast."""
        await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def send_typing(self, chat_id: int) -> None:
        """Show "typing..." while the agent works."""
        await self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    async def get_updates(
        self, offset: int | None, *, poll_seconds: int = 30
    ) -> list[dict[str, Any]]:
        """Long-poll for new message updates, waiting up to ``poll_seconds`` on Telegram's side."""
        payload: dict[str, Any] = {"timeout": poll_seconds, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        return list(await self.call("getUpdates", payload))

    async def set_webhook(self, url: str, secret: str) -> None:
        """Point Telegram at the deployed webhook."""
        await self.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ALLOWED_UPDATES,
                # One athlete, one thread: concurrent turns would overwrite each other's memory.
                "max_connections": 1,
            },
        )

    async def delete_webhook(self) -> None:
        """Remove the webhook so long polling can receive updates."""
        await self.call("deleteWebhook")


def split_message(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split on line breaks where possible so no chunk exceeds ``limit`` characters."""
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks
