from __future__ import annotations

from datetime import date

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    NoIndexExpectedDate,
    RawSourceDocument,
)
from app.services.thirteenf_filing_detail import (
    calculate_official_filing_deadline,
    ingest_accession_filing_detail,
)


class FakeEdgarClient:
    def __init__(self, body: bytes):
        self.body = body
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        return self.body


def _clear_13f(db_session) -> None:
    db_session.query(Holding13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(RawSourceDocument).delete()
    db_session.query(NoIndexExpectedDate).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(db_session, *, cik: str = "0001067983") -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name="Tracked Manager",
        legal_name="Tracked Manager",
        edgar_legal_name="Tracked Manager",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.commit()
    db_session.refresh(manager)
    return manager


def _submission(
    *,
    period: str | None = "03-31-2024",
    accepted: str = "20240515173000",
    form_type: str = "13F-HR",
    report_type: str = "13F HOLDINGS REPORT",
    form_spec_version: str = "2023",
    schema_location: str = "http://www.sec.gov/edgar/thirteenffiler eis_13F_Filer.xsd",
) -> bytes:
    period_xml = f"<periodOfReport>{period}</periodOfReport>" if period is not None else ""
    return f"""<SEC-DOCUMENT>
<SEC-HEADER>
<ACCEPTANCE-DATETIME>{accepted}
</SEC-HEADER>
<DOCUMENT>
<TYPE>{form_type}
<XML>
<edgarSubmission
  xmlns="http://www.sec.gov/edgar/thirteenffiler"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="{schema_location}">
  <headerData>
    <submissionType>{form_type}</submissionType>
  </headerData>
  <formData>
    <coverPage>
      {period_xml}
      <reportType>{report_type}</reportType>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>7</tableEntryTotal>
      <tableValueTotal>123456</tableValueTotal>
      <isConfidentialOmitted>false</isConfidentialOmitted>
    </summaryPage>
    <formSpecVersion>{form_spec_version}</formSpecVersion>
  </formData>
</edgarSubmission>
</XML>
</DOCUMENT>
</SEC-DOCUMENT>""".encode()


def _payload(manager: InstitutionManager, accession: str = "0001067983-24-000006", *, form_type: str = "13F-HR") -> dict:
    return {
        "accession_no": accession,
        "manager_id": manager.id,
        "cik": manager.cik,
        "form_type": form_type,
        "filename": f"edgar/data/1067983/{accession}.txt",
        "sync_date": "2024-05-16",
    }


def test_ingest_accession_detail_routes_by_period_not_sync_date_and_persists_metadata(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager),
        client=FakeEdgarClient(_submission(period="03-31-2024", accepted="20240515173000")),
    )

    assert result["status"] == "succeeded"
    assert result["report_quarter"] == "2024-Q1"
    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000006").one()
    assert filing.accession_no == "0001067983-24-000006"
    assert filing.cik == "0001067983"
    assert filing.form_type == "13F-HR"
    assert filing.period_of_report == date(2024, 3, 31)
    assert filing.quarter_end_date == date(2024, 3, 31)
    assert filing.report_quarter == "2024-Q1"
    assert filing.filing_date == date(2024, 5, 15)
    assert filing.accepted_at.date() == date(2024, 5, 15)
    assert filing.official_filing_deadline == date(2024, 5, 15)
    assert filing.parse_status == "pending"
    assert filing.raw_filing_url == "https://www.sec.gov/Archives/edgar/data/1067983/0001067983-24-000006.txt"
    assert filing.raw_primary_doc_id is not None
    assert filing.raw_infotable_doc_id is None
    assert filing.form_spec_version == "2023"
    assert "thirteenffiler" in filing.xml_schema_version
    assert filing.report_type == "holdings_report"
    assert filing.coverage_completeness == "complete"
    assert filing.coverage_type == "normal"
    assert filing.reported_total_value_thousands == 123456
    assert filing.holdings_count == 7


def test_ingest_accession_detail_is_idempotent_by_accession_number(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    payload = _payload(manager, "0001067983-24-000007")
    client = FakeEdgarClient(_submission(period="03-31-2024"))

    first = ingest_accession_filing_detail(db_session, payload, client=client)
    second = ingest_accession_filing_detail(db_session, payload, client=FakeEdgarClient(_submission(period="03-31-2024")))

    assert first["filing_id"] == second["filing_id"]
    assert db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000007").count() == 1


def test_hr_period_one_day_from_quarter_end_normalizes_inside_valid_window(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-24-000008"),
        client=FakeEdgarClient(_submission(period="03-30-2024", accepted="20240515173000")),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000008").one()
    assert result["status"] == "succeeded"
    assert filing.period_of_report == date(2024, 3, 31)
    assert filing.quarter_end_date == date(2024, 3, 31)
    assert filing.report_quarter == "2024-Q1"
    assert filing.parse_warning == "PERIOD_WEEKEND_ADJUSTED"


def test_hr_period_one_day_from_quarter_end_outside_window_needs_review(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-24-000012"),
        client=FakeEdgarClient(_submission(period="03-30-2024", accepted="20240330173000")),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000012").one()
    assert result["status"] == "needs_review"
    assert filing.parse_status == "needs_review"
    assert filing.parse_warning == "PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE"
    assert filing.quarter_end_date is None
    assert filing.report_quarter is None


def test_nt_period_one_day_from_quarter_end_needs_review_not_auto_normalized(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-24-000009", form_type="13F-NT"),
        client=FakeEdgarClient(_submission(period="03-30-2024", form_type="13F-NT", report_type="13F NOTICE")),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000009").one()
    assert result["status"] == "needs_review"
    assert filing.parse_status == "needs_review"
    assert filing.parse_warning == "PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE"
    assert filing.quarter_end_date is None
    assert filing.report_quarter is None
    assert filing.coverage_type == "notice_reported_elsewhere"


def test_period_three_days_from_quarter_end_needs_review(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-24-000013"),
        client=FakeEdgarClient(_submission(period="03-28-2024", accepted="20240515173000")),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000013").one()
    assert result["status"] == "needs_review"
    assert filing.parse_status == "needs_review"
    assert filing.parse_warning == "PERIOD_TOO_FAR_FROM_QUARTER_END"
    assert filing.quarter_end_date is None
    assert filing.report_quarter is None


def test_period_suspiciously_stale_needs_review(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-25-000014"),
        client=FakeEdgarClient(_submission(period="03-31-2024", accepted="20250415173000")),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-25-000014").one()
    assert result["status"] == "needs_review"
    assert filing.parse_status == "needs_review"
    assert filing.parse_warning == "PERIOD_SUSPICIOUSLY_STALE"
    assert filing.quarter_end_date == date(2024, 3, 31)
    assert filing.report_quarter == "2024-Q1"


def test_missing_period_persists_raw_doc_and_marks_needs_review_without_quarter(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-24-000010"),
        client=FakeEdgarClient(_submission(period=None)),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000010").one()
    assert result["status"] == "needs_review"
    assert filing.parse_status == "needs_review"
    assert filing.parse_warning == "PERIOD_MISSING"
    assert filing.quarter_end_date is None
    assert filing.report_quarter is None
    assert filing.raw_primary_doc_id is not None


def test_invalid_period_marks_failed_without_quarter(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)

    result = ingest_accession_filing_detail(
        db_session,
        _payload(manager, "0001067983-24-000011"),
        client=FakeEdgarClient(_submission(period="2024/03/31")),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number="0001067983-24-000011").one()
    assert result["status"] == "failed"
    assert filing.parse_status == "failed"
    assert filing.parse_error == "PERIOD_INVALID"
    assert filing.quarter_end_date is None
    assert filing.report_quarter is None


def test_official_filing_deadline_adjusts_weekend_and_expected_no_index_dates(db_session):
    _clear_13f(db_session)
    db_session.add(
        NoIndexExpectedDate(
            date=date(2026, 2, 16),
            reason="federal_holiday",
            holiday_name="Presidents Day",
            source="auto_generated",
        )
    )
    db_session.flush()

    assert calculate_official_filing_deadline(db_session, date(2025, 12, 31)) == date(2026, 2, 17)
