from __future__ import annotations


US_EXCHANGE_ALIASES = {
    "US",
    "NYSE",
    "NASDAQ",
    "NDQ",
    "NAS",
    "NMS",
    "NCM",
    "NGM",
    "NSDQ",
    "AMEX",
    "NYSEMKT",
    "NYSEAMERICAN",
    "ARCA",
    "BATS",
    "OTC",
    "PNK",
}

CANADA_EXCHANGE_ALIASES = {
    "CA",
    "CAN",
    "TSE",
    "TSX",
    "TSXV",
    "CVE",
}

LISTING_EXCHANGE_ALIASES = {
    "NASDAQ": "NDQ",
    "NAS": "NDQ",
    "NMS": "NDQ",
    "NCM": "NDQ",
    "NGM": "NDQ",
    "NSDQ": "NDQ",
    "TSX": "TSE",
}


def normalize_listing_exchange(exchange: str | None) -> str | None:
    if not exchange:
        return None
    normalized = exchange.strip().upper()
    if not normalized:
        return None
    return LISTING_EXCHANGE_ALIASES.get(normalized, normalized)


def canonical_market_country(exchange: str | None, *, ticker: str | None = None) -> str:
    normalized = normalize_listing_exchange(exchange)
    ticker_upper = ticker.upper() if ticker else ""
    if ticker_upper.endswith(".TO"):
        return "CA"
    if normalized in CANADA_EXCHANGE_ALIASES:
        return "CA"
    if normalized in US_EXCHANGE_ALIASES:
        return "US"
    return normalized or "UNKNOWN"
