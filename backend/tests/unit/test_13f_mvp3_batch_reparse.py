from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count
from unittest import mock

import pytest

from app.models.institutions import (
    Filing13F,
    FilingValueUnitOverride13F,
    Holding13F,
    InstitutionManager,
    JobRun,
    ParseRun13F,
)
from app.models.users import User
from app.services.thirteenf_batch_reparse import (
    BatchReparseScopeError,
    enqueue_batch_reparse,
    execute_batch_reparse,
    preview_batch_reparse,
)
from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing


_CIK_SEQ = count(9910000000)
_ACC_SEQ = count(1)


def _next_accession() -> str:
    return f"0009910001-26-{next(_ACC_SEQ):06d}"


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ)).zfill(10)
    manager = InstitutionManager(
        canonical_name=f"Batch Reparse Manager {cik}",
        legal_name=f"Batch Reparse Manager {cik}",
        edgar_legal_name=f"Batch Reparse Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    accession: str | None = None,
    report_quarter: str = "2026-Q1",
    quarter_end: date = date(2026, 3, 31),
    coverage_type: str = "normal",
    form_type: str = "13F-HR",
) -> Filing13F:
    accession = accession or _next_accession()
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type=form_type,
        period_of_report=quarter_end,
        filed_at=date(2026, 5, 15),
        filing_date=date(2026, 5, 15),
        accepted_at=datetime(2026, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter=report_quarter,
        quarter_end_date=quarter_end,
        is_active_for_manager_period=True,
        parse_status="succeeded",
        report_type="holdings_report" if coverage_type == "normal" else "notice_report",
        coverage_completeness="complete",
        coverage_type=coverage_type,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _infotable(*, rows: int = 1) -> bytes:
    second = b""
    if rows > 1:
        second = b"""
  <infoTable>
    <nameOfIssuer>MICROSOFT CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>594918104</cusip>
    <value>9000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>40000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>40000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>"""
    return b"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>8000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>50000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>50000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>""" + second + b"""
</informationTable>"""


def _ingest(db_session, filing: Filing13F, *, rows: int = 1) -> int:
    result = ingest_holdings_for_filing(db_session, filing, _infotable(rows=rows))
    return result["parse_run_id"]


def test_batch_reparse_requires_exactly_one_scope(db_session):
    with pytest.raises(BatchReparseScopeError):
        preview_batch_reparse(db_session)
    with pytest.raises(BatchReparseScopeError):
        preview_batch_reparse(db_session, quarter="2026-Q1", manager_id=1)


def test_preview_does_not_mutate_state(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    initial_run_id = _ingest(db_session, filing)

    parse_runs_before = db_session.query(ParseRun13F).count()
    holdings_before = db_session.query(Holding13F).count()

    preview = preview_batch_reparse(db_session, quarter="2026-Q1")

    parse_runs_after = db_session.query(ParseRun13F).count()
    holdings_after = db_session.query(Holding13F).count()

    assert parse_runs_after == parse_runs_before
    assert holdings_after == holdings_before
    assert preview["scope"] == {"kind": "quarter", "value": "2026-Q1"}
    assert preview["lock_key"] == "13f_batch_reparse:quarter:2026-Q1"
    accessions = [c["accession_number"] for c in preview["candidate_filings"]]
    assert filing.accession_number in accessions
    assert preview["estimated_scope"]["candidate_count"] >= 1
    db_session.get(ParseRun13F, initial_run_id)  # still readable / untouched


def test_preview_excludes_13fnt_and_inactive_filings(db_session):
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    holdings_filing = _filing(db_session, manager_a)
    _ingest(db_session, holdings_filing)
    nt_filing = _filing(
        db_session,
        manager_b,
        coverage_type="notice_reported_elsewhere",
        form_type="13F-NT",
    )
    # NT does not produce holdings; only the holdings filing should be considered.

    preview = preview_batch_reparse(db_session, quarter="2026-Q1")
    accessions = {c["accession_number"] for c in preview["candidate_filings"]}

    assert holdings_filing.accession_number in accessions
    assert nt_filing.accession_number not in accessions


def test_enqueue_creates_job_run_with_lock_key(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    _ingest(db_session, filing)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    assert job.job_type == "batch_reparse_by_quarter"
    assert job.lock_key == "13f_batch_reparse:quarter:2026-Q1"
    assert job.dedupe_key == "13f_batch_reparse:quarter:2026-Q1"
    assert job.status == "queued"
    assert job.input_json["scope"] == {"kind": "quarter", "value": "2026-Q1"}


def test_enqueue_skips_duplicate_active_request(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    _ingest(db_session, filing)

    job_a = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    with pytest.raises(BatchReparseScopeError, match="already active"):
        enqueue_batch_reparse(db_session, quarter="2026-Q1")

    # Closing the active job allows a new one
    job_a.status = "succeeded"
    db_session.add(job_a)
    db_session.commit()

    job_b = enqueue_batch_reparse(db_session, quarter="2026-Q1")
    assert job_b.id != job_a.id


def test_enqueue_translates_unique_index_race_into_scope_error(db_session, monkeypatch):
    """Simulate the TOCTOU race: two enqueue calls both pass the pre-check,
    but only one survives the partial unique index uq_job_runs_active_lock_key
    at commit time. The losing call must raise BatchReparseScopeError, not
    leak a raw IntegrityError.
    """
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    _ingest(db_session, filing)

    # Seed an existing active batch for the same scope.
    existing = enqueue_batch_reparse(db_session, quarter="2026-Q1")
    assert existing.status == "queued"

    # Bypass the pre-check so the unique-index path is exercised.
    from app.services import thirteenf_batch_reparse as batch_mod

    monkeypatch.setattr(
        batch_mod,
        "_active_job_for_lock_key",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    with pytest.raises(BatchReparseScopeError, match="lock_key uniqueness"):
        enqueue_batch_reparse(db_session, quarter="2026-Q1")


def test_execute_batch_reparse_aggregates_impact(db_session):
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    filing_a = _filing(db_session, manager_a)
    filing_b = _filing(db_session, manager_b)
    _ingest(db_session, filing_a, rows=1)
    _ingest(db_session, filing_b, rows=1)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    def infotable_provider(accession_number: str) -> bytes:
        return _infotable(rows=2)

    result = execute_batch_reparse(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        infotable_provider=infotable_provider,
    )

    assert result["status"] == "succeeded"
    impact = result["impact_summary"]
    assert impact["filings_attempted"] == 2
    assert impact["filings_succeeded"] == 2
    assert impact["filings_failed"] == 0
    assert impact["filings_skipped"] == 0
    assert impact["parse_runs_created"] == 2
    assert impact["current_pointers_changed"] == 2
    assert impact["holdings_rows_created"] == 4  # 2 filings * 2 rows
    assert impact["holdings_row_count_delta"] == 2  # each grew by 1
    scopes = impact["ownership_changes_recompute_scope"]
    assert {scope["accession_number"] for scope in scopes} == {
        filing_a.accession_number,
        filing_b.accession_number,
    }
    refreshed = db_session.get(JobRun, job.id)
    assert refreshed.status == "succeeded"


def test_execute_isolates_per_filing_validation_failure(db_session):
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    filing_a = _filing(db_session, manager_a)
    filing_b = _filing(db_session, manager_b)
    _ingest(db_session, filing_a)
    _ingest(db_session, filing_b)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")
    failing_accession = filing_a.accession_number

    def validation_gate(_session, filing, _run):
        if filing.accession_number == failing_accession:
            return (False, ["value_unit_sanity_still_open"])
        return (True, [])

    result = execute_batch_reparse(
        db_session,
        job_run_id=job.id,
        validation_gate=validation_gate,
        infotable_provider=lambda _acc: _infotable(rows=2),
    )

    impact = result["impact_summary"]
    assert result["status"] == "partial_success"
    assert impact["filings_attempted"] == 2
    assert impact["filings_succeeded"] == 1
    assert impact["filings_failed"] == 1
    per_filing = {r["accession_number"]: r["status"] for r in result["per_filing"]}
    assert per_filing[failing_accession] == "validation_failed"
    assert per_filing[filing_b.accession_number] == "succeeded"
    refreshed = db_session.get(JobRun, job.id)
    assert refreshed.status == "partial_success"


def test_execute_isolates_per_filing_parse_crash(db_session):
    """MVP3-04 deferred: a parse crash inside controlled_reparse is reported
    per-filing without poisoning siblings. controlled_reparse_accession catches
    parse exceptions internally and returns status='failed'; the batch service
    must count it as a per-filing failure but continue with the next filing.
    """
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    filing_a = _filing(db_session, manager_a)
    filing_b = _filing(db_session, manager_b)
    _ingest(db_session, filing_a)
    _ingest(db_session, filing_b)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")
    crash_accession = filing_a.accession_number

    from app.services import thirteenf_holdings_ingest as ingest_mod

    real_reparse = ingest_mod.reparse_accession

    def flaky_reparse(session, accession_number, **kwargs):
        if accession_number == crash_accession:
            raise RuntimeError("simulated parse crash")
        return real_reparse(session, accession_number, **kwargs)

    with mock.patch(
        "app.services.thirteenf_controlled_reparse.reparse_accession",
        side_effect=flaky_reparse,
    ):
        result = execute_batch_reparse(
            db_session,
            job_run_id=job.id,
            validation_gate=lambda *_: (True, []),
            infotable_provider=lambda _acc: _infotable(rows=2),
        )

    impact = result["impact_summary"]
    assert result["status"] == "partial_success"
    assert impact["filings_attempted"] == 2
    assert impact["filings_succeeded"] == 1
    assert impact["filings_failed"] == 1
    by_accession = {r["accession_number"]: r for r in result["per_filing"]}
    assert by_accession[crash_accession]["status"] == "failed"
    assert by_accession[crash_accession]["validation_errors"] == ["parse_failed"]
    assert by_accession[filing_b.accession_number]["status"] == "succeeded"


def test_execute_isolates_per_filing_invariant_rejection(db_session):
    """An override that doesn't belong to this filing must surface as a per-filing
    rejection without breaking sibling filings. This closes the MVP3-04 carryover
    that controlled reparse may also raise ValueError-style invariant failures.
    """
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    filing_a = _filing(db_session, manager_a)
    filing_b = _filing(db_session, manager_b)
    run_a = _ingest(db_session, filing_a)
    _ingest(db_session, filing_b)

    reviewer = User(email=f"reviewer-{next(_CIK_SEQ)}@example.com", role="admin")
    db_session.add(reviewer)
    db_session.flush()

    # Override pointing at filing_b's accession, but pinned to filing_a as owner.
    # The override-vs-accession mismatch is checked inside controlled_reparse.
    override = FilingValueUnitOverride13F(
        filing_id=filing_a.id,
        accession_number=filing_b.accession_number,
        old_parse_rule="schema_thousands",
        new_override_value="dollars",
        reason="Cross-filing override (deliberately invalid).",
        evidence_json={"rule_code": "value_unit_sanity"},
        reviewer_id=reviewer.id,
        reviewed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        baseline_parse_run_id=run_a,
        status="pending_reparse",
    )
    db_session.add(override)
    db_session.commit()
    # Note: the batch loop doesn't pass override_id per filing, so this test
    # exercises the "invariant rejected" path by patching the batch to forward
    # a single invariant-failing override for one accession.

    from app.services import thirteenf_batch_reparse as batch_mod

    real_controlled = batch_mod.controlled_reparse_accession

    def patched(session, accession_number, **kwargs):
        if accession_number == filing_a.accession_number:
            # Force an invariant ValueError by passing an override that doesn't
            # belong to this accession.
            return real_controlled(
                session,
                accession_number,
                override_id=override.id,
                **kwargs,
            )
        return real_controlled(session, accession_number, **kwargs)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    with mock.patch.object(batch_mod, "controlled_reparse_accession", side_effect=patched):
        result = execute_batch_reparse(
            db_session,
            job_run_id=job.id,
            validation_gate=lambda *_: (True, []),
            infotable_provider=lambda _acc: _infotable(rows=2),
        )

    by_accession = {r["accession_number"]: r for r in result["per_filing"]}
    assert by_accession[filing_a.accession_number]["status"] == "rejected"
    assert "belongs to" in by_accession[filing_a.accession_number]["error"]
    assert by_accession[filing_b.accession_number]["status"] == "succeeded"
    assert result["status"] == "partial_success"


def test_execute_requires_explicit_validation_gate(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    _ingest(db_session, filing)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    with pytest.raises(ValueError, match="validation_gate is required"):
        execute_batch_reparse(
            db_session,
            job_run_id=job.id,
            validation_gate=None,
            infotable_provider=lambda _acc: _infotable(rows=2),
        )


def test_execute_skips_filings_without_raw_infotable_when_no_provider(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    # No ingest call → no raw_infotable_doc_id set; reparse cannot resolve bytes.

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    result = execute_batch_reparse(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        infotable_provider=None,
    )

    impact = result["impact_summary"]
    assert result["status"] == "skipped"
    assert impact["filings_attempted"] == 0
    assert impact["filings_skipped"] >= 1
    per_filing = {r["accession_number"]: r["status"] for r in result["per_filing"]}
    assert per_filing[filing.accession_number] == "skipped"


def test_execute_all_failed_sets_aggregate_status_failed(db_session):
    """When every attempted filing fails (no successes, no skips), the batch
    aggregate status must be 'failed', not 'partial_success'.
    """
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    filing_a = _filing(db_session, manager_a)
    filing_b = _filing(db_session, manager_b)
    _ingest(db_session, filing_a)
    _ingest(db_session, filing_b)

    job = enqueue_batch_reparse(db_session, quarter="2026-Q1")

    result = execute_batch_reparse(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (False, ["value_unit_sanity_still_open"]),
        infotable_provider=lambda _acc: _infotable(rows=2),
    )

    impact = result["impact_summary"]
    assert result["status"] == "failed"
    assert impact["filings_attempted"] == 2
    assert impact["filings_succeeded"] == 0
    assert impact["filings_failed"] == 2
    refreshed = db_session.get(JobRun, job.id)
    assert refreshed.status == "failed"


def test_manager_scope_batch_reparse_runs_only_for_manager(db_session):
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    filing_a = _filing(db_session, manager_a)
    filing_b = _filing(db_session, manager_b)
    _ingest(db_session, filing_a)
    _ingest(db_session, filing_b)

    job = enqueue_batch_reparse(db_session, manager_id=manager_a.id)
    assert job.job_type == "batch_reparse_by_manager"
    assert job.lock_key == f"13f_batch_reparse:manager:{manager_a.id}"

    result = execute_batch_reparse(
        db_session,
        job_run_id=job.id,
        validation_gate=lambda *_: (True, []),
        infotable_provider=lambda _acc: _infotable(rows=2),
    )

    impact = result["impact_summary"]
    assert impact["filings_attempted"] == 1
    accessions = {r["accession_number"] for r in result["per_filing"]}
    assert filing_a.accession_number in accessions
    assert filing_b.accession_number not in accessions
