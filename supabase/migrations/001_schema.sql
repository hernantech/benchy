-- Benchy schema — hardware test agent

-- Devices (RPi runners)
create table devices (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  status text not null default 'offline',
  capabilities jsonb not null default '{}',
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

-- Test runs
create table runs (
  id uuid primary key default gen_random_uuid(),
  device_id uuid references devices(id),
  status text not null default 'queued',
  goal text not null,
  trigger_type text not null default 'manual',
  trigger_ref text,
  agent_plan jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);
create index idx_runs_status on runs(status);
create index idx_runs_created on runs(created_at desc);

-- Run steps (commands issued to instruments)
create table run_steps (
  id bigserial primary key,
  run_id uuid not null references runs(id) on delete cascade,
  seq int not null,
  command_type text not null,
  args jsonb not null default '{}',
  status text not null default 'queued',
  result jsonb,
  artifact_url text,
  error text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now()
);
create index idx_run_steps_run on run_steps(run_id, seq);

-- Measurements (numeric results)
create table measurements (
  id bigserial primary key,
  run_id uuid not null references runs(id) on delete cascade,
  name text not null,
  value double precision not null,
  unit text not null,
  tags jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index idx_measurements_run on measurements(run_id);

-- Diagnoses (AI analysis)
create table diagnoses (
  id bigserial primary key,
  run_id uuid not null references runs(id) on delete cascade,
  model text not null,
  summary text not null,
  root_cause text,
  confidence double precision,
  suggested_fix jsonb,
  created_at timestamptz not null default now()
);
create index idx_diagnoses_run on diagnoses(run_id);

-- Enable realtime on tables the frontend subscribes to
alter publication supabase_realtime add table runs;
alter publication supabase_realtime add table run_steps;
alter publication supabase_realtime add table measurements;
alter publication supabase_realtime add table diagnoses;

-- RLS: allow anon read, service_role write
alter table devices enable row level security;
alter table runs enable row level security;
alter table run_steps enable row level security;
alter table measurements enable row level security;
alter table diagnoses enable row level security;

-- Read access for anon (frontend)
create policy "anon_read_devices" on devices for select using (true);
create policy "anon_read_runs" on runs for select using (true);
create policy "anon_read_steps" on run_steps for select using (true);
create policy "anon_read_measurements" on measurements for select using (true);
create policy "anon_read_diagnoses" on diagnoses for select using (true);

-- Write access for service_role only (backend/runner)
create policy "service_write_devices" on devices for all using (true) with check (true);
create policy "service_write_runs" on runs for all using (true) with check (true);
create policy "service_write_steps" on run_steps for all using (true) with check (true);
create policy "service_write_measurements" on measurements for all using (true) with check (true);
create policy "service_write_diagnoses" on diagnoses for all using (true) with check (true);

-- Storage bucket for waveform artifacts
insert into storage.buckets (id, name, public) values ('artifacts', 'artifacts', true);
