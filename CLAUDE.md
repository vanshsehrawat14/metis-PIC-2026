# Vane — maintainer context

Working context for future Claude/Codex sessions in this repository. Start with
`README.md`, then `docs/ARCHITECTURE.md` and `docs/MATH.md`. This file is the short
orientation plus the rules that are not obvious from the code.

## What this is

Vane is a decision-support tool for venue and live-event operations: it compiles a
venue into a queueing network and reports wait, congestion, safety, revenue, and
recommended actions under a given event scenario.

It began as **Metis**, a finalist in the **2026 UNLV President's Innovation Challenge**,
and is now a solo, personal engineering project maintained under the name Vane. It is
not hosted anywhere and is not a commercial product. It is published to show the code
and the math. Contributors bring their own API keys and run or host it themselves.

## Two frontends, one repo

- **Web app** (`web/` + `api/`): the main product. React 18 + Vite over FastAPI,
  running the queueing-network engine (`simulation/network.py`, `temporal.py`,
  `metrics.py`, `demand.py`).
- **Streamlit demo** (`app.py`): an earlier, simpler view over a single-node model
  (`simulation/engine.py`, with `simulation/environment.py`, `optimization/`,
  `visualization/`). Runs with `streamlit run app.py`, no keys.

Keep these separate. The web app is where the real math lives; do not wire the
single-node demo into the network stack.

## Stack

- Frontend: React 18, Vite, Recharts, Framer Motion. Streamlit for the demo.
- Backend: Python, FastAPI, Pydantic, httpx.
- Simulation: NumPy / SciPy queueing models.
- Persistence (optional): Supabase Postgres.
- Chat (optional): Anthropic Messages API with backend tool use.

## Runtime and intelligence flow

`api.main` does not import `api.engine_bridge` at module load, so SciPy stays off the
import path until needed. A FastAPI lifespan builds `EngineBridge()` on a thread pool
after bind; `/ready` is dependency-free and answers immediately; engine routes call
`_ensure_bridge()` and return 503 until the bridge exists; `/health` reports
`venues_loaded: 0` until then. `/chat` shares the one process-wide `EngineBridge` via
`VaneIntelligence(bridge=...)`. Full request lifecycle is in `docs/ARCHITECTURE.md`.

Chat is a tool-use loop: Claude selects from `run_simulation`,
`run_temporal_simulation`, `run_what_if`, `run_stress_tests`, `get_venue_info`,
`get_engine_specs`; the backend runs them against the shared engine and trims results
before returning. The intelligence layer narrates engine output; it must not invent
numbers or sound like a generic chatbot. Lead with the controlling finding, use units,
rank recommendations, state assumptions.

## Math and metrics

The full, code-verified model is in `docs/MATH.md`: traffic equations
`(I - R^T) lambda = gamma`, Erlang-C in log space, Allen-Cunneen G/G/s correction,
Whitt QNA variance propagation, Beta arrival profiles with exponential egress, Fruin
LOS, HES (multiplicative), SRS (max of crush / flow / evacuation), and the
price-feasibility and revenue layers. When you change math behavior, update `docs/MATH.md`
in the same commit and add or adjust a test.

## Data and provenance

Every venue value, external overlay, and modeled input keeps `source`, `confidence`
(`high` / `medium` / `low`), and `notes` where estimated. Do not remove provenance or
confidence fields, and do not fabricate precision: if a gate count is estimated, it
stays labeled estimated. Live data sources report unavailable rather than returning
fabricated values. Sources are catalogued in `docs/data_sources.md`.

## Security (in code)

`api/security.py` provides per-IP rate limits (slowapi, in-memory), a 256 KB body cap,
security headers, and a bounded-LRU conversation cache. `runs`/`conversation_id` path
params are UUID-validated; `ChatRequest.message` is capped. `APP_ENV=production` hides
`/docs` and refuses a wildcard CORS origin. Supabase migration `0002_enable_rls.sql`
enables RLS as defense in depth (the backend uses `service_role` and bypasses it). The
rate limiter is single-process; swap to a Redis backend to scale out.

## Environment variables

All optional except that chat needs `ANTHROPIC_API_KEY`. See `.env.example` for the
full set (`ANTHROPIC_MODEL`, `TICKETMASTER_API_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `APP_ENV`, `CORS_ALLOWED_ORIGINS`, `TRUSTED_HOSTS`,
`SERVE_WEB_DIST`, `VITE_API_URL`). Never commit real keys; `.env` is git-ignored.

## Validation

```bash
python -m pytest tests/ -q
cd web && npm run build
python -m tests.validation.backtest
```

`tests/test_api.py` waits until `/health` reports venues loaded (the bridge starts
async). The intelligence tests expect `ANTHROPIC_API_KEY` to be unset (they check the
503 path).

## Engineering rules

- Keep changes scoped to the requested behavior; prefer existing patterns over new
  abstractions.
- Preserve provenance and confidence fields. Do not hide model limitations.
- Keep API behavior backward-compatible unless a breaking change is explicitly
  requested.
- Add tests when contracts, math behavior, persistence, or user-visible workflows change.
- Keep docs in lockstep: update `README.md`, `docs/ARCHITECTURE.md`, `docs/MATH.md`, and
  `.env.example` when behavior, boot sequence, env contracts, or the model change.
