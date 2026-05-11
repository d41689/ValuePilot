"""MVP3 controlled 13F reparse contract.

This module wraps the existing audit-preserving single-accession reparse path
with validation-gated activation semantics and a structured before/after impact
summary. It intentionally does not implement batch reparse or admin API/UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.institutions import (
    Filing13F,
    FilingValueUnitOverride13F,
    Holding13F,
    OwnershipChange13F,
    ParseRun13F,
    QualityFinding13F,
)
from app.services.thirteenf_holdings_ingest import reparse_accession

ValidationGate = Callable[[Session, Filing13F, ParseRun13F], bool | tuple[bool, list[str]]]


@dataclass(frozen=True)
class ControlledReparseResult:
    status: str
    accession_number: str
    old_parse_run_id: int | None
    new_parse_run_id: int | None
    impact_summary: dict[str, Any]
    validation_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "accession_number": self.accession_number,
            "old_parse_run_id": self.old_parse_run_id,
            "new_parse_run_id": self.new_parse_run_id,
            "impact_summary": self.impact_summary,
            "validation_errors": self.validation_errors,
        }


def controlled_reparse_accession(
    session: Session,
    accession_number: str,
    *,
    infotable_bytes: bytes | None = None,
    override_id: int | None = None,
    validation_gate: ValidationGate | None = None,
) -> ControlledReparseResult:
    """Run a validation-gated single-accession reparse.

    The existing parser path creates and audits the new parse_run. This wrapper
    records impact, reverts current-pointer activation when validation fails, and
    applies a filing-level value-unit override only after the controlled reparse
    succeeds.
    """
    if validation_gate is None:
        raise ValueError("validation_gate is required for controlled reparse")

    filing = _filing_for_accession(session, accession_number)
    before = _snapshot(session, filing)
    override = _override_for_id(session, override_id) if override_id is not None else None

    if override is not None and override.accession_number != accession_number:
        raise ValueError(
            f"Override {override_id} belongs to {override.accession_number!r}, "
            f"not {accession_number!r}."
        )
    if override is not None and override.status != "pending_reparse":
        raise ValueError(
            f"Override {override_id} has status {override.status!r}; "
            "only 'pending_reparse' overrides may be applied."
        )

    try:
        result = reparse_accession(session, accession_number, infotable_bytes=infotable_bytes)
    except Exception:
        after_failure = _snapshot(session, filing)
        if override is not None:
            override.status = "reparse_failed"
            session.add(override)
            session.commit()
        return ControlledReparseResult(
            status="failed",
            accession_number=accession_number,
            old_parse_run_id=before["current_parse_run_id"],
            new_parse_run_id=None,
            impact_summary=_impact_summary(filing, before, after_failure),
            validation_errors=["parse_failed"],
        )

    new_run = session.get(ParseRun13F, result["parse_run_id"])
    if new_run is None:
        raise RuntimeError(f"Controlled reparse did not persist parse_run {result['parse_run_id']}")
    new_run_holdings_count = _holdings_count_for_parse_run(session, new_run.id)

    gate_passed, validation_errors = _run_validation_gate(validation_gate, session, filing, new_run)
    if not gate_passed:
        _restore_current_pointer(session, before["current_parse_run_id"], new_run.id)
        if override is not None:
            override.status = "reparse_failed"
            override.result_parse_run_id = new_run.id
            session.add(override)
        session.commit()
        after_validation_failure = _snapshot(session, filing)
        return ControlledReparseResult(
            status="validation_failed",
            accession_number=accession_number,
            old_parse_run_id=before["current_parse_run_id"],
            new_parse_run_id=new_run.id,
            impact_summary=_impact_summary(
                filing,
                before,
                after_validation_failure,
                new_parse_run_id=new_run.id,
                new_parse_run_holdings_count=new_run_holdings_count,
            ),
            validation_errors=validation_errors,
        )

    if override is not None:
        filing.effective_value_unit_override = override.new_override_value
        filing.effective_value_unit_override_id = override.id
        override.status = "applied"
        override.result_parse_run_id = new_run.id
        session.add_all([filing, override])

    session.commit()

    after = _snapshot(session, filing)
    return ControlledReparseResult(
        status="succeeded",
        accession_number=accession_number,
        old_parse_run_id=before["current_parse_run_id"],
        new_parse_run_id=new_run.id,
        impact_summary=_impact_summary(
            filing,
            before,
            after,
            new_parse_run_id=new_run.id,
            new_parse_run_holdings_count=new_run_holdings_count,
        ),
        validation_errors=[],
    )


def _filing_for_accession(session: Session, accession_number: str) -> Filing13F:
    filing = session.query(Filing13F).filter(Filing13F.accession_number == accession_number).one_or_none()
    if filing is None:
        raise ValueError(f"Filing not found for accession: {accession_number}")
    return filing


def _override_for_id(session: Session, override_id: int) -> FilingValueUnitOverride13F:
    override = session.get(FilingValueUnitOverride13F, override_id)
    if override is None:
        raise ValueError(f"Filing value-unit override not found: {override_id}")
    return override


def _run_validation_gate(
    validation_gate: ValidationGate,
    session: Session,
    filing: Filing13F,
    parse_run: ParseRun13F,
) -> tuple[bool, list[str]]:
    result = validation_gate(session, filing, parse_run)
    if isinstance(result, tuple):
        passed, errors = result
        return bool(passed), list(errors or [])
    return bool(result), []


def _restore_current_pointer(
    session: Session,
    old_parse_run_id: int | None,
    new_parse_run_id: int,
) -> None:
    # Demote before promote: the non-deferrable partial unique index on
    # (accession_number WHERE is_current) fires at flush time, so the new run
    # must be deactivated before the old run is reactivated.
    new_run = session.get(ParseRun13F, new_parse_run_id)
    if new_run is not None:
        new_run.is_current = False
        session.add(new_run)
        session.flush()
    if old_parse_run_id is not None:
        old_run = session.get(ParseRun13F, old_parse_run_id)
        if old_run is not None:
            old_run.is_current = True
            session.add(old_run)
            session.flush()


def _snapshot(session: Session, filing: Filing13F) -> dict[str, Any]:
    current_run = (
        session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number == filing.accession_number)
        .filter(ParseRun13F.is_current.is_(True))
        .one_or_none()
    )
    current_parse_run_id = current_run.id if current_run is not None else None
    holdings_count = (
        session.query(Holding13F).filter(Holding13F.parse_run_id == current_parse_run_id).count()
        if current_parse_run_id is not None
        else 0
    )
    open_findings_count = (
        session.query(QualityFinding13F)
        .filter(QualityFinding13F.accession_number == filing.accession_number)
        .filter(QualityFinding13F.status == "open")
        .count()
    )
    ownership_changes_count = (
        session.query(OwnershipChange13F)
        .filter(OwnershipChange13F.current_filing_id == filing.id)
        .count()
    )
    return {
        "current_parse_run_id": current_parse_run_id,
        "holdings_count": holdings_count,
        "filing_parse_status": filing.parse_status,
        "open_quality_findings_count": open_findings_count,
        "ownership_changes_count": ownership_changes_count,
    }


def _holdings_count_for_parse_run(session: Session, parse_run_id: int) -> int:
    return session.query(Holding13F).filter(Holding13F.parse_run_id == parse_run_id).count()


def _impact_summary(
    filing: Filing13F,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    new_parse_run_id: int | None = None,
    new_parse_run_holdings_count: int | None = None,
) -> dict[str, Any]:
    before_holdings = int(before["holdings_count"] or 0)
    after_holdings = int(after["holdings_count"] or 0)
    # Kept separate from current holdings because validation failure restores the
    # old current pointer while retaining the audited candidate parse run.
    holdings_rows_created = new_parse_run_holdings_count if new_parse_run_id is not None else after_holdings
    return {
        "filings_affected": 1,
        "parse_runs_created": 1 if new_parse_run_id is not None else 0,
        "current_pointers_changed": 1 if before["current_parse_run_id"] != after["current_parse_run_id"] else 0,
        "holdings_rows_before": before_holdings,
        "holdings_rows_after": after_holdings,
        "holdings_rows_created": holdings_rows_created,
        "holdings_row_count_delta": abs(holdings_rows_created - before_holdings),
        "ownership_changes_recompute_count": int(before["ownership_changes_count"] or 0),
        "ownership_changes_recompute_scope": {
            "manager_id": filing.manager_id,
            "report_quarter": filing.report_quarter,
            "accession_number": filing.accession_number,
        },
        "readiness_level_impact": {
            "parse_status_before": before["filing_parse_status"],
            "parse_status_after": after["filing_parse_status"],
        },
        "quality_finding_delta": {
            "open_before": before["open_quality_findings_count"],
            "open_after": after["open_quality_findings_count"],
            "delta": after["open_quality_findings_count"] - before["open_quality_findings_count"],
        },
    }
