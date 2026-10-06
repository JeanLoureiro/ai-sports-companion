"""Test doubles shared across the suite."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
import httpx2
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, tool
from pydantic import Field

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob


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
