"""User-authorized, stock-centric read model for a research case."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.artifacts import PdfDocument
from app.models.coverage import ResearchCoverageRequirement
from app.models.facts import MetricFact
from app.models.oracles_lens import OraclesLensSignal
from app.models.research import ResearchCase, ResearchCaseOrigin, ResearchCaseRevision
from app.models.stocks import Stock
from app.services.market_data_service import read_canonical_eod_price
from app.services.metric_fact_visibility import visible_metric_fact_predicate
from app.services.analysis_method_gate import (
    analysis_kind_for_metric,
    evaluate_analysis_method,
    metric_fact_matches_method,
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


def _sec_provenance(fact: MetricFact) -> dict[str, Any] | None:
    """Project approved public SEC lineage without querying raw SEC tables."""
    if fact.source_type != "sec" or not isinstance(fact.value_json, dict):
        return None
    payload = fact.value_json
    dimensions = payload.get("dimensions")
    locator = payload.get("locator")
    return {
        "source_accession": payload.get("source_accession"),
        "filing_form": payload.get("filing_form"),
        "filing_id": payload.get("filing_id"),
        "artifact_id": payload.get("artifact_id"),
        "raw_fact_id": payload.get("raw_fact_id"),
        "parse_run_id": payload.get("parse_run_id"),
        "parser_version": payload.get("parser_version"),
        "mapping_version": payload.get("mapping_version"),
        "mapping_known_at": payload.get("mapping_known_at"),
        "knowledge_at": payload.get("knowledge_at"),
        "period_start": payload.get("period_start"),
        "period_end": payload.get("period_end"),
        "context_id": payload.get("context_id"),
        "dimensions_policy": payload.get("dimensions_policy"),
        "dimensions": dimensions if isinstance(dimensions, dict) else {},
        "unit_measure": payload.get("unit_measure"),
        "decimals": payload.get("decimals"),
        "scale": payload.get("scale"),
        "value_basis": payload.get("value_basis"),
        "locator": locator if isinstance(locator, dict) else None,
    }


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
            PdfDocument.lifecycle_state == "active",
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
    method_results = {
        kind: evaluate_analysis_method(
            session,
            stock_id=stock.id,
            analysis_kind=kind,
            cutoff=datetime.now(timezone.utc),
        )
        for kind in ("owner_earnings", "roic", "per_share_trend", "valuation")
    }
    facts = [
        fact
        for fact in facts
        if (kind := analysis_kind_for_metric(fact.metric_key)) is None
        or metric_fact_matches_method(fact, method_results[kind])
    ]
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
    price = read_canonical_eod_price(session, stock=stock, as_of=as_of)
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
                    else None
                ),
                "sec_provenance": _sec_provenance(fact),
            }
            for fact in facts
        ],
        "analysis_methods": {
            kind: {
                "state": result.state,
                "reason": result.reason_code,
                "policy_version": result.policy_version,
                "classification": result.classification,
                "classification_id": result.classification_id,
                "method_id": result.method_id,
                "required_evidence": list(result.required_evidence),
                "output_authorized": result.output_authorized,
            }
            for kind, result in method_results.items()
        },
        "piotroski_f_score": _piotroski_series(facts),
        "actual_conflicts": actual_conflicts,
        "missing_items": [
            serialize_requirement(row, stock)
            for row in coverage_rows
            if row.state != "ready"
        ],
        "price": {
            "price_id": price.price_id,
            "close": price.close,
            "price_date": price.price_date.isoformat() if price.price_date else None,
            "currency": price.currency,
            "source": price.source,
            "freshness_state": price.freshness_state,
            "reason_code": price.reason_code,
            "expected_session_date": (
                price.expected_session_date.isoformat() if price.expected_session_date else None
            ),
            "freshness_policy_version": price.freshness_policy_version,
        },
        "valuation": {
            "user_intrinsic_value": valuation.user_intrinsic_value,
            "user_intrinsic_value_status": valuation.user_intrinsic_value_status,
            "user_intrinsic_value_as_of": (
                valuation.user_intrinsic_value_as_of.isoformat()
                if valuation.user_intrinsic_value_as_of
                else None
            ),
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
