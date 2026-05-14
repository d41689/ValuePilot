"""MVP5-02 amendment-blocked holder exclusion tests.

Pre-MVP5-02: a holder whose filing has ``amendment_status`` of
``amendments_pending`` or ``amendment_failed`` still contributed to
``signal_weighted_consensus_score`` / ``conviction_score`` /
``distinctive_consensus_score``; the caveat only demoted
``score_confidence``.

Post-MVP5-02: those holders are excluded from the score aggregate
entirely. The existence of the excluded holder is still surfaced
at the page level via ``caution_flag_codes`` and via the new
``excluded_holders`` / ``excluded_holder_count`` fields on
``score_explanation``.
"""
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
from app.models.oracles_lens import OraclesLensSignal
from app.models.stocks import Stock
from app.services.oracles_lens.signal_weighted_score import (
    compute_signal_weighted_scores,
)


_CIK_SEQ = count(9970200000)
_ACC_SEQ = count(720001)
_STOCK_SEQ = count(72001)


_QUARTER = "2026-Q1"
_QUARTER_END = date(2026, 3, 31)


def _manager(
    db_session, *, manager_type: str = "long_term_fundamental",
) -> InstitutionManager:
    cik = str(next(_CIK_SEQ))
    manager = InstitutionManager(
        canonical_name=f"Mv5-02 Mgr {cik}",
        legal_name=f"Mv5-02 Mgr {cik}",
        edgar_legal_name=f"Mv5-02 Mgr {cik}",
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
        ticker=f"M52{seq:04d}"[-10:],
        exchange="NYSE",
        company_name=f"M52Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _filing(
    db_session,
    manager: InstitutionManager,
    *,
    amendment_status: str = "no_amendments_seen",
) -> Filing13F:
    accession = f"00099702-26-{next(_ACC_SEQ):06d}"
    filing = Filing13F(
        manager_id=manager.id,
        accession_no=accession,
        accession_number=accession,
        cik=manager.cik,
        period_of_report=_QUARTER_END,
        filed_at=_QUARTER_END,
        filing_date=_QUARTER_END,
        accepted_at=datetime(_QUARTER_END.year, _QUARTER_END.month, _QUARTER_END.day, 17, tzinfo=timezone.utc),
        form_type="13F-HR",
        report_type="holdings_report",
        coverage_completeness="complete",
        coverage_type="normal",
        quarter_end_date=_QUARTER_END,
        report_quarter=_QUARTER,
        official_filing_deadline=date(2026, 5, 15),
        parse_status="succeeded",
        is_active_for_manager_period=True,
        is_latest_for_period=True,
        amendment_status=amendment_status,
        computed_total_value_thousands=1_000_000,
        reported_total_value_thousands=1_000_000,
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


def _holding(db_session, filing: Filing13F, stock: Stock) -> Holding13F:
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
        value_thousands=50_000,
        value_raw="50000000",
        value_unit_raw="dollars",
        value_parse_rule="schema_dollars",
        value_usd=50_000_000,
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


def _signal_for(db_session, stock: Stock) -> OraclesLensSignal | None:
    return (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .one_or_none()
    )


# ===========================================================================
# Score-aggregate exclusion
# ===========================================================================


def test_amendments_pending_holder_excluded_from_score(db_session):
    """1 amendment-pending + 3 clean = 3 included after exclusion;
    stock scored on the 3 clean holders only. excluded_holder_count
    and excluded_holders both populated; AMENDMENTS_PENDING still
    in page-level caution_flag_codes."""
    stock = _stock(db_session)

    pending_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, pending_mgr, amendment_status="amendments_pending"),
        stock,
    )

    clean_mgr_ids: list[int] = []
    for _ in range(3):
        mgr = _manager(db_session)
        clean_mgr_ids.append(mgr.id)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    signal = _signal_for(db_session, stock)
    assert signal is not None
    assert signal.raw_consensus_count == 3, (
        "score must aggregate the 3 clean holders only, not 4"
    )

    explanation = signal.score_explanation or {}
    assert explanation.get("excluded_holder_count") == 1
    excluded = explanation.get("excluded_holders") or []
    assert len(excluded) == 1
    entry = excluded[0]
    assert entry["manager_id"] == pending_mgr.id
    assert entry["exclusion_reason"] == "AMENDMENT_PENDING_EXCLUDED"
    assert entry["manager_canonical_name"]  # non-empty string

    # Page-level visibility preserved.
    assert "AMENDMENTS_PENDING" in (signal.caution_flag_codes or [])


def test_amendment_failed_holder_excluded_from_score(db_session):
    """Same shape as AMENDMENTS_PENDING but for amendment_failed."""
    stock = _stock(db_session)

    failed_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, failed_mgr, amendment_status="amendment_failed"),
        stock,
    )
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    signal = _signal_for(db_session, stock)
    assert signal is not None
    assert signal.raw_consensus_count == 3

    explanation = signal.score_explanation or {}
    excluded = explanation.get("excluded_holders") or []
    assert len(excluded) == 1
    assert excluded[0]["manager_id"] == failed_mgr.id
    assert excluded[0]["exclusion_reason"] == "AMENDMENT_FAILED_EXCLUDED"
    assert "AMENDMENT_FAILED" in (signal.caution_flag_codes or [])


# ===========================================================================
# Eligibility floor — over-exclusion
# ===========================================================================


def test_over_excluded_stock_skipped_entirely(db_session):
    """If exclusion drops the included-holder count below the
    eligibility floor (min_holders=3), the stock is skipped — no
    ``oracles_lens_signals`` row is written. The score is not
    meaningful with 1 holder."""
    stock = _stock(db_session)

    pending_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, pending_mgr, amendment_status="amendments_pending"),
        stock,
    )
    failed_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, failed_mgr, amendment_status="amendment_failed"),
        stock,
    )
    # Only one clean holder → after excluding the 2 amendment holders,
    # included count is 1, below min_holders=3.
    clean_mgr = _manager(db_session)
    _holding(db_session, _filing(db_session, clean_mgr), stock)

    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    assert _signal_for(db_session, stock) is None


# ===========================================================================
# Conviction / distinctive consistency
# ===========================================================================


def test_conviction_and_distinctive_exclude_blocked_holders(db_session):
    """The same partitioned contributions feed signal-weighted,
    conviction, and distinctive scoring. Excluded holders must not
    bias the conviction or distinctive aggregates either.

    Construction: a stock with 3 clean holders (control). A second
    stock with the SAME 3 clean holders plus 1 amendment-pending
    holder. The conviction + distinctive scores on both stocks
    should match because the amendment holder is excluded.
    """
    control_stock = _stock(db_session)
    treatment_stock = _stock(db_session)

    clean_mgrs = [_manager(db_session) for _ in range(3)]
    for mgr in clean_mgrs:
        f = _filing(db_session, mgr)
        _holding(db_session, f, control_stock)
        _holding(db_session, f, treatment_stock)

    # treatment_stock gets one extra amendment-pending holder.
    pending_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, pending_mgr, amendment_status="amendments_pending"),
        treatment_stock,
    )

    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    control = _signal_for(db_session, control_stock)
    treatment = _signal_for(db_session, treatment_stock)
    assert control is not None
    assert treatment is not None

    # raw_consensus_count is the included-holder count (the eligibility
    # floor check sees the same partitioned list scoring uses).
    assert control.raw_consensus_count == 3
    assert treatment.raw_consensus_count == 3

    # Conviction is a stock-level aggregate over included contributions.
    # Same 3 clean holders → same conviction.
    assert control.conviction_score == treatment.conviction_score, (
        f"conviction mismatch: control={control.conviction_score} "
        f"treatment={treatment.conviction_score}"
    )

    # Distinctive is signal_weighted × three factors; the factors are
    # also computed over included contributions, so same input → same
    # output.
    assert (
        control.distinctive_consensus_score
        == treatment.distinctive_consensus_score
    ), (
        f"distinctive mismatch: control={control.distinctive_consensus_score} "
        f"treatment={treatment.distinctive_consensus_score}"
    )

    # And signal_weighted itself matches.
    assert (
        control.signal_weighted_consensus_score
        == treatment.signal_weighted_consensus_score
    )


# ===========================================================================
# Mixed exclusion reasons on the same stock
# ===========================================================================


def test_excluded_holders_payload_distinguishes_reasons(db_session):
    """One stock with both an AMENDMENTS_PENDING and an
    AMENDMENT_FAILED holder. excluded_holders should carry both
    entries with their respective exclusion_reason values."""
    stock = _stock(db_session)

    pending_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, pending_mgr, amendment_status="amendments_pending"),
        stock,
    )
    failed_mgr = _manager(db_session)
    _holding(
        db_session,
        _filing(db_session, failed_mgr, amendment_status="amendment_failed"),
        stock,
    )
    # Three clean holders so the included count stays above min_holders.
    for _ in range(3):
        mgr = _manager(db_session)
        _holding(db_session, _filing(db_session, mgr), stock)

    compute_signal_weighted_scores(db_session, quarter=_QUARTER)

    signal = _signal_for(db_session, stock)
    assert signal is not None
    explanation = signal.score_explanation or {}
    assert explanation.get("excluded_holder_count") == 2

    by_manager = {
        e["manager_id"]: e for e in explanation.get("excluded_holders") or []
    }
    assert by_manager[pending_mgr.id]["exclusion_reason"] == "AMENDMENT_PENDING_EXCLUDED"
    assert by_manager[failed_mgr.id]["exclusion_reason"] == "AMENDMENT_FAILED_EXCLUDED"

    codes = set(signal.caution_flag_codes or [])
    assert "AMENDMENTS_PENDING" in codes
    assert "AMENDMENT_FAILED" in codes
