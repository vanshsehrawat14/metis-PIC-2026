"""
data/sources/traffic_live.py — Google Routes API live traffic overlay.

Adds a live traffic overlay on top of the static NDOT AADT + diurnal base
layer using Google Routes travel-time ratios. This is a live route-duration
proxy, not a direct roadway sensor feed, and it is cached for 10 minutes.

Endpoint:
  POST https://routes.googleapis.com/directions/v2:computeRoutes
Docs:
  https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes

The field mask limits billing to just the two fields we need:
  routes.duration          — with current traffic (TRAFFIC_AWARE_OPTIMAL)
  routes.staticDuration    — free-flow / typical

Congestion ratio we return (dimensionless):
  ratio = duration / staticDuration − 1
         0.0  → free flow
         0.5  → 50 % slower than typical
         1.0  → twice as long as free flow
We clamp to [0, 2] defensively so one anomalous route can't dominate.

Auth:
  GOOGLE_ROUTES_API_KEY (preferred) or GOOGLE_MAPS_API_KEY (fallback).
  If neither is set, the module returns `available: False` with a
  precise `reason` and the caller falls back to the static AADT layer.
  No fabrication: when Google can't answer, we say so.

Cache:
  In-memory + on-disk (10 min TTL), keyed by (venue_id, 10-min time bucket).
  Routes are expensive (~$5/1k @ preferred routing); the cache keeps staging
  + production costs trivial without hiding short-horizon variation.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Configuration ──────────────────────────────────────────────────────────────
_ROUTES_URL    = "https://routes.googleapis.com/directions/v2:computeRoutes"
_TIMEOUT_S     = 6.0
_CACHE_TTL_S   = 600          # 10 minutes
_FIELD_MASK    = "routes.duration,routes.staticDuration,routes.distanceMeters"
_SRC_DIR       = Path(__file__).parent
_VENUE_FILE    = _SRC_DIR.parent / "venues" / "vegas_venues.json"
_CACHE_DIR     = _SRC_DIR / "_cache_traffic_live"
_CACHE_DIR.mkdir(exist_ok=True)

# Two stable origin anchors for every Vegas venue.  Picking *two* so one
# congested corridor (e.g. I-15 southbound jam) doesn't single-handedly
# decide the overlay.  We take the MIN ratio across both to avoid
# double-counting when the same bottleneck feeds both anchors.
#
#   HARRY_REID — Harry Reid International Airport (McCarran):
#               most inbound visitor traffic lands here.
#   LV_STRIP_N — Northern Strip anchor (Wynn / Encore area): catches
#                downtown + north-Strip traffic patterns.
_ANCHORS = [
    ("harry_reid",      36.0840, -115.1537, "Harry Reid International (LAS)"),
    ("lv_strip_north",  36.1304, -115.1660, "Las Vegas Strip — Wynn/Encore anchor"),
]

# Venue lat/lon index, loaded once.
def _load_venue_coords() -> dict[str, dict]:
    """
    Build venue_id → {lat, lon} index.  The venues JSON stores venues as a
    *list* of objects each with `venue_id` and `location.{lat,lon}`.
    """
    coords: dict[str, dict] = {}
    try:
        with open(_VENUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        venues = data.get("venues") or []
        if isinstance(venues, dict):
            # Defensive: accept both shapes in case the schema ever migrates.
            iter_ = venues.items()
            for vid, v in iter_:
                loc = (v or {}).get("location") or {}
                if "lat" in loc and "lon" in loc:
                    coords[vid] = {"lat": float(loc["lat"]), "lon": float(loc["lon"])}
        else:
            for v in venues:
                vid = (v or {}).get("venue_id")
                loc = (v or {}).get("location") or {}
                if vid and "lat" in loc and "lon" in loc:
                    coords[vid] = {"lat": float(loc["lat"]), "lon": float(loc["lon"])}
    except Exception:
        pass
    return coords

_VENUE_COORDS = _load_venue_coords()

# ── In-memory cache ────────────────────────────────────────────────────────────
_MEM_CACHE: dict[str, tuple[float, dict]] = {}   # {key: (ts, payload)}

def _cache_key(venue_id: str, dt: datetime) -> str:
    bucket = dt.strftime("%Y-%m-%d_%H") + f"_{(dt.minute // 10) * 10:02d}"
    return f"{venue_id}_{bucket}"

def _cache_get(key: str) -> Optional[dict]:
    hit = _MEM_CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL_S:
        return hit[1]

    # Disk cache (survives process restarts; useful for staging).
    disk = _CACHE_DIR / f"{key}.json"
    if disk.exists():
        try:
            mtime = disk.stat().st_mtime
            if time.time() - mtime < _CACHE_TTL_S:
                with open(disk, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                _MEM_CACHE[key] = (mtime, payload)
                return payload
        except Exception:
            pass
    return None

def _cache_put(key: str, payload: dict) -> None:
    _MEM_CACHE[key] = (time.time(), payload)
    try:
        with open(_CACHE_DIR / f"{key}.json", "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


# ── Key management ─────────────────────────────────────────────────────────────
def _resolve_api_key() -> Optional[str]:
    return (
        os.environ.get("GOOGLE_ROUTES_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or None
    )


# ── Core HTTP call ─────────────────────────────────────────────────────────────
def _compute_route(api_key: str, origin: tuple[float, float], dest: tuple[float, float]) -> dict:
    """
    Hit Routes v2 computeRoutes with TRAFFIC_AWARE_OPTIMAL.

    Raises requests exceptions on network failure; returns the parsed JSON
    body on HTTP 2xx.  The caller wraps this in try/except and falls back.
    """
    body = {
        "origin":      {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": dest[0],   "longitude": dest[1]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        # departureTime default = now; for future events the caller already
        # falls back to the static model so we don't need to set this.
    }
    resp = requests.post(
        _ROUTES_URL,
        headers={
            "Content-Type":     "application/json",
            "X-Goog-Api-Key":   api_key,
            "X-Goog-FieldMask": _FIELD_MASK,
        },
        json=body,
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_duration(s: str | None) -> float | None:
    """Google returns durations like "642s" → 642.0 (seconds)."""
    if not s or not isinstance(s, str) or not s.endswith("s"):
        return None
    try:
        return float(s[:-1])
    except ValueError:
        return None


# ── Public API ─────────────────────────────────────────────────────────────────
def get_live_congestion(venue_id: str, dt: datetime) -> tuple[Optional[float], dict]:
    """
    Return (congestion_ratio, provenance) for a venue at a specific datetime.

    congestion_ratio : float in [0, 2] or None
        `None` when the API is unavailable, the venue has no coordinates,
        or the request is too far in the future to benefit from live data.
        0.0 means free flow; 1.0 means twice the typical travel time.

    provenance : dict
        Always populated.  Standard keys:
          source, kind, live (bool), available (bool), reason (on failure),
          retrieved_at, anchors_sampled, ratios_per_anchor, cache_hit.
    """
    now = datetime.now(timezone.utc).timestamp()
    event_ts = dt.timestamp() if dt.tzinfo else dt.replace(tzinfo=timezone.utc).timestamp()

    # Live traffic is meaningful only for "nowish" windows.  Beyond ~18 h
    # Google is effectively serving a synthetic estimate; we prefer our own
    # explicit diurnal model in that regime.
    if event_ts - now > 18 * 3600 or now - event_ts > 2 * 3600:
        return None, {
            "source": "google_routes_v2",
            "kind": "live",
            "live": False,
            "available": False,
            "reason": "event time outside live-traffic window (±2 h past / +18 h future)",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    coords = _VENUE_COORDS.get(venue_id)
    if not coords:
        return None, {
            "source": "google_routes_v2",
            "kind": "live",
            "live": False,
            "available": False,
            "reason": f"no lat/lon registered for venue '{venue_id}' in vegas_venues.json",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    api_key = _resolve_api_key()
    if not api_key:
        return None, {
            "source": "google_routes_v2",
            "kind": "live",
            "live": False,
            "available": False,
            "reason": "neither GOOGLE_ROUTES_API_KEY nor GOOGLE_MAPS_API_KEY is set",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # Cache lookup.
    key = _cache_key(venue_id, dt)
    cached = _cache_get(key)
    if cached is not None:
        cached = {**cached, "cache_hit": True}
        return cached.get("congestion_ratio"), cached

    # Fire one request per anchor.  If ANY anchor fails, we still aggregate
    # over the successes (better than failing the whole overlay).
    ratios: list[dict] = []
    errors: list[str] = []
    dest = (coords["lat"], coords["lon"])
    for a_id, a_lat, a_lon, a_name in _ANCHORS:
        try:
            payload = _compute_route(api_key, (a_lat, a_lon), dest)
            route = (payload.get("routes") or [{}])[0]
            d_live   = _parse_duration(route.get("duration"))
            d_static = _parse_duration(route.get("staticDuration"))
            if d_live is None or d_static is None or d_static <= 0:
                errors.append(f"{a_id}: missing duration fields in response")
                continue
            ratio = max(0.0, min(d_live / d_static - 1.0, 2.0))
            ratios.append({
                "anchor_id":   a_id,
                "anchor_name": a_name,
                "duration_s":          round(d_live, 1),
                "static_duration_s":   round(d_static, 1),
                "distance_m":          route.get("distanceMeters"),
                "congestion_ratio":    round(ratio, 4),
            })
        except requests.exceptions.RequestException as e:
            errors.append(f"{a_id}: {type(e).__name__}: {e}")
            continue
        except Exception as e:
            errors.append(f"{a_id}: {type(e).__name__}: {e}")
            continue

    if not ratios:
        prov = {
            "source": "google_routes_v2",
            "kind": "live",
            "live": False,
            "available": False,
            "reason": "all anchor requests failed",
            "errors": errors,
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        return None, prov

    # Aggregate: take the MEAN ratio across anchors.  Mean, not max, because
    # a single congested approach shouldn't double-count if the venue has
    # multiple access routes.
    avg_ratio = sum(r["congestion_ratio"] for r in ratios) / len(ratios)
    prov = {
        "source": "google_routes_v2",
        "kind": "live",
        "live": True,
        "available": True,
        "congestion_ratio": round(avg_ratio, 4),
        "anchors_sampled": len(ratios),
        "ratios_per_anchor": ratios,
        "errors": errors,   # empty list if all succeeded
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cache_ttl_s": _CACHE_TTL_S,
        "cache_hit": False,
    }
    _cache_put(key, prov)
    return avg_ratio, prov


if __name__ == "__main__":
    # Manual smoke test — requires GOOGLE_ROUTES_API_KEY set.
    test_cases = [
        ("allegiant_stadium",    datetime.now()),
        ("t_mobile_arena",       datetime.now()),
        ("sphere_las_vegas",     datetime.now()),
    ]
    print(f"API key set: {bool(_resolve_api_key())}")
    for vid, dt in test_cases:
        ratio, prov = get_live_congestion(vid, dt)
        print(f"\n{vid}:")
        print(f"  ratio={ratio}  live={prov.get('live')}  available={prov.get('available')}")
        if prov.get("reason"):
            print(f"  reason: {prov['reason']}")
        for anc in prov.get("ratios_per_anchor", []):
            print(f"    anchor {anc['anchor_id']}: {anc['duration_s']}s vs {anc['static_duration_s']}s  ratio={anc['congestion_ratio']}")
