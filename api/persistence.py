"""
api/persistence.py — Supabase-backed persistence for Vane.

Thin wrapper around the Supabase REST API. Lazy-initialized from the
SUPABASE_URL + SUPABASE_SERVICE_KEY environment variables.

Gracefully no-ops when Supabase is not configured so local dev without a
Supabase project still works: every persistence method returns a sensible
default (None, [], etc.) and `configured` is False.

We call Supabase via plain httpx requests against its PostgREST interface
rather than pulling in the official `supabase-py` SDK. Motivations:
  - Zero extra dependency beyond httpx (already in requirements.txt).
  - supabase-py has historically had sync/async model churn; PostgREST is stable.
  - Direct REST calls are trivially inspectable in logs.

Tables (see supabase/migrations/0001_init.sql):
  - runs             (id, venue_id, event_type, attendance, event_date,
                      service_rate_tier, request_json, response_json,
                      hes, srs, wait_mean, is_public, created_at)
  - conversations    (id, messages, scenario, created_at, updated_at)
  - scenario_library (slug, name, description, request_json, is_canonical,
                      display_order, created_at)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_REST_PATH = "/rest/v1"


class Persistence:
    """
    Supabase persistence adapter.

    Construction is cheap — the HTTP client is created lazily on first use.
    Check `self.configured` before assuming any call will reach Supabase.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        timeout: float = 8.0,
    ) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.service_key = service_key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @property
    def configured(self) -> bool:
        return bool(self.url and self.service_key)

    def _client_or_none(self) -> Optional[httpx.Client]:
        if not self.configured:
            return None
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.url + _REST_PATH,
                headers={
                    "apikey": self.service_key,
                    "Authorization": f"Bearer {self.service_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    def reachable(self) -> bool:
        """Quick readiness probe for the /health endpoint."""
        c = self._client_or_none()
        if c is None:
            return False
        try:
            r = c.get("/scenario_library", params={"select": "slug", "limit": "1"})
            return r.status_code < 500
        except Exception as e:
            logger.warning("Supabase unreachable: %s", e)
            return False

    # ── runs ─────────────────────────────────────────────────────────────────

    def save_run(
        self,
        *,
        request: dict,
        response: dict,
    ) -> Optional[str]:
        """
        Persist one simulation run and return its uuid.

        Returns None if Supabase isn't configured (caller must treat this as
        "saving is unavailable right now" and show no share link).
        """
        c = self._client_or_none()
        if c is None:
            return None

        metrics = (response or {}).get("metrics") or {}
        params = (response or {}).get("parameters") or {}
        experience = metrics.get("experience") or {}
        safety = metrics.get("safety") or {}
        operational = metrics.get("operational") or {}

        row: dict[str, Any] = {
            "venue_id": request.get("venue_id"),
            "event_type": request.get("event_type"),
            "attendance": request.get("attendance"),
            "event_date": _coerce_ts(request.get("event_date"), request.get("event_time")),
            "service_rate_tier": params.get("service_rate_tier")
                or request.get("service_rate_tier")
                or "operational",
            "request_json": request,
            "response_json": response,
            "hes": _num(experience.get("hes")),
            "srs": _num(safety.get("srs")),
            "wait_mean": _num(
                (operational.get("wait_time") or {}).get(
                    "mean",
                    (response.get("simulation") or {}).get("wait_mean"),
                )
            ),
            "is_public": True,
        }

        try:
            r = c.post(
                "/runs",
                json=row,
                headers={"Prefer": "return=representation"},
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                return str(data[0].get("id"))
            if isinstance(data, dict):
                return str(data.get("id"))
        except Exception as e:
            logger.warning("save_run failed: %s", e)
        return None

    def get_run(self, run_id: str) -> Optional[dict]:
        c = self._client_or_none()
        if c is None:
            return None
        try:
            r = c.get(
                "/runs",
                params={"id": f"eq.{run_id}", "select": "*", "limit": "1"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if isinstance(data, list) and data else None
        except Exception as e:
            logger.warning("get_run(%s) failed: %s", run_id, e)
            return None

    # ── conversations ────────────────────────────────────────────────────────

    def load_conversation(self, conv_id: str) -> Optional[dict]:
        """
        Return {"id", "messages", "scenario"} or None.
        """
        c = self._client_or_none()
        if c is None:
            return None
        try:
            r = c.get(
                "/conversations",
                params={"id": f"eq.{conv_id}", "select": "*", "limit": "1"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if isinstance(data, list) and data else None
        except Exception as e:
            logger.warning("load_conversation(%s) failed: %s", conv_id, e)
            return None

    def save_conversation(
        self,
        conv_id: str,
        messages: list[dict],
        scenario: Optional[dict] = None,
    ) -> bool:
        """
        Idempotent upsert on conversations.id. Returns True on success.
        """
        c = self._client_or_none()
        if c is None:
            return False
        row = {
            "id": conv_id,
            "messages": messages,
            "scenario": scenario,
            "updated_at": "now()",
        }
        try:
            # PostgREST upsert via Prefer: resolution=merge-duplicates
            r = c.post(
                "/conversations",
                json=row,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning("save_conversation(%s) failed: %s", conv_id, e)
            return False

    def delete_conversation(self, conv_id: str) -> bool:
        c = self._client_or_none()
        if c is None:
            return False
        try:
            r = c.delete("/conversations", params={"id": f"eq.{conv_id}"})
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning("delete_conversation(%s) failed: %s", conv_id, e)
            return False

    # ── scenario_library ────────────────────────────────────────────────────

    def list_scenarios(self) -> list[dict]:
        c = self._client_or_none()
        if c is None:
            return []
        try:
            r = c.get(
                "/scenario_library",
                params={
                    "select": "*",
                    "order": "display_order.asc",
                },
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("list_scenarios failed: %s", e)
            return []

    def get_scenario(self, slug: str) -> Optional[dict]:
        c = self._client_or_none()
        if c is None:
            return None
        try:
            r = c.get(
                "/scenario_library",
                params={"slug": f"eq.{slug}", "select": "*", "limit": "1"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0] if isinstance(data, list) and data else None
        except Exception as e:
            logger.warning("get_scenario(%s) failed: %s", slug, e)
            return None

    def upsert_scenario(self, scenario: dict) -> bool:
        c = self._client_or_none()
        if c is None:
            return False
        try:
            r = c.post(
                "/scenario_library",
                json=scenario,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.warning("upsert_scenario(%s) failed: %s", scenario.get("slug"), e)
            return False


# ── helpers ─────────────────────────────────────────────────────────────────


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_ts(date_str: Optional[str], time_str: Optional[str]) -> Optional[str]:
    """Turn a {event_date, event_time} pair into an ISO timestamptz string."""
    if not date_str:
        return None
    if time_str:
        return f"{date_str}T{time_str}:00"
    return f"{date_str}T00:00:00"


# ── singleton accessor ──────────────────────────────────────────────────────

_persistence: Optional[Persistence] = None


def get_persistence() -> Persistence:
    """
    Process-wide singleton. Cheap to call; lazy HTTP client.
    """
    global _persistence
    if _persistence is None:
        _persistence = Persistence()
    return _persistence
