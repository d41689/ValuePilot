"""MVP4-03 signal-weighted consensus score tests.

Plan §7.2 primary ranking metric. Mixes pure-function tests for the
position-signal-weight math + caveat → confidence demotion with
DB-integration tests for the end-to-end compute / persist / read
path.
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
    JobRun,
    ParseRun13F,
)
from app.models.oracles_lens import OraclesLensScoreComponent, OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.base_primitives import (
    HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT,
    NT_QUARTER_STREAK_BREAK_CAVEAT,
    PARTIAL_COVERAGE_CAVEAT,
    PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT,
    STALE_UNTIL_RECOMPUTE_CAVEAT,
)
from app.services.oracles_lens.signal_weighted_score import (
    SignalWeightedBackfillError,
    compute_position_signal_weight,
    compute_signal_weighted_scores,
    determine_score_confidence,
    enqueue_signal_weighted_backfill,
    execute_signal_weighted_backfill,
)


_CIK_SEQ = count(9992200000)
_ACC_SEQ = count(900001)
_STOCK_SEQ = count(91001)


# ===========================================================================
# Pure function tests — compute_position_signal_weight (plan §7.2)
# ===========================================================================


def test_position_signal_weight_base_only():
    """No bonuses, no action adjustment → returns just the
    portfolio_weight base."""
    result = compute_position_signal_weight(
        portfolio_weight=Decimal("0.03"),
        holding_streak_quarters=1,
        is_top_10=False,
        add_intensity=None,
        caveats=[],
    )
    assert result.value == Decimal("0.03")
    assert result.bonus_top_10 == Decimal("0")
    assert result.bonus_weight_5pct == Decimal("0")
    assert result.bonus_streak == Decimal("0")
    assert result.action_adjustment == Decimal("0")


def test_position_signal_weight_top_10_bonus():
    result = compute_position_signal_weight(
        portfolio_weight=Decimal("0.03"),
        holding_streak_quarters=1,
        is_top_10=True,
        add_intensity=None,
        caveats=[],
    )
    assert result.bonus_top_10 == Decimal("0.40")
    assert result.value == Decimal("0.43")


def test_position_signal_weight_5pct_threshold_inclusive():
    """Bonus fires at exactly 0.05, not at 0.0499."""
    above = compute_position_signal_weight(
        portfolio_weight=Decimal("0.05"),
        holding_streak_quarters=1,
        is_top_10=False,
        add_intensity=None,
        caveats=[],
    )
    below = compute_position_signal_weight(
        portfolio_weight=Decimal("0.0499"),
        holding_streak_quarters=1,
        is_top_10=False,
        add_intensity=None,
        caveats=[],
    )
    assert above.bonus_weight_5pct == Decimal("0.30")
    assert below.bonus_weight_5pct == Decimal("0")


def test_position_signal_weight_streak_threshold_inclusive():
    """Bonus fires at streak >= 4, not at streak == 3."""
    at_4 = compute_position_signal_weight(
        portfolio_weight=Decimal("0.01"),
        holding_streak_quarters=4,
        is_top_10=False,
        add_intensity=None,
        caveats=[],
    )
    at_3 = compute_position_signal_weight(
        portfolio_weight=Decimal("0.01"),
        holding_streak_quarters=3,
        is_top_10=False,
        add_intensity=None,
        caveats=[],
    )
    assert at_4.bonus_streak == Decimal("0.30")
    assert at_3.bonus_streak == Decimal("0")


def test_position_signal_weight_action_adjustments():
    """V1 calibration on add_intensity: new/add/reduce/exit."""

    def adj(value):
        return compute_position_signal_weight(
            portfolio_weight=Decimal("0.01"),
            holding_streak_quarters=1,
            is_top_10=False,
            add_intensity=value,
            caveats=[],
        ).action_adjustment

    assert adj(Decimal("1.0")) == Decimal("0.20")       # new position
    assert adj(Decimal("0.5")) == Decimal("0.10")        # added
    assert adj(Decimal("0.0")) == Decimal("0")            # unchanged
    assert adj(None) == Decimal("0")                       # no signal
    assert adj(Decimal("-0.5")) == Decimal("-0.10")      # reduced
    assert adj(Decimal("-1.0")) == Decimal("-0.20")      # exit


def test_position_signal_weight_stale_caveat_zeros_action():
    """D3 rule (b)/(e): when the underlying delta cannot be trusted,
    the action_adjustment is clamped to 0 regardless of add_intensity
    magnitude. Bonuses still fire from the other inputs."""
    stale = compute_position_signal_weight(
        portfolio_weight=Decimal("0.06"),
        holding_streak_quarters=5,
        is_top_10=True,
        add_intensity=Decimal("1.0"),  # would be +0.20 without caveat
        caveats=[STALE_UNTIL_RECOMPUTE_CAVEAT],
    )
    assert stale.action_adjustment == Decimal("0")
    # base 0.06 + top_10 0.40 + 5pct 0.30 + streak 0.30 + action 0
    assert stale.value == Decimal("1.06")


# ===========================================================================
# Pure function tests — determine_score_confidence
# ===========================================================================


def test_confidence_high_when_no_caveats():
    assert determine_score_confidence([]) == "high_confidence"


def test_confidence_medium_for_partial_or_confidential_or_nt_or_pre_2023():
    for caveat in (
        PARTIAL_COVERAGE_CAVEAT,
        NT_QUARTER_STREAK_BREAK_CAVEAT,
        PRE_2023_PRE_HISTORY_UNAVAILABLE_CAVEAT,
    ):
        assert determine_score_confidence([caveat]) == "medium_confidence", caveat


def test_confidence_low_for_stale_or_backfill_validation():
    assert determine_score_confidence(
        [STALE_UNTIL_RECOMPUTE_CAVEAT]
    ) == "low_confidence"
    assert determine_score_confidence(
        [HISTORICAL_BACKFILL_NEEDS_VALIDATION_CAVEAT]
    ) == "low_confidence"


def test_confidence_worst_caveat_wins():
    """Mix of medium-tier and low-tier caveats → low wins."""
    mixed = [
        PARTIAL_COVERAGE_CAVEAT,
        STALE_UNTIL_RECOMPUTE_CAVEAT,
        NT_QUARTER_STREAK_BREAK_CAVEAT,
    ]
    assert determine_score_confidence(mixed) == "low_confidence"


# ===========================================================================
# DB integration tests — compute_signal_weighted_scores
# ===========================================================================


def _manager(db_session, *, manager_type: str = "long_term_fundamental") -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv4-03 Mgr {cik}",
        legal_name=f"Mv4-03 Mgr {cik}",
        edgar_legal_name=f"Mv4-03 Mgr {cik}",
        cik=cik,
        status="active",
        match_status="confirmed",
        manager_type=manager_type,
    )
    db_session.add(manager)
    db_session.flush()
    return manager


def _stock(db_session, ticker: str | None = None) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=ticker or f"S4{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"S4Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    quarter: str = "2026-Q1",
    computed_total: int | None = 1_000_000,
    coverage_completeness: str = "complete",
) -> Filing13F:
    accession = f"00099220-26-{next(_ACC_SEQ):06d}"
    year_str, qtr_str = quarter.split("-Q")
    period_end_month = int(qtr_str) * 3
    last_day = 31 if period_end_month in (1, 3, 5, 7, 8, 10, 12) else 30
    period_end = date(int(year_str), period_end_month, last_day)
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=period_end,
        filed_at=period_end,
        filing_date=period_end,
        accepted_at=datetime(period_end.year, period_end.month, period_end.day, 17, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness=coverage_completeness,
        coverage_type="normal",
        quarter_end_date=period_end,
        report_quarter=quarter,
        official_filing_deadline=date(period_end.year, period_end.month, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
        computed_total_value_thousands=computed_total,
        reported_total_value_thousands=computed_total,
    )
    db_session.add(filing)
    db_session.flush()
    return filing


def _current_parse_run(db_session, filing: Filing13F) -> ParseRun13F:
    parse_run = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=0,
        is_current=True,
    )
    db_session.add(parse_run)
    db_session.flush()
    return parse_run


def _holding(
    db_session,
    filing: Filing13F,
    stock: Stock,
    *,
    parse_run: ParseRun13F | None = None,
    value_thousands: int = 50_000,
    shares: int = 1000,
) -> Holding13F:
    pr = parse_run or _current_parse_run(db_session, filing)
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
        shares=shares,
        ssh_prnamt=shares,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(holding)
    db_session.flush()
    pr.holdings_count = (pr.holdings_count or 0) + 1
    return holding


def _setup_n_holders(db_session, *, n: int, quarter: str = "2026-Q1") -> tuple[Stock, list[InstitutionManager]]:
    """Seed N managers each holding the same stock in the given quarter."""
    stock = _stock(db_session)
    managers: list[InstitutionManager] = []
    for _ in range(n):
        mgr = _manager(db_session)
        filing = _filing(db_session, mgr, quarter=quarter)
        _holding(db_session, filing, stock, value_thousands=50_000)
        managers.append(mgr)
    return stock, managers


def test_eligibility_two_holders_not_scored(db_session):
    """Plan §7.1: consensus_count >= 3 is required."""
    _setup_n_holders(db_session, n=2, quarter="2026-Q1")

    result = compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    # No oracles_lens_signals row should be written for any
    # below-threshold stock.
    assert result["filings_scored"] == 0


def test_eligibility_three_holders_produces_score(db_session):
    stock, managers = _setup_n_holders(db_session, n=3, quarter="2026-Q1")

    result = compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    assert result["filings_scored"] >= 1
    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .filter(OraclesLensSignal.report_quarter == "2026-Q1")
        .one()
    )
    assert signal.raw_consensus_count == 3
    assert signal.signal_weighted_consensus_score is not None
    assert signal.score_confidence in {
        "high_confidence",
        "medium_confidence",
        "low_confidence",
    }


def test_upsert_idempotence(db_session):
    """Re-running compute for the same (stock, quarter, version) must
    overwrite existing row in place, not duplicate."""
    stock, _ = _setup_n_holders(db_session, n=3, quarter="2026-Q1")

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")
    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    rows = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .filter(OraclesLensSignal.report_quarter == "2026-Q1")
        .all()
    )
    assert len(rows) == 1, "upsert must not duplicate per (stock, quarter, version)"


def test_partial_coverage_demotes_confidence_to_medium(db_session):
    stock = _stock(db_session)
    managers = []
    for index in range(3):
        mgr = _manager(db_session)
        # One holder is a partial-coverage Combination Report filer;
        # the others are complete.
        coverage = "partial" if index == 0 else "complete"
        filing = _filing(
            db_session, mgr, quarter="2026-Q1", coverage_completeness=coverage,
        )
        _holding(db_session, filing, stock, value_thousands=50_000)
        managers.append(mgr)

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    assert signal.score_confidence == "medium_confidence"
    assert PARTIAL_COVERAGE_CAVEAT in (signal.caution_flag_codes or [])


def test_score_components_persisted(db_session):
    stock, managers = _setup_n_holders(db_session, n=3, quarter="2026-Q1")

    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )
    components = (
        db_session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id == signal.id)
        .all()
    )
    # At least one manager_signal_weight component row per holder.
    by_kind = {c.component_name for c in components}
    assert "manager_signal_weight" in by_kind
    assert "position_signal_weight" in by_kind


def test_multiple_holdings_per_manager_stock_are_aggregated(db_session):
    """13F filers can legitimately emit several SOLE-discretion InfoTable
    rows for the same security (e.g. one slice co-attributed via
    ``otherManagers``, another solely the filer's). The scoring service
    must aggregate them into one (manager, stock) contribution, both to
    reflect the manager's true exposure AND so the unique constraint
    ``uq_oracles_lens_score_components_per_score_component_manager`` is
    respected.
    """
    stock = _stock(db_session)
    quarter = "2026-Q1"

    # Manager A — TWO holdings for the same stock in the same filing.
    mgr_a = _manager(db_session)
    filing_a = _filing(db_session, mgr_a, quarter=quarter)
    pr_a = _current_parse_run(db_session, filing_a)
    holding_a1 = _holding(
        db_session, filing_a, stock, parse_run=pr_a, value_thousands=40_000,
    )
    # Second slice — different source_row_index keeps fingerprints
    # distinct (mirrors ingestion behavior).
    holding_a2 = Holding13F(
        filing_id=filing_a.id,
        parse_run_id=pr_a.id,
        manager_id=filing_a.manager_id,
        accession_number=filing_a.accession_number,
        report_quarter=filing_a.report_quarter,
        quarter_end_date=filing_a.quarter_end_date,
        row_fingerprint=f"{filing_a.accession_number}-{stock.id}-2",
        holding_row_fingerprint=f"{filing_a.accession_number}-{stock.id}-2",
        cusip=holding_a1.cusip,
        issuer_name=holding_a1.issuer_name,
        name_of_issuer=holding_a1.name_of_issuer,
        title_of_class="COM",
        value_thousands=10_000,
        value_raw="10000000",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=10_000 * 1000,
        shares=200,
        ssh_prnamt=200,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=200,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=1,
        other_managers_raw="1",
    )
    db_session.add(holding_a2)
    db_session.flush()
    pr_a.holdings_count = (pr_a.holdings_count or 0) + 1

    # Two additional holders for the same stock to clear min_holders >= 3.
    for _ in range(2):
        mgr = _manager(db_session)
        filing = _filing(db_session, mgr, quarter=quarter)
        _holding(db_session, filing, stock, value_thousands=50_000)

    # Must not raise (previously violated the unique constraint).
    result = compute_signal_weighted_scores(db_session, quarter=quarter)
    assert result["filings_scored"] >= 1

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .filter(OraclesLensSignal.report_quarter == quarter)
        .one()
    )

    # Exactly one manager_signal_weight + one position_signal_weight per
    # manager — duplicates would violate the unique constraint and the
    # raw row count would balloon to 4 for manager_a alone.
    mgr_a_rows = (
        db_session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id == signal.id)
        .filter(OraclesLensScoreComponent.manager_id == mgr_a.id)
        .filter(
            OraclesLensScoreComponent.component_name.in_(
                ["manager_signal_weight", "position_signal_weight"]
            )
        )
        .all()
    )
    by_kind = {c.component_name: c for c in mgr_a_rows}
    assert set(by_kind) == {"manager_signal_weight", "position_signal_weight"}, (
        f"expected one of each component per manager; got {[c.component_name for c in mgr_a_rows]}"
    )

    # raw_consensus_count counts unique holders (3), not raw rows (4).
    assert signal.raw_consensus_count == 3


def test_option_holdings_excluded_from_scoring_eligibility(db_session):
    """13F-HR filers occasionally report options under the underlying's
    CUSIP with ``put_call`` set (e.g. Third Point KVUE Call). Without an
    explicit filter these enter ``_contributions_for_stock`` because they
    pass ``cusip_mapping_status='linked'`` + ``holding_attribution_status
    ='direct'`` and inflate the common-stock signal with option-notional
    exposure. The scorer must exclude any row with ``put_call IS NOT
    NULL`` across all four eligibility paths.
    """
    stock = _stock(db_session)
    quarter = "2026-Q1"

    # Three managers with plain common holdings — clears min_holders >= 3.
    common_managers = []
    for _ in range(3):
        mgr = _manager(db_session)
        common_managers.append(mgr)
        _holding(db_session, _filing(db_session, mgr, quarter=quarter), stock,
                 value_thousands=50_000)

    # A fourth manager holds ONLY a Call option on the same stock — must
    # not contribute to the signal and must not push raw_consensus_count
    # above 3.
    option_mgr = _manager(db_session)
    option_filing = _filing(db_session, option_mgr, quarter=quarter)
    pr_opt = _current_parse_run(db_session, option_filing)
    option_holding = Holding13F(
        filing_id=option_filing.id,
        parse_run_id=pr_opt.id,
        manager_id=option_filing.manager_id,
        accession_number=option_filing.accession_number,
        report_quarter=option_filing.report_quarter,
        quarter_end_date=option_filing.quarter_end_date,
        row_fingerprint=f"{option_filing.accession_number}-{stock.id}-opt",
        holding_row_fingerprint=f"{option_filing.accession_number}-{stock.id}-opt",
        cusip=f"{stock.id:09d}",
        issuer_name=f"Issuer {stock.id}",
        name_of_issuer=f"Issuer {stock.id}",
        title_of_class="COM",
        put_call="Call",
        value_thousands=999_999,
        value_raw=f"{999_999 * 1000}",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=999_999 * 1000,
        shares=10_000,
        ssh_prnamt=10_000,
        share_type="SH",
        ssh_prnamt_type="SH",
        investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=10_000,
        voting_shared=0,
        voting_none=0,
        stock_id=stock.id,
        cusip_mapping_status="linked",
        source_row_index=0,
    )
    db_session.add(option_holding)
    db_session.flush()
    pr_opt.holdings_count = (pr_opt.holdings_count or 0) + 1

    compute_signal_weighted_scores(db_session, quarter=quarter)

    signal = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .filter(OraclesLensSignal.report_quarter == quarter)
        .one()
    )
    # Exactly 3 common-stock holders — option manager must be excluded.
    assert signal.raw_consensus_count == 3

    # No score component should reference the option-only manager.
    option_mgr_rows = (
        db_session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id == signal.id)
        .filter(OraclesLensScoreComponent.manager_id == option_mgr.id)
        .all()
    )
    assert option_mgr_rows == [], (
        f"option-only holder must not contribute components; got {option_mgr_rows!r}"
    )


def test_top_n_aggregates_multi_row_cusips_before_ranking(db_session):
    """The ``top_n_by_manager`` lookup used for the ``bonus_top_10``
    flag must aggregate value_thousands per (manager, stock) before
    ranking. Without aggregation, a duplicate-row CUSIP would consume
    two ranked slots and evict a stock that should occupy the Nth slot
    after collapse, silently mis-applying the top-10 bonus.
    """
    from app.services.oracles_lens.signal_weighted_score import (
        _top_n_stock_ids_per_manager,
    )

    quarter = "2026-Q1"
    mgr = _manager(db_session)
    filing = _filing(db_session, mgr, quarter=quarter)
    pr = _current_parse_run(db_session, filing)

    # Stock A: 2 rows (10_000 + 9_000 = 19_000 aggregated → rank #1)
    stock_a = _stock(db_session)
    _holding(db_session, filing, stock_a, parse_run=pr, value_thousands=10_000)
    holding_a2 = Holding13F(
        filing_id=filing.id, parse_run_id=pr.id, manager_id=filing.manager_id,
        accession_number=filing.accession_number,
        report_quarter=filing.report_quarter,
        quarter_end_date=filing.quarter_end_date,
        row_fingerprint=f"{filing.accession_number}-{stock_a.id}-2",
        holding_row_fingerprint=f"{filing.accession_number}-{stock_a.id}-2",
        cusip=f"{stock_a.id:09d}", issuer_name="x", name_of_issuer="x",
        title_of_class="COM", value_thousands=9_000, value_raw="9000000",
        value_unit_raw="dollars", value_parse_rule="schema_dollars",
        value_usd=9_000_000, shares=200, ssh_prnamt=200, share_type="SH",
        ssh_prnamt_type="SH", investment_discretion="SOLE",
        holding_attribution_status="direct",
        voting_sole=200, voting_shared=0, voting_none=0,
        stock_id=stock_a.id, cusip_mapping_status="linked", source_row_index=1,
    )
    db_session.add(holding_a2)
    db_session.flush()

    # Single-row stocks B (8_000), C (7_000), D (6_000).
    stock_b = _stock(db_session)
    _holding(db_session, filing, stock_b, parse_run=pr, value_thousands=8_000)
    stock_c = _stock(db_session)
    _holding(db_session, filing, stock_c, parse_run=pr, value_thousands=7_000)
    stock_d = _stock(db_session)
    _holding(db_session, filing, stock_d, parse_run=pr, value_thousands=6_000)

    # top_n=3 — without aggregation, set-collapse on stock_a's two rows
    # would yield {stock_a, stock_b} (stock_c never selected); with
    # aggregation, the result is the true top-3 by aggregated value.
    top = _top_n_stock_ids_per_manager(db_session, quarter=quarter, top_n=3)
    assert top[mgr.id] == {stock_a.id, stock_b.id, stock_c.id}


# ===========================================================================
# JobRun orchestration
# ===========================================================================


def test_enqueue_creates_jobrun_with_lock_key(db_session):
    job = enqueue_signal_weighted_backfill(
        db_session, quarter="2026-Q1", score_version="v1.0",
    )
    assert job.job_type == "oracles_lens_score_backfill"
    assert job.lock_key == "oracles_lens_score:2026-Q1:v1.0"
    assert job.dedupe_key == job.lock_key
    assert job.status == "queued"


def test_enqueue_duplicate_active_rejected(db_session):
    enqueue_signal_weighted_backfill(db_session, quarter="2026-Q1")
    with pytest.raises(SignalWeightedBackfillError, match="already active"):
        enqueue_signal_weighted_backfill(db_session, quarter="2026-Q1")


def test_execute_marks_job_succeeded_and_returns_impact_summary(db_session):
    _setup_n_holders(db_session, n=3, quarter="2026-Q1")
    job = enqueue_signal_weighted_backfill(db_session, quarter="2026-Q1")

    result = execute_signal_weighted_backfill(db_session, job_run_id=job.id)

    refreshed = db_session.get(JobRun, job.id)
    assert refreshed.status == "succeeded"
    assert result["status"] == "succeeded"
    assert result["impact_summary"]["filings_scored"] >= 1


# ===========================================================================
# build_oracles_lens_response — the future HTTP-endpoint read helper.
# The /api/v1/13f/oracles-lens endpoint itself is already implemented
# by app/services/oracles_lens/dashboard.py (in-memory compute).
# Wiring this persisted-table read into that endpoint is a separate
# follow-up; here we just pin the read helper's shape.
# ===========================================================================


def test_build_oracles_lens_response_returns_ranked_list(db_session):
    from app.services.oracles_lens.signal_weighted_score import (
        build_oracles_lens_response,
    )

    _setup_n_holders(db_session, n=3, quarter="2026-Q1")
    compute_signal_weighted_scores(db_session, quarter="2026-Q1")

    payload = build_oracles_lens_response(db_session, period="2026-Q1")

    assert payload["period"] == "2026-Q1"
    assert payload["score_version"] == "v1.0"
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) >= 1
    first = payload["items"][0]
    assert {
        "stock_id",
        "ticker",
        "company_name",
        "consensus_count",
        "signal_weighted_consensus_score",
        "score_confidence",
        "caution_flag_codes",
        "score_explanation",
    }.issubset(first.keys())


def test_build_oracles_lens_response_empty_quarter_returns_empty_list(db_session):
    from app.services.oracles_lens.signal_weighted_score import (
        build_oracles_lens_response,
    )

    payload = build_oracles_lens_response(db_session, period="1999-Q1")
    assert payload["items"] == []
