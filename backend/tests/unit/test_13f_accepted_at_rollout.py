"""T1-FU accepted_at deploy gate (series-review P2 follow-up).

The first cut of this gate lived inside the runbook script's `main()` and only
inspected filings that HAD a stored primary doc — so it returned exit 0 while
`accepted_at IS NULL` rows remained, failing to prove the very condition the
deploy order depends on. These tests pin the contract:

  gate passes  ⇔  NO filing has accepted_at IS NULL.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import Filing13F, InstitutionManager, RawSourceDocument
from app.services.thirteenf_accepted_at_rollout import (
    run_accepted_at_backfill,
    verify_accepted_at_populated,
)

_SEQ = count(1)
_CIK = count(6600000000)

_QEND = date(2024, 3, 31)

# A primary doc WITH the SEC header acceptance tag (2024-05-15 16:30 ET).
_DOC_WITH_TAG = b"""<SEC-HEADER>
<ACCEPTANCE-DATETIME>20240515163000
</SEC-HEADER>
<edgarSubmission>
  <submissionType>13F-HR</submissionType>
  <periodOfReport>03-31-2024</periodOfReport>
  <formData><coverPage>
    <reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
  </coverPage></formData>
</edgarSubmission>"""

# A primary doc with NO acceptance tag (a bare primary_doc.xml).
_DOC_NO_TAG = b"""<edgarSubmission>
  <submissionType>13F-HR</submissionType>
  <periodOfReport>03-31-2024</periodOfReport>
  <formData><coverPage>
    <reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
  </coverPage></formData>
</edgarSubmission>"""


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"AAR {cik}", legal_name=f"AAR {cik}",
        edgar_legal_name=f"AAR {cik}", cik=cik,
        status="active", match_status="confirmed",
    )
    db_session.add(m)
    db_session.flush()
    return m


def _doc(db_session) -> RawSourceDocument:
    n = next(_SEQ)
    doc = RawSourceDocument(
        source_system="edgar", document_type="13f_primary",
        source_url=f"https://example.test/p-{n}.xml", body_path=f"/aar-{n}",
    )
    db_session.add(doc)
    db_session.flush()
    return doc


def _filing(
    db_session, mgr, *,
    accepted_at: datetime | None = None,
    primary_doc: RawSourceDocument | None = None,
    qend: date | None = _QEND,
) -> Filing13F:
    n = next(_SEQ)
    accession = f"AAR{n:016d}"
    f = Filing13F(
        manager_id=mgr.id, cik=mgr.cik,
        accession_no=accession, accession_number=accession,
        form_type="13F-HR",
        period_of_report=qend or date(2024, 5, 15),
        filed_at=date(2024, 5, 15), filing_date=date(2024, 5, 15),
        accepted_at=accepted_at,
        quarter_end_date=qend,
        raw_primary_doc_id=primary_doc.id if primary_doc else None,
        is_latest_for_period=False,
    )
    db_session.add(f)
    db_session.flush()
    return f


def test_gate_passes_when_every_filing_has_accepted_at(db_session):
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=datetime(2024, 5, 15, 20, 30, tzinfo=timezone.utc))

    report = verify_accepted_at_populated(db_session)

    assert report["failures"] == []
    assert report["null_total"] == 0


def test_gate_fails_on_null_filing_without_primary_doc(db_session):
    """THE regression: the old gate only looked at filings WITH a stored primary
    doc, so this row slipped through and the script exited 0 while a NULL
    remained."""
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=None, primary_doc=None)

    report = verify_accepted_at_populated(db_session)

    assert report["failures"], "gate must fail when any accepted_at is NULL"
    assert report["null_total"] == 1
    assert len(report["null_without_primary_doc"]) == 1
    assert report["null_with_primary_doc"] == []


def test_gate_fails_on_null_filing_whose_doc_lacks_acceptance_tag(db_session, monkeypatch):
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=None, primary_doc=_doc(db_session))
    monkeypatch.setattr("app.edgar.fetcher.load_body", lambda d: _DOC_NO_TAG)

    report = run_accepted_at_backfill(db_session)

    assert report["routing"]["accepted_at_filled"] == 0
    assert report["failures"]
    assert len(report["null_with_primary_doc"]) == 1
    assert report["null_without_primary_doc"] == []


def test_backfill_fills_from_stored_doc_and_gate_then_passes(db_session, monkeypatch):
    mgr = _manager(db_session)
    filing = _filing(db_session, mgr, accepted_at=None, primary_doc=_doc(db_session))
    monkeypatch.setattr("app.edgar.fetcher.load_body", lambda d: _DOC_WITH_TAG)

    report = run_accepted_at_backfill(db_session)

    # Eastern 16:30 EDT → 20:30 UTC (the T1-FU parser correction).
    assert filing.accepted_at == datetime(2024, 5, 15, 20, 30, tzinfo=timezone.utc)
    assert report["routing"]["accepted_at_filled"] == 1
    assert report["failures"] == []
    # Idempotent: a second run fills nothing and still passes.
    report2 = run_accepted_at_backfill(db_session)
    assert report2["routing"]["accepted_at_filled"] == 0
    assert report2["failures"] == []


def test_at_risk_groups_flag_only_real_competition_pools(db_session):
    """A solo NULL filing is unpopulated-but-harmless (the authority resolves it
    without ordering evidence); a NULL inside a ≥2 POOL will freeze. Both fail
    the gate, but only the latter is reported as at-risk."""
    solo_mgr = _manager(db_session)
    _filing(db_session, solo_mgr, accepted_at=None)

    pool_mgr = _manager(db_session)  # two competing originals
    _filing(db_session, pool_mgr, accepted_at=None)
    _filing(db_session, pool_mgr, accepted_at=datetime(2024, 5, 16, 20, 30, tzinfo=timezone.utc))

    report = verify_accepted_at_populated(db_session)

    assert report["null_total"] == 2
    assert report["failures"]  # both still block the gate
    at_risk = report["at_risk_groups"]
    assert len(at_risk) == 1
    assert at_risk[0]["manager_id"] == pool_mgr.id
    assert at_risk[0]["pool_kind"] == "originals"
    assert at_risk[0]["pool_size"] == 2
    assert at_risk[0]["pool_missing_accepted_at"] == 1


def test_group_of_two_with_one_member_pool_is_not_at_risk(db_session):
    """Rehearsal regression (real data, Berkshire 2025-Q1): a group holding ONE
    original plus ONE non-restatement amendment has a one-member competition
    pool — it resolves without ordering evidence and must NOT be reported as
    "will freeze". The old group_size>=2 proxy reported 16 such groups on a
    373-filing snapshot where only 2 could actually freeze."""
    mgr = _manager(db_session)
    original = _filing(db_session, mgr, accepted_at=None)
    amendment = _filing(db_session, mgr, accepted_at=None)
    amendment.form_type = "13F-HR/A"
    amendment.is_amendment = True
    amendment.amendment_type = "NEW_HOLDINGS"   # not a RESTATEMENT
    amendment.amendment_status = "amendments_pending"
    amendment.parse_status = "succeeded"
    db_session.flush()

    report = verify_accepted_at_populated(db_session)

    assert report["null_total"] == 2      # both still block the gate
    assert report["at_risk_groups"] == []  # ...but nothing will freeze
    assert original.accepted_at is None


def test_two_competing_restatements_with_null_are_at_risk(db_session):
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=datetime(2024, 5, 15, 20, 30, tzinfo=timezone.utc))
    for _ in range(2):
        r = _filing(db_session, mgr, accepted_at=None)
        r.form_type = "13F-HR/A"
        r.is_amendment = True
        r.amendment_type = "RESTATEMENT"
        r.amendment_status = "pending_parse"
        r.parse_status = "succeeded"
    db_session.flush()

    at_risk = verify_accepted_at_populated(db_session)["at_risk_groups"]

    assert len(at_risk) == 1
    assert at_risk[0]["pool_kind"] == "restatement"
    assert at_risk[0]["pool_size"] == 2


def test_admin_applied_amendment_slot_needs_no_ordering_evidence(db_session):
    """A single applied amendment needs no ordering evidence."""
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=None)
    applied = _filing(db_session, mgr, accepted_at=None)
    applied.form_type = "13F-HR/A"
    applied.is_amendment = True
    applied.amendment_type = "NEW_HOLDINGS"
    applied.amendment_status = "applied"
    applied.parse_status = "succeeded"
    db_session.flush()

    assert verify_accepted_at_populated(db_session)["at_risk_groups"] == []


def test_multiple_admin_applied_amendments_with_missing_acceptance_are_at_risk(db_session):
    mgr = _manager(db_session)
    for accepted_at in (None, datetime(2024, 5, 16, 20, 30, tzinfo=timezone.utc)):
        applied = _filing(db_session, mgr, accepted_at=accepted_at)
        applied.form_type = "13F-HR/A"
        applied.is_amendment = True
        applied.amendment_type = "NEW_HOLDINGS"
        applied.amendment_status = "applied"
        applied.parse_status = "succeeded"
    db_session.flush()

    at_risk = verify_accepted_at_populated(db_session)["at_risk_groups"]

    assert len(at_risk) == 1
    assert at_risk[0]["pool_kind"] == "amendment_owned"
    assert at_risk[0]["pool_missing_accepted_at"] == 1


def test_filing_without_quarter_end_date_fails_gate_but_is_not_at_risk(db_session):
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=None, qend=None)

    report = verify_accepted_at_populated(db_session)

    assert report["failures"]
    assert report["at_risk_groups"] == []  # belongs to no competition pool


# ---------------------------------------------------------------------------
# Drift guard: the whole point of extracting `competition_pool` was that a
# SECOND, hand-written definition of "which filings compete" silently diverged
# from the authority's (an 8x over-report on real data). Nothing structural
# stopped it then; this stops it now.
# ---------------------------------------------------------------------------

def test_pool_selection_is_defined_once_and_shared():
    """`apply_active_filing_policy` and the deploy gate must BOTH obtain their
    pool from `competition_pool`; neither may re-inline the predicates."""
    import inspect

    from app.services import thirteenf_accepted_at_rollout as gate_mod
    from app.services import thirteenf_filing_detail as authority_mod

    authority = inspect.getsource(authority_mod.apply_active_filing_policy)
    pool = inspect.getsource(authority_mod.competition_pool)
    at_risk = inspect.getsource(gate_mod._at_risk_groups)

    # Both consumers delegate.
    assert "competition_pool(" in authority, "the authority must ask competition_pool"
    assert "competition_pool(" in at_risk, "the gate diagnostic must ask competition_pool"

    # Pool-selection predicates live ONLY in competition_pool. (Markers chosen
    # so the authority's legitimate *writes* — e.g. setting a winner's status to
    # "applied", or restoring a RESTATEMENT's pre-flag status — do not trip it.)
    for marker in ('hr_originals', 'amendment_status == "applied"'):
        assert marker in pool, f"{marker!r} should define the pool"
        assert marker not in authority, (
            f"{marker!r} re-inlined in apply_active_filing_policy — pool selection "
            "has forked from competition_pool again"
        )
        assert marker not in at_risk, (
            f"{marker!r} re-inlined in the gate diagnostic — this is exactly the "
            "drift that made it over-report 16 groups when only 2 could freeze"
        )

    # The four kinds the consumers branch on are all produced here.
    for kind in ("restatement", "amendment_owned", "originals", "none"):
        assert f'"{kind}"' in pool
