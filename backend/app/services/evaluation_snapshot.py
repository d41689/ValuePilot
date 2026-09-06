"""One database-owned boundary for an ordinary current-truth evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import bindparam, cast, func, or_, text
from sqlalchemy.orm import Session
from sqlalchemy.types import UserDefinedType


class _TxidSnapshot(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kw):
        return "txid_snapshot"


@dataclass(frozen=True)
class EvaluationSnapshot:
    cutoff: datetime
    visibility_snapshot: str


@dataclass(frozen=True)
class _SnapshotCacheEntry:
    snapshot: EvaluationSnapshot
    transaction: object


def retained_evaluation_snapshot(
    session: Session, cutoff: datetime
) -> EvaluationSnapshot | None:
    """Return a pair only inside the transaction that captured it."""

    entry = session.info.get("evaluation_snapshots", {}).get(cutoff.isoformat())
    if not isinstance(entry, _SnapshotCacheEntry):
        return None
    transaction = session.get_transaction()
    if transaction is None or entry.transaction is not transaction:
        return None
    return entry.snapshot


def transaction_visible_in_snapshot_predicate(
    transaction_id,
    *,
    visibility_snapshot: str,
    bind_name: str,
):
    """Use PostgreSQL transaction identity for stable read-your-writes."""

    return or_(
        transaction_id == func.txid_current(),
        func.txid_visible_in_snapshot(
            transaction_id,
            cast(bindparam(bind_name, visibility_snapshot), _TxidSnapshot()),
        ),
    )


def database_evaluation_snapshot(
    session: Session, supplied_cutoff: datetime | None = None
) -> EvaluationSnapshot:
    """Capture database time and transaction visibility in one statement."""

    if supplied_cutoff is not None and supplied_cutoff.tzinfo is None:
        raise ValueError("knowledge cutoff must be timezone-aware")
    if supplied_cutoff is not None:
        normalized = supplied_cutoff.astimezone(timezone.utc)
        retained = retained_evaluation_snapshot(session, normalized)
        if retained is not None:
            return retained
    row = session.execute(
        text(
            "WITH allocated AS MATERIALIZED (SELECT txid_current() AS txid) "
            "SELECT clock_timestamp() AS cutoff, "
            "txid_current_snapshot()::text AS visibility_snapshot "
            "FROM allocated"
        )
    ).one()
    cutoff = supplied_cutoff or row.cutoff
    if cutoff is None or cutoff.tzinfo is None:
        raise RuntimeError("database clock did not return an aware timestamp")
    snapshot = EvaluationSnapshot(
        cutoff=cutoff.astimezone(timezone.utc),
        visibility_snapshot=str(row.visibility_snapshot),
    )
    # Transitional consumers that receive only the cutoff can still recover
    # the exact database snapshot; no second statement may silently substitute
    # a later visibility boundary.
    transaction = session.get_transaction()
    if transaction is None:
        raise RuntimeError("evaluation snapshot requires an active transaction")
    session.info.setdefault("evaluation_snapshots", {})[snapshot.cutoff.isoformat()] = (
        _SnapshotCacheEntry(snapshot=snapshot, transaction=transaction)
    )
    return snapshot
