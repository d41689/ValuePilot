from __future__ import annotations

import pytest

from app.rate_guard.client import RateGuardFetchError, RateGuardIdentityUnavailable
from app.rate_guard import routing as main
from app.rate_guard.route_state import RateGuardRoute, clear_active_route, get_active_route


@pytest.fixture(autouse=True)
def _clear_rate_guard_route(monkeypatch):
    monkeypatch.setattr(main.settings, "RATE_GUARD_ALLOW_LOCAL_FALLBACK", False)
    monkeypatch.setattr(main.settings, "RATE_GUARD_FALLBACK_URL", None)
    clear_active_route()
    yield
    clear_active_route()


def test_replay_mode_does_not_contact_rate_guard(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "EDGAR_FETCH_MODE", "replay")
    monkeypatch.setattr(
        main,
        "RateGuardClient",
        lambda: (_ for _ in ()).throw(AssertionError("must not construct client")),
        raising=False,
    )

    assert main.verify_live_rate_guard() is None


def test_live_mode_fails_when_expected_identity_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(main.settings, "RATE_GUARD_URL", "http://rate-guard:9000")
    monkeypatch.setattr(main.settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", None)

    with pytest.raises(RuntimeError, match="EXPECTED_INSTANCE_ID"):
        main.verify_live_rate_guard()


def test_live_mode_verifies_rate_guard_before_startup(monkeypatch) -> None:
    expected = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(main.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(main.settings, "RATE_GUARD_URL", "http://rate-guard:9000")
    monkeypatch.setattr(main.settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", expected)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify_identity(self):
            return expected

    monkeypatch.setattr(main, "RateGuardClient", FakeClient, raising=False)

    assert main.verify_live_rate_guard() == expected


def test_live_mode_surfaces_unreachable_rate_guard(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(main.settings, "RATE_GUARD_URL", "http://rate-guard:9000")
    monkeypatch.setattr(
        main.settings,
        "RATE_GUARD_EXPECTED_INSTANCE_ID",
        "11111111-1111-4111-8111-111111111111",
    )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify_identity(self):
            raise RateGuardFetchError("Rate Guard unreachable")

    monkeypatch.setattr(main, "RateGuardClient", FakeClient, raising=False)

    with pytest.raises(RuntimeError, match="unreachable"):
        main.verify_live_rate_guard()


def _enable_adaptive_development(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(main.settings, "RATE_GUARD_URL", "https://primary.example")
    monkeypatch.setattr(main.settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", None)
    monkeypatch.setattr(main.settings, "RATE_GUARD_ALLOW_LOCAL_FALLBACK", True)
    monkeypatch.setattr(
        main.settings, "RATE_GUARD_FALLBACK_URL", "http://rate-guard-local:9000"
    )


def test_adaptive_development_prefers_reachable_primary(monkeypatch) -> None:
    _enable_adaptive_development(monkeypatch)
    calls: list[tuple[str, str | None, str]] = []

    def probe(url, expected, source):
        calls.append((url, expected, source))
        return RateGuardRoute(url, "11111111-1111-4111-8111-111111111111", source)

    monkeypatch.setattr(main, "_probe_rate_guard_route", probe)

    assert main.verify_live_rate_guard() == "11111111-1111-4111-8111-111111111111"
    assert get_active_route().source == "primary"
    assert calls == [("https://primary.example", None, "primary")]


def test_adaptive_development_falls_back_only_when_primary_is_unavailable(
    monkeypatch,
) -> None:
    _enable_adaptive_development(monkeypatch)
    calls: list[str] = []

    def probe(url, expected, source):
        calls.append(source)
        if source == "primary":
            raise RateGuardIdentityUnavailable("origin offline")
        return RateGuardRoute(url, "22222222-2222-4222-8222-222222222222", source)

    monkeypatch.setattr(main, "_probe_rate_guard_route", probe)

    assert main.verify_live_rate_guard() == "22222222-2222-4222-8222-222222222222"
    assert get_active_route().source == "fallback"
    assert calls == ["primary", "fallback"]


def test_adaptive_development_does_not_mask_primary_identity_failure(
    monkeypatch,
) -> None:
    _enable_adaptive_development(monkeypatch)
    calls: list[str] = []

    def probe(_url, _expected, source):
        calls.append(source)
        raise RateGuardFetchError("unexpected instance")

    monkeypatch.setattr(main, "_probe_rate_guard_route", probe)

    with pytest.raises(RuntimeError, match="unexpected instance"):
        main.verify_live_rate_guard()
    assert calls == ["primary"]


def test_adaptive_development_rejects_non_private_fallback_url(monkeypatch) -> None:
    _enable_adaptive_development(monkeypatch)
    monkeypatch.setattr(
        main.settings, "RATE_GUARD_FALLBACK_URL", "https://attacker.example"
    )
    monkeypatch.setattr(
        main,
        "_probe_rate_guard_route",
        lambda *_args: (_ for _ in ()).throw(
            RateGuardIdentityUnavailable("origin offline")
        ),
    )

    with pytest.raises(RuntimeError, match="private development endpoint"):
        main.verify_live_rate_guard()


def test_reconcile_switches_from_fallback_back_to_primary(monkeypatch) -> None:
    _enable_adaptive_development(monkeypatch)
    main.set_active_route(
        RateGuardRoute(
            "http://rate-guard-local:9000",
            "22222222-2222-4222-8222-222222222222",
            "fallback",
        )
    )
    monkeypatch.setattr(
        main,
        "_probe_rate_guard_route",
        lambda url, expected, source: RateGuardRoute(
            url, "11111111-1111-4111-8111-111111111111", source
        ),
    )

    route = main.reconcile_rate_guard_route()

    assert route.source == "primary"
    assert get_active_route().source == "primary"


def test_reconcile_switches_to_fallback_after_primary_becomes_unavailable(
    monkeypatch,
) -> None:
    _enable_adaptive_development(monkeypatch)

    def probe(url, expected, source):
        if source == "primary":
            raise RateGuardIdentityUnavailable("origin offline")
        return RateGuardRoute(url, "22222222-2222-4222-8222-222222222222", source)

    monkeypatch.setattr(main, "_probe_rate_guard_route", probe)

    route = main.reconcile_rate_guard_route()

    assert route.source == "fallback"
    assert get_active_route().source == "fallback"


def test_monitor_blocks_existing_primary_route_after_identity_failure(
    monkeypatch,
) -> None:
    _enable_adaptive_development(monkeypatch)
    main.set_active_route(
        RateGuardRoute(
            "https://primary.example",
            "11111111-1111-4111-8111-111111111111",
            "primary",
        )
    )
    monkeypatch.setattr(
        main,
        "_probe_rate_guard_route",
        lambda *_args: (_ for _ in ()).throw(
            RateGuardFetchError("unexpected instance")
        ),
    )

    with pytest.raises(RateGuardFetchError, match="unexpected instance"):
        main.reconcile_monitored_rate_guard_route()

    assert get_active_route().source == "blocked"
    assert get_active_route().base_url == ""


def test_monitor_keeps_verified_fallback_after_primary_identity_failure(
    monkeypatch,
) -> None:
    _enable_adaptive_development(monkeypatch)
    main.set_active_route(
        RateGuardRoute(
            "http://rate-guard-local:9000",
            "22222222-2222-4222-8222-222222222222",
            "fallback",
        )
    )
    monkeypatch.setattr(
        main,
        "_probe_rate_guard_route",
        lambda *_args: (_ for _ in ()).throw(
            RateGuardFetchError("central authentication failed")
        ),
    )

    with pytest.raises(RateGuardFetchError, match="authentication"):
        main.reconcile_monitored_rate_guard_route()

    assert get_active_route().source == "fallback"


def test_production_style_configuration_never_uses_fallback(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "EDGAR_FETCH_MODE", "live")
    monkeypatch.setattr(main.settings, "RATE_GUARD_URL", "http://rate-guard:9000")
    monkeypatch.setattr(
        main.settings,
        "RATE_GUARD_EXPECTED_INSTANCE_ID",
        "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(main.settings, "RATE_GUARD_ALLOW_LOCAL_FALLBACK", False)
    monkeypatch.setattr(main.settings, "RATE_GUARD_FALLBACK_URL", None)
    calls: list[str] = []

    def probe(_url, _expected, source):
        calls.append(source)
        raise RateGuardIdentityUnavailable("offline")

    monkeypatch.setattr(main, "_probe_rate_guard_route", probe)

    with pytest.raises(RuntimeError, match="offline"):
        main.verify_live_rate_guard()
    assert calls == ["primary"]
