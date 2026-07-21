import math
import numpy as np


def _confidence(mean: float, p90: float, threshold: float, above: bool = False) -> float:
    """
    Estimate P(X < threshold) using a normal CDF approximation.
    Sigma is estimated from mean + P90 (z=1.2816 for the 90th percentile).
    Uses math.erf — no scipy required.
    """
    sigma = max((float(p90) - float(mean)) / 1.2816, 1e-6)
    z = (float(threshold) - float(mean)) / (sigma * math.sqrt(2))
    prob = 0.5 * (1.0 + math.erf(z))
    if above:
        prob = 1.0 - prob
    return round(min(max(prob * 100.0, 2.0), 98.0), 1)


class VectorizedOptimizer:
    def __init__(self, engine):
        self.engine = engine

    def optimize(self, goal: str, current_inputs: dict) -> list:
        # Seed RNG for reproducible optimization across identical inputs
        np.random.seed(42)
        # 10×10 search grid = 100 configurations evaluated simultaneously
        staff_range = np.linspace(
            max(100, current_inputs["staffing"] - 300),
            current_inputs["staffing"] + 500, 10,
        )
        price_range = np.linspace(
            max(50, current_inputs["price"] - 50),
            current_inputs["price"] + 100, 10,
        )
        S, P   = np.meshgrid(staff_range, price_range)
        S_flat = S.flatten()
        P_flat = P.flatten()

        res = self.engine.run_vectorized(
            current_inputs["attendance"], S_flat, P_flat,
            current_inputs["weather"], current_inputs["transit"],
        )

        # Fully-vectorised multi-objective scoring — no Python loop over the grid
        if goal == "Minimize Congestion Risk":
            scores = -res["cong_p90"]
        elif goal == "Keep wait time < 10 mins":
            penalty = np.where(res["wait_mean"] > 10, res["wait_mean"] - 10, 0.0)
            scores  = -penalty + res["hes_mean"] * 0.01
        else:  # Maximize Revenue Safely (Breakdown < 5%)
            safety_penalty = np.where(res["brk_mean"] > 0.05, 1e9, 0.0)
            scores         = res["rev_mean"] - safety_penalty

        top_3 = np.argsort(scores)[-3:][::-1]

        recommendations = []
        for i in range(3):
            idx = int(top_3[i])

            if goal == "Minimize Congestion Risk":
                conf = _confidence(res["cong_mean"][idx], res["cong_p90"][idx], 0.50)
            elif goal == "Keep wait time < 10 mins":
                conf = _confidence(res["wait_mean"][idx], res["wait_p90"][idx], 10.0)
            else:
                conf = _confidence(res["brk_mean"][idx], res["brk_p90"][idx], 0.05)

            recommendations.append({
                "staffing":       int(S_flat[idx]),
                "price":          float(P_flat[idx]),
                "staffing_delta": int(S_flat[idx])   - current_inputs["staffing"],
                "price_delta":    float(P_flat[idx]) - current_inputs["price"],
                "revenue":        float(res["rev_mean"][idx]),
                "rev_p10":        float(res["rev_p10"][idx]),
                "rev_p90":        float(res["rev_p90"][idx]),
                "breakdown":      float(res["brk_mean"][idx]),
                "hes":            float(res["hes_mean"][idx]),
                "congestion":     float(res["cong_mean"][idx]),
                "wait":           float(res["wait_mean"][idx]),
                "wait_p90":       float(res["wait_p90"][idx]),
                "confidence":     conf,
            })

        return recommendations
