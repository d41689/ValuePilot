"""Point-in-time authority for the ``metric_facts.is_current`` projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from sqlalchemy import and_, false, func, or_, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact, MetricFactCurrentnessRevision
from app.services.evaluation_snapshot import (
    EvaluationSnapshot,
    database_evaluation_snapshot,
    transaction_visible_in_snapshot_predicate,
)


HISTORICAL_CURRENTNESS_UNVERIFIABLE = "historical_currentness_unverifiable"
CURRENTNESS_SCOPE_REQUIRED = "metric_fact_currentness_scope_required"
CURRENTNESS_SCOPE_BOUND_EXCEEDED = "metric_fact_currentness_scope_bound_exceeded"
MAX_CURRENTNESS_FACT_IDS = 1_000
MAX_CURRENTNESS_STOCK_IDS = 1_000
MAX_CURRENTNESS_DOCUMENT_IDS = 1_000
MAX_CURRENTNESS_METRIC_KEYS = 64
MAX_CURRENTNESS_USER_IDS = 64
MAX_CURRENTNESS_SOURCE_TYPES = 64
MAX_CURRENTNESS_PERIOD_TYPES = 64
MAX_CURRENTNESS_PERIOD_DATES = 1_000


class CurrentnessScopeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CurrentnessScope:
    """Immutable candidate slot constraints applied before timeline ranking."""

    fact_ids: tuple[int, ...] = ()
    stock_ids: tuple[int, ...] = ()
    metric_keys: tuple[str, ...] = ()
    user_ids: tuple[int | None, ...] = ()
    source_types: tuple[str, ...] = ()
    source_document_ids: tuple[int, ...] = ()
    period_types: tuple[str | None, ...] = ()
    period_end_dates: tuple[date | None, ...] = ()
    as_of_dates: tuple[date | None, ...] = ()

    @classmethod
    def one_stock(
        cls,
        stock_id: int,
        *,
        metric_keys: Sequence[str] = (),
        user_ids: Sequence[int | None] = (),
        source_types: Sequence[str] = (),
    ) -> "CurrentnessScope":
        return cls(
            stock_ids=(stock_id,),
            metric_keys=tuple(metric_keys),
            user_ids=tuple(user_ids),
            source_types=tuple(source_types),
        )


def _normalized_scope(scope: CurrentnessScope) -> CurrentnessScope:
    return CurrentnessScope(
        fact_ids=tuple(dict.fromkeys(scope.fact_ids)),
        stock_ids=tuple(dict.fromkeys(scope.stock_ids)),
        metric_keys=tuple(dict.fromkeys(scope.metric_keys)),
        user_ids=tuple(dict.fromkeys(scope.user_ids)),
        source_types=tuple(dict.fromkeys(scope.source_types)),
        source_document_ids=tuple(dict.fromkeys(scope.source_document_ids)),
        period_types=tuple(dict.fromkeys(scope.period_types)),
        period_end_dates=tuple(dict.fromkeys(scope.period_end_dates)),
        as_of_dates=tuple(dict.fromkeys(scope.as_of_dates)),
    )


def _validate_scope(scope: CurrentnessScope | None) -> CurrentnessScope:
    if scope is None or not any(
        (
            scope.fact_ids,
            scope.stock_ids,
            scope.metric_keys,
            scope.source_document_ids,
        )
    ):
        raise CurrentnessScopeError(
            CURRENTNESS_SCOPE_REQUIRED,
            "Metric-fact currentness requires an explicit bounded candidate scope.",
        )
    scope = _normalized_scope(scope)
    bounds = (
        (scope.fact_ids, MAX_CURRENTNESS_FACT_IDS, "fact_ids"),
        (scope.stock_ids, MAX_CURRENTNESS_STOCK_IDS, "stock_ids"),
        (scope.source_document_ids, MAX_CURRENTNESS_DOCUMENT_IDS, "document_ids"),
        (scope.metric_keys, MAX_CURRENTNESS_METRIC_KEYS, "metric_keys"),
        (scope.user_ids, MAX_CURRENTNESS_USER_IDS, "user_ids"),
        (scope.source_types, MAX_CURRENTNESS_SOURCE_TYPES, "source_types"),
        (scope.period_types, MAX_CURRENTNESS_PERIOD_TYPES, "period_types"),
        (
            scope.period_end_dates,
            MAX_CURRENTNESS_PERIOD_DATES,
            "period_end_dates",
        ),
        (scope.as_of_dates, MAX_CURRENTNESS_PERIOD_DATES, "as_of_dates"),
    )
    for values, limit, dimension in bounds:
        if len(values) > limit:
            raise CurrentnessScopeError(
                CURRENTNESS_SCOPE_BOUND_EXCEEDED,
                f"Metric-fact currentness {dimension} exceeds {limit} candidates.",
            )
    return scope


def _nullable_in(column, values):
    concrete = [value for value in values if value is not None]
    clauses = []
    if concrete:
        clauses.append(column.in_(concrete))
    if None in values:
        clauses.append(column.is_(None))
    return or_(*clauses)


def _scope_predicates(revision, scope: CurrentnessScope):
    predicates = []
    for values, column in (
        (scope.fact_ids, revision.fact_id),
        (scope.stock_ids, revision.stock_id),
        (scope.metric_keys, revision.metric_key),
        (scope.source_types, revision.source_type),
        (scope.source_document_ids, revision.source_document_id),
    ):
        if values:
            predicates.append(column.in_(values))
    for values, column in (
        (scope.user_ids, revision.user_id),
        (scope.period_types, revision.period_type),
        (scope.period_end_dates, revision.period_end_date),
        (scope.as_of_dates, revision.as_of_date),
    ):
        if values:
            predicates.append(_nullable_in(column, values))
    return predicates


def _fact_scope_predicates(scope: CurrentnessScope):
    """Apply the immutable slot scope to the compact fact relation.

    This is deliberately separate from timeline ranking.  A stock or metric
    filter can match millions of historical revision rows even when it names
    only a small number of facts.  Candidate IDs are established from
    ``metric_facts`` with an N+1 query first; the window below then receives
    exact fact IDs only.
    """

    predicates = []
    for values, column in (
        (scope.fact_ids, MetricFact.id),
        (scope.stock_ids, MetricFact.stock_id),
        (scope.metric_keys, MetricFact.metric_key),
        (scope.source_types, MetricFact.source_type),
        (scope.source_document_ids, MetricFact.source_document_id),
    ):
        if values:
            predicates.append(column.in_(values))
    for values, column in (
        (scope.user_ids, MetricFact.user_id),
        (scope.period_types, MetricFact.period_type),
        (scope.period_end_dates, MetricFact.period_end_date),
        (scope.as_of_dates, MetricFact.as_of_date),
    ):
        if values:
            predicates.append(_nullable_in(column, values))
    return predicates


def _candidate_anchor(scope: CurrentnessScope):
    """Choose an indexed immutable prefix for candidate keyset traversal."""

    if scope.fact_ids:
        return MetricFact.id
    if scope.stock_ids:
        return MetricFact.stock_id
    if scope.metric_keys:
        return MetricFact.metric_key
    return MetricFact.source_document_id


def _candidate_order_columns(scope: CurrentnessScope):
    anchor = _candidate_anchor(scope)
    return (MetricFact.id,) if anchor.key == "id" else (anchor, MetricFact.id)


def bounded_currentness_candidate_scope(
    session: Session,
    *,
    scope: CurrentnessScope | None,
) -> CurrentnessScope:
    """Return at most 1,000 exact fact IDs or fail with a typed overflow.

    The limit applies before any currentness revision is ranked.  It therefore
    bounds both SQL bind count and timeline work, and it cannot be defeated by
    adding arbitrarily many revisions for the same fact.
    """

    validated = _validate_scope(scope)
    candidate_ids = tuple(
        session.scalars(
            select(MetricFact.id)
            .where(*_fact_scope_predicates(validated))
            .order_by(*_candidate_order_columns(validated))
            .limit(MAX_CURRENTNESS_FACT_IDS + 1)
            .execution_options(autoflush=False)
        )
    )
    if len(candidate_ids) > MAX_CURRENTNESS_FACT_IDS:
        raise CurrentnessScopeError(
            CURRENTNESS_SCOPE_BOUND_EXCEEDED,
            "Metric-fact currentness fact candidates exceed "
            f"{MAX_CURRENTNESS_FACT_IDS} rows.",
        )
    return CurrentnessScope(fact_ids=candidate_ids)


class HistoricalCurrentnessUnverifiableError(ValueError):
    code = HISTORICAL_CURRENTNESS_UNVERIFIABLE

    def __init__(self) -> None:
        super().__init__(
            "Metric-fact currentness cannot be reconstructed at this cutoff."
        )


def require_currentness_authority(
    session: Session, *, knowledge_cutoff: datetime
) -> None:
    """Fail closed before reading the retained currentness timeline."""

    cache_key = "metric_fact_currentness_authority_started_at"
    authority_started_at = session.info.get(cache_key)
    if authority_started_at is None:
        authority_started_at = session.scalar(
            text(
                "SELECT authority_started_at "
                "FROM metric_fact_currentness_authority WHERE singleton=true"
            )
        )
        session.info[cache_key] = authority_started_at
    if authority_started_at is None or knowledge_cutoff < authority_started_at:
        raise HistoricalCurrentnessUnverifiableError()


def current_metric_fact_ids_at(
    session: Session,
    *,
    knowledge_cutoff: datetime,
    knowledge_txid_snapshot: str | None = None,
    scope: CurrentnessScope | None = None,
):
    """Return a bounded SQL subquery selecting facts current at exactly T.

    The migration observation is the conservative beginning of reconstructable
    history.  No caller timestamp or the mutable live projection is used.
    """

    if knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    scope = bounded_currentness_candidate_scope(session, scope=scope)
    if knowledge_txid_snapshot is None:
        knowledge_txid_snapshot = database_evaluation_snapshot(
            session, knowledge_cutoff
        ).visibility_snapshot
    if knowledge_txid_snapshot is not None and not isinstance(
        knowledge_txid_snapshot, str
    ):
        raise ValueError("knowledge_txid_snapshot must be a database snapshot")
    require_currentness_authority(session, knowledge_cutoff=knowledge_cutoff)

    revision = MetricFactCurrentnessRevision
    if not scope.fact_ids:
        return select(revision.fact_id).where(false())
    temporal_scope = [
        revision.known_at <= knowledge_cutoff,
        *_scope_predicates(revision, scope),
    ]
    if knowledge_txid_snapshot is not None:
        temporal_scope.append(
            or_(
                revision.created_txid.is_(None),
                transaction_visible_in_snapshot_predicate(
                    revision.created_txid,
                    visibility_snapshot=knowledge_txid_snapshot,
                    bind_name="metric_fact_currentness_visibility_snapshot",
                ),
            )
        )
    ranked = (
        select(
            revision.fact_id.label("fact_id"),
            revision.is_current.label("is_current"),
            func.row_number()
            .over(
                partition_by=revision.fact_id,
                order_by=(revision.known_at.desc(), revision.id.desc()),
            )
            .label("revision_rank"),
        )
        .where(*temporal_scope)
        .subquery()
    )
    return select(ranked.c.fact_id).where(
        ranked.c.revision_rank == 1,
        ranked.c.is_current.is_(True),
    )


def currentness_state_subquery(
    *,
    knowledge_cutoff: datetime,
    knowledge_txid_snapshot: str | None = None,
    scope: CurrentnessScope | None = None,
):
    """Latest currentness state at T, for projected conflict queries."""

    scope = _validate_scope(scope)
    if not scope.fact_ids:
        raise CurrentnessScopeError(
            CURRENTNESS_SCOPE_REQUIRED,
            "Currentness state ranking requires exact candidate fact IDs.",
        )
    if knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    revision = MetricFactCurrentnessRevision
    predicates = [
        revision.known_at <= knowledge_cutoff,
        *_scope_predicates(revision, scope),
    ]
    if knowledge_txid_snapshot is not None:
        predicates.append(
            or_(
                revision.created_txid.is_(None),
                transaction_visible_in_snapshot_predicate(
                    revision.created_txid,
                    visibility_snapshot=knowledge_txid_snapshot,
                    bind_name="metric_fact_currentness_state_visibility_snapshot",
                ),
            )
        )
    ranked = (
        select(
            revision.fact_id.label("fact_id"),
            revision.is_current.label("is_current"),
            func.row_number()
            .over(
                partition_by=revision.fact_id,
                order_by=(revision.known_at.desc(), revision.id.desc()),
            )
            .label("revision_rank"),
        )
        .where(*predicates)
        .subquery()
    )
    return (
        select(ranked.c.fact_id, ranked.c.is_current)
        .where(ranked.c.revision_rank == 1)
        .subquery()
    )


def iter_current_metric_fact_id_chunks_at(
    session: Session,
    *,
    evaluation_snapshot: EvaluationSnapshot,
    scope: CurrentnessScope,
):
    """Yield complete current fact IDs in bounded, snapshot-stable chunks.

    Direct one-stock/metric calls intentionally fail at N+1. Consumers whose
    contract legitimately spans many stocks use this explicit traversal: both
    stock binds and candidate fact binds stay at or below 1,000, every chunk
    reuses the caller's exact evaluation snapshot, and no prefix is presented
    as a complete result.
    """

    scope = _normalized_scope(scope)
    if not any(
        (
            scope.fact_ids,
            scope.stock_ids,
            scope.metric_keys,
            scope.source_document_ids,
        )
    ):
        _validate_scope(scope)
    # The iterator deliberately relaxes only the two dimensions it knows how
    # to segment. All other dimensions retain the direct-call bind bounds.
    _validate_scope(
        CurrentnessScope(
            fact_ids=(
                scope.fact_ids[:MAX_CURRENTNESS_FACT_IDS]
                if scope.fact_ids
                else scope.fact_ids
            ),
            stock_ids=(
                scope.stock_ids
                if scope.fact_ids
                else scope.stock_ids[:MAX_CURRENTNESS_STOCK_IDS]
            ),
            metric_keys=scope.metric_keys,
            user_ids=scope.user_ids,
            source_types=scope.source_types,
            source_document_ids=scope.source_document_ids,
            period_types=scope.period_types,
            period_end_dates=scope.period_end_dates,
            as_of_dates=scope.as_of_dates,
        )
    )

    if scope.fact_ids:
        primary_segments = [
            CurrentnessScope(
                fact_ids=tuple(
                    scope.fact_ids[index : index + MAX_CURRENTNESS_FACT_IDS]
                ),
                stock_ids=scope.stock_ids,
                metric_keys=scope.metric_keys,
                user_ids=scope.user_ids,
                source_types=scope.source_types,
                source_document_ids=scope.source_document_ids,
                period_types=scope.period_types,
                period_end_dates=scope.period_end_dates,
                as_of_dates=scope.as_of_dates,
            )
            for index in range(0, len(scope.fact_ids), MAX_CURRENTNESS_FACT_IDS)
        ]
    else:
        stock_segments = (
            [
                tuple(scope.stock_ids[index:index + MAX_CURRENTNESS_STOCK_IDS])
                for index in range(0, len(scope.stock_ids), MAX_CURRENTNESS_STOCK_IDS)
            ]
            if scope.stock_ids
            else [()]
        )
        primary_segments = [
            CurrentnessScope(
                stock_ids=stock_ids,
                metric_keys=scope.metric_keys,
                user_ids=scope.user_ids,
                source_types=scope.source_types,
                source_document_ids=scope.source_document_ids,
                period_types=scope.period_types,
                period_end_dates=scope.period_end_dates,
                as_of_dates=scope.as_of_dates,
            )
            for stock_ids in stock_segments
        ]

    for segment in primary_segments:
        if segment.fact_ids:
            current_ids = tuple(
                session.scalars(
                    select(MetricFact.id)
                    .where(
                        MetricFact.id.in_(
                            current_metric_fact_ids_at(
                                session,
                                knowledge_cutoff=evaluation_snapshot.cutoff,
                                knowledge_txid_snapshot=(
                                    evaluation_snapshot.visibility_snapshot
                                ),
                                scope=segment,
                            )
                        )
                    )
                    .order_by(MetricFact.id)
                    .execution_options(autoflush=False)
                )
            )
            if current_ids:
                yield current_ids
            continue
        anchor = _candidate_anchor(segment)
        last_anchor = None
        last_fact_id = 0
        while True:
            cursor_predicate = (
                ()
                if last_anchor is None
                else (
                    or_(
                        anchor > last_anchor,
                        and_(anchor == last_anchor, MetricFact.id > last_fact_id),
                    ),
                )
            )
            rows = tuple(
                session.execute(
                    select(MetricFact.id, anchor.label("candidate_anchor"))
                    .where(
                        *cursor_predicate,
                        *_fact_scope_predicates(segment),
                    )
                    .order_by(anchor, MetricFact.id)
                    .limit(MAX_CURRENTNESS_FACT_IDS)
                    .execution_options(autoflush=False)
                )
            )
            candidate_ids = tuple(int(row.id) for row in rows)
            if not candidate_ids:
                break
            current_ids = tuple(
                session.scalars(
                    select(MetricFact.id)
                    .where(
                        MetricFact.id.in_(
                            current_metric_fact_ids_at(
                                session,
                                knowledge_cutoff=evaluation_snapshot.cutoff,
                                knowledge_txid_snapshot=(
                                    evaluation_snapshot.visibility_snapshot
                                ),
                                scope=CurrentnessScope(fact_ids=candidate_ids),
                            )
                        )
                    )
                    .order_by(MetricFact.id)
                    .execution_options(autoflush=False)
                )
            )
            if current_ids:
                yield current_ids
            if len(candidate_ids) < MAX_CURRENTNESS_FACT_IDS:
                break
            last_anchor = rows[-1].candidate_anchor
            last_fact_id = candidate_ids[-1]
