"""Test doubles shared across the suite."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import httpx
import httpx2
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from coach.core.config import Settings
from coach.core.db import Connection, Pool
from coach.core.deps import Deps
from coach.core.graph import build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry, ScheduledJob
from coach.core.telegram import TelegramClient
from tests.conftest import TEST_DATABASE_URL

TEST_TOKEN = "TEST:TOKEN"
WEBHOOK_SECRET = "hook-secret"


@tool
def fake_lookup(query: str) -> str:
    """Look something up in the fake sport."""
    return f"fake:{query}"


@dataclass
class FakeModule:
    """A discipline module with canned answers."""

    name: str = "fakesport"
    migrations: Path = Path("/nonexistent")
    module_tools: list[BaseTool] = field(default_factory=lambda: [fake_lookup])
    prompt_text: str = "FAKE PROMPT"
    context_text: str = "fake context line"

    def tools(self) -> list[BaseTool]:
        return list(self.module_tools)

    def prompt(self, athlete: Athlete) -> str:
        return self.prompt_text

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        return self.context_text

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return []


class FakeChatModel(GenericFakeChatModel):
    """Scripted chat model that records every prompt it receives."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def scripted(*replies: AIMessage | str) -> FakeChatModel:
    """A fake model that answers with ``replies`` in order."""
    return FakeChatModel(
        messages=iter([r if isinstance(r, AIMessage) else AIMessage(content=r) for r in replies])
    )


class ExplodingChatModel(FakeChatModel):
    """A model whose API is down."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        )


class TelegramRecorder:
    """A fake Bot API: records calls, serves queued getUpdates batches, can fail a method."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.update_batches: list[list[dict[str, Any]]] = []
        self.fail_on = fail_on

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload: dict[str, Any] = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if method == self.fail_on:
            return httpx.Response(400, json={"ok": False, "description": "Bad Request"})
        result: Any = True
        if method == "getUpdates":
            result = self.update_batches.pop(0) if self.update_batches else []
        elif method == "sendMessage":
            result = {"message_id": len(self.calls)}
        return httpx.Response(200, json={"ok": True, "result": result})

    def client(self) -> TelegramClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return TelegramClient(TEST_TOKEN, http)

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]

    def sent_texts(self) -> list[str]:
        return [str(p["text"]) for m, p in self.calls if m == "sendMessage"]


def make_deps(
    pool: Pool, model: FakeChatModel, recorder: TelegramRecorder, *, allowed: list[int]
) -> Deps:
    settings = Settings.model_validate(
        {
            "database_url": TEST_DATABASE_URL,
            "telegram_bot_token": TEST_TOKEN,
            "telegram_webhook_secret": WEBHOOK_SECRET,
            "telegram_allowed_chat_ids": allowed,
            "anthropic_api_key": "sk-test",
            "agent_model": "test-model",
        }
    )
    registry = Registry([])
    return Deps(
        settings=settings,
        pool=pool,
        registry=registry,
        graph=build_graph(model, registry, InMemorySaver()),
        telegram=recorder.client(),
    )


def text_update(update_id: int, chat_id: int, text: str | None = "hi") -> dict[str, Any]:
    message: dict[str, Any] = {"message_id": 1, "chat": {"id": chat_id, "type": "private"}}
    if text is not None:
        message["text"] = text
    else:
        message["photo"] = [{"file_id": "abc", "width": 1, "height": 1}]
    return {"update_id": update_id, "message": message}


class BrokenChatModel(FakeChatModel):
    """A model integration that fails with something other than an API error."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise RuntimeError("boom")
