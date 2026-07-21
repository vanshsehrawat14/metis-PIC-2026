"""
api/main.py — FastAPI application for the Vane simulation engine.

REST endpoints wrapping the queueing-network, temporal, and metrics engines,
plus optional Supabase persistence and the Anthropic-backed chat layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from api.engine_bridge import EngineBridge

import httpx

# Load environment variables from a local .env file (e.g. ANTHROPIC_API_KEY,
# TICKETMASTER_API_KEY, SUPABASE_*) before anything else imports `os.environ`.
# The .env file is git-ignored; production deploys inject env vars directly.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from slowapi.errors import RateLimitExceeded
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.models import (
    SimulationRequest, SimulationResponse,
    TemporalRequest, TemporalResponse,
    ScenarioCompareRequest, CompareResponse,
    WhatIfRequest,
    StressTestRequest, StressTestResponse,
    VenueListResponse, VenueDetailResponse,
    SpecsResponse,
)
from api.intelligence import VaneIntelligence
from api.persistence import get_persistence
from api.security import (
    BodySizeLimitMiddleware,
    BoundedLRU,
    CHAT_LIMIT,
    HEAVY_LIMIT,
    READ_LIMIT,
    SIM_LIMIT,
    SecurityHeadersMiddleware,
    is_uuid,
    limiter,
    rate_limit_handler,
)

logger = logging.getLogger(__name__)

# Filled asynchronously after bind so /ready responds immediately while the
# engine loads (see _init_bridge_worker).
bridge: EngineBridge | None = None


def _ensure_bridge() -> EngineBridge:
    if bridge is None:
        raise HTTPException(
            status_code=503,
            detail="Engine still initializing. Try again in a few seconds.",
        )
    return bridge


async def _init_bridge_worker() -> None:
    global bridge
    try:
        # Import here so uvicorn can bind before scipy/simulation load.
        from api.engine_bridge import EngineBridge as _EngineBridge

        logger.info("EngineBridge initialization starting...")
        loop = asyncio.get_running_loop()
        b = await loop.run_in_executor(None, _EngineBridge)
        bridge = b
        logger.info("EngineBridge ready with %d venues", len(bridge.venues))
    except Exception:
        logger.exception("EngineBridge initialization failed")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_init_bridge_worker())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# True when self-hosting publicly. Set APP_ENV=production to (a) hide
# Swagger/ReDoc and (b) refuse a wildcard CORS origin at boot.
_IS_PROD = os.environ.get("APP_ENV", "").strip().lower() in {"production", "prod"}

# Hide Swagger/ReDoc in prod so the full API surface (request schemas with
# cap/min/max, every endpoint) isn't trivially indexable. Set
# VANE_ENABLE_DOCS=1 to override in prod (e.g., for a brief audit).
_DOCS_ENABLED = (
    os.environ.get("VANE_ENABLE_DOCS", "").strip() == "1" or not _IS_PROD
)

app = FastAPI(
    title="Vane API",
    description="Predictive intelligence for venue operations",
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

# ── Security: rate limit + body cap + headers ───────────────────────────────
# Order matters: BodySizeLimit runs before route handlers so oversize uploads
# never reach the limiter or pydantic parser. SlowAPI's state must be on the
# app instance and its exception handler registered before any decorated
# route is added (decorators below pick up `app.state.limiter`).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)


# ── CORS ────────────────────────────────────────────────────────────────────
# CORS_ALLOWED_ORIGINS is a comma-separated list of allowed origins. Defaults
# to "*" for dev convenience; a blank value is treated the same way.
#
# In production (APP_ENV=production) we refuse to start with a wildcard: that
# would let any third-party site script the API from the user's browser. A
# misconfigured public deploy should crash, not silently expose the API.
_cors_raw = (os.environ.get("CORS_ALLOWED_ORIGINS") or "*").strip()
if _cors_raw == "*":
    if _IS_PROD:
        raise RuntimeError(
            "Refusing to start with CORS_ALLOWED_ORIGINS='*' when APP_ENV=production. "
            "Set CORS_ALLOWED_ORIGINS to a comma-separated list of your frontend "
            "origin(s), e.g. 'https://your-frontend.example.com'."
        )
    _cors_origins: list[str] = ["*"]
    _cors_credentials = False  # wildcard + credentials is forbidden by the spec
else:
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Trusted Host (defense against Host header injection / cache poisoning) ─
# TRUSTED_HOSTS is comma-separated. Unset (dev) allows any host. When
# self-hosting publicly, pin it to the hostname(s) that serve the API.
_trusted_raw = (os.environ.get("TRUSTED_HOSTS") or "").strip()
if _trusted_raw:
    _trusted_hosts = [h.strip() for h in _trusted_raw.split(",") if h.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts)
elif _IS_PROD:
    logger.warning(
        "TRUSTED_HOSTS not set with APP_ENV=production. Consider pinning it to "
        "the hostname(s) that serve this API."
    )

persistence = get_persistence()

_DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"


# ═══════════════════════════════════════════════════════════════════════════════
#  Simulation endpoints
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/simulate", response_model=SimulationResponse)
@app.post("/api/simulate", response_model=SimulationResponse)
@limiter.limit(SIM_LIMIT)
async def simulate(request: Request, req: SimulationRequest):
    """Run a full Monte Carlo simulation on the venue queueing network."""
    b = _ensure_bridge()
    try:
        result = b.run_simulation(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("simulate failed")
        raise HTTPException(status_code=500, detail="Simulation failed.")

    # Optional persistence — writes to Supabase when `save=True` and the
    # SUPABASE_* env vars are set. Fails silently on the write side so a
    # Supabase outage never prevents the user from seeing their simulation.
    if req.save and persistence.configured:
        run_id = persistence.save_run(request=req.model_dump(mode="json"), response=result)
        if run_id:
            result["run_id"] = run_id

    return result


@app.post("/simulate/temporal", response_model=TemporalResponse)
@app.post("/api/simulate/temporal", response_model=TemporalResponse)
@limiter.limit(SIM_LIMIT)
async def simulate_temporal(request: Request, req: TemporalRequest):
    """Run a time-resolved simulation across the full event lifecycle."""
    b = _ensure_bridge()
    try:
        return b.run_temporal(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("simulate_temporal failed")
        raise HTTPException(status_code=500, detail="Temporal simulation failed.")


@app.post("/scenario/compare", response_model=CompareResponse)
@app.post("/api/scenario/compare", response_model=CompareResponse)
@limiter.limit(HEAVY_LIMIT)
async def compare_scenarios(request: Request, req: ScenarioCompareRequest):
    """Compare two scenarios and show the operational delta."""
    b = _ensure_bridge()
    try:
        return b.compare_scenarios(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("compare_scenarios failed")
        raise HTTPException(status_code=500, detail="Comparison failed.")


@app.post("/scenario/what-if", response_model=CompareResponse)
@app.post("/api/scenario/what-if", response_model=CompareResponse)
@limiter.limit(HEAVY_LIMIT)
async def what_if(request: Request, req: WhatIfRequest):
    """Apply a perturbation to a base scenario and show the impact."""
    b = _ensure_bridge()
    try:
        return b.run_what_if(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("what_if failed")
        raise HTTPException(status_code=500, detail="What-if failed.")


@app.post("/stress-test", response_model=StressTestResponse)
@app.post("/api/stress-test", response_model=StressTestResponse)
@limiter.limit(HEAVY_LIMIT)
async def stress_test(request: Request, req: StressTestRequest):
    """Run predefined stress scenarios against a baseline."""
    b = _ensure_bridge()
    try:
        return b.run_stress_tests(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("stress_test failed")
        raise HTTPException(status_code=500, detail="Stress test failed.")


@app.get("/venues", response_model=VenueListResponse)
@app.get("/api/venues", response_model=VenueListResponse)
@limiter.limit(READ_LIMIT)
async def list_venues(request: Request):
    """List all available venue profiles."""
    return _ensure_bridge().get_venue_list()


@app.get("/venues/{venue_id}", response_model=VenueDetailResponse)
@app.get("/api/venues/{venue_id}", response_model=VenueDetailResponse)
@limiter.limit(READ_LIMIT)
async def get_venue(request: Request, venue_id: str):
    """Get detailed profile and graph topology for a specific venue."""
    b = _ensure_bridge()
    try:
        return b.get_venue_detail(venue_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/specs", response_model=SpecsResponse)
@app.get("/api/specs", response_model=SpecsResponse)
@limiter.limit(READ_LIMIT)
async def get_specs(request: Request):
    """Get the technical specification of the Vane simulation engine."""
    return _ensure_bridge().get_specs()


@app.get("/health")
@app.get("/api/health")
async def health():
    try:
        from data.sources.registry import get_data_sources
        reg = get_data_sources()
        data_summary = reg["summary"]
    except Exception as e:
        data_summary = {"error": f"{type(e).__name__}: {e}"}

    return {
        "status": "operational",
        "engine": "vane_network_v1",
        "venues_loaded": len(bridge.venues) if bridge is not None else 0,
        "intelligence": {
            "available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        },
        "persistence": {
            "configured": persistence.configured,
            "reachable": persistence.reachable() if persistence.configured else False,
        },
        "data_sources": data_summary,
    }


@app.get("/ready")
@app.get("/api/ready")
async def ready():
    """
    Lightweight readiness probe for load balancers and container healthchecks.

    Keep this path dependency-free: it should not call external services or
    optional integrations during boot.
    """
    return {
        "status": "ready",
        "engine": "vane_network_v1",
        "persistence_configured": persistence.configured,
    }


@app.get("/data/sources")
@app.get("/api/data/sources")
@limiter.limit(READ_LIMIT)
async def data_sources(request: Request):
    """
    Return the full data-source registry: every source Vane uses, its kind
    (live / cached / dataset / literature), its URL, license, availability,
    and freshness, so the numbers shown in the UI can be traced to real,
    citable data.
    """
    from data.sources.registry import get_data_sources
    return get_data_sources()


# ═══════════════════════════════════════════════════════════════════════════════
#  Persisted runs — shareable URLs
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/runs/{run_id}")
@app.get("/api/runs/{run_id}")
@limiter.limit(READ_LIMIT)
async def get_run(request: Request, run_id: str):
    """
    Fetch a persisted simulation run by uuid. Used by the /runs/:id route in
    the SPA to hydrate the shared scenario back into the main UI state.
    """
    if not is_uuid(run_id):
        raise HTTPException(status_code=400, detail="Invalid run_id format.")
    if not persistence.configured:
        raise HTTPException(status_code=503, detail="Persistence is not configured on this server.")
    row = persistence.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {
        "id": row["id"],
        "created_at": row.get("created_at"),
        "venue_id": row.get("venue_id"),
        "event_type": row.get("event_type"),
        "attendance": row.get("attendance"),
        "service_rate_tier": row.get("service_rate_tier"),
        "request": row.get("request_json"),
        "response": row.get("response_json"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Scenario library — canonical seeded scenarios
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/scenarios")
@app.get("/api/scenarios")
@limiter.limit(READ_LIMIT)
async def list_scenarios(request: Request):
    """
    List canonical scenarios (Super Bowl LVIII, UFC 306, CES 2026, ...).
    Read from Supabase scenario_library table. Returns [] when persistence
    is not configured so the UI can still render gracefully.
    """
    return {"scenarios": persistence.list_scenarios()}


@app.get("/scenarios/{slug}")
@app.get("/api/scenarios/{slug}")
@limiter.limit(READ_LIMIT)
async def get_scenario(request: Request, slug: str):
    if not persistence.configured:
        raise HTTPException(status_code=503, detail="Persistence is not configured on this server.")
    row = persistence.get_scenario(slug)
    if not row:
        raise HTTPException(status_code=404, detail="Scenario not found.")
    return row


# ═══════════════════════════════════════════════════════════════════════════════
#  Intelligence Layer — Natural Language Interface
# ═══════════════════════════════════════════════════════════════════════════════

_SCENARIO_MAX_BYTES = 16 * 1024


class ChatRequest(BaseModel):
    # Hard caps so a single client can't drive arbitrarily large Anthropic
    # spend with one POST. 4 KB is comfortable for any real operator question.
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    # `scenario` flows into the LLM system prompt as compact JSON. The 256 KB
    # body cap stops gross abuse, but a 60 KB scenario still becomes paid
    # tokens. 16 KB is generous for any real venue/event context object.
    scenario: Optional[dict] = None

    @field_validator("scenario")
    @classmethod
    def _cap_scenario_size(cls, v: Optional[dict]) -> Optional[dict]:
        if v is None:
            return v
        import json as _json
        if len(_json.dumps(v, default=str)) > _SCENARIO_MAX_BYTES:
            raise ValueError(
                f"scenario payload too large (max {_SCENARIO_MAX_BYTES} bytes)."
            )
        return v


class ChatResponse(BaseModel):
    response: str
    tool_calls_made: list[str]
    simulation_results: Optional[list] = None
    web_searches: Optional[list] = None
    conversation_id: str


# In-memory write-through cache for conversations. Supabase is the source of
# truth; the cache saves ~1 round-trip per chat turn on warm instances.
# Bounded so an attacker can't OOM the process by spawning unique conv_ids.
# Evicted entries rehydrate from Supabase on next hit.
_conversations: BoundedLRU = BoundedLRU(maxsize=1000)


def _hydrate_conversation(conv_id: str) -> VaneIntelligence:
    """
    Look up `conv_id` in the write-through cache; on miss, try to rehydrate
    from Supabase; on full miss, start a fresh conversation.
    """
    if conv_id in _conversations:
        return _conversations[conv_id]

    intel = VaneIntelligence(bridge=_ensure_bridge())
    if persistence.configured:
        row = persistence.load_conversation(conv_id)
        if row and isinstance(row.get("messages"), list):
            intel.conversation_history = row["messages"]
    _conversations[conv_id] = intel
    return intel


@app.post("/chat", response_model=ChatResponse)
@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(CHAT_LIMIT)
async def chat(request: Request, req: ChatRequest):
    """
    Natural language interface to the Vane simulation engine.
    Send a message in plain English, get simulation-backed operational intelligence.
    """
    _ensure_bridge()
    # Reject client-supplied conversation_ids that aren't well-formed UUIDs —
    # blocks path-style probes ("../foo") and keeps Supabase keys uniform.
    if req.conversation_id is not None and not is_uuid(req.conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id format.")
    conv_id = req.conversation_id or str(uuid.uuid4())
    intel = _hydrate_conversation(conv_id)

    try:
        result = await intel.chat(req.message, scenario=req.scenario)
    except ValueError as e:
        # Missing API key or bad input — 503 so the UI can render a setup hint.
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503,
            detail=(
                "Intelligence provider unavailable. Check API key, network access, "
                "and provider status."
            ),
        ) from e
    except Exception:
        logger.exception("chat failed")
        raise HTTPException(status_code=500, detail="Intelligence layer error.")

    # Write-through to Supabase (best-effort; cache is still authoritative on
    # this process). Failure here is logged but does not block the response.
    if persistence.configured:
        persistence.save_conversation(
            conv_id,
            intel.conversation_history,
            scenario=req.scenario,
        )

    return ChatResponse(
        response=result["response"],
        tool_calls_made=result["tool_calls_made"],
        simulation_results=result.get("simulation_results"),
        web_searches=result.get("web_searches"),
        conversation_id=conv_id,
    )


@app.delete("/chat/{conversation_id}")
@app.delete("/api/chat/{conversation_id}")
@limiter.limit(READ_LIMIT)
async def end_conversation(request: Request, conversation_id: str):
    """Clear a conversation's history."""
    if not is_uuid(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation_id format.")
    _conversations.pop(conversation_id, None)
    if persistence.configured:
        persistence.delete_conversation(conversation_id)
    return {"status": "cleared"}


# ═══════════════════════════════════════════════════════════════════════════════
#  Optional static hosting (single-origin deployment)
# ═══════════════════════════════════════════════════════════════════════════════
#
# If you deploy FastAPI as the primary service, you can also serve the built Vite
# app from this same origin. Set SERVE_WEB_DIST=1 and ensure `web/dist` exists.
#
if os.environ.get("SERVE_WEB_DIST") == "1" and _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="web")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):  # noqa: ARG001
        index = _DIST_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404, detail="web dist not found")
