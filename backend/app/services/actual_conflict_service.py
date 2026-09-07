from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.artifacts import (
    PdfDocument,
    ValueLineDocumentReportIdentityRevision,
    ValueLineParseRun,
)
from app.models.facts import MetricFact
from app.services.active_report_resolver import (
    ActiveReportSelection,
    ActualConflictAuthorityAmbiguousError,
)
from app.services.metric_fact_currentness import (
    CurrentnessScope,
    bounded_currentness_candidate_scope,
    currentness_state_subquery,
    require_currentness_authority,
)
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.value_line_report_identity import ReportIdentityUnverifiableError
from app.services.value_line_source_visibility import (
    ValueLineSourceUnavailableError,
    current_value_line_source_available_predicate,
    current_value_line_source_unavailable_predicate,
)


MAX_ACTUAL_CONFLICT_OBSERVATIONS = 500
ACTUAL_CONFLICT_AUTHORITY_BOUND_EXCEEDED = (
    "actual_conflict_authority_bound_exceeded"
)


class ActualConflictAuthorityBoundExceededError(ValueError):
    """A complete conflict result cannot be produced within its resource bound."""

    code = ACTUAL_CONFLICT_AUTHORITY_BOUND_EXCEEDED

    def __init__(self, *, dimension: str, limit: int):
        self.dimension = dimension
        self.limit = limit
        super().__init__(
            "Actual conflict authority exceeds the supported bounded scope."
        )


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
        evaluation_snapshot = database_evaluation_snapshot(session)
        knowledge_cutoff = evaluation_snapshot.cutoff
    elif knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    shared_ids = sorted(set(shared_parsed_user_ids or []))
    if len(shared_ids) > MAX_ACTUAL_CONFLICT_OBSERVATIONS:
        raise ActualConflictAuthorityBoundExceededError(
            dimension="shared_parsed_user_ids",
            limit=MAX_ACTUAL_CONFLICT_OBSERVATIONS,
        )
    # Validate the conservative backfill boundary before using any historical
    # canonical projection. The returned ID query is used by simpler consumers;
    # conflicts need both true and false states and therefore join the complete
    # latest-state projection below.
    evaluation_snapshot = database_evaluation_snapshot(session, knowledge_cutoff)
    visibility_snapshot = evaluation_snapshot.visibility_snapshot
    currentness_scope = CurrentnessScope.one_stock(
        stock_id,
        source_types=("parsed",),
        user_ids=(
            tuple(dict.fromkeys((current_user_id, *shared_ids)))
            if current_user_id is not None
            else ()
        ),
    )
    currentness_scope = bounded_currentness_candidate_scope(
        session,
        scope=currentness_scope,
        evaluation_snapshot=evaluation_snapshot,
    )
    require_currentness_authority(session, knowledge_cutoff=knowledge_cutoff)
    if not currentness_scope.fact_ids:
        return []
    currentness = currentness_state_subquery(
        knowledge_cutoff=knowledge_cutoff,
        knowledge_txid_snapshot=visibility_snapshot,
        scope=currentness_scope,
    )
    fact_nature_expr = MetricFact.value_json["fact_nature"].as_string()
    scope = [
        MetricFact.id.in_(currentness_scope.fact_ids),
        MetricFact.stock_id == stock_id,
        MetricFact.source_type == "parsed",
        MetricFact.source_document_id.is_not(None),
        fact_nature_expr == "actual",
        MetricFact.created_at <= knowledge_cutoff,
    ]
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
    identity_mismatch = or_(
        MetricFact.value_line_report_identity_revision_id.is_(None),
        MetricFact.value_line_fact_known_at.is_(None),
        identity.id.is_(None),
        identity.known_at > knowledge_cutoff,
        identity.document_id != MetricFact.source_document_id,
        identity.user_id != MetricFact.user_id,
        and_(identity.stock_id.is_not(None), identity.stock_id != MetricFact.stock_id),
        and_(
            MetricFact.value_line_created_txid.is_(None),
            MetricFact.value_line_fact_known_at > knowledge_cutoff,
        ),
        and_(
            MetricFact.value_line_created_txid.is_not(None),
            or_(
                MetricFact.created_at.is_(None),
                MetricFact.value_line_fact_known_at != MetricFact.created_at,
                MetricFact.created_at > knowledge_cutoff,
            ),
        ),
    )
    unverifiable = session.execute(
        select(MetricFact.id, MetricFact.source_document_id)
        .outerjoin(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .where(*scope, identity_mismatch)
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
        .limit(MAX_ACTUAL_CONFLICT_OBSERVATIONS + 1)
    ).all()
    if len(source_document_ids) > MAX_ACTUAL_CONFLICT_OBSERVATIONS:
        raise ActualConflictAuthorityBoundExceededError(
            dimension="observations",
            limit=MAX_ACTUAL_CONFLICT_OBSERVATIONS,
        )
    if source_document_ids:
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

    observations = session.execute(
        select(
            MetricFact.id,
            MetricFact.metric_key,
            MetricFact.period_type,
            MetricFact.period_end_date,
            MetricFact.source_document_id,
            MetricFact.value_numeric,
            MetricFact.value_text,
            currentness.c.is_current,
            identity.id.label("report_identity_revision_id"),
            identity.report_date.label("source_report_date"),
        )
        .join(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .join(currentness, currentness.c.fact_id == MetricFact.id)
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
        .order_by(MetricFact.id.asc())
        .limit(MAX_ACTUAL_CONFLICT_OBSERVATIONS + 1)
    ).all()
    if len(observations) > MAX_ACTUAL_CONFLICT_OBSERVATIONS:
        raise ActualConflictAuthorityBoundExceededError(
            dimension="observations",
            limit=MAX_ACTUAL_CONFLICT_OBSERVATIONS,
        )

    canonical_groups: dict[
        tuple[int, int, str, str | None, date | None], list[Any]
    ] = defaultdict(list)
    for observation in observations:
        canonical_groups[
            (
                observation.source_document_id,
                observation.report_identity_revision_id,
                observation.metric_key,
                observation.period_type,
                observation.period_end_date,
            )
        ].append(observation)

    canonical_observations = [
        _canonical_observation(rows)
        for rows in canonical_groups.values()
    ]
    grouped: dict[tuple[str, str | None, date | None], list[dict[str, Any]]] = defaultdict(list)
    for observation in canonical_observations:
        grouped[
            (
                observation.metric_key,
                observation.period_type,
                observation.period_end_date,
            )
        ].append(
            {
                "fact_id": observation.id,
                "source_document_id": observation.source_document_id,
                "source_report_identity_revision_id": (
                    observation.report_identity_revision_id
                ),
                "source_report_date": (
                    observation.source_report_date.isoformat()
                    if observation.source_report_date
                    else None
                ),
                "value_numeric": (
                    float(observation.value_numeric)
                    if observation.value_numeric is not None
                    else None
                ),
                "value_text": observation.value_text,
                "is_active_report": bool(
                    active_report is not None
                    and observation.source_document_id is not None
                    and active_report.document_id == observation.source_document_id
                    and active_report.report_identity_revision_id
                    == observation.report_identity_revision_id
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
            key=lambda obs: obs["source_report_date"] or "",
            reverse=True,
        )
        ranked_dates = list(
            dict.fromkeys(obs["source_report_date"] or "" for obs in ranked)
        )
        # Both projected values must be selected by report date alone. A
        # document/revision/row identifier is provenance, never a tie-breaker.
        for decisive_date in ranked_dates[:2]:
            tied = [
                obs
                for obs in ranked
                if (obs["source_report_date"] or "") == decisive_date
            ]
            if len(
                {
                    (
                        obs["source_document_id"],
                        obs["source_report_identity_revision_id"],
                    )
                    for obs in tied
                }
            ) > 1:
                raise ActualConflictAuthorityAmbiguousError(
                    fact_ids=[obs["fact_id"] for obs in tied]
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
                "current_report_identity_revision_id": ranked[0][
                    "source_report_identity_revision_id"
                ],
                "current_report_date": ranked[0]["source_report_date"],
                "previous_value_numeric": ranked[1]["value_numeric"],
                "previous_value_text": ranked[1]["value_text"],
                "previous_source_document_id": ranked[1]["source_document_id"],
                "previous_report_identity_revision_id": ranked[1][
                    "source_report_identity_revision_id"
                ],
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


def _canonical_observation(rows: list[Any]) -> Any:
    """Select one fact only from explicit canonical/supersession authority.

    The live ``is_current`` projection is the only canonical winner recorded by
    the metric-facts contract. Parse-run completion time and row identifiers do
    not establish a supersession edge, so duplicate retained rows without one
    unique current fact are not provably ordered and fail closed.
    """

    if len(rows) == 1:
        return rows[0]
    current = [row for row in rows if row.is_current is True]
    if len(current) == 1:
        return current[0]
    if len(current) > 1:
        raise ActualConflictAuthorityAmbiguousError(
            fact_ids=[row.id for row in rows]
        )
    raise ActualConflictAuthorityAmbiguousError(
        fact_ids=[row.id for row in rows]
    )
