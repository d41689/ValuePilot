"""Point-in-time Value Line document identity authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.artifacts import ValueLineDocumentReportIdentityRevision
from app.models.facts import MetricFact


REPORT_IDENTITY_UNVERIFIABLE = "historical_report_identity_unverifiable"


class ReportIdentityUnverifiableError(ValueError):
    code = REPORT_IDENTITY_UNVERIFIABLE

    def __init__(self, *, fact_ids: Iterable[int], document_ids: Iterable[int]):
        self.fact_ids = tuple(sorted(set(fact_ids)))
        self.document_ids = tuple(sorted(set(document_ids)))
        super().__init__(
            "Value Line report identity cannot be reconstructed at the requested "
            "knowledge cutoff."
        )


@dataclass(frozen=True)
class ResolvedValueLineReportIdentity:
    revision_id: int
    document_id: int
    user_id: int
    stock_id: int | None
    report_date: date | None
    known_at: datetime


def _require_aware(knowledge_cutoff: datetime) -> None:
    if knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")


def resolve_fact_report_identities(
    session: Session,
    *,
    facts: Iterable[MetricFact],
    knowledge_cutoff: datetime,
) -> dict[int, ResolvedValueLineReportIdentity]:
    """Resolve each parsed fact's exact DB-owned report-identity binding.

    A later document edit or reparse must never relabel a retained fact.
    Pre-authority legacy facts have no binding and are explicitly unverifiable
    instead of silently projecting mutable document metadata.
    """

    _require_aware(knowledge_cutoff)
    parsed_facts = [
        fact
        for fact in facts
        if fact.source_type == "parsed" and fact.source_document_id is not None
    ]
    if not parsed_facts:
        return {}
    revision_ids = sorted(
        {
            int(fact.value_line_report_identity_revision_id)
            for fact in parsed_facts
            if fact.value_line_report_identity_revision_id is not None
        }
    )
    revision_rows = session.execute(
        select(
            ValueLineDocumentReportIdentityRevision.id,
            ValueLineDocumentReportIdentityRevision.document_id,
            ValueLineDocumentReportIdentityRevision.user_id,
            ValueLineDocumentReportIdentityRevision.stock_id,
            ValueLineDocumentReportIdentityRevision.report_date,
            ValueLineDocumentReportIdentityRevision.known_at,
        )
        .where(
            ValueLineDocumentReportIdentityRevision.id.in_(revision_ids),
            ValueLineDocumentReportIdentityRevision.known_at <= knowledge_cutoff,
        )
    ).all()
    by_id = {revision.id: revision for revision in revision_rows}

    resolved: dict[int, ResolvedValueLineReportIdentity] = {}
    invalid_fact_ids: list[int] = []
    invalid_document_ids: list[int] = []
    for fact in parsed_facts:
        fact_id = int(fact.id) if fact.id is not None else -1
        revision = by_id.get(fact.value_line_report_identity_revision_id)
        fact_time_unverifiable = (
            fact.value_line_fact_known_at is None
            or (
                fact.value_line_created_txid is None
                and fact.value_line_fact_known_at > knowledge_cutoff
            )
            or (
                fact.value_line_created_txid is not None
                and (
                    fact.created_at is None
                    or fact.value_line_fact_known_at != fact.created_at
                    or fact.created_at > knowledge_cutoff
                )
            )
        )
        if (
            fact.id is None
            or revision is None
            or fact_time_unverifiable
            or revision.document_id != fact.source_document_id
            or revision.user_id != fact.user_id
            or (
                revision.stock_id is not None
                and revision.stock_id != fact.stock_id
            )
        ):
            invalid_fact_ids.append(fact_id)
            invalid_document_ids.append(int(fact.source_document_id))
            continue
        resolved[fact.id] = ResolvedValueLineReportIdentity(
            revision_id=revision.id,
            document_id=revision.document_id,
            user_id=revision.user_id,
            stock_id=revision.stock_id,
            report_date=revision.report_date,
            known_at=revision.known_at,
        )
    if invalid_fact_ids:
        raise ReportIdentityUnverifiableError(
            fact_ids=invalid_fact_ids,
            document_ids=invalid_document_ids,
        )
    return resolved


def resolve_document_report_identities(
    session: Session,
    *,
    knowledge_cutoff: datetime,
    user_id: int | None = None,
    stock_id: int | None = None,
    document_ids: Iterable[int] | None = None,
) -> dict[int, ResolvedValueLineReportIdentity]:
    """Return the latest DB-versioned document identity known at one cutoff."""

    _require_aware(knowledge_cutoff)
    ranked = select(
        ValueLineDocumentReportIdentityRevision.id.label("revision_id"),
        func.row_number()
        .over(
            partition_by=ValueLineDocumentReportIdentityRevision.document_id,
            order_by=(
                ValueLineDocumentReportIdentityRevision.known_at.desc(),
                ValueLineDocumentReportIdentityRevision.id.desc(),
            ),
        )
        .label("authority_rank"),
    ).where(ValueLineDocumentReportIdentityRevision.known_at <= knowledge_cutoff)
    if document_ids is not None:
        requested = sorted(set(document_ids))
        if not requested:
            return {}
        ranked = ranked.where(
            ValueLineDocumentReportIdentityRevision.document_id.in_(requested)
        )
    ranked_subquery = ranked.subquery()
    stmt = (
        select(ValueLineDocumentReportIdentityRevision)
        .join(
            ranked_subquery,
            ranked_subquery.c.revision_id
            == ValueLineDocumentReportIdentityRevision.id,
        )
        .where(ranked_subquery.c.authority_rank == 1)
    )
    if user_id is not None:
        stmt = stmt.where(ValueLineDocumentReportIdentityRevision.user_id == user_id)
    if stock_id is not None:
        stmt = stmt.where(ValueLineDocumentReportIdentityRevision.stock_id == stock_id)
    return {
        revision.document_id: ResolvedValueLineReportIdentity(
            revision_id=revision.id,
            document_id=revision.document_id,
            user_id=revision.user_id,
            stock_id=revision.stock_id,
            report_date=revision.report_date,
            known_at=revision.known_at,
        )
        for revision in session.scalars(stmt).all()
    }
