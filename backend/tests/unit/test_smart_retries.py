import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
from app.models.institutions import JobRun, Filing13F, InstitutionManager
from app.services.thirteenf_admin_dashboard import smart_retry_failed_jobs, trigger_job

def test_smart_retry_failed_jobs_filters_by_age(db_session):
    # Setup: one old partially failed job, one recent one
    now = datetime.now(timezone.utc)
    old_job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        lock_key="old_job",
        finished_at=now - timedelta(hours=25),
        summary_json={"failed_accessions": [{"accession_no": "123-456"}]}
    )
    recent_job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        lock_key="recent_job",
        finished_at=now - timedelta(hours=2),
        summary_json={"failed_accessions": [{"accession_no": "789-012"}]}
    )
    db_session.add_all([old_job, recent_job])
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 999}
        results = smart_retry_failed_jobs(db_session)
        
        # Should only retry the old job
        assert len(results) == 1
        mock_trigger.assert_called_once()
        assert mock_trigger.call_args[1]["payload"]["accession_no"] == "123-456"

def test_smart_retry_failed_jobs_skips_already_retried(db_session):
    now = datetime.now(timezone.utc)
    # Old job that failed
    old_job = JobRun(
        job_type="ingest_holdings",
        status="partial_success",
        lock_key="old_job",
        created_at=now - timedelta(hours=30),
        finished_at=now - timedelta(hours=25),
        summary_json={"failed_accessions": [{"accession_no": "123-456"}]}
    )
    # Newer job that succeeded for the same accession
    retry_job = JobRun(
        job_type="ingest_accession",
        status="succeeded",
        lock_key="ingest_accession:123-456",
        created_at=now - timedelta(hours=10),
        finished_at=now - timedelta(hours=9)
    )
    db_session.add_all([old_job, retry_job])
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        results = smart_retry_failed_jobs(db_session)
        # Should skip because it was already successfully retried
        assert len(results) == 0
        mock_trigger.assert_not_called()

def test_smart_retry_failed_jobs_handles_nested_failures(db_session):
    now = datetime.now(timezone.utc)
    # Quarterly pipeline nested summary
    pipeline_job = JobRun(
        job_type="quarterly_pipeline",
        status="partial_success",
        lock_key="pipeline_job",
        finished_at=now - timedelta(hours=25),
        summary_json={
            "holdings_ingestion": {
                "failed_accessions": [{"accession_no": "abc-def"}]
            }
        }
    )
    db_session.add(pipeline_job)
    db_session.commit()

    with patch("app.services.thirteenf_admin_dashboard.trigger_job") as mock_trigger:
        mock_trigger.return_value = {"id": 100}
        results = smart_retry_failed_jobs(db_session)
        assert len(results) == 1
        assert mock_trigger.call_args[1]["payload"]["accession_no"] == "abc-def"
