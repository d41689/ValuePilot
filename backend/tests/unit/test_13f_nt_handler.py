"""13F-1B-03: NT header handling and holdings query contract tests."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.edgar.parsers.primary_doc import parse_primary_doc
from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    NoIndexExpectedDate,
    ParseRun13F,
    RawSourceDocument,
)
from app.services.thirteenf_filing_detail import ingest_accession_filing_detail
from app.services.thirteenf_holdings_query import (
    active_hr_holdings_query,
    nt_only_manager_ids,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CIK_SEQ = count(9800000000)


def _clear(session) -> None:
    session.query(Holding13F).delete()
    session.query(ParseRun13F).delete()
    session.query(Filing13F).delete()
    session.query(RawSourceDocument).delete()
    session.query(NoIndexExpectedDate).delete()
    session.query(InstitutionManagerCikReviewEvent).delete()
    session.query(InstitutionManager).delete()
    session.flush()


def _manager(session, *, cik: str | None = None) -> InstitutionManager:
    cik = cik or str(next(_CIK_SEQ)).zfill(10)
    m = InstitutionManager(
        canonical_name=f"NT Test Manager {cik}",
        legal_name=f"NT Test Manager {cik}",
        edgar_legal_name=f"NT Test Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    session.add(m)
    session.flush()
    return m


def _nt_submission(
    *,
    period: str | None = "03-31-2024",
    accepted: str = "20240515173000",
    managers: list[dict] | None = None,
) -> bytes:
    """Build a minimal 13F-NT EDGAR submission XML."""
    period_xml = f"<reportCalendarOrQuarter>{period}</reportCalendarOrQuarter>" if period else ""
    if managers is None:
        managers = [
            {"name": "BERKSHIRE HATHAWAY INC", "file_number": "028-00584"},
            {"name": "NATIONAL INDEMNITY CO", "file_number": "028-09999", "cik": "0001234567890"},
        ]
    other_manager_blocks = ""
    for i, mgr in enumerate(managers, 1):
        cik_xml = f"<cik>{mgr['cik']}</cik>" if "cik" in mgr else ""
        other_manager_blocks += f"""
        <otherManager>
          <sequenceNumber>{i}</sequenceNumber>
          <name>{mgr['name']}</name>
          <form13FFileNumber>{mgr['file_number']}</form13FFileNumber>
          {cik_xml}
        </otherManager>"""
    return f"""<SEC-DOCUMENT>
<SEC-HEADER>
<ACCEPTANCE-DATETIME>{accepted}
</SEC-HEADER>
<DOCUMENT>
<TYPE>13F-NT
<XML>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.sec.gov/edgar/thirteenffiler eis_13F_Filer.xsd">
  <headerData>
    <submissionType>13F-NT</submissionType>
  </headerData>
  <formData>
    <coverPage>
      {period_xml}
      <reportType>13F NOTICE</reportType>
      <otherManagersInfo>{other_manager_blocks}
      </otherManagersInfo>
    </coverPage>
  </formData>
</edgarSubmission>
</XML>
</DOCUMENT>
</SEC-DOCUMENT>""".encode()


class FakeEdgarClient:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url: str) -> bytes:
        return self.body


def _nt_payload(manager: InstitutionManager, accession: str, *, cik: str | None = None) -> dict:
    return {
        "accession_no": accession,
        "manager_id": manager.id,
        "cik": cik or manager.cik,
        "form_type": "13F-NT",
        "filename": f"edgar/data/{manager.cik.lstrip('0')}/{accession}.txt",
        "sync_date": "2024-05-16",
    }


# ---------------------------------------------------------------------------
# Pure parser unit tests (no DB)
# ---------------------------------------------------------------------------

def test_parse_other_managers_reporting_with_name_file_number_and_cik():
    body = _nt_submission(managers=[
        {"name": "BERKSHIRE HATHAWAY INC", "file_number": "028-00584"},
        {"name": "NATIONAL INDEMNITY CO", "file_number": "028-09999", "cik": "0001234567890"},
    ])
    summary = parse_primary_doc(body)
    managers = summary.other_managers_reporting
    assert managers is not None
    assert len(managers) == 2
    assert managers[0]["name"] == "BERKSHIRE HATHAWAY INC"
    assert managers[0]["file_number"] == "028-00584"
    assert "cik" not in managers[0]
    assert managers[1]["name"] == "NATIONAL INDEMNITY CO"
    assert managers[1]["file_number"] == "028-09999"
    assert managers[1]["cik"] == "0001234567890"


def test_parse_other_managers_reporting_without_cik():
    body = _nt_submission(managers=[
        {"name": "SOME MANAGER LLC", "file_number": "028-11111"},
    ])
    summary = parse_primary_doc(body)
    managers = summary.other_managers_reporting
    assert managers is not None and len(managers) == 1
    assert managers[0]["name"] == "SOME MANAGER LLC"
    assert managers[0]["file_number"] == "028-11111"
    assert "cik" not in managers[0]


def test_parse_other_managers_reporting_empty_when_section_absent():
    """HR submission has no otherManagersInfo — result should be empty list."""
    hr_body = b"""<SEC-DOCUMENT>
<SEC-HEADER><ACCEPTANCE-DATETIME>20240515173000</SEC-HEADER>
<DOCUMENT><TYPE>13F-HR
<XML>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData><submissionType>13F-HR</submissionType></headerData>
  <formData>
    <coverPage>
      <periodOfReport>03-31-2024</periodOfReport>
      <reportType>13F HOLDINGS REPORT</reportType>
    </coverPage>
  </formData>
</edgarSubmission>
</XML></DOCUMENT></SEC-DOCUMENT>"""
    summary = parse_primary_doc(hr_body)
    assert summary.other_managers_reporting == []


# ---------------------------------------------------------------------------
# NT ingest: coverage record written, no parse_run, no holdings
# ---------------------------------------------------------------------------

def test_nt_ingest_creates_coverage_record_with_correct_fields(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    accession = "0001067983-24-000030"

    result = ingest_accession_filing_detail(
        db_session,
        _nt_payload(manager, accession),
        client=FakeEdgarClient(_nt_submission()),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number=accession).one()
    assert filing.form_type == "13F-NT"
    assert filing.report_type == "notice_report"
    assert filing.coverage_type == "notice_reported_elsewhere"
    assert filing.quarter_end_date == date(2024, 3, 31)
    assert filing.report_quarter == "2024-Q1"
    assert filing.raw_primary_doc_id is not None
    assert result["status"] == "succeeded"


def test_nt_ingest_stores_other_managers_reporting_with_distinct_keys(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    accession = "0001067983-24-000031"

    ingest_accession_filing_detail(
        db_session,
        _nt_payload(manager, accession),
        client=FakeEdgarClient(_nt_submission()),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number=accession).one()
    managers = filing.other_managers_reporting
    assert managers is not None and len(managers) == 2
    # First entry: name + file_number, no cik
    first = managers[0]
    assert first["name"] == "BERKSHIRE HATHAWAY INC"
    assert first["file_number"] == "028-00584"
    assert "cik" not in first
    # Second entry: name + file_number + cik
    second = managers[1]
    assert second["name"] == "NATIONAL INDEMNITY CO"
    assert second["file_number"] == "028-09999"
    assert second["cik"] == "0001234567890"


def test_nt_ingest_creates_no_parse_run_and_no_holdings(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    accession = "0001067983-24-000032"

    ingest_accession_filing_detail(
        db_session,
        _nt_payload(manager, accession),
        client=FakeEdgarClient(_nt_submission()),
    )

    assert db_session.query(ParseRun13F).filter_by(accession_number=accession).count() == 0
    assert db_session.query(Holding13F).join(
        Filing13F, Holding13F.filing_id == Filing13F.id
    ).filter(Filing13F.accession_number == accession).count() == 0


# ---------------------------------------------------------------------------
# Holdings query guard
# ---------------------------------------------------------------------------

def _hr_filing_with_parse_run_and_holding(session, manager: InstitutionManager, accession: str) -> Holding13F:
    """Create an active HR filing, current parse_run, and one holding."""
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        filing_date=date(2024, 5, 15),
        accepted_at=datetime(2024, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter="2024-Q1",
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
        parse_status="succeeded",
    )
    session.add(filing)
    session.flush()

    run = ParseRun13F(
        accession_number=accession,
        parser_version="v1",
        fingerprint_version="v1",
        status="succeeded",
        is_current=True,
    )
    session.add(run)
    session.flush()

    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=run.id,
        manager_id=manager.id,
        accession_number=accession,
        report_quarter="2024-Q1",
        quarter_end_date=date(2024, 3, 31),
        row_fingerprint=f"fp-{accession}",
        holding_row_fingerprint=f"fp-{accession}",
        cusip="037833100",
        issuer_name="APPLE INC",
        value_thousands=8000,
    )
    session.add(holding)
    session.flush()
    return holding


def _nt_filing_only(session, manager: InstitutionManager, accession: str) -> Filing13F:
    """Create an active NT filing with no parse_run and no holdings."""
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-NT",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        filing_date=date(2024, 5, 15),
        accepted_at=datetime(2024, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter="2024-Q1",
        quarter_end_date=date(2024, 3, 31),
        report_type="notice_report",
        coverage_type="notice_reported_elsewhere",
        is_active_for_manager_period=True,
        parse_status="pending",
    )
    session.add(filing)
    session.flush()
    return filing


def test_active_hr_holdings_query_returns_hr_holdings(db_session):
    _clear(db_session)
    hr_manager = _manager(db_session)
    _hr_filing_with_parse_run_and_holding(db_session, hr_manager, "0001067983-24-000040")

    results = active_hr_holdings_query(db_session).all()
    assert len(results) == 1
    assert results[0].cusip == "037833100"


def test_active_hr_holdings_query_excludes_nt_active_filing(db_session):
    _clear(db_session)
    nt_manager = _manager(db_session)
    _nt_filing_only(db_session, nt_manager, "0001067983-24-000041")

    results = active_hr_holdings_query(db_session).all()
    assert results == []


def test_active_hr_holdings_query_excludes_nt_even_when_hr_also_present(db_session):
    _clear(db_session)
    hr_manager = _manager(db_session)
    nt_manager = _manager(db_session)
    _hr_filing_with_parse_run_and_holding(db_session, hr_manager, "0001067983-24-000042")
    _nt_filing_only(db_session, nt_manager, "0001067983-24-000043")

    results = active_hr_holdings_query(db_session).all()
    assert len(results) == 1


def test_nt_coverage_type_signals_reported_elsewhere_not_no_positions(db_session):
    """Query guard returns 0 holdings for NT; the filing record explains why (not 'no positions')."""
    _clear(db_session)
    nt_manager = _manager(db_session)
    filing = _nt_filing_only(db_session, nt_manager, "0001067983-24-000044")

    holdings = active_hr_holdings_query(db_session).all()
    assert holdings == [], "query guard returns empty — correct; do NOT interpret as 'no positions'"
    assert filing.coverage_type == "notice_reported_elsewhere", (
        "API must check coverage_type before reporting empty holdings"
    )


# ---------------------------------------------------------------------------
# Expected filers denominator: NT-only managers excluded
# ---------------------------------------------------------------------------

def test_nt_only_manager_ids_excludes_managers_with_only_nt_active_filing(db_session):
    _clear(db_session)
    hr_manager = _manager(db_session)
    nt_manager = _manager(db_session)
    _hr_filing_with_parse_run_and_holding(db_session, hr_manager, "0001067983-24-000045")
    _nt_filing_only(db_session, nt_manager, "0001067983-24-000046")

    nt_only = nt_only_manager_ids(db_session, quarter="2024-Q1")
    assert nt_manager.id in nt_only
    assert hr_manager.id not in nt_only
