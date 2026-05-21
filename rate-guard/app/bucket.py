"""A thread-safe token bucket.

One bucket per upstream lives in the single Rate Guard process, so the
*combined* egress rate across every ValuePilot process is bounded by one
limiter — which is the whole reason Rate Guard exists.
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    """Refills at `rate_per_sec` tokens/sec, capped at `burst` tokens.

    `acquire()` blocks until a token is available and returns the seconds it
    waited. Tokens may go negative — that reserves future capacity, so
    concurrent callers are spaced ~`1/rate` apart without holding the lock
    across the sleep.
    """

    def __init__(self, rate_per_sec: float, burst: int) -> None:
        self._rate = max(float(rate_per_sec), 0.001)
        self._capacity = float(max(int(burst), 1))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._capacity,
                self._tokens + (now - self._updated) * self._rate,
            )
            self._updated = now
            wait = 0.0 if self._tokens >= 1.0 else (1.0 - self._tokens) / self._rate
            self._tokens -= 1.0
        if wait > 0:
            time.sleep(wait)
        return wait
