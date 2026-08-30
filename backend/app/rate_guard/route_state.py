"""Process-local, atomically replaced Rate Guard route selection."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class RateGuardRoute:
    base_url: str
    expected_instance_id: str
    source: str  # primary | fallback | blocked


_lock = RLock()
_active_route: RateGuardRoute | None = None


def get_active_route() -> RateGuardRoute | None:
    with _lock:
        return _active_route


def set_active_route(route: RateGuardRoute) -> None:
    global _active_route
    with _lock:
        _active_route = route


def clear_active_route() -> None:
    global _active_route
    with _lock:
        _active_route = None
