from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.artifacts import (
    PdfDocument,
    ValueLineDocumentReportIdentityRevision,
    ValueLineParseRun,
)
from app.models.facts import MetricFact
from app.services.canonical_financials import database_evaluation_cutoff
from app.services.value_line_report_identity import ReportIdentityUnverifiableError
from app.services.value_line_source_visibility import (
    ValueLineSourceUnavailableError,
    current_value_line_source_available_predicate,
    current_value_line_source_unavailable_predicate,
)


MAX_ACTIVE_REPORT_AUTHORITY_ITEMS = 500
ACTIVE_REPORT_AUTHORITY_BOUND_EXCEEDED = (
    "active_report_authority_bound_exceeded"
)


class ActiveReportAuthorityBoundExceededError(ValueError):
    """The resolver cannot make a complete choice within its resource bound."""

    code = ACTIVE_REPORT_AUTHORITY_BOUND_EXCEEDED

    def __init__(self, *, dimension: str, limit: int):
        self.dimension = dimension
        self.limit = limit
        super().__init__(
            "Active report authority exceeds the supported bounded scope."
        )


class ActualConflictAuthorityAmbiguousError(ValueError):
    """No unique active report or canonical observation can be selected."""

    code = "actual_conflict_authority_ambiguous"

    def __init__(self, *, fact_ids: list[int]):
        self.fact_ids = tuple(sorted(set(fact_ids)))
        super().__init__(
            "Actual conflict authority cannot identify a unique canonical fact."
        )


@dataclass(frozen=True)
class ActiveReportSelection:
    stock_id: int
    document_id: int
    report_identity_revision_id: int
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
    if document_ids is not None:
        document_ids = _bounded_ids(document_ids, dimension="document_ids")
    if stock_ids is not None:
        stock_ids = _bounded_ids(stock_ids, dimension="stock_ids")
    shared_ids = _bounded_ids(
        shared_parsed_user_ids or [],
        dimension="shared_parsed_user_ids",
    )
    if knowledge_cutoff is not None and knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    if document_ids == [] or stock_ids == []:
        return {}

    if knowledge_cutoff is None:
        knowledge_cutoff = database_evaluation_cutoff(session)
    scope = [
        MetricFact.source_type == "parsed",
        MetricFact.source_document_id.is_not(None),
    ]

    if document_ids is not None:
        scope.append(MetricFact.source_document_id.in_(document_ids))

    if stock_ids is not None:
        scope.append(MetricFact.stock_id.in_(stock_ids))

    if current_user_id is not None:
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

    fact_time_authority = [
        MetricFact.value_line_fact_known_at <= knowledge_cutoff,
        identity.known_at <= knowledge_cutoff,
        or_(
            MetricFact.value_line_created_txid.is_(None),
            MetricFact.created_at <= knowledge_cutoff,
        ),
    ]
    temporal_authority = [
        *fact_time_authority,
        or_(
            MetricFact.value_line_parse_run_id.is_(None),
            and_(
                ValueLineParseRun.status == "succeeded",
                ValueLineParseRun.completed_at.is_not(None),
                ValueLineParseRun.completed_at <= knowledge_cutoff,
            ),
            and_(
                ValueLineParseRun.status == "running",
                ValueLineParseRun.created_txid == func.txid_current(),
            ),
        ),
    ]
    source_document_ids = session.scalars(
        select(MetricFact.source_document_id)
        .join(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .outerjoin(
            ValueLineParseRun,
            ValueLineParseRun.id == MetricFact.value_line_parse_run_id,
        )
        .where(*scope, *temporal_authority)
        .distinct()
        .limit(MAX_ACTIVE_REPORT_AUTHORITY_ITEMS + 1)
    ).all()
    if len(source_document_ids) > MAX_ACTIVE_REPORT_AUTHORITY_ITEMS:
        raise ActiveReportAuthorityBoundExceededError(
            dimension="candidates",
            limit=MAX_ACTIVE_REPORT_AUTHORITY_ITEMS,
        )
    if source_document_ids:
        # Hold current document authorization stable until the request
        # transaction ends. A concurrent transfer or source revocation either
        # completes before this lock and is rejected below, or waits.
        session.execute(
            select(PdfDocument.id)
            .where(PdfDocument.id.in_(source_document_ids))
            .with_for_update(of=PdfDocument, read=True)
        ).all()
    source_unavailable = session.execute(
        select(MetricFact.id)
        .join(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .outerjoin(PdfDocument, PdfDocument.id == MetricFact.source_document_id)
        .outerjoin(
            ValueLineParseRun,
            ValueLineParseRun.id == MetricFact.value_line_parse_run_id,
        )
        .where(
            *scope,
            *temporal_authority,
            current_value_line_source_unavailable_predicate(),
        )
        .limit(1)
    ).first()
    if source_unavailable is not None:
        raise ValueLineSourceUnavailableError()

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
        .join(PdfDocument, PdfDocument.id == MetricFact.source_document_id)
        .outerjoin(
            ValueLineParseRun,
            ValueLineParseRun.id == MetricFact.value_line_parse_run_id,
        )
        .where(
            *scope,
            *temporal_authority,
            current_value_line_source_available_predicate(),
        )
        .distinct()
        .order_by(
            MetricFact.stock_id,
            MetricFact.source_document_id,
            identity.id,
        )
        .limit(MAX_ACTIVE_REPORT_AUTHORITY_ITEMS + 1)
    ).all()
    if len(rows) > MAX_ACTIVE_REPORT_AUTHORITY_ITEMS:
        raise ActiveReportAuthorityBoundExceededError(
            dimension="candidates",
            limit=MAX_ACTIVE_REPORT_AUTHORITY_ITEMS,
        )
    candidates_by_stock: dict[int, list[ActiveReportSelection]] = {}
    for row in rows:
        if row.stock_id is None or row.source_document_id is None:
            continue
        candidate = ActiveReportSelection(
            stock_id=row.stock_id,
            document_id=row.source_document_id,
            report_identity_revision_id=row.revision_id,
            report_date=row.report_date,
        )
        candidates_by_stock.setdefault(row.stock_id, []).append(candidate)

    active_by_stock: dict[int, ActiveReportSelection] = {}
    for candidate_stock_id, candidates in candidates_by_stock.items():
        dated_candidates = [
            candidate for candidate in candidates if candidate.report_date is not None
        ]
        if not dated_candidates:
            # One undated report remains useful provenance. Multiple undated
            # reports have no date authority with which to select an active one.
            if len(candidates) == 1:
                active_by_stock[candidate_stock_id] = candidates[0]
            continue
        latest_rank = max(_selection_rank(candidate) for candidate in dated_candidates)
        latest = [
            candidate
            for candidate in dated_candidates
            if _selection_rank(candidate) == latest_rank
        ]
        if len(latest) != 1:
            raise ActualConflictAuthorityAmbiguousError(fact_ids=[])
        active_by_stock[candidate_stock_id] = latest[0]
    return active_by_stock


def _selection_rank(selection: ActiveReportSelection) -> date:
    return selection.report_date or date.min


def _bounded_ids(values: list[int], *, dimension: str) -> list[int]:
    requested = sorted(set(values))
    if len(requested) > MAX_ACTIVE_REPORT_AUTHORITY_ITEMS:
        raise ActiveReportAuthorityBoundExceededError(
            dimension=dimension,
            limit=MAX_ACTIVE_REPORT_AUTHORITY_ITEMS,
        )
    return requested
