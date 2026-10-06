# Hybrid Athlete Coach — Project Plan

Oct 6, 2026 · @Jean L

## Overview

Build a chat-based agent that logs and plans BJJ, surf and gym training in one place, and reasons across all three. Ship it open source, document it as a 7-part build-in-public series, and use it as the centrepiece portfolio project for AI engineering roles.

**The hook: a coach for hybrid athletes.** Generic fitness apps track one sport. This agent connects them:

- Rolled hard Monday, surfed 3 hours Tuesday, leg day Wednesday? It suggests moving or lightening leg day.
- Shoulders cooked from paddling? It swaps overhead pressing in this week's gym session.
- Good swell forecast Thursday? It moves the gym session so you're fresh for it.
- Stuck in half guard three sessions running? It flags the pattern and suggests what to drill.

**Goals**

1. Exercise core agentic skills end to end: tool use, memory, multimodal input, scheduled agents and evals.
2. Produce a live demo, a public repo and a post series people actually engage with.
3. Build it as a core plus pluggable discipline modules: phase 1 ships surf and gym, phase 2 adds BJJ as one new module without touching the core.

**Constraint: near-zero spend.** Every component runs on a free tier during development.
Model calls on real data, live eval runs and the demo use paid Claude models under a hard cap of $5 to $10 a month.
The public demo is a recorded video plus a public dashboard on a synthetic athlete, not a hosted bot.

**Priorities.** It is a coach used every day, published open source as a portfolio piece.
When goals conflict, the portfolio wins and daily use is the honesty check: every real session gets logged from week 1, even into a half-built bot.

## Features

Every discipline gets the same four capabilities: log, see, plan, and proactive messages. Phase 1 ships surf and gym; BJJ follows in phase 2 as its own module. Voice is the main input because you log straight after training, often with wet or taped hands.

| Capability | BJJ (phase 2) | Surf | Gym |
| --- | --- | --- | --- |
| Log (voice or text) | "Drilled knee cut, subbed twice, got passed from half" → techniques, rounds, subs, problem positions | "Burleigh, 2 hours, 3–4 ft, caught 12, struggled on backhand" → spot, duration, conditions, waves, notes | Tick off the next pending program session, with RPE and any swaps |
| See (photo) | Class whiteboard → techniques taught that day | Lineup photo → rough read on size and conditions | — |
| Plan | What to drill next, based on recurring problem positions | Where and when to surf, from forecast and tide tools | Adapts the current phase to fatigue and the surf forecast |
| Proactive | Weekly review as a voice note | Early-morning alert when a favourite break looks good | Morning message with the next planned session, ending in a one-tap readiness check |

**Out of scope for v1:** video analysis of rolls, social features, a hosted public bot (the demo is a recorded video), multiple users (v1 is single-user with a Telegram chat-id allowlist), and generating new program blocks (phase 3).

## Architecture

&#91;embedded content: architecture · chat and schedule in, one agent loop, Supabase out\]

Telegram messages arrive through a webhook and scheduled jobs arrive through a 15-minute tick; both enter the same agent loop, and replies go back out through Telegram.
Facts land in Postgres, fuzzy notes in pgvector, and the dashboard reads both live.

| Component | Choice | Cost |
| --- | --- | --- |
| Chat channel | Telegram Bot API: webhook in production (secret-token header, chat-id allowlist), long polling in local dev only, both through the same update handler | Free |
| Backend | Python, FastAPI, deployed as its own Vercel project (`backend/`, region `syd1`) | Free (Hobby) |
| Agent | LangGraph; `agent_runs` is the trace record, LangSmith optional in dev | Free, open source |
| Model | Claude Haiku 4.5 for extraction and the agent loop; Claude Sonnet 5.5 as eval judge only; free tiers (Gemini, Groq) only for throwaway dev loops on synthetic data; all behind one interface | $5 to $10 a month cap |
| Embeddings | Voyage `voyage-4-lite` | Free (200M tokens) |
| Database | Supabase Postgres + pgvector, through the transaction pooler (prepared statements off for the LangGraph checkpointer) | Free tier |
| Speech | Groq Whisper API for transcription; edge-tts for voice replies (local faster-whisper and Piper do not fit a serverless bundle) | Free |
| Forecast and tides | Open-Meteo Marine API: swell, wind and `sea_level_height_msl` for tide, labelled as estimates | Free for non-commercial use |
| Scheduling | Supabase `pg_cron` + `pg_net` POST `/jobs/tick` every 15 minutes with a `CRON_SECRET` header; the module registry decides what is due | Free |
| Dashboard | New Next.js app in `dashboard/`, its own Vercel project | Free (Hobby) |
| Hosting | Vercel Hobby for both projects; functions run up to 300s, enough for a full voice turn | Free |

Check each provider's current free-tier limits before relying on them; they change often.
Vercel Hobby cron is limited to once a day with ±59 minutes of jitter, which is why scheduling lives in `pg_cron`.

## Modular design

The core knows nothing about surfing, gyms or BJJ. Each discipline is a module that registers its own tables, tools, prompt, jobs, evals and dashboard widgets, so adding BJJ means adding one folder and enabling it.

**The core owns** the athlete profile, the shared `sessions` and `readiness_checkins` tables, notes and RAG, `agent_runs`, the Telegram adapter, speech, the job tick, the LangGraph agent and the dashboard shell.
Every module writes to `sessions`, so the core can see total load across all disciplines.

**Modules never import each other.** Cross-domain reasoning comes from the model: each module contributes a short `context(athlete)` summary (for example "surf: 2 long sessions this week, good swell Thursday"), the core joins them in `load_context`, and the agent reasons across them.
This keeps "add BJJ with zero core changes" literally true.

**Each module owns:**

| Piece | Surf (phase 1) | Gym (phase 1) | BJJ (phase 2) |
| --- | --- | --- | --- |
| Tables | `surf_details`, `surf_spots` | `gym_details`, `exercises`, program tables, `program_proposals` | `bjj_details` |
| Tools | `log_surf_session`, `get_surf_forecast`, `surf_history` | `log_gym_session`, `get_program`, `propose_program_change`, `propose_exercise` | `log_bjj_session`, `bjj_patterns` |
| Prompt fragment | Spot knowledge, conditions vocabulary | Program phases and progression rules | Technique vocabulary |
| Context summary | Recent sessions, upcoming swell | Next session, sessions this week, pending proposals | Recent rounds, problem positions |
| Scheduled jobs | Swell alert | Morning session message with readiness check | Weekly drill focus |
| Eval set | Surf voice logs | Gym voice logs | BJJ voice logs |
| Dashboard widgets | Waves and spots | Program adherence | Problem positions |

Every module implements the same interface:

```python
class DisciplineModule(Protocol):
    name: str                                  # "surf", "gym", "bjj"
    migrations: Path                           # SQL for the module's own tables

    def tools(self) -> list[BaseTool]: ...     # LangChain tools bound to the agent
    def prompt(self, athlete: Athlete) -> str: ...   # system prompt fragment
    def context(self, athlete: Athlete) -> str: ...  # short state summary joined into load_context
    def jobs(self) -> list[ScheduledJob]: ...  # each says when it is due in the athlete's time zone
    def evals(self) -> list[Path]: ...         # public synthetic eval cases for this module

# core/registry.py
ENABLED: list[DisciplineModule] = [SurfModule(), GymModule()]  # phase 2: + BJJModule()
```

The LangGraph graph is built from the registry at startup: `load_context` (profile plus every module's `context()`) → `agent` (the model bound to core tools plus every enabled module's tools, with the prompt fragments joined) → `tools` → back to `agent` until it answers. Adding a module changes the tool list and the prompt, never the graph. If the tool list grows too large later, the same registry can generate a router plus one subgraph per module.

On each `/jobs/tick`, the core asks every module's jobs whether they are due in the athlete's time zone, and records each run in `job_runs` keyed on (job, local date) so a repeated tick never sends twice.

**Conversation memory.** There is one checkpointer thread per athlete, kept forever and trimmed to the last ~30 messages, with tool calls and their results trimmed together.
Long-term facts come from Postgres through `load_context`, not from chat history.
A summariser is added only if evals show lost context.

```
backend/
  core/            agent graph, registry, telegram webhook, job tick, speech, db, core tools
  modules/
    surf/          module.py, tools.py, prompt.md, migrations/, evals/
    gym/           ... plus exercises.yaml, programs/
    bjj/           phase 2
dashboard/         Next.js; widgets registered per module the same way
```

## Supabase schema

Facts live in relational tables and are queried with SQL. Only fuzzy text (technique notes, coach tips, reflections) gets embeddings in pgvector. One shared `sessions` table holds what every discipline has in common, with a details table per discipline.

| Table | Owner | Holds |
| --- | --- | --- |
| `disciplines` | Core | One row per installed module; modules insert their own row |
| `athletes` | Core | Profile: stance, boards, time zone, Telegram chat id, Supabase Auth user id |
| `sessions` | Core | One row per training session, any discipline |
| `readiness_checkins` | Core | Daily soreness and energy by body area |
| `notes` | Core | Technique notes, coach tips, reflections, with embeddings |
| `agent_runs` | Core | Each turn's input, tool calls, output, tokens, latency |
| `processed_updates` | Core | Telegram `update_id`s already handled, so webhook retries are no-ops |
| `job_runs` | Core | One row per (job, local date), so a job never fires twice |
| `eval_cases`, `eval_runs` | Core | Private real eval cases; results of every eval run, read by the dashboard |
| `surf_spots`, `surf_details` | Surf module | Spots with coordinates; per-session conditions, waves, board |
| `exercises`, `program_*`, `gym_details` | Gym module | Exercise library; the program as an ordered sequence; proposals; what was actually done |
| `bjj_details` | BJJ module (phase 2) | Techniques, rounds, subs, problem positions |

**Core migration**

```sql
create extension if not exists vector;

-- a text key, not an enum: a new module adds a row instead of altering a type
create table disciplines (
  name text primary key,              -- 'surf', 'gym', 'bjj'
  label text not null,
  enabled boolean not null default true
);

create table athletes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid unique references auth.users(id),  -- magic-link login for the dashboard
  telegram_chat_id bigint unique,
  name text not null,
  timezone text not null default 'Australia/Brisbane',
  profile jsonb not null default '{}',  -- module-specific bits: stance, boards, belt...
  created_at timestamptz default now()
);

create table sessions (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  discipline text not null references disciplines(name),
  started_at timestamptz not null,
  duration_min int,
  rpe smallint check (rpe between 1 and 10),
  summary text,
  raw_input text,                      -- transcript or message, kept for evals
  input_type text check (input_type in ('voice', 'text', 'photo')),
  created_at timestamptz default now()
);
create index on sessions (athlete_id, started_at desc);

create table readiness_checkins (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  checked_on date not null,
  area text,                           -- shoulders, lower back, legs...
  level smallint check (level between 1 and 5),
  energy smallint check (energy between 1 and 5),
  note text
);

create table notes (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  session_id uuid references sessions(id) on delete set null,
  discipline text references disciplines(name),
  kind text check (kind in ('technique', 'coach_tip', 'spot', 'reflection')),
  content text not null,
  embedding vector(1024),              -- voyage-4-lite; confirm the dimension in week 4
  created_at timestamptz default now()
);
create index on notes using hnsw (embedding vector_cosine_ops);

create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid references athletes(id) on delete cascade,
  trigger text check (trigger in ('message', 'schedule')),
  input text,
  tool_calls jsonb default '[]',       -- [{tool, module, args, result_summary, ms}]
  output text,
  model text,
  input_tokens int,
  output_tokens int,
  latency_ms int,
  created_at timestamptz default now()
);

create table processed_updates (
  update_id bigint primary key,        -- Telegram retries a webhook; insert first, skip on conflict
  processed_at timestamptz default now()
);

create table job_runs (
  athlete_id uuid not null references athletes(id) on delete cascade,
  job text not null,                   -- 'gym.morning_session', 'surf.swell_alert'
  local_date date not null,            -- in the athlete's time zone
  ran_at timestamptz default now(),
  primary key (athlete_id, job, local_date)
);

create table eval_cases (              -- private real transcripts; the public synthetic set lives in the repo
  id uuid primary key default gen_random_uuid(),
  discipline text references disciplines(name),
  eval_set text not null check (eval_set in ('extraction', 'tool_choice', 'coaching')),
  input text not null,
  expected jsonb not null,
  created_at timestamptz default now()
);

create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  dataset text not null check (dataset in ('synthetic', 'private')),
  mode text not null check (mode in ('replay', 'live')),
  git_sha text,
  model text,
  metrics jsonb not null,              -- per-set, per-field scores, cost, p50/p95 latency
  created_at timestamptz default now()
);
```

**Surf module migration**

```sql
insert into disciplines (name, label) values ('surf', 'Surf');

create table surf_spots (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  name text not null,                  -- 'Burleigh', 'Snapper'
  latitude numeric not null,
  longitude numeric not null,
  favourite boolean default false,
  unique (athlete_id, name)
);

create table surf_details (
  session_id uuid primary key references sessions(id) on delete cascade,
  spot_id uuid references surf_spots(id),
  wave_height_min_ft numeric,
  wave_height_max_ft numeric,
  wind text,
  tide text,
  waves_caught int,
  board text
);
```

**Gym module migration.** The program is data, and it is an ordered sequence rather than a calendar: the next session is the first one not yet done, and dates are only suggestions the agent can move.
That fits weeks that vary (three surfs and two gym sessions one week, no surf the next).
The source of truth is two reviewed YAML files in `modules/gym/`: `exercises.yaml` (the library, starting from your exercise list) and `programs/*.yaml` (the first block, drafted together in week 2).
A seed command loads them.
When a block is finished, the agent says so and the next block is added as a new YAML file; generating blocks automatically is phase 3.

```sql
insert into disciplines (name, label) values ('gym', 'Gym');

-- the library: metadata lets swaps keep the movement pattern and avoid sore areas
create table exercises (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  name text not null,
  pattern text not null check (pattern in ('push', 'pull', 'hinge', 'squat', 'lunge', 'carry', 'core', 'conditioning')),
  equipment text[] default '{}',
  load_areas text[] default '{}',      -- shoulders, lower back, legs... matches readiness areas
  unique (athlete_id, name)
);

create table programs (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  name text not null,                  -- 'Surf + BJJ hybrid, block 1'
  source_file text,                    -- programs/block-1.yaml
  sessions_per_week_target int default 3,
  active boolean default true
);

create table program_sessions (
  id uuid primary key default gen_random_uuid(),
  program_id uuid not null references programs(id) on delete cascade,
  position int not null,               -- order in the sequence
  phase text not null,                 -- Foundation | Building | Power | Peak
  label text,                          -- 'Week 3, day 2' as written in the YAML
  status text not null default 'pending' check (status in ('pending', 'done', 'skipped')),
  planned_date date,                   -- a suggestion; moved through proposals
  unique (program_id, position)
);

create table program_exercises (
  id uuid primary key default gen_random_uuid(),
  program_session_id uuid not null references program_sessions(id) on delete cascade,
  position int not null,
  exercise_id uuid not null references exercises(id),
  sets int,
  reps text,                           -- '8-10', '30s'
  notes text
);

-- proposals instead of interrupt(): the chat thread never blocks while one waits
create table program_proposals (
  id uuid primary key default gen_random_uuid(),
  athlete_id uuid not null references athletes(id) on delete cascade,
  change_type text not null check (change_type in ('swap_exercise', 'reduce_volume', 'move_session', 'skip_session', 'add_exercise')),
  payload jsonb not null,
  reason text not null,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'declined', 'expired')),
  expires_at timestamptz not null,     -- the affected session's planned date
  telegram_message_id bigint,
  created_at timestamptz default now()
);

create table gym_details (
  session_id uuid primary key references sessions(id) on delete cascade,
  program_session_id uuid references program_sessions(id),
  exercises jsonb default '[]'         -- [{name, sets, reps, load_kg, swapped_from}]
);
```

**BJJ module migration (phase 2)**

```sql
insert into disciplines (name, label) values ('bjj', 'BJJ');

create table bjj_details (
  session_id uuid primary key references sessions(id) on delete cascade,
  session_type text check (session_type in ('class', 'drilling', 'open_mat', 'competition')),
  rounds int,
  subs_for int default 0,
  subs_against int default 0,
  techniques text[] default '{}',
  problem_positions text[] default '{}'
);
```

Enable row-level security on every table with policies keyed on `athlete_id`, matched to `athletes.user_id = auth.uid()`, so the dashboard can use the Supabase client directly behind a magic-link login for one user.
A seeded synthetic athlete backs the public `/demo` view, with a read-only policy for anonymous visitors that covers that athlete only.
The backend uses the service role key.
Module migrations only ever add tables and reference core ones, never alter them.
The `pg_cron` schedule that calls `/jobs/tick` is a core migration; modules never add cron entries.

## Agent tools

Core tools are always bound to the agent; module tools are added by each enabled module.
Reads run freely.
Anything that changes the program becomes a row in `program_proposals`, shown in Telegram with inline Yes/No buttons; the agent turn ends immediately, so the single chat thread never blocks.
LangGraph's `interrupt()` is kept for the one case where blocking is right: a log that cannot be saved until you answer a question.

| Tool | Owner | What it does | Confirmation |
| --- | --- | --- | --- |
| `query_history` | Core | Typed queries across all disciplines: recent sessions, weekly load, sessions per discipline | No |
| `log_readiness` | Core | Records soreness and energy by body area | No |
| `search_notes` | Core | Vector search over notes, optionally filtered by discipline | No |
| `save_note` | Core | Saves a note and its embedding, optionally linked to a session | No |
| `log_surf_session` | Surf | Turns a surf log into a `sessions` row plus `surf_details` | No (reply shows what was logged, with an Undo button); `interrupt()` if the spot is unknown |
| `get_surf_forecast` | Surf | Swell, wind and tide estimate for a saved spot over the next few days | No |
| `surf_history` | Surf | Waves and conditions by spot; best conditions for each spot | No |
| `log_gym_session` | Gym | Logs what was done against the next pending program session | No (Undo button); `interrupt()` if the session is ambiguous |
| `get_program` | Gym | Current phase, the next pending session, sessions done this week against the target | No |
| `propose_program_change` | Gym | Suggests a swap (same pattern, avoiding sore areas), volume cut, move or skip, with a reason | Yes, proposal + buttons |
| `propose_exercise` | Gym | Suggests adding an exercise to the library, with its metadata | Yes, proposal + buttons |
| `log_bjj_session` | BJJ (phase 2) | Techniques, rounds, subs, problem positions | No |
| `bjj_patterns` | BJJ (phase 2) | Recurring problem positions and technique frequency | No |

Tools are LangChain tools with Pydantic argument schemas. The athlete id comes from graph state through `InjectedState`, never from the model. Every log tool writes the core `sessions` row and its module's details row in one transaction:

```python
# modules/surf/tools.py
class SurfSessionInput(BaseModel):
    """Log one surf session. Fill only what the athlete said; never guess."""
    started_at: datetime = Field(description="Resolve 'this morning' etc. in the athlete's time zone")
    spot: str = Field(description="Spot name as the athlete said it, e.g. 'Burleigh'")
    duration_min: int | None = None
    rpe: int | None = Field(None, ge=1, le=10)
    wave_height_min_ft: float | None = None
    wave_height_max_ft: float | None = None
    wind: str | None = None
    tide: str | None = None
    waves_caught: int | None = None
    board: str | None = None
    summary: str | None = Field(None, description="One line in the athlete's words")

@tool("log_surf_session", args_schema=SurfSessionInput)
async def log_surf_session(state: Annotated[dict, InjectedState], **args) -> str:
    athlete_id = state["athlete_id"]
    spot_id = await resolve_spot(athlete_id, args["spot"])   # fuzzy match to saved spots
    if spot_id is None:
        # resolved before the transaction: interrupt() re-runs the tool on resume
        answer = interrupt({"type": "unknown_spot", "spot": args["spot"]})  # Telegram asks for a location pin or a pick from the list
        spot_id = await create_or_pick_spot(athlete_id, args["spot"], answer)
    async with db.transaction() as tx:
        session_id = await core.create_session(tx, athlete_id, discipline="surf", **core_fields(args))
        await tx.insert("surf_details", session_id=session_id, spot_id=spot_id, **surf_fields(args))
    return f"Logged surf at {args['spot']}."
```

```python
# modules/gym/tools.py
class ExerciseDone(BaseModel):
    name: str
    sets: int | None = None
    reps: str | None = None
    load_kg: float | None = None
    swapped_from: str | None = None

class GymSessionInput(BaseModel):
    """Log a gym session against the next pending program session. Fill only what was said."""
    started_at: datetime
    program_session_position: int | None = Field(None, description="Defaults to the first pending session")
    rpe: int | None = Field(None, ge=1, le=10)
    exercises: list[ExerciseDone] = []

class ProgramChangeInput(BaseModel):
    """Propose a program change. Applied only after the athlete taps Yes."""
    change_type: Literal["swap_exercise", "reduce_volume", "move_session", "skip_session"]
    program_session_position: int
    from_exercise: str | None = None
    to_exercise: str | None = Field(None, description="From the library: same pattern, not loading a sore area")
    new_date: date | None = None
    reason: str = Field(description="Cite the sessions, readiness or forecast behind it")

@tool("propose_program_change", args_schema=ProgramChangeInput)
async def propose_program_change(state: Annotated[dict, InjectedState], **args) -> str:
    proposal = await create_proposal(state["athlete_id"], **args)   # pending row; expires at the session's planned date
    await telegram.send_proposal(proposal)                          # inline Yes/No; callback data carries proposal.id
    return "Proposal sent; the athlete will confirm with a button."

# core/telegram.py: the button callback applies or declines the row in code, then notes the outcome in the thread
```

Use LangGraph's Postgres checkpointer on the same Supabase database (transaction pooler, prepared statements off) so a pending `interrupt()` survives across function invocations.
Open-Meteo takes coordinates, which is why `surf_spots` stores them; new spots get coordinates from a Telegram location pin.

## Dashboard

The dashboard is a new Next.js app in `dashboard/`, deployed as its own Vercel project, and is the project's main differentiator: most agent demos stop at a chat window.
It has two modes: a public `/demo` on a seeded synthetic athlete that anyone can click through, and your real data behind a Supabase magic-link login.
Five views, built in priority order; the memory panel and evals view are stretch goals for week 6.
Discipline-specific widgets live in each module and register with the dashboard the same way tools register with the agent:

1. **Training timeline.** All three disciplines on one calendar, colour-coded, with load per day. This is the cross-domain story in one picture.
2. **Agent trace viewer.** Each turn from `agent_runs`: the message, every tool call with arguments and timing, the reply, tokens and cost. Best screenshot material for posts.
3. **Memory panel.** What the agent knows: profile, recent sessions, notes. Editable, so you can correct it, and a good talking point on transparency.
4. **Insights.** Mat hours and waves per week, recurring BJJ problem positions, best surf conditions by spot, program adherence (gym sessions done per week against the program's target).
5. **Evals.** The latest eval run from `eval_runs`: extraction accuracy per field, cost and latency, compared with the previous run.

Use Supabase Realtime on `sessions` and `agent_runs` so the dashboard updates live while you message the bot. That makes the demo video land.

## Evals

Three small eval sets, started in week 2 and grown as you go.
Every set exists twice: real transcripts stay private in the `eval_cases` table (they contain health details, locations and your schedule), and the public repo ships a synthetic set that mirrors them.
Published numbers come from both.

How they run:

- **On every PR:** the synthetic set runs against recorded model responses (replay), so CI needs no API keys and costs nothing.
- **On manual dispatch and weekly:** live runs on both sets, using the Anthropic key and a read-only Supabase key held in a GitHub environment secret, so forked PRs never see them.
- **Judge:** Claude Sonnet 5.5 scores coaching answers; the system under test is Claude Haiku 4.5.
- **Results:** every run writes a row to `eval_runs`, which the dashboard reads.

| Eval set | Size to start | What it checks | Metric |
| --- | --- | --- | --- |
| Log extraction | One set per module, each with hand-labelled expected output: 15 surf and 15 gym voice logs in phase 1, 15 BJJ in phase 2 | `log_session` fills the right fields and invents nothing | Field-level precision and recall; hallucinated-field count |
| Tool choice | 20 questions ("how many waves this month?", "what should I drill?") | The agent calls the right tool with sensible arguments | % correct tool; % valid arguments |
| Coaching answers | 15 scenarios with known context (fatigue, forecast, next program session) | Advice cites real data and suggests a sensible change; swaps keep the pattern and spare sore areas | LLM-as-judge score against a rubric, spot-checked by hand |

Also track cost per turn, p50 and p95 latency, and transcription word error rate on the voice set. Record your own logs from day one; real messy voice notes are the most valuable data in the project.

## Build plan and post series

Three phases.
Phase 1 builds the core with gym and surf over 7 weeks, including a buffer week after week 5.
Phase 2 adds BJJ as a module in about 2 weeks, which itself proves the architecture.
Phase 3 adds program-block generation.
Posts are decoupled from the build schedule: one LinkedIn post a week about whatever is working and can be screen-recorded, not about what was planned for that week.

| Week | Build | Done when | Post |
| --- | --- | --- | --- |
| **Phase 1** | **Core + gym + surf** |  |  |
| 1 | `git init` + public GitHub repo (MIT), core migration, module registry, Telegram bot on long polling locally, LangGraph skeleton with `query_history`; at the end of the week, the backend Vercel project with the webhook, secret token and chat-id allowlist | A message reaches the deployed agent and a reply comes back | Why hybrid athletes have nowhere to log their training, and the plan |
| 2 | Gym module: exercise library YAML from your list, first program YAML drafted together, seed command, `get_program`, `log_gym_session` with Undo; gym eval set started (private real + public synthetic) | "What's my next session?" and a typed gym log both work; first eval score | Turning a training program into data an agent can reason about |
| 3 | Surf module: spots, `log_surf_session` with the unknown-spot `interrupt()` (location pin), `get_surf_forecast` with tide estimate, `surf_history`; surf eval set | A surf log lands with its spot; a new spot is created from a pin; forecasts come back for saved spots | Plugging live surf data into an agent |
| 4 | Voice in (Groq Whisper) and out (edge-tts); notes with Voyage embeddings and pgvector, `search_notes` and `save_note`; check Voyage's data policy before real notes go in | A voice note logs a session and gets a voice reply | SQL for facts, vectors for notes: when RAG is the wrong tool |
| 5 | Cross-domain coaching: module `context()` providers, `log_readiness`, `program_proposals` with Yes/No buttons, `propose_program_change`, `propose_exercise`; `pg_cron` tick to `/jobs/tick`; morning message with one-tap readiness; swell alert | The agent proposes moving a gym session around good swell and applies it when you tap Yes | One agent, two sports: cross-domain reasoning with a human in the loop |
| 6 | Buffer: catch up, fix what daily use exposed, grow the eval sets | Every real session of the past weeks is logged | Whatever is working (posts are decoupled) |
| 7 | Dashboard: timeline and trace viewer, public `/demo` on a synthetic athlete, magic-link login for real data; memory panel and evals view if time allows; CI replay evals plus one live run; demo video | Video recorded; repo public with README and numbers | What the evals caught, and what it all costs |
| **Phase 2** | **BJJ module** |  |  |
| 8 | `modules/bjj`: migration, `log_bjj_session`, `context()`, prompt fragment with technique vocabulary, BJJ eval set | BJJ logs work with zero changes to core code | Adding a whole sport in one folder: the payoff of a modular agent |
| 9 | `bjj_patterns`, weekly drill-focus job, problem-positions widget, cross-domain coaching across all three sports | The weekly review covers mat, surf and gym together | The finished coach, plus lessons learned |
| **Phase 3** | **Program generation** |  |  |
| Later | The agent drafts the next program block from the library and your history when a block ends, applied through a proposal, with its own evals | A generated block passes review and is used | Letting the agent write the program, safely |

Week 8's post is the strongest portfolio signal: a diff that adds a sport without touching the core shows design judgement better than any claim. Week 7's numbers come a close second.

## Risks and decisions

**Risks**

| Risk | Mitigation |
| --- | --- |
| Scope creep across three sports stalls the project | Modules plus phases: ship gym and surf end to end first; BJJ waits for phase 2; program generation waits for phase 3 |
| Week 1 is heavy (repo, schema, bot, agent and deploy) | Long polling locally first; deploy to Vercel only at the end of the week |
| Advice about soreness reads as medical advice | Frame changes as training adjustments, add a clear notice, and suggest seeing a professional for pain |
| Free forecast and tide data is patchy for specific breaks | Map each spot to its nearest forecast point; label forecasts and tides as estimates (Open-Meteo is reasonably accurate only near unobstructed coasts) |
| Voice transcription mangles BJJ terms ("kimura", "de la Riva") | Pass a vocabulary prompt to the transcription model; track word error rate in evals |
| Personal data leaks through a public repo or dashboard | Real eval cases stay in a private table; public synthetic set; `/demo` uses a synthetic athlete; RLS on `auth.uid()`; free tiers never see real data |
| Telegram retries a slow webhook and a session is logged twice | Insert `update_id` into `processed_updates` first and skip duplicates; send "typing…" before the agent turn |
| Model spend creeps past the cap | Haiku for the hot path, Sonnet only as judge; PR evals replay recorded responses; live runs only on dispatch and weekly |

**Decisions**

- [x] Agent framework: LangGraph, chosen for its explicit graph, human-in-the-loop interrupts and presence in job ads.
- [x] Chat channel: Telegram only; webhook in production, long polling in local dev.
- [x] Users: single user with a chat-id allowlist; `athlete_id` kept everywhere; Supabase Auth for one user, for the dashboard only.
- [x] Spend: free in development, $5 to $10 a month cap for real data, live evals and the demo.
- [x] Models: Claude Haiku 4.5 for extraction and the agent, Claude Sonnet 5.5 as eval judge, free tiers only on synthetic data; Voyage `voyage-4-lite` for embeddings.
- [x] Hosting: Python FastAPI backend and Next.js dashboard as two Vercel Hobby projects, functions in `syd1`.
- [x] Scheduling: Supabase `pg_cron` + `pg_net` 15-minute tick to `/jobs/tick`; the module registry decides what is due.
- [x] Modules: never import each other; cross-domain reasoning through `context(athlete)` summaries joined in `load_context`.
- [x] Gym program: lives in a separate app with nothing reusable, so it is rebuilt as an exercise library plus program YAML files in the repo, stored as an ordered sequence with suggested dates.
- [x] Memory: one checkpointer thread forever, trimmed to the last ~30 messages; no summariser until evals show a need.
- [x] Confirmations: program changes and new exercises go through `program_proposals` with Yes/No buttons and expiry; `interrupt()` only for deterministic log blockers (unknown spot, ambiguous session, unresolvable date), always resumed by the next message.
- [x] Readiness: a one-tap check at the end of the morning message.
- [x] Evals: private real set plus public synthetic set; replay on PRs, live on dispatch and weekly.
- [x] Public demo: a recorded video plus a public `/demo` dashboard on a synthetic athlete; no hosted bot.
- [x] Build order: the core plus gym and surf first (gym first), then BJJ as a separate module, then program generation.
