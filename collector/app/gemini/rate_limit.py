"""Process-level Gemini request rate limiter (rolling 1-minute window)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RequestRateLimiter:
    """
    Allow at most `max_per_minute` acquire() calls to start in any rolling 60s window.

    Sleeps only when the budget is exhausted — not between every giveaway.
    """

    def __init__(
        self,
        max_per_minute: int,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if max_per_minute < 1:
            raise ValueError("max_per_minute must be >= 1")
        self._max = int(max_per_minute)
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    @property
    def max_per_minute(self) -> int:
        return self._max

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                cutoff = now - 60.0
                self._timestamps = [t for t in self._timestamps if t > cutoff]
                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return
                wait = 60.0 - (now - self._timestamps[0]) + 0.01
            self._sleep(max(wait, 0.01))
