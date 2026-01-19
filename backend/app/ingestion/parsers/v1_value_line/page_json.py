import calendar
import re
from typing import Any, Optional

from app.ingestion.normalization.scaler import Scaler
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser


def build_value_line_page_json(parser: ValueLineV1Parser, *, page_number: int) -> dict[str, Any]:
    results = parser.parse()
    by_key = {res.field_key: res for res in results}
    identity = parser.extract_identity()

    report_date = _report_date(by_key)

    output = {
        "meta": {
            "parser_version": "value_line_v1",
            "page_number": page_number,
            "report_date": report_date,
            "source": "value_line",
        },
        "identity": {
            "company_name": identity.company_name,
            "ticker": identity.ticker,
            "exchange": identity.exchange,
        },
        "header": _build_header(by_key),
        "ratings": _build_ratings(by_key),
        "quality_metrics": _build_quality_metrics(by_key),
        "target_price_18m": _build_target_18m(by_key),
        "long_term_projection": _build_long_term_projection(by_key),
        "institutional_decisions": _build_institutional_decisions(by_key),
        "capital_structure": _build_capital_structure(by_key),
        "financial_position": _build_financial_position(by_key),
        "annual_rates": _build_annual_rates(parser.text, by_key),
        "net_premiums_earned": _build_quarterly_block(
            by_key.get("quarterly_sales_usd_millions"),
            unit="USD_millions",
            report_date=report_date,
        ),
        "earnings_per_share": _build_quarterly_block(
            by_key.get("earnings_per_share"),
            unit="USD_per_share",
            report_date=report_date,
        ),
        "quarterly_dividends_paid": _build_quarterly_block(
            by_key.get("quarterly_dividends_paid_per_share"),
            unit="USD_per_share",
            report_date=report_date,
            add_missing_report_year=True,
        ),
        "annual_financials": _build_annual_financials(by_key),
        "total_return": _build_total_return(by_key),
        "historical_price_range": _build_historical_price_range(by_key),
        "narrative": _build_narrative(by_key, report_date),
    }

    return output


def _report_date(by_key: dict[str, Any]) -> Optional[str]:
    res = by_key.get("report_date")
    if not res:
        return None
    if isinstance(res.parsed_value_json, dict):
        iso = res.parsed_value_json.get("iso_date")
        if iso:
            return iso
    return res.raw_value_text


def _to_number(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    raw = value.strip().replace(",", "")
    if raw.upper() in {"--", "NMF", "NIL"}:
        return None
    if raw.startswith("."):
        raw = f"0{raw}"
    if raw.endswith("%"):
        raw = raw[:-1]
    try:
        return float(raw)
    except ValueError:
        return None


def _format_pct_display(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    raw = raw.strip()
    if raw.startswith(("+", "-")):
        return raw
    if raw.endswith("%"):
        return f"+{raw}"
    return f"+{raw}%"


def _build_header(by_key: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_price": _to_number(_raw(by_key, "recent_price")),
        "pe_ratio": _to_number(_raw(by_key, "pe_ratio")),
        "pe_ratio_trailing": _to_number(_raw(by_key, "pe_ratio_trailing")),
        "pe_ratio_median": _to_number(_raw(by_key, "pe_ratio_median")),
        "relative_pe_ratio": _to_number(_raw(by_key, "relative_pe_ratio")),
        "dividend_yield_pct": _to_number(_raw(by_key, "dividend_yield")),
    }


def _build_ratings(by_key: dict[str, Any]) -> dict[str, Any]:
    ratings = {}
    for key in ("timeliness", "safety", "technical"):
        res = by_key.get(key)
        value = res.parsed_value_json.get("value") if res and res.parsed_value_json else None
        notes = res.parsed_value_json.get("notes") if res and res.parsed_value_json else None
        event = _parse_event(notes)
        ratings[key] = {"value": value, "event": event} if event else {"value": value}

    beta_res = by_key.get("beta")
    beta_display = _raw(by_key, "beta")
    beta_norm, beta_unit = (None, None)
    if beta_display:
        beta_norm, beta_unit = Scaler.normalize(beta_display, "ratio")
    beta_notes = _extract_parenthetical(getattr(beta_res, "original_text_snippet", None))
    ratings["beta"] = {
        "display": beta_display,
        "normalized": beta_norm,
        "unit": beta_unit,
        "notes": beta_notes,
    }

    return ratings


def _build_quality_metrics(by_key: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_financial_strength": {
            "value": _raw(by_key, "company_financial_strength"),
            "scale": "letter_grade",
        },
        "stock_price_stability": {
            "value": _to_number(_raw(by_key, "stock_price_stability")),
            "scale": "0-100",
        },
        "price_growth_persistence": {
            "value": _to_number(_raw(by_key, "price_growth_persistence")),
            "scale": "0-100",
        },
        "earnings_predictability": {
            "value": _to_number(_raw(by_key, "earnings_predictability")),
            "scale": "0-100",
        },
    }


def _build_target_18m(by_key: dict[str, Any]) -> dict[str, Any]:
    low = _raw(by_key, "target_18m_low")
    high = _raw(by_key, "target_18m_high")
    mid = _raw(by_key, "target_18m_mid")
    pct = _raw(by_key, "target_18m_upside_pct")
    pct_norm, _ = Scaler.normalize(pct, "percent") if pct else (None, None)
    return {
        "period_type": "target_horizon",
        "horizon_months": 18,
        "range": {
            "low": {"display": f"${low}" if low else None, "normalized": _to_number(low), "unit": "USD"},
            "high": {"display": f"${high}" if high else None, "normalized": _to_number(high), "unit": "USD"},
        },
        "midpoint": {
            "price": {"display": f"${mid}" if mid else None, "normalized": _to_number(mid), "unit": "USD"},
            "pct_to_mid": {"display": pct, "normalized": pct_norm, "unit": "ratio"},
        },
    }


def _build_long_term_projection(by_key: dict[str, Any]) -> dict[str, Any]:
    high_price = _raw(by_key, "long_term_projection_high_price")
    low_price = _raw(by_key, "long_term_projection_low_price")
    high_gain = _raw(by_key, "long_term_projection_high_price_gain_pct")
    low_gain = _raw(by_key, "long_term_projection_low_price_gain_pct")
    high_return = _raw(by_key, "long_term_projection_high_total_return_pct")
    low_return = _raw(by_key, "long_term_projection_low_total_return_pct")

    high_gain_norm, _ = Scaler.normalize(high_gain, "percent") if high_gain else (None, None)
    low_gain_norm, _ = Scaler.normalize(low_gain, "percent") if low_gain else (None, None)
    high_return_norm, _ = Scaler.normalize(high_return, "percent") if high_return else (None, None)
    low_return_norm, _ = Scaler.normalize(low_return, "percent") if low_return else (None, None)

    return {
        "projection_year_range": _raw(by_key, "long_term_projection_year_range"),
        "period_type": "projection_range",
        "scenarios": {
            "high": {
                "price": {"display": high_price, "normalized": _to_number(high_price), "unit": "USD"},
                "price_gain": {
                    "display": _format_pct_display(high_gain),
                    "normalized": high_gain_norm,
                    "unit": "ratio",
                },
                "annual_total_return": {
                    "display": high_return,
                    "normalized": high_return_norm,
                    "unit": "ratio",
                },
            },
            "low": {
                "price": {"display": low_price, "normalized": _to_number(low_price), "unit": "USD"},
                "price_gain": {
                    "display": _format_pct_display(low_gain),
                    "normalized": low_gain_norm,
                    "unit": "ratio",
                },
                "annual_total_return": {
                    "display": low_return,
                    "normalized": low_return_norm,
                    "unit": "ratio",
                },
            },
        },
    }


def _build_institutional_decisions(by_key: dict[str, Any]) -> dict[str, Any]:
    res = by_key.get("institutional_decisions")
    if not res or not res.parsed_value_json:
        return {"unit": {"hlds": "thousand_shares"}, "by_quarter": []}

    quarterly = res.parsed_value_json.get("quarterly", [])
    rows = []
    for row in quarterly:
        period = row.get("period")
        year, quarter = _parse_period(period)
        period_end_date = _quarter_end_date(year, quarter) if year and quarter else None
        rows.append({
            "period": period,
            "period_type": "Q",
            "period_end_date": period_end_date,
            "to_buy": row.get("to_buy"),
            "to_sell": row.get("to_sell"),
            "holdings_thousand_shares": row.get("holds_000"),
        })

    return {
        "unit": {"hlds": "thousand_shares"},
        "by_quarter": rows,
    }


def _build_capital_structure(by_key: dict[str, Any]) -> dict[str, Any]:
    cap = {
        "as_of": _raw(by_key, "capital_structure_as_of"),
        "total_debt": _money_entry(_raw(by_key, "total_debt")),
        "debt_due_in_5_years": _money_entry(_raw(by_key, "debt_due_in_5_years")),
        "lt_debt": _money_entry(_raw(by_key, "lt_debt")),
        "lt_interest": _money_entry(_raw(by_key, "lt_interest")),
        "debt_percent_of_capital": _percent_entry(_raw(by_key, "debt_percent_of_capital")),
        "pension_plan": None,
        "preferred_stock": _money_entry(_raw(by_key, "preferred_stock")),
        "preferred_dividend": _money_entry(_raw(by_key, "preferred_dividend")),
    }

    shares = by_key.get("common_stock_shares_outstanding")
    shares_as_of = None
    if shares and isinstance(shares.parsed_value_json, dict):
        shares_as_of = shares.parsed_value_json.get("as_of")
    cap["common_stock_shares_outstanding"] = {
        "display": _raw(by_key, "common_stock_shares_outstanding"),
        "normalized": _to_number(_raw(by_key, "common_stock_shares_outstanding")),
        "unit": "shares",
        "as_of": shares_as_of,
    }

    market_cap = _money_entry(_raw(by_key, "market_cap"))
    market_cap["notes"] = None
    mkt_as_of = _raw(by_key, "market_cap_as_of")
    market_cap["as_of"] = mkt_as_of
    cap["market_cap"] = market_cap

    return cap


def _build_financial_position(by_key: dict[str, Any]) -> Optional[dict[str, Any]]:
    res = by_key.get("financial_position_usd_millions")
    return res.parsed_value_json if res and res.parsed_value_json else None


def _build_annual_rates(text: str, by_key: dict[str, Any]) -> dict[str, Any]:
    res = by_key.get("annual_rates_of_change")
    parsed = res.parsed_value_json if res and res.parsed_value_json else {}
    from_period, to_period = _annual_rates_periods(text)

    metrics = []
    for metric_key in ("premium_income", "investment_income", "earnings", "dividends", "book_value"):
        data = parsed.get(metric_key)
        if not data:
            metrics.append({
                "metric_key": metric_key,
                "past_10y_cagr_pct": None,
                "past_5y_cagr_pct": None,
                "estimated_cagr_pct": None,
            })
            continue

        past_10y = _ratio_to_pct(data.get("past_10y"))
        past_5y = _ratio_to_pct(data.get("past_5y"))
        est = _ratio_to_pct(data.get("est_to_2028_2030"))
        metric = {
            "metric_key": metric_key,
            "past_10y_cagr_pct": past_10y,
            "past_5y_cagr_pct": past_5y,
            "estimated_cagr_pct": {
                "from_period": from_period,
                "to_period": to_period,
                "value": est,
            },
        }
        note = data.get("past_5y_note")
        if note:
            metric["past_5y_note"] = note
        metrics.append(metric)

    return {"unit": "per_share", "metrics": metrics}


def _build_quarterly_block(
    res: Any,
    *,
    unit: str,
    report_date: Optional[str],
    add_missing_report_year: bool = False,
) -> dict[str, Any]:
    rows = res.parsed_value_json if res and res.parsed_value_json else []
    report_year = int(report_date[:4]) if report_date else None
    by_year = []
    for row in rows:
        year = row.get("calendar_year")
        quarters = {
            "Q1": {"period_end": _quarter_end_date(year, 1), "value": row.get("mar_31")},
            "Q2": {"period_end": _quarter_end_date(year, 2), "value": row.get("jun_30")},
            "Q3": {"period_end": _quarter_end_date(year, 3), "value": row.get("sep_30")},
            "Q4": {"period_end": _quarter_end_date(year, 4), "value": row.get("dec_31")},
        }
        is_estimated = report_year is not None and year is not None and year >= report_year - 1
        by_year.append({
            "calendar_year": year,
            "quarters": quarters,
            "full_year": {"value": row.get("full_year"), "is_estimated": is_estimated},
        })

    if add_missing_report_year and report_year:
        last_year = by_year[-1]["calendar_year"] if by_year else None
        if last_year is None or last_year < report_year:
            by_year.append({
                "calendar_year": report_year,
                "quarters": None,
                "full_year": {
                    "value": None,
                    "is_estimated": True,
                    "notes": "No quarterly or full-year dividend values provided in report",
                },
            })
        else:
            by_year[-1]["full_year"]["is_estimated"] = True

    return {"unit": unit, "by_year": by_year}


def _build_annual_financials(by_key: dict[str, Any]) -> dict[str, Any]:
    res = by_key.get("tables_time_series")
    if not res or not res.parsed_value_json:
        return {"meta": {}}

    annual = res.parsed_value_json.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {})
    years = annual.get("years", [])
    projection_range = annual.get("projection_year_range")
    projection = annual.get("projection_2028_2030", {})

    per_share = _series_group_to_year_map(
        annual.get("per_share", {}),
        years,
        projection,
        keys=[
            "pc_prem_earned_per_share_usd",
            "investment_income_per_share_usd",
            "underwriting_income_per_share_usd",
            "earnings_per_share_usd",
            "dividends_declared_per_share_usd",
            "book_value_per_share_usd",
            "common_shares_outstanding_millions",
        ],
    )
    valuation = _series_group_to_year_map(
        annual.get("valuation", {}),
        years,
        projection,
        keys=[
            "price_to_book_value_pct",
            "avg_annual_pe_ratio",
            "relative_pe_ratio",
            "avg_annual_dividend_yield_pct",
        ],
        drop_trailing_null=True,
    )
    income_statement = _series_group_to_year_map(
        annual.get("income_statement_usd_millions", {}),
        years,
        projection,
        keys=["net_profit"],
    )
    balance_sheet = _series_group_to_year_map(
        annual.get("balance_sheet_and_returns_usd_millions", {}),
        years,
        projection,
        keys=["total_assets", "shareholders_equity"],
    )

    return {
        "meta": {
            "source": "value_line",
            "table_type": "annual_financials_and_ratios",
            "currency": "USD",
            "historical_years": years,
            "projection_year_range": projection_range,
        },
        "per_share_metrics": per_share,
        "valuation_metrics": valuation,
        "income_statement_usd_millions": income_statement,
        "balance_sheet_and_returns_usd_millions": balance_sheet,
    }


def _build_total_return(by_key: dict[str, Any]) -> dict[str, Any]:
    res = by_key.get("price_semantics_and_returns")
    parsed = res.parsed_value_json if res and res.parsed_value_json else {}
    total_return = parsed.get("total_return", {})
    as_of_date = parsed.get("value_line_total_return_as_of")

    series = []
    for window in (1, 3, 5):
        value = total_return.get("stock", {}).get(f"{window}y")
        series.append({
            "name": "this_stock",
            "window_years": window,
            "value_pct": _ratio_to_pct(value),
        })
    for window in (1, 3, 5):
        value = total_return.get("index", {}).get(f"{window}y")
        series.append({
            "name": "vl_arithmetic_index",
            "window_years": window,
            "value_pct": _ratio_to_pct(value),
        })

    return {
        "as_of_date": as_of_date,
        "unit": "percent",
        "source": "value_line",
        "series": series,
    }


def _build_historical_price_range(by_key: dict[str, Any]) -> list[dict[str, Any]]:
    res = by_key.get("tables_time_series")
    if not res or not res.parsed_value_json:
        return []

    annual = res.parsed_value_json.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {})
    years = annual.get("years", [])
    prices = res.parsed_value_json.get("price_history_high_low", {})
    highs = prices.get("high", [])
    lows = prices.get("low", [])

    rows = []
    for idx, year in enumerate(years):
        rows.append({
            "year": year,
            "high": highs[idx] if idx < len(highs) else None,
            "low": lows[idx] if idx < len(lows) else None,
        })
    return rows


def _build_narrative(by_key: dict[str, Any], report_date: Optional[str]) -> dict[str, Any]:
    analyst = by_key.get("analyst_name")
    analyst_name = None
    if analyst and isinstance(analyst.parsed_value_json, dict):
        analyst_name = analyst.parsed_value_json.get("value")
    if analyst_name is None:
        analyst_name = _raw(by_key, "analyst_name")

    return {
        "business": _raw(by_key, "business_description"),
        "analyst_commentary": _raw(by_key, "analyst_commentary"),
        "analyst_name": analyst_name,
        "commentary_date": report_date,
    }


def _raw(by_key: dict[str, Any], key: str) -> Optional[str]:
    res = by_key.get(key)
    if not res:
        return None
    return res.raw_value_text


def _money_entry(raw_value: Optional[str]) -> dict[str, Any]:
    normalized, unit = Scaler.normalize(raw_value, "number") if raw_value else (None, None)
    return {"display": raw_value, "normalized": normalized, "unit": unit}


def _percent_entry(raw_value: Optional[str]) -> dict[str, Any]:
    normalized, unit = Scaler.normalize(raw_value, "percent") if raw_value else (None, None)
    return {"display": raw_value, "normalized": normalized, "unit": unit}


def _parse_event(notes: Optional[str]) -> Optional[dict[str, Any]]:
    if not notes:
        return None
    match = re.search(r'(Lowered|Raised)\s*(\d{1,2}/\d{1,2}/\d{2})', notes, re.IGNORECASE)
    if not match:
        return None
    iso = _iso_from_mdy(match.group(2))
    return {
        "type": match.group(1).lower(),
        "date": iso,
        "raw": notes,
    }


def _extract_parenthetical(snippet: Optional[str]) -> Optional[str]:
    if not snippet:
        return None
    match = re.search(r'\(([^)]*)\)', snippet)
    if not match:
        return None
    cleaned = re.sub(r'\s*=\s*', ' = ', match.group(1).strip())
    return re.sub(r'\s+', ' ', cleaned)


def _ratio_to_pct(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value * 100.0, 1)


def _annual_rates_periods(text: str) -> tuple[Optional[str], Optional[str]]:
    block_match = re.search(r'ANNUALRATES.*?(\bto[^\n]+)', text, re.IGNORECASE | re.DOTALL)
    segment = block_match.group(0) if block_match else text

    from_match = re.search(
        r"Est(?:[\u2019'`]d)?\s*[\u2019'`]?(\d{2})-?[\u2019'`]?(\d{2})",
        segment,
        re.IGNORECASE,
    )
    to_match = re.search(r"to[\u2019'`]?\s*(\d{2})-?[\u2019'`]?(\d{2})", segment, re.IGNORECASE)

    from_period = None
    to_period = None
    if from_match:
        from_period = f"20{from_match.group(1)}-20{from_match.group(2)}"
    if to_match:
        to_period = f"20{to_match.group(1)}-20{to_match.group(2)}"
    return from_period, to_period


def _parse_period(period: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not period:
        return None, None
    match = re.match(r'(\d)Q(\d{4})', period)
    if not match:
        return None, None
    return int(match.group(2)), int(match.group(1))


def _quarter_end_date(year: Optional[int], quarter: Optional[int]) -> Optional[str]:
    if not year or not quarter:
        return None
    month = quarter * 3
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last_day:02d}"


def _series_group_to_year_map(
    group: dict[str, Any],
    years: list[int],
    projection: dict[str, Any],
    *,
    keys: list[str],
    drop_trailing_null: bool = False,
) -> dict[str, Any]:
    output = {}
    for key in keys:
        series = group.get(key)
        if not isinstance(series, list):
            continue
        output[key] = _series_to_year_map(
            series,
            years,
            _projection_value(key, projection),
            drop_trailing_null=drop_trailing_null,
        )
    return output


def _series_to_year_map(
    series: list[Optional[float]],
    years: list[int],
    projection_value: Optional[float],
    *,
    drop_trailing_null: bool = False,
) -> dict[str, Any]:
    result = {str(year): series[idx] if idx < len(series) else None for idx, year in enumerate(years)}
    if drop_trailing_null and years:
        last_year_key = str(years[-1])
        if result.get(last_year_key) is None:
            result.pop(last_year_key, None)
    if projection_value is not None:
        result["projection_2028_2030"] = projection_value
    return result


def _projection_value(metric_key: str, projection: dict[str, Any]) -> Optional[float]:
    if metric_key in projection:
        return projection.get(metric_key)
    if metric_key in {"net_profit", "shareholders_equity", "total_assets"}:
        return projection.get(f"{metric_key}_usd_millions")
    return None


def _iso_from_mdy(value: str) -> Optional[str]:
    match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2})', value)
    if not match:
        return None
    year = 2000 + int(match.group(3))
    return f"{year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
