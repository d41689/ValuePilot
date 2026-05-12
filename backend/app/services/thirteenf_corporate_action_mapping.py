"""MVP3-06 corporate-action temporal CUSIP mapping contract.

D4 (decision-gate): MVP 3 corporate-action temporal mapping requires manual admin
confirmation. OpenFIGI metadata and SEC issuer data may be shown as supporting
evidence, but no source may auto-confirm.

This service exposes two operations:

- ``preview_corporate_action_confirmation`` — pure read; returns the count and
  sample of ``ownership_changes`` rows that would be flagged for recomputation
  if a given effective-quarter window were confirmed for a CUSIP.
- ``confirm_corporate_action_mapping`` — inserts a new ``cusip_ticker_map`` row
  with ``mapping_status='confirmed'``, optionally supersedes a prior mapping by
  setting its ``effective_to_quarter`` and flipping its status, and persists an
  audit trail (one ``QualityReport13F`` + per-affected-row ``QualityFinding13F``)
  so downstream recompute pipelines can pick the work up.

The service explicitly does **not** mutate historical ``ownership_changes`` rows
(``change_status``, ``current_value_usd``, ``shares``, weights) — that contradicts
D4's silent-rewrite prohibition. Recomputation is the responsibility of
MVP3-05 controlled / batch reparse or future MVP2 ownership-change recompute jobs,
keyed off the findings written here.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.institutions import (
    CusipTickerMap,
    OwnershipChange13F,
    QualityFinding13F,
    QualityReport13F,
)

logger = logging.getLogger(__name__)

CORPORATE_ACTION_RULE_CODE = "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"
_QUALITY_REPORT_STATUS = "warning"
_PREVIEW_SAMPLE_LIMIT = 25


class CorporateActionMappingError(ValueError):
    """Raised when a corporate-action confirmation rejects an invariant."""


def preview_corporate_action_confirmation(
    session: Session,
    *,
    cusip: str,
    effective_from_quarter: str,
    effective_to_quarter: str | None = None,
) -> dict[str, Any]:
    """Pure read: report affected ownership_changes and existing-overlap diagnostics.

    Does not mutate ``cusip_ticker_map``, ``ownership_changes``, or any quality
    table. Callers can use this to render an admin-review screen before invoking
    ``confirm_corporate_action_mapping``.
    """
    cusip = _validate_canonical_cusip(cusip)
    _validate_quarter_string(effective_from_quarter, field="effective_from_quarter")
    if effective_to_quarter is not None:
        _validate_quarter_string(effective_to_quarter, field="effective_to_quarter")
        _ensure_quarter_order(effective_from_quarter, effective_to_quarter)

    affected_query = _affected_ownership_changes_query(
        session,
        cusip=cusip,
        effective_from_quarter=effective_from_quarter,
        effective_to_quarter=effective_to_quarter,
    )
    affected_total = affected_query.count()
    sample = (
        affected_query
        .order_by(OwnershipChange13F.report_quarter.asc(), OwnershipChange13F.id.asc())
        .limit(_PREVIEW_SAMPLE_LIMIT)
        .all()
    )
    overlap_candidates = _overlapping_mappings(
        session,
        cusip=cusip,
        effective_from_quarter=effective_from_quarter,
        effective_to_quarter=effective_to_quarter,
        exclude_mapping_id=None,
    )
    return {
        "cusip": cusip,
        "effective_from_quarter": effective_from_quarter,
        "effective_to_quarter": effective_to_quarter,
        "affected_ownership_changes_count": affected_total,
        "affected_ownership_changes_sample": [
            {
                "id": row.id,
                "manager_id": row.manager_id,
                "report_quarter": row.report_quarter,
                "current_cusip": row.current_cusip,
                "previous_cusip": row.previous_cusip,
                "change_status": row.change_status,
            }
            for row in sample
        ],
        "overlapping_mapping_ids": [m.id for m in overlap_candidates],
    }


def confirm_corporate_action_mapping(
    session: Session,
    *,
    cusip: str,
    new_ticker: str | None,
    new_issuer_name: str | None,
    effective_from_quarter: str,
    effective_to_quarter: str | None = None,
    evidence_url: str,
    reason: str,
    reviewer_id: int,
    prior_mapping_id: int | None = None,
) -> dict[str, Any]:
    """Manually confirm a corporate-action temporal mapping for ``cusip``."""
    cusip = _validate_canonical_cusip(cusip)
    _validate_quarter_string(effective_from_quarter, field="effective_from_quarter")
    if effective_to_quarter is not None:
        _validate_quarter_string(effective_to_quarter, field="effective_to_quarter")
        _ensure_quarter_order(effective_from_quarter, effective_to_quarter)
    if not evidence_url or not evidence_url.strip():
        raise CorporateActionMappingError(
            "evidence_url is required for corporate-action confirmation (D4)."
        )
    if not reason or not reason.strip():
        raise CorporateActionMappingError(
            "reason is required for corporate-action confirmation (D4)."
        )

    # Serialize confirmations for the same canonical CUSIP. Reuses the same
    # 64-bit hashing strategy as the MVP1B enrichment path (PRD §14).
    lock_id = _cusip_lock_id(cusip)
    locked = session.execute(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": lock_id}).scalar()
    if not locked:
        raise CorporateActionMappingError(
            f"Could not acquire advisory lock for CUSIP {cusip}; retry in a moment."
        )

    prior_mapping: CusipTickerMap | None = None
    if prior_mapping_id is not None:
        prior_mapping = session.get(CusipTickerMap, prior_mapping_id)
        if prior_mapping is None or prior_mapping.cusip != cusip:
            raise CorporateActionMappingError(
                f"prior_mapping_id {prior_mapping_id} does not belong to CUSIP {cusip}."
            )
        if prior_mapping.mapping_status not in {"confirmed", "needs_review"}:
            raise CorporateActionMappingError(
                f"prior_mapping_id {prior_mapping_id} has mapping_status="
                f"{prior_mapping.mapping_status!r}; cannot supersede."
            )

    overlapping = _overlapping_mappings(
        session,
        cusip=cusip,
        effective_from_quarter=effective_from_quarter,
        effective_to_quarter=effective_to_quarter,
        exclude_mapping_id=prior_mapping.id if prior_mapping else None,
    )
    if overlapping:
        raise CorporateActionMappingError(
            f"CUSIP {cusip} new effective window "
            f"[{effective_from_quarter}, {effective_to_quarter or '∞'}] overlaps "
            f"existing confirmed/superseded mappings: {[m.id for m in overlapping]}."
        )

    now = datetime.now(timezone.utc)
    if prior_mapping is not None:
        prior_mapping.mapping_status = "superseded"
        prior_mapping.effective_to_quarter = _previous_quarter(effective_from_quarter)
        prior_mapping.updated_at = now
        session.add(prior_mapping)

    new_mapping = CusipTickerMap(
        cusip=cusip,
        ticker=new_ticker,
        issuer_name=new_issuer_name,
        source="manual",
        mapping_reason=reason.strip(),
        confidence="manual",
        evidence_url=evidence_url.strip(),
        mapping_status="confirmed",
        effective_from_quarter=effective_from_quarter,
        effective_to_quarter=effective_to_quarter,
        reviewed_by=reviewer_id,
        reviewed_at=now,
        is_active=True,
    )
    session.add(new_mapping)
    session.flush()

    affected_rows = (
        _affected_ownership_changes_query(
            session,
            cusip=cusip,
            effective_from_quarter=effective_from_quarter,
            effective_to_quarter=effective_to_quarter,
        )
        .all()
    )

    report = QualityReport13F(
        quarter=effective_from_quarter,
        status=_QUALITY_REPORT_STATUS,
        error_count=0,
        warning_count=len(affected_rows),
        info_count=0,
        summary=(
            f"Corporate-action mapping confirmed for CUSIP {cusip} "
            f"[{effective_from_quarter}, {effective_to_quarter or '∞'}]; "
            f"{len(affected_rows)} ownership_changes flagged for recomputation."
        ),
        issues_json=[
            {
                "cusip": cusip,
                "new_mapping_id": new_mapping.id,
                "prior_mapping_id": prior_mapping.id if prior_mapping else None,
                "effective_from_quarter": effective_from_quarter,
                "effective_to_quarter": effective_to_quarter,
                "reviewer_id": reviewer_id,
            }
        ],
        checked_at=now,
    )
    session.add(report)
    session.flush()

    for change in affected_rows:
        session.add(
            QualityFinding13F(
                validation_run_id=report.id,
                rule_code=CORPORATE_ACTION_RULE_CODE,
                severity="warning",
                entity_type="ownership_change",
                entity_id=change.id,
                quarter=change.report_quarter,
                manager_id=change.manager_id,
                accession_number=None,
                detail=(
                    f"CUSIP {cusip} corporate-action temporal mapping confirmed; "
                    "recomputation required."
                ),
                value_json={
                    "cusip": cusip,
                    "new_mapping_id": new_mapping.id,
                    "prior_mapping_id": prior_mapping.id if prior_mapping else None,
                    "current_cusip": change.current_cusip,
                    "previous_cusip": change.previous_cusip,
                    "report_quarter": change.report_quarter,
                },
                status="open",
                first_seen_at=now,
                last_seen_at=now,
            )
        )

    session.commit()

    return {
        "new_mapping_id": new_mapping.id,
        "prior_mapping_id": prior_mapping.id if prior_mapping else None,
        "quality_report_id": report.id,
        "affected_ownership_changes_count": len(affected_rows),
        "effective_from_quarter": effective_from_quarter,
        "effective_to_quarter": effective_to_quarter,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_canonical_cusip(cusip: str) -> str:
    if cusip is None:
        raise CorporateActionMappingError("cusip is required.")
    canonical = cusip.strip().upper()
    if len(canonical) != 9:
        raise CorporateActionMappingError(
            f"cusip must be 9 characters (got {len(canonical)})."
        )
    return canonical


_QUARTER_RE_HINT = "expected format YYYY-Q[1-4], e.g. 2024-Q3"


def _validate_quarter_string(value: str, *, field: str) -> None:
    if not value or "-Q" not in value:
        raise CorporateActionMappingError(f"{field} invalid; {_QUARTER_RE_HINT}.")
    year_text, qtr_text = value.split("-Q", 1)
    if not (year_text.isdigit() and qtr_text.isdigit()):
        raise CorporateActionMappingError(f"{field} invalid; {_QUARTER_RE_HINT}.")
    if int(qtr_text) not in (1, 2, 3, 4):
        raise CorporateActionMappingError(f"{field} invalid; {_QUARTER_RE_HINT}.")


def _ensure_quarter_order(start: str, end: str) -> None:
    if _quarter_key(start) > _quarter_key(end):
        raise CorporateActionMappingError(
            f"effective_to_quarter {end} must not precede effective_from_quarter {start}."
        )


def _quarter_key(quarter: str) -> tuple[int, int]:
    year_text, qtr_text = quarter.split("-Q", 1)
    return (int(year_text), int(qtr_text))


def _previous_quarter(quarter: str) -> str:
    year, qtr = _quarter_key(quarter)
    if qtr == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{qtr - 1}"


def _cusip_lock_id(cusip: str) -> int:
    digest = hashlib.sha256(cusip.encode()).digest()
    return struct.unpack("<q", digest[:8])[0]


def _overlapping_mappings(
    session: Session,
    *,
    cusip: str,
    effective_from_quarter: str,
    effective_to_quarter: str | None,
    exclude_mapping_id: int | None,
) -> list[CusipTickerMap]:
    candidates = (
        session.query(CusipTickerMap)
        .filter(CusipTickerMap.cusip == cusip)
        .filter(CusipTickerMap.mapping_status.in_(("confirmed", "superseded")))
        .all()
    )
    new_from = _quarter_key(effective_from_quarter)
    new_to = _quarter_key(effective_to_quarter) if effective_to_quarter else None
    overlapping: list[CusipTickerMap] = []
    for row in candidates:
        if exclude_mapping_id is not None and row.id == exclude_mapping_id:
            continue
        if row.effective_from_quarter is None:
            row_from: tuple[int, int] | None = None
        else:
            row_from = _quarter_key(row.effective_from_quarter)
        row_to = _quarter_key(row.effective_to_quarter) if row.effective_to_quarter else None

        # Open-ended on either side treated as ±∞.
        starts_before_new_end = (new_to is None) or (row_from is None) or (row_from <= new_to)
        ends_after_new_start = (row_to is None) or (row_to >= new_from)
        if starts_before_new_end and ends_after_new_start:
            overlapping.append(row)
    return overlapping


def _affected_ownership_changes_query(
    session: Session,
    *,
    cusip: str,
    effective_from_quarter: str,
    effective_to_quarter: str | None,
):
    query = (
        session.query(OwnershipChange13F)
        .filter(
            (OwnershipChange13F.current_cusip == cusip)
            | (OwnershipChange13F.previous_cusip == cusip)
        )
        .filter(OwnershipChange13F.report_quarter >= effective_from_quarter)
    )
    if effective_to_quarter is not None:
        query = query.filter(OwnershipChange13F.report_quarter <= effective_to_quarter)
    return query
