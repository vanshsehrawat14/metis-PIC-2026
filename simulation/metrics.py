"""
simulation/metrics.py — Standalone metrics computation layer.

Takes raw simulation output from the network engine (simulation/network.py) and
temporal engine (simulation/temporal.py) and produces operationally meaningful
scores for safety, experience, revenue, and Fruin LOS.

Classes:
  FruinLOS         — Fruin Level of Service (HCM6 / Fruin 1971)
  RevenueImpact    — Dollar-value impact from operational metrics
  SafetyRiskScore  — Composite safety risk (crush / flow / evacuation)
  EnhancedHES      — Multi-factor Human Experience Score (0-100)

Function:
  compute_full_metrics() — Master aggregator for API / LLM consumption

Sources:
  Fruin, J.J. (1971). "Pedestrian Planning and Design."
  Highway Capacity Manual, 6th Edition (2016), Chapter 24.
  Predtechenskii & Milinskii (1978). "Planning for Foot Traffic Flow in Buildings."
  NFPA 101 Life Safety Code.
  HSE (UK) crowd density guidelines.
  Helbing et al. (2007). "Dynamics of crowd disasters."
  NAC 2023 benchmarks; Technomic venue foodservice reports.
"""

from __future__ import annotations

import math
from collections import Counter


# ═══════════════════════════════════════════════════════════════════════════════
#  FruinLOS
# ═══════════════════════════════════════════════════════════════════════════════

class FruinLOS:
    """
    Fruin Level of Service computation for pedestrian spaces.

    Reference: Fruin, J.J. (1971). "Pedestrian Planning and Design."
    Updated thresholds from Highway Capacity Manual, 6th Edition (2016).

    Grades are based on pedestrian density (persons per square meter):
      A: d < 0.31  — Free flow. Walk at desired speed, no conflicts.
      B: 0.31 <= d < 0.43 — Minor conflicts. Slightly restricted speed.
      C: 0.43 <= d < 0.72 — Restricted movement. Limited ability to pass slower pedestrians.
      D: 0.72 <= d < 1.08 — Severely restricted. No passing possible. Frequent speed changes.
      E: 1.08 <= d < 2.17 — Walking at shuffle pace. Unavoidable body contact.
      F: d >= 2.17 — Crush conditions. No movement possible. Risk of injury/death.

    Also computes walking speed degradation as a function of density:
      v(d) = v_free * max(0.1, 1 - 0.35 * d)  for d < 2.17
      v(d) = 0  for d >= 2.17 (no movement in crush)

      where v_free = 1.2 m/s (HCM6 standard for mixed-age pedestrian population)

    Source: HCM6 Chapter 24; Fruin (1971); Predtechenskii & Milinskii (1978).
    """

    THRESHOLDS = {
        "A": (0.0, 0.31),
        "B": (0.31, 0.43),
        "C": (0.43, 0.72),
        "D": (0.72, 1.08),
        "E": (1.08, 2.17),
        "F": (2.17, float("inf")),
    }

    FREE_FLOW_SPEED_MS = 1.2  # m/s, HCM6 standard

    MODIFIERS = {
        "stairway": 0.6,       # speed multiplier for stairs
        "ramp": 0.85,          # speed multiplier for ramps
        "counter_flow": 0.7,   # speed multiplier when bidirectional flow
    }

    @staticmethod
    def grade(density_per_m2: float) -> str:
        """Return Fruin LOS grade A-F for given density."""
        if density_per_m2 < 0.31:
            return "A"
        if density_per_m2 < 0.43:
            return "B"
        if density_per_m2 < 0.72:
            return "C"
        if density_per_m2 < 1.08:
            return "D"
        if density_per_m2 < 2.17:
            return "E"
        return "F"

    @staticmethod
    def walking_speed(density_per_m2: float, modifier: str = None) -> float:
        """Return walking speed in m/s at given density, with optional modifier."""
        if density_per_m2 >= 2.17:
            return 0.0

        speed = FruinLOS.FREE_FLOW_SPEED_MS * max(0.1, 1.0 - 0.35 * density_per_m2)

        if modifier and modifier in FruinLOS.MODIFIERS:
            speed *= FruinLOS.MODIFIERS[modifier]

        return speed

    @staticmethod
    def is_dangerous(density_per_m2: float) -> bool:
        """Return True if density is at or approaching crush conditions (LOS E or F)."""
        return density_per_m2 >= 1.08

    @staticmethod
    def grade_description(grade: str) -> str:
        """Return human-readable description for ops managers, not engineers."""
        descriptions = {
            "A": "Free flow — no congestion issues",
            "B": "Light congestion — minor slowdowns, no action needed",
            "C": "Moderate congestion — noticeable crowding, monitor closely",
            "D": "Heavy congestion — movement severely restricted, consider intervention",
            "E": "Critical crowding — shuffle pace, body contact, intervene immediately",
            "F": "CRUSH RISK — movement stopped, immediate danger, emergency protocols",
        }
        return descriptions.get(grade, "Unknown")


# ═══════════════════════════════════════════════════════════════════════════════
#  Event-type priors for *revenue benchmarks* (not for queueing — that is already
#  event-aware in `network.py` and `temporal.py`).  Modest multipliers (≈0.78–1.14)
#  on NAC/Technomic *midpoints* so a theater and an NFL game do not claim the
#  same per-capita attach.  Literature-informed category judgment, not POS data.
#  Unknown event_type → unity.  See `RevenueImpact.__init__` + provenance.
# ═══════════════════════════════════════════════════════════════════════════════
_EVENT_TYPE_REVENUE_BENCHMARK_MULTS: dict[str, dict[str, float | str]] = {
    "nfl": {
        "concession_per_capita": 0.92,
        "merchandise_per_capita": 1.10,
        "rationale": "Tailgating displaces in-bowl F&B; very high team / apparel merch.",
    },
    "concert": {
        "concession_per_capita": 1.07,
        "merchandise_per_capita": 1.0,
        "rationale": "Long dwell and bar/food; artist merch at industry norm.",
    },
    "concert_large": {
        "concession_per_capita": 1.10,
        "merchandise_per_capita": 0.98,
        "rationale": "Stadium-scale shows; F&B very high, merch split across vendors.",
    },
    "sports": {
        "concession_per_capita": 0.95,
        "merchandise_per_capita": 1.08,
        "rationale": "More in-venue eating than tailgate-heavy NFL; strong team retail.",
    },
    "boxing_mma": {
        "concession_per_capita": 1.04,
        "merchandise_per_capita": 0.94,
        "rationale": "Beverage-heavy night events; less apparel than league sports.",
    },
    "convention": {
        "concession_per_capita": 1.12,
        "merchandise_per_capita": 1.10,
        "rationale": "All-day floor traffic; exhibitor and badge-holder capture.",
    },
    "festival": {
        "concession_per_capita": 1.12,
        "merchandise_per_capita": 1.04,
        "rationale": "Extended outdoor/multi-stage; high vendor F&B mix.",
    },
    "theater": {
        "concession_per_capita": 0.82,
        "merchandise_per_capita": 0.78,
        "rationale": "Short intermission, seated show; lower attach than sports/arena pop.",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
#  RevenueImpact
# ═══════════════════════════════════════════════════════════════════════════════

class RevenueImpact:
    """
    Revenue impact model linking operational metrics to dollar outcomes.

    Models three revenue streams affected by venue operations:
    1. Concession revenue — directly impacted by concession wait times
    2. Merchandise revenue — impacted by general congestion (can't browse if packed)
    3. Future ticket revenue — impacted by overall experience (HES drives repeat purchase)

    **Where the numbers come from (honest data lineage):**

    - **Industry benchmarks (static, not live API):** Default per-capita spend,
      purchase probabilities, and anchor ticket price are midpoints informed by
      NAC / Technomic-style venue foodservice surveys — the same class of
      figures finance teams use for pro-formas. They are *not* pulled from
      your venue's POS or from a regression on "similar events" in a database.
    - **Live from the simulation:** Concession wait (from queueing nodes),
      corridor-density proxy for merch, and HES for the repeat-ticket term.
      These are the rigorous parts — they come from the Monte Carlo network
      engine, not from an LLM guess.
    - **Ticket price:** User-supplied average face value. It scales *future*
      ticket revenue linearly (count of repeat attendees × price). For
      concession/merch *baselines*, we apply a **sublinear** spend-tier
      multiplier (P/P_anchor)^α with α<1 so premium events don't double
      claimed secondary spend when price doubles — a documented elasticity
      heuristic, not econometric panel data.

    If we ever integrate historical sales or ticket comps, that belongs here
    with an explicit `kind: "client_data"` line in `provenance`.
    """

    DEFAULTS = {
        "concession_per_capita": 35.0,
        "merchandise_per_capita": 8.0,
        "purchase_probability": 0.62,
        "merch_purchase_probability": 0.15,
        "repeat_ticket_base_probability": 0.45,
        "average_ticket_price": 95.0,
    }

    # Anchor for NAC-style defaults; also the neutral point where spend tier = 1.0.
    _ANCHOR_TICKET_USD = 95.0
    # Sublinear elasticity: premium tickets → higher secondary spend, but not 1:1.
    _SPEND_TIER_EXPONENT = 0.42
    _SPEND_TIER_CLAMP = (0.65, 1.45)

    @staticmethod
    def _clean_money(value: float, threshold: float = 0.5) -> float:
        """Zero out floating-point dust so the UI doesn't show phantom pennies."""
        value = float(value)
        return 0.0 if abs(value) < threshold else value

    def __init__(
        self,
        venue_capacity: int,
        custom_params: dict = None,
        event_type: str | None = None,
    ):
        self.venue_capacity = venue_capacity
        self.params = self.DEFAULTS.copy()
        if custom_params:
            self.params.update(custom_params)
        self._event_type: str | None = event_type
        self._event_revenue_priors: dict | None = None
        if event_type:
            row = _EVENT_TYPE_REVENUE_BENCHMARK_MULTS.get(
                event_type,
                {
                    "concession_per_capita": 1.0,
                    "merchandise_per_capita": 1.0,
                    "rationale": (
                        f"Event type '{event_type}' has no dedicated row — "
                        "unity multipliers on NAC/Technomic midpoints."
                    ),
                },
            )
            self._event_revenue_priors = {
                "concession_per_capita": float(row["concession_per_capita"]),
                "merchandise_per_capita": float(row["merchandise_per_capita"]),
                "rationale": str(row.get("rationale", "")),
            }
            self.params["concession_per_capita"] *= self._event_revenue_priors["concession_per_capita"]
            self.params["merchandise_per_capita"] *= self._event_revenue_priors["merchandise_per_capita"]

    def _spend_tier_multiplier(self) -> float:
        """
        Scale concession/merch *baseline* dollars by ticket-price tier vs anchor.

        τ = clamp( (P / P_anchor)^α , [τ_min, τ_max] )

        Rationale: empirical studies and venue reports show positive correlation
        between face-value tier and in-venue attach — we use sublinear α so the
        model does not claim that doubling ticket price doubles beer sales.

        This is a **calibrated heuristic**, not a fitted coefficient from your
        historical P&L. See `provenance` on the revenue object.
        """
        p = float(self.params.get("average_ticket_price", self._ANCHOR_TICKET_USD))
        if p <= 0:
            p = self._ANCHOR_TICKET_USD
        raw = (p / self._ANCHOR_TICKET_USD) ** self._SPEND_TIER_EXPONENT
        lo, hi = self._SPEND_TIER_CLAMP
        return max(lo, min(hi, raw))

    def concession_revenue_impact(
        self,
        concession_wait_minutes: float,
        attendance: int,
        *,
        spend_tier_multiplier: float | None = None,
    ) -> dict:
        """
        Compute concession revenue and loss due to wait times.

        Model:
          s' = concession_per_capita * τ   (τ = spend tier from ticket price)
          base_revenue = attendance * purchase_probability * s'
          wait_penalty = max(0.2, 1 - 0.08 * wait_minutes)
          actual_revenue = base_revenue * wait_penalty
        """
        p = self.params
        tier = spend_tier_multiplier if spend_tier_multiplier is not None else self._spend_tier_multiplier()
        pc_eff = p["concession_per_capita"] * tier
        base_revenue = attendance * p["purchase_probability"] * pc_eff
        wait_penalty = max(0.2, 1.0 - 0.08 * concession_wait_minutes)
        actual_revenue = base_revenue * wait_penalty
        lost_revenue = self._clean_money(base_revenue - actual_revenue)
        loss_pct = (lost_revenue / base_revenue * 100.0) if base_revenue > 0 else 0.0

        if loss_pct < 5.0:
            recommendation = "Concession operations are efficient. No action needed."
        elif loss_pct < 15.0:
            # Estimate additional registers to hit 3-min wait
            extra = max(1, int(math.ceil((concession_wait_minutes - 3.0) * 2)))
            recommendation = (
                f"Moderate revenue leakage from concession wait times. "
                f"Consider adding {extra} registers to recover "
                f"${lost_revenue:,.0f} per event."
            )
        elif loss_pct < 30.0:
            recommendation = (
                "Significant revenue loss. Current wait times are driving "
                "attendees away from concessions. Recommend staffing increase."
            )
        else:
            recommendation = (
                "Critical revenue loss. Concession infrastructure is severely "
                "undersized for this attendance level."
            )

        return {
            "base_revenue": base_revenue,
            "actual_revenue": actual_revenue,
            "lost_revenue": lost_revenue,
            "loss_percentage": loss_pct,
            "wait_minutes": concession_wait_minutes,
            "recommendation": recommendation,
            "spend_tier_multiplier": tier,
            "effective_concession_per_capita": pc_eff,
        }

    def merchandise_revenue_impact(
        self,
        mean_corridor_density: float,
        attendance: int,
        *,
        spend_tier_multiplier: float | None = None,
    ) -> dict:
        """
        Compute merch revenue impact from corridor congestion.

        Model:
          s' = merchandise_per_capita * τ   (same τ as concessions)
          base_revenue = attendance * merch_purchase_probability * s'
          density_penalty = max(0.3, 1 - 0.5 * max(0, density - 0.43))
          Merch browsing drops sharply once corridors exceed LOS C.
        """
        p = self.params
        tier = spend_tier_multiplier if spend_tier_multiplier is not None else self._spend_tier_multiplier()
        pc_eff = p["merchandise_per_capita"] * tier
        base_revenue = attendance * p["merch_purchase_probability"] * pc_eff
        density_penalty = max(0.3, 1.0 - 0.5 * max(0.0, mean_corridor_density - 0.43))
        actual_revenue = base_revenue * density_penalty
        lost_revenue = self._clean_money(base_revenue - actual_revenue)
        loss_pct = (lost_revenue / base_revenue * 100.0) if base_revenue > 0 else 0.0

        if loss_pct < 5.0:
            recommendation = "Corridor congestion is not impacting merchandise sales."
        elif loss_pct < 20.0:
            recommendation = (
                "Moderate merch revenue loss from corridor crowding. "
                "Consider relocating merch stands to less congested areas."
            )
        else:
            recommendation = (
                "Significant merch revenue loss. Corridor density is suppressing "
                "browse-and-buy behavior. Consider flow management interventions."
            )

        return {
            "base_revenue": base_revenue,
            "actual_revenue": actual_revenue,
            "lost_revenue": lost_revenue,
            "loss_percentage": loss_pct,
            "corridor_density": mean_corridor_density,
            "recommendation": recommendation,
            "spend_tier_multiplier": tier,
            "effective_merchandise_per_capita": pc_eff,
        }

    def future_ticket_impact(self, hes_score: float, attendance: int) -> dict:
        """
        Estimate future ticket revenue impact from current event experience.

        Model:
          repeat_probability = base * (hes / 70)^1.5, capped at 1.0
          Compare against baseline (HES=70) to compute delta.
        """
        p = self.params
        base_prob = p["repeat_ticket_base_probability"]
        ticket_price = p["average_ticket_price"]

        hes_ratio = max(hes_score, 0.0) / 70.0
        repeat_prob = min(1.0, base_prob * hes_ratio ** 1.5)
        baseline_prob = base_prob  # HES=70 → ratio=1.0 → prob = base

        expected_repeat = int(attendance * repeat_prob)
        baseline_repeat = int(attendance * baseline_prob)

        future_revenue = expected_repeat * ticket_price
        baseline_revenue = baseline_repeat * ticket_price
        delta = future_revenue - baseline_revenue

        if delta >= 0:
            recommendation = (
                f"Positive experience impact: {expected_repeat - baseline_repeat:+d} "
                f"additional repeat attendees projected (${delta:+,.0f})."
            )
        else:
            recommendation = (
                f"Negative experience impact: {expected_repeat - baseline_repeat:+d} "
                f"fewer repeat attendees projected (${delta:+,.0f}). "
                f"Improving HES would recover future ticket revenue."
            )

        return {
            "repeat_probability": repeat_prob,
            "baseline_repeat_probability": baseline_prob,
            "expected_repeat_attendees": expected_repeat,
            "baseline_repeat_attendees": baseline_repeat,
            "future_revenue_impact": delta,
            "recommendation": recommendation,
        }

    def _build_provenance(self, spend_tier: float) -> dict:
        """Structured lineage for API + UI — what is benchmark, sim, or heuristic."""
        p = self.params
        prov = {
            "model": "revenue_impact_v2.1",
            "anchor_ticket_usd": self._ANCHOR_TICKET_USD,
            "spend_tier": {
                "multiplier": round(spend_tier, 4),
                "formula": f"clamp((P / {self._ANCHOR_TICKET_USD})^{self._SPEND_TIER_EXPONENT}, {self._SPEND_TIER_CLAMP[0]}, {self._SPEND_TIER_CLAMP[1]})",
                "applies_to": [
                    "concession_per_capita (baseline spend before wait penalty)",
                    "merchandise_per_capita (baseline spend before density penalty)",
                ],
                "does_not_apply_to": [
                    "future ticket $ — those use P directly × repeat-attendee delta",
                ],
                "kind": "calibrated_heuristic",
                "note": (
                    "Sublinear link between face-value tier and secondary spend; "
                    "not a regression on your historical sales or 'similar events'."
                ),
            },
            "inputs_from_simulation": {
                "concession_wait_minutes": "Mean wait at concession-class nodes from Monte Carlo network output.",
                "corridor_density": "Proxy from Fruin LOS midpoints on corridor nodes (or worst LOS if sparse).",
                "hes_score": "Human Experience Score from weighted operational factors.",
            },
            "event_type_context": (
                {
                    "event_type": self._event_type,
                    "priors": self._event_revenue_priors,
                    "kind": "category_benchmark_scaling",
                    "note": (
                        "Scales NAC/Technomic *midpoints* by event category. "
                        "Network/temporal already use the same `event_type` for "
                        "arrival windows and Beta arrival profiles; this block "
                        "only affects revenue baselines."
                    ),
                }
                if self._event_type
                else None
            ),
            "benchmarks": [
                {
                    "parameter": "concession_per_capita",
                    "naive_nac_midpoint_usd": self.DEFAULTS["concession_per_capita"],
                    "after_event_type_and_tau_effective": round(
                        p["concession_per_capita"] * spend_tier, 4
                    ),
                    "source": "NAC / Technomic-style midpoint, then × event prior (if any), then × τ.",
                },
                {
                    "parameter": "merchandise_per_capita",
                    "naive_nac_midpoint_usd": self.DEFAULTS["merchandise_per_capita"],
                    "after_event_type_and_tau_effective": round(
                        p["merchandise_per_capita"] * spend_tier, 4
                    ),
                    "source": "Same stacking as concession.",
                },
                {
                    "parameter": "purchase_probability / merch_purchase_probability",
                    "values": f"{p['purchase_probability']:.2f} / {p['merch_purchase_probability']:.2f}",
                    "source": "Industry attach-rate midpoints.",
                },
                {
                    "parameter": "average_ticket_price",
                    "value_usd": p.get("average_ticket_price"),
                    "source": "User input on simulate request; defaults to anchor if omitted.",
                },
            ],
            "heuristic_formulas": [
                {
                    "name": "concession_wait_penalty",
                    "formula": "max(0.2, 1 - 0.08 * W_minutes)",
                    "role": "Maps simulated wait to share of baseline concession capture.",
                },
                {
                    "name": "merch_density_penalty",
                    "formula": "max(0.3, 1 - 0.5 * max(0, rho - 0.43))",
                    "role": "LOS C+ crowding suppresses browse-and-buy.",
                },
                {
                    "name": "future_repeat_prob",
                    "formula": "min(1, 0.45 * (HES/70)^1.5)",
                    "role": "Experience-driven repeat attendance vs HES=70 baseline.",
                },
            ],
            "limitations": [
                "Dollars are model outputs, not audited financial statements or tax filings.",
                "No integration with your POS, CRM, or ticket platform — unless you connect one later.",
                "No econometric 'similar events' panel: benchmarks are static + simulation-stressed.",
                "Spend-tier τ is a transparency feature so ticket price affects secondary baselines coherently; it is not peer-reviewed elasticity for your market.",
                "Current-event downside is only as credible as the modeled concession/corridor load in the simulation topology.",
            ],
        }
        return prov

    def total_impact(self, concession_wait: float, corridor_density: float,
                     hes_score: float, attendance: int) -> dict:
        """Aggregate all revenue impacts into a single summary."""
        tier = self._spend_tier_multiplier()
        conc = self.concession_revenue_impact(
            concession_wait, attendance, spend_tier_multiplier=tier
        )
        merch = self.merchandise_revenue_impact(
            corridor_density, attendance, spend_tier_multiplier=tier
        )
        future = self.future_ticket_impact(hes_score, attendance)

        current_loss = self._clean_money(
            conc["lost_revenue"] + merch["lost_revenue"]
        )
        future_impact = future["future_revenue_impact"]
        future_downside = abs(min(future_impact, 0))
        future_upside = max(future_impact, 0)
        total = self._clean_money(current_loss + future_downside)
        current_actual = conc["actual_revenue"] + merch["actual_revenue"]
        current_baseline = conc["base_revenue"] + merch["base_revenue"]

        if current_loss <= 0.0:
            summary = (
                "Current-event downside is negligible under the simulated "
                "conditions."
            )
        else:
            summary = (
                f"This event configuration puts an estimated "
                f"${current_loss:,.0f} of current-event concession/merch "
                f"revenue at risk."
            )
        if future_impact < 0:
            summary += f" Future demand downside adds ${future_downside:,.0f}."
        elif future_upside > 0:
            summary += (
                f" Experience implies ${future_upside:,.0f} of repeat-demand "
                f"upside, reported separately and not counted as downside."
            )

        return {
            "concession": conc,
            "merchandise": merch,
            "future_tickets": future,
            "current_event_baseline_revenue": current_baseline,
            "current_event_actual_revenue": current_actual,
            "total_current_event_loss": current_loss,
            "total_future_impact": future_impact,
            "future_demand_downside": future_downside,
            "future_demand_upside": future_upside,
            "total_economic_impact": total,
            "interpretation": "modeled downside at risk, not gross event revenue",
            "summary": summary,
            "secondary_spend_tier_multiplier": tier,
            "provenance": self._build_provenance(tier),
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  SafetyRiskScore
# ═══════════════════════════════════════════════════════════════════════════════

class SafetyRiskScore:
    """
    Composite safety risk assessment for venue operations.

    Three independent risk dimensions, combined via a dominant-component envelope:

    1. Crush Risk (SRS_crush): Based on maximum pedestrian density.
       Reference: HSE (UK Health & Safety Executive) crowd density guidelines;
       Fruin (1993); Helbing et al. (2007) "Dynamics of crowd disasters."

    2. Flow Capacity Risk (SRS_flow): Based on ratio of current throughput
       to required emergency evacuation throughput.
       Reference: NFPA 101 Life Safety Code; IBC egress requirements.

    3. Evacuation Time Risk (SRS_evac): Based on estimated evacuation time
       vs. the operational planning target.
       Reference: NFPA 101 (8-minute standard for assembly occupancies);
       SFPE Handbook Chapter 64.

    Output: 0.0 (no risk) to 1.0 (maximum risk)
    Thresholds:
      0.0 - 0.3: LOW — normal operations
      0.3 - 0.5: MODERATE — increased monitoring recommended
      0.5 - 0.7: ELEVATED — consider operational adjustments
      0.7 - 0.9: HIGH — immediate intervention recommended
      0.9 - 1.0: CRITICAL — emergency protocols should be activated
    """

    NFPA_EVAC_TARGET_MINUTES = 8.0
    # NFPA 101's 8-min is for egress system sizing, not actual evacuation time.
    # Real stadium evacuations take 20-60 min. 30-min threshold for risk scoring
    # matches the temporal engine design decision.
    PLANNING_EVAC_TARGET_MINUTES = 30.0
    EVAC_RISK_SPAN_MINUTES = 60.0

    @staticmethod
    def risk_level_for(score: float) -> str:
        if score < 0.25:
            return "LOW"
        if score < 0.45:
            return "MODERATE"
        if score < 0.65:
            return "ELEVATED"
        if score < 0.85:
            return "HIGH"
        return "CRITICAL"

    def __init__(self, total_attendance: int, venue_capacity: int):
        self.total_attendance = total_attendance
        self.venue_capacity = venue_capacity

    def crush_risk(self, max_density_per_m2: float) -> float:
        """
        SRS_crush = sigmoid((d_max - 1.5) * 4)

        Densities below 1.0 are uncomfortable but safe.
        At 1.5 persons/m2 (deep into LOS E), crush risk is ~50%.
        At 2.17+ (LOS F), risk approaches 1.0.
        """
        return 1.0 / (1.0 + math.exp(-(max_density_per_m2 - 1.5) * 4.0))

    def flow_capacity_risk(self, total_exit_throughput_per_hour: float) -> float:
        """
        SRS_flow = max(0, 1 - (total_exit_throughput / required_throughput))

        required_throughput = total_attendance * 60 / 30 = total_attendance * 2.0 per hour
        Uses 30-min planning target for consistency with evacuation_time_risk.
        """
        required = self.total_attendance * (60.0 / self.PLANNING_EVAC_TARGET_MINUTES)
        if required <= 0:
            return 0.0
        if total_exit_throughput_per_hour <= 0:
            return 1.0
        return max(0.0, 1.0 - total_exit_throughput_per_hour / required)

    def evacuation_time_risk(self, total_exit_throughput_per_hour: float) -> float:
        """
        estimated_evac_minutes = total_attendance / (throughput_per_hour / 60)
        SRS_evac = clamp((estimated_evac_minutes - PLANNING_EVAC_TARGET) / 60, [0, 1])

        Uses the 30-minute planning threshold as the zero-risk boundary, then
        ramps toward 1.0 over the following hour.
        """
        if total_exit_throughput_per_hour <= 0:
            return 1.0
        evac_minutes = self.total_attendance / (total_exit_throughput_per_hour / 60.0)
        if evac_minutes <= self.PLANNING_EVAC_TARGET_MINUTES:
            return 0.0
        return min(
            1.0,
            (evac_minutes - self.PLANNING_EVAC_TARGET_MINUTES)
            / self.EVAC_RISK_SPAN_MINUTES,
        )

    def compute(self, max_density_per_m2: float,
                total_exit_throughput_per_hour: float,
                node_metrics: dict = None) -> dict:
        """
        Compute composite SRS and all sub-scores.
        """
        srs_crush = self.crush_risk(max_density_per_m2)
        srs_flow = self.flow_capacity_risk(total_exit_throughput_per_hour)
        srs_evac = self.evacuation_time_risk(total_exit_throughput_per_hour)

        srs = max(srs_crush, srs_flow, srs_evac)

        # Determine risk level
        risk_level = self.risk_level_for(srs)

        # Dominant risk
        scores = {"crush": srs_crush, "flow": srs_flow, "evacuation": srs_evac}
        dominant = max(scores, key=scores.get)

        # Evacuation time estimate
        if total_exit_throughput_per_hour > 0:
            evac_min = self.total_attendance / (total_exit_throughput_per_hour / 60.0)
        else:
            evac_min = 120.0

        # Recommendation
        if risk_level == "LOW":
            recommendation = "Safety margins are adequate. Continue monitoring."
        elif dominant == "crush":
            recommendation = (
                f"Dominant risk is crowd compression. Peak density is "
                f"{max_density_per_m2:.2f} p/m\u00b2; reduce corridor crowding "
                f"before increasing attendance."
            )
        elif dominant == "flow":
            recommendation = (
                "Exit capacity is the limiting factor. Open additional lanes "
                "or redistribute egress demand across more exits."
            )
        elif risk_level in ("MODERATE", "ELEVATED", "HIGH"):
            recommendation = (
                f"Evacuation planning is the dominant constraint. Current "
                f"clearance time is {evac_min:.0f} min against a "
                f"{self.PLANNING_EVAC_TARGET_MINUTES:.0f}-minute planning target."
            )
        else:
            recommendation = (
                f"Emergency protocols recommended. Estimated clearance time is "
                f"{evac_min:.0f} min and the dominant risk is {dominant}."
            )

        # Technical details
        details = (
            f"SRS={srs:.3f} (crush={srs_crush:.3f}, flow={srs_flow:.3f}, "
            f"evac={srs_evac:.3f}). Estimated evacuation: {evac_min:.1f} min. "
            f"Planning target: {self.PLANNING_EVAC_TARGET_MINUTES:.0f} min "
            f"(NFPA sizing reference {self.NFPA_EVAC_TARGET_MINUTES:.0f} min). "
            f"Dominant risk factor: {dominant}."
        )

        return {
            "srs": srs,
            "srs_crush": srs_crush,
            "srs_flow": srs_flow,
            "srs_evac": srs_evac,
            "crush_risk": srs_crush,
            "flow_risk": srs_flow,
            "evac_risk": srs_evac,
            "risk_level": risk_level,
            "estimated_evac_minutes": evac_min,
            "estimated_evacuation_min": evac_min,
            "nfpa_target_minutes": self.NFPA_EVAC_TARGET_MINUTES,
            "planning_target_minutes": self.PLANNING_EVAC_TARGET_MINUTES,
            "dominant_risk": dominant,
            "recommendation": recommendation,
            "details": details,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  EnhancedHES
# ═══════════════════════════════════════════════════════════════════════════════

class EnhancedHES:
    """
    Enhanced Human Experience Score — multi-factor, weighted, 0-100.

    Each factor is a 0-1 satisfaction multiplier:
      HES = 100 * product(w_i * f_i + (1 - w_i))

    This formulation ensures:
    - Each factor can independently drive HES toward zero if bad enough
    - Weights control how much each factor matters
    - A factor at 1.0 (perfect) contributes nothing negative
    - Multiple bad factors compound (multiplicative, not additive)
    """

    DEFAULT_WEIGHTS = {
        "wait": 0.35,
        "density": 0.25,
        "temperature": 0.20,
        "service": 0.10,
        "access": 0.10,
    }

    def __init__(self, weights: dict = None):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()

    @staticmethod
    def wait_factor(mean_wait_minutes: float) -> float:
        """
        f_wait = e^{-0.05 * max(0, W - 5)}

        Waits under 5 minutes feel acceptable (f ~ 1.0).
        At 10 min: f = 0.78. At 15 min: f = 0.61. At 20 min: f = 0.47.
        """
        return math.exp(-0.05 * max(0.0, mean_wait_minutes - 5.0))

    @staticmethod
    def density_factor(worst_fruin_grade: str) -> float:
        """Maps Fruin LOS grade to satisfaction factor."""
        mapping = {"A": 1.0, "B": 0.95, "C": 0.80, "D": 0.55, "E": 0.25, "F": 0.05}
        return mapping.get(worst_fruin_grade, 0.5)

    @staticmethod
    def temperature_factor(heat_index_f: float) -> float:
        """
        1.0 for 60-80F comfort zone.
        Below 60: cold discomfort. Above 80: heat stress.
        Floor at 0.1.
        """
        if 60.0 <= heat_index_f <= 80.0:
            return 1.0
        if heat_index_f < 60.0:
            return max(0.1, 1.0 - 0.01 * (60.0 - heat_index_f) ** 1.3)
        # Above 80
        return max(0.1, 1.0 - 0.004 * (heat_index_f - 80.0) ** 1.5)

    @staticmethod
    def service_factor(mean_concession_wait: float) -> float:
        """
        f_service = max(0.2, 1 - 0.06 * max(0, concession_wait - 3))

        Concession wait under 3 min is expected.
        """
        return max(0.2, 1.0 - 0.06 * max(0.0, mean_concession_wait - 3.0))

    @staticmethod
    def access_factor(mean_entry_wait: float, mean_exit_time: float) -> float:
        """
        f_access = 0.5 * entry_score + 0.5 * exit_score
        """
        entry_score = max(0.1, 1.0 - 0.04 * max(0.0, mean_entry_wait - 10.0))
        exit_score = max(0.1, 1.0 - 0.03 * max(0.0, mean_exit_time - 15.0))
        return 0.5 * entry_score + 0.5 * exit_score

    def compute(self, mean_wait: float, worst_fruin: str,
                heat_index_f: float = 75.0,
                concession_wait: float = 0.0,
                entry_wait: float = 0.0,
                exit_time: float = 0.0) -> dict:
        """
        Compute enhanced HES.

        HES = 100 * product(w_i * f_i + (1 - w_i)) for each factor.
        """
        factors = {
            "wait": self.wait_factor(mean_wait),
            "density": self.density_factor(worst_fruin),
            "temperature": self.temperature_factor(heat_index_f),
            "service": self.service_factor(concession_wait),
            "access": self.access_factor(entry_wait, exit_time),
        }

        product = 1.0
        factor_details = {}
        for name, f_val in factors.items():
            w = self.weights[name]
            contrib = w * f_val + (1.0 - w)
            product *= contrib
            factor_details[name] = {"value": f_val, "weight": w, "score": contrib}

        hes = max(0.0, min(100.0, 100.0 * product))

        # Grade
        if hes >= 90:
            grade = "Excellent"
        elif hes >= 70:
            grade = "Good"
        elif hes >= 50:
            grade = "Fair"
        elif hes >= 30:
            grade = "Poor"
        else:
            grade = "Critical"

        # Dominant detractor: factor with lowest score contribution
        dominant = min(factor_details, key=lambda k: factor_details[k]["score"])

        # Recommendation
        recs = {
            "wait": f"Reduce average wait time (currently {mean_wait:.0f} min) to improve experience.",
            "density": f"Address corridor crowding (Fruin LOS {worst_fruin}) to improve flow.",
            "temperature": f"Mitigate temperature impact (heat index {heat_index_f:.0f}°F) with cooling/shade.",
            "service": f"Speed up concession service (currently {concession_wait:.0f} min wait).",
            "access": f"Improve entry/exit flow (entry {entry_wait:.0f} min, exit {exit_time:.0f} min).",
        }

        return {
            "hes": hes,
            "grade": grade,
            "factors": factor_details,
            "dominant_detractor": dominant,
            "recommendation": recs.get(dominant, ""),
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  compute_full_metrics
# ═══════════════════════════════════════════════════════════════════════════════

def compute_full_metrics(network_result: dict,
                         temporal_result=None,
                         attendance: int = 0,
                         venue_capacity: int = 0,
                         weather_data: dict = None,
                         revenue_params: dict = None,
                         event_type: str | None = None,
                         demand_model: dict | None = None) -> dict:
    """
    Master function that takes raw engine output and produces the complete
    metrics package for API responses and LLM consumption.

    Inputs:
    - network_result: output dict from NetworkMonteCarloEngine.run()
    - temporal_result: output from TemporalSimulator.run_fast() (optional)
    - attendance: total attendees
    - venue_capacity: max venue capacity
    - weather_data: {"heat_index_f": float, "weather_severity": float}
    - revenue_params: optional overrides for `RevenueImpact` (e.g. ticket price)
    - event_type: same string as the queueing run (nfl, theater, …) — steers
      revenue *benchmark* priors; network/temporal already use event type in
      `simulation.network` and `simulation/temporal`
    """
    weather_data = weather_data or {}
    heat_index_f = weather_data.get("heat_index_f", 75.0)
    weather_severity = weather_data.get("weather_severity", 0.0)

    def temporal_value(key: str, default=0.0):
        if temporal_result is None:
            return default
        if isinstance(temporal_result, dict):
            return temporal_result.get(key, default)
        return getattr(temporal_result, key, default)

    def temporal_steps():
        if temporal_result is None or isinstance(temporal_result, dict):
            return []
        return getattr(temporal_result, "time_steps", []) or []

    def humanize_node_id(node_id: str) -> str:
        return node_id.replace("_", " ") if node_id else "the bottleneck"

    def additional_servers_needed(node: dict, target_util: float = 0.82) -> int:
        current_servers = int(node.get("num_servers", 0) or 0)
        util = float(node.get("util_p90", node.get("util_mean", 0.0)) or 0.0)
        if current_servers < 1 or util <= target_util:
            return 0
        required_servers = math.ceil(current_servers * util / target_util)
        return max(0, required_servers - current_servers)

    def targeted_ops_recommendation(node_id: str, node: dict, *, target_util: float = 0.82) -> dict | None:
        node_type = node.get("node_type")
        if node_type not in ("security", "ticketing", "gate", "concession"):
            return None
        extra = additional_servers_needed(node, target_util=target_util)
        if extra <= 0:
            return None
        service_rate = float(node.get("service_rate_per_hr", 0.0) or 0.0)
        util = float(node.get("util_p90", node.get("util_mean", 0.0)) or 0.0)
        label = humanize_node_id(node_id)
        if node_type in ("security", "ticketing", "gate"):
            category = "security" if node_type in ("security", "gate") else "staffing"
            unit = "lanes"
            action = (
                f"Add {extra} {unit} at {label} to bring modeled utilization toward "
                f"{target_util * 100:.0f}%."
            )
            impact = (
                f"Adds about {extra * service_rate:,.0f} persons/hour of screening or entry "
                f"capacity and relieves a {util * 100:.0f}% utilization bottleneck."
            )
            return {"category": category, "action": action, "expected_impact": impact}
        action = (
            f"Add {extra} points of service at {label} to keep concession queues from "
            f"dominating current-event revenue leakage."
        )
        impact = (
            f"Adds about {extra * service_rate:,.0f} persons/hour of service capacity at a "
            f"{util * 100:.0f}% utilized commercial node."
        )
        return {"category": "staffing", "action": action, "expected_impact": impact}

    # ── Operational metrics ──────────────────────────────────────────────────
    wait_mean = network_result.get("wait_mean", 0.0)
    wait_p10 = network_result.get("wait_p10", 0.0)
    wait_p90 = network_result.get("wait_p90", 0.0)
    cong_mean = network_result.get("congestion_mean", network_result.get("cong_mean", 0.0))
    cong_p10 = network_result.get("congestion_p10", network_result.get("cong_p10", 0.0))
    cong_p90 = network_result.get("congestion_p90", network_result.get("cong_p90", 0.0))
    util_mean = network_result.get("util_mean", 0.0)

    bottleneck_node = network_result.get("bottleneck_node", "")
    bottleneck_freq = network_result.get("bottleneck_frequency", 0.0)
    throughput = network_result.get("network_throughput_mean", 0.0)

    worst_los = network_result.get("worst_fruin_los", "A") or "A"

    # Per-node detail for bottleneck utilization
    node_detail = network_result.get("node_metrics", {})
    bn_util = 0.0
    if bottleneck_node and bottleneck_node in node_detail:
        bn_util = node_detail[bottleneck_node].get("util_mean", 0.0)

    operational = {
        "wait_time": {"mean": wait_mean, "p10": wait_p10, "p90": wait_p90, "unit": "minutes"},
        "congestion": {"mean": cong_mean, "p10": cong_p10, "p90": cong_p90, "unit": "fraction"},
        "utilization": {"mean": util_mean, "unit": "fraction"},
        "bottleneck": {"node": bottleneck_node, "utilization": bn_util, "frequency": bottleneck_freq},
        "throughput": {"venue_total": throughput, "unit": "persons/hour"},
    }

    # ── Fruin LOS distribution ───────────────────────────────────────────────
    grade_dist = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "F": 0}
    worst_location = ""
    worst_grade = "A"
    _los_order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}

    for nid, nd in node_detail.items():
        los = nd.get("fruin_los_mode")
        if los and los in grade_dist:
            grade_dist[los] += 1
            if _los_order.get(los, 0) > _los_order.get(worst_grade, 0):
                worst_grade = los
                worst_location = nid

    # If no per-node LOS data, use network-level worst
    if worst_grade == "A" and worst_los != "A":
        worst_grade = worst_los

    fruin = {
        "worst_grade": worst_grade,
        "worst_location": worst_location,
        "grade_distribution": grade_dist,
    }

    # ── Concession wait (from node detail) ───────────────────────────────────
    concession_wait = 0.0
    conc_count = 0
    entry_wait = 0.0
    entry_count = 0
    exit_throughput_pph = 0.0
    corridor_density = 0.0
    corr_count = 0
    max_density = 0.0
    density_midpoints = {"A": 0.15, "B": 0.37, "C": 0.57, "D": 0.90, "E": 1.62, "F": 2.5}

    for nid, nd in node_detail.items():
        node_type = nd.get("node_type", "")
        w = nd.get("wait_mean", 0.0)
        if node_type == "concession" or "concession" in nid:
            concession_wait += w
            conc_count += 1
        if node_type in ("ticketing", "security", "gate") or "gate" in nid or "security" in nid:
            entry_wait += w
            entry_count += 1
        if node_type == "exit" or nid.startswith("exit_"):
            # Estimate exit throughput from node detail — use capacity heuristic
            # throughput ~ service_rate * num_servers, but we only have util
            # Fall back to network throughput for safety calc
            exit_throughput_pph += (
                max(0.0, float(nd.get("num_servers", 0) or 0.0))
                * max(0.0, float(nd.get("service_rate_per_hr", 0.0) or 0.0))
            )

    concession_wait = concession_wait / conc_count if conc_count > 0 else wait_mean
    entry_wait = entry_wait / entry_count if entry_count > 0 else wait_mean

    # Prefer structural exit capacity; only fall back to network throughput when
    # node-level exit parameters are unavailable.
    exit_throughput_pph = max(exit_throughput_pph, throughput, 1.0)

    # ── Corridor density for merch impact ────────────────────────────────────
    for nid, nd in node_detail.items():
        node_type = nd.get("node_type", "")
        if node_type == "corridor" or "corridor" in nid or "concourse" in nid:
            # Estimate density from queue length and (unknown) area
            # Use Fruin LOS mode as a proxy
            los = nd.get("fruin_los_mode")
            if los:
                d = density_midpoints.get(los, 0.15)
                corridor_density += d
                corr_count += 1
                if d > max_density:
                    max_density = d

    corridor_density = corridor_density / corr_count if corr_count > 0 else 0.15
    if max_density == 0.0:
        max_density = density_midpoints.get(worst_grade, 0.15)

    # If a temporal simulation is available, use event-phase concession waits
    # and corridor densities. That better represents in-event commercial stress
    # than ingress-only steady-state snapshots.
    t_steps = temporal_steps()
    if t_steps:
        temp_conc_wait = 0.0
        temp_conc_weight = 0.0
        temp_corr_density = 0.0
        temp_corr_count = 0
        temp_max_density = max_density

        for step in t_steps:
            if getattr(step, "phase", None) != "event":
                continue
            for nid, nm in (getattr(step, "node_metrics", {}) or {}).items():
                node_type = node_detail.get(nid, {}).get("node_type", "")
                if node_type == "concession":
                    temp_conc_wait += nm.arrival_rate * nm.expected_wait_minutes
                    temp_conc_weight += nm.arrival_rate
                elif node_type == "corridor" and nm.density_per_m2 is not None:
                    temp_corr_density += nm.density_per_m2
                    temp_corr_count += 1
                    temp_max_density = max(temp_max_density, nm.density_per_m2)

        if temp_conc_weight > 0:
            concession_wait = temp_conc_wait / temp_conc_weight
        if temp_corr_count > 0:
            corridor_density = temp_corr_density / temp_corr_count
            max_density = temp_max_density

    # ── Safety ───────────────────────────────────────────────────────────────
    srs_calc = SafetyRiskScore(attendance or 30000, venue_capacity or 65000)
    safety = srs_calc.compute(max_density, exit_throughput_pph, node_detail)
    safety["structural_srs"] = safety["srs"]
    temporal_peak_srs = temporal_value("max_safety_risk", None)
    temporal_peak_time = temporal_value("max_safety_risk_time", None)
    if temporal_peak_srs is not None:
        safety["temporal_peak_srs"] = temporal_peak_srs
        safety["temporal_peak_time_minutes"] = temporal_peak_time
        if temporal_peak_srs > safety["srs"]:
            safety["srs"] = temporal_peak_srs
            safety["risk_level"] = SafetyRiskScore.risk_level_for(temporal_peak_srs)
            safety["dominant_risk"] = "temporal_peak"
            if safety["risk_level"] in ("HIGH", "CRITICAL"):
                safety["recommendation"] = (
                    f"Peak temporal safety risk reaches {temporal_peak_srs:.2f} "
                    f"around minute {temporal_peak_time:.0f}. Reinforce staffing "
                    f"and flow controls at that window before operating at this load."
                )
            else:
                safety["recommendation"] = (
                    f"Temporal safety risk peaks at {temporal_peak_srs:.2f} around "
                    f"minute {temporal_peak_time:.0f}. Monitor ingress/egress "
                    f"operations at that window."
                )
            safety["details"] += (
                f" Temporal simulation peaks at SRS={temporal_peak_srs:.3f} "
                f"around t={temporal_peak_time:.0f} min and governs the reported score."
            )
        else:
            safety["details"] += (
                f" Temporal peak SRS={temporal_peak_srs:.3f} at "
                f"t={temporal_peak_time:.0f} min remains below the structural envelope."
            )

    # ── Experience ───────────────────────────────────────────────────────────
    hes_calc = EnhancedHES()
    # Estimate exit time from temporal result or from throughput
    exit_time = temporal_value("total_egress_time_minutes", 15.0)

    experience = hes_calc.compute(
        mean_wait=wait_mean,
        worst_fruin=worst_grade,
        heat_index_f=heat_index_f,
        concession_wait=concession_wait,
        entry_wait=entry_wait,
        exit_time=exit_time,
    )

    # ── Revenue ──────────────────────────────────────────────────────────────
    # Accept per-request overrides for ticket price (and any other benchmark
    # param) so the revenue module can be calibrated to the actual event
    # being priced instead of the NAC default.
    rev_calc = RevenueImpact(
        venue_capacity or 65000,
        custom_params=revenue_params or None,
        event_type=event_type,
    )
    revenue = rev_calc.total_impact(
        concession_wait=concession_wait,
        corridor_density=corridor_density,
        hes_score=experience["hes"],
        attendance=attendance or 30000,
    )
    # Surface the effective params so the Revenue derivation sheet can show
    # "avg_ticket_price = $X (user-supplied)" vs "default $95".
    revenue["params"] = dict(rev_calc.params)
    revenue["params_user_overrides"] = sorted((revenue_params or {}).keys())
    demand = demand_model or {
        "model_applied": False,
        "requested_attendance": attendance or 30000,
        "effective_attendance": attendance or 30000,
        "attendance_delta_due_to_price": 0,
        "attendance_delta_due_to_capacity": 0,
        "attendance_delta_total": 0,
        "price_is_binding": False,
        "capacity_is_binding": False,
        "pricing_posture": "not_applied",
        "pricing_recommendation": None,
    }

    # ── Temporal ─────────────────────────────────────────────────────────────
    temporal = None
    if temporal_result is not None:
        temporal = {
            "peak_congestion_time": temporal_value("peak_congestion_time", 0.0),
            "peak_wait": temporal_value("peak_congestion_wait", 0.0),
            "congestion_duration": temporal_value("congestion_duration_minutes", 0.0),
            "egress_time": temporal_value("total_egress_time_minutes", 0.0),
        }

    # ── Recommendations ──────────────────────────────────────────────────────
    recommendations = []

    if demand.get("model_applied") and demand.get("pricing_posture") in ("constrained", "headroom", "capacity_capped"):
        ticket_delta = float(demand.get("ticket_revenue_delta") or 0.0)
        recommendations.append({
            "priority": len(recommendations) + 1,
            "category": "pricing",
            "action": demand.get("pricing_recommendation") or "Revisit ticket pricing assumptions.",
            "expected_impact": (
                f"Turnout delta {int(demand.get('attendance_delta_total', 0)):+,} attendees and "
                f"{ticket_delta:+,.0f} gross ticket dollars versus the requested scenario."
            ),
        })

    security_candidates = [
        (nid, nd) for nid, nd in node_detail.items()
        if nd.get("node_type") in ("security", "ticketing", "gate")
    ]
    if security_candidates:
        security_node_id, security_node = max(
            security_candidates,
            key=lambda item: item[1].get("util_p90", item[1].get("util_mean", 0.0)),
        )
        security_rec = targeted_ops_recommendation(security_node_id, security_node)
        if security_rec:
            security_rec["priority"] = len(recommendations) + 1
            recommendations.append(security_rec)

    service_candidates = [
        (nid, nd) for nid, nd in node_detail.items()
        if nd.get("node_type") == "concession"
    ]
    if service_candidates:
        service_node_id, service_node = max(
            service_candidates,
            key=lambda item: item[1].get("util_p90", item[1].get("util_mean", 0.0)),
        )
        service_rec = targeted_ops_recommendation(service_node_id, service_node)
        if service_rec:
            service_rec["priority"] = len(recommendations) + 1
            recommendations.append(service_rec)

    # Safety recommendations (highest priority)
    if safety["risk_level"] in ("HIGH", "CRITICAL"):
        recommendations.append({
            "priority": len(recommendations) + 1,
            "category": "safety",
            "action": safety["recommendation"],
            "expected_impact": f"Reduce SRS from {safety['srs']:.2f} to safe levels",
        })

    # Wait time / revenue recommendations
    conc_loss = revenue["concession"]["lost_revenue"]
    if conc_loss > 1000:
        recommendations.append({
            "priority": len(recommendations) + 1,
            "category": "revenue",
            "action": revenue["concession"]["recommendation"],
            "expected_impact": f"Recover up to ${conc_loss:,.0f} per event",
        })

    # Experience recommendations
    if experience["hes"] < 70:
        recommendations.append({
            "priority": len(recommendations) + 1,
            "category": "experience",
            "action": experience["recommendation"],
            "expected_impact": f"Improve HES from {experience['hes']:.0f} toward 70+",
        })

    # Congestion recommendations
    if worst_grade in ("D", "E", "F"):
        recommendations.append({
            "priority": len(recommendations) + 1,
            "category": "congestion",
            "action": FruinLOS.grade_description(worst_grade),
            "expected_impact": f"Reduce corridor density from LOS {worst_grade} to LOS C or better",
        })

    # Merch revenue
    merch_loss = revenue["merchandise"]["lost_revenue"]
    if merch_loss > 500:
        recommendations.append({
            "priority": len(recommendations) + 1,
            "category": "revenue",
            "action": revenue["merchandise"]["recommendation"],
            "expected_impact": f"Recover up to ${merch_loss:,.0f} per event",
        })

    # Sort by priority and cap at 5
    recommendations.sort(key=lambda r: r["priority"])
    recommendations = recommendations[:5]
    # Re-number priorities
    for i, rec in enumerate(recommendations):
        rec["priority"] = i + 1

    result = {
        "operational": operational,
        "safety": safety,
        "experience": experience,
        "revenue": revenue,
        "demand": demand,
        "fruin": fruin,
        "recommendations": recommendations,
    }
    if temporal is not None:
        result["temporal"] = temporal

    return result
