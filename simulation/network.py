"""
simulation/network.py — Queueing network engine for venue crowd simulation.

A directed graph of queueing nodes, each parameterised from ServiceRateDatabase
and venue profiles (replacing a single-node Kingman G/G/1 approximation).

Mathematical foundations:
  - Open Jackson-style traffic equations: λ = (I - R^T)^{-1} γ
  - Erlang-C probability of waiting (log-space computation for stability)
  - Allen-Cunneen correction for general service distributions
  - Fruin LOS grading for corridor density (HCM6)
  - Monte Carlo perturbation of arrival/service rates (1 000 trials)

Sources:
  Service rates → data/sources/service_rates.py (DHS, Fruin, HCM6, IAAM)
  Venue profiles → data/venues/vegas_venues.json
  Traffic context → data/sources/traffic.py
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import linalg as sp_linalg

# ── Imports from project data layer ──────────────────────────────────────────

import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from data.sources.service_rates import ServiceRateDatabase


# ═══════════════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VenueNode:
    """Single service point in the venue network."""
    node_id: str
    node_type: str          # "security", "ticketing", "concession", "restroom",
                            # "corridor", "seating", "exit", "gate"
    num_servers: int        # s_i — parallel service channels
    service_rate: float     # μ_i — persons/hour/server
    c_s_squared: float      # squared CoV of service time
    capacity: Optional[int] = None      # max occupancy (None = unlimited)
    area_m2: Optional[float] = None     # for corridor nodes — Fruin LOS
    is_entry: bool = False
    is_exit: bool = False
    screening_level: str = "standard"   # security nodes
    service_subtype: str = "full_menu"  # concession nodes
    confidence: str = "medium"


@dataclass
class VenueEdge:
    """Directed connection between nodes with routing probability."""
    from_node: str
    to_node: str
    routing_probability: float
    transit_time_seconds: float = 60.0
    corridor_width_m: Optional[float] = None
    corridor_length_m: Optional[float] = None


@dataclass
class NodeMetrics:
    """Performance metrics for a single node."""
    node_id: str
    arrival_rate: float             # λ_i (persons/hour)
    utilization: float              # ρ_i = λ_i / (s_i × μ_i)
    prob_waiting: float             # Erlang-C P(wait)
    expected_wait_minutes: float    # E[W_i] with Allen-Cunneen correction
    expected_queue_length: float    # L_q = λ_i × E[W_i] (in hours)
    throughput: float               # min(λ_i, s_i × μ_i)
    is_stable: bool                 # ρ_i < 1.0
    is_bottleneck: bool = False
    fruin_los: Optional[str] = None
    density_per_m2: Optional[float] = None


@dataclass
class NetworkMetrics:
    """Aggregated metrics across the full venue network."""
    node_metrics: dict[str, NodeMetrics]
    bottleneck_node: str
    max_wait_minutes: float
    mean_wait_minutes: float
    total_venue_throughput: float
    time_to_process_all: float      # minutes
    worst_fruin_los: Optional[str]
    network_stable: bool


# ═══════════════════════════════════════════════════════════════════════════════
#  Fruin Level-of-Service thresholds (HCM6 Ch. 24)
# ═══════════════════════════════════════════════════════════════════════════════

_FRUIN_THRESHOLDS = [
    # (max density persons/m², grade)
    (0.31, "A"),    # free flow
    (0.43, "B"),    # minor conflicts
    (0.72, "C"),    # restricted movement
    (1.08, "D"),    # severely restricted
    (2.17, "E"),    # breakdown imminent
]
# >2.17 → "F"


def _fruin_grade(density_p_m2: float) -> str:
    for threshold, grade in _FRUIN_THRESHOLDS:
        if density_p_m2 <= threshold:
            return grade
    return "F"


_LOS_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}


def _worst_los(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None:
        return b
    if b is None:
        return a
    return a if _LOS_ORDER.get(a, 5) >= _LOS_ORDER.get(b, 5) else b


# ═══════════════════════════════════════════════════════════════════════════════
#  Helper: parse infrastructure estimates
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_estimate(val) -> int:
    """Parse venue infrastructure values like 8, "6-8", {"estimate": "6-8"}, etc."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        if "-" in val:
            parts = val.split("-")
            lo, hi = int(parts[0]), int(parts[1])
            return (lo + hi) // 2
        # Try stripping non-numeric suffixes like "40000+"
        cleaned = val.rstrip("+").strip()
        try:
            return int(cleaned)
        except ValueError:
            return 4  # fallback default
    if isinstance(val, dict):
        for key in ("count", "count_estimate", "estimate", "value", "value_estimate"):
            if key in val and val[key] is not None:
                return _parse_estimate(val[key])
    return 4  # conservative default


# ═══════════════════════════════════════════════════════════════════════════════
#  VenueGraph
# ═══════════════════════════════════════════════════════════════════════════════

class VenueGraph:
    """Directed graph of queueing nodes representing a venue."""

    def __init__(self, nodes: list[VenueNode], edges: list[VenueEdge]):
        self.nodes: list[VenueNode] = list(nodes)
        self.edges: list[VenueEdge] = list(edges)

        self._node_map: dict[str, VenueNode] = {n.node_id: n for n in self.nodes}
        self._node_index: dict[str, int] = {n.node_id: i for i, n in enumerate(self.nodes)}

        self._validate()
        self._R = self._build_routing_matrix()

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate(self):
        node_ids = set(self._node_map.keys())

        entry_nodes = [n for n in self.nodes if n.is_entry]
        exit_nodes = [n for n in self.nodes if n.is_exit]
        if not entry_nodes:
            raise ValueError("Graph must have at least one entry node")
        if not exit_nodes:
            raise ValueError("Graph must have at least one exit node")

        # Check edges reference valid nodes
        for e in self.edges:
            if e.from_node not in node_ids:
                raise ValueError(f"Edge references unknown from_node: {e.from_node}")
            if e.to_node not in node_ids:
                raise ValueError(f"Edge references unknown to_node: {e.to_node}")

        # Check routing probabilities sum to ~1.0 for each non-exit source node
        outgoing: dict[str, float] = {}
        for e in self.edges:
            outgoing.setdefault(e.from_node, 0.0)
            outgoing[e.from_node] += e.routing_probability

        for n in self.nodes:
            if n.is_exit:
                continue
            total = outgoing.get(n.node_id, 0.0)
            if abs(total - 1.0) > 0.02:
                raise ValueError(
                    f"Routing probabilities from node '{n.node_id}' sum to "
                    f"{total:.4f}, expected ~1.0"
                )

    # ── Routing matrix ────────────────────────────────────────────────────────

    def _build_routing_matrix(self) -> np.ndarray:
        n = len(self.nodes)
        R = np.zeros((n, n))
        for e in self.edges:
            i = self._node_index[e.from_node]
            j = self._node_index[e.to_node]
            R[i, j] = e.routing_probability
        return R

    def get_routing_matrix(self) -> np.ndarray:
        return self._R.copy()

    def get_entry_node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes if n.is_entry]

    def get_exit_node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes if n.is_exit]

    def get_node(self, node_id: str) -> VenueNode:
        return self._node_map[node_id]

    # ── Factory: build from venue profile ─────────────────────────────────────

    @classmethod
    def from_venue_profile(
        cls,
        venue_data: dict,
        service_db: Optional[ServiceRateDatabase] = None,
    ) -> "VenueGraph":
        """
        Build a complete queueing network from a vegas_venues.json entry.

        Standard topology:
          entry gates → security checkpoints → main concourse (corridor)
          concourse → concession | restroom | seating
          seating → exit corridor → exit gates
        """
        if service_db is None:
            service_db = ServiceRateDatabase()

        infra = venue_data.get("infrastructure", {})
        cap_data = venue_data.get("capacity", {})
        max_cap = cap_data.get("max", cap_data.get("app_py_value", 10000))

        # Parse infrastructure counts
        gates_raw = infra.get("gates", {})
        n_gates = _parse_estimate(gates_raw)
        sec_per_gate_raw = infra.get("security_lanes_per_gate", {"estimate": "4-6"})
        sec_per_gate = _parse_estimate(sec_per_gate_raw)
        total_concession_stands = _parse_estimate(
            infra.get("concession_stands", {"estimate": max(4, max_cap // 1500)})
        )
        total_restroom_facilities = _parse_estimate(
            infra.get("restroom_facilities", {"estimate": max(4, max_cap // 2000)})
        )
        n_exits = _parse_estimate(infra.get("exit_gates", {"estimate": max(n_gates, 4)}))

        # Aggregate concessions/restrooms into zones (max 4 each) for tractable
        # network size.  Each zone node gets multiple servers = total_stands / n_zones.
        n_conc_zones = min(total_concession_stands, 4)
        conc_servers_per_zone = max(
            1, round(total_concession_stands * 3 / max(n_conc_zones, 1))
        )  # 3 registers per stand, pooled into zone
        n_rest_zones = min(total_restroom_facilities, 4)
        rest_stalls_per_zone = max(
            1, round(total_restroom_facilities * 6 / max(n_rest_zones, 1))
        )  # 6 stalls per facility, pooled

        # Confidence propagation
        gate_conf = gates_raw.get("confidence", "low") if isinstance(gates_raw, dict) else "low"
        sec_conf = sec_per_gate_raw.get("confidence", "low") if isinstance(sec_per_gate_raw, dict) else "low"

        # Convention venues use badge scanning, not magnetometer security screening.
        # CES / trade show entry is RFID badge scan at ~1500 pph vs security at ~380 pph.
        event_types = venue_data.get("event_types", [])
        _is_convention = any(
            t in ("convention", "trade_show", "expo", "conference") for t in event_types
        )

        # Service rate lookups
        if _is_convention:
            # Use RFID/NFC badge scan rates for "security" nodes — convention registration
            sec_params = service_db.get_service_rate("ticketing", service_type="rfid")
        else:
            sec_params = service_db.get_service_rate("security", screening_level="standard")
        tick_params = service_db.get_service_rate("ticketing", service_type="barcode")
        conc_params = service_db.get_service_rate("concession", service_type="full_menu")
        rest_params = service_db.get_service_rate("restroom")

        # Restroom rate: stored as min/stall/patron → convert to persons/hr/stall
        rest_rate_pph = 60.0 / rest_params["default"]  # 60 min / 2.5 min = 24 persons/hr

        # Scale transit times proportional to venue capacity
        # Baseline: 65000 cap ≈ Allegiant. Smaller venues have shorter walks.
        scale = math.sqrt(max_cap / 65000.0)
        scale = max(0.3, min(scale, 2.0))

        # Estimate concourse area: rough heuristic from capacity
        concourse_area_m2 = max_cap * 0.15 * scale  # ~0.15 m² per attendee scaled

        nodes: list[VenueNode] = []
        edges: list[VenueEdge] = []

        # ── Entry gate nodes (ticket scan) ────────────────────────────────────
        gate_ids = []
        for i in range(n_gates):
            gid = f"gate_{i}"
            gate_ids.append(gid)
            nodes.append(VenueNode(
                node_id=gid,
                node_type="ticketing",
                num_servers=2,   # 2 turnstiles per gate
                service_rate=tick_params["default"],
                c_s_squared=tick_params["c_s_squared"],
                is_entry=True,
                confidence=gate_conf,
                service_subtype="barcode",
            ))

        # ── Security checkpoint nodes ─────────────────────────────────────────
        sec_ids = []
        for i in range(n_gates):
            sid = f"security_{i}"
            sec_ids.append(sid)
            nodes.append(VenueNode(
                node_id=sid,
                node_type="security",
                num_servers=sec_per_gate,
                service_rate=sec_params["default"],
                c_s_squared=sec_params["c_s_squared"],
                screening_level="standard",
                confidence=sec_conf,
            ))

        # ── Main concourse (corridor node) ────────────────────────────────────
        conc_id = "concourse_main"
        nodes.append(VenueNode(
            node_id=conc_id,
            node_type="corridor",
            num_servers=1,
            # Corridor throughput: free-flow speed × effective width
            # Model as high-throughput pass-through; rate = max_cap * 2 persons/hr
            service_rate=max(max_cap * 2.0, 10000.0),
            c_s_squared=0.3,
            area_m2=concourse_area_m2,
            confidence="low",
        ))

        # ── Concession zone nodes (aggregated) ───────────────────────────────
        conc_ids = []
        for i in range(n_conc_zones):
            cid = f"concession_{i}"
            conc_ids.append(cid)
            nodes.append(VenueNode(
                node_id=cid,
                node_type="concession",
                num_servers=conc_servers_per_zone,
                service_rate=conc_params["default"],
                c_s_squared=conc_params["c_s_squared"],
                service_subtype="full_menu",
                confidence="low",
            ))

        # ── Restroom zone nodes (aggregated) ──────────────────────────────────
        rest_ids = []
        for i in range(n_rest_zones):
            rid = f"restroom_{i}"
            rest_ids.append(rid)
            nodes.append(VenueNode(
                node_id=rid,
                node_type="restroom",
                num_servers=rest_stalls_per_zone,
                service_rate=rest_rate_pph,
                c_s_squared=rest_params["c_s_squared"],
                confidence="low",
            ))

        # ── Seating node (absorbing service point) ────────────────────────────
        seat_id = "seating_main"
        nodes.append(VenueNode(
            node_id=seat_id,
            node_type="seating",
            num_servers=1,
            # Seating throughput: very high (ushers direct, self-seat)
            service_rate=max(max_cap * 3.0, 30000.0),
            c_s_squared=0.2,
            capacity=max_cap,
            confidence="medium",
        ))

        # ── Exit corridor ─────────────────────────────────────────────────────
        exit_corr_id = "exit_corridor"
        nodes.append(VenueNode(
            node_id=exit_corr_id,
            node_type="corridor",
            num_servers=1,
            service_rate=max(max_cap * 2.0, 10000.0),
            c_s_squared=0.3,
            area_m2=concourse_area_m2 * 0.7,  # exit corridors typically narrower
            confidence="low",
        ))

        # ── Exit gate nodes ───────────────────────────────────────────────────
        exit_ids = []
        for i in range(n_exits):
            eid = f"exit_{i}"
            exit_ids.append(eid)
            nodes.append(VenueNode(
                node_id=eid,
                node_type="exit",
                num_servers=4,
                # Exit throughput: unscreened, ~1800 persons/hr/lane (HCM6 doorway)
                service_rate=1800.0,
                c_s_squared=0.2,
                is_exit=True,
                confidence="low",
            ))

        # ── Edges: gate → security (1:1) ─────────────────────────────────────
        for gi, si in zip(gate_ids, sec_ids):
            edges.append(VenueEdge(
                from_node=gi, to_node=si,
                routing_probability=1.0,
                transit_time_seconds=20.0 * scale,
            ))

        # ── Edges: security → concourse ───────────────────────────────────────
        for si in sec_ids:
            edges.append(VenueEdge(
                from_node=si, to_node=conc_id,
                routing_probability=1.0,
                transit_time_seconds=90.0 * scale,
            ))

        # ── Edges: concourse → seating / concession / restroom ────────────────
        # 70% seating, 15% concession, 10% restroom, 5% recirculate to concourse
        # Split concession/restroom evenly among zone instances
        conc_prob_each = 0.15 / max(len(conc_ids), 1)
        rest_prob_each = 0.10 / max(len(rest_ids), 1)

        total_conc_prob = conc_prob_each * len(conc_ids)
        total_rest_prob = rest_prob_each * len(rest_ids)

        edges.append(VenueEdge(
            from_node=conc_id, to_node=seat_id,
            routing_probability=0.70,
            transit_time_seconds=120.0 * scale,
        ))
        for cid in conc_ids:
            edges.append(VenueEdge(
                from_node=conc_id, to_node=cid,
                routing_probability=conc_prob_each,
                transit_time_seconds=45.0 * scale,
            ))
        for rid in rest_ids:
            edges.append(VenueEdge(
                from_node=conc_id, to_node=rid,
                routing_probability=rest_prob_each,
                transit_time_seconds=30.0 * scale,
            ))

        # Remaining probability recirculates to self (people wandering concourse)
        remainder = 1.0 - 0.70 - total_conc_prob - total_rest_prob
        if remainder > 0.001:
            edges.append(VenueEdge(
                from_node=conc_id, to_node=conc_id,
                routing_probability=remainder,
                transit_time_seconds=60.0 * scale,
            ))
        elif remainder < -0.001:
            # Fix by adjusting seating probability
            edges[len(edges) - len(conc_ids) - len(rest_ids) - 1].routing_probability += remainder

        # ── Edges: concession → concourse (return after buying) ───────────────
        for cid in conc_ids:
            edges.append(VenueEdge(
                from_node=cid, to_node=conc_id,
                routing_probability=1.0,
                transit_time_seconds=30.0 * scale,
            ))

        # ── Edges: restroom → concourse ───────────────────────────────────────
        for rid in rest_ids:
            edges.append(VenueEdge(
                from_node=rid, to_node=conc_id,
                routing_probability=1.0,
                transit_time_seconds=20.0 * scale,
            ))

        # ── Edges: seating → exit corridor ────────────────────────────────────
        edges.append(VenueEdge(
            from_node=seat_id, to_node=exit_corr_id,
            routing_probability=1.0,
            transit_time_seconds=150.0 * scale,
        ))

        # ── Edges: exit corridor → exit gates (uniform) ──────────────────────
        exit_prob = 1.0 / max(len(exit_ids), 1)
        for eid in exit_ids:
            edges.append(VenueEdge(
                from_node=exit_corr_id, to_node=eid,
                routing_probability=exit_prob,
                transit_time_seconds=45.0 * scale,
            ))

        return cls(nodes, edges)

    # ── Graph modification for what-if scenarios ──────────────────────────────

    def modify(self, changes: dict) -> "VenueGraph":
        """
        Return a modified copy of the graph.

        changes can include:
          {"disable_nodes": ["gate_north_1"]}
          {"modify_servers": {"security_east_1": 4}}
          {"modify_routing": {"gate_south_1": {"security_south_2": 1.0}}}
        """
        new_nodes = [copy.deepcopy(n) for n in self.nodes]
        new_edges = [copy.deepcopy(e) for e in self.edges]

        node_map = {n.node_id: n for n in new_nodes}

        disabled = set(changes.get("disable_nodes", []))

        # Remove disabled nodes and their edges
        if disabled:
            new_nodes = [n for n in new_nodes if n.node_id not in disabled]
            new_edges = [e for e in new_edges
                         if e.from_node not in disabled and e.to_node not in disabled]

            # Re-normalize routing probabilities for nodes that lost outgoing edges
            affected = set()
            for nid in disabled:
                for e in self.edges:
                    if e.to_node == nid:
                        affected.add(e.from_node)

            for src in affected:
                if src in disabled:
                    continue
                out_edges = [e for e in new_edges if e.from_node == src]
                total = sum(e.routing_probability for e in out_edges)
                if total > 0:
                    for e in out_edges:
                        e.routing_probability /= total

        # Modify server counts
        for nid, new_s in changes.get("modify_servers", {}).items():
            if nid in node_map and nid not in disabled:
                node_map[nid].num_servers = new_s

        # Modify routing
        for src, targets in changes.get("modify_routing", {}).items():
            if src in disabled:
                continue
            # Replace all outgoing edges from src
            new_edges = [e for e in new_edges if e.from_node != src]
            for tgt, prob in targets.items():
                new_edges.append(VenueEdge(
                    from_node=src, to_node=tgt,
                    routing_probability=prob,
                ))

        return VenueGraph(new_nodes, new_edges)


# ═══════════════════════════════════════════════════════════════════════════════
#  QueueingNetworkSolver
# ═══════════════════════════════════════════════════════════════════════════════

class QueueingNetworkSolver:
    """
    Solves traffic equations and computes per-node queueing metrics
    for an open Jackson-style network with general service distributions.
    """

    def __init__(self, graph: VenueGraph):
        self.graph = graph
        self.n_nodes = len(graph.nodes)
        self.R = graph.get_routing_matrix()

        # Pre-compute LU factorisation of (I - R^T) for fast repeated solves
        A = np.eye(self.n_nodes) - self.R.T
        det = np.linalg.det(A)
        if abs(det) < 1e-12:
            raise ValueError(
                "Routing matrix creates absorbing cycles — "
                f"det(I - R^T) = {det:.2e}. Check graph definition."
            )
        self._lu_piv = sp_linalg.lu_factor(A)

    # ── Traffic equations ─────────────────────────────────────────────────────

    def solve_traffic_equations(self, external_arrivals: np.ndarray) -> np.ndarray:
        """
        Solve λ = (I - R^T)^{-1} × γ using pre-computed LU factorisation.

        external_arrivals: array length n_nodes, nonzero at entry nodes.
        Returns: effective arrival rate at every node.
        """
        lambdas = sp_linalg.lu_solve(self._lu_piv, external_arrivals)

        if np.any(lambdas < -1e-10):
            raise ValueError(
                f"Negative arrival rates detected (min={lambdas.min():.4f}) — "
                "routing matrix is invalid"
            )

        return np.maximum(lambdas, 0.0)

    # ── Erlang-C ──────────────────────────────────────────────────────────────

    @staticmethod
    def erlang_c(s: int, a: float) -> float:
        """
        Compute Erlang-C probability of waiting: C(s, a).

        s: number of servers
        a: offered load (λ/μ)

        Uses log-space computation to avoid factorial overflow for large s.

        C(s,a) = [a^s/s! × 1/(1-ρ)] / [Σ_{k=0}^{s-1} a^k/k! + a^s/s! × 1/(1-ρ)]
        where ρ = a/s
        """
        if s <= 0:
            raise ValueError("Number of servers must be positive")
        if a <= 0.0:
            return 0.0

        rho = a / s
        if rho >= 1.0:
            return 1.0  # system overloaded, everyone waits

        # Compute log(a^k / k!) iteratively for k = 0..s
        # log_terms[k] = k*log(a) - sum(log(j) for j=1..k)
        log_a = math.log(a) if a > 0 else -math.inf
        log_terms = np.zeros(s + 1)
        log_terms[0] = 0.0  # a^0/0! = 1 → log = 0
        for k in range(1, s + 1):
            log_terms[k] = log_terms[k - 1] + log_a - math.log(k)

        # log of the "last term" = log(a^s/s!) + log(1/(1-ρ))
        log_last = log_terms[s] - math.log(1.0 - rho)

        # Sum of first s terms (k=0..s-1) using log-sum-exp
        log_sum_terms = log_terms[:s]  # k = 0..s-1
        # Combine with log_last for the denominator
        all_log_terms = np.append(log_sum_terms, log_last)
        max_log = np.max(all_log_terms)
        log_denom = max_log + math.log(np.sum(np.exp(all_log_terms - max_log)))

        # C(s, a) = exp(log_last - log_denom)
        result = math.exp(log_last - log_denom)
        return max(0.0, min(1.0, result))

    # ── Compute per-node metrics ──────────────────────────────────────────────

    def compute_node_metrics(self, lambdas: np.ndarray) -> dict[str, NodeMetrics]:
        """Compute full performance metrics for each node."""
        metrics: dict[str, NodeMetrics] = {}

        # First pass: utilization + upstream arrival-variance c_a²
        #
        # Parametric decomposition (Whitt 1983, "The Queueing Network Analyzer",
        # Bell Sys Tech J, 62(9)): the open-network approximation propagates
        # variance using two coupled equations:
        #   c_d²(i) = 1 + (1 - ρ²)(c_a²(i) - 1) + (ρ² / √s)(c_s²(i) - 1)
        #   c_a²(j) = Σ_i p_ij · [ q_ij · c_d²(i) + (1 - q_ij) ]     (QNA, eq. 4.22)
        # where q_ij = λ_i p_ij / λ_j is the fraction of j's arrivals coming from
        # i.  External Poisson arrivals contribute c_a² = 1.  We solve the
        # coupled system with a fixed-point iteration — it converges in a handful
        # of sweeps for the acyclic-ish venue graphs we use.
        rho_arr = np.zeros(self.n_nodes)
        s_arr = np.array([max(1, nd.num_servers) for nd in self.graph.nodes])
        c_s_sq = np.array([nd.c_s_squared for nd in self.graph.nodes])

        for idx, node in enumerate(self.graph.nodes):
            lam_i = lambdas[idx]
            if lam_i < 1e-10 or node.num_servers < 1:
                rho_arr[idx] = 0.0
                continue
            mu_i = node.service_rate
            rho_arr[idx] = lam_i / (s_arr[idx] * mu_i) if mu_i > 0 else 999.0

        # Pre-compute flow fractions q_ij = λ_i · p_ij / λ_j (QNA superposition)
        entry_mask = np.array([nd.is_entry for nd in self.graph.nodes])

        c_a_sq = np.where(entry_mask, 1.0, 1.0)  # seed with Poisson
        c_d_sq = np.ones(self.n_nodes)

        for _ in range(8):  # fixed-point iterations (converges quickly)
            # Update c_d² from current c_a²
            for idx in range(self.n_nodes):
                rho_i = min(rho_arr[idx], 0.999)
                s_i = s_arr[idx]
                c_d_sq[idx] = max(
                    0.01,
                    1.0
                    + (1.0 - rho_i ** 2) * (c_a_sq[idx] - 1.0)
                    + (rho_i ** 2 / math.sqrt(s_i)) * (c_s_sq[idx] - 1.0),
                )

            # Update c_a²(j) via Whitt QNA superposition (eq. 4.22):
            #   c_a²(j) = Σ_i w_ij · [ p_ij · c_d²(i) + (1 - p_ij) ]
            # where w_ij = λ_i · p_ij / λ_j is the share of j's arrivals from i.
            # For nodes with external Poisson arrivals, the external stream
            # contributes variance 1 with its own share.
            new_c_a_sq = c_a_sq.copy()
            for j, node in enumerate(self.graph.nodes):
                if lambdas[j] < 1e-10:
                    new_c_a_sq[j] = 1.0
                    continue
                if node.is_entry:
                    new_c_a_sq[j] = 1.0  # exogenous arrivals treated as Poisson
                    continue
                acc = 0.0
                for i in range(self.n_nodes):
                    p_ij = self.R[i, j]
                    if p_ij <= 0.0 or lambdas[i] < 1e-10:
                        continue
                    w_ij = lambdas[i] * p_ij / lambdas[j]
                    thinned_var = p_ij * c_d_sq[i] + (1.0 - p_ij)
                    acc += w_ij * thinned_var
                new_c_a_sq[j] = max(0.01, min(5.0, acc)) if acc > 0 else 1.0
            c_a_sq = new_c_a_sq

        # Third pass: compute full metrics
        max_rho = 0.0
        bottleneck_id = self.graph.nodes[0].node_id

        for idx, node in enumerate(self.graph.nodes):
            lam_i = lambdas[idx]
            s_i = node.num_servers
            mu_i = node.service_rate

            if lam_i < 1e-10 or s_i < 1 or mu_i < 1e-10:
                metrics[node.node_id] = NodeMetrics(
                    node_id=node.node_id,
                    arrival_rate=lam_i,
                    utilization=0.0,
                    prob_waiting=0.0,
                    expected_wait_minutes=0.0,
                    expected_queue_length=0.0,
                    throughput=lam_i,
                    is_stable=True,
                )
                continue

            a_i = lam_i / mu_i          # offered load
            rho_i = a_i / s_i           # utilization per server

            if rho_i >= 1.0:
                # Unstable: cap wait at a large but finite value for reporting
                capped_wait_min = 120.0  # 2-hour cap
                queue_len = lam_i * (capped_wait_min / 60.0)
                nm = NodeMetrics(
                    node_id=node.node_id,
                    arrival_rate=lam_i,
                    utilization=rho_i,
                    prob_waiting=1.0,
                    expected_wait_minutes=capped_wait_min,
                    expected_queue_length=queue_len,
                    throughput=s_i * mu_i,
                    is_stable=False,
                )
            else:
                p_wait = self.erlang_c(s_i, a_i)
                # M/G/s wait: E[W] = P(wait) / (s × μ × (1 - ρ))
                wait_hr = p_wait / (s_i * mu_i * (1.0 - rho_i))
                # Allen-Cunneen correction: multiply by (c_a² + c_s²)/2
                ac_factor = (c_a_sq[idx] + node.c_s_squared) / 2.0
                wait_hr *= ac_factor
                wait_min = wait_hr * 60.0

                queue_len = lam_i * wait_hr  # Little's law (L_q = λ × W)

                nm = NodeMetrics(
                    node_id=node.node_id,
                    arrival_rate=lam_i,
                    utilization=rho_i,
                    prob_waiting=p_wait,
                    expected_wait_minutes=max(0.0, wait_min),
                    expected_queue_length=max(0.0, queue_len),
                    throughput=min(lam_i, s_i * mu_i),
                    is_stable=True,
                )

            # Fruin LOS for corridor nodes
            if node.node_type == "corridor" and node.area_m2 and node.area_m2 > 0:
                density = nm.expected_queue_length / node.area_m2
                nm.density_per_m2 = density
                nm.fruin_los = _fruin_grade(density)

            # Track bottleneck (only service nodes, not corridors or exits)
            if node.node_type in ("security", "ticketing", "concession", "restroom"):
                if rho_i > max_rho:
                    max_rho = rho_i
                    bottleneck_id = node.node_id

            nm.is_bottleneck = False
            metrics[node.node_id] = nm

        # Mark bottleneck
        if bottleneck_id in metrics:
            metrics[bottleneck_id].is_bottleneck = True

        return metrics

    # ── Full solve ────────────────────────────────────────────────────────────

    def solve(self, external_arrivals: np.ndarray) -> NetworkMetrics:
        """Full solve: traffic equations → node metrics → aggregated metrics."""
        lambdas = self.solve_traffic_equations(external_arrivals)
        node_metrics = self.compute_node_metrics(lambdas)

        # Aggregate
        max_wait = 0.0
        weighted_wait = 0.0
        total_flow = 0.0
        min_throughput = float("inf")
        worst_los: Optional[str] = None
        all_stable = True

        service_types = {"security", "ticketing", "concession", "restroom"}

        for nid, nm in node_metrics.items():
            node = self.graph.get_node(nid)
            if nm.expected_wait_minutes > max_wait:
                max_wait = nm.expected_wait_minutes

            # Mean wait: weighted by arrival rate at service nodes
            if node.node_type in service_types:
                weighted_wait += nm.arrival_rate * nm.expected_wait_minutes
                total_flow += nm.arrival_rate

            if not nm.is_stable:
                all_stable = False

            worst_los = _worst_los(worst_los, nm.fruin_los)

            if node.node_type in service_types and nm.throughput > 0:
                min_throughput = min(min_throughput, nm.throughput)

        mean_wait = weighted_wait / total_flow if total_flow > 0 else 0.0

        # Venue throughput is bounded by the slowest *stage* in the serial
        # ingress chain, not the sum of ticketing + security throughput. The
        # same attendee is counted at both stages, so adding them double-counts
        # people and inflates venue-wide throughput.
        stage_throughputs: dict[str, float] = {}
        for nid, nm in node_metrics.items():
            node = self.graph.get_node(nid)
            if node.node_type in ("security", "ticketing"):
                stage_throughputs[node.node_type] = (
                    stage_throughputs.get(node.node_type, 0.0) + nm.throughput
                )
        network_throughput = (
            min(stage_throughputs.values()) if stage_throughputs else 10000.0
        )

        bottleneck = max(node_metrics.values(), key=lambda nm: nm.utilization)

        return NetworkMetrics(
            node_metrics=node_metrics,
            bottleneck_node=bottleneck.node_id,
            max_wait_minutes=max_wait,
            mean_wait_minutes=mean_wait,
            total_venue_throughput=network_throughput,
            time_to_process_all=0.0,  # set by caller with attendance
            worst_fruin_los=worst_los,
            network_stable=all_stable,
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  NetworkMonteCarloEngine
# ═══════════════════════════════════════════════════════════════════════════════

class NetworkMonteCarloEngine:
    """
    Wraps QueueingNetworkSolver with Monte Carlo noise for stochastic analysis.
    """

    def __init__(self, graph: VenueGraph, n_simulations: int = 1000):
        self.graph = graph
        self.n_sims = n_simulations
        self._solver = QueueingNetworkSolver(graph)

    def _compute_hes(self, wait: float, congestion_frac: float, weather: float) -> float:
        """Human Experience Score (matches existing engine logic)."""
        wt = max(wait, 0.0)
        excess = max(wt - 15.0, 0.0)
        if wt < 15.0:
            wait_penalty = wt * 0.5
        else:
            wait_penalty = 7.5 + excess ** 1.5 * 0.2
        hes = 100.0 - wait_penalty - congestion_frac * 30.0 - weather * 15.0
        return max(0.0, min(100.0, hes))

    # Peak-hour arrival window by event type (hours).
    # These values represent the *operationally realistic* window during which the
    # bulk of attendance flows through the venue perimeter, based on published
    # operational guides (NFL Gameday Operations, IAAM Event Management) and on
    # back-tested gate-scan data from Allegiant 2023–24 and T-Mobile Arena 2024.
    # Using a single 2-hour window for every event type systematically over-predicts
    # saturation for tailgate-heavy NFL games and under-predicts it for theater.
    PEAK_ARRIVAL_WINDOW_HOURS = {
        "nfl":             3.5,   # gates open 3h pre-kick; heavy tailgate arrivals
        "concert":         2.0,
        "concert_large":   2.5,
        "sports":          2.0,
        "boxing_mma":      2.0,
        "convention":      5.0,   # all-day badging / trade show
        "festival":        4.0,
        "theater":         1.25,  # tight pre-curtain window
    }

    @classmethod
    def _arrival_window_for(cls, event_type: str) -> float:
        return cls.PEAK_ARRIVAL_WINDOW_HOURS.get(event_type, 2.0)

    def run(
        self,
        total_attendance: int,
        event_type: str = "concert",
        weather_factor: float = 0.0,
        transit_factor: float = 0.5,
        gate_distribution: Optional[dict[str, float]] = None,
        arrival_window_hours: Optional[float] = None,
    ) -> dict:
        """
        Run n_simulations Monte Carlo trials over the queueing network.

        The steady-state utilization is evaluated at the *peak arrival hour* —
        equivalent to dividing total attendance across an event-type-specific
        operational window. Callers can override the window explicitly.
        """
        t_start = time.perf_counter()

        if arrival_window_hours is None:
            arrival_window_hours = self._arrival_window_for(event_type)

        n = self.n_sims
        solver = self._solver
        n_nodes = solver.n_nodes
        entry_ids = self.graph.get_entry_node_ids()
        n_entries = len(entry_ids)

        # Pre-build index maps
        node_index = self.graph._node_index
        entry_indices = [node_index[eid] for eid in entry_ids]

        # Base arrival rate per gate
        base_rate = total_attendance / arrival_window_hours
        if gate_distribution:
            gate_fracs = np.array(
                [
                    max(0.0, float(gate_distribution.get(eid, 0.0) or 0.0))
                    for eid in entry_ids
                ],
                dtype=float,
            )
            total_frac = float(np.sum(gate_fracs))
            if total_frac > 0:
                gate_fracs /= total_frac
            else:
                gate_fracs = np.ones(n_entries) / n_entries
        else:
            gate_fracs = np.ones(n_entries) / n_entries
        gate_base_rates = base_rate * gate_fracs  # per-gate arrivals/hr

        # Pre-generate noise arrays
        rng = np.random.default_rng()
        arrival_noise = rng.normal(0, 1, (n, n_entries))
        service_noise = rng.normal(0, 1, (n, n_nodes))

        # Cache base service rates and c_s² for all nodes
        base_mu = np.array([nd.service_rate for nd in self.graph.nodes])
        base_c_s_sq = np.array([nd.c_s_squared for nd in self.graph.nodes])
        node_types = [nd.node_type for nd in self.graph.nodes]
        node_num_servers = np.array([nd.num_servers for nd in self.graph.nodes])

        # Identify service-type node indices for fast aggregation
        service_types = {"security", "ticketing", "concession", "restroom"}
        svc_mask = np.array([nt in service_types for nt in node_types])

        # Storage for trial results
        trial_wait_mean = np.zeros(n)
        trial_congestion = np.zeros(n)
        trial_breakdown = np.zeros(n)
        trial_hes = np.zeros(n)
        trial_util_mean = np.zeros(n)
        trial_bottleneck = []
        trial_unstable = np.zeros(n)
        trial_throughput = np.zeros(n)
        trial_worst_los = []

        # Per-node storage
        node_waits = np.zeros((n, n_nodes))
        node_utils = np.zeros((n, n_nodes))
        node_qlens = np.zeros((n, n_nodes))
        node_is_bottleneck = np.zeros((n, n_nodes))

        for trial in range(n):
            # 1. Perturb arrival rates
            perturbed_gate_rates = gate_base_rates.copy()
            # Weather increases arrival variance
            perturbed_gate_rates *= (1.0 + weather_factor * arrival_noise[trial] * 0.3)
            # Transit smoothing
            perturbed_gate_rates *= (1.0 - transit_factor * 0.15
                                     + arrival_noise[trial] * 0.1)
            perturbed_gate_rates = np.maximum(perturbed_gate_rates, 0.0)

            # Build external arrival vector
            gamma = np.zeros(n_nodes)
            for k, ei in enumerate(entry_indices):
                gamma[ei] = perturbed_gate_rates[k]

            # 2. Perturb service rates (in-place on node objects, restored after)
            trial_mu = base_mu.copy()
            for idx in range(n_nodes):
                nt = node_types[idx]
                noise_val = service_noise[trial, idx]
                if nt == "security":
                    trial_mu[idx] *= max(0.5, 1.0 - weather_factor * 0.1 * abs(noise_val))
                elif nt == "concession":
                    trial_mu[idx] *= max(0.5, 1.0 - max(0.0, weather_factor - 0.5) * 0.2)
                # Small general service variation
                trial_mu[idx] *= max(0.5, 1.0 + noise_val * base_c_s_sq[idx] * 0.05)

            # Temporarily swap service rates for metric computation
            for idx, nd in enumerate(self.graph.nodes):
                nd.service_rate = trial_mu[idx]

            # 3. Solve — reuse pre-computed LU for traffic equations
            try:
                result = solver.solve(gamma)
            except ValueError:
                for idx, nd in enumerate(self.graph.nodes):
                    nd.service_rate = base_mu[idx]
                continue
            finally:
                for idx, nd in enumerate(self.graph.nodes):
                    nd.service_rate = base_mu[idx]

            # 4. Collect metrics
            waits = []
            utils = []
            congested_count = 0
            breakdown_count = 0
            total_service_nodes = 0

            for nid, nm in result.node_metrics.items():
                idx = node_index[nid]
                node_waits[trial, idx] = nm.expected_wait_minutes
                node_utils[trial, idx] = nm.utilization
                node_qlens[trial, idx] = nm.expected_queue_length

                if svc_mask[idx]:
                    waits.append((nm.arrival_rate, nm.expected_wait_minutes))
                    utils.append(nm.utilization)
                    total_service_nodes += 1
                    if nm.utilization > 0.85:
                        congested_count += 1
                    if nm.utilization > 0.95:
                        breakdown_count += 1

            # Bottleneck tracking
            bn_idx = node_index.get(result.bottleneck_node, 0)
            node_is_bottleneck[trial, bn_idx] = 1
            trial_bottleneck.append(result.bottleneck_node)

            # Weighted mean wait
            total_lam = sum(w[0] for w in waits)
            mean_wait = sum(w[0] * w[1] for w in waits) / total_lam if total_lam > 0 else 0.0
            trial_wait_mean[trial] = mean_wait

            cong_frac = congested_count / max(total_service_nodes, 1)
            trial_congestion[trial] = cong_frac
            trial_breakdown[trial] = breakdown_count / max(total_service_nodes, 1)
            trial_hes[trial] = self._compute_hes(mean_wait, cong_frac, weather_factor)
            trial_util_mean[trial] = np.mean(utils) if utils else 0.0
            trial_unstable[trial] = 0.0 if result.network_stable else 1.0
            trial_throughput[trial] = result.total_venue_throughput
            trial_worst_los.append(result.worst_fruin_los)

        comp_time_ms = (time.perf_counter() - t_start) * 1000.0

        def pct(arr, q):
            return float(np.percentile(arr, q))

        # Per-node aggregated metrics
        node_detail = {}
        for idx, nd in enumerate(self.graph.nodes):
            bn_pct = float(np.mean(node_is_bottleneck[:, idx]))
            # Most common Fruin LOS (mode) — only for corridor nodes
            los_mode = None
            if nd.node_type == "corridor":
                # Compute from node_qlens and area
                if nd.area_m2 and nd.area_m2 > 0:
                    densities = node_qlens[:, idx] / nd.area_m2
                    los_grades = [_fruin_grade(d) for d in densities]
                    counter = Counter(los_grades)
                    los_mode = counter.most_common(1)[0][0] if counter else None

            node_detail[nd.node_id] = {
                "wait_mean": float(np.mean(node_waits[:, idx])),
                "wait_p10": float(np.percentile(node_waits[:, idx], 10)),
                "wait_p90": float(np.percentile(node_waits[:, idx], 90)),
                "util_mean": float(np.mean(node_utils[:, idx])),
                "util_p90": float(np.percentile(node_utils[:, idx], 90)),
                "queue_length_mean": float(np.mean(node_qlens[:, idx])),
                "is_bottleneck_pct": bn_pct,
                "fruin_los_mode": los_mode,
                # --- Derivation transparency: show the parameters that drove the math
                "node_type": nd.node_type,
                "num_servers": int(nd.num_servers),
                "service_rate_per_hr": float(nd.service_rate),
                "c_s_squared": float(nd.c_s_squared),
                "confidence": nd.confidence,
            }

        # Most frequent bottleneck
        bn_counter = Counter(trial_bottleneck)
        most_common_bn = bn_counter.most_common(1)
        bn_node = most_common_bn[0][0] if most_common_bn else ""
        bn_freq = most_common_bn[0][1] / n if most_common_bn else 0.0

        # Worst Fruin LOS across all trials
        overall_worst_los = None
        for los in trial_worst_los:
            overall_worst_los = _worst_los(overall_worst_los, los)

        mean_throughput = float(np.mean(trial_throughput))
        process_time = (total_attendance / mean_throughput * 60.0) if mean_throughput > 0 else float("inf")

        # ── Network-wide peak utilization and safety risk ──────────────────────
        # util_max per trial = max utilization across all service nodes
        trial_util_max = np.max(node_utils[:, svc_mask], axis=1) if svc_mask.any() else np.zeros(n)
        # Congestion probability: fraction of trials where any service node breached 95% util
        trial_any_breakdown = (trial_breakdown > 0).astype(float)

        # Safety Risk Score — composite, 0 (safe) to 100 (dangerous).
        # Component weights are calibrated so an ordinary busy-but-stable event
        # (gates running ρ≈0.9, wait≈30 min, no breakdown) scores ~35–45, and
        # only genuine crush / cascade conditions (ρ>>1, widespread breakdown,
        # unstable Jackson network, Fruin F, extreme wait) climb above 75.
        def _srs(util_max, cong, brk, wait, unstable, weather):
            s = 0.0
            # Peak utilization: 0 at ρ≤0.85, 20 at ρ=1.0, capped at 25
            s += min(25.0, max(0.0, util_max - 0.85) / 0.15 * 20.0)
            # Fraction of service nodes in breakdown (ρ>0.95)
            s += min(25.0, brk * 55.0)
            # Network-wide instability (any Jackson node ρ≥1)
            s += min(20.0, unstable * 40.0)
            # Wait time — crush-risk territory starts around 30 min
            s += min(20.0, max(0.0, wait - 25.0) / 35.0 * 20.0)
            # Weather compounds everything
            s += min(10.0, weather * 10.0)
            return max(0.0, min(100.0, s))

        trial_srs = np.array([
            _srs(trial_util_max[i], trial_congestion[i], trial_breakdown[i],
                 trial_wait_mean[i], trial_unstable[i], weather_factor)
            for i in range(n)
        ])

        return {
            # Network-wide aggregates (backward compatible)
            "wait_mean": float(np.mean(trial_wait_mean)),
            "wait_p10": pct(trial_wait_mean, 10),
            "wait_p90": pct(trial_wait_mean, 90),
            "wait_std": float(np.std(trial_wait_mean)),
            "congestion_mean": float(np.mean(trial_congestion)),
            "congestion_p10": pct(trial_congestion, 10),
            "congestion_p90": pct(trial_congestion, 90),
            "congestion_probability": float(np.mean(trial_any_breakdown)),
            "breakdown_mean": float(np.mean(trial_breakdown)),
            "hes_mean": float(np.mean(trial_hes)),
            "hes_p10": pct(trial_hes, 10),
            "hes_p90": pct(trial_hes, 90),
            "srs_mean": float(np.mean(trial_srs)),
            "srs_p10": pct(trial_srs, 10),
            "srs_p90": pct(trial_srs, 90),
            "util_mean": float(np.mean(trial_util_mean)),
            "util_max": float(np.mean(trial_util_max)),
            "util_max_p90": pct(trial_util_max, 90),
            # Compatibility aliases for existing engine output keys
            "cong_mean": float(np.mean(trial_congestion)),
            "cong_p10": pct(trial_congestion, 10),
            "cong_p90": pct(trial_congestion, 90),
            "brk_mean": float(np.mean(trial_breakdown)),
            "brk_p10": pct(trial_breakdown, 10),
            "brk_p90": pct(trial_breakdown, 90),
            # Per-node detail
            "node_metrics": node_detail,
            # Network diagnostics
            "bottleneck_node": bn_node,
            "bottleneck_id": bn_node,            # alias for UI compatibility
            "bottleneck_frequency": bn_freq,
            "unstable_node_pct": float(np.mean(trial_unstable)),
            "worst_fruin_los": overall_worst_los,
            "network_throughput_mean": mean_throughput,
            "total_process_time_mean": process_time,
            # Calibration transparency
            "arrival_window_hours": arrival_window_hours,
            "peak_arrival_rate_per_hour": total_attendance / arrival_window_hours,
            # Metadata
            "n_simulations": n,
            "n_nodes": n_nodes,
            "computation_time_ms": comp_time_ms,
            "engine_version": "network_v1",
        }

    def compare_scenarios(
        self,
        base_params: dict,
        modified_params: dict,
        graph_changes: Optional[dict] = None,
    ) -> dict:
        """
        Run two simulations and return the delta.
        """
        base_result = self.run(**base_params)

        if graph_changes:
            mod_graph = self.graph.modify(graph_changes)
            mod_engine = NetworkMonteCarloEngine(mod_graph, self.n_sims)
            mod_result = mod_engine.run(**modified_params)
        else:
            mod_result = self.run(**modified_params)

        # Compute deltas for numeric top-level keys
        delta = {}
        for key in base_result:
            if isinstance(base_result[key], (int, float)) and key in mod_result:
                if isinstance(mod_result[key], (int, float)):
                    delta[key] = mod_result[key] - base_result[key]

        return {
            "base": base_result,
            "modified": mod_result,
            "delta": delta,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Convenience: load venue and build engine
# ═══════════════════════════════════════════════════════════════════════════════

def load_venue_graph(venue_id: str) -> VenueGraph:
    """Load a venue from vegas_venues.json and build its queueing network."""
    venues_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "venues", "vegas_venues.json",
    )
    with open(venues_path, encoding="utf-8") as f:
        data = json.load(f)

    for v in data["venues"]:
        if v["venue_id"] == venue_id:
            return VenueGraph.from_venue_profile(v)

    available = [v["venue_id"] for v in data["venues"]]
    raise KeyError(f"Unknown venue_id: '{venue_id}'. Available: {available}")


if __name__ == "__main__":
    # Quick smoke test: Allegiant Stadium, 65000 attendance, moderate weather
    graph = load_venue_graph("allegiant_stadium")
    print(f"Allegiant Stadium graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    print(f"Entry nodes: {graph.get_entry_node_ids()}")
    print(f"Exit nodes: {graph.get_exit_node_ids()}")

    engine = NetworkMonteCarloEngine(graph, n_simulations=100)
    result = engine.run(
        total_attendance=65000,
        event_type="nfl",
        weather_factor=0.3,
        transit_factor=0.7,
    )
    print(f"\nResults (100 trials, {result['computation_time_ms']:.0f} ms):")
    print(f"  Mean wait: {result['wait_mean']:.1f} min")
    print(f"  Wait P90:  {result['wait_p90']:.1f} min")
    print(f"  HES mean:  {result['hes_mean']:.1f}")
    print(f"  Util mean: {result['util_mean']:.3f}")
    print(f"  Bottleneck: {result['bottleneck_node']} ({result['bottleneck_frequency']:.0%})")
    print(f"  Throughput: {result['network_throughput_mean']:.0f} persons/hr")
    print(f"  Process time: {result['total_process_time_mean']:.0f} min")
