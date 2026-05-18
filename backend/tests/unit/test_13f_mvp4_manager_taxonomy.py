"""MVP4-11 manager_type taxonomy reconciliation tests.

PO-approved decisions (gate doc D1-D5):
- D1: canonical 8-value set; legacy ``fundamental_long`` removed.
- D2: admin-set wins; three-way source label
  ``admin`` / ``behavior`` / ``fallback_unknown``.
- D3: ``multi_strategy`` is a V1 conservative fallback to the
  ``unknown`` weight (``Decimal("0.60")``), not an independent
  calibration.
- D4: weights live in ``app/services/oracles_lens/constants.py``
  as ``Decimal``.
"""
from __future__ import annotations

from decimal import Decimal
from itertools import count

import pytest

from app.models.institutions import (
    InstitutionManager,
    MANAGER_TYPES,
)
from app.services.oracles_lens.constants import MANAGER_SIGNAL_WEIGHTS
from app.services.oracles_lens.manager_signal import DerivedManagerSignalProfile
from app.services.oracles_lens.manager_taxonomy import (
    ManagerTypeResolution,
    resolve_manager_type,
)
from app.services.thirteenf_user_api import VALUE_MANAGER_TYPES


_CIK_SEQ = count(9991100000)


CANONICAL_MANAGER_TYPES = {
    "long_term_fundamental",
    "value_concentrated",
    "activist",
    "quant",
    "high_turnover",
    "index_like",
    "multi_strategy",
    "unknown",
}


def _manager(db_session, *, manager_type: str = "unknown") -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-11 Mgr {cik}",
        legal_name=f"Mv4-11 Mgr {cik}",
        edgar_legal_name=f"Mv4-11 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _derived(manager_type: str) -> DerivedManagerSignalProfile:
    return DerivedManagerSignalProfile(
        manager_type=manager_type,
        manager_signal_weight=1.0,
        portfolio_concentration=0.5,
        portfolio_holding_count=20,
        average_holding_period_quarters=6.0,
        source="derived_13f_behavior",
    )


# ===========================================================================
# D1 — canonical taxonomy
# ===========================================================================


def test_manager_types_enum_matches_canonical_set():
    assert MANAGER_TYPES == CANONICAL_MANAGER_TYPES, (
        f"MANAGER_TYPES diverged from MVP4-11 D1 canonical set. "
        f"Diff: {MANAGER_TYPES.symmetric_difference(CANONICAL_MANAGER_TYPES)}"
    )


def test_legacy_fundamental_long_is_rejected(db_session):
    with pytest.raises(ValueError, match="manager_type"):
        _manager(db_session, manager_type="fundamental_long")


def test_new_value_concentrated_and_high_turnover_are_accepted(db_session):
    a = _manager(db_session, manager_type="value_concentrated")
    b = _manager(db_session, manager_type="high_turnover")
    assert a.manager_type == "value_concentrated"
    assert b.manager_type == "high_turnover"


# ===========================================================================
# D2 — admin-set vs behavior-derived precedence
# ===========================================================================


def test_admin_set_wins_when_not_unknown(db_session):
    manager = _manager(db_session, manager_type="long_term_fundamental")

    # A behavior-derived profile that disagrees must not override the
    # admin label.
    result = resolve_manager_type(
        manager, derived_profile=_derived("quant"),
    )

    assert isinstance(result, ManagerTypeResolution)
    assert result.canonical_type == "long_term_fundamental"
    assert result.source == "admin"
    assert result.weight == Decimal("1.00")


def test_behavior_falls_back_when_admin_is_unknown(db_session):
    manager = _manager(db_session, manager_type="unknown")

    result = resolve_manager_type(
        manager, derived_profile=_derived("value_concentrated"),
    )

    assert result.canonical_type == "value_concentrated"
    assert result.source == "behavior"
    assert result.weight == Decimal("1.00")


def test_fallback_unknown_when_both_admin_and_behavior_are_unknown(db_session):
    manager = _manager(db_session, manager_type="unknown")

    # Behavior also returns 'unknown' — neither layer can classify.
    result = resolve_manager_type(
        manager, derived_profile=_derived("unknown"),
    )

    assert result.canonical_type == "unknown"
    assert result.source == "fallback_unknown"
    assert result.weight == MANAGER_SIGNAL_WEIGHTS["unknown"]


def test_fallback_unknown_when_no_derived_profile_provided(db_session):
    """A caller that has not computed a behavior profile (e.g. very new
    manager with no holdings yet) must still get a resolution rather
    than an exception.
    """
    manager = _manager(db_session, manager_type="unknown")

    result = resolve_manager_type(manager, derived_profile=None)

    assert result.canonical_type == "unknown"
    assert result.source == "fallback_unknown"


# ===========================================================================
# D3 / D4 — weight table
# ===========================================================================


def test_all_canonical_manager_types_have_weights():
    missing = CANONICAL_MANAGER_TYPES - set(MANAGER_SIGNAL_WEIGHTS.keys())
    extra = set(MANAGER_SIGNAL_WEIGHTS.keys()) - CANONICAL_MANAGER_TYPES
    assert not missing, (
        f"MANAGER_SIGNAL_WEIGHTS missing canonical types: {missing}. "
        "Every canonical manager_type must have a weight (per D4) so "
        "MVP4-03 signal-weighted score does not need a runtime fallback."
    )
    assert not extra, (
        f"MANAGER_SIGNAL_WEIGHTS has non-canonical keys: {extra}. "
        "Add new types to MANAGER_TYPES first; do not let the weight "
        "table drift from the enum."
    )


def test_weights_use_decimal_type():
    for key, value in MANAGER_SIGNAL_WEIGHTS.items():
        assert isinstance(value, Decimal), (
            f"MANAGER_SIGNAL_WEIGHTS[{key!r}] is {type(value).__name__}, "
            "expected Decimal (D4)."
        )


def test_multi_strategy_weight_equals_unknown_weight_v1():
    """D3 V1 conservative fallback: multi_strategy is not an
    independent calibration. It must match unknown until V2 tuning
    decides otherwise.
    """
    assert MANAGER_SIGNAL_WEIGHTS["multi_strategy"] == (
        MANAGER_SIGNAL_WEIGHTS["unknown"]
    )
    assert MANAGER_SIGNAL_WEIGHTS["unknown"] == Decimal("0.60")


def test_plan_section_7_2_example_weights_present():
    """D4: ship plan §7.2 example weights as defaults. Spot-check the
    distinctive values to prevent silent recalibration.
    """
    assert MANAGER_SIGNAL_WEIGHTS["long_term_fundamental"] == Decimal("1.00")
    assert MANAGER_SIGNAL_WEIGHTS["value_concentrated"] == Decimal("1.00")
    assert MANAGER_SIGNAL_WEIGHTS["activist"] == Decimal("0.80")
    assert MANAGER_SIGNAL_WEIGHTS["quant"] == Decimal("0.40")
    assert MANAGER_SIGNAL_WEIGHTS["high_turnover"] == Decimal("0.30")
    assert MANAGER_SIGNAL_WEIGHTS["index_like"] == Decimal("0.10")


# ===========================================================================
# MVP2 consumer continuity — VALUE_MANAGER_TYPES rename
# ===========================================================================


def test_value_manager_types_uses_canonical_long_term_fundamental():
    """D1 + MVP2 consumer continuity: the only MVP2 consumer that
    still referenced `fundamental_long` must be updated to the
    canonical spelling. The set membership (one renamed value plus
    `activist`) stays the same; only the literal changes.
    """
    assert VALUE_MANAGER_TYPES == {"long_term_fundamental", "activist"}
    assert "fundamental_long" not in VALUE_MANAGER_TYPES
