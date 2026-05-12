"""MVP4-11 manager_type taxonomy resolution.

Single helper that orchestrates the PO-approved precedence rule
(decision gate D2):

  1. If admin has set ``InstitutionManager.manager_type`` to a value
     other than ``unknown``, return it with ``source='admin'``.
  2. Else, if a behavior-derived profile is available and its
     ``manager_type`` is non-``unknown``, return it with
     ``source='behavior'``.
  3. Else, return ``unknown`` with ``source='fallback_unknown'``.

The three-way source label keeps the score-explanation payload
unambiguous: "is this score's confidence low because we have no admin
label, or because behavior couldn't classify?" each gets a distinct
answer.

The weight is precomputed at resolution time so callers don't make a
second dictionary lookup. The weight table itself lives in
``app/services/oracles_lens/constants.py`` (MVP4-11 D4); changing a
weight is a code change that should be paired with a ``SCORE_VERSION``
bump.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.models.institutions import InstitutionManager
from app.services.oracles_lens.constants import MANAGER_SIGNAL_WEIGHTS
from app.services.oracles_lens.manager_signal import DerivedManagerSignalProfile


# Source labels for ``ManagerTypeResolution.source``. Kept as
# module-level constants so callers (MVP4-03 score_explanation,
# admin dashboard surfaces) can import the canonical strings instead
# of re-typing them.
SOURCE_ADMIN = "admin"
SOURCE_BEHAVIOR = "behavior"
SOURCE_FALLBACK_UNKNOWN = "fallback_unknown"


@dataclass(frozen=True)
class ManagerTypeResolution:
    """Resolved manager_type plus its provenance.

    ``canonical_type``: one of the eight values in
    ``app.models.institutions.MANAGER_TYPES``.
    ``source``: one of ``SOURCE_ADMIN`` / ``SOURCE_BEHAVIOR`` /
    ``SOURCE_FALLBACK_UNKNOWN``.
    ``weight``: ``MANAGER_SIGNAL_WEIGHTS[canonical_type]`` precomputed
    so callers see weight + source together.
    """

    canonical_type: str
    source: str
    weight: Decimal


def resolve_manager_type(
    manager: InstitutionManager,
    *,
    derived_profile: Optional[DerivedManagerSignalProfile] = None,
) -> ManagerTypeResolution:
    """Apply the MVP4-11 D2 precedence rule.

    The caller is responsible for computing ``derived_profile`` from
    holdings data when behavior fallback is needed — MVP4-11 does not
    re-run the behavior heuristics inside this function so the caller
    can cache the profile across multiple ``resolve_manager_type``
    calls within a single scoring batch.
    """
    admin_type = manager.manager_type or "unknown"
    if admin_type != "unknown":
        return ManagerTypeResolution(
            canonical_type=admin_type,
            source=SOURCE_ADMIN,
            weight=_weight_for(admin_type),
        )

    if derived_profile is not None and derived_profile.manager_type != "unknown":
        derived_type = derived_profile.manager_type
        return ManagerTypeResolution(
            canonical_type=derived_type,
            source=SOURCE_BEHAVIOR,
            weight=_weight_for(derived_type),
        )

    return ManagerTypeResolution(
        canonical_type="unknown",
        source=SOURCE_FALLBACK_UNKNOWN,
        weight=_weight_for("unknown"),
    )


def _weight_for(manager_type: str) -> Decimal:
    # MANAGER_SIGNAL_WEIGHTS is asserted to cover every canonical type
    # by tests/unit/test_13f_mvp4_manager_taxonomy.py — direct lookup
    # is safe under that invariant. We still default to ``unknown``'s
    # weight when an unexpected type sneaks in (defense in depth for a
    # caller bypassing the validator), rather than KeyError-ing
    # mid-score.
    return MANAGER_SIGNAL_WEIGHTS.get(manager_type, MANAGER_SIGNAL_WEIGHTS["unknown"])
