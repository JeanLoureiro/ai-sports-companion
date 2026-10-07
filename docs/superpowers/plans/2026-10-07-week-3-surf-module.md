# Week 3: Surf Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Burleigh this morning, 2 hours, 3-4 ft, caught 12" logs a surf session against a saved spot in one message (with Undo); an unknown spot makes the coach ask for a location pin and carry on when it arrives; "where should I surf tomorrow?" gets a forecast per favourite spot, rated against what each break likes.

**Architecture:** A `surf` discipline module under `backend/src/coach/modules/surf/` (migration, public `spots.yaml` with spot profiles, seed command, `forecast.py` Open-Meteo client, tools `log_surf_session`, `get_surf_forecast`, `surf_history`, prompt, context, eval set).
Three small core additions: `normalize` moves to `coach.core.text` (both modules need it and modules never import each other); tools get an HTTP client through `CoachContext.http`; the turn runner and handler support LangGraph `interrupt()` (a pending interrupt is resumed by the next message, text or Telegram location pin, and the interrupt's question becomes the reply).

**Tech Stack:** As week 2; Open-Meteo Marine and Forecast APIs over httpx.

**Spec:** `docs/Hybrid Athlete Coach — Project Plan.md` and `docs/ARCHITECTURE.md`.
Facts and decisions taken after the spec:

- Open-Meteo's marine model is regional: Burleigh Heads, Snapper Rocks, Currumbin Alley and Duranbah all resolve to the same grid cell (-28.04, 153.63), so swell, period, direction and sea level are identical for all four; wind (forecast API) is local enough. Spot differences therefore come from a spot profile: the swell directions the break works with, the wind directions that blow offshore, and a minimum swell. Forecasts are labelled estimates.
- The athlete surfs Burleigh Heads, Snapper Rocks / Superbank, Currumbin Alley and Duranbah (D'Bah); all four are seeded as favourites from a public `spots.yaml`. Profiles are best-effort defaults the athlete confirms or edits (Task 7).
- Wave heights are in feet as the athlete says them; forecast swell is reported in metres and feet.
- The unknown-spot `interrupt()` is the first one in the codebase: the next message always resumes it (spec decision); a location pin creates the spot, a reply naming a saved spot logs there and remembers the new name as an alias, anything else logs the session without a spot.
- Deploying (week 1 Task 11) happens after this week.

## Global Constraints

- Everything in weeks 1 and 2 still applies (Python 3.14, uv `exclude-newer = "7 days"`, ruff + mypy strict + pytest gate, `SecretStr`, no em dashes, no AI attribution in commits, one sentence per line in long Markdown, commit after every task, tests never delete shared local data).
- Modules never import each other; shared helpers go in `coach.core`. After Task 1, `coach.core.evals` no longer imports the gym module (modules contribute a `canonical` hook).
- No network in tests: Open-Meteo is reached only through `CoachContext.http`, replaced by `httpx.MockTransport` in tests.
- Live eval recordings are re-made whenever the prompt or any tool schema changes (CI replay refuses stale recordings).

## Review Focus

1. A message arrives while an interrupt is pending (the athlete ignores the question and says something else): it resumes the interrupt instead of starting a new turn, and the session is still logged. Test: Task 1 and Task 5.
2. A location pin with no pending question: treated as an ordinary message, not an error. Test: Task 1.
3. Wind direction ranges that wrap past north (offshore from 300 to 30 degrees): rated correctly. Test: Task 3.
4. Open-Meteo returns gaps (`null` hours) or an HTTP error: the tool reports the gap or the failure instead of crashing the turn. Test: Task 3.
5. Spot names with apostrophes and spacing variants ("D'Bah", "dbah", "d bah"): all resolve to Duranbah. Test: Task 4.

---

## File Structure

```
backend/src/coach/core/
  text.py                      normalize (moved from gym.library; gym re-exports it)
  models.py                    + Location
  telegram.py                  + TgLocation on Message
  context.py                   + http
  deps.py                      + http
  turn.py                      interrupt-aware run_turn (Command(resume=...), question as reply)
  handler.py                   location messages; passes location and http
  registry.py                  default_registry enables SurfModule
  evals.py                     canonical normalizer moves to core (no gym import)
backend/src/coach/modules/surf/
  __init__.py
  module.py                    SurfModule
  spots.py                     SpotDef, load_spots, resolve_spot, spot rows
  seed.py                      python -m coach.modules.surf.seed
  forecast.py                  Open-Meteo client, compass, wind relation, rating, tides, windows
  repo.py                      surf SQL
  tools.py                     log_surf_session, get_surf_forecast, surf_history
  prompt.md
  spots.yaml                   public spot profiles
  migrations/0001_surf.sql
  evals/extraction.yaml, evals/recordings/extraction.json
backend/tests/
  fakes.py                     + ask_tool, make_deps(http=...), location_update
  test_interrupts.py
  test_surf_seed.py
  test_surf_forecast.py
  test_surf_tools.py
```

---

### Task 1: Core: shared normalize, HTTP for tools, interrupts and location pins

**Files:**
- Create: `backend/src/coach/core/text.py`
- Modify: `backend/src/coach/modules/gym/library.py` (import `normalize` from core), `backend/src/coach/core/{models,telegram,context,deps,turn,handler,evals}.py`, `backend/tests/fakes.py`
- Test: `backend/tests/test_interrupts.py`

**Interfaces:**
- Produces:
  - `coach.core.text.normalize(text) -> str` (same behaviour as week 2's; `gym.library.normalize` stays importable as a re-export).
  - `coach.core.text.make_canonicalizer(resolvers: Sequence[Callable[[str], str | None]]) -> Callable[[str], str]`: the first resolver that returns a name wins, normalized; otherwise the normalized text. `core.evals` builds its scorer from every module's `canonical(name)` (gym: library names; surf: spot names) through a new optional module hook (see below).
  - `models.Location(latitude: float, longitude: float)`.
  - `telegram.TgLocation(latitude, longitude)`; `Message.location: TgLocation | None`.
  - `CoachContext.http: httpx.AsyncClient | None = None`; `Deps.http: httpx.AsyncClient`.
  - `run_turn(graph, ctx, text, *, model_name, trigger="message", location: Location | None = None) -> TurnResult`: when the thread has a pending interrupt it resumes with `{"text": text, "location": {"latitude", "longitude"} | None}`; when the turn ends interrupted, `reply` is the interrupt's `question`.
  - Handler: a message with a location (and no text) is a turn with text `"(shared a location)"`.
  - Optional module hook `canonical(self, name: str) -> str | None` (not part of the Protocol; `core.evals` uses `getattr(module, "canonical", None)`), implemented by `GymModule` (library name) and later `SurfModule` (spot name).
  - Test helpers: `fakes.ask_tool` (interrupts with `{"question": question}`), `make_deps(..., http: httpx.AsyncClient | None = None)`, `fakes.location_update(update_id, chat_id, latitude, longitude)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_interrupts.py`:

```python
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.handler import handle_update
from coach.core.models import Athlete, Location
from coach.core.registry import Registry
from coach.core.telegram import Update
from coach.core.text import make_canonicalizer, normalize
from coach.core.turn import run_turn
from tests.factories import new_update_id
from tests.fakes import (
    FakeModule,
    TelegramRecorder,
    ask_tool,
    location_update,
    make_deps,
    scripted,
)

pytestmark = pytest.mark.anyio

ASK = Registry([FakeModule(module_tools=[ask_tool], context_text="")])


def ask(question: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "ask_tool", "args": {"question": question}, "id": "a1"}]
    )


def test_normalize_lives_in_core() -> None:
    assert normalize("D'Bah ") == "d bah"


def test_canonicalizer_uses_the_first_resolver_that_knows_the_name() -> None:
    canonical = make_canonicalizer([lambda s: "Duranbah" if normalize(s) == "dbah" else None])

    assert canonical("dbah") == "duranbah"
    assert canonical("Burleigh") == "burleigh"


async def test_an_interrupt_question_is_the_reply_and_the_next_message_answers_it(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted(ask("Where was that?"), "Logged at Burleigh.")
    graph = build_graph(model, ASK, InMemorySaver())
    ctx = CoachContext(athlete=athlete, pool=pool, registry=ASK)

    first = await run_turn(graph, ctx, "surfed this morning", model_name="m")
    second = await run_turn(graph, ctx, "Burleigh", model_name="m")

    assert first.reply == "Where was that?"
    assert second.reply == "Logged at Burleigh."
    tool_result = next(m for m in model.seen[-1] if isinstance(m, ToolMessage))
    assert json.loads(tool_result.text.removeprefix("answer: ")) == {
        "text": "Burleigh",
        "location": None,
    }


async def test_a_location_pin_answers_a_pending_question(pool: Pool, athlete: Athlete) -> None:
    model = scripted(ask("Send me a pin"), "Saved.")
    graph = build_graph(model, ASK, InMemorySaver())
    ctx = CoachContext(athlete=athlete, pool=pool, registry=ASK)

    await run_turn(graph, ctx, "surfed at the secret spot", model_name="m")
    await run_turn(
        graph, ctx, "(shared a location)", model_name="m", location=Location(-28.1, 153.5)
    )

    tool_result = next(m for m in model.seen[-1] if isinstance(m, ToolMessage))
    assert json.loads(tool_result.text.removeprefix("answer: "))["location"] == {
        "latitude": -28.1,
        "longitude": 153.5,
    }


async def test_a_location_without_a_question_is_an_ordinary_message(
    pool: Pool, athlete: Athlete
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("Nice spot.")
    deps = make_deps(pool, model, recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(
        deps,
        Update.model_validate(
            location_update(new_update_id(), athlete.telegram_chat_id, -28.1, 153.5)
        ),
    )

    assert recorder.sent_texts() == ["Nice spot."]
    assert model.seen[0][-1].text == "(shared a location)"
```

Add to `backend/tests/fakes.py` (merge imports: `from langgraph.types import interrupt`):

```python
@tool
async def ask_tool(question: str) -> str:
    """Ask the athlete something and wait for the answer."""
    answer = interrupt({"question": question})
    return f"answer: {json.dumps(answer)}"


def location_update(
    update_id: int, chat_id: int, latitude: float, longitude: float
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "location": {"latitude": latitude, "longitude": longitude},
        },
    }
```

and give `make_deps` an `http: httpx.AsyncClient | None = None` parameter passed to `Deps(http=http or httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_interrupts.py -q`
Expected: ERROR at import (`coach.core.text`, `Location`, `ask_tool` missing).

- [ ] **Step 3: Implement**

`backend/src/coach/core/text.py`:

```python
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
```

In `gym/library.py` replace the `normalize` definition with `from coach.core.text import normalize` (keep the `re`/`unicodedata` imports only if still used) and keep `canonical_name`.
Add to `GymModule`:

```python
    def canonical(self, name: str) -> str | None:
        exercise = library_index().resolve(name)
        return exercise.name if exercise else None
```

`models.py`: add `Location` (frozen, slots: `latitude: float`, `longitude: float`).
`telegram.py`: add `class TgLocation(BaseModel): latitude: float; longitude: float` and `location: TgLocation | None = None` on `Message`.
`context.py`: `http: httpx.AsyncClient | None = None` (before `reply_buttons`).
`deps.py`: `Deps.http: httpx.AsyncClient`; `build_deps` passes the `http` client it already opens.

`turn.py`, replace the invoke part of `run_turn`:

```python
async def run_turn(
    graph: CoachGraph,
    ctx: CoachContext,
    text: str,
    *,
    model_name: str,
    trigger: Trigger = "message",
    location: Location | None = None,
) -> TurnResult:
    """Run one turn on the athlete's thread; a pending interrupt is resumed by this message."""
    config: RunnableConfig = {"configurable": {"thread_id": str(ctx.athlete.id)}}
    snapshot = await graph.aget_state(config)
    seen = {m.id for m in snapshot.values.get("messages", [])}
    pending = [i for task in snapshot.tasks for i in task.interrupts]
    payload: Any
    if pending:
        payload = Command(
            resume={"text": text, "location": asdict(location) if location else None}
        )
    else:
        payload = {"messages": [HumanMessage(content=text)]}
    started = time.perf_counter()
    new: list[BaseMessage] = []
    error: str | None = None
    try:
        out = await graph.ainvoke(payload, config, context=ctx)
        new = [m for m in out["messages"] if m.id not in seen]
        interrupts = out.get("__interrupt__") or []
        reply = _question(interrupts[0].value) if interrupts else _final_reply(new)
    except Exception as err:  # noqa: BLE001 - the athlete always gets an answer and a record
        ...
```

(keep the rest of `run_turn` as it is) and add:

```python
def _question(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("question"), str):
        return value["question"]
    return str(value)
```

(imports: `from dataclasses import asdict`, `from langgraph.types import Command`, `Location`).

`handler.py`: replace the text-only check and the turn call:

```python
    if not message.text and message.location is None:
        await deps.telegram.send_message(chat_id, UNSUPPORTED_REPLY)
        return
    location = (
        Location(message.location.latitude, message.location.longitude)
        if message.location
        else None
    )
    text = message.text or "(shared a location)"
    ...
    ctx = CoachContext(athlete=athlete, pool=deps.pool, registry=deps.registry, http=deps.http)
    result = await run_turn(
        deps.graph, ctx, text, model_name=deps.settings.agent_model, location=location
    )
```

`evals.py` `_run`: replace the gym import with

```python
    canonical = make_canonicalizer(
        [hook for m in registry.modules if (hook := getattr(m, "canonical", None))]
    )
```

and pass `canonical` to `score_case`. Update the `UNSUPPORTED_REPLY` text to: "I can read text and location pins for now. Voice notes and photos are coming soon."

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass (week 2's `test_text_less_messages_get_a_short_explanation` uses a photo, still unsupported).

- [ ] **Step 5: Quality gate and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run python -m coach.core.evals
cd .. && git add backend && git commit -m "feat: resume interrupts with the next message or a location pin; give tools HTTP"
```

(The replay must still pass: the gym prompt and schemas are unchanged.)

---

### Task 2: Surf schema, spot profiles and seeding

**Files:**
- Create: `backend/src/coach/modules/surf/{__init__.py,module.py,spots.py,seed.py,spots.yaml,migrations/0001_surf.sql}`
- Modify: `backend/src/coach/core/registry.py`, `backend/tests/test_registry.py`, `backend/tests/test_telegram.py`
- Test: `backend/tests/test_surf_seed.py`

**Interfaces:**
- Produces:
  - `spots.SpotDef(name, aliases, latitude, longitude, swell_from: tuple[int, int] | None, offshore_from: tuple[int, int] | None, min_swell_m: float | None, favourite: bool)`; `load_spots(path) -> list[SpotDef]`; `SPOTS_PATH`.
  - `spots.spot_keys(row) -> list[str]` (normalized name and aliases); `async resolve_spot(conn, athlete, said) -> dict | None` (exact normalized match on name or alias, then `difflib.get_close_matches` with cutoff 0.85, unique only); `async list_spots(conn, athlete) -> list[dict]`; `async create_spot(conn, athlete, name, location) -> dict`; `async add_alias(conn, spot_id, alias)`.
  - `seed.seed_spots(conn, athlete, spots) -> int` (upsert by name; returns count); `python -m coach.modules.surf.seed --chat-id N`.
  - `SurfModule` skeleton (tools, prompt, context empty); `default_registry()` returns `Registry([GymModule(), SurfModule()])`.

Spot rows are dicts with keys `id, name, aliases, latitude, longitude, swell_from_min, swell_from_max, offshore_from_min, offshore_from_max, min_swell_m, favourite`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_surf_seed.py`:

```python
import pytest

from coach.core.db import Connection
from coach.core.models import Athlete, Location
from coach.modules.surf.seed import seed_spots
from coach.modules.surf.spots import (
    SPOTS_PATH,
    add_alias,
    create_spot,
    list_spots,
    load_spots,
    resolve_spot,
)

pytestmark = pytest.mark.anyio


def test_the_four_favourites_ship_with_profiles() -> None:
    spots = {s.name: s for s in load_spots(SPOTS_PATH)}

    assert set(spots) == {"Burleigh Heads", "Snapper Rocks", "Currumbin Alley", "Duranbah"}
    assert all(s.favourite and s.offshore_from and s.swell_from for s in spots.values())


async def test_seeding_is_idempotent(conn: Connection, athlete: Athlete) -> None:
    spots = load_spots(SPOTS_PATH)

    assert await seed_spots(conn, athlete, spots) == 4
    assert await seed_spots(conn, athlete, spots) == 4
    assert len(await list_spots(conn, athlete)) == 4


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("burleigh", "Burleigh Heads"),
        ("Snapper", "Snapper Rocks"),
        ("superbank", "Snapper Rocks"),
        ("the alley", "Currumbin Alley"),
        ("D'Bah", "Duranbah"),
        ("dbah", "Duranbah"),
        ("d bah", "Duranbah"),
        ("burleigh heds", "Burleigh Heads"),
        ("kirra", None),
    ],
)
async def test_spot_names_resolve_with_aliases_and_typos(
    conn: Connection, athlete: Athlete, said: str, expected: str | None
) -> None:
    await seed_spots(conn, athlete, load_spots(SPOTS_PATH))

    spot = await resolve_spot(conn, athlete, said)

    assert (spot["name"] if spot else None) == expected


async def test_new_spots_and_aliases(conn: Connection, athlete: Athlete) -> None:
    await seed_spots(conn, athlete, load_spots(SPOTS_PATH))

    kirra = await create_spot(conn, athlete, "Kirra", Location(-28.167, 153.531))
    burleigh = await resolve_spot(conn, athlete, "burleigh")
    assert burleigh is not None
    await add_alias(conn, burleigh["id"], "the point")

    found_kirra = await resolve_spot(conn, athlete, "kirra")
    found_point = await resolve_spot(conn, athlete, "the point")
    assert found_kirra is not None and found_kirra["id"] == kirra["id"]
    assert found_point is not None and found_point["name"] == "Burleigh Heads"
```

In `test_registry.py`, `test_gym_is_enabled` becomes `test_gym_and_surf_are_enabled` asserting `["gym", "surf"]`; in `test_telegram.py`, the build-deps test expects `["gym", "surf"]`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_surf_seed.py -q`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.modules.surf'`.

- [ ] **Step 3: Migration**

`backend/src/coach/modules/surf/migrations/0001_surf.sql`:

```sql
insert into disciplines (name, label) values ('surf', 'Surf') on conflict (name) do nothing;

-- a spot's profile says what the break likes; the regional forecast is rated against it
create table surf_spots (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  name text not null,
  aliases text[] not null default '{}',
  latitude double precision not null,
  longitude double precision not null,
  favourite boolean not null default false,
  swell_from_min smallint check (swell_from_min between 0 and 359),  -- degrees the swell comes from
  swell_from_max smallint check (swell_from_max between 0 and 359),
  offshore_from_min smallint check (offshore_from_min between 0 and 359),  -- wind from: offshore
  offshore_from_max smallint check (offshore_from_max between 0 and 359),
  min_swell_m numeric,
  unique (athlete_id, name)
);

create table surf_details (
  session_id uuid primary key references sessions(id) on delete cascade,
  spot_id uuid references surf_spots(id) on delete set null,
  wave_height_min_ft numeric,
  wave_height_max_ft numeric,
  wind text,
  tide text,
  waves_caught int,
  board text,
  notes text
);
create index on surf_details (spot_id);

alter table surf_spots enable row level security;
alter table surf_details enable row level security;
```

- [ ] **Step 4: Spot profiles**

`backend/src/coach/modules/surf/spots.yaml`:

```yaml
# Public spot profiles. Directions are degrees the swell or wind comes FROM (0 = north).
# swell_from: swell directions the break works with; offshore_from: wind directions that blow
# offshore there. Best-effort defaults; the athlete edits them (see README).
spots:
  - name: Snapper Rocks
    aliases: [snapper, superbank, snapper rocks superbank, the superbank]
    latitude: -28.1626
    longitude: 153.5497
    swell_from: [60, 170]
    offshore_from: [200, 290]
    min_swell_m: 0.6
    favourite: true
  - name: Burleigh Heads
    aliases: [burleigh, burly, burleigh point]
    latitude: -28.0890
    longitude: 153.4560
    swell_from: [90, 170]
    offshore_from: [200, 290]
    min_swell_m: 0.8
    favourite: true
  - name: Currumbin Alley
    aliases: [currumbin, the alley, alley, currumbin alley]
    latitude: -28.1283
    longitude: 153.4850
    swell_from: [90, 180]
    offshore_from: [180, 270]
    min_swell_m: 0.6
    favourite: true
  - name: Duranbah
    aliases: [dbah, d bah, d'bah, duranbah beach]
    latitude: -28.1683
    longitude: 153.5525
    swell_from: [45, 160]
    offshore_from: [225, 300]
    min_swell_m: 0.4
    favourite: true
```

- [ ] **Step 5: Spots, seeding and the module skeleton**

`backend/src/coach/modules/surf/__init__.py`:

```python
"""Surf: spots, logging sessions, history and forecasts rated per spot."""
```

`backend/src/coach/modules/surf/spots.py`:

```python
"""Spot profiles and resolving spot names said in chat."""

import difflib
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict

from coach.core.db import Connection
from coach.core.models import Athlete, Location
from coach.core.text import normalize

SPOTS_PATH = Path(__file__).parent / "spots.yaml"
_COLUMNS = (
    "id, name, aliases, latitude, longitude, swell_from_min, swell_from_max, "
    "offshore_from_min, offshore_from_max, min_swell_m, favourite"
)


class SpotDef(BaseModel):
    """One spot as written in spots.yaml."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    aliases: tuple[str, ...] = ()
    latitude: float
    longitude: float
    swell_from: tuple[int, int] | None = None
    offshore_from: tuple[int, int] | None = None
    min_swell_m: float | None = None
    favourite: bool = False


def load_spots(path: Path) -> list[SpotDef]:
    """Read ``spots:`` from a YAML file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [SpotDef.model_validate(item) for item in data["spots"]]


def spot_keys(row: dict[str, Any]) -> list[str]:
    """Every normalized name a spot answers to, spaces removed too ('d bah' and 'dbah')."""
    keys = [normalize(k) for k in (row["name"], *row["aliases"])]
    return [*keys, *(k.replace(" ", "") for k in keys)]


async def list_spots(conn: Connection, athlete: Athlete) -> list[dict[str, Any]]:
    """The athlete's spots, favourites first."""
    cur = await conn.execute(
        f"select {_COLUMNS} from surf_spots where athlete_id = %s "  # noqa: S608 - constant columns
        "order by favourite desc, name",
        (athlete.id,),
    )
    return await cur.fetchall()


async def resolve_spot(conn: Connection, athlete: Athlete, said: str) -> dict[str, Any] | None:
    """Exact name or alias first, then a single close match (typos); otherwise None."""
    spots = await list_spots(conn, athlete)
    wanted = normalize(said)
    candidates = {wanted, wanted.replace(" ", "")}
    by_key: dict[str, dict[str, Any]] = {}
    for spot in spots:
        for key in spot_keys(spot):
            by_key.setdefault(key, spot)
    for key in candidates:
        if key in by_key:
            return by_key[key]
    close = {
        by_key[k]["id"]: by_key[k] for k in difflib.get_close_matches(wanted, by_key, cutoff=0.85)
    }
    return next(iter(close.values())) if len(close) == 1 else None


async def create_spot(
    conn: Connection, athlete: Athlete, name: str, location: Location
) -> dict[str, Any]:
    """A new spot from a location pin, without a profile yet."""
    cur = await conn.execute(
        "insert into surf_spots (athlete_id, name, latitude, longitude) values (%s, %s, %s, %s) "
        f"on conflict (athlete_id, name) do update set latitude = excluded.latitude, "  # noqa: S608
        f"longitude = excluded.longitude returning {_COLUMNS}",
        (athlete.id, name, location.latitude, location.longitude),
    )
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("spot insert returned no row")
    return row


async def add_alias(conn: Connection, spot_id: UUID, alias: str) -> None:
    """Remember another name for a spot."""
    await conn.execute(
        "update surf_spots set aliases = array_append(aliases, %s) "
        "where id = %s and not (%s = any(aliases))",
        (alias, spot_id, alias),
    )
```

`backend/src/coach/modules/surf/seed.py`:

```python
"""Load spot profiles for an athlete: ``python -m coach.modules.surf.seed``."""

import argparse
import asyncio
from collections.abc import Sequence

from coach.core.config import get_settings
from coach.core.db import Connection, create_pool
from coach.core.models import Athlete
from coach.core.repo import get_athlete_by_chat_id
from coach.modules.surf.spots import SPOTS_PATH, SpotDef, load_spots


async def seed_spots(conn: Connection, athlete: Athlete, spots: Sequence[SpotDef]) -> int:
    """Upsert every spot by name, profile included; returns how many were written."""
    async with conn.transaction():
        for spot in spots:
            swell = spot.swell_from or (None, None)
            offshore = spot.offshore_from or (None, None)
            await conn.execute(
                "insert into surf_spots (athlete_id, name, aliases, latitude, longitude, "
                "favourite, swell_from_min, swell_from_max, offshore_from_min, "
                "offshore_from_max, min_swell_m) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (athlete_id, name) do update set aliases = excluded.aliases, "
                "latitude = excluded.latitude, longitude = excluded.longitude, "
                "favourite = excluded.favourite, swell_from_min = excluded.swell_from_min, "
                "swell_from_max = excluded.swell_from_max, "
                "offshore_from_min = excluded.offshore_from_min, "
                "offshore_from_max = excluded.offshore_from_max, "
                "min_swell_m = excluded.min_swell_m",
                (
                    athlete.id, spot.name, list(spot.aliases), spot.latitude, spot.longitude,
                    spot.favourite, swell[0], swell[1], offshore[0], offshore[1],
                    spot.min_swell_m,
                ),
            )
    return len(spots)


async def _seed(chat_id: int) -> None:
    pool = create_pool(get_settings().database_url.get_secret_value())
    await pool.open()
    try:
        async with pool.connection() as conn:
            athlete = await get_athlete_by_chat_id(conn, chat_id)
            if athlete is None:
                raise SystemExit(f"No athlete for chat {chat_id}; run `coach add-athlete` first.")
            count = await seed_spots(conn, athlete, load_spots(SPOTS_PATH))
        print(f"Seeded {count} spots for {athlete.name}")
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Seed the shipped spot profiles for an athlete."""
    parser = argparse.ArgumentParser(prog="python -m coach.modules.surf.seed")
    parser.add_argument("--chat-id", type=int, required=True)
    asyncio.run(_seed(parser.parse_args(argv).chat_id))


if __name__ == "__main__":
    main()
```

`backend/src/coach/modules/surf/module.py`: `SurfModule` with `name = "surf"`, `migrations = HERE / "migrations"`, empty `tools`, `prompt`, `context`, `jobs`, `evals`, and

```python
    def canonical(self, name: str) -> str | None:
        return None  # spot names are canonicalized per athlete in the database
```

`registry.default_registry()` imports both modules locally and returns `Registry([GymModule(), SurfModule()])`.

- [ ] **Step 6: Run tests, gate, commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run coach migrate`
Expected: all pass; the surf migration is applied locally (by the tests or by `migrate`).

```bash
git add backend && git commit -m "feat: add surf schema, spot profiles and seeding"
```

---

### Task 3: Forecasts from Open-Meteo, rated per spot

**Files:**
- Create: `backend/src/coach/modules/surf/forecast.py`
- Test: `backend/tests/test_surf_forecast.py`

**Interfaces:**
- Produces:
  - `compass(degrees) -> str` (16 points); `in_range(degrees, lo, hi) -> bool` (wraps past north); `angle_between(a, b) -> float`.
  - `Spot` dataclass built from a spot row: `Spot.from_row(row)`.
  - `Hour(time: datetime, swell_m: float, period_s: float, swell_from: float, wind_kn: float, wind_from: float, sea_level_m: float | None)`.
  - `wind_relation(spot, wind_from) -> Literal["offshore", "cross-shore", "onshore", "unknown"]`; `rate(spot, hour) -> int` (0 to 5).
  - `tide_events(hours) -> list[dict]` (`time`, `kind` high or low, `sea_level_m`).
  - `async fetch_hours(http, spot, *, days, timezone) -> list[Hour]` (raises `ForecastError` on HTTP failure).
  - `windows(spot, hours) -> list[dict]`: per local day, the best hour in each of morning (05-09), midday (10-13) and afternoon (14-18), with `day`, `window`, `time`, `swell_m`, `swell_ft`, `period_s`, `swell_from`, `wind_kn`, `wind_from`, `wind`, `tide` (rising, falling or unknown), `rating`.
  - `MARINE_URL`, `WEATHER_URL`, `ESTIMATE_NOTE`.

Rating rules (documented in the code): +2 when swell meets the spot's minimum (0.5 m without one), +1 more when the period is 10 s or longer; +1 when the swell direction is in the spot's range (or the spot has no range); +1 when the wind is offshore or under 6 kn; -1 when onshore at 12 kn or more; clamp to 0..5.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_surf_forecast.py`:

```python
from datetime import datetime
from typing import Any

import httpx
import pytest

from coach.modules.surf.forecast import (
    MARINE_URL,
    ForecastError,
    Hour,
    Spot,
    compass,
    fetch_hours,
    in_range,
    rate,
    tide_events,
    wind_relation,
    windows,
)

pytestmark = pytest.mark.anyio

SNAPPER = Spot(
    name="Snapper Rocks", latitude=-28.16, longitude=153.55,
    swell_from=(60, 170), offshore_from=(200, 290), min_swell_m=0.6,
)
NORTHERLY = Spot(
    name="Wrap", latitude=0, longitude=0, swell_from=None, offshore_from=(300, 30),
    min_swell_m=None,
)


def hour(at: str, **values: float) -> Hour:
    base: dict[str, Any] = {"swell_m": 1.0, "period_s": 9.0, "swell_from": 100.0,
                            "wind_kn": 5.0, "wind_from": 250.0, "sea_level_m": 0.0}
    base.update(values)
    return Hour(time=datetime.fromisoformat(at), **base)


def test_compass_points() -> None:
    assert [compass(d) for d in (0, 44, 90, 202, 355)] == ["N", "NE", "E", "SSW", "N"]


def test_ranges_wrap_past_north() -> None:
    assert in_range(350, 300, 30) and in_range(10, 300, 30)
    assert not in_range(180, 300, 30)
    assert in_range(100, 60, 170) and not in_range(200, 60, 170)


def test_wind_relation_uses_the_spot_profile() -> None:
    assert wind_relation(SNAPPER, 245) == "offshore"
    assert wind_relation(SNAPPER, 65) == "onshore"
    assert wind_relation(SNAPPER, 160) == "cross-shore"
    assert wind_relation(NORTHERLY, 0) == "offshore"
    assert wind_relation(Spot("x", 0, 0, None, None, None), 90) == "unknown"


def test_rating_rewards_size_period_direction_and_offshore_wind() -> None:
    perfect = hour("2026-10-08T06:00", swell_m=1.2, period_s=11, swell_from=110, wind_kn=8,
                   wind_from=250)
    blown_out = hour("2026-10-08T14:00", swell_m=1.2, period_s=11, swell_from=110, wind_kn=18,
                     wind_from=60)
    flat = hour("2026-10-08T06:00", swell_m=0.3, swell_from=20)

    assert (rate(SNAPPER, perfect), rate(SNAPPER, blown_out), rate(SNAPPER, flat)) == (5, 3, 1)


def test_tide_events_are_local_extremes() -> None:
    levels = [0.0, 0.4, 0.8, 0.6, 0.2, -0.3, -0.1, 0.3]
    hours = [hour(f"2026-10-08T{h:02d}:00", sea_level_m=lv) for h, lv in enumerate(levels)]

    assert [(e["time"], e["kind"]) for e in tide_events(hours)] == [
        ("2026-10-08 02:00", "high"), ("2026-10-08 05:00", "low"),
    ]


def test_windows_pick_the_best_hour_per_part_of_the_day() -> None:
    hours = [
        hour("2026-10-08T05:00", wind_kn=15, wind_from=60, sea_level_m=0.1),
        hour("2026-10-08T07:00", wind_kn=4, wind_from=250, sea_level_m=0.3),
        hour("2026-10-08T15:00", wind_kn=20, wind_from=60, sea_level_m=0.5),
    ]

    morning, afternoon = windows(SNAPPER, hours)

    assert (morning["window"], morning["time"], morning["wind"]) == ("morning", "07:00", "offshore")
    assert morning["tide"] == "rising"
    assert morning["swell_ft"] == 3.3
    assert afternoon["window"] == "afternoon"


def payloads(swell: list[float | None]) -> dict[str, dict[str, Any]]:
    times = [f"2026-10-08T{h:02d}:00" for h in range(len(swell))]
    marine = {"hourly": {"time": times, "swell_wave_height": swell,
                         "swell_wave_period": [9.0] * len(swell),
                         "swell_wave_direction": [100.0] * len(swell),
                         "sea_level_height_msl": [0.1] * len(swell)}}
    weather = {"hourly": {"time": times, "wind_speed_10m": [5.0] * len(swell),
                          "wind_direction_10m": [250.0] * len(swell)}}
    return {"marine": marine, "weather": weather}


def client(data: dict[str, dict[str, Any]], status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        key = "marine" if str(request.url).startswith(MARINE_URL) else "weather"
        return httpx.Response(status, json=data[key])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_skips_hours_with_gaps() -> None:
    hours = await fetch_hours(client(payloads([1.0, None, 1.2])), SNAPPER, days=1,
                              timezone="Australia/Brisbane")

    assert [h.time.hour for h in hours] == [0, 2]


async def test_fetch_reports_http_failures() -> None:
    with pytest.raises(ForecastError):
        await fetch_hours(client(payloads([1.0]), status=502), SNAPPER, days=1,
                          timezone="Australia/Brisbane")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_surf_forecast.py -q`
Expected: ERROR, no module `coach.modules.surf.forecast`.

- [ ] **Step 3: Implement**

`backend/src/coach/modules/surf/forecast.py`:

```python
"""Open-Meteo forecasts, rated against a spot's profile. Every number is an estimate."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FT_PER_M = 3.28084
ESTIMATE_NOTE = (
    "Estimates from Open-Meteo's regional model: nearby spots share the same swell and tide "
    "numbers; ratings come from each spot's profile (swell direction, offshore wind)."
)
_POINTS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
_WINDOWS = (("morning", 5, 9), ("midday", 10, 13), ("afternoon", 14, 18))

type WindRelation = Literal["offshore", "cross-shore", "onshore", "unknown"]


class ForecastError(RuntimeError):
    """Open-Meteo could not be reached or answered with an error."""


@dataclass(frozen=True, slots=True)
class Spot:
    """What the rating needs to know about a spot."""

    name: str
    latitude: float
    longitude: float
    swell_from: tuple[int, int] | None
    offshore_from: tuple[int, int] | None
    min_swell_m: float | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Spot":
        def pair(lo: Any, hi: Any) -> tuple[int, int] | None:
            return (int(lo), int(hi)) if lo is not None and hi is not None else None

        return cls(
            name=row["name"],
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            swell_from=pair(row["swell_from_min"], row["swell_from_max"]),
            offshore_from=pair(row["offshore_from_min"], row["offshore_from_max"]),
            min_swell_m=float(row["min_swell_m"]) if row["min_swell_m"] is not None else None,
        )


@dataclass(frozen=True, slots=True)
class Hour:
    """One forecast hour, local time."""

    time: datetime
    swell_m: float
    period_s: float
    swell_from: float
    wind_kn: float
    wind_from: float
    sea_level_m: float | None


def compass(degrees: float) -> str:
    """16-point compass name."""
    return _POINTS[round(degrees / 22.5) % 16]


def in_range(degrees: float, lo: int, hi: int) -> bool:
    """Whether a direction lies in [lo, hi], wrapping past north when lo > hi."""
    d = degrees % 360
    return lo <= d <= hi if lo <= hi else d >= lo or d <= hi


def angle_between(a: float, b: float) -> float:
    """Smallest angle between two directions."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)


def _centre(lo: int, hi: int) -> float:
    span = (hi - lo) % 360
    return (lo + span / 2) % 360


def wind_relation(spot: Spot, wind_from: float) -> WindRelation:
    """Offshore within 45 degrees of the spot's offshore centre, onshore beyond 135."""
    if spot.offshore_from is None:
        return "unknown"
    gap = angle_between(wind_from, _centre(*spot.offshore_from))
    if gap <= 45:
        return "offshore"
    return "onshore" if gap >= 135 else "cross-shore"


def rate(spot: Spot, hour: Hour) -> int:
    """0 to 5: size, period, swell direction and wind, all against the spot's profile."""
    score = 0
    if hour.swell_m >= (spot.min_swell_m or 0.5):
        score += 2
        if hour.period_s >= 10:
            score += 1
    if spot.swell_from is None or in_range(hour.swell_from, *spot.swell_from):
        score += 1
    relation = wind_relation(spot, hour.wind_from)
    if relation == "offshore" or hour.wind_kn < 6:
        score += 1
    elif relation == "onshore" and hour.wind_kn >= 12:
        score -= 1
    return max(0, min(5, score))


def tide_events(hours: list[Hour]) -> list[dict[str, Any]]:
    """Highs and lows as local extremes of the hourly sea level."""
    levels = [(h.time, h.sea_level_m) for h in hours if h.sea_level_m is not None]
    events = []
    for (_, before), (at, level), (_, after) in zip(levels, levels[1:], levels[2:], strict=False):
        if before < level >= after:
            kind = "high"
        elif before > level <= after:
            kind = "low"
        else:
            continue
        events.append({"time": f"{at:%Y-%m-%d %H:%M}", "kind": kind, "sea_level_m": level})
    return events


def _tide_trend(hours: list[Hour], at: Hour) -> str:
    position = hours.index(at)
    if at.sea_level_m is None:
        return "unknown"
    following = next((h for h in hours[position + 1 :] if h.sea_level_m is not None), None)
    previous = next((h for h in reversed(hours[:position]) if h.sea_level_m is not None), None)
    other = following or previous
    if other is None or other.sea_level_m is None:
        return "unknown"
    rising = other.sea_level_m > at.sea_level_m if following else other.sea_level_m < at.sea_level_m
    return "rising" if rising else "falling"


def windows(spot: Spot, hours: list[Hour]) -> list[dict[str, Any]]:
    """The best hour of each morning, midday and afternoon, day by day."""
    out = []
    for day in sorted({h.time.date() for h in hours}):
        for name, start, end in _WINDOWS:
            candidates = [h for h in hours if h.time.date() == day and start <= h.time.hour <= end]
            if not candidates:
                continue
            best = max(candidates, key=lambda h: (rate(spot, h), -h.time.hour))
            out.append({
                "day": f"{day:%a %d %b}",
                "window": name,
                "time": f"{best.time:%H:%M}",
                "swell_m": round(best.swell_m, 1),
                "swell_ft": round(best.swell_m * FT_PER_M, 1),
                "period_s": round(best.period_s),
                "swell_from": compass(best.swell_from),
                "wind_kn": round(best.wind_kn),
                "wind_from": compass(best.wind_from),
                "wind": wind_relation(spot, best.wind_from),
                "tide": _tide_trend(hours, best),
                "rating": rate(spot, best),
            })
    return out


async def fetch_hours(
    http: httpx.AsyncClient, spot: Spot, *, days: int, timezone: str
) -> list[Hour]:
    """Hourly swell, wind and sea level for a spot; hours with gaps are skipped."""
    common = {"latitude": spot.latitude, "longitude": spot.longitude,
              "timezone": timezone, "forecast_days": days}
    try:
        marine = await http.get(MARINE_URL, params={**common, "hourly": (
            "swell_wave_height,swell_wave_period,swell_wave_direction,sea_level_height_msl")})
        weather = await http.get(WEATHER_URL, params={
            **common, "hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "kn"})
        marine.raise_for_status()
        weather.raise_for_status()
    except httpx.HTTPError as err:
        raise ForecastError(f"Open-Meteo is unavailable ({type(err).__name__})") from err
    m, w = marine.json()["hourly"], weather.json()["hourly"]
    wind = dict(zip(w["time"], zip(w["wind_speed_10m"], w["wind_direction_10m"], strict=True),
                    strict=True))
    hours = []
    for i, at in enumerate(m["time"]):
        swell, period, direction = (m["swell_wave_height"][i], m["swell_wave_period"][i],
                                    m["swell_wave_direction"][i])
        speed, wind_from = wind.get(at, (None, None))
        if None in (swell, period, direction, speed, wind_from):
            continue
        hours.append(Hour(time=datetime.fromisoformat(at), swell_m=swell, period_s=period,
                          swell_from=direction, wind_kn=speed, wind_from=wind_from,
                          sea_level_m=m["sea_level_height_msl"][i]))
    return hours
```

- [ ] **Step 4: Run tests, gate, commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass. If the hand-computed expectations in `test_rating_...` or `test_windows_...` disagree with the stated rules, recompute them from the rules (the rules are the spec) and fix the test, not the rules; ledger it.

```bash
git add backend && git commit -m "feat: rate Open-Meteo forecasts against each spot's profile"
```

---

### Task 4: `get_surf_forecast` and `surf_history`

**Files:**
- Create: `backend/src/coach/modules/surf/repo.py`, `backend/src/coach/modules/surf/tools.py`
- Modify: `backend/src/coach/modules/surf/module.py`
- Test: `backend/tests/test_surf_tools.py`

**Interfaces:**
- Consumes: `fetch_hours`, `windows`, `tide_events`, `Spot`, `ESTIMATE_NOTE`, `ForecastError` (Task 3); `resolve_spot`, `list_spots`, `seed_spots` (Task 2); `CoachContext.http` (Task 1); `history_window` (core).
- Produces: tools `get_surf_forecast(spot: str | None, days: 1..3 = 2)` and `surf_history(spot: str | None, days: 1..365 = 90)`; `repo.surf_sessions(conn, athlete, *, since, spot_id=None) -> list[dict]`; `SurfModule.tools() == [get_surf_forecast, surf_history]` for now.

`get_surf_forecast` returns JSON `{"note": ESTIMATE_NOTE, "spots": [{"name", "windows": [...], "tides": [...]}]}` for one spot or every favourite; an unknown spot name returns `{"error": "unknown spot ...", "known_spots": [...]}`; `ForecastError` returns `{"error": "..."}` (the turn continues).
`surf_history` returns per spot: `sessions`, `last` (local date), `avg_waves`, and the `best` session (most waves) with heights, wind, tide and date.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_surf_tools.py` (shared helpers reused by Task 5):

```python
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_session
from coach.modules.surf.forecast import MARINE_URL
from coach.modules.surf.module import SurfModule
from coach.modules.surf.seed import seed_spots
from coach.modules.surf.spots import SPOTS_PATH, load_spots, resolve_spot
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 7, 21, 0, tzinfo=UTC)  # Thursday 07:00 in Brisbane
SURF = Registry([SurfModule()])


def forecast_http(status: int = 200) -> httpx.AsyncClient:
    times = [f"2026-10-08T{h:02d}:00" for h in range(24)]
    marine = {"hourly": {"time": times, "swell_wave_height": [1.1] * 24,
                         "swell_wave_period": [10.0] * 24,
                         "swell_wave_direction": [110.0] * 24,
                         "sea_level_height_msl": [((h - 6) % 12) / 10 for h in range(24)]}}
    weather = {"hourly": {"time": times, "wind_speed_10m": [5.0] * 8 + [15.0] * 16,
                          "wind_direction_10m": [250.0] * 8 + [60.0] * 16}}

    def handler(request: httpx.Request) -> httpx.Response:
        body = marine if str(request.url).startswith(MARINE_URL) else weather
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def seeded(pool: Pool, athlete: Athlete) -> None:
    async with pool.connection() as conn:
        await seed_spots(conn, athlete, load_spots(SPOTS_PATH))


def ctx(athlete: Athlete, pool: Pool, http: httpx.AsyncClient | None = None) -> CoachContext:
    return CoachContext(athlete=athlete, pool=pool, registry=SURF, now=lambda: NOW,
                        http=http or forecast_http())


async def call_tool(context: CoachContext, name: str, args: dict[str, Any]) -> str:
    model = scripted(
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "s1"}]), "ok"
    )
    out = await build_graph(model, SURF).ainvoke(
        {"messages": [HumanMessage("surf")]}, context=context
    )
    return next(m.text for m in out["messages"] if isinstance(m, ToolMessage))


async def test_forecast_for_one_spot_rates_the_morning_best(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(ctx(athlete, pool), "get_surf_forecast",
                                        {"spot": "snapper", "days": 1}))

    [snapper] = result["spots"]
    assert snapper["name"] == "Snapper Rocks"
    morning = snapper["windows"][0]
    assert (morning["window"], morning["wind"], morning["rating"]) == ("morning", "offshore", 5)
    assert snapper["tides"]
    assert "regional" in result["note"]


async def test_forecast_without_a_spot_covers_every_favourite(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(ctx(athlete, pool), "get_surf_forecast", {"days": 1}))

    assert {s["name"] for s in result["spots"]} == {
        "Burleigh Heads", "Snapper Rocks", "Currumbin Alley", "Duranbah",
    }


async def test_forecast_for_an_unknown_spot_lists_the_known_ones(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(ctx(athlete, pool), "get_surf_forecast",
                                        {"spot": "pipeline"}))

    assert "unknown spot" in result["error"]
    assert "Duranbah" in result["known_spots"]


async def test_forecast_outage_is_reported_not_raised(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(ctx(athlete, pool, forecast_http(502)),
                                        "get_surf_forecast", {"spot": "burleigh"}))

    assert "unavailable" in result["error"]


async def test_history_groups_sessions_by_spot(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)
    async with pool.connection() as conn:
        burleigh = await resolve_spot(conn, athlete, "burleigh")
        assert burleigh is not None
        for days_ago, waves in ((3, 12), (10, 6)):
            session_id = await create_session(conn, athlete, discipline="surf",
                                              started_at=NOW - timedelta(days=days_ago))
            await conn.execute(
                "insert into surf_details (session_id, spot_id, waves_caught, "
                "wave_height_min_ft, wave_height_max_ft) values (%s, %s, %s, 3, 4)",
                (session_id, burleigh["id"], waves),
            )

    result = json.loads(await call_tool(ctx(athlete, pool), "surf_history", {}))

    [spot] = result["spots"]
    assert (spot["spot"], spot["sessions"], spot["avg_waves"]) == ("Burleigh Heads", 2, 9.0)
    assert spot["best"]["waves_caught"] == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_surf_tools.py -q`
Expected: FAIL (tools not bound).

- [ ] **Step 3: Implement**

`backend/src/coach/modules/surf/repo.py`:

```python
"""SQL for the surf tables."""

from datetime import datetime
from typing import Any
from uuid import UUID

from coach.core.db import Connection
from coach.core.models import Athlete


async def surf_sessions(
    conn: Connection, athlete: Athlete, *, since: datetime, spot_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Surf sessions since a moment with their details, newest first, times local."""
    cur = await conn.execute(
        "select s.id, (s.started_at at time zone %(tz)s) as started_at, s.duration_min, "
        "sp.name as spot, d.wave_height_min_ft, d.wave_height_max_ft, d.wind, d.tide, "
        "d.waves_caught, d.board from sessions s "
        "join surf_details d on d.session_id = s.id "
        "left join surf_spots sp on sp.id = d.spot_id "
        "where s.athlete_id = %(athlete_id)s and s.started_at >= %(since)s "
        "and (%(spot_id)s::uuid is null or d.spot_id = %(spot_id)s) "
        "order by s.started_at desc",
        {"tz": athlete.timezone, "athlete_id": athlete.id, "since": since, "spot_id": spot_id},
    )
    return await cur.fetchall()


async def insert_details(conn: Connection, session_id: UUID, details: dict[str, Any]) -> None:
    """The surf part of a logged session."""
    await conn.execute(
        "insert into surf_details (session_id, spot_id, wave_height_min_ft, wave_height_max_ft, "
        "wind, tide, waves_caught, board, notes) values (%(session_id)s, %(spot_id)s, "
        "%(wave_height_min_ft)s, %(wave_height_max_ft)s, %(wind)s, %(tide)s, %(waves_caught)s, "
        "%(board)s, %(notes)s)",
        {"session_id": session_id, **details},
    )
```

`backend/src/coach/modules/surf/tools.py`:

```python
"""Surf tools bound to the agent."""

import json
from datetime import timedelta
from typing import Annotated, Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from coach.core.context import CoachContext
from coach.modules.surf.forecast import (
    ESTIMATE_NOTE,
    ForecastError,
    Spot,
    fetch_hours,
    tide_events,
    windows,
)
from coach.modules.surf.repo import surf_sessions
from coach.modules.surf.spots import list_spots, resolve_spot


def _dump(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False)


@tool
async def get_surf_forecast(
    runtime: ToolRuntime[CoachContext],
    spot: Annotated[str | None, Field(description="Spot as the athlete said it; omit for all favourites")] = None,
    days: Annotated[int, Field(ge=1, le=3)] = 2,
) -> str:
    """Swell, wind and tide for the next days at one spot or every favourite, with each
    morning, midday and afternoon rated 0 to 5 for that spot. Estimates, not a surf report."""
    ctx = runtime.context
    if ctx.http is None:
        raise RuntimeError("no HTTP client in the context")
    async with ctx.pool.connection() as conn:
        if spot:
            found = await resolve_spot(conn, ctx.athlete, spot)
            if found is None:
                known = [s["name"] for s in await list_spots(conn, ctx.athlete)]
                return _dump({"error": f"unknown spot {spot!r}", "known_spots": known})
            rows = [found]
        else:
            rows = [s for s in await list_spots(conn, ctx.athlete) if s["favourite"]]
    report = []
    for row in rows:
        target = Spot.from_row(row)
        try:
            hours = await fetch_hours(ctx.http, target, days=days, timezone=ctx.athlete.timezone)
        except ForecastError as err:
            return _dump({"error": str(err)})
        report.append({"name": target.name, "windows": windows(target, hours),
                       "tides": tide_events(hours)})
    return _dump({"note": ESTIMATE_NOTE, "spots": report})


@tool
async def surf_history(
    runtime: ToolRuntime[CoachContext],
    spot: Annotated[str | None, Field(description="Spot as said; omit for every spot")] = None,
    days: Annotated[int, Field(ge=1, le=365)] = 90,
) -> str:
    """Surf sessions per spot over the last days: count, last session, average waves caught,
    and the best session (most waves) with its conditions."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        spot_id = None
        if spot:
            found = await resolve_spot(conn, ctx.athlete, spot)
            if found is None:
                return _dump({"error": f"unknown spot {spot!r}"})
            spot_id = found["id"]
        sessions = await surf_sessions(
            conn, ctx.athlete, since=ctx.now() - timedelta(days=days), spot_id=spot_id
        )
    by_spot: dict[str, list[dict[str, Any]]] = {}
    for session in sessions:
        by_spot.setdefault(session["spot"] or "unknown spot", []).append(session)
    report = []
    for name, rows in by_spot.items():
        waves = [r["waves_caught"] for r in rows if r["waves_caught"] is not None]
        best = max(rows, key=lambda r: r["waves_caught"] or 0)
        report.append({
            "spot": name,
            "sessions": len(rows),
            "last": rows[0]["started_at"],
            "avg_waves": round(sum(waves) / len(waves), 1) if waves else None,
            "best": {k: best[k] for k in ("started_at", "wave_height_min_ft",
                                          "wave_height_max_ft", "wind", "tide", "waves_caught")},
        })
    return _dump({"spots": report})
```

`SurfModule.tools()` returns `[get_surf_forecast, surf_history]`.

- [ ] **Step 4: Run tests, gate, commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`

```bash
git add backend && git commit -m "feat: add surf forecasts per spot and surf history"
```

---

### Task 5: `log_surf_session` with the unknown-spot interrupt

**Files:**
- Modify: `backend/src/coach/modules/surf/tools.py`, `backend/src/coach/modules/surf/module.py`
- Test: `backend/tests/test_surf_tools.py` (append)

**Interfaces:**
- Consumes: `resolve_spot`, `list_spots`, `create_spot`, `add_alias` (Task 2); `insert_details` (Task 4); `create_session`, `ReplyButton` (core); interrupt resume payload `{"text": str, "location": {"latitude", "longitude"} | None}` (Task 1).
- Produces: `log_surf_session(spot, started_at, duration_min, rpe, wave_height_min_ft, wave_height_max_ft, wind, tide, waves_caught, board, notes)` with `spot` required; `SurfModule.tools() == [log_surf_session, get_surf_forecast, surf_history]`.

Flow: resolve the spot (no writes). If unknown, `interrupt({"question": "I don't know <spot> yet. Send me a location pin for it, or tell me which of your spots it was: <names>."})`. On resume (the tool runs again from the top): a `location` creates the spot under the name said; text naming a saved spot logs there and adds the said name as an alias; anything else logs without a spot. Then one transaction writes the `sessions` row (discipline `surf`, summary `Surf at <spot>`) and `surf_details`, and an Undo button is appended. Naive `started_at` is the athlete's local time: gym's private `_started_at` helper moves to `CoachContext.local_to_utc(value)` so both modules share it.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_surf_tools.py`:

```python
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.models import Location
from coach.core.turn import run_turn


async def surf_rows(pool: Pool, athlete: Athlete) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select s.id, s.started_at, s.duration_min, s.summary, sp.name as spot, "
            "d.wave_height_min_ft, d.wave_height_max_ft, d.waves_caught, d.notes "
            "from sessions s join surf_details d on d.session_id = s.id "
            "left join surf_spots sp on sp.id = d.spot_id where s.athlete_id = %s",
            (athlete.id,),
        )
        return await cur.fetchall()


def log_call(**args: Any) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": "log_surf_session", "args": args, "id": "l1"}]
    )


async def test_logs_a_session_at_a_known_spot(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)
    turn = ctx(athlete, pool)

    await call_tool(turn, "log_surf_session", {
        "spot": "burleigh", "started_at": "2026-10-08T06:00:00", "duration_min": 120,
        "wave_height_min_ft": 3, "wave_height_max_ft": 4, "waves_caught": 12,
        "notes": "struggled on my backhand",
    })

    [row] = await surf_rows(pool, athlete)
    assert (row["spot"], row["waves_caught"], row["notes"]) == (
        "Burleigh Heads", 12, "struggled on my backhand")
    assert row["started_at"] == datetime(2026, 10, 7, 20, 0, tzinfo=UTC)
    assert turn.reply_buttons[0].data == f"undo:{row['id']}"


async def test_an_unknown_spot_asks_for_a_pin_and_creates_it(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    model = scripted(log_call(spot="Kirra", waves_caught=7), "Logged at Kirra.")
    graph = build_graph(model, SURF, InMemorySaver())
    turn = ctx(athlete, pool)

    asked = await run_turn(graph, turn, "kirra this arvo, 7 waves", model_name="m")
    done = await run_turn(graph, turn, "(shared a location)", model_name="m",
                          location=Location(-28.167, 153.531))

    assert "location pin" in asked.reply
    assert done.reply == "Logged at Kirra."
    [row] = await surf_rows(pool, athlete)
    assert (row["spot"], row["waves_caught"]) == ("Kirra", 7)


async def test_naming_a_saved_spot_answers_the_question_and_learns_the_alias(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    model = scripted(log_call(spot="the point"), "Logged at Burleigh.")
    graph = build_graph(model, SURF, InMemorySaver())
    turn = ctx(athlete, pool)

    await run_turn(graph, turn, "the point this morning", model_name="m")
    await run_turn(graph, turn, "burleigh", model_name="m")

    [row] = await surf_rows(pool, athlete)
    assert row["spot"] == "Burleigh Heads"
    async with pool.connection() as conn:
        assert (await resolve_spot(conn, athlete, "the point")) is not None


async def test_an_unrelated_reply_still_logs_the_session_without_a_spot(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    model = scripted(log_call(spot="somewhere up north", waves_caught=4), "Logged.")
    graph = build_graph(model, SURF, InMemorySaver())
    turn = ctx(athlete, pool)

    await run_turn(graph, turn, "surfed somewhere up north", model_name="m")
    await run_turn(graph, turn, "how much did I train this week?", model_name="m")

    [row] = await surf_rows(pool, athlete)
    assert (row["spot"], row["waves_caught"]) == (None, 4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_surf_tools.py -q`
Expected: the four new tests FAIL (no `log_surf_session`).

- [ ] **Step 3: Implement**

`coach/core/context.py`, add to `CoachContext`:

```python
    def local_to_utc(self, value: datetime | None) -> datetime:
        """None is now; a time without a zone is the athlete's local time."""
        if value is None:
            return self.now()
        if value.tzinfo is None:
            return value.replace(tzinfo=ZoneInfo(self.athlete.timezone)).astimezone(UTC)
        return value
```

and replace gym's `_started_at(started_at, ctx)` with `ctx.local_to_utc(started_at)` (delete `_started_at`).

Append to `surf/tools.py`:

```python
from datetime import datetime

from langgraph.types import interrupt

from coach.core.models import Location, ReplyButton
from coach.core.repo import create_session
from coach.modules.surf.repo import insert_details
from coach.modules.surf.spots import add_alias, create_spot


@tool
async def log_surf_session(
    runtime: ToolRuntime[CoachContext],
    spot: Annotated[str, Field(description="Spot as the athlete said it, e.g. 'Burleigh'")],
    started_at: Annotated[datetime | None, Field(description="Local date and time; omit for now")] = None,
    duration_min: Annotated[int | None, Field(ge=1, le=600)] = None,
    rpe: Annotated[int | None, Field(ge=1, le=10)] = None,
    wave_height_min_ft: Annotated[float | None, Field(ge=0, le=60)] = None,
    wave_height_max_ft: Annotated[float | None, Field(ge=0, le=60)] = None,
    wind: Annotated[str | None, Field(description="As said: offshore, onshore, light...")] = None,
    tide: Annotated[str | None, Field(description="As said: low, mid, high, pushing...")] = None,
    waves_caught: Annotated[int | None, Field(ge=0, le=500)] = None,
    board: Annotated[str | None, Field(description="As said, e.g. 6'0 shortboard")] = None,
    notes: Annotated[str | None, Field(description="Anything else, in their words")] = None,
) -> str:
    """Log one surf session. Fill only what the athlete said; never guess heights or waves.
    For an unknown spot the athlete is asked for a location pin first."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        found = await resolve_spot(conn, ctx.athlete, spot)
        names = [s["name"] for s in await list_spots(conn, ctx.athlete)]
    if found is None:
        answer = interrupt({"question": (
            f"I don't know {spot} yet. Send me a location pin for it, or tell me which of your "
            f"spots it was: {', '.join(names) or 'none saved yet'}."
        )})
        found = await _spot_from_answer(ctx, spot, answer)
    details = {
        "spot_id": found["id"] if found else None,
        "wave_height_min_ft": wave_height_min_ft, "wave_height_max_ft": wave_height_max_ft,
        "wind": wind, "tide": tide, "waves_caught": waves_caught, "board": board, "notes": notes,
    }
    place = found["name"] if found else spot
    async with ctx.pool.connection() as conn, conn.transaction():
        session_id = await create_session(
            conn, ctx.athlete, discipline="surf", started_at=ctx.local_to_utc(started_at),
            duration_min=duration_min, rpe=rpe, summary=f"Surf at {place}",
        )
        await insert_details(conn, session_id, details)
    ctx.reply_buttons.append(ReplyButton(text="Undo", data=f"undo:{session_id}"))
    saved = "" if found else " (no saved spot: logged without one)"
    return f"Logged surf at {place}{saved}. Details: {_dump({k: v for k, v in details.items() if v is not None and k != 'spot_id'})}"


async def _spot_from_answer(
    ctx: CoachContext, said: str, answer: dict[str, Any]
) -> dict[str, Any] | None:
    location = answer.get("location")
    async with ctx.pool.connection() as conn:
        if location:
            return await create_spot(
                conn, ctx.athlete, said.strip().title(),
                Location(location["latitude"], location["longitude"]),
            )
        named = await resolve_spot(conn, ctx.athlete, answer.get("text") or "")
        if named is not None:
            await add_alias(conn, named["id"], said.strip())
        return named
```

`SurfModule.tools()` returns `[log_surf_session, get_surf_forecast, surf_history]`.

- [ ] **Step 4: Run tests, gate, commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: all pass (long lines in the tool signature are wrapped by `ruff format`; fix E501 by wrapping descriptions).

```bash
git add backend && git commit -m "feat: log surf sessions, asking for a location pin when the spot is new"
```

---

### Task 6: Surf context, prompt and eval set

**Files:**
- Create: `backend/src/coach/modules/surf/prompt.md`, `backend/src/coach/modules/surf/evals/extraction.yaml`, `backend/src/coach/modules/surf/evals/recordings/extraction.json` (recorded)
- Modify: `backend/src/coach/modules/surf/module.py`
- Test: `backend/tests/test_surf_tools.py` (append), `backend/tests/test_evals.py`

**Interfaces:**
- Produces: `SurfModule.prompt()` (`prompt.md`, which names the shipped favourites; the athlete's own spot list needs the database, so the tools carry it); `SurfModule.context(conn, athlete)`: "Last surf 2 days ago at Burleigh Heads (3-4 ft, 12 waves); 3 surfs in the last 14 days." or "" with no surfs; `SurfModule.evals() == [HERE / "evals" / "extraction.yaml"]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_surf_tools.py`:

```python
async def test_context_summarises_recent_surfing(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)
    # context() reads the real clock, so log relative to it.
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await call_tool(ctx(athlete, pool), "log_surf_session", {
        "spot": "burleigh", "started_at": yesterday,
        "wave_height_min_ft": 3, "wave_height_max_ft": 4, "waves_caught": 12,
    })

    async with pool.connection() as conn:
        line = await SurfModule().context(conn, athlete)

    assert line.startswith("Last surf ")
    assert "Burleigh Heads (3-4 ft, 12 waves)" in line


def test_prompt_explains_feet_spots_and_estimates() -> None:
    prompt = SurfModule().prompt(Athlete(id=UUID(int=1), name="J", timezone="Australia/Brisbane", telegram_chat_id=1))

    assert "feet" in prompt and "Duranbah" in prompt and "estimate" in prompt
```

(import `UUID`). In `test_evals.py`, add:

```python
def test_the_surf_set_has_fifteen_cases() -> None:
    from coach.modules.surf.module import SurfModule

    [path] = SurfModule().evals()
    assert len(load_set(path).cases) == 15
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

`backend/src/coach/modules/surf/prompt.md`:

```markdown
Surf module.
The athlete surfs the Gold Coast. Their saved spots include Burleigh Heads (Burleigh), Snapper Rocks (Snapper, Superbank), Currumbin Alley (the Alley) and Duranbah (D'Bah).
Wave heights are in feet, as the athlete says them ("3-4 ft"); forecast swell is in metres with feet alongside.
When the athlete says they surfed, call log_surf_session once with the spot as they said it. Fill only what they said: never guess heights, waves caught, wind or tide. If the spot is new, the tool asks them for a location pin; relay that and wait.
For "where should I surf" questions call get_surf_forecast without a spot and compare the ratings; say which window and why (size, period, wind relative to the spot). Forecasts are estimates from a regional model: say so, and do not promise conditions.
For past sessions per spot use surf_history; for totals across sports use query_history.
After logging, mention they can undo it with the button under your reply.
```

`module.py`: `PROMPT = (HERE / "prompt.md").read_text(...).strip()`; `prompt()` returns `PROMPT`; `context()`:

```python
    async def context(self, conn: Connection, athlete: Athlete) -> str:
        now = datetime.now(UTC)
        recent = await surf_sessions(conn, athlete, since=now - timedelta(days=14))
        if not recent:
            return ""
        last = recent[0]
        local_now = now.astimezone(ZoneInfo(athlete.timezone)).replace(tzinfo=None)
        days_ago = (local_now.date() - last["started_at"].date()).days
        when = "today" if days_ago == 0 else "yesterday" if days_ago == 1 else f"{days_ago} days ago"
        size = (
            f"{last['wave_height_min_ft']:g}-{last['wave_height_max_ft']:g} ft"
            if last["wave_height_min_ft"] is not None and last["wave_height_max_ft"] is not None
            else "size not logged"
        )
        waves = f", {last['waves_caught']} waves" if last["waves_caught"] is not None else ""
        return (
            f"Last surf {when} at {last['spot'] or 'an unsaved spot'} ({size}{waves}); "
            f"{len(recent)} surfs in the last 14 days."
        )
```

`evals()` returns `[HERE / "evals" / "extraction.yaml"]`.

`backend/src/coach/modules/surf/evals/extraction.yaml`:

```yaml
# Synthetic surf logging messages. expected: the log_surf_session arguments to extract;
# null means the tool must not be called. Spot names compare as said.
tool: log_surf_session
cases:
  - id: surf-01
    input: Burleigh this morning, 2 hours, 3-4 ft, caught 12, struggled on my backhand
    expected: {spot: Burleigh, duration_min: 120, wave_height_min_ft: 3, wave_height_max_ft: 4, waves_caught: 12}
  - id: surf-02
    input: surfed snapper for an hour, 2-3ft and onshore, only got 5
    expected: {spot: snapper, duration_min: 60, wave_height_min_ft: 2, wave_height_max_ft: 3, wind: onshore, waves_caught: 5}
  - id: surf-03
    input: dbah 90 mins on the 6'0, 8 waves
    expected: {spot: dbah, duration_min: 90, board: 6'0, waves_caught: 8}
  - id: surf-04
    input: quick 45 min at the alley, mid tide, 2ft
    expected: {spot: the alley, duration_min: 45, tide: mid, wave_height_max_ft: 2}
  - id: surf-05
    input: Snapper was pumping, 4-6ft offshore, 3 hours, rpe 8
    expected: {spot: Snapper, wave_height_min_ft: 4, wave_height_max_ft: 6, wind: offshore, duration_min: 180, rpe: 8}
  - id: surf-06
    input: surfed currumbin, caught 20 waves on the longboard
    expected: {spot: currumbin, waves_caught: 20, board: longboard}
  - id: surf-07
    input: Burleigh 1.5 hours, 3ft, low tide, 10 waves
    expected: {spot: Burleigh, duration_min: 90, wave_height_max_ft: 3, tide: low, waves_caught: 10}
  - id: surf-08
    input: kirra this arvo, 7 waves
    expected: {spot: kirra, waves_caught: 7}
  - id: surf-09
    input: Superbank 2 hours, crowded, 6 waves
    expected: {spot: Superbank, duration_min: 120, waves_caught: 6}
  - id: surf-10
    input: dawny at D'Bah, 3-4ft, light offshore, 15 waves
    expected: {spot: D'Bah, wave_height_min_ft: 3, wave_height_max_ft: 4, wind: light offshore, waves_caught: 15}
  - id: surf-11
    input: an hour at the point, 2-3 ft, rpe 6
    expected: {spot: the point, duration_min: 60, wave_height_min_ft: 2, wave_height_max_ft: 3, rpe: 6}
  - id: surf-12
    input: surfed snapper on the 5'10, high tide, 1 hour
    expected: {spot: snapper, board: 5'10, tide: high, duration_min: 60}
  - id: surf-13
    input: 2 hour surf at Currumbin Alley
    expected: {spot: Currumbin Alley, duration_min: 120}
  - id: surf-14
    input: where should I surf tomorrow morning?
    expected: null
  - id: surf-15
    input: how many waves did I catch at burleigh this month?
    expected: null
```

- [ ] **Step 4: Run tests, gate**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`

- [ ] **Step 5: Record both eval sets live and replay**

The prompt and tools changed, so both recordings are stale. This sends 31 short prompts to Claude Haiku (under $0.10).
Run: `cd backend && uv run python -m coach.core.evals --mode live --record --save-run`, then `uv run python -m coach.core.evals`.
Expected: both sets print scores at or above 0.80 tool accuracy and recall; replay exits 0. If surf falls below the bar, read the misses, fix the prompt or tool descriptions (not the expectations, unless an expectation contradicts the instructions), re-record, and ledger it.

- [ ] **Step 6: Commit**

```bash
git add backend && git commit -m "feat: add the surf prompt, context and first surf eval set"
```

---

### Task 7: Seed the athlete's spots, docs, end to end

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `README.md`

- [ ] **Step 1: Seed locally**

Run: `cd backend && uv run python -m coach.modules.surf.seed --chat-id 8952884287`
Expected: `Seeded 4 spots for Jean`.

- [ ] **Step 2: Docs**

`docs/ARCHITECTURE.md`: code map (`core/text.py`, surf module files), the interrupt flow (pending interrupt resumed by the next message or pin; the question is the reply), `CoachContext.http`, surf tables, forecast caveat (regional model, profiles), evals across modules (`canonical` hook).
`README.md`: `uv run python -m coach.modules.surf.seed --chat-id <id>`; edit `src/coach/modules/surf/spots.yaml` to correct spot profiles, then re-run the seed.

- [ ] **Step 3: Restart the local bot and verify with the athlete**

Ask the athlete to send: "where should I surf tomorrow morning?", "Burleigh this morning, 2 hours, 3-4 ft, caught 12", then a session at a spot not saved yet (and answer with a location pin), then tap Undo on one log.
Expected: ratings per favourite with a stated estimate caveat; the log reply with an Undo button; the coach asks for a pin and logs after it; Undo answers "Undone.".
Ask the athlete to confirm or correct each spot profile (swell directions, offshore winds, minimum size).

- [ ] **Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md README.md
git commit -m "docs: describe the surf module, interrupts and spot profiles"
```
