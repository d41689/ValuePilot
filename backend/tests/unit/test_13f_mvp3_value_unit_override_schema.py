from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect

from app.models.institutions import (
    FILING_VALUE_UNIT_OVERRIDE_STATUSES,
    Filing13F,
    FilingValueUnitOverride13F,
    InstitutionManager,
    ParseRun13F,
    VALUE_UNIT_OVERRIDES,
)
from app.models.users import User


def _manager(db_session) -> InstitutionManager:
    manager = InstitutionManager(
        canonical_name="MVP 3 Manager",
        legal_name="MVP 3 Manager",
        cik="0009000303",
        status="active",
        match_status="confirmed",
        value_unit_override="infer",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _filing(db_session, manager: InstitutionManager) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no="0009000303-26-000001",
        accession_number="0009000303-26-000001",
        cik=manager.cik,
        period_of_report=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        form_type="13F-HR",
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        parse_status="succeeded",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _reviewer(db_session) -> User:
    user = User(email="mvp3-reviewer@example.com", role="admin")
    db_session.add(user)
    db_session.flush()
    return user


def _parse_run(
    db_session,
    filing: Filing13F,
    *,
    status: str = "succeeded",
    is_current: bool = False,
) -> ParseRun13F:
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="13f-parser-test",
        fingerprint_version="v1",
        status=status,
        is_current=is_current,
    )
    db_session.add(parse_run)
    db_session.flush()
    return parse_run


def _override(db_session, filing: Filing13F, **overrides) -> FilingValueUnitOverride13F:
    reviewer = overrides.pop("reviewer", None) or _reviewer(db_session)
    payload = {
        "filing_id": filing.id,
        "accession_number": filing.accession_number,
        "old_parse_rule": "header_total_value_thousands",
        "new_override_value": "dollars",
        "reason": "Header total shows dollar-denominated values.",
        "evidence_json": {
            "source": "admin_review",
            "reported_total_value_thousands": 123_456_789,
            "computed_total_value_thousands": 123_456,
        },
        "reviewer_id": reviewer.id,
        "reviewed_at": datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        "status": "pending_reparse",
    }
    payload.update(overrides)
    row = FilingValueUnitOverride13F(**payload)
    db_session.add(row)
    db_session.flush()
    return row


def test_value_unit_override_schema_columns_and_indexes_exist(db_session):
    inspector = inspect(db_session.bind)

    filing_columns = {column["name"] for column in inspector.get_columns("filings_13f")}
    assert {
        "effective_value_unit_override",
        "effective_value_unit_override_id",
    } <= filing_columns

    override_columns = {column["name"] for column in inspector.get_columns("filing_value_unit_overrides")}
    assert {
        "id",
        "filing_id",
        "accession_number",
        "old_parse_rule",
        "new_override_value",
        "reason",
        "evidence_json",
        "reviewer_id",
        "reviewed_at",
        "baseline_parse_run_id",
        "result_parse_run_id",
        "status",
        "created_at",
        "updated_at",
    } <= override_columns

    filing_indexes = {index["name"] for index in inspector.get_indexes("filings_13f")}
    assert "ix_filings_13f_effective_value_unit_override" in filing_indexes

    override_indexes = {index["name"] for index in inspector.get_indexes("filing_value_unit_overrides")}
    assert "ix_filing_value_unit_overrides_filing_id" in override_indexes
    assert "ix_filing_value_unit_overrides_accession" in override_indexes
    assert "ix_filing_value_unit_overrides_status" in override_indexes
    assert "ix_filing_value_unit_overrides_reviewed_at" in override_indexes


@pytest.mark.parametrize("override_value", sorted(VALUE_UNIT_OVERRIDES))
def test_filing_effective_value_unit_override_accepts_prd_values(override_value):
    filing = Filing13F(
        manager_id=1,
        accession_no="0000000001-26-000001",
        period_of_report=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        form_type="13F-HR",
        effective_value_unit_override=override_value,
    )

    assert filing.effective_value_unit_override == override_value


@pytest.mark.parametrize("status", sorted(FILING_VALUE_UNIT_OVERRIDE_STATUSES))
def test_filing_value_unit_override_status_accepts_contract_values(status):
    row = FilingValueUnitOverride13F(
        filing_id=1,
        accession_number="0000000001-26-000001",
        new_override_value="dollars",
        reason="Admin reviewed value units.",
        reviewer_id=1,
        reviewed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        status=status,
    )

    assert row.status == status


def test_filing_value_unit_override_rejects_unknown_values():
    with pytest.raises(ValueError):
        Filing13F(
            manager_id=1,
            accession_no="0000000001-26-000001",
            period_of_report=date(2026, 3, 31),
            filed_at=date(2026, 5, 15),
            form_type="13F-HR",
            effective_value_unit_override="auto_fix",
        )

    with pytest.raises(ValueError):
        FilingValueUnitOverride13F(
            filing_id=1,
            accession_number="0000000001-26-000001",
            new_override_value="auto_fix",
            reason="Invalid override.",
            reviewer_id=1,
            reviewed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
            status="pending_reparse",
        )

    with pytest.raises(ValueError):
        FilingValueUnitOverride13F(
            filing_id=1,
            accession_number="0000000001-26-000001",
            new_override_value="dollars",
            reason="Invalid status.",
            reviewer_id=1,
            reviewed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
            status="silently_applied",
        )


def test_filing_level_override_audit_pointer_does_not_change_manager_override(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    baseline_run = _parse_run(db_session, filing, status="succeeded", is_current=True)
    result_run = _parse_run(db_session, filing, status="succeeded")
    override = _override(
        db_session,
        filing,
        baseline_parse_run_id=baseline_run.id,
        result_parse_run_id=result_run.id,
        status="applied",
    )

    filing.effective_value_unit_override = "dollars"
    filing.effective_value_unit_override_id = override.id
    db_session.flush()
    db_session.expire_all()

    persisted_filing = db_session.get(Filing13F, filing.id)
    persisted_manager = db_session.get(InstitutionManager, manager.id)
    persisted_override = db_session.get(FilingValueUnitOverride13F, override.id)

    assert persisted_filing.effective_value_unit_override == "dollars"
    assert persisted_filing.effective_value_unit_override_id == persisted_override.id
    assert persisted_manager.value_unit_override == "infer"
    assert persisted_override.accession_number == filing.accession_number
    assert persisted_override.evidence_json["source"] == "admin_review"
    assert persisted_override.baseline_parse_run_id == baseline_run.id
    assert persisted_override.result_parse_run_id == result_run.id
    assert persisted_filing.effective_value_unit_override_event.id == persisted_override.id
    assert persisted_filing.override_events[0].id == persisted_override.id


def test_filing_value_unit_override_requires_reviewer(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)

    with pytest.raises(ValueError):
        FilingValueUnitOverride13F(
            filing_id=filing.id,
            accession_number=filing.accession_number,
            old_parse_rule="header_total_value_thousands",
            new_override_value="dollars",
            reason="Missing reviewer should fail.",
            reviewer_id=None,
            reviewed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
            status="pending_reparse",
        )


def test_filing_delete_cascades_override_events_with_effective_pointer(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager)
    override = _override(db_session, filing)
    filing.effective_value_unit_override = "dollars"
    filing.effective_value_unit_override_id = override.id
    db_session.flush()

    filing_id = filing.id
    override_id = override.id
    db_session.delete(filing)
    db_session.flush()

    assert db_session.get(Filing13F, filing_id) is None
    assert db_session.get(FilingValueUnitOverride13F, override_id) is None
