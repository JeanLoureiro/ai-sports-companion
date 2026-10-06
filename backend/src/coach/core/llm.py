"""The one place that knows which chat model the agent uses."""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from coach.core.config import Settings


def get_chat_model(settings: Settings) -> BaseChatModel:
    """Claude Haiku by default; swap providers here and nowhere else."""
    return ChatAnthropic(
        model=settings.agent_model,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
        timeout=60.0,
        max_retries=2,
    )
