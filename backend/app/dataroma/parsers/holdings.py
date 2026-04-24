"""Parse Dataroma holdings.php HTML → ticker/name bootstrap data.

Current page structure (as of 2026):
  <td class="stock">
    <a href="/m/stock.php?sym=AAPL">AAPL<span> - Apple Inc.</span></a>
  </td>

CUSIP is not shown on Dataroma — we capture ticker + issuer_name only.
"""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional


@dataclass
class DataromaHolding:
    ticker: str
    issuer_name: Optional[str]
    cusip: Optional[str] = None


_TICKER_HREF_RE = re.compile(
    r"/m/stock\.php\?sym=([A-Za-z0-9\.\-]+)"   # current format
    r"|/m/holdings\.php\?stock=([A-Za-z0-9\.]+)",  # legacy format
    re.IGNORECASE,
)


class _HoldingsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.holdings: list[DataromaHolding] = []
        self._in_stock_link = False
        self._current_ticker: Optional[str] = None
        self._in_span = False
        self._span_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href", "") or ""
            m = _TICKER_HREF_RE.search(href)
            if m:
                self._current_ticker = (m.group(1) or m.group(2) or "").upper()
                self._in_stock_link = True
                self._in_span = False
                self._span_parts = []
        elif tag == "span" and self._in_stock_link:
            self._in_span = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._in_stock_link:
            self._in_span = False
        elif tag == "a" and self._in_stock_link:
            name = " ".join(self._span_parts).strip()
            # Strip leading " - " separator
            name = re.sub(r"^[\s\-]+", "", name).strip()
            if self._current_ticker:
                self.holdings.append(
                    DataromaHolding(ticker=self._current_ticker, issuer_name=name or None)
                )
            self._in_stock_link = False
            self._current_ticker = None
            self._in_span = False
            self._span_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_stock_link and self._in_span:
            self._span_parts.append(data)


def parse_holdings(html: bytes) -> list[DataromaHolding]:
    """Parse holdings.php HTML → list of DataromaHolding (ticker + name)."""
    text = html.decode("utf-8", errors="replace")
    parser = _HoldingsParser()
    parser.feed(text)

    seen: set[str] = set()
    result: list[DataromaHolding] = []
    for h in parser.holdings:
        if h.ticker not in seen:
            seen.add(h.ticker)
            result.append(h)
    return result
