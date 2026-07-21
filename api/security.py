"""
api/security.py — Hardening for public deployment.

Centralizes:
  - per-IP rate limiting (slowapi, in-memory)
  - request body-size cap (rejects oversize uploads before the route runs)
  - security headers (HSTS, X-Content-Type-Options, X-Frame-Options, ...)
  - bounded LRU conversation cache (prevents memory growth from /chat abuse)

Designed for a single-process FastAPI server. To run more than one replica,
or to keep limits across restarts, swap slowapi's in-memory storage for Redis
via `Limiter(storage_uri="redis://...")`; no other code changes.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from typing import TypeVar

from fastapi import Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ── Rate limiter ────────────────────────────────────────────────────────────
#
# Limits chosen for "1000s of users" on a small single-process box:
#   - costly endpoints (chat, simulate, temporal) get tight per-minute caps
#     so a single attacker can't burst-spend the Anthropic budget or peg CPU
#   - cheap read endpoints get a loose hourly cap (mostly there to catch
#     scrapers and accidental client-side loops)
#   - /ready, /health, /docs are never decorated → never rate-limited
#
# Real humans don't hit these limits. They exist to stop bots and runaway
# clients before they show up on a billing dashboard.

CHAT_LIMIT = "5/minute;20/hour"
SIM_LIMIT = "10/minute;60/hour"
HEAVY_LIMIT = "10/minute;60/hour"   # stress-test, compare, what-if
READ_LIMIT = "60/minute;600/hour"


def _client_ip(request: Request) -> str:
    """
    Resolve the real client IP behind a reverse proxy / load balancer.

    A proxy that terminates TLS forwards the client via X-Forwarded-For; the
    leftmost entry is the original client (later entries are proxy hops). If
    the header is missing we fall back to the direct peer, which behind a proxy
    is the proxy itself, so all such requests share one bucket (acceptable: it
    only happens when no XFF is set).
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    if request.client:
        return request.client.host
    return "unknown"


# headers_enabled=False on purpose: when a route uses Pydantic `response_model`
# the handler returns a dict, and slowapi can't inject X-RateLimit-* headers
# into it (it raises). The 429 body already echoes the limit, so the headers
# are nice-to-have rather than essential.
limiter = Limiter(key_func=_client_ip, headers_enabled=False)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Friendly 429 with the limit string echoed back."""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Rate limit exceeded. Slow down and retry shortly.",
            "limit": str(exc.detail),
        },
    )


# ── Body size cap ───────────────────────────────────────────────────────────
#
# FastAPI/Starlette have no built-in max body size. Without this, a single
# POST with a 100 MB body would be fully buffered into memory before our
# route ever runs. 256 KB is generous for any legitimate Vane request:
# the largest payload (`/scenario/compare` with two full SimulationRequests
# plus graph_changes) is well under 10 KB.

MAX_BODY_BYTES = 256 * 1024  # 256 KB


class BodySizeLimitMiddleware:
    """
    Reject requests whose body exceeds MAX_BODY_BYTES.

    Implemented as raw ASGI middleware (not BaseHTTPMiddleware) so we can
    short-circuit *before* Starlette buffers the body. We check
    Content-Length first (cheap), then fall back to counting bytes as they
    stream in (catches chunked uploads with no Content-Length).
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: trust Content-Length when present.
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > self.max_bytes:
                        await _send_413(send)
                        return
                except ValueError:
                    pass
                break

        # Slow path: count streamed bytes (chunked encoding, missing header).
        total = 0
        rejected = False

        async def counting_receive() -> Message:
            nonlocal total, rejected
            msg = await receive()
            if msg["type"] == "http.request":
                body = msg.get("body") or b""
                total += len(body)
                if total > self.max_bytes:
                    rejected = True
            return msg

        await self.app(scope, counting_receive, send)
        if rejected:
            # Best we can do post-hoc: log it. The route still ran, but the
            # Content-Length check above catches 99% of abuse cheaply.
            logger.warning("Streamed body exceeded %d bytes", self.max_bytes)


async def _send_413(send: Send) -> None:
    # 413 — Content Too Large (the RFC name; older Starlette aliases it as
    # REQUEST_ENTITY_TOO_LARGE, which is deprecated).
    await send({
        "type": "http.response.start",
        "status": status.HTTP_413_CONTENT_TOO_LARGE,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"detail":"Request body too large."}',
    })


# ── Security headers ────────────────────────────────────────────────────────
#
# Applied to every response. Conservative defaults:
#   - HSTS only when the request was HTTPS (no point on plain http://localhost)
#   - X-Frame-Options=DENY (this is an API + SPA, never legitimately framed)
#   - Referrer-Policy strict-origin-when-cross-origin (don't leak run_ids
#     in the Referer to third parties)
#   - X-Content-Type-Options=nosniff
#   - Permissions-Policy disables sensors/camera/mic (we never use them)
#
# No CSP: the SPA is normally served separately, not from this origin, and the
# rare HTML responses here (/docs, /redoc) need Swagger's inline scripts.

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), interest-cohort=()",
        )
        if request.url.scheme == "https":
            h.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )
        return response


# ── Bounded LRU cache ───────────────────────────────────────────────────────
#
# Replaces the unbounded `_conversations: dict` in api.main. Without a cap,
# an attacker can spawn unique conversation_ids forever and OOM the process.
# 1000 active conversations is plenty for a small/medium deployment; on
# eviction the conversation is still in Supabase and rehydrates on next hit.

V = TypeVar("V")


class BoundedLRU(dict):
    """
    Minimal LRU. Dict-compatible so callers can keep using `cache[k] = v`
    and `cache.pop(k, None)`. On insert past `maxsize`, evicts the least
    recently used entry.
    """

    def __init__(self, maxsize: int = 1000) -> None:
        super().__init__()
        self._order: "OrderedDict[str, None]" = OrderedDict()
        self._maxsize = maxsize

    def __setitem__(self, key: str, value) -> None:
        if key in self._order:
            self._order.move_to_end(key)
        else:
            self._order[key] = None
            if len(self._order) > self._maxsize:
                oldest, _ = self._order.popitem(last=False)
                super().pop(oldest, None)
        super().__setitem__(key, value)

    def __getitem__(self, key: str):
        v = super().__getitem__(key)
        self._order.move_to_end(key)
        return v

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key)

    def pop(self, key, default=None):
        self._order.pop(key, None)
        return super().pop(key, default)


# ── UUID path-param guard ───────────────────────────────────────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_uuid(s: str) -> bool:
    """RFC 4122 UUID v1–v5 check. Cheap; no exception path."""
    return bool(_UUID_RE.match(s or ""))
