"""MVP4-05 caution flags surface.

The persisted ``oracles_lens_signals.caution_flag_codes`` JSONB array
is a flat list of string codes accumulated by MVP4-03 / MVP4-04 from
per-holder caveats. This module enriches that flat list into the
user-facing structured surface plan §7.13 specifies: each flag
carries ``code``, ``severity``, ``scope``, and ``label`` so MVP4-07
frontend can render the caution panel without inventing presentation
metadata.

Two MVP3 caveat vocabularies share concepts but use different
spellings:

- Score-emitted row-level: ``stale_until_recompute`` (MVP4-02
  primitive output) and ``NT_QUARTER_STREAK_BREAK``.
- Readiness pass-through: ``OWNERSHIP_CHANGES_NEEDS_RECOMPUTE``
  (MVP3-09 warning code), ``HISTORICAL_BACKFILL_NEEDS_VALIDATION``,
  ``CONFIDENTIAL_TREATMENT``, ``PARTIAL_COVERAGE``,
  ``AMENDMENTS_PENDING``, ``AMENDMENT_FAILED``,
  ``PRE_2023_PRE_HISTORY_UNAVAILABLE``,
  ``NT_DETECTION_UNSUPPORTED``.

``enrich_caveat_codes`` dedupes the alias pair
(``stale_until_recompute`` ↔ ``OWNERSHIP_CHANGES_NEEDS_RECOMPUTE``)
into a single user-facing entry under the readiness canonical name,
matching the SME D3 caution-flags vocabulary rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.thirteenf_quality_codes import (
    HISTORICAL_BACKFILL_NEEDS_VALIDATION as _HISTORICAL_BACKFILL_FINDING_RULE_CODE,
)


# ---------------------------------------------------------------------------
# Caveat code constants — caveat-collection sites import these by name so
# any rename here propagates through the codebase.
# ---------------------------------------------------------------------------

# Already collected by MVP4-02 / MVP4-03 (re-exported for symmetry):
CAVEAT_CONFIDENTIAL_TREATMENT = "CONFIDENTIAL_TREATMENT"
CAVEAT_PARTIAL_COVERAGE = "PARTIAL_COVERAGE"
CAVEAT_NT_QUARTER_STREAK_BREAK = "NT_QUARTER_STREAK_BREAK"
CAVEAT_STALE_UNTIL_RECOMPUTE = "stale_until_recompute"
# Dual-use string: same value is the QualityFinding13F.rule_code (canonical
# in thirteenf_quality_codes) AND the row-level caveat on score rows. Bind
# to the canonical source so the two surfaces can't desync silently.
CAVEAT_HISTORICAL_BACKFILL_NEEDS_VALIDATION = _HISTORICAL_BACKFILL_FINDING_RULE_CODE
CAVEAT_PRE_2023_PRE_HISTORY_UNAVAILABLE = "PRE_2023_PRE_HISTORY_UNAVAILABLE"

# Readiness vocabulary canonical name for the recompute concept
# (MVP3-09 surfaces this code as a warning). Same finding as
# ``stale_until_recompute``; the structured surface dedupes them
# under this canonical name.
CAVEAT_OWNERSHIP_CHANGES_NEEDS_RECOMPUTE = "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE"

# New in MVP4-05 — emitted by signal_weighted_score._contributions_for_stock
# when Filing13F.amendment_status flags a pending or failed amendment
# on the holder's filing.
CAVEAT_AMENDMENTS_PENDING = "AMENDMENTS_PENDING"
CAVEAT_AMENDMENT_FAILED = "AMENDMENT_FAILED"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaveatMetadata:
    code: str  # canonical user-facing code (UPPER_SNAKE_CASE)
    severity: str  # "low" | "medium" — mirrors score_confidence demotion tier
    scope: str  # "row" | "stock"
    label: str  # human-readable surface text


# Aliases: keys are the spellings that may appear in
# ``oracles_lens_signals.caution_flag_codes``; values are the
# canonical user-facing CaveatMetadata. ``stale_until_recompute`` and
# ``OWNERSHIP_CHANGES_NEEDS_RECOMPUTE`` map to the same metadata so
# the enrichment dedupes them.
_RECOMPUTE_METADATA = CaveatMetadata(
    code=CAVEAT_OWNERSHIP_CHANGES_NEEDS_RECOMPUTE,
    severity="low",
    scope="row",
    label=(
        "Recent corporate-action mapping changes; this holder's "
        "ownership-change delta may be stale until recompute completes."
    ),
)


CAUTION_FLAG_REGISTRY: dict[str, CaveatMetadata] = {
    CAVEAT_CONFIDENTIAL_TREATMENT: CaveatMetadata(
        code=CAVEAT_CONFIDENTIAL_TREATMENT,
        severity="medium",
        scope="row",
        label="Some holdings were omitted from this manager's filing under confidential treatment.",
    ),
    CAVEAT_PARTIAL_COVERAGE: CaveatMetadata(
        code=CAVEAT_PARTIAL_COVERAGE,
        severity="medium",
        scope="row",
        label="This holder filed a Combination Report; their portfolio weight is not available.",
    ),
    CAVEAT_AMENDMENTS_PENDING: CaveatMetadata(
        code=CAVEAT_AMENDMENTS_PENDING,
        severity="medium",
        scope="row",
        label="An amendment to this holder's filing is pending; the displayed position may change.",
    ),
    CAVEAT_AMENDMENT_FAILED: CaveatMetadata(
        code=CAVEAT_AMENDMENT_FAILED,
        severity="medium",
        scope="row",
        label="An amendment to this holder's filing failed parsing and is awaiting admin review.",
    ),
    CAVEAT_OWNERSHIP_CHANGES_NEEDS_RECOMPUTE: _RECOMPUTE_METADATA,
    CAVEAT_STALE_UNTIL_RECOMPUTE: _RECOMPUTE_METADATA,  # alias
    CAVEAT_HISTORICAL_BACKFILL_NEEDS_VALIDATION: CaveatMetadata(
        code=CAVEAT_HISTORICAL_BACKFILL_NEEDS_VALIDATION,
        severity="low",
        scope="row",
        label="This holder's filing was historically backfilled and is awaiting validation.",
    ),
    CAVEAT_NT_QUARTER_STREAK_BREAK: CaveatMetadata(
        code=CAVEAT_NT_QUARTER_STREAK_BREAK,
        severity="medium",
        scope="row",
        label="A 13F-NT quarter punctuated this holder's streak; persistence may be understated.",
    ),
    CAVEAT_PRE_2023_PRE_HISTORY_UNAVAILABLE: CaveatMetadata(
        code=CAVEAT_PRE_2023_PRE_HISTORY_UNAVAILABLE,
        severity="medium",
        scope="row",
        label="Data starts at 2023-Q1; pre-2023 ownership for this holder is not observed.",
    ),
}


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


def enrich_caveat_codes(codes: list[str]) -> list[dict[str, Any]]:
    """Convert a flat list of caveat strings into the structured
    surface MVP4-07 frontend renders.

    - Order: first-occurrence preserved.
    - Dedupe: alias pair
      (``stale_until_recompute``, ``OWNERSHIP_CHANGES_NEEDS_RECOMPUTE``)
      collapses to one entry using the readiness canonical name.
    - Unknown codes: surfaced with ``severity="unknown"`` rather than
      silently dropped so a regression in the registry shows up in
      review.
    """
    seen_codes: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw_code in codes or []:
        metadata = CAUTION_FLAG_REGISTRY.get(raw_code)
        if metadata is None:
            canonical = raw_code
            if canonical in seen_codes:
                continue
            seen_codes.add(canonical)
            out.append({
                "code": canonical,
                "severity": "unknown",
                "scope": "row",
                "label": raw_code,
            })
            continue
        canonical = metadata.code
        if canonical in seen_codes:
            continue
        seen_codes.add(canonical)
        out.append({
            "code": metadata.code,
            "severity": metadata.severity,
            "scope": metadata.scope,
            "label": metadata.label,
        })
    return out
