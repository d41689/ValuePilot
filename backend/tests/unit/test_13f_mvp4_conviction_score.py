"""MVP4-04 conviction score tests.

Plan §7.9 — V1 0-100 capped composite with five components
(position_importance/30, holding_persistence/25,
manager_quality/20, recent_action/15, agreement/10).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import count

import pytest

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.conviction_score import (
    ConvictionComponents,
    compute_conviction_components,
)
from app.services.oracles_lens.signal_weighted_score import (
    PositionSignalWeightResult,
    _HolderContribution,
    compute_signal_weighted_scores,
)


_CIK_SEQ = count(9994400000)
_ACC_SEQ = count(960001)
_STOCK_SEQ = count(94001)


def _contribution(
    *,
    portfolio_weight: Decimal,
    holding_streak_quarters: int,
    is_top_10: bool,
    manager_weight: Decimal,
    add_intensity: Decimal | None,
    holding_id: int = 1,
    manager_id: int = 1,
) -> _HolderContribution:
    """Build a _HolderContribution for pure-function tests."""
    psw = PositionSignalWeightResult(
        value=portfolio_weight,
        base=portfolio_weight,
        bonus_top_10=Decimal("0.40") if is_top_10 else Decimal("0"),
        bonus_weight_5pct=Decimal("0.30") if portfolio_weight >= Decimal("0.05") else Decimal("0"),
        bonus_streak=Decimal("0.30") if holding_streak_quarters >= 4 else Decimal("0"),
        action_adjustment=Decimal("0.10") if add_intensity is not None and add_intensity > 0 else Decimal("0"),
    )
    return _HolderContribution(
        holding_id=holding_id,
        manager_id=manager_id,
        manager_canonical_type="long_term_fundamental",
        manager_type_source="admin",
        manager_weight=manager_weight,
        position_signal_weight=psw,
        contribution=manager_weight * psw.value,
        caveats=[],
        holding_streak_quarters=holding_streak_quarters,
        add_intensity=add_intensity,
    )


# Stash the add_intensity / streak / top_10 inputs alongside the
# contribution so conviction can derive its components from them
# without re-querying.
def _setup_contributions(specs: list[dict]) -> list[_HolderContribution]:
    return [
        _contribution(
            portfolio_weight=Decimal(str(s["portfolio_weight"])),
            holding_streak_quarters=s["holding_streak_quarters"],
            is_top_10=s.get("is_top_10", False),
            manager_weight=Decimal(str(s["manager_weight"])),
            add_intensity=Decimal(str(s["add_intensity"])) if s.get("add_intensity") is not None else None,
            holding_id=s.get("holding_id", 1),
            manager_id=s.get("manager_id", 1),
        )
        for s in specs
    ]


# ===========================================================================
# Pure function tests — compute_conviction_components
# ===========================================================================


def test_empty_holders_returns_all_zeros():
    components = compute_conviction_components([])
    assert components.position_importance == 0
    assert components.holding_persistence == 0
    assert components.manager_quality == 0
    assert components.recent_action == 0
    assert components.agreement == 0
    assert components.total == 0


def test_position_importance_caps_at_30():
    """Even with max weight 50% and all holders ranking top-10, the
    component caps at 30."""
    contributions = _setup_contributions([
        {"portfolio_weight": 0.50, "holding_streak_quarters": 1, "is_top_10": True,
         "manager_weight": 0.6, "add_intensity": 0, "manager_id": 1},
        {"portfolio_weight": 0.50, "holding_streak_quarters": 1, "is_top_10": True,
         "manager_weight": 0.6, "add_intensity": 0, "manager_id": 2},
    ])
    components = compute_conviction_components(contributions)
    assert components.position_importance == 30


def test_holding_persistence_caps_at_25_at_4_quarter_median():
    """Median streak of 4 quarters → full 25 points; higher median
    stays capped."""
    contributions = _setup_contributions([
        {"portfolio_weight": 0.02, "holding_streak_quarters": 4, "manager_weight": 0.6,
         "add_intensity": 0, "manager_id": 1},
        {"portfolio_weight": 0.02, "holding_streak_quarters": 4, "manager_weight": 0.6,
         "add_intensity": 0, "manager_id": 2},
    ])
    components = compute_conviction_components(contributions)
    assert components.holding_persistence == 25


def test_holding_persistence_scales_with_median():
    """Median streak 2 → 50% of 25 = 12 or 13 (rounding)."""
    contributions = _setup_contributions([
        {"portfolio_weight": 0.02, "holding_streak_quarters": 2, "manager_weight": 0.6,
         "add_intensity": 0, "manager_id": 1},
        {"portfolio_weight": 0.02, "holding_streak_quarters": 2, "manager_weight": 0.6,
         "add_intensity": 0, "manager_id": 2},
    ])
    components = compute_conviction_components(contributions)
    # 2/4 = 0.5 → round(0.5 * 25) = 12 (banker's rounding) or 13
    assert components.holding_persistence in {12, 13}


def test_manager_quality_caps_at_20_when_all_high_signal():
    """All long_term_fundamental managers (weight 1.0) → 20 points."""
    contributions = _setup_contributions([
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 1.0,
         "add_intensity": 0, "manager_id": 1},
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 1.0,
         "add_intensity": 0, "manager_id": 2},
    ])
    components = compute_conviction_components(contributions)
    assert components.manager_quality == 20


def test_recent_action_caps_at_15_when_all_added():
    """100% of holders adding/new → 15 points."""
    contributions = _setup_contributions([
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 0.6,
         "add_intensity": 0.5, "manager_id": 1},
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 0.6,
         "add_intensity": 1.0, "manager_id": 2},
    ])
    components = compute_conviction_components(contributions)
    assert components.recent_action == 15


def test_recent_action_zero_when_all_flat_or_reducing():
    contributions = _setup_contributions([
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 0.6,
         "add_intensity": 0, "manager_id": 1},
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 0.6,
         "add_intensity": -0.3, "manager_id": 2},
    ])
    components = compute_conviction_components(contributions)
    assert components.recent_action == 0


def test_agreement_caps_at_10_at_five_holders():
    contributions = _setup_contributions([
        {"portfolio_weight": 0.02, "holding_streak_quarters": 1, "manager_weight": 0.6,
         "add_intensity": 0, "manager_id": i + 1}
        for i in range(5)
    ])
    components = compute_conviction_components(contributions)
    assert components.agreement == 10


def test_total_caps_at_100_with_maxed_inputs():
    """Every component maxed → total = 100."""
    contributions = _setup_contributions([
        {"portfolio_weight": 0.50, "holding_streak_quarters": 8, "is_top_10": True,
         "manager_weight": 1.0, "add_intensity": 1.0, "manager_id": i + 1}
        for i in range(5)
    ])
    components = compute_conviction_components(contributions)
    assert components.total == 100
    assert components.position_importance == 30
    assert components.holding_persistence == 25
    assert components.manager_quality == 20
    assert components.recent_action == 15
    assert components.agreement == 10


def test_total_is_sum_of_components():
    contributions = _setup_contributions([
        {"portfolio_weight": 0.06, "holding_streak_quarters": 3, "is_top_10": True,
         "manager_weight": 0.8, "add_intensity": 0.5, "manager_id": 1},
        {"portfolio_weight": 0.04, "holding_streak_quarters": 2, "is_top_10": False,
         "manager_weight": 0.6, "add_intensity": 0, "manager_id": 2},
        {"portfolio_weight": 0.03, "holding_streak_quarters": 5, "is_top_10": False,
         "manager_weight": 1.0, "add_intensity": -0.2, "manager_id": 3},
    ])
    components = compute_conviction_components(contributions)
    expected_total = (
        components.position_importance
        + components.holding_persistence
        + components.manager_quality
        + components.recent_action
        + components.agreement
    )
    assert components.total == expected_total


# ===========================================================================
# Integration test — written via MVP4-03 backfill pass
# ===========================================================================


def _manager(db_session, *, manager_type: str = "long_term_fundamental") -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-04 Mgr {cik}",
        legal_name=f"Mv4-04 Mgr {cik}",
        edgar_legal_name=f"Mv4-04 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"C4{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"C4Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(db_session, manager: InstitutionManager) -> Filing13F:
    accession = f"00099440-26-{next(_ACC_SEQ):06d}"
    period_end = date(2026, 3, 31)
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=period_end,
        filed_at=period_end,
        filing_date=period_end,
        accepted_at=datetime(2026, 3, 31, 17, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=period_end,
        report_quarter="2026-Q1",
        official_filing_deadline=date(2026, 5, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
        computed_total_value_thousands=1_000_000,
        reported_total_value_thousands=1_000_000,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _holding(db_session, filing: Filing13F, stock: Stock, *, value_thousands: int = 50_000) -> Holding13F:
    pr = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=1,
        is_current=True,
    )
    db_session.add(pr)
    db_session.flush()
    holding = Holding13F(
        filing_id=filing.id,
        parse_run_id=pr.id,
        manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{stock.id}",
        holding_row_fingerprint=f"{filing.accession_number}-{stock.id}",
        cusip=f"{stock.id:09d}",
        issuer_name=f"Issuer {stock.id}",
        name_of_issuer=f"Issuer {stock.id}",
        title_of_class="COM",
        value_thousands=value_thousands,
        value_raw=f"{value_thousands * 1000}",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=value_thousands * 1000,
        shares=1000,
        ssh_prnamt=1000,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=1000,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(holding)
    db_session.flush()
    return holding


def test_compute_pass_persists_conviction_score(db_session):
    stock = _stock(db_session)
    for _ in range(3):
        mgr = _manager(db_session)
        filing = _filing(db_session, mgr)
        _holding(db_session, filing, stock, value_thousands=50_000)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    assert signal.conviction_score is not None
    # In Decimal NUMERIC(18,6) — convert for comparison.
    score_int = int(signal.conviction_score)
    assert 0 <= score_int <= 100


def test_compute_pass_writes_conviction_component_rows(db_session):
    stock = _stock(db_session)
    for _ in range(3):
        mgr = _manager(db_session)
        filing = _filing(db_session, mgr)
        _holding(db_session, filing, stock, value_thousands=50_000)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    component_names = {
        c.component_name
        for c in db_session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id == signal.id)
        .all()
    }
    assert {
        "conviction_position_importance",
        "conviction_holding_persistence",
        "conviction_manager_quality",
        "conviction_recent_action",
        "conviction_agreement",
        "conviction_total",
    }.issubset(component_names)
