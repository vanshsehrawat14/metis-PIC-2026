"""
api/engine_bridge.py — Wires API requests to simulation engines.

Glue layer between Pydantic models and the simulation engine classes.
Handles venue loading, parameter resolution, graph construction, and execution.
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from simulation.network import VenueGraph, NetworkMonteCarloEngine
from simulation.temporal import ArrivalProfile, TemporalSimulator
from simulation.metrics import compute_full_metrics
from simulation.demand import resolve_ticket_demand
from data.sources.service_rates import ServiceRateDatabase

if TYPE_CHECKING:
    from api.models import (
        SimulationRequest, TemporalRequest, ScenarioCompareRequest,
        WhatIfRequest, StressTestRequest,
    )

logger = logging.getLogger(__name__)

VENUES_PATH = Path(__file__).parent.parent / "data" / "venues" / "vegas_venues.json"


def _service_rate_provenance(tier: str) -> dict:
    """
    Return a provenance block for the service-rate parameters being used in a run.

    Two tiers are supported:
      'literature'  — conservative DHS/Fruin/HCM6/IAAM published values
                      (the numbers every peer-reviewed textbook would cite).
      'operational' — planning defaults informed by public event reporting,
                      venue operations context, and literature upper bounds.
                      These are not calibrated from venue-owned scanner logs.

    The tier is surfaced in API responses and in the data-sources card so
    users can see which calibration is driving the numbers they see.
    """
    tier = tier if tier in ("operational", "literature") else "operational"
    if tier == "literature":
        return {
            "tier": "literature",
            "source": "DHS (2018) venue security, Fruin (1987/1993), HCM6 Ch.24, IAAM (2007)",
            "url": "https://www.cisa.gov/resources-tools/resources/public-venue-security-screening-guide",
            "license": "Public-domain / published literature; cited per-parameter in data/sources/service_rates.py",
            "kind": "literature",
            "live": False,
            "fetched_fresh": False,
            "available": True,
            "notes": (
                "Conservative planning values. These are the textbook numbers. "
                "Will typically over-predict wait times by 1.5-3x vs. real venue throughput."
            ),
        }
    return {
        "tier": "operational",
        "source": "Operational planning defaults informed by public reporting from Super Bowl LVIII (2024-02-11), UFC 306 at Sphere (2024-09-14), CES 2024, and literature upper bounds",
        "url": None,
        "license": "Derived synthesis from public reporting and published operations literature",
        "kind": "dataset",
        "live": False,
        "fetched_fresh": False,
        "available": True,
        "notes": (
            "Planning defaults for expected operations. Informed by public event reporting "
            "and literature, but not calibrated from venue-owned scanner or sensor logs. "
            "Use 'literature' tier for conservative / worst-case planning."
        ),
    }


def _tier_value(tier) -> str:
    """Normalize Pydantic enums / strings to the canonical tier label."""
    return getattr(tier, "value", tier) or "operational"


def _canonical_hes(result: dict) -> float:
    """Use the user-facing HES definition when comparing scenarios."""
    return float(
        result.get("metrics", {}).get("experience", {}).get(
            "hes",
            result.get("simulation", {}).get("hes_mean", 50.0),
        )
    )


class EngineBridge:
    """
    Bridges API requests to simulation engines.
    Handles venue loading, parameter auto-resolution, and result formatting.
    """

    def __init__(self):
        # Two service_db instances — operational (default) and literature (conservative)
        self.service_db = ServiceRateDatabase(tier="operational")
        self.service_db_literature = ServiceRateDatabase(tier="literature")
        self.venues = self._load_venues()
        # Graph cache keyed by (venue_id, tier) — different tiers produce different node rates
        self._graph_cache: dict[tuple, VenueGraph] = {}

    def _load_venues(self) -> dict:
        """Load all venue profiles keyed by venue_id."""
        with open(VENUES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {v["venue_id"]: v for v in data["venues"]}

    def _get_graph(self, venue_id: str, tier: str = "operational") -> VenueGraph:
        """Get or build a VenueGraph for the given venue. Cache keyed by (venue_id, tier)."""
        cache_key = (venue_id, tier)
        if cache_key not in self._graph_cache:
            if venue_id not in self.venues:
                raise ValueError(
                    f"Unknown venue: {venue_id}. Available: {list(self.venues.keys())}"
                )
            sdb = self.service_db if tier == "operational" else self.service_db_literature
            self._graph_cache[cache_key] = VenueGraph.from_venue_profile(
                self.venues[venue_id], sdb
            )
        return self._graph_cache[cache_key]

    def _get_venue_capacity(self, venue_id: str) -> int:
        """Backward-compatible generic capacity lookup."""
        return self._get_event_capacity(venue_id)[0]

    def _get_event_capacity(self, venue_id: str, event_type: str | None = None) -> tuple[int, str]:
        """Extract the event-appropriate sellable capacity from the venue profile."""
        cap = self.venues[venue_id]["capacity"]
        basis_map = {
            "nfl": ["football", "max", "app_py_value"],
            "concert": ["concert_with_floor", "concert", "seated_concert", "standing", "max", "app_py_value"],
            "concert_large": ["concert_with_floor", "concert", "standing", "max", "app_py_value"],
            "sports": ["basketball", "hockey_nhl", "concert", "max", "app_py_value"],
            "boxing_mma": ["concert", "basketball", "standing", "max", "app_py_value"],
            "convention": ["app_py_value", "max"],
            "festival": ["standing", "max", "app_py_value"],
            "theater": ["theater", "seated_concert", "concert", "max", "app_py_value"],
        }
        keys = basis_map.get(event_type or "", [])
        keys += [
            "max", "football", "concert_with_floor", "concert", "basketball",
            "hockey_nhl", "seated_concert", "standing", "app_py_value",
        ]
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            value = cap.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value), key
        return 10000, "fallback_default"

    def _resolve_demand(self, req, venue_id: str, event_type: str) -> tuple[dict, int, str]:
        capacity, capacity_basis = self._get_event_capacity(venue_id, event_type)
        demand = resolve_ticket_demand(
            requested_attendance=getattr(req, "attendance", 0),
            venue_capacity=capacity,
            event_type=event_type,
            avg_ticket_price=getattr(req, "avg_ticket_price", None),
            capacity_basis=capacity_basis,
        )
        return demand, capacity, capacity_basis

    @staticmethod
    def _revenue_params(req) -> dict | None:
        """
        Build the optional `revenue_params` override dict for compute_full_metrics.

        Only forwards fields the user explicitly supplied — so the NAC-benchmark
        defaults in `RevenueImpact.DEFAULTS` stay authoritative when nothing is
        passed.  Today the only knob exposed over HTTP is `avg_ticket_price`
        (maps to `average_ticket_price` on the model).
        """
        overrides: dict = {}
        ticket_price = getattr(req, "avg_ticket_price", None)
        if ticket_price is not None:
            overrides["average_ticket_price"] = float(ticket_price)
        return overrides or None

    @staticmethod
    def _weather_payload(severity: float, prov: dict | None) -> dict:
        """
        Build the `weather_data` payload for compute_full_metrics.

        Historically we synthesised heat index as `75 + severity * 50`, which
        meant HES "temperature" was NOT what Open-Meteo returned even when the
        live path succeeded — a provenance/UX mismatch.

        New hierarchy (most honest first):
          1. Use the real Rothfusz heat_index_f from Open-Meteo when present
             (requires temp_f ≥ 80 °F AND RH ≥ 40%).
          2. Vegas has ~20% RH year-round, so HI is usually null even on
             110°F days.  Fall back to the raw temp_f from the same API call
             — this IS the honest heat-stress signal for arid climates (NWS
             excessive-heat criteria switch to temp-based at low RH anyway).
          3. Only if neither is available (default-default fallback), use the
             severity-derived proxy (`75 + severity·50`).  Marked explicitly
             in the provenance so the UI can show the caveat.
        """
        if isinstance(prov, dict):
            real_hi = prov.get("heat_index_f")
            if real_hi is not None:
                return {
                    "heat_index_f": float(real_hi),
                    "heat_index_source": "open-meteo:rothfusz",
                    "weather_severity": severity,
                }
            real_temp = prov.get("temp_f")
            if real_temp is not None:
                return {
                    "heat_index_f": float(real_temp),
                    "heat_index_source": "open-meteo:temp_f_low_humidity",
                    "weather_severity": severity,
                }
        return {
            "heat_index_f": 75.0 + severity * 50.0,
            "heat_index_source": "severity_proxy_fallback",
            "weather_severity": severity,
        }

    def _resolve_weather(
        self,
        weather_factor: float | None,
        event_date: str | None,
        event_time: str | None,
    ) -> tuple[float, dict]:
        """
        Resolve weather factor and return (value, provenance).

        Provenance policy:
        1. If explicit value supplied by caller → kind="user_override".
        2. Else try Open-Meteo forecast_fetch() if event_date is given → kind="live".
        3. Else → kind="fallback_default" with value=0.3 and a clear reason.
        """
        if weather_factor is not None:
            return weather_factor, {
                "source": "user_override",
                "kind": "user_override",
                "live": False,
                "value": weather_factor,
                "note": "weather_factor explicitly supplied in request",
            }

        if event_date:
            try:
                from data.sources.weather import forecast_fetch, _FORECAST_URL, _HISTORICAL_URL, LV_LAT, LV_LON
                hours = forecast_fetch(event_date)
                target_hour = 19
                if event_time:
                    try:
                        target_hour = int(event_time.split(":")[0])
                    except (ValueError, IndexError):
                        pass
                if hours and len(hours) > target_hour:
                    record = hours[target_hour]
                elif hours:
                    record = hours[0]
                else:
                    record = None

                if record is not None:
                    is_clim = bool(record.get("is_climatology"))
                    return record.get("weather_severity", 0.3), {
                        "source": (
                            "Open-Meteo ERA5 Historical Archive (climatology)"
                            if is_clim else
                            "Open-Meteo Forecast API"
                        ),
                        "kind": "climatology" if is_clim else "live",
                        "live": not is_clim,
                        "url": _HISTORICAL_URL if is_clim else _FORECAST_URL,
                        "lat": LV_LAT,
                        "lon": LV_LON,
                        "date": event_date,
                        "hour": target_hour,
                        "climatology_year": record.get("climatology_year"),
                        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "temp_f": record.get("temp_f"),
                        "heat_index_f": record.get("heat_index_f"),
                        "weather_severity": record.get("weather_severity"),
                        "weather_code": record.get("weather_code"),
                        "license": "CC BY 4.0 (Open-Meteo)",
                        "note": (
                            "Forecast horizon exceeds 16 days; using ERA5 "
                            "historical same-day climatology from the most recent archived year."
                        ) if is_clim else None,
                    }
            except Exception as e:
                logger.warning("Weather auto-fetch failed: %s. Using default 0.3.", e)
                return 0.3, {
                    "source": "fallback_default",
                    "kind": "fallback_default",
                    "live": False,
                    "value": 0.3,
                    "reason": f"Open-Meteo fetch failed: {type(e).__name__}: {e}",
                }

        return 0.3, {
            "source": "fallback_default",
            "kind": "fallback_default",
            "live": False,
            "value": 0.3,
            "reason": "no event_date supplied and no explicit weather_factor",
        }

    def _resolve_traffic(
        self,
        transit_factor: float | None,
        venue_id: str,
        event_date: str | None,
        event_time: str | None,
    ) -> tuple[float, dict]:
        """
        Resolve transit factor and return (value, provenance).
        """
        if transit_factor is not None:
            return transit_factor, {
                "source": "user_override",
                "kind": "user_override",
                "live": False,
                "value": transit_factor,
                "note": "transit_factor explicitly supplied in request",
            }

        if event_date:
            try:
                from data.sources.traffic import get_traffic_context
                hour = 19
                if event_time:
                    try:
                        hour = int(event_time.split(":")[0])
                    except (ValueError, IndexError):
                        pass
                dt = datetime.strptime(f"{event_date} {hour:02d}:00", "%Y-%m-%d %H:%M")
                ctx = get_traffic_context(venue_id, dt)
                # Honest provenance split.  The base traffic load comes from
                # static NDOT AADT + RTC tables (a dataset, not a live feed).
                # Three overlay components can each be live:
                #   events         — Ticketmaster Discovery API
                #   holidays       — Nager.Date API
                #   live_traffic   — Google Routes v2 (duration_in_traffic)
                # Top-level `live` is True iff at least one component actually
                # succeeded against its upstream.
                sub_prov = ctx.get("provenance", {}) or {}
                events_live       = bool(sub_prov.get("events", {}).get("live"))
                holidays_live     = bool(sub_prov.get("holidays", {}).get("live"))
                live_traffic_prov = sub_prov.get("live_traffic", {}) or {}
                traffic_live      = bool(live_traffic_prov.get("live"))
                any_live_overlay  = events_live or holidays_live or traffic_live
                return ctx.get("transit_accessibility", 0.5), {
                    "source": "Vane traffic model (NDOT AADT + RTC transit ± live events/holidays/routes overlays)",
                    "kind": "composite_dataset_plus_overlay",
                    # True iff at least one overlay (events, holidays, or
                    # Google Routes) fetched live data for this date.
                    "live": any_live_overlay,
                    "base_layer_live": False,
                    "base_layer_kind": "dataset",
                    "overlay_events_live":   events_live,
                    "overlay_holidays_live": holidays_live,
                    "overlay_traffic_live":  traffic_live,
                    "base_traffic_load":  ctx.get("base_traffic_load"),
                    "event_overlay_factor": ctx.get("event_overlay_factor"),
                    "live_congestion_ratio": ctx.get("live_congestion_ratio"),
                    "transit_accessibility": ctx.get("transit_accessibility"),
                    "traffic_factor": ctx.get("traffic_factor"),
                    "corridor_aadt": ctx.get("corridor_aadt"),
                    "corridor_id":   ctx.get("corridor_id"),
                    "is_major_event_date": ctx.get("is_major_event_date"),
                    "is_holiday":          ctx.get("is_holiday"),
                    "live_subsources":  sub_prov,
                    "static_sources":   ctx.get("sources", []),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            except Exception as e:
                logger.warning("Traffic auto-fetch failed: %s. Using default 0.5.", e)
                return 0.5, {
                    "source": "fallback_default",
                    "kind": "fallback_default",
                    "live": False,
                    "value": 0.5,
                    "reason": f"traffic context failed: {type(e).__name__}: {e}",
                }

        return 0.5, {
            "source": "fallback_default",
            "kind": "fallback_default",
            "live": False,
            "value": 0.5,
            "reason": "no event_date supplied and no explicit transit_factor",
        }

    # ── Simulation ──────────────────────────────────────────────────────────────

    def run_simulation(self, req: SimulationRequest) -> dict:
        """Execute a full Monte Carlo simulation."""
        start = time.time()

        tier = _tier_value(getattr(req, "service_rate_tier", "operational"))
        graph = self._get_graph(req.venue_id, tier=tier)
        weather, weather_prov = self._resolve_weather(req.weather_factor, req.event_date, req.event_time)
        transit, transit_prov = self._resolve_traffic(req.transit_factor, req.venue_id, req.event_date, req.event_time)
        demand, capacity, capacity_basis = self._resolve_demand(req, req.venue_id, req.event_type.value)
        effective_attendance = demand["effective_attendance"]

        engine = NetworkMonteCarloEngine(graph, n_simulations=req.n_simulations or 1000)
        raw_result = engine.run(
            total_attendance=effective_attendance,
            event_type=req.event_type.value,
            weather_factor=weather,
            transit_factor=transit,
            gate_distribution=req.gate_distribution,
        )

        metrics = compute_full_metrics(
            network_result=raw_result,
            attendance=effective_attendance,
            venue_capacity=capacity,
            weather_data=self._weather_payload(weather, weather_prov),
            revenue_params=self._revenue_params(req),
            event_type=req.event_type.value,
            demand_model=demand,
        )

        elapsed = (time.time() - start) * 1000

        return {
            "success": True,
            "venue_id": req.venue_id,
            "venue_name": self.venues[req.venue_id]["name"],
            "parameters": {
                "attendance": effective_attendance,
                "attendance_requested": req.attendance,
                "event_type": req.event_type.value,
                "weather_factor": weather,
                "transit_factor": transit,
                "n_simulations": req.n_simulations or 1000,
                "service_rate_tier": tier,
                "avg_ticket_price": getattr(req, "avg_ticket_price", None),
                "venue_capacity": capacity,
                "capacity_basis": capacity_basis,
            },
            "simulation": raw_result,
            "metrics": metrics,
            "data_provenance": {
                "weather": weather_prov,
                "transit": transit_prov,
                "service_rates": _service_rate_provenance(tier),
                "pricing_demand": demand.get("provenance"),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "computation_time_ms": round(elapsed, 1),
            "engine_version": raw_result.get("engine_version", "network_v1"),
        }

    # ── Temporal Simulation ─────────────────────────────────────────────────────

    def run_temporal(self, req: TemporalRequest) -> dict:
        """Execute a temporal simulation (fast or deep mode)."""
        start = time.time()

        tier = _tier_value(getattr(req, "service_rate_tier", "operational"))
        graph = self._get_graph(req.venue_id, tier=tier)
        weather, weather_prov = self._resolve_weather(req.weather_factor, req.event_date, req.event_time)
        transit, transit_prov = self._resolve_traffic(req.transit_factor, req.venue_id, req.event_date, req.event_time)
        demand, capacity, capacity_basis = self._resolve_demand(req, req.venue_id, req.event_type.value)
        effective_attendance = demand["effective_attendance"]

        dt = req.dt_minutes or 2.0
        simulator = TemporalSimulator(graph, dt_minutes=dt)

        params = dict(
            total_attendance=effective_attendance,
            event_type=req.event_type.value,
            event_duration_hours=req.event_duration_hours,
            weather_factor=weather,
            transit_factor=transit,
            gate_distribution=req.gate_distribution,
        )

        if req.mode == "deep":
            raw = simulator.run_deep(**params)
            temporal_data = raw["fast_result"].to_dict()
            temporal_data["critical_points"] = [
                {
                    "t_minutes": cp["t_minutes"],
                    "phase": cp["phase"],
                    "wait_mean": cp["monte_carlo_result"]["wait_mean"],
                    "wait_p10": cp["monte_carlo_result"]["wait_p10"],
                    "wait_p90": cp["monte_carlo_result"]["wait_p90"],
                    "hes_mean": cp["monte_carlo_result"]["hes_mean"],
                }
                for cp in raw["critical_points"]
                if cp.get("monte_carlo_result")
            ]
            temporal_data["uncertainty_summary"] = raw.get("uncertainty_summary", {})
            fast_result = raw["fast_result"]
        else:
            fast_result = simulator.run_fast(**params)
            temporal_data = fast_result.to_dict()

        # Compute metrics at peak congestion point using a snapshot simulation
        snapshot_engine = NetworkMonteCarloEngine(graph, n_simulations=200)
        snapshot = snapshot_engine.run(
            total_attendance=effective_attendance,
            event_type=req.event_type.value,
            weather_factor=weather,
            transit_factor=transit,
            gate_distribution=req.gate_distribution,
        )
        metrics = compute_full_metrics(
            network_result=snapshot,
            temporal_result=fast_result,
            attendance=effective_attendance,
            venue_capacity=capacity,
            weather_data=self._weather_payload(weather, weather_prov),
            revenue_params=self._revenue_params(req),
            event_type=req.event_type.value,
            demand_model=demand,
        )

        elapsed = (time.time() - start) * 1000
        if req.mode == "deep":
            temporal_data["fast_curve_computation_time_ms"] = temporal_data.get("computation_time_ms")
            temporal_data["computation_time_ms"] = round(elapsed, 1)

        return {
            "success": True,
            "venue_id": req.venue_id,
            "venue_name": self.venues[req.venue_id]["name"],
            "parameters": {
                "attendance": effective_attendance,
                "attendance_requested": req.attendance,
                "event_type": req.event_type.value,
                "event_duration_hours": req.event_duration_hours,
                "weather_factor": weather,
                "transit_factor": transit,
                "mode": req.mode,
                "dt_minutes": dt,
                "service_rate_tier": tier,
                "avg_ticket_price": getattr(req, "avg_ticket_price", None),
                "venue_capacity": capacity,
                "capacity_basis": capacity_basis,
            },
            "mode": req.mode,
            "temporal": temporal_data,
            "metrics": metrics,
            "data_provenance": {
                "weather": weather_prov,
                "transit": transit_prov,
                "service_rates": _service_rate_provenance(tier),
                "pricing_demand": demand.get("provenance"),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "computation_time_ms": round(elapsed, 1),
        }

    # ── Scenario Comparison ────────────────────────────────────────────────────

    def compare_scenarios(self, req: ScenarioCompareRequest) -> dict:
        """Run two simulations and compute the delta."""
        if req.base.venue_id != req.venue_id or req.modified.venue_id != req.venue_id:
            raise ValueError(
                "ScenarioCompareRequest venue_id must match both base.venue_id and modified.venue_id."
            )

        base_result = self.run_simulation(req.base)

        if req.graph_changes:
            tier = _tier_value(getattr(req.modified, "service_rate_tier", "operational"))
            graph = self._get_graph(req.venue_id, tier=tier)
            mod_graph = graph.modify(req.graph_changes)
            weather, weather_prov = self._resolve_weather(
                req.modified.weather_factor, req.modified.event_date, req.modified.event_time
            )
            transit, transit_prov = self._resolve_traffic(
                req.modified.transit_factor, req.modified.venue_id,
                req.modified.event_date, req.modified.event_time,
            )
            demand, capacity, capacity_basis = self._resolve_demand(
                req.modified, req.modified.venue_id, req.modified.event_type.value
            )
            effective_attendance = demand["effective_attendance"]
            engine = NetworkMonteCarloEngine(mod_graph, n_simulations=req.modified.n_simulations or 1000)
            raw = engine.run(
                total_attendance=effective_attendance,
                event_type=req.modified.event_type.value,
                weather_factor=weather,
                transit_factor=transit,
                gate_distribution=req.modified.gate_distribution,
            )
            metrics = compute_full_metrics(
                network_result=raw,
                attendance=effective_attendance,
                venue_capacity=capacity,
                weather_data=self._weather_payload(weather, weather_prov),
                revenue_params=self._revenue_params(req.modified),
                event_type=req.modified.event_type.value,
                demand_model=demand,
            )
            mod_result = {
                "success": True,
                "venue_id": req.modified.venue_id,
                "venue_name": self.venues[req.modified.venue_id]["name"],
                "parameters": {
                    "attendance": effective_attendance,
                    "attendance_requested": req.modified.attendance,
                    "event_type": req.modified.event_type.value,
                    "weather_factor": weather,
                    "transit_factor": transit,
                    "n_simulations": req.modified.n_simulations or 1000,
                    "service_rate_tier": tier,
                    "avg_ticket_price": getattr(req.modified, "avg_ticket_price", None),
                    "venue_capacity": capacity,
                    "capacity_basis": capacity_basis,
                },
                "simulation": raw,
                "metrics": metrics,
                "data_provenance": {
                    "weather": weather_prov,
                    "transit": transit_prov,
                    "service_rates": _service_rate_provenance(tier),
                    "pricing_demand": demand.get("provenance"),
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                "computation_time_ms": 0,
                "engine_version": raw.get("engine_version", "network_v1"),
            }
        else:
            mod_result = self.run_simulation(req.modified)

        return self._build_compare_response(base_result, mod_result)

    def run_what_if(self, req: WhatIfRequest) -> dict:
        """Apply a perturbation and compare against baseline."""
        from api.models import SimulationRequest

        tier = _tier_value(getattr(req, "service_rate_tier", "operational"))
        graph = self._get_graph(req.venue_id, tier=tier)
        node_ids = {nd.node_id for nd in graph.nodes}
        base_req = SimulationRequest(
            venue_id=req.venue_id,
            attendance=req.attendance,
            event_type=req.event_type,
            weather_factor=req.weather_factor,
            transit_factor=req.transit_factor,
            event_date=req.event_date,
            event_time=req.event_time,
            avg_ticket_price=req.avg_ticket_price,
            n_simulations=500,
            service_rate_tier=tier,
        )
        base_result = self.run_simulation(base_req)

        # Build graph changes from the changes dict
        graph_changes: dict = {"disable_nodes": [], "modify_servers": {}}
        changes = req.changes
        allowed_change_keys = {"disable_gates", "add_servers", "reduce_staffing_pct", "close_section"}
        unknown_keys = set(changes) - allowed_change_keys
        if unknown_keys:
            raise ValueError(f"Unknown what-if change keys: {sorted(unknown_keys)}")

        if "disable_gates" in changes:
            for gate_id in changes["disable_gates"]:
                if gate_id not in node_ids or not gate_id.startswith("gate_"):
                    raise ValueError(f"Unknown gate id in disable_gates: {gate_id}")
                graph_changes["disable_nodes"].append(gate_id)
                # Also disable the paired security checkpoint
                sec_id = gate_id.replace("gate_", "security_")
                if sec_id in node_ids:
                    graph_changes["disable_nodes"].append(sec_id)

        if "add_servers" in changes:
            for node_id, extra in changes["add_servers"].items():
                if node_id not in node_ids:
                    raise ValueError(f"Unknown node id in add_servers: {node_id}")
                if extra < 0:
                    raise ValueError("add_servers values must be non-negative")
                current = graph.get_node(node_id).num_servers
                graph_changes["modify_servers"][node_id] = current + extra

        if "reduce_staffing_pct" in changes:
            pct = changes["reduce_staffing_pct"]
            if pct < 0 or pct >= 1:
                raise ValueError("reduce_staffing_pct must be in [0, 1).")
            for nd in graph.nodes:
                if nd.node_type in ("security", "ticketing", "concession", "restroom"):
                    new_s = max(1, int(nd.num_servers * (1 - pct)))
                    graph_changes["modify_servers"][nd.node_id] = new_s

        if "close_section" in changes:
            prefix = changes["close_section"]
            matched = False
            for nd in graph.nodes:
                if nd.node_id.startswith(prefix):
                    graph_changes["disable_nodes"].append(nd.node_id)
                    matched = True
            if not matched:
                raise ValueError(f"close_section prefix matched no nodes: {prefix}")

        # Run modified scenario
        mod_graph = graph.modify(graph_changes)
        weather, weather_prov = self._resolve_weather(req.weather_factor, req.event_date, req.event_time)
        transit, transit_prov = self._resolve_traffic(req.transit_factor, req.venue_id, req.event_date, req.event_time)
        demand, capacity, capacity_basis = self._resolve_demand(req, req.venue_id, req.event_type.value)
        effective_attendance = demand["effective_attendance"]

        engine = NetworkMonteCarloEngine(mod_graph, n_simulations=500)
        raw = engine.run(
            total_attendance=effective_attendance,
            event_type=req.event_type.value,
            weather_factor=weather,
            transit_factor=transit,
        )
        metrics = compute_full_metrics(
            network_result=raw,
            attendance=effective_attendance,
            venue_capacity=capacity,
            weather_data=self._weather_payload(weather, weather_prov),
            revenue_params=self._revenue_params(req),
            event_type=req.event_type.value,
            demand_model=demand,
        )
        mod_result = {
            "success": True,
            "venue_id": req.venue_id,
            "venue_name": self.venues[req.venue_id]["name"],
            "parameters": {
                "attendance": effective_attendance,
                "attendance_requested": req.attendance,
                "event_type": req.event_type.value,
                "weather_factor": weather,
                "transit_factor": transit,
                "n_simulations": 500,
                "service_rate_tier": tier,
                "avg_ticket_price": getattr(req, "avg_ticket_price", None),
                "venue_capacity": capacity,
                "capacity_basis": capacity_basis,
            },
            "simulation": raw,
            "metrics": metrics,
            "data_provenance": {
                "weather": weather_prov,
                "transit": transit_prov,
                "service_rates": _service_rate_provenance(tier),
                "pricing_demand": demand.get("provenance"),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "computation_time_ms": 0,
            "engine_version": raw.get("engine_version", "network_v1"),
        }

        return self._build_compare_response(base_result, mod_result)

    def _build_compare_response(self, base: dict, modified: dict) -> dict:
        """Build a comparison response from two simulation results."""
        delta = {}
        base_sim = base["simulation"]
        mod_sim = modified["simulation"]
        for key in base_sim:
            if isinstance(base_sim.get(key), (int, float)) and isinstance(mod_sim.get(key), (int, float)):
                delta[key] = mod_sim[key] - base_sim[key]
        delta["hes"] = _canonical_hes(modified) - _canonical_hes(base)

        # Identify improved/degraded nodes
        improved = []
        degraded = []
        base_nodes = base_sim.get("node_metrics", {})
        mod_nodes = mod_sim.get("node_metrics", {})
        for nid in base_nodes:
            if nid in mod_nodes:
                bw = base_nodes[nid].get("wait_mean", 0)
                mw = mod_nodes[nid].get("wait_mean", 0)
                if mw < bw - 0.5:
                    improved.append(nid)
                elif mw > bw + 0.5:
                    degraded.append(nid)

        # Summary
        wait_delta = delta.get("wait_mean", 0)
        hes_delta = delta.get("hes", delta.get("hes_mean", 0))
        if wait_delta < -1:
            summary = f"Modified scenario reduces average wait by {abs(wait_delta):.1f} min."
        elif wait_delta > 1:
            summary = f"Modified scenario increases average wait by {wait_delta:.1f} min."
        else:
            summary = "Modified scenario has negligible impact on wait times."
        if abs(hes_delta) > 2:
            summary += f" HES {'improves' if hes_delta > 0 else 'degrades'} by {abs(hes_delta):.1f} points."

        return {
            "success": True,
            "base": base,
            "modified": modified,
            "delta": delta,
            "improved_nodes": improved,
            "degraded_nodes": degraded,
            "summary": summary,
        }

    # ── Stress Tests ────────────────────────────────────────────────────────────

    def run_stress_tests(self, req: StressTestRequest) -> dict:
        """Run predefined stress scenarios against a baseline."""
        from api.models import SimulationRequest, StressTestType

        all_tests = [
            StressTestType.gate_failure,
            StressTestType.extreme_heat,
            StressTestType.transit_shutdown,
            StressTestType.staffing_cut,
            StressTestType.mass_egress,
            StressTestType.compound,
        ]
        tests_to_run = req.tests or all_tests

        tier = _tier_value(getattr(req, "service_rate_tier", "operational"))
        weather, weather_prov = self._resolve_weather(req.weather_factor, req.event_date, None)
        transit, transit_prov = self._resolve_traffic(req.transit_factor, req.venue_id, req.event_date, None)

        # Run baseline
        base_req = SimulationRequest(
            venue_id=req.venue_id,
            attendance=req.attendance,
            event_type=req.event_type,
            weather_factor=weather,
            transit_factor=transit,
            avg_ticket_price=req.avg_ticket_price,
            n_simulations=500,
            service_rate_tier=tier,
        )
        base_result = self.run_simulation(base_req)
        base_hes = _canonical_hes(base_result)

        graph = self._get_graph(req.venue_id, tier=tier)
        capacity, capacity_basis = self._get_event_capacity(req.venue_id, req.event_type.value)

        stress_results = {}
        worst_degradation = -1.0
        worst_test = ""

        for test_type in tests_to_run:
            test_weather = weather
            test_transit = transit
            test_graph_changes: dict = {"disable_nodes": [], "modify_servers": {}}
            test_attendance = req.attendance
            temporal_result = None

            if test_type == StressTestType.gate_failure:
                # Disable 1 random gate + its security checkpoint
                entry_ids = graph.get_entry_node_ids()
                if entry_ids:
                    victim = entry_ids[random.randint(0, len(entry_ids) - 1)]
                    test_graph_changes["disable_nodes"].append(victim)
                    sec_id = victim.replace("gate_", "security_")
                    test_graph_changes["disable_nodes"].append(sec_id)

            elif test_type == StressTestType.extreme_heat:
                test_weather = 0.95
                # Reduce service rates by 15% via server count reduction
                for nd in graph.nodes:
                    if nd.node_type in ("security", "concession"):
                        new_s = max(1, int(nd.num_servers * 0.85))
                        test_graph_changes["modify_servers"][nd.node_id] = new_s

            elif test_type == StressTestType.transit_shutdown:
                test_transit = 0.1

            elif test_type == StressTestType.staffing_cut:
                # Reduce all server counts by 40%
                for nd in graph.nodes:
                    if nd.node_type in ("security", "ticketing", "concession", "restroom"):
                        new_s = max(1, int(nd.num_servers * 0.6))
                        test_graph_changes["modify_servers"][nd.node_id] = new_s

            elif test_type == StressTestType.mass_egress:
                # This is a high-load egress stress pass on the existing exit
                # topology, so it gets an additional temporal pass later.
                test_attendance = min(req.attendance, 100000)

            elif test_type == StressTestType.compound:
                # Combine gate_failure + extreme_heat at 50% severity
                entry_ids = graph.get_entry_node_ids()
                if entry_ids:
                    victim = entry_ids[0]
                    test_graph_changes["disable_nodes"].append(victim)
                    sec_id = victim.replace("gate_", "security_")
                    test_graph_changes["disable_nodes"].append(sec_id)
                test_weather = 0.7
                for nd in graph.nodes:
                    if nd.node_type in ("security", "concession"):
                        new_s = max(1, int(nd.num_servers * 0.9))
                        test_graph_changes["modify_servers"][nd.node_id] = new_s

            # Build modified graph and run
            has_changes = (
                test_graph_changes["disable_nodes"]
                or test_graph_changes["modify_servers"]
            )
            if has_changes:
                mod_graph = graph.modify(test_graph_changes)
            else:
                mod_graph = graph

            demand = resolve_ticket_demand(
                requested_attendance=test_attendance,
                venue_capacity=capacity,
                event_type=req.event_type.value,
                avg_ticket_price=req.avg_ticket_price,
                capacity_basis=capacity_basis,
            )
            effective_attendance = demand["effective_attendance"]
            engine = NetworkMonteCarloEngine(mod_graph, n_simulations=500)
            raw = engine.run(
                total_attendance=effective_attendance,
                event_type=req.event_type.value,
                weather_factor=test_weather,
                transit_factor=test_transit,
            )
            if test_type == StressTestType.mass_egress:
                temporal_result = TemporalSimulator(mod_graph, dt_minutes=2.0).run_fast(
                    total_attendance=effective_attendance,
                    event_type=req.event_type.value,
                    event_duration_hours=3.0,
                    weather_factor=test_weather,
                    transit_factor=test_transit,
                )
            metrics = compute_full_metrics(
                network_result=raw,
                temporal_result=temporal_result,
                attendance=effective_attendance,
                venue_capacity=capacity,
                weather_data=self._weather_payload(test_weather, None),
                revenue_params=self._revenue_params(req),
                event_type=req.event_type.value,
                demand_model=demand,
            )

            # Compute delta from baseline
            test_delta = {}
            for key in base_result["simulation"]:
                bv = base_result["simulation"].get(key)
                mv = raw.get(key)
                if isinstance(bv, (int, float)) and isinstance(mv, (int, float)):
                    test_delta[key] = mv - bv
            if temporal_result is not None:
                test_delta["wait_mean"] = (
                    metrics.get("temporal", {}).get("peak_wait", raw.get("wait_mean", 0.0))
                    - base_result["metrics"]["operational"]["wait_time"]["mean"]
                )

            test_hes = _canonical_hes({"simulation": raw, "metrics": metrics})
            test_delta["hes"] = test_hes - base_hes
            degradation = base_hes - test_hes
            if degradation > worst_degradation:
                worst_degradation = degradation
                worst_test = test_type.value

            stress_results[test_type.value] = {
                "simulation": raw,
                "metrics": metrics,
                "delta": test_delta,
                "parameters": {
                    "weather_factor": test_weather,
                    "transit_factor": test_transit,
                    "attendance_requested": test_attendance,
                    "attendance": effective_attendance,
                    "avg_ticket_price": getattr(req, "avg_ticket_price", None),
                    "graph_changes": test_graph_changes if has_changes else None,
                },
            }
            if temporal_result is not None:
                stress_results[test_type.value]["temporal"] = temporal_result.to_dict()

        # Resilience score semantics:
        #   Each row's bar shows  100 − max(0, base_hes − stressed_hes)   (i.e. "HES preserved,
        #   capped by 100"). The aggregate score is defined the same way so the panel is
        #   internally consistent: aggregate == minimum of the per-row bars.
        #
        # The previous formulation normalised the worst degradation by base_hes, which
        # collapses to 0 whenever worst_degradation ≥ base_hes — a real and common case
        # (e.g. staffing cut pushing HES to zero). That silently masked the real number.
        actual_degradation = max(0.0, worst_degradation)
        resilience = max(0.0, min(100.0, 100.0 - actual_degradation))

        return {
            "success": True,
            "venue_id": req.venue_id,
            "venue_name": self.venues[req.venue_id]["name"],
            "base_scenario": {
                "simulation": base_result["simulation"],
                "metrics": base_result["metrics"],
            },
            "stress_results": stress_results,
            "most_vulnerable": worst_test or "none",
            "resilience_score": round(resilience, 1),
            "data_provenance": {
                "weather": weather_prov,
                "transit": transit_prov,
                "service_rates": _service_rate_provenance(tier),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        }

    # ── Venue Info ──────────────────────────────────────────────────────────────

    def get_venue_list(self) -> dict:
        """Return list of available venues with summary info."""
        venues = []
        for vid, v in self.venues.items():
            cap = v["capacity"]
            venues.append({
                "venue_id": vid,
                "name": v["name"],
                "capacity": cap.get("max") or cap.get("football") or cap.get("concert") or cap.get("app_py_value"),
                "event_types": v.get("event_types", []),
                "confidence": cap.get("confidence", "unknown"),
                "location": v.get("location", {}),
            })
        return {"success": True, "venues": venues}

    def get_venue_detail(self, venue_id: str) -> dict:
        """Return full venue profile plus graph topology summary."""
        if venue_id not in self.venues:
            raise ValueError(f"Unknown venue: {venue_id}")

        graph = self._get_graph(venue_id, tier="operational")

        # Count node types
        type_counts: dict[str, int] = {}
        for nd in graph.nodes:
            type_counts[nd.node_type] = type_counts.get(nd.node_type, 0) + 1

        return {
            "success": True,
            "venue": self.venues[venue_id],
            "graph_summary": {
                "total_nodes": len(graph.nodes),
                "entry_nodes": len(graph.get_entry_node_ids()),
                "exit_nodes": len(graph.get_exit_node_ids()),
                "node_types": type_counts,
                "total_edges": len(graph.edges),
            },
        }

    def get_specs(self) -> dict:
        """Return the technical specification of the Vane simulation engine."""
        return {
            "success": True,
            "engine": {
                "name": "Vane Queueing Network Simulator",
                "version": "1.0",
                "methodology": {
                    "core": "Jackson queueing network with Erlang-C service model",
                    "corrections": "Allen-Cunneen correction for general service time distributions",
                    "stochastic": "Monte Carlo simulation with correlated weather-transit noise",
                    "temporal": "Time-stepped fluid flow model with Beta-distribution arrival profiles",
                    "pedestrian": "Fruin Level of Service (HCM6) for corridor density assessment",
                },
                "capabilities": [
                    "Steady-state queueing network analysis (1000 Monte Carlo trials per scenario)",
                    "Time-resolved event simulation (arrival -> event -> egress, FAST and DEEP modes; DEEP adds arrival-phase uncertainty checkpoints)",
                    "Scenario comparison and what-if analysis",
                    "Automated stress testing (gate failure, extreme heat, transit shutdown, staffing cuts)",
                    "Safety risk scoring (crush risk, flow capacity, evacuation time)",
                    "Revenue impact estimation (concession, merchandise, future ticket sales)",
                    "Human Experience Score (multi-factor: wait, density, temperature, service, access)",
                ],
                "limitations": [
                    "Fixed routing -- does not model dynamic crowd rerouting within a single simulation",
                    "No agent-based pedestrian dynamics -- uses aggregate flow model",
                    "Venue infrastructure data at medium-low confidence for most venues (no building plans)",
                    "No empirical validation against real venue measurements yet",
                    "Jackson network assumes independence between queues -- may underestimate cascading effects",
                ],
                "data_sources": [
                    "Open-Meteo ERA5 reanalysis (2022-2024) for weather",
                    "Nevada DOT HPMS AADT for traffic corridors",
                    "RTC Southern Nevada transit ridership data",
                    "DHS/Fruin/HCM6 published service rate benchmarks",
                    "Operational service-rate defaults informed by public event reporting",
                    "LVCVA visitor statistics",
                ],
                "venues_available": len(self.venues),
                "location_focus": "Las Vegas, Nevada",
            },
        }
