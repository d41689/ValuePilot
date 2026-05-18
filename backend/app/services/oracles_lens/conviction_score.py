"""MVP4-04 conviction score (plan §7.9).

Secondary explainer metric capped at 0-100. Five capped components:

    conviction_score_0_100 =
        position_importance      (max 30)
      + holding_persistence      (max 25)
      + manager_quality          (max 20)
      + recent_action            (max 15)
      + agreement                (max 10)

Pure functions; no DB access. Consumes the same
``_HolderContribution`` structure ``compute_signal_weighted_scores``
already builds in MVP4-03 so conviction is a passenger on the same
backfill pass — no second compute walk, no new JobRun.

V1 component formulas mirror the dashboard's existing
``_conviction_components`` (in ``oracles_lens/dashboard.py``) so the
persisted-path conviction reads the same way the legacy in-memory
dashboard already presents it. The dashboard's
``signal_weighted_consensus_score`` formula deliberately diverges
from MVP4-03 (see MVP4-03b task log); conviction does **not**
diverge, because plan §7.9 has a single formula and the in-memory
dashboard already implements it correctly.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover — import-cycle avoidance.
    from app.services.oracles_lens.signal_weighted_score import _HolderContribution


# Per-component caps. Plan §7.9.
_CAP_POSITION_IMPORTANCE = 30
_CAP_HOLDING_PERSISTENCE = 25
_CAP_MANAGER_QUALITY = 20
_CAP_RECENT_ACTION = 15
_CAP_AGREEMENT = 10

# Position-importance V1 thresholds (mirror dashboard).
_POSITION_IMPORTANCE_WEIGHT_FULL = Decimal("0.10")  # 10% portfolio weight saturates.
_POSITION_IMPORTANCE_WEIGHT_POINTS = 20
_POSITION_IMPORTANCE_TOP10_POINTS = 10
_POSITION_IMPORTANCE_TOP10_FULL_COUNT = 2  # 2 top-10 holders saturates.

# Holding-persistence threshold: median streak of 4 quarters saturates.
_PERSISTENCE_STREAK_FULL = 4

# Agreement threshold: 5 holders saturates.
_AGREEMENT_HOLDER_FULL = 5


@dataclass(frozen=True)
class ConvictionComponents:
    """Plan §7.9 component breakdown plus capped composite total."""

    position_importance: int
    holding_persistence: int
    manager_quality: int
    recent_action: int
    agreement: int

    @property
    def total(self) -> int:
        # The components are individually capped, so the sum is already
        # at most 100; an extra ``min(100, ...)`` would be redundant but
        # we apply it defensively in case a future tuning round raises
        # a per-component cap above its current value.
        return min(
            100,
            self.position_importance
            + self.holding_persistence
            + self.manager_quality
            + self.recent_action
            + self.agreement,
        )


def compute_conviction_components(
    contributions: Iterable["_HolderContribution"],
) -> ConvictionComponents:
    """Pure function. No DB. Plan §7.9 V1 formulas.

    Each component is capped individually so a single dominant input
    cannot mask the others. The drilldown exposes the per-component
    values (PO MVP4-01 D5 component-input-exposability rule).
    """
    contributions = list(contributions)
    if not contributions:
        return ConvictionComponents(0, 0, 0, 0, 0)

    holder_count = len(contributions)

    # Position importance — combines the strongest position weight
    # across holders with the count of top-10 ranks (saturated at 2).
    weights = [c.position_signal_weight.base for c in contributions]
    max_weight = max(weights)
    top_10_count = sum(
        1 for c in contributions if c.position_signal_weight.bonus_top_10 > Decimal("0")
    )
    weight_fraction = min(max_weight / _POSITION_IMPORTANCE_WEIGHT_FULL, Decimal("1"))
    top10_fraction = min(
        Decimal(top_10_count) / Decimal(_POSITION_IMPORTANCE_TOP10_FULL_COUNT),
        Decimal("1"),
    )
    position_importance = min(
        _CAP_POSITION_IMPORTANCE,
        int(
            round(
                float(weight_fraction) * _POSITION_IMPORTANCE_WEIGHT_POINTS
                + float(top10_fraction) * _POSITION_IMPORTANCE_TOP10_POINTS
            )
        ),
    )

    # Holding persistence — median streak across holders, saturated at
    # 4 quarters. Reads the raw ``holding_streak_quarters`` carried on
    # the contribution (added in MVP4-04 to avoid losing the streak
    # precision a binary bonus_streak flag would discard).
    streaks = [max(c.holding_streak_quarters, 0) for c in contributions]
    median_streak = median(streaks) if streaks else 0
    persistence_fraction = min(median_streak / _PERSISTENCE_STREAK_FULL, 1.0)
    holding_persistence = min(
        _CAP_HOLDING_PERSISTENCE,
        int(round(persistence_fraction * _CAP_HOLDING_PERSISTENCE)),
    )

    # Manager quality — mean of manager_signal_weight across holders.
    avg_manager_weight = sum(
        (float(c.manager_weight) for c in contributions), 0.0,
    ) / holder_count
    manager_quality = min(
        _CAP_MANAGER_QUALITY,
        int(round(min(avg_manager_weight, 1.0) * _CAP_MANAGER_QUALITY)),
    )

    # Recent action — fraction of holders that added or opened a new
    # position. Reads the raw ``add_intensity`` (carried on the
    # contribution by MVP4-04) so we count true add behavior even when
    # the signal-weighted ``action_adjustment`` is clamped to 0 by a
    # Class A caveat. Conviction is about the underlying story, so a
    # stale-recompute caveat shouldn't suppress the persistent
    # "manager added" fact.
    added_count = sum(
        1 for c in contributions
        if c.add_intensity is not None and c.add_intensity > Decimal("0")
    )
    add_context = added_count / holder_count
    recent_action = min(
        _CAP_RECENT_ACTION,
        int(round(add_context * _CAP_RECENT_ACTION)),
    )

    # Agreement — saturates at 5 holders.
    agreement_fraction = min(holder_count / _AGREEMENT_HOLDER_FULL, 1.0)
    agreement = min(
        _CAP_AGREEMENT,
        int(round(agreement_fraction * _CAP_AGREEMENT)),
    )

    return ConvictionComponents(
        position_importance=position_importance,
        holding_persistence=holding_persistence,
        manager_quality=manager_quality,
        recent_action=recent_action,
        agreement=agreement,
    )
