"""OpenFIGI API Client."""

import json
import logging
import time
from typing import Any, List, Dict

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class OpenFigiClient:
    """Client for OpenFIGI API with rate limiting and stub fallback."""
    
    BASE_URL = "https://api.openfigi.com/v3/mapping"
    
    def __init__(self, api_key: str | None = None, use_stub: bool = False):
        self.api_key = api_key or settings.OPENFIGI_API_KEY
        self.use_stub = use_stub
        # Rate limits: without key 25 req/min (2.4s delay), with key 250 req/min (0.24s delay)
        self.delay_s = 0.25 if self.api_key else 2.5
        self._last_request_time = 0.0

    def _wait_for_rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.delay_s:
            time.sleep(self.delay_s - elapsed)
        self._last_request_time = time.time()

    def map_cusips(self, cusips: List[str]) -> List[List[Dict[str, Any]]]:
        """Map a batch of CUSIPs to FIGI objects.
        
        Returns a list of results corresponding to each CUSIP.
        If a CUSIP has no matches, the corresponding result is an empty list.
        """
        if self.use_stub or (not self.api_key and settings.EDGAR_FETCH_MODE == "replay"):
            # Stub mode: return dummy match for testing purposes
            logger.debug("OpenFIGI: using stub fallback for %d CUSIPs", len(cusips))
            return self._stub_mapping(cusips)

        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in cusips]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key

        self._wait_for_rate_limit()

        try:
            with httpx.Client(timeout=10.0) as http_client:
                response = http_client.post(self.BASE_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            
            # API returns a list of {"data": [...]} or {"error": "..."} in the same order
            results = []
            for item in data:
                if "data" in item:
                    results.append(item["data"])
                else:
                    results.append([])
            return results
            
        except Exception as exc:
            logger.error("OpenFIGI mapping failed: %s", exc)
            raise

    def _stub_mapping(self, cusips: List[str]) -> List[List[Dict[str, Any]]]:
        """Return dummy mapping data for tests/local dev without a key."""
        results = []
        for c in cusips:
            if c.startswith("0000"):
                # Simulate invalid / no match
                results.append([])
            elif c.startswith("9999"):
                # Simulate multiple matches (ambiguous)
                results.append([
                    {"ticker": "DUMMY1", "name": "Dummy Corp", "securityType": "Common Stock", "exchCode": "US"},
                    {"ticker": "DUMMY2", "name": "Dummy Corp", "securityType": "Common Stock", "exchCode": "US"}
                ])
            else:
                # Simulate single exact match
                results.append([
                    {"ticker": f"TICKER_{c[:4]}", "name": "Mocked Company Inc", "securityType": "Common Stock", "exchCode": "US"}
                ])
        return results
