"""In-process sliding-window rate limiter.

Limitation (documented in docs/SECURITY.md): state is per process, so with N
worker processes the effective limit is N times higher. Swap the store for a
shared one if you deploy multiple workers.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from flask import current_app, request

from app.config.settings import parse_rate_limit
from app.utils.errors import ApiError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> int:
        """Record a hit; return 0 if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return max(1, int(window_seconds - (now - hits[0])) + 1)
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def enforce_rate_limit(scope: str, *extra_keys: str) -> None:
    """Raise 429 when the client IP (or any extra key, e.g. an email) exceeds the limit."""
    settings = current_app.extensions["settings"]
    limit, window = parse_rate_limit(settings.auth.login_rate_limit)
    limiter: RateLimiter = current_app.extensions["rate_limiter"]
    for key in (request.remote_addr or "unknown", *extra_keys):
        retry_after = limiter.hit(f"{scope}:{key}", limit, window)
        if retry_after:
            raise ApiError(
                "Too many attempts. Please wait and try again.",
                status_code=429,
                code="rate_limited",
                details={"retry_after_seconds": retry_after},
            )
