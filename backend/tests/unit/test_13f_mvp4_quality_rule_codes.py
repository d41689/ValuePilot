"""MVP4-09 shared QualityFinding rule_code constants.

These tests pin the canonical strings so a future refactor cannot
accidentally rename them — DB rows persisted by MVP3-02 / MVP3-06 /
MVP3-07 already use these exact values.
"""
from __future__ import annotations


def test_canonical_rule_codes_have_documented_values():
    from app.services import thirteenf_quality_codes as qc

    assert qc.VALUE_UNIT_SANITY == "VALUE_UNIT_SANITY"
    assert qc.OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION == (
        "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION"
    )
    assert qc.HISTORICAL_BACKFILL_NEEDS_VALIDATION == "HISTORICAL_BACKFILL_NEEDS_VALIDATION"


def test_writer_modules_use_canonical_module_as_source_of_truth():
    """Every writer / reader that previously held a private copy now
    resolves to the same string the canonical module exposes. The check
    is by-value so legacy local aliases (e.g.
    `VALUE_UNIT_SANITY_RULE_CODE` for readability) are still permitted
    so long as they bind to the canonical constant.
    """
    from app.services import thirteenf_quality_codes as qc
    from app.services import edgar_quality
    from app.services import thirteenf_corporate_action_mapping as corp_action
    from app.services import thirteenf_historical_backfill as backfill

    assert edgar_quality.VALUE_UNIT_SANITY_RULE_CODE == qc.VALUE_UNIT_SANITY
    assert corp_action.CORPORATE_ACTION_RULE_CODE == (
        qc.OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION
    )
    assert backfill.HISTORICAL_BACKFILL_RULE_CODE == qc.HISTORICAL_BACKFILL_NEEDS_VALIDATION


def test_canonical_module_has_no_unexpected_extras():
    """Defend against the module growing arbitrary string constants. If
    a new rule_code needs to land, it must be added here intentionally
    and this assertion updated — that's the whole point of the module.
    """
    from app.services import thirteenf_quality_codes as qc

    expected = {
        "VALUE_UNIT_SANITY",
        "OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION",
        "HISTORICAL_BACKFILL_NEEDS_VALIDATION",
    }
    actual = {
        name
        for name in dir(qc)
        if not name.startswith("_")
        and name.isupper()
        and isinstance(getattr(qc, name), str)
    }
    assert actual == expected, (
        f"thirteenf_quality_codes diverged from MVP4-09 scope. "
        f"Unexpected additions/removals: {actual.symmetric_difference(expected)}"
    )
