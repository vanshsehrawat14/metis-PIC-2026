# Vane

Vane is a decision-support tool for venue and live-event operations. It compiles a
venue into a queueing network, runs a Monte Carlo simulation of crowd flow through
gates, security, concourses, concessions, restrooms, and exits, and reports where
lines form, how long guests wait, where the safety and revenue risks sit, and which
operational change helps most.

It answers questions like:

- How long will guests wait under a given event, attendance, weather, and transit?
- Which node controls the system, and what happens if a gate closes or staffing drops?
- Is the requested attendance economically feasible at a given ticket price?

The math engine is the product. An optional chat layer (Anthropic tool use) is a
narrator on top of it: it calls the same engine and does not invent numbers.

## Background

Vane began as **Metis**, a finalist in the **2026 UNLV President's Innovation
Challenge**. This repository is the continuation of that project, rebuilt and
maintained solo under the name Vane. It is a personal engineering project, published
to show the code and the math. It is not hosted anywhere: clone it, add your own API
keys, and run or host it however you like.

## What's here

- **Web app** (`web/` + `api/`): the main product. A React 18 + Vite frontend on a
  FastAPI backend running the queueing-network engine (`simulation/network.py`,
  `temporal.py`, `metrics.py`, `demand.py`), with optional persistence and chat.
- **Streamlit demo** (`app.py`): an earlier, simpler single-command view built on a
  single-node Monte Carlo model (`simulation/engine.py`). No API keys required.

## Run it

Streamlit demo (no API keys required):

```bash
pip install -r requirements.txt
streamlit run app.py
```

Full web app:

```bash
pip install -r requirements.txt

# terminal 1 — backend
uvicorn api.main:app --port 8000

# terminal 2 — frontend
cd web && npm install && npm run dev
# open http://localhost:5173
```

Simulation, temporal, stress tests, and the whole UI run with no keys. Only the chat
endpoint needs an Anthropic key; persistence (shareable run URLs, the scenario
library) is optional and needs Supabase. Copy `.env.example` to `.env` and fill in
what you want. Interactive API docs are at `http://localhost:8000/docs`.

## The model

Vane compiles each venue into a directed queueing network. Nodes are gates, security
lanes, concourses, concessions, restrooms, seating, exit corridors, and exits; edges
are attendee routing probabilities.

Node arrival rates solve the open-network traffic equations:

```
lambda = gamma + R^T lambda   =>   lambda = (I - R^T)^{-1} gamma
```

where `gamma` is external arrival demand and `R` is the routing matrix. Each service
node uses M/M/s Erlang-C (computed in log space to avoid factorial overflow at large
server counts), corrected toward G/G/s with the Allen-Cunneen factor
`(c_a^2 + c_s^2) / 2`. Inter-arrival variance is propagated across the graph with a
Whitt QNA fixed-point pass. A 1,000-trial Monte Carlo layer perturbs arrivals,
service rates, weather, and transit, and reports means with P10/P90 bands. A temporal
model steps through arrival, in-event circulation, and egress using event-type Beta
arrival profiles and exponential egress decay.

Full derivations, every constant, and where each formula lives in code are in
[`docs/MATH.md`](docs/MATH.md).

## Outputs

- **Wait and congestion**: per-node wait, queue length, utilization, bottleneck ranking.
- **Fruin LOS**: A to F pedestrian level-of-service from density and walking-speed bands.
- **HES**: Human Experience Score, a multiplicative composite of wait, density,
  temperature, service, and access, so several weak factors compound.
- **SRS**: Safety Risk Score, the max of crush-density risk, exit-flow capacity risk,
  and estimated evacuation time against a planning target.
- **Revenue**: downside-at-risk for concessions, merchandise, and future ticket
  demand, with optional ticket-price feasibility that caps effective attendance.

## Data and provenance

Every venue value, external overlay, and modeled input carries a source and a
confidence level, and estimated values are marked as estimated. Weather, holidays,
live events, and traffic are pulled from public sources with honest failure modes
(they report unavailable rather than fabricating). Sources and confidence levels are
in [`docs/data_sources.md`](docs/data_sources.md).

## Limits

Vane is theory-grounded and back-tested against public event reporting, not calibrated
from venue scanner or queue-measurement logs. It fits stadium and arena ingress better
than convention registration flow, and can over-predict waits when public topology
understates real security throughput. Outputs are decision support, not regulatory
certification or emergency-egress approval. See
[`docs/BENCHMARKS_AND_VALIDATION.md`](docs/BENCHMARKS_AND_VALIDATION.md).

## Layout

```
api/            FastAPI app, engine bridge, intelligence (chat), persistence, security
simulation/     network + temporal + metrics + demand (queueing-network engine);
                engine.py is the single-node model used by the Streamlit demo
data/           venue profiles, live-data sources, service-rate calibration
web/            React 18 + Vite frontend (main product)
app.py          Streamlit demo; optimization/ and visualization/ support it
supabase/       optional persistence schema + seed
tests/          backend, metrics, temporal, persistence, API, and validation tests
docs/           architecture, math, data sources, benchmarks
```

## Tests

```bash
python -m pytest tests/ -q
cd web && npm run build
python -m tests.validation.backtest   # historical back-test
```
