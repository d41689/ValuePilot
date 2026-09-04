"""Exact, non-precedential comparison of canonical financial facts.

The module compares bounded descriptors whose values already live in
``metric_facts``.  It never writes a value, changes ``is_current``, or elects a
source winner.  Database materialization and authorization are intentionally
kept at the edge so the pure reconciliation policy is deterministic and easy
to replay.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from functools import lru_cache
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session
import yaml

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.services.canonical_financials import (
    CanonicalSourceConflictError,
    partition_sec_run_availability,
    visible_metric_fact_predicate,
)


POLICY_VERSION = "financial-source-reconciliation-v1"
ABSOLUTE_TOLERANCE = Decimal("0.000001")
RELATIVE_TOLERANCE = Decimal("0.000001")
FISCAL_PERIOD_TYPES = frozenset({"FY", "Q", "YTD", "TTM", "PROJ_FY"})
ALLOWED_SOURCE_TYPES = frozenset({"sec", "parsed", "manual", "calculated"})
MAX_RECONCILIATION_FACTS = 250
MAX_METRIC_FILTERS = 50
METRIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
BLOCKING_EXCLUSION_REASONS = frozenset(
    {
        "source_unauthorized",
        "source_revoked",
        "source_retired",
        "unsupported_source_type",
        "unresolved_amendment_parse_failure",
    }
)
PASSTHROUGH_EXCLUSION_REASONS = frozenset(
    {"user_authored_valuation_out_of_scope", "user_manual_input_out_of_scope"}
)


@dataclass(frozen=True)
class ReconciliationCandidate:
    fact_id: int
    stock_id: int
    source_type: str
    source_role: str
    source_identity: str
    metric_key: str
    definition_family: str
    definition_basis: str
    definition_id: str
    mapping_version: str
    source_mapping_version: str
    period_type: str
    period_end_date: date
    fiscal_year: int | None
    fiscal_quarter_ordinal: int | None
    period_start_date: date | None
    duration_days: int | None
    dimensions_identity: str
    unit: str
    currency: str | None
    fact_nature: str
    value_numeric: Decimal | None
    known_at: datetime
    effective_at: datetime
    authorization_state: str
    is_current: bool
    lineage_fact_ids: tuple[int, ...] = ()
    identity_complete: bool = True


class CanonicalReconciliationError(CanonicalSourceConflictError):
    code = "unresolved_source_reconciliation"

    def __init__(self, *, consumer: str, blocking_items: Iterable[dict[str, Any]]):
        self.consumer = consumer
        self.blocking_items = tuple(blocking_items)
        self.source_types = tuple(
            sorted(
                {
                    source_type
                    for item in self.blocking_items
                    for source_type in item.get("source_types", ())
                }
            )
        )
        ValueError.__init__(
            self,
            f"{consumer} cannot use facts with unresolved source reconciliation"
        )


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _candidate_sort_key(candidate: ReconciliationCandidate) -> tuple[Any, ...]:
    return (
        candidate.metric_key,
        candidate.period_end_date,
        candidate.period_type,
        candidate.source_type,
        candidate.fact_id,
    )


def _bucket_key(candidate: ReconciliationCandidate) -> tuple[Any, ...]:
    if candidate.period_type in FISCAL_PERIOD_TYPES:
        period_family = (
            "FY"
            if candidate.period_type in {"FY", "PROJ_FY"}
            else candidate.period_type
        )
        if candidate.fiscal_year is not None and (
            candidate.period_type not in {"Q", "YTD"}
            or candidate.fiscal_quarter_ordinal is not None
        ):
            return (
                candidate.metric_key,
                "fiscal",
                period_family,
                candidate.fiscal_year,
                candidate.fiscal_quarter_ordinal,
            )
        return (
            candidate.metric_key,
            "fiscal_identity_unavailable",
            period_family,
            candidate.period_end_date,
        )
    return (
        candidate.metric_key,
        "as_of",
        candidate.period_end_date,
    )


def _canonical_unit(unit: str, *, metric_key: str) -> str:
    canonical = {
        "USD": "currency",
        "currency": "currency",
        "USD_per_share": "currency_per_share",
        "currency_per_share": "currency_per_share",
        "percent": "ratio",
        "ratio": "ratio",
        "shares": "shares",
    }.get(unit, unit)
    if canonical == "currency" and metric_key.startswith("per_share."):
        return "currency_per_share"
    return canonical


def _safe_candidate(candidate: ReconciliationCandidate) -> dict[str, Any]:
    return {
        "fact_id": candidate.fact_id,
        "source_type": candidate.source_type,
        "source_role": candidate.source_role,
        "source_identity": candidate.source_identity,
        "metric_key": candidate.metric_key,
        "definition_family": candidate.definition_family,
        "definition_basis": candidate.definition_basis,
        "definition_id": candidate.definition_id,
        "mapping_version": candidate.mapping_version,
        "source_mapping_version": candidate.source_mapping_version,
        "period_type": candidate.period_type,
        "period_end_date": _iso(candidate.period_end_date),
        "fiscal_year": candidate.fiscal_year,
        "fiscal_quarter_ordinal": candidate.fiscal_quarter_ordinal,
        "period_start_date": _iso(candidate.period_start_date),
        "duration_days": candidate.duration_days,
        "dimensions_identity": candidate.dimensions_identity,
        "unit": candidate.unit,
        "currency": candidate.currency,
        "fact_nature": candidate.fact_nature,
        "known_at": _iso(candidate.known_at),
        "effective_at": _iso(candidate.effective_at),
        "authorization_state": candidate.authorization_state,
        "is_current": candidate.is_current,
        "lineage_fact_ids": list(candidate.lineage_fact_ids),
        "identity_complete": candidate.identity_complete,
    }


def _excluded(candidate: ReconciliationCandidate, reason_code: str) -> dict[str, Any]:
    return {
        "fact_id": candidate.fact_id,
        "source_type": candidate.source_type,
        "metric_key": candidate.metric_key,
        "reason_code": reason_code,
    }


def _alignment_conflict(
    candidates: list[ReconciliationCandidate],
) -> str | None:
    checks: tuple[tuple[str, Any], ...] = (
        ("definition_family_mismatch", lambda item: item.definition_family),
        ("mapping_version_mismatch", lambda item: item.mapping_version),
        (
            "period_mismatch",
            lambda item: (
                item.period_type,
                item.period_end_date,
                item.period_start_date,
                item.duration_days,
            ),
        ),
        ("dimensions_mismatch", lambda item: item.dimensions_identity),
        (
            "unit_mismatch",
            lambda item: _canonical_unit(item.unit, metric_key=item.metric_key),
        ),
        ("currency_mismatch", lambda item: item.currency),
    )
    for reason, getter in checks:
        if len({getter(candidate) for candidate in candidates}) > 1:
            return reason
    return None


def _base_item(candidates: list[ReconciliationCandidate]) -> dict[str, Any]:
    first = candidates[0]
    return {
        "metric_key": first.metric_key,
        "period_type": first.period_type,
        "period_end_date": _iso(first.period_end_date),
        "fact_ids": sorted(candidate.fact_id for candidate in candidates),
        "source_types": sorted({candidate.source_type for candidate in candidates}),
        "source_roles": sorted({candidate.source_role for candidate in candidates}),
        "status": None,
        "reason_code": None,
        "blocking": False,
        "absolute_variance": None,
        "relative_variance": None,
        "absolute_tolerance": _decimal_text(ABSOLUTE_TOLERANCE),
        "relative_tolerance": _decimal_text(RELATIVE_TOLERANCE),
        "inputs": [_safe_candidate(candidate) for candidate in candidates],
    }


def _finish(
    item: dict[str, Any],
    *,
    status: str,
    reason_code: str,
    blocking: bool,
) -> dict[str, Any]:
    item["status"] = status
    item["reason_code"] = reason_code
    item["blocking"] = blocking
    return item


def _reconcile_group(candidates: list[ReconciliationCandidate]) -> dict[str, Any]:
    candidates = sorted(candidates, key=_candidate_sort_key)
    item = _base_item(candidates)
    missing_manual_lineage = any(
        candidate.source_role == "user_manual_correction"
        and not candidate.lineage_fact_ids
        for candidate in candidates
    )
    if missing_manual_lineage:
        return _finish(
            item,
            status="unresolved",
            reason_code="manual_lineage_unavailable",
            blocking=True,
        )
    missing_derived_lineage = any(
        candidate.source_type == "calculated" and not candidate.lineage_fact_ids
        for candidate in candidates
    )
    if missing_derived_lineage:
        return _finish(
            item,
            status="unresolved",
            reason_code="derived_lineage_unavailable",
            blocking=True,
        )

    if len(candidates) == 1:
        return _finish(
            item,
            status="unresolved",
            reason_code="single_source_only",
            blocking=False,
        )

    if any(not candidate.identity_complete for candidate in candidates):
        return _finish(
            item,
            status="mapping_conflict",
            reason_code="comparison_identity_incomplete",
            blocking=True,
        )

    current_by_source: dict[str, list[ReconciliationCandidate]] = {}
    for candidate in candidates:
        if candidate.is_current:
            current_by_source.setdefault(candidate.source_type, []).append(candidate)
    if any(len(rows) > 1 for rows in current_by_source.values()):
        return _finish(
            item,
            status="unresolved",
            reason_code="ambiguous_current_duplicate",
            blocking=True,
        )

    source_types = {candidate.source_type for candidate in candidates}
    if len(source_types) == 1 and len(
        {candidate.source_mapping_version for candidate in candidates}
    ) > 1:
        return _finish(
            item,
            status="mapping_conflict",
            reason_code="source_mapping_version_mismatch",
            blocking=True,
        )
    if len(source_types) == 1 and any(not candidate.is_current for candidate in candidates):
        values = {candidate.value_numeric for candidate in candidates}
        if len(values) > 1:
            return _finish(
                item,
                status="restatement",
                reason_code="source_value_superseded",
                blocking=False,
            )

    alignment_conflict = _alignment_conflict(candidates)
    if alignment_conflict is not None:
        return _finish(
            item,
            status="mapping_conflict",
            reason_code=alignment_conflict,
            blocking=True,
        )

    fact_natures = {candidate.fact_nature for candidate in candidates}
    if "manual" in fact_natures:
        manual = [candidate for candidate in candidates if candidate.fact_nature == "manual"]
        other_ids = {
            candidate.fact_id for candidate in candidates if candidate.fact_nature != "manual"
        }
        if not manual or any(
            not (set(candidate.lineage_fact_ids) & other_ids) for candidate in manual
        ):
            return _finish(
                item,
                status="unresolved",
                reason_code="manual_lineage_unavailable",
                blocking=True,
            )
        return _finish(
            item,
            status="expected_definition_difference",
            reason_code="explicit_manual_correction",
            blocking=False,
        )

    if "derived_actual" in fact_natures or any(
        candidate.source_type == "calculated" for candidate in candidates
    ):
        derived = [
            candidate
            for candidate in candidates
            if candidate.fact_nature == "derived_actual"
            or candidate.source_type == "calculated"
        ]
        if not derived or any(not candidate.lineage_fact_ids for candidate in derived):
            return _finish(
                item,
                status="unresolved",
                reason_code="derived_lineage_unavailable",
                blocking=True,
            )
        return _finish(
            item,
            status="expected_definition_difference",
            reason_code="direct_vs_derived",
            blocking=False,
        )

    if "actual" in fact_natures and "estimate" in fact_natures:
        return _finish(
            item,
            status="expected_definition_difference",
            reason_code="actual_vs_estimate",
            blocking=False,
        )
    if len(fact_natures) > 1:
        return _finish(
            item,
            status="mapping_conflict",
            reason_code="fact_nature_mismatch",
            blocking=True,
        )

    definition_bases = {candidate.definition_basis for candidate in candidates}
    definition_ids = {candidate.definition_id for candidate in candidates}
    if definition_bases == {"as_filed", "adjusted"} and source_types == {
        "sec",
        "parsed",
    }:
        if any(
            candidate.value_numeric is None or not candidate.value_numeric.is_finite()
            for candidate in candidates
        ):
            return _finish(
                item,
                status="expected_definition_difference",
                reason_code="as_filed_vs_adjusted",
                blocking=False,
            )
        numeric_values = [
            candidate.value_numeric
            for candidate in candidates
            if candidate.value_numeric is not None
        ]
        absolute_variance = max(numeric_values) - min(numeric_values)
        magnitude = max(abs(value) for value in numeric_values)
        item["absolute_variance"] = _decimal_text(absolute_variance)
        item["relative_variance"] = _decimal_text(
            Decimal(0) if magnitude == 0 else absolute_variance / magnitude
        )
        return _finish(
            item,
            status="expected_definition_difference",
            reason_code="as_filed_vs_adjusted",
            blocking=False,
        )
    if len(definition_ids) > 1 or len(definition_bases) > 1:
        return _finish(
            item,
            status="mapping_conflict",
            reason_code="definition_mismatch",
            blocking=True,
        )

    if any(
        candidate.value_numeric is None or not candidate.value_numeric.is_finite()
        for candidate in candidates
    ):
        return _finish(
            item,
            status="unresolved",
            reason_code="numeric_value_unavailable",
            blocking=True,
        )
    values = [candidate.value_numeric for candidate in candidates]
    assert all(value is not None for value in values)
    numeric_values = [value for value in values if value is not None]
    absolute_variance = max(numeric_values) - min(numeric_values)
    magnitude = max(abs(value) for value in numeric_values)
    relative_variance = (
        Decimal(0) if magnitude == 0 else absolute_variance / magnitude
    )
    item["absolute_variance"] = _decimal_text(absolute_variance)
    item["relative_variance"] = _decimal_text(relative_variance)
    matches = (
        absolute_variance <= ABSOLUTE_TOLERANCE
        or relative_variance <= RELATIVE_TOLERANCE
    )
    if matches:
        return _finish(
            item,
            status="match",
            reason_code="within_review_tolerance",
            blocking=False,
        )

    return _finish(
        item,
        status="unresolved",
        reason_code="material_value_difference",
        blocking=True,
    )


def _report_digest(report: dict[str, Any]) -> str:
    encoded = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reconcile_candidates(
    facts: Iterable[ReconciliationCandidate],
    *,
    knowledge_cutoff: datetime,
) -> dict[str, Any]:
    """Return a deterministic comparison report for exact candidate facts."""

    if knowledge_cutoff.tzinfo is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    knowledge_cutoff = knowledge_cutoff.astimezone(timezone.utc)
    ordered = sorted(facts, key=_candidate_sort_key)
    eligible: list[ReconciliationCandidate] = []
    excluded: list[dict[str, Any]] = []
    expected_stock_id = ordered[0].stock_id if ordered else None
    for candidate in ordered:
        reason = None
        if candidate.source_type not in ALLOWED_SOURCE_TYPES:
            reason = "unsupported_source_type"
        elif candidate.stock_id != expected_stock_id:
            reason = "cross_stock_fact"
        elif candidate.authorization_state == "retired":
            reason = "source_retired"
        elif candidate.authorization_state == "revoked":
            reason = "source_revoked"
        elif candidate.authorization_state != "authorized":
            reason = "source_unauthorized"
        elif candidate.known_at > knowledge_cutoff:
            reason = "fact_known_after_cutoff"
        elif candidate.effective_at > knowledge_cutoff:
            reason = "fact_effective_after_cutoff"
        if reason is not None:
            excluded.append(_excluded(candidate, reason))
        else:
            eligible.append(candidate)

    grouped: dict[tuple[Any, ...], list[ReconciliationCandidate]] = {}
    lineage_blocked_ids = {
        candidate.fact_id
        for candidate in eligible
        if (
            candidate.source_role == "user_manual_correction"
            and not candidate.lineage_fact_ids
        )
        or (
            candidate.source_type == "calculated"
            and not candidate.lineage_fact_ids
        )
    }
    lineage_items = [
        _reconcile_group([candidate])
        for candidate in eligible
        if candidate.fact_id in lineage_blocked_ids
    ]
    period_identity_blocked_ids: set[int] = set()
    fiscal_by_metric: dict[str, list[ReconciliationCandidate]] = {}
    for candidate in eligible:
        if candidate.fact_id in lineage_blocked_ids:
            continue
        if candidate.period_type in FISCAL_PERIOD_TYPES:
            fiscal_by_metric.setdefault(candidate.metric_key, []).append(candidate)
    identity_items: list[dict[str, Any]] = []
    for candidates in fiscal_by_metric.values():
        if len({candidate.source_type for candidate in candidates}) <= 1:
            continue
        incomplete = any(
            candidate.fiscal_year is None
            or (
                candidate.period_type in {"Q", "YTD"}
                and candidate.fiscal_quarter_ordinal is None
            )
            for candidate in candidates
        )
        if incomplete:
            period_identity_blocked_ids.update(
                candidate.fact_id for candidate in candidates
            )
            identity_items.append(
                _finish(
                    _base_item(sorted(candidates, key=_candidate_sort_key)),
                    status="mapping_conflict",
                    reason_code="period_identity_unavailable",
                    blocking=True,
                )
            )
    for candidate in eligible:
        if (
            candidate.fact_id in lineage_blocked_ids
            or candidate.fact_id in period_identity_blocked_ids
        ):
            continue
        grouped.setdefault(_bucket_key(candidate), []).append(candidate)
    items: list[dict[str, Any]] = [*lineage_items, *identity_items]
    for key in sorted(grouped, key=lambda value: tuple(str(part) for part in value)):
        rows = grouped[key]
        history_items: list[dict[str, Any]] = []
        for source_type in sorted({row.source_type for row in rows}):
            source_rows = [row for row in rows if row.source_type == source_type]
            if len(source_rows) > 1 and any(not row.is_current for row in source_rows):
                history_items.append(_reconcile_group(source_rows))
        items.extend(history_items)
        current_rows = [row for row in rows if row.is_current]
        current_by_source: dict[str, list[ReconciliationCandidate]] = {}
        for row in current_rows:
            current_by_source.setdefault(row.source_type, []).append(row)
        if any(len(source_rows) > 1 for source_rows in current_by_source.values()):
            items.append(_reconcile_group(current_rows))
        elif len(current_rows) > 1:
            items.extend(
                _reconcile_group(list(pair))
                for pair in combinations(current_rows, 2)
            )
        elif not history_items:
            items.append(_reconcile_group(current_rows or rows))
    report: dict[str, Any] = {
        "status": "complete",
        "policy_version": POLICY_VERSION,
        "knowledge_cutoff": knowledge_cutoff.isoformat(),
        "stock_id": expected_stock_id,
        "eligible_fact_ids": sorted(candidate.fact_id for candidate in eligible),
        "excluded": excluded,
        "items": items,
        "blocking_item_count": sum(1 for item in items if item["blocking"]),
    }
    report["report_digest"] = _report_digest(report)
    return report


_SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "metric_facts_mapping_spec.yml"


@lru_cache(maxsize=1)
def _mapping_spec_identity() -> tuple[str, str, str]:
    payload = _SPEC_PATH.read_bytes()
    spec = yaml.safe_load(payload)
    versions = spec.get("source_reconciliation", {}).get("versions", [])
    policy = next(
        (
            version
            for version in versions
            if version.get("id") == POLICY_VERSION
            and version.get("status") == "approved"
        ),
        None,
    )
    if not isinstance(policy, dict):
        raise RuntimeError("approved source reconciliation policy is unavailable")
    definition_version = policy.get("canonical_definition_version")
    if not isinstance(definition_version, str) or not definition_version:
        raise RuntimeError("canonical definition version is unavailable")
    return POLICY_VERSION, hashlib.sha256(payload).hexdigest(), definition_version


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _json_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _lineage_ids(metadata: dict[str, Any], *, source_type: str) -> tuple[int, ...]:
    raw: list[Any] = []
    if source_type == "manual":
        raw.extend(
            (
                metadata.get("corrects_fact_id"),
                metadata.get("corrected_from_fact_id"),
                metadata.get("source_fact_id"),
            )
        )
    elif source_type == "calculated":
        inputs = metadata.get("inputs")
        if isinstance(inputs, list):
            raw.extend(
                item.get("fact_id")
                for item in inputs
                if isinstance(item, dict)
            )
    return tuple(sorted({value for value in raw if isinstance(value, int) and value > 0}))


def _document_authority(
    session: Session,
    facts: Sequence[MetricFact],
) -> dict[int, PdfDocument]:
    ids = sorted(
        {
            fact.source_document_id
            for fact in facts
            if fact.source_type == "parsed" and fact.source_document_id is not None
        }
    )
    if not ids:
        return {}
    return {
        document.id: document
        for document in session.scalars(select(PdfDocument).where(PdfDocument.id.in_(ids)))
    }


def _sec_authority(
    session: Session,
    facts: Sequence[MetricFact],
    *,
    knowledge_cutoff: datetime,
) -> dict[int, dict[str, Any]]:
    ids = sorted({fact.id for fact in facts if fact.source_type == "sec"})
    if not ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT p.metric_fact_id, p.id AS publication_id, p.status AS publication_status,
                   p.source_role,
                   p.fact_nature, p.derivation_kind, p.period_start_date,
                   p.fiscal_year, p.fiscal_quarter_ordinal,
                   p.period_basis, p.dimensions_policy, p.dimensions_sha256,
                   p.known_at, p.created_at, p.mapping_rule_id,
                   r.id AS publication_run_id, r.mapping_version_id,
                   r.status AS run_status, r.requested_cutoff,
                   a.available_at, v.status AS mapping_status,
                   v.effective_from AS mapping_effective_from,
                   v.known_at AS mapping_known_at, v.retired_at AS mapping_retired_at,
                   rule.rule_id,
                   COALESCE(array_agg(source.metric_fact_id ORDER BY i.input_ordinal)
                     FILTER (WHERE source.metric_fact_id IS NOT NULL), '{}') AS lineage_fact_ids
            FROM sec_metric_publications p
            JOIN sec_metric_publication_runs r ON r.id=p.publication_run_id
            LEFT JOIN sec_metric_publication_availabilities a
              ON a.publication_run_id=r.id
            JOIN sec_metric_mapping_versions v ON v.id=r.mapping_version_id
            JOIN sec_metric_mapping_rules rule ON rule.id=p.mapping_rule_id
              AND rule.mapping_version_id=r.mapping_version_id
            LEFT JOIN sec_metric_publication_inputs i ON i.publication_id=p.id
            LEFT JOIN sec_metric_publications source ON source.id=i.source_publication_id
            WHERE p.metric_fact_id = ANY(:fact_ids)
            GROUP BY p.metric_fact_id, p.id, p.status, p.source_role, p.fact_nature,
                     p.derivation_kind, p.period_start_date, p.fiscal_year,
                     p.fiscal_quarter_ordinal, p.period_basis,
                     p.dimensions_policy, p.dimensions_sha256, p.known_at,
                     p.created_at, p.mapping_rule_id, r.id, r.mapping_version_id,
                     r.status, r.requested_cutoff, a.available_at, v.status,
                     v.effective_from, v.known_at, v.retired_at, rule.rule_id
            """
        ),
        {"fact_ids": ids},
    ).mappings()
    return {int(row.metric_fact_id): dict(row) for row in rows}


def materialize_reconciliation_candidates(
    session: Session,
    facts: Iterable[MetricFact],
    *,
    user_id: int,
    knowledge_cutoff: datetime,
) -> tuple[list[ReconciliationCandidate], list[dict[str, Any]]]:
    """Project visible ``metric_facts`` into bounded comparison descriptors."""

    if knowledge_cutoff.tzinfo is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    rows = list(facts)
    documents = _document_authority(session, rows)
    sec = _sec_authority(session, rows, knowledge_cutoff=knowledge_cutoff)
    _, _, canonical_definition_version = _mapping_spec_identity()
    candidates: list[ReconciliationCandidate] = []
    excluded: list[dict[str, Any]] = []

    visible_lineage = {
        source.id: source
        for source in session.scalars(
            select(MetricFact).where(
                MetricFact.id.in_(
                    sorted(
                        {
                            lineage_id
                            for fact in rows
                            for lineage_id in _lineage_ids(
                                _json_dict(fact.value_json), source_type=fact.source_type
                            )
                        }
                    )
                ),
                visible_metric_fact_predicate(MetricFact, user_id=user_id),
            )
        )
    } if rows and any(_lineage_ids(_json_dict(f.value_json), source_type=f.source_type) for f in rows) else {}

    for fact in rows:
        reason: str | None = None
        metadata = _json_dict(fact.value_json)
        known_at = max(_aware(fact.created_at), _aware(fact.updated_at))
        effective_at = known_at
        authorization_state = "authorized"
        source_role = ""
        definition_basis = str(metadata.get("definition_basis") or "")
        definition_id = str(metadata.get("mapping_id") or fact.metric_key)
        period_start = _parse_date(metadata.get("period_start_date"))
        duration_days = metadata.get("duration_days")
        dimensions = str(metadata.get("dimensions_identity") or "")
        fact_nature = str(metadata.get("fact_nature") or "")
        lineage = _lineage_ids(metadata, source_type=fact.source_type)
        source_authority_complete = True
        source_mapping_version = str(metadata.get("source_mapping_version") or "")
        fiscal_year = metadata.get("fiscal_year")
        fiscal_year = fiscal_year if isinstance(fiscal_year, int) else None
        fiscal_quarter = metadata.get("fiscal_quarter_ordinal")
        fiscal_quarter = fiscal_quarter if isinstance(fiscal_quarter, int) else None

        if fact.source_type == "sec":
            authority = sec.get(fact.id)
            if fact.user_id is not None or authority is None:
                authorization_state = "unauthorized"
            else:
                known_at = max(
                    _aware(authority["known_at"]),
                    _aware(authority["created_at"]),
                    _aware(authority["available_at"]),
                )
                effective_at = max(
                    _aware(authority["mapping_effective_from"]),
                    _aware(authority["created_at"]),
                )
                retired_at = authority["mapping_retired_at"]
                authorized = (
                    authority["publication_status"] == "published"
                    and
                    authority["run_status"] == "succeeded"
                    and authority["available_at"] is not None
                    and authority["mapping_status"] == "approved"
                    and _aware(authority["mapping_known_at"]) <= knowledge_cutoff
                    and _aware(authority["mapping_effective_from"]) <= knowledge_cutoff
                    and (retired_at is None or _aware(retired_at) > knowledge_cutoff)
                )
                if retired_at is not None and _aware(retired_at) <= knowledge_cutoff:
                    authorization_state = "retired"
                else:
                    authorization_state = "authorized" if authorized else "unauthorized"
                source_role = str(authority["source_role"])
                fact_nature = str(authority["fact_nature"])
                definition_basis = "as_filed"
                definition_id = str(authority["rule_id"])
                source_mapping_version = str(authority["mapping_version_id"])
                period_start = authority["period_start_date"]
                fiscal_year = int(authority["fiscal_year"])
                fiscal_quarter = authority["fiscal_quarter_ordinal"]
                duration_days = (
                    (fact.period_end_date - period_start).days + 1
                    if fact.period_end_date is not None and period_start is not None
                    else None
                )
                dimensions = str(authority["dimensions_sha256"] or "")
                lineage = tuple(int(value) for value in authority["lineage_fact_ids"])
        elif fact.user_id != user_id:
            authorization_state = "unauthorized"
        elif fact.source_type == "parsed":
            document = documents.get(fact.source_document_id or -1)
            source_authority_complete = document is not None
            authorized = fact.source_document_id is None or (
                document is not None
                and document.user_id == user_id
                and document.source in {"upload", "value_line"}
                and document.parse_status == "parsed"
                and not document.identity_needs_review
                and (document.stock_id is None or document.stock_id == fact.stock_id)
                and _aware(document.upload_time) <= knowledge_cutoff
            )
            authorization_state = "authorized" if authorized else "unauthorized"
            source_role = (
                "value_line_estimate"
                if fact_nature == "estimate"
                else "value_line_adjusted_actual"
            )
            fact_nature = fact_nature or "actual"
            definition_basis = definition_basis or "adjusted"
        elif fact.source_type == "manual":
            if fact.metric_key == "val.fair_value":
                reason = "user_authored_valuation_out_of_scope"
            is_correction = bool(
                metadata.get("correction") is True
                or metadata.get("corrects_fact_id")
                or metadata.get("corrected_from_fact_id")
                or metadata.get("source_fact_id")
            )
            if reason is None and (
                metadata.get("manual_role") == "original_input"
                or not is_correction
            ):
                reason = "user_manual_input_out_of_scope"
            source_role = "user_manual_correction"
            source_mapping_version = source_mapping_version or "manual-financial-v1"
            fact_nature = "manual"
            definition_basis = definition_basis or "adjusted"
        elif fact.source_type == "calculated":
            source_role = "deterministic_derived"
            source_mapping_version = str(metadata.get("calculation_version") or "")
            fact_nature = "derived_actual"
            definition_basis = definition_basis or "derived"
        else:
            reason = "unsupported_source_type"

        metadata_authorization = metadata.get("authorization_state")
        if metadata.get("retired") is True or metadata_authorization == "retired":
            authorization_state = "retired"
        elif metadata_authorization == "revoked":
            authorization_state = "revoked"
        elif metadata_authorization == "unauthorized":
            authorization_state = "unauthorized"
        if fact.period_end_date is None and fact.as_of_date is None:
            period_end = date.min
            identity_complete = False
        else:
            period_end = fact.period_end_date or fact.as_of_date
            identity_complete = bool(
                source_authority_complete
                and
                fact.period_type
                and dimensions
                and definition_id
                and definition_basis
                and source_mapping_version
                and (
                    fact.period_type not in FISCAL_PERIOD_TYPES
                    or (
                        period_start is not None
                        and isinstance(duration_days, int)
                        and fiscal_year is not None
                        and (
                            fact.period_type not in {"Q", "YTD"}
                            or fiscal_quarter in {1, 2, 3, 4}
                        )
                    )
                )
            )
        if fact.source_type in {"manual", "calculated"} and lineage:
            expected_lineage = lineage
            visible_valid_lineage = tuple(
                value
                for value in lineage
                if value in visible_lineage
                and visible_lineage[value].stock_id == fact.stock_id
                and max(
                    _aware(visible_lineage[value].created_at),
                    _aware(visible_lineage[value].updated_at),
                )
                <= knowledge_cutoff
                and value != fact.id
            )
            lineage = (
                visible_valid_lineage
                if visible_valid_lineage == expected_lineage
                else ()
            )
        if reason is not None:
            excluded.append(_excluded_fact(fact, reason))
            continue
        candidates.append(
            ReconciliationCandidate(
                fact_id=fact.id,
                stock_id=fact.stock_id,
                source_type=fact.source_type,
                source_role=source_role,
                source_identity=(
                    f"sec-publication:{sec[fact.id]['publication_id']}"
                    if fact.source_type == "sec" and fact.id in sec
                    else f"{fact.source_type}:{fact.source_document_id or fact.source_ref_id or fact.id}"
                ),
                metric_key=fact.metric_key,
                definition_family=f"canonical:{fact.metric_key}",
                definition_basis=definition_basis,
                definition_id=definition_id,
                mapping_version=canonical_definition_version,
                source_mapping_version=source_mapping_version or "unknown",
                period_type=fact.period_type or "UNSPECIFIED",
                period_end_date=period_end,
                fiscal_year=fiscal_year,
                fiscal_quarter_ordinal=fiscal_quarter,
                period_start_date=period_start,
                duration_days=duration_days if isinstance(duration_days, int) else None,
                dimensions_identity=dimensions or "unknown",
                unit=fact.unit or "unknown",
                currency=fact.currency,
                fact_nature=fact_nature or "unknown",
                value_numeric=fact.value_numeric,
                known_at=known_at,
                effective_at=effective_at,
                authorization_state=authorization_state,
                is_current=fact.is_current,
                lineage_fact_ids=lineage,
                identity_complete=identity_complete,
            )
        )
    return candidates, excluded


def _excluded_fact(fact: MetricFact, reason_code: str) -> dict[str, Any]:
    return {
        "fact_id": fact.id,
        "source_type": fact.source_type,
        "metric_key": fact.metric_key,
        "reason_code": reason_code,
    }


def _lineage_blocking_item(
    fact: MetricFact,
    *,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "status": "unresolved",
        "reason_code": reason_code,
        "blocking": True,
        "fact_ids": [fact.id],
        "source_types": [fact.source_type],
        "metric_key": fact.metric_key,
    }


def _expand_visible_lineage(
    session: Session,
    *,
    facts: Sequence[MetricFact],
    user_id: int,
    knowledge_cutoff: datetime,
    max_facts: int,
) -> tuple[list[MetricFact], list[dict[str, Any]]]:
    """Resolve a bounded tenant-visible lineage closure and reject cycles."""

    if not facts:
        return [], []
    stock_id = facts[0].stock_id
    by_id = {fact.id: fact for fact in facts}
    queue = {
        lineage_id
        for fact in facts
        for lineage_id in _lineage_ids(
            _json_dict(fact.value_json), source_type=fact.source_type
        )
        if lineage_id not in by_id
    }
    errors: list[dict[str, Any]] = []
    while queue:
        if len(by_id) + len(queue) > max_facts:
            errors.append(
                _lineage_blocking_item(
                    facts[0], reason_code="derived_lineage_bound_exceeded"
                )
            )
            break
        requested = sorted(queue)
        queue.clear()
        fetched = list(
            session.scalars(
                select(MetricFact).where(
                    MetricFact.id.in_(requested),
                    visible_metric_fact_predicate(MetricFact, user_id=user_id),
                )
            )
        )
        fetched_by_id = {fact.id: fact for fact in fetched}
        missing = set(requested) - set(fetched_by_id)
        if missing:
            parent = next(
                fact
                for fact in by_id.values()
                if missing
                & set(
                    _lineage_ids(
                        _json_dict(fact.value_json), source_type=fact.source_type
                    )
                )
            )
            errors.append(
                _lineage_blocking_item(
                    parent, reason_code="lineage_reference_unavailable"
                )
            )
            break
        for fact in fetched:
            if fact.stock_id != stock_id:
                errors.append(
                    _lineage_blocking_item(
                        fact, reason_code="cross_stock_lineage_reference"
                    )
                )
                continue
            if max(_aware(fact.created_at), _aware(fact.updated_at)) > knowledge_cutoff:
                errors.append(
                    _lineage_blocking_item(
                        fact, reason_code="lineage_known_after_cutoff"
                    )
                )
                continue
            by_id[fact.id] = fact
            queue.update(
                lineage_id
                for lineage_id in _lineage_ids(
                    _json_dict(fact.value_json), source_type=fact.source_type
                )
                if lineage_id not in by_id
            )
        if errors:
            break

    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(fact_id: int) -> bool:
        if fact_id in visiting:
            return True
        if fact_id in visited:
            return False
        visiting.add(fact_id)
        fact = by_id[fact_id]
        for lineage_id in _lineage_ids(
            _json_dict(fact.value_json), source_type=fact.source_type
        ):
            if lineage_id in by_id and visit(lineage_id):
                return True
        visiting.remove(fact_id)
        visited.add(fact_id)
        return False

    if not errors:
        for fact_id in sorted(by_id):
            if visit(fact_id):
                errors.append(
                    _lineage_blocking_item(
                        by_id[fact_id], reason_code="lineage_cycle_detected"
                    )
                )
                break
    return list(by_id.values()), errors


def _partition_available_sec_facts(
    session: Session,
    *,
    stock_id: int,
    facts: Sequence[MetricFact],
) -> tuple[list[MetricFact], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the canonical unresolved-amendment boundary before comparison."""

    available, states = partition_sec_run_availability(
        session,
        stock_id=stock_id,
        facts=facts,
    )
    available_object_ids = {id(fact) for fact in available}
    blocked = [
        fact
        for fact in facts
        if fact.source_type == "sec" and id(fact) not in available_object_ids
    ]
    exclusions = [
        _excluded_fact(fact, "unresolved_amendment_parse_failure")
        for fact in blocked
    ]
    safe_states = [
        {
            "status": state.get("status"),
            "reason_code": state.get("reason_code"),
            "period_end_date": _iso(state.get("period_end_date")),
            "mapping_version": state.get("mapping_version"),
            "known_at": _iso(state.get("known_at")),
            "requested_knowledge_cutoff": _iso(
                state.get("requested_knowledge_cutoff")
            ),
            "filing_cycle": {
                "base_form": (state.get("filing_cycle") or {}).get("base_form"),
                "report_date": _iso(
                    (state.get("filing_cycle") or {}).get("report_date")
                ),
            },
        }
        for state in states
    ]
    return list(available), exclusions, safe_states


def build_source_reconciliation_report(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    knowledge_cutoff: datetime,
    metric_keys: Sequence[str] | None = None,
    max_facts: int = MAX_RECONCILIATION_FACTS,
    historical_request: bool = False,
) -> dict[str, Any]:
    """Build the bounded, read-only reconciliation view for one tenant/stock."""

    requested_keys = list(metric_keys or ())
    if len(requested_keys) > MAX_METRIC_FILTERS:
        raise ValueError("metric key filter exceeds bounded contract")
    if any(not METRIC_KEY_PATTERN.fullmatch(key) for key in requested_keys):
        raise ValueError("invalid canonical metric key filter")
    keys = sorted(set(requested_keys))
    statement = select(MetricFact).where(
        MetricFact.stock_id == stock_id,
        visible_metric_fact_predicate(MetricFact, user_id=user_id),
    )
    if keys:
        statement = statement.where(MetricFact.metric_key.in_(keys))
    facts = list(
        session.scalars(
            statement.order_by(
                MetricFact.metric_key,
                MetricFact.period_end_date,
                MetricFact.source_type,
                MetricFact.is_current.desc(),
                MetricFact.created_at.desc(),
                MetricFact.id,
            ).limit(max_facts + 1)
        )
    )
    if len(facts) > max_facts:
        raise ValueError("reconciliation fact set exceeds bounded contract")
    return build_source_reconciliation_report_from_facts(
        session,
        facts=facts,
        user_id=user_id,
        stock_id=stock_id,
        knowledge_cutoff=knowledge_cutoff,
        historical_request=historical_request,
        max_facts=max_facts,
    )


def build_source_reconciliation_report_from_facts(
    session: Session,
    *,
    facts: Iterable[MetricFact],
    user_id: int,
    stock_id: int,
    knowledge_cutoff: datetime,
    historical_request: bool = False,
    max_facts: int = MAX_RECONCILIATION_FACTS,
) -> dict[str, Any]:
    """Build a report for a consumer's already-bounded canonical fact view."""

    fact_rows = list(facts)
    if len(fact_rows) > max_facts:
        raise ValueError("reconciliation fact set exceeds bounded contract")
    if any(fact.stock_id != stock_id for fact in fact_rows):
        raise ValueError("reconciliation fact set contains another stock")
    expanded_rows, lineage_errors = _expand_visible_lineage(
        session,
        facts=fact_rows,
        user_id=user_id,
        knowledge_cutoff=knowledge_cutoff,
        max_facts=max_facts,
    )
    available_rows, sec_excluded, sec_unavailable_states = (
        _partition_available_sec_facts(
            session,
            stock_id=stock_id,
            facts=expanded_rows,
        )
    )
    candidates, materialization_excluded = materialize_reconciliation_candidates(
        session,
        available_rows,
        user_id=user_id,
        knowledge_cutoff=knowledge_cutoff,
    )
    report = reconcile_candidates(candidates, knowledge_cutoff=knowledge_cutoff)
    report["items"].extend(lineage_errors)
    report["blocking_item_count"] += len(lineage_errors)
    report["stock_id"] = stock_id
    report["excluded"] = sorted(
        [*report["excluded"], *materialization_excluded, *sec_excluded],
        key=lambda row: (row["metric_key"], row["source_type"], row["fact_id"]),
    )
    report["blocking_exclusion_count"] = sum(
        row["reason_code"] in BLOCKING_EXCLUSION_REASONS
        for row in report["excluded"]
    )
    report["sec_unavailable_states"] = sec_unavailable_states
    report["consumer_gate_status"] = (
        "blocked"
        if report["blocking_item_count"] or report["blocking_exclusion_count"]
        else "clear"
    )
    _, spec_digest, definition_version = _mapping_spec_identity()
    report["mapping_spec_sha256"] = spec_digest
    report["canonical_definition_version"] = definition_version
    report["point_in_time_status"] = (
        "historical_current_projection_unverifiable"
        if historical_request and any(fact.source_type != "sec" for fact in fact_rows)
        else "verified_from_available_authority"
    )
    if report["point_in_time_status"] == "historical_current_projection_unverifiable":
        report["status"] = "partial"
    report.pop("report_digest", None)
    report["report_digest"] = _report_digest(report)
    return report


def guard_reconciled_source_selection(
    facts: Iterable[ReconciliationCandidate | MetricFact],
    *,
    consumer: str,
    knowledge_cutoff: datetime,
    selected_source_type: str | None = None,
    session: Session | None = None,
    user_id: int | None = None,
) -> list[ReconciliationCandidate | MetricFact]:
    """Apply FT-06 blocking outcomes before any explicit source selection."""

    originals = list(facts)
    if len(originals) > MAX_RECONCILIATION_FACTS:
        raise CanonicalReconciliationError(
            consumer=consumer,
            blocking_items=[
                {
                    "status": "unresolved",
                    "reason_code": "reconciliation_fact_bound_exceeded",
                    "blocking": True,
                    "fact_ids": [],
                    "source_types": [],
                    "metric_key": None,
                }
            ],
        )
    if originals and isinstance(originals[0], MetricFact):
        if session is None or user_id is None:
            raise ValueError("session and user_id are required for metric_facts")
        stock_ids = {fact.stock_id for fact in originals}
        if len(stock_ids) != 1:
            raise ValueError("reconciliation fact set contains multiple stocks")
        expanded_facts, lineage_errors = _expand_visible_lineage(
            session,
            facts=originals,  # type: ignore[arg-type]
            user_id=user_id,
            knowledge_cutoff=knowledge_cutoff,
            max_facts=MAX_RECONCILIATION_FACTS,
        )
        if lineage_errors:
            raise CanonicalReconciliationError(
                consumer=consumer,
                blocking_items=lineage_errors,
            )
        available_originals, sec_excluded, _ = _partition_available_sec_facts(
            session,
            stock_id=next(iter(stock_ids)),
            facts=expanded_facts,
        )
        candidates, materialization_excluded = materialize_reconciliation_candidates(
            session,
            available_originals,
            user_id=user_id,
            knowledge_cutoff=knowledge_cutoff,
        )
        materialization_excluded = [*materialization_excluded, *sec_excluded]
    else:
        candidates = list(originals)  # type: ignore[assignment]
        materialization_excluded = []
    report = reconcile_candidates(candidates, knowledge_cutoff=knowledge_cutoff)
    blocking = [item for item in report["items"] if item["blocking"]]
    blocking_exclusions = [
        {
            "status": "unresolved",
            "reason_code": row["reason_code"],
            "blocking": True,
            "fact_ids": [row["fact_id"]],
            "source_types": [row["source_type"]],
            "metric_key": row["metric_key"],
        }
        for row in [*report["excluded"], *materialization_excluded]
        if row["reason_code"] in BLOCKING_EXCLUSION_REASONS
    ]
    blocking.extend(blocking_exclusions)
    if blocking:
        raise CanonicalReconciliationError(
            consumer=consumer,
            blocking_items=blocking,
        )
    eligible_ids = set(report["eligible_fact_ids"])
    passthrough_ids = {
        row["fact_id"]
        for row in materialization_excluded
        if row["reason_code"] in PASSTHROUGH_EXCLUSION_REASONS
    }
    eligible_originals = [fact for fact in originals if fact.fact_id in eligible_ids] if (
        originals and isinstance(originals[0], ReconciliationCandidate)
    ) else [
        fact
        for fact in originals
        if fact.id in eligible_ids or fact.id in passthrough_ids
    ]
    if selected_source_type is not None:
        if selected_source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError("unsupported source_type selection")
        return [
            fact
            for fact in eligible_originals
            if fact.source_type == selected_source_type
        ]
    exact_slots: dict[tuple[Any, ...], set[str]] = {}
    for fact in eligible_originals:
        exact_slots.setdefault(
            (
                fact.metric_key,
                getattr(fact, "period_type", None),
                getattr(fact, "period_end_date", None),
                getattr(fact, "as_of_date", None),
            ),
            set(),
        ).add(fact.source_type)
    passthrough_collisions = [
        source_types
        for source_types in exact_slots.values()
        if len(source_types) > 1
    ]
    if passthrough_collisions:
        raise CanonicalSourceConflictError(
            consumer=consumer,
            source_types={
                source_type
                for source_types in passthrough_collisions
                for source_type in source_types
            },
        )
    ambiguous_items = [
        item
        for item in report["items"]
        if len(item.get("source_types", ())) > 1
    ]
    if ambiguous_items:
        raise CanonicalSourceConflictError(
            consumer=consumer,
            source_types={
                source_type
                for item in ambiguous_items
                for source_type in item["source_types"]
            },
        )
    return eligible_originals
