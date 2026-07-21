"""
api/models.py — Pydantic request/response models for the Vane API.

All data contracts between API consumers and the simulation engines.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════════════════════

class EventType(str, Enum):
    nfl = "nfl"
    concert = "concert"
    concert_large = "concert_large"
    sports = "sports"
    boxing_mma = "boxing_mma"
    convention = "convention"
    festival = "festival"
    theater = "theater"


class StressTestType(str, Enum):
    gate_failure = "gate_failure"
    extreme_heat = "extreme_heat"
    transit_shutdown = "transit_shutdown"
    staffing_cut = "staffing_cut"
    mass_egress = "mass_egress"
    compound = "compound"


class ServiceRateTier(str, Enum):
    operational = "operational"
    literature = "literature"


# ═══════════════════════════════════════════════════════════════════════════════
#  Request Models
# ═══════════════════════════════════════════════════════════════════════════════

class SimulationRequest(BaseModel):
    """Request for a full Monte Carlo network simulation."""
    venue_id: str = Field(..., description="Venue identifier from vegas_venues.json")
    attendance: int = Field(..., ge=100, le=250000)  # Convention-scale events (CES ≈ 130k)
    event_type: EventType
    weather_factor: Optional[float] = Field(None, ge=0, le=1)
    transit_factor: Optional[float] = Field(None, ge=0, le=1)
    event_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD for auto weather/traffic fetch")
    event_time: Optional[str] = Field(None, description="HH:MM 24hr for time-of-day traffic adjustment")
    gate_distribution: Optional[dict[str, float]] = Field(None, description="Custom per-gate arrival fractions")
    avg_ticket_price: Optional[float] = Field(
        None,
        ge=5,
        le=10000,
        description=(
            "Average single-ticket face value in USD. When supplied, Vane uses "
            "it both for revenue-layer ticket economics and for the ticket-price "
            "turnout-feasibility check that can reduce effective attendance. "
            "When omitted, turnout is left unchanged and the revenue module "
            "uses its NAC-benchmark default ($95)."
        ),
    )
    n_simulations: Optional[int] = Field(1000, ge=100, le=5000)
    service_rate_tier: ServiceRateTier = Field(
        ServiceRateTier.operational,
        description=(
            "Service rate tier: 'operational' (default) uses planning defaults informed "
            "by public event reporting and published literature; 'literature' uses "
            "conservative DHS/Fruin/HCM6 published values for worst-case planning."
        ),
    )
    save: bool = Field(
        False,
        description=(
            "When True and persistence is configured, the run is written to the "
            "`runs` table and the response includes `run_id` for share-by-URL. "
            "No-ops silently when SUPABASE_URL / SUPABASE_SERVICE_KEY are unset."
        ),
    )


class TemporalRequest(BaseModel):
    """Request for a time-resolved simulation across the full event lifecycle."""
    venue_id: str
    attendance: int = Field(..., ge=100, le=250000)
    event_type: EventType
    event_duration_hours: float = Field(3.0, ge=0.5, le=12)
    weather_factor: Optional[float] = Field(None, ge=0, le=1)
    transit_factor: Optional[float] = Field(None, ge=0, le=1)
    event_date: Optional[str] = None
    event_time: Optional[str] = None
    gate_distribution: Optional[dict[str, float]] = None
    avg_ticket_price: Optional[float] = Field(
        None,
        ge=5,
        le=10000,
        description="Optional average ticket price in USD for turnout-feasibility and revenue modeling.",
    )
    mode: str = Field("fast", pattern="^(fast|deep)$")
    dt_minutes: Optional[float] = Field(2.0, ge=0.5, le=10)
    service_rate_tier: ServiceRateTier = Field(
        ServiceRateTier.operational,
        description=(
            "Service rate tier: 'operational' (default) uses planning defaults informed "
            "by public event reporting and published literature; 'literature' uses "
            "conservative DHS/Fruin/HCM6 published values for worst-case planning."
        ),
    )


class ScenarioCompareRequest(BaseModel):
    """Request to compare two scenarios and show the delta."""
    venue_id: str
    base: SimulationRequest
    modified: SimulationRequest
    graph_changes: Optional[dict] = Field(None, description="Graph modifications for the modified scenario")


class WhatIfRequest(BaseModel):
    """Request to apply a perturbation to a base scenario."""
    venue_id: str
    attendance: int = Field(..., ge=100, le=250000)
    event_type: EventType
    weather_factor: Optional[float] = Field(None, ge=0, le=1)
    transit_factor: Optional[float] = Field(None, ge=0, le=1)
    event_date: Optional[str] = None
    event_time: Optional[str] = None
    avg_ticket_price: Optional[float] = Field(
        None,
        ge=5,
        le=10000,
        description="Optional average ticket price in USD for turnout-feasibility and revenue modeling.",
    )
    service_rate_tier: ServiceRateTier = Field(
        ServiceRateTier.operational,
        description=(
            "Service rate tier: 'operational' (default) uses planning defaults informed "
            "by public event reporting and published literature; 'literature' uses "
            "conservative DHS/Fruin/HCM6 published values for worst-case planning."
        ),
    )
    changes: dict = Field(..., description="Changes: disable_gates, add_servers, reduce_staffing_pct, close_section")


class StressTestRequest(BaseModel):
    """Request to run predefined stress scenarios."""
    venue_id: str
    attendance: int = Field(..., ge=100, le=250000)
    event_type: EventType
    weather_factor: Optional[float] = Field(None, ge=0, le=1)
    transit_factor: Optional[float] = Field(None, ge=0, le=1)
    event_date: Optional[str] = None
    avg_ticket_price: Optional[float] = Field(
        None,
        ge=5,
        le=10000,
        description="Optional average ticket price in USD for turnout-feasibility and revenue modeling.",
    )
    service_rate_tier: ServiceRateTier = Field(
        ServiceRateTier.operational,
        description=(
            "Service rate tier: 'operational' (default) uses planning defaults informed "
            "by public event reporting and published literature; 'literature' uses "
            "conservative DHS/Fruin/HCM6 published values for worst-case planning."
        ),
    )
    tests: Optional[list[StressTestType]] = Field(None, description="Specific tests to run. If omitted, runs all.")


# ═══════════════════════════════════════════════════════════════════════════════
#  Response Models
# ═══════════════════════════════════════════════════════════════════════════════

class SimulationResponse(BaseModel):
    success: bool
    venue_id: str
    venue_name: str
    parameters: dict
    simulation: dict
    metrics: dict
    computation_time_ms: float
    engine_version: str
    data_provenance: Optional[dict] = None
    run_id: Optional[str] = Field(
        None,
        description="Set when `save=True` on the request and persistence is reachable. Use /runs/{run_id} to fetch later.",
    )


class TemporalResponse(BaseModel):
    success: bool
    venue_id: str
    venue_name: str
    parameters: dict
    mode: str
    temporal: dict
    metrics: dict
    computation_time_ms: float
    data_provenance: Optional[dict] = None


class CompareResponse(BaseModel):
    success: bool
    base: SimulationResponse
    modified: SimulationResponse
    delta: dict
    improved_nodes: list[str]
    degraded_nodes: list[str]
    summary: str


class StressTestResponse(BaseModel):
    success: bool
    venue_id: str
    venue_name: str
    base_scenario: dict
    stress_results: dict
    most_vulnerable: str
    resilience_score: float
    data_provenance: Optional[dict] = None


class VenueListResponse(BaseModel):
    success: bool
    venues: list[dict]


class VenueDetailResponse(BaseModel):
    success: bool
    venue: dict
    graph_summary: dict


class SpecsResponse(BaseModel):
    success: bool
    engine: dict
