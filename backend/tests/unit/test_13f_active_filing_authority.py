"""T1-FU: single active-filing authority + accepted_at + ties + concurrency.

`apply_active_filing_policy(session, manager_id, quarter_end_date)` is THE
decision point for `is_active_for_manager_period`. These tests pin its rules:

- ranking = (accepted_at, accession_no) desc; NT never beats HR; parse gate for
  restatements only; terminal admin statuses respected (a rejected restatement
  must never be re-activated by a pipeline re-run — pre-existing bug).
- equal-accepted_at ties: originals → deactivate-all + warning (existing
  apply_amendment_policy semantics); restatements → NO auto-switch + warning.
- accepted_at is populated from the primary doc on the bulk path
  (apply_primary_doc_metadata + backfill_period_routing) — it was NULL on all
  373 real filings, degrading every ranking to accession_no.
- a (manager, period) advisory xact lock serializes concurrent reparse jobs.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import Filing13F, InstitutionManager, RawSourceDocument

_SEQ = count(1)
_CIK_SEQ = count(7700000000)

_QEND = date(2024, 3, 31)


def _manager(session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"AFA Manager {cik}",
        legal_name=f"AFA Manager {cik}",
        edgar_legal_name=f"AFA Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    session.add(m)
    session.flush()
    return m


def _filing(
    session,
    mgr,
    *,
    form_type: str = "13F-HR",
    accepted_at: datetime | None = None,
    is_amendment: bool = False,
    amendment_type: str | None = None,
    amendment_status: str = "no_amendments_seen",
    parse_status: str = "pending",
    active: bool = False,
    qend: date = _QEND,
) -> Filing13F:
    n = next(_SEQ)
    accession = f"AFA{n:017d}"
    f = Filing13F(
        manager_id=mgr.id,
        cik=mgr.cik,
        accession_no=accession,
        accession_number=accession,
        form_type=form_type,
        period_of_report=qend,
        filed_at=date(qend.year, qend.month, 15),
        filing_date=date(qend.year, qend.month, 15),
        accepted_at=accepted_at,
        report_quarter=f"{qend.year}-Q{(qend.month - 1) // 3 + 1}",
        quarter_end_date=qend,
        is_amendment=is_amendment,
        amendment_type=amendment_type,
        amendment_status=amendment_status,
        parse_status=parse_status,
        is_active_for_manager_period=active,
        # Orthogonal to active-filing selection; the partial unique index
        # uq_filings_13f_latest_per_period allows only one TRUE per period.
        is_latest_for_period=False,
    )
    session.add(f)
    session.flush()
    return f


def _ts(hour: int) -> datetime:
    return datetime(2024, 5, 15, hour, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Originals selection
# ---------------------------------------------------------------------------

def test_authority_activates_latest_original_by_accepted_at(db_session):
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    early = _filing(db_session, mgr, accepted_at=_ts(10))
    late = _filing(db_session, mgr, accepted_at=_ts(12))

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert late.is_active_for_manager_period is True
    assert early.is_active_for_manager_period is False


def test_authority_original_tie_deactivates_all_with_warning(db_session):
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    a = _filing(db_session, mgr, accepted_at=_ts(10), active=True)
    b = _filing(db_session, mgr, accepted_at=_ts(10))

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    for f in (a, b):
        assert f.is_active_for_manager_period is False
        assert f.amendment_sort_warning is True
        assert f.amendment_status == "amendments_pending"


def test_authority_tie_recovery_restores_status(db_session):
    """Pre-existing dead-code bug: the amendments_pending → no_amendments_seen
    recovery checked amendment_sort_warning AFTER clearing it, so a resolved tie
    left originals stuck in amendments_pending forever."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    a = _filing(db_session, mgr, accepted_at=_ts(10))
    b = _filing(db_session, mgr, accepted_at=_ts(10))
    apply_active_filing_policy(db_session, mgr.id, _QEND)  # tie
    assert a.amendment_status == "amendments_pending"

    b.accepted_at = _ts(12)  # tie resolved (e.g. corrected acceptance data)
    db_session.flush()
    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert b.is_active_for_manager_period is True
    assert a.is_active_for_manager_period is False
    for f in (a, b):
        assert f.amendment_sort_warning is False
        assert f.amendment_status == "no_amendments_seen"


def test_authority_solo_hr_activated_solo_unresolved_amendment_not(db_session):
    """Phase-4c parity: a solo plain 13F-HR is activated; a solo 13F-HR/A with
    no parsed RESTATEMENT resolution must never be auto-activated."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr1 = _manager(db_session)
    hr = _filing(db_session, mgr1)
    apply_active_filing_policy(db_session, mgr1.id, _QEND)
    assert hr.is_active_for_manager_period is True

    mgr2 = _manager(db_session)
    amd = _filing(
        db_session, mgr2, form_type="13F-HR/A",
        is_amendment=True, amendment_status="amendments_pending",
    )
    apply_active_filing_policy(db_session, mgr2.id, _QEND)
    assert amd.is_active_for_manager_period is False


# ---------------------------------------------------------------------------
# NT exclusion
# ---------------------------------------------------------------------------

def test_authority_hr_beats_nt_regardless_of_accepted_at(db_session):
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    hr = _filing(db_session, mgr, form_type="13F-HR", accepted_at=_ts(10))
    nt = _filing(db_session, mgr, form_type="13F-NT", accepted_at=_ts(14))

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert hr.is_active_for_manager_period is True
    assert nt.is_active_for_manager_period is False


def test_authority_nt_only_period_activates_nt(db_session):
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    nt = _filing(db_session, mgr, form_type="13F-NT", accepted_at=_ts(10))

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert nt.is_active_for_manager_period is True


# ---------------------------------------------------------------------------
# Restatements
# ---------------------------------------------------------------------------

def test_authority_parsed_restatement_supersedes_original(db_session):
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(10), active=True)
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert rst.is_active_for_manager_period is True
    assert rst.amendment_status == "applied"
    assert orig.is_active_for_manager_period is False


def test_authority_unparsed_restatement_does_not_supersede(db_session):
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(10), active=True)
    _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="pending",
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert orig.is_active_for_manager_period is True


def test_authority_restatement_tie_no_auto_switch(db_session):
    """Equal accepted_at between the top two parsed restatements → do NOT
    auto-switch: the currently active filing stays active, the tied
    restatements get amendment_sort_warning + amendments_pending for a human."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(10), active=True)
    r1 = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    r2 = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert orig.is_active_for_manager_period is True  # no auto-switch
    for r in (r1, r2):
        assert r.is_active_for_manager_period is False
        assert r.amendment_sort_warning is True
        assert r.amendment_status == "amendments_pending"


def test_authority_rejected_restatement_never_reactivated(db_session):
    """Pre-existing bug: Phase 5's reconcile ignored amendment_status, so an
    admin-REJECTED restatement was force re-activated by any quarter re-run."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(10), active=True)
    rejected = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="rejected", parse_status="succeeded",
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert orig.is_active_for_manager_period is True
    assert rejected.is_active_for_manager_period is False
    assert rejected.amendment_status == "rejected"  # terminal, untouched


def test_authority_respects_applied_admin_amendment(db_session):
    """An admin activate_as_original on a non-restatement amendment owns the
    slot; originals stay off and the admin's choice is not disturbed."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(14))  # later than amendment!
    applied = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="NEW_HOLDINGS",
        amendment_status="applied", parse_status="succeeded", active=True,
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert applied.is_active_for_manager_period is True
    assert orig.is_active_for_manager_period is False


def test_reconcile_wrapper_converges_regardless_of_argument(db_session):
    """reconcile_restatement_activation now delegates to the authority: calling
    it on the EARLIER restatement still activates the ranked winner."""
    from app.services.thirteenf_holdings_ingest import reconcile_restatement_activation

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    early = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(11),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    late = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(13),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )

    changed = reconcile_restatement_activation(db_session, early)

    assert changed is True
    assert late.is_active_for_manager_period is True
    assert early.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is False


# ---------------------------------------------------------------------------
# Review fixes — P1-2 rule-2 owner, P1-3 missing acceptance, P1-4 propagation,
# P2-6 restatement tie recovery
# ---------------------------------------------------------------------------

def test_rule2_selects_unique_owner_and_demotes_rejected_active(db_session):
    """P1-2 (review timeline): apply A, apply B, reject B. Rule 2 must pick a
    unique applied owner (A) and demote the rejected-but-still-active B — the
    old rule 2 only demoted originals and left B serving forever."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9))
    a = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(11),
        is_amendment=True, amendment_type="NEW_HOLDINGS",
        amendment_status="applied", parse_status="succeeded",
    )
    b = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(13),
        is_amendment=True, amendment_type="NEW_HOLDINGS",
        amendment_status="rejected", parse_status="succeeded", active=True,
    )

    out = apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert out["decision"] == "amendment_owned"
    assert a.is_active_for_manager_period is True
    assert b.is_active_for_manager_period is False  # rejected must not serve
    assert orig.is_active_for_manager_period is False


def test_none_eligible_demotes_stray_active(db_session):
    """P1-2 corollary: a period whose ONLY filing is a rejected-but-active
    amendment must end with nothing active."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    b = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(13),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="rejected", parse_status="succeeded", active=True,
    )

    out = apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert out["decision"] == "none_eligible"
    assert b.is_active_for_manager_period is False


def test_missing_acceptance_does_not_flip_active(db_session):
    """P1-3: NULL accepted_at is missing evidence, not "earliest". A currently
    active restatement whose doc failed to yield accepted_at must NOT lose to
    an older sibling that has one; both sides get flagged instead."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    older = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(10),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    newer_null = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=None,
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="applied", parse_status="succeeded", active=True,
    )

    out = apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert out["decision"] == "missing_acceptance"
    assert newer_null.is_active_for_manager_period is True  # no auto-switch
    assert older.is_active_for_manager_period is False
    assert newer_null.amendment_sort_warning is True  # flagged (kept-active)
    assert newer_null.amendment_status == "applied"  # terminal, untouched


def test_solo_restatement_with_null_acceptance_still_wins(db_session):
    """P1-3 reverse guard: a SINGLE parsed restatement needs no ordering
    evidence — NULL accepted_at must not block it from superseding."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=None,
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert rst.is_active_for_manager_period is True
    assert orig.is_active_for_manager_period is False


def test_restatement_tie_flags_kept_active_filing(db_session):
    """P1-4: when a restatement tie keeps the original serving, the original
    itself must carry amendments_pending + warning so product consumers
    (Oracle's Lens MVP4-05/MVP5-02) see the dispute instead of scoring it as
    a clean signal."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    for _ in range(2):
        _filing(
            db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
            is_amendment=True, amendment_type="RESTATEMENT",
            amendment_status="pending_parse", parse_status="succeeded",
        )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert orig.is_active_for_manager_period is True
    assert orig.amendment_sort_warning is True
    assert orig.amendment_status == "amendments_pending"  # Lens excludes this


def test_restatement_tie_recovery_clears_all_residue(db_session):
    """P2-6: once a restatement tie resolves, the loser AND the previously
    kept-active original must be un-flagged (the loser back to pending_parse,
    the original back to no_amendments_seen) — no immortal admin task."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    r1 = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    r2 = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    apply_active_filing_policy(db_session, mgr.id, _QEND)  # tie
    assert r1.amendment_status == "amendments_pending"
    assert orig.amendment_status == "amendments_pending"

    r2.accepted_at = _ts(14)  # tie resolved
    db_session.flush()
    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert r2.is_active_for_manager_period is True
    assert r2.amendment_status == "applied"
    assert r2.amendment_sort_warning is False
    # Loser restored to its pre-tie state; no stale admin task.
    assert r1.amendment_sort_warning is False
    assert r1.amendment_status == "pending_parse"
    # Previously kept-active original fully recovered.
    assert orig.is_active_for_manager_period is False
    assert orig.amendment_sort_warning is False
    assert orig.amendment_status == "no_amendments_seen"


def test_nt_a_restatement_never_competes_for_holdings_slot(db_session):
    """P2-9: a parsed 13F-NT/A RESTATEMENT must not supersede an HR original —
    a notice amendment carries no holdings."""
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    hr = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    nta = _filing(
        db_session, mgr, form_type="13F-NT/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )

    apply_active_filing_policy(db_session, mgr.id, _QEND)

    assert hr.is_active_for_manager_period is True
    assert nta.is_active_for_manager_period is False


# ---------------------------------------------------------------------------
# Review fixes — P1-1 admin resolution through lock + authority
# ---------------------------------------------------------------------------

def test_admin_reject_immediately_demotes_active_restatement(db_session):
    """P1-1 (review timeline): rejecting the ACTIVE restatement must hand the
    slot back to the original in the same action — not leave a rejected filing
    serving the product until some future sweep."""
    from app.services.thirteenf_admin_dashboard import resolve_amendment

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9))
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="applied", parse_status="succeeded", active=True,
    )

    resolve_amendment(db_session, rst.accession_no, "reject")

    db_session.refresh(rst)
    db_session.refresh(orig)
    assert rst.amendment_status == "rejected"
    assert rst.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is True  # next eligible takes over


def test_admin_defer_is_honored_and_excluded_from_competition(db_session):
    """Re-review P1: defer must PARK a parsed restatement, not be erased by the
    convergence in the same transaction. The old defer status
    (amendments_pending) was a COMPETING state, so the authority immediately
    re-applied the just-deferred restatement."""
    from app.services.thirteenf_admin_dashboard import resolve_amendment
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )

    resolve_amendment(db_session, rst.accession_no, "defer")

    db_session.refresh(rst)
    db_session.refresh(orig)
    assert rst.amendment_status == "deferred"  # NOT re-applied
    assert rst.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is True

    # Durable: a later sweep must not undo the deferral either.
    apply_active_filing_policy(db_session, mgr.id, _QEND)
    assert rst.amendment_status == "deferred"
    assert rst.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is True


def test_admin_defer_of_active_restatement_hands_slot_back(db_session):
    """Deferring the CURRENTLY ACTIVE restatement withdraws it: the next
    eligible filing (the original) takes over in the same action."""
    from app.services.thirteenf_admin_dashboard import resolve_amendment

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9))
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="applied", parse_status="succeeded", active=True,
    )

    resolve_amendment(db_session, rst.accession_no, "defer")

    db_session.refresh(rst)
    db_session.refresh(orig)
    assert rst.amendment_status == "deferred"
    assert rst.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is True


def test_bulk_reingest_does_not_reset_deferred(db_session):
    """deferred is an admin decision — a metadata re-apply (Phase 2.5) must
    not reset it back into a competing state."""
    from app.services.thirteenf_filing_detail import apply_amendment_policy

    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="deferred", parse_status="succeeded",
    )
    rst.amendment_type_raw = "RESTATEMENT"
    db_session.flush()

    apply_amendment_policy(db_session, rst)  # metadata re-apply

    assert rst.amendment_status == "deferred"  # terminal: untouched
    assert rst.is_active_for_manager_period is False


def test_admin_applied_nta_counts_as_nt_only(db_session):
    """Re-review P2: an admin-applied ACTIVE 13F-NT/A is still a notice — the
    manager must appear in nt_only_manager_ids (not be counted in the
    expected-HR denominator)."""
    from app.services.thirteenf_admin_dashboard import resolve_amendment
    from app.services.thirteenf_holdings_query import nt_only_manager_ids

    mgr = _manager(db_session)
    nt = _filing(db_session, mgr, form_type="13F-NT", accepted_at=_ts(9), active=True)
    nta = _filing(
        db_session, mgr, form_type="13F-NT/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="NEW_HOLDINGS",
        amendment_status="amendments_pending", parse_status="succeeded",
    )

    resolve_amendment(db_session, nta.accession_no, "apply")

    db_session.refresh(nta)
    db_session.refresh(nt)
    assert nta.is_active_for_manager_period is True  # admin decision honored
    assert nt.is_active_for_manager_period is False
    assert mgr.id in nt_only_manager_ids(db_session)  # still a notice manager


def test_active_nta_treated_as_notice_across_consumers(db_session):
    """Third-review P2: an ACTIVE 13F-NT/A must be treated as a notice by
    EVERY exact-NT consumer, not only nt_only_manager_ids — quarter status
    `reported_elsewhere`, holdings response NOTICE_REPORTED_ELSEWHERE, and
    Oracle's Lens `_is_nt_quarter` breaking the streak with the NT caveat."""
    from app.services.oracles_lens.base_primitives import _is_nt_quarter
    from app.services.thirteenf_user_api import (
        _filing_caveats,
        _quarter_payload,
        build_user_manager_holdings,
    )

    mgr = _manager(db_session)
    nta = _filing(
        db_session, mgr, form_type="13F-NT/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="NEW_HOLDINGS",
        amendment_status="applied", parse_status="succeeded", active=True,
    )

    # user_api: quarter status + caveat + holdings response.
    assert _quarter_payload(nta)["status"] == "reported_elsewhere"
    caveat_codes = {c["code"] for c in _filing_caveats(nta)}
    assert "NOTICE_REPORTED_ELSEWHERE" in caveat_codes
    holdings = build_user_manager_holdings(db_session, mgr.id, nta.report_quarter)
    assert holdings["status"] == "unavailable"
    assert holdings["reason"]["code"] == "NOTICE_REPORTED_ELSEWHERE"

    # Oracle's Lens streak logic: an NT/A quarter IS an NT quarter.
    assert _is_nt_quarter(
        db_session, manager_id=mgr.id, quarter=nta.report_quarter
    ) is True


def test_admin_apply_activates_target_through_authority(db_session):
    from app.services.thirteenf_admin_dashboard import resolve_amendment

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9), active=True)
    amd = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="NEW_HOLDINGS",
        amendment_status="amendments_pending", parse_status="succeeded",
    )

    resolve_amendment(db_session, amd.accession_no, "activate_as_original")

    db_session.refresh(amd)
    db_session.refresh(orig)
    assert amd.amendment_status == "applied"
    assert amd.is_active_for_manager_period is True
    assert orig.is_active_for_manager_period is False


# ---------------------------------------------------------------------------
# Review fixes — P1-5 controlled-reparse durable rejection
# ---------------------------------------------------------------------------

def test_validation_failed_restatement_rejection_is_sweep_durable(db_session):
    """P1-5: a validation-gate failure must persist a state the authority
    honors. The old bare pointer-restore left the restatement eligible, so the
    next sweep deterministically re-activated it, silently undoing the gate."""
    from app.services.thirteenf_controlled_reparse import (
        _reject_validation_failed_amendment,
    )
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    mgr = _manager(db_session)
    orig = _filing(db_session, mgr, accepted_at=_ts(9))
    rst = _filing(
        db_session, mgr, form_type="13F-HR/A", accepted_at=_ts(12),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="applied", parse_status="succeeded", active=True,
    )

    _reject_validation_failed_amendment(db_session, rst)

    assert rst.amendment_status == "rejected"
    assert rst.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is True

    # THE point: a later sweep must NOT undo the gate's rejection.
    out = apply_active_filing_policy(db_session, mgr.id, _QEND)
    assert out["active_id"] == orig.id
    assert rst.is_active_for_manager_period is False


# ---------------------------------------------------------------------------
# Review fixes — P2-8 accepted_at merge semantics
# ---------------------------------------------------------------------------

def test_merge_accepted_at_never_erases_with_null(db_session):
    from app.services.thirteenf_filing_detail import merge_accepted_at

    mgr = _manager(db_session)
    filing = _filing(db_session, mgr, accepted_at=_ts(10))

    assert merge_accepted_at(filing, None) is False
    assert filing.accepted_at == _ts(10)  # NULL never erases evidence

    assert merge_accepted_at(filing, _ts(11)) is True
    assert filing.accepted_at == _ts(11)  # non-NULL re-parse is authoritative

    assert merge_accepted_at(filing, _ts(11)) is False  # idempotent


# ---------------------------------------------------------------------------
# accepted_at population (item 2)
# ---------------------------------------------------------------------------

_PRIMARY_DOC = b"""<SEC-HEADER>
<ACCEPTANCE-DATETIME>20240515163000
</SEC-HEADER>
<edgarSubmission>
  <submissionType>13F-HR</submissionType>
  <periodOfReport>03-31-2024</periodOfReport>
  <formData><coverPage>
    <reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
  </coverPage></formData>
</edgarSubmission>"""


def test_apply_primary_doc_metadata_sets_accepted_at(db_session):
    from app.edgar.parsers.primary_doc import parse_primary_doc
    from app.services.thirteenf_filing_detail import apply_primary_doc_metadata

    mgr = _manager(db_session)
    filing = _filing(db_session, mgr)
    assert filing.accepted_at is None

    summary = parse_primary_doc(_PRIMARY_DOC)
    apply_primary_doc_metadata(db_session, filing, summary)

    # 2024-05-15 16:30 EASTERN (EDT, UTC-4) → 20:30 UTC. The raw 14-digit
    # ACCEPTANCE-DATETIME is Eastern wall time; the parser converts (T1-FU).
    assert filing.accepted_at == datetime(2024, 5, 15, 20, 30, 0, tzinfo=timezone.utc)


def test_backfill_period_routing_fills_accepted_at(db_session, monkeypatch):
    from app.models.institutions import RawSourceDocument
    from app.services.edgar_ingestion import backfill_period_routing

    mgr = _manager(db_session)
    filing = _filing(db_session, mgr)
    doc = RawSourceDocument(
        source_system="edgar", document_type="13f_primary",
        source_url="https://example.test/primary.xml", body_path="/nonexistent",
    )
    db_session.add(doc)
    db_session.flush()
    filing.raw_primary_doc_id = doc.id
    db_session.flush()

    monkeypatch.setattr("app.edgar.fetcher.load_body", lambda d: _PRIMARY_DOC)

    summary = backfill_period_routing(db_session, filings=[filing])

    # Eastern 16:30 (EDT) → 20:30 UTC (see parser tz note).
    assert filing.accepted_at == datetime(2024, 5, 15, 20, 30, 0, tzinfo=timezone.utc)
    assert summary.get("accepted_at_filled") == 1

    # Idempotent: second run fills nothing.
    summary2 = backfill_period_routing(db_session, filings=[filing])
    assert summary2.get("accepted_at_filled") == 0


# ---------------------------------------------------------------------------
# P2-7: ACCEPTANCE-DATETIME is Eastern wall time (DST-aware), stored as UTC
# ---------------------------------------------------------------------------

def _sgml(accession_dt: str | None, *, period="03-31-2024", form="13F-HR", amendment=False) -> bytes:
    header = f"<ACCEPTANCE-DATETIME>{accession_dt}\n" if accession_dt else ""
    amd = (
        "<amendmentInfo><amendmentType>RESTATEMENT</amendmentType></amendmentInfo>"
        if amendment
        else ""
    )
    return f"""<SEC-HEADER>
{header}</SEC-HEADER>
<edgarSubmission>
  <submissionType>{form}</submissionType>
  <periodOfReport>{period}</periodOfReport>
  <formData><coverPage>
    <reportCalendarOrQuarter>{period}</reportCalendarOrQuarter>
    {amd}
  </coverPage></formData>
</edgarSubmission>""".encode()


def test_acceptance_datetime_is_eastern_wall_time():
    from app.edgar.parsers.primary_doc import parse_primary_doc

    # Winter (EST, UTC-5): 2024-01-15 16:30 ET → 21:30 UTC.
    s = parse_primary_doc(_sgml("20240115163000"))
    assert s.accepted_at == datetime(2024, 1, 15, 21, 30, tzinfo=timezone.utc)

    # Summer (EDT, UTC-4): 2024-06-14 16:30 ET → 20:30 UTC.
    s = parse_primary_doc(_sgml("20240614163000"))
    assert s.accepted_at == datetime(2024, 6, 14, 20, 30, tzinfo=timezone.utc)

    # Post-20:00 ET crosses the UTC midnight — but the SEC filing DATE must
    # stay the EASTERN date.
    from app.edgar.parsers.primary_doc import edgar_accepted_date_eastern

    s = parse_primary_doc(_sgml("20240614203000"))
    assert s.accepted_at == datetime(2024, 6, 15, 0, 30, tzinfo=timezone.utc)
    assert edgar_accepted_date_eastern(s.accepted_at) == date(2024, 6, 14)


# ---------------------------------------------------------------------------
# Composition: the REAL bulk-ingest job end to end (review test gap)
# ---------------------------------------------------------------------------

def _stored_doc(db_session, doc_type: str) -> "RawSourceDocument":
    n = next(_SEQ)
    doc = RawSourceDocument(
        source_system="edgar", document_type=doc_type,
        source_url=f"https://example.test/{doc_type}-{n}.xml",
        body_path=f"/afa-{doc_type}-{n}",
    )
    db_session.add(doc)
    db_session.flush()
    return doc


_INFOTABLE = b"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip><value>8000000</value>
    <shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>50000</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>"""


def _job_filing(db_session, mgr, *, accession, form="13F-HR", filed, primary_bytes):
    """A quarter-window filing with stored primary+infotable docs, as the
    form.idx path leaves it (proxy period, nothing routed/parsed yet)."""
    primary = _stored_doc(db_session, "13f_primary")
    infotable = _stored_doc(db_session, "13f_infotable")
    f = Filing13F(
        manager_id=mgr.id, cik=mgr.cik,
        accession_no=accession, accession_number=accession,
        form_type=form,
        # The proxy IS filed_at (see `_accession_period_of_report`); `report_quarter`
        # stays NULL until routing. ingest_holdings("2025-Q4") claims it through
        # the filed-quarter arm, because 2025-Q4 13Fs are filed in 2026-Q1.
        period_of_report=filed,
        filed_at=filed, filing_date=filed,
        raw_primary_doc_id=primary.id, raw_infotable_doc_id=infotable.id,
        is_latest_for_period=False, parse_status="pending",
    )
    db_session.add(f)
    db_session.flush()
    return f, {primary.id: primary_bytes, infotable.id: _INFOTABLE}


def test_bulk_ingest_job_composition_end_to_end(db_session, monkeypatch):
    """Review test gap: drive the REAL ingest job — Phase 2 routing (fills
    accepted_at from the stored primary doc), Phase 2.5 metadata+policy,
    Phase 3 parse, Phase 5 authority sweep — and verify the result through
    the product query. Only the raw-byte reads and the EDGAR fetch are
    stubbed."""
    from app.services.thirteenf_admin_dashboard import execute_job_payload
    from app.services.thirteenf_holdings_query import active_hr_holdings_query

    mgr = _manager(db_session)
    filing, bodies = _job_filing(
        db_session, mgr, accession="AFAJOB0000000000001", filed=date(2026, 2, 14),
        primary_bytes=_sgml("20260214163000", period="12-31-2025"),
    )

    monkeypatch.setattr(
        "app.edgar.fetcher.load_body", lambda doc: bodies[doc.id]
    )
    monkeypatch.setattr(
        "app.services.edgar_ingestion.ensure_filing_infotable_doc",
        lambda session, f: f.raw_infotable_doc,
    )

    result = execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})

    assert result["status"] == "succeeded", result
    db_session.refresh(filing)
    # accepted_at persisted from the stored doc: 2026-02-14 16:30 EST → 21:30 UTC.
    assert filing.accepted_at == datetime(2026, 2, 14, 21, 30, tzinfo=timezone.utc)
    assert filing.quarter_end_date == date(2025, 12, 31)  # routed
    assert filing.parse_status == "succeeded"
    assert filing.is_active_for_manager_period is True  # policy sweep
    visible = (
        active_hr_holdings_query(db_session)
        .filter(Filing13F.id == filing.id)
        .count()
    )
    assert visible == 1  # product-visible end to end


def test_bulk_ingest_job_mixed_null_acceptance_does_not_flip(db_session, monkeypatch):
    """Review test gap, missing-evidence case: a restatement whose stored doc
    LACKS the acceptance tag (bare XML) yields accepted_at NULL. With a
    non-NULL sibling restatement the pool is unrankable — the job must NOT
    flip the active pointer; it keeps the incumbent and flags the dispute."""
    from app.services.thirteenf_admin_dashboard import execute_job_payload

    mgr = _manager(db_session)
    orig, bodies_o = _job_filing(
        db_session, mgr, accession="AFAJOB0000000000010", filed=date(2026, 2, 14),
        primary_bytes=_sgml("20260214163000", period="12-31-2025"),
    )
    # Parsed FIRST (earlier filed_at): becomes the incumbent restatement.
    r_null, bodies_1 = _job_filing(
        db_session, mgr, accession="AFAJOB0000000000011", form="13F-HR/A",
        filed=date(2026, 2, 20),
        primary_bytes=_sgml(None, period="12-31-2025", form="13F-HR/A", amendment=True),
    )
    r_dated, bodies_2 = _job_filing(
        db_session, mgr, accession="AFAJOB0000000000012", form="13F-HR/A",
        filed=date(2026, 2, 25),
        primary_bytes=_sgml("20260225163000", period="12-31-2025", form="13F-HR/A", amendment=True),
    )
    bodies = {**bodies_o, **bodies_1, **bodies_2}

    monkeypatch.setattr("app.edgar.fetcher.load_body", lambda doc: bodies[doc.id])
    monkeypatch.setattr(
        "app.services.edgar_ingestion.ensure_filing_infotable_doc",
        lambda session, f: f.raw_infotable_doc,
    )

    execute_job_payload(db_session, "ingest_holdings", {"quarter": "2025-Q4"})

    db_session.refresh(r_null)
    db_session.refresh(r_dated)
    db_session.refresh(orig)
    # r_null parsed first and won while alone; once r_dated joined, the pool
    # became unrankable (mixed NULL) → NO flip, incumbent kept, both flagged.
    assert r_null.is_active_for_manager_period is True
    assert r_dated.is_active_for_manager_period is False
    assert orig.is_active_for_manager_period is False
    assert r_null.amendment_sort_warning is True
    assert r_dated.amendment_sort_warning is True


# ---------------------------------------------------------------------------
# Source guard: the single-authority contract (review writer inventory)
# ---------------------------------------------------------------------------

def test_no_active_flag_writer_outside_the_authority_module():
    """Every `is_active_for_manager_period = ...` assignment must live in
    thirteenf_filing_detail.py (the authority + its per-filing normalization).
    The admin resolve action and the controlled-reparse restore used to write
    it directly — both now converge through the authority; this guard keeps
    the contract from silently regressing."""
    import re
    from pathlib import Path

    import app.services as services_pkg

    services_dir = Path(services_pkg.__file__).parent
    pattern = re.compile(r"\.is_active_for_manager_period\s*=[^=]")
    offenders: list[str] = []
    for path in services_dir.rglob("*.py"):
        if path.name == "thirteenf_filing_detail.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "direct is_active_for_manager_period writers outside the authority:\n"
        + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Concurrency (item 4)
# ---------------------------------------------------------------------------

def test_concurrent_policy_calls_serialize_on_period_lock():
    """Two sessions racing the same (manager, period): B must block on the
    advisory xact lock while A holds it, then converge to exactly one active
    filing (the ranked winner) with no unique-constraint abort.

    Uses real committed sessions (not the rollback fixture) with full cleanup.
    """
    from app.core.db import SessionLocal
    from app.services.thirteenf_filing_detail import apply_active_filing_policy

    setup = SessionLocal()
    mgr = _manager(setup)
    mgr_id = mgr.id
    orig = _filing(setup, mgr, accepted_at=_ts(9), active=True)
    r1 = _filing(
        setup, mgr, form_type="13F-HR/A", accepted_at=_ts(11),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    r2 = _filing(
        setup, mgr, form_type="13F-HR/A", accepted_at=_ts(13),
        is_amendment=True, amendment_type="RESTATEMENT",
        amendment_status="pending_parse", parse_status="succeeded",
    )
    filing_ids = [orig.id, r1.id, r2.id]
    setup.commit()

    b_done = threading.Event()
    b_error: list[Exception] = []

    def run_b():
        s_b = SessionLocal()
        try:
            apply_active_filing_policy(s_b, mgr_id, _QEND)
            s_b.commit()
        except Exception as exc:  # pragma: no cover - failure path
            s_b.rollback()
            b_error.append(exc)
        finally:
            s_b.close()
            b_done.set()

    s_a = SessionLocal()
    try:
        # A acquires the lock inside its transaction and holds it (no commit yet).
        apply_active_filing_policy(s_a, mgr_id, _QEND)

        # P2 review hardening: prove it is the ADVISORY lock that is held —
        # not merely a row lock from A's uncommitted UPDATEs (which would also
        # block B and let this test pass vacuously). pg_try_advisory_xact_lock
        # from an independent session must fail while A holds the key.
        from sqlalchemy import text as _text

        lock_key = f"active_filing:{mgr_id}:{_QEND.isoformat()}"
        probe = SessionLocal()
        try:
            got = probe.execute(
                _text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": lock_key},
            ).scalar()
            assert got is False, "advisory period lock not actually held by A"
        finally:
            probe.rollback()
            probe.close()

        t = threading.Thread(target=run_b)
        t.start()
        # B must be blocked while A's transaction is open.
        assert not b_done.wait(timeout=1.0), "B ran while A held the period lock"

        s_a.commit()  # releases the advisory xact lock
        assert b_done.wait(timeout=10.0), "B never finished after A committed"
        t.join(timeout=10.0)
        assert not b_error, f"B raised: {b_error}"

        # With A committed and B finished, the key must be acquirable again
        # (probing before B finishes would race B's own queued acquisition).
        probe2 = SessionLocal()
        try:
            got2 = probe2.execute(
                _text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": lock_key},
            ).scalar()
            assert got2 is True, "advisory period lock leaked past commit"
        finally:
            probe2.rollback()
            probe2.close()

        verify = SessionLocal()
        try:
            rows = (
                verify.query(Filing13F)
                .filter(Filing13F.id.in_(filing_ids))
                .all()
            )
            by_id = {f.id: f for f in rows}
            active_ids = [f.id for f in rows if f.is_active_for_manager_period]
            assert active_ids == [r2.id], f"expected only r2 active, got {active_ids}"
            assert by_id[r2.id].amendment_status == "applied"
        finally:
            verify.close()
    finally:
        s_a.rollback()
        s_a.close()
        cleanup = SessionLocal()
        try:
            cleanup.query(Filing13F).filter(Filing13F.id.in_(filing_ids)).delete(
                synchronize_session=False
            )
            cleanup.query(InstitutionManager).filter(
                InstitutionManager.id == mgr_id
            ).delete(synchronize_session=False)
            cleanup.commit()
        finally:
            cleanup.close()
