-- ============================================================================
--  Vane — initial persistence schema
-- ============================================================================
--  Three tables:
--    runs              — persisted simulation runs (share-by-URL mechanism)
--    conversations     — persistent chat history (survives backend restart)
--    scenario_library  — curated canonical scenarios (Super Bowl LVIII, etc.)
--  One storage bucket:
--    exports           — PDF/CSV report downloads (wired later; bucket ready)
--
--  RLS is disabled here: share-by-URL is the only interaction model and the
--  URL itself is the capability. Migration 0002 enables RLS as defense in
--  depth (the backend uses the service_role key, which bypasses it).
-- ============================================================================

create extension if not exists "uuid-ossp";

-- ─── runs ───────────────────────────────────────────────────────────────────

create table if not exists public.runs (
    id                  uuid primary key default uuid_generate_v4(),
    venue_id            text not null,
    event_type          text not null,
    attendance          integer not null,
    event_date          timestamptz,
    service_rate_tier   text not null default 'operational',
    request_json        jsonb not null,
    response_json       jsonb not null,
    hes                 numeric,
    srs                 numeric,
    wait_mean           numeric,
    is_public           boolean not null default true,
    created_at          timestamptz not null default now()
);

create index if not exists runs_venue_created_idx
    on public.runs (venue_id, created_at desc);
create index if not exists runs_is_public_created_idx
    on public.runs (is_public, created_at desc);

comment on table public.runs is
  'Persisted simulation runs. id is the shareable URL token; request_json / response_json are full fidelity replays of the simulate call.';

-- ─── conversations ──────────────────────────────────────────────────────────

create table if not exists public.conversations (
    id          uuid primary key default uuid_generate_v4(),
    messages    jsonb not null default '[]'::jsonb,
    scenario    jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists conversations_updated_idx
    on public.conversations (updated_at desc);

comment on table public.conversations is
  'Persistent chat transcripts. messages is the full Anthropic conversation_history list.';

-- ─── scenario_library ──────────────────────────────────────────────────────

create table if not exists public.scenario_library (
    slug           text primary key,
    name           text not null,
    description    text,
    request_json   jsonb not null,
    is_canonical   boolean not null default true,
    display_order  integer not null default 100,
    created_at     timestamptz not null default now()
);

create index if not exists scenario_library_order_idx
    on public.scenario_library (display_order asc);

comment on table public.scenario_library is
  'Curated, canonical scenarios seeded by supabase/seed.py. Shown on the landing page as one-click operator presets.';

-- ─── storage bucket ────────────────────────────────────────────────────────

-- Storage buckets live in the storage.buckets table (managed by Supabase).
-- This is idempotent — safe to re-run.
insert into storage.buckets (id, name, public)
values ('exports', 'exports', true)
on conflict (id) do nothing;

-- ─── RLS (deferred to auth-pass) ───────────────────────────────────────────
--
-- When the auth pass lands, we'll uncomment the following block. Until then,
-- the service role used by the FastAPI backend bypasses RLS entirely and the
-- anon key is not exposed to the browser.
--
-- alter table public.runs              enable row level security;
-- alter table public.conversations     enable row level security;
-- alter table public.scenario_library  enable row level security;
--
-- create policy "anon can read public runs"
--   on public.runs for select using (is_public = true);
--
-- create policy "anon can read canonical scenarios"
--   on public.scenario_library for select using (is_canonical = true);
