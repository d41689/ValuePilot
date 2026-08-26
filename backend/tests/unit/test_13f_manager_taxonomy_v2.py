"""Manager taxonomy V2 — two-layer label + multi-dimensional metadata.

Task doc: ``docs/tasks/2026-05-24_manager-taxonomy-v2.md``

These tests pin the contract that:

1. ``STYLE_PRIMARY`` covers the eight value-investor-friendly buckets and
   ``derive_legacy_manager_type(style_primary)`` is exhaustive over it.
2. The five named Tiger Cubs (Tiger Global, Lone Pine, Viking, Maverick,
   Durable) resolve to legacy ``high_turnover`` (weight 0.30) after seeding —
   the single change that fixes the worst signal-pollution case identified in
   the PO acceptance review.
3. The seed JSON ships **all 80+** confirmed superinvestors with the new
   fields populated (every entry has CIK + style_primary + capital_structure
   + classification_rationale).
4. ``seed_confirmed_managers()`` writes the new columns, derives legacy
   ``manager_type`` from ``style_primary``, and is idempotent.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.institutions import (
    CAPITAL_STRUCTURE,
    GEO_FOCUS,
    MANAGER_TYPES,
    MARKET_CAP_FOCUS,
    STYLE_PRIMARY,
    TURNOVER_BUCKETS,
    InstitutionManager,
)
from app.services.edgar_ingestion import seed_confirmed_managers
from app.services.oracles_lens.constants import MANAGER_SIGNAL_WEIGHTS
from app.services.oracles_lens.manager_style import (
    STYLE_PRIMARY_TO_LEGACY,
    derive_legacy_manager_type,
)
from scripts.seed_13f_dev_fixture import _seed_managers


SEED_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "services"
    / "seed_data"
    / "confirmed_managers.json"
)


# ---------------------------------------------------------------------------
# Enum surface
# ---------------------------------------------------------------------------


def test_style_primary_has_v2_buckets():
    # The PO-approved V2 taxonomy: eight buckets that map cleanly to a
    # value investor's mental model. ``unknown`` is the safe default for
    # rows seeded without a classification (e.g. Dataroma bootstrap of
    # newly discovered managers).
    assert STYLE_PRIMARY == {
        "value_deep",
        "value_concentrated",
        "quality_compounder",
        "activist",
        "growth_long_short",
        "special_situations",
        "multi_strategy_macro",
        "endowment_passive",
        "unknown",
    }


def test_capital_structure_has_v2_buckets():
    assert CAPITAL_STRUCTURE == {
        "permanent_capital",
        "locked_lp",
        "standard_lp",
        "mutual_fund_etf",
        "endowment_foundation",
        "unknown",
    }


def test_market_cap_focus_buckets():
    assert MARKET_CAP_FOCUS == {"micro", "small", "mid", "large", "mega", "all"}


def test_geo_focus_buckets():
    assert GEO_FOCUS == {"us", "global", "em", "europe", "asia"}


def test_turnover_buckets():
    assert TURNOVER_BUCKETS == {"low", "med", "high"}


# ---------------------------------------------------------------------------
# Style → legacy manager_type derivation (the heart of the change)
# ---------------------------------------------------------------------------


def test_style_to_legacy_mapping_is_exhaustive_over_style_primary():
    # Every value in STYLE_PRIMARY must have a legacy mapping. A missing
    # entry would produce an unknown-weighted score silently, which is
    # exactly the failure mode the V1 taxonomy already had.
    assert set(STYLE_PRIMARY_TO_LEGACY.keys()) == STYLE_PRIMARY


def test_style_to_legacy_targets_are_canonical_manager_types():
    # Every right-hand side must be a value that ``MANAGER_TYPES``
    # accepts, otherwise the model's ``@validates`` will reject seeds.
    for style, legacy in STYLE_PRIMARY_TO_LEGACY.items():
        assert legacy in MANAGER_TYPES, f"{style} maps to non-canonical {legacy}"


def test_derive_legacy_manager_type_tiger_cubs_become_high_turnover():
    """The hero assertion: Tiger Cubs no longer ride the 1.00 weight.

    Tiger Global / Lone Pine / Viking / Maverick / Durable are all
    classified ``growth_long_short`` in the seed. Their derived legacy
    manager_type must be ``high_turnover`` (weight 0.30) — *not*
    ``long_term_fundamental`` (weight 1.00).
    """
    legacy = derive_legacy_manager_type("growth_long_short")
    assert legacy == "high_turnover"
    assert MANAGER_SIGNAL_WEIGHTS[legacy] == Decimal("0.30")


def test_derive_legacy_manager_type_activist_stays_activist():
    # Bill Ackman, Trian, ValueAct, TCI, Engaged, Icahn, Third Point.
    assert derive_legacy_manager_type("activist") == "activist"


def test_derive_legacy_manager_type_endowment_passive_low_weight():
    # Gates Foundation Trust holds what was donated; its "trades" are
    # gifting timing, not investment views. Legacy mapping is
    # ``index_like`` (weight 0.10) so its signals don't dominate.
    legacy = derive_legacy_manager_type("endowment_passive")
    assert legacy == "index_like"
    assert MANAGER_SIGNAL_WEIGHTS[legacy] == Decimal("0.10")


def test_derive_legacy_manager_type_value_buckets_keep_full_weight():
    # Both ``value_deep`` (Tweedy/Southeastern/Yacktman/Kahn) and
    # ``value_concentrated`` (Baupost/Akre/Pabrai/Greenlight) keep the
    # 1.00 weight — they are the canonical value-investor signal.
    for style in ("value_deep", "value_concentrated", "quality_compounder"):
        legacy = derive_legacy_manager_type(style)
        assert MANAGER_SIGNAL_WEIGHTS[legacy] == Decimal("1.00"), style


def test_derive_legacy_manager_type_unknown_passthrough():
    assert derive_legacy_manager_type("unknown") == "unknown"


def test_derive_legacy_manager_type_rejects_garbage():
    with pytest.raises(ValueError):
        derive_legacy_manager_type("not_a_style")


def test_dev_fixture_seeds_value_investor_v2_metadata(db_session):
    """The visual-acceptance fixture must populate the product taxonomy.

    Legacy ``manager_type`` remains deliberately exhaustive so the scoring
    fixture still exercises all eight weight branches. The consumer product,
    however, filters on V2 ``style_primary`` and would otherwise render an
    empty default manager universe.
    """
    managers = _seed_managers(db_session)

    assert len(managers) == 32
    assert {manager.manager_type for manager in managers} == MANAGER_TYPES
    assert all(manager.capital_structure != "unknown" for manager in managers)
    assert all(manager.historical_turnover in TURNOVER_BUCKETS for manager in managers)

    value_styles = {"value_deep", "value_concentrated", "quality_compounder"}
    value_managers = [
        manager for manager in managers if manager.style_primary in value_styles
    ]
    assert len(value_managers) == 8
    assert {manager.style_primary for manager in value_managers} == value_styles

    noisy_types = {"quant", "high_turnover", "index_like", "multi_strategy"}
    assert all(
        manager.style_primary not in value_styles
        for manager in managers
        if manager.manager_type in noisy_types
    )

    # Re-running updates fixture-owned metadata without duplicating managers.
    managers[0].style_primary = "unknown"
    rerun = _seed_managers(db_session)
    assert len(rerun) == 32
    assert rerun[0].style_primary == "quality_compounder"
    assert db_session.query(InstitutionManager).filter(
        InstitutionManager.canonical_name.like("DEVSEED %")
    ).count() == 32


# ---------------------------------------------------------------------------
# Seed JSON contract
# ---------------------------------------------------------------------------


def _seed_entries() -> list[dict]:
    with open(SEED_PATH, "r") as f:
        return json.load(f)


def test_seed_json_ships_full_universe():
    # PO directive: seed all 80+ confirmed superinvestors, not just the 20
    # priority entries that exist today. We require at least 80 to leave
    # headroom for a couple of late additions without making the threshold
    # brittle.
    entries = _seed_entries()
    assert len(entries) >= 80, f"only {len(entries)} entries — must be >= 80"


def test_seed_json_every_entry_has_required_v2_fields():
    entries = _seed_entries()
    missing: list[str] = []
    for entry in entries:
        name = entry.get("display_name") or entry.get("legal_name") or "<unnamed>"
        for required_field in (
            "cik",
            "legal_name",
            "display_name",
            "style_primary",
            "capital_structure",
            "classification_rationale",
        ):
            if not entry.get(required_field):
                missing.append(f"{name}: {required_field}")
    assert not missing, "Seed entries missing required V2 fields: " + "; ".join(missing)


def test_seed_json_classifications_use_canonical_vocabularies():
    entries = _seed_entries()
    for entry in entries:
        name = entry.get("display_name") or entry.get("legal_name")
        assert entry["style_primary"] in STYLE_PRIMARY, (
            f"{name}: bad style_primary={entry['style_primary']}"
        )
        assert entry["capital_structure"] in CAPITAL_STRUCTURE, (
            f"{name}: bad capital_structure={entry['capital_structure']}"
        )
        if entry.get("market_cap_focus"):
            assert entry["market_cap_focus"] in MARKET_CAP_FOCUS, (
                f"{name}: bad market_cap_focus={entry['market_cap_focus']}"
            )
        if entry.get("geo_focus"):
            assert entry["geo_focus"] in GEO_FOCUS, (
                f"{name}: bad geo_focus={entry['geo_focus']}"
            )
        if entry.get("historical_turnover"):
            assert entry["historical_turnover"] in TURNOVER_BUCKETS, (
                f"{name}: bad historical_turnover={entry['historical_turnover']}"
            )


def test_seed_json_named_tiger_cubs_are_growth_long_short():
    """The five Tiger Cubs identified in the PO review must ship classified
    correctly. Hard-coded by CIK so a typo in display_name doesn't silently
    drop a manager out of the assertion.
    """
    cik_to_expected = {
        "0001167483": "Tiger Global",           # TIGER GLOBAL MANAGEMENT LLC
        "0001061165": "Lone Pine",              # LONE PINE CAPITAL LLC
        "0001103804": "Viking Global",          # VIKING GLOBAL INVESTORS LP
        "0000934639": "Maverick Capital",       # MAVERICK CAPITAL LTD
        "0001798849": "Durable Capital",        # Durable Capital Partners LP
    }
    by_cik = {e["cik"]: e for e in _seed_entries()}
    for cik, label in cik_to_expected.items():
        assert cik in by_cik, f"{label} (CIK {cik}) missing from seed"
        assert by_cik[cik]["style_primary"] == "growth_long_short", (
            f"{label} should be growth_long_short, got {by_cik[cik]['style_primary']}"
        )


def test_seed_json_tci_is_activist():
    by_cik = {e["cik"]: e for e in _seed_entries()}
    assert by_cik["0001647251"]["style_primary"] == "activist", (
        "TCI Fund Management should be activist (Chris Hohn runs concentrated "
        "activist positions in Visa/Charter/Moody's)"
    )


def test_seed_json_berkshire_is_value_concentrated():
    by_cik = {e["cik"]: e for e in _seed_entries()}
    assert by_cik["0001067983"]["style_primary"] == "value_concentrated", (
        "Berkshire Hathaway should be value_concentrated (Top 10 ≈ 80% of "
        "the equity book)"
    )


def test_seed_json_gates_foundation_is_endowment_passive():
    by_cik = {e["cik"]: e for e in _seed_entries()}
    assert by_cik["0001166559"]["style_primary"] == "endowment_passive", (
        "Gates Foundation Trust holds donations; mapping to endowment_passive "
        "→ index_like (weight 0.10) keeps it from polluting the signal"
    )


# ---------------------------------------------------------------------------
# seed_confirmed_managers() writes the new columns
# ---------------------------------------------------------------------------


def test_seed_confirmed_managers_populates_v2_columns(db_session):
    # Run the seeding code against the fixture-rolled-back session.
    # M1: seeding returns a diff report now, not a bare count — a deploy-time
    # re-seed must be able to show what it did, and what it refused to do.
    report = seed_confirmed_managers(db_session)
    assert report["created"] >= 80, f"expected to seed >= 80, got {report}"
    db_session.flush()

    # Spot-check a Tiger Cub: legacy manager_type must be derived from
    # style_primary, not left at the default ``unknown``.
    tiger = (
        db_session.query(InstitutionManager)
        .filter_by(cik="0001167483")  # Tiger Global
        .one()
    )
    assert tiger.style_primary == "growth_long_short"
    assert tiger.manager_type == "high_turnover", (
        f"Tiger Global legacy manager_type should be derived to high_turnover, "
        f"got {tiger.manager_type}"
    )

    # Spot-check Berkshire: value_concentrated → legacy stays value_concentrated.
    brk = (
        db_session.query(InstitutionManager)
        .filter_by(cik="0001067983")
        .one()
    )
    assert brk.style_primary == "value_concentrated"
    assert brk.capital_structure == "permanent_capital"
    assert brk.manager_type == "value_concentrated"

    # Spot-check Gates Foundation: endowment_passive → index_like.
    gates = (
        db_session.query(InstitutionManager)
        .filter_by(cik="0001166559")
        .one()
    )
    assert gates.style_primary == "endowment_passive"
    assert gates.manager_type == "index_like"


def test_seed_confirmed_managers_is_idempotent(db_session):
    # First seed.
    seed_confirmed_managers(db_session)
    db_session.flush()
    count_after_first = (
        db_session.query(InstitutionManager).filter_by(match_status="confirmed").count()
    )

    # Re-run; row count must not grow.
    seed_confirmed_managers(db_session)
    db_session.flush()
    count_after_second = (
        db_session.query(InstitutionManager).filter_by(match_status="confirmed").count()
    )
    assert count_after_first == count_after_second, (
        f"seed_confirmed_managers is not idempotent: {count_after_first} → "
        f"{count_after_second}"
    )


def test_seed_confirmed_managers_populates_metadata_when_present(db_session):
    seed_confirmed_managers(db_session)
    db_session.flush()

    # Punch Card Management is our small-cap value sleuth — it should
    # have market_cap_focus and ideology_tags populated.
    punch_card = (
        db_session.query(InstitutionManager)
        .filter_by(cik="0001631664")
        .one_or_none()
    )
    assert punch_card is not None, "Punch Card Management missing from seed"
    # Either small or micro is acceptable for Punch Card's bucket.
    assert punch_card.market_cap_focus in {"small", "micro"}, (
        f"Punch Card market_cap_focus={punch_card.market_cap_focus}"
    )
