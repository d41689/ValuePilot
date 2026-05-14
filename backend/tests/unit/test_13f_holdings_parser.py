"""13F-1B-04: HR/HR-A cover page and information table parser tests."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from itertools import count

import pytest

from app.edgar.parsers.infotable import HoldingRow, parse_infotable
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
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.services.thirteenf_holdings_ingest import (
    ingest_holdings_for_filing,
    normalize_investment_discretion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CIK_SEQ = count(9900000000)
FIXTURE_DIR = "tests/fixtures/13f/value_units"


def _clear(session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    session.query(OraclesLensScoreComponent).delete()
    session.query(OraclesLensSignal).delete()
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
        canonical_name=f"Test Manager {cik}",
        legal_name=f"Test Manager {cik}",
        edgar_legal_name=f"Test Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    session.add(m)
    session.flush()
    return m


def _hr_filing(
    session,
    manager: InstitutionManager,
    accession: str,
    *,
    accepted_at: datetime | None = None,
    form_spec_version: str | None = None,
    xml_schema_version: str | None = None,
    report_type: str = "holdings_report",
    coverage_completeness: str = "complete",
) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=date(2024, 3, 31),
        filed_at=date(2024, 5, 15),
        filing_date=date(2024, 5, 15),
        accepted_at=accepted_at or datetime(2024, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter="2024-Q1",
        quarter_end_date=date(2024, 3, 31),
        is_active_for_manager_period=True,
        parse_status="pending",
        report_type=report_type,
        coverage_completeness=coverage_completeness,
        form_spec_version=form_spec_version,
        xml_schema_version=xml_schema_version,
    )
    session.add(filing)
    session.flush()
    return filing


def _sole_holding_xml(
    *,
    cusip: str = "037833100",
    issuer: str = "APPLE INC",
    value: str = "8000000",
    shares: str = "50000",
    discretion: str = "SOLE",
    other_manager: str | None = None,
) -> str:
    other_mgr_xml = f"<otherManager>{other_manager}</otherManager>" if other_manager else ""
    return f"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>{issuer}</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>{cusip}</cusip>
    <value>{value}</value>
    <shrsOrPrnAmt>
      <sshPrnamt>{shares}</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>{discretion}</investmentDiscretion>
    {other_mgr_xml}
    <votingAuthority>
      <Sole>{shares}</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>"""


def _multi_row_infotable(rows: list[dict]) -> bytes:
    """Build a multi-row infotable XML for fingerprint/uniqueness tests."""
    entries = ""
    for r in rows:
        other_mgr = f"<otherManager>{r['other_manager']}</otherManager>" if r.get("other_manager") else ""
        entries += f"""  <infoTable>
    <nameOfIssuer>{r.get('issuer', 'TEST INC')}</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>{r.get('cusip', '037833100')}</cusip>
    <value>{r.get('value', '1000000')}</value>
    <shrsOrPrnAmt>
      <sshPrnamt>{r.get('shares', '10000')}</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>{r.get('discretion', 'SOLE')}</investmentDiscretion>
    {other_mgr}
    <votingAuthority>
      <Sole>{r.get('shares', '10000')}</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
"""
    return f"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
{entries}</informationTable>""".encode()


def _load_fixture(filename: str) -> bytes:
    with open(f"{FIXTURE_DIR}/{filename}", "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Pure unit: normalize_investment_discretion
# ---------------------------------------------------------------------------

def test_normalize_investment_discretion_sole():
    assert normalize_investment_discretion("SOLE") == "SOLE"
    assert normalize_investment_discretion("sole") == "SOLE"


def test_normalize_investment_discretion_defined_variants():
    assert normalize_investment_discretion("DEFINED") == "DFND"
    assert normalize_investment_discretion("DFND") == "DFND"
    assert normalize_investment_discretion("defined") == "DFND"
    assert normalize_investment_discretion("dfnd") == "DFND"


def test_normalize_investment_discretion_other_variants():
    assert normalize_investment_discretion("OTR") == "OTR"
    assert normalize_investment_discretion("OTHER") == "OTR"
    assert normalize_investment_discretion("SHARED") == "OTR"
    assert normalize_investment_discretion("shared") == "OTR"


def test_normalize_investment_discretion_none():
    assert normalize_investment_discretion(None) is None


# ---------------------------------------------------------------------------
# Pure unit: parse_infotable extensions
# ---------------------------------------------------------------------------

def test_parse_infotable_assigns_source_row_index():
    xml = _multi_row_infotable([
        {"cusip": "037833100", "issuer": "APPLE INC"},
        {"cusip": "594918104", "issuer": "MICROSOFT"},
        {"cusip": "02079K305", "issuer": "ALPHABET"},
    ])
    rows = parse_infotable(xml)
    assert len(rows) == 3
    assert rows[0].source_row_index == 0
    assert rows[1].source_row_index == 1
    assert rows[2].source_row_index == 2


def test_parse_infotable_captures_value_raw_str():
    xml = _sole_holding_xml(value="38217").encode()
    rows = parse_infotable(xml)
    assert rows[0].value_raw_str == "38217"


def test_parse_infotable_captures_other_managers_raw_when_present():
    xml = _sole_holding_xml(discretion="DFND", other_manager="4,5").encode()
    rows = parse_infotable(xml)
    assert rows[0].other_managers_raw == "4,5"


def test_parse_infotable_other_managers_raw_none_when_absent():
    xml = _sole_holding_xml(discretion="SOLE").encode()
    rows = parse_infotable(xml)
    assert rows[0].other_managers_raw is None


# ---------------------------------------------------------------------------
# Cover page: combination report and confidential treatment (primary_doc)
# ---------------------------------------------------------------------------

def test_combination_report_primary_doc_sets_coverage_completeness_partial(db_session):
    """Combination report cover page produces coverage_completeness=partial on filing."""
    _clear(db_session)
    from app.services.thirteenf_filing_detail import ingest_accession_filing_detail
    from tests.unit.test_13f_nt_handler import FakeEdgarClient

    manager = _manager(db_session)
    accession = "0001067983-24-000200"

    combination_primary_doc = b"""<SEC-DOCUMENT>
<SEC-HEADER>
<ACCEPTANCE-DATETIME>20240515173000
</SEC-HEADER>
<DOCUMENT>
<TYPE>13F-HR
<XML>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData>
    <submissionType>13F-HR</submissionType>
  </headerData>
  <formData>
    <coverPage>
      <periodOfReport>03-31-2024</periodOfReport>
      <reportType>13F COMBINATION REPORT</reportType>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>2</tableEntryTotal>
      <tableValueTotal>9000</tableValueTotal>
    </summaryPage>
  </formData>
</edgarSubmission>
</XML>
</DOCUMENT>
</SEC-DOCUMENT>"""

    ingest_accession_filing_detail(
        db_session,
        {
            "accession_no": accession,
            "manager_id": manager.id,
            "cik": manager.cik,
            "form_type": "13F-HR",
            "sync_date": "2024-05-16",
        },
        client=FakeEdgarClient(combination_primary_doc),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number=accession).one()
    assert filing.report_type == "combination_report"
    assert filing.coverage_completeness == "partial"


def test_confidential_treatment_is_independent_of_report_type(db_session):
    """has_confidential_treatment=True can coexist with any report type."""
    _clear(db_session)
    from app.services.thirteenf_filing_detail import ingest_accession_filing_detail
    from tests.unit.test_13f_nt_handler import FakeEdgarClient

    manager = _manager(db_session)
    accession = "0001067983-24-000201"

    confid_primary_doc = b"""<SEC-DOCUMENT>
<SEC-HEADER>
<ACCEPTANCE-DATETIME>20240515173000
</SEC-HEADER>
<DOCUMENT>
<TYPE>13F-HR
<XML>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData>
    <submissionType>13F-HR</submissionType>
  </headerData>
  <formData>
    <coverPage>
      <periodOfReport>03-31-2024</periodOfReport>
      <reportType>13F COMBINATION REPORT</reportType>
      <isConfidentialOmitted>true</isConfidentialOmitted>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>1</tableEntryTotal>
      <tableValueTotal>5000</tableValueTotal>
    </summaryPage>
  </formData>
</edgarSubmission>
</XML>
</DOCUMENT>
</SEC-DOCUMENT>"""

    ingest_accession_filing_detail(
        db_session,
        {
            "accession_no": accession,
            "manager_id": manager.id,
            "cik": manager.cik,
            "form_type": "13F-HR",
            "sync_date": "2024-05-16",
        },
        client=FakeEdgarClient(confid_primary_doc),
    )

    filing = db_session.query(Filing13F).filter_by(accession_number=accession).one()
    assert filing.coverage_completeness == "partial"
    assert filing.has_confidential_treatment is True


# ---------------------------------------------------------------------------
# cover page: other_managers_included from combination HR
# ---------------------------------------------------------------------------

def test_primary_doc_parses_other_managers_included_for_combination_report():
    """HR combination cover page with otherManager2 elements populates other_managers_included."""
    xml_body = b"""<SEC-DOCUMENT>
<SEC-HEADER>
<ACCEPTANCE-DATETIME>20240515173000
</SEC-HEADER>
<DOCUMENT>
<TYPE>13F-HR
<XML>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData>
    <submissionType>13F-HR</submissionType>
  </headerData>
  <formData>
    <coverPage>
      <periodOfReport>03-31-2024</periodOfReport>
      <reportType>13F COMBINATION REPORT</reportType>
      <otherManagers2Info>
        <otherManager2>
          <sequenceNumber>1</sequenceNumber>
          <name>SOME SUBSIDIARY LLC</name>
          <form13FFileNumber>028-11111</form13FFileNumber>
        </otherManager2>
        <otherManager2>
          <sequenceNumber>2</sequenceNumber>
          <name>ANOTHER FUND LP</name>
          <form13FFileNumber>028-22222</form13FFileNumber>
          <cik>0001234567</cik>
        </otherManager2>
      </otherManagers2Info>
    </coverPage>
  </formData>
</edgarSubmission>
</XML>
</DOCUMENT>
</SEC-DOCUMENT>"""

    summary = parse_primary_doc(xml_body)
    mgrs = summary.other_managers_included
    assert mgrs is not None and len(mgrs) == 2
    assert mgrs[0]["name"] == "SOME SUBSIDIARY LLC"
    assert mgrs[0]["file_number"] == "028-11111"
    assert "cik" not in mgrs[0]
    assert mgrs[1]["name"] == "ANOTHER FUND LP"
    assert mgrs[1]["file_number"] == "028-22222"
    assert mgrs[1]["cik"] == "0001234567"


def test_primary_doc_other_managers_included_empty_for_holdings_report():
    """Standard HR cover page without otherManager2 yields empty list."""
    xml_body = b"""<SEC-DOCUMENT>
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
    summary = parse_primary_doc(xml_body)
    assert summary.other_managers_included == []


# ---------------------------------------------------------------------------
# DB integration: value unit normalization
# ---------------------------------------------------------------------------

def test_pre_2023_infotable_value_usd_is_raw_times_1000(db_session):
    """Pre-2023 filing: value_raw=38217 (thousands) → value_usd=38217000."""
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(
        db_session,
        manager,
        "0001067983-24-000210",
        accepted_at=datetime(2022, 8, 15, 17, tzinfo=timezone.utc),
    )

    infotable = _load_fixture("2022_sio_capital_0001214659-22-013603_infotable.xml")
    result = ingest_holdings_for_filing(db_session, filing, infotable)

    assert result["holdings_count"] > 0
    assert result["value_unit_raw"] == "thousands"

    holdings = db_session.query(Holding13F).filter_by(parse_run_id=result["parse_run_id"]).all()
    for h in holdings:
        assert h.value_unit_raw == "thousands"
        assert h.value_parse_rule == "schema_thousands"
        assert h.value_usd == int(h.value_raw) * 1000


def test_post_2023_infotable_value_usd_equals_raw_value(db_session):
    """Post-2023 filing: value_raw=66075480 (dollars) → value_usd=66075480."""
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(
        db_session,
        manager,
        "0001067983-24-000211",
        accepted_at=datetime(2023, 3, 10, 17, tzinfo=timezone.utc),
    )

    infotable = _load_fixture("2023_berkshire_0000950123-23-005270_22815.xml")
    result = ingest_holdings_for_filing(db_session, filing, infotable)

    assert result["holdings_count"] > 0
    assert result["value_unit_raw"] == "dollars"

    holdings = db_session.query(Holding13F).filter_by(parse_run_id=result["parse_run_id"]).all()
    for h in holdings:
        assert h.value_unit_raw == "dollars"
        assert h.value_usd == int(h.value_raw)


# ---------------------------------------------------------------------------
# DB integration: investment_discretion normalization + attribution
# ---------------------------------------------------------------------------

def test_shared_normalizes_to_otr_attribution_shared(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000220")

    xml = _sole_holding_xml(discretion="SHARED").encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.investment_discretion == "OTR"
    assert h.holding_attribution_status == "shared"


def test_other_normalizes_to_otr_attribution_shared(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000221")

    xml = _sole_holding_xml(discretion="OTHER").encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.investment_discretion == "OTR"
    assert h.holding_attribution_status == "shared"


def test_sole_produces_direct_attribution(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000222")

    xml = _sole_holding_xml(discretion="SOLE").encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.investment_discretion == "SOLE"
    assert h.holding_attribution_status == "direct"


def test_defined_with_parseable_managers_is_reported_for_other(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000223")

    xml = _sole_holding_xml(discretion="DEFINED", other_manager="4,5").encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.investment_discretion == "DFND"
    assert h.holding_attribution_status == "reported_for_other"


def test_dfnd_with_parseable_managers_is_reported_for_other(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000224")

    xml = _sole_holding_xml(discretion="DFND", other_manager="2").encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.investment_discretion == "DFND"
    assert h.holding_attribution_status == "reported_for_other"


def test_dfnd_without_managers_is_unresolved(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000225")

    xml = _sole_holding_xml(discretion="DFND", other_manager=None).encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.investment_discretion == "DFND"
    assert h.holding_attribution_status == "unresolved"


# ---------------------------------------------------------------------------
# DB integration: holding_row_fingerprint stability and uniqueness
# ---------------------------------------------------------------------------

def test_holding_row_fingerprint_is_stable_across_filings(db_session):
    """Same raw row content in two different filings produces the same holding_row_fingerprint.

    The holding_row_fingerprint must be stable so that reparsed holdings can be
    matched across parse_runs. row_fingerprint differs between parse_runs (it
    includes parse_run_id) but holding_row_fingerprint must be identical.
    """
    _clear(db_session)
    manager1 = _manager(db_session)
    manager2 = _manager(db_session)
    filing1 = _hr_filing(db_session, manager1, "0001067983-24-000230")
    filing2 = _hr_filing(db_session, manager2, "0001067983-24-000232")

    xml = _sole_holding_xml(cusip="037833100", value="1000000", shares="50000").encode()

    result1 = ingest_holdings_for_filing(db_session, filing1, xml)
    result2 = ingest_holdings_for_filing(db_session, filing2, xml)

    h1 = db_session.query(Holding13F).filter_by(parse_run_id=result1["parse_run_id"]).first()
    h2 = db_session.query(Holding13F).filter_by(parse_run_id=result2["parse_run_id"]).first()
    assert h1 is not None and h2 is not None
    assert h1.holding_row_fingerprint == h2.holding_row_fingerprint


def test_same_raw_content_in_two_parse_runs_same_fingerprint_but_both_succeed(db_session):
    """Same row appears in two parse runs → same holding_row_fingerprint.
    (parse_run_id, holding_row_fingerprint) unique — both succeed because parse_run_id differs.
    """
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000240")

    xml = _sole_holding_xml(cusip="037833100", value="5000000", shares="30000").encode()
    r1 = ingest_holdings_for_filing(db_session, filing, xml)

    # Force is_current=False on the first run so second can become current
    run1 = db_session.get(ParseRun13F, r1["parse_run_id"])
    run1.is_current = False
    db_session.flush()

    r2 = ingest_holdings_for_filing(db_session, filing, xml)

    h1 = db_session.query(Holding13F).filter_by(parse_run_id=r1["parse_run_id"]).one()
    h2 = db_session.query(Holding13F).filter_by(parse_run_id=r2["parse_run_id"]).one()
    assert h1.holding_row_fingerprint == h2.holding_row_fingerprint
    assert h1.parse_run_id != h2.parse_run_id


def test_duplicate_fingerprint_within_same_parse_run_raises(db_session):
    """Two identical raw rows in the same filing + parse_run must violate (parse_run_id, holding_row_fingerprint)."""
    from sqlalchemy.exc import IntegrityError

    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000250")

    # Two rows that are byte-for-byte identical → same source_row_index → different fingerprints
    # To force a duplicate fingerprint we need identical source_row_index which can't happen naturally.
    # Instead, validate that the unique constraint uq_holdings_fingerprint prevents duplicate
    # (parse_run_id, holding_row_fingerprint) pairs by inserting directly.
    xml = _sole_holding_xml(cusip="037833100", value="1000000").encode()
    r = ingest_holdings_for_filing(db_session, filing, xml)
    existing = db_session.query(Holding13F).filter_by(parse_run_id=r["parse_run_id"]).one()

    with pytest.raises(IntegrityError):
        dup = Holding13F(
            filing_id=filing.id,
            parse_run_id=existing.parse_run_id,
            manager_id=manager.id,
            accession_number=filing.accession_number,
            report_quarter=filing.report_quarter,
            quarter_end_date=filing.quarter_end_date,
            row_fingerprint="unique-row-fp",
            holding_row_fingerprint=existing.holding_row_fingerprint,  # duplicate!
            cusip="037833100",
            issuer_name="APPLE INC",
            value_thousands=0,
        )
        db_session.add(dup)
        db_session.flush()


# ---------------------------------------------------------------------------
# DB integration: MVP 1B field invariants
# ---------------------------------------------------------------------------

def test_portfolio_weight_pct_is_null(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000260")

    xml = _sole_holding_xml().encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    h = db_session.query(Holding13F).filter_by(filing_id=filing.id).one()
    assert h.portfolio_weight_pct is None


def test_initial_holdings_cusip_mapping_status_is_pending_mapping(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000261")

    xml = _multi_row_infotable([
        {"cusip": "037833100", "issuer": "APPLE INC"},
        {"cusip": "594918104", "issuer": "MICROSOFT CORP"},
    ])
    ingest_holdings_for_filing(db_session, filing, xml)

    holdings = db_session.query(Holding13F).filter_by(filing_id=filing.id).all()
    assert len(holdings) == 2
    assert all(h.cusip_mapping_status == "pending_mapping" for h in holdings)


def test_ingest_creates_parse_run_with_is_current_true(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000262")

    xml = _sole_holding_xml().encode()
    result = ingest_holdings_for_filing(db_session, filing, xml)

    run = db_session.get(ParseRun13F, result["parse_run_id"])
    assert run is not None
    assert run.is_current is True
    assert run.status == "succeeded"
    assert run.holdings_count == 1


def test_ingest_returns_correct_summary_fields(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000263")

    xml = _multi_row_infotable([
        {"cusip": "037833100", "value": "1000000"},
        {"cusip": "594918104", "value": "2000000"},
    ])
    result = ingest_holdings_for_filing(db_session, filing, xml)

    assert result["holdings_count"] == 2
    assert result["parse_run_id"] is not None
    assert result["value_unit_raw"] in ("dollars", "thousands", "unknown")
    assert result["value_parse_rule"] is not None


def test_combination_report_coverage_completeness_preserved_through_ingest(db_session):
    """Filing with coverage_completeness=partial keeps that value after holdings ingest."""
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(
        db_session,
        manager,
        "0001067983-24-000264",
        report_type="combination_report",
        coverage_completeness="partial",
    )

    xml = _sole_holding_xml().encode()
    ingest_holdings_for_filing(db_session, filing, xml)

    db_session.refresh(filing)
    assert filing.coverage_completeness == "partial"
    assert filing.report_type == "combination_report"


def test_source_row_index_written_to_holding(db_session):
    _clear(db_session)
    manager = _manager(db_session)
    filing = _hr_filing(db_session, manager, "0001067983-24-000265")

    xml = _multi_row_infotable([
        {"cusip": "037833100"},
        {"cusip": "594918104"},
    ])
    ingest_holdings_for_filing(db_session, filing, xml)

    holdings = (
        db_session.query(Holding13F)
        .filter_by(filing_id=filing.id)
        .order_by(Holding13F.source_row_index)
        .all()
    )
    assert len(holdings) == 2
    assert holdings[0].source_row_index == 0
    assert holdings[1].source_row_index == 1
