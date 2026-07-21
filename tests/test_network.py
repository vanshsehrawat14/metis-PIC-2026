"""
tests/test_network.py — Test suite for simulation/network.py queueing network engine.

Covers:
  - Erlang-C against published tables
  - Traffic equation conservation
  - Routing probability validation
  - Simple linear network with known analytical solution
  - Gate closure what-if scenario
  - Unstable system handling
  - Venue profile graph construction
  - Backward-compatible output format
"""

import json
import math
import os
import sys

import numpy as np
import pytest

# Ensure project root is importable
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from simulation.network import (
    VenueNode,
    VenueEdge,
    VenueGraph,
    QueueingNetworkSolver,
    NetworkMonteCarloEngine,
    load_venue_graph,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_linear_3_node_graph(
    arrival_rate=1000.0,
    sec_servers=4,
    sec_rate=300.0,
    sec_c_s_sq=0.5,
):
    """
    Build a simple 3-node linear network: gate → security → seating.

    gate: entry node (ticket scan, very fast)
    security: sec_servers lanes at sec_rate persons/hr/lane
    seating: exit sink (infinite capacity)
    """
    nodes = [
        VenueNode(
            node_id="gate",
            node_type="ticketing",
            num_servers=10,        # many turnstiles — not the bottleneck
            service_rate=1050.0,   # barcode scan rate
            c_s_squared=0.15,
            is_entry=True,
        ),
        VenueNode(
            node_id="security",
            node_type="security",
            num_servers=sec_servers,
            service_rate=sec_rate,
            c_s_squared=sec_c_s_sq,
        ),
        VenueNode(
            node_id="seating",
            node_type="seating",
            num_servers=1,
            service_rate=100000.0,  # effectively infinite
            c_s_squared=0.1,
            is_exit=True,
        ),
    ]
    edges = [
        VenueEdge(from_node="gate", to_node="security", routing_probability=1.0),
        VenueEdge(from_node="security", to_node="seating", routing_probability=1.0),
    ]
    return VenueGraph(nodes, edges)


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Erlang-C against known values
# ═══════════════════════════════════════════════════════════════════════════════

class TestErlangC:
    """Verify Erlang-C against published tables."""

    def test_s1_a05(self):
        """s=1, a=0.5 → C(1, 0.5) = 0.5 (exact, M/M/1 busy probability)."""
        result = QueueingNetworkSolver.erlang_c(1, 0.5)
        assert abs(result - 0.5) < 0.001, f"Expected 0.5, got {result}"

    def test_s2_a15(self):
        """s=2, a=1.5 → C(2, 1.5) ≈ 0.6."""
        # Exact: [1.5²/2! × 1/(1-0.75)] / [1 + 1.5 + 1.5²/2! × 1/(1-0.75)]
        # = [1.125 × 4] / [1 + 1.5 + 4.5] = 4.5 / 7.0 ≈ 0.6429
        result = QueueingNetworkSolver.erlang_c(2, 1.5)
        assert abs(result - 0.6429) < 0.01, f"Expected ~0.643, got {result}"

    def test_s10_a8(self):
        """s=10, a=8.0 → C ≈ 0.4092 (exact formula)."""
        result = QueueingNetworkSolver.erlang_c(10, 8.0)
        assert abs(result - 0.4092) < 0.005, f"Expected ~0.4092, got {result}"

    def test_zero_load(self):
        """Zero offered load → C = 0."""
        assert QueueingNetworkSolver.erlang_c(5, 0.0) == 0.0

    def test_overloaded(self):
        """a/s >= 1 → C = 1.0 (everyone waits)."""
        assert QueueingNetworkSolver.erlang_c(3, 4.0) == 1.0
        assert QueueingNetworkSolver.erlang_c(1, 1.5) == 1.0

    def test_invalid_servers(self):
        """Zero or negative servers should raise."""
        with pytest.raises(ValueError):
            QueueingNetworkSolver.erlang_c(0, 1.0)

    def test_large_system_no_overflow(self):
        """s=100, a=80 should not overflow (factorial of 100 is enormous)."""
        result = QueueingNetworkSolver.erlang_c(100, 80.0)
        assert 0.0 <= result <= 1.0
        # For s=100, a=80, ρ=0.8 — moderate load, C should be reasonable
        assert result < 0.5


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Simple linear network
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimpleLinearNetwork:
    """3-node linear: gate → security → seating. Known analytical solution."""

    def test_arrival_rate_propagation(self):
        """λ at security should equal external arrival rate (no branching)."""
        graph = _make_linear_3_node_graph()
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0])  # 1000/hr at gate
        lambdas = solver.solve_traffic_equations(gamma)

        assert abs(lambdas[0] - 1000.0) < 0.01  # gate
        assert abs(lambdas[1] - 1000.0) < 0.01  # security
        assert abs(lambdas[2] - 1000.0) < 0.01  # seating

    def test_security_utilization(self):
        """ρ = λ / (s × μ) = 1000 / (4 × 300) = 0.833."""
        graph = _make_linear_3_node_graph()
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0])
        result = solver.solve(gamma)

        sec_metrics = result.node_metrics["security"]
        expected_rho = 1000.0 / (4 * 300.0)
        assert abs(sec_metrics.utilization - expected_rho) < 0.001

    def test_security_is_bottleneck(self):
        """Security should be identified as the bottleneck."""
        graph = _make_linear_3_node_graph()
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0])
        result = solver.solve(gamma)

        assert result.node_metrics["security"].is_bottleneck

    def test_wait_positive(self):
        """Positive wait at security for ρ = 0.833."""
        graph = _make_linear_3_node_graph()
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0])
        result = solver.solve(gamma)

        assert result.node_metrics["security"].expected_wait_minutes > 0

    def test_network_stable(self):
        """Network should be stable when ρ < 1."""
        graph = _make_linear_3_node_graph()
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0])
        result = solver.solve(gamma)

        assert result.network_stable


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Traffic equation conservation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrafficEquationsConservation:
    """Total flow into network = total flow out (conservation of mass)."""

    def test_linear_conservation(self):
        """In a linear network, arrival = departure at every node."""
        graph = _make_linear_3_node_graph()
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([5000.0, 0.0, 0.0])
        lambdas = solver.solve_traffic_equations(gamma)

        # All nodes should see the same rate
        assert all(abs(l - 5000.0) < 0.01 for l in lambdas)

    def test_branching_conservation(self):
        """In a branching network, flow splits correctly."""
        nodes = [
            VenueNode("entry", "ticketing", 10, 10000.0, 0.1, is_entry=True),
            VenueNode("branch_a", "security", 5, 300.0, 0.5),
            VenueNode("branch_b", "security", 5, 300.0, 0.5),
            VenueNode("sink", "seating", 1, 100000.0, 0.1, is_exit=True),
        ]
        edges = [
            VenueEdge("entry", "branch_a", 0.6),
            VenueEdge("entry", "branch_b", 0.4),
            VenueEdge("branch_a", "sink", 1.0),
            VenueEdge("branch_b", "sink", 1.0),
        ]
        graph = VenueGraph(nodes, edges)
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0, 0.0])
        lambdas = solver.solve_traffic_equations(gamma)

        assert abs(lambdas[0] - 1000.0) < 0.01  # entry
        assert abs(lambdas[1] - 600.0) < 0.01   # branch_a (60%)
        assert abs(lambdas[2] - 400.0) < 0.01   # branch_b (40%)
        assert abs(lambdas[3] - 1000.0) < 0.01  # sink (all flow)

    def test_recirculation_amplifies(self):
        """A node that recirculates 20% should see λ > external arrivals."""
        nodes = [
            VenueNode("entry", "ticketing", 10, 10000.0, 0.1, is_entry=True),
            VenueNode("loop", "corridor", 1, 50000.0, 0.3),
            VenueNode("sink", "seating", 1, 100000.0, 0.1, is_exit=True),
        ]
        edges = [
            VenueEdge("entry", "loop", 1.0),
            VenueEdge("loop", "sink", 0.8),
            VenueEdge("loop", "loop", 0.2),  # 20% recirculate
        ]
        graph = VenueGraph(nodes, edges)
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([1000.0, 0.0, 0.0])
        lambdas = solver.solve_traffic_equations(gamma)

        # Loop node: λ = 1000 + 0.2 × λ → λ = 1000/0.8 = 1250
        assert abs(lambdas[1] - 1250.0) < 0.1
        # Sink: 0.8 × 1250 = 1000 (all external arrivals exit)
        assert abs(lambdas[2] - 1000.0) < 0.1


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Routing probability validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoutingProbabilityValidation:
    """Non-stochastic routing matrix should raise error."""

    def test_probabilities_not_summing_to_one(self):
        """Routing probs that don't sum to 1.0 should raise ValueError."""
        nodes = [
            VenueNode("a", "ticketing", 1, 1000.0, 0.1, is_entry=True),
            VenueNode("b", "security", 1, 300.0, 0.5),
            VenueNode("c", "seating", 1, 100000.0, 0.1, is_exit=True),
        ]
        edges = [
            VenueEdge("a", "b", 0.5),   # only 0.5, not 1.0
            VenueEdge("b", "c", 1.0),
        ]
        with pytest.raises(ValueError, match="sum to"):
            VenueGraph(nodes, edges)

    def test_no_entry_node(self):
        nodes = [
            VenueNode("a", "security", 1, 300.0, 0.5),
            VenueNode("b", "seating", 1, 100000.0, 0.1, is_exit=True),
        ]
        edges = [VenueEdge("a", "b", 1.0)]
        with pytest.raises(ValueError, match="entry"):
            VenueGraph(nodes, edges)

    def test_no_exit_node(self):
        nodes = [
            VenueNode("a", "ticketing", 1, 1000.0, 0.1, is_entry=True),
            VenueNode("b", "security", 1, 300.0, 0.5),
        ]
        edges = [VenueEdge("a", "b", 1.0)]
        with pytest.raises(ValueError, match="exit"):
            VenueGraph(nodes, edges)

    def test_invalid_edge_reference(self):
        nodes = [
            VenueNode("a", "ticketing", 1, 1000.0, 0.1, is_entry=True),
            VenueNode("b", "seating", 1, 100000.0, 0.1, is_exit=True),
        ]
        edges = [VenueEdge("a", "nonexistent", 1.0)]
        with pytest.raises(ValueError, match="unknown"):
            VenueGraph(nodes, edges)


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Gate closure scenario
# ═══════════════════════════════════════════════════════════════════════════════

class TestGateClosureScenario:
    """Closing one gate should increase wait at remaining gates."""

    def test_closing_gate_increases_wait(self):
        """Build a 2-gate system, close one gate, verify wait increases."""
        nodes = [
            VenueNode("gate_0", "ticketing", 5, 1050.0, 0.15, is_entry=True),
            VenueNode("gate_1", "ticketing", 5, 1050.0, 0.15, is_entry=True),
            VenueNode("sec_0", "security", 4, 300.0, 0.5),
            VenueNode("sec_1", "security", 4, 300.0, 0.5),
            VenueNode("seating", "seating", 1, 100000.0, 0.1, is_exit=True),
        ]
        edges = [
            VenueEdge("gate_0", "sec_0", 1.0),
            VenueEdge("gate_1", "sec_1", 1.0),
            VenueEdge("sec_0", "seating", 1.0),
            VenueEdge("sec_1", "seating", 1.0),
        ]
        graph = VenueGraph(nodes, edges)

        # Baseline: 1000/hr split across 2 gates
        solver = QueueingNetworkSolver(graph)
        gamma_base = np.array([500.0, 500.0, 0.0, 0.0, 0.0])
        result_base = solver.solve(gamma_base)
        base_wait = result_base.mean_wait_minutes

        # Close gate_1: all 1000/hr through gate_0
        modified = graph.modify({"disable_nodes": ["gate_1", "sec_1"]})
        solver_mod = QueueingNetworkSolver(modified)
        idx = modified._node_index
        gamma_mod = np.zeros(len(modified.nodes))
        gamma_mod[idx["gate_0"]] = 1000.0
        result_mod = solver_mod.solve(gamma_mod)
        mod_wait = result_mod.mean_wait_minutes

        assert mod_wait > base_wait, (
            f"Closing a gate should increase wait: base={base_wait:.2f}, "
            f"modified={mod_wait:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Unstable system handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnstableSystemHandling:
    """Arrival rate > service capacity should flag instability, not crash."""

    def test_unstable_flags(self):
        """ρ > 1 should be flagged as unstable."""
        # 4 lanes × 300 = 1200 capacity; 2000 demand → ρ = 1.67
        graph = _make_linear_3_node_graph(sec_servers=4, sec_rate=300.0)
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([2000.0, 0.0, 0.0])
        result = solver.solve(gamma)

        sec = result.node_metrics["security"]
        assert not sec.is_stable
        assert sec.utilization > 1.0
        assert not result.network_stable

    def test_unstable_does_not_crash(self):
        """Even with extreme overload, solver should return, not raise."""
        graph = _make_linear_3_node_graph(sec_servers=1, sec_rate=100.0)
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([50000.0, 0.0, 0.0])
        result = solver.solve(gamma)
        assert result.node_metrics["security"].expected_wait_minutes > 0

    def test_unstable_wait_capped(self):
        """Unstable node wait should be capped at 120 minutes."""
        graph = _make_linear_3_node_graph(sec_servers=1, sec_rate=100.0)
        solver = QueueingNetworkSolver(graph)
        gamma = np.array([50000.0, 0.0, 0.0])
        result = solver.solve(gamma)
        assert result.node_metrics["security"].expected_wait_minutes == 120.0


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: from_venue_profile
# ═══════════════════════════════════════════════════════════════════════════════

class TestFromVenueProfile:
    """Build network from Allegiant Stadium profile, verify it solves."""

    def test_allegiant_graph_structure(self):
        """Graph should have entry nodes, exit nodes, and reasonable size."""
        graph = load_venue_graph("allegiant_stadium")
        assert len(graph.nodes) > 10
        assert len(graph.get_entry_node_ids()) > 0
        assert len(graph.get_exit_node_ids()) > 0

    def test_allegiant_has_security(self):
        """Graph should contain security nodes."""
        graph = load_venue_graph("allegiant_stadium")
        sec_nodes = [n for n in graph.nodes if n.node_type == "security"]
        assert len(sec_nodes) >= 4  # at least some security checkpoints

    def test_allegiant_solves(self):
        """Full solve should complete without error."""
        graph = load_venue_graph("allegiant_stadium")
        solver = QueueingNetworkSolver(graph)
        entry_ids = graph.get_entry_node_ids()
        gamma = np.zeros(len(graph.nodes))
        for eid in entry_ids:
            gamma[graph._node_index[eid]] = 5000.0 / len(entry_ids)
        result = solver.solve(gamma)
        assert result.bottleneck_node is not None
        assert result.max_wait_minutes >= 0

    def test_small_venue_solves(self):
        """Small venue (T-Mobile Arena) should also work."""
        graph = load_venue_graph("t_mobile_arena")
        solver = QueueingNetworkSolver(graph)
        entry_ids = graph.get_entry_node_ids()
        gamma = np.zeros(len(graph.nodes))
        for eid in entry_ids:
            gamma[graph._node_index[eid]] = 2000.0 / len(entry_ids)
        result = solver.solve(gamma)
        assert result.bottleneck_node is not None

    def test_all_venues_build_without_error(self):
        """Every venue in vegas_venues.json should produce a valid graph."""
        venues_path = os.path.join(_PROJECT_ROOT, "data", "venues", "vegas_venues.json")
        with open(venues_path, encoding="utf-8") as f:
            data = json.load(f)
        for v in data["venues"]:
            graph = VenueGraph.from_venue_profile(v)
            assert len(graph.nodes) > 0
            assert len(graph.get_entry_node_ids()) > 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: Backward-compatible output
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibleOutput:
    """Output dict must contain all keys the existing engine produces."""

    REQUIRED_KEYS = {
        # Wait
        "wait_mean", "wait_p10", "wait_p90", "wait_std",
        # Congestion (backward-compat aliases)
        "cong_mean", "cong_p10", "cong_p90",
        # Breakdown
        "brk_mean", "brk_p10", "brk_p90",
        # HES
        "hes_mean", "hes_p10", "hes_p90",
        # Utilization
        "util_mean",
    }

    NEW_KEYS = {
        "node_metrics", "bottleneck_node", "bottleneck_frequency",
        "unstable_node_pct", "worst_fruin_los", "network_throughput_mean",
        "total_process_time_mean", "n_simulations", "n_nodes",
        "computation_time_ms", "engine_version",
    }

    def test_has_all_required_keys(self):
        """MC engine output should include all backward-compatible keys."""
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=50)
        result = engine.run(total_attendance=500, weather_factor=0.1, transit_factor=0.5)

        missing = self.REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing backward-compatible keys: {missing}"

    def test_has_new_keys(self):
        """MC engine output should include new network-specific keys."""
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=50)
        result = engine.run(total_attendance=500, weather_factor=0.1, transit_factor=0.5)

        missing = self.NEW_KEYS - set(result.keys())
        assert not missing, f"Missing new keys: {missing}"

    def test_values_are_numeric(self):
        """All metric values should be finite numbers."""
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=50)
        result = engine.run(total_attendance=500, weather_factor=0.1, transit_factor=0.5)

        for key in self.REQUIRED_KEYS:
            val = result[key]
            assert isinstance(val, (int, float)), f"{key} should be numeric, got {type(val)}"
            assert math.isfinite(val), f"{key} should be finite, got {val}"

    def test_engine_version(self):
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=10)
        result = engine.run(total_attendance=500)
        assert result["engine_version"] == "network_v1"

    def test_node_metrics_present(self):
        """node_metrics should contain entries for every node."""
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=50)
        result = engine.run(total_attendance=500)

        assert "node_metrics" in result
        node_ids = {n.node_id for n in graph.nodes}
        assert set(result["node_metrics"].keys()) == node_ids


# ═══════════════════════════════════════════════════════════════════════════════
#  Test: compare_scenarios
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompareScenarios:
    """compare_scenarios should return base, modified, and delta."""

    def test_returns_structure(self):
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=30)
        result = engine.compare_scenarios(
            base_params={"total_attendance": 500, "weather_factor": 0.1},
            modified_params={"total_attendance": 800, "weather_factor": 0.1},
        )
        assert "base" in result
        assert "modified" in result
        assert "delta" in result
        assert isinstance(result["delta"], dict)

    def test_delta_direction(self):
        """Higher attendance should increase wait time."""
        graph = _make_linear_3_node_graph()
        engine = NetworkMonteCarloEngine(graph, n_simulations=50)
        result = engine.compare_scenarios(
            base_params={"total_attendance": 300, "weather_factor": 0.0},
            modified_params={"total_attendance": 900, "weather_factor": 0.0},
        )
        assert result["delta"]["wait_mean"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
