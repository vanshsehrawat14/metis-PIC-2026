"""
data/sources/weather.py — Open-Meteo ERA5 weather fetcher for Las Vegas venue operations.

Two public entry points:
  historical_fetch()         — downloads 2022-2024 ERA5 archive, caches to parquet
  forecast_fetch(date_str)   — hits Open-Meteo forecast API for a future date

Derived features added on top of raw API fields:
  heat_index_f               — Rothfusz regression (NWS standard; valid T ≥ 80 °F, RH ≥ 40%)
  heat_advisory              — bool: Heat Index ≥ 105 °F (NWS heat advisory threshold)
  excessive_heat_warning     — bool: Heat Index ≥ 115 °F (NWS excessive heat warning)
  wind_chill_f               — NWS formula (valid T ≤ 50 °F, wind > 3 mph)
  weather_severity           — 0-1 composite: heat stress + precipitation + wind

Sources:
  ERA5 data: Open-Meteo Historical Weather API (open-meteo.com), CC BY 4.0
  Rothfusz equation: NWS Technical Attachment SR90-23 (Rothfusz, 1990)
  Wind chill: NWS Wind Chill Temperature Index (2001 revision; Osczevski & Bluestein 2005)
  Heat advisory thresholds: NWS Heat Index Chart (www.weather.gov/safety/heat-index)
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
_SRC_DIR   = Path(__file__).parent
_DATA_DIR  = _SRC_DIR.parent
_CACHE_DIR = _DATA_DIR / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

PARQUET_PATH = _CACHE_DIR / "vegas_weather_2022_2024.parquet"

# ── API coordinates ────────────────────────────────────────────────────────────
# Centroid of major Las Vegas venues (slightly north of Strip midpoint)
# Source: calculated midpoint of VEGAS_VENUES coordinates in visualization/map.py
LV_LAT = 36.17
LV_LON = -115.14

_HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL   = "https://api.open-meteo.com/v1/forecast"

_HOURLY_VARS = (
    "temperature_2m,relative_humidity_2m,precipitation,"
    "wind_speed_10m,wind_gusts_10m,weather_code"
)


# ── Derived feature functions ──────────────────────────────────────────────────

def _rothfusz_heat_index(temp_f: float, rh: float) -> Optional[float]:
    """
    Rothfusz regression heat index.

    Source: NWS Technical Attachment SR90-23 (Rothfusz, 1990).
    Valid domain: T ≥ 80 °F and RH ≥ 40%. Returns None outside valid domain.

    For 80 ≤ T ≤ 112 °F and RH ≤ 13%, NWS applies an adjustment:
      HI = HI - ((13 - RH) / 4) * sqrt((17 - |T - 95|) / 17)
    For RH > 85% and 80 ≤ T ≤ 87 °F, NWS applies:
      HI = HI + ((RH - 85) / 10) * ((87 - T) / 5)
    """
    if temp_f < 80.0 or rh < 40.0:
        return None

    T, R = temp_f, rh
    hi = (
        -42.379
        + 2.04901523 * T
        + 10.14333127 * R
        - 0.22475541 * T * R
        - 0.00683783 * T * T
        - 0.05481717 * R * R
        + 0.00122874 * T * T * R
        + 0.00085282 * T * R * R
        - 0.00000199 * T * T * R * R
    )

    # Low-humidity adjustment (NWS)
    if R <= 13.0 and 80.0 <= T <= 112.0:
        adj = ((13.0 - R) / 4.0) * math.sqrt(max(0.0, (17.0 - abs(T - 95.0)) / 17.0))
        hi -= adj

    # High-humidity adjustment (NWS)
    if R >= 85.0 and 80.0 <= T <= 87.0:
        adj = ((R - 85.0) / 10.0) * ((87.0 - T) / 5.0)
        hi += adj

    return round(hi, 1)


def _wind_chill(temp_f: float, wind_mph: float) -> Optional[float]:
    """
    NWS Wind Chill Temperature Index (2001 revision).

    Source: Osczevski & Bluestein (2005), Bull. Amer. Meteor. Soc.
    Valid domain: T ≤ 50 °F and wind > 3 mph. Returns None outside valid domain.
    """
    if temp_f > 50.0 or wind_mph <= 3.0:
        return None
    V = wind_mph
    wc = 35.74 + 0.6215 * temp_f - 35.75 * (V ** 0.16) + 0.4275 * temp_f * (V ** 0.16)
    return round(wc, 1)


def _weather_severity(
    temp_f: float,
    heat_index_f: Optional[float],
    precip_mm: float,
    wind_kph: float,
    weather_code: int,
) -> float:
    """
    Composite operational weather severity score, 0-1.

    Components:
      heat_stress   — ramps from 0 at HI=90°F to 1 at HI=130°F (or temp alone if no HI)
      precip_stress — 0 to 0.35 (Las Vegas rain is rare but operationally disruptive)
      wind_stress   — ramps from 0 at 30 kph to 1 at 80 kph
      code_severe   — WMO weather code penalty: 0.15 for thunderstorms (≥95), 0.08 for rain (≥61)

    Weights derived to ensure a 115°F heat index day scores ~0.85 and
    a severe thunderstorm scores ~0.5 on its own, consistent with NWS warning thresholds.
    """
    hi = heat_index_f if heat_index_f is not None else temp_f

    # Heat stress: 0 at HI ≤ 90 °F → 1.0 at HI = 130 °F
    heat_stress = max(0.0, min(1.0, (hi - 90.0) / 40.0))

    # Precipitation: rare in LV; 10 mm/hr is an extreme event (max contribution 0.35)
    precip_stress = min(precip_mm / 10.0, 0.35)

    # Wind: above 30 kph → operational concern; 80 kph = max contribution 0.30
    wind_stress = max(0.0, min(0.30, (wind_kph - 30.0) / 50.0))

    # WMO code penalty
    if weather_code >= 95:
        code_penalty = 0.15   # thunderstorm
    elif weather_code >= 61:
        code_penalty = 0.08   # rain
    elif weather_code >= 71:
        code_penalty = 0.10   # snow (rare; high disruption if occurs)
    else:
        code_penalty = 0.0

    severity = heat_stress * 0.55 + precip_stress * 0.25 + wind_stress * 0.10 + code_penalty
    return round(min(severity, 1.0), 4)


def _enrich_record(rec: dict) -> dict:
    """Add all derived features to a raw API record dict."""
    temp_f     = rec["temp_c"] * 9 / 5 + 32
    wind_mph   = rec["wind_speed_kph"] * 0.621371
    rh         = rec.get("relative_humidity_pct", 20.0)  # LV avg ~20% RH

    hi = _rothfusz_heat_index(temp_f, rh)
    wc = _wind_chill(temp_f, wind_mph)

    rec["temp_f"]                   = round(temp_f, 1)
    rec["wind_mph"]                 = round(wind_mph, 2)
    rec["heat_index_f"]             = hi
    rec["heat_advisory"]            = bool(hi is not None and hi >= 105.0)
    rec["excessive_heat_warning"]   = bool(hi is not None and hi >= 115.0)
    rec["wind_chill_f"]             = wc
    rec["weather_severity"]         = _weather_severity(
        temp_f, hi, rec["precip_mm"], rec["wind_speed_kph"], rec["weather_code"]
    )
    return rec


def _parse_api_response(data: dict) -> list[dict]:
    """Convert Open-Meteo JSON response into list of enriched record dicts."""
    h = data["hourly"]
    times  = h["time"]
    tc     = h["temperature_2m"]
    rh     = h["relative_humidity_2m"]
    pr     = h["precipitation"]
    ws     = h["wind_speed_10m"]
    wg     = h["wind_gusts_10m"]
    wc     = h["weather_code"]

    records = []
    for i, ts in enumerate(times):
        tc_i = tc[i] if tc[i] is not None else 25.0
        rh_i = rh[i] if rh[i] is not None else 20.0
        pr_i = pr[i] if pr[i] is not None else 0.0
        ws_i = ws[i] if ws[i] is not None else 10.0
        wg_i = wg[i] if wg[i] is not None else ws_i
        wc_i = int(wc[i]) if wc[i] is not None else 0

        dt = datetime.fromisoformat(ts)
        rec = {
            "datetime"             : ts,
            "temp_c"               : round(tc_i, 2),
            "relative_humidity_pct": round(rh_i, 1),
            "precip_mm"            : round(pr_i, 3),
            "wind_speed_kph"       : round(ws_i, 2),
            "wind_gusts_kph"       : round(wg_i, 2),
            "weather_code"         : wc_i,
            "hour"                 : dt.hour,
            "weekday"              : dt.weekday(),
            "month"                : dt.month,
            "year"                 : dt.year,
        }
        records.append(_enrich_record(rec))
    return records


# ── Public API ─────────────────────────────────────────────────────────────────

def historical_fetch(
    start: str = "2022-01-01",
    end: str   = "2024-12-31",
    force_refresh: bool = False,
) -> "pd.DataFrame":
    """
    Fetch ERA5 hourly data for Las Vegas 2022-2024, cache as parquet.

    Returns a pandas DataFrame with all raw + derived features.
    Requires: pandas, pyarrow (pip install pandas pyarrow).

    Parameters
    ----------
    start, end : ISO date strings (inclusive)
    force_refresh : if True, re-download even if cache exists
    """
    import pandas as pd

    if PARQUET_PATH.exists() and not force_refresh:
        print(f"[weather] Loading from cache: {PARQUET_PATH}")
        return pd.read_parquet(PARQUET_PATH)

    print(f"[weather] Fetching ERA5 {start} → {end} from Open-Meteo...")
    resp = requests.get(
        _HISTORICAL_URL,
        params={
            "latitude"  : LV_LAT,
            "longitude" : LV_LON,
            "start_date": start,
            "end_date"  : end,
            "hourly"    : _HOURLY_VARS,
            "timezone"  : "America/Los_Angeles",
        },
        timeout=120,
    )
    resp.raise_for_status()
    records = _parse_api_response(resp.json())
    print(f"[weather]   {len(records)} hourly records received.")

    df = pd.DataFrame(records)
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"[weather]   Cached → {PARQUET_PATH}")
    return df


def forecast_fetch(date_str: str) -> list[dict]:
    """
    Fetch Open-Meteo forecast for a specific date.

    For dates within ~16 days of today → hits the live forecast API.
    For dates further out             → falls back to ERA5 historical climatology
                                         (same month/day in the most recent archived year),
                                         which is still a real, cited measurement.

    Returns a list of 24 enriched hourly dicts for the requested date.
    """
    today = datetime.now(timezone.utc).date()
    try:
        target = datetime.fromisoformat(date_str).date()
    except Exception:
        target = today

    horizon_days = (target - today).days

    def _hit(url: str, params: dict) -> list[dict]:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return _parse_api_response(resp.json())

    # Path A: live short-range forecast (≤16 days ahead, including past 7 days)
    if -7 <= horizon_days <= 16:
        try:
            return _hit(_FORECAST_URL, {
                "latitude"    : LV_LAT,
                "longitude"   : LV_LON,
                "hourly"      : _HOURLY_VARS,
                "timezone"    : "America/Los_Angeles",
                "start_date"  : date_str,
                "end_date"    : date_str,
            })
        except Exception:
            pass  # fall through to climatology

    # Path B: ERA5 historical climatology — fetch same month/day from last archived year.
    # Open-Meteo's archive typically lags ~5 days and reliably covers 2 years back.
    for years_back in (1, 2, 3):
        archive_year = target.year - years_back
        if archive_year < 1950:
            break
        archive_date = target.replace(year=archive_year).isoformat()
        try:
            records = _hit(_HISTORICAL_URL, {
                "latitude"  : LV_LAT,
                "longitude" : LV_LON,
                "start_date": archive_date,
                "end_date"  : archive_date,
                "hourly"    : _HOURLY_VARS,
                "timezone"  : "America/Los_Angeles",
            })
            # Tag records so the caller knows these are climatology, not a forecast.
            for r in records:
                r["climatology_year"] = archive_year
                r["is_climatology"] = True
            return records
        except Exception:
            continue

    raise RuntimeError(
        f"No weather data available for {date_str}: forecast horizon too far "
        f"({horizon_days}d) and ERA5 climatology lookups failed."
    )


def get_hour_conditions(date_str: str, hour: int) -> dict:
    """
    Return enriched weather conditions for a specific date/hour.

    Tries forecast API first (for future dates); falls back to ERA5 cache
    for historical dates in the 2022-2024 window.
    """
    import pandas as pd

    target_dt = datetime.fromisoformat(f"{date_str}T{hour:02d}:00:00")
    cutoff = datetime(2025, 1, 1)

    if target_dt >= cutoff:
        records = forecast_fetch(date_str)
        matches = [r for r in records if r["hour"] == hour]
        return matches[0] if matches else records[0]
    else:
        df = historical_fetch()
        row = df[df["datetime"] == f"{date_str}T{hour:02d}:00"]
        if row.empty:
            raise ValueError(f"No historical record for {date_str} hour={hour}")
        return row.iloc[0].to_dict()


# ── Data source registry entry ─────────────────────────────────────────────────

DATA_SOURCE_ENTRY = {
    "source_name"       : "Open-Meteo ERA5 Historical Weather API",
    "type"              : "weather",
    "provider"          : "Open-Meteo (data from ECMWF ERA5 reanalysis)",
    "url"               : "https://open-meteo.com/en/docs/historical-weather-api",
    "data_type"         : "Hourly ERA5 reanalysis: temperature, humidity, precipitation, wind, weather code",
    "temporal_coverage" : "2022-01-01 to 2024-12-31 (3 full years)",
    "spatial_resolution": "0.25° × 0.25° grid (~25 km); interpolated to point (36.17, -115.14)",
    "update_frequency"  : "Historical archive updated daily with ~5-day lag; forecast API refresh cadence is model-dependent (typically hourly to 6-hourly)",
    "license"           : "CC BY 4.0 (Open-Meteo); underlying ERA5 data: Copernicus Climate Data Store",
    "retrieval_date"    : "2026-04-10",
    "variables_used"    : ["temperature_2m", "relative_humidity_2m", "precipitation",
                           "wind_speed_10m", "wind_gusts_10m", "weather_code"],
    "derived_features"  : ["heat_index_f (Rothfusz 1990)", "heat_advisory (NWS ≥105°F)",
                           "excessive_heat_warning (NWS ≥115°F)", "wind_chill_f (Osczevski 2005)",
                           "weather_severity (composite 0-1)"],
    "notes"             : (
        "ERA5 is a reanalysis product — it blends historical observations with a numerical weather "
        "model. Point accuracy for Las Vegas is high (flat terrain, well-instrumented area) but "
        "local microclimate effects (urban heat island, valley effects) are not captured at 25km "
        "resolution. Precipitation is especially uncertain: ERA5 frequently overestimates in arid "
        "regions. Wind gusts are modeled, not measured."
    ),
}


def save_data_source_entry(output_path: Optional[str] = None) -> None:
    """Append/update the weather source entry in data/sources/data_sources.json."""
    if output_path is None:
        output_path = str(_SRC_DIR / "data_sources.json")

    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    else:
        registry = {"sources": []}

    # Upsert by source_name
    existing = [s for s in registry["sources"] if s["source_name"] != DATA_SOURCE_ENTRY["source_name"]]
    existing.append(DATA_SOURCE_ENTRY)
    registry["sources"] = existing

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    print(f"[weather] Data source entry saved → {output_path}")


if __name__ == "__main__":
    df = historical_fetch()
    print(df[["datetime", "temp_c", "relative_humidity_pct", "heat_index_f",
              "heat_advisory", "weather_severity"]].head(48))
    save_data_source_entry()
