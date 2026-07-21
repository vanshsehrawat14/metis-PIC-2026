"""
tests/test_metrics.py — Tests for the metrics computation layer.

Tests FruinLOS, RevenueImpact, SafetyRiskScore, EnhancedHES, and
compute_full_metrics.
"""

import math
import sys
import os
from types import SimpleNamespace

# Ensure project root is on path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest

from simulation.demand import resolve_ticket_demand
from simulation.metrics import (
    FruinLOS,
    RevenueImpact,
    SafetyRiskScore,
    EnhancedHES,
    compute_full_metrics,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  FruinLOS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFruinLOS:

    def test_fruin_grades_correct(self):
        """Verify all Fruin thresholds produce correct grades."""
        assert FruinLOS.grade(0.2) == "A"
        assert FruinLOS.grade(0.35) == "B"
        assert FruinLOS.grade(0.5) == "C"
        assert FruinLOS.grade(0.8) == "D"
        assert FruinLOS.grade(1.5) == "E"
        assert FruinLOS.grade(2.5) == "F"

    def test_fruin_grade_boundary_values(self):
        """Test exact boundary values."""
        assert FruinLOS.grade(0.0) == "A"
        assert FruinLOS.grade(0.30) == "A"
        assert FruinLOS.grade(0.31) == "B"
        assert FruinLOS.grade(0.43) == "C"
        assert FruinLOS.grade(0.72) == "D"
        assert FruinLOS.grade(1.08) == "E"
        assert FruinLOS.grade(2.17) == "F"

    def test_fruin_walking_speed_decreases_with_density(self):
        """Walking speed should monotonically decrease."""
        speeds = [FruinLOS.walking_speed(d) for d in [0.1, 0.5, 1.0, 1.5, 2.0]]
        assert all(speeds[i] >= speeds[i + 1] for i in range(len(speeds) - 1))

    def test_fruin_walking_speed_zero_at_crush(self):
        """At LOS F density, no movement."""
        assert FruinLOS.walking_speed(2.17) == 0.0
        assert FruinLOS.walking_speed(3.0) == 0.0

    def test_fruin_walking_speed_free_flow(self):
        """At zero density, speed should equal free flow speed."""
        speed = FruinLOS.walking_speed(0.0)
        assert abs(speed - FruinLOS.FREE_FLOW_SPEED_MS) < 0.01

    def test_fruin_walking_speed_with_modifier(self):
        """Stairway modifier should reduce speed."""
        normal = FruinLOS.walking_speed(0.3)
        stairs = FruinLOS.walking_speed(0.3, modifier="stairway")
        assert stairs < normal
        assert abs(stairs - normal * 0.6) < 0.01

    def test_fruin_crush_detection(self):
        assert not FruinLOS.is_dangerous(0.5)
        assert FruinLOS.is_dangerous(1.2)
        assert FruinLOS.is_dangerous(2.5)

    def test_fruin_grade_description_all_grades(self):
        """All grades should have descriptions."""
        for grade in "ABCDEF":
            desc = FruinLOS.grade_description(grade)
            assert desc != "Unknown"
            assert len(desc) > 10

    def test_fruin_grade_description_unknown(self):
        assert FruinLOS.grade_description("Z") == "Unknown"


# ═══════════════════════════════════════════════════════════════════════════════
#  RevenueImpact
# ═══════════════════════════════════════════════════════════════════════════════

class TestRevenueImpact:

    def test_revenue_loss_increases_with_wait(self):
        """Longer concession waits should lose more revenue."""
        ri = RevenueImpact(65000)
        r5 = ri.concession_revenue_impact(5.0, 45000)
        r15 = ri.concession_revenue_impact(15.0, 45000)
        assert r15["lost_revenue"] > r5["lost_revenue"]

    def test_revenue_loss_floor(self):
        """Even at extreme waits, revenue doesn't go below 20% of base."""
        ri = RevenueImpact(65000)
        r60 = ri.concession_revenue_impact(60.0, 45000)
        assert r60["actual_revenue"] >= r60["base_revenue"] * 0.19  # slight tolerance

    def test_revenue_zero_wait_no_loss(self):
        """Zero wait should produce zero loss."""
        ri = RevenueImpact(65000)
        r0 = ri.concession_revenue_impact(0.0, 45000)
        assert r0["lost_revenue"] == 0.0
        assert r0["loss_percentage"] == 0.0

    def test_revenue_output_keys(self):
        """Verify all expected keys are present."""
        ri = RevenueImpact(65000)
        result = ri.concession_revenue_impact(10.0, 30000)
        expected_keys = {
            "base_revenue", "actual_revenue", "lost_revenue", "loss_percentage",
            "wait_minutes", "recommendation", "spend_tier_multiplier",
            "effective_concession_per_capita",
        }
        assert set(result.keys()) == expected_keys

    def test_merchandise_impact_low_density(self):
        """Low corridor density should have minimal merch impact."""
        ri = RevenueImpact(65000)
        result = ri.merchandise_revenue_impact(0.2, 45000)
        assert result["loss_percentage"] < 1.0

    def test_merchandise_impact_high_density(self):
        """High density should significantly reduce merch revenue."""
        ri = RevenueImpact(65000)
        result = ri.merchandise_revenue_impact(1.5, 45000)
        assert result["loss_percentage"] > 20.0

    def test_future_ticket_positive_hes(self):
        """High HES should produce positive future revenue delta."""
        ri = RevenueImpact(65000)
        result = ri.future_ticket_impact(90.0, 45000)
        assert result["future_revenue_impact"] > 0

    def test_future_ticket_negative_hes(self):
        """Low HES should produce negative future revenue delta."""
        ri = RevenueImpact(65000)
        result = ri.future_ticket_impact(40.0, 45000)
        assert result["future_revenue_impact"] < 0

    def test_total_impact_excludes_future_upside_from_downside(self):
        """Positive future lift should be reported separately, not counted as downside."""
        ri = RevenueImpact(65000)
        result = ri.total_impact(0.0, 0.2, 90.0, 45000)
        assert result["total_current_event_loss"] == 0.0
        assert result["future_demand_upside"] > 0
        assert result["total_economic_impact"] == 0.0
        assert "upside" in result["summary"].lower()

    def test_total_impact_all_sections(self):
        """Total impact should contain all three revenue streams."""
        ri = RevenueImpact(65000)
        result = ri.total_impact(10.0, 0.5, 65.0, 45000)
        assert "concession" in result
        assert "merchandise" in result
        assert "future_tickets" in result
        assert "total_current_event_loss" in result
        assert "total_economic_impact" in result
        assert "summary" in result

    def test_custom_params(self):
        """Custom parameters should override defaults."""
        ri = RevenueImpact(65000, {"concession_per_capita": 50.0})
        r = ri.concession_revenue_impact(0.0, 10000)
        expected = 10000 * 0.62 * 50.0
        assert abs(r["base_revenue"] - expected) < 0.01

    def test_spend_tier_scales_secondary_spend_with_ticket_price(self):
        """Higher face value should raise effective per-capita via sublinear τ."""
        base = RevenueImpact(65000, {"average_ticket_price": 95.0})
        hi = RevenueImpact(65000, {"average_ticket_price": 190.0})
        tb = base._spend_tier_multiplier()
        th = hi._spend_tier_multiplier()
        assert tb == 1.0
        assert th > 1.0
        cb = base.concession_revenue_impact(0.0, 10000)
        ch = hi.concession_revenue_impact(0.0, 10000)
        assert ch["base_revenue"] > cb["base_revenue"]
        assert "provenance" in base.total_impact(0.0, 0.15, 70.0, 10000)

    def test_event_type_adjusts_revenue_benchmarks(self):
        """Theater vs NFL should shift NAC midpoints differently (category priors)."""
        theater = RevenueImpact(65000, event_type="theater")
        nfl = RevenueImpact(65000, event_type="nfl")
        assert theater.params["concession_per_capita"] < nfl.params["concession_per_capita"]
        prov = theater.total_impact(0.0, 0.3, 70.0, 20000)["provenance"]
        assert prov["event_type_context"]["event_type"] == "theater"


# ═══════════════════════════════════════════════════════════════════════════════
#  SafetyRiskScore
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyRiskScore:

    def test_safety_low_at_normal_operations(self):
        srs = SafetyRiskScore(30000, 65000)
        # Required throughput for 30-min planning clearance: 30000 * 2 = 60000 pph.
        # Provide 250000 to be comfortably above.
        result = srs.compute(max_density_per_m2=0.3, total_exit_throughput_per_hour=250000)
        assert result["risk_level"] == "LOW"

    def test_safety_critical_at_crush(self):
        srs = SafetyRiskScore(65000, 65000)
        result = srs.compute(max_density_per_m2=2.5, total_exit_throughput_per_hour=10000)
        assert result["risk_level"] in ("HIGH", "CRITICAL")

    def test_crush_risk_sigmoid_shape(self):
        """Crush risk should be ~0.5 at density 1.5."""
        srs = SafetyRiskScore(30000, 65000)
        risk = srs.crush_risk(1.5)
        assert 0.45 < risk < 0.55  # sigmoid center at 1.5

    def test_crush_risk_low_at_low_density(self):
        srs = SafetyRiskScore(30000, 65000)
        risk = srs.crush_risk(0.3)
        assert risk < 0.01

    def test_crush_risk_high_at_crush(self):
        srs = SafetyRiskScore(30000, 65000)
        risk = srs.crush_risk(2.5)
        assert risk > 0.95

    def test_flow_capacity_risk_adequate(self):
        """With enough exit throughput, flow risk should be zero."""
        srs = SafetyRiskScore(10000, 65000)
        # Required: 10000 * 2.0 = 20000 pph (30-min planning target). Provide 25000.
        risk = srs.flow_capacity_risk(25000)
        assert risk == 0.0

    def test_flow_capacity_risk_inadequate(self):
        """With insufficient exit throughput, flow risk should be positive."""
        srs = SafetyRiskScore(10000, 65000)
        # Required: 20000 pph. Provide 10000 (half).
        risk = srs.flow_capacity_risk(10000)
        assert abs(risk - 0.5) < 0.01

    def test_evacuation_time_risk(self):
        """Evacuation time at the 30-min planning target should give zero risk."""
        srs = SafetyRiskScore(10000, 65000)
        # If throughput = 10000 * 60/30 = 20000 pph,
        # evac_time = 10000 / (20000/60) = 30 min → risk = 1.0
        risk = srs.evacuation_time_risk(20000)
        assert risk == 0.0

    def test_evacuation_time_risk_ramps_after_target(self):
        srs = SafetyRiskScore(10000, 65000)
        # 45 min evacuation -> (45 - 30) / 60 = 0.25
        risk = srs.evacuation_time_risk(13333.3333333)
        assert abs(risk - 0.25) < 0.02

    def test_srs_output_keys(self):
        srs = SafetyRiskScore(30000, 65000)
        result = srs.compute(0.5, 50000)
        expected = {
            "srs", "srs_crush", "srs_flow", "srs_evac",
            "crush_risk", "flow_risk", "evac_risk",
            "risk_level", "estimated_evac_minutes", "estimated_evacuation_min",
            "nfpa_target_minutes", "planning_target_minutes",
            "dominant_risk", "recommendation", "details",
        }
        assert expected.issubset(result.keys())

    def test_srs_dominant_risk_identified(self):
        """When crush is the only high risk, it should be dominant."""
        srs = SafetyRiskScore(10000, 65000)
        # Very high density but adequate exit capacity
        result = srs.compute(max_density_per_m2=2.5, total_exit_throughput_per_hour=500000)
        assert result["dominant_risk"] == "crush"


# ═══════════════════════════════════════════════════════════════════════════════
#  EnhancedHES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnhancedHES:

    def test_hes_perfect_conditions(self):
        hes = EnhancedHES()
        result = hes.compute(mean_wait=3, worst_fruin="A", heat_index_f=72,
                             concession_wait=2, entry_wait=5, exit_time=10)
        assert result["hes"] >= 85
        assert result["grade"] in ("Excellent", "Good")

    def test_hes_terrible_conditions(self):
        hes = EnhancedHES()
        result = hes.compute(mean_wait=35, worst_fruin="E", heat_index_f=112,
                             concession_wait=20, entry_wait=30, exit_time=40)
        # Multiplicative weighted model floors around ~35 even with all factors bad
        assert result["hes"] < 50
        assert result["grade"] in ("Poor", "Critical")

    def test_hes_dominant_detractor_identified(self):
        hes = EnhancedHES()
        # Good everything except terrible wait
        result = hes.compute(mean_wait=30, worst_fruin="A", heat_index_f=72,
                             concession_wait=2, entry_wait=5, exit_time=10)
        assert result["dominant_detractor"] == "wait"

    def test_hes_density_detractor(self):
        hes = EnhancedHES()
        # Good everything except terrible density
        result = hes.compute(mean_wait=3, worst_fruin="F", heat_index_f=72,
                             concession_wait=2, entry_wait=5, exit_time=10)
        assert result["dominant_detractor"] == "density"

    def test_hes_temperature_detractor(self):
        hes = EnhancedHES()
        # Good everything except extreme heat
        result = hes.compute(mean_wait=3, worst_fruin="A", heat_index_f=120,
                             concession_wait=2, entry_wait=5, exit_time=10)
        assert result["dominant_detractor"] == "temperature"

    def test_wait_factor_grace_period(self):
        """Waits under 5 min should have factor near 1.0."""
        assert abs(EnhancedHES.wait_factor(0.0) - 1.0) < 0.01
        assert abs(EnhancedHES.wait_factor(5.0) - 1.0) < 0.01

    def test_wait_factor_decreases(self):
        """Wait factor should decrease with longer waits."""
        f10 = EnhancedHES.wait_factor(10)
        f20 = EnhancedHES.wait_factor(20)
        f30 = EnhancedHES.wait_factor(30)
        assert f10 > f20 > f30

    def test_density_factor_values(self):
        assert EnhancedHES.density_factor("A") == 1.0
        assert EnhancedHES.density_factor("F") == 0.05

    def test_temperature_factor_comfort_zone(self):
        """60-80F should all be 1.0."""
        assert EnhancedHES.temperature_factor(60.0) == 1.0
        assert EnhancedHES.temperature_factor(70.0) == 1.0
        assert EnhancedHES.temperature_factor(80.0) == 1.0

    def test_temperature_factor_heat_stress(self):
        """Above 80F should decrease."""
        f95 = EnhancedHES.temperature_factor(95.0)
        f105 = EnhancedHES.temperature_factor(105.0)
        f115 = EnhancedHES.temperature_factor(115.0)
        assert f95 > f105 > f115
        assert f115 > 0.1  # should not go below floor at 115

    def test_temperature_factor_cold(self):
        """Below 60F should decrease."""
        f50 = EnhancedHES.temperature_factor(50.0)
        f30 = EnhancedHES.temperature_factor(30.0)
        assert f50 > f30

    def test_service_factor_grace_period(self):
        """Under 3 min concession wait should be 1.0."""
        assert abs(EnhancedHES.service_factor(2.0) - 1.0) < 0.01

    def test_access_factor_good_conditions(self):
        """Short entry/exit should produce high access factor."""
        f = EnhancedHES.access_factor(5.0, 10.0)
        assert f > 0.9

    def test_hes_output_keys(self):
        hes = EnhancedHES()
        result = hes.compute(10, "B")
        assert "hes" in result
        assert "grade" in result
        assert "factors" in result
        assert "dominant_detractor" in result
        assert "recommendation" in result
        assert set(result["factors"].keys()) == {"wait", "density", "temperature", "service", "access"}

    def test_hes_grades(self):
        """Verify grade boundaries."""
        hes = EnhancedHES()
        # Build conditions that map to known HES ranges
        r_excellent = hes.compute(2, "A", 72, 1, 3, 5)
        assert r_excellent["grade"] == "Excellent"

    def test_hes_custom_weights(self):
        """Custom weights should change the score."""
        default = EnhancedHES()
        custom = EnhancedHES(weights={"wait": 0.8, "density": 0.05,
                                       "temperature": 0.05, "service": 0.05, "access": 0.05})
        # With terrible wait, higher wait weight = lower HES
        r_default = default.compute(25, "A", 72, 2, 5, 10)
        r_custom = custom.compute(25, "A", 72, 2, 5, 10)
        assert r_custom["hes"] < r_default["hes"]


# ═══════════════════════════════════════════════════════════════════════════════
#  compute_full_metrics
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeFullMetrics:

    @staticmethod
    def _make_network_result(**overrides):
        """Build a mock NetworkMonteCarloEngine.run() output."""
        base = {
            "wait_mean": 8.0,
            "wait_p10": 4.0,
            "wait_p90": 14.0,
            "wait_std": 3.0,
            "congestion_mean": 0.2,
            "congestion_p10": 0.05,
            "congestion_p90": 0.4,
            "cong_mean": 0.2,
            "cong_p10": 0.05,
            "cong_p90": 0.4,
            "breakdown_mean": 0.05,
            "brk_mean": 0.05,
            "brk_p10": 0.0,
            "brk_p90": 0.1,
            "hes_mean": 75.0,
            "hes_p10": 60.0,
            "hes_p90": 88.0,
            "util_mean": 0.65,
            "node_metrics": {
                "gate_0": {"wait_mean": 2.0, "util_mean": 0.5, "fruin_los_mode": None},
                "security_0": {"wait_mean": 12.0, "util_mean": 0.85, "fruin_los_mode": None},
                "concourse_main": {"wait_mean": 0.1, "util_mean": 0.1, "fruin_los_mode": "B"},
                "concession_0": {"wait_mean": 6.0, "util_mean": 0.7, "fruin_los_mode": None},
                "seating_main": {"wait_mean": 0.0, "util_mean": 0.05, "fruin_los_mode": None},
                "exit_corridor": {"wait_mean": 0.1, "util_mean": 0.1, "fruin_los_mode": "A"},
                "exit_0": {"wait_mean": 0.5, "util_mean": 0.3, "fruin_los_mode": None},
            },
            "bottleneck_node": "security_0",
            "bottleneck_frequency": 0.92,
            "unstable_node_pct": 0.0,
            "worst_fruin_los": "B",
            "network_throughput_mean": 25000.0,
            "total_process_time_mean": 108.0,
            "n_simulations": 1000,
            "n_nodes": 7,
            "computation_time_ms": 1500.0,
            "engine_version": "network_v1",
        }
        base.update(overrides)
        return base

    def test_returns_all_sections(self):
        """Full metrics output should have all required top-level keys."""
        nr = self._make_network_result()
        result = compute_full_metrics(nr, attendance=45000, venue_capacity=65000)
        assert "operational" in result
        assert "safety" in result
        assert "experience" in result
        assert "revenue" in result
        assert "fruin" in result
        assert "recommendations" in result

    def test_temporal_section_present_when_provided(self):
        """Temporal section should appear when temporal_result is given."""
        nr = self._make_network_result()

        class MockTemporal:
            peak_congestion_time = 120.0
            peak_congestion_wait = 18.0
            congestion_duration_minutes = 45.0
            total_egress_time_minutes = 55.0

        result = compute_full_metrics(nr, temporal_result=MockTemporal(),
                                       attendance=45000, venue_capacity=65000)
        assert "temporal" in result
        assert result["temporal"]["peak_wait"] == 18.0

    def test_temporal_section_absent_when_not_provided(self):
        nr = self._make_network_result()
        result = compute_full_metrics(nr, attendance=45000, venue_capacity=65000)
        assert "temporal" not in result

    def test_operational_structure(self):
        nr = self._make_network_result()
        result = compute_full_metrics(nr, attendance=45000, venue_capacity=65000)
        op = result["operational"]
        assert "wait_time" in op
        assert op["wait_time"]["mean"] == 8.0
        assert op["bottleneck"]["node"] == "security_0"
        assert op["throughput"]["venue_total"] == 25000.0

    def test_recommendations_sorted_by_priority(self):
        """Recommendations should be sorted by priority number."""
        nr = self._make_network_result(wait_mean=25.0)
        result = compute_full_metrics(nr, attendance=45000, venue_capacity=65000)
        recs = result["recommendations"]
        if len(recs) > 1:
            priorities = [r["priority"] for r in recs]
            assert priorities == sorted(priorities)

    def test_recommendations_max_five(self):
        """Should never return more than 5 recommendations."""
        nr = self._make_network_result(wait_mean=30.0, worst_fruin_los="E")
        result = compute_full_metrics(nr, attendance=60000, venue_capacity=65000)
        assert len(result["recommendations"]) <= 5

    def test_weather_data_affects_experience(self):
        """Hot weather should lower HES."""
        nr = self._make_network_result()
        cool = compute_full_metrics(nr, attendance=45000, venue_capacity=65000,
                                     weather_data={"heat_index_f": 72})
        hot = compute_full_metrics(nr, attendance=45000, venue_capacity=65000,
                                    weather_data={"heat_index_f": 110})
        assert hot["experience"]["hes"] < cool["experience"]["hes"]

    def test_fruin_distribution(self):
        nr = self._make_network_result()
        result = compute_full_metrics(nr, attendance=45000, venue_capacity=65000)
        fruin = result["fruin"]
        assert "worst_grade" in fruin
        assert "grade_distribution" in fruin
        assert set(fruin["grade_distribution"].keys()) == {"A", "B", "C", "D", "E", "F"}

    def test_safety_uses_exit_capacity_when_available(self):
        nr = self._make_network_result(
            network_throughput_mean=8000.0,
            node_metrics={
                "corridor_main": {
                    "node_type": "corridor",
                    "wait_mean": 0.1,
                    "util_mean": 0.1,
                    "fruin_los_mode": "B",
                },
                "exit_a": {
                    "node_type": "exit",
                    "wait_mean": 0.2,
                    "util_mean": 0.2,
                    "fruin_los_mode": None,
                    "num_servers": 6,
                    "service_rate_per_hr": 8000.0,
                },
                "exit_b": {
                    "node_type": "exit",
                    "wait_mean": 0.2,
                    "util_mean": 0.2,
                    "fruin_los_mode": None,
                    "num_servers": 6,
                    "service_rate_per_hr": 8000.0,
                },
            },
        )
        result = compute_full_metrics(nr, attendance=45000, venue_capacity=65000)
        assert result["safety"]["estimated_evac_minutes"] < 30.0
        assert result["safety"]["risk_level"] in ("LOW", "MODERATE")

    def test_temporal_event_phase_overrides_concession_wait_for_revenue(self):
        nr = self._make_network_result(
            node_metrics={
                "gate_0": {"node_type": "gate", "wait_mean": 2.0, "util_mean": 0.5, "fruin_los_mode": None},
                "concourse_main": {"node_type": "corridor", "wait_mean": 0.1, "util_mean": 0.1, "fruin_los_mode": "B"},
                "concession_0": {"node_type": "concession", "wait_mean": 0.0, "util_mean": 0.2, "fruin_los_mode": None},
                "exit_0": {
                    "node_type": "exit",
                    "wait_mean": 0.2,
                    "util_mean": 0.3,
                    "fruin_los_mode": None,
                    "num_servers": 4,
                    "service_rate_per_hr": 9000.0,
                },
            },
        )

        event_step = SimpleNamespace(
            phase="event",
            node_metrics={
                "concession_0": SimpleNamespace(arrival_rate=1500.0, expected_wait_minutes=12.0, density_per_m2=None),
                "concourse_main": SimpleNamespace(arrival_rate=0.0, expected_wait_minutes=0.0, density_per_m2=1.4),
            },
        )
        temporal = SimpleNamespace(
            time_steps=[event_step],
            peak_congestion_time=120.0,
            peak_congestion_wait=12.0,
            congestion_duration_minutes=40.0,
            total_egress_time_minutes=28.0,
        )

        result = compute_full_metrics(
            nr,
            temporal_result=temporal,
            attendance=45000,
            venue_capacity=65000,
        )
        assert result["revenue"]["concession"]["wait_minutes"] == 12.0
        assert result["revenue"]["merchandise"]["corridor_density"] == 1.4

    def test_temporal_peak_safety_can_dominate_reported_srs(self):
        nr = self._make_network_result(
            network_throughput_mean=200000.0,
            node_metrics={
                "concourse_main": {
                    "node_type": "corridor",
                    "wait_mean": 0.1,
                    "util_mean": 0.1,
                    "fruin_los_mode": "B",
                },
                "exit_a": {
                    "node_type": "exit",
                    "wait_mean": 0.2,
                    "util_mean": 0.2,
                    "fruin_los_mode": None,
                    "num_servers": 6,
                    "service_rate_per_hr": 8000.0,
                },
                "exit_b": {
                    "node_type": "exit",
                    "wait_mean": 0.2,
                    "util_mean": 0.2,
                    "fruin_los_mode": None,
                    "num_servers": 6,
                    "service_rate_per_hr": 8000.0,
                },
            },
        )
        temporal = SimpleNamespace(
            time_steps=[],
            peak_congestion_time=120.0,
            peak_congestion_wait=12.0,
            congestion_duration_minutes=40.0,
            total_egress_time_minutes=28.0,
            max_safety_risk=0.82,
            max_safety_risk_time=148.0,
        )

        result = compute_full_metrics(
            nr,
            temporal_result=temporal,
            attendance=45000,
            venue_capacity=65000,
        )
        assert result["safety"]["structural_srs"] < 0.1
        assert result["safety"]["temporal_peak_srs"] == 0.82
        assert result["safety"]["srs"] == 0.82
        assert result["safety"]["risk_level"] == "HIGH"

    def test_demand_and_targeted_ops_recommendations_surface_when_price_binds(self):
        nr = self._make_network_result(
            node_metrics={
                "security_0": {
                    "node_type": "security",
                    "wait_mean": 15.0,
                    "util_mean": 0.94,
                    "util_p90": 0.98,
                    "fruin_los_mode": None,
                    "num_servers": 4,
                    "service_rate_per_hr": 900.0,
                },
                "concession_0": {
                    "node_type": "concession",
                    "wait_mean": 8.0,
                    "util_mean": 0.91,
                    "util_p90": 0.95,
                    "fruin_los_mode": None,
                    "num_servers": 3,
                    "service_rate_per_hr": 180.0,
                },
                "concourse_main": {
                    "node_type": "corridor",
                    "wait_mean": 0.1,
                    "util_mean": 0.1,
                    "fruin_los_mode": "B",
                },
                "exit_0": {
                    "node_type": "exit",
                    "wait_mean": 0.2,
                    "util_mean": 0.3,
                    "fruin_los_mode": None,
                    "num_servers": 6,
                    "service_rate_per_hr": 6000.0,
                },
            },
            bottleneck_node="security_0",
        )
        demand = resolve_ticket_demand(
            requested_attendance=65000,
            venue_capacity=65000,
            event_type="concert",
            avg_ticket_price=10000,
            capacity_basis="concert_with_floor",
        )
        result = compute_full_metrics(
            nr,
            attendance=demand["effective_attendance"],
            venue_capacity=65000,
            demand_model=demand,
        )
        assert result["demand"]["price_is_binding"] is True
        categories = {rec["category"] for rec in result["recommendations"]}
        assert "pricing" in categories
        assert "security" in categories or "staffing" in categories
