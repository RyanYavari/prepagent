"""In-process per-IP rate limiting (specs/deployment.md).

Valid only because the API runs as a single worker: the counters live in process
memory, so with N workers every limit would be N times looser. The client address is
whatever uvicorn resolves (`--proxy-headers` behind Caddy); this module never reads
`X-Forwarded-For` itself, so a client cannot choose its own bucket.
"""

import ipaddress
import math
import os
import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

WINDOW_SECONDS = 60.0
MAX_TRACKED_KEYS = 10_000
_UNLIMITED_PATHS = {"/health"}


def _env_limit(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if raw.isdigit() and 1 <= int(raw) <= 100_000:
        return int(raw)
    return default


def auth_limit_per_minute() -> int:
    return _env_limit("RATE_LIMIT_AUTH_PER_MINUTE", 20)


def global_limit_per_minute() -> int:
    # The briefing viewer polls every 3 s (20 requests a minute) on its own.
    return _env_limit("RATE_LIMIT_GLOBAL_PER_MINUTE", 120)


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window: float = WINDOW_SECONDS,
        max_keys: int = MAX_TRACKED_KEYS,
    ):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int | None = None) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds); a blocked hit is not recorded."""
        cap = self.limit if limit is None else limit
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                self._make_room(now)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= cap:
                return False, max(1, math.ceil(hits[0] + self.window - now))
            hits.append(now)
            return True, 0

    def _make_room(self, now: float) -> None:
        if len(self._hits) < self.max_keys:
            return
        for key in [
            k for k, h in self._hits.items() if not h or h[-1] <= now - self.window
        ]:
            del self._hits[key]
        while len(self._hits) >= self.max_keys:  # still full: drop the oldest key
            del self._hits[next(iter(self._hits))]

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_auth_limiter = SlidingWindowLimiter(limit=20)
_global_limiter = SlidingWindowLimiter(limit=120)


def reset() -> None:
    """Forget all counters (tests)."""
    _auth_limiter.reset()
    _global_limiter.reset()


def bucket_key(host: str | None) -> str:
    """Rate-limit bucket for a peer address. IPv6 clients are grouped by /64: one
    customer typically controls a whole /64, so keying on the full address would hand
    them 2^64 separate buckets and make the limit meaningless."""
    if not host:
        return "unknown"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def _client_key(request: Request) -> str:
    return bucket_key(request.client.host if request.client else None)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _UNLIMITED_PATHS:
            return await call_next(request)
        key = _client_key(request)
        checks = []
        if path.startswith("/auth/"):
            checks.append(_auth_limiter.check(key, auth_limit_per_minute()))
        checks.append(_global_limiter.check(key, global_limit_per_minute()))
        for allowed, retry_after in checks:
            if not allowed:
                return JSONResponse(
                    {"detail": "Too many requests"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)
