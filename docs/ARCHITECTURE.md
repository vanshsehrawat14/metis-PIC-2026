# Vane — System Architecture

A technical reference for engineers reading the codebase for the first time. For the
math see [`MATH.md`](./MATH.md); for data provenance see
[`data_sources.md`](./data_sources.md); for validation see
[`BENCHMARKS_AND_VALIDATION.md`](./BENCHMARKS_AND_VALIDATION.md).

## 1. Topology

The repository holds two frontends over Python simulation code. Nothing is hosted;
everything runs locally, and every external dependency is optional.

```
  Web app (main product)                 Streamlit demo
  React 18 + Vite (web/)                  app.py
        |  /api                                |
        v                                       v
  FastAPI / uvicorn                      simulation/engine.py
    api/main.py                          (single-node Monte Carlo,
    api/engine_bridge.py                  optimization/ + visualization/)
    api/intelligence.py
    api/persistence.py
        |
        +--> simulation/  network + temporal + metrics + demand (queueing engine)
        +--> Supabase Postgres   (optional: runs, conversations, scenario_library)
        +--> Anthropic Claude    (optional: chat tool-use)
        +--> Open-Meteo / Nager.Date / Ticketmaster / NDOT + RTC  (live and cached data)
```

The web app is the main product and runs the queueing-network engine. The Streamlit
demo is an earlier, simpler view over a single-node model and does not use the network
stack.

**Backend boot.** `api.main` does not import `api.engine_bridge` at module load, so
SciPy and the simulation stack stay off the import path until needed. A FastAPI
lifespan context builds `EngineBridge()` on a thread-pool executor after the process
binds, so uvicorn can serve `GET /ready` immediately. Routes that need the engine call
`_ensure_bridge()` and return 503 until construction finishes. `/chat` reuses the same
shared `EngineBridge` instance as the REST routes.

Single-process FastAPI: no queue, no Redis, no worker pool. Every request is CPU-bound
Monte Carlo that finishes inside the HTTP timeout. Local benchmark ranges are roughly
0.4 to 1.0s for FAST temporal mode, 4.6 to 11.0s for DEEP temporal mode, and 1.3 to
2.8s for 1,000-trial snapshots. See [`BENCHMARKS_AND_VALIDATION.md`](./BENCHMARKS_AND_VALIDATION.md).

## 2. Request lifecycle

### POST /simulate (and variants)

```
Client -> FastAPI router -> api.models.SimulationRequest
  -> api.engine_bridge.EngineBridge.run_simulation()
     -> resolve venue profile + graph from data/venues/
     -> fetch live context (weather, holidays, events, traffic)
     -> simulation.network (Erlang-C log-space, Allen-Cunneen, Whitt QNA variance)
     -> simulation.metrics (Fruin LOS, HES, SRS, revenue, recommendations)
  -> SimulationResponse
  -> if req.save and Supabase configured: persistence.save_run(...) -> run_id
```

### POST /chat

```
Client -> FastAPI -> _ensure_bridge() (503 if engine still booting)
  -> api.intelligence.VaneIntelligence.chat()
  -> Anthropic messages.create(tools=[run_simulation, run_temporal_simulation,
       run_what_if, run_stress_tests, get_venue_info, get_engine_specs])
  -> tool-use loop: Claude selects tools, FastAPI executes them against the shared
     EngineBridge, results trimmed to top bottleneck nodes and returned
  -> final assistant text
  -> if Supabase configured: persistence.save_conversation(id, msgs)
```

A bounded-LRU cache of `VaneIntelligence` instances acts as a write-through cache so
chat latency does not pay for Supabase every turn; evicted conversations rehydrate from
Supabase on the next hit.

### GET /runs/:id

Fetches the saved request/response pair from the Supabase `runs` table. The frontend
hydrates the main UI from it so a viewer can inspect, edit, and re-run from that
baseline.

## 3. Simulation engine

Core math lives under `simulation/`. Full formulas are in [`MATH.md`](./MATH.md).

| File | Responsibility |
|---|---|
| `network.py` | Venue-specific G/G/s graph (17 to 71 nodes). Traffic equations by LU solve, Erlang-C in log space, Allen-Cunneen correction, Whitt QNA variance propagation, Monte Carlo. |
| `temporal.py` | Beta arrival profiles per event type, in-event circulation, exponential egress. FAST (deterministic) and DEEP (adds MC sweeps) modes. |
| `metrics.py` | Fruin LOS, HES, Safety Risk Score, Revenue Impact, and prioritized recommendations. |
| `demand.py` | Ticket-price turnout feasibility (caps effective attendance before revenue math). |
| `engine.py` | Single-node Kingman Monte Carlo. Used by the Streamlit demo (`app.py`), not by the web app. |

Service rates come from two tiers, each with provenance: literature (DHS / HCM6 / Fruin
published values) and operational (planning defaults informed by public event reporting
and literature upper bounds). The tier is a request parameter and is echoed back in
`data_provenance`, so every number carries its lineage.

## 4. Persistence (optional, Supabase)

Three tables and one storage bucket. Migration:
[`supabase/migrations/0001_init.sql`](../supabase/migrations/0001_init.sql).

| Table | Purpose |
|---|---|
| `runs` | Saved simulations (full request + response JSON, indexed headline metrics). Powers `/runs/:id`. |
| `conversations` | Persistent chat history keyed by `conversation_id`. |
| `scenario_library` | Curated canonical scenarios. Powers the scenario strip and `/scenarios`. |
| `exports` (storage) | Reserved for PDF / CSV exports. Not yet wired. |

Migration [`0002_enable_rls.sql`](../supabase/migrations/0002_enable_rls.sql) enables
row-level security as defense in depth: the backend uses the `service_role` key and
bypasses RLS, while the anon key can only read public runs and canonical scenarios.
Persistence is entirely optional: `api/persistence.py` no-ops gracefully when
`SUPABASE_URL` / `SUPABASE_SERVICE_KEY` are unset, so local dev is zero-config.

## 5. Live data sources

Each module under `data/sources/` exposes a uniform `source_status()` dict so the
`/data/sources` endpoint can surface freshness. Every source has an honest failure
mode: it reports unavailable rather than fabricating data.

| Module | Fetches | Failure mode |
|---|---|---|
| `weather.py` | Open-Meteo ERA5 history + forecast (<=16 days). | Climatology fallback for far-future dates; NOAA normals are calibration-only. |
| `holidays_live.py` | Nager.Date public holidays. | Cached last-good, then a built-in US federal fallback. |
| `events_live.py` | Ticketmaster Discovery concurrent LV events. | Returns `available=false` without a key; major-event labeling is a keyword heuristic. |
| `traffic.py` | NDOT AADT + RTC transit baselines. | Static registry fallback with confidence flags. |
| `traffic_live.py` | Google Routes duration proxy. | Returns `available=false` + reason without a key; static AADT still drives the overlay. |
| `service_rates.py` | Literature + operational service rates. | Bundled with the repo. |

## 6. Frontends

**Web app** (`web/`). React 18 + Vite single-page app, two routes:

| Route | Component |
|---|---|
| `/` | Setup and run UI; fetches `/scenarios` on mount. |
| `/runs/:id` | Hydrates a saved run and reconstructs UI state from the request/response pair. |

Design system (MONOLITH): near-black canvas, 1px borders, no radii, JetBrains Mono for
data, Instrument Serif for the wordmark, colored status dots. Key hooks: `useSimulation`
(form state, live data, `POST /simulate`, `loadRun`), `useChat` (`POST /chat`,
`conversation_id` in `localStorage`), `useVaneAPI` (thin endpoint wrappers).

**Streamlit demo** (`app.py`). A single-command view over the single-node model
(`simulation/engine.py`) with its own environment, optimization, and visualization
helpers. No backend or keys required: `streamlit run app.py`.

## 7. Testing

```
tests/
  test_api.py           FastAPI endpoints and provenance plumbing
  test_demand.py        Ticket-price turnout feasibility
  test_intelligence.py  LLM tool-use loop and error paths
  test_metrics.py       Fruin LOS, revenue, recommendations
  test_network.py       Erlang-C + QNA variance math
  test_persistence.py   Saved-run hydration and route recovery
  test_provenance.py    Live-vs-cached provenance guarantees
  test_temporal.py      Beta arrivals, egress, HES/SRS
  validation/backtest.py  Historical back-test vs public event reporting
```

Run the suite with `python -m pytest tests/ -q`. The intelligence tests expect
`ANTHROPIC_API_KEY` to be unset (they verify the 503 path); unset it first if your
shell already has one loaded.

## 8. Adding a venue, scenario, or data source

1. **Venue**: append to `data/venues/vegas_venues.json` with `confidence`, capacity,
   gate counts, and corridor references. The graph is rebuilt on the next request.
2. **Scenario**: edit `supabase/seed.py` and run `python supabase/seed.py` (upsert keyed
   on `slug`).
3. **Data source**: add `data/sources/<name>.py` implementing `fetch(...)` and
   `source_status()`, then register it in `data/sources/registry.py`.

## 9. Non-goals

Out of scope in the current build: user accounts / auth, a Redis or dedicated cache
layer, multi-instance horizontal scaling (the graph cache is in-process), an admin
dashboard, and the PDF / CSV export pipeline (the bucket exists; wiring is pending).
