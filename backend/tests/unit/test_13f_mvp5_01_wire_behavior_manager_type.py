"""MVP5-01 tests — behavior-derived manager_type wired into live scoring.

Pre-MVP5-01 production behavior:

  ``resolve_manager_type(manager, derived_profile=None)``

was called with ``derived_profile`` hardcoded to ``None`` at
``signal_weighted_score.py:510``. The MVP4-11 three-tier precedence
(admin → behavior → fallback_unknown) therefore collapsed to two
tiers in production: admin-set if non-unknown, else
``fallback_unknown=0.60``. Behavior-derived classification was
unreachable in live scoring.

Post-MVP5-01: ``_contributions_for_stock`` lazily computes
``DerivedManagerSignalProfile`` for every manager whose admin type
is ``None`` or ``unknown`` and passes it into ``resolve_manager_type``.
The three tests below pin the three resolution paths end-to-end
through ``compute_signal_weighted_scores`` so the integration is
real, not just unit-level."""
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
from app.services.oracles_lens.signal_weighted_score import (
    compute_signal_weighted_scores,
)


_CIK_SEQ = count(9970100000)
_ACC_SEQ = count(700001)
_STOCK_SEQ = count(70001)


# ===========================================================================
# Fixtures
# ===========================================================================


def _manager(
    db_session, *, manager_type: str = "unknown",
) -> InstitutionManager:
    """A manager. Default ``manager_type="unknown"`` matches the
    `institution_managers` server_default; admin has not yet
    classified this manager and behavior derivation is the only path
    to a non-unknown weight."""
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv5-01 Mgr {cik}",
        legal_name=f"Mv5-01 Mgr {cik}",
        edgar_legal_name=f"Mv5-01 Mgr {cik}",
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
        ticker=f"M5{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"M5Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    quarter: str,
    quarter_end: date,
    total_thousands: int = 1_000_000,
) -> Filing13F:
    accession = f"00099701-26-{next(_ACC_SEQ):06d}"
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=quarter_end,
        filed_at=quarter_end,
        filing_date=quarter_end,
        accepted_at=datetime(quarter_end.year, quarter_end.month, quarter_end.day, 17, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=quarter_end,
        report_quarter=quarter,
        official_filing_deadline=date(quarter_end.year, quarter_end.month, quarter_end.day) if quarter_end.month != 12 else date(quarter_end.year + 1, 2, 14),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status="no_amendments_seen",
        computed_total_value_thousands=total_thousands,
        reported_total_value_thousands=total_thousands,
    )
    db_session.add(filing)
    db_session.flush()
    pr = ParseRun13F(
        accession_number=filing.accession_number,
        parser_version="test",
        fingerprint_version="v1",
        status="succeeded",
        holdings_count=0,
        is_current=True,
    )
    db_session.add(pr)
    db_session.flush()
    filing._test_parse_run = pr  # type: ignore[attr-defined]
    return filing


def _holding(
    db_session,
    filing: Filing13F,
    stock: Stock,
    *,
    value_thousands: int = 50_000,
) -> Holding13F:
    pr: ParseRun13F = filing._test_parse_run  # type: ignore[attr-defined]
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


def _signal_for(db_session, stock: Stock) -> OraclesLensSignal:
    return (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one()
    )


def _holder_entry(db_session, signal: OraclesLensSignal, manager_id: int) -> dict:
    """Read the per-holder ``manager_signal_weight`` component row for
    a given (score, manager) and return a dict shaped like the test
    expects. The per-holder detail lives in
    ``oracles_lens_score_components`` (evidence_json columns), not in
    ``score_explanation``."""
    component = (
        db_session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id == signal.id)
        .filter(OraclesLensScoreComponent.component_name == "manager_signal_weight")
        .filter(OraclesLensScoreComponent.manager_id == manager_id)
        .one_or_none()
    )
    assert component is not None, (
        f"no manager_signal_weight component row for score {signal.id} "
        f"manager {manager_id}"
    )
    evidence = component.evidence_json or {}
    return {
        "manager_id": manager_id,
        "manager_canonical_type": component.string_value,
        "manager_type_source": evidence.get("source"),
        "manager_weight": component.numeric_value,
    }


# ===========================================================================
# Resolution path tests
# ===========================================================================


_CURRENT_QUARTER = "2026-Q1"
_CURRENT_QUARTER_END = date(2026, 3, 31)


def test_admin_typed_manager_resolves_via_admin_path(db_session):
    """Manager admin-typed as long_term_fundamental → admin path,
    weight 1.00, source 'admin'. Behavior derivation never runs."""
    stock = _stock(db_session)

    admin_mgr = _manager(db_session, manager_type="long_term_fundamental")
    _holding(db_session, _filing(db_session, admin_mgr, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END), stock)

    for _ in range(2):
        other = _manager(db_session, manager_type="long_term_fundamental")
        _holding(db_session, _filing(db_session, other, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END), stock)
    compute_signal_weighted_scores(db_session, quarter=_CURRENT_QUARTER)

    signal = _signal_for(db_session, stock)
    entry = _holder_entry(db_session, signal, admin_mgr.id)
    assert entry["manager_canonical_type"] == "long_term_fundamental"
    assert entry["manager_type_source"] == "admin"
    assert Decimal(entry["manager_weight"]) == Decimal("1.00")


def test_unknown_admin_with_high_turnover_behavior_resolves_via_behavior(db_session):
    """Admin type ``unknown`` + behavior derivation produces
    ``high_turnover`` (turnover_proxy >= 0.6) → behavior path,
    weight 0.30, source 'behavior'."""
    # The manager being scored. The stock under test is "shared_stock"
    # (held this quarter alongside other holders so it's eligible).
    behavior_mgr = _manager(db_session, manager_type="unknown")

    shared_stock = _stock(db_session)

    # Current quarter portfolio for behavior_mgr: 5 distinct stocks
    # (shared_stock + 4 unique extras). One filing covers all 5
    # holdings; portfolio_weight per holding = 200_000 / 1_000_000 = 0.20.
    current_filing = _filing(
        db_session, behavior_mgr, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END,
    )
    _holding(db_session, current_filing, shared_stock, value_thousands=200_000)
    current_extras = [_stock(db_session) for _ in range(4)]
    for s in current_extras:
        _holding(db_session, current_filing, s, value_thousands=200_000)

    # Previous quarter portfolio for behavior_mgr: 5 DIFFERENT stocks.
    # symmetric_difference / union = 10/10 = 1.0 >> 0.6, so behavior
    # derivation classifies as high_turnover.
    prev_quarter = "2025-Q4"
    prev_quarter_end = date(2025, 12, 31)
    prev_filing = _filing(
        db_session, behavior_mgr, quarter=prev_quarter, quarter_end=prev_quarter_end,
    )
    for _ in range(5):
        _holding(db_session, prev_filing, _stock(db_session), value_thousands=200_000)

    # Two other admin-typed long_term_fundamental holders so shared_stock
    # has >= 3 holders and gets scored.
    for _ in range(2):
        other = _manager(db_session, manager_type="long_term_fundamental")
        _holding(
            db_session,
            _filing(db_session, other, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END),
            shared_stock,
        )

    compute_signal_weighted_scores(db_session, quarter=_CURRENT_QUARTER)

    signal = _signal_for(db_session, shared_stock)
    entry = _holder_entry(db_session, signal, behavior_mgr.id)
    assert entry["manager_canonical_type"] == "high_turnover"
    assert entry["manager_type_source"] == "behavior"
    # high_turnover weight = 0.30 per constants.MANAGER_SIGNAL_WEIGHTS.
    assert Decimal(entry["manager_weight"]) == Decimal("0.30")


def test_unknown_admin_with_unclassifiable_behavior_falls_back_to_unknown(db_session):
    """Admin ``unknown`` + behavior derivation cannot classify (low
    turnover, low concentration, short streak) → fallback_unknown,
    weight 0.60, source 'fallback_unknown'.

    Setup: same single stock held this quarter and last quarter, small
    position weight. ``derive_manager_signal_profile`` produces
    ``turnover_proxy=0.0`` (no change), ``concentration=0.05``
    (well below the 0.5 threshold), ``avg_holding_period=2`` (below
    the 4-quarter threshold). All three classification branches miss
    and the function returns ``manager_type='unknown'`` → resolver
    falls back to fallback_unknown.
    """
    shared_stock = _stock(db_session)

    fallback_mgr = _manager(db_session, manager_type="unknown")

    # Current-quarter holding of shared_stock.
    _holding(
        db_session,
        _filing(db_session, fallback_mgr, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END),
        shared_stock,
    )
    # Previous-quarter holding of the SAME stock — keeps
    # turnover_proxy at 0 and avg_holding_period at 2. Without this,
    # the dashboard's symmetric-difference algorithm classifies a
    # brand-new manager as 100% turnover → high_turnover, which is a
    # known quirk that V2 may revisit (out of scope for MVP5-01).
    _holding(
        db_session,
        _filing(db_session, fallback_mgr, quarter="2025-Q4", quarter_end=date(2025, 12, 31)),
        shared_stock,
    )

    for _ in range(2):
        other = _manager(db_session, manager_type="long_term_fundamental")
        _holding(
            db_session,
            _filing(db_session, other, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END),
            shared_stock,
        )

    compute_signal_weighted_scores(db_session, quarter=_CURRENT_QUARTER)

    signal = _signal_for(db_session, shared_stock)
    entry = _holder_entry(db_session, signal, fallback_mgr.id)
    assert entry["manager_canonical_type"] == "unknown"
    assert entry["manager_type_source"] == "fallback_unknown"
    assert Decimal(entry["manager_weight"]) == Decimal("0.60")


def test_derived_profile_cache_avoids_redundant_computation(db_session):
    """A manager who holds many scored stocks should have their
    behavior profile derived ONCE per scoring batch, not once per
    stock they hold. We assert this indirectly by confirming the
    resolver outputs are consistent across stocks held by the same
    manager — the cache keeps the result stable."""
    behavior_mgr = _manager(db_session, manager_type="unknown")

    # behavior_mgr holds 3 stocks this quarter (each will be scored).
    current_filing = _filing(
        db_session, behavior_mgr, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END,
    )
    held_stocks = [_stock(db_session) for _ in range(3)]
    for s in held_stocks:
        _holding(db_session, current_filing, s, value_thousands=200_000)

    # Pad each held stock to 3 holders so they get scored.
    for stock in held_stocks:
        for _ in range(2):
            other = _manager(db_session, manager_type="long_term_fundamental")
            _holding(
                db_session,
                _filing(db_session, other, quarter=_CURRENT_QUARTER, quarter_end=_CURRENT_QUARTER_END),
                stock,
            )

    compute_signal_weighted_scores(db_session, quarter=_CURRENT_QUARTER)

    # The resolution result must be identical for behavior_mgr on
    # every stock — same canonical_type, same source, same weight.
    sources: set[str] = set()
    types: set[str] = set()
    weights: set[str] = set()
    for stock in held_stocks:
        signal = _signal_for(db_session, stock)
        entry = _holder_entry(db_session, signal, behavior_mgr.id)
        sources.add(entry["manager_type_source"])
        types.add(entry["manager_canonical_type"])
        weights.add(str(entry["manager_weight"]))
    assert len(sources) == 1, sources
    assert len(types) == 1, types
    assert len(weights) == 1, weights
