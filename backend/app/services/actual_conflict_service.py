from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.services.active_report_resolver import ActiveReportSelection
from app.services.canonical_financials import database_evaluation_cutoff
from app.services.value_line_report_identity import resolve_fact_report_identities


def detect_actual_conflicts(
    session: Session,
    *,
    stock_id: int,
    active_report: ActiveReportSelection | None,
    current_user_id: int | None = None,
    shared_parsed_user_ids: list[int] | None = None,
    knowledge_cutoff: datetime | None = None,
) -> list[dict[str, Any]]:
    if knowledge_cutoff is None:
        knowledge_cutoff = database_evaluation_cutoff(session)
    elif knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    fact_nature_expr = MetricFact.value_json["fact_nature"].as_string()
    stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock_id,
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id.is_not(None),
            fact_nature_expr == "actual",
            MetricFact.created_at <= knowledge_cutoff,
        )
    )
    if current_user_id is not None:
        stmt = stmt.where(
            or_(
                MetricFact.user_id == current_user_id,
                and_(
                    MetricFact.source_type == "parsed",
                    MetricFact.user_id.in_(shared_parsed_user_ids or []),
                ),
            )
        )
    facts = session.scalars(stmt).all()
    identities = resolve_fact_report_identities(
        session,
        facts=facts,
        knowledge_cutoff=knowledge_cutoff,
    )

    grouped: dict[tuple[str, str | None, date | None], list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        identity = identities[fact.id]
        grouped[(fact.metric_key, fact.period_type, fact.period_end_date)].append(
            {
                "source_document_id": fact.source_document_id,
                "source_report_date": (
                    identity.report_date.isoformat() if identity.report_date else None
                ),
                "value_numeric": (
                    float(fact.value_numeric)
                    if fact.value_numeric is not None
                    else None
                ),
                "value_text": fact.value_text,
                "is_active_report": bool(
                    active_report is not None
                    and fact.source_document_id is not None
                    and active_report.document_id == fact.source_document_id
                ),
            }
        )

    conflicts: list[dict[str, Any]] = []
    for (metric_key, period_type, period_end_date), observations in grouped.items():
        distinct_values = {
            (obs["value_numeric"], obs["value_text"])
            for obs in observations
        }
        if len(distinct_values) <= 1:
            continue
        ranked = sorted(
            observations,
            key=lambda obs: (
                obs["source_report_date"] or "",
                obs["source_document_id"] or -1,
            ),
            reverse=True,
        )
        conflicts.append(
            {
                "metric_key": metric_key,
                "period_type": period_type,
                "period_end_date": period_end_date.isoformat() if period_end_date else None,
                "selection_rule": "latest_report_wins_for_same_actual_period",
                "current_value_numeric": ranked[0]["value_numeric"],
                "current_value_text": ranked[0]["value_text"],
                "current_source_document_id": ranked[0]["source_document_id"],
                "current_report_date": ranked[0]["source_report_date"],
                "previous_value_numeric": ranked[1]["value_numeric"],
                "previous_value_text": ranked[1]["value_text"],
                "previous_source_document_id": ranked[1]["source_document_id"],
                "previous_report_date": ranked[1]["source_report_date"],
                "observations": ranked,
            }
        )

    return sorted(
        conflicts,
        key=lambda item: (
            item["period_end_date"] or "",
            item["metric_key"],
        ),
        reverse=True,
    )
