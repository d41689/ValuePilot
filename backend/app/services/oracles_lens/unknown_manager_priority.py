"""MVP4-07b admin surface — managers with manager_type='unknown' ranked
by how much they drag score_confidence on the latest usable quarter.

Originally the SME non-blocking note on MVP4-11 (the manager_type
taxonomy reconciliation); deferred to "after MVP4-03 ships when
score_confidence outputs exist." Those outputs are now live
(MVP4-03/04/05/06), so this service powers an admin prioritization
panel so the typing backlog has an obvious priority order.

For each ``unknown`` admin manager who currently appears as a
direct linked holder in at least one scored stock for the latest
usable quarter, returns:

- ``affected_signal_count`` — how many ``oracles_lens_signals``
  rows the manager contributes to (i.e. how many stocks the user
  sees in Oracle's Lens whose confidence is *partially driven by
  this unknown*).
- ``worst_score_confidence_observed`` — the lowest tier among
  those signals; ranks ``low_confidence`` worst,
  ``high_confidence`` best.

Default ordering: ``affected_signal_count`` descending, then
``worst_score_confidence_observed`` ascending tier. Managers who
appear on the most scores and drag the most confidence to the
bottom appear first.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensSignal
from app.services.oracles_lens.constants import SCORE_VERSION
from app.services.thirteenf_holdings_query import HR_FORM_TYPES


# Confidence tier ranking for "worst observed" comparison. Lower
# rank = worse confidence; ``low_confidence`` is the worst tier so
# it sorts first.
_CONFIDENCE_TIER_RANK = {
    "low_confidence": 0,
    "medium_confidence": 1,
    "high_confidence": 2,
    "unavailable": -1,  # already unavailable — worse than low
}


def build_unknown_manager_priority(
    session: Session, *, score_version: str = SCORE_VERSION,
) -> dict[str, Any]:
    """Return the admin priority payload.

    The empty case (no scored signals yet) returns ``items=[]`` plus
    a null ``quarter`` field so the admin UI can render a "no
    persisted scores yet — run a backfill first" hint without
    crashing.
    """
    latest_quarter = _latest_scored_quarter(session, score_version=score_version)
    if latest_quarter is None:
        return {"quarter": None, "score_version": score_version, "items": []}

    # All linked direct holdings by unknown-typed managers in the
    # latest scored quarter, joined to their scored stocks.
    rows = (
        session.query(
            InstitutionManager.id,
            InstitutionManager.canonical_name,
            OraclesLensSignal.stock_id,
            OraclesLensSignal.score_confidence,
        )
        .join(Holding13F, Holding13F.manager_id == InstitutionManager.id)
        .join(ParseRun13F, ParseRun13F.id == Holding13F.parse_run_id)
        .join(
            Filing13F,
            Filing13F.accession_number == ParseRun13F.accession_number,
        )
        .join(OraclesLensSignal, OraclesLensSignal.stock_id == Holding13F.stock_id)
        .filter(InstitutionManager.manager_type == "unknown")
        .filter(InstitutionManager.status == "active")
        .filter(Filing13F.form_type.in_(HR_FORM_TYPES))
        .filter(Filing13F.is_active_for_manager_period.is_(True))
        .filter(ParseRun13F.is_current.is_(True))
        .filter(Holding13F.report_quarter == latest_quarter)
        .filter(Holding13F.cusip_mapping_status == "linked")
        .filter(Holding13F.holding_attribution_status == "direct")
        .filter(OraclesLensSignal.report_quarter == latest_quarter)
        .filter(OraclesLensSignal.score_version == score_version)
        .all()
    )

    # Aggregate in Python: per manager, distinct affected stock_ids
    # plus the worst confidence tier observed across them.
    per_manager: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "manager_id": 0,
            "canonical_name": "",
            "affected_stock_ids": set(),
            "worst_score_confidence_observed": "high_confidence",
        }
    )
    for manager_id, canonical_name, stock_id, score_confidence in rows:
        entry = per_manager[manager_id]
        entry["manager_id"] = manager_id
        entry["canonical_name"] = canonical_name
        entry["affected_stock_ids"].add(stock_id)
        if _worse(score_confidence, entry["worst_score_confidence_observed"]):
            entry["worst_score_confidence_observed"] = score_confidence

    items = [
        {
            "manager_id": entry["manager_id"],
            "canonical_name": entry["canonical_name"],
            "affected_signal_count": len(entry["affected_stock_ids"]),
            "worst_score_confidence_observed": entry["worst_score_confidence_observed"],
        }
        for entry in per_manager.values()
    ]
    # Default sort: affected_signal_count desc, then worst tier asc.
    items.sort(
        key=lambda x: (
            -x["affected_signal_count"],
            _CONFIDENCE_TIER_RANK.get(x["worst_score_confidence_observed"], 99),
            x["manager_id"],
        )
    )
    return {
        "quarter": latest_quarter,
        "score_version": score_version,
        "items": items,
    }


def _latest_scored_quarter(
    session: Session, *, score_version: str,
) -> str | None:
    """Most recent ``report_quarter`` with at least one
    ``oracles_lens_signals`` row for the requested ``score_version``.
    """
    row = (
        session.query(OraclesLensSignal.report_quarter)
        .filter(OraclesLensSignal.score_version == score_version)
        .order_by(OraclesLensSignal.report_quarter.desc())
        .first()
    )
    return row[0] if row else None


def _worse(candidate: str | None, current: str | None) -> bool:
    """Return True iff ``candidate`` ranks worse than ``current``."""
    return _CONFIDENCE_TIER_RANK.get(candidate or "unavailable", -1) < _CONFIDENCE_TIER_RANK.get(
        current or "unavailable", -1
    )
