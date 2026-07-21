-- ============================================================================
--  Vane — enable Row-Level Security on all public tables
-- ============================================================================
--  Defense in depth. The backend uses the *service_role* key, which bypasses
--  RLS by design, so existing app behavior is unchanged. RLS only matters if
--  the *anon* key is ever exposed (in a misconfigured deploy, a leaked .env,
--  a future Supabase JS client in the browser). Without RLS, an exposed anon
--  key would let anyone read/insert/delete any row. With these policies,
--  anon can only SELECT canonical scenarios and public runs — never write,
--  never read conversations.
--
--  Idempotent. Safe to re-run.
-- ============================================================================

-- ── runs ───────────────────────────────────────────────────────────────────
alter table public.runs enable row level security;

drop policy if exists "anon can read public runs" on public.runs;
create policy "anon can read public runs"
  on public.runs
  for select
  to anon
  using (is_public = true);

-- No insert/update/delete policy for anon → all writes blocked unless caller
-- is service_role (which bypasses RLS).

-- ── conversations ─────────────────────────────────────────────────────────
alter table public.conversations enable row level security;

-- No policies at all for anon → conversations are fully invisible to the
-- anon key. Only the backend (service_role) can read/write them. Chat
-- transcripts can contain user PII and scenario state we don't want public.

-- ── scenario_library ──────────────────────────────────────────────────────
alter table public.scenario_library enable row level security;

drop policy if exists "anon can read canonical scenarios" on public.scenario_library;
create policy "anon can read canonical scenarios"
  on public.scenario_library
  for select
  to anon
  using (is_canonical = true);

-- ── verification ──────────────────────────────────────────────────────────
-- After applying, confirm with:
--   select schemaname, tablename, rowsecurity
--     from pg_tables where schemaname = 'public';
-- All three rows should show rowsecurity = true.
