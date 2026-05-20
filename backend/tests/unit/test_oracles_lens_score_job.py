"""Tests for wiring oracles_lens_score_backfill into the job dispatcher
and quarterly_pipeline (PR #10 — the final pipeline wire).

Before this, the Oracle's Lens scoring subsystem (compute_signal_weighted_scores,
JOB_TYPE = "oracles_lens_score_backfill") existed but was orphaned: the job
worker's _execute_job dispatcher had no case for it, _JOB_LOCK_BUILDERS had no
entry, and quarterly_pipeline had only 4 stages. Net effect: oracles_lens_signals
stayed empty, and /watchlist returned no_qualifying_period for every stock.
"""
from __future__ import annotations

from unittest.mock import patch

from app.services.thirteenf_admin_dashboard import (
    _JOB_LOCK_BUILDERS,
    execute_job_payload,
    trigger_job,
)
from app.models.institutions import JobRun


def test_oracles_lens_score_backfill_has_lock_key_builder():
    """The job type is registered so trigger_job / _execute_pipeline_stage_job
    can build a lock_key for it."""
    assert "oracles_lens_score_backfill" in _JOB_LOCK_BUILDERS
    lock_key = _JOB_LOCK_BUILDERS["oracles_lens_score_backfill"]({"quarter": "2025-Q4"})
    # Format: oracles_lens_score:<quarter>:<score_version>
    assert lock_key.startswith("oracles_lens_score:2025-Q4:")


def test_oracles_lens_score_backfill_lock_key_honors_explicit_version():
    lock_key = _JOB_LOCK_BUILDERS["oracles_lens_score_backfill"](
        {"quarter": "2025-Q4", "score_version": "v9.9"}
    )
    assert lock_key == "oracles_lens_score:2025-Q4:v9.9"


def test_trigger_job_accepts_oracles_lens_score_backfill(db_session):
    """trigger_job should create a queued JobRun for the scoring job type
    without raising 'Unsupported job_type'."""
    result = trigger_job(
        db_session,
        requested_by_user_id=None,
        payload={"job_type": "oracles_lens_score_backfill", "quarter": "2025-Q4"},
    )
    job = db_session.get(JobRun, result["id"])
    assert job.job_type == "oracles_lens_score_backfill"
    assert job.status == "queued"
    assert job.lock_key.startswith("oracles_lens_score:2025-Q4:")


def test_execute_job_dispatches_to_compute_signal_weighted_scores(db_session):
    """execute_job_payload routes oracles_lens_score_backfill to
    compute_signal_weighted_scores with quarter + min_holders + source_job_id."""
    fake_impact = {"quarter": "2025-Q4", "filings_scored": 7, "components_written": 42}
    with patch(
        "app.services.oracles_lens.signal_weighted_score.compute_signal_weighted_scores",
        return_value=fake_impact,
    ) as mock_compute:
        summary = execute_job_payload(
            db_session,
            "oracles_lens_score_backfill",
            {"quarter": "2025-Q4", "_job_id": 123},
        )

    assert summary["status"] == "succeeded"
    assert summary["filings_scored"] == 7
    assert summary["components_written"] == 42
    mock_compute.assert_called_once()
    call_kwargs = mock_compute.call_args.kwargs
    assert call_kwargs["quarter"] == "2025-Q4"
    assert call_kwargs["min_holders"] == 3
    assert call_kwargs["source_job_id"] == 123


def test_execute_job_oracles_lens_scoring_honors_min_holders_override(db_session):
    with patch(
        "app.services.oracles_lens.signal_weighted_score.compute_signal_weighted_scores",
        return_value={"quarter": "2025-Q4", "filings_scored": 0, "components_written": 0},
    ) as mock_compute:
        execute_job_payload(
            db_session,
            "oracles_lens_score_backfill",
            {"quarter": "2025-Q4", "min_holders": 5, "_job_id": 1},
        )
    assert mock_compute.call_args.kwargs["min_holders"] == 5


def test_quarterly_pipeline_includes_oracles_lens_scoring_stage(db_session):
    """The 5-stage quarterly_pipeline runs oracles_lens_score_backfill after
    quality_check. Each stage is stubbed so the test asserts orchestration,
    not the individual stage logic."""
    seen_stage_job_types: list[str] = []

    def fake_stage(session, *, parent_payload, job_type, payload):
        seen_stage_job_types.append(job_type)
        return {
            "stage": {"job_type": job_type, "job_id": len(seen_stage_job_types), "status": "succeeded"},
            "summary": {"status": "succeeded"},
        }

    with patch(
        "app.services.thirteenf_admin_dashboard._execute_pipeline_stage_job",
        side_effect=fake_stage,
    ):
        summary = execute_job_payload(
            db_session,
            "quarterly_pipeline",
            {"quarter": "2025-Q4", "_job_id": 1},
        )

    assert seen_stage_job_types == [
        "fetch_quarter_index",
        "ingest_holdings",
        "enrich_metadata",
        "quality_check",
        "oracles_lens_score_backfill",
    ]
    assert summary["status"] == "succeeded"
    assert "oracles_lens_scoring" in summary
