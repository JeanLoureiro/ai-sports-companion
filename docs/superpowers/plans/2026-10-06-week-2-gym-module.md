# Week 2: Gym Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The athlete's coach-written dumbbell program lives in the database, the agent can say what the next session is, and "did Treino B, sumo 24 kg, rpe 8" logs a session in one message with an Undo button, scored by the first eval set.

**Architecture:** A `gym` discipline module under `backend/src/coach/modules/gym/` implementing the week 1 `DisciplineModule` protocol: its own SQL migration, an exercise library (`exercises.yaml`, public), program files in YAML (the real program is private and git-ignored, a sample program is public), a seed command, two tools (`get_program`, `log_gym_session`), a prompt fragment and a `context()` summary.
Two small core additions make logging safe: tools can attach inline buttons to the reply (`CoachContext.reply_buttons`), and the handler understands Telegram callback queries so an `undo:<session id>` button deletes the logged session; module tables free their slots through foreign keys, so the core never knows about gym tables.
A core eval harness scores tool-call extraction against each module's eval cases, records live model answers to a committed cassette, and replays them in CI at no cost.

**Tech Stack:** As week 1, plus PyYAML.

**Spec:** `docs/Hybrid Athlete Coach — Project Plan.md` and `docs/ARCHITECTURE.md`.
Decisions taken after the spec, from reading the real program (`docs/trainings/*.pdf`, private):

- The program is 6 weeks of 3 sessions (Treino A, B, C), all dumbbell; progression is tempo (cadência) per week, not phases. So there is no `phase` column; sessions carry `week` and `day_label`, and each prescription carries `rest_s`, `tempo` and `notes`.
- Rows with a rest interval are the `main` block; rows without are the `prep` block (mobility and stability).
- The real program YAML is private (`docs/trainings/`, git-ignored) and seeded from there; the repo ships `programs/sample.yaml` in the same format for tests, CI and the future `/demo` athlete.
- Exercise names are the coach's Portuguese names with English aliases; the coach replies in English.
- Logging reports deviations only: everything not mentioned counts as done as prescribed; the prep block is assumed done.
- Week 4 is transcribed exactly as written.

## Global Constraints

- Everything in week 1's Global Constraints still applies (Python 3.14, uv with `exclude-newer = "7 days"`, ruff + mypy strict + pytest gate, `SecretStr`, no em dashes, no AI attribution in commits, one sentence per line in long Markdown, commit after every task).
- Modules never import each other; the gym module may import from `coach.core`; `coach.core` never imports `coach.modules` except inside `registry.default_registry()` (and, until a second module ships, the eval CLI's normalizer).
- Nothing derived from the private program (the YAML, its content, a generator script) is ever committed; this plan itself contains no program content.
- Local test database: `postgresql://postgres:postgres@127.0.0.1:54422/postgres` (shared with local development; tests must not delete data they did not create).

## Review Focus

1. Running the test suite while the athlete uses the local bot: the athlete's row, thread and logs must survive. Test: Task 1 (manual check with the real athlete row), plus no `truncate` left in `conftest.py`.
2. Undo pressed twice, pressed for someone else's session, or with garbage callback data: deletes at most the athlete's own session once, answers "Nothing to undo." otherwise. Tests: Task 2.
3. "Did Treino B" when every B session is already done: nothing in the program is silently marked; the session is logged as an extra session. Test: Task 5.
4. A time with no zone ("this morning at 7") is the athlete's local time, not UTC. Test: Task 5.
5. An exercise name the library does not know: kept as said and flagged, never dropped and never mapped to the wrong exercise. Test: Task 5.

---

## File Structure

```
.gitignore                                   commit the user's docs/trainings rule
backend/pyproject.toml                       + pyyaml, + types-pyyaml (dev)
backend/src/coach/core/
  models.py                                  + ReplyButton
  context.py                                 + reply_buttons
  telegram.py                                + CallbackQuery, buttons on send_message, answer_callback,
                                               ALLOWED_UPDATES
  repo.py                                    + create_session, undo_session
  handler.py                                 + callback handling, buttons on the reply
  turn.py                                    + note_in_thread
  registry.py                                default_registry() enables GymModule
  evals.py                                   eval harness + `python -m coach.core.evals`
backend/src/coach/modules/gym/
  __init__.py
  module.py                                  GymModule
  library.py                                 ExerciseDef, ExerciseIndex, normalize, library_index
  program.py                                 ProgramDef, load_program
  repo.py                                    gym SQL
  tools.py                                   get_program, log_gym_session, merge_lifts
  seed.py                                    seed_program + `python -m coach.modules.gym.seed`
  prompt.md
  exercises.yaml                             public exercise library
  programs/sample.yaml                       public sample program
  migrations/0001_gym.sql
  evals/extraction.yaml                      15 synthetic logging cases
  evals/recordings/extraction.json           recorded model answers (cassette)
backend/tests/
  conftest.py                                no truncation; all migration dirs
  fakes.py                                   + button tool, registry in make_deps, callback_update
  test_undo.py
  test_gym_seed.py
  test_gym_tools.py
  test_evals.py
.github/workflows/ci.yml                     + replay eval step
docs/ARCHITECTURE.md, README.md              gym module, buttons, evals, seeding
docs/trainings/forca-3x-halter.yaml          PRIVATE, git-ignored, written in Task 6
```

---

### Task 1: Stop the test suite from wiping local data

**Files:**
- Modify: `.gitignore` (commit the existing uncommitted `docs/trainings` line)
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: week 1 `conftest.py`.
- Produces: a `pool` fixture that applies migrations and inserts the `testsport` discipline, and deletes nothing.

This is a test-configuration change, so its check is behavioural rather than a new test.

- [ ] **Step 1: Record the athlete row before**

Run: `psql postgresql://postgres:postgres@127.0.0.1:54422/postgres -Atc "select id from athletes where telegram_chat_id = 8952884287"`
Expected: one uuid (the real local athlete).

- [ ] **Step 2: Remove the truncation**

In `backend/tests/conftest.py`, replace the body of the `pool` fixture after `await migrate_all(...)` with:

```python
    async with pool.connection() as conn:
        # Tests share the local development database: create only, never delete.
        await conn.execute(
            "insert into disciplines (name, label) values ('testsport', 'Test sport') "
            "on conflict (name) do nothing"
        )
    yield pool
    await pool.close()
```

- [ ] **Step 3: Run the suite and check the athlete survived**

Run: `cd backend && uv run pytest -q && psql postgresql://postgres:postgres@127.0.0.1:54422/postgres -Atc "select id from athletes where telegram_chat_id = 8952884287"`
Expected: all tests pass; the same uuid as Step 1.

- [ ] **Step 4: Commit**

```bash
git add .gitignore backend/tests/conftest.py
git commit -m "test: keep the shared local database intact when the suite runs"
```

---

### Task 2: Reply buttons and Undo

**Files:**
- Modify: `backend/src/coach/core/models.py`, `context.py`, `telegram.py`, `repo.py`, `handler.py`, `turn.py`
- Modify: `backend/tests/fakes.py`
- Test: `backend/tests/test_undo.py`

**Interfaces:**
- Consumes: week 1 core.
- Produces:
  - `coach.core.models.ReplyButton(text: str, data: str)` (frozen dataclass; `data` at most 64 bytes, Telegram's callback limit).
  - `CoachContext.reply_buttons: list[ReplyButton]` (default empty list; tools append, the handler sends).
  - `telegram.ALLOWED_UPDATES = ["message", "callback_query"]`; `CallbackQuery(id: str, data: str | None, message: Message | None)`; `Update.callback_query`; `TelegramClient.send_message(chat_id, text, buttons: Sequence[ReplyButton] = ())`; `TelegramClient.answer_callback(callback_id: str, text: str)`.
  - `repo.create_session(conn, athlete, *, discipline, started_at, duration_min=None, rpe=None, summary=None, input_type="text") -> UUID`; `repo.undo_session(conn, athlete, session_id: UUID) -> str | None` (the deleted session's summary, or None).
  - `turn.note_in_thread(graph, athlete, text) -> None`.
  - `handler.UNDO_PREFIX = "undo:"`, `handler.NOTHING_TO_UNDO = "Nothing to undo."`.
  - Test helpers: `fakes.button_tool`, `make_deps(..., registry: Registry | None = None)`, `fakes.callback_update(update_id, chat_id, data)`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/fakes.py` (merge imports into the top block):

```python
from langgraph.prebuilt import ToolRuntime

from coach.core.context import CoachContext
from coach.core.models import ReplyButton


@tool
async def button_tool(label: str, runtime: ToolRuntime[CoachContext]) -> str:
    """Attach a button to the reply."""
    runtime.context.reply_buttons.append(ReplyButton(text=label, data="noop"))
    return "button attached"


def callback_update(update_id: int, chat_id: int, data: str) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb-{update_id}",
            "from": {"id": chat_id, "is_bot": False, "first_name": "T"},
            "data": data,
            "message": {"message_id": 9, "chat": {"id": chat_id, "type": "private"}},
        },
    }
```

Change `make_deps` to take an optional registry:

```python
def make_deps(
    pool: Pool,
    model: FakeChatModel,
    recorder: TelegramRecorder,
    *,
    allowed: list[int],
    registry: Registry | None = None,
) -> Deps:
    ...
    registry = registry or Registry([])
```

(Keep the rest of `make_deps` as it is, using this `registry`.)

`backend/tests/test_undo.py`:

```python
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from coach.core.db import Pool
from coach.core.handler import NOTHING_TO_UNDO, handle_update
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_athlete, create_session
from coach.core.telegram import ALLOWED_UPDATES, Update
from tests.factories import new_chat_id, new_update_id
from tests.fakes import (
    FakeModule,
    TelegramRecorder,
    button_tool,
    callback_update,
    make_deps,
    scripted,
    text_update,
)

pytestmark = pytest.mark.anyio

STARTED = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)


async def a_logged_session(pool: Pool, athlete: Athlete) -> str:
    async with pool.connection() as conn:
        session_id = await create_session(
            conn, athlete, discipline="testsport", started_at=STARTED, summary="Test session"
        )
    return str(session_id)


async def session_exists(pool: Pool, session_id: str) -> bool:
    async with pool.connection() as conn:
        cur = await conn.execute("select 1 from sessions where id = %s", (session_id,))
        return await cur.fetchone() is not None


def test_both_update_types_are_requested() -> None:
    assert ALLOWED_UPDATES == ["message", "callback_query"]


async def test_buttons_go_on_the_last_chunk_only() -> None:
    from coach.core.models import ReplyButton

    recorder = TelegramRecorder()

    await recorder.client().send_message(1, "x" * 5000, [ReplyButton("Undo", "undo:1")])

    payloads = [p for m, p in recorder.calls if m == "sendMessage"]
    assert "reply_markup" not in payloads[0]
    assert payloads[1]["reply_markup"] == {
        "inline_keyboard": [[{"text": "Undo", "callback_data": "undo:1"}]]
    }


async def test_a_tool_can_put_a_button_under_the_reply(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted(
        AIMessage(
            content="",
            tool_calls=[{"name": "button_tool", "args": {"label": "Undo"}, "id": "b1"}],
        ),
        "Logged.",
    )
    deps = make_deps(
        pool, model, recorder, allowed=[athlete.telegram_chat_id],
        registry=Registry([FakeModule(module_tools=[button_tool])]),
    )

    await handle_update(deps, Update.model_validate(
        text_update(new_update_id(), athlete.telegram_chat_id)))

    [reply] = [p for m, p in recorder.calls if m == "sendMessage"]
    assert reply["text"] == "Logged."
    assert reply["reply_markup"]["inline_keyboard"][0][0]["text"] == "Undo"


async def test_undo_deletes_the_session_and_tells_the_thread(
    pool: Pool, athlete: Athlete
) -> None:
    assert athlete.telegram_chat_id is not None
    session_id = await a_logged_session(pool, athlete)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(deps, Update.model_validate(
        callback_update(new_update_id(), athlete.telegram_chat_id, f"undo:{session_id}")))

    assert not await session_exists(pool, session_id)
    assert ("answerCallbackQuery", {"callback_query_id": recorder.calls[0][1]["callback_query_id"],
                                    "text": "Undone."}) in recorder.calls
    assert recorder.sent_texts() == ["Undone: Test session."]
    config: RunnableConfig = {"configurable": {"thread_id": str(athlete.id)}}
    state = await deps.graph.aget_state(config)
    assert state.values["messages"][-1].text == "Undone: Test session."


async def test_undo_twice_only_deletes_once(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    session_id = await a_logged_session(pool, athlete)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    for _ in range(2):
        await handle_update(deps, Update.model_validate(
            callback_update(new_update_id(), athlete.telegram_chat_id, f"undo:{session_id}")))

    answers = [p["text"] for m, p in recorder.calls if m == "answerCallbackQuery"]
    assert answers == ["Undone.", NOTHING_TO_UNDO]


@pytest.mark.parametrize("data", ["undo:not-a-uuid", "something-else"])
async def test_garbage_callback_data_undoes_nothing(
    pool: Pool, athlete: Athlete, data: str
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(deps, Update.model_validate(
        callback_update(new_update_id(), athlete.telegram_chat_id, data)))

    assert [p["text"] for m, p in recorder.calls if m == "answerCallbackQuery"] == [
        NOTHING_TO_UNDO
    ]
    assert recorder.sent_texts() == []


async def test_cannot_undo_someone_elses_session(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    async with pool.connection() as conn:
        other = await create_athlete(conn, name="Other", telegram_chat_id=new_chat_id())
    session_id = await a_logged_session(pool, other)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(deps, Update.model_validate(
        callback_update(new_update_id(), athlete.telegram_chat_id, f"undo:{session_id}")))

    assert await session_exists(pool, session_id)


async def test_callbacks_from_other_chats_are_ignored(pool: Pool, athlete: Athlete) -> None:
    session_id = await a_logged_session(pool, athlete)
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted(), recorder, allowed=[])

    await handle_update(deps, Update.model_validate(
        callback_update(new_update_id(), new_chat_id(), f"undo:{session_id}")))

    assert recorder.calls == []
    assert await session_exists(pool, session_id)
```

Add to `backend/tests/test_repo.py`:

```python
async def test_create_and_undo_a_session(conn: Connection, athlete: Athlete) -> None:
    session_id = await create_session(
        conn, athlete, discipline="testsport", started_at=NOW, duration_min=45, rpe=7,
        summary="Treino A",
    )

    assert await undo_session(conn, athlete, session_id) == "Treino A"
    assert await undo_session(conn, athlete, session_id) is None
```

(import `create_session`, `undo_session` from `coach.core.repo`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_undo.py tests/test_repo.py -q`
Expected: ERROR at import (`ReplyButton`, `create_session`, `ALLOWED_UPDATES` do not exist).

- [ ] **Step 3: Implement the core additions**

`models.py`, append:

```python
@dataclass(frozen=True, slots=True)
class ReplyButton:
    """An inline button under the reply; ``data`` comes back as a callback (max 64 bytes)."""

    text: str
    data: str
```

`context.py`: import `ReplyButton` and add the field after `now`:

```python
    # Tools append; the handler sends them under the reply. Mutable on purpose.
    reply_buttons: list[ReplyButton] = field(default_factory=list)
```

`telegram.py`:

```python
ALLOWED_UPDATES = ["message", "callback_query"]


class CallbackQuery(BaseModel):
    """A tap on an inline button."""

    id: str
    data: str | None = None
    message: Message | None = None
```

Add `callback_query: CallbackQuery | None = None` to `Update`.
Use `ALLOWED_UPDATES` in `get_updates` and `set_webhook` instead of `["message"]`.
Replace `send_message` and add `answer_callback`:

```python
    async def send_message(
        self, chat_id: int, text: str, buttons: Sequence[ReplyButton] = ()
    ) -> None:
        """Send text split at Telegram's limit; buttons go under the last chunk."""
        chunks = split_message(text)
        for number, chunk in enumerate(chunks, start=1):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if buttons and number == len(chunks):
                payload["reply_markup"] = {
                    "inline_keyboard": [[{"text": b.text, "callback_data": b.data}] for b in buttons]
                }
            await self.call("sendMessage", payload)

    async def answer_callback(self, callback_id: str, text: str) -> None:
        """Acknowledge a button tap with a short toast."""
        await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
```

`repo.py`, append:

```python
async def create_session(
    conn: Connection,
    athlete: Athlete,
    *,
    discipline: str,
    started_at: datetime,
    duration_min: int | None = None,
    rpe: int | None = None,
    summary: str | None = None,
    input_type: str = "text",
) -> UUID:
    """Insert one training session in any discipline."""
    cur = await conn.execute(
        "insert into sessions (athlete_id, discipline, started_at, duration_min, rpe, summary, "
        "input_type) values (%s, %s, %s, %s, %s, %s, %s) returning id",
        (athlete.id, discipline, started_at, duration_min, rpe, summary, input_type),
    )
    session_id: UUID = (await _one(cur))["id"]
    return session_id


async def undo_session(conn: Connection, athlete: Athlete, session_id: UUID) -> str | None:
    """Delete one of this athlete's sessions; module rows go with it through foreign keys."""
    cur = await conn.execute(
        "delete from sessions where id = %s and athlete_id = %s returning summary",
        (session_id, athlete.id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return str(row["summary"] or "a session")
```

`turn.py`, append:

```python
async def note_in_thread(graph: CoachGraph, athlete: Athlete, text: str) -> None:
    """Add an assistant note to the athlete's thread, e.g. that a log was undone."""
    config: RunnableConfig = {"configurable": {"thread_id": str(athlete.id)}}
    await graph.aupdate_state(config, {"messages": [AIMessage(content=text)]}, as_node="agent")
```

(import `Athlete` from `coach.core.models`).

`handler.py`: at the top of `handle_update`, before `message = update.message`:

```python
    if update.callback_query is not None:
        await _handle_callback(deps, update.update_id, update.callback_query)
        return
```

Send the reply with the turn's buttons:

```python
    result = await run_turn(deps.graph, ctx, message.text, model_name=deps.settings.agent_model)
    await deps.telegram.send_message(chat_id, result.reply, ctx.reply_buttons)
```

Append:

```python
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
```

(imports: `from uuid import UUID`, `CallbackQuery` from telegram, `undo_session` from repo, `note_in_thread` from turn).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy`

```bash
git add backend
git commit -m "feat: let tools put buttons under the reply and undo a logged session"
```

---

### Task 3: Gym schema, exercise library, program files and seeding

**Files:**
- Modify: `backend/pyproject.toml` (deps), `backend/src/coach/core/registry.py`, `backend/tests/conftest.py`, `backend/tests/test_registry.py`
- Create: `backend/src/coach/modules/gym/{__init__.py,module.py,library.py,program.py,seed.py,exercises.yaml,programs/sample.yaml,migrations/0001_gym.sql}`
- Test: `backend/tests/test_gym_seed.py`

**Interfaces:**
- Consumes: `Registry`, `ENABLED`, `migrate_all`, `Connection`, `Athlete`, `get_athlete_by_chat_id`, `create_pool`, `get_settings`.
- Produces:
  - `library.normalize(text) -> str` (casefold, accents removed, punctuation to spaces).
  - `library.ExerciseDef(name, aliases, pattern, equipment, load_areas)`; `load_library(path) -> list[ExerciseDef]`; `ExerciseIndex(exercises)` with `.resolve(name) -> ExerciseDef | None` and iteration; `LIBRARY_PATH`; `library_index() -> ExerciseIndex` (cached).
  - `program.Prescription`, `program.ProgramSession` (with `.label`), `program.ProgramDef`; `load_program(path, index) -> ProgramDef` (raises `ValueError` naming unknown exercises).
  - `seed.ProgramConflict(Exception)`; `seed.seed_program(conn, athlete, program, index, *, source_file: str, replace: bool = False) -> UUID`; `python -m coach.modules.gym.seed --program PATH (--check | --chat-id N [--replace])`.
  - `module.GymModule` (tools empty, prompt and context empty until Task 4); `default_registry()` returns `Registry([GymModule()])` (the `ENABLED` list is removed).
  - `programs/sample.yaml`: 2 weeks x 2 sessions (A, B), 4 sessions.

- [ ] **Step 1: Dependencies**

```bash
cd backend && uv add pyyaml && uv add --dev types-pyyaml
```

- [ ] **Step 2: Write the failing tests**

In `backend/tests/conftest.py`, migrate every enabled module:

```python
from coach.core.registry import default_registry
...
    await migrate_all(pool, default_registry().migration_dirs())
```

(remove the now unused `CORE_MIGRATIONS` import if ruff flags it).

In `backend/tests/test_registry.py`, replace `test_default_registry_starts_empty` with:

```python
def test_gym_is_enabled() -> None:
    assert [m.name for m in default_registry().modules] == ["gym"]
```

`backend/tests/test_gym_seed.py`:

```python
from pathlib import Path

import pytest

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.modules.gym.library import ExerciseIndex, library_index, load_library, normalize
from coach.modules.gym.program import load_program
from coach.modules.gym.seed import ProgramConflict, main, seed_program

SAMPLE = Path(__file__).parents[1] / "src/coach/modules/gym/programs/sample.yaml"


def test_normalize_ignores_case_accents_and_punctuation() -> None:
    assert normalize("Cócoras") == "cocoras"
    assert normalize("  SL SQUAT - Estabilidade ") == "sl squat estabilidade"
    assert normalize("90/90 com intenção") == "90/90 com intencao"


def test_library_resolves_portuguese_names_and_english_aliases() -> None:
    index = library_index()

    goblet = index.resolve("agachamento goblet")
    assert goblet is not None
    assert index.resolve("Goblet squat") == goblet
    assert index.resolve("serrote") == index.resolve("one arm dumbbell row")
    assert index.resolve("cocoras") is not None
    assert index.resolve("bulgarian bag spin") is None


def test_library_rejects_an_alias_used_by_two_exercises(tmp_path: Path) -> None:
    path = tmp_path / "lib.yaml"
    path.write_text(
        "exercises:\n"
        "  - {name: One, aliases: [shared], pattern: core}\n"
        "  - {name: Two, aliases: [shared], pattern: core}\n"
    )

    with pytest.raises(ValueError, match="shared"):
        ExerciseIndex(load_library(path))


def test_sample_program_loads() -> None:
    program = load_program(SAMPLE, library_index())

    assert [s.label for s in program.sessions] == [
        "Week 1 Treino A", "Week 1 Treino B", "Week 2 Treino A", "Week 2 Treino B",
    ]
    assert {p.block for s in program.sessions for p in s.exercises} == {"prep", "main"}


def test_unknown_exercises_are_named(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: Bad\nsessions:\n  - week: 1\n    day: A\n    exercises:\n"
        "      - {exercise: Moonwalk, block: main, sets: 3, reps: '10'}\n"
    )

    with pytest.raises(ValueError, match="Moonwalk"):
        load_program(path, library_index())


@pytest.mark.anyio
async def test_seed_writes_the_program_in_order(conn: Connection, athlete: Athlete) -> None:
    program = load_program(SAMPLE, library_index())

    program_id = await seed_program(
        conn, athlete, program, library_index(), source_file="sample.yaml"
    )

    cur = await conn.execute(
        "select ps.position, ps.label, count(pe.id)::int as exercises from program_sessions ps "
        "join program_exercises pe on pe.program_session_id = ps.id "
        "where ps.program_id = %s group by ps.position, ps.label order by ps.position",
        (program_id,),
    )
    rows = await cur.fetchall()
    assert [r["label"] for r in rows] == [s.label for s in program.sessions]
    assert [r["exercises"] for r in rows] == [len(s.exercises) for s in program.sessions]


@pytest.mark.anyio
async def test_reseeding_needs_replace(conn: Connection, athlete: Athlete) -> None:
    program = load_program(SAMPLE, library_index())
    first = await seed_program(conn, athlete, program, library_index(), source_file="a.yaml")

    with pytest.raises(ProgramConflict, match="a.yaml"):
        await seed_program(conn, athlete, program, library_index(), source_file="b.yaml")
    second = await seed_program(
        conn, athlete, program, library_index(), source_file="b.yaml", replace=True
    )

    cur = await conn.execute(
        "select id, active from programs where athlete_id = %s order by created_at, active",
        (athlete.id,),
    )
    assert {(r["id"], r["active"]) for r in await cur.fetchall()} == {
        (first, False), (second, True)
    }


def test_check_mode_validates_without_a_database(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--program", str(SAMPLE), "--check"])

    assert "4 sessions over 2 weeks" in capsys.readouterr().out
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gym_seed.py -q`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.modules.gym'`.

- [ ] **Step 4: Migration**

`backend/src/coach/modules/gym/migrations/0001_gym.sql`:

```sql
insert into disciplines (name, label) values ('gym', 'Gym') on conflict (name) do nothing;

-- the library: pattern and load areas let swaps keep the movement and spare sore areas
create table exercises (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  name text not null,
  aliases text[] not null default '{}',
  pattern text not null check (pattern in (
    'push', 'pull', 'hinge', 'squat', 'lunge', 'carry', 'core',
    'mobility', 'stability', 'plyometric')),
  equipment text[] not null default '{}',
  load_areas text[] not null default '{}',
  unique (athlete_id, name)
);

create table programs (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  name text not null,
  source_file text not null,
  sessions_per_week_target int not null default 3 check (sessions_per_week_target between 1 and 14),
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create index on programs (athlete_id);
create unique index programs_one_active_per_athlete on programs (athlete_id) where active;

-- an ordered sequence: the next session is the first one neither completed nor skipped
create table program_sessions (
  id uuid primary key default gen_random_uuid(),
  program_id uuid not null references programs(id) on delete cascade,
  position int not null,
  week int not null,
  day_label text not null,
  label text not null,
  planned_date date,
  -- deleting the logged session (Undo) frees the slot again
  completed_session_id uuid unique references sessions(id) on delete set null,
  skipped boolean not null default false,
  unique (program_id, position)
);

create table program_exercises (
  id uuid primary key default gen_random_uuid(),
  program_session_id uuid not null references program_sessions(id) on delete cascade,
  position int not null,
  exercise_id uuid not null references exercises(id),
  block text not null check (block in ('prep', 'main')),
  sets int not null,
  reps text not null,
  rest_s int,
  tempo text,
  notes text,
  unique (program_session_id, position)
);

create table gym_details (
  session_id uuid primary key references sessions(id) on delete cascade,
  program_session_id uuid references program_sessions(id) on delete set null,
  lifts jsonb not null default '[]'
);

alter table exercises enable row level security;
alter table programs enable row level security;
alter table program_sessions enable row level security;
alter table program_exercises enable row level security;
alter table gym_details enable row level security;
```

- [ ] **Step 5: Library and its YAML**

`backend/src/coach/modules/gym/__init__.py`:

```python
"""Gym: the athlete's dumbbell program, what is next, and logging sessions against it."""
```

`backend/src/coach/modules/gym/library.py`:

```python
"""The exercise library and name matching across Portuguese names and English aliases."""

import re
import unicodedata
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

LIBRARY_PATH = Path(__file__).parent / "exercises.yaml"

type Pattern = Literal[
    "push", "pull", "hinge", "squat", "lunge", "carry", "core", "mobility", "stability",
    "plyometric",
]


def normalize(text: str) -> str:
    """Casefold, strip accents, turn punctuation into single spaces (keeps '/' for 90/90)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9/]+", " ", plain).split())


class ExerciseDef(BaseModel):
    """One exercise: the coach's name, aliases, and what it trains and loads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    aliases: tuple[str, ...] = ()
    pattern: Pattern
    equipment: tuple[str, ...] = ()
    load_areas: tuple[str, ...] = ()


def load_library(path: Path) -> list[ExerciseDef]:
    """Read ``exercises:`` from a YAML file."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [ExerciseDef.model_validate(item) for item in data["exercises"]]


class ExerciseIndex:
    """Resolves any name or alias, in any case and with or without accents."""

    def __init__(self, exercises: list[ExerciseDef]) -> None:
        self._exercises = list(exercises)
        self._by_key: dict[str, ExerciseDef] = {}
        for exercise in self._exercises:
            for key in (exercise.name, *exercise.aliases):
                normal = normalize(key)
                existing = self._by_key.get(normal)
                if existing is not None and existing != exercise:
                    raise ValueError(f"{key!r} names both {existing.name!r} and {exercise.name!r}")
                self._by_key[normal] = exercise

    def resolve(self, name: str) -> ExerciseDef | None:
        """The exercise this name refers to, or None."""
        return self._by_key.get(normalize(name))

    def __iter__(self) -> Iterator[ExerciseDef]:
        return iter(self._exercises)


@cache
def library_index() -> ExerciseIndex:
    """The shipped library, loaded once."""
    return ExerciseIndex(load_library(LIBRARY_PATH))
```

`backend/src/coach/modules/gym/exercises.yaml`:

```yaml
# Public exercise library. Names are the coach's Portuguese names; aliases add English.
# pattern: push pull hinge squat lunge carry core mobility stability plyometric
exercises:
  - {name: Volta ao mundo, aliases: [around the world, hip circles], pattern: mobility, load_areas: [hips]}
  - {name: Melhor do mundo, aliases: [worlds greatest stretch, world's greatest stretch], pattern: mobility, load_areas: [hips, upper back]}
  - {name: Psoas, aliases: [psoas stretch, hip flexor stretch], pattern: mobility, load_areas: [hips]}
  - {name: Psoas com mobilidade, aliases: [psoas mobility, dynamic hip flexor stretch], pattern: mobility, load_areas: [hips]}
  - {name: 90/90 com intenção, aliases: [90/90 with intent, 90 90 with intent], pattern: mobility, load_areas: [hips]}
  - {name: Mobilidade de quadril 90/90, aliases: [90/90 hip mobility, 90/90 hip switch], pattern: mobility, load_areas: [hips]}
  - {name: Cócoras, aliases: [deep squat hold, squat hold], pattern: mobility, load_areas: [hips, ankles]}
  - {name: Estabilidade de joelho - ISO, aliases: [knee stability iso, knee isometric], pattern: stability, load_areas: [knees]}
  - {name: Pallof press, aliases: [pallof], pattern: core, equipment: [band], load_areas: [core]}
  - {name: SL squat - estabilidade, aliases: [single leg squat stability, single leg squat], pattern: stability, load_areas: [knees, hips]}
  - {name: Prancha tocando ombros, aliases: [plank shoulder taps, shoulder taps], pattern: core, load_areas: [core, shoulders]}
  - {name: Copenhagen plank, aliases: [copenhagen], pattern: core, load_areas: [hips, core]}
  - {name: Aterrisagem solo, aliases: [landing drill, single leg landing, landings], pattern: plyometric, load_areas: [knees, ankles]}
  - {name: Suitcase carry, aliases: [suitcase walk], pattern: carry, equipment: [dumbbell], load_areas: [core]}
  - {name: Agachamento goblet, aliases: [goblet squat, goblet], pattern: squat, equipment: [dumbbell], load_areas: [knees, hips]}
  - {name: Remada curvada, aliases: [bent over row, bent over dumbbell row, dumbbell row], pattern: pull, equipment: [dumbbell], load_areas: [upper back, lower back]}
  - {name: Supino reto com halter, aliases: [dumbbell bench press, bench press, flat dumbbell press, bench], pattern: push, equipment: [dumbbell, bench], load_areas: [shoulders]}
  - {name: Afundo, aliases: [lunge, lunges, split squat], pattern: lunge, equipment: [dumbbell], load_areas: [knees, hips]}
  - {name: Agachamento terra sumo, aliases: [sumo deadlift, sumo squat, sumo], pattern: hinge, equipment: [dumbbell], load_areas: [hips, lower back]}
  - {name: Serrote, aliases: [one arm dumbbell row, single arm row, one arm row], pattern: pull, equipment: [dumbbell, bench], load_areas: [upper back]}
  - {name: Barra fixa, aliases: [pull up, pull ups, pullup, pullups, chin up], pattern: pull, equipment: [pull-up bar], load_areas: [shoulders, elbows]}
  - {name: Stiff unilateral, aliases: [single leg rdl, single leg romanian deadlift, single leg stiff], pattern: hinge, equipment: [dumbbell], load_areas: [hips, lower back]}
  - {name: Supino ponte com halter, aliases: [glute bridge dumbbell press, bridge press, floor press bridge], pattern: push, equipment: [dumbbell], load_areas: [shoulders]}
  - {name: Side lunge, aliases: [lateral lunge, afundo lateral], pattern: lunge, equipment: [dumbbell], load_areas: [knees, hips]}
  - {name: Military press semi ajoelhado, aliases: [half kneeling press, half kneeling military press, military press, overhead press], pattern: push, equipment: [dumbbell], load_areas: [shoulders]}
```

- [ ] **Step 6: Program model and the public sample**

`backend/src/coach/modules/gym/program.py`:

```python
"""Program files: an ordered list of sessions, each a list of prescriptions."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from coach.modules.gym.library import ExerciseIndex


class Prescription(BaseModel):
    """One exercise as the coach wrote it for one session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exercise: str
    block: Literal["prep", "main"]
    sets: int = Field(ge=1)
    reps: str
    rest_s: int | None = Field(default=None, ge=0)
    tempo: str | None = None
    notes: str | None = None


class ProgramSession(BaseModel):
    """One session in the sequence (e.g. week 2, Treino B)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    week: int = Field(ge=1)
    day: str
    exercises: tuple[Prescription, ...] = Field(min_length=1)

    @property
    def label(self) -> str:
        """How the athlete and the coach name it."""
        return f"Week {self.week} Treino {self.day}"


class ProgramDef(BaseModel):
    """A whole program file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    sessions_per_week_target: int = Field(default=3, ge=1, le=14)
    sessions: tuple[ProgramSession, ...] = Field(min_length=1)


def load_program(path: Path, index: ExerciseIndex) -> ProgramDef:
    """Read and validate a program file; every exercise must be in the library."""
    program = ProgramDef.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    unknown = sorted(
        {p.exercise for s in program.sessions for p in s.exercises if index.resolve(p.exercise) is None}
    )
    if unknown:
        raise ValueError(f"exercises missing from the library: {', '.join(unknown)}")
    return program
```

`backend/src/coach/modules/gym/programs/sample.yaml` (made up; same format as the private program):

```yaml
# A made-up sample program for tests, CI and the demo athlete. Not anyone's real program.
name: Sample dumbbell program
sessions_per_week_target: 2
sessions:
  - week: 1
    day: A
    exercises:
      - {exercise: Volta ao mundo, block: prep, sets: 2, reps: "8"}
      - {exercise: Pallof press, block: prep, sets: 3, reps: "12"}
      - {exercise: Agachamento goblet, block: main, sets: 3, reps: "10", rest_s: 90, tempo: 3.0.1.0}
      - {exercise: Remada curvada, block: main, sets: 3, reps: "10", rest_s: 90, tempo: 3.0.1.0}
  - week: 1
    day: B
    exercises:
      - {exercise: Cócoras, block: prep, sets: 1, reps: 60s}
      - {exercise: Agachamento terra sumo, block: main, sets: 3, reps: 8-10, rest_s: 90, tempo: 3.0.1.0}
      - {exercise: Serrote, block: main, sets: 3, reps: "10", rest_s: 90, tempo: 3.0.1.0, notes: each side}
  - week: 2
    day: A
    exercises:
      - {exercise: Volta ao mundo, block: prep, sets: 2, reps: "8"}
      - {exercise: Pallof press, block: prep, sets: 3, reps: "12"}
      - {exercise: Agachamento goblet, block: main, sets: 3, reps: "10", rest_s: 90, tempo: 4.0.X.0}
      - {exercise: Remada curvada, block: main, sets: 3, reps: "10", rest_s: 90, tempo: 4.0.X.0}
  - week: 2
    day: B
    exercises:
      - {exercise: Cócoras, block: prep, sets: 1, reps: 60s}
      - {exercise: Agachamento terra sumo, block: main, sets: 3, reps: 8-10, rest_s: 90, tempo: 4.0.X.0}
      - {exercise: Serrote, block: main, sets: 3, reps: "10", rest_s: 90, tempo: 4.0.X.0, notes: each side}
```

- [ ] **Step 7: Seeding**

`backend/src/coach/modules/gym/seed.py`:

```python
"""Load a program file into the database: ``python -m coach.modules.gym.seed``."""

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from coach.core.config import get_settings
from coach.core.db import Connection, create_pool
from coach.core.models import Athlete
from coach.core.repo import get_athlete_by_chat_id
from coach.modules.gym.library import ExerciseIndex, library_index
from coach.modules.gym.program import ProgramDef, load_program


class ProgramConflict(Exception):
    """The athlete already has an active program and ``replace`` was not given."""


async def _upsert_library(conn: Connection, athlete: Athlete, index: ExerciseIndex) -> dict[str, UUID]:
    ids: dict[str, UUID] = {}
    for exercise in index:
        cur = await conn.execute(
            "insert into exercises (athlete_id, name, aliases, pattern, equipment, load_areas) "
            "values (%s, %s, %s, %s, %s, %s) on conflict (athlete_id, name) do update set "
            "aliases = excluded.aliases, pattern = excluded.pattern, "
            "equipment = excluded.equipment, load_areas = excluded.load_areas returning id",
            (
                athlete.id, exercise.name, list(exercise.aliases), exercise.pattern,
                list(exercise.equipment), list(exercise.load_areas),
            ),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("exercise upsert returned no row")
        ids[exercise.name] = row["id"]
    return ids


async def seed_program(
    conn: Connection,
    athlete: Athlete,
    program: ProgramDef,
    index: ExerciseIndex,
    *,
    source_file: str,
    replace: bool = False,
) -> UUID:
    """Write the library and the program in one transaction; returns the new program id."""
    async with conn.transaction():
        cur = await conn.execute(
            "select id, source_file from programs where athlete_id = %s and active", (athlete.id,)
        )
        active = await cur.fetchone()
        if active is not None and not replace:
            raise ProgramConflict(
                f"active program already seeded from {active['source_file']}; use --replace"
            )
        if active is not None:
            await conn.execute("update programs set active = false where id = %s", (active["id"],))
        ids = await _upsert_library(conn, athlete, index)
        cur = await conn.execute(
            "insert into programs (athlete_id, name, source_file, sessions_per_week_target) "
            "values (%s, %s, %s, %s) returning id",
            (athlete.id, program.name, source_file, program.sessions_per_week_target),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("program insert returned no row")
        program_id: UUID = row["id"]
        for position, session in enumerate(program.sessions, start=1):
            cur = await conn.execute(
                "insert into program_sessions (program_id, position, week, day_label, label) "
                "values (%s, %s, %s, %s, %s) returning id",
                (program_id, position, session.week, session.day, session.label),
            )
            session_row = await cur.fetchone()
            if session_row is None:
                raise RuntimeError("program session insert returned no row")
            for exercise_position, p in enumerate(session.exercises, start=1):
                exercise = index.resolve(p.exercise)
                if exercise is None:
                    raise ValueError(f"unknown exercise {p.exercise!r}")
                await conn.execute(
                    "insert into program_exercises (program_session_id, position, exercise_id, "
                    "block, sets, reps, rest_s, tempo, notes) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        session_row["id"], exercise_position, ids[exercise.name], p.block,
                        p.sets, p.reps, p.rest_s, p.tempo, p.notes,
                    ),
                )
    return program_id


async def _seed(path: Path, program: ProgramDef, chat_id: int, replace: bool) -> None:
    pool = create_pool(get_settings().database_url.get_secret_value())
    await pool.open()
    try:
        async with pool.connection() as conn:
            athlete = await get_athlete_by_chat_id(conn, chat_id)
            if athlete is None:
                raise SystemExit(f"No athlete for chat {chat_id}; run `coach add-athlete` first.")
            program_id = await seed_program(
                conn, athlete, program, library_index(), source_file=path.name, replace=replace
            )
        print(f"Seeded {program.name} for {athlete.name} ({program_id})")
    finally:
        await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Validate a program file and, unless ``--check``, seed it for an athlete."""
    parser = argparse.ArgumentParser(prog="python -m coach.modules.gym.seed")
    parser.add_argument("--program", type=Path, required=True)
    parser.add_argument("--chat-id", type=int)
    parser.add_argument("--replace", action="store_true", help="retire the active program")
    parser.add_argument("--check", action="store_true", help="validate only")
    args = parser.parse_args(argv)
    program = load_program(args.program, library_index())
    weeks = len({s.week for s in program.sessions})
    print(f"{program.name}: {len(program.sessions)} sessions over {weeks} weeks")
    if args.check:
        return
    if args.chat_id is None:
        parser.error("--chat-id is required unless --check")
    asyncio.run(_seed(args.program, program, args.chat_id, args.replace))


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Module skeleton and enabling it**

`backend/src/coach/modules/gym/module.py`:

```python
"""The gym discipline module."""

from pathlib import Path

from langchain_core.tools import BaseTool

from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.registry import ScheduledJob

HERE = Path(__file__).parent


class GymModule:
    """Program, next session, and logging against it."""

    name = "gym"
    migrations = HERE / "migrations"

    def tools(self) -> list[BaseTool]:
        return []

    def prompt(self, athlete: Athlete) -> str:
        return ""

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        return ""

    def jobs(self) -> list[ScheduledJob]:
        return []

    def evals(self) -> list[Path]:
        return []
```

In `backend/src/coach/core/registry.py`, replace `ENABLED` and `default_registry` with a function that imports the enabled modules locally (modules import `ScheduledJob` and `CoachContext` from the core, so a module-level import would be circular):

```python
def default_registry() -> Registry:
    """The enabled discipline modules, in migration order. Week 3 adds SurfModule()."""
    from coach.modules.gym.module import GymModule  # local: modules import from the core

    return Registry([GymModule()])
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass (including `test_every_public_table_has_row_level_security`, now covering the gym tables).

- [ ] **Step 10: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run coach migrate`
Expected: clean; `coach migrate` applies `gym/0001_gym.sql` to the local database.

```bash
git add backend
git commit -m "feat: add gym schema, exercise library, program files and seeding"
```

---

### Task 4: `get_program`, gym context and prompt

**Files:**
- Create: `backend/src/coach/modules/gym/repo.py`, `backend/src/coach/modules/gym/tools.py`, `backend/src/coach/modules/gym/prompt.md`
- Modify: `backend/src/coach/modules/gym/module.py`
- Test: `backend/tests/test_gym_tools.py`

**Interfaces:**
- Consumes: `seed_program`, `load_program`, `library_index` (Task 3); `history_window` (week 1 core tools); `CoachContext`.
- Produces:
  - `gym.repo.active_program(conn, athlete) -> dict | None` (`id`, `name`, `sessions_per_week_target`); `next_pending(conn, program_id, *, day_label: str | None = None) -> dict | None` (`id`, `position`, `week`, `day_label`, `label`, `planned_date`); `prescriptions(conn, program_session_id) -> list[dict]` (`block`, `exercise`, `sets`, `reps`, `rest_s`, `tempo`, `notes`); `progress(conn, program_id) -> dict` (`done`, `skipped`, `total`); `done_since(conn, program_id, since: datetime) -> int`.
  - `gym.tools.get_program` (no model arguments); `gym.tools.program_summary(conn, athlete, now) -> dict | None`.
  - `GymModule.tools() == [get_program]` for now; `prompt()` from `prompt.md` plus the library list; `context()` one line.
  - Test helper (in the test file): `seeded(conn_or_pool, athlete) -> UUID` seeding the sample program.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gym_tools.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_session
from coach.modules.gym.library import library_index
from coach.modules.gym.module import GymModule
from coach.modules.gym.program import load_program
from coach.modules.gym.seed import seed_program
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

SAMPLE = Path(__file__).parents[1] / "src/coach/modules/gym/programs/sample.yaml"
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)  # Tuesday 19:00 in Brisbane
GYM = Registry([GymModule()])


async def seeded(pool: Pool, athlete: Athlete) -> UUID:
    async with pool.connection() as conn:
        return await seed_program(
            conn, athlete, load_program(SAMPLE, library_index()), library_index(),
            source_file="sample.yaml",
        )


async def complete(pool: Pool, athlete: Athlete, position: int, started_at: datetime) -> None:
    async with pool.connection() as conn:
        session_id = await create_session(conn, athlete, discipline="gym", started_at=started_at)
        await conn.execute(
            "update program_sessions ps set completed_session_id = %s from programs p "
            "where ps.program_id = p.id and p.athlete_id = %s and p.active and ps.position = %s",
            (session_id, athlete.id, position),
        )


def ctx(athlete: Athlete, pool: Pool) -> CoachContext:
    return CoachContext(athlete=athlete, pool=pool, registry=GYM, now=lambda: NOW)


async def call_tool(athlete: Athlete, pool: Pool, name: str, args: dict[str, object]) -> str:
    model = scripted(
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "g1"}]), "ok"
    )
    out = await build_graph(model, GYM).ainvoke(
        {"messages": [HumanMessage("gym")]}, context=ctx(athlete, pool)
    )
    return next(m.text for m in out["messages"] if isinstance(m, ToolMessage))


async def test_get_program_shows_the_next_session_in_full(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["program"] == "Sample dumbbell program"
    assert result["progress"] == {"done": 0, "skipped": 0, "total": 4}
    assert result["this_week"] == {"done": 0, "target": 2}
    next_session = result["next_session"]
    assert next_session["label"] == "Week 1 Treino A"
    assert next_session["exercises"][2] == {
        "block": "main", "exercise": "Agachamento goblet", "sets": 3, "reps": "10",
        "rest_s": 90, "tempo": "3.0.1.0", "notes": None,
    }


async def test_progress_and_this_week_follow_completed_sessions(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    await complete(pool, athlete, 1, datetime(2026, 10, 5, 22, 0, tzinfo=UTC))  # Tue local

    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["progress"]["done"] == 1
    assert result["this_week"]["done"] == 1
    assert result["next_session"]["label"] == "Week 1 Treino B"


async def test_without_a_program_get_program_says_so(pool: Pool, athlete: Athlete) -> None:
    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["program"] is None


async def test_context_is_one_line(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    async with pool.connection() as conn:
        line = await GymModule().context(conn, athlete)

    assert line == (
        "Sample dumbbell program: 0/4 sessions done, 0/2 this week, next is Week 1 Treino A."
    )


def test_prompt_teaches_tempo_and_lists_the_library() -> None:
    athlete = Athlete(id=UUID(int=1), name="J", timezone="Australia/Brisbane", telegram_chat_id=1)

    prompt = GymModule().prompt(athlete)

    assert "4.0.X.0" in prompt
    assert "Agachamento goblet (goblet squat, goblet)" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gym_tools.py -q`
Expected: FAIL; `get_program` is not a bound tool (the ToolMessage is an error), and `prompt()` returns "".

- [ ] **Step 3: Implement gym SQL**

`backend/src/coach/modules/gym/repo.py`:

```python
"""SQL for the gym tables."""

from datetime import datetime
from typing import Any
from uuid import UUID

from coach.core.db import Connection
from coach.core.models import Athlete


async def active_program(conn: Connection, athlete: Athlete) -> dict[str, Any] | None:
    """The athlete's active program, if any."""
    cur = await conn.execute(
        "select id, name, sessions_per_week_target from programs "
        "where athlete_id = %s and active",
        (athlete.id,),
    )
    return await cur.fetchone()


async def next_pending(
    conn: Connection, program_id: UUID, *, day_label: str | None = None
) -> dict[str, Any] | None:
    """The first session neither completed nor skipped, optionally for one day label."""
    cur = await conn.execute(
        "select id, position, week, day_label, label, planned_date from program_sessions "
        "where program_id = %(program_id)s and completed_session_id is null and not skipped "
        "and (%(day)s::text is null or day_label = %(day)s) order by position limit 1",
        {"program_id": program_id, "day": day_label},
    )
    return await cur.fetchone()


async def prescriptions(conn: Connection, program_session_id: UUID) -> list[dict[str, Any]]:
    """Every exercise of one session, in order."""
    cur = await conn.execute(
        "select pe.block, e.name as exercise, pe.sets, pe.reps, pe.rest_s, pe.tempo, pe.notes "
        "from program_exercises pe join exercises e on e.id = pe.exercise_id "
        "where pe.program_session_id = %s order by pe.position",
        (program_session_id,),
    )
    return await cur.fetchall()


async def progress(conn: Connection, program_id: UUID) -> dict[str, Any]:
    """How many sessions are done, skipped, and in total."""
    cur = await conn.execute(
        "select count(*) filter (where completed_session_id is not null)::int as done, "
        "count(*) filter (where skipped)::int as skipped, count(*)::int as total "
        "from program_sessions where program_id = %s",
        (program_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else {"done": 0, "skipped": 0, "total": 0}


async def done_since(conn: Connection, program_id: UUID, since: datetime) -> int:
    """Program sessions completed by sessions that started at or after ``since``."""
    cur = await conn.execute(
        "select count(*)::int as n from program_sessions ps "
        "join sessions s on s.id = ps.completed_session_id "
        "where ps.program_id = %s and s.started_at >= %s",
        (program_id, since),
    )
    row = await cur.fetchone()
    return int(row["n"]) if row else 0
```

- [ ] **Step 4: Implement the tool, prompt and context**

`backend/src/coach/modules/gym/tools.py`:

```python
"""Gym tools bound to the agent."""

import json
from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from coach.core.context import CoachContext
from coach.core.db import Connection
from coach.core.models import Athlete
from coach.core.tools import history_window
from coach.modules.gym.repo import active_program, done_since, next_pending, prescriptions, progress


async def program_summary(conn: Connection, athlete: Athlete, now: datetime) -> dict[str, Any] | None:
    """Progress, this week against the target, and the next session in full."""
    program = await active_program(conn, athlete)
    if program is None:
        return None
    week_start, _ = history_window("this_week", 7, now, athlete.timezone)
    upcoming = await next_pending(conn, program["id"])
    next_session = None
    if upcoming is not None:
        next_session = {
            "position": upcoming["position"],
            "label": upcoming["label"],
            "planned_date": upcoming["planned_date"],
            "exercises": await prescriptions(conn, upcoming["id"]),
        }
    return {
        "program": program["name"],
        "progress": await progress(conn, program["id"]),
        "this_week": {
            "done": await done_since(conn, program["id"], week_start),
            "target": program["sessions_per_week_target"],
        },
        "next_session": next_session,
    }


@tool
async def get_program(runtime: ToolRuntime[CoachContext]) -> str:
    """The athlete's gym program: progress, sessions done this week against the target, and the
    next pending session with every exercise as prescribed (sets, reps, rest in seconds, tempo
    as cadência such as 4.0.X.0, and notes). Use it for "what's my next session?"."""
    ctx = runtime.context
    async with ctx.pool.connection() as conn:
        summary = await program_summary(conn, ctx.athlete, ctx.now())
    if summary is None:
        summary = {"program": None, "message": "No active gym program has been seeded."}
    return json.dumps(summary, default=str, ensure_ascii=False)
```

`backend/src/coach/modules/gym/prompt.md`:

```markdown
Gym module.
The athlete follows a dumbbell strength program written by their coach in Portuguese: sessions in a fixed order, labelled Treino A, B and C, about three a week.
Exercise names are the coach's Portuguese names; the athlete may use the English aliases listed below. Use the Portuguese name in tool calls and English when talking.
Cadência is tempo in seconds, written eccentric.pause.concentric.pause; X means as explosive as possible. 4.0.X.0 means four seconds down, no pause, explode up.
Each session has a prep block (mobility and stability, no rest) and a main block (strength, with rest).
Use get_program for the next session, this week's count or progress; never recite a session from memory.
When the athlete says they trained in the gym, call log_gym_session once. They report only deviations from the plan: the day they did, loads, sets or reps that differed, swaps, skipped exercises, duration and RPE. Never invent loads, reps or exercises they did not mention; everything not mentioned counts as done as prescribed.
After logging, mention they can undo it with the button under your reply.
```

Replace `module.py`'s `tools`, `prompt` and `context`:

```python
PROMPT = (HERE / "prompt.md").read_text(encoding="utf-8").strip()


class GymModule:
    ...
    def tools(self) -> list[BaseTool]:
        return [get_program]

    def prompt(self, athlete: Athlete) -> str:
        lines = [
            f"- {e.name} ({', '.join(e.aliases)})" if e.aliases else f"- {e.name}"
            for e in library_index()
        ]
        return f"{PROMPT}\n\nExercise library:\n" + "\n".join(lines)

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        summary = await program_summary(conn, athlete, datetime.now(UTC))
        if summary is None:
            return ""
        progress, week = summary["progress"], summary["this_week"]
        upcoming = summary["next_session"]
        next_part = f"next is {upcoming['label']}" if upcoming else "the program is complete"
        return (
            f"{summary['program']}: {progress['done']}/{progress['total']} sessions done, "
            f"{week['done']}/{week['target']} this week, {next_part}."
        )
```

(imports: `datetime`, `UTC`; `library_index`; `get_program`, `program_summary` from `coach.modules.gym.tools`).

Note: `context()` uses the real clock because the protocol has no clock argument; the context test does not depend on the week count beyond 0.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Quality gate and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd .. && git add backend && git commit -m "feat: add get_program, gym context and the gym prompt fragment"
```

---

### Task 5: `log_gym_session`

**Files:**
- Modify: `backend/src/coach/modules/gym/tools.py`, `backend/src/coach/modules/gym/repo.py`, `backend/src/coach/modules/gym/module.py`
- Test: `backend/tests/test_gym_tools.py` (append)

**Interfaces:**
- Consumes: `create_session` (Task 2), `ReplyButton` (Task 2), gym repo (Task 4), `library_index`, `normalize` (Task 3).
- Produces:
  - `gym.tools.LiftLog(exercise: str, load_kg: float | None, sets: int | None, reps: str | None, swapped_to: str | None, skipped: bool = False)`.
  - `gym.tools.merge_lifts(planned: list[dict], lifts: list[LiftLog], index) -> list[dict]`.
  - `gym.tools.log_gym_session` with model arguments `day`, `started_at`, `duration_min`, `rpe`, `notes`, `lifts`.
  - `gym.repo.complete_program_session(conn, program_session_id, session_id)`; `gym.repo.insert_details(conn, session_id, program_session_id, lifts)`.
  - `GymModule.tools() == [get_program, log_gym_session]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_gym_tools.py`:

```python
async def gym_rows(pool: Pool, athlete: Athlete) -> list[dict[str, object]]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select s.id, s.started_at, s.rpe, s.summary, ps.label, gd.lifts "
            "from sessions s join gym_details gd on gd.session_id = s.id "
            "left join program_sessions ps on ps.id = gd.program_session_id "
            "where s.athlete_id = %s order by s.created_at",
            (athlete.id,),
        )
        return await cur.fetchall()


async def test_logs_the_next_session_with_the_loads_mentioned(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    turn = ctx(athlete, pool)
    model = scripted(
        AIMessage(content="", tool_calls=[{"name": "log_gym_session", "id": "l1", "args": {
            "rpe": 7, "lifts": [{"exercise": "goblet squat", "load_kg": 22}]}}]),
        "Logged.",
    )

    await build_graph(model, GYM).ainvoke({"messages": [HumanMessage("did A")]}, context=turn)

    [row] = await gym_rows(pool, athlete)
    assert row["label"] == "Week 1 Treino A"
    assert row["rpe"] == 7
    goblet = next(lift for lift in row["lifts"] if lift["exercise"] == "Agachamento goblet")
    assert goblet["load_kg"] == 22
    assert goblet["done"] is True
    rows_by_name = {lift["exercise"]: lift for lift in row["lifts"]}
    assert rows_by_name["Remada curvada"]["done"] is True  # not mentioned: done as prescribed
    assert "Volta ao mundo" not in rows_by_name  # prep block is assumed, not stored
    assert turn.reply_buttons[0].data == f"undo:{row['id']}"


async def test_a_named_day_picks_the_first_pending_session_with_that_label(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    await call_tool(athlete, pool, "log_gym_session", {"day": "Treino B"})

    [row] = await gym_rows(pool, athlete)
    assert row["label"] == "Week 1 Treino B"


async def test_a_day_with_nothing_pending_is_logged_as_an_extra_session(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)
    await complete(pool, athlete, 2, NOW)
    await complete(pool, athlete, 4, NOW)

    result = await call_tool(athlete, pool, "log_gym_session", {"day": "B"})

    assert "extra" in result.lower()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select count(*)::int as n from program_sessions ps join programs p "
            "on p.id = ps.program_id where p.athlete_id = %s and ps.completed_session_id "
            "is not null",
            (athlete.id,),
        )
        assert (await cur.fetchone()) == {"n": 2}


async def test_swaps_skips_and_unknown_exercises_are_kept(pool: Pool, athlete: Athlete) -> None:
    await seeded(pool, athlete)

    await call_tool(athlete, pool, "log_gym_session", {"lifts": [
        {"exercise": "Remada curvada", "swapped_to": "push ups"},
        {"exercise": "goblet", "skipped": True},
        {"exercise": "bulgarian bag spin", "sets": 2},
    ]})

    [row] = await gym_rows(pool, athlete)
    lifts = {lift["exercise"]: lift for lift in row["lifts"]}
    assert lifts["Remada curvada"]["swapped_to"] == "push ups"
    assert lifts["Agachamento goblet"]["done"] is False
    assert lifts["bulgarian bag spin"] == {
        "exercise": "bulgarian bag spin", "extra": True, "known": False, "done": True, "sets": 2,
    }


async def test_a_time_without_a_zone_is_the_athletes_local_time(
    pool: Pool, athlete: Athlete
) -> None:
    await seeded(pool, athlete)

    await call_tool(athlete, pool, "log_gym_session", {"started_at": "2026-10-06T07:00:00"})

    [row] = await gym_rows(pool, athlete)
    assert row["started_at"] == datetime(2026, 10, 5, 21, 0, tzinfo=UTC)


async def test_undo_frees_the_program_slot(pool: Pool, athlete: Athlete) -> None:
    from coach.core.repo import undo_session

    await seeded(pool, athlete)
    await call_tool(athlete, pool, "log_gym_session", {})
    [row] = await gym_rows(pool, athlete)

    async with pool.connection() as conn:
        assert await undo_session(conn, athlete, row["id"]) is not None
    result = json.loads(await call_tool(athlete, pool, "get_program", {}))

    assert result["next_session"]["label"] == "Week 1 Treino A"
    assert result["progress"]["done"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_gym_tools.py -q`
Expected: the new tests FAIL (no `log_gym_session` tool; `gym_rows` finds nothing).

- [ ] **Step 3: Implement**

Append to `backend/src/coach/modules/gym/repo.py`:

```python
async def complete_program_session(
    conn: Connection, program_session_id: UUID, session_id: UUID
) -> None:
    """Mark a program session as done by a logged session."""
    await conn.execute(
        "update program_sessions set completed_session_id = %s where id = %s",
        (session_id, program_session_id),
    )


async def insert_details(
    conn: Connection,
    session_id: UUID,
    program_session_id: UUID | None,
    lifts: list[dict[str, Any]],
) -> None:
    """The gym part of a logged session."""
    await conn.execute(
        "insert into gym_details (session_id, program_session_id, lifts) values (%s, %s, %s)",
        (session_id, program_session_id, Jsonb(lifts)),
    )
```

(import `Jsonb` from `psycopg.types.json`).

Append to `backend/src/coach/modules/gym/tools.py`:

```python
import re
from datetime import UTC
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from coach.core.models import ReplyButton
from coach.core.repo import create_session
from coach.modules.gym.library import ExerciseIndex, library_index, normalize
from coach.modules.gym.repo import complete_program_session, insert_details


class LiftLog(BaseModel):
    """One exercise the athlete mentioned. Fill only what they said."""

    exercise: str = Field(description="As the athlete said it, Portuguese or English")
    load_kg: float | None = Field(default=None, ge=0, description="Dumbbell weight in kg")
    sets: int | None = Field(default=None, ge=1)
    reps: str | None = None
    swapped_to: str | None = Field(default=None, description="What they did instead")
    skipped: bool = False


def merge_lifts(
    planned: list[dict[str, Any]], lifts: list[LiftLog], index: ExerciseIndex
) -> list[dict[str, Any]]:
    """Main-block exercises as prescribed, overridden by what the athlete mentioned.

    Prep exercises are stored only when mentioned; unknown exercises are kept as said.
    """
    mentioned: dict[str, tuple[str, LiftLog, bool]] = {}
    for lift in lifts:
        known = index.resolve(lift.exercise)
        name = known.name if known else lift.exercise
        mentioned[normalize(name)] = (name, lift, known is not None)
    entries: list[dict[str, Any]] = []
    for p in planned:
        said = mentioned.pop(normalize(p["exercise"]), None)
        if p["block"] != "main" and said is None:
            continue
        entry: dict[str, Any] = {
            "exercise": p["exercise"],
            "planned": {"sets": p["sets"], "reps": p["reps"], "tempo": p["tempo"]},
            "done": True,
        }
        if said is not None:
            entry.update(_said(said[1], index))
        entries.append(entry)
    for name, lift, known in mentioned.values():
        entries.append({"exercise": name, "extra": True, "known": known, **_said(lift, index)})
    return entries


def _said(lift: LiftLog, index: ExerciseIndex) -> dict[str, Any]:
    out: dict[str, Any] = {"done": not lift.skipped}
    if lift.load_kg is not None:
        out["load_kg"] = lift.load_kg
    if lift.sets is not None:
        out["sets"] = lift.sets
    if lift.reps is not None:
        out["reps"] = lift.reps
    if lift.swapped_to is not None:
        swapped = index.resolve(lift.swapped_to)
        out["swapped_to"] = swapped.name if swapped else lift.swapped_to
    return out


def _day_label(day: str | None) -> str | None:
    if not day:
        return None
    match = re.search(r"([a-z])\s*$", normalize(day))
    return match.group(1).upper() if match else None


def _started_at(value: datetime | None, ctx: CoachContext) -> datetime:
    if value is None:
        return ctx.now()
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo(ctx.athlete.timezone)).astimezone(UTC)
    return value


@tool
async def log_gym_session(
    runtime: ToolRuntime[CoachContext],
    day: Annotated[str | None, Field(description="Program day if named: A, B or C")] = None,
    started_at: Annotated[
        datetime | None, Field(description="Local date and time; omit for now")
    ] = None,
    duration_min: Annotated[int | None, Field(ge=1, le=600)] = None,
    rpe: Annotated[int | None, Field(ge=1, le=10)] = None,
    notes: Annotated[str | None, Field(description="Anything else, in their words")] = None,
    lifts: list[LiftLog] | None = None,
) -> str:
    """Log one gym session against the program. Everything not mentioned counts as done as
    prescribed. Without a day, it completes the next pending session; with a day, the first
    pending session for that day. Call once per session."""
    ctx = runtime.context
    index = library_index()
    label_day = _day_label(day)
    async with ctx.pool.connection() as conn, conn.transaction():
        program = await active_program(conn, ctx.athlete)
        planned = None
        if program is not None:
            planned = await next_pending(conn, program["id"], day_label=label_day)
        planned_rows = await prescriptions(conn, planned["id"]) if planned else []
        entries = merge_lifts(planned_rows, lifts or [], index)
        label = planned["label"] if planned else "Extra gym session"
        session_id = await create_session(
            conn, ctx.athlete, discipline="gym", started_at=_started_at(started_at, ctx),
            duration_min=duration_min, rpe=rpe, summary=label,
        )
        await insert_details(conn, session_id, planned["id"] if planned else None, entries)
        if planned is not None:
            await complete_program_session(conn, planned["id"], session_id)
        total = (await progress(conn, program["id"]))["total"] if program else 0
    ctx.reply_buttons.append(ReplyButton(text="Undo", data=f"undo:{session_id}"))
    changed = [e for e in entries if set(e) - {"exercise", "planned", "done"} or not e["done"]]
    detail = json.dumps(changed, ensure_ascii=False) if changed else "everything as prescribed"
    if planned is None:
        reason = f"no pending Treino {label_day} left" if label_day else "no active program"
        return f"Logged as an extra session ({reason}). Changes: {detail}. Notes: {notes or '-'}"
    return (
        f"Logged {label} (session {planned['position']} of {total}). "
        f"Changes: {detail}. Notes: {notes or '-'}"
    )
```

Note on `notes`: the tool accepts notes so the model has a place for free text, but week 2 does not store them (no column); week 4's `save_note` stores reflections. Keep the argument; mention it in the return text so the model can acknowledge it.

`module.py`: `tools()` returns `[get_program, log_gym_session]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Quality gate and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd .. && git add backend && git commit -m "feat: log gym sessions against the program with an Undo button"
```

---

### Task 6: Transcribe and seed the real program (private, nothing committed)

**Files:**
- Create: `docs/trainings/forca-3x-halter.yaml` (git-ignored)
- Scratch only: a generator script in the session scratchpad.

**Interfaces:**
- Consumes: the program file format (Task 3), the seed command (Task 3), the athlete for chat `8952884287`.
- Produces: the athlete's active program in the local database.

- [ ] **Step 1: Transcribe**

Read `docs/trainings/Jean Loureiro -  Força 3x + soltando jogo - HALTER.pdf`.
Write a generator script in the scratchpad that holds the three session templates (exercise, sets, reps, rest, notes) and the per-week tempo table, and writes `docs/trainings/forca-3x-halter.yaml` with `name: Força 3x + soltando jogo`, `sessions_per_week_target: 3`, and 18 sessions in order week 1 A, B, C, week 2 A, B, C, and so on.
Rules: rows with a rest interval are `block: main`, rows without are `block: prep`; `rest_s` in seconds; `tempo` as written (`ISO` and `isometria` become `ISO`); reps exactly as written (`8-10`, `6 a 10` as `6-10`, `12(6+6)`, `20s`, `20 passos`); notes as written (`cada perna`, `cada lado`, `cada mão`, `Realizar com halter`, `Devagar`); week 4 exactly as written; exercise names as in `exercises.yaml` or one of its aliases.

- [ ] **Step 2: Validate**

Run: `cd backend && uv run python -m coach.modules.gym.seed --program "../docs/trainings/forca-3x-halter.yaml" --check`
Expected: `Força 3x + soltando jogo: 18 sessions over 6 weeks`.
Spot-check three rows against the PDF (week 1 Treino A Remada curvada tempo 3.0.0.0; week 4 Treino B Barra fixa reps 10-12; week 6 Treino C Supino ponte tempo 6.0.X.0).

- [ ] **Step 3: Seed**

Run: `cd backend && uv run python -m coach.modules.gym.seed --program "../docs/trainings/forca-3x-halter.yaml" --chat-id 8952884287`
Expected: `Seeded Força 3x + soltando jogo for Jean (<uuid>)`.

- [ ] **Step 4: Confirm nothing private is staged**

Run: `git status --short`
Expected: no `docs/trainings` entry. No commit in this task.

---

### Task 7: Eval harness and the first gym eval

**Files:**
- Create: `backend/src/coach/core/evals.py`, `backend/src/coach/modules/gym/evals/extraction.yaml`, `backend/src/coach/modules/gym/evals/recordings/extraction.json` (recorded in Step 6)
- Modify: `backend/src/coach/modules/gym/module.py` (`evals()`), `.github/workflows/ci.yml`
- Test: `backend/tests/test_evals.py`

**Interfaces:**
- Consumes: `system_prompt`, `CORE_TOOLS`, `Registry`, `default_registry`, `get_chat_model`, `get_settings`, `create_pool`, `normalize` (gym library; the harness gets a normalizer passed in, it does not import the module).
- Produces:
  - `EvalCase(id, input, expected: dict | None)`; `EvalSet(name, tool, cases, path)`; `load_set(path) -> EvalSet`.
  - `flatten(args, normalize) -> dict[str, str]`; `score_case(case, tool, calls, normalize) -> CaseScore(tool_ok, precision, recall, hallucinated)`; `summarize(scores) -> dict`.
  - `predict(model, registry, cases) -> dict[str, list[dict]]`; cassette read/write; `run(...)`.
  - CLI: `python -m coach.core.evals [--mode replay|live] [--record] [--save-run]`.

Scoring rules: arguments are flattened to dotted paths; list items that have an `exercise` key are keyed by the normalized exercise name (`lifts[agachamento goblet].load_kg`); strings are normalized (casefold, accents and punctuation removed); numbers compare as floats; `None`, `False` and empty lists count as not given; `started_at` and `notes` are ignored (free text and clock dependent).
A case with `expected: null` passes the tool check only if the set's tool is not called.
Precision is correct fields over predicted fields, recall is correct fields over expected fields, hallucinated fields are predicted fields absent from the expectation.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_evals.py`:

```python
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from coach.core.evals import EvalCase, flatten, load_set, predict, score_case, summarize
from coach.core.registry import Registry
from coach.modules.gym.library import normalize
from coach.modules.gym.module import GymModule
from tests.fakes import scripted

pytestmark = pytest.mark.anyio

GYM_SET = Path(__file__).parents[1] / "src/coach/modules/gym/evals/extraction.yaml"


def test_flatten_keys_lifts_by_exercise_and_drops_empty_values() -> None:
    args = {"day": "B", "rpe": 8, "notes": "x", "started_at": "2026-10-06T07:00",
            "lifts": [{"exercise": "Agachamento Terra Sumo", "load_kg": 24, "skipped": False,
                       "reps": None}]}

    assert flatten(args, normalize) == {
        "day": "b", "rpe": "8.0", "lifts[agachamento terra sumo].exercise": "agachamento terra sumo",
        "lifts[agachamento terra sumo].load_kg": "24.0",
    }


def test_score_counts_correct_missing_and_invented_fields() -> None:
    case = EvalCase(id="c", input="x", expected={"day": "A", "rpe": 7})

    score = score_case(case, "log_gym_session",
                       [{"name": "log_gym_session", "args": {"day": "A", "duration_min": 40}}],
                       normalize)

    assert score.tool_ok
    assert (score.precision, score.recall) == (0.5, 0.5)
    assert score.hallucinated == ["duration_min"]


def test_a_case_that_must_not_log_fails_when_it_logs() -> None:
    case = EvalCase(id="c", input="how many sessions this week?", expected=None)

    logged = score_case(case, "log_gym_session",
                        [{"name": "log_gym_session", "args": {}}], normalize)
    asked = score_case(case, "log_gym_session", [{"name": "get_program", "args": {}}], normalize)

    assert (logged.tool_ok, asked.tool_ok) == (False, True)


def test_the_gym_set_has_fifteen_cases_with_known_exercises() -> None:
    eval_set = load_set(GYM_SET)

    assert eval_set.tool == "log_gym_session"
    assert len(eval_set.cases) == 15
    assert len({c.id for c in eval_set.cases}) == 15


async def test_predict_takes_the_models_first_reply() -> None:
    model = scripted(AIMessage(content="", tool_calls=[
        {"name": "log_gym_session", "args": {"day": "A"}, "id": "e1"}]))
    case = EvalCase(id="one", input="did A", expected={"day": "A"})

    predictions = await predict(model, Registry([GymModule()]), [case])

    assert predictions == {"one": [{"name": "log_gym_session", "args": {"day": "A"}}]}


def test_summary_averages_cases() -> None:
    case = EvalCase(id="c", input="x", expected={"day": "A"})
    good = score_case(case, "t", [{"name": "t", "args": {"day": "A"}}], normalize)
    bad = score_case(case, "t", [], normalize)

    assert summarize([good, bad]) == {
        "cases": 2, "tool_accuracy": 0.5, "precision": 0.5, "recall": 0.5, "hallucinated": 0,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_evals.py -q`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.core.evals'`.

- [ ] **Step 3: Write the eval set**

`backend/src/coach/modules/gym/evals/extraction.yaml`:

```yaml
# Synthetic gym logging messages. expected: the log_gym_session arguments that must be
# extracted (exercise names as in the library); null means the tool must not be called.
tool: log_gym_session
cases:
  - id: gym-01
    input: did treino A today, goblet 22kg, rpe 7
    expected: {day: A, rpe: 7, lifts: [{exercise: Agachamento goblet, load_kg: 22}]}
  - id: gym-02
    input: Finished Treino B. Sumo 24 kg, serrote 18kg. Felt like an 8.
    expected: {day: B, rpe: 8, lifts: [{exercise: Agachamento terra sumo, load_kg: 24}, {exercise: Serrote, load_kg: 18}]}
  - id: gym-03
    input: gym done, everything as planned
    expected: {}
  - id: gym-04
    input: Did C but skipped the side lunges, knee was cranky
    expected: {day: C, lifts: [{exercise: Side lunge, skipped: true}]}
  - id: gym-05
    input: Treino A, swapped the bench press for push ups, rows with 20kg
    expected: {day: A, lifts: [{exercise: Supino reto com halter, swapped_to: push ups}, {exercise: Remada curvada, load_kg: 20}]}
  - id: gym-06
    input: 45 minute gym session, rpe 6
    expected: {duration_min: 45, rpe: 6}
  - id: gym-07
    input: B this morning, 50 minutes, rpe 7, sumo deadlift 26kg
    expected: {day: B, duration_min: 50, rpe: 7, lifts: [{exercise: Agachamento terra sumo, load_kg: 26}]}
  - id: gym-08
    input: "Treino C: stiff 16kg cada perna, supino ponte 20, military press 12kg"
    expected: {day: C, lifts: [{exercise: Stiff unilateral, load_kg: 16}, {exercise: Supino ponte com halter, load_kg: 20}, {exercise: Military press semi ajoelhado, load_kg: 12}]}
  - id: gym-09
    input: Did treino A. Goblet 24, remada 22, supino 20, afundo 12s. RPE 9
    expected: {day: A, rpe: 9, lifts: [{exercise: Agachamento goblet, load_kg: 24}, {exercise: Remada curvada, load_kg: 22}, {exercise: Supino reto com halter, load_kg: 20}, {exercise: Afundo, load_kg: 12}]}
  - id: gym-10
    input: pull ups went up to 10 reps today on B
    expected: {day: B, lifts: [{exercise: Barra fixa, reps: "10"}]}
  - id: gym-11
    input: skipped the copenhagen plank, rest as written, treino b
    expected: {day: B, lifts: [{exercise: Copenhagen plank, skipped: true}]}
  - id: gym-12
    input: Session A done in 55 minutes
    expected: {day: A, duration_min: 55}
  - id: gym-13
    input: "Today's gym: goblet squat only 3 sets instead of 4, 20kg"
    expected: {lifts: [{exercise: Agachamento goblet, sets: 3, load_kg: 20}]}
  - id: gym-14
    input: treino C feito, rpe 6
    expected: {day: C, rpe: 6}
  - id: gym-15
    input: how many gym sessions have I done this week?
    expected: null
```

- [ ] **Step 4: Implement the harness**

`backend/src/coach/core/evals.py`:

```python
"""Tool-call extraction evals: ``python -m coach.core.evals``.

Each module lists YAML eval sets in ``evals()``. Live mode asks the model once per case and
can record its answers to ``recordings/<set>.json``; replay mode scores those recordings, so CI
needs no API key.
"""

import argparse
import asyncio
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from coach.core.models import Athlete
from coach.core.prompt import system_prompt
from coach.core.registry import Registry
from coach.core.tools import CORE_TOOLS

type Normalizer = Callable[[str], str]

EVAL_ATHLETE = Athlete(
    id=UUID(int=0), name="Eval Athlete", timezone="Australia/Brisbane", telegram_chat_id=None
)
EVAL_NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
IGNORED_FIELDS = {"started_at", "notes"}


class EvalCase(BaseModel):
    """One message and the arguments it should produce (None: the tool must not be called)."""

    id: str
    input: str
    expected: dict[str, Any] | None


class EvalSet(BaseModel):
    """A YAML file of cases for one tool."""

    name: str
    tool: str
    cases: list[EvalCase]
    path: Path


def load_set(path: Path) -> EvalSet:
    """Read an eval set; its name is the file stem."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return EvalSet(name=path.stem, tool=data["tool"], cases=data["cases"], path=path)


def flatten(value: Any, normalize: Normalizer, prefix: str = "") -> dict[str, str]:
    """Dotted paths to comparable strings; empty values and ignored fields are dropped."""
    out: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if not prefix and key in IGNORED_FIELDS:
                continue
            out.update(flatten(item, normalize, f"{prefix}{key}" if not prefix else f"{prefix}.{key}"))
    elif isinstance(value, list):
        for position, item in enumerate(value):
            key = normalize(str(item["exercise"])) if isinstance(item, dict) and "exercise" in item else str(position)
            out.update(flatten(item, normalize, f"{prefix}[{key}]"))
    elif value is None or value is False:
        pass
    elif isinstance(value, bool):
        out[prefix] = "true"
    elif isinstance(value, int | float):
        out[prefix] = str(float(value))
    else:
        text = str(value)
        try:
            out[prefix] = str(float(text))
        except ValueError:
            out[prefix] = normalize(text)
    return out


@dataclass(frozen=True, slots=True)
class CaseScore:
    """How one case went."""

    case_id: str
    tool_ok: bool
    precision: float
    recall: float
    hallucinated: list[str]


def score_case(
    case: EvalCase, tool: str, calls: list[dict[str, Any]], normalize: Normalizer
) -> CaseScore:
    """Compare the first call to ``tool`` with the expectation."""
    call = next((c for c in calls if c["name"] == tool), None)
    if case.expected is None:
        return CaseScore(case.id, call is None, 1.0, 1.0, [])
    if call is None:
        return CaseScore(case.id, False, 0.0, 0.0, [])
    expected = flatten(case.expected, normalize)
    predicted = flatten(call["args"], normalize)
    correct = [k for k, v in expected.items() if predicted.get(k) == v]
    precision = len(correct) / len(predicted) if predicted else 1.0
    recall = len(correct) / len(expected) if expected else 1.0
    hallucinated = sorted(k for k in predicted if k not in expected)
    return CaseScore(case.id, True, precision, recall, hallucinated)


def summarize(scores: Sequence[CaseScore]) -> dict[str, Any]:
    """Averages across cases."""
    n = len(scores)
    return {
        "cases": n,
        "tool_accuracy": sum(s.tool_ok for s in scores) / n,
        "precision": sum(s.precision for s in scores) / n,
        "recall": sum(s.recall for s in scores) / n,
        "hallucinated": sum(len(s.hallucinated) for s in scores),
    }


async def predict(
    model: BaseChatModel, registry: Registry, cases: Sequence[EvalCase]
) -> dict[str, list[dict[str, Any]]]:
    """Ask the model once per case, with every tool bound and the real system prompt."""
    bound = model.bind_tools([*CORE_TOOLS, *registry.tools()])
    system = SystemMessage(system_prompt(EVAL_ATHLETE, registry, "", EVAL_NOW))
    out: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        reply = await bound.ainvoke([system, HumanMessage(case.input)])
        calls = reply.tool_calls if isinstance(reply, AIMessage) else []
        out[case.id] = [{"name": c["name"], "args": c["args"]} for c in calls]
    return out


def recording_path(eval_set: EvalSet) -> Path:
    """Where a set's recorded model answers live."""
    return eval_set.path.parent / "recordings" / f"{eval_set.name}.json"


async def _run(args: argparse.Namespace) -> None:
    from coach.core.config import get_settings
    from coach.core.db import create_pool
    from coach.core.llm import get_chat_model
    from coach.core.registry import default_registry
    from coach.modules.gym.library import normalize  # the only normalizer so far

    registry = default_registry()
    results: dict[str, dict[str, Any]] = {}
    for module in registry.modules:
        for path in module.evals():
            eval_set = load_set(path)
            recording = recording_path(eval_set)
            if args.mode == "live":
                settings = get_settings()
                predictions = await predict(get_chat_model(settings), registry, eval_set.cases)
                if args.record:
                    recording.parent.mkdir(parents=True, exist_ok=True)
                    recording.write_text(json.dumps(
                        {"model": settings.agent_model, "cases": predictions},
                        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            else:
                if not recording.exists():
                    raise SystemExit(f"No recording for {eval_set.name}; run with --mode live --record")
                predictions = json.loads(recording.read_text(encoding="utf-8"))["cases"]
            scores = [
                score_case(c, eval_set.tool, predictions.get(c.id, []), normalize)
                for c in eval_set.cases
            ]
            results[eval_set.name] = summarize(scores)
            print(f"{module.name}/{eval_set.name}: {json.dumps(results[eval_set.name])}")
            for s in scores:
                if not s.tool_ok or s.recall < 1 or s.hallucinated:
                    print(f"  {s.case_id}: tool_ok={s.tool_ok} recall={s.recall:.2f} "
                          f"invented={s.hallucinated}")
    if args.save_run:
        pool = create_pool(get_settings().database_url.get_secret_value())
        await pool.open()
        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "insert into eval_runs (dataset, mode, git_sha, model, metrics) "
                    "values ('synthetic', %s, %s, %s, %s)",
                    (args.mode, os.environ.get("GITHUB_SHA"), get_settings().agent_model,
                     Jsonb(results)),
                )
        finally:
            await pool.close()


def main(argv: Sequence[str] | None = None) -> None:
    """Run every enabled module's eval sets."""
    parser = argparse.ArgumentParser(prog="python -m coach.core.evals")
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--record", action="store_true", help="live: write recordings")
    parser.add_argument("--save-run", action="store_true", help="write eval_runs")
    asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
```

`module.py`: `evals()` returns `[HERE / "evals" / "extraction.yaml"]`.

Note: `_run` imports the gym normalizer lazily; that keeps `coach.core.evals` importable without modules. When a second module ships, move `normalize` to `coach.core` (it is generic text normalization) and drop the lazy import.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Record the first live run**

This sends 15 short prompts to Claude Haiku with the athlete's key from `backend/.env` (well under $0.05).
Run: `cd backend && uv run python -m coach.core.evals --mode live --record --save-run`
Expected: a line `gym/extraction: {"cases": 15, ...}` with the scores, `evals/recordings/extraction.json` written, and one `eval_runs` row in the local database.
Then: `uv run python -m coach.core.evals` (replay) prints the same numbers.
Record the numbers in the ledger; they are the "first eval score" for the week 2 post.

- [ ] **Step 7: Replay in CI**

Add after the Tests step in `.github/workflows/ci.yml`:

```yaml
      - name: Evals (replay)
        working-directory: backend
        run: uv run python -m coach.core.evals
```

- [ ] **Step 8: Quality gate and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd .. && git add backend .github && git commit -m "feat: add tool-call evals with recorded replay and the first gym eval set"
```

---

### Task 8: Docs and an end-to-end check with the real bot

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: docs that match the code; a verified Telegram round trip.

- [ ] **Step 1: Update the docs**

`docs/ARCHITECTURE.md`:
- Code map: add `core/evals.py` and the `modules/gym/` files.
- Request flows: add "Undo" (button with `undo:<session id>`, callback handled by `handle_update`, the core deletes the `sessions` row, module rows follow through foreign keys, a note goes into the thread).
- Module system: note that modules can attach reply buttons through `CoachContext.reply_buttons`.
- Data: add the gym tables.
- Testing and quality: replace the planned evals line with the replay/live description.

`README.md`, Local development: after `coach add-athlete`, add
`uv run python -m coach.modules.gym.seed --program <your program.yaml> --chat-id <id>` (sample: `src/coach/modules/gym/programs/sample.yaml`) and `uv run python -m coach.core.evals` (replay) / `--mode live --record` (needs the Anthropic key).

- [ ] **Step 2: End-to-end with the local bot**

Restart `coach poll` (it caches code at start).
Ask the athlete to send, in order: "what's my next gym session?", "did treino A, goblet 20kg, rpe 7", then tap Undo, then "what's next?".
Expected: the next session is Week 1 Treino A with its exercises; the log reply carries an Undo button; Undo answers "Undone." and posts "Undone: Week 1 Treino A."; the next session is Treino A again.
Check `agent_runs` for the four turns with no errors.

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md README.md
git commit -m "docs: describe the gym module, Undo and evals"
```
