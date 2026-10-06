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
