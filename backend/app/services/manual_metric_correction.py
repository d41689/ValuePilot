"""Canonical append-only manual correction for one exact metric-fact slot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ingestion.normalization.scaler import Scaler
from app.models.facts import MetricFact
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.services.metric_fact_locking import acquire_metric_fact_stock_lock


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

    source_metadata = (
        source_fact.value_json if isinstance(source_fact.value_json, dict) else {}
    )
    original_source_fact_id = (
        source_metadata.get("source_fact_id")
        if source_fact.source_type == "manual"
        else source_fact.id
    )
    if not isinstance(original_source_fact_id, int):
        original_source_fact_id = source_fact.id

    source_extraction_id = source_metadata.get("source_extraction_id")
    if not isinstance(source_extraction_id, int):
        source_extraction_id = source_fact.source_ref_id
    source_parse_run_id = source_metadata.get("source_parse_run_id")
    if not isinstance(source_parse_run_id, int):
        source_parse_run_id = source_fact.value_line_parse_run_id

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
        if identity_key in source_metadata:
            value_json[identity_key] = source_metadata[identity_key]
    if note:
        value_json["note"] = str(note)

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
