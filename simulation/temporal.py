"""
simulation/temporal.py — Time-varying queueing network simulation.

Adds a temporal dimension to the queueing-network engine (simulation/network.py).
Instead of a single steady-state solve, this module steps through the full
event lifecycle — arrival, steady-state event, egress — running the network
solver at each time step with time-varying external arrival rates.

Mathematical foundations:
  - Arrival patterns: scaled Beta distribution λ(t) = N × Beta(t/T; α, β) / T
  - Egress patterns: exponential release λ_exit(t) = N_rem × κ × e^{-κt}
  - Per-time-step: reuse QueueingNetworkSolver with updated external arrivals
    (LU factorisation of (I − R^T) is invariant across time steps)
  - HES: multi-factor scoring (wait, density, weather, service quality)
  - SRS: max(crush risk, flow inadequacy, evacuation time risk)

Sources:
  Arrival profiles — Still (2014), Fruin (1993), Predtechenskii & Milinskii (1978)
  Egress decay — empirical crowd management literature
  Safety thresholds — NFPA 101 Life Safety Code, Fruin crush density thresholds
"""

from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.stats import beta as _beta_dist

from simulation.network import (
    VenueGraph,
    VenueNode,
    NodeMetrics,
    NetworkMetrics,
    QueueingNetworkSolver,
    NetworkMonteCarloEngine,
    _fruin_grade,
    _worst_los,
    _LOS_ORDER,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  ArrivalProfile
# ═══════════════════════════════════════════════════════════════════════════════

class ArrivalProfile:
    """
    Time-varying arrival rate model for venue events.

    Arrival patterns modeled as scaled Beta distribution:
      λ(t) = N × Beta(t/T; α, β) / T

    Where N = total attendance, T = arrival window duration,
    and α, β shape the arrival curve by event type.

    Empirical shape parameters from crowd management literature
    (Still, 2014; Fruin, 1993; Predtechenskii & Milinskii, 1978).
    """

    EVENT_PROFILES = {
        "nfl":        {"alpha": 2.5, "beta": 1.8, "window_hours": 2.5, "early_leave_frac": 0.08,
                       "source": "Event-class heuristic grounded in Still/Fruin crowd-arrival literature; not fit to venue scanner logs"},
        "concert":    {"alpha": 3.5, "beta": 1.5, "window_hours": 2.0, "early_leave_frac": 0.05,
                       "source": "Concert arrival heuristic grounded in crowd-management literature; sharper late-arrival assumption than sports"},
        "sports":     {"alpha": 2.5, "beta": 1.8, "window_hours": 2.0, "early_leave_frac": 0.12,
                       "source": "General sporting event pattern; moderate early departure"},
        "concert_large": {"alpha": 3.8, "beta": 1.3, "window_hours": 2.0, "early_leave_frac": 0.03,
                          "source": "Large concert/festival heuristic; very compressed late arrival"},
        "convention": {"alpha": 1.8, "beta": 2.2, "window_hours": 3.0, "early_leave_frac": 0.20,
                       "source": "Convention-style heuristic with earlier peak and longer tail; not calibrated to badge-scan logs"},
        "boxing_mma": {"alpha": 3.0, "beta": 1.5, "window_hours": 2.0, "early_leave_frac": 0.15,
                       "source": "Combat sports; late arrival (undercard), significant early departure"},
        "festival":   {"alpha": 2.0, "beta": 2.0, "window_hours": 4.0, "early_leave_frac": 0.10,
                       "source": "Multi-stage festival; symmetric spread"},
        "theater":    {"alpha": 2.8, "beta": 2.0, "window_hours": 1.5, "early_leave_frac": 0.02,
                       "source": "Theater/show; punctual arrivals, minimal early departure"},
        "default":    {"alpha": 2.5, "beta": 1.8, "window_hours": 2.0, "early_leave_frac": 0.08,
                       "source": "Generic event default"},
    }

    # Egress decay rate κ (per minute) by event type category
    _EGRESS_KAPPA = {
        "nfl": 0.02, "sports": 0.02,
        "concert": 0.03, "concert_large": 0.03,
        "convention": 0.015,
        "boxing_mma": 0.025,
        "festival": 0.018,
        "theater": 0.025,
        "default": 0.02,
    }

    def __init__(
        self,
        total_attendance: int,
        event_type: str = "default",
        arrival_window_hours: float | None = None,
        custom_alpha: float | None = None,
        custom_beta: float | None = None,
    ):
        profile = self.EVENT_PROFILES.get(event_type, self.EVENT_PROFILES["default"])
        self.total_attendance = total_attendance
        self.event_type = event_type

        self.alpha = custom_alpha if custom_alpha is not None else profile["alpha"]
        self.beta_param = custom_beta if custom_beta is not None else profile["beta"]
        self.window_hours = arrival_window_hours if arrival_window_hours is not None else profile["window_hours"]
        self.window_minutes = self.window_hours * 60.0
        self.early_leave_frac = profile["early_leave_frac"]
        self.kappa = self._EGRESS_KAPPA.get(event_type, 0.02)

    # ── Arrival ──────────────────────────────────────────────────────────────

    def arrival_rate(self, t_minutes: float) -> float:
        """
        Return arrival rate (persons/hour) at time t minutes before event start.
        t=0 is event start. t=window_minutes is the start of the arrival window.

        Convention: t is minutes *before* event start, so the arrival window
        runs from t=window_minutes down to t=0.  Internally we map to a
        normalised x ∈ [0, 1] where x = 1 − t/window_minutes (fraction of
        window elapsed).
        """
        if t_minutes < 0 or t_minutes > self.window_minutes:
            return 0.0

        x = 1.0 - t_minutes / self.window_minutes          # 0 at window start → 1 at event start
        pdf_val = _beta_dist.pdf(x, self.alpha, self.beta_param)  # density on [0,1]

        # λ(t) persons/hour = N × pdf(x) / T  (T in hours)
        rate = self.total_attendance * pdf_val / self.window_hours
        return max(rate, 0.0)

    def arrival_curve(self, dt_minutes: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        """
        Return (time_array, rate_array) for the full arrival window.
        time_array: minutes relative to event start (negative = before event).
        rate_array: persons/hour.
        """
        n_steps = max(int(round(self.window_minutes / dt_minutes)), 2)
        # time before event: from -window_minutes to 0
        times = np.linspace(-self.window_minutes, 0.0, n_steps)
        rates = np.empty(n_steps)
        for i, t in enumerate(times):
            # t is negative minutes before event; arrival_rate expects positive minutes-before-event
            rates[i] = self.arrival_rate(-t)
        return times, rates

    # ── Egress ───────────────────────────────────────────────────────────────

    def egress_rate(self, t_minutes_after_end: float, event_duration_hours: float = 3.0) -> float:
        """
        Return egress rate (persons/hour) at t minutes after event end.

        Model:
          - Early departures: uniform trickle during final 20 min of event
            λ_early = early_leave_frac × N / 20  (persons/min → ×60 for /hr)
          - Main egress: exponential release of remaining attendees
            λ_exit(t) = N_rem × κ × e^{−κt}  (per minute → ×60 for /hr)
        """
        N = self.total_attendance
        n_early = N * self.early_leave_frac

        # Early departure phase (t < 0 means before event end)
        if t_minutes_after_end < 0:
            if t_minutes_after_end >= -20.0:
                return (n_early / 20.0) * 60.0   # persons/hour
            return 0.0

        # Main egress: exponential release of remaining attendees
        n_remaining = N - n_early
        # κ is per-minute decay.  Rate in persons/min = n_remaining × κ × e^{-κt}
        rate_per_min = n_remaining * self.kappa * math.exp(-self.kappa * t_minutes_after_end)
        return rate_per_min * 60.0  # convert to persons/hour

    def egress_curve(
        self, event_duration_hours: float = 3.0, dt_minutes: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Return (time_array, rate_array) for the full egress window.
        time_array: minutes relative to event end (negative = before end for early leavers).
        Egress continues until 95% of remaining attendees have exited.
        """
        # Early leavers: -20 to 0
        # Main egress: 0 to t_95 where e^{-κ t_95} = 0.05  →  t_95 = -ln(0.05)/κ
        t_95 = -math.log(0.05) / self.kappa
        t_start = -20.0
        t_end = t_95

        n_steps = max(int(round((t_end - t_start) / dt_minutes)), 2)
        times = np.linspace(t_start, t_end, n_steps)
        rates = np.array([self.egress_rate(t, event_duration_hours) for t in times])
        return times, rates

    # ── Full event curve ─────────────────────────────────────────────────────

    def full_event_curve(
        self, event_duration_hours: float = 3.0, dt_minutes: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Complete arrival → event → egress curve.
        Time zero = start of arrival window.
        """
        # Phase 1: Arrival
        arr_times, arr_rates = self.arrival_curve(dt_minutes)
        # Shift so time zero = start of arrival window
        arr_times_shifted = arr_times + self.window_minutes  # now 0 → window_minutes

        # Phase 2: Event (background circulation)
        peak_rate = np.max(arr_rates) if len(arr_rates) > 0 else 1.0
        bg_rate = peak_rate * 0.08  # 8% of peak arrival rate
        event_minutes = event_duration_hours * 60.0
        n_event = max(int(round(event_minutes / dt_minutes)), 2)
        event_times = np.linspace(self.window_minutes, self.window_minutes + event_minutes, n_event)
        event_rates = np.full(n_event, bg_rate)

        # Phase 3: Egress
        egr_times, egr_rates = self.egress_curve(event_duration_hours, dt_minutes)
        egr_times_shifted = egr_times + self.window_minutes + event_minutes

        # Combine (drop duplicate boundary points)
        all_times = np.concatenate([arr_times_shifted, event_times[1:], egr_times_shifted[1:]])
        all_rates = np.concatenate([arr_rates, event_rates[1:], egr_rates[1:]])
        return all_times, all_rates


# ═══════════════════════════════════════════════════════════════════════════════
#  TimeStepResult / TemporalResult
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TimeStepResult:
    """Results for a single time step."""
    t_minutes: float
    phase: str
    arrival_rate_total: float
    node_metrics: dict[str, NodeMetrics]
    bottleneck_node: str
    max_wait_minutes: float
    mean_wait_minutes: float
    worst_fruin_los: str | None
    hes: float
    safety_risk_score: float
    cumulative_person_minutes_waiting: float


@dataclass
class TemporalResult:
    """Complete temporal simulation output."""
    time_steps: list[TimeStepResult]

    # Summary statistics
    peak_arrival_time: float
    peak_congestion_time: float
    peak_congestion_wait: float
    congestion_start_time: float
    congestion_end_time: float
    congestion_duration_minutes: float

    total_person_hours_waiting: float
    mean_hes_over_event: float
    min_hes: float
    min_hes_time: float
    max_safety_risk: float
    max_safety_risk_time: float

    total_egress_time_minutes: float

    node_timeseries: dict[str, dict]

    computation_time_ms: float

    def to_dict(self) -> dict:
        """Serialize for API response."""
        return {
            "peak_arrival_time": self.peak_arrival_time,
            "peak_congestion_time": self.peak_congestion_time,
            "peak_congestion_wait": self.peak_congestion_wait,
            "congestion_start_time": self.congestion_start_time,
            "congestion_end_time": self.congestion_end_time,
            "congestion_duration_minutes": self.congestion_duration_minutes,
            "total_person_hours_waiting": self.total_person_hours_waiting,
            "mean_hes_over_event": self.mean_hes_over_event,
            "min_hes": self.min_hes,
            "min_hes_time": self.min_hes_time,
            "max_safety_risk": self.max_safety_risk,
            "max_safety_risk_time": self.max_safety_risk_time,
            "total_egress_time_minutes": self.total_egress_time_minutes,
            "computation_time_ms": self.computation_time_ms,
            "n_time_steps": len(self.time_steps),
            "node_timeseries": self.node_timeseries,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  TemporalSimulator
# ═══════════════════════════════════════════════════════════════════════════════

class TemporalSimulator:
    """
    Runs the queueing network through time-varying arrival/egress patterns.

    Two modes:
    - FAST (deterministic): Single solver pass per time step. ~0.5s total.
    - DEEP (stochastic): Monte Carlo at critical time points. ~10-15s total.
    """

    def __init__(self, graph: VenueGraph, dt_minutes: float = 1.0):
        self.graph = graph
        self.dt = dt_minutes
        self.solver = QueueingNetworkSolver(graph)

        # Cache node indices by role for fast vector building
        self._entry_ids = graph.get_entry_node_ids()
        self._exit_ids = graph.get_exit_node_ids()
        self._entry_indices = [graph._node_index[eid] for eid in self._entry_ids]
        self._exit_indices = [graph._node_index[eid] for eid in self._exit_ids]
        self._n_nodes = len(graph.nodes)

        # Cache base service rates (restored after weather degradation)
        self._base_mu = np.array([nd.service_rate for nd in graph.nodes])

        # Identify node types for metrics
        self._service_mask = np.array([
            nd.node_type in ("security", "ticketing", "concession", "restroom")
            for nd in graph.nodes
        ])
        self._corridor_mask = np.array([nd.node_type == "corridor" for nd in graph.nodes])

        # For egress: build reversed routing by swapping entry/exit roles
        # and using seating as the egress source
        self._seating_indices = [
            graph._node_index[nd.node_id]
            for nd in graph.nodes if nd.node_type == "seating"
        ]
        # Concession/restroom indices for background circulation
        self._concession_indices = [
            graph._node_index[nd.node_id]
            for nd in graph.nodes if nd.node_type == "concession"
        ]
        self._restroom_indices = [
            graph._node_index[nd.node_id]
            for nd in graph.nodes if nd.node_type == "restroom"
        ]

    # ── Arrival distribution ─────────────────────────────────────────────────

    def _distribute_arrivals_to_gates(
        self,
        total_rate: float,
        gate_distribution: dict[str, float] | None = None,
    ) -> np.ndarray:
        """Convert total arrival rate to per-node external arrival vector."""
        gamma = np.zeros(self._n_nodes)
        if total_rate <= 0:
            return gamma

        n_entries = len(self._entry_indices)
        if n_entries == 0:
            return gamma

        if gate_distribution:
            for eid, idx in zip(self._entry_ids, self._entry_indices):
                frac = gate_distribution.get(eid, 1.0 / n_entries)
                gamma[idx] = total_rate * frac
        else:
            per_gate = total_rate / n_entries
            for idx in self._entry_indices:
                gamma[idx] = per_gate

        return gamma

    def _distribute_egress_to_sources(self, total_rate: float) -> np.ndarray:
        """
        For egress, people flow from seating → exit corridor → exits.
        We inject external arrivals at seating nodes (people getting up to leave).
        The existing routing seating → exit_corridor → exit gates handles flow.
        """
        gamma = np.zeros(self._n_nodes)
        if total_rate <= 0:
            return gamma

        n_seats = len(self._seating_indices)
        if n_seats == 0:
            # Fallback: inject at exit nodes
            n_exits = len(self._exit_indices)
            if n_exits == 0:
                return gamma
            per_exit = total_rate / n_exits
            for idx in self._exit_indices:
                gamma[idx] = per_exit
            return gamma

        per_seat = total_rate / n_seats
        for idx in self._seating_indices:
            gamma[idx] = per_seat
        return gamma

    def _distribute_background(self, total_rate: float) -> np.ndarray:
        """
        Background circulation during event: 60% concession, 30% restroom, 10% random.
        Inject at concourse (which routes to concession/restroom/seating).
        """
        gamma = np.zeros(self._n_nodes)
        if total_rate <= 0:
            return gamma

        # Distribute: 60% concession, 30% restroom via their source nodes
        conc_rate = total_rate * 0.60
        rest_rate = total_rate * 0.30
        other_rate = total_rate * 0.10

        n_conc = len(self._concession_indices)
        n_rest = len(self._restroom_indices)

        if n_conc > 0:
            per_conc = conc_rate / n_conc
            for idx in self._concession_indices:
                gamma[idx] = per_conc

        if n_rest > 0:
            per_rest = rest_rate / n_rest
            for idx in self._restroom_indices:
                gamma[idx] = per_rest

        # Remaining 10%: inject at seating (random movement)
        n_seats = len(self._seating_indices)
        if n_seats > 0:
            per_seat = other_rate / n_seats
            for idx in self._seating_indices:
                gamma[idx] += per_seat

        return gamma

    # ── HES computation ──────────────────────────────────────────────────────

    def _compute_hes(self, node_metrics: dict[str, NodeMetrics], weather_factor: float) -> float:
        """
        Human Experience Score for this time step.

        Base = 100
        - Wait penalty: 2 pts/min ≤ 15 min, then (W−15)^1.5 above 15 min
        - Density penalty: 10 pts per Fruin grade below C
        - Weather penalty: weather_factor × 15
        Floor 0, cap 100.
        """
        # Attendance-weighted mean wait across service nodes
        total_lam = 0.0
        weighted_wait = 0.0
        worst_los = None

        for nid, nm in node_metrics.items():
            node = self.graph.get_node(nid)
            if node.node_type in ("security", "ticketing", "concession", "restroom"):
                total_lam += nm.arrival_rate
                weighted_wait += nm.arrival_rate * nm.expected_wait_minutes
            if node.node_type == "corridor":
                worst_los = _worst_los(worst_los, nm.fruin_los)

        mean_wait = weighted_wait / total_lam if total_lam > 0 else 0.0

        # Wait penalty
        if mean_wait <= 15.0:
            wait_pen = mean_wait * 2.0
        else:
            wait_pen = 30.0 + (mean_wait - 15.0) ** 1.5

        # Density penalty: 10 pts per grade below C
        density_pen = 0.0
        if worst_los is not None:
            grade_idx = _LOS_ORDER.get(worst_los, 0)
            c_idx = _LOS_ORDER["C"]
            if grade_idx > c_idx:
                density_pen = (grade_idx - c_idx) * 10.0

        # Weather penalty
        weather_pen = weather_factor * 15.0

        hes = 100.0 - wait_pen - density_pen - weather_pen
        return max(0.0, min(100.0, hes))

    # ── Safety Risk Score ────────────────────────────────────────────────────

    def _compute_safety_risk(self, node_metrics: dict[str, NodeMetrics], total_attendance: int) -> float:
        """
        Safety Risk Score (0–1).  SRS = max(SRS_crush, SRS_flow, SRS_evac).

        SRS_crush: sigmoid on worst corridor density vs 1.5 p/m² threshold.
        SRS_flow:  ratio of attendance to total exit *capacity* (s_i × μ_i).
                   Uses capacity (not current throughput) because during arrival
                   phase exit throughput is near-zero but that's not a safety risk.
        SRS_evac:  estimated evac time above the 30-min target, ramped over the
                   following 60 minutes.
                   NFPA 101 specifies egress-system sizing, not actual evac time.
                   Real stadium evac takes 20-60 min; 30 min is a reasonable
                   planning threshold for safety concern.
        """
        # SRS_crush: sigmoid on worst corridor density
        max_density = 0.0
        for nid, nm in node_metrics.items():
            if nm.density_per_m2 is not None and nm.density_per_m2 > max_density:
                max_density = nm.density_per_m2
        srs_crush = 1.0 / (1.0 + math.exp(-(max_density - 1.5) * 4.0))

        # Exit capacity: sum of s_i × μ_i for all exit nodes (max throughput in pph)
        exit_capacity_pph = 0.0
        for nd in self.graph.nodes:
            if nd.is_exit:
                exit_capacity_pph += nd.num_servers * nd.service_rate

        # SRS_flow: zero risk when exit capacity can clear the active crowd within
        # the 30-minute planning envelope; rises linearly as capacity falls short.
        if exit_capacity_pph > 0:
            required_pph = total_attendance * 2.0  # 30-minute planning target
            srs_flow = max(0.0, 1.0 - exit_capacity_pph / required_pph) if required_pph > 0 else 0.0
        else:
            srs_flow = 1.0

        # SRS_evac: planning-target exceedance, not raw ratio-to-target
        if exit_capacity_pph > 0:
            evac_time_min = total_attendance / (exit_capacity_pph / 60.0)
        else:
            evac_time_min = 120.0
        if evac_time_min <= 30.0:
            srs_evac = 0.0
        else:
            srs_evac = min(1.0, (evac_time_min - 30.0) / 60.0)

        return max(0.0, min(1.0, max(srs_crush, srs_flow, srs_evac)))

    # ── FAST MODE ────────────────────────────────────────────────────────────

    def run_fast(
        self,
        total_attendance: int,
        event_type: str,
        event_duration_hours: float,
        weather_factor: float,
        transit_factor: float,
        gate_distribution: dict[str, float] | None = None,
    ) -> TemporalResult:
        """
        FAST MODE: Deterministic temporal simulation.

        Runs one solver pass per time step through arrival → event → egress.
        LU factorisation is reused across all time steps (routing is constant).
        """
        t0 = _time.perf_counter()

        profile = ArrivalProfile(total_attendance, event_type)
        event_minutes = event_duration_hours * 60.0

        # Apply weather degradation to service rates (static for entire sim)
        weather_degrade = 1.0 - weather_factor * 0.10
        for idx, nd in enumerate(self.graph.nodes):
            nd.service_rate = self._base_mu[idx] * max(0.5, weather_degrade)

        # Transit factor: poor transit compresses arrivals (higher peak, narrower)
        # Model: scale alpha by (1 + (1-transit) × 0.3) → higher alpha = later peak
        # Actually: poor transit means people arrive more unevenly (more variance)
        # For now: poor transit increases arrival noise but the deterministic curve
        # stays the same. Transit effect is handled in deep mode stochastic noise.

        # Phase boundaries (in minutes from start of arrival window = time zero)
        arrival_end = profile.window_minutes       # end of arrival = event start
        event_end = arrival_end + event_minutes
        # Egress: -20 min (early leavers start) to t_95
        t_95 = -math.log(0.05) / profile.kappa
        egress_end = event_end + t_95

        # Background circulation rate during event
        _, arr_rates = profile.arrival_curve(self.dt)
        peak_rate = float(np.max(arr_rates)) if len(arr_rates) > 0 else 1.0
        bg_rate = peak_rate * 0.08

        # Step through time
        dt = self.dt
        time_points = np.arange(0.0, egress_end + dt, dt)

        steps: list[TimeStepResult] = []
        cumulative_pw = 0.0  # person-minutes waiting
        on_site_attendance = 0.0

        solver = self.solver

        for t in time_points:
            arrivals_pph = 0.0
            departures_pph = 0.0
            # Determine phase and arrival rate
            if t <= arrival_end:
                phase = "arrival"
                # t is minutes from window start; arrival_rate expects minutes-before-event
                t_before_event = arrival_end - t
                rate = profile.arrival_rate(t_before_event)
                arrivals_pph = rate
                gamma = self._distribute_arrivals_to_gates(rate, gate_distribution)
            elif t <= event_end - 20.0:
                phase = "event"
                gamma = self._distribute_background(bg_rate)
                rate = bg_rate
            elif t <= event_end:
                phase = "event"
                # Early leavers starting + background
                t_after_end = t - event_end  # negative (before event end)
                early_rate = profile.egress_rate(t_after_end, event_duration_hours)
                gamma = self._distribute_background(bg_rate)
                gamma += self._distribute_egress_to_sources(early_rate)
                rate = bg_rate + early_rate
                departures_pph = early_rate
            else:
                phase = "egress"
                t_after_end = t - event_end
                rate = profile.egress_rate(t_after_end, event_duration_hours)
                gamma = self._distribute_egress_to_sources(rate)
                departures_pph = rate

            on_site_attendance = min(
                float(total_attendance),
                max(
                    0.0,
                    on_site_attendance + (arrivals_pph - departures_pph) * (dt / 60.0),
                ),
            )

            # Solve traffic equations (reuses LU factorisation)
            try:
                lambdas = solver.solve_traffic_equations(gamma)
                nm = solver.compute_node_metrics(lambdas)
            except ValueError:
                # Degenerate step (zero arrivals) — produce empty metrics
                nm = {}
                for nd in self.graph.nodes:
                    nm[nd.node_id] = NodeMetrics(
                        node_id=nd.node_id, arrival_rate=0.0, utilization=0.0,
                        prob_waiting=0.0, expected_wait_minutes=0.0,
                        expected_queue_length=0.0, throughput=0.0, is_stable=True,
                    )

            # Aggregate step metrics
            max_wait = 0.0
            total_lam = 0.0
            weighted_wait = 0.0
            queue_length_total = 0.0
            worst_los = None
            bottleneck_id = ""
            max_util = -1.0

            for nid, m in nm.items():
                if m.expected_wait_minutes > max_wait:
                    max_wait = m.expected_wait_minutes
                node = self.graph.get_node(nid)
                if node.node_type in ("security", "ticketing", "concession", "restroom"):
                    total_lam += m.arrival_rate
                    weighted_wait += m.arrival_rate * m.expected_wait_minutes
                    queue_length_total += m.expected_queue_length
                    if m.utilization > max_util:
                        max_util = m.utilization
                        bottleneck_id = nid
                worst_los = _worst_los(worst_los, m.fruin_los)

            mean_wait = weighted_wait / total_lam if total_lam > 0 else 0.0
            cumulative_pw += queue_length_total * dt  # person-minutes via ∫Lq(t)dt

            hes = self._compute_hes(nm, weather_factor)
            srs = self._compute_safety_risk(nm, int(round(on_site_attendance)))

            steps.append(TimeStepResult(
                t_minutes=t,
                phase=phase,
                arrival_rate_total=rate,
                node_metrics=nm,
                bottleneck_node=bottleneck_id,
                max_wait_minutes=max_wait,
                mean_wait_minutes=mean_wait,
                worst_fruin_los=worst_los,
                hes=hes,
                safety_risk_score=srs,
                cumulative_person_minutes_waiting=cumulative_pw,
            ))

        # Restore base service rates
        for idx, nd in enumerate(self.graph.nodes):
            nd.service_rate = self._base_mu[idx]

        # ── Compute summary statistics ───────────────────────────────────────
        result = self._build_temporal_result(steps, profile, event_duration_hours, t0)
        return result

    def _build_temporal_result(
        self,
        steps: list[TimeStepResult],
        profile: ArrivalProfile,
        event_duration_hours: float,
        t0: float,
    ) -> TemporalResult:
        """Extract summary statistics from step list."""
        if not steps:
            elapsed = (_time.perf_counter() - t0) * 1000.0
            return TemporalResult(
                time_steps=[], peak_arrival_time=0, peak_congestion_time=0,
                peak_congestion_wait=0, congestion_start_time=0, congestion_end_time=0,
                congestion_duration_minutes=0, total_person_hours_waiting=0,
                mean_hes_over_event=100, min_hes=100, min_hes_time=0,
                max_safety_risk=0, max_safety_risk_time=0,
                total_egress_time_minutes=0, node_timeseries={},
                computation_time_ms=elapsed,
            )

        # Peak arrival rate
        peak_arr_idx = max(range(len(steps)), key=lambda i: steps[i].arrival_rate_total)
        peak_arrival_time = steps[peak_arr_idx].t_minutes

        # Peak congestion (max mean_wait)
        peak_cong_idx = max(range(len(steps)), key=lambda i: steps[i].mean_wait_minutes)
        peak_congestion_time = steps[peak_cong_idx].t_minutes
        peak_congestion_wait = steps[peak_cong_idx].mean_wait_minutes

        # Congestion window (mean_wait > 10 min)
        cong_start = -1.0
        cong_end = -1.0
        for s in steps:
            if s.mean_wait_minutes > 10.0:
                if cong_start < 0:
                    cong_start = s.t_minutes
                cong_end = s.t_minutes
        if cong_start < 0:
            cong_start = 0.0
            cong_end = 0.0
        cong_duration = max(0.0, cong_end - cong_start)

        # Total person-hours waiting
        total_ph = steps[-1].cumulative_person_minutes_waiting / 60.0 if steps else 0.0

        # HES statistics
        hes_values = [s.hes for s in steps]
        mean_hes = float(np.mean(hes_values))
        min_hes_idx = min(range(len(steps)), key=lambda i: steps[i].hes)
        min_hes = steps[min_hes_idx].hes
        min_hes_time = steps[min_hes_idx].t_minutes

        # Safety risk statistics
        max_srs_idx = max(range(len(steps)), key=lambda i: steps[i].safety_risk_score)
        max_srs = steps[max_srs_idx].safety_risk_score
        max_srs_time = steps[max_srs_idx].t_minutes

        # Egress time
        event_end_t = profile.window_minutes + event_duration_hours * 60.0
        egress_steps = [s for s in steps if s.phase == "egress"]
        if egress_steps:
            total_egress = egress_steps[-1].t_minutes - event_end_t
        else:
            total_egress = 0.0

        # Node timeseries
        node_ts: dict[str, dict] = {}
        for nd in self.graph.nodes:
            nid = nd.node_id
            waits = []
            utils = []
            los_list = []
            for s in steps:
                if nid in s.node_metrics:
                    waits.append(s.node_metrics[nid].expected_wait_minutes)
                    utils.append(s.node_metrics[nid].utilization)
                    los_list.append(s.node_metrics[nid].fruin_los)
                else:
                    waits.append(0.0)
                    utils.append(0.0)
                    los_list.append(None)
            node_ts[nid] = {"wait": waits, "util": utils, "los": los_list}

        elapsed = (_time.perf_counter() - t0) * 1000.0
        return TemporalResult(
            time_steps=steps,
            peak_arrival_time=peak_arrival_time,
            peak_congestion_time=peak_congestion_time,
            peak_congestion_wait=peak_congestion_wait,
            congestion_start_time=cong_start,
            congestion_end_time=cong_end,
            congestion_duration_minutes=cong_duration,
            total_person_hours_waiting=total_ph,
            mean_hes_over_event=mean_hes,
            min_hes=min_hes,
            min_hes_time=min_hes_time,
            max_safety_risk=max_srs,
            max_safety_risk_time=max_srs_time,
            total_egress_time_minutes=total_egress,
            node_timeseries=node_ts,
            computation_time_ms=elapsed,
        )

    # ── DEEP MODE ────────────────────────────────────────────────────────────

    def run_deep(
        self,
        total_attendance: int,
        event_type: str,
        event_duration_hours: float,
        weather_factor: float,
        transit_factor: float,
        n_trials: int = 500,
        n_critical_points: int = 8,
        gate_distribution: dict[str, float] | None = None,
    ) -> dict:
        """
        DEEP MODE: Stochastic temporal simulation.

        1. Run fast mode for deterministic temporal curve.
        2. Identify critical time points.
        3. Run NetworkMonteCarloEngine only at arrival-phase critical points,
           where the steady-state snapshot approximation is most defensible.
        """
        t0 = _time.perf_counter()

        fast_result = self.run_fast(
            total_attendance, event_type, event_duration_hours,
            weather_factor, transit_factor, gate_distribution,
        )

        if not fast_result.time_steps:
            elapsed = (_time.perf_counter() - t0) * 1000.0
            return {
                "fast_result": fast_result,
                "critical_points": [],
                "uncertainty_summary": {},
                "computation_time_ms": elapsed,
            }

        # Identify critical time points
        critical_times = set()
        critical_times.add(fast_result.peak_arrival_time)
        critical_times.add(fast_result.peak_congestion_time)
        if fast_result.congestion_start_time > 0:
            critical_times.add(fast_result.congestion_start_time)
        if fast_result.congestion_end_time > 0:
            critical_times.add(fast_result.congestion_end_time)
        critical_times.add(fast_result.max_safety_risk_time)

        # Find peak egress time
        egress_steps = [s for s in fast_result.time_steps if s.phase == "egress"]
        if egress_steps:
            peak_egress = max(egress_steps, key=lambda s: s.arrival_rate_total)
            critical_times.add(peak_egress.t_minutes)

        # Fill remaining slots with evenly spaced points
        all_times = [s.t_minutes for s in fast_result.time_steps]
        t_min_val, t_max_val = min(all_times), max(all_times)
        n_remaining = max(0, n_critical_points - len(critical_times))
        if n_remaining > 0:
            spacing = np.linspace(t_min_val, t_max_val, n_remaining + 2)[1:-1]
            for sp in spacing:
                critical_times.add(float(sp))

        # Trim to n_critical_points
        critical_list = sorted(critical_times)[:n_critical_points]

        # Build MC engine
        mc_engine = NetworkMonteCarloEngine(self.graph, n_simulations=n_trials)
        profile = ArrivalProfile(total_attendance, event_type)
        arrival_end = profile.window_minutes
        event_end = arrival_end + event_duration_hours * 60.0

        critical_results = []
        modeled_times: set[float] = set()
        for cp_t in critical_list:
            # Find the fast-mode step closest to this time
            closest = min(fast_result.time_steps, key=lambda s: abs(s.t_minutes - cp_t))
            if closest.phase != "arrival":
                continue
            if closest.t_minutes in modeled_times:
                continue
            modeled_times.add(closest.t_minutes)

            # Determine arrival rate at this point for MC
            arrival_window = profile.window_hours
            if closest.arrival_rate_total > 0:
                # Use the rate from the fast mode step
                effective_rate = closest.arrival_rate_total
            else:
                effective_rate = 1.0  # minimal to avoid zero

            # Run MC with equivalent steady-state rate
            # MC engine takes total_attendance and window → rate = attendance/window
            # We want it to solve at the rate from this time step
            # So: set attendance such that attendance / window = effective_rate
            effective_attendance = int(effective_rate * arrival_window)
            effective_attendance = max(100, effective_attendance)

            mc_result = mc_engine.run(
                total_attendance=effective_attendance,
                event_type=event_type,
                weather_factor=weather_factor,
                transit_factor=transit_factor,
                gate_distribution=gate_distribution,
                arrival_window_hours=arrival_window,
            )

            critical_results.append({
                "t_minutes": closest.t_minutes,
                "phase": closest.phase,
                "monte_carlo_result": mc_result,
            })

        # Uncertainty summary from critical points
        peak_waits = [cp["monte_carlo_result"]["wait_mean"] for cp in critical_results]
        if peak_waits:
            uncertainty = {
                "peak_wait_p10": min(cp["monte_carlo_result"]["wait_p10"] for cp in critical_results),
                "peak_wait_mean": max(peak_waits),
                "peak_wait_p90": max(cp["monte_carlo_result"]["wait_p90"] for cp in critical_results),
                "egress_time_p10": fast_result.total_egress_time_minutes * 0.85,
                "egress_time_p90": fast_result.total_egress_time_minutes * 1.20,
                "coverage": "arrival_phase_monte_carlo_waits",
                "critical_points_modeled": len(critical_results),
            }
        else:
            uncertainty = {}

        elapsed = (_time.perf_counter() - t0) * 1000.0
        return {
            "fast_result": fast_result,
            "critical_points": critical_results,
            "uncertainty_summary": uncertainty,
            "computation_time_ms": elapsed,
        }

    # ── Comparison ───────────────────────────────────────────────────────────

    def compare_temporal(
        self,
        base_params: dict,
        modified_params: dict,
        graph_changes: dict | None = None,
    ) -> dict:
        """
        Run two fast-mode temporal simulations and return delta curves.
        """
        base_result = self.run_fast(**base_params)

        if graph_changes:
            mod_graph = self.graph.modify(graph_changes)
            mod_sim = TemporalSimulator(mod_graph, self.dt)
            mod_result = mod_sim.run_fast(**modified_params)
        else:
            mod_result = self.run_fast(**modified_params)

        delta = {
            "peak_wait_delta": mod_result.peak_congestion_wait - base_result.peak_congestion_wait,
            "congestion_duration_delta": mod_result.congestion_duration_minutes - base_result.congestion_duration_minutes,
            "egress_time_delta": mod_result.total_egress_time_minutes - base_result.total_egress_time_minutes,
            "hes_delta": mod_result.mean_hes_over_event - base_result.mean_hes_over_event,
            "safety_risk_delta": mod_result.max_safety_risk - base_result.max_safety_risk,
        }

        # Per-node deltas for nodes that exist in both
        node_deltas = {}
        for nid in base_result.node_timeseries:
            if nid in mod_result.node_timeseries:
                base_waits = base_result.node_timeseries[nid]["wait"]
                mod_waits = mod_result.node_timeseries[nid]["wait"]
                n = min(len(base_waits), len(mod_waits))
                if n > 0:
                    base_max = max(base_waits[:n])
                    mod_max = max(mod_waits[:n])
                    node_deltas[nid] = {
                        "peak_wait_delta": mod_max - base_max,
                        "improved": mod_max < base_max,
                    }

        return {
            "base_result": base_result,
            "modified_result": mod_result,
            "delta": delta,
            "node_deltas": node_deltas,
        }
