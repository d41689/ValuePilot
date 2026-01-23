from __future__ import annotations

from datetime import date
from statistics import median
from typing import Optional


EPS_KEY = "per_share.eps"
CAPEX_KEY = "per_share.capital_spending"
DEPRECIATION_KEY = "is.depreciation"
SHARES_KEY = "equity.shares_outstanding"

OEPS_KEY = "owners_earnings_per_share"
OEPS_NORM_KEY = "owners_earnings_per_share_normalized"


def build_owners_earnings_facts(
    facts: list[dict],
    *,
    report_date: Optional[date],
) -> list[dict]:
    by_date: dict[date, dict[str, float]] = {}

    for fact in facts:
        if fact.get("period_type") != "FY":
            continue
        metric_key = fact.get("metric_key")
        if metric_key not in {EPS_KEY, CAPEX_KEY, DEPRECIATION_KEY, SHARES_KEY}:
            continue
        period_end = fact.get("period_end_date")
        if not isinstance(period_end, date):
            continue
        value = fact.get("value_numeric")
        numeric = float(value) if isinstance(value, (int, float)) else 0.0
        by_date.setdefault(period_end, {})[metric_key] = numeric

    if not by_date:
        return []

    derived: list[dict] = []
    oeps_by_date: dict[date, float] = {}

    for period_end in sorted(by_date.keys()):
        inputs = by_date[period_end]
        eps = inputs.get(EPS_KEY, 0.0)
        capex = inputs.get(CAPEX_KEY, 0.0)
        depreciation = inputs.get(DEPRECIATION_KEY, 0.0)
        shares = inputs.get(SHARES_KEY, 0.0)
        dep_per_share = depreciation / shares if shares > 0 else 0.0
        oeps_value = eps + dep_per_share - capex
        oeps_by_date[period_end] = oeps_value
        derived.append(
            {
                "metric_key": OEPS_KEY,
                "value_numeric": oeps_value,
                "value_text": None,
                "value_json": None,
                "unit": "USD",
                "period_type": "FY",
                "period_end_date": period_end,
            }
        )

    if report_date and oeps_by_date:
        last_dates = sorted(oeps_by_date.keys())[-5:]
        series = [oeps_by_date[dt] for dt in last_dates]
        normalized_value = float(median(series)) if series else 0.0
        derived.append(
            {
                "metric_key": OEPS_NORM_KEY,
                "value_numeric": normalized_value,
                "value_text": None,
                "value_json": None,
                "unit": "USD",
                "period_type": "AS_OF",
                "period_end_date": report_date,
            }
        )

    return derived
