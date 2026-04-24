"""Parse Dataroma holdings.php HTML → CUSIP/ticker bootstrap data.

The holdings page table typically has columns: Stock, % of Portfolio, Shares, ...
The stock cell contains a link whose text is the ticker symbol; the title or
a sibling cell may contain the full company name.  CUSIP is not directly shown
on Dataroma — we capture ticker + issuer_name for cusip_ticker_map seeding.
"""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional


@dataclass
class DataromaHolding:
    ticker: str
    issuer_name: Optional[str]
    # CUSIP not available from Dataroma HTML; left empty for later enrichment
    cusip: Optional[str] = None


_TICKER_HREF_RE = re.compile(r"/m/holdings\.php\?stock=([A-Za-z0-9\.]+)", re.IGNORECASE)


class _HoldingsParser(HTMLParser):
    """
    Dataroma holdings table structure (simplified):
      <table>
        <tr>  (header)
        <tr>  (each holding)
          <td><a href="/m/holdings.php?stock=AAPL">Apple Inc</a></td>
          ...
        </tr>
      </table>
    We grab the first <a> in each data row that matches the stock href pattern.
    """

    def __init__(self) -> None:
        super().__init__()
        self.holdings: list[DataromaHolding] = []
        self._in_stock_link = False
        self._current_ticker: Optional[str] = None
        self._name_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return
        attr_dict = dict(attrs)
        href = attr_dict.get("href", "") or ""
        m = _TICKER_HREF_RE.search(href)
        if m:
            self._in_stock_link = True
            self._current_ticker = m.group(1).upper()
            self._name_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_stock_link:
            name = " ".join(self._name_parts).strip()
            if self._current_ticker:
                self.holdings.append(
                    DataromaHolding(
                        ticker=self._current_ticker,
                        issuer_name=name or None,
                    )
                )
            self._in_stock_link = False
            self._current_ticker = None

    def handle_data(self, data: str) -> None:
        if self._in_stock_link:
            self._name_parts.append(data)


def parse_holdings(html: bytes) -> list[DataromaHolding]:
    """Parse holdings.php HTML → list of DataromaHolding (ticker + name)."""
    text = html.decode("utf-8", errors="replace")
    parser = _HoldingsParser()
    parser.feed(text)

    # Deduplicate by ticker
    seen: set[str] = set()
    result: list[DataromaHolding] = []
    for h in parser.holdings:
        if h.ticker not in seen:
            seen.add(h.ticker)
            result.append(h)
    return result
