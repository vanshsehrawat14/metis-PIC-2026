"""
supabase/seed.py — one-off seed script for the scenario_library table.

Populates the landing-page scenario gallery with canonical Las Vegas events
that showcase the simulation engine at different scales and topologies.

Idempotent: each row is upserted on its slug, so re-running the script after
editing a scenario will update the row in place rather than duplicating it.

Usage:
    # Requires SUPABASE_URL + SUPABASE_SERVICE_KEY in the environment (or .env)
    python supabase/seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from api.persistence import get_persistence


SCENARIOS: list[dict] = [
    {
        "slug": "super-bowl-lviii",
        "name": "Super Bowl LVIII",
        "description": (
            "Allegiant Stadium at capacity for the biggest NFL event of 2024. "
            "Simulates the arrival surge, security throughput, and traffic overlay "
            "from the documented 2024-02-11 game."
        ),
        "display_order": 10,
        "is_canonical": True,
        "request_json": {
            "venue_id": "allegiant_stadium",
            "attendance": 65000,
            "event_type": "nfl",
            "event_date": "2026-02-08",
            "event_time": "15:30",
            "service_rate_tier": "operational",
        },
    },
    {
        "slug": "ufc-at-sphere",
        "name": "UFC 306 at Sphere",
        "description": (
            "The Noche UFC card at the Sphere — first major combat-sports event "
            "at the venue. Demonstrates how a novel venue topology with limited "
            "egress paths affects wait-time distributions."
        ),
        "display_order": 20,
        "is_canonical": True,
        "request_json": {
            "venue_id": "sphere_las_vegas",
            "attendance": 18000,
            "event_type": "boxing_mma",
            "event_date": "2026-09-12",
            "event_time": "18:00",
            "service_rate_tier": "operational",
        },
    },
    {
        "slug": "ces-2026",
        "name": "CES 2026",
        "description": (
            "Las Vegas Convention Center on peak CES day. Convention-scale "
            "attendance with rolling arrivals — a fundamentally different "
            "arrival pattern from concerts or sports events."
        ),
        "display_order": 30,
        "is_canonical": True,
        "request_json": {
            "venue_id": "las_vegas_convention_center",
            "attendance": 130000,
            "event_type": "convention",
            "event_date": "2026-01-07",
            "event_time": "09:00",
            "service_rate_tier": "operational",
        },
    },
    {
        "slug": "f1-las-vegas-gp",
        "name": "F1 Las Vegas Grand Prix",
        "description": (
            "Saturday-night street race on the Strip. Traffic overlay is "
            "dominated by course-side closures — a stress case for the "
            "NDOT corridor AADT inputs."
        ),
        "display_order": 40,
        "is_canonical": True,
        "request_json": {
            "venue_id": "las_vegas_convention_center",
            "attendance": 100000,
            "event_type": "festival",
            "event_date": "2026-11-21",
            "event_time": "22:00",
            "service_rate_tier": "operational",
        },
    },
    {
        "slug": "raiders-sunday",
        "name": "Raiders Home Sunday",
        "description": (
            "A typical Raiders home game at Allegiant — the regular-season "
            "benchmark for the engine. Uses auto-fetched weather and the live "
            "Nager.Date holiday overlay for the selected date."
        ),
        "display_order": 50,
        "is_canonical": True,
        "request_json": {
            "venue_id": "allegiant_stadium",
            "attendance": 62000,
            "event_type": "nfl",
            "event_date": "2026-10-18",
            "event_time": "13:25",
            "service_rate_tier": "operational",
        },
    },
]


def main() -> int:
    p = get_persistence()
    if not p.configured:
        print(
            "[seed] SUPABASE_URL / SUPABASE_SERVICE_KEY not set. "
            "Aborting — no rows written."
        )
        return 1

    print(f"[seed] Upserting {len(SCENARIOS)} scenarios into scenario_library...")
    for s in SCENARIOS:
        p.upsert_scenario(s)
        print(f"  [OK] {s['slug']:<28s} {s['name']}")
    print("[seed] Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
