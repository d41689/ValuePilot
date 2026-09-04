"""Shared canonical-financial visibility, source, method, and evidence guards.

Fundamental values are always read from ``metric_facts``.  SEC lineage tables
are used only to resolve bounded evidence for a selected canonical fact or a
typed unavailable publication decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException
import re
from typing import Any, Iterable

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact


CANONICAL_SOURCE_TYPES = frozenset({"sec", "parsed", "manual", "calculated"})
SYSTEM_METHOD_KEYS = frozenset(
    {"owner_earnings", "roic", "per_share_trend", "system_valuation"}
)
PIOTROSKI_PREFIX = "score.piotroski."
PIOTROSKI_TOTAL_CAPITAL_KEY = "returns.total_capital"
PIOTROSKI_TOTAL_KEY = "score.piotroski.total"
MAX_PIOTROSKI_REQUEST_FACTS = 500
MAX_PIOTROSKI_PERIOD_GROUPS = 50
MAX_PIOTROSKI_MANIFEST_INPUTS = 32
MAX_PIOTROSKI_UNIQUE_INPUT_IDS = 1_000
MAX_PIOTROSKI_CURRENT_SIBLINGS_PER_PERIOD = 10


class CanonicalSourceConflictError(ValueError):
    code = "source_conflict"

    def __init__(self, *, consumer: str, source_types: Iterable[str]):
        self.consumer = consumer
        self.source_types = tuple(sorted(set(source_types)))
        super().__init__(
            f"{consumer} requires an explicit source selection; available sources: "
            + ", ".join(self.source_types)
        )


class UnsupportedSystemMethodError(ValueError):
    code = "unsupported"

    def __init__(self, decision: "MethodGateDecision"):
        self.decision = decision
        super().__init__(f"{decision.method_key} is unsupported: {decision.reason_code}")


class CanonicalUnavailableError(ValueError):
    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.code = str(state["reason_code"])
        super().__init__(f"canonical SEC facts are unavailable: {self.code}")


class PiotroskiMethodAuthorityError(ValueError):
    def __init__(self, state: dict[str, Any]):
        self.state = state
        self.code = str(state["reason_code"])
        super().__init__(f"Piotroski input authority is unavailable: {self.code}")


@dataclass(frozen=True)
class RiskReviewSnapshot:
    risk_attribute: str
    review_id: int
    is_present: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk_attribute": self.risk_attribute,
            "review_id": self.review_id,
            "is_present": self.is_present,
        }


@dataclass(frozen=True)
class MethodGateDecision:
    method_key: str
    status: str
    reason_code: str
    method_policy_version_id: str | None
    policy_sha256: str | None
    economic_class: str
    classification_review_id: int | None
    method_version_id: str | None
    required_evidence: tuple[str, ...]
    required_adjustments: tuple[str, ...]
    required_outputs: tuple[str, ...]
    required_risk_reviews: tuple[str, ...]
    risk_review_ids: tuple[int, ...]
    risk_reviews: tuple[RiskReviewSnapshot, ...]
    risk_attributes: tuple[str, ...]
    missing_risk_reviews: tuple[str, ...]
    unsupported_reasons: tuple[str, ...]
    effective_as_of: date
    knowledge_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_key": self.method_key,
            "status": self.status,
            "reason_code": self.reason_code,
            "method_policy_version_id": self.method_policy_version_id,
            "policy_sha256": self.policy_sha256,
            "economic_class": self.economic_class,
            "classification_review_id": self.classification_review_id,
            "method_version_id": self.method_version_id,
            "required_evidence": list(self.required_evidence),
            "required_adjustments": list(self.required_adjustments),
            "required_outputs": list(self.required_outputs),
            "required_risk_reviews": list(self.required_risk_reviews),
            "risk_review_ids": list(self.risk_review_ids),
            "risk_reviews": [review.as_dict() for review in self.risk_reviews],
            "risk_attributes": list(self.risk_attributes),
            "missing_risk_reviews": list(self.missing_risk_reviews),
            "unsupported_reasons": list(self.unsupported_reasons),
            "effective_as_of": self.effective_as_of.isoformat(),
            "knowledge_at": self.knowledge_at.isoformat(),
        }


def _method_decision(
    *,
    method_key: str,
    status: str,
    reason_code: str,
    method_policy_version_id: str | None,
    policy_sha256: str | None,
    economic_class: str,
    classification_review_id: int | None,
    effective_as_of: date,
    knowledge_at: datetime,
    method_version_id: str | None = None,
    required_evidence: tuple[str, ...] = (),
    required_adjustments: tuple[str, ...] = (),
    required_outputs: tuple[str, ...] = (),
    required_risk_reviews: tuple[str, ...] = (),
    risk_review_ids: tuple[int, ...] = (),
    risk_reviews: tuple[RiskReviewSnapshot, ...] = (),
    risk_attributes: tuple[str, ...] = (),
    missing_risk_reviews: tuple[str, ...] = (),
    unsupported_reasons: tuple[str, ...] = (),
) -> MethodGateDecision:
    return MethodGateDecision(
        method_key=method_key,
        status=status,
        reason_code=reason_code,
        method_policy_version_id=method_policy_version_id,
        policy_sha256=policy_sha256,
        economic_class=economic_class,
        classification_review_id=classification_review_id,
        method_version_id=method_version_id,
        required_evidence=required_evidence,
        required_adjustments=required_adjustments,
        required_outputs=required_outputs,
        required_risk_reviews=required_risk_reviews,
        risk_review_ids=risk_review_ids,
        risk_reviews=risk_reviews,
        risk_attributes=risk_attributes,
        missing_risk_reviews=missing_risk_reviews,
        unsupported_reasons=unsupported_reasons,
        effective_as_of=effective_as_of,
        knowledge_at=knowledge_at,
    )


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def visible_metric_fact_predicate(fact_entity: Any, *, user_id: int):
    """SEC is shared; every non-SEC fact remains owned by the requesting user."""

    return or_(
        and_(fact_entity.source_type == "sec", fact_entity.user_id.is_(None)),
        and_(fact_entity.source_type != "sec", fact_entity.user_id == user_id),
    )


def _fact_source_type(fact: Any) -> str | None:
    """Return the fact's canonical role without interpreting lineage metadata."""

    source_type = (
        fact.get("source_type") if isinstance(fact, dict) else getattr(fact, "source_type", None)
    )
    return source_type if isinstance(source_type, str) and source_type else None


def guard_source_selection(
    facts: Iterable[Any],
    *,
    consumer: str,
    selected_source_type: str | None = None,
) -> list[Any]:
    """Reject implicit cross-source precedence and return the bounded selection."""

    materialized = list(facts)
    if selected_source_type is not None:
        if selected_source_type not in CANONICAL_SOURCE_TYPES:
            raise ValueError("unsupported source_type selection")
        return [
            fact
            for fact in materialized
            if selected_source_type == _fact_source_type(fact)
        ]
    source_types = {
        source_type
        for fact in materialized
        if (source_type := _fact_source_type(fact)) is not None
    }
    if len(source_types) > 1:
        raise CanonicalSourceConflictError(consumer=consumer, source_types=source_types)
    return materialized


def reviewed_method_gate(
    session: Session,
    *,
    stock_id: int,
    method_key: str,
    effective_as_of: date,
    knowledge_at: datetime | None = None,
) -> MethodGateDecision:
    """Resolve the reviewed effective/knowledge-dated method authority."""

    if method_key not in SYSTEM_METHOD_KEYS:
        raise ValueError("unsupported method_key")
    cutoff = knowledge_at or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError("knowledge_at must be timezone-aware")
    policy = session.execute(
        text(
            """
            SELECT id, policy_sha256
            FROM sec_method_policy_versions
            WHERE status='approved' AND effective_from<=:cutoff AND known_at<=:cutoff
              AND NOT EXISTS (
                SELECT 1 FROM sec_method_policy_versions later
                WHERE later.status='approved' AND later.effective_from<=:cutoff
                  AND later.known_at<=:cutoff
                  AND (later.effective_from, later.known_at, later.id)>
                      (sec_method_policy_versions.effective_from,
                       sec_method_policy_versions.known_at,
                       sec_method_policy_versions.id)
              )
            LIMIT 1
            """
        ),
        {"cutoff": cutoff},
    ).mappings().first()
    if policy is None:
        return _method_decision(
            method_key=method_key,
            status="unsupported",
            reason_code="method_policy_unavailable",
            method_policy_version_id=None,
            policy_sha256=None,
            economic_class="unclassified",
            classification_review_id=None,
            effective_as_of=effective_as_of,
            knowledge_at=cutoff,
            unsupported_reasons=("method_policy_unavailable",),
        )
    classifications = session.execute(
        text(
            """
            WITH RECURSIVE review_descendants AS (
                SELECT root.id AS ancestor_id, root.id AS descendant_id,
                       root.effective_from AS descendant_effective_from,
                       root.effective_to AS descendant_effective_to
                FROM sec_economic_classification_reviews root
                WHERE root.stock_id=:stock_id
                  AND root.effective_from<=:as_of
                  AND (root.effective_to IS NULL OR root.effective_to>=:as_of)
                  AND root.known_at<=:cutoff
                UNION ALL
                SELECT path.ancestor_id, later.id, later.effective_from,
                       later.effective_to
                FROM review_descendants path
                JOIN sec_economic_classification_reviews later
                  ON later.supersedes_review_id=path.descendant_id
                WHERE later.stock_id=:stock_id AND later.known_at<=:cutoff
            )
            SELECT r.id, r.economic_class
            FROM sec_economic_classification_reviews r
            WHERE r.stock_id=:stock_id AND r.effective_from<=:as_of
              AND (r.effective_to IS NULL OR r.effective_to>=:as_of)
              AND r.known_at<=:cutoff
              AND NOT EXISTS (
                SELECT 1 FROM review_descendants later
                WHERE later.ancestor_id=r.id AND later.descendant_id<>r.id
                  AND later.descendant_effective_from<=:as_of
                  AND (later.descendant_effective_to IS NULL
                       OR later.descendant_effective_to>=:as_of)
              )
            ORDER BY r.known_at DESC, r.id DESC
            LIMIT 2
            """
        ),
        {"stock_id": stock_id, "as_of": effective_as_of, "cutoff": cutoff},
    ).mappings().all()
    if len(classifications) != 1:
        reason = "classification_unreviewed" if not classifications else "classification_conflict"
        return _method_decision(
            method_key=method_key,
            status="unsupported",
            reason_code=reason,
            method_policy_version_id=policy.id,
            policy_sha256=policy.policy_sha256,
            economic_class="unclassified",
            classification_review_id=None,
            effective_as_of=effective_as_of,
            knowledge_at=cutoff,
            unsupported_reasons=(reason,),
        )
    classification = classifications[0]
    economic_class = classification.economic_class
    rule = session.execute(
        text(
            """
            SELECT applicability, method_version_id, required_evidence_json,
                   required_outputs_json, required_risk_reviews_json,
                   required_adjustments_json, unsupported_reason_code
            FROM sec_method_policy_rules
            WHERE method_policy_version_id=:policy_id
              AND method_key=:method_key AND economic_class=:economic_class
            """
        ),
        {
            "policy_id": policy.id,
            "method_key": method_key,
            "economic_class": economic_class,
        },
    ).mappings().first()
    if rule is None:
        return _method_decision(
            method_key=method_key,
            status="unsupported",
            reason_code="method_rule_unavailable",
            method_policy_version_id=policy.id,
            policy_sha256=policy.policy_sha256,
            economic_class=economic_class,
            classification_review_id=classification.id,
            effective_as_of=effective_as_of,
            knowledge_at=cutoff,
            unsupported_reasons=("method_rule_unavailable",),
        )
    required_evidence = _string_tuple(rule.required_evidence_json)
    required_outputs = _string_tuple(rule.required_outputs_json)
    required_risk_reviews = _string_tuple(rule.required_risk_reviews_json)
    required_adjustments = _string_tuple(rule.required_adjustments_json)
    decision_fields: dict[str, Any] = {
        "method_key": method_key,
        "method_policy_version_id": policy.id,
        "policy_sha256": policy.policy_sha256,
        "economic_class": economic_class,
        "classification_review_id": classification.id,
        "effective_as_of": effective_as_of,
        "knowledge_at": cutoff,
        "required_evidence": required_evidence,
        "required_adjustments": required_adjustments,
        "required_outputs": required_outputs,
        "required_risk_reviews": required_risk_reviews,
    }
    risk_rows = session.execute(
        text(
            """
            WITH RECURSIVE review_descendants AS (
                SELECT root.id AS ancestor_id, root.id AS descendant_id,
                       root.effective_from AS descendant_effective_from,
                       root.effective_to AS descendant_effective_to
                FROM sec_economic_risk_attribute_reviews root
                WHERE root.stock_id=:stock_id
                  AND root.effective_from<=:as_of
                  AND (root.effective_to IS NULL OR root.effective_to>=:as_of)
                  AND root.known_at<=:cutoff
                UNION ALL
                SELECT path.ancestor_id, later.id, later.effective_from,
                       later.effective_to
                FROM review_descendants path
                JOIN sec_economic_risk_attribute_reviews later
                  ON later.supersedes_review_id=path.descendant_id
                WHERE later.stock_id=:stock_id AND later.known_at<=:cutoff
            )
            SELECT r.id, r.risk_attribute, r.is_present
            FROM sec_economic_risk_attribute_reviews r
            WHERE r.stock_id=:stock_id AND r.effective_from<=:as_of
              AND (r.effective_to IS NULL OR r.effective_to>=:as_of)
              AND r.known_at<=:cutoff
              AND NOT EXISTS (
                SELECT 1 FROM review_descendants later
                WHERE later.ancestor_id=r.id AND later.descendant_id<>r.id
                  AND later.descendant_effective_from<=:as_of
                  AND (later.descendant_effective_to IS NULL
                       OR later.descendant_effective_to>=:as_of)
              )
            ORDER BY r.risk_attribute, r.known_at DESC, r.id DESC
            """
        ),
        {"stock_id": stock_id, "as_of": effective_as_of, "cutoff": cutoff},
    ).mappings().all()
    by_risk: dict[str, list[Any]] = {attribute: [] for attribute in required_risk_reviews}
    for row in risk_rows:
        if row.risk_attribute in by_risk:
            by_risk[row.risk_attribute].append(row)
    risk_reviews = tuple(
        RiskReviewSnapshot(
            risk_attribute=attribute,
            review_id=int(row.id),
            is_present=row.is_present is True,
        )
        for attribute in required_risk_reviews
        for row in by_risk[attribute]
    )
    risk_review_ids = tuple(review.review_id for review in risk_reviews)
    conflicts = tuple(
        attribute for attribute in required_risk_reviews if len(by_risk[attribute]) > 1
    )
    if conflicts:
        return _method_decision(
            **decision_fields,
            status="unsupported",
            reason_code="risk_review_conflict",
            method_version_id=rule.method_version_id,
            risk_review_ids=risk_review_ids,
            risk_reviews=risk_reviews,
            unsupported_reasons=tuple(f"risk_review_conflict:{item}" for item in conflicts),
        )
    missing = tuple(
        attribute for attribute in required_risk_reviews if not by_risk[attribute]
    )
    present = tuple(
        attribute
        for attribute in required_risk_reviews
        if by_risk[attribute] and by_risk[attribute][0].is_present is True
    )
    if rule.applicability != "approved":
        reason = rule.unsupported_reason_code or "method_unsupported"
        detail_reasons = [reason]
        detail_reasons.extend(f"risk_review_conflict:{item}" for item in conflicts)
        detail_reasons.extend(f"risk_review_missing:{item}" for item in missing)
        detail_reasons.extend(f"reviewed_risk_attribute:{item}" for item in present)
        return _method_decision(
            **decision_fields,
            status="unsupported",
            reason_code=reason,
            risk_review_ids=risk_review_ids,
            risk_reviews=risk_reviews,
            risk_attributes=present,
            missing_risk_reviews=missing,
            unsupported_reasons=tuple(detail_reasons),
        )
    if not isinstance(rule.method_version_id, str) or not rule.method_version_id:
        return _method_decision(
            **decision_fields,
            status="unsupported",
            reason_code="method_policy_invalid",
            risk_review_ids=risk_review_ids,
            risk_reviews=risk_reviews,
            risk_attributes=present,
            missing_risk_reviews=missing,
            unsupported_reasons=("method_version_missing",),
        )
    if missing:
        return _method_decision(
            **decision_fields,
            status="unsupported",
            reason_code="risk_review_incomplete",
            method_version_id=rule.method_version_id,
            risk_review_ids=risk_review_ids,
            risk_reviews=risk_reviews,
            missing_risk_reviews=missing,
            unsupported_reasons=tuple(f"risk_review_missing:{item}" for item in missing),
        )
    if present:
        return _method_decision(
            **decision_fields,
            status="unsupported",
            reason_code="reviewed_risk_attribute_unsupported",
            method_version_id=rule.method_version_id,
            risk_review_ids=risk_review_ids,
            risk_reviews=risk_reviews,
            risk_attributes=present,
            unsupported_reasons=tuple(
                f"reviewed_risk_attribute:{item}" for item in present
            ),
        )
    return _method_decision(
        **decision_fields,
        status="approved",
        reason_code="approved",
        method_version_id=rule.method_version_id,
        risk_review_ids=risk_review_ids,
        risk_reviews=risk_reviews,
    )


def require_reviewed_method(*args: Any, **kwargs: Any) -> MethodGateDecision:
    decision = reviewed_method_gate(*args, **kwargs)
    if decision.status != "approved":
        raise UnsupportedSystemMethodError(decision)
    return decision


def system_method_for_metric_key(key: str) -> str | None:
    if key.startswith("owners_earnings_per_share"):
        return "owner_earnings"
    if key in {
        "returns.roic",
        "roic",
        "returns.total_capital",
        "bs.return_on_total_capital",
    } or key.startswith("returns.roic."):
        return "roic"
    if (
        key.startswith("per_share_trend.")
        or key.startswith("trend.per_share.")
        or (key.startswith("rates.") and ".cagr_" in key)
    ):
        return "per_share_trend"
    if key == "system_valuation" or key.startswith("system_valuation."):
        return "system_valuation"
    return None


def system_method_for_fact(fact: MetricFact) -> str | None:
    return system_method_for_metric_key(fact.metric_key)


def is_reserved_system_output_key(key: str) -> bool:
    """Return whether users may not publish a formula under this system key."""

    return system_method_for_metric_key(key) is not None or key.startswith(
        PIOTROSKI_PREFIX
    )


def _owner_earnings_origin_error(
    session: Session, *, stock_id: int, fact: MetricFact
) -> str | None:
    if fact.source_type != "calculated":
        return None
    metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
    snapshot = metadata.get("analysis_method")
    if snapshot is None:
        return "method_authority_snapshot_missing"
    if not isinstance(snapshot, dict):
        return "method_authority_snapshot_invalid"
    try:
        effective_raw = snapshot.get("effective_as_of")
        knowledge_raw = snapshot.get("knowledge_at")
        if not isinstance(effective_raw, str) or not isinstance(knowledge_raw, str):
            return "method_authority_snapshot_invalid"
        origin_effective_as_of = date.fromisoformat(effective_raw)
        origin_knowledge_at = datetime.fromisoformat(knowledge_raw.replace("Z", "+00:00"))
        if origin_knowledge_at.tzinfo is None:
            return "method_authority_snapshot_invalid"
        fact_created_at = fact.created_at
        if fact_created_at is None or fact_created_at.tzinfo is None:
            return "method_authority_snapshot_invalid"
        if origin_knowledge_at > fact_created_at:
            return "method_authority_snapshot_invalid"
        replay = reviewed_method_gate(
            session,
            stock_id=stock_id,
            method_key="owner_earnings",
            effective_as_of=origin_effective_as_of,
            knowledge_at=origin_knowledge_at,
        )
    except (TypeError, ValueError):
        return "method_authority_snapshot_invalid"
    if replay.status != "approved" or replay.as_dict() != snapshot:
        return "method_authority_snapshot_invalid"
    return None


def _piotroski_blocked_state(
    fact: MetricFact,
    *,
    reason_code: str,
    decision: MethodGateDecision | None = None,
) -> dict[str, Any]:
    return {
        "id": None,
        "status": "unsupported",
        "reason_code": reason_code,
        "method_key": "roic",
        "metric_key": fact.metric_key,
        "value_numeric": None,
        "unit": None,
        "period": fact.period_type,
        "period_end_date": fact.period_end_date,
        "source_type": fact.source_type,
        "method_gate": decision.as_dict() if decision is not None else None,
        "evidence_route": None,
    }


PIOTROSKI_STRICT_LINEAGE_FIELDS = frozenset(
    {
        "fact_id",
        "user_id",
        "stock_id",
        "metric_key",
        "period_type",
        "period_end_date",
        "value_numeric",
        "source_type",
        "fact_nature",
        "created_at",
    }
)


@dataclass(frozen=True)
class _PiotroskiRebuildDecision:
    status: str
    reason_code: str
    economic_class: str | None
    snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return self.snapshot


def _finite_decimal(value: Any) -> Decimal | None:
    try:
        candidate = value if isinstance(value, Decimal) else Decimal(str(value))
    except (DecimalException, TypeError, ValueError):
        return None
    return candidate if candidate.is_finite() else None


def _piotroski_lineage_item(fact: MetricFact) -> dict[str, Any]:
    metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
    numeric = (
        _finite_decimal(fact.value_numeric)
        if fact.value_numeric is not None
        else None
    )
    return {
        "fact_id": fact.id,
        "user_id": fact.user_id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "period_type": fact.period_type,
        "period_end_date": (
            fact.period_end_date.isoformat()
            if isinstance(fact.period_end_date, date)
            else None
        ),
        "value_numeric": (
            format(numeric, "f") if numeric is not None else None
        ),
        "source_type": fact.source_type,
        "fact_nature": metadata.get("fact_nature"),
        "created_at": (
            fact.created_at.isoformat()
            if isinstance(fact.created_at, datetime)
            else None
        ),
    }


def _piotroski_origin_decision(
    session: Session,
    *,
    fact: MetricFact,
    snapshot: Any,
    expected_status: str,
    cache: dict[tuple[int, date, datetime], MethodGateDecision],
) -> MethodGateDecision | None:
    try:
        if not isinstance(snapshot, dict):
            return None
        effective_raw = snapshot.get("effective_as_of")
        knowledge_raw = snapshot.get("knowledge_at")
        if not isinstance(effective_raw, str) or not isinstance(knowledge_raw, str):
            return None
        origin_effective = date.fromisoformat(effective_raw)
        origin_knowledge = datetime.fromisoformat(
            knowledge_raw.replace("Z", "+00:00")
        )
        if (
            origin_knowledge.tzinfo is None
            or fact.created_at is None
            or fact.created_at.tzinfo is None
            or origin_knowledge > fact.created_at
            or origin_effective != fact.period_end_date
        ):
            return None
        key = (fact.stock_id, origin_effective, origin_knowledge)
        decision = cache.get(key)
        if decision is None:
            decision = reviewed_method_gate(
                session,
                stock_id=fact.stock_id,
                method_key="roic",
                effective_as_of=origin_effective,
                knowledge_at=origin_knowledge,
            )
            cache[key] = decision
    except (TypeError, ValueError):
        return None
    if decision.status != expected_status or decision.as_dict() != snapshot:
        return None
    return decision


def _piotroski_rebuild_matches(
    fact: MetricFact,
    *,
    inputs: list[MetricFact],
    decision: MethodGateDecision | _PiotroskiRebuildDecision,
) -> bool:
    from app.services.calculated_metrics.piotroski_f_score import (
        build_piotroski_f_score_facts,
    )

    decisions = {
        item.period_end_date: decision
        for item in inputs
        if item.period_type == "FY" and item.period_end_date is not None
    }
    if any(
        item.value_numeric is not None
        and _finite_decimal(item.value_numeric) is None
        for item in inputs
    ) or (
        fact.value_numeric is not None
        and _finite_decimal(fact.value_numeric) is None
    ):
        return False
    try:
        rebuilt = build_piotroski_f_score_facts(
            inputs,
            roic_decisions_by_period=decisions,
        )
    except (CanonicalSourceConflictError, DecimalException, TypeError, ValueError):
        return False
    expected = next(
        (
            item
            for item in rebuilt
            if item["metric_key"] == fact.metric_key
            and item["period_type"] == fact.period_type
            and item["period_end_date"] == fact.period_end_date
        ),
        None,
    )
    if expected is None:
        return False
    expected_numeric = expected.get("value_numeric")
    expected_decimal = (
        _finite_decimal(expected_numeric) if expected_numeric is not None else None
    )
    fact_decimal = (
        _finite_decimal(fact.value_numeric)
        if fact.value_numeric is not None
        else None
    )
    numeric_matches = (
        expected_numeric is None and fact.value_numeric is None
    ) or (
        expected_numeric is not None
        and fact.value_numeric is not None
        and expected_decimal is not None
        and fact_decimal is not None
        and expected_decimal == fact_decimal
    )
    return bool(
        numeric_matches
        and expected.get("value_text") == fact.value_text
        and expected.get("unit") == fact.unit
        and expected.get("value_json") == fact.value_json
    )


def _piotroski_period_key(
    fact: MetricFact,
) -> tuple[int | None, int, str | None, date | None]:
    return (
        fact.user_id,
        fact.stock_id,
        fact.period_type,
        fact.period_end_date,
    )


def _parse_piotroski_manifest(
    fact: MetricFact,
) -> tuple[dict[int, dict[str, Any]] | None, str | None]:
    if fact.source_type != "calculated":
        return None, "piotroski_method_authority_source_invalid"
    metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
    if (
        metadata.get("calculation_version") != "piotroski_value_line_v2"
        or metadata.get("manifest_version") != "piotroski-strict-manifest-v1"
    ):
        return None, "piotroski_method_authority_manifest_missing"
    raw_inputs = metadata.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        return None, "piotroski_method_authority_manifest_invalid"
    if len(raw_inputs) > MAX_PIOTROSKI_MANIFEST_INPUTS:
        return None, "piotroski_method_authority_bound_exceeded"
    by_id: dict[int, dict[str, Any]] = {}
    for item in raw_inputs:
        fact_id = item.get("fact_id") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or set(item) != PIOTROSKI_STRICT_LINEAGE_FIELDS
            or not isinstance(fact_id, int)
            or isinstance(fact_id, bool)
            or fact_id <= 0
            or fact_id in by_id
        ):
            return None, "piotroski_method_authority_manifest_invalid"
        by_id[fact_id] = item
    return by_id, None


def _piotroski_declared_sibling_keys(fact: MetricFact) -> set[str] | None:
    metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
    if metadata.get("status") == "unavailable":
        return {PIOTROSKI_TOTAL_KEY}
    components = metadata.get("components")
    if not isinstance(components, list):
        return None
    keys = [
        item.get("metric_key") if isinstance(item, dict) else None
        for item in components
    ]
    if (
        any(
            not isinstance(key, str)
            or not key.startswith(PIOTROSKI_PREFIX)
            or key == PIOTROSKI_TOTAL_KEY
            for key in keys
        )
        or len(keys) != len(set(keys))
    ):
        return None
    return {PIOTROSKI_TOTAL_KEY, *keys}


def guard_piotroski_method_authority(
    session: Session,
    *,
    facts: Iterable[MetricFact],
    effective_as_of: date,
    knowledge_at: datetime | None = None,
) -> tuple[list[MetricFact], list[dict[str, Any]]]:
    """Rebuild strict Piotroski manifests and quarantine unverifiable periods."""

    cutoff = knowledge_at or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError("knowledge_at must be timezone-aware")
    materialized = list(facts)
    piotroski = [
        fact for fact in materialized if fact.metric_key.startswith(PIOTROSKI_PREFIX)
    ]
    non_piotroski = [
        fact for fact in materialized if not fact.metric_key.startswith(PIOTROSKI_PREFIX)
    ]
    if not piotroski:
        return materialized, []

    def block_all(reason_code: str) -> tuple[list[MetricFact], list[dict[str, Any]]]:
        return non_piotroski, [
            _piotroski_blocked_state(fact, reason_code=reason_code)
            for fact in piotroski
        ]

    if len(piotroski) > MAX_PIOTROSKI_REQUEST_FACTS:
        return block_all("piotroski_method_authority_bound_exceeded")

    requested_by_period: dict[
        tuple[int | None, int, str | None, date | None], list[MetricFact]
    ] = {}
    for fact in piotroski:
        requested_by_period.setdefault(_piotroski_period_key(fact), []).append(fact)
    if len(requested_by_period) > MAX_PIOTROSKI_PERIOD_GROUPS:
        return block_all("piotroski_method_authority_bound_exceeded")

    # Parse request manifests and enforce every request-side resource bound before
    # issuing either the sibling expansion or referenced-input query.
    request_errors: dict[int, str] = {}
    request_input_ids: set[int] = set()
    bounded_periods: set[tuple[int | None, int, str | None, date | None]] = set()
    for ordinal, fact in enumerate(piotroski):
        lineage, error = _parse_piotroski_manifest(fact)
        if error is not None:
            request_errors[ordinal] = error
            if error == "piotroski_method_authority_bound_exceeded":
                bounded_periods.add(_piotroski_period_key(fact))
            continue
        assert lineage is not None
        request_input_ids.update(lineage)
    if len(request_input_ids) > MAX_PIOTROSKI_UNIQUE_INPUT_IDS:
        return block_all("piotroski_method_authority_bound_exceeded")

    query_periods = [
        period
        for period in requested_by_period
        if period not in bounded_periods
        and isinstance(period[0], int)
        and isinstance(period[1], int)
        and period[2] == "FY"
        and isinstance(period[3], date)
    ]
    sibling_rows: list[MetricFact] = []
    if query_periods:
        period_clauses = [
            and_(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.period_type == period_type,
                MetricFact.period_end_date == period_end,
            )
            for user_id, stock_id, period_type, period_end in query_periods
        ]
        ranked_siblings = (
            select(
                MetricFact.id.label("fact_id"),
                func.row_number()
                .over(
                    partition_by=(
                        MetricFact.user_id,
                        MetricFact.stock_id,
                        MetricFact.period_type,
                        MetricFact.period_end_date,
                    ),
                    order_by=MetricFact.id,
                )
                .label("sibling_rank"),
            )
            .where(
                MetricFact.is_current.is_(True),
                MetricFact.metric_key.like(f"{PIOTROSKI_PREFIX}%"),
                or_(*period_clauses),
            )
            .subquery()
        )
        sibling_rows = list(
            session.scalars(
                select(MetricFact)
                .join(
                    ranked_siblings,
                    ranked_siblings.c.fact_id == MetricFact.id,
                )
                .where(
                    ranked_siblings.c.sibling_rank
                    <= MAX_PIOTROSKI_CURRENT_SIBLINGS_PER_PERIOD + 1
                )
                .limit(
                    len(query_periods)
                    * (MAX_PIOTROSKI_CURRENT_SIBLINGS_PER_PERIOD + 1)
                )
            ).all()
        )

    siblings_by_period: dict[
        tuple[int | None, int, str | None, date | None], list[MetricFact]
    ] = {}
    for fact in sibling_rows:
        siblings_by_period.setdefault(_piotroski_period_key(fact), []).append(fact)
    for period, siblings in siblings_by_period.items():
        if len(siblings) > MAX_PIOTROSKI_CURRENT_SIBLINGS_PER_PERIOD:
            # The limit+1 row proves the period exceeds the only valid key set.
            # The period is malformed, while other tenant/period groups remain usable.
            request_errors.update(
                {
                    ordinal: "piotroski_method_authority_manifest_invalid"
                    for ordinal, fact in enumerate(piotroski)
                    if _piotroski_period_key(fact) == period
                }
            )

    sibling_object_ids = {id(fact) for fact in sibling_rows}
    validation_facts = [
        *sibling_rows,
        *(fact for fact in piotroski if id(fact) not in sibling_object_ids),
    ]
    parsed_lineage: dict[int, dict[int, dict[str, Any]]] = {}
    preliminary_errors: dict[int, str] = {}
    all_input_ids: set[int] = set()
    for ordinal, fact in enumerate(validation_facts):
        period = _piotroski_period_key(fact)
        if period in bounded_periods:
            preliminary_errors[ordinal] = (
                "piotroski_method_authority_bound_exceeded"
            )
            continue
        lineage, error = _parse_piotroski_manifest(fact)
        if error is not None:
            preliminary_errors[ordinal] = error
            if error == "piotroski_method_authority_bound_exceeded":
                bounded_periods.add(period)
            continue
        assert lineage is not None
        parsed_lineage[ordinal] = lineage
        all_input_ids.update(lineage)

    if bounded_periods:
        all_input_ids = {
            fact_id
            for ordinal, lineage in parsed_lineage.items()
            if _piotroski_period_key(validation_facts[ordinal]) not in bounded_periods
            for fact_id in lineage
        }
    if len(all_input_ids) > MAX_PIOTROSKI_UNIQUE_INPUT_IDS:
        bounded_periods.update(requested_by_period)
        all_input_ids.clear()
        parsed_lineage.clear()
        preliminary_errors = {
            ordinal: "piotroski_method_authority_bound_exceeded"
            for ordinal in range(len(validation_facts))
        }

    referenced = (
        list(
            session.scalars(
                select(MetricFact).where(MetricFact.id.in_(all_input_ids))
            ).all()
        )
        if all_input_ids
        else []
    )
    referenced_by_id = {fact.id: fact for fact in referenced}
    origin_cache: dict[tuple[int, date, datetime], MethodGateDecision] = {}
    current_cache: dict[tuple[int, date, datetime], MethodGateDecision] = {}
    evaluations: list[tuple[MetricFact, str | None, MethodGateDecision | None]] = []
    for ordinal, fact in enumerate(validation_facts):
        if _piotroski_period_key(fact) in bounded_periods:
            evaluations.append(
                (fact, "piotroski_method_authority_bound_exceeded", None)
            )
            continue
        error = preliminary_errors.get(ordinal)
        decision: MethodGateDecision | None = None
        if error is not None:
            evaluations.append((fact, error, None))
            continue
        lineage = parsed_lineage[ordinal]
        inputs = [referenced_by_id.get(fact_id) for fact_id in lineage]
        if (
            fact.user_id is None
            or fact.period_type != "FY"
            or fact.period_end_date is None
            or fact.created_at is None
            or fact.created_at.tzinfo is None
            or any(item is None for item in inputs)
        ):
            evaluations.append(
                (fact, "piotroski_method_authority_manifest_invalid", None)
            )
            continue
        typed_inputs = [item for item in inputs if item is not None]
        if any(
            item.period_type != "FY"
            or item.period_end_date is None
            or item.created_at is None
            or item.created_at.tzinfo is None
            or item.created_at > fact.created_at
            or item.stock_id != fact.stock_id
            or not (
                (item.source_type == "sec" and item.user_id is None)
                or (item.source_type != "sec" and item.user_id == fact.user_id)
            )
            or lineage[item.id] != _piotroski_lineage_item(item)
            for item in typed_inputs
        ):
            evaluations.append(
                (fact, "piotroski_method_authority_manifest_invalid", None)
            )
            continue

        metadata = fact.value_json
        uses_total_capital = any(
            item.metric_key == PIOTROSKI_TOTAL_CAPITAL_KEY
            for item in typed_inputs
        )
        status = metadata.get("status")
        rebuild_decision: MethodGateDecision | _PiotroskiRebuildDecision
        if uses_total_capital and status == "unavailable":
            method_blocks = metadata.get("method_blocks")
            snapshots = {
                str(item.get("method_gate")): item.get("method_gate")
                for item in method_blocks
                if isinstance(item, dict)
            } if isinstance(method_blocks, list) else {}
            if len(snapshots) != 1:
                evaluations.append(
                    (fact, "piotroski_method_authority_manifest_invalid", None)
                )
                continue
            snapshot = next(iter(snapshots.values()))
            decision = _piotroski_origin_decision(
                session,
                fact=fact,
                snapshot=snapshot,
                expected_status="unsupported",
                cache=origin_cache,
            )
            if decision is None:
                evaluations.append(
                    (fact, "piotroski_method_authority_manifest_invalid", None)
                )
                continue
            rebuild_decision = decision
        elif uses_total_capital:
            snapshot = metadata.get("analysis_method")
            if snapshot is None:
                evaluations.append(
                    (fact, "piotroski_method_authority_snapshot_missing", None)
                )
                continue
            decision = _piotroski_origin_decision(
                session,
                fact=fact,
                snapshot=snapshot,
                expected_status="approved",
                cache=origin_cache,
            )
            if decision is None:
                evaluations.append(
                    (fact, "piotroski_method_authority_snapshot_invalid", None)
                )
                continue
            rebuild_decision = decision
        else:
            economic_class = metadata.get("economic_class")
            if economic_class is not None and not isinstance(economic_class, str):
                evaluations.append(
                    (fact, "piotroski_method_authority_manifest_invalid", None)
                )
                continue
            rebuild_decision = _PiotroskiRebuildDecision(
                status="approved",
                reason_code="approved",
                economic_class=economic_class,
                snapshot={},
            )
        if not _piotroski_rebuild_matches(
            fact,
            inputs=typed_inputs,
            decision=rebuild_decision,
        ):
            evaluations.append(
                (fact, "piotroski_method_authority_manifest_invalid", decision)
            )
            continue
        if status == "unavailable":
            reason = metadata.get("reason_code")
            evaluations.append(
                (
                    fact,
                    reason
                    if isinstance(reason, str)
                    else "piotroski_method_authority_manifest_invalid",
                    decision,
                )
            )
            continue
        if uses_total_capital:
            current_key = (fact.stock_id, effective_as_of, cutoff)
            current = current_cache.get(current_key)
            if current is None:
                current = reviewed_method_gate(
                    session,
                    stock_id=fact.stock_id,
                    method_key="roic",
                    effective_as_of=effective_as_of,
                    knowledge_at=cutoff,
                )
                current_cache[current_key] = current
            if current.status != "approved":
                evaluations.append((fact, current.reason_code, current))
                continue
        evaluations.append((fact, None, decision))

    evaluation_by_object = {
        id(fact): (reason, decision)
        for fact, reason, decision in evaluations
    }
    validation_by_period: dict[
        tuple[int | None, int, str | None, date | None], list[int]
    ] = {}
    for index, (fact, _reason, _decision) in enumerate(evaluations):
        validation_by_period.setdefault(_piotroski_period_key(fact), []).append(index)

    blocked_by_period: dict[
        tuple[int | None, int, str | None, date | None],
        tuple[str, MethodGateDecision | None],
    ] = {}
    for period in requested_by_period:
        indexes = validation_by_period.get(period, [])
        siblings = siblings_by_period.get(period, [])
        period_error: str | None = None
        if period in bounded_periods:
            period_error = "piotroski_method_authority_bound_exceeded"
        elif len(siblings) > MAX_PIOTROSKI_CURRENT_SIBLINGS_PER_PERIOD:
            period_error = "piotroski_method_authority_manifest_invalid"
        elif not siblings:
            period_error = "piotroski_method_authority_manifest_invalid"
        else:
            sibling_keys = [fact.metric_key for fact in siblings]
            totals = [
                fact for fact in siblings if fact.metric_key == PIOTROSKI_TOTAL_KEY
            ]
            if len(totals) != 1 or len(sibling_keys) != len(set(sibling_keys)):
                period_error = "piotroski_method_authority_manifest_invalid"
            else:
                declared = _piotroski_declared_sibling_keys(totals[0])
                if declared is None or declared != set(sibling_keys):
                    period_error = "piotroski_method_authority_manifest_invalid"

        if period_error is not None:
            blocked_by_period[period] = (period_error, None)
            continue

        root_index = next(
            (
                index
                for index in indexes
                if evaluations[index][0].metric_key == PIOTROSKI_TOTAL_KEY
                and evaluations[index][1] is not None
            ),
            next(
                (index for index in indexes if evaluations[index][1] is not None),
                None,
            ),
        )
        if root_index is None:
            continue
        root_reason = evaluations[root_index][1]
        root_decision = evaluations[root_index][2]
        assert root_reason is not None
        blocked_by_period[period] = (root_reason, root_decision)

    kept = list(non_piotroski)
    blocked: list[dict[str, Any]] = []
    for ordinal, fact in enumerate(piotroski):
        blocked_entry = blocked_by_period.get(_piotroski_period_key(fact))
        if blocked_entry is None:
            kept.append(fact)
            continue
        own_reason, own_decision = evaluation_by_object.get(id(fact), (None, None))
        request_error = request_errors.get(ordinal)
        reason, decision = blocked_entry
        blocked.append(
            _piotroski_blocked_state(
                fact,
                reason_code=request_error or own_reason or reason,
                decision=own_decision or decision,
            )
        )
    return kept, blocked


def apply_reviewed_method_gates(
    session: Session,
    *,
    stock_id: int,
    facts: Iterable[MetricFact],
    effective_as_of: date,
    knowledge_at: datetime | None = None,
    precomputed_decisions: dict[str, MethodGateDecision] | None = None,
) -> tuple[list[MetricFact], list[dict[str, Any]], dict[str, MethodGateDecision]]:
    """Remove unsupported system outputs while preserving raw and user-authored facts."""

    materialized, piotroski_blocked = guard_piotroski_method_authority(
        session,
        facts=list(facts),
        effective_as_of=effective_as_of,
        knowledge_at=knowledge_at,
    )
    required_methods = {
        method for fact in materialized if (method := system_method_for_fact(fact))
    }
    decisions = {
        method: (
            precomputed_decisions[method]
            if precomputed_decisions is not None and method in precomputed_decisions
            else reviewed_method_gate(
                session,
                stock_id=stock_id,
                method_key=method,
                effective_as_of=effective_as_of,
                knowledge_at=knowledge_at,
            )
        )
        for method in sorted(required_methods)
    }
    kept: list[MetricFact] = []
    blocked: list[dict[str, Any]] = list(piotroski_blocked)
    for fact in materialized:
        method = system_method_for_fact(fact)
        decision = decisions.get(method) if method else None
        origin_error = (
            _owner_earnings_origin_error(session, stock_id=stock_id, fact=fact)
            if method == "owner_earnings"
            and decision is not None
            and decision.status == "approved"
            else None
        )
        if decision is None or (decision.status == "approved" and origin_error is None):
            kept.append(fact)
            continue
        reason_code = origin_error or decision.reason_code
        blocked.append(
            {
                "id": None,
                "status": "unsupported",
                "reason_code": reason_code,
                "method_key": method,
                "metric_key": fact.metric_key,
                "value_numeric": None,
                "unit": None,
                "period": fact.period_type,
                "period_end_date": fact.period_end_date,
                "source_type": fact.source_type,
                "method_gate": decision.as_dict(),
                "evidence_route": None,
            }
        )
    return kept, blocked, decisions


def require_applicable_method_facts(
    session: Session,
    *,
    stock_id: int,
    facts: Iterable[MetricFact],
    effective_as_of: date,
    knowledge_at: datetime | None = None,
) -> list[MetricFact]:
    """Return facts only when every requested system method is authorized."""

    kept, blocked, decisions = apply_reviewed_method_gates(
        session,
        stock_id=stock_id,
        facts=facts,
        effective_as_of=effective_as_of,
        knowledge_at=knowledge_at,
    )
    if not blocked:
        return kept
    state = blocked[0]
    method_key = state.get("method_key")
    decision = decisions.get(method_key) if isinstance(method_key, str) else None
    if decision is not None and decision.status != "approved":
        raise UnsupportedSystemMethodError(decision)
    if str(state.get("metric_key", "")).startswith(PIOTROSKI_PREFIX):
        raise PiotroskiMethodAuthorityError(state)
    raise CanonicalUnavailableError(state)


def current_visible_facts(
    session: Session, *, stock_id: int, user_id: int
) -> list[MetricFact]:
    return list(
        session.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock_id,
                MetricFact.is_current.is_(True),
                visible_metric_fact_predicate(MetricFact, user_id=user_id),
            )
        ).all()
    )


def active_sec_run_unresolved_states(
    session: Session,
    *,
    stock_id: int,
    knowledge_cutoff: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return unresolved amendment states bounded by filing-cycle authority."""

    if knowledge_cutoff is not None and knowledge_cutoff.tzinfo is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    if knowledge_cutoff is not None:
        knowledge_cutoff = knowledge_cutoff.astimezone(timezone.utc)

    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (failed_filing.id)
                   r.id, r.mapping_version_id,
                   r.requested_cutoff, availability.available_at,
                   audit.reason_code,
                   GREATEST(
                     mapping.known_at, mapping.effective_from, mapping.created_at,
                     r.requested_cutoff, r.created_at, availability.available_at,
                     audit.known_at, audit.created_at,
                     failed_source.source_available_at, failed_source.created_at,
                     failed_parse.completed_at, failed_parse.known_at,
                     failed_parse.created_at, failed_filing.accepted_at,
                     failed_filing.known_at, failed_filing.created_at
                   ) AS known_at,
                   failed_filing.report_date, failed_filing.form_type,
                   failed_filing.accession_no
            FROM sec_metric_publication_audits audit
            JOIN sec_metric_publication_runs r ON r.id=audit.publication_run_id
            JOIN sec_metric_mapping_versions mapping ON mapping.id=r.mapping_version_id
            JOIN sec_metric_publication_availabilities availability
              ON availability.publication_run_id=r.id
            JOIN sec_metric_publication_run_sources failed_source
              ON failed_source.publication_run_id=r.id
            JOIN sec_financial_parse_runs failed_parse
              ON failed_parse.id=failed_source.parse_run_id
            JOIN sec_financial_filings failed_filing
              ON failed_filing.id=failed_source.filing_id
            WHERE r.stock_id=:stock_id AND r.status='succeeded'
              AND audit.reason_code='unresolved_amendment_parse_failure'
              AND failed_parse.status='failed' AND failed_filing.is_amendment
              AND mapping.status='approved'
              AND (
                (:knowledge_cutoff IS NULL AND mapping.retired_at IS NULL)
                OR (
                  :knowledge_cutoff IS NOT NULL
                  AND mapping.known_at<=:knowledge_cutoff
                  AND mapping.effective_from<=:knowledge_cutoff
                  AND mapping.created_at<=:knowledge_cutoff
                  AND (mapping.retired_at IS NULL OR mapping.retired_at>:knowledge_cutoff)
                  AND r.requested_cutoff<=:knowledge_cutoff
                  AND r.created_at<=:knowledge_cutoff
                  AND availability.available_at<=:knowledge_cutoff
                  AND audit.known_at<=:knowledge_cutoff
                  AND audit.created_at<=:knowledge_cutoff
                  AND failed_source.source_available_at<=:knowledge_cutoff
                  AND failed_source.created_at<=:knowledge_cutoff
                  AND failed_parse.completed_at<=:knowledge_cutoff
                  AND failed_parse.known_at<=:knowledge_cutoff
                  AND failed_parse.created_at<=:knowledge_cutoff
                  AND failed_filing.accepted_at<=:knowledge_cutoff
                  AND failed_filing.known_at<=:knowledge_cutoff
                  AND failed_filing.created_at<=:knowledge_cutoff
                )
              )
              AND NOT EXISTS (
                SELECT 1
                FROM sec_metric_publication_run_sources later_source
                JOIN sec_metric_publication_runs later_run
                  ON later_run.id=later_source.publication_run_id
                JOIN sec_metric_mapping_versions later_mapping
                  ON later_mapping.id=later_run.mapping_version_id
                JOIN sec_metric_publication_availabilities later_available
                  ON later_available.publication_run_id=later_run.id
                JOIN sec_financial_parse_runs later_parse
                  ON later_parse.id=later_source.parse_run_id
                WHERE later_source.filing_id=failed_source.filing_id
                  AND later_parse.status='succeeded'
                  AND later_run.status='succeeded'
                  AND later_run.requested_cutoff>=r.requested_cutoff
                  AND later_available.available_at>=availability.available_at
                  AND later_mapping.status='approved'
                  AND (
                    (:knowledge_cutoff IS NULL AND later_mapping.retired_at IS NULL)
                    OR (
                      :knowledge_cutoff IS NOT NULL
                      AND later_mapping.known_at<=:knowledge_cutoff
                      AND later_mapping.effective_from<=:knowledge_cutoff
                      AND later_mapping.created_at<=:knowledge_cutoff
                      AND (later_mapping.retired_at IS NULL OR later_mapping.retired_at>:knowledge_cutoff)
                      AND later_run.requested_cutoff<=:knowledge_cutoff
                      AND later_run.created_at<=:knowledge_cutoff
                      AND later_available.available_at<=:knowledge_cutoff
                      AND later_source.source_available_at<=:knowledge_cutoff
                      AND later_source.created_at<=:knowledge_cutoff
                      AND later_parse.completed_at<=:knowledge_cutoff
                      AND later_parse.known_at<=:knowledge_cutoff
                      AND later_parse.created_at<=:knowledge_cutoff
                    )
                  )
              )
            ORDER BY failed_filing.id, availability.available_at DESC, audit.id DESC
            """
        ),
        {"stock_id": stock_id, "knowledge_cutoff": knowledge_cutoff},
    ).mappings().all()
    return [
        {
            "id": None,
            "status": "unresolved",
            "reason_code": row.reason_code,
            "metric_key": None,
            "value_numeric": None,
            "unit": None,
            "period": "FILING_CYCLE",
            "period_end_date": row.report_date,
            "source_type": "sec",
            "mapping_version": row.mapping_version_id,
            "known_at": row.known_at,
            "requested_knowledge_cutoff": row.requested_cutoff,
            "filing": {
                "accession": row.accession_no,
                "form": row.form_type,
            },
            "filing_cycle": {
                "base_form": row.form_type.removesuffix("/A"),
                "report_date": row.report_date,
            },
            "evidence_route": None,
        }
        for row in rows
    ]


def active_sec_run_unresolved_state(
    session: Session, *, stock_id: int, period_end_date: date | None = None
) -> dict[str, Any] | None:
    """Compatibility accessor, optionally bounded to a requested filing cycle."""

    states = active_sec_run_unresolved_states(session, stock_id=stock_id)
    if period_end_date is not None:
        states = [state for state in states if state["period_end_date"] == period_end_date]
    return states[0] if states else None


def guard_sec_run_availability(
    session: Session, *, stock_id: int, facts: Iterable[Any]
) -> list[Any]:
    materialized, states = partition_sec_run_availability(
        session, stock_id=stock_id, facts=facts
    )
    if states:
        raise CanonicalUnavailableError(states[0])
    return materialized


def sec_fact_filing_cycles(
    session: Session, *, facts: Iterable[Any]
) -> dict[int, set[tuple[str, date]]]:
    """Resolve each SEC publication to every filing cycle used by its inputs."""

    publication_ids = sorted(
        {
            source_ref_id
            for fact in facts
            if _fact_source_type(fact) == "sec"
            and isinstance(
                source_ref_id := (
                    fact.get("source_ref_id")
                    if isinstance(fact, dict)
                    else getattr(fact, "source_ref_id", None)
                ),
                int,
            )
        }
    )
    cycles: dict[int, set[tuple[str, date]]] = {
        publication_id: set() for publication_id in publication_ids
    }
    if not publication_ids:
        return cycles
    rows = session.execute(
        text(
            """
            WITH RECURSIVE lineage(root_publication_id, publication_id) AS (
              SELECT p.id, p.id
              FROM sec_metric_publications p
              WHERE p.id=ANY(:publication_ids)
              UNION
              SELECT lineage.root_publication_id, input.source_publication_id
              FROM lineage
              JOIN sec_metric_publication_inputs input
                ON input.publication_id=lineage.publication_id
              WHERE input.source_publication_id IS NOT NULL
            ), evidence_sources AS (
              SELECT publication_id, run_source_id
              FROM sec_metric_publication_inputs
              WHERE run_source_id IS NOT NULL
              UNION ALL
              SELECT publication_id, run_source_id
              FROM sec_metric_publication_unresolved_inputs
            )
            SELECT DISTINCT lineage.root_publication_id,
                   replace(filing.form_type, '/A', '') AS base_form,
                   filing.report_date
            FROM lineage
            JOIN evidence_sources evidence
              ON evidence.publication_id=lineage.publication_id
            JOIN sec_metric_publication_run_sources source
              ON source.id=evidence.run_source_id
            JOIN sec_financial_filings filing ON filing.id=source.filing_id
            WHERE filing.report_date IS NOT NULL
            """
        ),
        {"publication_ids": publication_ids},
    ).mappings().all()
    for row in rows:
        cycles[row.root_publication_id].add((row.base_form, row.report_date))
    return cycles


def partition_sec_run_availability(
    session: Session,
    *,
    stock_id: int,
    facts: Iterable[Any],
    knowledge_cutoff: datetime | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Exclude only SEC facts in filing cycles with unresolved amendments."""

    materialized = list(facts)
    sec_facts = [fact for fact in materialized if _fact_source_type(fact) == "sec"]
    if not sec_facts:
        return materialized, []
    active_states = active_sec_run_unresolved_states(
        session,
        stock_id=stock_id,
        knowledge_cutoff=knowledge_cutoff,
    )
    if not active_states:
        return materialized, []
    state_by_cycle = {
        (
            state["filing_cycle"]["base_form"],
            state["filing_cycle"]["report_date"],
        ): state
        for state in active_states
        if state.get("filing_cycle")
        and state["filing_cycle"].get("report_date") is not None
    }
    fact_cycles = sec_fact_filing_cycles(session, facts=sec_facts)
    blocked_fact_ids: set[int] = set()
    states: list[dict[str, Any]] = []
    for fact in sec_facts:
        source_ref_id = (
            fact.get("source_ref_id")
            if isinstance(fact, dict)
            else getattr(fact, "source_ref_id", None)
        )
        cycles = fact_cycles.get(source_ref_id, set())
        matched = [state_by_cycle[cycle] for cycle in cycles if cycle in state_by_cycle]
        if not cycles:
            # A selected SEC fact without canonical publication/input authority
            # cannot prove that it is outside the unresolved amendment cycle.
            matched = active_states
        if matched:
            blocked_fact_ids.add(id(fact))
            for state in matched:
                if state not in states:
                    states.append(state)
    available = [
        fact
        for fact in materialized
        if id(fact) not in blocked_fact_ids
    ]
    return available, states


_SAFE_OCCURRENCE_KEYS = (
    "report_ordinal",
    "occurrence_ordinal",
    "row_ordinal",
    "column_ordinal",
)


def _safe_locator(locator: Any) -> dict[str, Any]:
    if not isinstance(locator, dict):
        return {"kind": "unavailable"}
    occurrences = locator.get("ordered_input_occurrences")
    if not isinstance(occurrences, list):
        occurrences = [locator]
    safe = []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        item = {key: occurrence.get(key) for key in _SAFE_OCCURRENCE_KEYS}
        safe.append(item)
    return {
        "kind": "derived_statement_occurrences" if len(safe) > 1 else "statement_occurrence",
        "occurrences": safe,
    }


def _concept_local_name(concept: str | None) -> str | None:
    if not concept:
        return None
    return concept.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _canonical_sec_url(*, cik: str, accession: str, primary_document: str) -> str | None:
    if not re.fullmatch(r"[0-9]{10}", cik):
        return None
    if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}", primary_document):
        return None
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik.lstrip('0')}/{accession.replace('-', '')}/{primary_document}"
    )


def resolve_sec_publication_evidence(
    session: Session, *, stock_id: int, publication_id: int
) -> dict[str, Any] | None:
    decision = session.execute(
        text(
            """
            SELECT p.id, p.status, p.reason_code, p.metric_key, p.period_type,
                   p.period_start_date, p.period_end_date, p.period_basis,
                   p.fiscal_year, p.fiscal_quarter_ordinal,
                   fact.value_numeric AS canonical_value_numeric,
                   p.unit, p.currency, p.source_role, p.fact_nature,
                   p.derivation_kind, p.context_id, p.dimensions_policy,
                   p.locator_json, p.known_at, p.metric_fact_id,
                   r.mapping_version_id, r.requested_cutoff
            FROM sec_metric_publications p
            JOIN sec_metric_publication_runs r ON r.id=p.publication_run_id
            JOIN sec_metric_publication_availabilities a ON a.publication_run_id=r.id
            LEFT JOIN metric_facts fact ON fact.id=p.metric_fact_id
            WHERE p.id=:publication_id AND p.stock_id=:stock_id
              AND r.status='succeeded'
            """
        ),
        {"publication_id": publication_id, "stock_id": stock_id},
    ).mappings().first()
    if decision is None:
        return None
    sources = session.execute(
        text(
            """
            SELECT rs.id AS run_source_id, rs.source_ordinal, rs.parser_version,
                   f.accession_no, f.form_type, f.accepted_at, f.known_at,
                   f.primary_document, issuer.cik
            FROM sec_metric_publications p
            JOIN sec_metric_publication_run_sources rs
              ON rs.publication_run_id=p.publication_run_id
            JOIN sec_financial_filings f ON f.id=rs.filing_id
            JOIN sec_issuer_identities issuer ON issuer.id=f.issuer_identity_id
            WHERE p.id=:publication_id
            ORDER BY rs.source_ordinal
            """
        ),
        {"publication_id": publication_id},
    ).mappings().all()
    filings = [
        {
            "source_ordinal": row.source_ordinal,
            "accession": row.accession_no,
            "form": row.form_type,
            "accepted_at": row.accepted_at.isoformat(),
            "known_at": row.known_at.isoformat(),
            "parser_version": row.parser_version,
            "sec_url": _canonical_sec_url(
                cik=row.cik,
                accession=row.accession_no,
                primary_document=row.primary_document,
            ),
        }
        for row in sources
    ]
    source_by_id = {row.run_source_id: row for row in sources}
    raw_inputs = session.execute(
        text(
            """
            SELECT i.input_ordinal, i.input_role, i.arithmetic_sign,
                   i.run_source_id, i.source_publication_id,
                   raw.concept, raw.concept_namespace_uri, raw.context_id,
                   raw.period_instant, raw.period_start, raw.period_end,
                   raw.unit_numerator_json, raw.unit_denominator_json,
                   n.normalization_version,
                   source.metric_key AS source_metric_key,
                   source.period_type AS source_period_type,
                   source.period_end_date AS source_period_end_date,
                   source_fact.value_numeric AS source_value_numeric,
                   source_fact.unit AS source_unit,
                   source_fact.currency AS source_currency
            FROM sec_metric_publication_inputs i
            LEFT JOIN sec_raw_xbrl_facts raw ON raw.id=i.raw_fact_id
            LEFT JOIN sec_raw_numeric_normalizations n ON n.id=i.normalization_id
            LEFT JOIN sec_metric_publications source ON source.id=i.source_publication_id
            LEFT JOIN metric_facts source_fact ON source_fact.id=source.metric_fact_id
            WHERE i.publication_id=:publication_id
            ORDER BY i.input_ordinal
            """
        ),
        {"publication_id": publication_id},
    ).mappings().all()
    if not raw_inputs and decision.status == "unresolved":
        raw_inputs = session.execute(
            text(
                """
                SELECT i.input_ordinal, 'unresolved_evidence' AS input_role,
                       1 AS arithmetic_sign, i.run_source_id,
                       NULL::bigint AS source_publication_id,
                       raw.concept, raw.concept_namespace_uri, raw.context_id,
                       raw.period_instant, raw.period_start, raw.period_end,
                       raw.unit_numerator_json, raw.unit_denominator_json,
                       n.normalization_version,
                       NULL::text AS source_metric_key,
                       NULL::text AS source_period_type,
                       NULL::date AS source_period_end_date,
                       NULL::numeric AS source_value_numeric,
                       NULL::text AS source_unit, NULL::text AS source_currency
                FROM sec_metric_publication_unresolved_inputs i
                JOIN sec_raw_xbrl_facts raw ON raw.id=i.raw_fact_id
                LEFT JOIN sec_raw_numeric_normalizations n ON n.id=i.normalization_id
                WHERE i.publication_id=:publication_id
                ORDER BY i.input_ordinal
                """
            ),
            {"publication_id": publication_id},
        ).mappings().all()
    inputs: list[dict[str, Any]] = []
    for row in raw_inputs:
        source = source_by_id.get(row.run_source_id)
        payload: dict[str, Any] = {
            "ordinal": row.input_ordinal,
            "role": row.input_role,
            "arithmetic_sign": row.arithmetic_sign,
        }
        if row.source_publication_id is not None:
            payload["kind"] = "canonical_operand"
            payload["canonical_operand"] = {
                "metric_key": row.source_metric_key,
                "period_type": row.source_period_type,
                "period_end_date": row.source_period_end_date.isoformat(),
                "value_numeric": row.source_value_numeric,
                "unit": row.source_unit,
                "currency": row.source_currency,
            }
        else:
            payload.update(
                {
                    "kind": "as_filed_fact_metadata",
                    "accession": source.accession_no if source else None,
                    "form": source.form_type if source else None,
                    "parser_version": source.parser_version if source else None,
                    "concept": {
                        "namespace_uri": row.concept_namespace_uri,
                        "local_name": _concept_local_name(row.concept),
                    },
                    "context_id": row.context_id,
                    "period": {
                        "instant": row.period_instant.isoformat() if row.period_instant else None,
                        "start": row.period_start.isoformat() if row.period_start else None,
                        "end": row.period_end.isoformat() if row.period_end else None,
                    },
                    "unit": {
                        "numerator": row.unit_numerator_json,
                        "denominator": row.unit_denominator_json,
                    },
                    "normalization_version": row.normalization_version,
                }
            )
        inputs.append(payload)
    return {
        "publication_id": decision.id,
        "metric_fact_id": decision.metric_fact_id,
        "status": decision.status,
        "reason_code": decision.reason_code,
        "metric_key": decision.metric_key,
        "value_numeric": decision.canonical_value_numeric,
        "mapping_version": decision.mapping_version_id,
        "known_at": decision.known_at.isoformat(),
        "requested_knowledge_cutoff": decision.requested_cutoff.isoformat(),
        "source_role": decision.source_role,
        "fact_nature": decision.fact_nature,
        "derivation_kind": decision.derivation_kind,
        "context_id": decision.context_id,
        "dimensions_policy": decision.dimensions_policy,
        "period": {
            "type": decision.period_type,
            "basis": decision.period_basis,
            "start": decision.period_start_date.isoformat() if decision.period_start_date else None,
            "end": decision.period_end_date.isoformat(),
            "fiscal_year": decision.fiscal_year,
            "fiscal_quarter": decision.fiscal_quarter_ordinal,
        },
        "unit": decision.unit,
        "currency": decision.currency,
        "filings": filings,
        "inputs": inputs,
        "locator": _safe_locator(decision.locator_json),
    }


def current_sec_unresolved_states(session: Session, *, stock_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT ranked.id, ranked.status, ranked.reason_code, ranked.metric_key,
                   ranked.period_type, ranked.period_end_date, ranked.known_at
            FROM (
              SELECT p.*,
                     row_number() OVER (
                       PARTITION BY p.metric_key, p.period_type, p.period_end_date
                       ORDER BY p.known_at DESC, p.id DESC
                     ) AS slot_rank
              FROM sec_metric_publications p
              JOIN sec_metric_publication_runs r ON r.id=p.publication_run_id
              JOIN sec_metric_publication_availabilities a
                ON a.publication_run_id=r.id
              WHERE p.stock_id=:stock_id AND r.status='succeeded'
            ) ranked
            WHERE ranked.slot_rank=1 AND ranked.status IN ('unresolved','rejected')
            ORDER BY ranked.metric_key, ranked.period_end_date
            """
        ),
        {"stock_id": stock_id},
    ).mappings().all()
    states = [
        {
            "id": None,
            "publication_id": row.id,
            "status": row.status,
            "reason_code": row.reason_code,
            "metric_key": row.metric_key,
            "value_numeric": None,
            "unit": None,
            "period": row.period_type,
            "period_end_date": row.period_end_date,
            "source_type": "sec",
            "known_at": row.known_at,
            "evidence_route": f"/api/v1/stocks/{stock_id}/sec-publications/{row.id}/evidence",
        }
        for row in rows
    ]
    states.extend(active_sec_run_unresolved_states(session, stock_id=stock_id))
    return states
