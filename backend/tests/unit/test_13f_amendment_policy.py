"""13F-1B-06: Amendment Policy and Active Filing Switching tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

import pytest

from app.edgar.parsers.primary_doc import parse_primary_doc, PrimaryDocSummary
from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    ParseRun13F,
    RawSourceDocument,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.services.thirteenf_filing_detail import ingest_accession_filing_detail
from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CIK_SEQ = count(8800000000)

def _clear(session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    session.query(OraclesLensScoreComponent).delete()
    session.query(OraclesLensSignal).delete()
    session.query(Holding13F).delete()
    session.query(ParseRun13F).delete()
    session.query(Filing13F).delete()
    session.query(RawSourceDocument).delete()
    session.query(InstitutionManagerCikReviewEvent).delete()
    session.query(InstitutionManager).delete()
    session.flush()

def _manager(session, *, cik: str | None = None) -> InstitutionManager:
    cik = cik or str(next(_CIK_SEQ)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"Manager {cik}",
        legal_name=f"Manager {cik}",
        edgar_legal_name=f"Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    session.add(m)
    session.flush()
    return m

def _xml_amendment(amendment_type: str) -> bytes:
    return f"""<edgarSubmission>
  <schemaVersion>X0101</schemaVersion>
  <submissionType>13F-HR/A</submissionType>
  <testOrLive>LIVE</testOrLive>
  <periodOfReport>03-31-2024</periodOfReport>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
      <amendmentInfo>
        <amendmentType>{amendment_type}</amendmentType>
        <amendmentNo>1</amendmentNo>
      </amendmentInfo>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>1</tableEntryTotal>
      <tableValueTotal>1000</tableValueTotal>
    </summaryPage>
  </formData>
</edgarSubmission>""".encode()

# ---------------------------------------------------------------------------
# Parsing Tests
# ---------------------------------------------------------------------------

def test_parse_primary_doc_extracts_amendment_type():
    doc = _xml_amendment("RESTATEMENT")
    summary = parse_primary_doc(doc)
    assert summary.amendment_type == "RESTATEMENT"
    assert summary.is_amendment is True


# ---------------------------------------------------------------------------
# Ingestion Tests
# ---------------------------------------------------------------------------

def test_ingest_accession_original_filing_resolves_conflicts(db_session):
    from app.services.thirteenf_filing_detail import ingest_accession_filing_detail

    _clear(db_session)
    manager = _manager(db_session)
    
    # 1. First original filing
    payload1 = {
        "accession_no": "0000000000-24-000001",
        "manager_id": manager.id,
        "form_type": "13F-HR",
        "filename": "some/path.txt",
    }
    class MockClient1:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-HR</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240501120000</ACCEPTANCE-DATETIME></edgarSubmission>"
    
    res1 = ingest_accession_filing_detail(db_session, payload1, client=MockClient1())
    f1 = db_session.get(Filing13F, res1["filing_id"])
    assert f1.is_active_for_manager_period is True
    assert f1.amendment_sort_warning is False

    # 2. Second original filing for SAME quarter, later accepted_at
    payload2 = {
        "accession_no": "0000000000-24-000002",
        "manager_id": manager.id,
        "form_type": "13F-NT",
        "filename": "some/path2.txt",
    }
    class MockClient2:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-NT</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240502120000</ACCEPTANCE-DATETIME></edgarSubmission>"
    
    res2 = ingest_accession_filing_detail(db_session, payload2, client=MockClient2())
    f2 = db_session.get(Filing13F, res2["filing_id"])
    
    db_session.refresh(f1)
    
    # f2 should steal the active status
    assert f2.is_active_for_manager_period is True
    assert f1.is_active_for_manager_period is False
    assert f1.amendment_status == "superseded" or f1.amendment_status == "no_amendments_seen"

    # 3. Third original filing with SAME accepted_at as f2
    payload3 = {
        "accession_no": "0000000000-24-000003",
        "manager_id": manager.id,
        "form_type": "13F-HR",
        "filename": "some/path3.txt",
    }
    class MockClient3:
        def get(self, url, **kwargs): return b"<edgarSubmission><submissionType>13F-HR</submissionType><periodOfReport>03-31-2024</periodOfReport><ACCEPTANCE-DATETIME>20240502120000</ACCEPTANCE-DATETIME></edgarSubmission>"
    
    res3 = ingest_accession_filing_detail(db_session, payload3, client=MockClient3())
    f3 = db_session.get(Filing13F, res3["filing_id"])
    
    db_session.refresh(f2)
    
    # Due to tie, NEITHER is active, both get warnings
    assert f2.is_active_for_manager_period is False
    assert f3.is_active_for_manager_period is False
    assert f2.amendment_sort_warning is True
    assert f3.amendment_sort_warning is True
    assert f3.amendment_status == "amendments_pending"


def test_ingest_accession_marks_amendments_correctly(db_session):
    from app.services.thirteenf_filing_detail import ingest_accession_filing_detail

    _clear(db_session)
    manager = _manager(db_session)
    
    payload = {
        "accession_no": "0000000000-24-A00001",
        "manager_id": manager.id,
        "form_type": "13F-HR/A",
        "filename": "some/path.txt",
    }
    class MockClient:
        def get(self, url, **kwargs): return _xml_amendment("NEW HOLDINGS")
    
    res = ingest_accession_filing_detail(db_session, payload, client=MockClient())
    f = db_session.get(Filing13F, res["filing_id"])
    
    assert f.is_amendment is True
    assert f.amendment_type == "NEW_HOLDINGS"
    assert f.amendment_status == "amendments_pending"
    assert f.is_active_for_manager_period is False


def test_reparse_restatement_switches_active_filing(db_session):
    from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing
    
    _clear(db_session)
    manager = _manager(db_session)
    
    # Original filing
    f_orig = Filing13F(
        manager_id=manager.id,
        accession_no="ORIG",
        accession_number="ORIG",
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
    )
    db_session.add(f_orig)
    
    # Restatement amendment
    f_amend = Filing13F(
        manager_id=manager.id,
        accession_no="AMEND",
        accession_number="AMEND",
        form_type="13F-HR/A",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=False,
        is_latest_for_period=False,
        is_amendment=True,
        amendment_type="RESTATEMENT",
        amendment_status="pending_parse",
    )
    db_session.add(f_amend)
    db_session.flush()
    
    # Perform parse
    infotable = b"<informationTable xmlns='http://www.sec.gov/edgar/document/thirteenf/informationtable'><infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>037833100</cusip><value>8000000</value><shrsOrPrnAmt><sshPrnamt>50000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion><votingAuthority><Sole>50000</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable></informationTable>"
    
    ingest_holdings_for_filing(db_session, f_amend, infotable)
    
    db_session.refresh(f_orig)
    db_session.refresh(f_amend)
    
    assert f_orig.is_active_for_manager_period is False
    assert f_amend.is_active_for_manager_period is True
    assert f_amend.amendment_status == "applied"


def test_resolve_amendment_activates_as_original(db_session):
    from app.services.thirteenf_admin_dashboard import resolve_amendment
    
    _clear(db_session)
    manager = _manager(db_session)
    
    f_orig = Filing13F(
        manager_id=manager.id,
        accession_no="ORIG",
        accession_number="ORIG",
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
    )
    db_session.add(f_orig)
    
    f_amend = Filing13F(
        manager_id=manager.id,
        accession_no="AMEND",
        accession_number="AMEND",
        form_type="13F-HR/A",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 16),
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=False,
        is_latest_for_period=False,
        is_amendment=True,
        amendment_type="NEW_HOLDINGS",
        amendment_status="amendments_pending",
    )
    db_session.add(f_amend)
    db_session.flush()
    
    res = resolve_amendment(db_session, "AMEND", "activate_as_original", "Looks good")
    
    db_session.refresh(f_orig)
    db_session.refresh(f_amend)
    
    assert f_orig.is_active_for_manager_period is False
    assert f_amend.is_active_for_manager_period is True
    assert f_amend.amendment_status == "applied"
    assert "Looks good" in f_amend.parse_warning
