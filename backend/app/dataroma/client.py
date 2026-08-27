"""Dataroma HTTP client — routes through the Rate Guard egress service.

Rate limiting, retry, and the browser User-Agent are owned by Rate Guard; this
client just names the Dataroma pages and forwards each GET.
"""
import httpx

from app.rate_guard.client import RateGuardClient

MANAGERS_URL = "https://www.dataroma.com/m/managers.php"
HOLDINGS_URL = "https://www.dataroma.com/m/holdings.php"
ACTIVITY_URL = "https://www.dataroma.com/m/m_activity.php"
PORTFOLIO_HISTORY_URL = "https://www.dataroma.com/m/hist/p_hist.php"
STOCK_HISTORY_URL = "https://www.dataroma.com/m/hist/hist.php"


class DataromaClient:
    """Fetches Dataroma pages through the Rate Guard egress service."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._rate_guard = RateGuardClient(http_client)

    def get(self, url: str) -> bytes:
        return self._rate_guard.fetch(upstream="dataroma", method="GET", url=url)

    def get_managers(self) -> bytes:
        return self.get(MANAGERS_URL)

    def get_holdings(self, dataroma_code: str, page: int | None = None) -> bytes:
        if page is not None and page < 1:
            raise ValueError("page must be >= 1")
        suffix = f"&L={page}" if page is not None else ""
        return self.get(f"{HOLDINGS_URL}?m={dataroma_code}{suffix}")

    def get_activity(self, dataroma_code: str, activity_type: str = "a") -> bytes:
        if activity_type not in {"a", "b", "s"}:
            raise ValueError("activity_type must be one of: a, b, s")
        return self.get(f"{ACTIVITY_URL}?m={dataroma_code}&typ={activity_type}")

    def get_portfolio_history(self, dataroma_code: str) -> bytes:
        return self.get(f"{PORTFOLIO_HISTORY_URL}?f={dataroma_code}")

    def get_stock_history(self, dataroma_code: str, ticker: str) -> bytes:
        return self.get(f"{STOCK_HISTORY_URL}?f={dataroma_code}&s={ticker}")

    def close(self) -> None:
        self._rate_guard.close()

    def __enter__(self) -> "DataromaClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
