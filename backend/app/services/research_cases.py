"""Transactional application service for user-owned research cases."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact, ScreeningRule
from app.models.institutions import Holding13F, OwnershipChange13F, Filing13F
from app.models.oracles_lens import OraclesLensSignal
from app.models.research import (
    ResearchCase,
    ResearchCaseEvent,
    ResearchCaseOrigin,
    ResearchCaseRevision,
)
from app.models.stocks import PoolMembership, Stock
from app.services.market_data_service import stock_price_evidence_matches
from app.services.metric_fact_locking import acquire_metric_fact_stock_lock
from app.schemas.research import (
    EvidenceInput,
    ResearchOriginInput,
    ResearchRevisionCreate,
)
from app.services.valuation import (
    USER_INTRINSIC_VALUE_KEY,
    publish_user_intrinsic_value,
    quantize_valuation_value,
    redact_published_unavailable_reason,
)
from app.services.privacy_erasure import begin_privacy_erasure_operation
from app.services.screener_service import ScreenerService


ACTIVE_STATES = {"queued", "researching", "monitoring"}
VALID_TRANSITIONS = {
    "queued": {"researching", "closed", "voided"},
    "researching": {"monitoring", "closed", "voided"},
    "monitoring": {"researching", "closed", "voided"},
    "closed": set(),
    "voided": set(),
}


class ResearchCaseError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _owned_case(
    session: Session,
    *,
    user_id: int,
    case_id: int,
    for_update: bool = False,
) -> ResearchCase:
    query = session.query(ResearchCase).filter(
        ResearchCase.id == case_id,
        ResearchCase.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()
    case = query.one_or_none()
    if case is None:
        raise ResearchCaseError("case_not_found", "Research case not found.", status_code=404)
    return case


def _validate_origin(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    origin: ResearchOriginInput,
) -> None:
    ref = origin.source_ref or {}
    if origin.origin_type in {"manual", "ticker_search"}:
        return
    if origin.origin_type == "watchlist":
        query = session.query(PoolMembership).filter(
            PoolMembership.user_id == user_id,
            PoolMembership.stock_id == stock_id,
        )
        if ref.get("pool_id") is not None:
            query = query.filter(PoolMembership.pool_id == int(ref["pool_id"]))
        valid = query.first() is not None
    elif origin.origin_type == "screener":
        rule_id = ref.get("rule_id")
        if rule_id:
            rule = session.get(ScreeningRule, int(rule_id))
            valid = bool(rule and rule.user_id == user_id)
        else:
            rule_json = ref.get("rule_json")
            conditions = rule_json.get("conditions") if isinstance(rule_json, dict) else None
            if (
                not isinstance(conditions, list)
                or len(conditions) > 20
                or len(json.dumps(rule_json, separators=(",", ":"))) > 10_000
            ):
                valid = False
            else:
                matches = ScreenerService(session).execute_screen(
                    rule_json, current_user_id=user_id
                )
                valid = stock_id in {stock.id for stock in matches}
    elif origin.origin_type == "oracle_lens":
        signal_id = ref.get("signal_id")
        if signal_id:
            signal = session.get(OraclesLensSignal, int(signal_id))
        else:
            query = session.query(OraclesLensSignal).filter(
                OraclesLensSignal.stock_id == stock_id
            )
            if ref.get("report_quarter"):
                query = query.filter(
                    OraclesLensSignal.report_quarter == str(ref["report_quarter"])
                )
            signal = query.order_by(
                OraclesLensSignal.report_quarter.desc(),
                OraclesLensSignal.computed_at.desc(),
                OraclesLensSignal.id.desc(),
            ).first()
        valid = bool(signal and signal.stock_id == stock_id)
    elif origin.origin_type == "manager_holding":
        holding_id = ref.get("holding_id")
        holding = session.get(Holding13F, int(holding_id)) if holding_id else None
        valid = bool(holding and holding.stock_id == stock_id)
    else:
        change_id = ref.get("change_id")
        change = session.get(OwnershipChange13F, int(change_id)) if change_id else None
        valid = bool(change and change.stock_id == stock_id)
    if not valid:
        raise ResearchCaseError(
            "origin_unavailable",
            "The origin is unavailable or does not match this user and stock.",
        )


def _append_event(
    session: Session,
    *,
    case_id: int,
    actor_user_id: int,
    event_type: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> ResearchCaseEvent:
    event = ResearchCaseEvent(
        case_id=case_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        payload_json=payload,
        correlation_id=correlation_id,
    )
    session.add(event)
    return event


def _add_origin(
    session: Session,
    *,
    case: ResearchCase,
    user_id: int,
    origin: ResearchOriginInput,
) -> tuple[ResearchCaseOrigin, bool]:
    _validate_origin(
        session, user_id=user_id, stock_id=case.stock_id, origin=origin
    )
    existing = (
        session.query(ResearchCaseOrigin)
        .filter_by(
            case_id=case.id,
            origin_type=origin.origin_type,
            origin_key=origin.origin_key,
            source_version=origin.source_version,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing, False
    row = ResearchCaseOrigin(
        case_id=case.id,
        origin_type=origin.origin_type,
        origin_key=origin.origin_key,
        source_version=origin.source_version,
        source_ref_json=origin.source_ref,
    )
    session.add(row)
    session.flush()
    _append_event(
        session,
        case_id=case.id,
        actor_user_id=user_id,
        event_type="origin_added",
        payload={
            "origin_id": row.id,
            "origin_type": row.origin_type,
            "origin_key": row.origin_key,
            "source_version": row.source_version,
        },
    )
    return row, True


def create_or_open_case(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    origin: ResearchOriginInput,
    commit: bool = True,
) -> tuple[ResearchCase, bool, bool]:
    stock = session.get(Stock, stock_id)
    if stock is None:
        raise ResearchCaseError("stock_not_found", "Stock not found.", status_code=404)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"research-case:{user_id}:{stock_id}"},
    )
    case = (
        session.query(ResearchCase)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCase.stock_id == stock_id,
            ResearchCase.state.in_(ACTIVE_STATES),
        )
        .one_or_none()
    )
    created = case is None
    if case is None:
        case = ResearchCase(user_id=user_id, stock_id=stock_id, state="queued")
        session.add(case)
        session.flush()
        _append_event(
            session,
            case_id=case.id,
            actor_user_id=user_id,
            event_type="case_created",
            payload={"stock_id": stock_id, "state": "queued"},
        )
    _, origin_created = _add_origin(
        session, case=case, user_id=user_id, origin=origin
    )
    if commit:
        session.commit()
        session.refresh(case)
    else:
        session.flush()
    return case, created, origin_created


def add_case_origin(
    session: Session,
    *,
    user_id: int,
    case_id: int,
    origin: ResearchOriginInput,
) -> tuple[ResearchCaseOrigin, bool]:
    case = _owned_case(session, user_id=user_id, case_id=case_id, for_update=True)
    row, created = _add_origin(session, case=case, user_id=user_id, origin=origin)
    session.commit()
    return row, created


def _validate_evidence(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    evidence: list[EvidenceInput],
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for item in evidence:
        valid = evidence_is_available(
            session,
            user_id=user_id,
            stock_id=stock_id,
            source_type=item.source_type,
            source_id=item.source_id,
        )
        if not valid:
            raise ResearchCaseError(
                "evidence_unavailable",
                "Evidence is unavailable or does not match this user and stock.",
            )
        snapshot = item.model_dump(mode="json", exclude_none=True)
        if item.source_type == "external_url" and item.url:
            snapshot["destination_domain"] = item.url.split("/", 3)[2]
        snapshots.append(snapshot)
    return snapshots


def evidence_is_available(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    source_type: str,
    source_id: int | None,
) -> bool:
    if source_type in {"user_note", "external_url"}:
        return True
    if source_type == "pdf_document":
        source = session.get(PdfDocument, source_id)
        return bool(source and source.user_id == user_id and source.stock_id == stock_id)
    if source_type == "metric_fact":
        source = session.get(MetricFact, source_id)
        return bool(source and source.user_id == user_id and source.stock_id == stock_id)
    if source_type == "filing_13f":
        return session.get(Filing13F, source_id) is not None
    if source_type == "holding_13f":
        source = session.get(Holding13F, source_id)
        return bool(source and source.stock_id == stock_id)
    if source_type == "ownership_change":
        source = session.get(OwnershipChange13F, source_id)
        return bool(source and source.stock_id == stock_id)
    if source_type == "oracles_lens_signal":
        source = session.get(OraclesLensSignal, source_id)
        return bool(source and source.stock_id == stock_id)
    if source_type == "stock_price":
        return stock_price_evidence_matches(
            session, price_id=source_id, stock_id=stock_id
        )
    return False


def _qualified(revision: ResearchCaseRevision) -> bool:
    valuation_ready = (
        revision.valuation_low is not None
        and revision.valuation_base is not None
        and revision.valuation_high is not None
    ) or bool(revision.valuation_unavailable_reason)
    review_ready = revision.decision == "pass" or revision.next_review_on is not None
    return bool(
        revision.decision
        and (revision.thesis or revision.decision_reason)
        and revision.risks_json
        and revision.evidence_json
        and valuation_ready
        and review_ready
    )


def save_revision(
    session: Session,
    *,
    user_id: int,
    case_id: int,
    payload: ResearchRevisionCreate,
    commit: bool = True,
    valuation_origin: str = "manual",
) -> tuple[ResearchCase, ResearchCaseRevision]:
    case_stock_id = session.scalar(
        select(ResearchCase.stock_id).where(
            ResearchCase.id == case_id,
            ResearchCase.user_id == user_id,
        )
    )
    if case_stock_id is not None:
        acquire_metric_fact_stock_lock(session, stock_id=case_stock_id)
    case = _owned_case(session, user_id=user_id, case_id=case_id, for_update=True)
    if payload.correlation_id:
        prior_event = (
            session.query(ResearchCaseEvent)
            .filter_by(
                case_id=case.id,
                event_type="revision_saved",
                correlation_id=payload.correlation_id,
            )
            .one_or_none()
        )
        if prior_event and prior_event.payload_json:
            revision = session.get(
                ResearchCaseRevision, prior_event.payload_json.get("revision_id")
            )
            if revision is not None:
                return case, revision
    if case.state in {"closed", "voided"}:
        raise ResearchCaseError(
            "terminal_case", "Closed and voided research cycles cannot be edited.", status_code=409
        )
    if case.head_revision_number != payload.expected_head_revision_number:
        raise ResearchCaseError(
            "stale_case_revision",
            "The case changed after this draft was opened.",
            status_code=409,
        )
    if payload.target_state != case.state and payload.target_state not in VALID_TRANSITIONS[case.state]:
        raise ResearchCaseError(
            "invalid_case_transition",
            f"Cannot transition from {case.state} to {payload.target_state}.",
            status_code=409,
        )
    stock = session.get(Stock, case.stock_id)
    if stock is None:
        raise ResearchCaseError("stock_not_found", "Stock not found.", status_code=404)
    evidence = _validate_evidence(
        session,
        user_id=user_id,
        stock_id=case.stock_id,
        evidence=payload.evidence,
    )
    revision_number = case.head_revision_number + 1
    valuation_low = (
        quantize_valuation_value(payload.valuation_low)
        if payload.valuation_low is not None
        else None
    )
    valuation_base = (
        quantize_valuation_value(payload.valuation_base)
        if payload.valuation_base is not None
        else None
    )
    valuation_high = (
        quantize_valuation_value(payload.valuation_high)
        if payload.valuation_high is not None
        else None
    )
    revision = ResearchCaseRevision(
        case_id=case.id,
        revision_number=revision_number,
        thesis=payload.thesis,
        variant_view=payload.variant_view,
        decision_reason=payload.decision_reason,
        assumptions_json=payload.assumptions,
        risks_json=payload.risks,
        evidence_json=evidence,
        case_state=payload.target_state,
        valuation_low=valuation_low,
        valuation_base=valuation_base,
        valuation_high=valuation_high,
        valuation_currency=payload.valuation_currency,
        valuation_unavailable_reason=payload.valuation_unavailable_reason,
        valuation_as_of_date=payload.valuation_as_of_date,
        decision=payload.decision,
        next_review_on=payload.next_review_on,
        snapshot_stock_id=stock.id,
        stock_ticker=stock.ticker,
        stock_company_name=stock.company_name,
        stock_exchange=stock.exchange,
        stock_listing_exchange=stock.listing_exchange,
        created_by_user_id=user_id,
    )
    revision.is_qualified_decision = _qualified(revision)
    if payload.decision_action != "draft" and not revision.is_qualified_decision:
        raise ResearchCaseError(
            "unqualified_decision",
            "A recorded decision/review requires thesis or reason, valuation, risk, evidence, and review date where applicable.",
        )
    if payload.decision_action == "decision" and (
        case.state == payload.target_state and case.decision == payload.decision
    ):
        raise ResearchCaseError(
            "decision_action_requires_transition",
            "Use an explicit review action when reaffirming an unchanged monitoring decision.",
        )
    if payload.decision_action == "review" and not (
        case.state == "monitoring"
        and payload.target_state == "monitoring"
        and case.decision == payload.decision
    ):
        raise ResearchCaseError(
            "review_action_requires_existing_decision",
            "A review action must reaffirm the current monitoring decision.",
        )
    session.add(revision)
    session.flush()
    if payload.valuation_base is not None or payload.valuation_unavailable_reason:
        assert payload.valuation_as_of_date is not None
        publish_user_intrinsic_value(
            session,
            user_id=user_id,
            stock_id=case.stock_id,
            value_numeric=valuation_base,
            as_of_date=payload.valuation_as_of_date,
            unavailable_reason=payload.valuation_unavailable_reason,
            source_ref_id=revision.id,
            valuation_origin=valuation_origin,
        )

    prior_state = case.state
    prior_decision = case.decision
    case.state = payload.target_state
    case.decision = payload.decision
    case.next_review_on = payload.next_review_on
    case.void_reason = payload.void_reason
    case.head_revision_number = revision_number
    case.version += 1
    if payload.target_state in {"closed", "voided"}:
        case.closed_at = datetime.now(timezone.utc)
    _append_event(
        session,
        case_id=case.id,
        actor_user_id=user_id,
        event_type="revision_saved",
        correlation_id=payload.correlation_id,
        payload={
            "revision_id": revision.id,
            "revision_number": revision_number,
            "qualified_decision": _qualified(revision),
        },
    )
    if prior_state != case.state or prior_decision != case.decision:
        _append_event(
            session,
            case_id=case.id,
            actor_user_id=user_id,
            event_type="case_transitioned",
            payload={
                "from_state": prior_state,
                "to_state": case.state,
                "from_decision": prior_decision,
                "to_decision": case.decision,
                "revision_id": revision.id,
            },
        )
    if payload.decision_action in {"decision", "review"}:
        _append_event(
            session,
            case_id=case.id,
            actor_user_id=user_id,
            event_type="qualified_decision_recorded",
            correlation_id=payload.correlation_id,
            payload={
                "revision_id": revision.id,
                "revision_number": revision_number,
                "decision_action": payload.decision_action,
                "decision": revision.decision,
                "case_state": revision.case_state,
            },
        )
    if commit:
        session.commit()
        session.refresh(case)
        session.refresh(revision)
    else:
        session.flush()
    return case, revision


def research_decision_metrics(
    session: Session,
    *,
    user_id: int,
    week_start: date,
) -> dict[str, Any]:
    week_end = week_start + timedelta(days=7)
    count = (
        session.query(ResearchCaseEvent)
        .join(ResearchCase, ResearchCase.id == ResearchCaseEvent.case_id)
        .filter(
            ResearchCase.user_id == user_id,
            ResearchCaseEvent.actor_user_id == user_id,
            ResearchCaseEvent.event_type == "qualified_decision_recorded",
            ResearchCaseEvent.created_at >= datetime.combine(
                week_start, datetime.min.time(), tzinfo=timezone.utc
            ),
            ResearchCaseEvent.created_at < datetime.combine(
                week_end, datetime.min.time(), tzinfo=timezone.utc
            ),
        )
        .count()
    )
    return {
        "metric": "qualified_research_decisions_per_active_user_per_week",
        "week_start": week_start.isoformat(),
        "week_end_exclusive": week_end.isoformat(),
        "qualified_research_decisions": count,
        "active_user_count": 1,
        "value_per_active_user": float(count),
    }


def save_product_valuation_revision(
    session: Session,
    *,
    user_id: int,
    stock_id: int,
    value_numeric: Decimal,
    valuation_low: Decimal | None,
    valuation_high: Decimal | None,
    as_of_date: date,
    source: str,
    pool_id: int | None,
    assumptions: list[dict[str, Any]],
    valuation_currency: str,
) -> tuple[ResearchCase, ResearchCaseRevision, MetricFact]:
    """Atomically save a UI valuation as revision, projection, and fact."""
    if valuation_currency != "USD":
        raise ResearchCaseError(
            "valuation_currency_not_supported",
            "Published valuation revisions currently support USD only.",
            status_code=409,
        )
    if source == "watchlist":
        origin = ResearchOriginInput(
            origin_type="watchlist",
            origin_key=f"watchlist:{pool_id or 'membership'}:{stock_id}",
            source_version="research-valuation-v1",
            source_ref={"pool_id": pool_id} if pool_id is not None else None,
        )
    else:
        origin = ResearchOriginInput(
            origin_type="manual",
            origin_key=f"{source}-valuation:{stock_id}",
            source_version="research-valuation-v1",
            source_ref={"source": source},
        )

    try:
        acquire_metric_fact_stock_lock(session, stock_id=stock_id)
        case, _, _ = create_or_open_case(
            session,
            user_id=user_id,
            stock_id=stock_id,
            origin=origin,
            commit=False,
        )
        head = None
        if case.head_revision_number:
            head = (
                session.query(ResearchCaseRevision)
                .filter_by(
                    case_id=case.id,
                    revision_number=case.head_revision_number,
                )
                .one()
            )

        preserved_assumptions = list(head.assumptions_json or []) if head else []
        if assumptions:
            incoming_sources = {
                item.get("source")
                for item in assumptions
                if isinstance(item, dict) and item.get("source")
            }
            preserved_assumptions = [
                item
                for item in preserved_assumptions
                if not (
                    isinstance(item, dict)
                    and item.get("source") in incoming_sources
                )
            ]
            preserved_assumptions.extend(assumptions)

        evidence = [
            EvidenceInput.model_validate(item)
            for item in (head.evidence_json or [] if head else [])
        ]
        low = valuation_low if valuation_low is not None else value_numeric
        high = valuation_high if valuation_high is not None else value_numeric
        reopens_for_review = case.state == "monitoring"
        revision_payload = ResearchRevisionCreate(
            expected_head_revision_number=case.head_revision_number,
            target_state="researching" if reopens_for_review else case.state,
            thesis=head.thesis if head else None,
            variant_view=head.variant_view if head else None,
            decision_reason=(
                None if reopens_for_review else head.decision_reason if head else None
            ),
            assumptions=preserved_assumptions,
            risks=list(head.risks_json or []) if head else [],
            evidence=evidence,
            valuation_low=low,
            valuation_base=value_numeric,
            valuation_high=high,
            valuation_currency=valuation_currency,
            valuation_as_of_date=as_of_date,
            decision=None,
            next_review_on=None,
        )
        case, revision = save_revision(
            session,
            user_id=user_id,
            case_id=case.id,
            payload=revision_payload,
            commit=False,
            valuation_origin=source,
        )
        fact = (
            session.query(MetricFact)
            .filter_by(
                user_id=user_id,
                stock_id=stock_id,
                metric_key=USER_INTRINSIC_VALUE_KEY,
                source_ref_id=revision.id,
            )
            .one()
        )
        session.commit()
        session.refresh(case)
        session.refresh(revision)
        session.refresh(fact)
        return case, revision, fact
    except Exception:
        session.rollback()
        raise


def redact_revision(
    session: Session,
    *,
    user_id: int,
    case_id: int,
    revision_number: int,
    reason: str,
) -> ResearchCaseRevision:
    case = _owned_case(session, user_id=user_id, case_id=case_id, for_update=True)
    revision = (
        session.query(ResearchCaseRevision)
        .filter_by(case_id=case.id, revision_number=revision_number)
        .with_for_update()
        .one_or_none()
    )
    if revision is None:
        raise ResearchCaseError("revision_not_found", "Revision not found.", status_code=404)
    if revision.is_redacted:
        return revision
    authored_content = {
        "thesis": revision.thesis,
        "variant_view": revision.variant_view,
        "decision_reason": revision.decision_reason,
        "assumptions": revision.assumptions_json,
        "risks": revision.risks_json,
        "evidence": revision.evidence_json,
        "valuation_unavailable_reason": revision.valuation_unavailable_reason,
    }
    revision.redaction_content_hash = hashlib.sha256(
        json.dumps(authored_content, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    revision.thesis = "[redacted]"
    revision.variant_view = "[redacted]" if revision.variant_view else None
    revision.decision_reason = "[redacted]" if revision.decision_reason else None
    revision.assumptions_json = []
    revision.risks_json = []
    revision.evidence_json = []
    revision.valuation_unavailable_reason = (
        "[redacted]" if revision.valuation_unavailable_reason else None
    )
    revision.is_redacted = True
    revision.redaction_reason = reason
    revision.redacted_by_user_id = user_id
    revision.redacted_at = datetime.now(timezone.utc)
    begin_privacy_erasure_operation(
        session,
        user_id=user_id,
        operation_kind="revision_redaction",
    )
    redact_published_unavailable_reason(
        session,
        user_id=user_id,
        stock_id=case.stock_id,
        revision_id=revision.id,
    )
    _append_event(
        session,
        case_id=case.id,
        actor_user_id=user_id,
        event_type="revision_redacted",
        payload={
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "content_hash": revision.redaction_content_hash,
            "reason": reason,
        },
    )
    session.commit()
    session.refresh(revision)
    return revision


def serialize_case(case: ResearchCase, stock: Stock) -> dict[str, Any]:
    return {
        "id": case.id,
        "stock_id": case.stock_id,
        "ticker": stock.ticker,
        "company_name": stock.company_name,
        "state": case.state,
        "decision": case.decision,
        "next_review_on": case.next_review_on.isoformat() if case.next_review_on else None,
        "void_reason": case.void_reason,
        "head_revision_number": case.head_revision_number,
        "version": case.version,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
    }


def serialize_origin(origin: ResearchCaseOrigin) -> dict[str, Any]:
    return {
        "id": origin.id,
        "case_id": origin.case_id,
        "origin_type": origin.origin_type,
        "origin_key": origin.origin_key,
        "source_version": origin.source_version,
        "source_ref": origin.source_ref_json,
        "created_at": origin.created_at.isoformat(),
    }


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def serialize_revision(revision: ResearchCaseRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "case_id": revision.case_id,
        "revision_number": revision.revision_number,
        "thesis": revision.thesis,
        "variant_view": revision.variant_view,
        "decision_reason": revision.decision_reason,
        "assumptions": revision.assumptions_json,
        "risks": revision.risks_json,
        "evidence": revision.evidence_json,
        "valuation_low": _decimal(revision.valuation_low),
        "valuation_base": _decimal(revision.valuation_base),
        "valuation_high": _decimal(revision.valuation_high),
        "valuation_currency": revision.valuation_currency,
        "valuation_unavailable_reason": revision.valuation_unavailable_reason,
        "valuation_as_of_date": (
            revision.valuation_as_of_date.isoformat()
            if revision.valuation_as_of_date
            else None
        ),
        "case_state": revision.case_state,
        "decision": revision.decision,
        "next_review_on": revision.next_review_on.isoformat() if revision.next_review_on else None,
        "recorded_identity": {
            "stock_id": revision.snapshot_stock_id,
            "ticker": revision.stock_ticker,
            "company_name": revision.stock_company_name,
            "exchange": revision.stock_exchange,
            "listing_exchange": revision.stock_listing_exchange,
        },
        "is_qualified_decision": revision.is_qualified_decision,
        "is_redacted": revision.is_redacted,
        "redaction_content_hash": revision.redaction_content_hash,
        "redaction_reason": revision.redaction_reason,
        "redacted_at": revision.redacted_at.isoformat() if revision.redacted_at else None,
        "created_at": revision.created_at.isoformat(),
    }
