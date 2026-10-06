# Week 1: Core Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A text message sent to the Telegram bot reaches a LangGraph agent running on Vercel, which can answer training-history questions through `query_history`, and replies.
Every turn is recorded in `agent_runs`.

**Architecture:** One Python package `coach` in `backend/` (src layout).
FastAPI exposes `POST /telegram` (webhook) and `GET /health`; a CLI offers `migrate`, `add-athlete`, `set-webhook` and `poll` (local long polling).
Both entry points share one update handler that runs a LangGraph graph `load_context -> agent <-> tools`, checkpointed in Supabase Postgres through `AsyncPostgresSaver`.
Discipline modules plug in through a `Registry`; week 1 ships the registry empty and proves it with a fake module in tests.
Data access is plain SQL through psycopg 3 rather than SQLAlchemy and Alembic, because the spec has every module own its SQL migrations folder; a 30-line migration runner applies core first, then each module.

**Tech Stack:** Python 3.14, uv, FastAPI, LangGraph 1.2, langchain-anthropic (Claude Haiku 4.5), psycopg 3 + psycopg-pool, pydantic-settings, httpx, Supabase Postgres (local via Supabase CLI), pytest + anyio, ruff, mypy, pre-commit, GitHub Actions, Vercel.

**Spec:** `Hybrid Athlete Coach — Project Plan.md` (repo root).
This plan implements the "Week 1" row of its build plan plus the cross-cutting decisions that week 1 code touches (allowlist, webhook secret, update dedupe, agent_runs, one forever thread trimmed to ~30 messages, RLS).

## Global Constraints

- Python `>=3.14` (Vercel supports 3.12, 3.13, 3.14); `.python-version` is `3.14`.
- Dependencies via `uv` only; `[tool.uv] exclude-newer = "7 days"` so nothing newer than a week is resolved; commit `uv.lock`.
- Quality gate: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest` must all pass before each commit.
- Type-hint everything; modern syntax (`X | None`, `list[X]`, `type` aliases); no bare `# type: ignore`, always `# type: ignore[code]  # reason`.
- Secrets are `SecretStr`, loaded from env vars prefixed `COACH_`; never log them. The bot token is part of Telegram URLs, so httpx request logging stays at WARNING.
- Model id: `claude-haiku-4-5-20251001`.
- Default athlete time zone: `Australia/Brisbane`.
- Vercel function region: `syd1`.
- Every table in `public` has row-level security enabled.
- No em dashes in any code, comment, doc or commit message.
- Commit after every task. Commit messages carry no AI or tool attribution lines (no `Co-Authored-By`, no "Generated with").
- Long Markdown files: one sentence per line.

## Review Focus

1. Telegram delivers the same update twice (retry after a slow response, or two concurrent deliveries): it must be handled exactly once. Tests: Task 4 concurrent `claim_update`, Task 8 duplicate webhook post.
2. An update that is not a plain text message (photo, sticker, edited message): no crash; a text-less message gets a short "text only for now" reply, other update types are ignored. Tests: Task 7.
3. The Anthropic API fails mid-turn: the athlete still gets a fallback reply, the webhook still returns 200 so Telegram does not retry forever, and `agent_runs.error` records it. Tests: Task 6, Task 8.
4. A reply longer than Telegram's 4096-character limit: it is split into several messages, none over the limit. Tests: Task 7.
5. "This week" near midnight: a session at Monday 05:00 Brisbane (Sunday 19:00 UTC) counts in the local Monday week, not the UTC one. Tests: Task 4.

---

## File Structure

```
.gitignore                         modify: python, env, coverage ignores
LICENSE                            MIT
README.md                          what it is, local dev commands
.pre-commit-config.yaml            hygiene hooks + ruff + mypy via uv
.github/workflows/ci.yml           lint, types, tests against local Supabase Postgres
supabase/config.toml               created by `supabase init`; local DB only
backend/
  .python-version                  3.14
  .env.example                     every COACH_ variable
  pyproject.toml                   deps, tool config, vercel entrypoint
  uv.lock
  vercel.json                      region syd1
  src/coach/
    __init__.py
    main.py                        FastAPI app: /health, /telegram
    cli.py                         coach migrate | add-athlete | set-webhook | poll
    core/
      __init__.py
      config.py                    Settings (pydantic-settings)
      db.py                        create_pool, Connection, Pool aliases
      models.py                    Athlete, AgentRun dataclasses
      migrations.py                apply_migrations, migrate_all
      migrations/0001_core.sql     core tables + RLS policies
      repo.py                      SQL for athletes, sessions, updates, agent_runs
      registry.py                  DisciplineModule, ScheduledJob, Registry, ENABLED
      context.py                   CoachContext (runtime context for graph + tools)
      prompt.py                    system prompt
      tools.py                     query_history, CORE_TOOLS
      llm.py                       get_chat_model
      graph.py                     CoachState, trim_history, build_graph
      turn.py                      run_turn, agent_runs recording
      telegram.py                  Update models, TelegramClient, split_message
      deps.py                      Deps, build_deps
      handler.py                   handle_update
      polling.py                   poll_once, run_polling
    modules/
      __init__.py                  gym (week 2) and surf (week 3) land here
  tests/
    __init__.py
    conftest.py                    pool, conn, athlete fixtures
    factories.py                   insert_session, new_update_id
    fakes.py                       FakeModule, FakeChatModel, ExplodingChatModel, TelegramRecorder, make_deps
    test_config.py
    test_migrations.py
    test_registry.py
    test_repo.py
    test_graph.py
    test_turn.py
    test_telegram.py
    test_api.py
    test_cli.py
scripts/provision.sh               interactive setup wizard (Task 11)
```

---

### Task 1: Repository and backend scaffold

**Files:**
- Modify: `.gitignore`
- Create: `LICENSE`, `README.md`, `.pre-commit-config.yaml`
- Create: `backend/.python-version`, `backend/.env.example`, `backend/pyproject.toml`, `backend/vercel.json`
- Create: `backend/src/coach/__init__.py`, `backend/src/coach/core/__init__.py`, `backend/src/coach/core/config.py`, `backend/src/coach/modules/__init__.py`
- Test: `backend/tests/__init__.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `coach.core.config.Settings` with fields `database_url: SecretStr`, `telegram_bot_token: SecretStr`, `telegram_webhook_secret: SecretStr`, `telegram_allowed_chat_ids: list[int]`, `anthropic_api_key: SecretStr`, `agent_model: str`, `history_messages: int`; `get_settings() -> Settings`; constant `DEFAULT_TIMEZONE = "Australia/Brisbane"`.

- [ ] **Step 1: Root files**

Replace `.gitignore` with:

```gitignore
/.lavish
.env
.venv/
__pycache__/
*.py[cod]
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/
.pytest_cache/
.vercel/
```

`LICENSE`: the standard MIT license text with the line `Copyright (c) 2026 Jean Loureiro`.

`README.md`:

```markdown
# Hybrid Athlete Coach

A Telegram coach that logs and plans BJJ, surf and gym training in one place and reasons across all three.
The full design lives in [the project plan](Hybrid%20Athlete%20Coach%20%E2%80%94%20Project%20Plan.md).
How the system fits together is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Local development

Requirements: uv, Docker, the Supabase CLI.

```bash
supabase db start                 # local Postgres on 127.0.0.1:54322
cd backend
cp .env.example .env              # fill in the Telegram and Anthropic values
uv sync
uv run coach migrate
uv run coach add-athlete --name "Your Name" --chat-id <your Telegram chat id>
uv run coach poll                 # long polling; use a separate dev bot
```

Quality gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
```

(Inside README the inner code fence is a normal triple-backtick block.)

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
      - id: detect-private-key
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: bash -c 'cd backend && uv run ruff check --fix .'
        language: system
        files: ^backend/
        pass_filenames: false
      - id: ruff-format
        name: ruff format
        entry: bash -c 'cd backend && uv run ruff format .'
        language: system
        files: ^backend/
        pass_filenames: false
      - id: mypy
        name: mypy
        entry: bash -c 'cd backend && uv run mypy'
        language: system
        files: ^backend/
        pass_filenames: false
```

- [ ] **Step 2: Backend project files**

`backend/.python-version`:

```
3.14
```

`backend/.env.example`:

```
COACH_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
COACH_TELEGRAM_BOT_TOKEN=
COACH_TELEGRAM_WEBHOOK_SECRET=
COACH_TELEGRAM_ALLOWED_CHAT_IDS=[]
COACH_ANTHROPIC_API_KEY=
COACH_AGENT_MODEL=claude-haiku-4-5-20251001
```

`backend/vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "regions": ["syd1"]
}
```

`backend/pyproject.toml`:

```toml
[project]
name = "coach"
version = "0.1.0"
description = "Hybrid Athlete Coach: a Telegram agent for BJJ, surf and gym training"
requires-python = ">=3.14"
dependencies = []

[project.scripts]
coach = "coach.cli:main"

[build-system]
requires = ["uv_build>=0.12.2,<0.13.0"]
build-backend = "uv_build"

[tool.uv]
exclude-newer = "7 days"

[tool.vercel]
entrypoint = "coach.main:app"

[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "ASYNC", "S", "BLE", "RUF", "N"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
files = ["src", "tests"]
mypy_path = "src"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

Empty files: `backend/src/coach/__init__.py`, `backend/src/coach/core/__init__.py`, `backend/tests/__init__.py`.

`backend/src/coach/modules/__init__.py`:

```python
"""Discipline modules. Gym arrives in week 2, surf in week 3, BJJ in phase 2."""
```

- [ ] **Step 3: Add dependencies**

```bash
cd backend
uv add fastapi httpx langgraph langgraph-checkpoint-postgres langchain-anthropic "psycopg[binary,pool]" pydantic-settings
uv add --dev pytest anyio pytest-cov ruff mypy pre-commit
```

Expected: `uv.lock` created; `pyproject.toml` dependencies get `>=` lower bounds (for example `fastapi>=0.141.1`, `langgraph>=1.2.12`).

- [ ] **Step 4: Write the failing test**

`backend/tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from coach.core.config import Settings

ENV = {
    "COACH_DATABASE_URL": "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    "COACH_TELEGRAM_BOT_TOKEN": "123:abc",
    "COACH_TELEGRAM_WEBHOOK_SECRET": "s3cret-hook",
    "COACH_TELEGRAM_ALLOWED_CHAT_IDS": "[111, 222]",
    "COACH_ANTHROPIC_API_KEY": "sk-ant-s3cret",
}


def test_reads_prefixed_env_and_parses_chat_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # values come from env

    assert settings.telegram_allowed_chat_ids == [111, 222]
    assert settings.agent_model == "claude-haiku-4-5-20251001"
    assert settings.history_messages == 30
    assert settings.database_url.get_secret_value().startswith("postgresql://")


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # values come from env

    assert "s3cret" not in repr(settings)


def test_missing_required_value_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]  # testing the missing-env failure
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coach.core.config'`.

- [ ] **Step 6: Implement**

`backend/src/coach/core/config.py`:

```python
"""Application settings loaded from the environment."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TIMEZONE = "Australia/Brisbane"


class Settings(BaseSettings):
    """Runtime configuration. Every variable is prefixed with ``COACH_``."""

    model_config = SettingsConfigDict(env_prefix="COACH_", env_file=".env", extra="ignore")

    database_url: SecretStr
    telegram_bot_token: SecretStr
    telegram_webhook_secret: SecretStr
    telegram_allowed_chat_ids: list[int] = Field(default_factory=list)
    anthropic_api_key: SecretStr
    agent_model: str = "claude-haiku-4-5-20251001"
    history_messages: int = Field(default=30, ge=4)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, read once from the environment."""
    return Settings()  # type: ignore[call-arg]  # values come from the environment
```

- [ ] **Step 7: Run the quality gate**

Run: `cd backend && uv run pytest tests/test_config.py -v && uv run ruff check . && uv run ruff format --check . && uv run mypy`
Expected: 3 passed; ruff and mypy clean. If mypy reports an unused `type: ignore`, delete that ignore.

- [ ] **Step 8: Install hooks and commit**

```bash
cd backend && uv run pre-commit install && cd ..
git add .gitignore LICENSE README.md .pre-commit-config.yaml backend docs
git commit -m "chore: scaffold backend package, tooling and settings"
```

---

### Task 2: Local database, migration runner and core schema

**Files:**
- Create: `supabase/` (via `supabase init`)
- Create: `backend/src/coach/core/db.py`, `backend/src/coach/core/models.py`, `backend/src/coach/core/migrations.py`, `backend/src/coach/core/migrations/0001_core.sql`
- Test: `backend/tests/conftest.py`, `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `coach.core.db`: `type Connection = AsyncConnection[DictRow]`, `type Pool = AsyncConnectionPool[AsyncConnection[DictRow]]`, `create_pool(database_url: str, *, max_size: int = 4) -> Pool` (unopened).
  - `coach.core.models`: `Athlete(id: UUID, name: str, timezone: str, telegram_chat_id: int | None)`, `type Trigger = Literal["message", "schedule"]`, `AgentRun(...)` (fields below).
  - `coach.core.migrations`: `CORE_MIGRATIONS: Path`, `type MigrationDir = tuple[str, Path]`, `apply_migrations(conn: Connection, dirs: Sequence[MigrationDir]) -> list[str]`, `migrate_all(pool: Pool, dirs: Sequence[MigrationDir]) -> list[str]`.
  - Test fixtures `pool` (session) and `conn` (per test, rolled back).

- [ ] **Step 1: Start the local database**

```bash
supabase init --with-vscode-settings=false --with-intellij-settings=false
supabase db start
```

Expected: `Started supabase local development setup.` and Postgres on `127.0.0.1:54322`.
If either flag is rejected by this CLI version, run plain `supabase init` and answer `N` to the editor prompts.

- [ ] **Step 2: Write the failing tests**

`backend/tests/conftest.py`:

```python
import os
from collections.abc import AsyncIterator

import pytest
from psycopg_pool import PoolTimeout

from coach.core.db import Connection, Pool, create_pool
from coach.core.migrations import CORE_MIGRATIONS, migrate_all

TEST_DATABASE_URL = os.environ.get(
    "COACH_TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def pool() -> AsyncIterator[Pool]:
    pool = create_pool(TEST_DATABASE_URL)
    try:
        await pool.open(wait=True, timeout=10)
    except PoolTimeout:
        pytest.fail("No test database. Start it with `supabase db start` from the repo root.")
    await migrate_all(pool, [("core", CORE_MIGRATIONS)])
    async with pool.connection() as conn:
        await conn.execute(
            "truncate athletes, processed_updates, eval_cases, eval_runs, "
            "checkpoints, checkpoint_writes, checkpoint_blobs cascade"
        )
        await conn.execute(
            "insert into disciplines (name, label) values ('testsport', 'Test sport') "
            "on conflict (name) do nothing"
        )
    yield pool
    await pool.close()


@pytest.fixture
async def conn(pool: Pool) -> AsyncIterator[Connection]:
    async with pool.connection() as connection, connection.transaction(force_rollback=True):
        yield connection
```

`backend/tests/test_migrations.py`:

```python
from pathlib import Path

import pytest

from coach.core.db import Connection, Pool
from coach.core.migrations import CORE_MIGRATIONS, migrate_all

pytestmark = pytest.mark.anyio


async def test_migrations_are_idempotent(pool: Pool) -> None:
    assert await migrate_all(pool, [("core", CORE_MIGRATIONS)]) == []


async def test_every_public_table_has_row_level_security(conn: Connection) -> None:
    cur = await conn.execute(
        "select tablename from pg_tables where schemaname = 'public' and not rowsecurity"
    )
    assert await cur.fetchall() == []


async def test_notes_embedding_matches_voyage_dimension(conn: Connection) -> None:
    cur = await conn.execute(
        "select atttypmod from pg_attribute "
        "where attrelid = 'public.notes'::regclass and attname = 'embedding'"
    )
    assert await cur.fetchone() == {"atttypmod": 1024}


async def test_anonymous_role_cannot_read_athletes(conn: Connection) -> None:
    await conn.execute("insert into athletes (name, telegram_chat_id) values ('Hidden', 999000111)")
    await conn.execute("set local role anon")

    cur = await conn.execute("select * from athletes")

    assert await cur.fetchall() == []


async def test_module_migrations_run_after_core(pool: Pool, tmp_path: Path) -> None:
    (tmp_path / "0001_fake.sql").write_text("create table fake_module_rows (id int primary key);")
    try:
        applied = await migrate_all(pool, [("core", CORE_MIGRATIONS), ("fake", tmp_path)])
        assert applied == ["fake/0001_fake.sql"]
    finally:
        async with pool.connection() as conn:
            await conn.execute("drop table if exists fake_module_rows")
            await conn.execute("delete from coach_migrations where id = 'fake/0001_fake.sql'")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_migrations.py -v`
Expected: ERROR at collection with `ModuleNotFoundError: No module named 'coach.core.db'`.

- [ ] **Step 4: Implement db and models**

`backend/src/coach/core/db.py`:

```python
"""Postgres connection pool shared by the app, the agent tools and the checkpointer."""

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

type Connection = AsyncConnection[DictRow]
type Pool = AsyncConnectionPool[AsyncConnection[DictRow]]


def create_pool(database_url: str, *, max_size: int = 4) -> Pool:
    """Create an unopened pool; callers ``await pool.open()``.

    Autocommit and dict rows are what the LangGraph checkpointer requires.
    Prepared statements are off because Supabase's transaction pooler cannot keep them.
    """
    return AsyncConnectionPool(
        conninfo=database_url,
        connection_class=AsyncConnection[DictRow],
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        min_size=1,
        max_size=max_size,
        open=False,
    )
```

`backend/src/coach/core/models.py`:

```python
"""Plain data objects passed between the core layers."""

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

type Trigger = Literal["message", "schedule"]


@dataclass(frozen=True, slots=True)
class Athlete:
    """The person being coached."""

    id: UUID
    name: str
    timezone: str
    telegram_chat_id: int | None


@dataclass(frozen=True, slots=True)
class AgentRun:
    """One agent turn as stored in ``agent_runs``."""

    athlete_id: UUID
    trigger: Trigger
    input: str
    output: str
    model: str
    latency_ms: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
```

- [ ] **Step 5: Implement the migration runner**

`backend/src/coach/core/migrations.py`:

```python
"""Plain-SQL migrations: core first, then each enabled module's own folder."""

from collections.abc import Sequence
from pathlib import Path

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.db import Connection, Pool

CORE_MIGRATIONS = Path(__file__).parent / "migrations"

type MigrationDir = tuple[str, Path]

# Supabase exposes the public schema over its REST API, so any table without RLS
# (including the checkpointer's own tables) would be readable with the anon key.
_ENABLE_RLS_EVERYWHERE = b"""
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' and not rowsecurity loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;
"""


async def apply_migrations(conn: Connection, dirs: Sequence[MigrationDir]) -> list[str]:
    """Apply every ``*.sql`` file not yet recorded, directory by directory, in filename order.

    Returns the ids (``owner/filename``) applied by this call.
    """
    await conn.execute(
        "create table if not exists coach_migrations ("
        "id text primary key, applied_at timestamptz not null default now())"
    )
    applied: list[str] = []
    for owner, directory in dirs:
        for path in sorted(directory.glob("*.sql")):
            migration_id = f"{owner}/{path.name}"
            async with conn.transaction():
                cur = await conn.execute(
                    "insert into coach_migrations (id) values (%s) on conflict (id) do nothing",
                    (migration_id,),
                )
                if cur.rowcount == 0:
                    continue
                await conn.execute(path.read_bytes())
            applied.append(migration_id)
    return applied


async def migrate_all(pool: Pool, dirs: Sequence[MigrationDir]) -> list[str]:
    """Apply SQL migrations, create the LangGraph checkpoint tables, and enforce RLS."""
    async with pool.connection() as conn:
        applied = await apply_migrations(conn, dirs)
    await AsyncPostgresSaver(pool).setup()
    async with pool.connection() as conn:
        await conn.execute(_ENABLE_RLS_EVERYWHERE)
    return applied
```

- [ ] **Step 6: Write the core migration**

`backend/src/coach/core/migrations/0001_core.sql`:

```sql
create extension if not exists vector with schema extensions;

-- a text key, not an enum: a new module adds a row instead of altering a type
create table disciplines (
  name text primary key,
  label text not null,
  enabled boolean not null default true
);

create table athletes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique references auth.users(id),  -- magic-link login for the dashboard
  telegram_chat_id bigint unique,
  name text not null,
  timezone text not null default 'Australia/Brisbane',
  profile jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table sessions (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  discipline text not null references disciplines(name),
  started_at timestamptz not null,
  duration_min int,
  rpe smallint check (rpe between 1 and 10),
  summary text,
  raw_input text,
  input_type text check (input_type in ('voice', 'text', 'photo')),
  created_at timestamptz not null default now()
);
create index on sessions (athlete_id, started_at desc);

create table readiness_checkins (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  checked_on date not null,
  area text,
  level smallint check (level between 1 and 5),
  energy smallint check (energy between 1 and 5),
  note text
);
create index on readiness_checkins (athlete_id, checked_on desc);

create table notes (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  session_id uuid references sessions(id) on delete set null,
  discipline text references disciplines(name),
  kind text check (kind in ('technique', 'coach_tip', 'spot', 'reflection')),
  content text not null,
  embedding extensions.vector(1024),   -- voyage-4-lite; confirm the dimension in week 4
  created_at timestamptz not null default now()
);
create index on notes using hnsw (embedding extensions.vector_cosine_ops);

create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid references athletes(id) on delete cascade,
  trigger text not null check (trigger in ('message', 'schedule')),
  input text,
  tool_calls jsonb not null default '[]',  -- [{tool, module, args, status, result_summary}]
  output text,
  model text,
  input_tokens int,
  output_tokens int,
  latency_ms int,
  error text,                              -- set when the model call failed
  created_at timestamptz not null default now()
);
create index on agent_runs (athlete_id, created_at desc);

create table processed_updates (
  update_id bigint primary key,            -- Telegram retries a webhook; insert first, skip on conflict
  processed_at timestamptz not null default now()
);

create table job_runs (
  athlete_id uuid not null references athletes(id) on delete cascade,
  job text not null,
  local_date date not null,
  ran_at timestamptz not null default now(),
  primary key (athlete_id, job, local_date)
);

create table eval_cases (                  -- private real transcripts; the public synthetic set is in the repo
  id uuid primary key default gen_random_uuid(),
  discipline text references disciplines(name),
  eval_set text not null check (eval_set in ('extraction', 'tool_choice', 'coaching')),
  input text not null,
  expected jsonb not null,
  created_at timestamptz not null default now()
);

create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  dataset text not null check (dataset in ('synthetic', 'private')),
  mode text not null check (mode in ('replay', 'live')),
  git_sha text,
  model text,
  metrics jsonb not null,
  created_at timestamptz not null default now()
);

-- Row-level security: the backend uses the service role (bypasses RLS);
-- the dashboard reads as the one logged-in athlete.
alter table disciplines enable row level security;
alter table athletes enable row level security;
alter table sessions enable row level security;
alter table readiness_checkins enable row level security;
alter table notes enable row level security;
alter table agent_runs enable row level security;
alter table processed_updates enable row level security;
alter table job_runs enable row level security;
alter table eval_cases enable row level security;
alter table eval_runs enable row level security;

create policy "authenticated read disciplines" on disciplines
  for select to authenticated using (true);
create policy "athlete reads own profile" on athletes
  for select to authenticated using (user_id = (select auth.uid()));
create policy "athlete reads own sessions" on sessions
  for select to authenticated
  using (athlete_id in (select id from athletes where user_id = (select auth.uid())));
create policy "athlete reads own readiness" on readiness_checkins
  for select to authenticated
  using (athlete_id in (select id from athletes where user_id = (select auth.uid())));
create policy "athlete reads own notes" on notes
  for select to authenticated
  using (athlete_id in (select id from athletes where user_id = (select auth.uid())));
create policy "athlete reads own agent runs" on agent_runs
  for select to authenticated
  using (athlete_id in (select id from athletes where user_id = (select auth.uid())));
create policy "authenticated read eval runs" on eval_runs
  for select to authenticated using (true);
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_migrations.py -v`
Expected: 5 passed.

- [ ] **Step 8: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean, 8 passed.

```bash
git add supabase backend
git commit -m "feat: add core schema, migration runner and local Supabase database"
```

---

### Task 3: Module registry

**Files:**
- Create: `backend/src/coach/core/registry.py`, `backend/src/coach/core/context.py`
- Test: `backend/tests/fakes.py`, `backend/tests/test_registry.py`

**Interfaces:**
- Consumes: `Athlete` (Task 2), `CORE_MIGRATIONS`, `MigrationDir` (Task 2), `Connection` (Task 2).
- Produces:
  - `ScheduledJob(name: str, is_due: Callable[[Athlete, datetime], bool], run: Callable[[CoachContext], Awaitable[None]])`.
  - `DisciplineModule` Protocol: `name: str`, `migrations: Path`, `tools() -> list[BaseTool]`, `prompt(athlete) -> str`, `async context(conn, athlete) -> str`, `jobs() -> list[ScheduledJob]`, `evals() -> list[Path]`.
  - `Registry(modules)`: `.modules`, `.tools() -> list[BaseTool]`, `.tool_owner(tool_name) -> str` ("core" when unknown), `.prompt(athlete) -> str`, `async .context(conn, athlete) -> str`, `.migration_dirs() -> list[MigrationDir]`.
  - `ENABLED: list[DisciplineModule]`, `default_registry() -> Registry`.
  - `coach.core.context.CoachContext(athlete: Athlete, pool: Pool, registry: Registry, now: Callable[[], datetime])` (frozen dataclass; `now` defaults to UTC now). It lives here because `ScheduledJob` refers to it and the mypy pre-commit hook must resolve that import in this commit.
  - Test helper `tests.fakes.FakeModule` and tool `fake_lookup`.

Spec deviation, on purpose: `context()` is async and takes a connection because every useful summary reads the database.

- [ ] **Step 1: Write the failing tests**

`backend/tests/fakes.py`:

```python
"""Test doubles shared across the suite."""

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool, tool

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
```

`backend/tests/test_registry.py`:

```python
from pathlib import Path
from uuid import uuid4

import pytest

from coach.core.db import Connection
from coach.core.migrations import CORE_MIGRATIONS
from coach.core.models import Athlete
from coach.core.registry import Registry, default_registry
from tests.fakes import FakeModule, fake_lookup

ATHLETE = Athlete(id=uuid4(), name="Jean", timezone="Australia/Brisbane", telegram_chat_id=1)


def test_default_registry_starts_empty() -> None:
    assert default_registry().modules == ()


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
    registry = Registry([FakeModule(name="a", module_tools=[], prompt_text="A rules"),
                         FakeModule(name="b", module_tools=[], prompt_text="  ")])

    assert registry.prompt(ATHLETE) == "A rules"


@pytest.mark.anyio
async def test_context_prefixes_module_names_and_skips_empty(conn: Connection) -> None:
    registry = Registry([FakeModule(name="surf", module_tools=[], context_text="good swell Thu"),
                         FakeModule(name="gym", module_tools=[], context_text="")])

    assert await registry.context(conn, ATHLETE) == "surf: good swell Thu"


def test_migration_dirs_put_core_first() -> None:
    registry = Registry([FakeModule(migrations=Path("/mods/fakesport"))])

    assert registry.migration_dirs() == [
        ("core", CORE_MIGRATIONS),
        ("fakesport", Path("/mods/fakesport")),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_registry.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.core.registry'`.

- [ ] **Step 3: Implement**

`backend/src/coach/core/registry.py`:

```python
"""Discipline modules and the registry that wires them into the core."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from langchain_core.tools import BaseTool

from coach.core.migrations import CORE_MIGRATIONS, MigrationDir
from coach.core.models import Athlete

if TYPE_CHECKING:
    from coach.core.context import CoachContext
    from coach.core.db import Connection


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    """A proactive job; ``is_due`` receives the athlete's local time (used from week 5)."""

    name: str
    is_due: Callable[[Athlete, datetime], bool]
    run: Callable[[CoachContext], Awaitable[None]]


class DisciplineModule(Protocol):
    """Everything a sport contributes. Modules never import each other."""

    name: str
    migrations: Path

    def tools(self) -> list[BaseTool]: ...

    def prompt(self, athlete: Athlete) -> str: ...

    async def context(self, conn: Connection, athlete: Athlete) -> str: ...

    def jobs(self) -> list[ScheduledJob]: ...

    def evals(self) -> list[Path]: ...


class Registry:
    """The enabled modules, validated once, queried by the graph, CLI and job tick."""

    def __init__(self, modules: Sequence[DisciplineModule]) -> None:
        names = [m.name for m in modules]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate module names: {names}")
        if "core" in names:
            raise ValueError('"core" is reserved for core tools and migrations')
        self._modules = tuple(modules)
        self._tool_owner: dict[str, str] = {}
        for module in self._modules:
            for module_tool in module.tools():
                if module_tool.name in self._tool_owner:
                    raise ValueError(f"tool {module_tool.name!r} is registered twice")
                self._tool_owner[module_tool.name] = module.name

    @property
    def modules(self) -> tuple[DisciplineModule, ...]:
        """The enabled modules, in migration order."""
        return self._modules

    def tools(self) -> list[BaseTool]:
        """Every module tool, to bind next to the core tools."""
        return [t for m in self._modules for t in m.tools()]

    def tool_owner(self, tool_name: str) -> str:
        """The module that owns a tool, or ``"core"``."""
        return self._tool_owner.get(tool_name, "core")

    def prompt(self, athlete: Athlete) -> str:
        """The modules' system prompt fragments, joined."""
        fragments = (m.prompt(athlete).strip() for m in self._modules)
        return "\n\n".join(f for f in fragments if f)

    async def context(self, conn: Connection, athlete: Athlete) -> str:
        """One ``module: summary`` line per module with something to say."""
        lines: list[str] = []
        for module in self._modules:
            text = (await module.context(conn, athlete)).strip()
            if text:
                lines.append(f"{module.name}: {text}")
        return "\n".join(lines)

    def migration_dirs(self) -> list[MigrationDir]:
        """Core migrations first, then each module's."""
        return [("core", CORE_MIGRATIONS), *((m.name, m.migrations) for m in self._modules)]


# Enabled discipline modules, in migration order. Week 2 adds GymModule(), week 3 SurfModule().
ENABLED: list[DisciplineModule] = []


def default_registry() -> Registry:
    """The registry built from ``ENABLED``."""
    return Registry(ENABLED)
```

Then the runtime context (imported by `registry.py` under `TYPE_CHECKING` only, so there is no import cycle):

`backend/src/coach/core/context.py`:

```python
"""Runtime context passed to every graph node and tool, never chosen by the model."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from coach.core.db import Pool
from coach.core.models import Athlete
from coach.core.registry import Registry


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CoachContext:
    """Who the turn is for and the dependencies the tools need."""

    athlete: Athlete
    pool: Pool
    registry: Registry
    now: Callable[[], datetime] = field(default=_utcnow)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_registry.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`

```bash
git add backend
git commit -m "feat: add discipline module registry"
```

---

### Task 4: Core repository queries

**Files:**
- Create: `backend/src/coach/core/repo.py`
- Modify: `backend/tests/conftest.py` (add `athlete` fixture)
- Test: `backend/tests/factories.py`, `backend/tests/test_repo.py`

**Interfaces:**
- Consumes: `Connection`, `Pool` (Task 2), `Athlete`, `AgentRun` (Task 2), `DEFAULT_TIMEZONE` (Task 1).
- Produces (all `async`, first argument `conn: Connection`):
  - `create_athlete(conn, *, name: str, telegram_chat_id: int | None, timezone: str = DEFAULT_TIMEZONE) -> Athlete`
  - `get_athlete_by_chat_id(conn, chat_id: int) -> Athlete | None`
  - `claim_update(conn, update_id: int) -> bool` (True only for the first claim)
  - `recent_sessions(conn, athlete: Athlete, *, since: datetime, limit: int = 50) -> list[dict[str, Any]]`
  - `sessions_per_discipline(conn, athlete: Athlete, *, since: datetime) -> list[dict[str, Any]]`
  - `weekly_load(conn, athlete: Athlete, *, since: datetime) -> list[dict[str, Any]]`
  - `record_agent_run(conn, run: AgentRun) -> UUID`
  - Fixture `athlete` (committed, random chat id); helpers `insert_session(...)`, `new_update_id()`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/factories.py`:

```python
"""Row builders for tests."""

import secrets
from datetime import datetime
from uuid import UUID

from coach.core.db import Connection
from coach.core.models import Athlete


def new_chat_id() -> int:
    return secrets.randbelow(10**12) + 1


def new_update_id() -> int:
    return secrets.randbelow(10**15) + 1


async def insert_session(
    conn: Connection,
    athlete: Athlete,
    *,
    started_at: datetime,
    discipline: str = "testsport",
    duration_min: int = 60,
    rpe: int = 6,
) -> UUID:
    cur = await conn.execute(
        "insert into sessions (athlete_id, discipline, started_at, duration_min, rpe) "
        "values (%s, %s, %s, %s, %s) returning id",
        (athlete.id, discipline, started_at, duration_min, rpe),
    )
    row = await cur.fetchone()
    assert row is not None
    session_id: UUID = row["id"]
    return session_id
```

Append to `backend/tests/conftest.py`:

```python
from coach.core.models import Athlete
from coach.core.repo import create_athlete
from tests.factories import new_chat_id


@pytest.fixture
async def athlete(pool: Pool) -> Athlete:
    async with pool.connection() as connection:
        return await create_athlete(connection, name="Test Athlete", telegram_chat_id=new_chat_id())
```

(Move the two new imports up to the import block at the top of the file.)

`backend/tests/test_repo.py`:

```python
import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from coach.core.db import Connection, Pool
from coach.core.models import AgentRun, Athlete
from coach.core.repo import (
    claim_update,
    create_athlete,
    get_athlete_by_chat_id,
    recent_sessions,
    record_agent_run,
    sessions_per_discipline,
    weekly_load,
)
from tests.factories import insert_session, new_chat_id, new_update_id

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


async def test_finds_athlete_by_chat_id(conn: Connection) -> None:
    chat_id = new_chat_id()
    created = await create_athlete(conn, name="Jean", telegram_chat_id=chat_id)

    assert await get_athlete_by_chat_id(conn, chat_id) == created
    assert created.timezone == "Australia/Brisbane"
    assert await get_athlete_by_chat_id(conn, new_chat_id()) is None


async def test_claim_update_only_succeeds_once(conn: Connection) -> None:
    update_id = new_update_id()

    assert await claim_update(conn, update_id) is True
    assert await claim_update(conn, update_id) is False


async def test_concurrent_claims_have_exactly_one_winner(pool: Pool) -> None:
    update_id = new_update_id()

    async def claim() -> bool:
        async with pool.connection() as connection:
            return await claim_update(connection, update_id)

    results = await asyncio.gather(*(claim() for _ in range(4)))

    assert sorted(results) == [False, False, False, True]


async def test_history_queries_only_see_this_athlete_and_window(conn: Connection) -> None:
    me = await create_athlete(conn, name="Me", telegram_chat_id=new_chat_id())
    other = await create_athlete(conn, name="Other", telegram_chat_id=new_chat_id())
    await insert_session(conn, me, started_at=NOW - timedelta(days=1), duration_min=90, rpe=7)
    await insert_session(conn, me, started_at=NOW - timedelta(days=40))
    await insert_session(conn, other, started_at=NOW - timedelta(days=1))
    since = NOW - timedelta(days=14)

    per_discipline = await sessions_per_discipline(conn, me, since=since)
    recent = await recent_sessions(conn, me, since=since)

    assert per_discipline == [{"discipline": "testsport", "sessions": 1, "minutes": 90}]
    assert [r["duration_min"] for r in recent] == [90]


async def test_weekly_load_uses_the_athletes_local_week(conn: Connection) -> None:
    me = await create_athlete(conn, name="Me", telegram_chat_id=new_chat_id())
    # Sunday 22:00 in Brisbane (UTC+10) belongs to the week starting Monday 28 Sep.
    await insert_session(conn, me, started_at=datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
                         duration_min=60, rpe=5)
    # Monday 05:00 in Brisbane is still Sunday in UTC, but it starts the local week of 5 Oct.
    await insert_session(conn, me, started_at=datetime(2026, 10, 4, 19, 0, tzinfo=UTC),
                         duration_min=60, rpe=7)

    weeks = await weekly_load(conn, me, since=NOW - timedelta(days=14))

    assert weeks == [
        {"week_start": date(2026, 9, 28), "sessions": 1, "minutes": 60, "load": 300},
        {"week_start": date(2026, 10, 5), "sessions": 1, "minutes": 60, "load": 420},
    ]


async def test_records_an_agent_run(conn: Connection, athlete: Athlete) -> None:
    run = AgentRun(
        athlete_id=athlete.id, trigger="message", input="hi", output="hello",
        model="test-model", latency_ms=12,
        tool_calls=[{"tool": "query_history", "module": "core", "args": {"kind": "weekly_load"}}],
        input_tokens=10, output_tokens=3,
    )

    run_id = await record_agent_run(conn, run)

    cur = await conn.execute("select * from agent_runs where id = %s", (run_id,))
    row = await cur.fetchone()
    assert row is not None
    assert row["tool_calls"][0]["tool"] == "query_history"
    assert (row["input_tokens"], row["output_tokens"], row["error"]) == (10, 3, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_repo.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.core.repo'`.

- [ ] **Step 3: Implement**

`backend/src/coach/core/repo.py`:

```python
"""SQL for the core tables. Every function takes an open connection; callers own transactions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncCursor
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from coach.core.config import DEFAULT_TIMEZONE
from coach.core.db import Connection
from coach.core.models import AgentRun, Athlete


async def _one(cur: AsyncCursor[DictRow]) -> DictRow:
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("query returned no row")
    return row


def _athlete(row: DictRow) -> Athlete:
    return Athlete(
        id=row["id"],
        name=row["name"],
        timezone=row["timezone"],
        telegram_chat_id=row["telegram_chat_id"],
    )


async def create_athlete(
    conn: Connection, *, name: str, telegram_chat_id: int | None, timezone: str = DEFAULT_TIMEZONE
) -> Athlete:
    """Insert an athlete and return it."""
    cur = await conn.execute(
        "insert into athletes (name, telegram_chat_id, timezone) values (%s, %s, %s) "
        "returning id, name, timezone, telegram_chat_id",
        (name, telegram_chat_id, timezone),
    )
    return _athlete(await _one(cur))


async def get_athlete_by_chat_id(conn: Connection, chat_id: int) -> Athlete | None:
    """The athlete linked to a Telegram chat, if any."""
    cur = await conn.execute(
        "select id, name, timezone, telegram_chat_id from athletes where telegram_chat_id = %s",
        (chat_id,),
    )
    row = await cur.fetchone()
    return _athlete(row) if row else None


async def claim_update(conn: Connection, update_id: int) -> bool:
    """Record a Telegram update id; True only the first time, so retries become no-ops."""
    cur = await conn.execute(
        "insert into processed_updates (update_id) values (%s) on conflict (update_id) do nothing",
        (update_id,),
    )
    return cur.rowcount == 1


async def recent_sessions(
    conn: Connection, athlete: Athlete, *, since: datetime, limit: int = 50
) -> list[dict[str, Any]]:
    """Sessions since a moment, newest first."""
    cur = await conn.execute(
        "select discipline, started_at, duration_min, rpe, summary from sessions "
        "where athlete_id = %(athlete_id)s and started_at >= %(since)s "
        "order by started_at desc limit %(limit)s",
        {"athlete_id": athlete.id, "since": since, "limit": limit},
    )
    return await cur.fetchall()


async def sessions_per_discipline(
    conn: Connection, athlete: Athlete, *, since: datetime
) -> list[dict[str, Any]]:
    """Session count and minutes per discipline since a moment."""
    cur = await conn.execute(
        "select discipline, count(*)::int as sessions, "
        "coalesce(sum(duration_min), 0)::int as minutes from sessions "
        "where athlete_id = %(athlete_id)s and started_at >= %(since)s "
        "group by discipline order by discipline",
        {"athlete_id": athlete.id, "since": since},
    )
    return await cur.fetchall()


async def weekly_load(conn: Connection, athlete: Athlete, *, since: datetime) -> list[dict[str, Any]]:
    """Sessions, minutes and load (minutes x RPE) per week, in the athlete's time zone."""
    cur = await conn.execute(
        "select (date_trunc('week', started_at at time zone %(tz)s))::date as week_start, "
        "count(*)::int as sessions, coalesce(sum(duration_min), 0)::int as minutes, "
        "coalesce(sum(duration_min * rpe), 0)::int as load from sessions "
        "where athlete_id = %(athlete_id)s and started_at >= %(since)s "
        "group by 1 order by 1",
        {"tz": athlete.timezone, "athlete_id": athlete.id, "since": since},
    )
    return await cur.fetchall()


async def record_agent_run(conn: Connection, run: AgentRun) -> UUID:
    """Store one agent turn for the trace viewer and evals."""
    cur = await conn.execute(
        "insert into agent_runs (athlete_id, trigger, input, tool_calls, output, model, "
        "input_tokens, output_tokens, latency_ms, error) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (
            run.athlete_id, run.trigger, run.input, Jsonb(run.tool_calls), run.output, run.model,
            run.input_tokens, run.output_tokens, run.latency_ms, run.error,
        ),
    )
    run_id: UUID = (await _one(cur))["id"]
    return run_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_repo.py -v`
Expected: 6 passed.

- [ ] **Step 5: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest`

```bash
git add backend
git commit -m "feat: add core repository queries with local-week load and update dedupe"
```

---

### Task 5: Agent graph with `query_history`

**Files:**
- Create: `backend/src/coach/core/prompt.py`, `backend/src/coach/core/tools.py`, `backend/src/coach/core/llm.py`, `backend/src/coach/core/graph.py`
- Modify: `backend/tests/fakes.py` (add `FakeChatModel`, `scripted`)
- Test: `backend/tests/test_graph.py`

**Interfaces:**
- Consumes: `Registry`, `CoachContext` (Task 3), repo history queries (Task 4), `Pool` (Task 2), `Settings` (Task 1).
- Produces:
  - `system_prompt(athlete: Athlete, registry: Registry, context: str, now: datetime) -> str`; constant `CORE_PROMPT`.
  - `query_history` tool; `CORE_TOOLS: list[BaseTool]`.
  - `get_chat_model(settings: Settings) -> BaseChatModel`.
  - `CoachState`, `type CoachGraph = CompiledStateGraph[Any, Any, Any, Any]`, `trim_history(messages, max_messages) -> list[BaseMessage]`, `build_graph(model, registry, checkpointer=None, *, history_messages=30) -> CoachGraph`.
  - Test helpers `FakeChatModel` (records prompts in `.seen`), `scripted(*replies) -> FakeChatModel`.

- [ ] **Step 1: Add the fake model**

Append to `backend/tests/fakes.py` (merge imports into the top block):

```python
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field


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
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_graph.py`:

```python
import json
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.config import Settings
from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import build_graph, trim_history
from coach.core.llm import get_chat_model
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.repo import create_athlete
from tests.factories import insert_session, new_chat_id
from tests.fakes import FakeModule, fake_lookup, scripted

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def context(athlete: Athlete, pool: Pool, registry: Registry | None = None) -> CoachContext:
    return CoachContext(athlete=athlete, pool=pool, registry=registry or Registry([]),
                        now=lambda: NOW)


def call(name: str, args: dict[str, object], call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


async def test_answers_from_query_history_for_the_context_athlete(
    pool: Pool, athlete: Athlete
) -> None:
    async with pool.connection() as conn:
        other = await create_athlete(conn, name="Other", telegram_chat_id=new_chat_id())
        await insert_session(conn, athlete, started_at=NOW - timedelta(days=1))
        await insert_session(conn, other, started_at=NOW - timedelta(days=1))
    model = scripted(call("query_history", {"kind": "per_discipline", "days": 30}),
                     "You trained once.")
    graph = build_graph(model, Registry([]))

    out = await graph.ainvoke({"messages": [HumanMessage("how much did I train?")]},
                              context=context(athlete, pool))

    tool_message = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert json.loads(tool_message.text) == [
        {"discipline": "testsport", "sessions": 1, "minutes": 60}
    ]
    assert out["messages"][-1].text == "You trained once."


async def test_invalid_tool_arguments_come_back_as_a_tool_error(
    pool: Pool, athlete: Athlete
) -> None:
    model = scripted(call("query_history", {"kind": "weekly_load", "days": 0}), "Sorry.")
    graph = build_graph(model, Registry([]))

    out = await graph.ainvoke({"messages": [HumanMessage("load?")]},
                              context=context(athlete, pool))

    tool_message = next(m for m in out["messages"] if isinstance(m, ToolMessage))
    assert tool_message.status == "error"


async def test_system_prompt_carries_module_prompt_context_and_local_time(
    pool: Pool, athlete: Athlete
) -> None:
    registry = Registry([FakeModule()])
    model = scripted("ok")
    graph = build_graph(model, registry)

    await graph.ainvoke({"messages": [HumanMessage("hi")]},
                        context=context(athlete, pool, registry))

    system = model.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "FAKE PROMPT" in system.text
    assert "fakesport: fake context line" in system.text
    assert "Test Athlete" in system.text
    assert "Tuesday 2026-10-06 19:00" in system.text  # 09:00 UTC in Brisbane


async def test_thread_history_stays_inside_the_window(pool: Pool, athlete: Athlete) -> None:
    model = scripted(*[f"reply {i}" for i in range(12)])
    graph = build_graph(model, Registry([]), InMemorySaver(), history_messages=6)
    config: RunnableConfig = {"configurable": {"thread_id": "window-test"}}

    for i in range(12):
        await graph.ainvoke({"messages": [HumanMessage(f"message {i}")]}, config,
                            context=context(athlete, pool))

    state = await graph.aget_state(config)
    messages = state.values["messages"]
    assert len(messages) <= 7
    assert isinstance(messages[0], HumanMessage)
    assert len(model.seen[-1]) <= 7  # system prompt + at most 6 history messages


def test_trim_never_starts_on_an_orphaned_tool_result() -> None:
    messages = [
        HumanMessage("a", id="1"), call("query_history", {"kind": "weekly_load"}),
        ToolMessage("[]", tool_call_id="call-1", id="3"), AIMessage("b", id="4"),
        HumanMessage("c", id="5"), AIMessage("d", id="6"),
    ]

    assert trim_history(messages, 4) == messages[4:]


def test_rejects_a_module_tool_that_shadows_a_core_tool() -> None:
    shadow = fake_lookup.model_copy(update={"name": "query_history"})

    with pytest.raises(ValueError, match="query_history"):
        build_graph(scripted("x"), Registry([FakeModule(module_tools=[shadow])]))


def test_chat_model_uses_the_configured_claude_model() -> None:
    settings = Settings.model_validate({
        "database_url": "postgresql://x", "telegram_bot_token": "t",
        "telegram_webhook_secret": "s", "anthropic_api_key": "sk-test",
    })

    model = get_chat_model(settings)

    assert getattr(model, "model") == "claude-haiku-4-5-20251001"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_graph.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.core.context'`.

- [ ] **Step 4: Implement prompt and llm**

`backend/src/coach/core/prompt.py`:

```python
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
```

`backend/src/coach/core/llm.py`:

```python
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
```

If mypy rejects a keyword on `ChatAnthropic(...)` because of a pydantic alias, add `# type: ignore[call-arg]  # pydantic field alias` on that line only.

- [ ] **Step 5: Implement the tool**

`backend/src/coach/core/tools.py`:

```python
"""Core tools, bound to the agent whatever modules are enabled."""

import json
from datetime import timedelta
from typing import Annotated, Literal

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import ToolRuntime
from pydantic import Field

from coach.core.context import CoachContext
from coach.core.repo import recent_sessions, sessions_per_discipline, weekly_load


@tool
async def query_history(
    kind: Literal["recent_sessions", "weekly_load", "per_discipline"],
    runtime: ToolRuntime[CoachContext],
    days: Annotated[int, Field(ge=1, le=365)] = 14,
) -> str:
    """Query the athlete's training history across every discipline.

    kind: recent_sessions lists sessions newest first; weekly_load totals sessions,
    minutes and load (minutes x RPE) per week in the athlete's time zone;
    per_discipline counts sessions and minutes per discipline.
    days: how many days back to look.
    """
    ctx = runtime.context
    since = ctx.now() - timedelta(days=days)
    async with ctx.pool.connection() as conn:
        match kind:
            case "recent_sessions":
                rows = await recent_sessions(conn, ctx.athlete, since=since)
            case "weekly_load":
                rows = await weekly_load(conn, ctx.athlete, since=since)
            case "per_discipline":
                rows = await sessions_per_discipline(conn, ctx.athlete, since=since)
    return json.dumps(rows, default=str)


CORE_TOOLS: list[BaseTool] = [query_history]
```

- [ ] **Step 6: Implement the graph**

`backend/src/coach/core/graph.py`:

```python
"""The LangGraph agent: load_context -> agent <-> tools."""

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, RemoveMessage, SystemMessage, trim_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime

from coach.core.context import CoachContext
from coach.core.prompt import system_prompt
from coach.core.registry import Registry
from coach.core.tools import CORE_TOOLS

type CoachGraph = CompiledStateGraph[Any, Any, Any, Any]


class CoachState(MessagesState):
    """Conversation messages plus the module context loaded at the start of the turn."""

    context: str


def trim_history(messages: Sequence[BaseMessage], max_messages: int) -> list[BaseMessage]:
    """Keep the newest messages, starting on a human turn so tool calls keep their results."""
    return trim_messages(
        messages, max_tokens=max_messages, token_counter=len, strategy="last", start_on="human"
    )


def build_graph(
    model: BaseChatModel,
    registry: Registry,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    history_messages: int = 30,
) -> CoachGraph:
    """Bind core and module tools to the model and wire the agent loop."""
    tools = [*CORE_TOOLS, *registry.tools()]
    names = [t.name for t in tools]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"tool names used twice: {duplicates}")
    bound = model.bind_tools(tools)

    async def load_context(state: CoachState, runtime: Runtime[CoachContext]) -> dict[str, Any]:
        ctx = runtime.context
        async with ctx.pool.connection() as conn:
            return {"context": await ctx.registry.context(conn, ctx.athlete)}

    async def agent(state: CoachState, runtime: Runtime[CoachContext]) -> dict[str, Any]:
        ctx = runtime.context
        history = trim_history(state["messages"], history_messages)
        system = SystemMessage(
            system_prompt(ctx.athlete, ctx.registry, state.get("context", ""), ctx.now())
        )
        reply = await bound.ainvoke([system, *history])
        # Drop what fell out of the window so the checkpointed thread stays bounded.
        kept = {m.id for m in history}
        stale = [RemoveMessage(id=m.id) for m in state["messages"] if m.id and m.id not in kept]
        return {"messages": [*stale, reply]}

    graph = StateGraph(CoachState, context_schema=CoachContext)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_graph.py -v`
Expected: 7 passed.

- [ ] **Step 8: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
Expected: all clean.

```bash
git add backend
git commit -m "feat: add LangGraph agent with query_history and bounded thread history"
```

---

### Task 6: Turn runner and `agent_runs` recording

**Files:**
- Create: `backend/src/coach/core/turn.py`
- Modify: `backend/tests/fakes.py` (add `ExplodingChatModel`)
- Test: `backend/tests/test_turn.py`

**Interfaces:**
- Consumes: `CoachGraph`, `build_graph` (Task 5), `CoachContext` (Task 5), `record_agent_run` (Task 4), `AgentRun`, `Trigger` (Task 2).
- Produces: `FALLBACK_REPLY: str`; `TurnResult(reply: str, run_id: UUID, error: str | None)`; `async run_turn(graph: CoachGraph, ctx: CoachContext, text: str, *, model_name: str, trigger: Trigger = "message") -> TurnResult`. Thread id is `str(ctx.athlete.id)`; the graph must have a checkpointer.

- [ ] **Step 1: Add the exploding model**

Append to `backend/tests/fakes.py` (merge imports):

```python
import anthropic
import httpx


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
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_turn.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.context import CoachContext
from coach.core.db import Pool
from coach.core.graph import CoachGraph, build_graph
from coach.core.models import Athlete
from coach.core.registry import Registry
from coach.core.turn import FALLBACK_REPLY, run_turn
from tests.factories import insert_session
from tests.fakes import ExplodingChatModel, FakeChatModel, scripted

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def usage(input_tokens: int, output_tokens: int) -> dict[str, int]:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens}


def ctx(athlete: Athlete, pool: Pool) -> CoachContext:
    return CoachContext(athlete=athlete, pool=pool, registry=Registry([]), now=lambda: NOW)


def graph_for(model: FakeChatModel, pool: Pool) -> CoachGraph:
    return build_graph(model, Registry([]), AsyncPostgresSaver(pool))


async def test_records_the_turn_with_tool_calls_and_tokens(pool: Pool, athlete: Athlete) -> None:
    async with pool.connection() as conn:
        await insert_session(conn, athlete, started_at=NOW - timedelta(days=2))
    model = scripted(
        AIMessage(content="", usage_metadata=usage(100, 10), tool_calls=[
            {"name": "query_history", "args": {"kind": "weekly_load"}, "id": "c1"}]),
        AIMessage(content="One session this week.", usage_metadata=usage(150, 20)),
    )

    result = await run_turn(graph_for(model, pool), ctx(athlete, pool), "this week?",
                            model_name="test-model")

    assert result.reply == "One session this week."
    assert result.error is None
    async with pool.connection() as conn:
        cur = await conn.execute("select * from agent_runs where id = %s", (result.run_id,))
        row = await cur.fetchone()
    assert row is not None
    assert row["trigger"] == "message"
    assert row["model"] == "test-model"
    assert (row["input_tokens"], row["output_tokens"]) == (250, 30)
    [tool_call] = row["tool_calls"]
    assert (tool_call["tool"], tool_call["module"], tool_call["status"]) == (
        "query_history", "core", "success")
    assert "2026-" in tool_call["result_summary"]


async def test_the_thread_remembers_the_previous_turn(pool: Pool, athlete: Athlete) -> None:
    model = scripted("Nice.", "You said you surfed.")
    graph = graph_for(model, pool)

    await run_turn(graph, ctx(athlete, pool), "I surfed this morning", model_name="m")
    await run_turn(graph, ctx(athlete, pool), "what did I say?", model_name="m")

    second_prompt = " ".join(m.text for m in model.seen[1])
    assert "I surfed this morning" in second_prompt


async def test_model_failure_returns_the_fallback_and_records_the_error(
    pool: Pool, athlete: Athlete
) -> None:
    graph = graph_for(ExplodingChatModel(messages=iter([])), pool)

    result = await run_turn(graph, ctx(athlete, pool), "hello", model_name="m")

    assert result.reply == FALLBACK_REPLY
    assert result.error is not None and result.error.startswith("APIConnectionError")
    async with pool.connection() as conn:
        cur = await conn.execute("select error, output from agent_runs where id = %s",
                                 (result.run_id,))
        row = await cur.fetchone()
    assert row is not None
    assert row["error"].startswith("APIConnectionError")
    assert row["output"] == FALLBACK_REPLY
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_turn.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.core.turn'`.

- [ ] **Step 4: Implement**

`backend/src/coach/core/turn.py`:

```python
"""One agent turn: run the graph on the athlete's thread and record it in agent_runs."""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import anthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from coach.core.context import CoachContext
from coach.core.graph import CoachGraph
from coach.core.models import AgentRun, Trigger
from coach.core.registry import Registry
from coach.core.repo import record_agent_run

FALLBACK_REPLY = (
    "Sorry, I couldn't reach the coach model just now. Your message arrived; try again in a minute."
)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """What to send back, and where the turn was recorded."""

    reply: str
    run_id: UUID
    error: str | None


async def run_turn(
    graph: CoachGraph,
    ctx: CoachContext,
    text: str,
    *,
    model_name: str,
    trigger: Trigger = "message",
) -> TurnResult:
    """Run one turn on the athlete's single thread; never raises for model API failures."""
    config: RunnableConfig = {"configurable": {"thread_id": str(ctx.athlete.id)}}
    snapshot = await graph.aget_state(config)
    seen = {m.id for m in snapshot.values.get("messages", [])}
    started = time.perf_counter()
    new: list[BaseMessage] = []
    error: str | None = None
    try:
        out = await graph.ainvoke({"messages": [HumanMessage(content=text)]}, config, context=ctx)
        new = [m for m in out["messages"] if m.id not in seen]
        reply = _final_reply(new)
    except anthropic.APIError as err:
        error = f"{type(err).__name__}: {err}"
        reply = FALLBACK_REPLY
    ai_messages = [m for m in new if isinstance(m, AIMessage) and m.usage_metadata]
    run = AgentRun(
        athlete_id=ctx.athlete.id,
        trigger=trigger,
        input=text,
        output=reply,
        model=model_name,
        latency_ms=round((time.perf_counter() - started) * 1000),
        tool_calls=_tool_calls(new, ctx.registry),
        input_tokens=sum(m.usage_metadata["input_tokens"] for m in ai_messages if m.usage_metadata),
        output_tokens=sum(
            m.usage_metadata["output_tokens"] for m in ai_messages if m.usage_metadata
        ),
        error=error,
    )
    async with ctx.pool.connection() as conn:
        run_id = await record_agent_run(conn, run)
    return TurnResult(reply=reply, run_id=run_id, error=error)


def _final_reply(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.text.strip():
            return message.text.strip()
    return "Done."


def _tool_calls(messages: list[BaseMessage], registry: Registry) -> list[dict[str, Any]]:
    results = {m.tool_call_id: m for m in messages if isinstance(m, ToolMessage)}
    calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            result = results.get(call["id"] or "")
            calls.append({
                "tool": call["name"],
                "module": registry.tool_owner(call["name"]),
                "args": call["args"],
                "status": result.status if result else "missing",
                "result_summary": result.text[:500] if result else "",
            })
    return calls
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_turn.py -v`
Expected: 3 passed.

- [ ] **Step 6: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`

```bash
git add backend
git commit -m "feat: run agent turns on a checkpointed thread and record them in agent_runs"
```

---

### Task 7: Telegram client and update handler

**Files:**
- Create: `backend/src/coach/core/telegram.py`, `backend/src/coach/core/deps.py`, `backend/src/coach/core/handler.py`
- Modify: `backend/tests/fakes.py` (add `TelegramRecorder`, `make_deps`)
- Test: `backend/tests/test_telegram.py`

**Interfaces:**
- Consumes: `run_turn` (Task 6), `build_graph`, `CoachGraph` (Task 5), `get_chat_model` (Task 5), `claim_update`, `get_athlete_by_chat_id` (Task 4), `create_pool`, `Pool` (Task 2), `migrate_all` not used here, `default_registry` (Task 3), `Settings` (Task 1).
- Produces:
  - `coach.core.telegram`: `Chat`, `Message`, `Update` (pydantic), `TelegramError`, `TelegramClient(token: str, http: httpx.AsyncClient)` with `call`, `send_message`, `send_typing`, `get_updates(offset: int | None, *, timeout: int = 30)`, `set_webhook(url, secret)`, `delete_webhook()`; `split_message(text, limit=4096) -> list[str]`; `TELEGRAM_TEXT_LIMIT`.
  - `coach.core.deps`: `Deps(settings, pool, registry, graph, telegram)`; `build_deps(settings) -> AbstractAsyncContextManager[Deps]`.
  - `coach.core.handler`: `UNSUPPORTED_REPLY`; `async handle_update(deps: Deps, update: Update) -> None`.
  - Test helpers `TelegramRecorder` and `make_deps(pool, model, recorder, *, allowed) -> Deps`.

- [ ] **Step 1: Add the Telegram test doubles**

Append to `backend/tests/fakes.py` (merge imports):

```python
import json
from langgraph.checkpoint.memory import InMemorySaver

from coach.core.config import Settings
from coach.core.deps import Deps
from coach.core.graph import build_graph
from coach.core.registry import Registry
from coach.core.telegram import TelegramClient
from tests.conftest import TEST_DATABASE_URL

TEST_TOKEN = "TEST:TOKEN"
WEBHOOK_SECRET = "hook-secret"


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
    settings = Settings.model_validate({
        "database_url": TEST_DATABASE_URL,
        "telegram_bot_token": TEST_TOKEN,
        "telegram_webhook_secret": WEBHOOK_SECRET,
        "telegram_allowed_chat_ids": allowed,
        "anthropic_api_key": "sk-test",
        "agent_model": "test-model",
    })
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
```

(`Pool` comes from `coach.core.db`.)

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_telegram.py`:

```python
import httpx
import pytest

from coach.core.config import Settings
from coach.core.db import Pool
from coach.core.deps import build_deps
from coach.core.handler import UNSUPPORTED_REPLY, handle_update
from coach.core.models import Athlete
from coach.core.telegram import TelegramClient, TelegramError, Update, split_message
from tests.conftest import TEST_DATABASE_URL
from tests.factories import new_chat_id, new_update_id
from tests.fakes import TEST_TOKEN, TelegramRecorder, make_deps, scripted, text_update

pytestmark = pytest.mark.anyio


def test_split_message_keeps_every_chunk_under_the_limit() -> None:
    text = "x" * 10_000

    chunks = split_message(text)

    assert [len(c) for c in chunks] == [4096, 4096, 1808]
    assert "".join(chunks) == text


def test_split_message_prefers_line_breaks() -> None:
    text = "a" * 3000 + "\n" + "b" * 3000

    assert split_message(text) == ["a" * 3000, "b" * 3000]


async def test_api_errors_raise_without_leaking_the_token() -> None:
    recorder = TelegramRecorder(fail_on="sendMessage")

    with pytest.raises(TelegramError) as raised:
        await recorder.client().send_message(1, "hi")

    assert TEST_TOKEN not in str(raised.value)


async def test_get_updates_omits_a_missing_offset() -> None:
    recorder = TelegramRecorder()

    await recorder.client().get_updates(None)

    assert "offset" not in recorder.calls[0][1]


async def test_replies_to_an_allowlisted_athlete(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("Hey!"), recorder, allowed=[athlete.telegram_chat_id])

    update = Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))
    await handle_update(deps, update)

    assert recorder.methods() == ["sendChatAction", "sendMessage"]
    assert recorder.sent_texts() == ["Hey!"]


async def test_ignores_chats_outside_the_allowlist(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("never")
    deps = make_deps(pool, model, recorder, allowed=[])
    update_id = new_update_id()

    await handle_update(deps, Update.model_validate(text_update(update_id, athlete.telegram_chat_id)))

    assert recorder.calls == []
    assert model.seen == []
    async with pool.connection() as conn:
        cur = await conn.execute("select 1 from processed_updates where update_id = %s", (update_id,))
        assert await cur.fetchone() is None


async def test_handles_a_repeated_update_once(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("Once.", "Twice?")
    deps = make_deps(pool, model, recorder, allowed=[athlete.telegram_chat_id])
    update = Update.model_validate(text_update(new_update_id(), athlete.telegram_chat_id))

    await handle_update(deps, update)
    await handle_update(deps, update)

    assert recorder.sent_texts() == ["Once."]
    assert len(model.seen) == 1


async def test_text_less_messages_get_a_short_explanation(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    model = scripted("never")
    deps = make_deps(pool, model, recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(deps, Update.model_validate(
        text_update(new_update_id(), athlete.telegram_chat_id, text=None)))

    assert recorder.sent_texts() == [UNSUPPORTED_REPLY]
    assert model.seen == []


async def test_non_message_updates_are_ignored(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("never"), recorder, allowed=[athlete.telegram_chat_id])
    edited = {"update_id": new_update_id(), "edited_message": {
        "message_id": 1, "chat": {"id": athlete.telegram_chat_id}, "text": "edit"}}

    await handle_update(deps, Update.model_validate(edited))

    assert recorder.calls == []


async def test_allowlisted_chat_without_an_athlete_gets_nothing(pool: Pool) -> None:
    chat_id = new_chat_id()
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("never"), recorder, allowed=[chat_id])

    await handle_update(deps, Update.model_validate(text_update(new_update_id(), chat_id)))

    assert recorder.calls == []


async def test_long_replies_are_split(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("y" * 5000), recorder, allowed=[athlete.telegram_chat_id])

    await handle_update(deps, Update.model_validate(
        text_update(new_update_id(), athlete.telegram_chat_id)))

    assert [len(t) for t in recorder.sent_texts()] == [4096, 904]


async def test_build_deps_wires_the_real_stack_without_network_calls() -> None:
    settings = Settings.model_validate({
        "database_url": TEST_DATABASE_URL, "telegram_bot_token": TEST_TOKEN,
        "telegram_webhook_secret": "s", "anthropic_api_key": "sk-test",
    })

    async with build_deps(settings) as deps:
        assert deps.registry.modules == ()
        assert isinstance(deps.telegram, TelegramClient)
        assert deps.graph.checkpointer is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_telegram.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.core.deps'` (raised while importing `tests.fakes`).

- [ ] **Step 4: Implement the client**

`backend/src/coach/core/telegram.py`:

```python
"""A minimal Telegram Bot API client and the update shapes the handler needs."""

from typing import Any

import httpx
from pydantic import BaseModel

TELEGRAM_TEXT_LIMIT = 4096


class Chat(BaseModel):
    """The chat a message came from."""

    id: int


class Message(BaseModel):
    """A message; ``text`` is None for photos, voice notes and stickers."""

    message_id: int
    chat: Chat
    text: str | None = None


class Update(BaseModel):
    """An incoming update; ``message`` is None for every other update type."""

    update_id: int
    message: Message | None = None


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

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send text, split into several messages when it exceeds Telegram's limit."""
        for chunk in split_message(text):
            await self.call("sendMessage", {"chat_id": chat_id, "text": chunk})

    async def send_typing(self, chat_id: int) -> None:
        """Show "typing..." while the agent works."""
        await self.call("sendChatAction", {"chat_id": chat_id, "action": "typing"})

    async def get_updates(self, offset: int | None, *, timeout: int = 30) -> list[dict[str, Any]]:
        """Long-poll for new message updates."""
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return list(await self.call("getUpdates", payload))

    async def set_webhook(self, url: str, secret: str) -> None:
        """Point Telegram at the deployed webhook."""
        await self.call(
            "setWebhook", {"url": url, "secret_token": secret, "allowed_updates": ["message"]}
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
```

- [ ] **Step 5: Implement deps and the handler**

`backend/src/coach/core/deps.py`:

```python
"""Everything a request needs, built once per process."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from coach.core.config import Settings
from coach.core.db import Pool, create_pool
from coach.core.graph import CoachGraph, build_graph
from coach.core.llm import get_chat_model
from coach.core.registry import Registry, default_registry
from coach.core.telegram import TelegramClient


@dataclass(frozen=True, slots=True)
class Deps:
    """Process-wide dependencies shared by the webhook and long polling."""

    settings: Settings
    pool: Pool
    registry: Registry
    graph: CoachGraph
    telegram: TelegramClient


@asynccontextmanager
async def build_deps(settings: Settings) -> AsyncIterator[Deps]:
    """Open the pool and HTTP client, build the graph, close everything on exit."""
    pool = create_pool(settings.database_url.get_secret_value())
    await pool.open()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as http:
            registry = default_registry()
            graph = build_graph(
                get_chat_model(settings),
                registry,
                AsyncPostgresSaver(pool),
                history_messages=settings.history_messages,
            )
            telegram = TelegramClient(settings.telegram_bot_token.get_secret_value(), http)
            yield Deps(settings=settings, pool=pool, registry=registry, graph=graph,
                       telegram=telegram)
    finally:
        await pool.close()
```

`backend/src/coach/core/handler.py`:

```python
"""One Telegram update in, one reply out. Shared by the webhook and long polling."""

import logging

from coach.core.context import CoachContext
from coach.core.deps import Deps
from coach.core.repo import claim_update, get_athlete_by_chat_id
from coach.core.telegram import Update
from coach.core.turn import run_turn

logger = logging.getLogger(__name__)

UNSUPPORTED_REPLY = "I can only read text messages for now. Voice notes and photos are coming soon."


async def handle_update(deps: Deps, update: Update) -> None:
    """Allowlist, dedupe, run one agent turn and reply."""
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
        logger.warning("chat %s is allowlisted but has no athlete; run `coach add-athlete`", chat_id)
        return
    if not message.text:
        await deps.telegram.send_message(chat_id, UNSUPPORTED_REPLY)
        return
    await deps.telegram.send_typing(chat_id)
    ctx = CoachContext(athlete=athlete, pool=deps.pool, registry=deps.registry)
    result = await run_turn(deps.graph, ctx, message.text, model_name=deps.settings.agent_model)
    await deps.telegram.send_message(chat_id, result.reply)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_telegram.py -v`
Expected: 12 passed.

- [ ] **Step 7: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`

```bash
git add backend
git commit -m "feat: add Telegram client and allowlisted, deduplicated update handler"
```

---

### Task 8: FastAPI webhook

**Files:**
- Create: `backend/src/coach/main.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `Deps`, `build_deps` (Task 7), `handle_update`, `Update` (Task 7), `get_settings` (Task 1).
- Produces: `create_app(deps_factory: DepsFactory = _default_deps) -> FastAPI`; module-level `app` (the Vercel entrypoint `coach.main:app`); routes `GET /health`, `POST /telegram`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_api.py`:

```python
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from coach.core.db import Pool
from coach.core.deps import Deps
from coach.core.models import Athlete
from coach.main import create_app
from tests.factories import new_update_id
from tests.fakes import WEBHOOK_SECRET, TelegramRecorder, make_deps, scripted, text_update

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def serve(deps: Deps) -> AsyncIterator[httpx.AsyncClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Deps]:
        yield deps

    app = create_app(factory)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


def headers(secret: str = WEBHOOK_SECRET) -> dict[str, str]:
    return {"X-Telegram-Bot-Api-Secret-Token": secret}


async def test_health(pool: Pool) -> None:
    async with serve(make_deps(pool, scripted(), TelegramRecorder(), allowed=[])) as client:
        response = await client.get("/health")

    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("sent", [None, "wrong-secret"])
async def test_rejects_a_missing_or_wrong_secret(pool: Pool, sent: str | None) -> None:
    deps = make_deps(pool, scripted(), TelegramRecorder(), allowed=[])
    async with serve(deps) as client:
        response = await client.post("/telegram", json=text_update(new_update_id(), 1),
                                     headers=headers(sent) if sent else {})

    assert response.status_code == 401


async def test_rejects_a_malformed_update(pool: Pool) -> None:
    async with serve(make_deps(pool, scripted(), TelegramRecorder(), allowed=[])) as client:
        response = await client.post("/telegram", json={"nope": 1}, headers=headers())

    assert response.status_code == 422


async def test_replies_and_deduplicates_retried_deliveries(pool: Pool, athlete: Athlete) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    deps = make_deps(pool, scripted("Hi Jean.", "again?"), recorder,
                     allowed=[athlete.telegram_chat_id])
    update = text_update(new_update_id(), athlete.telegram_chat_id)

    async with serve(deps) as client:
        first = await client.post("/telegram", json=update, headers=headers())
        retry = await client.post("/telegram", json=update, headers=headers())

    assert (first.status_code, retry.status_code) == (200, 200)
    assert recorder.sent_texts() == ["Hi Jean."]


async def test_a_failing_update_still_returns_200_and_is_logged(
    pool: Pool, athlete: Athlete, caplog: pytest.LogCaptureFixture
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder(fail_on="sendMessage")
    deps = make_deps(pool, scripted("unsendable"), recorder, allowed=[athlete.telegram_chat_id])
    update_id = new_update_id()

    with caplog.at_level(logging.ERROR):
        async with serve(deps) as client:
            response = await client.post(
                "/telegram", json=text_update(update_id, athlete.telegram_chat_id),
                headers=headers())

    assert response.status_code == 200
    assert f"update {update_id} failed" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.main'`.

- [ ] **Step 3: Implement**

`backend/src/coach/main.py`:

```python
"""FastAPI entrypoint (Vercel loads ``coach.main:app``): the Telegram webhook and a health check."""

import hmac
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, status

from coach.core.config import get_settings
from coach.core.deps import Deps, build_deps
from coach.core.handler import handle_update
from coach.core.telegram import Update

logging.basicConfig(level=logging.INFO)
# httpx logs request URLs at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

type DepsFactory = Callable[[], AbstractAsyncContextManager[Deps]]


def _default_deps() -> AbstractAsyncContextManager[Deps]:
    return build_deps(get_settings())


def create_app(deps_factory: DepsFactory = _default_deps) -> FastAPI:
    """Build the app; tests pass their own ``deps_factory``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with deps_factory() as deps:
            app.state.deps = deps
            yield

    app = FastAPI(title="Hybrid Athlete Coach", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram")
    async def telegram_webhook(
        update: Update,
        request: Request,
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        deps: Deps = request.app.state.deps
        expected = deps.settings.telegram_webhook_secret.get_secret_value()
        if x_telegram_bot_api_secret_token is None or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, expected
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")
        try:
            await handle_update(deps, update)
        except Exception:  # noqa: BLE001 - answer 200 so Telegram never retries a poisoned update
            logger.exception("update %s failed", update.update_id)
        return {"ok": True}

    return app


app = create_app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_api.py -v`
Expected: 6 passed.

- [ ] **Step 5: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`

```bash
git add backend
git commit -m "feat: add FastAPI webhook with secret-token check"
```

---

### Task 9: CLI and local long polling

**Files:**
- Create: `backend/src/coach/core/polling.py`, `backend/src/coach/cli.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `Deps`, `build_deps` (Task 7), `handle_update`, `Update` (Task 7), `migrate_all` (Task 2), `default_registry` (Task 3), `create_athlete`, `get_athlete_by_chat_id` (Task 4), `create_pool` (Task 2), `get_settings`, `DEFAULT_TIMEZONE` (Task 1).
- Produces: `poll_once(deps, offset: int | None, *, timeout: int = 30) -> int | None`; `run_polling(deps) -> None`; `add_athlete(pool, *, name, chat_id, timezone) -> tuple[Athlete, bool]`; `main(argv: Sequence[str] | None = None) -> None` with subcommands `migrate`, `add-athlete`, `set-webhook`, `poll`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_cli.py`:

```python
from zoneinfo import ZoneInfoNotFoundError

import pytest

from coach.cli import add_athlete, main
from coach.core.db import Pool
from coach.core.models import Athlete
from coach.core.polling import poll_once
from tests.factories import new_chat_id, new_update_id
from tests.fakes import TelegramRecorder, make_deps, scripted, text_update

pytestmark = pytest.mark.anyio


async def test_add_athlete_is_idempotent(pool: Pool) -> None:
    chat_id = new_chat_id()

    first, created = await add_athlete(pool, name="Jean", chat_id=chat_id,
                                       timezone="Australia/Brisbane")
    again, created_again = await add_athlete(pool, name="Other", chat_id=chat_id,
                                             timezone="Australia/Brisbane")

    assert (created, created_again) == (True, False)
    assert again == first


async def test_add_athlete_rejects_an_unknown_time_zone(pool: Pool) -> None:
    with pytest.raises(ZoneInfoNotFoundError):
        await add_athlete(pool, name="Jean", chat_id=new_chat_id(), timezone="Mars/Olympus")


async def test_poll_once_handles_the_batch_and_advances_the_offset(
    pool: Pool, athlete: Athlete
) -> None:
    assert athlete.telegram_chat_id is not None
    recorder = TelegramRecorder()
    first, second = new_update_id(), new_update_id()
    recorder.update_batches.append([
        text_update(first, athlete.telegram_chat_id, "hello"),
        {"update_id": second, "edited_message": {"message_id": 2,
                                                 "chat": {"id": athlete.telegram_chat_id}}},
    ])
    deps = make_deps(pool, scripted("Hi!"), recorder, allowed=[athlete.telegram_chat_id])

    offset = await poll_once(deps, None, timeout=0)

    assert offset == second + 1
    assert recorder.sent_texts() == ["Hi!"]


async def test_poll_once_keeps_the_offset_when_nothing_arrives(pool: Pool) -> None:
    deps = make_deps(pool, scripted(), TelegramRecorder(), allowed=[])

    assert await poll_once(deps, 42, timeout=0) == 42


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'coach.cli'`.

- [ ] **Step 3: Implement polling**

`backend/src/coach/core/polling.py`:

```python
"""Local development: receive updates by long polling instead of the webhook."""

import asyncio
import logging

import httpx

from coach.core.deps import Deps
from coach.core.handler import handle_update
from coach.core.telegram import Update

logger = logging.getLogger(__name__)


async def poll_once(deps: Deps, offset: int | None, *, timeout: int = 30) -> int | None:
    """Fetch one batch, handle each update, and return the next offset."""
    for raw in await deps.telegram.get_updates(offset, timeout=timeout):
        update = Update.model_validate(raw)
        offset = update.update_id + 1
        try:
            await handle_update(deps, update)
        except Exception:  # noqa: BLE001 - one bad update must not stop local polling
            logger.exception("update %s failed", update.update_id)
    return offset


async def run_polling(deps: Deps) -> None:
    """Delete the webhook, then poll forever. Use a separate dev bot token for this."""
    await deps.telegram.delete_webhook()
    offset: int | None = None
    while True:
        try:
            offset = await poll_once(deps, offset)
        except httpx.HTTPError as err:
            logger.warning("polling failed (%s); retrying in 5s", type(err).__name__)
            await asyncio.sleep(5)
```

- [ ] **Step 4: Implement the CLI**

`backend/src/coach/cli.py`:

```python
"""Command line: ``coach migrate | add-athlete | set-webhook | poll``."""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from coach.core.config import DEFAULT_TIMEZONE, Settings, get_settings
from coach.core.db import Pool, create_pool
from coach.core.deps import build_deps
from coach.core.migrations import migrate_all
from coach.core.models import Athlete
from coach.core.polling import run_polling
from coach.core.registry import default_registry
from coach.core.repo import create_athlete, get_athlete_by_chat_id


async def add_athlete(pool: Pool, *, name: str, chat_id: int, timezone: str) -> tuple[Athlete, bool]:
    """Create the athlete for a chat, or return the existing one. True when created."""
    ZoneInfo(timezone)  # raises ZoneInfoNotFoundError for a typo before anything is written
    async with pool.connection() as conn:
        existing = await get_athlete_by_chat_id(conn, chat_id)
        if existing:
            return existing, False
        created = await create_athlete(conn, name=name, telegram_chat_id=chat_id, timezone=timezone)
        return created, True


async def _with_pool(settings: Settings, args: argparse.Namespace) -> None:
    pool = create_pool(settings.database_url.get_secret_value())
    await pool.open()
    try:
        if args.command == "migrate":
            applied = await migrate_all(pool, default_registry().migration_dirs())
            print(f"Applied {len(applied)} migration(s): {', '.join(applied) or 'none'}")
        else:
            athlete, created = await add_athlete(
                pool, name=args.name, chat_id=args.chat_id, timezone=args.timezone
            )
            print(f"{'Created' if created else 'Already exists'}: {athlete.name} ({athlete.id})")
    finally:
        await pool.close()


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.command in {"migrate", "add-athlete"}:
        await _with_pool(settings, args)
        return
    async with build_deps(settings) as deps:
        if args.command == "set-webhook":
            await deps.telegram.set_webhook(
                args.url, settings.telegram_webhook_secret.get_secret_value()
            )
            print(f"Webhook set to {args.url}")
        else:
            print("Long polling. Press Ctrl+C to stop.")
            await run_polling(deps)


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for the ``coach`` script."""
    parser = argparse.ArgumentParser(prog="coach")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply core and module migrations")
    add = commands.add_parser("add-athlete", help="link a Telegram chat to a new athlete")
    add.add_argument("--name", required=True)
    add.add_argument("--chat-id", type=int, required=True)
    add.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    hook = commands.add_parser("set-webhook", help="point Telegram at the deployed webhook")
    hook.add_argument("--url", required=True, help="https://<backend domain>/telegram")
    commands.add_parser("poll", help="long polling for local development")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(_run(args))
```

Ruff may flag `print` (T201) only if that rule is selected; it is not in this config, so `print` is fine for CLI output.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_cli.py -v`
Expected: 5 passed.

- [ ] **Step 6: Smoke-test the CLI against the local database**

Run: `cd backend && COACH_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres COACH_TELEGRAM_BOT_TOKEN=x COACH_TELEGRAM_WEBHOOK_SECRET=x COACH_ANTHROPIC_API_KEY=x uv run coach migrate`
Expected: `Applied 0 migration(s): none` (tests already applied them).

- [ ] **Step 7: Quality gate and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov=coach --cov-report=term-missing`
Expected: all pass; coverage reported.

```bash
git add backend
git commit -m "feat: add coach CLI with migrate, add-athlete, set-webhook and local polling"
```

---

### Task 10: Continuous integration

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the quality gate commands from every earlier task; `supabase/config.toml` (Task 2).
- Produces: a `CI` workflow that runs on pushes to `main` and on pull requests.

- [ ] **Step 1: Write the workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - uses: supabase/setup-cli@v1
        with:
          version: latest
      - name: Start local Postgres
        run: supabase db start
      - name: Install
        working-directory: backend
        run: uv sync --locked
      - name: Lint
        working-directory: backend
        run: uv run ruff check . && uv run ruff format --check .
      - name: Types
        working-directory: backend
        run: uv run mypy
      - name: Tests
        working-directory: backend
        run: uv run pytest --cov=coach --cov-report=term-missing
```

- [ ] **Step 2: Validate locally**

Run: `cd backend && uv run pre-commit run --all-files`
Expected: every hook passes (check-yaml validates the workflow).

- [ ] **Step 3: Commit**

```bash
git add .github
git commit -m "ci: run lint, types and tests against local Supabase Postgres"
```

- [ ] **Step 4: Push and watch CI (ask first)**

Pushing publishes the repository's history.
Ask the user before running `git push origin main`.
After pushing: `gh run watch --exit-status` and fix anything red before continuing.

---

### Task 11: Provision accounts, deploy and verify end to end

The user currently has only GitHub.
Everything here needs a human at a browser, so generate a wizard rather than doing it by hand in chat.

**Files:**
- Create: `scripts/provision.sh` (generated with the `wizard` skill)

**Interfaces:**
- Consumes: `coach migrate`, `coach add-athlete`, `coach set-webhook`, `coach poll` (Task 9); `backend/vercel.json`, `[tool.vercel] entrypoint` (Task 1).
- Produces: a live Supabase project, two Telegram bots (dev for polling, prod for the webhook), an Anthropic key with a monthly limit, a Vercel project for `backend/` in `syd1`, and a verified round trip.

- [ ] **Step 1: Generate the wizard**

Invoke the `wizard` skill to write `scripts/provision.sh`.
It must walk the user through, in order, saving values into `backend/.env` (never echoing secrets):

1. Supabase: create a project in region `ap-southeast-2` (Sydney); copy the **transaction pooler** connection string (port 6543) into `COACH_DATABASE_URL`.
2. Telegram: in @BotFather create two bots, `<name>_dev_bot` and `<name>_bot`; store the dev token in `backend/.env` and keep the prod token for Vercel; message the dev bot, then read the chat id from `https://api.telegram.org/bot<dev token>/getUpdates`; set `COACH_TELEGRAM_ALLOWED_CHAT_IDS=[<chat id>]`.
3. Webhook secret: `openssl rand -hex 32` into `COACH_TELEGRAM_WEBHOOK_SECRET`.
4. Anthropic: create an API key in the console, set a monthly spend limit of $10, store it in `COACH_ANTHROPIC_API_KEY`.
5. Database: `cd backend && uv run coach migrate && uv run coach add-athlete --name "<name>" --chat-id <chat id>`.
6. Local check: `uv run coach poll`, send "how much did I train this week?" to the dev bot, expect a reply saying there is no training logged yet; Ctrl+C.
7. Vercel: `vercel login`; `cd backend && vercel link` (new project, root directory `backend`); add every `COACH_` variable for Production with `vercel env add` using the **prod** bot token; `vercel deploy --prod`.
8. Webhook: with the prod token in the environment, `uv run coach set-webhook --url https://<production domain>/telegram`.

- [ ] **Step 2: Run it**

Ask the user to run `! bash scripts/provision.sh` in this session so its output lands in the conversation.

- [ ] **Step 3: Verify end to end**

1. `curl -s https://<production domain>/health` returns `{"status":"ok"}`.
2. The user sends "how much did I train this week?" to the prod bot and gets a reply within a few seconds.
3. `psql "$COACH_DATABASE_URL" -c "select trigger, model, input_tokens, output_tokens, latency_ms, error from agent_runs order by created_at desc limit 1"` shows the turn with `error` empty.
4. A message from any other Telegram account gets no reply.

If Vercel cannot import `coach.main:app` (build log shows an entrypoint or import error), add `backend/main.py` containing `from coach.main import app` and `__all__ = ["app"]`, remove `[tool.vercel] entrypoint`, redeploy, and note it in the commit message.

- [ ] **Step 4: Commit**

```bash
git add scripts backend
git commit -m "chore: add provisioning wizard for Supabase, Telegram, Anthropic and Vercel"
```
