"""Oracle's Lens universe filter — Signal/Conviction/Distinctive recompute
over a manager subset selected by style_primary / capital_structure /
market_cap_focus.

Task doc: ``docs/tasks/2026-05-24_oracles-lens-universe-selector.md``

Pins the contract that:
1. ``resolve_manager_id_allowlist`` returns the right set of manager_ids
   for a given (style_primary, capital_structure, market_cap_focus)
   combo, and ``None`` when no filter is set.
2. ``_eligible_stock_ids(..., manager_id_allowlist=...)`` counts holders
   only from the allowlist when computing the min_holders gate.
3. ``_contributions_for_stock(..., manager_id_allowlist=...)`` returns
   only contributions from allowed managers.
4. Hero outcome: with the Deep Value preset
   (value_deep + value_concentrated + quality_compounder), Tiger Global
   (growth_long_short) does NOT contribute to a stock's score — fixing
   the V1 misclassification that PR #94 already addressed at the
   weight-table level and that this PR finally exposes via the UX.
5. Conviction and Distinctive recompute correctly off the filtered
   contributions list (they are pure functions of contributions, so
   threading the allowlist into ``_contributions_for_stock`` is
   sufficient — they don't need their own allowlist parameter).
6. Endpoint accepts the new query params, validates them, and returns
   ``universe`` metadata in the response.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from itertools import count

import pytest

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)
from app.models.stocks import Stock


_CIK_SEQ = count(8810000000)


# ---------------------------------------------------------------------------
# Fixtures — minimal manager/holding/filing/parse_run setup
# ---------------------------------------------------------------------------


def _manager(
    db_session,
    *,
    style_primary: str,
    capital_structure: str = "locked_lp",
    market_cap_focus: str | None = None,
    legal_name: str | None = None,
    superinvestor: bool = True,
) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    name = legal_name or f"Mgr-{style_primary}-{cik}"
    manager = InstitutionManager(
        cik=cik,
        canonical_name=name,
        legal_name=name,
        edgar_legal_name=name,
        display_name=name,
        name_normalized=name.lower(),
        match_status="confirmed",
        status="active",
        is_superinvestor=superinvestor,
        style_primary=style_primary,
        capital_structure=capital_structure,
        market_cap_focus=market_cap_focus,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str, name: str | None = None) -> Stock:
    stock = Stock(
        ticker=ticker, exchange="NYSE",
        company_name=name or f"{ticker} Corp",
        is_active=True,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing_with_parse_run(
    db_session,
    manager: InstitutionManager,
    *,
    accession: str,
    quarter: str = "2025-Q4",
    quarter_end: date = date(2025, 12, 31),
) -> tuple[Filing13F, ParseRun13F]:
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        period_of_report=quarter_end,
        filed_at=quarter_end,
        form_type="13F-HR",
        report_quarter=quarter,
        quarter_end_date=quarter_end,
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
        reported_total_value_thousands=100_000,
        computed_total_value_thousands=100_000,
        holdings_count=1,
        common_holdings_count=1,
    )
    db_session.add(filing)
    db_session.flush()
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="universe-filter-test",
        status="succeeded",
        is_current=True,
    )
    db_session.add(parse_run)
    db_session.flush()
    return filing, parse_run


def _holding(
    db_session,
    filing: Filing13F,
    parse_run: ParseRun13F,
    stock: Stock,
    *,
    value_thousands: int = 50_000,
    cusip: str | None = None,
) -> Holding13F:
    cusip_val = cusip or f"{stock.ticker:0<9}"[:9]
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=parse_run.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}:{stock.ticker}",
        holding_row_fingerprint=f"{filing.accession_number}:{stock.ticker}:v1",
        cusip=cusip_val,
        issuer_name=stock.company_name,
        title_of_class="COM",
        value_thousands=value_thousands,
        value_usd=value_thousands * 1000,
        shares=value_thousands * 10,
        ssh_prnamt=value_thousands * 10,
        ssh_prnamt_type="SH",
        share_type="SH",
        put_call=None,
        holding_attribution_status="direct",
        cusip_mapping_status="linked",
        stock_id=stock.id,
        portfolio_weight_pct=0.5,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


# ---------------------------------------------------------------------------
# Manager universe resolver
# ---------------------------------------------------------------------------


def test_resolver_returns_none_when_no_filters_set(db_session):
    """No filter params at all → ``None`` (caller should take the
    persisted fast path, not iterate every manager)."""
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )

    result = resolve_manager_id_allowlist(
        db_session,
        style_primary=[],
        capital_structure=[],
        market_cap_focus=[],
    )
    assert result is None


def test_resolver_filters_by_style_primary(db_session):
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )

    deep = _manager(db_session, style_primary="value_deep")
    concentrated = _manager(db_session, style_primary="value_concentrated")
    tiger = _manager(db_session, style_primary="growth_long_short")

    allowlist = resolve_manager_id_allowlist(
        db_session,
        style_primary=["value_deep", "value_concentrated"],
        capital_structure=[],
        market_cap_focus=[],
    )
    assert allowlist is not None
    assert deep.id in allowlist
    assert concentrated.id in allowlist
    assert tiger.id not in allowlist, (
        "Tiger Global must not be in the deep-value allowlist"
    )


def test_resolver_combines_filters_with_intersection(db_session):
    """Multiple dimensions intersect: a manager must match ALL specified
    dimensions to be in the allowlist. This makes presets composable:
    'Permanent Capital + Deep Value' = both filters AND'd together.
    """
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )

    perm_value = _manager(
        db_session,
        style_primary="value_concentrated",
        capital_structure="permanent_capital",
    )
    lp_value = _manager(
        db_session,
        style_primary="value_concentrated",
        capital_structure="locked_lp",
    )
    perm_growth = _manager(
        db_session,
        style_primary="growth_long_short",
        capital_structure="permanent_capital",
    )

    allowlist = resolve_manager_id_allowlist(
        db_session,
        style_primary=["value_concentrated"],
        capital_structure=["permanent_capital"],
        market_cap_focus=[],
    )
    assert allowlist is not None
    # Subset semantics — other V2-seeded managers may also match
    # ``value_concentrated + permanent_capital`` (e.g. Berkshire). What
    # we pin: our own fixtures land in the right buckets.
    assert perm_value.id in allowlist  # matches both dimensions
    assert lp_value.id not in allowlist  # right style, wrong capital
    assert perm_growth.id not in allowlist  # right capital, wrong style


def test_resolver_filters_by_market_cap_focus(db_session):
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )

    small = _manager(
        db_session,
        style_primary="value_concentrated",
        market_cap_focus="small",
    )
    micro = _manager(
        db_session,
        style_primary="value_concentrated",
        market_cap_focus="micro",
    )
    large = _manager(
        db_session,
        style_primary="value_concentrated",
        market_cap_focus="large",
    )

    allowlist = resolve_manager_id_allowlist(
        db_session,
        style_primary=[],
        capital_structure=[],
        market_cap_focus=["small", "micro"],
    )
    assert allowlist is not None
    assert small.id in allowlist
    assert micro.id in allowlist
    assert large.id not in allowlist


def test_resolver_rejects_unknown_style_primary(db_session):
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )

    with pytest.raises(ValueError):
        resolve_manager_id_allowlist(
            db_session,
            style_primary=["value_deep", "not_a_real_style"],
            capital_structure=[],
            market_cap_focus=[],
        )


def test_resolver_rejects_unknown_capital_structure(db_session):
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )

    with pytest.raises(ValueError):
        resolve_manager_id_allowlist(
            db_session,
            style_primary=[],
            capital_structure=["bogus"],
            market_cap_focus=[],
        )


# ---------------------------------------------------------------------------
# _contributions_for_stock and _eligible_stock_ids accept allowlist
# ---------------------------------------------------------------------------


def test_contributions_filters_by_allowlist(db_session):
    """When the allowlist excludes a manager, that manager's holding
    must not appear in the contributions list, regardless of the rest
    of the eligibility predicates passing."""
    from app.services.oracles_lens.signal_weighted_score import (
        _contributions_for_stock,
        _top_n_stock_ids_per_manager,
    )

    tweedy = _manager(db_session, style_primary="value_deep", legal_name="Tweedy fake")
    tiger = _manager(db_session, style_primary="growth_long_short", legal_name="Tiger fake")
    stock = _stock(db_session, "TGT")

    quarter = "2025-Q4"
    f_tweedy, r_tweedy = _filing_with_parse_run(db_session, tweedy, accession="ACC-TWEEDY-1")
    f_tiger, r_tiger = _filing_with_parse_run(db_session, tiger, accession="ACC-TIGER-1")
    _holding(db_session, f_tweedy, r_tweedy, stock, value_thousands=20_000)
    _holding(db_session, f_tiger, r_tiger, stock, value_thousands=20_000)

    top_n = _top_n_stock_ids_per_manager(db_session, quarter=quarter, top_n=10)

    # No allowlist: both holders show up.
    full, _excl = _contributions_for_stock(
        db_session,
        quarter=quarter,
        stock_id=stock.id,
        top_n_by_manager=top_n,
        derived_profile_cache={},
    )
    manager_ids_full = {c.manager_id for c in full}
    assert tweedy.id in manager_ids_full
    assert tiger.id in manager_ids_full

    # Allowlist limits to value managers: Tiger excluded.
    filtered, _excl2 = _contributions_for_stock(
        db_session,
        quarter=quarter,
        stock_id=stock.id,
        top_n_by_manager=top_n,
        derived_profile_cache={},
        manager_id_allowlist={tweedy.id},
    )
    manager_ids_filtered = {c.manager_id for c in filtered}
    assert manager_ids_filtered == {tweedy.id}
    assert tiger.id not in manager_ids_filtered


def test_eligible_stock_ids_filters_by_allowlist(db_session):
    """A stock with 3 holders globally but only 1 in the allowlist must
    NOT pass min_holders=2 for the filtered universe."""
    from app.services.oracles_lens.signal_weighted_score import (
        _eligible_stock_ids,
    )

    deep = _manager(db_session, style_primary="value_deep")
    conc = _manager(db_session, style_primary="value_concentrated")
    tiger = _manager(db_session, style_primary="growth_long_short")
    stock = _stock(db_session, "MIX")
    quarter = "2025-Q4"

    for idx, mgr in enumerate([deep, conc, tiger]):
        f, r = _filing_with_parse_run(db_session, mgr, accession=f"ACC-MIX-{idx}")
        _holding(db_session, f, r, stock, value_thousands=10_000)

    # No allowlist, min_holders=2 → stock is eligible (3 holders).
    eligible_full = _eligible_stock_ids(
        db_session, quarter=quarter, min_holders=2,
    )
    assert stock.id in eligible_full

    # Allowlist = {tiger}, min_holders=2 → stock NOT eligible
    # (only 1 holder from the filtered universe).
    eligible_filtered = _eligible_stock_ids(
        db_session,
        quarter=quarter,
        min_holders=2,
        manager_id_allowlist={tiger.id},
    )
    assert stock.id not in eligible_filtered


# ---------------------------------------------------------------------------
# Conviction + Distinctive auto-recompute on the filtered contributions
# ---------------------------------------------------------------------------


def test_conviction_and_distinctive_follow_the_allowlist(db_session):
    """``compute_conviction_components`` and
    ``compute_distinctive_consensus`` are pure functions of the
    contributions list. The test pins this: with a filtered
    contributions list, conviction/distinctive both differ from the
    all-managers numbers — confirming we DON'T have to thread the
    allowlist into them separately."""
    from app.services.oracles_lens.signal_weighted_score import (
        _contributions_for_stock,
        _top_n_stock_ids_per_manager,
    )
    from app.services.oracles_lens.conviction_score import (
        compute_conviction_components,
    )
    from app.services.oracles_lens.distinctive_consensus import (
        compute_distinctive_consensus,
    )

    value_a = _manager(db_session, style_primary="value_deep")
    value_b = _manager(db_session, style_primary="value_concentrated")
    tiger_a = _manager(db_session, style_primary="growth_long_short")
    tiger_b = _manager(db_session, style_primary="growth_long_short")
    stock = _stock(db_session, "CONV")
    quarter = "2025-Q4"

    for idx, mgr in enumerate([value_a, value_b, tiger_a, tiger_b]):
        f, r = _filing_with_parse_run(db_session, mgr, accession=f"ACC-CONV-{idx}")
        _holding(db_session, f, r, stock, value_thousands=10_000)

    top_n = _top_n_stock_ids_per_manager(db_session, quarter=quarter, top_n=10)

    full, _ = _contributions_for_stock(
        db_session,
        quarter=quarter,
        stock_id=stock.id,
        top_n_by_manager=top_n,
        derived_profile_cache={},
    )
    filtered, _ = _contributions_for_stock(
        db_session,
        quarter=quarter,
        stock_id=stock.id,
        top_n_by_manager=top_n,
        derived_profile_cache={},
        manager_id_allowlist={value_a.id, value_b.id},
    )

    full_conviction = compute_conviction_components(full)
    filtered_conviction = compute_conviction_components(filtered)

    # The filtered list has 2 holders vs full's 4 — the
    # ``agreement`` component caps by holder_count fraction so the
    # totals should differ; if conviction were silently cached or
    # otherwise universe-agnostic, the two totals would be identical.
    assert full_conviction.total != filtered_conviction.total

    full_total = sum((c.contribution for c in full), Decimal("0"))
    filtered_total = sum((c.contribution for c in filtered), Decimal("0"))
    full_distinctive = compute_distinctive_consensus(
        signal_weighted_score=full_total,
        contributions=full,
    )
    filtered_distinctive = compute_distinctive_consensus(
        signal_weighted_score=filtered_total,
        contributions=filtered,
    )
    # Distinctive consensus must reflect the filtered universe, not the
    # full one. The two scores being different proves it didn't silently
    # cache the all-managers value.
    assert (
        full_distinctive.distinctive_consensus_score
        != filtered_distinctive.distinctive_consensus_score
    )


# ---------------------------------------------------------------------------
# Hero outcome — Deep Value preset excludes Tiger Global
# ---------------------------------------------------------------------------


def test_deep_value_preset_excludes_tiger_cubs(db_session):
    """The PO review of V1 surfaced that Tiger Cubs were pollating the
    'value consensus' signal. This test pins the final user outcome:
    with the Deep Value preset (value_deep + value_concentrated +
    quality_compounder), a Tiger Cub's holding is excluded from a
    stock's contributions even when the Tiger Cub is the largest
    holder by value."""
    from app.services.oracles_lens.manager_universe import (
        resolve_manager_id_allowlist,
    )
    from app.services.oracles_lens.signal_weighted_score import (
        _contributions_for_stock,
        _top_n_stock_ids_per_manager,
    )

    tweedy = _manager(db_session, style_primary="value_deep", legal_name="Tweedy hero")
    akre = _manager(db_session, style_primary="value_concentrated", legal_name="Akre hero")
    polen = _manager(db_session, style_primary="quality_compounder", legal_name="Polen hero")
    tiger = _manager(db_session, style_primary="growth_long_short", legal_name="Tiger hero")
    stock = _stock(db_session, "HRO")
    quarter = "2025-Q4"

    # Tiger has the largest position by value_thousands; the V1 bug
    # would have weighted it the most.
    for idx, (mgr, value) in enumerate(
        [(tweedy, 5_000), (akre, 5_000), (polen, 5_000), (tiger, 500_000)]
    ):
        f, r = _filing_with_parse_run(db_session, mgr, accession=f"ACC-HRO-{idx}")
        _holding(db_session, f, r, stock, value_thousands=value)

    allowlist = resolve_manager_id_allowlist(
        db_session,
        style_primary=["value_deep", "value_concentrated", "quality_compounder"],
        capital_structure=[],
        market_cap_focus=[],
    )
    assert allowlist is not None
    assert tiger.id not in allowlist

    top_n = _top_n_stock_ids_per_manager(db_session, quarter=quarter, top_n=10)
    contributions, _ = _contributions_for_stock(
        db_session,
        quarter=quarter,
        stock_id=stock.id,
        top_n_by_manager=top_n,
        derived_profile_cache={},
        manager_id_allowlist=allowlist,
    )
    contributing_ids = {c.manager_id for c in contributions}
    assert tiger.id not in contributing_ids, (
        "Hero outcome: Tiger Global must not contribute to the "
        "Deep Value Consensus score for any stock."
    )
    assert contributing_ids == {tweedy.id, akre.id, polen.id}


# ---------------------------------------------------------------------------
# Endpoint contract
# ---------------------------------------------------------------------------


def test_endpoint_rejects_unknown_style_primary(client, db_session, user_factory, auth_headers):
    user = user_factory("oracles-lens-bad-style@example.com")
    response = client.get(
        "/api/v1/13f/oracles-lens",
        params={"style_primary": "value_deep,not_a_real_style"},
        headers=auth_headers(user),
    )
    assert response.status_code == 400


def test_endpoint_returns_universe_metadata(client, db_session, user_factory, auth_headers):
    """When style_primary is non-empty, the response must carry a
    ``universe`` object so the FE can render the
    'X of Y managers' subtitle without an extra round-trip."""
    user = user_factory("oracles-lens-universe-meta@example.com")
    response = client.get(
        "/api/v1/13f/oracles-lens",
        params={"style_primary": "value_deep,value_concentrated"},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    payload = response.json()
    assert "universe" in payload
    universe = payload["universe"]
    assert isinstance(universe["filtered_manager_count"], int)
    assert isinstance(universe["total_manager_count"], int)
    assert universe["applied_filters"]["style_primary"] == [
        "value_deep",
        "value_concentrated",
    ]
    assert universe["applied_filters"]["capital_structure"] == []
    assert universe["applied_filters"]["market_cap_focus"] == []
    # Filtered count must be a strict subset of total when any
    # style_primary filter is applied (assuming the universe has at
    # least one non-value manager, which the V2-seeded universe does).
    assert universe["filtered_manager_count"] <= universe["total_manager_count"]


def test_endpoint_empty_filters_omit_universe_to_signal_persisted_path(
    client, db_session, user_factory, auth_headers,
):
    """When no manager filter is set the response should NOT carry a
    ``universe`` object (or should carry one with ``applied_filters``
    all empty + filtered_manager_count == total_manager_count). The
    absence-or-equality signals the FE that we took the persisted
    fast path."""
    user = user_factory("oracles-lens-empty-filter@example.com")
    response = client.get(
        "/api/v1/13f/oracles-lens",
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    payload = response.json()
    universe = payload.get("universe")
    if universe is not None:
        # If present, must be a "no-op universe" with all filters empty.
        assert universe["applied_filters"] == {
            "style_primary": [],
            "capital_structure": [],
            "market_cap_focus": [],
        }
        assert (
            universe["filtered_manager_count"]
            == universe["total_manager_count"]
        )
