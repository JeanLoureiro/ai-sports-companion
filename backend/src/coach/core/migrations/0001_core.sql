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
