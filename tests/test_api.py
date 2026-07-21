"""
tests/test_api.py — API tests using FastAPI TestClient.

Tests the full stack: API -> EngineBridge -> Engine -> Metrics.
"""

import time

import pytest
from fastapi.testclient import TestClient

from api.main import app


def _wait_for_engine_ready(c: TestClient, timeout_s: float = 120.0) -> None:
    """EngineBridge loads in a background task; wait before hitting /venues etc."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = c.get("/health")
        if r.status_code == 200 and r.json().get("venues_loaded", 0) >= 15:
            return
        time.sleep(0.05)
    pytest.fail("EngineBridge did not become ready in time for API tests.")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        _wait_for_engine_ready(c)
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
#  Health & Info Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "operational"
    assert data["venues_loaded"] >= 15


def test_ready(client):
    r = client.get("/ready")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ready"
    assert "persistence_configured" in data
    assert "venues_loaded" not in data


def test_list_venues(client):
    r = client.get("/venues")
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert len(data["venues"]) >= 15
    # Each venue has required fields
    for v in data["venues"]:
        assert "venue_id" in v
        assert "name" in v
        assert "capacity" in v


def test_get_venue_detail(client):
    r = client.get("/venues/allegiant_stadium")
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert data["graph_summary"]["total_nodes"] > 0
    assert data["graph_summary"]["entry_nodes"] == 8
    assert data["graph_summary"]["exit_nodes"] == 12
    assert "node_types" in data["graph_summary"]


def test_get_venue_not_found(client):
    r = client.get("/venues/nonexistent_venue")
    assert r.status_code == 404


def test_specs(client):
    r = client.get("/specs")
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert "limitations" in data["engine"]
    assert "capabilities" in data["engine"]
    assert data["engine"]["venues_available"] >= 15


# ═══════════════════════════════════════════════════════════════════════════════
#  Simulation Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def test_simulate(client):
    r = client.post("/simulate", json={
        "venue_id": "allegiant_stadium",
        "attendance": 45000,
        "event_type": "nfl",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "n_simulations": 200,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert data["venue_id"] == "allegiant_stadium"
    assert data["venue_name"] == "Allegiant Stadium"
    # Simulation output
    assert "simulation" in data
    assert data["simulation"]["wait_mean"] >= 0
    assert data["simulation"]["n_simulations"] == 200
    # Metrics output
    assert "metrics" in data
    assert data["metrics"]["operational"]["wait_time"]["mean"] >= 0
    assert data["metrics"]["safety"]["risk_level"] in (
        "LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL"
    )
    assert data["metrics"]["experience"]["hes"] >= 0
    assert data["metrics"]["revenue"]["total_current_event_loss"] >= 0
    assert len(data["metrics"]["recommendations"]) >= 0
    # Performance
    assert data["computation_time_ms"] > 0
    assert data["engine_version"] == "network_v1"


def test_simulate_ticket_price_can_reduce_effective_attendance(client):
    r = client.post("/simulate", json={
        "venue_id": "allegiant_stadium",
        "attendance": 65000,
        "event_type": "concert",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "avg_ticket_price": 10000,
        "n_simulations": 200,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["parameters"]["attendance_requested"] == 65000
    assert data["parameters"]["attendance"] < 65000
    assert data["metrics"]["demand"]["price_is_binding"] is True


def test_simulate_rejects_out_of_range_ticket_price(client):
    r = client.post("/simulate", json={
        "venue_id": "allegiant_stadium",
        "attendance": 45000,
        "event_type": "nfl",
        "avg_ticket_price": 4,
    })
    assert r.status_code == 422


def test_allegiant_baseline_snapshot_metrics_are_sane(client):
    r = client.post("/simulate", json={
        "venue_id": "allegiant_stadium",
        "attendance": 61000,
        "event_type": "nfl",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "n_simulations": 200,
    })
    assert r.status_code == 200
    data = r.json()

    wait_mean = data["metrics"]["operational"]["wait_time"]["mean"]
    safety = data["metrics"]["safety"]
    revenue = data["metrics"]["revenue"]

    assert wait_mean < 30.0
    assert safety["risk_level"] == "LOW"
    assert safety["srs"] < 0.1
    assert revenue["total_economic_impact"] < 1000.0
    assert revenue["total_future_impact"] > 0.0
    assert revenue["interpretation"] == "modeled downside at risk, not gross event revenue"


def test_simulate_bad_venue(client):
    r = client.post("/simulate", json={
        "venue_id": "fake_venue",
        "attendance": 45000,
        "event_type": "nfl",
    })
    assert r.status_code == 400


def test_simulate_validation_errors(client):
    # Attendance too low
    r = client.post("/simulate", json={
        "venue_id": "allegiant_stadium",
        "attendance": 10,
        "event_type": "nfl",
    })
    assert r.status_code == 422

    # Bad event type
    r = client.post("/simulate", json={
        "venue_id": "allegiant_stadium",
        "attendance": 45000,
        "event_type": "badtype",
    })
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
#  Temporal Simulation Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def test_simulate_temporal_fast(client):
    r = client.post("/simulate/temporal", json={
        "venue_id": "t_mobile_arena",
        "attendance": 18000,
        "event_type": "boxing_mma",
        "event_duration_hours": 4.0,
        "weather_factor": 0.2,
        "transit_factor": 0.6,
        "mode": "fast",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert data["mode"] == "fast"
    assert "temporal" in data
    assert data["temporal"]["n_time_steps"] > 0
    assert data["temporal"]["peak_congestion_wait"] >= 0
    assert "metrics" in data
    assert data["computation_time_ms"] < 5000


def test_simulate_temporal_propagates_ticket_price_demand_model(client):
    r = client.post("/simulate/temporal", json={
        "venue_id": "t_mobile_arena",
        "attendance": 20000,
        "event_type": "concert",
        "event_duration_hours": 4.0,
        "weather_factor": 0.2,
        "transit_factor": 0.6,
        "avg_ticket_price": 10000,
        "mode": "fast",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["metrics"]["demand"]["model_applied"] is True
    assert data["parameters"]["attendance_requested"] == 20000
    assert data["parameters"]["attendance"] <= 20000


def test_simulate_temporal_deep_reports_total_runtime_and_uncertainty(client):
    r = client.post("/simulate/temporal", json={
        "venue_id": "thomas_mack_center",
        "attendance": 17000,
        "event_type": "concert",
        "event_duration_hours": 3.0,
        "weather_factor": 0.2,
        "transit_factor": 0.6,
        "mode": "deep",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert data["mode"] == "deep"
    assert "critical_points" in data["temporal"]
    assert "uncertainty_summary" in data["temporal"]
    assert data["temporal"]["fast_curve_computation_time_ms"] > 0
    assert data["temporal"]["computation_time_ms"] >= data["temporal"]["fast_curve_computation_time_ms"]
    assert abs(data["temporal"]["computation_time_ms"] - data["computation_time_ms"]) < 0.2


def test_allegiant_temporal_metrics_surface_peak_safety_without_criticalizing_baseline(client):
    r = client.post("/simulate/temporal", json={
        "venue_id": "allegiant_stadium",
        "attendance": 61000,
        "event_type": "nfl",
        "event_duration_hours": 3.0,
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "mode": "fast",
    })
    assert r.status_code == 200
    data = r.json()

    safety = data["metrics"]["safety"]
    revenue = data["metrics"]["revenue"]

    assert safety["temporal_peak_srs"] >= safety["structural_srs"]
    assert safety["srs"] < 0.6
    assert safety["risk_level"] in ("LOW", "MODERATE", "ELEVATED")
    assert revenue["total_economic_impact"] < 1000.0
    assert revenue["interpretation"] == "modeled downside at risk, not gross event revenue"


# ═══════════════════════════════════════════════════════════════════════════════
#  What-If Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def test_what_if(client):
    r = client.post("/scenario/what-if", json={
        "venue_id": "allegiant_stadium",
        "attendance": 55000,
        "event_type": "nfl",
        "weather_factor": 0.4,
        "transit_factor": 0.5,
        "changes": {"disable_gates": ["gate_0"]},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert "base" in data
    assert "modified" in data
    assert "delta" in data
    assert "summary" in data
    # Disabling a gate should affect results
    assert isinstance(data["improved_nodes"], list)
    assert isinstance(data["degraded_nodes"], list)


def test_what_if_modified_result_includes_service_rate_provenance(client):
    r = client.post("/scenario/what-if", json={
        "venue_id": "allegiant_stadium",
        "attendance": 55000,
        "event_type": "nfl",
        "weather_factor": 0.4,
        "transit_factor": 0.5,
        "changes": {"disable_gates": ["gate_0"]},
    })
    assert r.status_code == 200
    data = r.json()

    modified = data["modified"]
    assert modified["parameters"]["service_rate_tier"] == "operational"
    assert modified["data_provenance"]["service_rates"]["tier"] == "operational"


def test_what_if_staffing_cut(client):
    r = client.post("/scenario/what-if", json={
        "venue_id": "allegiant_stadium",
        "attendance": 45000,
        "event_type": "nfl",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "changes": {"reduce_staffing_pct": 0.3},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    # Staffing cut should degrade wait times
    assert data["delta"].get("wait_mean", 0) >= 0


def test_what_if_preserves_ticket_price_demand_logic(client):
    r = client.post("/scenario/what-if", json={
        "venue_id": "allegiant_stadium",
        "attendance": 65000,
        "event_type": "concert",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "avg_ticket_price": 10000,
        "changes": {"disable_gates": ["gate_0"]},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["modified"]["metrics"]["demand"]["model_applied"] is True
    assert data["modified"]["parameters"]["attendance"] < 65000


# ═══════════════════════════════════════════════════════════════════════════════
#  Stress Test Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def test_stress_test(client):
    r = client.post("/stress-test", json={
        "venue_id": "allegiant_stadium",
        "attendance": 50000,
        "event_type": "nfl",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "tests": ["gate_failure", "extreme_heat"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert "gate_failure" in data["stress_results"]
    assert "extreme_heat" in data["stress_results"]
    assert data["resilience_score"] >= 0
    assert data["resilience_score"] <= 100
    assert data["most_vulnerable"] in ("gate_failure", "extreme_heat")
    # Each stress result has simulation + metrics + delta
    for test_name, result in data["stress_results"].items():
        assert "simulation" in result
        assert "metrics" in result
        assert "delta" in result


def test_stress_test_all(client):
    r = client.post("/stress-test", json={
        "venue_id": "t_mobile_arena",
        "attendance": 18000,
        "event_type": "boxing_mma",
        "weather_factor": 0.2,
        "transit_factor": 0.6,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    # All 6 tests should run
    assert len(data["stress_results"]) == 6


def test_stress_test_propagates_ticket_price_demand_logic(client):
    r = client.post("/stress-test", json={
        "venue_id": "allegiant_stadium",
        "attendance": 65000,
        "event_type": "concert",
        "weather_factor": 0.3,
        "transit_factor": 0.5,
        "avg_ticket_price": 10000,
        "tests": ["gate_failure"],
    })
    assert r.status_code == 200
    data = r.json()
    result = data["stress_results"]["gate_failure"]
    assert result["metrics"]["demand"]["model_applied"] is True
    assert result["parameters"]["attendance_requested"] == 65000
    assert result["parameters"]["attendance"] < 65000


# ═══════════════════════════════════════════════════════════════════════════════
#  Scenario Compare Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_compare(client):
    r = client.post("/scenario/compare", json={
        "venue_id": "allegiant_stadium",
        "base": {
            "venue_id": "allegiant_stadium",
            "attendance": 45000,
            "event_type": "nfl",
            "weather_factor": 0.3,
            "transit_factor": 0.5,
            "n_simulations": 200,
        },
        "modified": {
            "venue_id": "allegiant_stadium",
            "attendance": 45000,
            "event_type": "nfl",
            "weather_factor": 0.8,
            "transit_factor": 0.5,
            "n_simulations": 200,
        },
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"]
    assert "base" in data
    assert "modified" in data
    assert "delta" in data
    assert "summary" in data


def test_scenario_compare_graph_changes_preserve_service_rate_tier_provenance(client):
    r = client.post("/scenario/compare", json={
        "venue_id": "allegiant_stadium",
        "base": {
            "venue_id": "allegiant_stadium",
            "attendance": 45000,
            "event_type": "nfl",
            "weather_factor": 0.3,
            "transit_factor": 0.5,
            "n_simulations": 150,
            "service_rate_tier": "literature",
        },
        "modified": {
            "venue_id": "allegiant_stadium",
            "attendance": 45000,
            "event_type": "nfl",
            "weather_factor": 0.3,
            "transit_factor": 0.5,
            "n_simulations": 150,
            "service_rate_tier": "literature",
        },
        "graph_changes": {
            "disable_nodes": ["gate_0", "security_0"],
            "modify_servers": {},
        },
    })
    assert r.status_code == 200
    data = r.json()

    modified = data["modified"]
    assert modified["parameters"]["service_rate_tier"] == "literature"
    assert modified["data_provenance"]["service_rates"]["tier"] == "literature"
