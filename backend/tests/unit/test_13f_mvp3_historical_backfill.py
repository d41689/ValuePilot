from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

import pytest

from app.models.institutions import (
    Filing13F,
    InstitutionManager,
    JobRun,
    QualityFinding13F,
    QualityReport13F,
)
from app.services.thirteenf_historical_backfill import (
    HistoricalBackfillError,
    enqueue_historical_backfill,
    execute_historical_backfill,
    preview_historical_backfill,
)


_CIK_SEQ = count(9930000000)
_ACC_SEQ = count(1)


def _next_accession() -> str:
    return f"0009930001-26-{next(_ACC_SEQ):06d}"


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ)).zfill(10)
    manager = InstitutionManager(
        canonical_name=f"Backfill Manager {cik}",
        legal_name=f"Backfill Manager {cik}",
        edgar_legal_name=f"Backfill Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _quarter_end(quarter: str) -> date:
    year_text, qtr_text = quarter.split("-Q")
    period_end_month = int(qtr_text) * 3
    last_day = 31 if period_end_month in (1, 3, 5, 7, 8, 10, 12) else 30
    return date(int(year_text), period_end_month, last_day)


def _existing_filing(db_session, manager: InstitutionManager, quarter: str) -> Filing13F:
    accession = _next_accession()
    period_end = _quarter_end(quarter)
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=period_end,
        filed_at=period_end,
        filing_date=period_end,
        accepted_at=datetime(period_end.year, period_end.month, period_end.day, 17, tzinfo=timezone.utc),
        report_quarter=quarter,
        quarter_end_date=period_end,
        is_active_for_manager_period=True,
        parse_status="succeeded",
        report_type="holdings_report",
        coverage_completeness="complete",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _discovery_returning(accessions_by_quarter: dict[str, list[str]]):
    """Build a filing_discovery_fn that yields fixed accessions per (manager, quarter)."""

    def _fn(manager: InstitutionManager, quarter: str) -> list[dict]:
        return [
            {"accession_number": acc, "manager_id": manager.id, "report_quarter": quarter}
            for acc in accessions_by_quarter.get(quarter, [])
        ]

    return _fn


def _ingest_succeeds(_session, _manager, meta):
    return {"status": "succeeded", "accession_number": meta["accession_number"]}


def _ingest_fails(_session, _manager, meta):
    return {
        "status": "failed",
        "accession_number": meta["accession_number"],
        "error": "simulated ingest failure",
    }


# ----- Preview -----------------------------------------------------------


def test_preview_defaults_to_2023_q1_when_no_start_given(db_session):
    _manager(db_session)
    preview = preview_historical_backfill(db_session)
    assert preview["start_quarter"] == "2023-Q1"
    assert preview["value_unit_risk_warning"] is False


def test_preview_flags_pre_2023_range_as_value_unit_risk_and_dry_run_required(db_session):
    _manager(db_session)
    preview = preview_historical_backfill(
        db_session, start_quarter="2022-Q4", end_quarter="2023-Q2"
    )
    assert preview["value_unit_risk_warning"] is True
    assert preview["requires_dry_run"] is True


def test_preview_does_not_mutate(db_session):
    _manager(db_session)
    parse_runs_before = db_session.query(JobRun).count()
    reports_before = db_session.query(QualityReport13F).count()
    findings_before = db_session.query(QualityFinding13F).count()

    preview_historical_backfill(db_session, start_quarter="2023-Q1", end_quarter="2023-Q3")

    assert db_session.query(JobRun).count() == parse_runs_before
    assert db_session.query(QualityReport13F).count() == reports_before
    assert db_session.query(QualityFinding13F).count() == findings_before


# ----- Enqueue -----------------------------------------------------------


def test_enqueue_creates_jobrun_with_deterministic_lock_key(db_session):
    job = enqueue_historical_backfill(
        db_session, start_quarter="2023-Q1", end_quarter="2023-Q3"
    )
    assert job.job_type == "historical_backfill"
    assert job.lock_key == "13f_historical_backfill:2023-Q1:2023-Q3:all_active_managers"
    assert job.dedupe_key == job.lock_key
    assert job.status == "queued"
    assert job.input_json["start_quarter"] == "2023-Q1"
    assert job.input_json["end_quarter"] == "2023-Q3"
    assert job.input_json["dry_run"] is False


def test_enqueue_rejects_duplicate_active_request(db_session):
    enqueue_historical_backfill(db_session, start_quarter="2023-Q1", end_quarter="2023-Q3")
    with pytest.raises(HistoricalBackfillError, match="already active"):
        enqueue_historical_backfill(db_session, start_quarter="2023-Q1", end_quarter="2023-Q3")


def test_enqueue_rejects_pre_2023_without_dry_run_flag(db_session):
    with pytest.raises(HistoricalBackfillError, match="dry_run"):
        enqueue_historical_backfill(
            db_session, start_quarter="2022-Q4", end_quarter="2023-Q1"
        )


def test_enqueue_allows_pre_2023_with_dry_run_flag(db_session):
    job = enqueue_historical_backfill(
        db_session, start_quarter="2022-Q4", end_quarter="2023-Q1", dry_run=True
    )
    assert job.input_json["dry_run"] is True


def test_enqueue_translates_unique_index_race(db_session, monkeypatch):
    from app.services import thirteenf_historical_backfill as backfill_mod

    enqueue_historical_backfill(db_session, start_quarter="2023-Q1", end_quarter="2023-Q1")

    monkeypatch.setattr(
        backfill_mod,
        "_active_job_for_lock_key",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    with pytest.raises(HistoricalBackfillError, match="lock_key uniqueness"):
        enqueue_historical_backfill(db_session, start_quarter="2023-Q1", end_quarter="2023-Q1")


# ----- Execute -----------------------------------------------------------


def test_execute_requires_explicit_validation_gate(db_session):
    job = enqueue_historical_backfill(db_session, start_quarter="2023-Q1", end_quarter="2023-Q1")
    with pytest.raises(ValueError, match="validation_gate is required"):
        execute_historical_backfill(
            db_session,
            job_run_id=job.id,
            validation_gate=None,
            filing_discovery_fn=lambda *_: [],
            ingest_fn=_ingest_succeeds,
        )


def test_execute_skips_manager_quarter_with_existing_active_filing(db_session):
    manager = _manager(db_session)
    _existing_filing(db_session, manager, "2023-Q1")

    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2023-Q1",
        end_quarter="2023-Q1",
        manager_ids=[manager.id],
    )
    ingest_calls: list[str] = []

    def _spying_ingest(session, mgr, meta):
        ingest_calls.append(meta["accession_number"])
        return _ingest_succeeds(session, mgr, meta)

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=_discovery_returning({"2023-Q1": ["should-not-be-ingested"]}),
        ingest_fn=_spying_ingest,
    )

    assert ingest_calls == []
    impact = result["impact_summary"]
    assert impact["filings_already_present"] == 1
    assert impact["filings_ingested"] == 0


def test_execute_ingests_missing_filings_and_writes_needs_validation_findings(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2023-Q1",
        end_quarter="2023-Q1",
        manager_ids=[manager.id],
    )

    discovery = _discovery_returning({"2023-Q1": ["acc-q1-a", "acc-q1-b"]})

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (False, ["awaiting human review"]),
        filing_discovery_fn=discovery,
        ingest_fn=_ingest_succeeds,
    )

    impact = result["impact_summary"]
    assert impact["filings_ingested"] == 2
    assert impact["quarters_needs_validation"] == 1
    assert impact["quarters_validated"] == 0

    report = (
        db_session.query(QualityReport13F)
        .filter(QualityReport13F.quarter == "2023-Q1")
        .order_by(QualityReport13F.id.desc())
        .first()
    )
    findings = (
        db_session.query(QualityFinding13F)
        .filter(QualityFinding13F.validation_run_id == report.id)
        .all()
    )
    assert {f.rule_code for f in findings} == {"HISTORICAL_BACKFILL_NEEDS_VALIDATION"}
    assert {f.status for f in findings} == {"open"}
    assert {f.accession_number for f in findings} == {"acc-q1-a", "acc-q1-b"}


def test_execute_validation_success_resolves_findings(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2023-Q1",
        end_quarter="2023-Q1",
        manager_ids=[manager.id],
    )
    discovery = _discovery_returning({"2023-Q1": ["acc-q1-a"]})

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=discovery,
        ingest_fn=_ingest_succeeds,
    )

    impact = result["impact_summary"]
    assert impact["quarters_validated"] == 1
    assert impact["quarters_needs_validation"] == 0
    finding = (
        db_session.query(QualityFinding13F)
        .filter(QualityFinding13F.rule_code == "HISTORICAL_BACKFILL_NEEDS_VALIDATION")
        .filter(QualityFinding13F.accession_number == "acc-q1-a")
        .one_or_none()
    )
    assert finding is not None
    assert finding.status == "resolved"
    assert finding.resolution_note is not None
    assert finding.resolved_at is not None


def test_execute_isolates_per_filing_ingest_failures(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2023-Q1",
        end_quarter="2023-Q1",
        manager_ids=[manager.id],
    )

    def mixed_ingest(session, mgr, meta):
        if meta["accession_number"] == "acc-q1-fails":
            return _ingest_fails(session, mgr, meta)
        return _ingest_succeeds(session, mgr, meta)

    discovery = _discovery_returning({"2023-Q1": ["acc-q1-fails", "acc-q1-ok"]})

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=discovery,
        ingest_fn=mixed_ingest,
    )

    impact = result["impact_summary"]
    assert impact["filings_failed"] == 1
    assert impact["filings_ingested"] == 1
    # The successful filing's finding flips to resolved; the failed one remains open
    # because validation is only as good as the inputs.
    findings = (
        db_session.query(QualityFinding13F)
        .filter(QualityFinding13F.rule_code == "HISTORICAL_BACKFILL_NEEDS_VALIDATION")
        .all()
    )
    by_acc = {f.accession_number: f.status for f in findings}
    assert by_acc.get("acc-q1-ok") == "resolved"
    assert by_acc.get("acc-q1-fails") == "open"


def test_execute_dry_run_skips_ingestion(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2022-Q4",
        end_quarter="2022-Q4",
        manager_ids=[manager.id],
        dry_run=True,
    )

    ingest_calls: list[str] = []

    def _spying_ingest(session, mgr, meta):
        ingest_calls.append(meta["accession_number"])
        return _ingest_succeeds(session, mgr, meta)

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        filing_discovery_fn=_discovery_returning({"2022-Q4": ["acc-dry-run"]}),
        ingest_fn=_spying_ingest,
    )

    impact = result["impact_summary"]
    assert ingest_calls == []
    assert impact["filings_ingested"] == 0
    assert impact["dry_run"] is True


def test_execute_aggregate_status_reflects_validation_outcomes(db_session):
    manager = _manager(db_session)
    job = enqueue_historical_backfill(
        db_session,
        start_quarter="2023-Q1",
        end_quarter="2023-Q2",
        manager_ids=[manager.id],
    )

    discovery = _discovery_returning({
        "2023-Q1": ["acc-q1-a"],
        "2023-Q2": ["acc-q2-a"],
    })

    def per_quarter_gate(_session, quarter, _results):
        return (quarter == "2023-Q1", [] if quarter == "2023-Q1" else ["gate failed"])

    result = execute_historical_backfill(
        db_session,
        job_run_id=job.id,
        validation_gate=per_quarter_gate,
        filing_discovery_fn=discovery,
        ingest_fn=_ingest_succeeds,
    )

    impact = result["impact_summary"]
    assert impact["quarters_scanned"] == 2
    assert impact["quarters_validated"] == 1
    assert impact["quarters_needs_validation"] == 1
    assert result["status"] == "partial_success"
