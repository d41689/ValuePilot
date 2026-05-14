from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock
from app.services.thirteenf_readiness import build_readiness_summary


_CIK_COUNTER = count(9100000000)


def _clear_13f(db_session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    db_session.query(OraclesLensScoreComponent).delete()
    db_session.query(OraclesLensSignal).delete()
    db_session.query(Holding13F).delete()
    db_session.query(ParseRun13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(db_session, name: str | None = None) -> InstitutionManager:
    cik = str(next(_CIK_COUNTER))
    manager = InstitutionManager(
        canonical_name=name or f"Manager {cik}",
        legal_name=name or f"Manager {cik}",
        edgar_legal_name=name or f"Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Inc")
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    accession: str,
    *,
    quarter: str = "2026-Q1",
    quarter_end: date = date(2026, 3, 31),
    form_type: str = "13F-HR",
    parse_status: str = "succeeded",
    coverage_completeness: str = "complete",
    coverage_type: str = "normal",
    has_confidential_treatment: bool = False,
    amendment_status: str = "no_amendments_seen",
    active: bool = True,
) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=quarter_end,
        filed_at=date(2026, 5, 14),
        filing_date=date(2026, 5, 14),
        accepted_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        form_type=form_type,
        report_type="notice_report" if form_type == "13F-NT" else "holdings_report",
        coverage_completeness=coverage_completeness,
        coverage_type=coverage_type,
        quarter_end_date=quarter_end,
        report_quarter=quarter,
        official_filing_deadline=date(2026, 5, 15),
        parse_status=parse_status,
        is_active_for_manager_period=active,
        is_latest_for_period=active,
        has_confidential_treatment=has_confidential_treatment,
        confidential_treatment_status="applied" if has_confidential_treatment else "none",
        amendment_status=amendment_status,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _current_parse_run(db_session, filing: Filing13F) -> ParseRun13F:
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=0,
        is_current=True,
    )
    db_session.add(parse_run)
    db_session.flush()
    return parse_run


def _holdings(db_session, filing: Filing13F, *, total: int = 10, linked: int = 7) -> None:
    parse_run = _current_parse_run(db_session, filing)
    for index in range(total):
        stock = _stock(db_session, f"T{filing.id}{index}") if index < linked else None
        db_session.add(
            Holding13F(
                filing_id=filing.id,
                parse_run_id=parse_run.id,
                manager_id=filing.manager_id,
                accession_number=filing.accession_number,
                report_quarter=filing.report_quarter,
                quarter_end_date=filing.quarter_end_date,
                row_fingerprint=f"{filing.accession_number}-{index}",
                holding_row_fingerprint=f"{filing.accession_number}-{index}",
                cusip=f"{index:09d}",
                issuer_name=f"Issuer {index}",
                name_of_issuer=f"Issuer {index}",
                title_of_class="COM",
                value_thousands=100,
                value_raw="100000",
                value_unit_raw="dollars",
                value_parse_rule="schema_dollars",
                value_usd=100000,
                shares=100,
                ssh_prnamt=100,
                share_type="SH",
                ssh_prnamt_type="SH",
                put_call=None,
                investment_discretion="SOLE",
                holding_attribution_status="direct",
                voting_sole=100,
                voting_shared=0,
                voting_none=0,
                stock_id=stock.id if stock else None,
                cusip_mapping_status="linked" if stock else "unresolved",
                source_row_index=index,
            )
        )
    parse_run.holdings_count = total
    db_session.flush()


def _ready_fixture(db_session) -> None:
    managers = [_manager(db_session) for _ in range(5)]
    for index, manager in enumerate(managers[:4]):
        filing = _filing(db_session, manager, f"000000000{index}-26-000001")
        _holdings(db_session, filing, total=10, linked=7)
    db_session.flush()


def test_ready_when_coverage_parse_and_mapping_thresholds_are_met(db_session):
    _clear_13f(db_session)
    _ready_fixture(db_session)

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["readiness_level"] == "ready"
    assert summary["latest_usable_quarter"] == "2026-Q1"
    assert summary["metrics"]["expected_filer_count"] == 5
    assert summary["metrics"]["filed_manager_count"] == 4
    assert summary["metrics"]["manager_coverage_ratio"]["value"] == 0.8
    assert summary["metrics"]["filing_parse_success_ratio"]["value"] == 1.0
    assert summary["metrics"]["linked_common_holding_ratio"]["value"] == 0.7
    assert summary["metrics"]["coverage_ratio"]["estimated"] is False


def test_nt_manager_is_excluded_from_expected_filer_denominator(db_session):
    _clear_13f(db_session)
    hr_managers = [_manager(db_session) for _ in range(3)]
    nt_manager = _manager(db_session)
    for index, manager in enumerate(hr_managers):
        filing = _filing(db_session, manager, f"000000001{index}-26-000001")
        _holdings(db_session, filing, total=10, linked=10)
    _filing(
        db_session,
        nt_manager,
        "0000000019-26-000001",
        form_type="13F-NT",
        coverage_completeness="unknown",
        coverage_type="notice_reported_elsewhere",
    )

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["metrics"]["active_manager_count"] == 4
    assert summary["metrics"]["expected_filer_count"] == 3
    assert summary["metrics"]["nt_filer_count"] == 1
    assert summary["metrics"]["manager_coverage_ratio"]["value"] == 1.0
    assert summary["quarter_lists"]["nt_quarters"] == ["2026-Q1"]


def test_nt_detection_unsupported_caps_ready_and_marks_coverage_estimated(db_session):
    _clear_13f(db_session)
    _ready_fixture(db_session)

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20), nt_detection_supported=False)

    assert summary["readiness_level"] == "usable_with_warning"
    assert summary["nt_detection_supported"] is False
    assert summary["metrics"]["coverage_ratio"]["estimated"] is True
    assert "NT_DETECTION_UNSUPPORTED" in [warning["code"] for warning in summary["warnings"]]


def test_confidential_active_filing_caps_readiness_at_usable_with_warning(db_session):
    _clear_13f(db_session)
    _ready_fixture(db_session)
    filing = db_session.query(Filing13F).filter(Filing13F.form_type == "13F-HR").first()
    filing.has_confidential_treatment = True
    filing.confidential_treatment_status = "applied"
    db_session.flush()

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["readiness_level"] == "usable_with_warning"
    assert summary["quarter_lists"]["confidential_quarters"] == ["2026-Q1"]
    assert "CONFIDENTIAL_TREATMENT" in [warning["code"] for warning in summary["warnings"]]


def test_combination_partial_filing_caps_readiness_at_usable_with_warning(db_session):
    _clear_13f(db_session)
    _ready_fixture(db_session)
    filing = db_session.query(Filing13F).filter(Filing13F.form_type == "13F-HR").first()
    filing.report_type = "combination_report"
    filing.coverage_completeness = "partial"
    filing.coverage_type = "combination_partial"
    db_session.flush()

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["readiness_level"] == "usable_with_warning"
    assert summary["quarter_lists"]["partial_coverage_quarters"] == ["2026-Q1"]
    assert "PARTIAL_COVERAGE" in [warning["code"] for warning in summary["warnings"]]


def test_low_cusip_mapping_blocks_ready(db_session):
    _clear_13f(db_session)
    managers = [_manager(db_session) for _ in range(5)]
    for index, manager in enumerate(managers[:4]):
        filing = _filing(db_session, manager, f"000000002{index}-26-000001")
        _holdings(db_session, filing, total=10, linked=2)
    db_session.flush()

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["readiness_level"] == "experimental"
    assert summary["metrics"]["linked_common_holding_ratio"]["value"] == 0.2
    assert "CUSIP_MAPPING_BELOW_READY_THRESHOLD" in [item["code"] for item in summary["blockers"]]


def test_pending_and_failed_amendments_cap_readiness(db_session):
    _clear_13f(db_session)
    _ready_fixture(db_session)
    filings = db_session.query(Filing13F).filter(Filing13F.form_type == "13F-HR").order_by(Filing13F.id.asc()).all()
    filings[0].amendment_status = "amendments_pending"
    filings[1].amendment_status = "amendment_failed"
    db_session.flush()

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["readiness_level"] == "usable_with_warning"
    assert summary["quarter_lists"]["amendment_pending_quarters"] == ["2026-Q1"]
    assert summary["quarter_lists"]["amendment_failed_quarters"] == ["2026-Q1"]
    assert {"AMENDMENTS_PENDING", "AMENDMENT_FAILED"}.issubset({warning["code"] for warning in summary["warnings"]})


def test_no_common_holdings_returns_null_ratio_not_zero(db_session):
    _clear_13f(db_session)
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0000000030-26-000001")
    _current_parse_run(db_session, filing)

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    ratio = summary["metrics"]["linked_common_holding_ratio"]
    assert ratio["value"] is None
    assert ratio["unavailable_reason"] == "NO_ACTIVE_COMMON_HOLDINGS"
    assert ratio["value"] != 0


def test_readiness_uses_official_filing_deadline_from_active_filings(db_session):
    _clear_13f(db_session)
    _ready_fixture(db_session)
    for filing in db_session.query(Filing13F).all():
        filing.official_filing_deadline = date(2026, 5, 25)
    db_session.flush()

    summary = build_readiness_summary(db_session, today=date(2026, 5, 20))

    assert summary["readiness_level"] == "experimental"
    assert summary["latest_usable_quarter"] is None
    assert "NO_CLOSED_FILING_WINDOW" in [item["code"] for item in summary["blockers"]]
