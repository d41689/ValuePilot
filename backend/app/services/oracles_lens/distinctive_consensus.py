"""MVP4-06 distinctive consensus score (plan §7.11).

Advanced-sort metric that penalizes the signal-weighted score for
weak / crowded / low-conviction consensus. The three factors are
each clamped to ``[0, 1]`` so distinctive ≤ signal_weighted by
construction — distinctive cannot **enhance** a score; it can only
soften one that looks artificially strong.

    distinctive_consensus_score =
        signal_weighted_consensus_score
      × concentration_factor
      × persistence_factor
      × anti_crowding_factor

V1 calibration (constants are dial-able by bumping ``SCORE_VERSION``
and re-shipping):

- ``concentration_factor`` saturates at 10% aggregate position weight
  across all holders. Three holders averaging ≥ 3.3% each → full
  credit; three holders averaging 1% each → 0.30 factor.
- ``persistence_factor`` saturates at a 4-quarter median streak
  (matches the streak bonus threshold in MVP4-03's
  ``position_signal_weight``).
- ``anti_crowding_factor`` is the mean ``manager_signal_weight``
  across contributors. All long_term_fundamental holders → 1.0;
  all unknown → 0.60.

Plan §7.11 explicitly says V1 anti-crowding is a weak proxy. The
factors are computed honestly but ``distinctive`` is intended as an
**advanced sort option**, not the default ranking — per PO MVP4
gate D3.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover — import-cycle avoidance.
    from app.services.oracles_lens.signal_weighted_score import _HolderContribution


# V1 calibration constants. Documented saturation thresholds:
_CONCENTRATION_FULL_AGGREGATE_WEIGHT = Decimal("0.10")
_PERSISTENCE_FULL_MEDIAN_STREAK = 4


@dataclass(frozen=True)
class DistinctiveConsensusResult:
    distinctive_consensus_score: Decimal
    concentration_factor: Decimal
    persistence_factor: Decimal
    anti_crowding_factor: Decimal


def compute_distinctive_consensus(
    *,
    signal_weighted_score: Decimal,
    contributions: Iterable["_HolderContribution"],
) -> DistinctiveConsensusResult:
    """Pure function. No DB. Plan §7.11 V1 formula."""
    contributions = list(contributions)
    if not contributions:
        zero = Decimal("0")
        return DistinctiveConsensusResult(
            distinctive_consensus_score=zero,
            concentration_factor=zero,
            persistence_factor=zero,
            anti_crowding_factor=zero,
        )

    aggregate_weight = sum(
        (c.position_signal_weight.base for c in contributions), Decimal("0")
    )
    concentration_factor = min(
        aggregate_weight / _CONCENTRATION_FULL_AGGREGATE_WEIGHT,
        Decimal("1"),
    )

    median_streak = Decimal(
        median(max(c.holding_streak_quarters, 0) for c in contributions)
    )
    persistence_factor = min(
        median_streak / Decimal(_PERSISTENCE_FULL_MEDIAN_STREAK),
        Decimal("1"),
    )

    avg_manager_weight = sum(
        (c.manager_weight for c in contributions), Decimal("0")
    ) / Decimal(len(contributions))
    anti_crowding_factor = min(avg_manager_weight, Decimal("1"))

    composite = (
        signal_weighted_score
        * concentration_factor
        * persistence_factor
        * anti_crowding_factor
    )
    return DistinctiveConsensusResult(
        distinctive_consensus_score=composite,
        concentration_factor=concentration_factor,
        persistence_factor=persistence_factor,
        anti_crowding_factor=anti_crowding_factor,
    )
