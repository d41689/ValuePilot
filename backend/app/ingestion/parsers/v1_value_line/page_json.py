import calendar
import re
from typing import Any, Optional

from app.ingestion.normalization.scaler import Scaler
from app.ingestion.parsers.v1_value_line.evidence import parse_rating_event_notes
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.semantics import (
    detect_quarter_month_order,
    fiscal_year_end_month_from_order,
    is_estimated_year,
    quarter_end_date_for_fiscal_year,
    quarter_fact_nature,
    split_actual_and_estimate_years,
)


def build_value_line_page_json(
    parser: ValueLineV1Parser,
    *,
    page_number: int,
    results: Optional[list] = None,
) -> dict[str, Any]:
    if results is None:
        results = parser.parse()
    by_key = {res.field_key: res for res in results}
    identity = parser.extract_identity()

    report_date = _report_date(by_key)
    insurance_layout = _detect_insurance_layout(by_key)
    ads_layout = _detect_ads_layout(parser, by_key)
    adr_layout = _detect_adr_layout(parser, by_key) if not ads_layout else False
    layout_id = "insurance" if insurance_layout else "industrial"
    security_unit = "ADS" if ads_layout else ("adr" if adr_layout else "share")
    quarter_month_order = detect_quarter_month_order(parser.text)
    header = _build_header(by_key)
    header["fact_nature"] = "snapshot"
    ratings = _build_ratings(by_key)
    ratings["fact_nature"] = "opinion"
    annual_rates = _build_annual_rates(
        parser.text,
        by_key,
        insurance_layout=insurance_layout,
        adr_layout=adr_layout,
        ads_layout=ads_layout,
    )
    annual_rates["fact_nature"] = "opinion"
    target_price_18m = _build_target_18m(by_key)
    target_price_18m["fact_nature"] = "opinion"
    long_term_projection = _build_long_term_projection(by_key)
    long_term_projection["fact_nature"] = "opinion"
    quarterly_sales_block = _build_quarterly_block(
        by_key.get("quarterly_sales_usd_millions"),
        unit="USD_millions",
        report_date=report_date,
        month_order=quarter_month_order,
    )
    quarterly_revenues_block = _build_quarterly_block(
        by_key.get("quarterly_revenues_usd_millions"),
        unit="USD_millions",
        report_date=report_date,
        month_order=quarter_month_order,
    )
    use_quarterly_revenues = bool(quarterly_revenues_block.get("by_year"))

    output = {
        "meta": {
            "parser_version": "value_line_v1",
            "schema_version": "1.1",
            "page_number": page_number,
            "report_date": report_date,
            "source": "value_line",
            "layout_id": layout_id,
            "security_unit": security_unit,
        },
        "identity": {
            "company_name": identity.company_name,
            "ticker": identity.ticker,
            "exchange": identity.exchange,
        },
        "header": header,
        "ratings": ratings,
        "quality_metrics": _build_quality_metrics(by_key),
        "target_price_18m": target_price_18m,
        "long_term_projection": long_term_projection,
        "institutional_decisions": _build_institutional_decisions(by_key),
        "capital_structure": _build_capital_structure(
            by_key,
            insurance_layout=insurance_layout,
            adr_layout=adr_layout,
            ads_layout=ads_layout,
        ),
        "financial_position": _build_financial_position(by_key),
        "annual_rates": annual_rates,
        # v1.1: stable keys; non-applicable blocks are emitted as null (not omitted).
        "quarterly_sales": quarterly_sales_block if not insurance_layout else None,
        "net_premiums_earned": quarterly_sales_block if insurance_layout else None,
        "earnings_per_share": _build_quarterly_block_or_none(
            by_key.get("earnings_per_share"),
            unit="USD_per_share",
            report_date=report_date,
            month_order=quarter_month_order,
        ),
        "earnings_per_adr": _build_quarterly_block_or_none(
            by_key.get("earnings_per_adr"),
            unit="USD_per_adr",
            report_date=report_date,
            month_order=quarter_month_order,
        ),
        "earnings_per_ads": _build_quarterly_block_or_none(
            by_key.get("earnings_per_ads"),
            unit="USD_per_ads",
            report_date=report_date,
            month_order=quarter_month_order,
        ),
        "quarterly_dividends_paid": _build_quarterly_dividends_paid(
            parser.text,
            by_key.get("quarterly_dividends_paid_per_share"),
            unit="USD_per_ads" if ads_layout else ("USD_per_adr" if adr_layout else "USD_per_share"),
            report_date=report_date,
            adr_layout=adr_layout or ads_layout,
        ),
        "annual_financials": _build_annual_financials(
            by_key,
            report_date=report_date,
            insurance_layout=insurance_layout,
            adr_layout=adr_layout,
            ads_layout=ads_layout,
            text=parser.text,
        ),
        "total_return": _build_total_return(by_key),
        "historical_price_range": _build_historical_price_range(by_key, insurance_layout=insurance_layout),
        "current_position": _build_current_position(by_key),
        "narrative": _build_narrative(by_key, report_date, adr_layout=adr_layout),
    }

    if ads_layout and output.get("earnings_per_ads") is not None:
        output["earnings_per_ads"]["notes"] = "Values are reported as Earnings per ADS in the source table."

    if not ads_layout:
        output.pop("earnings_per_ads", None)

    if use_quarterly_revenues:
        output.pop("quarterly_sales", None)
        output["quarterly_revenues"] = quarterly_revenues_block

    if isinstance(output.get("total_return"), dict):
        output["total_return"]["fact_nature"] = "snapshot"
    if isinstance(output.get("narrative"), dict):
        output["narrative"]["fact_nature"] = "opinion"

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
    if raw.upper() in {"NIL", "NMF", "--"}:
        return "Nil" if raw.upper() == "NIL" else raw
    if re.search(r"[A-Za-z]", raw):
        return raw
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
        event = parse_rating_event_notes(notes)
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


def _build_capital_structure(
    by_key: dict[str, Any],
    *,
    insurance_layout: bool,
    adr_layout: bool,
    ads_layout: bool,
) -> dict[str, Any]:
    cap: dict[str, Any] = {}

    as_of = _raw(by_key, "capital_structure_as_of")
    if as_of is not None:
        cap["as_of"] = as_of

    for output_key, raw_key, formatter in (
        ("total_debt", "total_debt", _money_entry),
        ("debt_due_in_5_years", "debt_due_in_5_years", _money_entry),
        ("lt_debt", "lt_debt", _money_entry),
        ("lt_interest", "lt_interest", _money_entry),
        ("lt_interest_percent_of_capital", "debt_percent_of_capital", _percent_entry),
    ):
        raw = _raw(by_key, raw_key)
        if raw is not None:
            cap[output_key] = formatter(raw)
    cap.setdefault("lt_interest_percent_of_capital", None)

    leases_raw = _raw(by_key, "leases_uncapitalized_annual_rentals")
    if leases_raw is not None:
        leases_entry = _money_entry(leases_raw)
        leases_entry["notes"] = "Annual rentals"
        cap["leases_uncapitalized"] = leases_entry
    elif not insurance_layout:
        cap["leases_uncapitalized"] = None

    pension_assets_raw = _raw(by_key, "pension_assets")
    if pension_assets_raw is not None:
        pension_entry = _money_entry(pension_assets_raw)
        pension_entry["as_of"] = _raw(by_key, "pension_assets_as_of")
        cap["pension_assets"] = pension_entry

    obligations_raw = _raw(by_key, "pension_obligations")
    if obligations_raw is not None:
        oblig_entry = _money_entry(obligations_raw)
        oblig_entry["label"] = "Oblig."
        cap["obligations_other"] = oblig_entry

    if insurance_layout:
        cap["pension_plan"] = None
    else:
        pension_res = by_key.get("pension_plan")
        if pension_res and isinstance(getattr(pension_res, "parsed_value_json", None), dict):
            cap["pension_plan"] = pension_res.parsed_value_json

    for output_key, raw_key in (
        ("preferred_stock", "preferred_stock"),
        ("preferred_dividend", "preferred_dividend"),
    ):
        raw = _raw(by_key, raw_key)
        if raw is not None:
            cap[output_key] = _money_entry(raw)
    if ads_layout:
        cap.setdefault("preferred_stock", None)

    shares_res = by_key.get("common_stock_shares_outstanding") or by_key.get("shares_outstanding")
    raw_shares = _raw(by_key, "common_stock_shares_outstanding") or _raw(by_key, "shares_outstanding")
    if raw_shares is not None:
        shares_display = raw_shares if insurance_layout else _shares_display(shares_res, raw_shares)
        unit = "shares"
        parsed_meta = shares_res.parsed_value_json if shares_res and isinstance(shares_res.parsed_value_json, dict) else {}
        if ads_layout or (parsed_meta.get("unit") == "ADS"):
            unit = "ads"
        elif adr_layout or (parsed_meta.get("unit") == "ADRs"):
            unit = "ADRs"
        common_stock = {
            "shares_outstanding": {
                "display": shares_display,
                "normalized": _to_number(raw_shares),
                "unit": unit,
            },
        }
        as_of = parsed_meta.get("as_of")
        if "as_of" in parsed_meta:
            common_stock["as_of"] = as_of
        elif cap.get("as_of"):
            common_stock["as_of"] = cap["as_of"]
        class_a_raw = parsed_meta.get("class_a_shares")
        class_a_display = parsed_meta.get("class_a_shares_display") or class_a_raw
        if class_a_raw:
            common_stock["class_a_shares"] = {
                "display": class_a_display,
                "normalized": _to_number(class_a_raw),
                "unit": "shares",
            }
        voting_multiple = parsed_meta.get("class_a_voting_power_multiple")
        voting_notes = parsed_meta.get("class_a_voting_power_notes")
        if voting_multiple or voting_notes:
            common_stock["class_a_voting_power"] = {
                "multiple": voting_multiple,
                "notes": voting_notes,
            }
        elif class_a_raw:
            common_stock["class_a_voting_power"] = None
        cap["common_stock"] = common_stock

    market_raw = _raw(by_key, "market_cap")
    if market_raw is not None:
        market_entry = _money_entry(market_raw)
        market_notes = None
        market_res = by_key.get("market_cap")
        if market_res and isinstance(market_res.parsed_value_json, dict):
            market_notes = market_res.parsed_value_json.get("notes")
        if insurance_layout:
            market_entry["notes"] = None
            mkt_as_of = _raw(by_key, "market_cap_as_of")
            if mkt_as_of is not None:
                market_entry["as_of"] = mkt_as_of
        else:
            if market_notes:
                market_entry["market_cap_category"] = market_notes
            else:
                market_entry["notes"] = None
                mkt_as_of = _raw(by_key, "market_cap_as_of")
                if mkt_as_of is not None:
                    market_entry["as_of"] = mkt_as_of
        cap["market_cap"] = market_entry

    return cap


def _build_financial_position(by_key: dict[str, Any]) -> Optional[dict[str, Any]]:
    res = by_key.get("financial_position_usd_millions")
    return res.parsed_value_json if res and res.parsed_value_json else None


def _build_current_position(by_key: dict[str, Any]) -> Optional[dict[str, Any]]:
    res = by_key.get("current_position_usd_millions")
    if not res or not res.parsed_value_json:
        return None

    parsed = res.parsed_value_json
    years = list(parsed.get("years", []))

    note_message = None
    if len(years) >= 2:
        def _year_int(value: Any) -> Optional[int]:
            if isinstance(value, int):
                return value
            if isinstance(value, str) and re.fullmatch(r"\d{4}", value):
                return int(value)
            return None

        first_year = _year_int(years[0])
        second_year = _year_int(years[1])
        if first_year is not None and second_year is not None and first_year == second_year:
            corrected_year = first_year - 1
            years[0] = str(corrected_year)
            _, third_end = _period_label_and_end(years[2]) if len(years) > 2 else (None, None)
            note_tail = third_end or years[2] if len(years) > 2 else str(second_year)
            note_message = f"should be {corrected_year},{second_year},{note_tail}"

    def _series_at(series: Optional[list[float]], idx: int) -> Optional[float]:
        if not isinstance(series, list) or idx >= len(series):
            return None
        return series[idx]

    periods = []
    for idx, year in enumerate(years):
        label, period_end_date = _period_label_and_end(year)
        inventory_avg_cost = _series_at(parsed.get("inventory_avg_cost"), idx)
        inventory_fifo = _series_at(parsed.get("inventory_fifo"), idx)
        inventory_lifo = _series_at(parsed.get("inventory_lifo"), idx)
        if inventory_avg_cost is not None:
            inventory_key = "inventory_avg_cost"
            inventory_value = inventory_avg_cost
        else:
            inventory_key = "inventory_fifo" if inventory_fifo is not None else "inventory_lifo"
            inventory_value = inventory_fifo if inventory_fifo is not None else inventory_lifo
        period = {
            "label": label,
            "period_end_date": period_end_date,
            "assets": {
                "cash_assets": _series_at(parsed.get("cash_assets"), idx),
                "receivables": _series_at(parsed.get("receivables"), idx),
                inventory_key: inventory_value,
                "other_current_assets": _series_at(parsed.get("other_current_assets"), idx),
                "total_current_assets": _series_at(parsed.get("current_assets_total"), idx),
            },
            "liabilities": {
                "accounts_payable": _series_at(parsed.get("accounts_payable"), idx),
                "debt_due": _series_at(parsed.get("debt_due"), idx),
                "other_current_liabilities": _series_at(parsed.get("other_current_liabilities"), idx),
                "total_current_liabilities": _series_at(parsed.get("current_liabilities_total"), idx),
            },
        }
        if idx == 0 and note_message:
            period["nots"] = note_message
        periods.append(period)

    return {"unit": "USD_millions", "periods": periods}


def _build_annual_rates(
    text: str,
    by_key: dict[str, Any],
    *,
    insurance_layout: bool,
    adr_layout: bool,
    ads_layout: bool,
) -> dict[str, Any]:
    res = by_key.get("annual_rates_of_change")
    parsed = res.parsed_value_json if res and res.parsed_value_json else {}
    from_period, to_period = _annual_rates_periods(text)

    metrics = []
    if insurance_layout:
        metric_defs = [
            ("premium_income", None),
            ("investment_income", None),
            ("earnings", None),
            ("dividends", None),
            ("book_value", None),
        ]
    else:
        if parsed.get("revenues"):
            metric_defs = [
                ("revenues", "revenues"),
                ("cash_flow_per_share", "cash_flow"),
                ("earnings", None),
                ("dividends", None),
                ("book_value", None),
            ]
        else:
            metric_defs = [
                ("sales", None),
                ("cash_flow_per_share", "cash_flow"),
                ("earnings", None),
                ("dividends", None),
                ("book_value", None),
            ]

    for source_key, output_key in metric_defs:
        data = parsed.get(source_key)
        if not data:
            continue

        past_10y = _ratio_to_pct(data.get("past_10y"))
        past_5y = _ratio_to_pct(data.get("past_5y"))
        est = _ratio_to_pct(data.get("est_to_2028_2030"))
        metric = {
            "metric_key": output_key or source_key,
            "past_10y_cagr_pct": past_10y,
            "past_5y_cagr_pct": past_5y,
            "estimated_cagr_pct": {
                "from_period": from_period,
                "to_period": to_period,
                "value": est,
            },
        }
        if output_key == "cash_flow":
            metric["display_name"] = "Cash Flow"
        if output_key == "revenues":
            metric["display_name"] = "Revenues"
        note = data.get("past_5y_note")
        if note:
            metric["past_5y_note"] = note
        metrics.append(metric)

    unit = "per_ads" if ads_layout else ("per_adr" if adr_layout else "per_share")
    if insurance_layout:
        unit = "per_share"
    return {"unit": unit, "metrics": metrics}


def _build_quarterly_block(
    res: Any,
    *,
    unit: str,
    report_date: Optional[str],
    month_order: Optional[list[str]] = None,
    add_missing_report_year: bool = False,
    estimate_year_offset: int = 1,
) -> dict[str, Any]:
    rows = res.parsed_value_json if res and res.parsed_value_json else []
    report_year = int(report_date[:4]) if report_date else None
    fiscal_year_end_month = None
    if rows and isinstance(rows, list) and isinstance(rows[0], dict):
        fiscal_year_end_month = rows[0].get("fiscal_year_end_month")
        if month_order is None:
            month_order = rows[0].get("quarter_month_order")
    if not isinstance(fiscal_year_end_month, int):
        fiscal_year_end_month = fiscal_year_end_month_from_order(month_order)
    by_year = []
    for row in rows:
        year = row.get("calendar_year")
        year_fact_nature = "estimate" if is_estimated_year(
            int(year) if year is not None else None,
            report_date,
            fiscal_year_end_month,
        ) else "actual"
        q1_end = quarter_end_date_for_fiscal_year(year, 1, month_order)
        q2_end = quarter_end_date_for_fiscal_year(year, 2, month_order)
        q3_end = quarter_end_date_for_fiscal_year(year, 3, month_order)
        q4_end = quarter_end_date_for_fiscal_year(year, 4, month_order)
        quarters = {
            "Q1": {"period_end": q1_end, "value": row.get("q1"), "fact_nature": quarter_fact_nature(q1_end, report_date)},
            "Q2": {"period_end": q2_end, "value": row.get("q2"), "fact_nature": quarter_fact_nature(q2_end, report_date)},
            "Q3": {"period_end": q3_end, "value": row.get("q3"), "fact_nature": quarter_fact_nature(q3_end, report_date)},
            "Q4": {"period_end": q4_end, "value": row.get("q4"), "fact_nature": quarter_fact_nature(q4_end, report_date)},
        }
        by_year.append({
            "calendar_year": year,
            "quarters": quarters,
            "full_year": {"value": row.get("full_year"), "fact_nature": year_fact_nature},
        })

    if add_missing_report_year and report_year:
        last_year = by_year[-1]["calendar_year"] if by_year else None
        if last_year is None or last_year < report_year:
            by_year.append({
                "calendar_year": report_year,
                "quarters": None,
                "full_year": {
                    "value": None,
                    "fact_nature": "estimate",
                    "notes": "No quarterly or full-year dividend values provided in report",
                },
            })
        else:
            by_year[-1]["full_year"]["fact_nature"] = "estimate"

    return {
        "unit": unit,
        "by_year": by_year,
        "fact_nature": "mixed",
        "quarter_month_order": month_order,
        "fiscal_year_end_month": fiscal_year_end_month,
    }


def _build_quarterly_block_or_none(
    res: Any,
    *,
    unit: str,
    report_date: Optional[str],
    month_order: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    block = _build_quarterly_block(
        res,
        unit=unit,
        report_date=report_date,
        month_order=month_order,
    )
    if not block.get("by_year"):
        return None
    return block


def _quarter_month_order(text: str) -> Optional[list[str]]:
    return detect_quarter_month_order(text)


def _build_annual_financials(
    by_key: dict[str, Any],
    *,
    report_date: Optional[str],
    insurance_layout: bool,
    adr_layout: bool,
    ads_layout: bool,
    text: Optional[str] = None,
) -> dict[str, Any]:
    res = by_key.get("tables_time_series")
    if not res or not res.parsed_value_json:
        return {"meta": {}}

    annual = res.parsed_value_json.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {})
    years = annual.get("years", [])
    fiscal_year_end_month = annual.get("fiscal_year_end_month")
    projection_range = annual.get("projection_year_range")
    projection = annual.get("projection_2028_2030", {})
    scan_text = text or ""
    actual_years, estimate_years = split_actual_and_estimate_years(
        years if isinstance(years, list) else [],
        report_date,
        fiscal_year_end_month if isinstance(fiscal_year_end_month, int) else None,
    )

    per_unit = "share"
    if not insurance_layout:
        per_unit = "ads" if ads_layout else ("adr" if adr_layout else "share")

    per_share_data = annual.get("per_share", {})
    income_statement_data = annual.get("income_statement_usd_millions", {})
    use_revenues = _series_has_values(per_share_data.get("revenues_per_share_usd")) or _series_has_values(
        income_statement_data.get("revenues")
    )

    has_dividends_declared = bool(
        re.search(r"Div.?d?s?Decl.?dper", scan_text, re.IGNORECASE)
    )
    has_avg_div_yield = bool(
        re.search(r"AvgAnn.?lDiv.?dYield", scan_text, re.IGNORECASE)
    )
    has_avg_pe_ratio = bool(
        re.search(r"AvgAnn.?lP/ERatio", scan_text, re.IGNORECASE)
    )
    has_relative_pe_ratio = bool(
        re.search(r"RelativeP/ERatio", scan_text, re.IGNORECASE)
    )
    has_all_divs = bool(
        re.search(r"AllDiv.?dstoNetProf", scan_text, re.IGNORECASE)
    )
    keep_all_null = use_revenues

    # v1.1: unify per-unit naming (unit is in annual_financials.per_unit + meta.currency).
    if insurance_layout:
        per_unit_map = {
            "pc_prem_earned_per_share_usd": "pc_prem_earned",
            "investment_income_per_share_usd": "investment_income",
            "underwriting_income_per_share_usd": "underwriting_income",
            "earnings_per_share_usd": "earnings",
            "dividends_declared_per_share_usd": "dividends_declared",
            "book_value_per_share_usd": "book_value",
            "common_shares_outstanding_millions": "common_shares_outstanding_millions",
        }
    else:
        if use_revenues:
            per_unit_map = {
                "revenues_per_share_usd": "revenues",
                "cash_flow_per_share_usd": "cash_flow",
                "capital_spending_per_share_usd": "capital_spending",
                "earnings_per_share_usd": "earnings",
                "dividends_declared_per_share_usd": "dividends_declared",
                "book_value_per_share_usd": "book_value",
                "common_shares_outstanding_millions": "common_shares_outstanding_millions",
            }
        else:
            per_unit_map = {
                "sales_per_share_usd": "sales",
                "cash_flow_per_share_usd": "cash_flow",
                "capital_spending_per_share_usd": "capital_spending",
                "earnings_per_share_usd": "earnings",
                "dividends_declared_per_share_usd": "dividends_declared",
                "book_value_per_share_usd": "book_value",
                "common_shares_outstanding_millions": "common_shares_outstanding_millions",
            }

    per_unit_metrics = _series_group_to_year_map(
        annual.get("per_share", {}),
        years,
        projection,
        keys=list(per_unit_map.keys()),
        keep_all_null_keys={"dividends_declared_per_share_usd"} if keep_all_null and has_dividends_declared else set(),
        include_projection_keys={"dividends_declared_per_share_usd"} if keep_all_null and has_dividends_declared else set(),
        rename_map=per_unit_map,
        drop_all_null=True,
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
        keep_all_null_keys={
            key
            for key, enabled in (
                ("avg_annual_pe_ratio", has_avg_pe_ratio),
                ("relative_pe_ratio", has_relative_pe_ratio),
                ("avg_annual_dividend_yield_pct", has_avg_div_yield),
            )
            if keep_all_null and enabled
        },
        include_projection_keys={
            key
            for key, enabled in (
                ("avg_annual_pe_ratio", has_avg_pe_ratio),
                ("relative_pe_ratio", has_relative_pe_ratio),
                ("avg_annual_dividend_yield_pct", has_avg_div_yield),
            )
            if keep_all_null and enabled
        },
        drop_all_null=True,
    )
    if insurance_layout:
        income_keys = [
            "pc_premiums_earned",
            "loss_to_prem_earned_pct",
            "expense_to_prem_written",
            "underwriting_margin_pct",
            "net_profit",
            "inv_inc_to_total_investments_pct",
        ]
    else:
        income_keys = [
            "revenues" if use_revenues else "sales",
            "gross_margin_pct",
            "operating_margin_pct",
            "number_of_stores",
            "depreciation",
            "net_profit",
        ]
    income_statement = _series_group_to_year_map(
        income_statement_data,
        years,
        projection,
        keys=income_keys,
        drop_all_null=True,
    )
    income_statement_ratios = _series_group_to_year_map(
        annual.get("income_statement_usd_millions", {}),
        years,
        projection,
        keys=["income_tax_rate_pct", "net_profit_margin_pct"],
        drop_all_null=True,
    )

    # v1.1: keep annual balance sheet/returns grouped (no BUD-only flattened fields).
    if insurance_layout:
        balance_keys = [
            "total_assets",
            "shareholders_equity",
            "return_on_shareholders_equity_pct",
            "retained_to_common_equity_pct",
            "all_dividends_to_net_profit_pct",
        ]
    else:
        balance_keys = [
            "working_capital",
            "long_term_debt",
            "shareholders_equity",
            "total_assets",
            "return_on_total_capital_pct",
            "return_on_shareholders_equity_pct",
            "retained_to_common_equity_pct",
            "all_dividends_to_net_profit_pct",
        ]
    balance_sheet = _series_group_to_year_map(
        annual.get("balance_sheet_and_returns_usd_millions", {}),
        years,
        projection,
        keys=balance_keys,
        keep_all_null_keys={"all_dividends_to_net_profit_pct"} if keep_all_null and has_all_divs else set(),
        include_projection_keys={"all_dividends_to_net_profit_pct"} if keep_all_null and has_all_divs else set(),
        drop_all_null=True,
    )
    for key in ("retained_to_common_equity_pct", "all_dividends_to_net_profit_pct"):
        series = balance_sheet.get(key)
        if isinstance(series, dict) and any(value is None for value in series.values()):
            note_label = "NMF values are represented as null"
            if key == "all_dividends_to_net_profit_pct" and re.search(
                r"AllDiv.?dstoNetProf\s+Nil",
                scan_text,
                re.IGNORECASE,
            ):
                note_label = "Nil values are represented as null"
            series["notes"] = note_label

    payload = {
        "meta": {
            "source": "value_line",
            "table_type": "annual_financials_and_ratios",
            "currency": "USD",
            "historical_years": years,
            "actual_years": actual_years,
            "estimate_years": estimate_years,
            "fact_nature": "mixed",
            "fiscal_year_end_month": fiscal_year_end_month,
            "projection_year_range": projection_range,
        },
        "per_unit": per_unit,
        "per_unit_metrics": per_unit_metrics,
        "valuation_metrics": valuation,
        "income_statement_usd_millions": income_statement,
        "income_statement_ratios_pct": income_statement_ratios,
        "balance_sheet_and_returns_usd_millions": balance_sheet,
    }

    return payload


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


def _build_historical_price_range(by_key: dict[str, Any], *, insurance_layout: bool) -> list[dict[str, Any]]:
    res = by_key.get("tables_time_series")
    if not res or not res.parsed_value_json:
        return []

    annual = res.parsed_value_json.get("annual_financials_and_ratios_2015_2026_with_projection_2028_2030", {})
    years = annual.get("years", [])
    if years and not insurance_layout:
        years = [year - 1 for year in years]
    prices = res.parsed_value_json.get("price_history_high_low", {})
    highs = prices.get("high", [])
    lows = prices.get("low", [])

    # Guardrail: occasionally the text-layer match grabs year tokens (e.g. 2028/2030)
    # instead of prices. If we see year-like prices, treat the whole block as unparsed.
    def _looks_like_year(value: Any) -> bool:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        return 1900 <= v <= 2100

    if any(_looks_like_year(v) for v in highs) or any(_looks_like_year(v) for v in lows):
        return []

    rows = []
    for idx, year in enumerate(years):
        rows.append({
            "year": year,
            "high": highs[idx] if idx < len(highs) else None,
            "low": lows[idx] if idx < len(lows) else None,
        })
    return rows


def _build_narrative(
    by_key: dict[str, Any],
    report_date: Optional[str],
    *,
    adr_layout: bool,
) -> dict[str, Any]:
    analyst = by_key.get("analyst_name")
    analyst_name = None
    if analyst and isinstance(analyst.parsed_value_json, dict):
        analyst_name = analyst.parsed_value_json.get("value")
    if analyst_name is None:
        analyst_name = _raw(by_key, "analyst_name")

    narrative = {
        "business": _raw(by_key, "business_description"),
        "analyst_name": analyst_name,
        "commentary_date": report_date,
    }
    commentary = _raw(by_key, "analyst_commentary")
    narrative["analyst_commentary"] = commentary
    return narrative


def _raw(by_key: dict[str, Any], key: str) -> Optional[str]:
    res = by_key.get(key)
    if not res:
        return None
    return res.raw_value_text


def _money_entry(raw_value: Optional[str]) -> dict[str, Any]:
    if raw_value and raw_value.strip().upper() in {"NIL", "NONE", "NMF", "--"}:
        return {"display": raw_value, "normalized": None, "unit": "USD"}
    normalized, unit = Scaler.normalize(raw_value, "number") if raw_value else (None, None)
    if normalized is not None:
        normalized = round(normalized, 6)
    return {"display": raw_value, "normalized": normalized, "unit": unit}


def _percent_entry(raw_value: Optional[str]) -> dict[str, Any]:
    normalized, unit = Scaler.normalize(raw_value, "percent") if raw_value else (None, None)
    return {"display": raw_value, "normalized": normalized, "unit": unit}


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
    # Normalize smart quotes found in some PDF text layers (e.g. to’28-’30).
    segment = text.translate({
        0x2018: ord("'"),
        0x2019: ord("'"),
        0x02BC: ord("'"),
    })
    # Search across the whole text: the only relevant "to" we care about includes
    # a two-digit year range (e.g. to'28-'30), which avoids false matches.

    from_match = re.search(
        r"Est(?:'d)?\s*'?(\d{2})\s*-\s*'?(\d{2})",
        segment,
        re.IGNORECASE,
    )
    to_match = re.search(r"to'?\s*'?(\d{2})\s*-\s*'?(\d{2})", segment, re.IGNORECASE)

    from_period = None
    to_period = None
    if from_match:
        from_period = f"20{from_match.group(1)}-20{from_match.group(2)}"
    if to_match:
        to_period = f"20{to_match.group(1)}-20{to_match.group(2)}"
    return from_period, to_period


def _build_quarterly_dividends_paid(
    text: str,
    res: Any,
    *,
    unit: str,
    report_date: Optional[str],
    adr_layout: bool,
) -> dict[str, Any]:
    # Standard quarterly rows (when present).
    block = _build_quarterly_block(
        res,
        unit=unit,
        report_date=report_date,
        add_missing_report_year=not adr_layout,
        estimate_year_offset=0 if adr_layout else 1,
    )

    # Some reports explicitly state there are no dividends instead of providing a table.
    compact = re.sub(r"\s+", "", text or "").upper()
    if not re.search(r"NOCASHDIVIDENDS.{0,200}BEINGPAID", compact):
        return block

    report_year = int(report_date[:4]) if report_date else None
    note = "No cash dividends being paid"

    # Try to derive the year range from the nearby text (filtering out long-term projection years).
    start = re.search(r"QUARTERLYDIVIDENDS\w*", text, re.IGNORECASE)
    if start:
        segment = text[start.start() : start.start() + 1400]
    else:
        m = re.search(r"No\s+cash\s+dividends\s+being\s+paid", text, re.IGNORECASE)
        segment = text[m.start() - 300 : m.start() + 600] if m else text

    years = []
    for y in re.findall(r"20\d{2}", segment):
        yi = int(y)
        if report_year and yi > report_year:
            continue
        years.append(yi)
    years = sorted(set(years))
    if report_year and len(years) < 2:
        years = list(range(report_year - 4, report_year + 1))

    by_year = [
        {
            "calendar_year": y,
            "quarters": None,
            "full_year": {"value": None, "fact_nature": "actual"},
            "notes": note,
        }
        for y in years
    ]
    return {"unit": unit, "note": note, "by_year": by_year, "fact_nature": "mixed"}


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
    drop_all_null: bool = False,
    keep_all_null_keys: Optional[set[str]] = None,
    include_projection_keys: Optional[set[str]] = None,
    rename_map: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    output = {}
    keep_all_null_keys = keep_all_null_keys or set()
    include_projection_keys = include_projection_keys or set()
    for key in keys:
        series = group.get(key)
        if not isinstance(series, list):
            continue
        year_map = _series_to_year_map(
            series,
            years,
            _projection_value(key, projection),
            drop_trailing_null=drop_trailing_null,
            include_projection_key=key in include_projection_keys,
        )
        if drop_all_null and _all_none(year_map) and key not in keep_all_null_keys:
            continue
        output[rename_map.get(key, key) if rename_map else key] = year_map
    return output


def _series_to_year_map(
    series: list[Optional[float]],
    years: list[int],
    projection_value: Optional[float],
    *,
    drop_trailing_null: bool = False,
    include_projection_key: bool = False,
) -> dict[str, Any]:
    result = {str(year): series[idx] if idx < len(series) else None for idx, year in enumerate(years)}
    if drop_trailing_null and years:
        last_year_key = str(years[-1])
        if result.get(last_year_key) is None:
            result.pop(last_year_key, None)
    if projection_value is not None or include_projection_key:
        result["projection_2028_2030"] = projection_value
    return result


def _projection_value(metric_key: str, projection: dict[str, Any]) -> Optional[float]:
    if metric_key in projection:
        return projection.get(metric_key)
    if metric_key in {"net_profit", "shareholders_equity", "total_assets"}:
        return projection.get(f"{metric_key}_usd_millions")
    return None


def _all_none(values: dict[str, Any]) -> bool:
    return all(value is None for value in values.values())


def _series_has_values(series: Any) -> bool:
    return isinstance(series, list) and any(value is not None for value in series)


def _detect_insurance_layout(by_key: dict[str, Any]) -> bool:
    res = by_key.get("tables_time_series")
    if res and res.parsed_value_json:
        annual = res.parsed_value_json.get(
            "annual_financials_and_ratios_2015_2026_with_projection_2028_2030",
            {},
        )
        per_share = annual.get("per_share", {})
        for key in (
            "pc_prem_earned_per_share_usd",
            "investment_income_per_share_usd",
            "underwriting_income_per_share_usd",
        ):
            if _series_has_values(per_share.get(key)):
                return True

    fp = by_key.get("financial_position_usd_millions")
    if fp and fp.parsed_value_json:
        return True

    ar = by_key.get("annual_rates_of_change")
    if ar and ar.parsed_value_json:
        if ar.parsed_value_json.get("premium_income") or ar.parsed_value_json.get("investment_income"):
            return True

    return False


def _detect_adr_layout(parser: ValueLineV1Parser, by_key: dict[str, Any]) -> bool:
    head_text = parser.text[:2000] if parser.text else ""
    # Guardrail: avoid treating legend text (e.g. "ADR 640") as an ADR layout signal.
    if re.search(r'\(\s*ADR\s*\)', head_text, re.IGNORECASE) or re.search(r'\bper\s*ADR\b', head_text, re.IGNORECASE):
        return True
    shares_res = by_key.get("common_stock_shares_outstanding") or by_key.get("shares_outstanding")
    if shares_res and getattr(shares_res, "original_text_snippet", None):
        if re.search(r'ADR', shares_res.original_text_snippet or "", re.IGNORECASE):
            return True
    if shares_res and isinstance(shares_res.parsed_value_json, dict):
        if shares_res.parsed_value_json.get("unit") == "ADRs":
            return True
    return False


def _detect_ads_layout(parser: ValueLineV1Parser, by_key: dict[str, Any]) -> bool:
    head_text = parser.text[:2000] if parser.text else ""
    if re.search(r'\(\s*ADS\s*\)', head_text, re.IGNORECASE) or re.search(r'\bper\s*ADS\b', head_text, re.IGNORECASE):
        return True
    shares_res = by_key.get("common_stock_shares_outstanding") or by_key.get("shares_outstanding")
    if shares_res and getattr(shares_res, "original_text_snippet", None):
        if re.search(r'ADS', shares_res.original_text_snippet or "", re.IGNORECASE):
            return True
    if shares_res and isinstance(shares_res.parsed_value_json, dict):
        if shares_res.parsed_value_json.get("unit") == "ADS":
            return True
    return False


def _shares_display(res: Any, raw_value: str) -> str:
    if res and getattr(res, "original_text_snippet", None):
        snippet = res.original_text_snippet or ""
        match = re.search(
            r'CommonStock\s*([\d,]+(?:\.\d+)?)\s*(mil|mill|million)\.?\s*(?:ADRs?|ADSs?)',
            snippet,
            re.IGNORECASE,
        )
        if match:
            return f"{match.group(1)} mil"
        match = re.search(
            r'Common\s*Stock\s*([\d\.]+)\s*(mil|mill|million)\.?\s*(?:shs|shares)',
            snippet,
            re.IGNORECASE,
        )
        if match:
            num = match.group(1)
            token = match.group(2).lower()
            if token == "million":
                return f"{num} million shares"
            token_display = "mill." if token in {"mil", "mill"} else token
            return f"{num} {token_display} shs"
        match = re.search(r'Common\s*Stock\s*([\d,]+)', snippet, re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r'CommonStock\s*([\d,]+)', snippet, re.IGNORECASE)
        if match:
            return match.group(1)
    return raw_value


def _period_label_and_end(value: Any) -> tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    text = str(value)
    if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
        return _mdy_label_from_iso(text), text
    if re.match(r'^\d{4}$', text):
        return text, f"{text}-12-31"
    iso = _iso_from_mdy(text)
    return text, iso or text


def _mdy_label_from_iso(value: str) -> str:
    parts = value.split("-")
    if len(parts) != 3:
        return value
    year = parts[0][2:]
    month = int(parts[1])
    day = int(parts[2])
    return f"{month}/{day}/{year}"


def _iso_from_mdy(value: str) -> Optional[str]:
    match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2})', value)
    if not match:
        return None
    year = 2000 + int(match.group(3))
    return f"{year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
