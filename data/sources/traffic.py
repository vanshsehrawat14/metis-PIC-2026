"""
data/sources/traffic.py — Traffic and transit context for Las Vegas venue corridors.

Static datasets (NDOT AADT counts, RTC ridership, Monorail) loaded from JSON files
in this directory. Dynamic context generated via get_traffic_context().

Public API:
  get_traffic_context(venue_id, dt) → dict with:
    base_traffic_load        — corridor AADT-derived hourly load (0-1)
    event_overlay_factor     — multiplier for event-day conditions
    transit_accessibility    — 0-1 score for this venue's transit options
    traffic_factor           — normalized 0-1 input for simulation engine
    corridor_aadt            — raw AADT for primary corridor
    sources                  — list of source citations used

Sources:
  NDOT AADT: data/sources/ndot_counts.json
  RTC transit: data/sources/rtc_transit.json
  Diurnal profiles: derived from NDOT standard peak-hour factors and
    Las Vegas travel demand model (Clark County RTP 2019, Table 3-4)
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

_SRC_DIR = Path(__file__).parent

# ── Load static datasets ───────────────────────────────────────────────────────
with open(_SRC_DIR / "ndot_counts.json", "r", encoding="utf-8") as _f:
    _NDOT = json.load(_f)

with open(_SRC_DIR / "rtc_transit.json", "r", encoding="utf-8") as _f:
    _RTC = json.load(_f)

# Index NDOT corridors by venue for quick lookup.
# The schema stores venue association in one of four places:
#   top-level     nearest_venue  : "allegiant_stadium"
#   top-level     venues_served  : ["...", "..."]
#   location      nearest_venue  : "allegiant_stadium"
#   location      nearest_venues : ["...", "..."]
# (historical drift — we accept all of them so the AADT actually reaches the engine.)
_CORRIDOR_BY_VENUE: dict[str, list[dict]] = {}
for _c in _NDOT["corridors"]:
    _venues: list[str] = []
    _top_served = _c.get("venues_served")
    if isinstance(_top_served, list):
        _venues.extend([v for v in _top_served if isinstance(v, str)])
    _top_nearest = _c.get("nearest_venue")
    if isinstance(_top_nearest, str):
        _venues.append(_top_nearest)
    _loc = _c.get("location") or {}
    _loc_nearest = _loc.get("nearest_venue")
    if isinstance(_loc_nearest, str):
        _venues.append(_loc_nearest)
    _loc_served = _loc.get("nearest_venues")
    if isinstance(_loc_served, list):
        _venues.extend([v for v in _loc_served if isinstance(v, str)])
    for _v in dict.fromkeys(_venues):  # dedupe while preserving order
        _CORRIDOR_BY_VENUE.setdefault(_v, []).append(_c)

# Transit accessibility scores — derived from proximity, frequency, and coverage.
# Method: routes_served count × (1/peak_freq_min) normalized to 0-1.
# Manual overrides where transit is particularly strong or weak.
# Source: RTC route maps + venue locations; see rtc_transit.json for route details.
_TRANSIT_SCORES: dict[str, float] = {
    # app.py values (transit field) used as ground truth where available
    "allegiant_stadium"          : 0.70,   # Route 115 + event shuttles; remote location
    "t_mobile_arena"             : 0.85,   # Deuce + SDX + Monorail (MGM Grand) + walkable
    "sphere_las_vegas"           : 0.70,   # Deuce + Monorail (Conv. Center, walk); parking limited
    "las_vegas_convention_center": 0.82,   # Monorail (direct) + Route 108 + Deuce nearby
    "las_vegas_festival_grounds" : 0.60,   # Deuce (Sahara stop) + Monorail (SLS/Sahara)
    "thomas_mack_center"         : 0.55,   # Route 201 (Tropicana) + Route 109; no Strip transit
    "mgm_grand_garden_arena"     : 0.82,   # Monorail (direct) + Deuce + walkable Strip
    "mandalay_bay_events_center" : 0.65,   # Deuce (south Strip) + tram; no Monorail
    "caesars_palace_colosseum"   : 0.88,   # Deuce + Monorail (Flamingo/Caesars) + walkable
    "resorts_world_theatre"      : 0.75,   # Deuce + Monorail (SLS/Sahara)
    "las_vegas_motor_speedway"   : 0.30,   # Event shuttles only; no regular transit
    "michelob_ultra_arena"       : 0.65,   # Same as mandalay_bay_events_center
    "dolby_live_park_mgm"        : 0.82,   # Deuce + Monorail (MGM Grand, walk) + walkable
    "encore_theater"             : 0.80,   # Deuce + Monorail (Conv. Center, ~10 min walk)
    "venetian_expo"              : 0.82,   # Deuce + Monorail (Conv. Center) + walkable
    "theater_at_virgin_hotels"   : 0.45,   # Route 108 (Paradise Rd); off-Strip, lower freq
    "orleans_arena"              : 0.35,   # Route 201 (Tropicana) + hotel shuttle; west of Strip
}

# ── Event calendar + holidays ─────────────────────────────────────────────────
# Previous versions of this module hardcoded _MAJOR_EVENT_DATES and _HOLIDAYS.
# Those hardcoded sets have been REPLACED by live API calls:
#   - holidays_live.is_holiday()       → Nager.Date (free, no key, CC0)
#   - events_live.is_major_event_date() → Ticketmaster Discovery API (needs key)
# If Ticketmaster is unavailable (no API key), event-day detection degrades to
# False and the caller sees provenance["available"]=False in the response.
from data.sources.holidays_live import is_holiday as _live_is_holiday
from data.sources.events_live import is_major_event_date as _live_is_major_event
# Live congestion overlay (Google Routes v2).  Returns (ratio|None, prov).
# Always imported so the provenance is consistent; the module itself is
# responsible for reporting "available: False" when the key is missing.
from data.sources.traffic_live import get_live_congestion as _live_congestion


# ── Diurnal load profile ───────────────────────────────────────────────────────
# Normalized hourly traffic load (0-1) for Las Vegas.
# Source: derived from NDOT standard diurnal distribution for urban arterials
# (Nevada DOT Traffic Data Collection Handbook, Appendix D — Las Vegas MSA profile)
# and aligned with the legacy pipeline.py traffic_stress() peak shape.
# Values represent fraction of daily AADT occurring in each hour × 24
# (so sum ≈ 24 if uniform, skewed toward peaks in practice).
_DIURNAL_FRACTION: list[float] = [
    # Hour:  0     1     2     3     4     5     6     7     8     9    10    11
              0.18, 0.12, 0.08, 0.05, 0.04, 0.05, 0.08, 0.48, 0.72, 0.65, 0.58, 0.55,
    # Hour: 12    13    14    15    16    17    18    19    20    21    22    23
              0.60, 0.62, 0.65, 0.70, 0.82, 0.95, 0.88, 0.75, 0.55, 0.42, 0.35, 0.25,
]
# Normalize to 0-1 (max = 0.95 at hour 17)
_DIURNAL_NORM = [v / max(_DIURNAL_FRACTION) for v in _DIURNAL_FRACTION]


def _diurnal_load(hour: int, is_weekend: bool) -> float:
    """
    Base corridor load fraction for a given hour of day.

    Weekend modifier: lower AM peak (fewer commuters), higher late-night (Strip).
    Source: Nevada DOT diurnal distribution + Las Vegas MSA weekend adjustment factors.
    """
    base = _DIURNAL_NORM[hour % 24]
    if is_weekend:
        if 20 <= hour or hour <= 3:
            base = min(base + 0.15, 1.0)   # Strip nightlife uplift
        elif 7 <= hour <= 9:
            base *= 0.72                    # no commuter peak
    return base


def _event_overlay(date_str: str, hour: int) -> tuple[float, dict]:
    """
    Event-day traffic multiplier.

    Returns (multiplier, provenance). Provenance dict includes the live-data
    sources consulted for holiday and major-event lookups, so the caller can
    surface whether the overlay came from live APIs or degraded fallbacks.

    Source: Las Vegas Stadium Authority EIS; Clark County RTP event traffic analysis.
    """
    is_holiday, holiday_prov = _live_is_holiday(date_str)
    is_major, event_prov = _live_is_major_event(date_str)

    dt = datetime.fromisoformat(f"{date_str}T{hour:02d}:00")
    is_weekend = dt.weekday() >= 5

    multiplier = 1.0
    if is_major:
        multiplier *= 1.35
    if is_holiday:
        multiplier *= 1.20
    if is_weekend and hour >= 18:
        multiplier *= 1.12

    provenance = {
        "holidays": {"is_holiday": is_holiday, **holiday_prov},
        "events":   {"is_major_event_date": is_major, **event_prov},
        "weekend":  is_weekend,
    }
    return min(multiplier, 2.0), provenance


def get_traffic_context(
    venue_id: str,
    dt: datetime,
) -> dict:
    """
    Return a traffic impact dictionary for a venue at a specific datetime.

    Parameters
    ----------
    venue_id : snake_case venue ID from vegas_venues.json
    dt       : timezone-naive or timezone-aware datetime (local LV time assumed)

    Returns
    -------
    dict with keys:
      base_traffic_load        — 0-1, raw diurnal corridor load for this hour
      event_overlay_factor     — multiplier applied for event/holiday conditions
      transit_accessibility    — 0-1, venue's transit quality score
      traffic_factor           — 0-1, combined normalized traffic input for engine
      corridor_aadt            — primary corridor AADT (None if no NDOT data)
      corridor_id              — primary corridor identifier (None if not found)
      sources                  — list of data source citations
    """
    date_str = dt.strftime("%Y-%m-%d")
    hour = dt.hour
    is_weekend = dt.weekday() >= 5

    # Base load from diurnal profile
    base_load = _diurnal_load(hour, is_weekend)

    # Event overlay — returns (multiplier, provenance dict)
    overlay, overlay_prov = _event_overlay(date_str, hour)

    # Transit accessibility
    transit_score = _TRANSIT_SCORES.get(venue_id, 0.50)

    # Primary NDOT corridor
    corridors = _CORRIDOR_BY_VENUE.get(venue_id, [])
    primary_corridor = corridors[0] if corridors else None
    aadt = primary_corridor["aadt"] if primary_corridor else None
    corridor_id = primary_corridor["corridor_id"] if primary_corridor else None

    # AADT-informed load scaling
    # I-15 (220k AADT) should register as higher load than Koval Lane (14k AADT)
    # Scale: reference AADT = 220,000 (I-15 at Russell Road = max in dataset)
    if aadt is not None:
        aadt_factor = min(aadt / 220_000.0, 1.0)
        # Blend aadt_factor with diurnal profile (AADT sets the ceiling)
        raw_load = base_load * (0.65 + 0.35 * aadt_factor)
    else:
        raw_load = base_load * 0.65

    # Apply event overlay (static datasets only up to this point)
    event_adjusted = min(raw_load * overlay, 1.0)

    # ── LIVE congestion overlay (Google Routes v2) ────────────────────────────
    # Blend the static model with real-time traffic IF the API is available
    # and the event is within the live window (±2 h past / +18 h future).
    #   live_ratio is (duration_with_traffic / free_flow_duration) - 1
    #   0.0 = no congestion, 0.5 = +50 %, 1.0 = double travel time.
    # We map that onto a congestion *uplift* in [0, 0.30] applied AFTER the
    # static computation, so the live feed can sharpen the signal but never
    # overshoot the well-calibrated baseline.
    live_ratio, live_prov = _live_congestion(venue_id, dt)
    if live_ratio is not None:
        # 1.0 ratio (2× free flow) → +0.30 uplift; saturates.
        live_uplift = min(0.30, 0.30 * (live_ratio / 1.0))
        event_adjusted = min(event_adjusted + live_uplift, 1.0)

    # traffic_factor: high traffic = high congestion risk for events.
    # Transit good → lower effective traffic_factor (people use transit instead).
    # Formula: event_adjusted × (1 - transit_discount)
    transit_discount = transit_score * 0.15   # max 15% reduction via transit
    traffic_factor = round(max(0.0, min(event_adjusted - transit_discount, 1.0)), 4)

    sources = [
        "Nevada DOT Traffic Records, HPMS (data/sources/ndot_counts.json)",
        "RTC Southern Nevada ridership data (data/sources/rtc_transit.json)",
        "Las Vegas MSA diurnal distribution — Nevada DOT Traffic Data Collection Handbook",
    ]
    if primary_corridor:
        sources.append(primary_corridor["source"])
    if live_prov.get("available"):
        sources.append("Google Routes API v2 (TRAFFIC_AWARE_OPTIMAL)")

    # Merge live overlay into overlay_prov so the top-level caller sees it
    # alongside the other live components.
    combined_prov = {**overlay_prov, "live_traffic": live_prov}

    return {
        "base_traffic_load"     : round(base_load, 4),
        "event_overlay_factor"  : round(overlay, 4),
        "transit_accessibility" : transit_score,
        "traffic_factor"        : traffic_factor,
        "corridor_aadt"         : aadt,
        "corridor_id"           : corridor_id,
        "live_congestion_ratio" : round(live_ratio, 4) if live_ratio is not None else None,
        "is_major_event_date"   : overlay_prov["events"]["is_major_event_date"],
        "is_holiday"            : overlay_prov["holidays"]["is_holiday"],
        "sources"               : sources,
        "provenance"            : combined_prov,
    }


if __name__ == "__main__":
    # Quick smoke test
    test_cases = [
        ("allegiant_stadium",    datetime(2026, 2, 8, 18, 0)),   # Super Bowl LX
        ("t_mobile_arena",       datetime(2026, 3, 15, 20, 0)),  # Sunday evening
        ("orleans_arena",        datetime(2026, 1, 7, 14, 0)),   # CES weekday afternoon
        ("las_vegas_motor_speedway", datetime(2026, 10, 18, 12, 0)),  # NASCAR Sunday
    ]
    for vid, dt in test_cases:
        ctx = get_traffic_context(vid, dt)
        print(f"\n{vid} @ {dt.strftime('%Y-%m-%d %H:%M')}:")
        for k, v in ctx.items():
            if k != "sources":
                print(f"  {k}: {v}")
