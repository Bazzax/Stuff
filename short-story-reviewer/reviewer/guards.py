"""Rate limits and spending caps, kept in process memory.

On a single server this is exact. On serverless hosting each instance keeps
its own counters, so treat these as a first line of defence and also set a
monthly spend limit on the Anthropic API key itself.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:
    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


class SpendTracker:
    """Actual spend per UTC day, across all runs on this process."""

    def __init__(self) -> None:
        self._day = dt.datetime.now(dt.timezone.utc).date()
        self._spent = 0.0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        today = dt.datetime.now(dt.timezone.utc).date()
        if today != self._day:
            self._day, self._spent = today, 0.0

    def add(self, usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent += usd

    def spent_today(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    def can_afford(self, worst_case: float, daily_cap: float) -> bool:
        return self.spent_today() + worst_case <= daily_cap
