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


def test_at_risk_groups_flag_only_multi_filing_periods(db_session):
    """A solo NULL filing is unpopulated-but-harmless (the authority resolves it
    without ordering evidence); a NULL inside a ≥2 group WILL freeze. Both fail
    the gate, but only the latter is reported as at-risk."""
    solo_mgr = _manager(db_session)
    _filing(db_session, solo_mgr, accepted_at=None)

    pool_mgr = _manager(db_session)
    _filing(db_session, pool_mgr, accepted_at=None)
    _filing(db_session, pool_mgr, accepted_at=datetime(2024, 5, 16, 20, 30, tzinfo=timezone.utc))

    report = verify_accepted_at_populated(db_session)

    assert report["null_total"] == 2
    assert report["failures"]  # both still block the gate
    at_risk = report["at_risk_groups"]
    assert len(at_risk) == 1
    assert at_risk[0]["manager_id"] == pool_mgr.id
    assert at_risk[0]["group_size"] == 2


def test_filing_without_quarter_end_date_fails_gate_but_is_not_at_risk(db_session):
    mgr = _manager(db_session)
    _filing(db_session, mgr, accepted_at=None, qend=None)

    report = verify_accepted_at_populated(db_session)

    assert report["failures"]
    assert report["at_risk_groups"] == []  # belongs to no competition pool
