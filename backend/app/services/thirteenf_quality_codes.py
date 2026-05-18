"""Canonical ``QualityFinding13F.rule_code`` constants (MVP4-09).

Single source of truth for the three UPPER_SNAKE_CASE rule_codes that
MVP3-02, MVP3-06, and MVP3-07 emit into ``quality_findings_13f`` rows.
Each downstream consumer (readiness service, admin dashboard, scoring
primitives in MVP4-02) imports the constants from here instead of
maintaining a private copy.

**Do not change the string values.** DB rows persisted by MVP3-02 /
MVP3-06 / MVP3-07 already carry these exact strings; renaming would
require a backfill migration.

**Not in scope:**

- Pre-MVP3 lowercase rule_codes emitted by
  ``edgar_quality._check_reconciliation`` /
  ``_check_cusip_format`` / etc. The TL1 fix in the MVP3 end-to-end
  review explicitly left these for a future cleanup that includes a
  DB migration.
- Caveat code vocabulary used by the scoring services
  (``PARTIAL_COVERAGE``, ``NT_QUARTER_STREAK_BREAK``,
  ``stale_until_recompute``, ``PRE_2023_PRE_HISTORY_UNAVAILABLE``).
  Those are row-level caveats on score rows, not finding
  ``rule_code`` values; they remain local to the emitting service
  until a separate caveat-vocabulary consumer appears.
"""
from __future__ import annotations


VALUE_UNIT_SANITY: str = "VALUE_UNIT_SANITY"
"""MVP3-02: value-unit sanity quality finding emitted by
``edgar_quality._check_value_unit_sanity`` when a filing's
reported total deviates by ~1000× from prior-quarter expectations.
"""

OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION: str = (
    "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"
)
"""MVP3-06: emitted when a corporate-action CUSIP mapping is
confirmed; flags ``ownership_changes`` rows whose deltas need to be
recomputed against the new mapping. Consumed by readiness as a
warning, by the admin dashboard as a quarter-health input, and by
MVP4-02 ``compute_add_intensity`` to snap stale intensities to flat.
"""

HISTORICAL_BACKFILL_NEEDS_VALIDATION: str = "HISTORICAL_BACKFILL_NEEDS_VALIDATION"
"""MVP3-07: emitted per backfilled filing pending validation-gate
clearance. Consumed by readiness as a warning, by the admin
dashboard as a quarter-health input, and by MVP4-02
``compute_add_intensity`` to snap intensities to flat while
validation is open.
"""
