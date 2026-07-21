"""
pipeline.py — Fetch real Las Vegas weather (Open-Meteo ERA5 archive) and
generate calibrated synthetic traffic. Outputs:
  data/vegas_weather_traffic_2023_2024.csv
"""

import requests
import csv
import json
import math
import os
from datetime import datetime, timezone

# ─── Open-Meteo ERA5 historical archive ───────────────────────────────────────
URL = (
    "https://archive-api.open-meteo.com/v1/archive"
    "?latitude=36.1147&longitude=-115.1728"
    "&start_date=2023-01-01&end_date=2024-12-31"
    "&hourly=temperature_2m,precipitation,windspeed_10m,weathercode"
    "&timezone=America%2FLos_Angeles"
)

print("Fetching Las Vegas weather from Open-Meteo (2023-01-01 to 2024-12-31)...")
resp = requests.get(URL, timeout=60)
resp.raise_for_status()
data = resp.json()
hourly = data["hourly"]

times      = hourly["time"]
temps_c    = hourly["temperature_2m"]
precip     = hourly["precipitation"]
windspeed  = hourly["windspeed_10m"]
wcode      = hourly["weathercode"]

print(f"  Received {len(times)} hourly records.")

# ─── F1 Las Vegas Grand Prix weekends ────────────────────────────────────────
F1_WEEKENDS = {
    # 2023: Nov 16–19
    *[f"2023-11-{d:02d}" for d in range(16, 20)],
    # 2024: Nov 21–24
    *[f"2024-11-{d:02d}" for d in range(21, 25)],
}

# Major holidays (simplified: New Year, Super Bowl w/e, 4th July, Labor Day, Thanksgiving, Christmas)
HOLIDAYS = {
    "2023-01-01", "2023-02-12", "2023-07-04", "2023-09-04",
    "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-02-11", "2024-07-04", "2024-09-02",
    "2024-11-28", "2024-12-25",
}

MAJOR_EVENTS = {
    # CES (early January), NFR (December), EDC (May)
    *[f"2023-01-{d:02d}" for d in range(5, 9)],
    *[f"2023-05-{d:02d}" for d in range(19, 22)],
    *[f"2023-12-{d:02d}" for d in range(7, 17)],
    *[f"2024-01-{d:02d}" for d in range(9, 13)],
    *[f"2024-05-{d:02d}" for d in range(17, 20)],
    *[f"2024-12-{d:02d}" for d in range(5, 15)],
}

def traffic_stress(dt_str: str, temp_c: float, precip_mm: float) -> float:
    """Synthesize a traffic_stress 0–1 for a given hour using domain rules."""
    dt = datetime.fromisoformat(dt_str)
    hour    = dt.hour
    weekday = dt.weekday()          # 0=Mon … 6=Sun
    date_s  = dt_str[:10]
    is_weekend  = weekday >= 5
    is_f1       = date_s in F1_WEEKENDS
    is_holiday  = date_s in HOLIDAYS
    is_event    = date_s in MAJOR_EVENTS

    # Base diurnal pattern
    if 7 <= hour <= 9:
        base = 0.82 + 0.06 * math.sin(math.pi * (hour - 7) / 2)   # morning peak ≈ 0.88
    elif 16 <= hour <= 19:
        base = 0.85 + 0.08 * math.sin(math.pi * (hour - 16) / 3)  # evening peak ≈ 0.93
    elif 22 <= hour or hour <= 2:
        base = 0.20 + 0.08 * (hour >= 22)                          # late night strip
    elif 3 <= hour <= 5:
        base = 0.12
    else:
        base = 0.45 + 0.15 * (10 <= hour <= 14)                    # midday bump

    # Weekend modifier (less commuter, more leisure — net slight increase evenings)
    if is_weekend:
        if 20 <= hour or hour <= 3:
            base = min(base + 0.12, 1.0)   # Strip nightlife
        else:
            base *= 0.78                    # fewer commuters

    # Event multipliers
    if is_f1:
        base = min(base * 1.45, 0.98)
    elif is_holiday or is_event:
        base = min(base * 1.22, 0.95)

    # Weather degradation
    heat_stress   = max(0.0, (temp_c - 38) / 20)   # above 38 °C (100 °F)
    precip_stress = min(precip_mm / 5.0, 0.15)      # rare in LV; max +15 pp
    base = min(base + heat_stress * 0.10 + precip_stress, 0.98)

    return round(base, 4)

# ─── Derived weather features ─────────────────────────────────────────────────
def weather_risk(temp_c, precip_mm, wind_kph, code):
    """0–1 composite weather risk."""
    heat  = max(0.0, (temp_c - 35) / 20)        # risk ramps above 35 °C
    rain  = min(precip_mm / 10.0, 0.4)
    wind  = max(0.0, (wind_kph - 30) / 60)
    # WMO code ≥ 61 = rain, ≥ 71 = snow, ≥ 95 = storm
    sev   = 0.2 if code >= 95 else (0.1 if code >= 61 else 0.0)
    return round(min(heat + rain + wind + sev, 1.0), 4)

# ─── Build rows ───────────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), "vegas_weather_traffic_2023_2024.csv")
fieldnames = [
    "datetime", "temp_c", "temp_f", "precip_mm", "windspeed_kph",
    "weathercode", "weather_risk", "traffic_stress",
    "hour", "weekday", "month", "is_weekend", "is_f1_weekend",
    "is_holiday", "is_major_event",
]

rows_written = 0
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for i, ts in enumerate(times):
        tc   = temps_c[i]  if temps_c[i]  is not None else 25.0
        pr   = precip[i]   if precip[i]   is not None else 0.0
        ws   = windspeed[i] if windspeed[i] is not None else 10.0
        wc   = wcode[i]    if wcode[i]    is not None else 0

        dt   = datetime.fromisoformat(ts)
        date_s = ts[:10]
        row = {
            "datetime"       : ts,
            "temp_c"         : round(tc, 2),
            "temp_f"         : round(tc * 9/5 + 32, 2),
            "precip_mm"      : round(pr, 3),
            "windspeed_kph"  : round(ws, 2),
            "weathercode"    : int(wc),
            "weather_risk"   : weather_risk(tc, pr, ws, int(wc)),
            "traffic_stress" : traffic_stress(ts, tc, pr),
            "hour"           : dt.hour,
            "weekday"        : dt.weekday(),
            "month"          : dt.month,
            "is_weekend"     : int(dt.weekday() >= 5),
            "is_f1_weekend"  : int(date_s in F1_WEEKENDS),
            "is_holiday"     : int(date_s in HOLIDAYS),
            "is_major_event" : int(date_s in MAJOR_EVENTS),
        }
        w.writerow(row)
        rows_written += 1

print(f"  Wrote {rows_written} rows -> {OUT}")
print("pipeline.py complete.")
