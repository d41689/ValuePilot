from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.artifacts import ValueLineDocumentReportIdentityRevision
from app.models.facts import MetricFact
from app.services.canonical_financials import database_evaluation_cutoff
from app.services.value_line_report_identity import ReportIdentityUnverifiableError


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
    scope = [
        MetricFact.source_type == "parsed",
        MetricFact.source_document_id.is_not(None),
    ]

    if document_ids is not None:
        if not document_ids:
            return {}
        scope.append(MetricFact.source_document_id.in_(document_ids))

    if stock_ids is not None:
        if not stock_ids:
            return {}
        scope.append(MetricFact.stock_id.in_(stock_ids))

    if current_user_id is not None:
        shared_ids = shared_parsed_user_ids or []
        scope.append(
            or_(
                MetricFact.user_id == current_user_id,
                and_(
                    MetricFact.source_type == "parsed",
                    MetricFact.user_id.in_(shared_ids),
                ),
            )
        )

    identity = ValueLineDocumentReportIdentityRevision
    mismatch = or_(
        MetricFact.value_line_report_identity_revision_id.is_(None),
        MetricFact.value_line_fact_known_at.is_(None),
        and_(
            MetricFact.value_line_created_txid.is_(None),
            or_(
                MetricFact.value_line_fact_known_at > knowledge_cutoff,
                identity.known_at > knowledge_cutoff,
            ),
        ),
        and_(
            MetricFact.value_line_created_txid.is_not(None),
            MetricFact.value_line_fact_known_at != MetricFact.created_at,
        ),
        identity.id.is_(None),
        identity.document_id != MetricFact.source_document_id,
        identity.user_id != MetricFact.user_id,
        and_(identity.stock_id.is_not(None), identity.stock_id != MetricFact.stock_id),
    )
    unverifiable = session.execute(
        select(MetricFact.id, MetricFact.source_document_id)
        .outerjoin(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .where(*scope, mismatch)
        .limit(1)
    ).first()
    if unverifiable is not None:
        raise ReportIdentityUnverifiableError(
            fact_ids=[unverifiable.id],
            document_ids=[unverifiable.source_document_id],
        )

    rows = session.execute(
        select(
            MetricFact.stock_id,
            MetricFact.source_document_id,
            identity.id.label("revision_id"),
            identity.report_date,
        )
        .join(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .where(
            *scope,
            MetricFact.value_line_fact_known_at <= knowledge_cutoff,
            identity.known_at <= knowledge_cutoff,
            or_(
                MetricFact.value_line_created_txid.is_(None),
                MetricFact.created_at <= knowledge_cutoff,
            ),
        )
        .distinct()
    ).all()
    active_by_stock: dict[int, ActiveReportSelection] = {}
    for row in rows:
        if row.stock_id is None or row.source_document_id is None:
            continue
        candidate = ActiveReportSelection(
            stock_id=row.stock_id,
            document_id=row.source_document_id,
            report_date=row.report_date,
        )
        current = active_by_stock.get(row.stock_id)
        if current is None or _selection_rank(candidate) > _selection_rank(current):
            active_by_stock[row.stock_id] = candidate
    return active_by_stock


def _selection_rank(selection: ActiveReportSelection) -> tuple[date, int]:
    return (selection.report_date or date.min, selection.document_id)
