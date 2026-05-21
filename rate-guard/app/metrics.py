"""Per-upstream rolling request metrics + global-pause state.

These feed Rate Guard's /v1/metrics endpoint, which the admin "EDGAR rate
limit" panel reads — so the panel shows the *true* global budget instead of
one api process's in-memory view.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone


class UpstreamMetrics:
    def __init__(self, window_s: float = 60.0) -> None:
        self._window = window_s
        self._events: deque[tuple[float, int]] = deque(maxlen=5000)
        self._lock = threading.Lock()
        self._global_pause_until: float | None = None
        self._cache_hits = 0
        self._cache_misses = 0

    def record(self, status: int) -> None:
        with self._lock:
            self._events.append((time.time(), int(status)))

    def cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def cache_miss(self) -> None:
        with self._lock:
            self._cache_misses += 1

    def pause(self, seconds: float) -> None:
        with self._lock:
            self._global_pause_until = max(
                self._global_pause_until or 0.0, time.time() + seconds
            )

    @property
    def global_pause_until(self) -> float | None:
        with self._lock:
            return self._global_pause_until

    def snapshot(self) -> dict:
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            recent = [s for (t, s) in self._events if t >= cutoff]
            pause = self._global_pause_until
            hits, misses = self._cache_hits, self._cache_misses
        return {
            "window_seconds": self._window,
            "recent_request_count": len(recent),
            "recent_403_count": sum(1 for s in recent if s == 403),
            "recent_429_count": sum(1 for s in recent if s == 429),
            "cache_hits": hits,
            "cache_misses": misses,
            "global_pause_until": (
                datetime.fromtimestamp(pause, tz=timezone.utc).isoformat()
                if pause and pause > now
                else None
            ),
        }
