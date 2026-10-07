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
