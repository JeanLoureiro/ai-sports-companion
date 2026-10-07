"""Text matching shared by every module: names said in chat versus names stored."""

import re
import unicodedata
from collections.abc import Callable, Sequence


def normalize(text: str) -> str:
    """Casefold, strip accents, turn punctuation into single spaces (keeps '/' for 90/90)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9/]+", " ", plain).split())


def make_canonicalizer(
    resolvers: Sequence[Callable[[str], str | None]],
) -> Callable[[str], str]:
    """The first resolver that knows a name gives its canonical form, normalized."""

    def canonical(text: str) -> str:
        for resolve in resolvers:
            name = resolve(text)
            if name is not None:
                return normalize(name)
        return normalize(text)

    return canonical
