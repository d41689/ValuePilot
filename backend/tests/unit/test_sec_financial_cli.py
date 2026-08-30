from datetime import date, datetime, timezone

import pytest
import typer

from app.cli.sec_financials import _resolve_gold_case_stock
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import register_reviewed_sec_identity


NOW = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
BRKB_CASE = {
    "case_id": "brkb-primary",
    "company_name": "Berkshire Hathaway Inc.",
    "cik": "0001067983",
    "primary_listing": {
        "ticker": "BRK-B",
        "mic": "XNYS",
        "country": "US",
        "instrument_type": "common_stock",
        "share_class": "class_b",
    },
}


def _stock(
    db_session,
    *,
    ticker: str,
    company_name: str = "Berkshire Hathaway Inc",
    listing_exchange: str | None = "NYSE",
    raw_exchange: str | None = None,
    exchange: str | None = None,
    is_active: bool = True,
) -> Stock:
    raw_exchange = listing_exchange if raw_exchange is None else raw_exchange
    exchange = listing_exchange or "US" if exchange is None else exchange
    stock = Stock(
        ticker=ticker,
        exchange=exchange,
        market_country="US",
        listing_exchange=listing_exchange,
        raw_exchange=raw_exchange,
        company_name=company_name,
        is_active=is_active,
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def test_gold_case_resolves_by_reviewed_cik_before_ticker_alias(db_session) -> None:
    reviewed_stock = _stock(db_session, ticker="BRK/B")
    _stock(db_session, ticker="BRK-B")
    register_reviewed_sec_identity(
        db_session,
        stock_id=reviewed_stock.id,
        cik=BRKB_CASE["cik"],
        effective_from=date(2015, 1, 1),
        known_at=NOW,
        review_reason="Locked gold-case identity review.",
    )

    resolution = _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)

    assert resolution.stock.id == reviewed_stock.id
    assert resolution.source == "reviewed_cik"
    assert resolution.manifest_ticker == "BRK-B"


def test_gold_case_bootstraps_narrow_separator_alias(db_session) -> None:
    stock = _stock(db_session, ticker="BRK/B")

    resolution = _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)

    assert resolution.stock.id == stock.id
    assert resolution.source == "locked_manifest_bootstrap"
    assert resolution.manifest_ticker == "BRK-B"


def test_gold_case_bootstrap_accepts_unambiguous_legacy_listing_fallback(
    db_session,
) -> None:
    stock = _stock(
        db_session,
        ticker="BRK/B",
        listing_exchange=None,
        raw_exchange="NYSE",
        exchange="NYSE",
    )

    resolution = _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)

    assert resolution.stock.id == stock.id
    assert resolution.source == "locked_manifest_bootstrap"


def test_gold_case_bootstrap_rejects_canonical_venue_mismatch_even_if_raw_matches(
    db_session,
) -> None:
    _stock(
        db_session,
        ticker="BRK/B",
        listing_exchange="NASDAQ",
        raw_exchange="NYSE",
        exchange="NYSE",
    )

    with pytest.raises(
        typer.BadParameter,
        match="locked case bootstrap must resolve to exactly one consistent stock row; found 0",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_bootstrap_rejects_conflicting_legacy_listing_metadata(
    db_session,
) -> None:
    _stock(
        db_session,
        ticker="BRK/B",
        listing_exchange=None,
        raw_exchange="NYSE",
        exchange="NASDAQ",
    )

    with pytest.raises(
        typer.BadParameter,
        match="locked case bootstrap must resolve to exactly one consistent stock row; found 0",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_bootstrap_alias_ambiguity_fails_closed(db_session) -> None:
    _stock(db_session, ticker="BRK/B")
    _stock(db_session, ticker="BRK.B")

    with pytest.raises(
        typer.BadParameter,
        match="locked case bootstrap must resolve to exactly one consistent stock row; found 2",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_conflicting_reviewed_cik_never_falls_back_to_ticker(
    db_session,
) -> None:
    conflicting = _stock(
        db_session,
        ticker="OTHER",
        company_name="Another Economic Issuer Inc.",
    )
    _stock(db_session, ticker="BRK/B")
    register_reviewed_sec_identity(
        db_session,
        stock_id=conflicting.id,
        cik=BRKB_CASE["cik"],
        effective_from=date(2015, 1, 1),
        known_at=NOW,
        review_reason="Conflicting reviewed identity fixture.",
    )

    with pytest.raises(
        typer.BadParameter,
        match="reviewed CIK identity conflicts with locked case brkb-primary",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)


def test_gold_case_inactive_reviewed_stock_never_falls_back_to_active_alias(
    db_session,
) -> None:
    inactive_reviewed = _stock(db_session, ticker="BRK/B", is_active=False)
    _stock(db_session, ticker="BRK.B")
    register_reviewed_sec_identity(
        db_session,
        stock_id=inactive_reviewed.id,
        cik=BRKB_CASE["cik"],
        effective_from=date(2015, 1, 1),
        known_at=NOW,
        review_reason="Inactive reviewed identity fixture.",
    )

    with pytest.raises(
        typer.BadParameter,
        match="reviewed CIK identity conflicts with locked case brkb-primary",
    ):
        _resolve_gold_case_stock(db_session, BRKB_CASE, at=NOW)
