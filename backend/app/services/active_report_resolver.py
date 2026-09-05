from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact


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
    if knowledge_cutoff is not None and knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    stmt = (
        select(
            MetricFact.stock_id,
            PdfDocument.id,
            PdfDocument.report_date,
        )
        .join(PdfDocument, PdfDocument.id == MetricFact.source_document_id)
        .where(
            MetricFact.source_type == "parsed",
            MetricFact.source_document_id.is_not(None),
        )
        .distinct()
    )

    if knowledge_cutoff is not None:
        stmt = stmt.where(
            MetricFact.created_at <= knowledge_cutoff,
            MetricFact.updated_at <= knowledge_cutoff,
        )

    if document_ids is not None:
        if not document_ids:
            return {}
        stmt = stmt.where(PdfDocument.id.in_(document_ids))

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

    rows = session.execute(stmt).all()
    active_by_stock: dict[int, ActiveReportSelection] = {}
    for stock_id, document_id, report_date in rows:
        if stock_id is None or document_id is None:
            continue
        candidate = ActiveReportSelection(
            stock_id=stock_id,
            document_id=document_id,
            report_date=report_date,
        )
        current = active_by_stock.get(stock_id)
        if current is None or _selection_rank(candidate) > _selection_rank(current):
            active_by_stock[stock_id] = candidate
    return active_by_stock


def _selection_rank(selection: ActiveReportSelection) -> tuple[date, int]:
    return (selection.report_date or date.min, selection.document_id)
