from app.ingestion.parsers.base import IdentityInfo
from app.models.stocks import Stock
from app.services.identity_service import IdentityService
from app.core.stock_identity import (
    canonical_market_country,
    normalize_listing_exchange,
)


def test_us_listing_exchange_aliases_resolve_to_us_market_country():
    assert canonical_market_country("NDQ") == "US"
    assert canonical_market_country("NASDAQ") == "US"
    assert canonical_market_country("NYSE") == "US"
    assert canonical_market_country("AMEX") == "US"
    assert canonical_market_country("TSE") == "CA"
    assert normalize_listing_exchange("NASDAQ") == "NDQ"


def test_value_line_specific_exchange_reuses_existing_us_stock(db_session):
    existing = Stock(
        ticker="XMCT",
        exchange="US",
        market_country="US",
        listing_exchange=None,
        company_name="Alphabet Inc. CL C",
        is_active=True,
    )
    db_session.add(existing)
    db_session.flush()

    stock, needs_review, note = IdentityService(db_session).resolve_stock(
        IdentityInfo(ticker="XMCT", exchange="NDQ", company_name="ALPHABET INC.")
    )

    assert stock.id == existing.id
    assert stock.exchange == "NDQ"
    assert stock.market_country == "US"
    assert stock.listing_exchange == "NDQ"
    assert stock.raw_exchange == "US"
    assert needs_review is False
    assert note is None
