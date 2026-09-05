"""Point-in-time authority for the ``metric_facts.is_current`` projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFactCurrentnessRevision
from app.services.evaluation_snapshot import (
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
    bounds = (
        (scope.fact_ids, MAX_CURRENTNESS_FACT_IDS, "fact_ids"),
        (scope.stock_ids, MAX_CURRENTNESS_STOCK_IDS, "stock_ids"),
        (scope.source_document_ids, MAX_CURRENTNESS_DOCUMENT_IDS, "document_ids"),
        (scope.metric_keys, MAX_CURRENTNESS_METRIC_KEYS, "metric_keys"),
        (scope.user_ids, MAX_CURRENTNESS_USER_IDS, "user_ids"),
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


class HistoricalCurrentnessUnverifiableError(ValueError):
    code = HISTORICAL_CURRENTNESS_UNVERIFIABLE

    def __init__(self) -> None:
        super().__init__(
            "Metric-fact currentness cannot be reconstructed at this cutoff."
        )


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

    scope = _validate_scope(scope)
    if knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    if knowledge_txid_snapshot is None:
        knowledge_txid_snapshot = database_evaluation_snapshot(
            session, knowledge_cutoff
        ).visibility_snapshot
    if knowledge_txid_snapshot is not None and not isinstance(
        knowledge_txid_snapshot, str
    ):
        raise ValueError("knowledge_txid_snapshot must be a database snapshot")
    cache_key = "metric_fact_currentness_authority_started_at"
    authority_started_at = session.info.get(cache_key)
    if authority_started_at is None:
        authority_started_at = session.scalar(
            text(
                "SELECT authority_started_at FROM metric_fact_currentness_authority "
                "WHERE singleton=true"
            )
        )
        session.info[cache_key] = authority_started_at
    if authority_started_at is None or knowledge_cutoff < authority_started_at:
        raise HistoricalCurrentnessUnverifiableError()

    revision = MetricFactCurrentnessRevision
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
