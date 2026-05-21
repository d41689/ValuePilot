"""Dataroma HTTP client — routes through the Rate Guard egress service.

Rate limiting, retry, and the browser User-Agent are owned by Rate Guard; this
client just names the Dataroma pages and forwards each GET.
"""
import httpx

from app.rate_guard.client import RateGuardClient

MANAGERS_URL = "https://www.dataroma.com/m/managers.php"
HOLDINGS_URL = "https://www.dataroma.com/m/holdings.php"


class DataromaClient:
    """Fetches Dataroma pages through the Rate Guard egress service."""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._rate_guard = RateGuardClient(http_client)

    def get(self, url: str) -> bytes:
        return self._rate_guard.fetch(upstream="dataroma", method="GET", url=url)

    def get_managers(self) -> bytes:
        return self.get(MANAGERS_URL)

    def get_holdings(self, dataroma_code: str) -> bytes:
        return self.get(f"{HOLDINGS_URL}?m={dataroma_code}")

    def close(self) -> None:
        self._rate_guard.close()

    def __enter__(self) -> "DataromaClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
