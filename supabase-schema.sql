-- Run once in a dedicated Supabase project. Only the Render server uses the
-- project's secret key. Browser users never connect to this table directly.
create table if not exists public.baze_lab_api_keys (
  slot text primary key check (slot in ('user', 'friend', 'member3', 'member4')),
  payload text not null,
  models jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.baze_lab_api_keys enable row level security;
revoke all on public.baze_lab_api_keys from public, anon, authenticated;
grant select, insert, update, delete on public.baze_lab_api_keys to service_role;

-- The active project pointer and every project file survive Render restarts.
-- Keep earlier project files by their unique project_id when a new run starts.
create table if not exists public.baze_lab_research_state (
  id text primary key check (id = 'active'),
  snapshot jsonb not null,
  updated_at timestamptz not null default now()
);
create table if not exists public.baze_lab_research_files (
  project_id text not null,
  path text not null,
  data text not null,
  sha256 text not null,
  updated_at timestamptz not null default now(),
  primary key (project_id, path)
);
alter table public.baze_lab_research_state enable row level security;
alter table public.baze_lab_research_files enable row level security;
revoke all on public.baze_lab_research_state, public.baze_lab_research_files from public, anon, authenticated;
grant select, insert, update, delete on public.baze_lab_research_state, public.baze_lab_research_files to service_role;

-- A database-only scheduler counter authorizes hourly work. A public health
-- request cannot increment it, so it cannot trigger extra model spending.
create table if not exists public.baze_lab_scheduler (
  id text primary key check (id = 'active'),
  tick bigint not null default 0,
  scheduled_at timestamptz
);
insert into public.baze_lab_scheduler (id, tick) values ('active', 0)
on conflict (id) do nothing;
alter table public.baze_lab_scheduler enable row level security;
revoke all on public.baze_lab_scheduler from public, anon, authenticated;
grant select on public.baze_lab_scheduler to service_role;
