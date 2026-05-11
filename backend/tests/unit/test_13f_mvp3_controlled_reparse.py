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
    ParseRun13F,
)
from app.models.users import User
from app.services.thirteenf_holdings_ingest import ingest_holdings_for_filing
from app.services.thirteenf_controlled_reparse import controlled_reparse_accession


_CIK_SEQ = count(9900000000)


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ)).zfill(10)
    manager = InstitutionManager(
        canonical_name=f"Controlled Reparse Manager {cik}",
        legal_name=f"Controlled Reparse Manager {cik}",
        edgar_legal_name=f"Controlled Reparse Manager {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _reviewer(db_session) -> User:
    user = User(email=f"controlled-reparse-{next(_CIK_SEQ)}@example.com", role="admin")
    db_session.add(user)
    db_session.flush()
    return user


def _filing(db_session, manager: InstitutionManager, accession: str) -> Filing13F:
    filing = Filing13F(
        manager_id=manager.id,
        cik=manager.cik,
        accession_no=accession,
        accession_number=accession,
        form_type="13F-HR",
        period_of_report=date(2026, 3, 31),
        filed_at=date(2026, 5, 15),
        filing_date=date(2026, 5, 15),
        accepted_at=datetime(2026, 5, 15, 17, tzinfo=timezone.utc),
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        is_active_for_manager_period=True,
        parse_status="succeeded",
        report_type="holdings_report",
        coverage_completeness="complete",
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _override(db_session, filing: Filing13F, reviewer: User, baseline_run: ParseRun13F) -> FilingValueUnitOverride13F:
    row = FilingValueUnitOverride13F(
        filing_id=filing.id,
        accession_number=filing.accession_number,
        old_parse_rule="schema_thousands",
        new_override_value="dollars",
        reason="Value unit sanity finding indicates dollar-denominated values.",
        evidence_json={"rule_code": "value_unit_sanity"},
        reviewer_id=reviewer.id,
        reviewed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        baseline_parse_run_id=baseline_run.id,
        status="pending_reparse",
    )
    db_session.add(row)
    db_session.flush()
    return row


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


def test_controlled_reparse_success_applies_override_and_returns_impact_summary(db_session):
    manager = _manager(db_session)
    reviewer = _reviewer(db_session)
    filing = _filing(db_session, manager, "0009900001-26-000001")
    initial = ingest_holdings_for_filing(db_session, filing, _infotable(rows=1))
    baseline_run = db_session.get(ParseRun13F, initial["parse_run_id"])
    override = _override(db_session, filing, reviewer, baseline_run)

    result = controlled_reparse_accession(
        db_session,
        filing.accession_number,
        infotable_bytes=_infotable(rows=2),
        override_id=override.id,
        validation_gate=lambda *_: (True, []),
    )
    db_session.expire_all()

    refreshed_filing = db_session.get(Filing13F, filing.id)
    refreshed_override = db_session.get(FilingValueUnitOverride13F, override.id)
    old_run = db_session.get(ParseRun13F, baseline_run.id)
    new_run = db_session.get(ParseRun13F, result.new_parse_run_id)

    assert result.status == "succeeded"
    assert result.impact_summary["filings_affected"] == 1
    assert result.impact_summary["parse_runs_created"] == 1
    assert result.impact_summary["current_pointers_changed"] == 1
    assert result.impact_summary["holdings_rows_before"] == 1
    assert result.impact_summary["holdings_rows_after"] == 2
    assert result.impact_summary["holdings_row_count_delta"] == 1
    assert result.impact_summary["ownership_changes_recompute_scope"] == {
        "manager_id": manager.id,
        "report_quarter": "2026-Q1",
        "accession_number": filing.accession_number,
    }
    assert old_run.is_current is False
    assert new_run.is_current is True
    assert refreshed_filing.effective_value_unit_override == "dollars"
    assert refreshed_filing.effective_value_unit_override_id == override.id
    assert refreshed_override.status == "applied"
    assert refreshed_override.result_parse_run_id == new_run.id


def test_controlled_reparse_requires_explicit_validation_gate(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0009900001-26-000003")
    initial = ingest_holdings_for_filing(db_session, filing, _infotable(rows=1))

    with pytest.raises(ValueError, match="validation_gate is required"):
        controlled_reparse_accession(
            db_session,
            filing.accession_number,
            infotable_bytes=_infotable(rows=2),
        )

    runs = db_session.query(ParseRun13F).filter_by(accession_number=filing.accession_number).all()
    assert [run.id for run in runs] == [initial["parse_run_id"]]


def test_controlled_reparse_validation_failure_restores_old_current_and_marks_override_failed(db_session):
    manager = _manager(db_session)
    reviewer = _reviewer(db_session)
    filing = _filing(db_session, manager, "0009900001-26-000002")
    initial = ingest_holdings_for_filing(db_session, filing, _infotable(rows=1))
    baseline_run = db_session.get(ParseRun13F, initial["parse_run_id"])
    override = _override(db_session, filing, reviewer, baseline_run)

    result = controlled_reparse_accession(
        db_session,
        filing.accession_number,
        infotable_bytes=_infotable(rows=2),
        override_id=override.id,
        validation_gate=lambda *_: (False, ["value_unit_sanity_still_open"]),
    )
    db_session.expire_all()

    refreshed_filing = db_session.get(Filing13F, filing.id)
    refreshed_override = db_session.get(FilingValueUnitOverride13F, override.id)
    old_run = db_session.get(ParseRun13F, baseline_run.id)
    new_run = db_session.get(ParseRun13F, result.new_parse_run_id)
    new_holdings = db_session.query(Holding13F).filter_by(parse_run_id=new_run.id).count()

    assert result.status == "validation_failed"
    assert result.validation_errors == ["value_unit_sanity_still_open"]
    assert result.impact_summary["parse_runs_created"] == 1
    assert result.impact_summary["current_pointers_changed"] == 0
    assert result.impact_summary["holdings_rows_before"] == 1
    assert result.impact_summary["holdings_rows_after"] == 1
    assert result.impact_summary["holdings_rows_created"] == 2
    assert result.impact_summary["holdings_row_count_delta"] == 1
    assert old_run.is_current is True
    assert new_run.is_current is False
    assert new_holdings == 2
    assert refreshed_filing.effective_value_unit_override == "infer"
    assert refreshed_filing.effective_value_unit_override_id is None
    assert refreshed_override.status == "reparse_failed"
    assert refreshed_override.result_parse_run_id == new_run.id


def test_controlled_reparse_success_without_override_commits_new_parse_run(db_session):
    manager = _manager(db_session)
    filing = _filing(db_session, manager, "0009900001-26-000004")
    initial = ingest_holdings_for_filing(db_session, filing, _infotable(rows=1))
    baseline_run = db_session.get(ParseRun13F, initial["parse_run_id"])

    result = controlled_reparse_accession(
        db_session,
        filing.accession_number,
        infotable_bytes=_infotable(rows=2),
        validation_gate=lambda *_: (True, []),
    )
    db_session.expire_all()

    old_run = db_session.get(ParseRun13F, baseline_run.id)
    new_run = db_session.get(ParseRun13F, result.new_parse_run_id)

    assert result.status == "succeeded"
    assert result.new_parse_run_id is not None
    assert old_run.is_current is False
    assert new_run.is_current is True


def test_controlled_reparse_parse_crash_marks_override_failed_and_preserves_old_current(db_session):
    manager = _manager(db_session)
    reviewer = _reviewer(db_session)
    filing = _filing(db_session, manager, "0009900001-26-000005")
    initial = ingest_holdings_for_filing(db_session, filing, _infotable(rows=1))
    baseline_run = db_session.get(ParseRun13F, initial["parse_run_id"])
    override = _override(db_session, filing, reviewer, baseline_run)

    with mock.patch(
        "app.services.thirteenf_controlled_reparse.reparse_accession",
        side_effect=RuntimeError("simulated parse crash"),
    ):
        result = controlled_reparse_accession(
            db_session,
            filing.accession_number,
            infotable_bytes=_infotable(rows=2),
            override_id=override.id,
            validation_gate=lambda *_: (True, []),
        )

    db_session.expire_all()
    refreshed_override = db_session.get(FilingValueUnitOverride13F, override.id)
    old_run = db_session.get(ParseRun13F, baseline_run.id)

    assert result.status == "failed"
    assert result.new_parse_run_id is None
    assert result.validation_errors == ["parse_failed"]
    assert old_run.is_current is True
    assert refreshed_override.status == "reparse_failed"
    assert refreshed_override.result_parse_run_id is None


def test_controlled_reparse_rejects_non_pending_override(db_session):
    manager = _manager(db_session)
    reviewer = _reviewer(db_session)
    filing = _filing(db_session, manager, "0009900001-26-000006")
    initial = ingest_holdings_for_filing(db_session, filing, _infotable(rows=1))
    baseline_run = db_session.get(ParseRun13F, initial["parse_run_id"])
    override = _override(db_session, filing, reviewer, baseline_run)
    override.status = "applied"
    db_session.add(override)
    db_session.flush()

    with pytest.raises(ValueError, match="pending_reparse"):
        controlled_reparse_accession(
            db_session,
            filing.accession_number,
            infotable_bytes=_infotable(rows=2),
            override_id=override.id,
            validation_gate=lambda *_: (True, []),
        )


def test_controlled_reparse_rejects_override_belonging_to_different_filing(db_session):
    manager_a = _manager(db_session)
    manager_b = _manager(db_session)
    reviewer = _reviewer(db_session)
    filing_a = _filing(db_session, manager_a, "0009900001-26-000007")
    filing_b = _filing(db_session, manager_b, "0009900001-26-000008")
    initial_a = ingest_holdings_for_filing(db_session, filing_a, _infotable(rows=1))
    ingest_holdings_for_filing(db_session, filing_b, _infotable(rows=1))
    baseline_run_a = db_session.get(ParseRun13F, initial_a["parse_run_id"])
    override_for_a = _override(db_session, filing_a, reviewer, baseline_run_a)

    with pytest.raises(ValueError, match="belongs to"):
        controlled_reparse_accession(
            db_session,
            filing_b.accession_number,
            infotable_bytes=_infotable(rows=2),
            override_id=override_for_a.id,
            validation_gate=lambda *_: (True, []),
        )
