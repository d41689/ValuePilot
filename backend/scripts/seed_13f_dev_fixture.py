"""Pre-MVP6-01: Synthetic 13F dev fixture seeder.

Path B (synthetic fixture) over Path A (real OpenFIGI ingestion) per
the PO decision recorded in
``docs/tasks/2026-05-12_pre-mvp6-01-13f-dev-data-bootstrap.md``.

Invoke:

    docker compose exec api python -m scripts.seed_13f_dev_fixture
    docker compose exec api python -m scripts.seed_13f_dev_fixture --reset

Idempotent — re-running against an already-seeded DB skips entities
that match deterministic keys (CIK / ticker / accession / fingerprint)
and never duplicates rows. The ``--reset`` flag wipes prior devseed
artifacts (matched by the ``DEVSEED`` / ``9999`` shibboleth) before
re-seeding; use it when iterating on the seeder itself.

What gets seeded:

- 8 stocks (DEVSEED1..DEVSEED8) with linked `stock_id` + CUSIP
  mapping rows so holdings can be flagged ``cusip_mapping_status='linked'``.
- 32 managers — 4 per canonical 8-value taxonomy
  (``long_term_fundamental``, ``value_concentrated``, ``activist``,
  ``quant``, ``high_turnover``, ``index_like``, ``multi_strategy``,
  ``unknown``) so the manager-weight branches are all exercised.
- 2 quarters: 2025-Q4 (prior) and 2026-Q1 (current). Cross-quarter
  delta + streak computation has something real to work with.
- 4 caveat cases distributed across the universe so MVP5-02
  exclusion / MVP4-05 caveat propagation paths fire:
  - One ``amendment_status='amendments_pending'`` filing.
  - One 13F-NT filing (``coverage_type='notice_reported_elsewhere'``).
  - One combination report (``coverage_completeness='partial'``).
  - One ``has_confidential_treatment=True`` filing.
- ~250 holdings (3-5 per manager-quarter pair).
- A persisted scoring backfill run for 2026-Q1 so
  ``oracles_lens_signals`` is non-empty and admin / dashboard
  surfaces render with real data.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.institutions import (
    CusipTickerMap,
    Filing13F,
    Holding13F,
    InstitutionManager,
    ParseRun13F,
)
from app.models.oracles_lens import (
    OraclesLensScoreComponent,
    OraclesLensSignal,
)
from app.models.stocks import Stock
from app.services.oracles_lens.signal_weighted_score import (
    compute_signal_weighted_scores,
)


# ===========================================================================
# Deterministic seed parameters
# ===========================================================================


_TICKER_PREFIX = "DEVSEED"
_CIK_PREFIX = "9999"  # produces 10-digit CIKs like '9999000001'
# Real SEC accession numbers are exactly 20 chars
# (XXXXXXXXXX-YY-NNNNNN: 10 + 1 + 2 + 1 + 6). The filings_13f.accession_no
# column is VARCHAR(20), so we mirror the SEC shape rather than coining
# our own format. The leading filer-CIK component encodes a dev-shibboleth
# 9999... CIK so devseed accessions are still visually distinct.
_ACCESSION_FILER_CIK = "0009999999"

_QUARTERS: list[tuple[str, date]] = [
    ("2025-Q4", date(2025, 12, 31)),
    ("2026-Q1", date(2026, 3, 31)),
]
_CURRENT_QUARTER = "2026-Q1"

# 4 per manager_type * 8 types = 32 managers
_MANAGER_TYPES_ORDERED: list[str] = [
    "long_term_fundamental",
    "value_concentrated",
    "activist",
    "quant",
    "high_turnover",
    "index_like",
    "multi_strategy",
    "unknown",
]
_MANAGERS_PER_TYPE = 4
_STOCK_COUNT = 8

# Per-filing holding count is round-robin within this range so the
# universe stays in the 200-500 holding target window.
_HOLDINGS_PER_FILING_OPTIONS = [3, 4, 5]


# ===========================================================================
# Stocks
# ===========================================================================


def _seed_stocks(session: Session) -> list[Stock]:
    """Idempotent stock + CUSIP-mapping seed. Returns the canonical
    list ordered by 1-indexed seed slot."""
    stocks: list[Stock] = []
    for slot in range(1, _STOCK_COUNT + 1):
        ticker = f"{_TICKER_PREFIX}{slot}"
        cusip = _cusip_for_slot(slot)
        stock = session.query(Stock).filter(Stock.ticker == ticker).one_or_none()
        if stock is None:
            stock = Stock(
                ticker=ticker,
                exchange="NYSE",
                company_name=f"Devseed Co {slot}",
                is_active=True,
            )
            session.add(stock)
            session.flush()
        stocks.append(stock)

        existing = (
            session.query(CusipTickerMap)
            .filter(CusipTickerMap.cusip == cusip)
            .one_or_none()
        )
        if existing is None:
            session.add(
                CusipTickerMap(
                    cusip=cusip,
                    ticker=ticker,
                    issuer_name=f"Devseed Co {slot}",
                    security_type="common_stock",
                    exchange="NYSE",
                    stock_id=stock.id,
                    is_13f_reportable=True,
                    source="manual",
                    mapping_status="confirmed",
                    is_active=True,
                )
            )
            session.flush()
    return stocks


def _cusip_for_slot(slot: int) -> str:
    """9-character synthetic CUSIP. ``DEV`` prefix + 6-digit zero-padded
    slot makes the CUSIP visually obvious as a dev artifact."""
    return f"DEV{slot:06d}"


# ===========================================================================
# Managers
# ===========================================================================


def _seed_managers(session: Session) -> list[InstitutionManager]:
    """Idempotent manager seed across the 8-value canonical taxonomy.
    Returns the full list ordered by 1-indexed seed slot. The slot is
    encoded in the manager's CIK so re-running matches by CIK."""
    managers: list[InstitutionManager] = []
    slot = 0
    for mgr_type in _MANAGER_TYPES_ORDERED:
        for _ in range(_MANAGERS_PER_TYPE):
            slot += 1
            cik = f"{_CIK_PREFIX}{slot:06d}"
            existing = (
                session.query(InstitutionManager)
                .filter(InstitutionManager.cik == cik)
                .one_or_none()
            )
            if existing is None:
                manager = InstitutionManager(
                    canonical_name=f"DEVSEED {mgr_type} Cap {slot}",
                    legal_name=f"DEVSEED {mgr_type} Capital {slot}",
                    edgar_legal_name=f"DEVSEED {mgr_type} Capital {slot}",
                    cik=cik,
                    status="active",
                    match_status="confirmed",
                    manager_type=mgr_type,
                    is_superinvestor=True,
                    source="manual",
                )
                session.add(manager)
                session.flush()
            else:
                manager = existing
            managers.append(manager)
    return managers


# ===========================================================================
# Filings + holdings
# ===========================================================================


def _seed_filings_and_holdings(
    session: Session,
    *,
    stocks: list[Stock],
    managers: list[InstitutionManager],
) -> dict[str, int]:
    """Build filings (one per manager × quarter) plus their
    holdings. Returns a count summary."""
    counts = {"filings": 0, "parse_runs": 0, "holdings": 0}
    holding_value = 50_000
    filing_total_value = 1_000_000

    for q_idx, (quarter, quarter_end) in enumerate(_QUARTERS):
        for m_idx, manager in enumerate(managers):
            accession = _accession_for(quarter, m_idx)
            filing = (
                session.query(Filing13F)
                .filter(Filing13F.accession_number == accession)
                .one_or_none()
            )
            if filing is None:
                # MVP5-02 amendment-pending case: manager #0 in current
                # quarter has amendments_pending. MVP4-05 amendment
                # caveat fires; MVP5-02 exclusion drops the contribution
                # from the score aggregate.
                amendment_status = "no_amendments_seen"
                if m_idx == 0 and quarter == _CURRENT_QUARTER:
                    amendment_status = "amendments_pending"

                # 13F-NT case: manager #1 filed 13F-NT in the PRIOR
                # quarter and a normal 13F-HR in current quarter, so
                # the current-quarter streak compute walks back into
                # the NT quarter and emits ``NT_QUARTER_STREAK_BREAK``.
                # Putting NT in the current quarter wouldn't fire the
                # caveat — the manager would just be invisible to
                # consensus scoring this quarter.
                form_type = "13F-HR"
                coverage_type = "normal"
                if m_idx == 1 and quarter != _CURRENT_QUARTER:
                    form_type = "13F-NT"
                    coverage_type = "notice_reported_elsewhere"

                # Combination report case: manager #2 in current
                # quarter has partial coverage. PARTIAL_COVERAGE
                # caveat fires; portfolio_weight result is suppressed
                # per MVP4-02.
                coverage_completeness = "complete"
                if m_idx == 2 and quarter == _CURRENT_QUARTER:
                    coverage_completeness = "partial"

                # Confidential treatment case: manager #3 in current
                # quarter has confidential_treatment. Per-holder
                # CONFIDENTIAL_TREATMENT caveat fires.
                has_confidential_treatment = (
                    m_idx == 3 and quarter == _CURRENT_QUARTER
                )

                filing = Filing13F(
                    manager_id=manager.id,
                    accession_no=accession,
                    accession_number=accession,
                    cik=manager.cik,
                    period_of_report=quarter_end,
                    filed_at=quarter_end,
                    filing_date=quarter_end,
                    accepted_at=datetime(
                        quarter_end.year, quarter_end.month, quarter_end.day,
                        17, tzinfo=timezone.utc,
                    ),
                    form_type=form_type,
                    report_type=(
                        "notice_report"
                        if form_type == "13F-NT"
                        else "holdings_report"
                    ),
                    coverage_completeness=coverage_completeness,
                    coverage_type=coverage_type,
                    quarter_end_date=quarter_end,
                    report_quarter=quarter,
                    official_filing_deadline=_filing_deadline(quarter_end),
                    parse_status="succeeded",
                    is_active_for_manager_period=True,
                    is_latest_for_period=True,
                    amendment_status=amendment_status,
                    has_confidential_treatment=has_confidential_treatment,
                    computed_total_value_thousands=filing_total_value,
                    reported_total_value_thousands=filing_total_value,
                )
                session.add(filing)
                session.flush()
                counts["filings"] += 1

            parse_run = (
                session.query(ParseRun13F)
                .filter(ParseRun13F.accession_number == accession)
                .filter(ParseRun13F.is_current.is_(True))
                .one_or_none()
            )
            if parse_run is None:
                parse_run = ParseRun13F(
                    accession_number=accession,
                    parser_version="devseed",
                    fingerprint_version="v1",
                    status="succeeded",
                    holdings_count=0,
                    is_current=True,
                )
                session.add(parse_run)
                session.flush()
                counts["parse_runs"] += 1

            # 13F-NT filings carry no holdings (notice-only). Skip.
            if filing.form_type == "13F-NT":
                continue

            # Pick which stocks this manager holds this quarter — a
            # deterministic rolling window so we get overlap between
            # holders (consensus possible) and overlap across quarters
            # (streak possible).
            count_idx = (m_idx + q_idx) % len(_HOLDINGS_PER_FILING_OPTIONS)
            num_holdings = _HOLDINGS_PER_FILING_OPTIONS[count_idx]
            stock_offset = m_idx % len(stocks)
            chosen = [
                stocks[(stock_offset + k) % len(stocks)]
                for k in range(num_holdings)
            ]

            for source_idx, stock in enumerate(chosen):
                fingerprint = f"{accession}-{stock.id}"
                existing = (
                    session.query(Holding13F)
                    .filter(Holding13F.holding_row_fingerprint == fingerprint)
                    .one_or_none()
                )
                if existing is not None:
                    continue
                cusip = _cusip_for_slot(_slot_for_ticker(stock.ticker))
                session.add(
                    Holding13F(
                        filing_id=filing.id,
                        parse_run_id=parse_run.id,
                        manager_id=manager.id,
                        accession_number=accession,
                        report_quarter=quarter,
                        quarter_end_date=quarter_end,
                        row_fingerprint=fingerprint,
                        holding_row_fingerprint=fingerprint,
                        cusip=cusip,
                        issuer_name=stock.company_name,
                        name_of_issuer=stock.company_name,
                        title_of_class="COM",
                        value_thousands=holding_value,
                        value_raw=str(holding_value * 1000),
                        value_unit_raw="dollars",
                        value_parse_rule="schema_dollars",
                        value_usd=holding_value * 1000,
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
                        source_row_index=source_idx,
                    )
                )
                counts["holdings"] += 1
            session.flush()
    return counts


def _slot_for_ticker(ticker: str) -> int:
    return int(ticker.removeprefix(_TICKER_PREFIX))


def _accession_for(quarter: str, manager_idx: int) -> str:
    """Real-SEC-shape 20-char accession. Sequence packs (quarter-slot,
    manager-slot) deterministically so re-running the seeder produces
    the same accession set."""
    q_slot = _QUARTER_INDEX[quarter]  # 0 or 1
    seq = q_slot * 1000 + manager_idx
    return f"{_ACCESSION_FILER_CIK}-26-{seq:06d}"


_QUARTER_INDEX: dict[str, int] = {q: i for i, (q, _) in enumerate(_QUARTERS)}


def _filing_deadline(quarter_end: date) -> date:
    # quarter_end + ~45 days, rounded to the 15th of the second
    # following month. Good enough for dev fixture.
    month = quarter_end.month + 2
    year = quarter_end.year + (1 if month > 12 else 0)
    if month > 12:
        month -= 12
    return date(year, month, 15)


# ===========================================================================
# Persisted scoring
# ===========================================================================


def _run_persisted_scoring(session: Session) -> dict[str, Any]:
    """Compute signal-weighted scores for the current quarter so
    ``oracles_lens_signals`` is populated. The compute function does
    its own commit."""
    return compute_signal_weighted_scores(session, quarter=_CURRENT_QUARTER)


# ===========================================================================
# Acceptance summary
# ===========================================================================


def _acceptance_summary(session: Session) -> dict[str, Any]:
    """Run the Pre-MVP6-01 acceptance queries and return a summary
    dict so the caller can print + assert."""
    from sqlalchemy import func

    signals_count = session.query(OraclesLensSignal).count()
    linked_holdings = (
        session.query(Holding13F)
        .filter(Holding13F.stock_id.isnot(None))
        .filter(Holding13F.cusip_mapping_status == "linked")
        .count()
    )
    succeeded_filings = (
        session.query(Filing13F)
        .filter(Filing13F.parse_status == "succeeded")
        .count()
    )
    typed_managers = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.manager_type != "unknown")
        .filter(InstitutionManager.canonical_name.like("DEVSEED %"))
        .count()
    )
    unknown_managers = (
        session.query(InstitutionManager)
        .filter(InstitutionManager.manager_type == "unknown")
        .filter(InstitutionManager.canonical_name.like("DEVSEED %"))
        .count()
    )
    # MVP5-02 amendment exclusion check
    exclusion_signals = 0
    for signal in session.query(OraclesLensSignal).all():
        explanation = signal.score_explanation or {}
        if explanation.get("excluded_holder_count", 0) > 0:
            exclusion_signals += 1
    # Distinct caution flag codes across all signals (sanity that
    # the four caveat cases produced at least some caveats)
    caveat_codes: set[str] = set()
    for signal in session.query(OraclesLensSignal).all():
        for code in signal.caution_flag_codes or []:
            caveat_codes.add(code)
    return {
        "oracles_lens_signals_count": signals_count,
        "linked_holdings_count": linked_holdings,
        "succeeded_filings_count": succeeded_filings,
        "devseed_typed_managers": typed_managers,
        "devseed_unknown_managers": unknown_managers,
        "signals_with_excluded_holders": exclusion_signals,
        "distinct_caveat_codes": sorted(caveat_codes),
    }


# ===========================================================================
# Reset (optional)
# ===========================================================================


def _reset_devseed(session: Session) -> dict[str, int]:
    """Wipe prior devseed artifacts so the seeder can re-run cleanly
    when its logic changes. Matched by the DEVSEED/9999 shibboleth so
    we never touch non-fixture rows."""
    # Order: child rows first so FK cascades aren't required.
    manager_cik_filter = InstitutionManager.cik.like(f"{_CIK_PREFIX}%")
    manager_ids = [
        m.id
        for m in session.query(InstitutionManager).filter(manager_cik_filter).all()
    ]
    # Holdings + parse runs + filings keyed on devseed managers.
    holdings_deleted = (
        session.query(Holding13F)
        .filter(Holding13F.manager_id.in_(manager_ids))
        .delete(synchronize_session=False)
        if manager_ids else 0
    )
    filings_q = session.query(Filing13F).filter(
        Filing13F.manager_id.in_(manager_ids)
    )
    filing_accessions = [f.accession_number for f in filings_q.all()] if manager_ids else []
    parse_runs_deleted = (
        session.query(ParseRun13F)
        .filter(ParseRun13F.accession_number.in_(filing_accessions))
        .delete(synchronize_session=False)
        if filing_accessions else 0
    )
    filings_deleted = (
        filings_q.delete(synchronize_session=False)
        if manager_ids else 0
    )
    # Score-side rows keyed on devseed stock_ids.
    stock_ids = [
        s.id
        for s in session.query(Stock).filter(Stock.ticker.like(f"{_TICKER_PREFIX}%")).all()
    ]
    signal_ids = [
        sig.id for sig in
        session.query(OraclesLensSignal).filter(OraclesLensSignal.stock_id.in_(stock_ids)).all()
    ] if stock_ids else []
    components_deleted = (
        session.query(OraclesLensScoreComponent)
        .filter(OraclesLensScoreComponent.score_id.in_(signal_ids))
        .delete(synchronize_session=False)
        if signal_ids else 0
    )
    signals_deleted = (
        session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id.in_(stock_ids))
        .delete(synchronize_session=False)
        if stock_ids else 0
    )
    # CUSIP map rows + managers + stocks themselves.
    cusip_deleted = (
        session.query(CusipTickerMap)
        .filter(CusipTickerMap.stock_id.in_(stock_ids))
        .delete(synchronize_session=False)
        if stock_ids else 0
    )
    managers_deleted = (
        session.query(InstitutionManager)
        .filter(manager_cik_filter)
        .delete(synchronize_session=False)
        if manager_ids else 0
    )
    stocks_deleted = (
        session.query(Stock)
        .filter(Stock.ticker.like(f"{_TICKER_PREFIX}%"))
        .delete(synchronize_session=False)
        if stock_ids else 0
    )
    session.commit()
    return {
        "holdings_deleted": holdings_deleted,
        "parse_runs_deleted": parse_runs_deleted,
        "filings_deleted": filings_deleted,
        "components_deleted": components_deleted,
        "signals_deleted": signals_deleted,
        "cusip_mappings_deleted": cusip_deleted,
        "managers_deleted": managers_deleted,
        "stocks_deleted": stocks_deleted,
    }


# ===========================================================================
# Entry point
# ===========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-MVP6-01 13F dev fixture seeder")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Wipe prior devseed rows before reseeding (idempotent normally; "
             "use this when the seeder's own logic changes).",
    )
    parser.add_argument(
        "--reset-only",
        action="store_true",
        help="Wipe devseed rows and exit without reseeding. Use before "
             "running pytest against the dev DB to avoid devseed pollution.",
    )
    args = parser.parse_args()

    session: Session = SessionLocal()
    try:
        if args.reset or args.reset_only:
            print("Pre-MVP6-01 reset: wiping devseed artifacts", flush=True)
            reset_summary = _reset_devseed(session)
            for key, value in reset_summary.items():
                print(f"  {key}: {value}", flush=True)
            if args.reset_only:
                return
        print("Pre-MVP6-01 seed: stocks", flush=True)
        stocks = _seed_stocks(session)
        print(f"  -> {len(stocks)} stocks present (idempotent)", flush=True)

        print("Pre-MVP6-01 seed: managers", flush=True)
        managers = _seed_managers(session)
        print(f"  -> {len(managers)} managers present (idempotent)", flush=True)

        print("Pre-MVP6-01 seed: filings + holdings", flush=True)
        filings_summary = _seed_filings_and_holdings(
            session, stocks=stocks, managers=managers,
        )
        session.commit()
        print(
            f"  -> filings created: {filings_summary['filings']}, "
            f"parse_runs created: {filings_summary['parse_runs']}, "
            f"holdings created: {filings_summary['holdings']}",
            flush=True,
        )

        print(f"Pre-MVP6-01 seed: scoring backfill for {_CURRENT_QUARTER}", flush=True)
        scoring_summary = _run_persisted_scoring(session)
        print(
            f"  -> filings_scored: {scoring_summary['filings_scored']}, "
            f"components_written: {scoring_summary['components_written']}",
            flush=True,
        )

        print("Pre-MVP6-01 acceptance summary:", flush=True)
        summary = _acceptance_summary(session)
        for key, value in summary.items():
            print(f"  {key}: {value}", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    main()
