from __future__ import annotations

import pytest

from app import main
from app.rate_guard.client import RateGuardFetchError


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
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify_identity(self):
            raise RateGuardFetchError("Rate Guard unreachable")

    monkeypatch.setattr(main, "RateGuardClient", FakeClient, raising=False)

    with pytest.raises(RuntimeError, match="unreachable"):
        main.verify_live_rate_guard()
