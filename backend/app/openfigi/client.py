"""OpenFIGI client — routes through the Rate Guard egress service.

Rate limiting and the OpenFIGI API key are owned by Rate Guard; this client
builds the ``/v3/mapping`` request and unwraps the response. A stub path serves
tests / replay mode without any network.
"""
import json
import logging
from typing import Any, Dict, List

import httpx

from app.core.config import settings
from app.rate_guard.client import RateGuardClient

logger = logging.getLogger(__name__)


class OpenFigiClient:
    """Maps CUSIPs to FIGI / ticker objects via the OpenFIGI API."""

    BASE_URL = "https://api.openfigi.com/v3/mapping"

    def __init__(
        self, use_stub: bool = False, http_client: httpx.Client | None = None
    ) -> None:
        self.use_stub = use_stub
        self._rate_guard = RateGuardClient(http_client)

    def map_cusips(self, cusips: List[str]) -> List[List[Dict[str, Any]]]:
        """Map a batch of CUSIPs to FIGI objects — one result list per CUSIP.

        A CUSIP with no matches yields an empty list at its position.
        """
        if self.use_stub or settings.EDGAR_FETCH_MODE == "replay":
            logger.debug("OpenFIGI: using stub fallback for %d CUSIPs", len(cusips))
            return self._stub_mapping(cusips)

        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
        body = json.dumps(payload).encode("utf-8")
        raw = self._rate_guard.fetch(
            upstream="openfigi", method="POST", url=self.BASE_URL, body=body
        )
        # OpenFIGI returns a list of {"data": [...]} or {"error": "..."}, in
        # the same order as the request.
        data = json.loads(raw)
        return [item["data"] if "data" in item else [] for item in data]

    def _stub_mapping(self, cusips: List[str]) -> List[List[Dict[str, Any]]]:
        """Deterministic dummy mapping for tests / replay mode (no network)."""
        results: List[List[Dict[str, Any]]] = []
        for c in cusips:
            if c.startswith("0000"):
                # Simulate invalid / no match.
                results.append([])
            elif c.startswith("9999"):
                # Simulate multiple matches (ambiguous).
                results.append([
                    {"ticker": "DUMMY1", "name": "Dummy Corp", "securityType": "Common Stock", "exchCode": "US"},
                    {"ticker": "DUMMY2", "name": "Dummy Corp", "securityType": "Common Stock", "exchCode": "US"},
                ])
            else:
                # Simulate a single exact match.
                results.append([
                    {"ticker": f"TICKER_{c[:4]}", "name": "Mocked Company Inc", "securityType": "Common Stock", "exchCode": "US"}
                ])
        return results

    def close(self) -> None:
        self._rate_guard.close()

    def __enter__(self) -> "OpenFigiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
