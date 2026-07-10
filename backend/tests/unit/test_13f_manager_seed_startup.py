"""M2 — the deploy-time caller of `seed_confirmed_managers`.

M1 made the seed *function* safe to run on every deploy. It deliberately left
three things to whoever calls it, and this module is that caller:

1. **The transaction boundary.** `seed_confirmed_managers` never commits; it
   takes a transaction-scoped advisory lock and expects the caller to end the
   transaction. If the caller forgets, the lock leaks for the life of the
   session and nothing is persisted.
2. **The fail-loud policy for a bad seed file.** A curated file that fails to
   load must stop the deploy, not start an API on a silently-empty universe.
3. **Surfacing a universe change.** The manager universe is a scoring input
   (Oracle's Lens needs `min_holders = 3`), so adding managers to a database
   that already holds 13F data invalidates previously-computed signals.
"""
import json
import logging
from pathlib import Path

import pytest

from app.models.institutions import InstitutionManager
from app.services.manager_seed_startup import (
    ManagerSeedError,
    run_startup_manager_seed,
)


class _KeepOpenSession:
    """Hand the fixture session to code that does `with session_factory() as db`.

    The real caller opens and closes its own session. Under the conftest
    savepoint fixture we must not let it close ours, but `commit()` and
    `rollback()` still operate on a SAVEPOINT, so the boundary under test
    behaves exactly as it does in production.
    """

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _factory(db_session):
    return lambda: _KeepOpenSession(db_session)


def _spy(db_session):
    """Record commit/rollback without changing their behaviour."""
    calls: list[str] = []
    real_commit, real_rollback = db_session.commit, db_session.rollback

    def commit():
        calls.append("commit")
        return real_commit()

    def rollback():
        calls.append("rollback")
        return real_rollback()

    db_session.commit = commit  # type: ignore[method-assign]
    db_session.rollback = rollback  # type: ignore[method-assign]
    return calls


def _clear_managers(db_session):
    db_session.query(InstitutionManager).delete()
    db_session.flush()


# --------------------------------------------------------------------------
# 1. The transaction boundary
# --------------------------------------------------------------------------


def test_startup_seed_commits_the_transaction(db_session):
    """The seed's advisory lock is transaction-scoped: no commit, no release."""
    _clear_managers(db_session)
    calls = _spy(db_session)

    report = run_startup_manager_seed(_factory(db_session))

    assert calls == ["commit"]
    assert report["created"] == report["seed_entries"] > 0
    assert db_session.query(InstitutionManager).count() == report["seed_entries"]


def test_startup_seed_rolls_back_when_the_seed_raises(monkeypatch, db_session):
    """A half-written universe is worse than none. Rollback, then re-raise."""
    _clear_managers(db_session)
    calls = _spy(db_session)

    def _explode(db):
        db.add(InstitutionManager(cik="0000000001", legal_name="Half Written"))
        db.flush()
        raise ValueError("style_primary 'vlaue_deep' is not a known style")

    monkeypatch.setattr(
        "app.services.manager_seed_startup.seed_confirmed_managers", _explode
    )

    with pytest.raises(ManagerSeedError, match="vlaue_deep"):
        run_startup_manager_seed(_factory(db_session))

    assert calls == ["rollback"]
    assert db_session.query(InstitutionManager).count() == 0


def test_startup_seed_is_idempotent_across_restarts(db_session):
    """Every deploy runs this. The second run must create nothing."""
    _clear_managers(db_session)
    first = run_startup_manager_seed(_factory(db_session))
    second = run_startup_manager_seed(_factory(db_session))

    assert first["created"] == first["seed_entries"]
    assert second["created"] == 0
    assert second["updated"] == second["seed_entries"]
    assert db_session.query(InstitutionManager).count() == first["seed_entries"]


# --------------------------------------------------------------------------
# 2. Fail loud on a bad or absent seed file
# --------------------------------------------------------------------------


def test_a_bad_style_primary_blocks_startup(monkeypatch, db_session):
    """`derive_legacy_manager_type` raises on a typo. That must reach uvicorn."""
    _clear_managers(db_session)

    def _explode(db):
        raise ValueError("style_primary 'quality_compunder' is not a known style")

    monkeypatch.setattr(
        "app.services.manager_seed_startup.seed_confirmed_managers", _explode
    )

    with pytest.raises(ManagerSeedError):
        run_startup_manager_seed(_factory(db_session))


def test_a_missing_seed_file_blocks_startup(monkeypatch, db_session):
    """`seed_confirmed_managers` returns an EMPTY report when the file is absent.

    It only logs a warning. Left alone, a deploy whose image lost the seed file
    would start an API with an empty manager universe and ingest nothing — the
    silent failure M1 exists to prevent. The startup caller must refuse.
    """
    _clear_managers(db_session)
    empty = {
        "seed_entries": 0, "created": 0, "updated": 0,
        "skipped_human_decided": 0, "skipped_needs_review": 0,
        "awaiting_confirmation": 0, "ambiguous_name_match": 0,
        "skipped_human_decided_ciks": [], "skipped_needs_review_ciks": [],
        "awaiting_confirmation_ciks": [], "ambiguous_name_match_ciks": [],
    }
    monkeypatch.setattr(
        "app.services.manager_seed_startup.seed_confirmed_managers",
        lambda db: empty,
    )

    with pytest.raises(ManagerSeedError, match="no seed entries"):
        run_startup_manager_seed(_factory(db_session))


def test_the_curated_seed_file_is_valid(db_session):
    """The guard that makes fail-loud safe: a bad file can never reach prod.

    Fail-loud at boot only stops a crash loop if CI rejects the bad file first.
    """
    from app.services.oracles_lens.manager_style import derive_legacy_manager_type

    path = (
        Path(__file__).resolve().parents[2]
        / "app" / "services" / "seed_data" / "confirmed_managers.json"
    )
    entries = json.loads(path.read_text())

    assert len(entries) > 0
    ciks = [e.get("cik") for e in entries]
    assert all(ciks), "every curated entry needs a CIK — one without is skipped silently"
    assert len(set(ciks)) == len(ciks), "duplicate CIK would collide on the unique index"
    for entry in entries:
        # Raises ValueError on a typo — that is the loud failure we rely on.
        derive_legacy_manager_type(entry.get("style_primary", "unknown"))


# --------------------------------------------------------------------------
# 3. A universe change is a scoring event, not a log line
# --------------------------------------------------------------------------


def test_creating_managers_on_a_database_with_holdings_warns_loudly(
    monkeypatch, db_session, caplog
):
    """Oracle's Lens `min_holders = 3` means the universe IS a scoring input.

    Signals computed under the old universe are now stale. M2 refuses to
    recompute silently; it names the problem.
    """
    _clear_managers(db_session)
    monkeypatch.setattr(
        "app.services.manager_seed_startup._database_has_13f_holdings",
        lambda db: True,
    )

    with caplog.at_level(logging.WARNING):
        report = run_startup_manager_seed(_factory(db_session))

    assert report["created"] > 0
    assert report["universe_changed"] is True
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "recompute" in joined.lower()


def test_no_universe_change_when_nothing_was_created(db_session, caplog):
    """The steady state — a re-deploy against an already-seeded prod."""
    _clear_managers(db_session)
    run_startup_manager_seed(_factory(db_session))

    with caplog.at_level(logging.WARNING):
        report = run_startup_manager_seed(_factory(db_session))

    assert report["created"] == 0
    assert report["universe_changed"] is False
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "recompute" not in joined.lower()


def test_a_first_deploy_onto_an_empty_database_is_not_a_universe_change(db_session):
    """Day 0: 82 managers created, but there is no prior scoring to invalidate."""
    _clear_managers(db_session)
    report = run_startup_manager_seed(_factory(db_session))

    assert report["created"] == report["seed_entries"]
    assert report["universe_changed"] is False


def test_an_ambiguous_name_match_is_reported_at_error_level(
    monkeypatch, db_session, caplog
):
    """A refused create means a curated manager is MISSING from the universe."""
    _clear_managers(db_session)
    report = {
        "seed_entries": 82, "created": 81, "updated": 0,
        "skipped_human_decided": 0, "skipped_needs_review": 0,
        "awaiting_confirmation": 0, "ambiguous_name_match": 1,
        "skipped_human_decided_ciks": [], "skipped_needs_review_ciks": [],
        "awaiting_confirmation_ciks": [], "ambiguous_name_match_ciks": ["0000936753"],
    }
    monkeypatch.setattr(
        "app.services.manager_seed_startup.seed_confirmed_managers",
        lambda db: report,
    )

    with caplog.at_level(logging.ERROR):
        run_startup_manager_seed(_factory(db_session))

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a refused create must not be logged at INFO"
    assert "0000936753" in "\n".join(r.getMessage() for r in errors)


def test_awaiting_confirmation_names_the_managers_that_will_not_be_ingested(
    monkeypatch, db_session, caplog
):
    """`ingest_quarter_index` selects on match_status='confirmed'. These are invisible."""
    _clear_managers(db_session)
    report = {
        "seed_entries": 82, "created": 0, "updated": 82,
        "skipped_human_decided": 0, "skipped_needs_review": 0,
        "awaiting_confirmation": 2, "ambiguous_name_match": 0,
        "skipped_human_decided_ciks": [], "skipped_needs_review_ciks": [],
        "awaiting_confirmation_ciks": ["0001067983", "0000936753"],
        "ambiguous_name_match_ciks": [],
    }
    monkeypatch.setattr(
        "app.services.manager_seed_startup.seed_confirmed_managers",
        lambda db: report,
    )

    with caplog.at_level(logging.WARNING):
        run_startup_manager_seed(_factory(db_session))

    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "0001067983" in joined
