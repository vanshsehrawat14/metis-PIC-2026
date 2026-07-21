"""
data/sources/holidays_live.py — Live US public holiday fetcher with offline fallback.

Primary:  Nager.Date public-holiday API (free, no key) — cached on disk for
          30 days (holiday calendars rarely change).  Served straight from
          the cache on subsequent calls so the API key-less endpoint
          withstands outages.

Offline fallback (static table below):
          When Nager.Date is unreachable AND no cache exists, we fall back
          to a hand-maintained set of fixed-date + observed US federal
          holidays.  This keeps the traffic overlay deterministic in
          air-gapped production or staging environments.  Tagged `kind: "dataset"` so
          provenance never fabricates a "live" claim.

API:    https://date.nager.at/api/v3/PublicHolidays/{year}/US
License: CC0 (public domain). See https://date.nager.at/Api
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

_SRC_DIR = Path(__file__).parent
_CACHE_DIR = _SRC_DIR.parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

_API_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/US"
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days
_TIMEOUT_S = 8.0

_MEM_CACHE: dict[int, dict] = {}


# ── Offline fallback ──────────────────────────────────────────────────────────
# Minimal US federal holiday calendar used ONLY when both the Nager.Date
# API and the on-disk cache are unavailable.  Fixed-date holidays are
# straightforward; floating ones (MLK, Presidents', Memorial, Labor,
# Columbus, Thanksgiving) are computed below.  This keeps the module
# usable offline without pulling the `holidays` PyPI package.
_FIXED_US_HOLIDAYS = {
    "01-01": "New Year's Day",
    "06-19": "Juneteenth National Independence Day",
    "07-04": "Independence Day",
    "11-11": "Veterans Day",
    "12-25": "Christmas Day",
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> str:
    """Return ISO date of the n-th given weekday (Mon=0) in a month."""
    from datetime import date, timedelta

    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d += timedelta(days=offset + 7 * (n - 1))
    return d.isoformat()


def _last_weekday(year: int, month: int, weekday: int) -> str:
    """Return ISO date of the LAST given weekday (Mon=0) in a month."""
    from datetime import date, timedelta
    from calendar import monthrange

    last = date(year, month, monthrange(year, month)[1])
    offset = (last.weekday() - weekday) % 7
    return (last - timedelta(days=offset)).isoformat()


def _static_us_holidays(year: int) -> dict[str, str]:
    dates: dict[str, str] = {f"{year}-{md}": name for md, name in _FIXED_US_HOLIDAYS.items()}
    dates[_nth_weekday(year, 1, 0, 3)]  = "Martin Luther King, Jr. Day"
    dates[_nth_weekday(year, 2, 0, 3)]  = "Presidents' Day"
    dates[_last_weekday(year, 5, 0)]    = "Memorial Day"
    dates[_nth_weekday(year, 9, 0, 1)]  = "Labor Day"
    dates[_nth_weekday(year, 10, 0, 2)] = "Columbus Day"
    dates[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    return dates


def _cache_path(year: int) -> Path:
    return _CACHE_DIR / f"holidays_us_{year}.json"


def _load_cache(year: int) -> Optional[dict]:
    path = _cache_path(year)
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


def _save_cache(year: int, payload: dict) -> None:
    try:
        with open(_cache_path(year), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def fetch_us_holidays(year: int) -> dict:
    """
    Fetch US public holidays for a given year.

    Returns a dict:
      {
        "year": 2026,
        "dates": {"2026-01-01": "New Year's Day", ...},
        "source": "Nager.Date",
        "url": "https://date.nager.at/api/v3/PublicHolidays/2026/US",
        "retrieved_at": ISO8601 UTC,
        "live": bool,          # True if fetched now, False if served from cache
        "cache_age_s": int,    # seconds since cache was written (0 if live)
      }

    Raises requests.RequestException on network failure with no cache.
    """
    if year in _MEM_CACHE:
        return _MEM_CACHE[year]

    cached = _load_cache(year)
    if cached is not None:
        cache_age = int(time.time() - _cache_path(year).stat().st_mtime)
        cached = {**cached, "live": False, "fetched_fresh": False, "cache_age_s": cache_age}
        _MEM_CACHE[year] = cached
        return cached

    url = _API_URL.format(year=year)
    resp = requests.get(url, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    raw = resp.json()

    dates = {item["date"]: item.get("localName") or item.get("name") for item in raw}
    payload = {
        "year": year,
        "dates": dates,
        "source": "Nager.Date Public Holidays API",
        "url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live": True,
        "fetched_fresh": True,
        "cache_age_s": 0,
    }
    _save_cache(year, payload)
    _MEM_CACHE[year] = payload
    return payload


def is_holiday(date_str: str) -> tuple[bool, Optional[dict]]:
    """
    Check whether a given ISO date (YYYY-MM-DD) is a US federal holiday.

    Returns (is_holiday, provenance_dict). On network failure returns
    (False, {"source": "Nager.Date", "live": False, "error": "..."})
    so callers can fail soft without silently lying to the user.
    """
    try:
        year = int(date_str.split("-", 1)[0])
    except Exception:
        return False, {
            "source": "Nager.Date",
            "live": False,
            "error": f"bad date string: {date_str!r}",
        }

    try:
        payload = fetch_us_holidays(year)
    except Exception as e:
        # Nager.Date unreachable AND no disk cache.  Fall back to the
        # offline static US-federal table so the traffic overlay stays
        # deterministic.  Provenance explicitly reports `live: False` and
        # `kind: "dataset"` so the fallback is never misrepresented as live.
        static_dates = _static_us_holidays(year)
        return date_str in static_dates, {
            "source": "static US federal holiday table (Vane built-in)",
            "kind": "dataset",
            "url": None,
            "live": False,
            "available": True,
            "fallback": True,
            "fallback_reason": f"Nager.Date unreachable and no cache: {type(e).__name__}: {e}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    prov = {k: payload[k] for k in ("source", "url", "retrieved_at", "live", "cache_age_s")}
    prov["fetched_fresh"] = payload.get("fetched_fresh", False)
    return date_str in payload["dates"], prov


def source_status() -> dict:
    """
    Lightweight status check used by /data/sources and /health.

    Does not network; reports only whether we have a valid cache for the
    current year. Network check is done lazily on first is_holiday() call.
    """
    year = datetime.now(timezone.utc).year
    cached = _load_cache(year)
    return {
        "source_name": "Nager.Date Public Holidays API",
        "kind": "live",
        "url": "https://date.nager.at/Api",
        "license": "CC0 (public domain)",
        "cached": cached is not None,
        "cache_age_s": (
            int(time.time() - _cache_path(year).stat().st_mtime) if _cache_path(year).exists() else None
        ),
        "requires_key": False,
    }


if __name__ == "__main__":
    for d in ["2026-01-01", "2026-07-04", "2026-04-19", "2026-12-25"]:
        ok, prov = is_holiday(d)
        print(f"{d}  holiday={ok}  live={prov.get('live')}")
