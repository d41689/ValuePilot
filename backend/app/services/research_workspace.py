"""User-authorized, stock-centric read model for a research case."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifacts import PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.facts import MetricFact
from app.models.oracles_lens import OraclesLensSignal
from app.models.research import ResearchCase, ResearchCaseOrigin, ResearchCaseRevision
from app.models.stocks import Stock
from app.services.market_data_service import (
    read_current_eod_price,
    serialize_canonical_eod_price,
)
from app.services.research_cases import (
    ResearchCaseError,
    serialize_case,
    evidence_is_available,
    serialize_origin,
    serialize_revision,
)
from app.services.research_coverage import serialize_requirement
from app.services.thirteenf_user_api import build_user_stock_holders
from app.services.valuation import read_valuation_context
from app.services.active_report_resolver import resolve_active_reports
from app.services.actual_conflict_service import detect_actual_conflicts
from app.services.canonical_financials import (
    apply_reviewed_method_gates,
    current_sec_unresolved_states,
    partition_sec_run_availability,
    reviewed_method_gate,
    visible_metric_fact_predicate,
)


def _piotroski_series(facts: list[MetricFact]) -> list[dict[str, Any]]:
    rows = []
    for fact in facts:
        if fact.metric_key != "score.piotroski.total":
            continue
        metadata = fact.value_json if isinstance(fact.value_json, dict) else {}
        fiscal_year = metadata.get("fiscal_year")
        if not isinstance(fiscal_year, int):
            fiscal_year = fact.period_end_date.year if fact.period_end_date else None
        rows.append(
            {
                "fiscal_year": fiscal_year,
                "period_end_date": (
                    fact.period_end_date.isoformat() if fact.period_end_date else None
                ),
                "score": (
                    float(fact.value_numeric)
                    if fact.value_numeric is not None
                    else None
                ),
                "status": metadata.get("status"),
                "variant": metadata.get("variant"),
            }
        )
    return sorted(
        rows,
        key=lambda item: (item["fiscal_year"] or -1, item["period_end_date"] or ""),
    )


def build_research_workspace(
    session: Session,
    *,
    user_id: int,
    case_id: int,
    as_of: date,
) -> dict[str, Any]:
    case = (
        session.query(ResearchCase)
        .filter(ResearchCase.id == case_id, ResearchCase.user_id == user_id)
        .one_or_none()
    )
    if case is None:
        raise ResearchCaseError("case_not_found", "Research case not found.", status_code=404)
    if as_of != date.today():
        raise ResearchCaseError(
            "historical_as_of_not_supported",
            "Only the current research workspace is supported; point-in-time reconstruction is unavailable.",
        )
    stock = session.get(Stock, case.stock_id)
    if stock is None:
        raise ResearchCaseError("stock_not_found", "Stock not found.", status_code=404)

    origins = (
        session.query(ResearchCaseOrigin)
        .filter_by(case_id=case.id)
        .order_by(ResearchCaseOrigin.created_at, ResearchCaseOrigin.id)
        .all()
    )
    revisions = (
        session.query(ResearchCaseRevision)
        .filter_by(case_id=case.id)
        .order_by(ResearchCaseRevision.revision_number.desc())
        .limit(100)
        .all()
    )
    documents = (
        session.query(PdfDocument)
        .filter(
            PdfDocument.user_id == user_id,
            PdfDocument.stock_id == stock.id,
        )
        .order_by(
            PdfDocument.report_date.desc().nullslast(),
            PdfDocument.upload_time.desc(),
            PdfDocument.id.desc(),
        )
        .limit(20)
        .all()
    )
    facts = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            visible_metric_fact_predicate(MetricFact, user_id=user_id),
        )
        .order_by(
            MetricFact.metric_key,
            MetricFact.period_end_date.desc().nullslast(),
            MetricFact.created_at.desc(),
            MetricFact.id.desc(),
        )
        .limit(250)
    ).all()
    facts, _ = partition_sec_run_availability(
        session, stock_id=stock.id, facts=facts
    )
    facts, unsupported_method_states, _ = apply_reviewed_method_gates(
        session,
        stock_id=stock.id,
        facts=facts,
        effective_as_of=as_of,
    )
    coverage_rows = (
        session.query(ResearchCoverageRequirement)
        .filter(
            ResearchCoverageRequirement.user_id == user_id,
            ResearchCoverageRequirement.stock_id == stock.id,
            ResearchCoverageRequirement.is_current.is_(True),
        )
        .order_by(ResearchCoverageRequirement.priority_rank, ResearchCoverageRequirement.kind)
        .all()
    )
    current_price = read_current_eod_price(session, stock=stock)
    valuation = read_valuation_context(session, user_id=user_id, stock_id=stock.id)
    active_report = resolve_active_reports(
        session,
        stock_ids=[stock.id],
        current_user_id=user_id,
    ).get(stock.id)
    actual_conflicts = detect_actual_conflicts(
        session,
        stock_id=stock.id,
        active_report=active_report,
        current_user_id=user_id,
    )
    signal = (
        session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .order_by(
            OraclesLensSignal.report_quarter.desc(),
            OraclesLensSignal.computed_at.desc(),
            OraclesLensSignal.id.desc(),
        )
        .first()
    )
    try:
        holders = build_user_stock_holders(session, stock.id, limit=20)
    except ValueError:
        holders = {
            "status": "unavailable",
            "stock_id": stock.id,
            "reason": {"code": "NO_ACTIVE_HOLDERS", "message": "No active 13F holders are available."},
            "top_holders": [],
            "recent_changes": [],
            "data_caveats": [],
        }

    serialized_revisions = []
    for revision in revisions:
        serialized = serialize_revision(revision)
        serialized["evidence"] = [
            {
                **evidence,
                "access_status": (
                    "available"
                    if evidence_is_available(
                        session,
                        user_id=user_id,
                        stock_id=stock.id,
                        source_type=str(evidence.get("source_type") or ""),
                        source_id=evidence.get("source_id"),
                    )
                    else "source_unavailable"
                ),
            }
            for evidence in serialized["evidence"]
        ]

        serialized_revisions.append(serialized)

    return {
        "as_of": as_of.isoformat(),
        "case": serialize_case(case, stock),
        "current_identity": {
            "stock_id": stock.id,
            "ticker": stock.ticker,
            "company_name": stock.company_name,
            "exchange": stock.exchange,
            "listing_exchange": stock.listing_exchange,
            "market_country": stock.market_country,
            "is_active": stock.is_active,
        },
        "origins": [serialize_origin(origin) for origin in origins],
        "revisions": serialized_revisions,
        "documents": [
            {
                "id": document.id,
                "file_name": document.file_name,
                "source": document.source,
                "report_date": document.report_date.isoformat() if document.report_date else None,
                "parse_status": document.parse_status,
                "identity_needs_review": document.identity_needs_review,
                "uploaded_at": document.upload_time.isoformat(),
            }
            for document in documents
        ],
        "fundamentals": [
            {
                "id": fact.id,
                "metric_key": fact.metric_key,
                "value_numeric": fact.value_numeric,
                "value_text": fact.value_text,
                "unit": fact.unit,
                "currency": fact.currency,
                "period_type": fact.period_type,
                "period_end_date": fact.period_end_date.isoformat() if fact.period_end_date else None,
                "source_type": fact.source_type,
                "source_document_id": fact.source_document_id,
                "source_ref_id": fact.source_ref_id,
                "source_report_date": next(
                    (
                        document.report_date.isoformat()
                        if document.report_date
                        else None
                        for document in documents
                        if document.id == fact.source_document_id
                    ),
                    None,
                ),
                "original_evidence_route": (
                    f"/documents/{fact.source_document_id}/review"
                    if fact.source_document_id is not None
                    else (
                        f"/api/v1/stocks/{stock.id}/sec-publications/{fact.source_ref_id}/evidence"
                        if fact.source_type == "sec" and fact.source_ref_id is not None
                        else None
                    )
                ),
            }
            for fact in facts
        ] + unsupported_method_states + current_sec_unresolved_states(session, stock_id=stock.id),
        "system_method_gates": {
            method_key: reviewed_method_gate(
                session,
                stock_id=stock.id,
                method_key=method_key,
                effective_as_of=as_of,
            ).as_dict()
            for method_key in ("owner_earnings", "roic", "per_share_trend", "system_valuation")
        },
        "piotroski_f_score": _piotroski_series(facts),
        "actual_conflicts": actual_conflicts,
        "missing_items": [
            serialize_requirement(row, stock)
            for row in coverage_rows
            if row.state != "ready"
        ],
        "current_price": serialize_canonical_eod_price(current_price),
        "valuation": {
            "user_intrinsic_value": valuation.user_intrinsic_value,
            "user_intrinsic_value_status": valuation.user_intrinsic_value_status,
            "user_intrinsic_value_as_of": (
                valuation.user_intrinsic_value_as_of.isoformat()
                if valuation.user_intrinsic_value_as_of
                else None
            ),
            "user_intrinsic_value_currency": valuation.user_intrinsic_value_currency,
            "display_state": (
                "under_review"
                if case.state == "researching"
                and valuation.user_intrinsic_value is not None
                else valuation.user_intrinsic_value_status
            ),
            "system_reference_value": valuation.system_reference_value,
            "system_reference_type": valuation.system_reference_type,
            "system_reference_as_of": (
                valuation.system_reference_as_of.isoformat()
                if valuation.system_reference_as_of
                else None
            ),
            "system_reference_currency": valuation.system_reference_currency,
        },
        "coverage": [serialize_requirement(row, stock) for row in coverage_rows],
        "oracles_lens": (
            {
                "signal_id": signal.id,
                "report_quarter": signal.report_quarter,
                "score_version": signal.score_version,
                "consensus_score": (
                    str(signal.signal_weighted_consensus_score)
                    if signal.signal_weighted_consensus_score is not None
                    else None
                ),
                "distinctive_score": (
                    str(signal.distinctive_consensus_score)
                    if signal.distinctive_consensus_score is not None
                    else None
                ),
                "confidence": signal.score_confidence,
                "caution_flag_codes": signal.caution_flag_codes or [],
                "computed_at": signal.computed_at.isoformat(),
            }
            if signal
            else None
        ),
        "holders_13f": holders,
    }
