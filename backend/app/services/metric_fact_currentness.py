"""Point-in-time authority for the ``metric_facts.is_current`` projection."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import bindparam, cast, func, or_, select, text
from sqlalchemy.orm import Session
from sqlalchemy.types import UserDefinedType

from app.models.facts import MetricFactCurrentnessRevision


HISTORICAL_CURRENTNESS_UNVERIFIABLE = "historical_currentness_unverifiable"


class HistoricalCurrentnessUnverifiableError(ValueError):
    code = HISTORICAL_CURRENTNESS_UNVERIFIABLE

    def __init__(self) -> None:
        super().__init__(
            "Metric-fact currentness cannot be reconstructed at this cutoff."
        )


class _TxidSnapshot(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kw):
        return "txid_snapshot"


def current_metric_fact_ids_at(
    session: Session,
    *,
    knowledge_cutoff: datetime,
    knowledge_txid_snapshot: str | None = None,
):
    """Return a bounded SQL subquery selecting facts current at exactly T.

    The migration observation is the conservative beginning of reconstructable
    history.  No caller timestamp or the mutable live projection is used.
    """

    if knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
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
    temporal_scope = [revision.known_at <= knowledge_cutoff]
    if knowledge_txid_snapshot is not None:
        temporal_scope.append(
            or_(
                revision.created_txid.is_(None),
                func.txid_visible_in_snapshot(
                    revision.created_txid,
                    cast(
                        bindparam(
                            "metric_fact_currentness_visibility_snapshot",
                            knowledge_txid_snapshot,
                        ),
                        _TxidSnapshot(),
                    ),
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


def currentness_state_subquery(*, knowledge_cutoff: datetime):
    """Latest currentness state at T, for projected conflict queries."""

    if knowledge_cutoff.utcoffset() is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    revision = MetricFactCurrentnessRevision
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
        .where(revision.known_at <= knowledge_cutoff)
        .subquery()
    )
    return (
        select(ranked.c.fact_id, ranked.c.is_current)
        .where(ranked.c.revision_rank == 1)
        .subquery()
    )
