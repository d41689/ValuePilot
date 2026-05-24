"""Manager taxonomy V2 — style_primary → legacy manager_type mapping.

Task doc: ``docs/tasks/2026-05-24_manager-taxonomy-v2.md``

The V2 taxonomy introduces eight value-investor-oriented ``style_primary``
buckets, but Oracle's Lens still reads the legacy eight-value
``manager_type`` enum to look up signal weights in
``app/services/oracles_lens/constants.py``. This module is the single
source of truth that maps V2 → V1 so that:

1. Seeding code (``seed_confirmed_managers``) can derive the legacy
   ``manager_type`` from each entry's ``style_primary``.
2. The hero outcome of the V2 change — Tiger Cubs no longer carrying a
   ``long_term_fundamental`` 1.00 weight — is enforced by a single
   table, not scattered across data files.

Adding a new ``style_primary`` value is a two-line change here plus a
test bump in
``backend/tests/unit/test_13f_manager_taxonomy_v2.py``.

Design notes
------------
- ``value_deep`` and ``value_concentrated`` both map to legacy
  ``value_concentrated``: same V1 weight (1.00) but the V2 split lets
  consumers filter "Tweedy/Southeastern/Yacktman" vs
  "Baupost/Akre/Pabrai" without changing scoring math.
- ``quality_compounder`` maps to ``long_term_fundamental`` (weight 1.00)
  because that's where Lindsell Train / Fundsmith / Polen / Cantillon
  conceptually live in V1.
- ``growth_long_short`` maps to legacy ``high_turnover`` (weight 0.30).
  This is the single most impactful mapping in this file — it is the
  PO-approved fix for the Tiger Cubs misclassification documented in
  the acceptance review.
- ``special_situations`` and ``multi_strategy_macro`` both map to
  legacy ``multi_strategy`` (weight 0.60, the conservative V1
  fallback). Behavior-derived weights will refine this in a later
  milestone.
- ``endowment_passive`` maps to ``index_like`` (weight 0.10) so the
  Gates Foundation Trust's gifting-driven trades don't dominate signal.
"""
from __future__ import annotations

from app.models.institutions import MANAGER_TYPES, STYLE_PRIMARY


# Single source of truth. Every key must be in ``STYLE_PRIMARY`` and every
# value must be in ``MANAGER_TYPES`` — both invariants are pinned by tests.
STYLE_PRIMARY_TO_LEGACY: dict[str, str] = {
    "value_deep": "value_concentrated",
    "value_concentrated": "value_concentrated",
    "quality_compounder": "long_term_fundamental",
    "activist": "activist",
    "growth_long_short": "high_turnover",
    "special_situations": "multi_strategy",
    "multi_strategy_macro": "multi_strategy",
    "endowment_passive": "index_like",
    "unknown": "unknown",
}


def derive_legacy_manager_type(style_primary: str) -> str:
    """Map a V2 ``style_primary`` to the legacy ``manager_type`` value
    that Oracle's Lens uses to look up its signal weight.

    Raises ``ValueError`` for unknown inputs so a typo in the seed JSON
    surfaces immediately instead of silently degrading to ``unknown``
    (which would mask the regression).
    """
    try:
        legacy = STYLE_PRIMARY_TO_LEGACY[style_primary]
    except KeyError as exc:
        raise ValueError(
            f"Unknown style_primary={style_primary!r}; expected one of "
            f"{sorted(STYLE_PRIMARY_TO_LEGACY.keys())}"
        ) from exc
    # Defense-in-depth: if a future edit puts a non-canonical legacy on
    # the right-hand side, fail loudly rather than letting the model
    # validator catch it on every write.
    if legacy not in MANAGER_TYPES:
        raise ValueError(
            f"STYLE_PRIMARY_TO_LEGACY[{style_primary!r}] = {legacy!r} is "
            f"not in MANAGER_TYPES; update both tables together."
        )
    return legacy
