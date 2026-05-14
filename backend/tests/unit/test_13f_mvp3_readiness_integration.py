"""MVP3-09 readiness integration tests.

SME C2 closure: the readiness service and admin quarter summary must
reflect open ``QualityFinding13F`` rows whose ``rule_code`` is one of
the two MVP3 cross-task codes
(``OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`` from
MVP3-06 and ``HISTORICAL_BACKFILL_NEEDS_VALIDATION`` from MVP3-07).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    InstitutionManagerCikReviewEvent,
    ParseRun13F,
    QualityFinding13F,
    QualityReport13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock
from app.services.thirteenf_admin_dashboard import build_quarters
from app.services.thirteenf_readiness import build_readiness_summary


_CIK_COUNTER = count(9990000000)
_QUARTER = "2026-Q1"
_QUARTER_END = date(2026, 3, 31)

CORPORATE_ACTION_RULE_CODE = "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"
HISTORICAL_BACKFILL_RULE_CODE = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"
RECOMPUTE_WARNING_CODE = "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE"
BACKFILL_WARNING_CODE = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"


def _clear_13f(db_session) -> None:
    # Pre-MVP8-01: persisted Oracle's Lens rows FK-reference
    # InstitutionManager, so they must clear first.
    db_session.query(OraclesLensScoreComponent).delete()
    db_session.query(OraclesLensSignal).delete()
    db_session.query(QualityFinding13F).delete()
    db_session.query(QualityReport13F).delete()
    db_session.query(Holding13F).delete()
    db_session.query(ParseRun13F).delete()
    db_session.query(Filing13F).delete()
    db_session.query(InstitutionManagerCikReviewEvent).delete()
    db_session.query(InstitutionManager).delete()
    db_session.flush()


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_COUNTER))
    manager = InstitutionManager(
        canonical_name=f"Readiness Mgr {cik}",
        legal_name=f"Readiness Mgr {cik}",
        edgar_legal_name=f"Readiness Mgr {cik}",
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


def _filing(db_session, manager: InstitutionManager, accession: str) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=_QUARTER_END,
        filed_at=date(2026, 5, 14),
        filing_date=date(2026, 5, 14),
        accepted_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=_QUARTER_END,
        report_quarter=_QUARTER,
        official_filing_deadline=date(2026, 5, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _holdings(db_session, filing: Filing13F, *, total: int = 10, linked: int = 7) -> None:
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=total,
        is_current=True,
    )
    db_session.add(parse_run)
    db_session.flush()
    for index in range(total):
        stock = _stock(db_session, f"R{filing.id}{index}") if index < linked else None
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
    db_session.flush()


def _ready_state(db_session) -> InstitutionManager:
    """Seed the minimum filing state for build_readiness_summary to return
    'ready' before we add any findings."""
    managers = [_manager(db_session) for _ in range(5)]
    for index, manager in enumerate(managers[:4]):
        filing = _filing(db_session, manager, f"099900000{index}-26-000001")
        _holdings(db_session, filing, total=10, linked=7)
    db_session.flush()
    return managers[0]


def _quality_report(db_session, *, status: str = "warning") -> QualityReport13F:
    report = QualityReport13F(
        quarter=_QUARTER,
        status=status,
        error_count=0,
        warning_count=0,
        info_count=0,
        summary="Test report",
        checked_at=datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(report)
    db_session.flush()
    return report


def _finding(
    db_session,
    *,
    rule_code: str,
    report: QualityReport13F,
    manager: InstitutionManager,
    quarter: str = _QUARTER,
    accession_number: str | None = None,
    status: str = "open",
) -> QualityFinding13F:
    now = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    finding = QualityFinding13F(
        validation_run_id=report.id,
        rule_code=rule_code,
        severity="warning",
        entity_type="filing" if accession_number else "ownership_change",
        entity_id=None,
        quarter=quarter,
        manager_id=manager.id,
        accession_number=accession_number,
        detail=f"Test finding for {rule_code}",
        value_json={"rule_code": rule_code},
        status=status,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(finding)
    db_session.flush()
    return finding


# ---------------------------------------------------------------------------
# Readiness summary tests
# ---------------------------------------------------------------------------


def test_open_corporate_action_finding_adds_recompute_warning(db_session):
    _clear_13f(db_session)
    manager = _ready_state(db_session)
    report = _quality_report(db_session)
    _finding(
        db_session,
        rule_code=CORPORATE_ACTION_RULE_CODE,
        report=report,
        manager=manager,
    )

    summary = build_readiness_summary(db_session, today=date(2026, 8, 1))

    warning_codes = {item["code"] for item in summary["warnings"]}
    blocker_codes = {item["code"] for item in summary["blockers"]}
    assert RECOMPUTE_WARNING_CODE in warning_codes
    assert RECOMPUTE_WARNING_CODE not in blocker_codes
    assert summary["readiness_level"] in {"usable_with_warning", "experimental"}
    assert summary["readiness_level"] != "unavailable"
    assert _QUARTER in summary["quarter_lists"]["ownership_changes_needs_recompute_quarters"]


def test_open_backfill_validation_finding_adds_validation_warning(db_session):
    _clear_13f(db_session)
    manager = _ready_state(db_session)
    report = _quality_report(db_session)
    _finding(
        db_session,
        rule_code=HISTORICAL_BACKFILL_RULE_CODE,
        report=report,
        manager=manager,
        accession_number="0999900000-26-000001",
    )

    summary = build_readiness_summary(db_session, today=date(2026, 8, 1))

    warning_codes = {item["code"] for item in summary["warnings"]}
    blocker_codes = {item["code"] for item in summary["blockers"]}
    assert BACKFILL_WARNING_CODE in warning_codes
    assert BACKFILL_WARNING_CODE not in blocker_codes
    assert summary["readiness_level"] != "unavailable"
    assert _QUARTER in summary["quarter_lists"]["historical_backfill_needs_validation_quarters"]


def test_resolved_findings_are_ignored_by_readiness(db_session):
    _clear_13f(db_session)
    manager = _ready_state(db_session)
    report = _quality_report(db_session, status="passed")
    _finding(
        db_session,
        rule_code=CORPORATE_ACTION_RULE_CODE,
        report=report,
        manager=manager,
        status="resolved",
    )
    _finding(
        db_session,
        rule_code=HISTORICAL_BACKFILL_RULE_CODE,
        report=report,
        manager=manager,
        accession_number="0999900000-26-000099",
        status="resolved",
    )

    summary = build_readiness_summary(db_session, today=date(2026, 8, 1))

    warning_codes = {item["code"] for item in summary["warnings"]}
    assert RECOMPUTE_WARNING_CODE not in warning_codes
    assert BACKFILL_WARNING_CODE not in warning_codes
    assert summary["quarter_lists"]["ownership_changes_needs_recompute_quarters"] == []
    assert summary["quarter_lists"]["historical_backfill_needs_validation_quarters"] == []
    assert summary["readiness_level"] == "ready"


def test_open_findings_never_make_quarter_unavailable(db_session):
    """Both rule_codes are warnings, never blockers. Even with many open
    findings the readiness level must not collapse to 'unavailable' on the
    basis of these findings alone.
    """
    _clear_13f(db_session)
    manager = _ready_state(db_session)
    report = _quality_report(db_session)
    for _ in range(5):
        _finding(
            db_session,
            rule_code=CORPORATE_ACTION_RULE_CODE,
            report=report,
            manager=manager,
        )
    for index in range(5):
        _finding(
            db_session,
            rule_code=HISTORICAL_BACKFILL_RULE_CODE,
            report=report,
            manager=manager,
            accession_number=f"0999900000-26-{index:06d}",
        )

    summary = build_readiness_summary(db_session, today=date(2026, 8, 1))

    blocker_codes = {item["code"] for item in summary["blockers"]}
    assert RECOMPUTE_WARNING_CODE not in blocker_codes
    assert BACKFILL_WARNING_CODE not in blocker_codes
    assert summary["readiness_level"] in {"ready", "usable_with_warning"}


# ---------------------------------------------------------------------------
# Admin dashboard tests
# ---------------------------------------------------------------------------


def test_admin_quarter_summary_reports_open_finding_counts(db_session):
    """SME C2: latest QualityReport13F.status='passed' must not mask open
    MVP3-06/07 findings. The quarter summary needs to expose the counts
    so the dashboard surfaces them independently.
    """
    _clear_13f(db_session)
    manager = _ready_state(db_session)
    passing_report = _quality_report(db_session, status="passed")
    _finding(
        db_session,
        rule_code=CORPORATE_ACTION_RULE_CODE,
        report=passing_report,
        manager=manager,
    )
    _finding(
        db_session,
        rule_code=HISTORICAL_BACKFILL_RULE_CODE,
        report=passing_report,
        manager=manager,
        accession_number="0999900000-26-000200",
    )

    quarters = build_quarters(db_session, limit=8)
    target = next(q for q in quarters if q["quarter"] == _QUARTER)

    assert target["open_recompute_finding_count"] >= 1
    assert target["open_backfill_validation_finding_count"] >= 1
    # quality_status still reflects the latest QualityReport13F — that
    # field is not what we're patching. Health is.
    assert target["quality_status"] == "passed"
    assert target["quarter_health"] == "needs_review"


def test_admin_quarter_summary_clears_finding_counts_when_resolved(db_session):
    _clear_13f(db_session)
    manager = _ready_state(db_session)
    report = _quality_report(db_session, status="passed")
    _finding(
        db_session,
        rule_code=CORPORATE_ACTION_RULE_CODE,
        report=report,
        manager=manager,
        status="resolved",
    )

    quarters = build_quarters(db_session, limit=8)
    target = next(q for q in quarters if q["quarter"] == _QUARTER)
    assert target["open_recompute_finding_count"] == 0
    assert target["open_backfill_validation_finding_count"] == 0
