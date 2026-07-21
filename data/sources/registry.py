"""
data/sources/registry.py — Central registry of all data sources used by Vane.

Every data source declares:
  - kind: "live"       → fetched from an external API at request time
          "cached"     → API-derived, cached on disk (e.g. ERA5 historical)
          "literature" → peer-reviewed / standards body constants (service rates, Fruin)
          "dataset"    → static published dataset (NDOT AADT, RTC ridership)
  - url: where to inspect the underlying source
  - license: usage license
  - requires_key: whether an env-var API key is required
  - available: whether the source is usable right now
  - notes: one-line description

The /data/sources endpoint returns this registry so operators and reviewers can see exactly
what is live vs cached, at what freshness, and under what license.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.sources.weather import DATA_SOURCE_ENTRY as _WEATHER_ENTRY
from data.sources.holidays_live import source_status as _holiday_status
from data.sources.events_live import source_status as _events_status

_CACHE_DIR = Path(__file__).parent.parent / "cache"
_PARQUET_WEATHER = _CACHE_DIR / "vegas_weather_2022_2024.parquet"


def _weather_live_available() -> bool:
    """Open-Meteo is a free public API — assume available unless network is hard-down."""
    return True


def get_data_sources() -> dict[str, Any]:
    """
    Build the full data-source report.

    Returns:
      {
        "generated_at": ISO8601,
        "summary": { "live": int, "cached": int, "literature": int, "dataset": int, "total": int },
        "sources": [ {...}, {...}, ... ]
      }
    """
    entries: list[dict[str, Any]] = []

    # Weather — live Open-Meteo forecast + cached ERA5 historical
    entries.append({
        "id": "weather_forecast",
        "name": "Open-Meteo Forecast API",
        "kind": "live",
        "url": "https://open-meteo.com/en/docs",
        "license": "CC BY 4.0",
        "requires_key": False,
        "available": _weather_live_available(),
        "notes": "Hourly forecast for event-day weather severity. Called per simulation when event_date is supplied.",
        "variables": list(_WEATHER_ENTRY.get("variables_used", [])),
    })
    entries.append({
        "id": "weather_historical",
        "name": "Open-Meteo ERA5 Historical Archive",
        "kind": "cached",
        "url": _WEATHER_ENTRY.get("url"),
        "license": _WEATHER_ENTRY.get("license"),
        "requires_key": False,
        "available": _PARQUET_WEATHER.exists(),
        "notes": _WEATHER_ENTRY.get("notes", ""),
        "temporal_coverage": _WEATHER_ENTRY.get("temporal_coverage"),
        "cache_path": str(_PARQUET_WEATHER) if _PARQUET_WEATHER.exists() else None,
    })

    # Holidays — live Nager.Date
    hs = _holiday_status()
    entries.append({
        "id": "holidays",
        "name": hs["source_name"],
        "kind": hs["kind"],
        "url": hs["url"],
        "license": hs["license"],
        "requires_key": hs["requires_key"],
        "available": True,  # public endpoint, no key
        "notes": "US public holidays. Used to scale event-day traffic overlay.",
        "cached": hs["cached"],
        "cache_age_s": hs["cache_age_s"],
    })

    # Events — live Ticketmaster (requires key)
    es = _events_status()
    entries.append({
        "id": "events_calendar",
        "name": es["source_name"],
        "kind": es["kind"],
        "url": es["url"],
        "license": es["license"],
        "requires_key": es["requires_key"],
        "key_env_var": es.get("key_env_var"),
        "available": es["available"],
        "notes": (
            "Live Las Vegas metro event calendar from the Ticketmaster Discovery catalog. "
            "When TICKETMASTER_API_KEY is set it replaces the old hardcoded calendar; "
            "major-event classification is still a venue-keyword heuristic, not direct attendance data."
        ),
    })

    # NDOT AADT — static published dataset (AADT is by definition annual)
    entries.append({
        "id": "ndot_aadt",
        "name": "Nevada DOT Traffic Information (AADT)",
        "kind": "dataset",
        "url": "https://www.dot.nv.gov/doing-business/about-ndot/ndot-divisions/operations/traffic-information",
        "license": "Public domain (US state DOT data)",
        "requires_key": False,
        "available": True,
        "notes": "Per-corridor AADT counts from NDOT's TRINA traffic-records system. "
                 "Annual average is the canonical statistic; realtime counts would not "
                 "change the analysis.",
        "path": "data/sources/ndot_counts.json",
    })

    # Live traffic — Google Routes v2 (duration_in_traffic)
    _routes_key_set = bool(
        os.environ.get("GOOGLE_ROUTES_API_KEY") or os.environ.get("GOOGLE_MAPS_API_KEY")
    )
    entries.append({
        "id": "google_routes_live_traffic",
        "name": "Google Routes API v2 (TRAFFIC_AWARE_OPTIMAL)",
        "kind": "live" if _routes_key_set else "dataset",
        "url": "https://developers.google.com/maps/documentation/routes",
        "license": "Google Maps Platform Terms of Service (paid API)",
        "requires_key": True,
        "key_env_var": "GOOGLE_ROUTES_API_KEY",
        "available": _routes_key_set,
        "notes": (
            "Real-time travel-time ratio (duration_in_traffic / staticDuration) "
            "from two Las Vegas anchor origins (Harry Reid Intl + Northern Strip) "
            "to each venue. Blended as an uplift on the static AADT model, cached "
            "10 min. When the key is absent the live overlay is skipped and the "
            "diurnal + AADT base model is used instead — provenance reports "
            "`live: false` so nothing is fabricated."
        ),
        "path": "data/sources/traffic_live.py",
    })

    # RTC transit — static dataset
    entries.append({
        "id": "rtc_transit",
        "name": "RTC Southern Nevada",
        "kind": "dataset",
        "url": "https://www.rtcsnv.com/",
        "license": "Public domain (regional transit authority data)",
        "requires_key": False,
        "available": True,
        "notes": "Route-level ridership and coverage map from the Regional Transportation "
                 "Commission of Southern Nevada. Local route-level figures are a static, "
                 "manually refreshed dataset derived from RTC reports and maps.",
        "path": "data/sources/rtc_transit.json",
    })

    # Service rates — literature tier (conservative textbook values)
    entries.append({
        "id": "service_rates_literature",
        "name": "CISA / Fruin / HCM6 / IAAM service-rate benchmarks",
        "kind": "literature",
        "url": "https://www.cisa.gov/resources-tools/resources/public-venue-security-screening-guide",
        "license": "Government / academic citations",
        "requires_key": False,
        "available": True,
        "notes": "Peer-reviewed and standards-body service-rate constants "
                 "(CISA Public Venue Security Screening Guide, Fruin pedestrian LOS, "
                 "HCM6 capacity, IAAM venue benchmarks). Conservative \u2014 over-predicts "
                 "wait vs. modern venue operations.",
        "path": "data/sources/service_rates.py",
    })

    # Service rates — operational tier (back-calibrated from documented LV events)
    entries.append({
        "id": "service_rates_operational",
        "name": "Operational back-calibration (Super Bowl LVIII, UFC 306, CES 2024)",
        "kind": "dataset",
        "url": None,
        "license": "Derived from public after-action reports (LVMPD) and venue operations briefings",
        "requires_key": False,
        "available": True,
        "notes": "Empirically back-calibrated service rates reflecting real-world venue "
                 "throughput \u2014 experienced staff, pre-screened fast lanes, optimised "
                 "entry configs. Use `service_rate_tier=\"literature\"` on any simulate "
                 "call to fall back to the conservative published values.",
        "path": "data/sources/service_rates.py",
    })

    # Venue profiles — dataset with citations
    entries.append({
        "id": "venue_profiles",
        "name": "Las Vegas venue infrastructure profiles",
        "kind": "dataset",
        "url": None,
        "license": "Curated from public sources (LVSA, AEG, NHL filings, press reporting)",
        "requires_key": False,
        "available": True,
        "notes": "Local curated dataset — capacity and topology per venue. Each field "
                 "carries a source citation and confidence level.",
        "path": "data/venues/vegas_venues.json",
    })

    # Revenue benchmarks — not a live API; industry midpoints + model stress from simulation
    entries.append({
        "id": "revenue_benchmarks",
        "name": "NAC / Technomic-style secondary-spend + attach-rate benchmarks",
        "kind": "literature",
        "url": "https://www.naconline.org/",
        "license": "Industry survey summaries (user must comply with NAC/Technomic terms if republishing raw tables)",
        "requires_key": False,
        "available": True,
        "notes": (
            "Concession/merch per-capita and purchase probabilities are static midpoints "
            "informed by NAC/Technomic foodservice venue ranges — the same *class* of "
            "figures as pro-forma models. They are then stressed by *live simulation "
            "outputs* (concession wait, corridor LOS proxy, HES). Average ticket price "
            "on the request scales future $ linearly; secondary baselines are scaled by a "
            "sublinear spend-tier factor τ=(P/95)^0.42 (clamped) — a documented heuristic, "
            "not POS data. See metrics.RevenueImpact + revenue.provenance in API responses."
        ),
        "path": "simulation/metrics.py",
    })

    # Summary counts
    summary: dict[str, int] = {"live": 0, "cached": 0, "literature": 0, "dataset": 0, "total": 0}
    for e in entries:
        summary[e["kind"]] = summary.get(e["kind"], 0) + 1
        summary["total"] += 1
    summary["live_available"] = sum(
        1 for e in entries if e["kind"] == "live" and e.get("available")
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "sources": entries,
    }
