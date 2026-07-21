import json
import math
import os
import numpy as np

_WEIGHTS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "calibration_weights.json"
)


def _load_weights():
    """Load calibrated weights from data/calibration_weights.json if present."""
    try:
        with open(_WEIGHTS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        coef = d["engine_coefficients"]
        return {
            "w_cap"  : float(coef["weather_capacity_penalty"]),
            "w_dem"  : float(coef["weather_demand_boost"]),
            "w_trans": float(coef["transit_throughput_penalty"]),
            "w_brk"  : float(coef["breakdown_wait_exponent"]),
            "w_hes"  : float(coef["hes_weather_weight"]),
            "r2"     : float(d.get("r2_score", 0.0)),
        }
    except Exception:
        # Fall back to conservative defaults if weights file is missing
        return {
            "w_cap"  : 0.15,
            "w_dem"  : 0.10,
            "w_trans": 0.25,
            "w_brk"  : 90.0,
            "w_hes"  : 15.0,
            "r2"     : 0.0,
        }


class MonteCarloEngine:
    def __init__(self, n_simulations=1000, peak_hour_fraction=0.30):
        self.n_sims = n_simulations
        # peak_hour_fraction: fraction of total attendance that arrives in the
        # single busiest hour (0.30 = realistic for major events with staggered entry)
        self.phf = peak_hour_fraction
        w = _load_weights()
        self.w_cap   = w["w_cap"]
        self.w_dem   = w["w_dem"]
        self.w_trans = w["w_trans"]
        self.w_brk   = w["w_brk"]
        self.w_hes   = w["w_hes"]
        self._r2     = w["r2"]

    def is_calibrated(self) -> bool:
        """True if real calibration weights were loaded (R² > 0)."""
        return self._r2 > 0.0

    def calibration_r2(self) -> float:
        return self._r2

    def run_vectorized(self, attendance, staffing, price, weather, transit):
        att   = np.atleast_1d(np.asarray(attendance, dtype=float))[:, np.newaxis]
        staff = np.atleast_1d(np.asarray(staffing,   dtype=float))[:, np.newaxis]
        prc   = np.atleast_1d(np.asarray(price,       dtype=float))[:, np.newaxis]

        n_configs  = att.shape[0]
        base_noise = np.random.normal(0, 0.05, (n_configs, self.n_sims))

        # Correlated noise: heat degrades capacity while inflating demand simultaneously
        # Floor capacity_noise at 0.05 to prevent negative capacity in extreme inputs.
        capacity_noise = np.maximum(1.0 + base_noise - (weather * self.w_cap), 0.05)
        demand_noise   = 1.0 + (base_noise * 0.5) + (weather * self.w_dem)

        # Non-linear price elasticity — linear decay up to $200, then exponential
        # At $200: linear branch = 0.80, exponential branch = 0.80 * exp(0) = 0.80
        # Continuous at the boundary to prevent nonsensical demand jumps
        price_elasticity = np.where(
            prc <= 200,
            1.0 - (prc / 1000),
            0.80 * np.exp(-(prc - 200) / 100),
        )
        # Total demand: how many people actually show up (for revenue)
        total_demand = att * price_elasticity * demand_noise
        # Peak-hour arrival rate: fraction of total that arrives in the busiest hour
        # (e.g., 30% of 65K = 19.5K people arriving in the busiest single hour)
        demand = total_demand * self.phf

        # Transit degradation reduces effective service throughput
        transit_efficiency = np.maximum(
            1.0 - ((1.0 - transit) * self.w_trans), 0.05
        )
        capacity = (staff * 45 * transit_efficiency) * capacity_noise

        # Kingman G/G/1 approximation: E[W] ≈ (ρ/(1-ρ)) · ((c_a² + c_s²)/2) · τ
        # where τ = mean service time = 60/45 ≈ 1.33 min per person per server.
        # Utilization capped at 0.98 (balking model — people leave if queue is too long).
        # c_a² scales with weather disruption; c_s² = 1.2 (hyper-exponential service).
        raw_util      = demand / np.maximum(capacity, 1)
        utilization   = np.clip(raw_util, 0.05, 0.98)
        c_a_sq        = 1.0 + weather * 1.8   # arrival variance grows under disruption
        c_s_sq        = 1.2                    # service variance (constant)
        variance_term = (c_a_sq + c_s_sq) / 2.0
        tau           = 60.0 / 45.0            # mean service time in minutes
        raw_wait      = (utilization / (1.0 - utilization)) * variance_term * tau
        wait_time     = np.where(raw_util < 0.01, 0.0, raw_wait)

        # Risk metrics derived from utilization and wait
        congestion_risk = 1.0 / (1.0 + np.exp(-12.0 * (utilization - 0.85)))
        breakdown_prob  = np.clip(
            (wait_time / self.w_brk) ** 2 + (weather * 0.1), 0, 1
        )

        # Financials — revenue uses total demand (not peak-hour)
        staff_cost = staff * 350
        revenue    = (prc * total_demand) - staff_cost

        # Human Experience Score — exponential wait penalty after 15-minute threshold
        # np.where evaluates both branches; guard the excess term to avoid
        # negative^1.5 RuntimeWarning on the non-active branch.
        wt_clip      = np.maximum(wait_time, 0.0)
        wt_excess    = np.maximum(wt_clip - 15.0, 0.0)
        wait_penalty = np.where(
            wt_clip < 15,
            wt_clip * 0.5,
            7.5 + wt_excess ** 1.5 * 0.2,
        )
        hes = np.clip(
            100 - wait_penalty - (congestion_risk * 30) - (weather * self.w_hes),
            0, 100
        )

        def pct(arr, q):
            return np.percentile(arr, q, axis=1)

        return {
            # Wait time
            "wait_mean": np.mean(wait_time, axis=1),
            "wait_p10":  pct(wait_time, 10),
            "wait_p90":  pct(wait_time, 90),
            "wait_std":  np.std(wait_time, axis=1),
            # Congestion
            "cong_mean": np.mean(congestion_risk, axis=1),
            "cong_p10":  pct(congestion_risk, 10),
            "cong_p90":  pct(congestion_risk, 90),
            "cong_std":  np.std(congestion_risk, axis=1),
            # Breakdown
            "brk_mean":  np.mean(breakdown_prob, axis=1),
            "brk_p10":   pct(breakdown_prob, 10),
            "brk_p90":   pct(breakdown_prob, 90),
            "brk_std":   np.std(breakdown_prob, axis=1),
            # Revenue
            "rev_mean":  np.mean(revenue, axis=1),
            "rev_p10":   pct(revenue, 10),
            "rev_p90":   pct(revenue, 90),
            "rev_std":   np.std(revenue, axis=1),
            # Human Experience Score
            "hes_mean":  np.mean(hes, axis=1),
            "hes_p10":   pct(hes, 10),
            "hes_p90":   pct(hes, 90),
            # Utilization
            "util_mean": np.mean(utilization, axis=1),
        }
