"""Parser for Dataroma manager Activity / Buys / Sells pages."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from typing import Optional

from app.dataroma.parsers.portfolio import (
    DataromaPageChanged,
    _Cell,
    _activity,
    _clean,
    _decimal,
    _integer,
    _issuer,
    _quarter,
    _ticker_from_href,
)


@dataclass(frozen=True)
class DataromaActivity:
    quarter: str
    ticker: str
    issuer_name: str | None
    action: str
    activity_pct: Decimal | None
    share_change: int
    portfolio_impact_pct: Decimal


class _ActivityHtmlParser(HTMLParser):
    """Collect cells in source order, including Dataroma's invalid bare td rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[tuple[str, list[_Cell]]] = []
        self._in_grid = False
        self._in_body = False
        self._cell: _Cell | None = None
        self._pending: list[_Cell] = []
        self._quarter: str | None = None
        self._quarter_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr = dict(attrs)
        if tag == "table" and attr.get("id") == "grid":
            self._in_grid = True
        elif tag == "tbody" and self._in_grid:
            self._in_body = True
        elif tag == "tr" and self._in_body and "q_chg" in (attr.get("class") or "").split():
            if self._pending:
                raise DataromaPageChanged("Dataroma activity quarter changed mid-row")
            self._quarter_cell = True
        elif tag == "td" and self._in_body:
            self._cell = _Cell()
        elif tag == "a" and self._cell is not None:
            self._cell.href = attr.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None:
            self._cell.text = _clean(self._cell.text)
            if self._quarter_cell:
                self._quarter = _quarter(self._cell.text)
                self._quarter_cell = False
            else:
                if not self._quarter:
                    raise DataromaPageChanged("Dataroma activity row appeared before a quarter")
                self._pending.append(self._cell)
                if len(self._pending) == 5:
                    self.records.append((self._quarter, self._pending))
                    self._pending = []
            self._cell = None
        elif tag == "tbody" and self._in_body:
            self._in_body = False
        elif tag == "table" and self._in_grid:
            self._in_grid = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.text += data


def parse_activity(html: bytes) -> tuple[DataromaActivity, ...]:
    parser = _ActivityHtmlParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    if parser._pending:
        raise DataromaPageChanged(
            f"Dataroma activity ended with {len(parser._pending)} incomplete cells"
        )
    if not parser.records:
        raise DataromaPageChanged("Dataroma activity grid was not found or had no activity")

    result: list[DataromaActivity] = []
    for quarter, cells in parser.records:
        ticker = _ticker_from_href(cells[1].href)
        if not ticker:
            raise DataromaPageChanged("Dataroma activity row has no stock ticker link")
        action, activity_pct = _activity(cells[2].text)
        if action is None:
            raise DataromaPageChanged("Dataroma activity row has no action")
        result.append(
            DataromaActivity(
                quarter=quarter,
                ticker=ticker,
                issuer_name=_issuer(cells[1].text, ticker),
                action=action,
                activity_pct=activity_pct,
                share_change=_integer(cells[3].text, "share change"),
                portfolio_impact_pct=_decimal(cells[4].text, "portfolio impact"),
            )
        )
    return tuple(result)

