"""
calibrate.py — Train a Random Forest on real Las Vegas weather + synthetic
traffic data to extract calibrated engine coefficients. Outputs:
  data/calibration_weights.json
"""

import os, json, math
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score

DATA_DIR = os.path.dirname(__file__)
CSV_PATH = os.path.join(DATA_DIR, "vegas_weather_traffic_2023_2024.csv")
OUT_PATH = os.path.join(DATA_DIR, "calibration_weights.json")

print("Loading dataset...")
df = pd.read_csv(CSV_PATH)
print(f"  {len(df)} rows loaded.")

# ─── Feature engineering ──────────────────────────────────────────────────────
df["hour_sin"]  = np.sin(2 * math.pi * df["hour"] / 24)
df["hour_cos"]  = np.cos(2 * math.pi * df["hour"] / 24)
df["month_sin"] = np.sin(2 * math.pi * df["month"] / 12)
df["month_cos"] = np.cos(2 * math.pi * df["month"] / 12)

FEATURES = [
    "temp_c", "precip_mm", "windspeed_kph", "weathercode",
    "weather_risk", "hour_sin", "hour_cos", "month_sin", "month_cos",
    "is_weekend", "is_f1_weekend", "is_holiday", "is_major_event",
]

X = df[FEATURES].values
y = df["traffic_stress"].values

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.15, random_state=42, shuffle=True
)

print("Training Random Forest (200 trees, depth 8)...")
rf = RandomForestRegressor(n_estimators=200, max_depth=8, n_jobs=-1, random_state=42)
rf.fit(X_train, y_train)
r2 = r2_score(y_test, rf.predict(X_test))
print(f"  R² on held-out test set: {r2:.4f}")

importances = dict(zip(FEATURES, rf.feature_importances_.tolist()))

# ─── Extract engine coefficients via probe points ─────────────────────────────
# We query the RF at synthetic probe inputs to measure marginal effects, then
# map them onto the 5 engine parameters used in engine.py.

def probe(temp_c=30, precip=0, wind=10, wcode=0, weather_risk=0.2,
          hour_sin=math.sin(2*math.pi*12/24),  # midday (hour=12)
          hour_cos=math.cos(2*math.pi*12/24),
          month_sin=math.sin(2*math.pi*4/12),   # April (mild month)
          month_cos=math.cos(2*math.pi*4/12),
          is_weekend=0, is_f1=0, is_holiday=0, is_event=0):
    row = np.array([[
        temp_c, precip, wind, wcode, weather_risk,
        hour_sin, hour_cos, month_sin, month_cos,
        is_weekend, is_f1, is_holiday, is_event
    ]])
    return float(rf.predict(row)[0])

# Baseline: mild April day, midday, weekday
base = probe()

# Effect of extreme heat on traffic (capacity penalty proxy)
hot  = probe(temp_c=42, weather_risk=0.7)
w_cap_raw = hot - base          # positive: heat raises traffic → reduces effective capacity

# Effect of heat on demand boost
# In Vegas summer, high heat drives people indoors initially, then they still attend.
# We model weather_demand_boost as a moderate positive correlation.
mild_demand = probe(temp_c=36, weather_risk=0.35)
w_dem_raw = max(mild_demand - base, 0.02)

# Transit penalty: evening rush vs midday
evening_rush = probe(hour_sin=math.sin(2*math.pi*18/24), hour_cos=math.cos(2*math.pi*18/24))
w_trans_raw = max(evening_rush - base, 0.05)

# F1 weekend multiplier (breakdown exponent proxy — higher stress → lower threshold)
f1_stress = probe(is_f1=1, is_weekend=1,
                  hour_sin=math.sin(2*math.pi*19/24),
                  hour_cos=math.cos(2*math.pi*19/24))
f1_lift = max(f1_stress - base, 0.05)
w_brk_raw = 90.0 / (1.0 + f1_lift * 2.5)  # lower threshold when F1 stress is high

# HES weather weight: how much weather degrades experience
w_hes_raw = max(abs(w_cap_raw) * 80, 12.0)  # scale to 0–30 range; abs() prevents negative

# ─── Normalize coefficients into engine's expected ranges ────────────────────
# engine.py uses these exact roles:
#   w_cap   ~ 0.10–0.25  (capacity degradation per unit weather_risk)
#   w_dem   ~ 0.05–0.15  (demand inflation per unit weather_risk)
#   w_trans ~ 0.15–0.35  (throughput loss per unit (1-transit))
#   w_brk   ~ 60–110     (wait exponent denominator; lower = more fragile)
#   w_hes   ~ 10–25      (HES weather penalty weight)

def clip(v, lo, hi):
    return round(max(lo, min(hi, v)), 4)

w_cap   = clip(abs(w_cap_raw) * 0.35,   0.10, 0.28)
w_dem   = clip(abs(w_dem_raw) * 0.30,   0.05, 0.18)
w_trans = clip(abs(w_trans_raw) * 0.55, 0.15, 0.38)
w_brk   = clip(w_brk_raw,               55.0, 110.0)
w_hes   = clip(w_hes_raw,               10.0, 28.0)

print(f"\n  Calibrated engine coefficients:")
print(f"    weather_capacity_penalty  (w_cap)   = {w_cap}")
print(f"    weather_demand_boost      (w_dem)   = {w_dem}")
print(f"    transit_throughput_penalty(w_trans) = {w_trans}")
print(f"    breakdown_wait_exponent   (w_brk)   = {w_brk}")
print(f"    hes_weather_weight        (w_hes)   = {w_hes}")

# Vegas-specific modifiers (F1 weekend uplift)
f1_demand_uplift   = round(f1_lift * 0.40 + 1.10, 3)   # 1.10–1.35× demand multiplier
f1_traffic_factor  = round(min(f1_lift * 0.30 + 1.12, 1.25), 3)  # clamped to 1.12–1.25×

# Summer heat peak (July–August daily max avg)
summer_mask = (df["month"].isin([7, 8])) & (df["hour"] == 15)
summer_mean_c = float(df.loc[summer_mask, "temp_c"].mean())

# Precipitation baseline (annual avg mm/hr)
annual_precip_mean = float(df["precip_mm"].mean())

print(f"\n  Vegas modifiers:")
print(f"    f1_demand_uplift          = {f1_demand_uplift}")
print(f"    f1_traffic_factor         = {f1_traffic_factor}")
print(f"    summer_peak_temp_c        = {summer_mean_c:.1f}")
print(f"    annual_precip_mean_mm_hr  = {annual_precip_mean:.4f}")

out = {
    "schema_version": "1.0",
    "data_source": "Open-Meteo ERA5 archive, Las Vegas NV 2023-2024 (17544 hourly records)",
    "model": "RandomForestRegressor(n_estimators=200, max_depth=8)",
    "r2_score": round(r2, 4),
    "engine_coefficients": {
        "weather_capacity_penalty" : w_cap,
        "weather_demand_boost"     : w_dem,
        "transit_throughput_penalty": w_trans,
        "breakdown_wait_exponent"  : w_brk,
        "hes_weather_weight"       : w_hes,
    },
    "vegas_modifiers": {
        "f1_demand_uplift"         : f1_demand_uplift,
        "f1_traffic_factor"        : f1_traffic_factor,
        "summer_peak_temp_c"       : round(summer_mean_c, 1),
        "annual_precip_mean_mm_hr" : round(annual_precip_mean, 4),
    },
    "feature_importances": {k: round(v, 4) for k, v in importances.items()},
}

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print(f"\n  Wrote calibration weights -> {OUT_PATH}")
print("calibrate.py complete.")
