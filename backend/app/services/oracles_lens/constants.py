"""Oracle's Lens scoring constants (MVP4-01 + MVP4-11).

Typed Python module per MVP4 decision gate D5 (TL revision): heuristic
constants live in code so the deploy / migration audit trail is
automatic, not in a DB table whose own per-row versioning would
duplicate the audit problem we want to solve.

This module owns:
- ``SCORE_VERSION`` — bumped when the scoring formula changes in a way
  that produces a parallel column of scores instead of overwriting.
- ``MANAGER_SIGNAL_WEIGHTS`` — plan §7.2 example weights keyed on the
  canonical manager_type vocabulary (MVP4-11 D1).
"""
from __future__ import annotations

from decimal import Decimal


# Bumped when the scoring formula changes in a way that should produce
# a parallel column of scores instead of overwriting the existing ones.
# Used in oracles_lens_signals.score_version and in the JobRun lock_key
# (`oracles_lens_score:{period}:{score_version}`) so a v1.0 production
# run and a v1.1 shadow run can proceed concurrently.
SCORE_VERSION: str = "v1.0"


# Plan §7.2 example weights, MVP4-11 D4. Keyed on the canonical
# manager_type vocabulary in ``app.models.institutions.MANAGER_TYPES``.
# Bumping SCORE_VERSION and re-shipping this table is the only
# supported tuning path (MVP4 D5 PO clarification: no pre-launch
# tuning; no DB-table override).
MANAGER_SIGNAL_WEIGHTS: dict[str, Decimal] = {
    "long_term_fundamental": Decimal("1.00"),
    "value_concentrated":    Decimal("1.00"),
    "activist":              Decimal("0.80"),
    "unknown":               Decimal("0.60"),
    # V1 conservative fallback (MVP4-11 D3): ``multi_strategy`` does
    # not imply a consistent long-equity signal quality. Same weight
    # as ``unknown`` until V2 re-tunes from behavior evidence
    # (holding duration, concentration, turnover proxy, top-10
    # persistence), not from the label.
    "multi_strategy":        Decimal("0.60"),
    "quant":                 Decimal("0.40"),
    "high_turnover":         Decimal("0.30"),
    "index_like":            Decimal("0.10"),
}
