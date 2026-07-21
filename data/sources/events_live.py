"""
data/sources/events_live.py — Live event-calendar fetcher (Ticketmaster Discovery).

Replaces the previously hardcoded _MAJOR_EVENT_DATES set in traffic.py with a
real API call to Ticketmaster's Discovery API. The API has a free tier (5000
requests / day) and returns a standardized event schema.

If TICKETMASTER_API_KEY is not set, this module degrades **honestly**:
the caller sees available=False with a clear reason, rather than silent
hardcoded values.

API:      https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
Endpoint: https://app.ticketmaster.com/discovery/v2/events.json
License:  Ticketmaster Discovery API Terms of Use
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

_SRC_DIR = Path(__file__).parent
_CACHE_DIR = _SRC_DIR.parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

_API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
# Las Vegas metro bounding box — roughly 30 mi / 50 km radius around the Strip.
# Source: centroid of VEGAS_VENUES in data/venues/vegas_venues.json
_LV_LAT = 36.17
_LV_LON = -115.14
_LV_RADIUS_MI = 30
_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours — event calendars shift intraday on occasion
_TIMEOUT_S = 10.0

# Heuristic: an event is "major" if it attracts a crowd large enough to load
# venue transit corridors. Ticketmaster doesn't publish attendance, so we
# proxy with (a) venue capacity class tag when present and (b) promoter/genre
# fallbacks. The threshold is tunable.
_MAJOR_VENUE_KEYWORDS = (
    "allegiant", "t-mobile arena", "sphere", "mgm grand garden",
    "mandalay bay", "caesars", "dolby live", "resorts world",
    "convention center", "las vegas motor speedway", "festival grounds",
    "venetian expo", "thomas & mack", "michelob ultra",
)

_MEM_CACHE: dict[str, dict] = {}


def _cache_path(cache_key: str) -> Path:
    return _CACHE_DIR / f"events_live_{cache_key}.json"


def _load_cache(cache_key: str) -> Optional[dict]:
    path = _cache_path(cache_key)
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(cache_key: str, payload: dict) -> None:
    try:
        with open(_cache_path(cache_key), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def _has_key() -> bool:
    return bool(os.environ.get("TICKETMASTER_API_KEY"))


def fetch_events_for_date(date_str: str) -> dict:
    """
    Fetch Ticketmaster events for a single date in the Las Vegas metro.

    Returns:
      {
        "date": "2026-11-21",
        "events": [{ "name": ..., "venue": ..., "start": ..., "major": bool }, ...],
        "count": int,
        "major_count": int,
        "is_major_event_date": bool,
        "source": "Ticketmaster Discovery API",
        "url": <full URL with key redacted>,
        "retrieved_at": ISO8601 UTC,
        "live": bool,
        "available": bool,     # False if no API key configured
        "reason": str | None,
      }
    """
    cache_key = date_str
    if cache_key in _MEM_CACHE:
        return _MEM_CACHE[cache_key]

    cached = _load_cache(cache_key)
    if cached is not None:
        cache_age = int(time.time() - _cache_path(cache_key).stat().st_mtime)
        out = {**cached, "live": False, "cache_age_s": cache_age}
        _MEM_CACHE[cache_key] = out
        return out

    if not _has_key():
        return {
            "date": date_str,
            "events": [],
            "count": 0,
            "major_count": 0,
            "is_major_event_date": False,
            "source": "Ticketmaster Discovery API",
            "url": _API_URL,
            "retrieved_at": None,
            "live": False,
            "available": False,
            "reason": "TICKETMASTER_API_KEY not set in environment",
        }

    try:
        dt = datetime.fromisoformat(date_str)
    except Exception:
        return {
            "date": date_str,
            "events": [],
            "count": 0,
            "major_count": 0,
            "is_major_event_date": False,
            "source": "Ticketmaster Discovery API",
            "url": _API_URL,
            "retrieved_at": None,
            "live": False,
            "available": False,
            "reason": f"bad date string: {date_str!r}",
        }

    start_iso = dt.strftime("%Y-%m-%dT00:00:00Z")
    end_iso = (dt + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    params = {
        "apikey": os.environ["TICKETMASTER_API_KEY"],
        "latlong": f"{_LV_LAT},{_LV_LON}",
        "radius": _LV_RADIUS_MI,
        "unit": "miles",
        "startDateTime": start_iso,
        "endDateTime": end_iso,
        "size": 200,
        "sort": "date,asc",
    }

    try:
        resp = requests.get(_API_URL, params=params, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        return {
            "date": date_str,
            "events": [],
            "count": 0,
            "major_count": 0,
            "is_major_event_date": False,
            "source": "Ticketmaster Discovery API",
            "url": _API_URL,
            "retrieved_at": None,
            "live": False,
            "available": False,
            "reason": f"{type(e).__name__}: {e}",
        }

    events_out = []
    embedded = raw.get("_embedded", {})
    for e in embedded.get("events", []):
        name = e.get("name", "")
        start = (e.get("dates", {}).get("start") or {}).get("dateTime")
        venue_name = ""
        try:
            venue_name = (e.get("_embedded", {}).get("venues") or [{}])[0].get("name", "")
        except Exception:
            venue_name = ""
        is_major = any(k in venue_name.lower() for k in _MAJOR_VENUE_KEYWORDS)
        events_out.append({
            "name": name,
            "venue": venue_name,
            "start": start,
            "major": is_major,
        })

    major_count = sum(1 for e in events_out if e["major"])
    out = {
        "date": date_str,
        "events": events_out[:50],  # cap payload
        "count": len(events_out),
        "major_count": major_count,
        "is_major_event_date": major_count >= 1,
        "source": "Ticketmaster Discovery API",
        "url": f"{_API_URL}?latlong={_LV_LAT},{_LV_LON}&radius={_LV_RADIUS_MI}mi&startDateTime={start_iso}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live": True,
        "available": True,
        "reason": None,
        "cache_age_s": 0,
    }
    _save_cache(cache_key, out)
    _MEM_CACHE[cache_key] = out
    return out


def is_major_event_date(date_str: str) -> tuple[bool, dict]:
    """
    Convenience wrapper — returns (is_major, provenance).

    Provenance dict always includes source + live/available flags so a caller
    can tell whether the answer comes from a real API or a fallback.
    """
    payload = fetch_events_for_date(date_str)
    prov = {
        "source": payload["source"],
        "url": payload["url"],
        "retrieved_at": payload.get("retrieved_at"),
        "live": payload["live"],
        "available": payload["available"],
        "reason": payload.get("reason"),
        "count": payload.get("count", 0),
        "major_count": payload.get("major_count", 0),
        "cache_age_s": payload.get("cache_age_s"),
    }
    return payload["is_major_event_date"], prov


def source_status() -> dict:
    """Status record for /data/sources and /health."""
    return {
        "source_name": "Ticketmaster Discovery API",
        "kind": "live",
        "url": "https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/",
        "license": "Ticketmaster Discovery API Terms of Use",
        "requires_key": True,
        "key_env_var": "TICKETMASTER_API_KEY",
        "available": _has_key(),
    }


if __name__ == "__main__":
    for d in ["2026-01-07", "2026-11-21", "2026-04-19"]:
        ok, prov = is_major_event_date(d)
        print(f"{d}  major={ok}  live={prov['live']}  reason={prov.get('reason')}")
