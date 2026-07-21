"""
simulation/demand.py - Ticket-price turnout feasibility layer.

This module keeps the demand logic explicit and auditable:
the user requests a turnout, then the model checks whether that turnout is
supportable at the stated average ticket price for the venue/event class.

The output is a demand envelope, not a claim that we know the market-clearing
price for every event. All priors here are labeled calibrated heuristics.
"""

from __future__ import annotations

from typing import Any


_MODEL_VERSION = "price_fill_ceiling_v1"


_EVENT_TYPE_PRIORS: dict[str, dict[str, float]] = {
    "nfl": {
        "reference_price": 180.0,
        "reference_fill": 0.97,
        "elasticity": 0.45,
        "fill_floor": 0.05,
    },
    "concert": {
        "reference_price": 120.0,
        "reference_fill": 0.88,
        "elasticity": 0.75,
        "fill_floor": 0.03,
    },
    "concert_large": {
        "reference_price": 150.0,
        "reference_fill": 0.90,
        "elasticity": 0.65,
        "fill_floor": 0.03,
    },
    "sports": {
        "reference_price": 90.0,
        "reference_fill": 0.85,
        "elasticity": 0.60,
        "fill_floor": 0.04,
    },
    "boxing_mma": {
        "reference_price": 175.0,
        "reference_fill": 0.80,
        "elasticity": 0.85,
        "fill_floor": 0.03,
    },
    "convention": {
        "reference_price": 60.0,
        "reference_fill": 0.70,
        "elasticity": 0.30,
        "fill_floor": 0.08,
    },
    "festival": {
        "reference_price": 220.0,
        "reference_fill": 0.85,
        "elasticity": 0.75,
        "fill_floor": 0.04,
    },
    "theater": {
        "reference_price": 95.0,
        "reference_fill": 0.75,
        "elasticity": 0.95,
        "fill_floor": 0.03,
    },
}


_DEFAULT_PRIOR = {
    "reference_price": 95.0,
    "reference_fill": 0.80,
    "elasticity": 0.65,
    "fill_floor": 0.04,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _as_positive_int(value: Any, fallback: int = 0) -> int:
    try:
        out = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(0, out)


def _as_bounded_price(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = 95.0
    return _clamp(out, 5.0, 10000.0)


def demand_prior(event_type: str | None) -> dict[str, Any]:
    row = dict(_DEFAULT_PRIOR)
    if event_type and event_type in _EVENT_TYPE_PRIORS:
        row.update(_EVENT_TYPE_PRIORS[event_type])
    row["event_type"] = event_type or "generic"
    row["model_version"] = _MODEL_VERSION
    return row


def resolve_ticket_demand(
    *,
    requested_attendance: int,
    venue_capacity: int,
    event_type: str | None,
    avg_ticket_price: float | None,
    capacity_basis: str | None = None,
) -> dict[str, Any]:
    """
    Convert requested attendance into effective attendance when ticket price is known.

    Policy:
    - If avg_ticket_price is omitted, do not apply a turnout correction.
    - If price is supplied, compute a price-implied fill ceiling and simulate on
      the feasible turnout.
    - Cheap prices never create attendance beyond what the user requested.
    """

    requested = _as_positive_int(requested_attendance)
    capacity = max(_as_positive_int(venue_capacity, fallback=requested or 1), 1)
    prior = demand_prior(event_type)

    result: dict[str, Any] = {
        "model_applied": False,
        "requested_attendance": requested,
        "effective_attendance": requested,
        "attendance_delta_due_to_price": 0,
        "attendance_delta_due_to_capacity": max(0, requested - capacity),
        "attendance_delta_total": 0,
        "price_implied_attendance_cap": requested,
        "venue_capacity_used": capacity,
        "capacity_basis": capacity_basis or "unknown",
        "requested_fill_rate": requested / capacity if capacity > 0 else 0.0,
        "price_implied_fill_rate": None,
        "price_is_binding": False,
        "capacity_is_binding": requested > capacity,
        "avg_ticket_price": avg_ticket_price,
        "price_to_support_requested_attendance": None,
        "ticket_revenue_requested": None,
        "ticket_revenue_effective": None,
        "ticket_revenue_delta": None,
        "pricing_posture": "not_applied",
        "pricing_recommendation": None,
        "demand_prior": prior,
        "provenance": {
            "model": _MODEL_VERSION,
            "kind": "calibrated_heuristic",
            "applied": False,
            "formula": (
                "fill_price = clamp(fill_ref * (P / P_ref)^(-epsilon), fill_floor, 1.0); "
                "N_eff = min(N_req, capacity, capacity * fill_price)"
            ),
            "note": (
                "Turnout feasibility is only applied when avg_ticket_price is supplied. "
                "Without a price, the engine preserves requested attendance."
            ),
            "capacity_basis": capacity_basis or "unknown",
            "prior": prior,
        },
    }

    if avg_ticket_price is None:
        result["attendance_delta_total"] = max(0, requested - result["effective_attendance"])
        return result

    price = _as_bounded_price(avg_ticket_price)
    reference_price = float(prior["reference_price"])
    reference_fill = float(prior["reference_fill"])
    elasticity = float(prior["elasticity"])
    fill_floor = float(prior["fill_floor"])

    requested_fill = requested / capacity if capacity > 0 else 0.0
    price_ratio = max(price / max(reference_price, 1.0), 0.01)
    raw_fill = reference_fill * (price_ratio ** (-elasticity))
    price_implied_fill = _clamp(raw_fill, fill_floor, 1.0)
    price_implied_attendance = int(round(capacity * price_implied_fill))

    capacity_limited_attendance = min(requested, capacity)
    effective_attendance = min(capacity_limited_attendance, price_implied_attendance)
    capacity_delta = max(0, requested - capacity_limited_attendance)
    price_delta = max(0, capacity_limited_attendance - effective_attendance)

    price_to_support_requested = None
    if 0.0 < requested_fill <= 1.0:
        target_fill = max(requested_fill, fill_floor)
        price_to_support_requested = reference_price * (
            reference_fill / max(target_fill, 1e-6)
        ) ** (1.0 / max(elasticity, 1e-6))
        price_to_support_requested = _clamp(price_to_support_requested, 5.0, 10000.0)

    ticket_revenue_requested = requested * price
    ticket_revenue_effective = effective_attendance * price
    ticket_revenue_delta = ticket_revenue_effective - ticket_revenue_requested

    pricing_posture = "aligned"
    pricing_recommendation = None
    if capacity_delta > 0:
        pricing_posture = "capacity_capped"
        pricing_recommendation = (
            f"Requested attendance exceeds the {capacity_basis or 'configured'} capacity "
            f"of {capacity:,}. Ticket price cannot clear more than the sellable limit."
        )
    elif price_delta > 0 and price_to_support_requested is not None:
        pricing_posture = "constrained"
        pricing_recommendation = (
            f"Average ticket price of ${price:,.0f} is suppressing turnout. "
            f"The model supports about {effective_attendance:,} attendees at this price; "
            f"to support {requested:,}, keep average face value near "
            f"${price_to_support_requested:,.0f} or lower."
        )
    elif (
        price_to_support_requested is not None
        and price < price_to_support_requested * 0.85
    ):
        pricing_posture = "headroom"
        pricing_recommendation = (
            f"Current average ticket price of ${price:,.0f} sits below the model-clearing "
            f"price for {requested:,} attendees. You likely have pricing headroom toward "
            f"${price_to_support_requested:,.0f} while preserving the requested turnout."
        )
    else:
        pricing_recommendation = (
            f"Current average ticket price of ${price:,.0f} is aligned with the requested "
            f"turnout envelope for this venue and event class."
        )

    result.update({
        "model_applied": True,
        "requested_attendance": requested,
        "effective_attendance": effective_attendance,
        "attendance_delta_due_to_price": price_delta,
        "attendance_delta_due_to_capacity": capacity_delta,
        "attendance_delta_total": requested - effective_attendance,
        "price_implied_attendance_cap": price_implied_attendance,
        "requested_fill_rate": requested_fill,
        "price_implied_fill_rate": price_implied_fill,
        "price_is_binding": price_delta > 0,
        "capacity_is_binding": capacity_delta > 0,
        "avg_ticket_price": price,
        "price_to_support_requested_attendance": price_to_support_requested,
        "ticket_revenue_requested": ticket_revenue_requested,
        "ticket_revenue_effective": ticket_revenue_effective,
        "ticket_revenue_delta": ticket_revenue_delta,
        "pricing_posture": pricing_posture,
        "pricing_recommendation": pricing_recommendation,
        "provenance": {
            "model": _MODEL_VERSION,
            "kind": "calibrated_heuristic",
            "applied": True,
            "formula": (
                "fill_price = clamp(fill_ref * (P / P_ref)^(-epsilon), fill_floor, 1.0); "
                "N_eff = min(N_req, capacity, capacity * fill_price)"
            ),
            "note": (
                "Price affects feasible turnout as a ceiling on sell-through, not as a claim "
                "that we know the full market demand curve for the event."
            ),
            "capacity_basis": capacity_basis or "unknown",
            "prior": prior,
        },
    })
    return result
