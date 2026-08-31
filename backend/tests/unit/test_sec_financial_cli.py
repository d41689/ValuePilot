from datetime import date, datetime, timedelta, timezone
import json
import uuid
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from app.cli import sec_financials as financial_cli
from app.cli.sec_financials import (
    _bootstrap_gold_case_stocks,
    _gold_case,
    _history_target_for_case,
    _resolve_gold_case_stock,
)
from app.models.sec_financials import SecFinancialFiling
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import (
    FinancialFilingSelection,
    FinancialIngestionReport,
    SecFinancialEvidenceAsOf,
    SecFinancialEvidenceFailureAsOf,
    register_reviewed_sec_identity,
)


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
BRKB_CASE = {
    "case_id": "brkb-primary",
    "company_name": "Berkshire Hathaway Inc.",
    "cik": "0001067983",
    "primary_listing": {
        "ticker": "BRK-B",
        "mic": "XNYS",
        "country": "US",
        "instrument_type": "common_stock",
        "share_class": "class_b",
    },
}


def _write_acceptance_pass_reports(
    reports_root,
    *,
    run_id: str = "step-d-resume-test",
    acceptance_pass: int = 2,
) -> list[dict]:
    manifest = financial_cli.yaml.safe_load(
        financial_cli.MANIFEST_PATH.read_text(encoding="utf-8")
    )
    destination = reports_root / f"pass-{acceptance_pass}"
    destination.mkdir(parents=True)
    for stock_id, case in enumerate(manifest["cases"], start=1):
        case_id = str(case["case_id"])
        payload = {
            "schema_version": 1,
            "acceptance_pass": acceptance_pass,
            "run_id": run_id,
            "case_id": case_id,
            "cik": str(case["cik"]),
            "stock_id": stock_id,
            "operation_id": str(uuid.uuid4()),
            "typed_gaps": (
                ["annual_coverage_gap:2022,2021"]
                if case_id == "jpm-primary"
                else []
            ),
            "typed_failures": (
                ["history_scan_limit_exceeded"]
                if case_id == "gs-primary"
                else []
            ),
        }
        (destination / f"{case_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return manifest["cases"]


def _stub_acceptance_report_database_audit(monkeypatch, *, validator=None):
    session = SimpleNamespace(
        execute=lambda *_args, **_kwargs: None,
        rollback=lambda: None,
        close=lambda: None,
    )
    audited: list[str] = []

    def audit(db, *, case, report, **_kwargs):
        assert db is session
        if validator is not None:
            validator(case, report)
        audited.append(str(case["case_id"]))
        return {"operation_id": report["operation_id"]}

    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli, "audit_case_report_operation", audit)
    return audited


def _stock(
    db_session,
    *,
    ticker: str,
    company_name: str = "Berkshire Hathaway Inc",
    listing_exchange: str | None = "NYSE",
    raw_exchange: str | None = None,
    exchange: str | None = None,
    is_active: bool = True,
) -> Stock:
    raw_exchange = listing_exchange if raw_exchange is None else raw_exchange
    exchange = listing_exchange or "US" if exchange is None else exchange
    stock = Stock(
        ticker=ticker,
        exchange=exchange,
        market_country="US",
        listing_exchange=listing_exchange,
        raw_exchange=raw_exchange,
        company_name=company_name,
        is_active=is_active,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def test_gold_case_resolves_by_reviewed_cik_before_ticker_alias(db_session) -> None:
    reviewed_stock = _stock(db_session, ticker="BRK/B")
    _stock(db_session, ticker="BRK-B")
    register_reviewed_sec_identity(
        db_session,
        stock_id=reviewed_stock.id,
        cik=BRKB_CASE["cik"],
        effective_from=date(2015, 1, 1),
        known_at=NOW,
        review_reason="Locked gold-case identity review.",
    )

    resolution = _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)

    assert resolution.stock.id == reviewed_stock.id
    assert resolution.source == "reviewed_cik"
    assert resolution.manifest_ticker == "BRK-B"


def test_locked_gold_case_builds_ten_year_history_target_at_cycle_cutoff() -> None:
    locked = _gold_case("aapl-primary")

    target = _history_target_for_case(
        locked.case, filing_selection_as_of=locked.cutoff_at
    )

    assert locked.cutoff_at == datetime(
        2026, 8, 26, 23, 59, 59, tzinfo=timezone.utc
    )
    assert target.filing_regime == "us_10k_10q"
    assert target.fiscal_year_end_mmdd == "0926"
    assert target.available_start_on == date(2015, 1, 1)
    assert target.completed_fiscal_year_cap == 10
    assert target.filing_selection_as_of == locked.cutoff_at


def test_acceptance_bootstrap_stocks_is_locked_and_idempotent(db_session) -> None:
    manifest = {
        "cases": [
            BRKB_CASE,
            {
                "case_id": "aapl-primary",
                "company_name": "Apple Inc.",
                "cik": "0000320193",
                "primary_listing": {
                    "ticker": "AAPL",
                    "mic": "XNAS",
                    "country": "US",
                    "instrument_type": "common_stock",
                    "share_class": "common",
                },
            },
        ]
    }

    assert _bootstrap_gold_case_stocks(db_session, manifest) == 2
    assert _bootstrap_gold_case_stocks(db_session, manifest) == 0
    rows = db_session.query(Stock).order_by(Stock.ticker).all()
    assert [(row.ticker, row.listing_exchange) for row in rows] == [
        ("AAPL", "XNAS"),
        ("BRK-B", "XNYS"),
    ]


@pytest.mark.parametrize(
    ("arguments", "selection_as_of", "expected_years"),
    [
        (
            ["ingest-gold-case", "--case-id", "aapl-primary"],
            "2026-08-26T23:59:59+00:00",
            "2025,2024,2023,2022,2021,2020,2019,2018,2017,2016",
        ),
        (
            [
                "ingest-gold-case",
                "--case-id",
                "aapl-primary",
                "--as-of",
                "2025-08-26T23:59:59Z",
            ],
            "2025-08-26T23:59:59+00:00",
            "2024,2023,2022,2021,2020,2019,2018,2017,2016,2015",
        ),
    ],
)
def test_ingest_gold_case_prints_stable_selection_and_pit_semantics(
    monkeypatch,
    arguments: list[str],
    selection_as_of: str,
    expected_years: str,
) -> None:
    evidence_known_at = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    stock = SimpleNamespace(id=77, ticker="AAPL")
    session = _SessionStub()
    captured: dict = {}
    monkeypatch.setattr(financial_cli, "_utc_now", lambda: evidence_known_at)
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        financial_cli,
        "_resolve_gold_case_stock",
        lambda db, case, at: SimpleNamespace(
            stock=stock,
            source="reviewed_cik",
            manifest_ticker="AAPL",
        ),
    )
    monkeypatch.setattr(financial_cli, "EdgarClient", _EdgarStub)
    monkeypatch.setattr(
        financial_cli,
        "finalize_pending_sec_financial_ingestion_operations",
        lambda db, stock_id: (),
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: evidence_known_at,
    )
    monkeypatch.setattr(
        financial_cli,
        "finalize_sec_financial_ingestion_operation",
        lambda db, operation_id: evidence_known_at,
    )

    def fake_ingest(*args, **kwargs):
        captured.update(kwargs)
        return FinancialIngestionReport(
            operation_id="11111111-1111-4111-8111-111111111111",
            stock_id=stock.id,
            cik="0000320193",
            filings_discovered=10,
            filings_created=10,
            artifacts_created=10,
            parse_runs_created=10,
            raw_facts_created=10,
            failures=(),
            selected_filings=(
                FinancialFilingSelection(
                    accession_no="0000320193-26-000079",
                    form_type="10-Q",
                    accepted_at=datetime(
                        2026, 7, 31, 20, 5, 28, tzinfo=timezone.utc
                    ),
                ),
            ),
        )

    monkeypatch.setattr(financial_cli, "ingest_latest_financial_filings", fake_ingest)

    result = CliRunner().invoke(financial_cli.app, arguments)

    assert result.exit_code == 0, result.output
    assert (
        f"filing_selection_as_of={selection_as_of} regime=us_10k_10q "
        f"fiscal_year_end_mmdd=0926 available_start_on=2015-01-01 "
        f"expected_completed_fiscal_years={expected_years} "
        "expected_completed_fiscal_year_count=10"
    ) in result.output
    assert (
        "ingestion_attempted_at=2026-08-30T12:00:00+00:00"
    ) in result.output
    assert "operation_attempted_at=2026-08-30T12:00:00+00:00" in result.output
    assert "selected_forms=10-Q selected_filing_count=1" in result.output
    assert (
        "earliest_replayable_evidence_at=2026-08-30T12:00:00+00:00 "
        "pit_replay_before_earliest_evidence=unavailable"
    ) in result.output
    assert captured["filing_selection_as_of"].isoformat() == selection_as_of
    assert captured["history_target"].filing_selection_as_of.isoformat() == selection_as_of


def test_ingest_gold_case_finalizes_terminal_acquisition_failure_before_exit(
    monkeypatch,
) -> None:
    stock = SimpleNamespace(id=77, ticker="AAPL")
    session = _SessionStub()
    finalized: list[str] = []
    operation_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setattr(financial_cli, "_utc_now", lambda: NOW)
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        financial_cli,
        "_resolve_gold_case_stock",
        lambda db, case, at: SimpleNamespace(
            stock=stock,
            source="reviewed_cik",
            manifest_ticker="AAPL",
        ),
    )
    monkeypatch.setattr(financial_cli, "EdgarClient", _EdgarStub)
    monkeypatch.setattr(
        financial_cli,
        "finalize_pending_sec_financial_ingestion_operations",
        lambda db, stock_id: (),
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: NOW,
    )

    def fake_finalize(db, *, operation_id: str):
        finalized.append(operation_id)
        return NOW

    monkeypatch.setattr(
        financial_cli,
        "finalize_sec_financial_ingestion_operation",
        fake_finalize,
    )
    monkeypatch.setattr(
        financial_cli,
        "ingest_latest_financial_filings",
        lambda *args, **kwargs: FinancialIngestionReport(
            operation_id=operation_id,
            stock_id=stock.id,
            cik="0000320193",
            filings_discovered=0,
            filings_created=0,
            artifacts_created=0,
            parse_runs_created=0,
            raw_facts_created=0,
            failures=("main_submissions:sec_temporarily_unavailable",),
        ),
    )

    result = CliRunner().invoke(
        financial_cli.app,
        ["ingest-gold-case", "--case-id", "aapl-primary"],
    )

    assert result.exit_code == 2, result.output
    assert finalized == [operation_id]
    assert session.commit_count == 2
    assert f"lineage_operation_id={operation_id} lineage_availability=pending" in result.output
    assert f"lineage_operation_id={operation_id} lineage_available_at=" in result.output
    assert "failure=main_submissions:sec_temporarily_unavailable" in result.output


@pytest.mark.parametrize("acceptance_pass", (1, 2))
def test_ingest_gold_case_writes_stable_acceptance_report(
    monkeypatch,
    tmp_path,
    acceptance_pass: int,
) -> None:
    stock = SimpleNamespace(id=77, ticker="AAPL")
    session = _SessionStub()
    operation_id = "11111111-1111-4111-8111-111111111111"
    report_path = (
        tmp_path / "reports" / f"pass-{acceptance_pass}" / "aapl-primary.json"
    )
    monkeypatch.setattr(financial_cli, "_utc_now", lambda: NOW)
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        financial_cli,
        "_resolve_gold_case_stock",
        lambda db, case, at: SimpleNamespace(
            stock=stock,
            source="reviewed_cik",
            manifest_ticker="AAPL",
        ),
    )
    monkeypatch.setattr(financial_cli, "EdgarClient", _EdgarStub)
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda run_id: SimpleNamespace(reports_root=tmp_path / "reports"),
    )
    monkeypatch.setattr(
        financial_cli,
        "finalize_pending_sec_financial_ingestion_operations",
        lambda db, stock_id: (),
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: NOW,
    )
    monkeypatch.setattr(
        financial_cli,
        "finalize_sec_financial_ingestion_operation",
        lambda db, operation_id: NOW + timedelta(seconds=2),
    )
    monkeypatch.setattr(
        financial_cli,
        "ingest_latest_financial_filings",
        lambda *args, **kwargs: FinancialIngestionReport(
            operation_id=operation_id,
            stock_id=stock.id,
            cik="0000320193",
            filings_discovered=1,
            filings_created=1,
            artifacts_created=3,
            parse_runs_created=1,
            raw_facts_created=3,
            failures=("annual_coverage_gap:2016",),
            selected_filings=(
                FinancialFilingSelection(
                    accession_no="0000320193-26-000079",
                    form_type="10-Q",
                    accepted_at=datetime(
                        2026, 7, 31, 20, 5, 28, tzinfo=timezone.utc
                    ),
                ),
            ),
        ),
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "ingest-gold-case",
            "--case-id",
            "aapl-primary",
            "--acceptance-run-id",
            "step-c-fake",
            "--acceptance-pass",
            str(acceptance_pass),
            "--report-json",
            str(report_path),
        ],
    )

    assert result.exit_code == 2, result.output
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "step-c-fake"
    assert payload["acceptance_pass"] == acceptance_pass
    assert payload["filing_selection_as_of"] == "2026-08-26T23:59:59+00:00"
    assert payload["operation_attempted_at"] == "2026-08-30T12:00:00+00:00"
    assert payload["evidence_available_at"] == "2026-08-30T12:00:02+00:00"
    assert payload["selected_forms"] == ["10-Q"]
    assert payload["typed_gaps"] == ["annual_coverage_gap:2016"]
    assert payload["typed_failures"] == []
    assert payload["metric_facts_published"] == 0
    assert "typed_gap=annual_coverage_gap:2016" in result.output
    assert f"acceptance_report_json={report_path}" in result.output


@pytest.mark.parametrize(
    "preflight_error",
    (
        "acceptance mode is required",
        "configured database is not the derived acceptance database",
        "acceptance storage is not the derived storage root",
        "acceptance storage must not use symlinks",
    ),
)
def test_ingest_gold_case_acceptance_preflight_fails_before_session_or_report(
    monkeypatch,
    tmp_path,
    preflight_error: str,
) -> None:
    report_path = tmp_path / "reports" / "aapl-primary.json"
    session_started = False

    def fail_session():
        nonlocal session_started
        session_started = True
        raise AssertionError("SessionLocal must not run after preflight failure")

    def fail_preflight(*args, **kwargs):
        raise ValueError(preflight_error)

    monkeypatch.setattr(financial_cli, "SessionLocal", fail_session)
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        fail_preflight,
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "ingest-gold-case",
            "--case-id",
            "aapl-primary",
            "--acceptance-run-id",
            "step-c-fake",
            "--report-json",
            str(report_path),
        ],
    )

    assert result.exit_code == 1
    assert f"acceptance preflight failed: {preflight_error}" in result.output
    assert session_started is False
    assert not report_path.exists()


def test_ingest_gold_case_acceptance_options_reject_standard_api_environment(
    monkeypatch,
    tmp_path,
) -> None:
    report_path = tmp_path / "reports" / "aapl-primary.json"
    session_started = False

    def fail_session():
        nonlocal session_started
        session_started = True
        raise AssertionError("standard API must not open an acceptance session")

    monkeypatch.setattr(financial_cli, "SessionLocal", fail_session)
    monkeypatch.setattr(
        financial_cli.settings,
        "SQLALCHEMY_DATABASE_URI",
        "postgresql://valuepilot:valuepilot@postgres:5432/valuepilot",
    )
    monkeypatch.setattr(financial_cli.settings, "VALUEPILOT_ACCEPTANCE_MODE", False)
    monkeypatch.setattr(
        financial_cli.settings, "VALUEPILOT_ACCEPTANCE_RUN_ID", None
    )
    monkeypatch.setattr(
        financial_cli.settings, "VALUEPILOT_ACCEPTANCE_DATABASE", None
    )
    monkeypatch.setattr(
        financial_cli.settings, "VALUEPILOT_ACCEPTANCE_STORAGE", None
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "ingest-gold-case",
            "--case-id",
            "aapl-primary",
            "--acceptance-run-id",
            "step-c-fake",
            "--report-json",
            str(report_path),
        ],
    )

    assert result.exit_code == 1
    assert "acceptance preflight failed: explicit acceptance mode is required" in (
        result.output
    )
    assert session_started is False
    assert not report_path.exists()


def test_replay_before_acquired_evidence_known_at_is_typed_nonzero(
    db_session,
    monkeypatch,
) -> None:
    selection_cutoff = datetime(2026, 8, 26, 23, 59, 59, tzinfo=timezone.utc)
    evidence_known_at = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    stock = _stock(
        db_session,
        ticker="PIT",
        company_name="PIT Fixture Inc.",
    )
    identity = register_reviewed_sec_identity(
        db_session,
        stock_id=stock.id,
        cik="0000000099",
        effective_from=date(2015, 1, 1),
        known_at=evidence_known_at,
        review_reason="PIT fixture identity.",
    )
    db_session.add(
        SecFinancialFiling(
            issuer_identity_id=identity.id,
            accession_no="0000000099-25-000001",
            form_type="10-K",
            is_amendment=False,
            filed_on=date(2026, 2, 15),
            report_date=date(2025, 12, 31),
            accepted_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
            known_at=evidence_known_at,
            primary_document="pit.htm",
            index_url="https://www.sec.gov/pit/index.json",
            source_url="https://www.sec.gov/pit/pit.htm",
            submissions_source_url=(
                "https://data.sec.gov/submissions/CIK0000000099.json"
            ),
            discovery_payload_sha256="a" * 64,
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        financial_cli,
        "SessionLocal",
        lambda: _SessionProxy(db_session),
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: evidence_known_at,
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "PIT",
            "--cutoff",
            selection_cutoff.isoformat(),
        ],
    )

    assert result.exit_code == 2
    assert "failure=pit_evidence_unavailable" in result.output
    assert (
        "earliest_replayable_evidence_at=2026-08-30T12:00:00+00:00"
        in result.output
    )


@pytest.mark.parametrize(
    "error_code",
    ["required_artifact_unavailable", "no_inline_xbrl_facts"],
)
def test_replay_surfaces_terminal_failed_parse_as_typed_nonzero(
    monkeypatch,
    error_code: str,
) -> None:
    stock = SimpleNamespace(id=77, ticker="FAILED")
    session = _SessionStub()
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli, "_single_stock", lambda db, ticker: stock)
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_evidence_as_of",
        lambda db, stock_id, cutoff, storage_root: [],
    )
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_failures_as_of",
        lambda db, stock_id, cutoff, storage_root: [
            SecFinancialEvidenceFailureAsOf(
                filing_id=11,
                accession_no="0000000077-26-000001",
                parse_run_id=22,
                error_code=error_code,
            )
        ],
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: NOW.replace(day=31),
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "FAILED",
            "--cutoff",
            "2026-08-30T12:00:00Z",
        ],
    )

    assert result.exit_code == 2
    assert "filings=0" in result.output
    assert f"failure=0000000077-26-000001:{error_code}" in result.output
    assert "pit_evidence_unavailable" not in result.output


def test_replay_outputs_mixed_success_and_terminal_failure_then_exits_nonzero(
    monkeypatch,
) -> None:
    stock = SimpleNamespace(id=77, ticker="MIXED")
    session = _SessionStub()
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli, "_single_stock", lambda db, ticker: stock)
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_evidence_as_of",
        lambda db, stock_id, cutoff, storage_root: [
            SecFinancialEvidenceAsOf(
                filing_id=11,
                accession_no="0000000077-26-000001",
                form_type="10-Q",
                accepted_at=NOW,
                parse_run_id=21,
                parser_version="inline-xbrl-v1",
                input_manifest_hash="a" * 64,
                fact_count=3,
            )
        ],
    )
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_failures_as_of",
        lambda db, stock_id, cutoff, storage_root: [
            SecFinancialEvidenceFailureAsOf(
                filing_id=12,
                accession_no="0000000077-26-000002",
                parse_run_id=22,
                error_code="required_artifact_unavailable",
            )
        ],
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "MIXED",
            "--cutoff",
            "2026-08-30T12:00:00Z",
        ],
    )

    assert result.exit_code == 2
    assert "ticker=MIXED cutoff=2026-08-30T12:00:00+00:00 filings=1" in result.output
    assert (
        "accession=0000000077-26-000001 form=10-Q "
        "parser=inline-xbrl-v1 facts=3"
    ) in result.output
    assert (
        "failure=0000000077-26-000002:required_artifact_unavailable"
        in result.output
    )


def test_replay_is_empty_success_only_when_no_eligible_run_history(monkeypatch) -> None:
    stock = SimpleNamespace(id=77, ticker="EMPTY")
    session = _SessionStub()
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli, "_single_stock", lambda db, ticker: stock)
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_evidence_as_of",
        lambda db, stock_id, cutoff, storage_root: [],
    )
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_failures_as_of",
        lambda db, stock_id, cutoff, storage_root: [],
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: None,
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "EMPTY",
            "--cutoff",
            "2026-08-30T12:00:00Z",
        ],
    )

    assert result.exit_code == 0
    assert "ticker=EMPTY cutoff=2026-08-30T12:00:00+00:00 filings=0" in result.output


def test_replay_switches_from_pit_unavailable_at_exact_lineage_boundary(
    monkeypatch,
) -> None:
    stock = SimpleNamespace(id=77, ticker="BOUNDARY")
    session = _SessionStub()
    boundary = datetime(2026, 8, 30, 12, 0, 2, tzinfo=timezone.utc)
    row = SecFinancialEvidenceAsOf(
        filing_id=11,
        accession_no="0000000077-26-000001",
        form_type="10-Q",
        accepted_at=NOW,
        parse_run_id=22,
        parser_version="inline-xbrl-v1",
        input_manifest_hash="a" * 64,
        fact_count=3,
    )
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli, "_single_stock", lambda db, ticker: stock)
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_evidence_as_of",
        lambda db, stock_id, cutoff, storage_root: [row] if cutoff >= boundary else [],
    )
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_failures_as_of",
        lambda db, stock_id, cutoff, storage_root: [],
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: boundary,
    )

    before = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "BOUNDARY",
            "--cutoff",
            (boundary - timedelta(microseconds=1)).isoformat(),
        ],
    )
    exact = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "BOUNDARY",
            "--cutoff",
            boundary.isoformat(),
        ],
    )

    assert before.exit_code == 2
    assert "failure=pit_evidence_unavailable" in before.output
    assert exact.exit_code == 0
    assert "filings=1" in exact.output


def test_replay_fails_closed_while_committed_lineage_awaits_finalize(
    monkeypatch,
) -> None:
    stock = SimpleNamespace(id=77, ticker="PENDING")
    session = _SessionStub()
    monkeypatch.setattr(financial_cli, "SessionLocal", lambda: session)
    monkeypatch.setattr(financial_cli, "_single_stock", lambda db, ticker: stock)
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_evidence_as_of",
        lambda db, stock_id, cutoff, storage_root: [],
    )
    monkeypatch.setattr(
        financial_cli,
        "select_sec_financial_failures_as_of",
        lambda db, stock_id, cutoff, storage_root: [],
    )
    monkeypatch.setattr(
        financial_cli,
        "earliest_replayable_sec_financial_evidence_at",
        lambda db, stock_id, storage_root: None,
    )
    monkeypatch.setattr(
        financial_cli,
        "has_pending_sec_financial_lineage",
        lambda db, stock_id: True,
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "replay",
            "--ticker",
            "PENDING",
            "--cutoff",
            "2026-08-30T12:00:00Z",
        ],
    )

    assert result.exit_code == 2
    assert "failure=pit_evidence_unavailable" in result.output
    assert "reason=lineage_pending_finalize" in result.output


class _SessionStub:
    def __init__(self) -> None:
        self.commit_count = 0

    def scalar(self, *args, **kwargs):
        return False

    def get(self, *args, **kwargs):
        return SimpleNamespace(attempted_at=NOW)

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class _SessionProxy:
    def __init__(self, session) -> None:
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self) -> None:
        pass


class _EdgarStub:
    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        pass


def test_gold_case_bootstraps_narrow_separator_alias(db_session) -> None:
    stock = _stock(db_session, ticker="BRK/B")

    resolution = _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)

    assert resolution.stock.id == stock.id
    assert resolution.source == "locked_manifest_bootstrap"
    assert resolution.manifest_ticker == "BRK-B"


def test_gold_case_bootstrap_accepts_unambiguous_legacy_listing_fallback(
    db_session,
) -> None:
    stock = _stock(
        db_session,
        ticker="BRK/B",
        listing_exchange=None,
        raw_exchange="NYSE",
        exchange="NYSE",
    )

    resolution = _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)

    assert resolution.stock.id == stock.id
    assert resolution.source == "locked_manifest_bootstrap"


def test_gold_case_bootstrap_rejects_canonical_venue_mismatch_even_if_raw_matches(
    db_session,
) -> None:
    _stock(
        db_session,
        ticker="BRK/B",
        listing_exchange="NASDAQ",
        raw_exchange="NYSE",
        exchange="NYSE",
    )

    with pytest.raises(
        typer.BadParameter,
        match="locked case bootstrap must resolve to exactly one consistent stock row; found 0",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_bootstrap_rejects_conflicting_legacy_listing_metadata(
    db_session,
) -> None:
    _stock(
        db_session,
        ticker="BRK/B",
        listing_exchange=None,
        raw_exchange="NYSE",
        exchange="NASDAQ",
    )

    with pytest.raises(
        typer.BadParameter,
        match="locked case bootstrap must resolve to exactly one consistent stock row; found 0",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_bootstrap_alias_ambiguity_fails_closed(db_session) -> None:
    _stock(db_session, ticker="BRK/B")
    _stock(db_session, ticker="BRK.B")

    with pytest.raises(
        typer.BadParameter,
        match="locked case bootstrap must resolve to exactly one consistent stock row; found 2",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_conflicting_reviewed_cik_never_falls_back_to_ticker(
    db_session,
) -> None:
    conflicting = _stock(
        db_session,
        ticker="OTHER",
        company_name="Another Economic Issuer Inc.",
    )
    _stock(db_session, ticker="BRK/B")
    register_reviewed_sec_identity(
        db_session,
        stock_id=conflicting.id,
        cik=BRKB_CASE["cik"],
        effective_from=date(2015, 1, 1),
        known_at=NOW,
        review_reason="Conflicting reviewed identity fixture.",
    )

    with pytest.raises(
        typer.BadParameter,
        match="reviewed CIK identity conflicts with locked case brkb-primary",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_inactive_reviewed_stock_never_falls_back_to_active_alias(
    db_session,
) -> None:
    inactive_reviewed = _stock(db_session, ticker="BRK/B", is_active=False)
    _stock(db_session, ticker="BRK.B")
    register_reviewed_sec_identity(
        db_session,
        stock_id=inactive_reviewed.id,
        cik=BRKB_CASE["cik"],
        effective_from=date(2015, 1, 1),
        known_at=NOW,
        review_reason="Inactive reviewed identity fixture.",
    )

    with pytest.raises(
        typer.BadParameter,
        match="reviewed CIK identity conflicts with locked case brkb-primary",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_acceptance_pass_report_status_preserves_resumed_typed_incomplete_exit(
    monkeypatch, tmp_path
) -> None:
    reports_root = tmp_path / "reports"
    _write_acceptance_pass_reports(reports_root)
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda run_id: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    audited = _stub_acceptance_report_database_audit(monkeypatch)

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "acceptance-pass-report-status",
            "--acceptance-run-id",
            "step-d-resume-test",
            "--acceptance-pass",
            "2",
        ],
    )

    assert result.exit_code == 2
    assert "completed=24/24" in result.output
    assert "typed_incomplete=2" in result.output
    assert len(audited) == 24


def test_acceptance_pass_report_status_audits_existing_reports_before_resume(
    monkeypatch, tmp_path
) -> None:
    reports_root = tmp_path / "reports"
    cases = _write_acceptance_pass_reports(reports_root)
    first_case_id = str(cases[0]["case_id"])
    for case in cases[1:]:
        (reports_root / "pass-2" / f"{case['case_id']}.json").unlink()
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda run_id: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    audited = _stub_acceptance_report_database_audit(monkeypatch)

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "acceptance-pass-report-status",
            "--acceptance-run-id",
            "step-d-resume-test",
            "--acceptance-pass",
            "2",
            "--allow-missing",
        ],
    )

    assert result.exit_code == 0
    assert "completed=1/24" in result.output
    assert "typed_incomplete=0" in result.output
    assert audited == [first_case_id]


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("run_id", "wrong-run"),
        ("case_id", "wrong-case"),
        ("acceptance_pass", 1),
    ),
)
def test_acceptance_pass_report_status_rejects_wrong_report_identity(
    monkeypatch, tmp_path, field, invalid_value
) -> None:
    reports_root = tmp_path / "reports"
    cases = _write_acceptance_pass_reports(reports_root)
    first_case_id = str(cases[0]["case_id"])
    report_path = reports_root / "pass-2" / f"{first_case_id}.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload[field] = invalid_value
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda run_id: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    _stub_acceptance_report_database_audit(monkeypatch)

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "acceptance-pass-report-status",
            "--acceptance-run-id",
            "step-d-resume-test",
            "--acceptance-pass",
            "2",
        ],
    )

    assert result.exit_code == 1
    assert f"acceptance report identity mismatch: {first_case_id}" in result.output


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("cik", "0000000001"),
        ("stock_id", 999999),
        ("operation_id", "11111111-1111-4111-8111-111111111111"),
    ),
)
def test_acceptance_pass_report_status_rejects_database_identity_conflict(
    monkeypatch, tmp_path, field, invalid_value
) -> None:
    reports_root = tmp_path / "reports"
    cases = _write_acceptance_pass_reports(reports_root)
    first_case_id = str(cases[0]["case_id"])
    report_path = reports_root / "pass-2" / f"{first_case_id}.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    expected_operation_id = payload["operation_id"]
    payload[field] = invalid_value
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda run_id: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )

    def validate_database_identity(case, report):
        if (
            str(report.get("cik")) != str(case["cik"])
            or int(report.get("stock_id", -1)) != 1
            or report.get("operation_id") != expected_operation_id
        ):
            raise ValueError(
                f"acceptance report database identity mismatch: {case['case_id']}"
            )

    audited = _stub_acceptance_report_database_audit(
        monkeypatch, validator=validate_database_identity
    )

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "acceptance-pass-report-status",
            "--acceptance-run-id",
            "step-d-resume-test",
            "--acceptance-pass",
            "2",
        ],
    )

    assert result.exit_code == 1
    assert f"acceptance report database identity mismatch: {first_case_id}" in result.output
    assert audited == []


def test_acceptance_pass_report_status_rejects_malformed_existing_report(
    monkeypatch, tmp_path
) -> None:
    reports_root = tmp_path / "reports"
    cases = _write_acceptance_pass_reports(reports_root)
    first_case_id = str(cases[0]["case_id"])
    report_path = reports_root / "pass-2" / f"{first_case_id}.json"
    report_path.write_text('{"broken":', encoding="utf-8")
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda run_id: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    _stub_acceptance_report_database_audit(monkeypatch)

    result = CliRunner().invoke(
        financial_cli.app,
        [
            "acceptance-pass-report-status",
            "--acceptance-run-id",
            "step-d-resume-test",
            "--acceptance-pass",
            "2",
        ],
    )

    assert result.exit_code == 1
    assert "JSONDecodeError" in result.output
