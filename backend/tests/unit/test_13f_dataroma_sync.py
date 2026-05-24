"""Dataroma sync decoupling — bootstrap is offline, sync is on-demand.

Task doc: ``docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md``

These tests pin the four behaviors that matter:

1. The new ``sync_dataroma_managers`` function classifies the diff
   correctly and **does not** write to ``institution_managers``.
2. ``add_dataroma_candidates`` is the only path that writes; it creates
   ``candidate`` rows (no CIK, V2 fields default to unknown) and is
   idempotent.
3. The legacy ``bootstrap_whitelist`` job_type now routes to
   ``seed_confirmed_managers`` — the offline JSON path — and never
   touches ``DataromaClient``.
4. The new ``dataroma_sync`` job_type runs the network sync and stores
   the diff summary on the JobRun row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import count

import pytest

from app.dataroma.parsers.managers import DataromaManager
from app.models.institutions import InstitutionManager
from app.services.edgar_ingestion import (
    DataromaSyncDiff,
    DataromaSyncEntry,
    add_dataroma_candidates,
    seed_confirmed_managers,
    sync_dataroma_managers,
)


_CIK_SEQ = count(7780000000)


def _make_existing(db_session, *, dataroma_code: str | None, cik: str | None = None,
                   legal_name: str = "Existing") -> InstitutionManager:
    cik_val = cik or str(next(_CIK_SEQ))
    m = InstitutionManager(
        canonical_name=legal_name,
        legal_name=legal_name,
        edgar_legal_name=legal_name,
        cik=cik_val,
        dataroma_code=dataroma_code,
        match_status="confirmed",
        status="active",
        is_superinvestor=True,
        style_primary="value_concentrated",
        capital_structure="locked_lp",
    )
    db_session.add(m)
    db_session.flush()
    return m


# ---------------------------------------------------------------------------
# sync_dataroma_managers — diff-only, no writes
# ---------------------------------------------------------------------------


def test_sync_dataroma_classifies_new_known_dropped(db_session, monkeypatch):
    """Given a Dataroma payload of 3 entries, where one is known to us by
    dataroma_code, one is brand new, and we additionally have one manager
    with a dataroma_code that Dataroma no longer returns — the diff must
    bucket them as known/new/dropped respectively.

    Assertions use *subset* semantics rather than equality because the
    dev DB may already have other seeded managers committed; what we
    care about is that *our* test fixtures land in the right bucket.
    """
    _make_existing(db_session, dataroma_code="UTKNOWN-A", legal_name="Known A")
    _make_existing(db_session, dataroma_code="UTGONE-Z", legal_name="Used to be in Dataroma")
    db_session.flush()

    fake_payload = [
        DataromaManager(name="Known A", dataroma_code="UTKNOWN-A"),
        DataromaManager(name="Brand New", dataroma_code="UTNEW-1"),
        DataromaManager(name="Also New", dataroma_code="UTNEW-2"),
    ]

    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        lambda: fake_payload,
    )

    diff = sync_dataroma_managers(db_session)

    assert isinstance(diff, DataromaSyncDiff)
    known_codes = {e.dataroma_code for e in diff.known}
    new_codes = {e.dataroma_code for e in diff.new}
    dropped_codes = {e.dataroma_code for e in diff.dropped}

    # Subset checks: our fixtures must each show up in exactly the
    # expected bucket and nowhere else.
    assert "UTKNOWN-A" in known_codes
    assert "UTKNOWN-A" not in new_codes
    assert "UTKNOWN-A" not in dropped_codes

    assert {"UTNEW-1", "UTNEW-2"} <= new_codes
    assert {"UTNEW-1", "UTNEW-2"}.isdisjoint(known_codes | dropped_codes)

    assert "UTGONE-Z" in dropped_codes
    assert "UTGONE-Z" not in known_codes | new_codes


def test_sync_dataroma_does_not_write_to_institution_managers(db_session, monkeypatch):
    before = db_session.query(InstitutionManager).count()

    fake_payload = [
        DataromaManager(name="Not Yet Tracked", dataroma_code="UNTRACKED-1"),
    ]
    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        lambda: fake_payload,
    )

    sync_dataroma_managers(db_session)

    after = db_session.query(InstitutionManager).count()
    assert after == before, (
        "sync_dataroma_managers must not insert into institution_managers; "
        f"row count changed {before} → {after}"
    )


def test_sync_dataroma_dropped_excludes_rows_without_dataroma_code(db_session, monkeypatch):
    """Managers without a dataroma_code (most V2-seeded entries) cannot
    be ``dropped`` because Dataroma never knew about them in the first
    place. They should not show up in the dropped list even if Dataroma
    returns an empty payload.

    Assertion is "*my* test row, identified by id, does not appear in
    dropped" — pre-existing committed managers with dataroma_code WILL
    show up in dropped against an empty fake payload, which is correct
    behavior and not what this test is about.
    """
    no_code = _make_existing(
        db_session, dataroma_code=None, legal_name="V2 seeded, no Dataroma code"
    )
    db_session.flush()

    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        lambda: [],
    )

    diff = sync_dataroma_managers(db_session)
    dropped_ids = {e.institution_manager_id for e in diff.dropped}
    assert no_code.id not in dropped_ids, (
        "manager without a dataroma_code must not appear in dropped"
    )


def test_sync_dataroma_returns_fetched_at_timestamp(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        lambda: [DataromaManager(name="X", dataroma_code="X")],
    )
    before = datetime.now(timezone.utc)
    diff = sync_dataroma_managers(db_session)
    after = datetime.now(timezone.utc)
    assert before <= diff.fetched_at <= after


# ---------------------------------------------------------------------------
# add_dataroma_candidates — the only write path
# ---------------------------------------------------------------------------


def test_add_dataroma_candidates_creates_candidate_rows(db_session):
    items = [
        DataromaSyncEntry(dataroma_code="ADD-1", name="Add One"),
        DataromaSyncEntry(dataroma_code="ADD-2", name="Add Two"),
    ]
    result = add_dataroma_candidates(db_session, items)
    db_session.flush()

    assert result["added"] == 2
    assert result["skipped"] == 0

    for code in ("ADD-1", "ADD-2"):
        m = db_session.query(InstitutionManager).filter_by(dataroma_code=code).one()
        assert m.cik is None, f"{code}: candidate should not have a CIK yet"
        assert m.match_status == "candidate"
        assert m.is_superinvestor is True
        # V2 fields default to unknown until admin classifies.
        assert m.style_primary == "unknown"
        assert m.capital_structure == "unknown"
        # Provenance: review_note records the Dataroma origin.
        assert m.review_note and "Dataroma" in m.review_note


def test_add_dataroma_candidates_is_idempotent(db_session):
    items = [DataromaSyncEntry(dataroma_code="IDEMP-1", name="Idemp One")]
    add_dataroma_candidates(db_session, items)
    db_session.flush()

    result = add_dataroma_candidates(db_session, items)
    db_session.flush()
    assert result["added"] == 0
    assert result["skipped"] == 1

    assert (
        db_session.query(InstitutionManager).filter_by(dataroma_code="IDEMP-1").count()
        == 1
    )


def test_add_dataroma_candidates_skips_when_dataroma_code_already_confirmed(db_session):
    _make_existing(db_session, dataroma_code="CONFIRMED-X", legal_name="Already Confirmed")

    result = add_dataroma_candidates(
        db_session,
        [DataromaSyncEntry(dataroma_code="CONFIRMED-X", name="Already Confirmed")],
    )

    assert result["added"] == 0
    assert result["skipped"] == 1


# ---------------------------------------------------------------------------
# Admin job dispatch — bootstrap_whitelist is now offline
# ---------------------------------------------------------------------------


def test_bootstrap_whitelist_job_type_uses_offline_seed_path(db_session, monkeypatch):
    """The deployed FE button job_type=bootstrap_whitelist still works, but
    its handler now calls ``seed_confirmed_managers`` (offline JSON) and
    must not touch ``DataromaClient``. If something accidentally calls
    Dataroma we want the test to fail loudly.
    """

    def _explode_if_called(*args, **kwargs):
        raise AssertionError(
            "bootstrap_whitelist job_type must not invoke DataromaClient — "
            "Dataroma sync now has its own dataroma_sync job_type."
        )

    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        _explode_if_called,
    )

    from app.services.thirteenf_admin_dashboard import _execute_job
    result = _execute_job(db_session, "bootstrap_whitelist", {})

    # The handler must report which path it took so admin UI shows
    # "seeded N" instead of the old "managers_seen N" (which lied about
    # being a passive count).
    assert "managers_seeded" in result
    assert result["status"] == "succeeded"


def test_dataroma_sync_job_type_returns_diff_summary(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        lambda: [
            DataromaManager(name="Sync N1", dataroma_code="SN-1"),
            DataromaManager(name="Sync N2", dataroma_code="SN-2"),
        ],
    )

    from app.services.thirteenf_admin_dashboard import _execute_job
    result = _execute_job(db_session, "dataroma_sync", {})

    assert result["status"] == "succeeded"
    # Summary must carry counts so admin overview can show "2 new from
    # Dataroma" without having to re-run the sync to count.
    assert "diff" in result
    assert result["diff"]["new_count"] == 2
    assert result["diff"]["known_count"] == 0
    # And include at least the first-N samples so the admin UI can
    # render the diff without an extra fetch.
    assert len(result["diff"]["new_sample"]) == 2


# ---------------------------------------------------------------------------
# Sanity: V2 seed still works end-to-end through the new bootstrap path
# ---------------------------------------------------------------------------


def test_bootstrap_whitelist_handler_actually_seeds_v2_managers(db_session, monkeypatch):
    """Verify the wiring: bootstrap_whitelist job_type → seed_confirmed_managers
    → V2 classification ends up on the row."""
    monkeypatch.setattr(
        "app.services.edgar_ingestion._fetch_dataroma_managers",
        lambda: (_ for _ in ()).throw(AssertionError("dataroma must not be called")),
    )

    from app.services.thirteenf_admin_dashboard import _execute_job
    _execute_job(db_session, "bootstrap_whitelist", {})
    db_session.flush()

    # Tiger Global should be present and correctly classified after this
    # offline bootstrap (validates the wiring end-to-end).
    tiger = (
        db_session.query(InstitutionManager)
        .filter_by(cik="0001167483")
        .one_or_none()
    )
    assert tiger is not None
    assert tiger.style_primary == "growth_long_short"
    assert tiger.manager_type == "high_turnover"
