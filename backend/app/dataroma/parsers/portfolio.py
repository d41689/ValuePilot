"""Strict parser for Dataroma's current manager holdings page.

Dataroma is corroborating evidence only.  The parser intentionally fails on a
structural/count mismatch so an upstream redesign cannot silently produce an
empty reconciliation that looks like agreement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse


class DataromaPageChanged(ValueError):
    """The response was HTML, but not the Dataroma page contract we parse."""


@dataclass(frozen=True)
class DataromaPortfolioHolding:
    ticker: str
    issuer_name: str | None
    portfolio_weight_pct: Decimal
    activity: str | None
    activity_pct: Decimal | None
    shares: int
    reported_price: Decimal
    value_usd: int
    current_price: Decimal | None
    change_since_report_pct: Decimal | None
    week_52_low: Decimal | None
    week_52_high: Decimal | None


@dataclass(frozen=True)
class DataromaPortfolio:
    manager_name: str
    quarter: str
    portfolio_date: date
    position_count: int
    portfolio_value_usd: int
    holdings: tuple[DataromaPortfolioHolding, ...]


@dataclass
class _Cell:
    text: str = ""
    href: str | None = None


class _PortfolioHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.manager_parts: list[str] = []
        self.summary_spans: list[str] = []
        self.rows: list[list[_Cell]] = []
        self.saw_grid = False
        self._in_manager = False
        self._in_summary = False
        self._in_summary_span = False
        self._summary_span_parts: list[str] = []
        self._in_grid = False
        self._in_body = False
        self._row: list[_Cell] | None = None
        self._cell: _Cell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr = dict(attrs)
        if tag == "div" and attr.get("id") == "f_name":
            self._in_manager = True
        elif tag == "p" and attr.get("id") == "p2":
            self._in_summary = True
        elif tag == "span" and self._in_summary:
            self._in_summary_span = True
            self._summary_span_parts = []
        elif tag == "table" and attr.get("id") == "grid":
            self._in_grid = True
            self.saw_grid = True
        elif tag == "tbody" and self._in_grid:
            self._in_body = True
        elif tag == "tr" and self._in_grid and self._in_body:
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = _Cell()
        elif tag == "a" and self._cell is not None:
            self._cell.href = attr.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_manager:
            self._in_manager = False
        elif tag == "span" and self._in_summary_span:
            self.summary_spans.append(_clean("".join(self._summary_span_parts)))
            self._in_summary_span = False
        elif tag == "p" and self._in_summary:
            self._in_summary = False
        elif tag == "td" and self._cell is not None and self._row is not None:
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
        if self._in_manager:
            self.manager_parts.append(data)
        if self._in_summary_span:
            self._summary_span_parts.append(data)
        if self._cell is not None:
            self._cell.text += data


def parse_portfolio(html: bytes, *, allow_partial: bool = False) -> DataromaPortfolio:
    parser = _PortfolioHtmlParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    if not parser.saw_grid:
        raise DataromaPageChanged("Dataroma holdings grid was not found")
    if len(parser.summary_spans) != 4:
        raise DataromaPageChanged(
            f"Dataroma holdings summary expected 4 values, parsed {len(parser.summary_spans)}"
        )

    period, portfolio_date, position_count, portfolio_value = parser.summary_spans
    declared_count = _integer(position_count, "position count")
    if not parser.rows and declared_count != 0:
        raise DataromaPageChanged("Dataroma holdings grid was not found or had no rows")
    holdings: list[DataromaPortfolioHolding] = []
    for cells in parser.rows:
        if len(cells) < 12:
            raise DataromaPageChanged(
                f"Dataroma holdings row expected 12 cells, parsed {len(cells)}"
            )
        ticker = _ticker_from_href(cells[1].href)
        if not ticker:
            raise DataromaPageChanged("Dataroma holdings row has no stock ticker link")
        activity, activity_pct = _activity(cells[3].text)
        holdings.append(
            DataromaPortfolioHolding(
                ticker=ticker,
                issuer_name=_issuer(cells[1].text, ticker),
                portfolio_weight_pct=_decimal(cells[2].text, "portfolio weight"),
                activity=activity,
                activity_pct=activity_pct,
                shares=_integer(cells[4].text, "shares"),
                reported_price=_money_decimal(cells[5].text, "reported price"),
                value_usd=_money_integer(cells[6].text, "reported value"),
                current_price=_optional_money(cells[8].text),
                change_since_report_pct=_optional_decimal(cells[9].text),
                week_52_low=_optional_money(cells[10].text),
                week_52_high=_optional_money(cells[11].text),
            )
        )

    if declared_count != len(holdings) and not allow_partial:
        raise DataromaPageChanged(
            f"Dataroma declares {declared_count} positions but parsed {len(holdings)}"
        )
    parsed_date = _date(portfolio_date)
    expected_quarter = _quarter_from_date(parsed_date)
    parsed_quarter = _quarter(period)
    if parsed_quarter != expected_quarter:
        raise DataromaPageChanged(
            f"Dataroma period {parsed_quarter} conflicts with portfolio date {parsed_date}"
        )
    manager_name = _clean("".join(parser.manager_parts))
    if not manager_name:
        raise DataromaPageChanged("Dataroma manager name was not found")
    return DataromaPortfolio(
        manager_name=manager_name,
        quarter=parsed_quarter,
        portfolio_date=parsed_date,
        position_count=declared_count,
        portfolio_value_usd=(
            0 if portfolio_value.strip() in {"", "$"}
            else _money_integer(portfolio_value, "portfolio value")
        ),
        holdings=tuple(holdings),
    )


def merge_portfolio_pages(pages: tuple[DataromaPortfolio, ...]) -> DataromaPortfolio:
    """Merge explicitly fetched Dataroma ``L=`` pages and validate completeness."""
    if not pages:
        raise DataromaPageChanged("No Dataroma portfolio pages were supplied")
    first = pages[0]
    holdings: list[DataromaPortfolioHolding] = []
    seen: set[str] = set()
    for page in pages:
        if (
            page.manager_name != first.manager_name
            or page.quarter != first.quarter
            or page.portfolio_date != first.portfolio_date
            or page.position_count != first.position_count
            or page.portfolio_value_usd != first.portfolio_value_usd
        ):
            raise DataromaPageChanged("Dataroma holdings pagination summaries disagree")
        for holding in page.holdings:
            if holding.ticker in seen:
                raise DataromaPageChanged(
                    f"Dataroma holdings pagination repeated ticker {holding.ticker}"
                )
            seen.add(holding.ticker)
            holdings.append(holding)
    if len(holdings) != first.position_count:
        raise DataromaPageChanged(
            f"Dataroma declares {first.position_count} positions but paginated evidence contains {len(holdings)}"
        )
    return DataromaPortfolio(
        manager_name=first.manager_name,
        quarter=first.quarter,
        portfolio_date=first.portfolio_date,
        position_count=first.position_count,
        portfolio_value_usd=first.portfolio_value_usd,
        holdings=tuple(holdings),
    )


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _ticker_from_href(href: str | None) -> str | None:
    if not href:
        return None
    values = parse_qs(urlparse(href).query).get("sym")
    return values[0].upper() if values else None


def _issuer(text: str, ticker: str) -> str | None:
    value = re.sub(rf"^{re.escape(ticker)}\s*-\s*", "", text, flags=re.IGNORECASE).strip()
    return value or None


def _quarter(value: str) -> str:
    match = re.fullmatch(r"Q([1-4])\s+(\d{4})", _clean(value), flags=re.IGNORECASE)
    if not match:
        raise DataromaPageChanged(f"Unrecognized Dataroma quarter: {value!r}")
    return f"{match.group(2)}-Q{match.group(1)}"


def _quarter_from_date(value: date) -> str:
    return f"{value.year}-Q{((value.month - 1) // 3) + 1}"


def _date(value: str) -> date:
    try:
        return datetime.strptime(value, "%d %b %Y").date()
    except ValueError as exc:
        raise DataromaPageChanged(f"Unrecognized Dataroma portfolio date: {value!r}") from exc


def _decimal(value: str, field: str) -> Decimal:
    cleaned = value.strip().replace(",", "").replace("%", "").replace("$", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise DataromaPageChanged(f"Invalid Dataroma {field}: {value!r}") from exc


def _optional_decimal(value: str) -> Decimal | None:
    return _decimal(value, "decimal") if value.strip() not in {"", "%", "-", "N/A"} else None


def _integer(value: str, field: str) -> int:
    number = _decimal(value, field)
    if number != number.to_integral_value():
        raise DataromaPageChanged(f"Dataroma {field} is not an integer: {value!r}")
    return int(number)


def _money_integer(value: str, field: str) -> int:
    return _integer(value, field)


def _money_decimal(value: str, field: str) -> Decimal:
    return _decimal(value, field)


def _optional_money(value: str) -> Decimal | None:
    return _money_decimal(value, "money") if value.strip() not in {"", "-", "N/A"} else None


def _activity(value: str) -> tuple[str | None, Decimal | None]:
    cleaned = _clean(value)
    if not cleaned:
        return None, None
    match = re.fullmatch(r"(Add|Buy|Reduce|Sell)(?:\s+([0-9.,]+)%)?", cleaned, re.IGNORECASE)
    if not match:
        raise DataromaPageChanged(f"Unrecognized Dataroma activity: {value!r}")
    return match.group(1).lower(), (_decimal(match.group(2), "activity percent") if match.group(2) else None)
