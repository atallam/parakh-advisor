-- advisory.v1: tables Parakh writes and WealthLens reads. Run once in the Supabase SQL editor.
-- Rules: append-only (no updates, no deletes from the app), every row carries user_id, row level
-- security on. The React tab reads with the user's own login; the Parakh writer uses a key that can
-- insert into these tables only. Idempotent: safe to run again.

create table if not exists advisory_runs (
  id uuid primary key, user_id uuid not null, kind text not null,
  started_at timestamptz not null, finished_at timestamptz not null,
  model text, policy_version int not null, status text not null, contract text not null
);
create table if not exists advisory_theses (
  id uuid primary key, user_id uuid not null, instrument_id text not null, symbol text,
  version int not null, created_at timestamptz not null, stance text not null,
  confidence text not null, valuation_stance text, change_decision text not null,
  body jsonb not null, inputs_digest text not null,
  unique (user_id, instrument_id, version)
);
create table if not exists advisory_drivers (
  thesis_id uuid not null, user_id uuid not null, driver_id text not null, kind text not null,
  indicator text, status text not null, value double precision, evidence_ids text[] not null default '{}',
  primary key (thesis_id, driver_id)
);
create table if not exists advisory_actions (
  id uuid primary key, user_id uuid not null, instrument_id text not null, symbol text,
  run_id uuid not null, action text not null, reason_codes text[] not null default '{}',
  weight_pct double precision, band_low double precision, band_high double precision,
  what_would_change text not null default '', created_at timestamptz not null
);
create table if not exists advisory_alerts (
  id uuid primary key, user_id uuid not null, instrument_id text not null, run_id uuid not null,
  severity text not null, kind text not null, title text not null, prev_value text, new_value text,
  detail text not null default '', evidence_ids text[] not null default '{}',
  created_at timestamptz not null, acknowledged_at timestamptz
);
create table if not exists advisory_evidence (
  id text primary key, user_id uuid not null, instrument_id text, source text, url text,
  retrieved_at timestamptz, content_hash text, excerpt text, quality_tier text
);
create table if not exists advisory_portfolio (
  run_id uuid primary key, user_id uuid not null, snapshot jsonb not null
);

create index if not exists advisory_actions_user_inst on advisory_actions (user_id, instrument_id, created_at desc);
create index if not exists advisory_theses_user_inst on advisory_theses (user_id, instrument_id, version desc);
create index if not exists advisory_alerts_user on advisory_alerts (user_id, created_at desc);

do $$
declare t text;
begin
  foreach t in array array['advisory_runs','advisory_theses','advisory_drivers','advisory_actions',
                           'advisory_alerts','advisory_evidence','advisory_portfolio']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists %I on %I', t || '_select_own', t);
    execute format('create policy %I on %I for select using (auth.uid() = user_id)', t || '_select_own', t);
  end loop;
  -- the user may acknowledge their own alerts, nothing else
  drop policy if exists advisory_alerts_ack_own on advisory_alerts;
  create policy advisory_alerts_ack_own on advisory_alerts for update
    using (auth.uid() = user_id) with check (auth.uid() = user_id);
end $$;

-- Writer role: insert only. Create a key for this role (or use a Postgres role behind an edge function)
-- and put it in .env as SUPABASE_KEY. Do NOT use the WealthLens service key.
-- (Supabase service-role keys bypass RLS; if you must use one, keep it out of git and rotate it.)

-- Current state = latest rows. Only runs that completed are visible.
create or replace view advisory_current_theses as
  select distinct on (user_id, instrument_id) * from advisory_theses
  order by user_id, instrument_id, version desc;
create or replace view advisory_current_actions as
  select distinct on (a.user_id, a.instrument_id) a.*
  from advisory_actions a join advisory_runs r on r.id = a.run_id and r.status = 'complete'
  order by a.user_id, a.instrument_id, r.finished_at desc;
alter view advisory_current_theses set (security_invoker = true);
alter view advisory_current_actions set (security_invoker = true);
