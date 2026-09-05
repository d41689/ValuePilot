from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.services.canonical_financials import database_evaluation_cutoff
from app.services.value_line_report_identity import resolve_fact_report_identities


@dataclass(frozen=True)
class ActiveReportSelection:
    stock_id: int
    document_id: int
    report_date: Optional[date]


def resolve_active_reports(
    session: Session,
    *,
    document_ids: Optional[list[int]] = None,
    stock_ids: Optional[list[int]] = None,
    current_user_id: Optional[int] = None,
    shared_parsed_user_ids: Optional[list[int]] = None,
    knowledge_cutoff: datetime | None = None,
) -> dict[int, ActiveReportSelection]:
    if knowledge_cutoff is None:
        knowledge_cutoff = database_evaluation_cutoff(session)
    elif knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    stmt = (
        select(MetricFact)
        .where(
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id.is_not(None),
            MetricFact.created_at <= knowledge_cutoff,
        )
    )

    if document_ids is not None:
        if not document_ids:
            return {}
        stmt = stmt.where(MetricFact.source_document_id.in_(document_ids))

    if stock_ids is not None:
        if not stock_ids:
            return {}
        stmt = stmt.where(MetricFact.stock_id.in_(stock_ids))

    if current_user_id is not None:
        shared_ids = shared_parsed_user_ids or []
        stmt = stmt.where(
            or_(
                MetricFact.user_id == current_user_id,
                and_(
                    MetricFact.source_type == "parsed",
                    MetricFact.user_id.in_(shared_ids),
                ),
            )
        )

    facts = session.scalars(stmt).all()
    identities = resolve_fact_report_identities(
        session,
        facts=facts,
        knowledge_cutoff=knowledge_cutoff,
    )
    active_by_stock: dict[int, ActiveReportSelection] = {}
    for fact in facts:
        if fact.stock_id is None or fact.source_document_id is None:
            continue
        identity = identities[fact.id]
        candidate = ActiveReportSelection(
            stock_id=fact.stock_id,
            document_id=fact.source_document_id,
            report_date=identity.report_date,
        )
        current = active_by_stock.get(fact.stock_id)
        if current is None or _selection_rank(candidate) > _selection_rank(current):
            active_by_stock[fact.stock_id] = candidate
    return active_by_stock


def _selection_rank(selection: ActiveReportSelection) -> tuple[date, int]:
    return (selection.report_date or date.min, selection.document_id)
