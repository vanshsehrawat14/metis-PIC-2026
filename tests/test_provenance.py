from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from data.sources import holidays_live


def test_holiday_cache_payload_is_not_marked_live(monkeypatch):
    monkeypatch.setattr(holidays_live, "_MEM_CACHE", {})

    year = 2026
    payload = {
        "year": year,
        "dates": {"2026-07-04": "Independence Day"},
        "source": "Nager.Date Public Holidays API",
        "url": f"https://date.nager.at/api/v3/PublicHolidays/{year}/US",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live": True,
        "fetched_fresh": True,
        "cache_age_s": 0,
    }
    monkeypatch.setattr(holidays_live, "_load_cache", lambda _year: payload)
    monkeypatch.setattr(holidays_live, "_cache_path", lambda _year: Path(__file__))

    cached = holidays_live.fetch_us_holidays(year)

    assert cached["live"] is False
    assert cached["fetched_fresh"] is False
    assert cached["cache_age_s"] >= 0
