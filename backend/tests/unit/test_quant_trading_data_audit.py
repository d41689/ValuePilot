from datetime import date, datetime, timedelta, timezone
import math

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import SessionLocal
from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.institutions import Filing13F, Holding13F, InstitutionManager, ParseRun13F
from app.models.stocks import Stock, StockPrice
from app.models.users import User
from app.services.quant_trading.data_audit import (
    DEFAULT_POWER_ASSUMPTIONS,
    SourceReadiness,
    begin_read_only_development_audit,
    build_audit_report,
    build_power_plans,
    collect_database_coverage,
    evaluate_hypothesis_gates,
    filing_lag_days,
    render_markdown,
    validate_audit_database_name,
)


def test_power_plan_models_target_power_not_only_expected_t() -> None:
    plans = build_power_plans(DEFAULT_POWER_ASSUMPTIONS)

    h1 = plans["H1"]
    selected = h1["selected_scenario"]

    assert h1["observation_frequency"] == "monthly"
    assert selected["tracking_error_annual"] == pytest.approx(0.04)
    assert selected["required_effective_holdout_years"] == pytest.approx(59.1, rel=0.01)
    assert selected["required_holdout_periods"] == 709
    assert selected["required_total_calendar_periods"] == 2364
    assert selected["required_total_calendar_years"] == pytest.approx(197.0)

    # Solving only E[t] = 3 would require 36 years at alpha/TE = .02/.04,
    # but would have only about a 50% chance of clearing the threshold.
    assert selected["required_effective_holdout_years"] > 36


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("annual_alpha", 0),
        ("target_power", 1),
        ("holdout_fraction", 0),
        ("t_threshold", -1),
    ],
)
def test_power_assumptions_reject_invalid_inputs(field: str, value: float) -> None:
    values = DEFAULT_POWER_ASSUMPTIONS.to_dict()
    values[field] = value

    with pytest.raises(ValueError):
        type(DEFAULT_POWER_ASSUMPTIONS)(**values)


def test_filing_lag_uses_publication_date_and_rejects_time_travel() -> None:
    assert filing_lag_days(date(2026, 3, 31), date(2026, 5, 15)) == 45

    with pytest.raises(ValueError, match="before period end"):
        filing_lag_days(date(2026, 3, 31), date(2026, 3, 30))


@pytest.mark.parametrize(
    "database_name",
    [
        "valuepilot",
        "valuepilot_test_a",
        "valuepilot_test_closing_gate_step_e_20260831",
    ],
)
def test_audit_database_guard_allows_dev_and_strict_test_database_names(
    database_name: str,
) -> None:
    assert validate_audit_database_name(database_name) == database_name


@pytest.mark.parametrize(
    "database_name",
    [
        None,
        "",
        "valuepilot_prod",
        "valuepilot_test",
        "valuepilot_test_",
        "valuepilot_test__audit",
        "valuepilot_test_audit_",
        "valuepilot_test_AUDIT",
        "valuepilot_test-audit",
        "prefix_valuepilot_test_audit",
        "valuepilot_test_audit.suffix",
        f"valuepilot_test_{'a' * 48}",
        "valuepilot_acceptance_step_d_gold_20260830",
    ],
)
def test_audit_database_guard_rejects_non_development_or_unsafe_test_database(
    database_name: str | None,
) -> None:
    with pytest.raises(RuntimeError, match="development or isolated test database"):
        validate_audit_database_name(database_name)


def test_authorized_source_state_requires_durable_evidence_reference() -> None:
    with pytest.raises(ValueError, match="backbone requires an evidence"):
        SourceReadiness(backbone_authorized=True)

    with pytest.raises(ValueError, match="Value Line automation requires an evidence"):
        SourceReadiness(value_line_automation_authorized=True)


def test_operational_audit_transaction_rejects_database_writes() -> None:
    session = SessionLocal()
    try:
        validated_database = begin_read_only_development_audit(session)
        connected_database = session.execute(text("SELECT current_database()"))
        assert validated_database == connected_database.scalar_one()
        session.add(User(email="quant-audit-read-only@example.com"))
        with pytest.raises(DBAPIError, match="read-only transaction"):
            session.flush()
    finally:
        session.rollback()
        session.close()


def _empty_coverage() -> dict:
    return {
        "metric_facts": {
            "publication_span_years": 0.0,
            "longest_consecutive_archive_weeks": 0,
            "minimum_monthly_stock_breadth": 0,
        },
        "prices": {
            "rows": 0,
            "stocks": 0,
            "span_years": 0.0,
        },
        "thirteenf": {
            "availability_span_years": 0.0,
            "quarters": 0,
            "minimum_manager_breadth": 0,
            "minimum_mapped_stock_breadth": 0,
        },
    }


def test_gate_fails_closed_without_source_evidence() -> None:
    plans = build_power_plans(DEFAULT_POWER_ASSUMPTIONS)

    result = evaluate_hypothesis_gates(
        coverage=_empty_coverage(),
        readiness=SourceReadiness(),
        power_plans=plans,
    )

    assert result["overall_1_r0_gate"] == "NO_GO"
    assert result["phase_1_follow_on_unlocked"] is False
    assert result["hypotheses"]["H1"]["status"] == "NO_GO"
    assert "backbone_authorization_missing" in result["hypotheses"]["H1"]["failed_reason_codes"]
    assert "value_line_automation_authorization_missing" in result["hypotheses"]["H2"]["failed_reason_codes"]
    assert "insufficient_13f_availability_history" in result["hypotheses"]["H3"]["failed_reason_codes"]


def test_h1_can_pass_only_with_evidenced_backbone_time_and_breadth() -> None:
    plans = build_power_plans(DEFAULT_POWER_ASSUMPTIONS)
    readiness = SourceReadiness(
        backbone_authorized=True,
        backbone_authorization_evidence_ref="contract-register:commodity-v1",
        backbone_survivorship_free=True,
        backbone_includes_delisted=True,
        backbone_has_fundamentals=True,
        backbone_has_prices=True,
        backbone_start_date=date(1800, 1, 1),
        backbone_end_date=date(2026, 7, 1),
        backbone_minimum_monthly_stock_breadth=500,
    )

    result = evaluate_hypothesis_gates(
        coverage=_empty_coverage(),
        readiness=readiness,
        power_plans=plans,
    )

    assert result["hypotheses"]["H1"]["status"] == "GO"
    assert result["overall_1_r0_gate"] == "GO"
    assert result["phase_1_follow_on_unlocked"] is True


def _manager(db_session, suffix: str) -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name=f"Audit Manager {suffix}",
        legal_name=f"Audit Manager {suffix} LLC",
        cik=f"{int(suffix):010d}",
        match_status="confirmed",
        status="active",
        manager_type="value_concentrated",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    accession: str,
    period_end: date,
    filed_at: date,
    active: bool,
) -> tuple[Filing13F, ParseRun13F]:
    accepted_at = datetime(
        filed_at.year,
        filed_at.month,
        filed_at.day,
        tzinfo=timezone.utc,
    )
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=period_end,
        filed_at=filed_at,
        filing_date=filed_at,
        accepted_at=accepted_at,
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=period_end,
        report_quarter=f"{period_end.year}-Q{math.ceil(period_end.month / 3)}",
        official_filing_deadline=filed_at,
        parse_status="succeeded",
        is_active_for_manager_period=active,
        is_latest_for_period=active,
        ingested_at=accepted_at + timedelta(minutes=30),
        updated_at=accepted_at + timedelta(minutes=30),
    )
    db_session.add(filing)
    db_session.flush()
    parse_run = ParseRun13F(
        accession_number=accession,
        parser_version="audit-test",
        status="succeeded",
        is_current=True,
        started_at=accepted_at + timedelta(hours=1),
        finished_at=accepted_at + timedelta(hours=2),
        created_at=accepted_at + timedelta(hours=1),
    )
    db_session.add(parse_run)
    db_session.flush()
    return filing, parse_run


def _holding(
    db_session,
    filing: Filing13F,
    parse_run: ParseRun13F,
    stock: Stock,
    *,
    suffix: str,
) -> Holding13F:
    created_at = (parse_run.finished_at or parse_run.created_at) + timedelta(
        minutes=1
    )
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=parse_run.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"row-{suffix}",
        holding_row_fingerprint=f"holding-{suffix}",
        cusip=f"{int(suffix):09d}",
        issuer_name=stock.company_name,
        value_thousands=100,
        value_usd=100_000,
        shares=100,
        ssh_prnamt=100,
        share_type="SH",
        ssh_prnamt_type="SH",
        stock_id=stock.id,
        cusip_mapping_status="linked",
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def _value_line_document(
    db_session,
    *,
    user: User,
    stock: Stock,
    report_date: date,
    suffix: str,
) -> PdfDocument:
    document = PdfDocument(
        user_id=user.id,
        file_name=f"vl-{suffix}.pdf",
        source="upload",
        upload_time=datetime(
            report_date.year,
            report_date.month,
            report_date.day,
            12,
            tzinfo=timezone.utc,
        ),
        report_date=report_date,
        file_storage_key=f"tests/vl-{suffix}.pdf",
        parse_status="parsed",
        raw_text="VALUE LINE TIMELINESS SAFETY RECENT PRICE 100",
        stock_id=stock.id,
    )
    db_session.add(document)
    db_session.flush()
    return document


def test_database_coverage_is_user_scoped_and_uses_authoritative_13f_rows(db_session) -> None:
    owner = User(email="quant-audit-owner@example.com")
    other = User(email="quant-audit-other@example.com")
    stocks = [
        Stock(ticker="QA1", exchange="NYSE", company_name="Quant Audit One"),
        Stock(ticker="QA2", exchange="NYSE", company_name="Quant Audit Two"),
        Stock(ticker="QA3", exchange="NYSE", company_name="Quant Audit Other"),
    ]
    db_session.add_all([owner, other, *stocks])
    db_session.flush()

    owner_docs = [
        _value_line_document(
            db_session,
            user=owner,
            stock=stocks[0],
            report_date=date(2026, 1, 5),
            suffix="1",
        ),
        _value_line_document(
            db_session,
            user=owner,
            stock=stocks[1],
            report_date=date(2026, 1, 12),
            suffix="2",
        ),
    ]
    other_doc = _value_line_document(
        db_session,
        user=other,
        stock=stocks[2],
        report_date=date(1990, 1, 1),
        suffix="3",
    )
    for index, document in enumerate([*owner_docs, other_doc], start=1):
        db_session.add(
            MetricFact(
                user_id=document.user_id,
                stock_id=document.stock_id,
                metric_key=f"per_share.audit_{index}",
                value_numeric=float(index),
                period_type="FY",
                period_end_date=date(2010 + index, 12, 31),
                source_document_id=document.id,
                source_type="parsed",
                is_current=True,
                created_at=datetime(
                    document.report_date.year,
                    document.report_date.month,
                    document.report_date.day,
                    13,
                    tzinfo=timezone.utc,
                ),
                updated_at=datetime(
                    document.report_date.year,
                    document.report_date.month,
                    document.report_date.day,
                    13,
                    tzinfo=timezone.utc,
                ),
            )
        )

    # Shared local prices are audited but never promoted to a licensed,
    # survivorship-free backbone merely because rows exist.
    db_session.add(
        StockPrice(
            stock_id=stocks[0].id,
            price_date=date(2026, 1, 5),
            open=10,
            high=11,
            low=9,
            close=10,
            adj_close=10,
            volume=100,
            source="test_fallback",
            currency="USD",
            created_at=datetime(2026, 1, 5, 22, tzinfo=timezone.utc),
        )
    )

    manager = _manager(db_session, "991")
    active_filing, active_parse = _filing(
        db_session,
        manager,
        accession="0000000991-26-000001",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        active=True,
    )
    _holding(db_session, active_filing, active_parse, stocks[0], suffix="991")
    inactive_filing, inactive_parse = _filing(
        db_session,
        manager,
        accession="0000000991-25-000002",
        period_end=date(2025, 12, 31),
        filed_at=date(2026, 2, 14),
        active=False,
    )
    _holding(db_session, inactive_filing, inactive_parse, stocks[1], suffix="992")
    db_session.flush()

    # A superseded version in the same manager/quarter is not part of today's
    # active snapshot, but it must be counted as historical PIT raw material.
    _filing(
        db_session,
        manager,
        accession="0000000991-26-000003",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 5, 1),
        active=False,
    )
    db_session.flush()

    audit_cutoff = db_session.scalar(text("SELECT clock_timestamp()"))
    coverage = collect_database_coverage(
        db_session,
        user_id=owner.id,
        knowledge_cutoff=audit_cutoff,
    )

    assert coverage["metric_facts"]["documents"] == 2
    assert coverage["metric_facts"]["parsed_fact_rows"] == 2
    assert coverage["metric_facts"]["stocks"] == 2
    assert coverage["metric_facts"]["publication_months"] == 1
    assert coverage["metric_facts"]["longest_consecutive_archive_weeks"] == 2
    assert coverage["prices"]["rows"] == 1
    assert coverage["prices"]["sources"] == {"test_fallback": 1}
    # Today's active flag is not historical authority. The standalone 2025-Q4
    # original and the later of the two 2026-Q1 originals were both observable
    # authorities at this cutoff.
    assert coverage["thirteenf"]["authoritative_filings"] == 2
    assert coverage["thirteenf"]["authoritative_holdings"] == 2
    assert coverage["thirteenf"]["mapped_holdings"] == 2
    assert coverage["thirteenf"]["filing_lag_days"]["maximum"] == 45
    assert coverage["thirteenf"]["versioned_filings"] == 3
    assert coverage["thirteenf"]["manager_quarters_with_multiple_versions"] == 1
    assert coverage["thirteenf"]["first_availability_date_start"] == "2026-02-14"
    assert coverage["thirteenf"]["mature_quarters"] == 2
    assert coverage["thirteenf"]["immature_quarters"] == 0


def test_backdated_audit_excludes_records_not_known_at_evaluation_time(db_session) -> None:
    user = User(email="quant-audit-pit@example.com")
    stock = Stock(ticker="QPIT", exchange="NYSE", company_name="Quant PIT")
    db_session.add_all([user, stock])
    db_session.flush()

    known_document = PdfDocument(
        user_id=user.id,
        file_name="known.pdf",
        source="upload",
        report_date=date(2026, 7, 1),
        file_storage_key="tests/known.pdf",
        parse_status="parsed",
        raw_text="VALUE LINE TIMELINESS SAFETY RECENT PRICE 100",
        stock_id=stock.id,
    )
    db_session.add(known_document)
    db_session.flush()
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.known_at_cutoff",
                value_numeric=1,
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_document_id=known_document.id,
                source_type="parsed",
                is_current=True,
            ),
            StockPrice(
                stock_id=stock.id,
                price_date=date.today(),
                open=10,
                high=10,
                low=10,
                close=10,
                source="known",
                currency="USD",
            ),
        ]
    )
    db_session.commit()
    cutoff = db_session.scalar(text("SELECT clock_timestamp()"))

    future_document = PdfDocument(
        user_id=user.id,
        file_name="future.pdf",
        source="upload",
        report_date=date(2026, 6, 1),
        file_storage_key="tests/future.pdf",
        parse_status="parsed",
        raw_text="VALUE LINE TIMELINESS SAFETY RECENT PRICE 100",
        stock_id=stock.id,
    )
    db_session.add(future_document)
    db_session.flush()
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.parsed_after_cutoff",
                value_numeric=2,
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_document_id=known_document.id,
                source_type="parsed",
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.future_document",
                value_numeric=3,
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_document_id=future_document.id,
                source_type="parsed",
                is_current=True,
            ),
            StockPrice(
                stock_id=stock.id,
                price_date=cutoff.date(),
                open=20,
                high=20,
                low=20,
                close=20,
                source="backfilled_after_cutoff",
                currency="USD",
                created_at=cutoff + timedelta(minutes=1),
            ),
            StockPrice(
                stock_id=stock.id,
                price_date=cutoff.date() + timedelta(days=1),
                open=30,
                high=30,
                low=30,
                close=30,
                source="future_session",
                currency="USD",
                created_at=cutoff + timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    coverage = build_audit_report(
        db_session,
        user_id=user.id,
        evaluated_at=cutoff,
        readiness=SourceReadiness(),
    )["coverage"]

    assert coverage["metric_facts"]["documents"] == 1
    assert coverage["metric_facts"]["parsed_fact_rows"] == 1
    assert coverage["metric_facts"]["metric_keys"] == 1
    assert coverage["prices"]["rows"] == 1
    assert coverage["prices"]["sources"] == {"known": 1}


def test_value_line_coverage_keeps_fact_visible_after_later_current_demotion(
    db_session,
) -> None:
    user = User(email="quant-audit-demotion-pit@example.com")
    stock = Stock(ticker="QDEM", exchange="NYSE", company_name="Quant Demotion")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _value_line_document(
        db_session,
        user=user,
        stock=stock,
        report_date=date(2026, 1, 5),
        suffix="demotion",
    )
    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="per_share.demotion_audit",
        value_numeric=1,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_document_id=document.id,
        source_type="parsed",
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()
    cutoff = db_session.execute(text("SELECT clock_timestamp()"))
    cutoff = cutoff.scalar_one()

    fact.is_current = False
    db_session.commit()

    coverage = collect_database_coverage(
        db_session,
        user_id=user.id,
        knowledge_cutoff=cutoff,
    )["metric_facts"]

    assert coverage["status"] == "available"
    assert coverage["documents"] == 1
    assert coverage["parsed_fact_rows"] == 1


def test_value_line_coverage_ignores_later_mutable_document_metadata(
    db_session,
) -> None:
    user = User(email="quant-audit-document-identity-pit@example.com")
    stock = Stock(ticker="QDOC", exchange="NYSE", company_name="Quant Document")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _value_line_document(
        db_session,
        user=user,
        stock=stock,
        report_date=date(2026, 1, 5),
        suffix="identity",
    )
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="per_share.document_identity_audit",
            value_numeric=1,
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            source_document_id=document.id,
            source_type="parsed",
            is_current=True,
        )
    )
    db_session.commit()
    cutoff = db_session.execute(text("SELECT clock_timestamp()"))
    cutoff = cutoff.scalar_one()

    document.report_date = date(2099, 1, 5)
    document.stock_id = None
    document.parse_status = "failed"
    document.raw_text = "mutated metadata no longer containing vendor markers"
    db_session.commit()

    coverage = collect_database_coverage(
        db_session,
        user_id=user.id,
        knowledge_cutoff=cutoff,
    )["metric_facts"]

    assert coverage["status"] == "available"
    assert coverage["documents"] == 1
    assert coverage["stocks"] == 1
    assert coverage["report_date_start"] == "2026-01-05"
    assert coverage["report_date_end"] == "2026-01-05"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE stock_prices SET source = 'rewritten' WHERE id = :id",
        "DELETE FROM stock_prices WHERE id = :id",
    ],
)
def test_stock_prices_reject_update_and_delete_at_database_boundary(
    db_session, statement
) -> None:
    stock = Stock(ticker="QIMM", exchange="NYSE", company_name="Quant Immutable")
    db_session.add(stock)
    db_session.flush()
    observation = StockPrice(
        stock_id=stock.id,
        price_date=date(2026, 7, 21),
        open=10,
        high=11,
        low=9,
        close=10,
        source="known",
        currency="USD",
        created_at=datetime(2026, 7, 21, 22, tzinfo=timezone.utc),
    )
    db_session.add(observation)
    db_session.flush()

    with pytest.raises(DBAPIError, match="insert-only"):
        db_session.execute(text(statement), {"id": observation.id})
        db_session.flush()


def test_database_coverage_rejects_conflicting_date_and_knowledge_cutoff(
    db_session,
) -> None:
    user = User(email="quant-audit-conflicting-cutoff@example.com")
    db_session.add(user)
    db_session.flush()

    with pytest.raises(ValueError, match="same UTC date"):
        collect_database_coverage(
            db_session,
            user_id=user.id,
            as_of_date=date(2026, 7, 20),
            knowledge_cutoff=datetime(2026, 7, 21, tzinfo=timezone.utc),
        )


def test_audit_normalizes_evaluated_at_to_one_utc_knowledge_date(db_session) -> None:
    user = User(email="quant-audit-utc-cutoff@example.com")
    db_session.add(user)
    db_session.flush()
    manager = _manager(db_session, "995")
    filing, _parse = _filing(
        db_session,
        manager,
        accession="0000000995-26-000001",
        period_end=date(2026, 6, 30),
        filed_at=date(2026, 7, 22),
        active=True,
    )
    filing.official_filing_deadline = date(2026, 8, 14)
    filing.updated_at = datetime(2026, 7, 22, 3, tzinfo=timezone.utc)
    db_session.flush()
    local_time = datetime(
        2026,
        7,
        21,
        23,
        30,
        tzinfo=timezone(timedelta(hours=-5)),
    )

    report = build_audit_report(
        db_session,
        user_id=user.id,
        evaluated_at=local_time,
        readiness=SourceReadiness(),
    )

    assert report["evaluated_at"] == "2026-07-22T04:30:00+00:00"
    assert report["coverage"]["thirteenf"]["versioned_filings"] == 1


def test_13f_audit_uses_filing_authority_known_at_cutoff(db_session) -> None:
    user = User(email="quant-audit-filing-authority@example.com")
    stock = Stock(ticker="QAUTH", exchange="NYSE", company_name="Quant Authority")
    db_session.add_all([user, stock])
    db_session.flush()
    manager = _manager(db_session, "996")
    original, original_parse = _filing(
        db_session,
        manager,
        accession="0000000996-26-000001",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        active=False,
    )
    _holding(db_session, original, original_parse, stock, suffix="996")
    amendment, _amendment_parse = _filing(
        db_session,
        manager,
        accession="0000000996-26-000002",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 8, 1),
        active=True,
    )
    amendment.form_type = "13F-HR/A"
    amendment.is_amendment = True
    amendment.amendment_type = "RESTATEMENT"
    amendment.amendment_status = "applied"
    db_session.flush()

    coverage = collect_database_coverage(
        db_session,
        user_id=user.id,
        knowledge_cutoff=datetime(2026, 7, 21, 23, tzinfo=timezone.utc),
    )["thirteenf"]

    assert coverage["authoritative_filings"] == 1
    assert coverage["authoritative_holdings"] == 1
    assert coverage["mapped_holdings"] == 1


def test_13f_audit_uses_latest_successful_parse_known_at_cutoff(db_session) -> None:
    user = User(email="quant-audit-parse-authority@example.com")
    stock = Stock(ticker="QPARSE", exchange="NYSE", company_name="Quant Parse")
    db_session.add_all([user, stock])
    db_session.flush()
    manager = _manager(db_session, "997")
    filing, original_parse = _filing(
        db_session,
        manager,
        accession="0000000997-26-000001",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        active=True,
    )
    original_holding = _holding(
        db_session,
        filing,
        original_parse,
        stock,
        suffix="997",
    )
    original_parse.is_current = False
    future_parse = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="audit-future-parse",
        status="succeeded",
        is_current=True,
        started_at=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
        finished_at=datetime(2026, 8, 1, 11, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 1, 10, tzinfo=timezone.utc),
    )
    db_session.add(future_parse)
    db_session.flush()
    _holding(db_session, filing, future_parse, stock, suffix="998")
    original_holding.stock_id = None
    original_holding.cusip_mapping_status = "pending_mapping"
    original_holding.updated_at = original_holding.created_at
    db_session.flush()
    original_holding.updated_at = original_holding.created_at
    db_session.flush()

    coverage = collect_database_coverage(
        db_session,
        user_id=user.id,
        knowledge_cutoff=datetime(2026, 7, 21, 23, tzinfo=timezone.utc),
    )["thirteenf"]

    assert coverage["authoritative_filings"] == 1
    assert coverage["authoritative_holdings"] == 1
    assert coverage["mapped_holdings"] == 0


def test_13f_audit_excludes_filing_and_mapping_mutated_after_cutoff(db_session) -> None:
    user = User(email="quant-audit-post-cutoff-mutation@example.com")
    stock = Stock(ticker="QMUT", exchange="NYSE", company_name="Quant Mutation")
    db_session.add_all([user, stock])
    db_session.flush()
    cutoff = datetime(2026, 7, 21, 23, tzinfo=timezone.utc)
    manager = _manager(db_session, "998")

    mutable_filing, mutable_parse = _filing(
        db_session,
        manager,
        accession="0000000998-26-000001",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        active=True,
    )
    _holding(db_session, mutable_filing, mutable_parse, stock, suffix="999")
    mutable_filing.updated_at = cutoff + timedelta(hours=1)

    stable_filing, stable_parse = _filing(
        db_session,
        manager,
        accession="0000000998-25-000002",
        period_end=date(2025, 12, 31),
        filed_at=date(2026, 2, 14),
        active=True,
    )
    mapped_later = _holding(
        db_session,
        stable_filing,
        stable_parse,
        stock,
        suffix="1000",
    )
    mapped_later.updated_at = cutoff + timedelta(hours=1)
    db_session.flush()

    coverage = collect_database_coverage(
        db_session,
        user_id=user.id,
        knowledge_cutoff=cutoff,
    )["thirteenf"]

    assert coverage["versioned_filings"] == 1
    assert coverage["authoritative_filings"] == 1
    assert coverage["authoritative_holdings"] == 0
    assert coverage["mapped_holdings"] == 0


def test_13f_breadth_excludes_quarters_before_official_deadline(db_session) -> None:
    user = User(email="quant-audit-maturity@example.com")
    stock = Stock(ticker="QAM", exchange="NYSE", company_name="Audit Maturity")
    db_session.add_all([user, stock])
    db_session.flush()
    manager = _manager(db_session, "992")

    mature_filing, mature_parse = _filing(
        db_session,
        manager,
        accession="0000000992-26-000001",
        period_end=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        active=True,
    )
    _holding(db_session, mature_filing, mature_parse, stock, suffix="993")
    immature_filing, immature_parse = _filing(
        db_session,
        manager,
        accession="0000000992-26-000002",
        period_end=date(2026, 6, 30),
        filed_at=date(2026, 7, 16),
        active=True,
    )
    immature_filing.official_filing_deadline = date(2026, 8, 14)
    immature_filing.updated_at = datetime(2026, 7, 16, 3, tzinfo=timezone.utc)
    _holding(db_session, immature_filing, immature_parse, stock, suffix="994")
    db_session.flush()

    coverage = collect_database_coverage(
        db_session,
        user_id=user.id,
        as_of_date=date(2026, 7, 21),
    )["thirteenf"]

    assert coverage["quarters"] == 2
    assert coverage["mature_quarters"] == 1
    assert coverage["immature_quarters"] == 1
    assert coverage["quarterly_cross_sections"][-1]["mature"] is False


def test_report_render_is_deterministic_and_explicitly_no_go(db_session) -> None:
    user = User(email="quant-audit-render@example.com")
    db_session.add(user)
    db_session.flush()

    report = build_audit_report(
        db_session,
        user_id=user.id,
        evaluated_at=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
        readiness=SourceReadiness(),
    )
    first = render_markdown(report)
    second = render_markdown(report)

    assert first == second
    assert "# Quant Trading 1-R0A Data-Sufficiency Audit" in first
    assert "Overall gate: **NO_GO**" in first
    assert "No hypothesis research or holdout evaluation is authorized" in first
    assert '"pending"' not in first.lower()
