"""
tests/test_security.py — verify the public-deploy hardening layer.

Focused on observable contract:
  - body size cap returns 413
  - oversize chat message rejected by pydantic (422)
  - malformed UUIDs on /chat/{id} and /runs/{id} get 400
  - security headers are present on every response
  - rate limiting actually triggers (uses /chat which has the tightest cap)

The rate-limit test uses a unique X-Forwarded-For so it doesn't interact
with other tests that share an IP bucket within the same process.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import BoundedLRU, MAX_BODY_BYTES, is_uuid


def _wait_for_engine_ready(c: TestClient, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = c.get("/health")
        if r.status_code == 200 and r.json().get("venues_loaded", 0) >= 1:
            return
        time.sleep(0.05)
    pytest.fail("EngineBridge did not become ready in time")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        _wait_for_engine_ready(c)
        yield c


# ── Body size cap ───────────────────────────────────────────────────────────

def test_oversize_body_rejected_with_413(client):
    # 512 KB body — well over MAX_BODY_BYTES (256 KB)
    big_payload = "x" * (MAX_BODY_BYTES + 1024)
    r = client.post(
        "/chat",
        data=big_payload,  # raw bytes; Content-Length will exceed cap
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


# ── Pydantic input caps ─────────────────────────────────────────────────────

def test_chat_message_length_capped(client):
    # Pydantic should reject before any rate-limit accounting
    r = client.post("/chat", json={"message": "x" * 4001})
    assert r.status_code == 422


def test_chat_empty_message_rejected(client):
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 422


def test_chat_scenario_size_capped(client):
    # 17 KB of nested junk → over the 16 KB scenario cap
    blob = "x" * 17_000
    r = client.post(
        "/chat",
        json={"message": "hi", "scenario": {"junk": blob}},
    )
    assert r.status_code == 422


# ── UUID path-param guard ───────────────────────────────────────────────────

def test_invalid_run_id_rejected(client):
    r = client.get("/runs/not-a-uuid")
    assert r.status_code == 400


def test_invalid_conversation_id_on_chat_post_rejected(client):
    r = client.post(
        "/chat",
        json={"message": "hi", "conversation_id": "../etc/passwd"},
    )
    assert r.status_code == 400


def test_invalid_conversation_id_on_delete_rejected(client):
    r = client.delete("/chat/not-a-uuid")
    assert r.status_code == 400


def test_is_uuid_helper():
    assert is_uuid("00000000-0000-4000-8000-000000000000")
    assert is_uuid("D4E5F6A7-B8C9-4012-9345-67890ABCDEF0")
    assert not is_uuid("")
    assert not is_uuid("not-a-uuid")
    assert not is_uuid("00000000-0000-0000-0000-000000000000")  # version nibble 0


# ── Security headers ────────────────────────────────────────────────────────

def test_security_headers_present(client):
    r = client.get("/ready")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in r.headers


def test_security_headers_on_404(client):
    # Errors should still get security headers — confirms middleware is on
    # the outer wrap and not only on successful responses.
    r = client.get("/this-route-does-not-exist")
    assert r.status_code == 404
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


# ── Rate limiting ───────────────────────────────────────────────────────────

def test_chat_rate_limit_triggers_429():
    """
    Use a fresh app + unique X-Forwarded-For so this test's bucket is
    isolated from any earlier /chat calls in the suite.
    """
    with TestClient(app) as c:
        _wait_for_engine_ready(c)
        ip = "203.0.113.99"  # TEST-NET-3
        headers = {"X-Forwarded-For": ip}
        statuses = []
        # CHAT_LIMIT is "5/minute;20/hour" — 6th call should 429.
        for _ in range(8):
            r = c.post("/chat", json={"message": "ping"}, headers=headers)
            statuses.append(r.status_code)
        assert 429 in statuses, f"expected at least one 429, got {statuses}"


# ── BoundedLRU ─────────────────────────────────────────────────────────────

def test_bounded_lru_evicts_oldest():
    cache = BoundedLRU(maxsize=3)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    # Touch 'a' so it becomes most-recently-used
    _ = cache["a"]
    cache["d"] = 4  # should evict 'b' (now oldest)
    assert "a" in cache
    assert "b" not in cache
    assert "c" in cache
    assert "d" in cache
    assert len(cache) == 3


def test_bounded_lru_pop_removes_from_order():
    cache = BoundedLRU(maxsize=2)
    cache["a"] = 1
    cache["b"] = 2
    cache.pop("a")
    cache["c"] = 3
    # 'a' was popped, so adding 'c' shouldn't have evicted 'b'
    assert "b" in cache
    assert "c" in cache
    assert "a" not in cache
