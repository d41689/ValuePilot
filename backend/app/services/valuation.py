from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.currencies import normalize_iso4217_currency
from app.models.facts import MetricFact
from app.services.metric_fact_currentness import current_metric_fact_ids_at
from app.models.research import ResearchCaseRevision
from app.services.canonical_financials import database_evaluation_cutoff


USER_INTRINSIC_VALUE_KEY = "val.fair_value"
VALUE_LINE_TARGET_REFERENCE_KEY = "target.price_18m.mid"
VALUATION_VALUE_QUANTUM = Decimal("0.000001")
VALUATION_ORIGIN_VERSION = "research-valuation-origin-v1"
VALUATION_ORIGIN_SOURCES = frozenset({"manual", "watchlist", "dcf"})
HUMAN_VALUATION_ORIGINS = frozenset({"manual", "watchlist"})


def quantize_valuation_value(value: Decimal) -> Decimal:
    """Normalize every published valuation to the revision's six-place contract."""

    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return decimal_value.quantize(VALUATION_VALUE_QUANTUM, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class ValuationContext:
    user_intrinsic_value: float | None
    user_intrinsic_value_status: str
    user_intrinsic_value_reason_code: str | None
    user_intrinsic_value_as_of: date | None
    user_intrinsic_value_fact_id: int | None
    user_intrinsic_value_currency: str | None
    system_reference_value: float | None
    system_reference_type: str | None
    system_reference_as_of: date | None
    system_reference_fact_id: int | None
    system_reference_currency: str | None


@dataclass(frozen=True)
class ValuationFactProjection:
    """Read-only fact view used to quarantine an inapplicable retained value."""

    id: int
    user_id: int | None
    stock_id: int
    metric_key: str
    value_numeric: None
    value_json: dict[str, Any]
    unit: str | None
    currency: str | None
    period_type: str | None
    period_end_date: date | None
    source_type: str
    source_ref_id: int | None
    is_current: bool
    created_at: datetime | None


ValuationFact = MetricFact | ValuationFactProjection


def _fact_currency(fact: ValuationFact | None) -> str | None:
    if fact is None:
        return None
    if fact.currency is not None:
        return normalize_iso4217_currency(fact.currency)
    return normalize_iso4217_currency(fact.unit)


def _has_source_type(fact: ValuationFact, *, source_type: str) -> bool:
    return fact.source_type == source_type


def _server_valuation_origin(fact: MetricFact) -> tuple[str, str | None]:
    metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
    if "valuation_origin" not in metadata:
        return "absent", None
    origin = metadata.get("valuation_origin")
    if not isinstance(origin, dict):
        return "invalid", None
    source = origin.get("source")
    if (
        origin.get("version") != VALUATION_ORIGIN_VERSION
        or source not in VALUATION_ORIGIN_SOURCES
        or fact.source_ref_id is None
        or origin.get("research_revision_id") != fact.source_ref_id
    ):
        return "invalid", None
    return "valid", str(source)


def _legacy_valuation_reason(
    revision: Any | None, *, fact: MetricFact
) -> str | None:
    if (
        revision is None
        or revision.is_redacted is True
        or int(revision.created_by_user_id) != fact.user_id
        or int(revision.snapshot_stock_id) != fact.stock_id
    ):
        return "valuation_origin_unverifiable"
    assumptions = revision.assumptions_json
    if not isinstance(assumptions, list):
        return "valuation_origin_unverifiable"
    sources = {
        item.get("source")
        for item in assumptions
        if isinstance(item, dict) and isinstance(item.get("source"), str)
    }
    if "dcf" in sources:
        return "system_valuation_method_pending_ft09"
    if sources & HUMAN_VALUATION_ORIGINS:
        return None
    return "valuation_origin_unverifiable"


def _server_valuation_reason(
    revision: Any | None, *, fact: MetricFact, origin_source: str
) -> str | None:
    """Validate the retained publication identity behind a server origin.

    Revision redaction removes authored research content, not the immutable
    publication source recorded on the fact. A verified DCF publication stays
    quarantined after redaction; a verified human publication remains usable.
    """

    if (
        revision is None
        or int(revision.created_by_user_id) != fact.user_id
        or int(revision.snapshot_stock_id) != fact.stock_id
    ):
        return "valuation_origin_unverifiable"
    if origin_source == "dcf":
        return "system_valuation_method_pending_ft09"
    return None


def _latest_current_fact(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    source_type: str | None = None,
) -> MetricFact | None:
    knowledge_cutoff = database_evaluation_cutoff(session)
    stmt = select(MetricFact).where(
        MetricFact.user_id == user_id,
        MetricFact.stock_id == stock_id,
        MetricFact.metric_key == metric_key,
        MetricFact.id.in_(
            current_metric_fact_ids_at(
                session, knowledge_cutoff=knowledge_cutoff
            )
        ),
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
    knowledge_cutoff: datetime | None = None,
) -> ValuationContext:
    return read_valuation_contexts(
        session,
        user_id=user_id,
        stock_ids=[stock_id],
        knowledge_cutoff=knowledge_cutoff,
    )[stock_id]


def _valuation_context_from_facts(
    facts: dict[str, ValuationFact],
) -> ValuationContext:
    manual = facts.get(USER_INTRINSIC_VALUE_KEY)
    reference = facts.get(VALUE_LINE_TARGET_REFERENCE_KEY)

    if manual is None:
        intrinsic_status = "missing"
        intrinsic_reason = None
        intrinsic_value = None
    elif (
        isinstance(manual.value_json, dict)
        and manual.value_json.get("status") == "unsupported"
    ):
        intrinsic_status = "unsupported"
        reason = manual.value_json.get("reason_code")
        intrinsic_reason = reason if isinstance(reason, str) else None
        intrinsic_value = None
    elif manual.value_numeric is None:
        intrinsic_status = "unavailable"
        intrinsic_reason = None
        intrinsic_value = None
    else:
        intrinsic_status = "available"
        intrinsic_reason = None
        intrinsic_value = float(manual.value_numeric)

    reference_value = (
        float(reference.value_numeric)
        if reference is not None and reference.value_numeric is not None
        else None
    )
    return ValuationContext(
        user_intrinsic_value=intrinsic_value,
        user_intrinsic_value_status=intrinsic_status,
        user_intrinsic_value_reason_code=intrinsic_reason,
        user_intrinsic_value_as_of=manual.period_end_date if manual else None,
        user_intrinsic_value_fact_id=manual.id if manual else None,
        user_intrinsic_value_currency=_fact_currency(manual),
        system_reference_value=reference_value,
        system_reference_type=(
            VALUE_LINE_TARGET_REFERENCE_KEY if reference_value is not None else None
        ),
        system_reference_as_of=reference.period_end_date if reference else None,
        system_reference_fact_id=reference.id if reference else None,
        system_reference_currency=_fact_currency(reference),
    )


def read_valuation_contexts(
    session: Session,
    *,
    user_id: int,
    stock_ids: list[int],
    knowledge_cutoff: datetime | None = None,
) -> dict[int, ValuationContext]:
    """Return valuation contexts with one user-scoped metric-fact query."""

    unique_stock_ids = list(dict.fromkeys(int(stock_id) for stock_id in stock_ids))
    facts_by_stock_id = read_valuation_facts_by_stock(
        session,
        user_id=user_id,
        stock_ids=unique_stock_ids,
        knowledge_cutoff=knowledge_cutoff,
    )
    return {
        stock_id: _valuation_context_from_facts(facts_by_stock_id[stock_id])
        for stock_id in unique_stock_ids
    }


def read_valuation_facts_by_stock(
    session: Session,
    *,
    user_id: int | None,
    stock_ids: list[int],
    knowledge_cutoff: datetime | None = None,
) -> dict[int, dict[str, ValuationFact]]:
    """Canonical, user-scoped valuation facts for batched product overlays.

    Anonymous callers receive no user-owned facts.  This matters for both the
    manually authored intrinsic value and parsed Value Line references: both
    belong to the uploading user and must never be selected across tenants.
    """
    unique_stock_ids = sorted(set(stock_ids))
    result: dict[int, dict[str, ValuationFact]] = {
        stock_id: {} for stock_id in unique_stock_ids
    }
    if user_id is None or not unique_stock_ids:
        return result
    if knowledge_cutoff is None:
        knowledge_cutoff = database_evaluation_cutoff(session)
    if knowledge_cutoff.tzinfo is None:
        raise ValueError("knowledge cutoff must be timezone-aware")
    fact_query = select(MetricFact).where(
        MetricFact.user_id == user_id,
        MetricFact.stock_id.in_(unique_stock_ids),
        MetricFact.metric_key.in_(
            [USER_INTRINSIC_VALUE_KEY, VALUE_LINE_TARGET_REFERENCE_KEY]
        ),
        MetricFact.id.in_(
            current_metric_fact_ids_at(
                session, knowledge_cutoff=knowledge_cutoff
            )
        ),
    )
    facts = session.scalars(
        fact_query
        .order_by(
            MetricFact.stock_id.asc(),
            MetricFact.period_end_date.desc().nullslast(),
            MetricFact.created_at.desc(),
            MetricFact.id.desc(),
        )
    ).all()
    revision_ids = {
        int(fact.source_ref_id)
        for fact in facts
        if fact.metric_key == USER_INTRINSIC_VALUE_KEY
        and fact.source_ref_id is not None
    }
    if revision_ids:
        revisions = session.execute(
            select(
                ResearchCaseRevision.id,
                ResearchCaseRevision.created_by_user_id,
                ResearchCaseRevision.snapshot_stock_id,
                ResearchCaseRevision.assumptions_json,
                ResearchCaseRevision.is_redacted,
            ).where(
                ResearchCaseRevision.id.in_(revision_ids),
                ResearchCaseRevision.created_by_user_id == user_id,
                ResearchCaseRevision.snapshot_stock_id.in_(unique_stock_ids),
            )
        ).all()
        revisions_by_id = {int(revision.id): revision for revision in revisions}
    else:
        revisions_by_id = {}
    for fact in facts:
        if (
            fact.metric_key == USER_INTRINSIC_VALUE_KEY
            and not _has_source_type(fact, source_type="manual")
        ):
            continue
        if (
            fact.metric_key == VALUE_LINE_TARGET_REFERENCE_KEY
            and not _has_source_type(fact, source_type="parsed")
        ):
            continue
        selected: ValuationFact = fact
        blocked_reason = None
        if fact.metric_key == USER_INTRINSIC_VALUE_KEY:
            origin_state, origin_source = _server_valuation_origin(fact)
            if origin_state == "invalid":
                blocked_reason = "valuation_origin_unverifiable"
            elif origin_state == "valid" and origin_source is not None:
                blocked_reason = _server_valuation_reason(
                    revisions_by_id.get(int(fact.source_ref_id)),
                    fact=fact,
                    origin_source=origin_source,
                )
            elif origin_state == "absent" and fact.source_ref_id is not None:
                blocked_reason = _legacy_valuation_reason(
                    revisions_by_id.get(int(fact.source_ref_id)), fact=fact
                )
        if blocked_reason is not None:
            selected = ValuationFactProjection(
                id=int(fact.id),
                user_id=fact.user_id,
                stock_id=int(fact.stock_id),
                metric_key=fact.metric_key,
                value_numeric=None,
                value_json={
                    "status": "unsupported",
                    "reason_code": blocked_reason,
                },
                unit=fact.unit,
                currency=fact.currency,
                period_type=fact.period_type,
                period_end_date=fact.period_end_date,
                source_type=fact.source_type,
                source_ref_id=fact.source_ref_id,
                is_current=fact.is_current,
                created_at=fact.created_at,
            )
        result[fact.stock_id].setdefault(fact.metric_key, selected)
    return result


def publish_user_intrinsic_value(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    value_numeric: Decimal | None,
    as_of_date: date,
    unavailable_reason: str | None = None,
    source_ref_id: int | None = None,
    valuation_origin: str | None = None,
) -> MetricFact:
    persisted_value = (
        quantize_valuation_value(value_numeric) if value_numeric is not None else None
    )
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

    if valuation_origin is not None and valuation_origin not in VALUATION_ORIGIN_SOURCES:
        raise ValueError("unsupported valuation_origin")
    if valuation_origin is not None and source_ref_id is None:
        raise ValueError("valuation_origin requires a research revision")

    value_json: dict[str, Any] | None = None
    if value_numeric is None:
        value_json = {
            "status": "unavailable",
            "reason": unavailable_reason or "user_cleared",
        }
    if valuation_origin is not None:
        value_json = {
            **(value_json or {}),
            "valuation_origin": {
                "version": VALUATION_ORIGIN_VERSION,
                "source": valuation_origin,
                "research_revision_id": source_ref_id,
            },
        }

    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=USER_INTRINSIC_VALUE_KEY,
        value_numeric=persisted_value,
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
        metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
        fact.value_json = {
            "status": "unavailable",
            "reason": "[redacted]",
            "redaction_content_hash": content_hash,
            **(
                {"valuation_origin": metadata["valuation_origin"]}
                if "valuation_origin" in metadata
                else {}
            ),
        }


def relative_discount(price: float | None, reference: float | None) -> float | None:
    if price is None or reference is None or reference == 0:
        return None
    return (reference - price) / reference
