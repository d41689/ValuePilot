from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import String, and_, cast, exists, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.services.financial_truth_locks import (
    acquire_active_account_mutation_lock,
    acquire_user_stock_fact_lock,
)
from app.services.metric_fact_visibility import visible_metric_fact_predicate


USER_INTRINSIC_VALUE_KEY = "val.fair_value"
VALUE_LINE_TARGET_REFERENCE_KEY = "target.price_18m.mid"
VALUE_LINE_TARGET_MANUAL_CORRECTION_REFERENCE = (
    "target.price_18m.mid.manual_correction"
)


@dataclass(frozen=True)
class ValuationContext:
    user_intrinsic_value: float | None
    user_intrinsic_value_status: str
    user_intrinsic_value_as_of: date | None
    user_intrinsic_value_fact_id: int | None
    system_reference_value: float | None
    system_reference_type: str | None
    system_reference_as_of: date | None
    system_reference_fact_id: int | None


def _valuation_source_predicate(fact_entity, *, user_id: int):
    """Restrict valuation claims to their exact, user-visible authority."""
    original = aliased(MetricFact)
    document = aliased(PdfDocument)
    extraction = aliased(MetricExtraction)
    exact_document_correction = exists(
        select(original.id)
        .join(document, document.id == original.source_document_id)
        .join(extraction, extraction.id == original.source_ref_id)
        .where(
            or_(
                cast(original.id, String)
                == fact_entity.value_json["corrected_from_fact_id"].as_string(),
                cast(extraction.id, String)
                == fact_entity.value_json[
                    "corrected_from_extraction_id"
                ].as_string(),
            ),
            original.user_id == fact_entity.user_id,
            original.stock_id == fact_entity.stock_id,
            original.metric_key == fact_entity.metric_key,
            original.period_type.is_not_distinct_from(fact_entity.period_type),
            original.period_end_date.is_not_distinct_from(
                fact_entity.period_end_date
            ),
            original.as_of_date.is_not_distinct_from(fact_entity.as_of_date),
            original.source_type == "parsed",
            original.source_document_id == fact_entity.source_document_id,
            original.source_ref_id == fact_entity.source_ref_id,
            original.is_current.is_(True),
            func.parsed_metric_fact_has_exact_authority(original.id).is_(True),
            document.user_id == user_id,
            or_(
                document.stock_id.is_(None),
                document.stock_id == fact_entity.stock_id,
            ),
            document.lifecycle_state == "active",
            document.current_parse_generation == original.parse_generation,
            extraction.user_id == user_id,
            extraction.document_id == document.id,
            extraction.resolved_stock_id == fact_entity.stock_id,
            extraction.parse_generation == original.parse_generation,
            extraction.original_text_snippet.is_not(None),
        )
    )
    return and_(
        visible_metric_fact_predicate(fact_entity, user_id=user_id),
        or_(
            and_(
                fact_entity.metric_key == USER_INTRINSIC_VALUE_KEY,
                fact_entity.source_type == "manual",
            ),
            and_(
                fact_entity.metric_key == VALUE_LINE_TARGET_REFERENCE_KEY,
                fact_entity.source_type == "parsed",
            ),
            and_(
                fact_entity.metric_key == VALUE_LINE_TARGET_REFERENCE_KEY,
                fact_entity.source_type == "manual",
                fact_entity.source_document_id.is_not(None),
                fact_entity.value_json["correction"].as_boolean().is_(True),
                exact_document_correction,
            ),
        ),
    )


def _latest_current_fact(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    source_type: str | None = None,
) -> MetricFact | None:
    stmt = select(MetricFact).where(
        MetricFact.user_id == user_id,
        MetricFact.stock_id == stock_id,
        MetricFact.metric_key == metric_key,
        MetricFact.is_current.is_(True),
        _valuation_source_predicate(MetricFact, user_id=user_id),
    )
    if source_type is not None:
        stmt = stmt.where(MetricFact.source_type == source_type)
    return session.scalars(
        stmt.order_by(
            MetricFact.period_end_date.desc().nullslast(),
            MetricFact.created_at.desc(),
            MetricFact.id.desc(),
        ).limit(1)
    ).first()


def read_valuation_context(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
) -> ValuationContext:
    manual = _latest_current_fact(
        session,
        user_id=user_id,
        stock_id=stock_id,
        metric_key=USER_INTRINSIC_VALUE_KEY,
        source_type="manual",
    )
    reference = _latest_current_fact(
        session,
        user_id=user_id,
        stock_id=stock_id,
        metric_key=VALUE_LINE_TARGET_REFERENCE_KEY,
    )

    if manual is None:
        intrinsic_status = "missing"
        intrinsic_value = None
    elif manual.value_numeric is None:
        intrinsic_status = "unavailable"
        intrinsic_value = None
    else:
        intrinsic_status = "available"
        intrinsic_value = float(manual.value_numeric)

    reference_value = (
        float(reference.value_numeric)
        if reference is not None and reference.value_numeric is not None
        else None
    )
    return ValuationContext(
        user_intrinsic_value=intrinsic_value,
        user_intrinsic_value_status=intrinsic_status,
        user_intrinsic_value_as_of=manual.period_end_date if manual else None,
        user_intrinsic_value_fact_id=manual.id if manual else None,
        system_reference_value=reference_value,
        system_reference_type=(
            (
                VALUE_LINE_TARGET_MANUAL_CORRECTION_REFERENCE
                if reference is not None and reference.source_type == "manual"
                else VALUE_LINE_TARGET_REFERENCE_KEY
            )
            if reference_value is not None
            else None
        ),
        system_reference_as_of=reference.period_end_date if reference else None,
        system_reference_fact_id=reference.id if reference else None,
    )


def read_valuation_facts_by_stock(
    session: Session,
    *,
    user_id: int | None,
    stock_ids: list[int],
) -> dict[int, dict[str, MetricFact]]:
    """Canonical, user-scoped valuation facts for batched product overlays.

    Anonymous callers receive no user-owned facts.  This matters for both the
    manually authored intrinsic value and parsed Value Line references: both
    belong to the uploading user and must never be selected across tenants.
    """
    unique_stock_ids = sorted(set(stock_ids))
    result: dict[int, dict[str, MetricFact]] = {
        stock_id: {} for stock_id in unique_stock_ids
    }
    if user_id is None or not unique_stock_ids:
        return result
    facts = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id.in_(unique_stock_ids),
            MetricFact.metric_key.in_(
                [USER_INTRINSIC_VALUE_KEY, VALUE_LINE_TARGET_REFERENCE_KEY]
            ),
            MetricFact.is_current.is_(True),
            _valuation_source_predicate(MetricFact, user_id=user_id),
        )
        .order_by(
            MetricFact.stock_id.asc(),
            MetricFact.period_end_date.desc().nullslast(),
            MetricFact.created_at.desc(),
            MetricFact.id.desc(),
        )
    ).all()
    for fact in facts:
        result[fact.stock_id].setdefault(fact.metric_key, fact)
    return result


def publish_user_intrinsic_value(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    value_numeric: float | None,
    as_of_date: date,
    source_ref_id: int,
    unavailable_reason: str | None = None,
) -> MetricFact:
    if not acquire_active_account_mutation_lock(session, user_id=user_id):
        raise ValueError("Account no longer accepts valuation changes")
    acquire_user_stock_fact_lock(session, user_id=user_id, stock_id=stock_id)
    session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == USER_INTRINSIC_VALUE_KEY,
            MetricFact.period_type == "AS_OF",
            MetricFact.period_end_date == as_of_date,
            MetricFact.source_type == "manual",
            MetricFact.is_current.is_(True),
        )
        .values(is_current=False)
    )

    value_json: dict[str, Any] | None = None
    if value_numeric is None:
        value_json = {
            "status": "unavailable",
            "reason": unavailable_reason or "user_cleared",
        }

    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=USER_INTRINSIC_VALUE_KEY,
        value_numeric=value_numeric,
        value_json=value_json,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=as_of_date,
        source_type="manual",
        source_ref_id=source_ref_id,
        is_current=True,
    )
    session.add(fact)
    session.flush()
    return fact


def redact_published_unavailable_reason(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    revision_id: int,
    content_hash: str,
) -> None:
    """Apply the narrow privacy redaction to duplicated user-authored text.

    The fact and its numeric/provenance identity remain intact. Only an
    unavailable reason copied from the research revision is tombstoned.
    """
    facts = session.scalars(
        select(MetricFact).where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == USER_INTRINSIC_VALUE_KEY,
            MetricFact.source_type == "manual",
            MetricFact.source_ref_id == revision_id,
            MetricFact.value_numeric.is_(None),
        )
    ).all()
    for fact in facts:
        fact.value_json = {
            "status": "unavailable",
            "reason": "[redacted]",
            "redaction_content_hash": content_hash,
        }


def relative_discount(price: float | None, reference: float | None) -> float | None:
    if price is None or reference is None or reference == 0:
        return None
    return (reference - price) / reference
