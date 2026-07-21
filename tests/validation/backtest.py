"""
tests/validation/backtest.py — Historical back-test against documented Las Vegas events.

Compares Vane queueing network predictions against documented outcomes from
three real Las Vegas events with publicly reported crowd management outcomes:

  1. Super Bowl LVIII — Allegiant Stadium — 2024-02-11
  2. UFC 306 — Sphere Las Vegas — 2024-09-14
  3. CES 2024 — Las Vegas Convention Center — 2024-01-10

Run with:
    python -m tests.validation.backtest

Outputs:
    tests/validation/backtest_report.json  (machine-readable full report)
    stdout                                  (summary table)

Methodology:
    - NetworkMonteCarloEngine: 1,000-trial MC over the queueing network
    - TemporalSimulator.run_fast(): deterministic time-stepping through full lifecycle
    - compute_full_metrics(): operational/safety/revenue/fruin aggregation
    - Comparison: documented wait range vs. model P10–P90 interval

Limitations (honest):
    - No empirical queue measurement data from any LV venue.
    - Gate counts for most venues are LOW-MEDIUM confidence estimates.
    - Enhanced Super Bowl security protocols are not modeled (raises service time).
    - "Documented" figures are media/after-action report ranges, not instrument readings.
    - Model confidence overall: LOW-MEDIUM.

Sources for documented outcomes:
    Super Bowl LVIII: LVMPD After-Action Report; NFL Operations; ESPN; Las Vegas Review-Journal
    UFC 306: ESPN; MMA Fighting; attendee social media; Sphere operations commentary
    CES 2024: CTA official reports; LVCVA; Las Vegas Review-Journal
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data.sources.service_rates import ServiceRateDatabase
from simulation.network import VenueGraph, NetworkMonteCarloEngine
from simulation.temporal import TemporalSimulator
from simulation.metrics import compute_full_metrics

# ── Venue loader ─────────────────────────────────────────────────────────────

_VENUES_PATH = _PROJECT_ROOT / "data" / "venues" / "vegas_venues.json"


def _load_venues() -> dict:
    with open(_VENUES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {v["venue_id"]: v for v in data["venues"]}


def _get_venue_capacity(venue_data: dict) -> int:
    cap = venue_data["capacity"]
    for key in ("max", "football", "mma", "concert", "daily_peak", "app_py_value"):
        if cap.get(key):
            return int(cap[key])
    # fallback: first numeric value found
    for v in cap.values():
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return 10_000


# ═══════════════════════════════════════════════════════════════════════════════
#  Event definitions
# ═══════════════════════════════════════════════════════════════════════════════

EVENTS = [
    {
        # ── Super Bowl LVIII ──────────────────────────────────────────────────
        "name": "Super Bowl LVIII",
        "venue_id": "allegiant_stadium",
        "attendance": 61_629,           # Official NFL figure
        "event_type": "nfl",
        "event_date": "2024-02-11",
        "event_time": "15:30",          # 3:30 PM PT kickoff
        "weather_factor": 0.15,         # February LV: ~60°F, clear, mild
        "transit_factor": 0.4,          # Heavy event traffic; transit augmented for SB
        "event_duration_hours": 4.5,    # Super Bowl runs ~4-4.5 hours
        "arrival_window_hours": 3.0,    # Gates open 3h pre-kickoff for Super Bowl
        # ── Documented outcomes ───────────────────────────────────────────────
        "documented": {
            "source": (
                "LVMPD After-Action Report; NFL Operations Report; "
                "Las Vegas Review-Journal; ESPN coverage 2024-02-11"
            ),
            "reported_wait_min": 30,    # minutes
            "reported_wait_max": 45,    # minutes
            "reported_issues": (
                "Significant congestion at south gates; VIP entry delays; "
                "some attendees queued 45+ minutes at secondary screening checkpoints."
            ),
            "documented_egress_time_min": 35,   # minutes
            "documented_egress_time_max": 45,
            "notes": (
                "Enhanced Super Bowl-level security (far more rigorous than standard NFL). "
                "~115,000 additional people in surrounding corridor (non-ticket holders). "
                "Clear weather; no weather-driven service degradation."
            ),
        },
        # ── Known modeling gaps ───────────────────────────────────────────────
        "modeling_gaps": [
            "Super Bowl security protocol is ~2× more thorough than standard NFL — "
            "model uses standard NFL service rates (under-predicts wait).",
            "Surrounding 115k non-ticket crowd compresses vehicle/pedestrian access "
            "to gates — not modeled; likely explains longer tail in real waits.",
            "VIP/club entry is parallel fast lane — keeps average down vs. general admission.",
        ],
    },
    {
        # ── UFC 306 — The Sphere ─────────────────────────────────────────────
        "name": "UFC 306 at The Sphere",
        "venue_id": "sphere_las_vegas",
        "attendance": 18_506,           # Reported attendance
        "event_type": "boxing_mma",
        "event_date": "2024-09-14",
        "event_time": "16:00",          # Main card ~10 PM; gates open ~4 PM
        "weather_factor": 0.65,         # September LV: ~100°F, outdoor queuing
        "transit_factor": 0.5,          # Venetian Expo area, moderate transit
        "event_duration_hours": 5.0,    # UFC events run long (undercard + main)
        "arrival_window_hours": 2.0,    # Standard combat sports window
        # ── Documented outcomes ───────────────────────────────────────────────
        "documented": {
            "source": (
                "ESPN; MMA Fighting; MMA media pool; attendee social media reports; "
                "Sphere venue operational commentary (inaugural event)"
            ),
            "reported_wait_min": 15,
            "reported_wait_max": 25,
            "reported_issues": (
                "Some confusion with new venue navigation and entry flow; "
                "but operations generally praised as efficient for inaugural event. "
                "Heat was a significant attendee concern during exterior queuing."
            ),
            "documented_egress_time_min": None,  # Not documented
            "documented_egress_time_max": None,
            "notes": (
                "First major sporting event at The Sphere (opened Sept 2023). "
                "Capacity 18,600 — near-full house. Enhanced security for inaugural event. "
                "Venetian/Palazzo area infrastructure supported access. "
                "Unique circular entry geometry not fully captured in model topology."
            ),
        },
        "modeling_gaps": [
            "Sphere gate count is low-confidence estimate (not publicly documented). "
            "Model may over- or under-estimate entry throughput.",
            "Unique circular entry geometry and Venetian casino integration "
            "differ from standard arena topology in model.",
            "Inaugural event: staff learning curve not modeled (adds variance).",
            "Heat stress (100°F) degrades outdoor queuing comfort — weather_factor=0.65 "
            "captures service degradation but not attendee patience/behavior change.",
        ],
    },
    {
        # ── CES 2024 — Las Vegas Convention Center ───────────────────────────
        "name": "CES 2024 (Peak Day)",
        "venue_id": "las_vegas_convention_center",
        "attendance": 40_000,           # Daily peak (total 135k+ over 4 days)
        "event_type": "convention",
        "event_date": "2024-01-10",     # Mid-show peak day (Wed Jan 10)
        "event_time": "09:00",          # Registration opens 9 AM
        "weather_factor": 0.1,          # January LV: ~55°F, comfortable
        "transit_factor": 0.45,         # Monorail + shuttles; Strip corridor congested
        "event_duration_hours": 8.0,    # Convention floor open 9 AM–6 PM
        "arrival_window_hours": 3.0,    # Convention arrivals spread over morning
        # ── Documented outcomes ───────────────────────────────────────────────
        "documented": {
            "source": (
                "Consumer Technology Association (CTA) official reports; "
                "LVCVA attendance data; Las Vegas Review-Journal CES 2024 coverage"
            ),
            "reported_wait_min": 10,
            "reported_wait_max": 20,
            "reported_issues": (
                "West Hall to North Hall transit congestion; "
                "food court overcrowding at lunch; "
                "registration surge at 9–10 AM."
            ),
            "documented_egress_time_min": None,  # Convention egress is gradual; not documented
            "documented_egress_time_max": None,
            "notes": (
                "Convention pattern: morning surge at registration, "
                "sustained lunch-hour congestion at concessions/food, "
                "gradual afternoon taper. "
                "Registration desks are the primary bottleneck. "
                "LVCC has ~200 entry points across multiple halls — "
                "model topology aggregates these into gate nodes."
            ),
        },
        "modeling_gaps": [
            "Convention registration desks function differently from stadium gates — "
            "badge scanning/printing adds service time not in standard 'ticketing' rates.",
            "LVCC has 200+ entry points across West/Central/North halls; "
            "model aggregates into a single gate/security topology.",
            "Convention attendees self-select arrival times heavily; "
            "Beta-distribution arrival curve may not capture the registration surge shape.",
            "Lunch-hour concession surge is a distinct second peak not in arrival model.",
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Accuracy assessment helper
# ═══════════════════════════════════════════════════════════════════════════════

def _assess_accuracy(
    predicted_p10: float,
    predicted_p90: float,
    documented_min: float,
    documented_max: float,
    within_range: bool,
) -> str:
    """
    Classify model accuracy against documented outcomes.

    We consider four tiers:
    - Strong match:  predicted interval overlaps documented range AND
                     both midpoints within 30% of each other.
    - Reasonable:    predicted interval overlaps documented range OR
                     predicted midpoint is within 50% of documented midpoint.
    - Poor match:    predicted interval does not overlap and midpoints >50% apart.
    - Insufficient data: documented range is missing.
    """
    if documented_min is None or documented_max is None:
        return "Insufficient data"

    doc_mid = (documented_min + documented_max) / 2.0
    pred_mid = (predicted_p10 + predicted_p90) / 2.0

    if doc_mid > 0:
        pct_error = abs(pred_mid - doc_mid) / doc_mid
    else:
        pct_error = 0.0

    if within_range and pct_error <= 0.30:
        return "Strong match"
    elif within_range or pct_error <= 0.50:
        return "Reasonable"
    else:
        return "Poor match"


def _intervals_overlap(
    pred_p10: float, pred_p90: float, doc_min: float, doc_max: float
) -> bool:
    """True if [pred_p10, pred_p90] and [doc_min, doc_max] share any overlap."""
    return pred_p10 <= doc_max and doc_min <= pred_p90


def _peak_congestion_time_str(temporal_result, arrival_window_hours: float) -> str:
    """Convert peak congestion time (minutes from window start) to a relative label."""
    if temporal_result is None:
        return "N/A"
    t = temporal_result.peak_congestion_time
    window_end = arrival_window_hours * 60.0
    if t <= window_end:
        mins_before = window_end - t
        return f"T-{mins_before:.0f}min (arrival phase)"
    else:
        mins_after = t - window_end
        return f"T+{mins_after:.0f}min (in-event)"


# ═══════════════════════════════════════════════════════════════════════════════
#  Per-event simulation runner
# ═══════════════════════════════════════════════════════════════════════════════

def run_event_backtest(
    event: dict,
    venues: dict,
    service_db: ServiceRateDatabase,
) -> dict:
    """Run full backtest for a single event. Returns validation record."""
    name = event["name"]
    vid = event["venue_id"]
    print(f"\n{'-'*68}")
    print(f"  {name}")
    print(f"{'-'*68}")

    # ── Build graph ───────────────────────────────────────────────────────────
    if vid not in venues:
        return {
            "event_name": name,
            "error": f"Venue '{vid}' not found in vegas_venues.json",
            "model_accuracy_assessment": "Insufficient data",
        }

    venue_data = venues[vid]
    venue_capacity = _get_venue_capacity(venue_data)
    print(f"  Venue:      {venue_data['name']}")
    print(f"  Capacity:   {venue_capacity:,}")
    print(f"  Attendance: {event['attendance']:,}  "
          f"({event['attendance']/venue_capacity*100:.1f}% fill)")

    t_graph = time.perf_counter()
    graph = VenueGraph.from_venue_profile(venue_data, service_db)
    print(f"  Graph:      {len(graph.nodes)} nodes built in "
          f"{(time.perf_counter()-t_graph)*1000:.0f}ms")

    # ── Monte Carlo network simulation ────────────────────────────────────────
    print(f"  Running NetworkMonteCarloEngine (1,000 trials)...")
    mc_engine = NetworkMonteCarloEngine(graph, n_simulations=1000)
    t_mc = time.perf_counter()
    network_result = mc_engine.run(
        total_attendance=event["attendance"],
        event_type=event["event_type"],
        weather_factor=event["weather_factor"],
        transit_factor=event["transit_factor"],
        arrival_window_hours=event.get("arrival_window_hours", 2.0),
    )
    mc_ms = (time.perf_counter() - t_mc) * 1000
    print(f"  MC done in {mc_ms:.0f}ms - "
          f"wait_mean={network_result['wait_mean']:.1f}min  "
          f"P10={network_result['wait_p10']:.1f}  P90={network_result['wait_p90']:.1f}")

    # ── Temporal simulation ───────────────────────────────────────────────────
    print(f"  Running TemporalSimulator (FAST mode)...")
    temporal_sim = TemporalSimulator(graph, dt_minutes=2.0)
    t_temp = time.perf_counter()
    try:
        temporal_result = temporal_sim.run_fast(
            total_attendance=event["attendance"],
            event_type=event["event_type"],
            event_duration_hours=event["event_duration_hours"],
            weather_factor=event["weather_factor"],
            transit_factor=event["transit_factor"],
        )
        temp_ms = (time.perf_counter() - t_temp) * 1000
        temp_dict = temporal_result.to_dict()
        print(f"  Temporal done in {temp_ms:.0f}ms - "
              f"peak_cong={temporal_result.peak_congestion_wait:.1f}min  "
              f"egress={temporal_result.total_egress_time_minutes:.0f}min")
    except Exception as exc:
        print(f"  WARNING: Temporal simulation failed: {exc}")
        temporal_result = None
        temp_dict = None
        temp_ms = 0.0

    # ── Full metrics ──────────────────────────────────────────────────────────
    weather_data = {
        "heat_index_f": 85.0 + event["weather_factor"] * 50.0,  # rough proxy
        "weather_severity": event["weather_factor"],
    }
    full = compute_full_metrics(
        network_result=network_result,
        temporal_result=temp_dict,
        attendance=event["attendance"],
        venue_capacity=venue_capacity,
        weather_data=weather_data,
        event_type=event["event_type"],
    )

    # ── Extract comparison metrics ────────────────────────────────────────────
    doc = event["documented"]
    doc_min = doc.get("reported_wait_min")
    doc_max = doc.get("reported_wait_max")

    # MC steady-state values
    mc_p10 = network_result["wait_p10"]
    mc_p90 = network_result["wait_p90"]
    pred_mean = network_result["wait_mean"]

    # Temporal: compute arrival-rate-weighted mean wait during arrival phase.
    # This represents the expected wait for a randomly selected attendee, which
    # corresponds to the documented "average wait" figures (30-45 min, etc.).
    # peak_congestion_wait is the worst 2-minute window — not what most people
    # experience, and not what after-action reports typically cite.
    temp_peak = None
    temp_arrival_mean = None
    if temporal_result is not None:
        temp_peak = temporal_result.peak_congestion_wait
        arrival_steps = [s for s in temporal_result.time_steps if s.phase == "arrival"]
        total_arr = sum(s.arrival_rate_total for s in arrival_steps)
        if total_arr > 0:
            temp_arrival_mean = (
                sum(s.mean_wait_minutes * s.arrival_rate_total for s in arrival_steps) / total_arr
            )
        else:
            temp_arrival_mean = 0.0

    # Primary comparison: MC P10-P90 (steady-state average arrival rate matches
    # documented "average attendee" experience better than temporal peak/mean).
    # Temporal models queue build-up during the peak minute; documented figures
    # cite the typical experience of a randomly-selected attendee.
    pred_p10 = mc_p10
    pred_p90 = mc_p90
    primary_method = "steady-state MC (operational rates)"

    overlap = _intervals_overlap(pred_p10, pred_p90, doc_min, doc_max) \
        if (doc_min is not None and doc_max is not None) else None

    accuracy = _assess_accuracy(pred_p10, pred_p90, doc_min, doc_max, overlap or False)

    bottleneck = network_result.get("bottleneck_node", "unknown")
    bn_freq = network_result.get("bottleneck_frequency", 0.0)

    # ── Egress comparison ─────────────────────────────────────────────────────
    pred_egress = temporal_result.total_egress_time_minutes if temporal_result else None
    doc_egress_min = doc.get("documented_egress_time_min")
    doc_egress_max = doc.get("documented_egress_time_max")

    # ── Qualitative notes ─────────────────────────────────────────────────────
    doc_mid = (doc_min + doc_max) / 2 if (doc_min is not None and doc_max is not None) else None
    primary_val = pred_mean
    direction = ""
    if doc_mid is not None:
        if overlap:
            direction = (f"[{primary_method}] Predicted P10-P90 interval overlaps the documented range.")
        elif primary_val < doc_min:
            direction = (f"[{primary_method}] Model UNDER-PREDICTS by "
                         f"{doc_min - primary_val:.1f}-{doc_max - primary_val:.1f} min.")
        elif primary_val > doc_max:
            direction = (f"[{primary_method}] Model OVER-PREDICTS by "
                         f"{primary_val - doc_max:.1f}-{primary_val - doc_min:.1f} min.")

    comparison_notes = (
        f"{direction} "
        + "Known modeling gaps: "
        + " | ".join(event["modeling_gaps"])
    ).strip()

    srs_level = full.get("safety", {}).get("risk_level", "N/A")
    hes = full.get("experience", {}).get("hes", network_result.get("hes_mean", 0.0))
    peak_cong_str = _peak_congestion_time_str(temporal_result, event.get("arrival_window_hours", 2.0))

    result = {
        "event_name": name,
        "venue_id": vid,
        "venue_name": venue_data["name"],
        "attendance": event["attendance"],
        "venue_capacity": venue_capacity,
        "fill_pct": round(event["attendance"] / venue_capacity * 100, 1),
        "event_type": event["event_type"],
        "event_date": event["event_date"],
        "simulation_inputs": {
            "weather_factor": event["weather_factor"],
            "transit_factor": event["transit_factor"],
            "event_duration_hours": event["event_duration_hours"],
            "arrival_window_hours": event.get("arrival_window_hours", 2.0),
            "n_mc_trials": 1000,
        },
        # ── Predicted values ─────────────────────────────────────────────────
        "primary_method": primary_method,
        "predicted_temporal_arrival_mean": round(temp_arrival_mean, 2) if temp_arrival_mean is not None else None,
        "predicted_temporal_peak_wait": round(temp_peak, 2) if temp_peak is not None else None,
        "predicted_mean_wait_mc": round(pred_mean, 2),
        "predicted_wait_p10": round(pred_p10, 2),
        "predicted_wait_p90": round(pred_p90, 2),
        "mc_wait_p10": round(mc_p10, 2),
        "mc_wait_p90": round(mc_p90, 2),
        "predicted_peak_congestion_time": peak_cong_str,
        "predicted_egress_time": round(pred_egress, 1) if pred_egress is not None else None,
        "predicted_hes": round(hes, 1),
        "predicted_srs": srs_level,
        "predicted_bottleneck": bottleneck,
        "predicted_bottleneck_frequency_pct": round(bn_freq * 100, 1),
        "predicted_fruin_worst": full.get("fruin", {}).get("worst_grade", "N/A"),
        # ── Documented values ─────────────────────────────────────────────────
        "documented_wait_range": [doc_min, doc_max],
        "documented_egress_range": [doc_egress_min, doc_egress_max],
        "documented_source": doc["source"],
        "documented_issues": doc.get("reported_issues", ""),
        "documented_notes": doc.get("notes", ""),
        # ── Comparison ────────────────────────────────────────────────────────
        "within_predicted_range": bool(overlap) if overlap is not None else None,
        "comparison_notes": comparison_notes,
        "model_accuracy_assessment": accuracy,
        "known_modeling_gaps": event["modeling_gaps"],
        # ── Performance ───────────────────────────────────────────────────────
        "computation_ms": {
            "monte_carlo": round(mc_ms, 0),
            "temporal": round(temp_ms, 0),
        },
        # ── Full metrics (for reference) ─────────────────────────────────────
        "full_metrics_summary": {
            "operational": full.get("operational", {}),
            "safety_level": srs_level,
            "hes": hes,
            "fruin_worst": full.get("fruin", {}).get("worst_grade"),
            "top_recommendations": [
                r.get("action", "") for r in
                full.get("recommendations", [])[:3]
            ],
        },
    }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Summary table printer
# ═══════════════════════════════════════════════════════════════════════════════

def _accuracy_color(assessment: str) -> str:
    """ASCII indicator for accuracy tier."""
    return {
        "Strong match": "[STRONG]",
        "Reasonable": "[REASONABLE]",
        "Poor match": "[POOR]",
        "Insufficient data": "[NO DATA]",
    }.get(assessment, "[?]")


def print_summary_table(records: list[dict]) -> None:
    col_w = 30
    print("\n")
    print("=" * 90)
    print("  Vane BACK-TEST RESULTS -- Las Vegas Historical Events")
    print("=" * 90)

    header = (
        f"{'Event':<{col_w}}  "
        f"{'Predicted (P10-P90)':<22}  "
        f"{'Documented':<16}  "
        f"{'Overlap?':<8}  "
        f"{'Assessment':<14}"
    )
    print(header)
    print("-" * 90)

    for r in records:
        name = r["event_name"][:col_w - 1]
        pred = f"P10-P90: {r['mc_wait_p10']:.0f}-{r['mc_wait_p90']:.0f} min"
        dw = r["documented_wait_range"]
        if dw[0] is not None:
            doc = f"{dw[0]}-{dw[1]} min"
        else:
            doc = "N/A"
        overlap = "YES" if r.get("within_predicted_range") else ("N/A" if r.get("within_predicted_range") is None else "NO")
        assessment = r["model_accuracy_assessment"]
        print(
            f"{name:<{col_w}}  "
            f"{pred:<22}  "
            f"{doc:<16}  "
            f"{overlap:<8}  "
            f"{assessment:<14}"
        )

    print("-" * 90)
    print()

    for r in records:
        print(f"  {r['event_name']}")
        print(f"    MC P10-P90 (primary):    {r['mc_wait_p10']:.1f}-{r['mc_wait_p90']:.1f} min  [accuracy basis]")
        print(f"    MC mean wait:            {r['predicted_mean_wait_mc']:.1f} min")
        if r.get("predicted_temporal_arrival_mean") is not None:
            mean_t = r["predicted_temporal_arrival_mean"]
            peak_t = r.get("predicted_temporal_peak_wait")
            print(f"    Temporal arrival-mean:   {mean_t:.1f} min  [queue build-up context]")
            if peak_t is not None:
                print(f"    Temporal peak (worst):   {peak_t:.1f} min")
        if r["documented_wait_range"][0] is not None:
            print(f"    Documented range:        {r['documented_wait_range'][0]}-{r['documented_wait_range'][1]} min")
        print(f"    Bottleneck:              {r['predicted_bottleneck']} "
              f"({r['predicted_bottleneck_frequency_pct']:.0f}% of trials)")
        print(f"    HES:                     {r['predicted_hes']:.1f} / 100")
        print(f"    Safety level:            {r['predicted_srs']}")
        print(f"    Fruin worst LOS:         {r.get('predicted_fruin_worst', 'N/A')}")
        if r["predicted_egress_time"] is not None:
            print(f"    Predicted egress time:   {r['predicted_egress_time']:.0f} min")
            de = r["documented_egress_range"]
            if de[0] is not None:
                print(f"    Documented egress:       {de[0]}-{de[1]} min")
        print(f"    Assessment:              {r['model_accuracy_assessment']} "
              f"{_accuracy_color(r['model_accuracy_assessment'])}")
        print()

    print("=" * 90)
    print("  MODEL CONFIDENCE: LOW-MEDIUM (theory-grounded queueing network;")
    print("  no empirical validation from measured LV venue queue data)")
    print("=" * 90)
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("=" * 68)
    print("  Vane Historical Back-Test")
    print("  Las Vegas Events 2024 -- Model Validation")
    print("=" * 68)

    venues = _load_venues()
    service_db = ServiceRateDatabase()

    records = []
    t_total = time.perf_counter()

    for event in EVENTS:
        record = run_event_backtest(event, venues, service_db)
        records.append(record)

    total_ms = (time.perf_counter() - t_total) * 1000
    print(f"\n  All events completed in {total_ms:.0f}ms total.")

    # ── Save JSON report ──────────────────────────────────────────────────────
    report = {
        "meta": {
            "description": "Vane queueing network back-test against documented LV events",
            "model_version": "network_v1",
            "model_confidence": "LOW-MEDIUM",
            "run_note": (
                "Predicted values from theory-grounded queueing network. "
                "Documented values from public sources (after-action reports, media, CTA). "
                "No instrument-measured queue data from any LV venue."
            ),
        },
        "events": records,
        "summary": {
            "n_events": len(records),
            "accuracy_counts": {
                tier: sum(1 for r in records if r.get("model_accuracy_assessment") == tier)
                for tier in ["Strong match", "Reasonable", "Poor match", "Insufficient data"]
            },
        },
    }

    report_path = Path(__file__).parent / "backtest_report.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                report,
                f,
                indent=2,
                default=lambda value: value.item() if hasattr(value, "item") else str(value),
            )
        print(f"  Report saved -> {report_path}")
    except Exception as exc:
        print(f"  Report write skipped -> {report_path} ({type(exc).__name__}: {exc})")

    # ── Print summary ─────────────────────────────────────────────────────────
    print_summary_table(records)


if __name__ == "__main__":
    main()
