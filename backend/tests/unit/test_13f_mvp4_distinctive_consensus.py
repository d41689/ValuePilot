"""MVP4-06 distinctive consensus score tests (plan §7.11)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import count

from app.models.institutions import (
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.distinctive_consensus import (
    DistinctiveConsensusResult,
    compute_distinctive_consensus,
)
from app.services.oracles_lens.signal_weighted_score import (
    PositionSignalWeightResult,
    _HolderContribution,
    build_oracles_lens_response,
    compute_signal_weighted_scores,
)


_CIK_SEQ = count(9996600000)
_ACC_SEQ = count(980001)
_STOCK_SEQ = count(96001)


def _contribution(
    *,
    portfolio_weight: Decimal,
    holding_streak_quarters: int,
    manager_weight: Decimal,
    manager_id: int = 1,
) -> _HolderContribution:
    psw = PositionSignalWeightResult(
        value=portfolio_weight,
        base=portfolio_weight,
        bonus_top_10=Decimal("0"),
        bonus_weight_5pct=Decimal("0"),
        bonus_streak=Decimal("0"),
        action_adjustment=Decimal("0"),
    )
    return _HolderContribution(
        holding_id=manager_id,
        manager_id=manager_id,
        manager_canonical_type="long_term_fundamental",
        manager_type_source="admin",
        manager_weight=manager_weight,
        position_signal_weight=psw,
        contribution=manager_weight * psw.value,
        caveats=[],
        holding_streak_quarters=holding_streak_quarters,
        add_intensity=None,
    )


# ===========================================================================
# Pure function — factor caps
# ===========================================================================


def test_concentration_factor_saturates_at_10pct_aggregate_weight():
    """Three holders each at 5% portfolio weight = 15% aggregate →
    factor saturates at 1.0."""
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.05"),
            holding_streak_quarters=1,
            manager_weight=Decimal("0.6"),
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    assert result.concentration_factor == Decimal("1.0")


def test_concentration_factor_scales_below_threshold():
    """Three holders each at 1% = 3% aggregate → 0.3 factor."""
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.01"),
            holding_streak_quarters=1,
            manager_weight=Decimal("0.6"),
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    assert result.concentration_factor == Decimal("0.30")


def test_persistence_factor_saturates_at_4_quarter_median():
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.02"),
            holding_streak_quarters=streak,
            manager_weight=Decimal("0.6"),
            manager_id=i + 1,
        )
        for i, streak in enumerate([4, 4, 4])
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    assert result.persistence_factor == Decimal("1.0")


def test_persistence_factor_uses_median_not_mean():
    """One huge streak shouldn't pull a low median up."""
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.02"),
            holding_streak_quarters=streak,
            manager_weight=Decimal("0.6"),
            manager_id=i + 1,
        )
        for i, streak in enumerate([1, 1, 20])  # median = 1
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    assert result.persistence_factor == Decimal("0.25")  # 1/4


def test_quality_agreement_factor_caps_at_one_for_all_high_signal():
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.02"),
            holding_streak_quarters=1,
            manager_weight=Decimal("1.0"),  # long_term_fundamental
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    assert result.quality_agreement_factor == Decimal("1.0")


def test_quality_agreement_factor_low_for_unknown_heavy_mix():
    """All holders unknown (weight 0.60) → factor 0.60."""
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.02"),
            holding_streak_quarters=1,
            manager_weight=Decimal("0.60"),
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    assert result.quality_agreement_factor == Decimal("0.60")


# ===========================================================================
# Composite
# ===========================================================================


def test_composite_equals_signal_times_three_factors():
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.02"),
            holding_streak_quarters=2,
            manager_weight=Decimal("0.80"),
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("3.0"),
        contributions=contributions,
    )
    expected = (
        Decimal("3.0")
        * result.concentration_factor
        * result.persistence_factor
        * result.quality_agreement_factor
    )
    assert result.distinctive_consensus_score == expected


def test_high_signal_stock_distinctive_near_signal():
    """Every factor at 1.0 → distinctive == signal_weighted."""
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.05"),  # 3×5% = 15% > 10% threshold
            holding_streak_quarters=4,
            manager_weight=Decimal("1.0"),
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("4.5"),
        contributions=contributions,
    )
    assert result.distinctive_consensus_score == Decimal("4.5")


def test_low_signal_stock_distinctive_much_below_signal():
    """Tiny positions, fresh streaks, unknown managers → factors all
    small, distinctive collapses far below signal."""
    contributions = [
        _contribution(
            portfolio_weight=Decimal("0.005"),  # 3×0.5% = 1.5% aggregate → 0.15
            holding_streak_quarters=1,           # median 1 → 0.25
            manager_weight=Decimal("0.60"),      # → 0.60
            manager_id=i + 1,
        )
        for i in range(3)
    ]
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=contributions,
    )
    # 0.15 * 0.25 * 0.60 = 0.0225 → 1.0 * 0.0225 = 0.0225
    assert result.distinctive_consensus_score < Decimal("0.10")


def test_empty_contributions_returns_zero():
    result = compute_distinctive_consensus(
        signal_weighted_score=Decimal("1.0"),
        contributions=[],
    )
    assert result.distinctive_consensus_score == Decimal("0")
    assert result.concentration_factor == Decimal("0")
    assert result.persistence_factor == Decimal("0")
    assert result.quality_agreement_factor == Decimal("0")


# ===========================================================================
# DB integration
# ===========================================================================


def _manager(db_session) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-06 Mgr {cik}",
        legal_name=f"Mv4-06 Mgr {cik}",
        edgar_legal_name=f"Mv4-06 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type="long_term_fundamental",
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=f"D6{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"D6Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(db_session, manager: InstitutionManager) -> Filing13F:
    accession = f"00099660-26-{next(_ACC_SEQ):06d}"
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


def test_compute_pass_persists_distinctive_consensus_score(db_session):
    stock = _stock(db_session)
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    assert signal.distinctive_consensus_score is not None
    # Distinctive is the signal-weighted × three factors in [0, 1],
    # so distinctive ≤ signal_weighted by construction.
    assert signal.distinctive_consensus_score <= signal.signal_weighted_consensus_score


def test_compute_pass_writes_distinctive_component_rows(db_session):
    stock = _stock(db_session)
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    names = {
        c.component_name
        for c in db_session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id == signal.id)
        .all()
    }
    assert {
        "distinctive_concentration_factor",
        "distinctive_persistence_factor",
        "distinctive_quality_agreement_factor",
        "distinctive_total",
    }.issubset(names)


def test_build_oracles_lens_response_exposes_distinctive_consensus_score(db_session):
    stock = _stock(db_session)
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)
    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    payload = build_oracles_lens_response(db_session, period="2026-Q1")
    item = next((i for i in payload["items"] if i["stock_id"] == stock.id), None)
    assert item is not None
    assert item["distinctive_consensus_score"] is not None
    # API returns strings for Decimal — confirm it's numeric.
    assert float(item["distinctive_consensus_score"]) >= 0
