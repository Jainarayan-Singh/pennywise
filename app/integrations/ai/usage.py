from __future__ import annotations

import threading
import time
from collections import Counter, deque
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.integrations.ai.base import AIRateLimited

# Gemini's daily quota resets at midnight Pacific time.
_QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")


class UsageGuard:
    """Counts outgoing requests and refuses new ones before the provider's free-tier limits are hit."""

    def __init__(self, requests_per_minute: int, daily_budget: int = 0) -> None:
        self._rpm = requests_per_minute
        self._daily_budget = daily_budget
        self._recent: deque[float] = deque()
        self._today: date | None = None
        self._by_model: Counter[str] = Counter()
        self._lock = threading.Lock()

    def _roll_day(self) -> None:
        today = datetime.now(_QUOTA_TIMEZONE).date()
        if today != self._today:
            self._today = today
            self._by_model.clear()

    def reserve(self, model: str) -> None:
        """Record one outgoing request, or raise AIRateLimited without making it."""
        now = time.monotonic()
        with self._lock:
            self._roll_day()
            while self._recent and now - self._recent[0] >= 60:
                self._recent.popleft()
            if len(self._recent) >= self._rpm:
                raise AIRateLimited("per-minute guard")
            if self._daily_budget and sum(self._by_model.values()) >= self._daily_budget:
                raise AIRateLimited("daily budget guard")
            self._recent.append(now)
            self._by_model[model] += 1

    def snapshot(self) -> dict:
        with self._lock:
            self._roll_day()
            return {
                "requests_today": sum(self._by_model.values()),
                "by_model": dict(self._by_model),
                "daily_budget": self._daily_budget or None,
                "requests_per_minute_limit": self._rpm,
            }
