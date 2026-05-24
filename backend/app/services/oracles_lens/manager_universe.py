"""Resolve a manager_id allowlist from the V2 taxonomy filters
(``style_primary`` / ``capital_structure`` / ``market_cap_focus``).

Task doc: ``docs/tasks/2026-05-24_oracles-lens-universe-selector.md``

Returns ``None`` when no filter is applied — the caller MUST then
take the persisted fast path. Returns a (possibly empty) set of
manager_ids when any filter is applied; downstream callers use this
to filter holdings before recomputing Signal / Conviction /
Distinctive scores.

Validation: rejects unknown values from the V2 vocabularies with
``ValueError`` so a typo in the API query surfaces as HTTP 400, not
as a silent zero-result "filter".
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.institutions import (
    CAPITAL_STRUCTURE,
    MARKET_CAP_FOCUS,
    STYLE_PRIMARY,
    InstitutionManager,
)


def _validate_each(field: str, values: list[str], allowed: set[str]) -> None:
    bad = [v for v in values if v not in allowed]
    if bad:
        raise ValueError(
            f"{field} contains unknown value(s) {bad!r}; allowed = "
            f"{sorted(allowed)}"
        )


def resolve_manager_id_allowlist(
    session: Session,
    *,
    style_primary: list[str],
    capital_structure: list[str],
    market_cap_focus: list[str],
) -> Optional[set[int]]:
    """Resolve the manager_id set matching ALL specified dimensions.

    Returns ``None`` when every list is empty — the universe is "all
    managers" and the caller should take the persisted fast path.

    The semantics are **intersection across dimensions, union within a
    dimension** — e.g.
    ``style_primary=[value_deep, value_concentrated],
      capital_structure=[permanent_capital]`` returns managers whose
    style_primary is one of {value_deep, value_concentrated} AND whose
    capital_structure is permanent_capital.

    This makes presets composable: "Deep Value × Permanent Capital" is
    one preset that AND's together two filters from different
    dimensions, while "Deep Value" alone is a single-dimension preset
    that picks multiple style values.
    """
    if not style_primary and not capital_structure and not market_cap_focus:
        return None

    _validate_each("style_primary", style_primary, STYLE_PRIMARY)
    _validate_each("capital_structure", capital_structure, CAPITAL_STRUCTURE)
    _validate_each("market_cap_focus", market_cap_focus, MARKET_CAP_FOCUS)

    q = session.query(InstitutionManager.id)
    if style_primary:
        q = q.filter(InstitutionManager.style_primary.in_(style_primary))
    if capital_structure:
        q = q.filter(InstitutionManager.capital_structure.in_(capital_structure))
    if market_cap_focus:
        q = q.filter(InstitutionManager.market_cap_focus.in_(market_cap_focus))
    return {row.id for row in q.all()}
