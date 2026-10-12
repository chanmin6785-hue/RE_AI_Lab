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
