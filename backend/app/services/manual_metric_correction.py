"""Canonical append-only manual correction for one exact metric-fact slot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ingestion.normalization.scaler import Scaler
from app.models.artifacts import ValueLineFactExtractionInput
from app.models.facts import MetricFact
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.metric_fact_currentness import (
    CurrentnessScope,
    current_metric_fact_ids_at,
)
from app.services.metric_fact_locking import acquire_metric_fact_stock_lock


MAX_MANUAL_CORRECTION_ANCESTRY = 32


@dataclass(frozen=True)
class ManualMetricCorrectionError(ValueError):
    code: str
    message: str


def create_manual_metric_correction(
    session: Session,
    *,
    user_id: int,
    source_fact: MetricFact,
    raw_value: str,
    unit_hint: Optional[str] = None,
    note: Optional[str] = None,
) -> MetricFact:
    """Append a correction and demote only the prior manual fact in its slot."""

    if source_fact.user_id != user_id:
        raise ManualMetricCorrectionError(
            code="correction_source_not_visible",
            message="Correction source fact is not visible to this user",
        )
    raw_text = str(raw_value).strip()
    if not raw_text:
        raise ManualMetricCorrectionError(
            code="correction_value_required",
            message="Correction value is required",
        )

    value_numeric, normalized_unit, value_text = _normalize_correction(
        raw_text=raw_text,
        unit_hint=unit_hint,
        fact=source_fact,
    )
    if value_numeric is None and value_text is None:
        raise ManualMetricCorrectionError(
            code="correction_value_invalid",
            message="Correction value could not be normalized",
        )

    acquire_metric_fact_stock_lock(session, stock_id=source_fact.stock_id)
    evaluation_snapshot = database_evaluation_snapshot(session)
    source_fact_id = _positive_id(source_fact.id)
    if source_fact_id is None or session.scalar(
        select(MetricFact.id).where(
            MetricFact.id == source_fact_id,
            MetricFact.id.in_(
                current_metric_fact_ids_at(
                    session,
                    knowledge_cutoff=evaluation_snapshot.cutoff,
                    knowledge_txid_snapshot=(
                        evaluation_snapshot.visibility_snapshot
                    ),
                    scope=CurrentnessScope(fact_ids=(source_fact_id,)),
                )
            ),
        )
    ) is None:
        raise _lineage_unavailable()
    source_metadata = _fact_metadata(source_fact)
    original_source = (
        _resolve_manual_original_parsed_fact(
            session,
            user_id=user_id,
            manual_fact=source_fact,
        )
        if source_fact.source_type == "manual"
        else source_fact
    )
    original_source_fact_id = original_source.id
    source_extraction_id, source_parse_run_id = _exact_primary_lineage(
        session,
        parsed_fact=original_source,
    )
    if source_fact.source_type == "manual":
        declared_extraction = source_metadata.get("source_extraction_id")
        declared_run = source_metadata.get("source_parse_run_id")
        if (
            isinstance(declared_extraction, int)
            and declared_extraction != source_extraction_id
        ) or (
            isinstance(declared_run, int)
            and declared_run != source_parse_run_id
        ):
            raise _lineage_unavailable()

    identity_metadata = _fact_metadata(original_source)

    value_json = {
        "raw": raw_text,
        "correction": True,
        "corrected_from_fact_id": source_fact.id,
        "source_fact_id": original_source_fact_id,
    }
    if isinstance(source_extraction_id, int):
        value_json["source_extraction_id"] = source_extraction_id
    if isinstance(source_parse_run_id, int):
        value_json["source_parse_run_id"] = source_parse_run_id
    for identity_key in (
        "mapping_id",
        "source_mapping_version",
        "definition_basis",
        "period_start_date",
        "duration_days",
        "period_duration_kind",
        "fiscal_year",
        "fiscal_quarter_ordinal",
        "dimensions_identity",
        "fact_nature",
    ):
        if identity_key in identity_metadata:
            value_json[identity_key] = identity_metadata[identity_key]
    if note:
        value_json["note"] = str(note)

    # All fail-closed source/lineage checks must finish before currentness is
    # changed. A caller may intentionally catch a typed validation error and
    # commit unrelated work without an endpoint-level rollback.
    session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == source_fact.stock_id,
            MetricFact.metric_key == source_fact.metric_key,
            MetricFact.period_type == source_fact.period_type,
            MetricFact.period_end_date == source_fact.period_end_date,
            MetricFact.as_of_date == source_fact.as_of_date,
            MetricFact.source_type == "manual",
            MetricFact.is_current.is_(True),
        )
        .values(is_current=False)
    )

    manual_fact = MetricFact(
        user_id=user_id,
        stock_id=source_fact.stock_id,
        metric_key=source_fact.metric_key,
        value_json=value_json,
        value_numeric=value_numeric,
        value_text=value_text,
        unit=normalized_unit or source_fact.unit,
        currency=source_fact.currency,
        period=source_fact.period,
        period_type=source_fact.period_type,
        period_end_date=source_fact.period_end_date,
        as_of_date=source_fact.as_of_date,
        source_document_id=source_fact.source_document_id,
        source_type="manual",
        source_ref_id=source_extraction_id,
        is_current=True,
    )
    session.add(manual_fact)
    session.flush()
    ValueLineRatioCalculator(session).calculate_for_stock(
        user_id=user_id,
        stock_id=source_fact.stock_id,
    )
    PiotroskiFScoreCalculator(session).calculate_for_stock(
        user_id=user_id,
        stock_id=source_fact.stock_id,
    )
    return manual_fact


def _fact_metadata(fact: MetricFact) -> dict:
    return fact.value_json if isinstance(fact.value_json, dict) else {}


def _positive_id(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _lineage_unavailable() -> ManualMetricCorrectionError:
    return ManualMetricCorrectionError(
        code="correction_lineage_unavailable",
        message=(
            "Correction source has no exact primary extraction lineage; "
            "manual correction requires review"
        ),
    )


def _same_correction_slot(left: MetricFact, right: MetricFact) -> bool:
    return (
        left.user_id == right.user_id
        and left.stock_id == right.stock_id
        and left.metric_key == right.metric_key
        and left.period_type == right.period_type
        and left.period_end_date == right.period_end_date
        and left.as_of_date == right.as_of_date
        and left.source_document_id == right.source_document_id
    )


def _resolve_manual_original_parsed_fact(
    session: Session,
    *,
    user_id: int,
    manual_fact: MetricFact,
) -> MetricFact:
    """Follow explicit correction ancestry to one parsed source, boundedly."""

    if manual_fact.user_id != user_id:
        raise _lineage_unavailable()
    cursor = manual_fact
    visited: set[int] = set()
    declared_root: int | None = None
    for _ in range(MAX_MANUAL_CORRECTION_ANCESTRY):
        cursor_id = _positive_id(cursor.id)
        if cursor_id is None or cursor_id in visited:
            raise _lineage_unavailable()
        visited.add(cursor_id)
        if cursor.source_type == "parsed":
            if (
                not _same_correction_slot(cursor, manual_fact)
                or (declared_root is not None and cursor_id != declared_root)
            ):
                raise _lineage_unavailable()
            return cursor
        if cursor.source_type != "manual" or not _same_correction_slot(
            cursor, manual_fact
        ):
            raise _lineage_unavailable()
        metadata = _fact_metadata(cursor)
        if metadata.get("correction") is not True:
            raise _lineage_unavailable()
        root_id = _positive_id(metadata.get("source_fact_id"))
        if root_id is not None:
            if root_id in visited or (
                declared_root is not None and root_id != declared_root
            ):
                raise _lineage_unavailable()
            declared_root = root_id
        parent_id = _positive_id(metadata.get("corrected_from_fact_id"))
        if parent_id is None:
            parent_id = root_id
        if parent_id is None or parent_id in visited:
            raise _lineage_unavailable()
        parent = session.get(MetricFact, parent_id)
        if parent is None or parent.user_id != user_id:
            raise _lineage_unavailable()
        cursor = parent
    raise _lineage_unavailable()


def _exact_primary_lineage(
    session: Session,
    *,
    parsed_fact: MetricFact,
) -> tuple[int, int | None]:
    if parsed_fact.source_type != "parsed" or _positive_id(parsed_fact.id) is None:
        raise _lineage_unavailable()
    primary_inputs = session.execute(
        select(
            ValueLineFactExtractionInput.extraction_id,
            ValueLineFactExtractionInput.value_line_parse_run_id,
        )
        .where(
            ValueLineFactExtractionInput.fact_id == parsed_fact.id,
            ValueLineFactExtractionInput.input_role == "primary",
        )
        .limit(2)
    ).all()
    if len(primary_inputs) == 1:
        primary = primary_inputs[0]
        if (
            parsed_fact.value_line_parse_run_id is None
            or primary.value_line_parse_run_id
            != parsed_fact.value_line_parse_run_id
        ):
            raise _lineage_unavailable()
        return primary.extraction_id, primary.value_line_parse_run_id
    raise _lineage_unavailable()


def _normalize_correction(
    *,
    raw_text: str,
    unit_hint: Optional[str],
    fact: MetricFact,
) -> tuple[Optional[float], Optional[str], Optional[str]]:
    value_type = _correction_value_type(fact)
    if value_type == "text":
        return None, fact.unit, raw_text

    normalization_input = raw_text
    if unit_hint and unit_hint.lower() not in raw_text.lower():
        normalization_input = f"{raw_text} {unit_hint}"
    value_numeric, normalized_unit = Scaler.normalize(normalization_input, value_type)
    return value_numeric, normalized_unit, None


def _correction_value_type(fact: MetricFact) -> str:
    metric_key = (fact.metric_key or "").lower()
    unit = (fact.unit or "").lower()
    if fact.value_numeric is None and unit not in {"usd", "ratio", "number", "shares"}:
        return "text"
    if unit == "usd" or any(
        token in metric_key
        for token in (
            "price",
            "market_cap",
            "debt",
            "sales",
            "revenue",
            "cash",
            "earnings",
            "income",
            "dividend",
        )
    ):
        return "currency"
    if unit == "ratio":
        if "%" in str(fact.value_json or "") or any(
            token in metric_key
            for token in ("yield", "pct", "percent", "margin", "cagr", "rate")
        ):
            return "percent"
        return "ratio"
    if any(
        token in metric_key
        for token in ("yield", "pct", "percent", "margin", "cagr")
    ):
        return "percent"
    return "number"
