"""The system prompt: core rules, athlete facts, module fragments and live context."""

from datetime import datetime
from zoneinfo import ZoneInfo

from coach.core.models import Athlete
from coach.core.registry import Registry

CORE_PROMPT = """\
You are a coach for a hybrid athlete who trains Brazilian jiu-jitsu, surfs and lifts.
You reply in Telegram, so keep answers short and plain: a few sentences, no tables.
Answer questions about training from the tools; never invent sessions, numbers or dates.
If a tool returns nothing, say so plainly.
Frame every suggestion as a training adjustment, not medical advice.
If the athlete mentions pain or injury, suggest seeing a qualified professional."""


def system_prompt(athlete: Athlete, registry: Registry, context: str, now: datetime) -> str:
    """Assemble the system prompt for one model call."""
    local = now.astimezone(ZoneInfo(athlete.timezone))
    parts = [
        CORE_PROMPT,
        f"Athlete: {athlete.name}. Time zone: {athlete.timezone}. "
        f"Local time now: {local:%A %Y-%m-%d %H:%M}.",
        registry.prompt(athlete),
        f"What the modules know right now:\n{context}" if context else "",
    ]
    return "\n\n".join(p for p in parts if p)
