import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from app.models.institutions import JobRun
from app.services.thirteenf_admin_dashboard import smart_retry_failed_jobs, MAX_SMART_RETRY_ATTEMPTS

# Fixed reference point shared across all tests — avoids clock-dependent behaviour.
NOW = datetime(2026, 5, 7, 2, 0, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(hours=24)


def _old_partial_job(accession_no: str, lock_key: str, created_offset_hours: int = 30) -> JobRun:
    return JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        lock_key=lock_key,
        trigger_source="scheduler",
        created_at=NOW - timedelta(hours=created_offset_hours),
        finished_at=NOW - timedelta(hours=25),
        summary_json={"failed_accessions": [{"accession_no": accession_no}]},
    )


def test_smart_retry_filters_by_age(db_session):
    """Jobs finished less than 24 h ago must be skipped; older ones retried."""
    old_job = _old_partial_job("123-456", "old_job")
    recent_job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        lock_key="recent_job",
        trigger_source="scheduler",
        finished_at=NOW - timedelta(hours=2),
        summary_json={"failed_accessions": [{"accession_no": "789-012"}]},
    )
    db_session.add_all([old_job, recent_job])
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 999}
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 1
    mock_trigger.assert_called_once()
    assert mock_trigger.call_args[1]["payload"]["accession_no"] == "123-456"


def test_smart_retry_skips_already_succeeded(db_session):
    """Accession already successfully retried by a newer job must be skipped."""
    old_job = _old_partial_job("123-456", "old_job", created_offset_hours=30)
    retry_job = JobRun(
        job_type="ingest_accession",
        status="succeeded",
        lock_key="ingest_accession:123-456",
        trigger_source="smart_retry",
        created_at=old_job.created_at + timedelta(hours=1),
        finished_at=NOW - timedelta(hours=9),
    )
    db_session.add_all([old_job, retry_job])
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 0
    mock_trigger.assert_not_called()


def test_smart_retry_handles_nested_quarterly_failures(db_session):
    """failed_accessions nested under holdings_ingestion (quarterly_pipeline format) must be extracted."""
    pipeline_job = JobRun(
        job_type="quarterly_pipeline",
        status="partial_success",
        lock_key="pipeline_job",
        trigger_source="scheduler",
        finished_at=NOW - timedelta(hours=25),
        summary_json={"holdings_ingestion": {"failed_accessions": [{"accession_no": "abc-def"}]}},
    )
    db_session.add(pipeline_job)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 100}
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 1
    assert mock_trigger.call_args[1]["payload"]["accession_no"] == "abc-def"


def test_smart_retry_handles_quarterly_enrichment_stage_failure(db_session):
    """Pipeline enrichment stage failures should queue an enrichment-only retry."""
    pipeline_job = JobRun(
        job_type="quarterly_pipeline",
        status="partial_success",
        lock_key="quarterly_pipeline:2025-Q4",
        quarter="2025-Q4",
        trigger_source="scheduler",
        created_at=NOW - timedelta(hours=30),
        finished_at=NOW - timedelta(hours=25),
        summary_json={
            "stages": [
                {"job_type": "fetch_quarter_index", "job_id": 1, "status": "succeeded"},
                {"job_type": "ingest_holdings", "job_id": 2, "status": "succeeded"},
                {"job_type": "enrich_metadata", "job_id": 3, "status": "failed"},
                {"job_type": "quality_check", "job_id": 4, "status": "succeeded"},
            ],
        },
    )
    db_session.add(pipeline_job)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 101}
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 1
    assert mock_trigger.call_args[1]["payload"] == {
        "job_type": "enrich_metadata",
        "quarter": "2025-Q4",
        "trigger_source": "smart_retry",
    }


def test_smart_retry_does_not_auto_retry_full_quarter_ingest_stage(db_session):
    """Smart retry should avoid broad quarter ingestion reruns; accession retries stay targeted."""
    pipeline_job = JobRun(
        job_type="quarterly_pipeline",
        status="partial_success",
        lock_key="quarterly_pipeline:2025-Q4",
        quarter="2025-Q4",
        trigger_source="scheduler",
        created_at=NOW - timedelta(hours=30),
        finished_at=NOW - timedelta(hours=25),
        summary_json={
            "stages": [
                {"job_type": "ingest_holdings", "job_id": 2, "status": "failed"},
            ],
        },
    )
    db_session.add(pipeline_job)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert results == []
    mock_trigger.assert_not_called()


def test_smart_retry_stops_stage_retry_at_max_attempts(db_session):
    """Stage-level retries use the same max-attempt guard as accession retries."""
    pipeline_job = JobRun(
        job_type="quarterly_pipeline",
        status="partial_success",
        lock_key="quarterly_pipeline:2025-Q4",
        quarter="2025-Q4",
        trigger_source="scheduler",
        created_at=NOW - timedelta(hours=30),
        finished_at=NOW - timedelta(hours=25),
        summary_json={
            "stages": [{"job_type": "enrich_metadata", "job_id": 3, "status": "failed"}],
        },
    )
    db_session.add(pipeline_job)
    db_session.flush()
    db_session.add_all(
        [
            JobRun(
                job_type="enrich_metadata",
                status="failed",
                lock_key="enrich_metadata:2025-Q4",
                quarter="2025-Q4",
                trigger_source="smart_retry",
                created_at=pipeline_job.created_at + timedelta(hours=i + 1),
                finished_at=pipeline_job.created_at + timedelta(hours=i + 2),
            )
            for i in range(MAX_SMART_RETRY_ATTEMPTS)
        ]
    )
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert results == []
    mock_trigger.assert_not_called()


def test_smart_retry_deduplicates_same_accession_across_jobs(db_session):
    """Same accession appearing in two different partial_success jobs must only trigger one retry."""
    job1 = _old_partial_job("dup-001", "job1", created_offset_hours=50)
    job2 = _old_partial_job("dup-001", "job2", created_offset_hours=40)
    db_session.add_all([job1, job2])
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 200}
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 1
    mock_trigger.assert_called_once()


def test_smart_retry_retries_after_failed_newer_run(db_session):
    """A newer run that itself failed must not block another smart retry."""
    old_job = _old_partial_job("fail-001", "old_job", created_offset_hours=30)
    db_session.add(old_job)
    db_session.flush()

    failed_retry = JobRun(
        job_type="ingest_accession",
        status="failed",
        lock_key="ingest_accession:fail-001",
        trigger_source="smart_retry",
        created_at=old_job.created_at + timedelta(hours=1),
        finished_at=old_job.created_at + timedelta(hours=2),
    )
    db_session.add(failed_retry)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 400}
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 1
    mock_trigger.assert_called_once()


def test_smart_retry_skips_malformed_failed_accessions(db_session):
    """Jobs with non-list failed_accessions in summary_json must be skipped gracefully."""
    bad_job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        lock_key="bad_job",
        trigger_source="scheduler",
        finished_at=NOW - timedelta(hours=25),
        summary_json={"failed_accessions": "not-a-list"},
    )
    db_session.add(bad_job)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 0
    mock_trigger.assert_not_called()


def test_smart_retry_stops_at_max_attempts(db_session):
    """Accession that has already been smart-retried MAX times must not be queued again."""
    old_job = _old_partial_job("stuck-001", "old_job", created_offset_hours=30)
    db_session.add(old_job)
    db_session.flush()  # ensure old_job.created_at is set before building retries

    # Simulate MAX prior smart-retry attempts, all partial_success (not yet succeeded).
    prior_retries = [
        JobRun(
            job_type="ingest_accession",
            status="partial_success",
            lock_key="ingest_accession:stuck-001",
            trigger_source="smart_retry",
            created_at=old_job.created_at + timedelta(hours=i + 1),
            finished_at=old_job.created_at + timedelta(hours=i + 2),
        )
        for i in range(MAX_SMART_RETRY_ATTEMPTS)
    ]
    db_session.add_all(prior_retries)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 0
    mock_trigger.assert_not_called()


def test_smart_retry_allows_retry_below_max_attempts(db_session):
    """Accession with fewer than MAX prior retries must still be queued."""
    old_job = _old_partial_job("partial-001", "old_job", created_offset_hours=30)
    db_session.add(old_job)
    db_session.flush()

    prior_retries = [
        JobRun(
            job_type="ingest_accession",
            status="partial_success",
            lock_key="ingest_accession:partial-001",
            trigger_source="smart_retry",
            created_at=old_job.created_at + timedelta(hours=i + 1),
            finished_at=old_job.created_at + timedelta(hours=i + 2),
        )
        for i in range(MAX_SMART_RETRY_ATTEMPTS - 1)
    ]
    db_session.add_all(prior_retries)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 300}
        results = smart_retry_failed_jobs(db_session, now=NOW)

    assert len(results) == 1
    mock_trigger.assert_called_once()
