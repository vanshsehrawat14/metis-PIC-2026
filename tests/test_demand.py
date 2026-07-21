"""
tests/test_demand.py - Regression tests for ticket-price turnout feasibility.
"""

import os
import sys


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from simulation.demand import resolve_ticket_demand


def test_missing_price_does_not_apply_demand_model():
    result = resolve_ticket_demand(
        requested_attendance=55000,
        venue_capacity=65000,
        event_type="nfl",
        avg_ticket_price=None,
        capacity_basis="football",
    )
    assert result["model_applied"] is False
    assert result["effective_attendance"] == 55000
    assert result["pricing_posture"] == "not_applied"


def test_high_price_reduces_effective_attendance():
    result = resolve_ticket_demand(
        requested_attendance=65000,
        venue_capacity=65000,
        event_type="concert",
        avg_ticket_price=10000,
        capacity_basis="concert_with_floor",
    )
    assert result["model_applied"] is True
    assert result["price_is_binding"] is True
    assert result["effective_attendance"] < result["requested_attendance"]
    assert result["attendance_delta_due_to_price"] > 0


def test_low_price_never_creates_attendance_above_request():
    result = resolve_ticket_demand(
        requested_attendance=22000,
        venue_capacity=65000,
        event_type="concert",
        avg_ticket_price=10,
        capacity_basis="concert_with_floor",
    )
    assert result["model_applied"] is True
    assert result["effective_attendance"] == 22000
    assert result["price_is_binding"] is False


def test_price_to_support_requested_attendance_moves_below_binding_price():
    result = resolve_ticket_demand(
        requested_attendance=55000,
        venue_capacity=65000,
        event_type="concert",
        avg_ticket_price=350,
        capacity_basis="concert_with_floor",
    )
    assert result["price_is_binding"] is True
    assert result["price_to_support_requested_attendance"] is not None
    assert result["price_to_support_requested_attendance"] < result["avg_ticket_price"]
