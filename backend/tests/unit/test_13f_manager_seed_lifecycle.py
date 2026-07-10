"""M1: manager seeding must never overwrite a human lifecycle decision.

`seed_confirmed_managers` is about to be wired into the deploy path, so its
write semantics become a recurring, silent event. Two defects made that unsafe:

- it wrote `match_status = "confirmed"` unconditionally, so a re-seed RESURRECTED
  a manager an admin had retired (`status/match_status = "inactive"`), and
  ingestion selects managers by `match_status == "confirmed"`;
- it never wrote `status` on creation, so a fresh bootstrap produced
  `status = "candidate"` rows that `thirteenf_daily_sync`, `thirteenf_readiness`
  and `thirteenf_historical_backfill` (all of which filter `status == "active"`)
  cannot see.

PO ruling: the seed expresses INTENT (identity + classification); a human
expresses LIFECYCLE; the human wins. Seeding never deactivates anyone.
"""
from __future__ import annotations

from app.models.institutions import (
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
)
from app.services.edgar_ingestion import seed_confirmed_managers


def _seeded(db_session) -> InstitutionManager:
    """One manager that is genuinely in the seed file."""
    seed_confirmed_managers(db_session)
    db_session.flush()
    m = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.match_status == "confirmed")
        .order_by(InstitutionManager.id)
        .first()
    )
    assert m is not None
    return m


def test_reseeding_a_database_seeded_from_the_old_file_re_points_not_duplicates(
    db_session,
):
    """External review P1 — the regression that blocked deploy.

    A curated CIK can change: the filer moves entities, or the original was
    simply wrong. On a database seeded from the OLD file — 82 rows carrying the
    OLD CIKs — the new seed must find each manager by its `previous_ciks` and
    RE-POINT the existing row, not create a second confirmed row for the same
    manager (5 real duplicates) and refuse the rest as name collisions (5 more
    left absent), turning 82 into 87 on every deploy.
    """
    import json
    from pathlib import Path

    from app.services.edgar_ingestion import _normalize_name

    seed_path = (
        Path(__file__).resolve().parents[2]
        / "app" / "services" / "seed_data" / "confirmed_managers.json"
    )
    entries = json.loads(seed_path.read_text())

    # Build the DB as the OLD file would have: every manager at its previous CIK
    # where one is recorded, else its current CIK.
    for e in entries:
        old_cik = (e.get("previous_ciks") or [e["cik"]])[0]
        db_session.add(
            InstitutionManager(
                cik=old_cik, legal_name=e["legal_name"], display_name=e["display_name"],
                name_normalized=_normalize_name(e["legal_name"]),
                dataroma_code=e.get("dataroma_code"), match_status="confirmed",
                status="active", is_superinvestor=True,
                style_primary=e.get("style_primary", "unknown"),
                capital_structure=e.get("capital_structure", "unknown"),
            )
        )
    db_session.flush()
    before = db_session.query(InstitutionManager).count()

    report = seed_confirmed_managers(db_session)
    db_session.flush()

    n_changed = sum(1 for e in entries if e.get("previous_ciks"))
    assert report["created"] == 0, "a re-seed must never create a duplicate manager"
    assert report["ambiguous_name_match"] == 0, "no manager left absent as a collision"
    assert report["updated"] == len(entries)
    assert report["cik_repointed"] == n_changed
    assert db_session.query(InstitutionManager).count() == before == len(entries)

    # Every display_name resolves to exactly one row, now at the new CIK.
    for e in entries:
        rows = (
            db_session.query(InstitutionManager)
            .filter(InstitutionManager.display_name == e["display_name"])
            .all()
        )
        assert len(rows) == 1, f"{e['display_name']} has {len(rows)} rows"
        assert rows[0].cik == e["cik"]

    # Each re-point left an audit event naming the old and new CIK.
    events = (
        db_session.query(InstitutionManagerCikReviewEvent)
        .filter(InstitutionManagerCikReviewEvent.event_type == "seed_cik_repoint")
        .all()
    )
    assert len(events) == n_changed
    assert all(ev.requires_downstream_review for ev in events)
    changed = {(e["previous_ciks"][0], e["cik"]) for e in entries if e.get("previous_ciks")}
    assert {(ev.old_cik, ev.new_cik) for ev in events} == changed


def test_a_re_point_does_not_fire_on_a_fresh_or_already_migrated_database(db_session):
    """No spurious audit events when the CIK is already correct."""
    first = seed_confirmed_managers(db_session)
    db_session.flush()
    assert first["cik_repointed"] == 0  # fresh DB: everyone created at the new CIK

    second = seed_confirmed_managers(db_session)
    assert second["cik_repointed"] == 0  # already-migrated DB: nothing to re-point
    events = (
        db_session.query(InstitutionManagerCikReviewEvent)
        .filter(InstitutionManagerCikReviewEvent.event_type == "seed_cik_repoint")
        .count()
    )
    assert events == 0


def test_a_manager_revoked_at_its_previous_cik_is_not_resurrected(db_session):
    """External review round 2. A revoke NULLs the CIK and records the OLD cik in
    an audit event. Neither the previous_ciks lookup (filters on a non-NULL cik)
    nor the revoke guard (checked only the NEW cik) would find it — so the create
    path resurrected a human-revoked manager under the new CIK, defeating the
    revocation. The revoke guard must consider every CIK the seed knows for this
    manager, current and previous.
    """
    import json
    from pathlib import Path

    from app.models.institutions import InstitutionManagerCikReviewEvent
    from app.services.edgar_ingestion import _normalize_name

    entries = json.loads(
        (Path(__file__).resolve().parents[2]
         / "app" / "services" / "seed_data" / "confirmed_managers.json").read_text()
    )
    changed = next(e for e in entries if e.get("previous_ciks"))
    old_cik = changed["previous_ciks"][0]

    # A database seeded from the OLD file: this manager at his OLD cik.
    m = InstitutionManager(
        cik=old_cik, legal_name=changed["legal_name"], display_name=changed["display_name"],
        name_normalized=_normalize_name(changed["legal_name"]), match_status="confirmed",
        status="active", is_superinvestor=True,
    )
    db_session.add(m)
    db_session.flush()

    # A human revokes him at that OLD cik (the real revoke: NULL cik + event).
    db_session.add(
        InstitutionManagerCikReviewEvent(
            manager_id=m.id, event_type="revoke_confirmed_cik",
            old_cik=old_cik, new_cik=None,
            old_match_status="confirmed", new_match_status="revoked",
            note="human revoked",
        )
    )
    m.cik = None
    m.match_status = "revoked"
    m.status = "needs_review"
    db_session.flush()

    report = seed_confirmed_managers(db_session)
    db_session.flush()

    rows = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.display_name == changed["display_name"])
        .all()
    )
    assert len(rows) == 1, "the revoked manager must not be duplicated"
    assert rows[0].match_status == "revoked", "the revocation stands"
    assert rows[0].cik is None, "the new CIK is not re-attached"
    assert changed["cik"] in report["skipped_human_decided_ciks"]


def test_a_human_retired_manager_is_not_re_pointed(db_session):
    """The re-point lookup feeds the same update path, so the human still wins."""
    seed_confirmed_managers(db_session)
    db_session.flush()
    import json
    from pathlib import Path

    entries = json.loads(
        (Path(__file__).resolve().parents[2]
         / "app" / "services" / "seed_data" / "confirmed_managers.json").read_text()
    )
    changed = next(e for e in entries if e.get("previous_ciks"))
    m = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.cik == changed["cik"])
        .one()
    )
    # An operator retires him and detaches the CIK to the OLD value.
    m.status = "inactive"
    m.cik = changed["previous_ciks"][0]
    db_session.flush()

    report = seed_confirmed_managers(db_session)

    db_session.refresh(m)
    assert m.status == "inactive", "a retired manager is not reactivated"
    assert m.cik == changed["previous_ciks"][0], "and his CIK is not re-pointed"
    assert changed["cik"] in report["skipped_human_decided_ciks"]


def test_seed_returns_a_diff_report_not_a_bare_count(db_session):
    report = seed_confirmed_managers(db_session)

    assert isinstance(report, dict), "seeding must report a diff, not a bare int"
    for key in ("created", "updated", "skipped_human_decided"):
        assert key in report, f"missing {key!r} in {sorted(report)}"
    assert report["created"] >= 80
    assert report["skipped_human_decided"] == 0


def test_new_rows_are_active_so_the_universe_is_actually_tracked(db_session):
    """P2: daily sync / readiness / historical backfill all filter
    `status == 'active'`. A seeded manager stuck at the model default
    'candidate' is invisible to them — the fresh-bootstrap chain breaks."""
    seed_confirmed_managers(db_session)
    db_session.flush()

    rows = db_session.query(InstitutionManager).all()
    assert rows
    assert all(m.match_status == "confirmed" for m in rows)
    assert all(m.status == "active" for m in rows), (
        "seeded managers must be active; otherwise daily_sync/readiness/"
        "historical_backfill filter them all out"
    )


def test_reseed_never_resurrects_an_admin_deactivated_manager(db_session):
    """P1, the headline: an admin retires a manager; the next deploy re-seeds.
    The manager must STAY retired."""
    m = _seeded(db_session)
    cik = m.cik

    # exactly what thirteenf_admin_dashboard's retire action writes
    m.status = "inactive"
    m.match_status = "inactive"
    m.display_name = "RETIRED - DO NOT TOUCH"
    db_session.flush()

    report = seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert m.match_status == "inactive", "re-seed resurrected a retired manager"
    assert m.status == "inactive"
    # Skipped WHOLE: seeding must not reach into a row whose lifecycle a human
    # owns, not even to refresh identity fields.
    assert m.display_name == "RETIRED - DO NOT TOUCH"
    assert report["skipped_human_decided"] >= 1
    assert cik in report["skipped_human_decided_ciks"]


def test_reseed_does_not_promote_an_unconfirmed_manager_but_reports_him(db_session):
    """A Dataroma candidate later curated into the JSON must NOT be silently
    promoted — a human confirms. But "nothing happened" must not be silent
    either: he is reported under awaiting_confirmation."""
    m = _seeded(db_session)
    cik = m.cik
    m.match_status = "candidate"
    m.status = "candidate"
    db_session.flush()

    report = seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert m.match_status == "candidate", "seeding must not promote; a human confirms"
    assert report["awaiting_confirmation"] >= 1
    assert cik in report["awaiting_confirmation_ciks"]


def test_reseed_never_overwrites_lifecycle_of_a_live_manager(db_session):
    """Even for a manager who is NOT deactivated, seeding expresses intent, not
    lifecycle: it must leave `match_status` / `status` exactly as found."""
    m = _seeded(db_session)
    m.match_status = "needs_review"   # a human parked this one for review
    m.status = "needs_review"
    db_session.flush()

    seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert m.match_status == "needs_review"
    assert m.status == "needs_review"


def test_reseed_still_refreshes_identity_and_classification(db_session):
    """Seeding remains useful: it re-applies curated identity/classification."""
    m = _seeded(db_session)
    original_style = m.style_primary
    m.display_name = "STALE"
    m.style_primary = "unknown"
    db_session.flush()

    seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert m.display_name != "STALE"
    assert m.style_primary == original_style


def test_seed_never_deactivates_a_manager_absent_from_the_seed_file(db_session):
    """PO ruling: seeding never retires anyone. A manager not in the JSON is
    left completely alone (dropped-bucket handling is the sync task's job,
    and it only ever proposes)."""
    seed_confirmed_managers(db_session)
    stranger = InstitutionManager(
        cik="0009999123", legal_name="Not In Seed LP", display_name="Not In Seed",
        name_normalized="not in seed lp", match_status="confirmed", status="active",
    )
    db_session.add(stranger)
    db_session.flush()

    seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(stranger)

    assert stranger.match_status == "confirmed"
    assert stranger.status == "active"


def test_seed_is_idempotent(db_session):
    first = seed_confirmed_managers(db_session)
    db_session.flush()
    n_after_first = db_session.query(InstitutionManager).count()

    second = seed_confirmed_managers(db_session)
    db_session.flush()
    n_after_second = db_session.query(InstitutionManager).count()

    assert n_after_second == n_after_first, "seeding duplicated rows"
    assert first["created"] >= 80
    assert second["created"] == 0, "second run must create nothing"


# ---------------------------------------------------------------------------
# REVOKED is the heaviest human decision in this table: `revoke_confirmed_cik`
# demands a note, writes an InstitutionManagerCikReviewEvent, and NULLs the CIK
# ("this CIK is not this manager"). Seeding found two ways to undo it.
# ---------------------------------------------------------------------------

def _revoke(db_session, m) -> None:
    """Exactly what thirteenf_admin_dashboard.revoke_confirmed_cik writes:
    the CIK is detached AND an audit event records which CIK was revoked.
    Seeding keys off that event, so a test that skips it is not faithful."""
    old_cik = m.cik
    m.cik = None
    m.match_status = "revoked"
    db_session.add(
        InstitutionManagerCikReviewEvent(
            manager_id=m.id,
            event_type="revoke_confirmed_cik",
            old_cik=old_cik,
            old_match_status="confirmed",
            new_match_status="revoked",
        )
    )
    db_session.flush()


def test_reseed_does_not_reattach_a_revoked_cik(db_session):
    """A revoked manager who still carries a dataroma_code IS found by the seed.
    Writing `existing.cik = cik` would silently re-attach the very CIK a human
    detached, leaving the row contradicting its own audit trail."""
    seed_confirmed_managers(db_session)
    db_session.flush()
    m = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.dataroma_code.isnot(None))
        .order_by(InstitutionManager.id)
        .first()
    )
    assert m is not None and m.cik
    _revoke(db_session, m)

    report = seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert m.cik is None, "re-seed re-attached a revoked CIK"
    assert m.match_status == "revoked"
    assert report["skipped_human_decided"] >= 1


def test_reseed_does_not_duplicate_a_revoked_manager_without_a_dataroma_code(db_session):
    """Only 20 of the 82 seed entries carry a dataroma_code. For the rest, a
    revocation NULLs the only key the seed matched on — so it used to CREATE A
    SECOND, `confirmed` row for the same person, which then gets ingested and
    defeats the revocation entirely. The name_normalized fallback finds him."""
    seed_confirmed_managers(db_session)
    db_session.flush()
    m = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.dataroma_code.is_(None))
        .order_by(InstitutionManager.id)
        .first()
    )
    assert m is not None and m.cik
    _revoke(db_session, m)
    rows_before = db_session.query(InstitutionManager).count()

    report = seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert db_session.query(InstitutionManager).count() == rows_before, (
        "re-seed created a duplicate row for a revoked manager"
    )
    assert report["created"] == 0
    assert m.cik is None and m.match_status == "revoked"
    assert report["skipped_human_decided"] >= 1


# ---------------------------------------------------------------------------
# Review findings (2026-07-09): names must never be an update key; needs_review
# is a human state; the seed must be safe under concurrent deploy-time runs.
# ---------------------------------------------------------------------------

def test_seed_never_writes_through_a_normalized_name_match(db_session):
    """`_normalize_name` strips 'capital'/'management'/'investments', so 35 of
    the 82 curated names collapse to a single token. An unrelated manager whose
    name normalizes the same must NOT receive the curated CIK/identity — that
    would ingest and score the wrong SEC filer under his id."""
    from app.services.edgar_ingestion import _normalize_name

    impostor = InstitutionManager(
        cik=None, dataroma_code=None,
        legal_name="Ariel Capital LLC", display_name="Ariel Capital",
        name_normalized=_normalize_name("Ariel Capital LLC"),
        match_status="candidate", status="candidate",
    )
    db_session.add(impostor)
    db_session.flush()
    assert impostor.name_normalized == _normalize_name("ARIEL INVESTMENTS, LLC")

    report = seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(impostor)

    # untouched: no CIK grafted on, no curated identity written through
    assert impostor.cik is None
    assert impostor.legal_name == "Ariel Capital LLC"
    assert impostor.display_name == "Ariel Capital"
    assert impostor.style_primary in (None, "unknown")
    # and the conflict is named, not silent
    assert report["ambiguous_name_match"] >= 1
    assert report["ambiguous_name_match_ciks"]


def test_needs_review_row_is_skipped_whole_in_its_own_bucket(db_session):
    """An operator explicitly parked this row. Refreshing its name or
    classification mid-review would overwrite what is being adjudicated — and
    'awaiting_confirmation' describes a different workflow."""
    m = _seeded(db_session)
    cik = m.cik
    m.match_status = "needs_review"
    m.status = "needs_review"
    m.display_name = "OPERATOR IS LOOKING AT THIS"
    m.style_primary = "unknown"
    db_session.flush()

    report = seed_confirmed_managers(db_session)
    db_session.flush()
    db_session.refresh(m)

    assert m.display_name == "OPERATOR IS LOOKING AT THIS", "seed touched a parked row"
    assert m.style_primary == "unknown"
    assert m.match_status == "needs_review"
    assert report["skipped_needs_review"] >= 1
    assert cik in report["skipped_needs_review_ciks"]
    assert cik not in report["awaiting_confirmation_ciks"], (
        "a human-parked row is not the same workflow as awaiting confirmation"
    )


def test_revoked_row_lands_in_human_decided_not_needs_review(db_session):
    """A revoked row derives status='needs_review'. Bucket order matters: it is
    a human DECISION, not a row parked for review."""
    seed_confirmed_managers(db_session)
    db_session.flush()
    m = (
        db_session.query(InstitutionManager)
        .filter(InstitutionManager.dataroma_code.isnot(None))
        .order_by(InstitutionManager.id)
        .first()
    )
    cik = m.cik
    _revoke(db_session, m)

    report = seed_confirmed_managers(db_session)

    assert cik in report["skipped_human_decided_ciks"]
    assert cik not in report["skipped_needs_review_ciks"]


def test_concurrent_seed_serializes_on_the_advisory_lock():
    """M2 runs this on every deploy and prod may start two api containers. Two
    processes must not both walk the create path into the unique `cik` index —
    one would die and, under `restart: unless-stopped`, crash-loop.

    Uses real committed sessions (not the rollback fixture), with cleanup.
    """
    import threading

    from sqlalchemy import text

    from app.core.db import SessionLocal

    b_done = threading.Event()
    b_error: list[Exception] = []

    def run_b():
        s_b = SessionLocal()
        try:
            seed_confirmed_managers(s_b)
            s_b.commit()
        except Exception as exc:  # pragma: no cover - failure path
            s_b.rollback()
            b_error.append(exc)
        finally:
            s_b.close()
            b_done.set()

    s_a = SessionLocal()
    try:
        seed_confirmed_managers(s_a)  # takes the advisory lock, does not commit

        probe = SessionLocal()
        try:
            got = probe.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended('seed_confirmed_managers', 0))")
            ).scalar()
            assert got is False, "seeding did not hold a global advisory lock"
        finally:
            probe.rollback()
            probe.close()

        t = threading.Thread(target=run_b)
        t.start()
        assert not b_done.wait(timeout=1.0), "B seeded while A held the lock"

        s_a.commit()
        assert b_done.wait(timeout=20.0), "B never finished after A committed"
        t.join(timeout=20.0)
        assert not b_error, f"concurrent seed raised: {b_error}"

        verify = SessionLocal()
        try:
            # B must have taken the update path, not duplicated anyone.
            rows = verify.query(InstitutionManager).count()
            dupes = verify.execute(text(
                "SELECT count(*) FROM (SELECT cik FROM institution_managers "
                "WHERE cik IS NOT NULL GROUP BY cik HAVING count(*)>1) d")).scalar()
            assert dupes == 0, "concurrent seed produced duplicate CIKs"
            assert rows >= 80
        finally:
            verify.close()
    finally:
        s_a.rollback()
        s_a.close()
        cleanup = SessionLocal()
        try:
            cleanup.query(InstitutionManager).delete()
            cleanup.commit()
        finally:
            cleanup.close()
