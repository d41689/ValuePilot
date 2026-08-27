"""Parser for Dataroma's manager portfolio-history page."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
import re
from typing import Optional

from app.dataroma.parsers.portfolio import (
    DataromaPageChanged,
    _Cell,
    _clean,
    _decimal,
    _ticker_from_href,
)


@dataclass(frozen=True)
class DataromaHistoricalHolding:
    ticker: str
    portfolio_weight_pct: Decimal | None


@dataclass(frozen=True)
class DataromaPortfolioHistory:
    quarter: str
    portfolio_value_usd: Decimal
    portfolio_value_display: str
    top_holdings: tuple[DataromaHistoricalHolding, ...]


@dataclass
class _HistoryCell(_Cell):
    link_title: str | None = None


class _HistoryHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_HistoryCell]] = []
        self._in_grid = False
        self._in_body = False
        self._row: list[_HistoryCell] | None = None
        self._cell: _HistoryCell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr = dict(attrs)
        if tag == "table" and attr.get("id") == "grid":
            self._in_grid = True
        elif tag == "tbody" and self._in_grid:
            self._in_body = True
        elif tag == "tr" and self._in_body:
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = _HistoryCell()
        elif tag == "a" and self._cell is not None:
            self._cell.href = attr.get("href")
            self._cell.link_title = attr.get("title")

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self._row is not None:
            self._cell.text = _clean(self._cell.text)
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "tbody" and self._in_body:
            self._in_body = False
        elif tag == "table" and self._in_grid:
            self._in_grid = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.text += data


def parse_portfolio_history(html: bytes) -> tuple[DataromaPortfolioHistory, ...]:
    parser = _HistoryHtmlParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    if not parser.rows:
        raise DataromaPageChanged("Dataroma portfolio history grid was not found or had no rows")
    result: list[DataromaPortfolioHistory] = []
    for cells in parser.rows:
        if len(cells) < 2:
            raise DataromaPageChanged("Dataroma portfolio history row has fewer than 2 cells")
        quarter = _history_quarter(cells[0].text)
        holdings: list[DataromaHistoricalHolding] = []
        for cell in cells[2:]:
            ticker = _ticker_from_href(cell.href)
            if not ticker:
                continue
            title = cell.link_title or cell.text
            match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s+of\s+portfolio", title, re.IGNORECASE)
            holdings.append(
                DataromaHistoricalHolding(
                    ticker=ticker,
                    portfolio_weight_pct=_decimal(match.group(1), "history weight") if match else None,
                )
            )
        result.append(
            DataromaPortfolioHistory(
                quarter=quarter,
                portfolio_value_usd=_scaled_money(cells[1].text),
                portfolio_value_display=cells[1].text,
                top_holdings=tuple(holdings),
            )
        )
    return tuple(result)


def _history_quarter(value: str) -> str:
    match = re.fullmatch(r"(\d{4})\s+Q([1-4])", _clean(value), re.IGNORECASE)
    if not match:
        raise DataromaPageChanged(f"Unrecognized Dataroma history quarter: {value!r}")
    return f"{match.group(1)}-Q{match.group(2)}"


def _scaled_money(value: str) -> Decimal:
    match = re.fullmatch(r"\$?\s*([0-9,.]+)\s*([KMBT])?", _clean(value), re.IGNORECASE)
    if not match:
        raise DataromaPageChanged(f"Unrecognized Dataroma history value: {value!r}")
    scale = {None: 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}
    return _decimal(match.group(1), "history portfolio value") * scale[match.group(2).upper() if match.group(2) else None]
