from pathlib import Path
from uuid import uuid4

import pytest

from coach.core.db import Connection
from coach.core.migrations import CORE_MIGRATIONS
from coach.core.models import Athlete
from coach.core.registry import Registry, default_registry
from tests.fakes import FakeModule, fake_lookup

ATHLETE = Athlete(id=uuid4(), name="Jean", timezone="Australia/Brisbane", telegram_chat_id=1)


def test_gym_is_enabled() -> None:
    assert [m.name for m in default_registry().modules] == ["gym"]


def test_rejects_duplicate_module_names() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Registry([FakeModule(), FakeModule()])


def test_core_is_a_reserved_name() -> None:
    with pytest.raises(ValueError, match="reserved"):
        Registry([FakeModule(name="core")])


def test_rejects_a_tool_registered_by_two_modules() -> None:
    with pytest.raises(ValueError, match="fake_lookup"):
        Registry([FakeModule(name="a"), FakeModule(name="b")])


def test_collects_tools_and_owners() -> None:
    registry = Registry([FakeModule()])

    assert [t.name for t in registry.tools()] == [fake_lookup.name]
    assert registry.tool_owner("fake_lookup") == "fakesport"
    assert registry.tool_owner("query_history") == "core"


def test_prompt_joins_fragments_and_skips_empty_ones() -> None:
    registry = Registry(
        [
            FakeModule(name="a", module_tools=[], prompt_text="A rules"),
            FakeModule(name="b", module_tools=[], prompt_text="  "),
        ]
    )

    assert registry.prompt(ATHLETE) == "A rules"


@pytest.mark.anyio
async def test_context_prefixes_module_names_and_skips_empty(conn: Connection) -> None:
    registry = Registry(
        [
            FakeModule(name="surf", module_tools=[], context_text="good swell Thu"),
            FakeModule(name="gym", module_tools=[], context_text=""),
        ]
    )

    assert await registry.context(conn, ATHLETE) == "surf: good swell Thu"


def test_migration_dirs_put_core_first() -> None:
    registry = Registry([FakeModule(migrations=Path("/mods/fakesport"))])

    assert registry.migration_dirs() == [
        ("core", CORE_MIGRATIONS),
        ("fakesport", Path("/mods/fakesport")),
    ]
