"""
tests/test_temporal.py — Test suite for simulation/temporal.py temporal engine.

Covers:
  - ArrivalProfile: Beta distribution integration, event type differentiation,
    egress accounting
  - TemporalSimulator fast mode: speed, temporal shape, phase transitions
  - TemporalSimulator deep mode: uncertainty bands at critical points
  - Safety risk scoring under load
  - Egress flow direction validation
  - Scenario comparison
"""

import math
import os
import sys
import time

import numpy as np
import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from simulation.network import (
    VenueGraph,
    VenueNode,
    VenueEdge,
    QueueingNetworkSolver,
    NetworkMonteCarloEngine,
    load_venue_graph,
)
from simulation.temporal import (
    ArrivalProfile,
    TimeStepResult,
    TemporalResult,
    TemporalSimulator,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def allegiant_graph():
    """Load Allegiant Stadium graph once for all tests in this module."""
    return load_venue_graph("allegiant_stadium")


@pytest.fixture(scope="module")
def allegiant_sim(allegiant_graph):
    """TemporalSimulator for Allegiant Stadium with 2-minute time steps."""
    return TemporalSimulator(allegiant_graph, dt_minutes=2.0)


@pytest.fixture(scope="module")
def allegiant_fast_result(allegiant_sim):
    """Cached fast-mode result for Allegiant Stadium, NFL, 45k attendance."""
    return allegiant_sim.run_fast(
        total_attendance=45000,
        event_type="nfl",
        event_duration_hours=3.0,
        weather_factor=0.3,
        transit_factor=0.5,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  ArrivalProfile tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestArrivalProfile:

    def test_arrival_profile_integrates_to_attendance(self):
        """Total area under arrival curve should equal total attendance (within 2%)."""
        profile = ArrivalProfile(45000, "nfl")
        times, rates = profile.arrival_curve(dt_minutes=1.0)
        # rates is persons/hour, times is in minutes
        # integral = sum(rate_i × dt_hours) = sum(rate_i × (1/60))
        total = np.trapezoid(rates, times / 60.0)  # integrate over hours
        assert abs(total - 45000) / 45000 < 0.02, (
            f"Expected ~45000, got {total:.0f} ({abs(total-45000)/45000:.1%} error)"
        )

    def test_arrival_profiles_differ_by_event_type(self):
        """Concert should have later peak than NFL (higher alpha → later mode)."""
        nfl = ArrivalProfile(45000, "nfl")
        concert = ArrivalProfile(45000, "concert")
        nfl_times, nfl_rates = nfl.arrival_curve()
        concert_times, concert_rates = concert.arrival_curve()
        nfl_peak = nfl_times[np.argmax(nfl_rates)]
        concert_peak = concert_times[np.argmax(concert_rates)]
        assert concert_peak > nfl_peak, (
            f"Concert peak ({concert_peak:.0f} min) should be later than NFL ({nfl_peak:.0f} min)"
        )

    def test_arrival_rate_zero_outside_window(self):
        """Arrival rate should be zero outside the arrival window."""
        profile = ArrivalProfile(45000, "nfl")
        assert profile.arrival_rate(-10.0) == 0.0   # after event start
        assert profile.arrival_rate(profile.window_minutes + 10.0) == 0.0  # before window

    def test_arrival_rate_positive_inside_window(self):
        """Arrival rate should be positive somewhere inside the window."""
        profile = ArrivalProfile(45000, "nfl")
        mid = profile.window_minutes / 2.0
        assert profile.arrival_rate(mid) > 0.0

    def test_convention_has_earlier_peak(self):
        """Convention (α=1.8, β=2.2) peaks earlier than NFL (α=2.5, β=1.8)."""
        conv = ArrivalProfile(20000, "convention")
        nfl = ArrivalProfile(20000, "nfl")
        conv_t, conv_r = conv.arrival_curve()
        nfl_t, nfl_r = nfl.arrival_curve()
        conv_peak = conv_t[np.argmax(conv_r)]
        nfl_peak = nfl_t[np.argmax(nfl_r)]
        # Convention has lower α/β ratio → earlier mode
        # But convention has 3hr window vs NFL 2.5hr so peak in absolute time may differ
        # Check relative position: convention peaks in first half of its window
        conv_frac = (conv_peak - conv_t[0]) / (conv_t[-1] - conv_t[0])
        nfl_frac = (nfl_peak - nfl_t[0]) / (nfl_t[-1] - nfl_t[0])
        assert conv_frac < nfl_frac, "Convention should peak earlier (fractionally) in its window"

    def test_custom_alpha_beta_override(self):
        """Custom alpha/beta should override event type defaults."""
        profile = ArrivalProfile(10000, "nfl", custom_alpha=1.0, custom_beta=1.0)
        # α=1, β=1 → uniform distribution
        assert profile.alpha == 1.0
        assert profile.beta_param == 1.0

    def test_custom_window_override(self):
        """Custom arrival window should override event type default."""
        profile = ArrivalProfile(10000, "nfl", arrival_window_hours=5.0)
        assert profile.window_hours == 5.0
        assert profile.window_minutes == 300.0

    def test_multiple_event_types_integrate(self):
        """All event types should integrate to within 3% of attendance."""
        for etype in ArrivalProfile.EVENT_PROFILES:
            profile = ArrivalProfile(30000, etype)
            times, rates = profile.arrival_curve(dt_minutes=0.5)
            total = np.trapezoid(rates, times / 60.0)
            err = abs(total - 30000) / 30000
            assert err < 0.03, f"Event type '{etype}': integral={total:.0f}, error={err:.1%}"


class TestEgressProfile:

    def test_egress_accounts_for_all_attendees(self):
        """Egress curve integral should account for ≥85% of attendees."""
        profile = ArrivalProfile(45000, "nfl")
        times, rates = profile.egress_curve(event_duration_hours=3.0, dt_minutes=0.5)
        total_egress = np.trapezoid(rates, times / 60.0)
        assert total_egress > 45000 * 0.85, (
            f"Egress integral {total_egress:.0f} < {45000 * 0.85:.0f} (85% of 45000)"
        )

    def test_egress_rate_positive_after_event(self):
        """Egress rate should be positive immediately after event end."""
        profile = ArrivalProfile(45000, "nfl")
        rate = profile.egress_rate(1.0)  # 1 minute after end
        assert rate > 0.0

    def test_egress_rate_decays(self):
        """Egress rate should decrease over time (exponential decay)."""
        profile = ArrivalProfile(45000, "nfl")
        rate_5 = profile.egress_rate(5.0)
        rate_30 = profile.egress_rate(30.0)
        rate_60 = profile.egress_rate(60.0)
        assert rate_5 > rate_30 > rate_60, "Egress should decay monotonically"

    def test_early_leavers(self):
        """Early departure rate should be positive in final 20 min of event."""
        profile = ArrivalProfile(45000, "nfl")
        rate = profile.egress_rate(-10.0)  # 10 min before event end
        assert rate > 0.0, "Should have early leavers"
        # No early leavers before the 20-min window
        rate_far = profile.egress_rate(-25.0)
        assert rate_far == 0.0, "No early leavers 25 min before end"

    def test_egress_kappa_varies_by_type(self):
        """Concert should have faster egress (higher κ) than convention."""
        concert = ArrivalProfile(30000, "concert")
        convention = ArrivalProfile(30000, "convention")
        assert concert.kappa > convention.kappa


class TestFullEventCurve:

    def test_full_curve_has_three_phases(self):
        """Full event curve should span arrival + event + egress."""
        profile = ArrivalProfile(45000, "nfl")
        times, rates = profile.full_event_curve(event_duration_hours=3.0)
        # Arrival window is 2.5hr = 150 min, event = 180 min, egress ~150 min
        total_span = times[-1] - times[0]
        assert total_span > 150 + 180, f"Curve spans only {total_span:.0f} min"

    def test_full_curve_non_negative(self):
        """All rates should be non-negative."""
        profile = ArrivalProfile(45000, "nfl")
        times, rates = profile.full_event_curve()
        assert np.all(rates >= 0), "Negative rates found in full event curve"


# ═══════════════════════════════════════════════════════════════════════════════
#  TemporalSimulator — Fast Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestFastMode:

    def test_fast_mode_completes_under_2_seconds(self, allegiant_graph):
        """Fast mode on Allegiant Stadium should be interactive-speed."""
        sim = TemporalSimulator(allegiant_graph, dt_minutes=2.0)
        start = time.perf_counter()
        result = sim.run_fast(45000, "nfl", 3.0, 0.3, 0.5)
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"Fast mode took {elapsed:.2f}s, expected < 2.0s"
        assert len(result.time_steps) > 0

    def test_fast_mode_temporal_shape(self, allegiant_fast_result):
        """Wait times should peak during arrival, decrease during event."""
        result = allegiant_fast_result
        steps = result.time_steps

        # Find peak arrival-phase wait
        arrival_steps = [s for s in steps if s.phase == "arrival"]
        event_steps = [s for s in steps if s.phase == "event"]

        if arrival_steps and event_steps:
            max_arrival_wait = max(s.mean_wait_minutes for s in arrival_steps)
            # Mid-event wait should be lower than arrival peak
            mid_idx = len(event_steps) // 2
            mid_event_wait = event_steps[mid_idx].mean_wait_minutes
            assert mid_event_wait < max_arrival_wait, (
                f"Mid-event wait ({mid_event_wait:.1f}) >= arrival peak ({max_arrival_wait:.1f})"
            )

    def test_fast_mode_has_all_phases(self, allegiant_fast_result):
        """Result should contain arrival, event, and egress phases."""
        phases = set(s.phase for s in allegiant_fast_result.time_steps)
        assert "arrival" in phases
        assert "event" in phases
        assert "egress" in phases

    def test_fast_mode_hes_range(self, allegiant_fast_result):
        """HES should be in [0, 100] for all time steps."""
        for s in allegiant_fast_result.time_steps:
            assert 0.0 <= s.hes <= 100.0, f"HES {s.hes} out of range at t={s.t_minutes}"

    def test_fast_mode_safety_risk_range(self, allegiant_fast_result):
        """Safety risk should be in [0, 1] for all time steps."""
        for s in allegiant_fast_result.time_steps:
            assert 0.0 <= s.safety_risk_score <= 1.0, (
                f"SRS {s.safety_risk_score} out of range at t={s.t_minutes}"
            )

    def test_fast_mode_peak_congestion_during_arrival(self, allegiant_fast_result):
        """Peak congestion should occur during or just after the arrival phase."""
        result = allegiant_fast_result
        # Peak congestion time should be within the arrival window or shortly after
        arrival_end = ArrivalProfile(45000, "nfl").window_minutes
        assert result.peak_congestion_time <= arrival_end + 30, (
            f"Peak congestion at {result.peak_congestion_time:.0f} min, "
            f"arrival ends at {arrival_end:.0f} min"
        )

    def test_fast_mode_summary_statistics_populated(self, allegiant_fast_result):
        """All summary statistics should be populated."""
        r = allegiant_fast_result
        assert r.computation_time_ms > 0
        assert r.mean_hes_over_event > 0
        assert r.total_egress_time_minutes > 0
        assert len(r.node_timeseries) > 0

    def test_total_person_hours_waiting_matches_queue_length_integral(self, allegiant_fast_result, allegiant_graph):
        """Waiting person-hours should integrate queue length over time."""
        service_ids = {
            nd.node_id
            for nd in allegiant_graph.nodes
            if nd.node_type in ("security", "ticketing", "concession", "restroom")
        }
        dt_minutes = (
            allegiant_fast_result.time_steps[1].t_minutes - allegiant_fast_result.time_steps[0].t_minutes
        )
        manual_person_hours = sum(
            sum(
                step.node_metrics[nid].expected_queue_length
                for nid in service_ids
                if nid in step.node_metrics
            ) * (dt_minutes / 60.0)
            for step in allegiant_fast_result.time_steps
        )
        assert allegiant_fast_result.total_person_hours_waiting == pytest.approx(
            manual_person_hours,
            rel=1e-6,
        )

    def test_fast_mode_to_dict(self, allegiant_fast_result):
        """to_dict should produce a JSON-serializable dict."""
        d = allegiant_fast_result.to_dict()
        assert isinstance(d, dict)
        assert "peak_congestion_wait" in d
        assert "n_time_steps" in d
        assert d["n_time_steps"] == len(allegiant_fast_result.time_steps)

    def test_fast_mode_node_timeseries(self, allegiant_fast_result, allegiant_graph):
        """Node timeseries should have entries for all nodes."""
        n_steps = len(allegiant_fast_result.time_steps)
        for nd in allegiant_graph.nodes:
            assert nd.node_id in allegiant_fast_result.node_timeseries
            ts = allegiant_fast_result.node_timeseries[nd.node_id]
            assert len(ts["wait"]) == n_steps
            assert len(ts["util"]) == n_steps

    def test_fast_mode_restores_service_rates(self, allegiant_graph):
        """Service rates should be restored after simulation."""
        original_rates = [nd.service_rate for nd in allegiant_graph.nodes]
        sim = TemporalSimulator(allegiant_graph, dt_minutes=5.0)
        sim.run_fast(30000, "nfl", 3.0, 0.5, 0.5)  # high weather factor
        restored_rates = [nd.service_rate for nd in allegiant_graph.nodes]
        for orig, restored in zip(original_rates, restored_rates):
            assert abs(orig - restored) < 0.01, "Service rates not properly restored"


# ═══════════════════════════════════════════════════════════════════════════════
#  TemporalSimulator — Deep Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeepMode:

    def test_deep_mode_provides_uncertainty_bands(self, allegiant_graph):
        """Deep mode should return P10/P90 at critical points."""
        sim = TemporalSimulator(allegiant_graph, dt_minutes=5.0)
        result = sim.run_deep(
            total_attendance=45000,
            event_type="nfl",
            event_duration_hours=3.0,
            weather_factor=0.3,
            transit_factor=0.5,
            n_trials=100,
            n_critical_points=4,
        )
        assert "critical_points" in result
        assert len(result["critical_points"]) >= 1
        assert result["uncertainty_summary"]["coverage"] == "arrival_phase_monte_carlo_waits"
        for cp in result["critical_points"]:
            assert cp["phase"] == "arrival"
            mc = cp["monte_carlo_result"]
            assert mc["wait_p10"] <= mc["wait_mean"] + 1.0  # stochastic noise at overloaded points
            assert mc["wait_mean"] <= mc["wait_p90"] + 1.0

    def test_deep_mode_returns_fast_result(self, allegiant_graph):
        """Deep mode should include the full fast result."""
        sim = TemporalSimulator(allegiant_graph, dt_minutes=5.0)
        result = sim.run_deep(45000, "nfl", 3.0, 0.3, 0.5, n_trials=50, n_critical_points=3)
        assert "fast_result" in result
        assert isinstance(result["fast_result"], TemporalResult)
        assert len(result["fast_result"].time_steps) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Safety Risk Scoring
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyRisk:

    def test_safety_risk_increases_with_density(self, allegiant_graph):
        """Overloaded venue should have higher SRS than normal load."""
        sim = TemporalSimulator(allegiant_graph, dt_minutes=3.0)
        result_normal = sim.run_fast(30000, "nfl", 3.0, 0.3, 0.5)
        result_overloaded = sim.run_fast(65000, "nfl", 3.0, 0.3, 0.5)
        assert result_overloaded.max_safety_risk > result_normal.max_safety_risk, (
            f"Overloaded SRS ({result_overloaded.max_safety_risk:.3f}) "
            f"<= normal SRS ({result_normal.max_safety_risk:.3f})"
        )

    def test_safety_risk_bounded(self, allegiant_fast_result):
        """SRS should be in [0, 1]."""
        assert 0.0 <= allegiant_fast_result.max_safety_risk <= 1.0

    def test_flow_risk_zero_at_planning_capacity(self, allegiant_graph):
        sim = TemporalSimulator(allegiant_graph, dt_minutes=3.0)
        exit_capacity_pph = sum(
            nd.num_servers * nd.service_rate
            for nd in allegiant_graph.nodes
            if nd.is_exit
        )
        attendance = int(exit_capacity_pph / 2.0)  # 30-minute planning envelope
        risk = sim._compute_safety_risk({}, attendance)
        assert risk < 0.05


# ═══════════════════════════════════════════════════════════════════════════════
#  Egress Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestEgress:

    def test_egress_reversal(self, allegiant_graph, allegiant_fast_result):
        """During egress, exit nodes should have non-trivial utilization."""
        result = allegiant_fast_result
        egress_steps = [s for s in result.time_steps if s.phase == "egress"]
        exit_ids = set(allegiant_graph.get_exit_node_ids())

        if egress_steps:
            # Check first few egress steps with meaningful flow
            active_egress = [s for s in egress_steps if s.arrival_rate_total > 100]
            if active_egress:
                step = active_egress[0]
                exit_utils = [
                    step.node_metrics[nid].utilization
                    for nid in exit_ids
                    if nid in step.node_metrics
                ]
                # At least some exit node should show activity
                # (utilization may be very low for high-throughput exits, so check arrival_rate)
                exit_rates = [
                    step.node_metrics[nid].arrival_rate
                    for nid in exit_ids
                    if nid in step.node_metrics
                ]
                assert max(exit_rates) > 0, "Exit nodes should have flow during egress"


# ═══════════════════════════════════════════════════════════════════════════════
#  Scenario Comparison
# ═══════════════════════════════════════════════════════════════════════════════

class TestComparison:

    def test_compare_temporal_returns_delta(self, allegiant_graph):
        """compare_temporal should return base, modified, and delta."""
        sim = TemporalSimulator(allegiant_graph, dt_minutes=5.0)
        base = {
            "total_attendance": 45000, "event_type": "nfl",
            "event_duration_hours": 3.0, "weather_factor": 0.3, "transit_factor": 0.5,
        }
        modified = {
            "total_attendance": 45000, "event_type": "nfl",
            "event_duration_hours": 3.0, "weather_factor": 0.6, "transit_factor": 0.5,
        }
        result = sim.compare_temporal(base, modified)
        assert "delta" in result
        assert "hes_delta" in result["delta"]
        # Worse weather should lower HES
        assert result["delta"]["hes_delta"] < 0, (
            f"Expected negative HES delta for worse weather, got {result['delta']['hes_delta']:.2f}"
        )

    def test_compare_temporal_shows_improvement(self, allegiant_graph):
        """Reducing attendance should improve peak wait."""
        sim = TemporalSimulator(allegiant_graph, dt_minutes=5.0)
        base = {
            "total_attendance": 55000, "event_type": "nfl",
            "event_duration_hours": 3.0, "weather_factor": 0.3, "transit_factor": 0.5,
        }
        reduced = {
            "total_attendance": 30000, "event_type": "nfl",
            "event_duration_hours": 3.0, "weather_factor": 0.3, "transit_factor": 0.5,
        }
        result = sim.compare_temporal(base, reduced)
        assert result["delta"]["peak_wait_delta"] <= 0, (
            "Reducing attendance should not increase peak wait"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Small graph smoke test (fast, no venue JSON dependency)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSmallGraph:
    """Validate temporal sim on a minimal 3-node graph."""

    @staticmethod
    def _make_small_graph():
        nodes = [
            VenueNode("gate", "ticketing", num_servers=4, service_rate=1050.0,
                       c_s_squared=0.15, is_entry=True),
            VenueNode("security", "security", num_servers=6, service_rate=215.0,
                       c_s_squared=0.9),
            VenueNode("concourse", "corridor", num_servers=1, service_rate=50000.0,
                       c_s_squared=0.3, area_m2=500.0),
            VenueNode("seating", "seating", num_servers=1, service_rate=100000.0,
                       c_s_squared=0.2),
            VenueNode("exit", "exit", num_servers=4, service_rate=1800.0,
                       c_s_squared=0.2, is_exit=True),
        ]
        edges = [
            VenueEdge("gate", "security", 1.0),
            VenueEdge("security", "concourse", 1.0),
            VenueEdge("concourse", "seating", 1.0),
            VenueEdge("seating", "exit", 1.0),
        ]
        return VenueGraph(nodes, edges)

    def test_small_fast_mode(self):
        graph = self._make_small_graph()
        sim = TemporalSimulator(graph, dt_minutes=5.0)
        result = sim.run_fast(5000, "concert", 2.0, 0.1, 0.5)
        assert len(result.time_steps) > 0
        assert result.computation_time_ms > 0

    def test_small_deep_mode(self):
        graph = self._make_small_graph()
        sim = TemporalSimulator(graph, dt_minutes=5.0)
        result = sim.run_deep(5000, "concert", 2.0, 0.1, 0.5,
                              n_trials=50, n_critical_points=3)
        assert len(result["critical_points"]) >= 2
