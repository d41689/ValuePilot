from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Iterable


EPS_KEY = "per_share.eps"
CAPEX_KEY = "per_share.capital_spending"
DEPRECIATION_KEY = "is.depreciation"
SHARES_KEY = "equity.shares_outstanding"

OEPS_KEY = "owners_earnings_per_share"
OEPS_NORM_KEY = "owners_earnings_per_share_normalized"
OE_INPUT_KEYS = (EPS_KEY, CAPEX_KEY, DEPRECIATION_KEY, SHARES_KEY)
OEPS_CALCULATION_VERSION = "owners-earnings-per-share-v1"
OEPS_NORMALIZATION_VERSION = "owners-earnings-median-latest-five-v1"


def _field(fact: Any, key: str) -> Any:
    return fact.get(key) if isinstance(fact, dict) else getattr(fact, key, None)


def _metadata(fact: Any) -> dict[str, Any]:
    value = _field(fact, "value_json")
    return value if isinstance(value, dict) else {}


def _finite_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def infer_owners_earnings_fact_nature(facts: Iterable[Any]) -> str:
    fact_natures = {
        str(_metadata(fact).get("fact_nature"))
        for fact in facts
        if _metadata(fact).get("fact_nature")
    }
    return "estimate" if "estimate" in fact_natures else "actual"


def _lineage(facts: Iterable[Any]) -> list[dict[str, Any]]:
    return [
        {"fact_id": int(_field(fact, "id")), "metric_key": str(_field(fact, "metric_key"))}
        for fact in facts
    ]


def build_owners_earnings_facts(facts: Iterable[Any]) -> list[dict[str, Any]]:
    """Derive FY OEPS only from complete, exact, persisted canonical inputs.

    The function deliberately refuses missing values, duplicate input slots,
    unpersisted rows, non-current rows, mixed currency, and invalid share
    counts.  It emits immutable fact IDs rather than copying source values as
    unverifiable metadata.
    """

    by_period: dict[date, dict[str, list[Any]]] = {}
    for fact in facts:
        if _field(fact, "period_type") != "FY":
            continue
        metric_key = _field(fact, "metric_key")
        period_end = _field(fact, "period_end_date")
        fact_id = _field(fact, "id")
        if (
            metric_key not in OE_INPUT_KEYS
            or not isinstance(period_end, date)
            or not isinstance(fact_id, int)
            or fact_id <= 0
            or _field(fact, "is_current") is not True
            or not isinstance(_field(fact, "source_type"), str)
        ):
            continue
        by_period.setdefault(period_end, {}).setdefault(metric_key, []).append(fact)

    derived: list[dict[str, Any]] = []
    for period_end in sorted(by_period):
        slot = by_period[period_end]
        if any(len(slot.get(key, ())) != 1 for key in OE_INPUT_KEYS):
            continue
        inputs = [slot[key][0] for key in OE_INPUT_KEYS]
        numbers = [_finite_decimal(_field(fact, "value_numeric")) for fact in inputs]
        if any(number is None for number in numbers):
            continue
        eps, capex, depreciation, shares = numbers
        assert eps is not None and capex is not None
        assert depreciation is not None and shares is not None
        if shares <= 0:
            continue
        monetary_currencies = {
            _field(fact, "currency")
            for fact in inputs[:3]
            if isinstance(_field(fact, "currency"), str)
            and _field(fact, "currency")
        }
        if len(monetary_currencies) != 1 or any(
            not _field(fact, "currency") for fact in inputs[:3]
        ):
            continue
        currency = next(iter(monetary_currencies))
        fact_nature = infer_owners_earnings_fact_nature(inputs)
        derived.append(
            {
                "metric_key": OEPS_KEY,
                "value_numeric": eps + depreciation / shares - capex,
                "value_text": None,
                "value_json": {
                    "calculation_version": OEPS_CALCULATION_VERSION,
                    "calculation_method": (
                        "eps_plus_depreciation_per_share_minus_capex_per_share"
                    ),
                    "inputs": _lineage(inputs),
                    "input_fact_nature": fact_nature,
                    "mapping_id": OEPS_KEY,
                    "definition_basis": "derived",
                    "dimensions_identity": "empty",
                    "fiscal_year": period_end.year,
                    "period_duration_kind": "fiscal_year",
                },
                "unit": currency,
                "currency": currency,
                "period_type": "FY",
                "period_end_date": period_end,
            }
        )
    return derived


def build_normalized_owners_earnings_fact(
    facts: Iterable[Any],
    *,
    report_date: date,
) -> dict[str, Any] | None:
    """Return a normalized OEPS snapshot from exact persisted FY OEPS facts."""

    by_period: dict[date, list[Any]] = {}
    for fact in facts:
        fact_id = _field(fact, "id")
        period_end = _field(fact, "period_end_date")
        if (
            _field(fact, "metric_key") != OEPS_KEY
            or _field(fact, "source_type") != "calculated"
            or _field(fact, "period_type") != "FY"
            or _field(fact, "is_current") is not True
            or not isinstance(fact_id, int)
            or fact_id <= 0
            or not isinstance(period_end, date)
            or _metadata(fact).get("calculation_version") != OEPS_CALCULATION_VERSION
            or _finite_decimal(_field(fact, "value_numeric")) is None
        ):
            return None
        by_period.setdefault(period_end, []).append(fact)
    if not by_period or any(len(rows) != 1 for rows in by_period.values()):
        return None
    latest_periods = sorted(by_period)[-5:]
    selected = [by_period[period][0] for period in latest_periods]
    currencies = {_field(fact, "currency") for fact in selected}
    if len(currencies) != 1 or None in currencies or "" in currencies:
        return None
    values = [_finite_decimal(_field(fact, "value_numeric")) for fact in selected]
    if any(value is None for value in values):
        return None
    normalized = median([value for value in values if value is not None])
    currency = str(next(iter(currencies)))
    return {
        "metric_key": OEPS_NORM_KEY,
        "value_numeric": normalized,
        "value_text": None,
        "value_json": {
            "calculation_version": OEPS_NORMALIZATION_VERSION,
            "calculation_method": "median_latest_five_owner_earnings_per_share",
            "inputs": _lineage(selected),
            "mapping_id": OEPS_NORM_KEY,
            "definition_basis": "derived",
            "dimensions_identity": "empty",
            "fact_nature": "snapshot",
        },
        "unit": currency,
        "currency": currency,
        "period_type": "AS_OF",
        "period_end_date": report_date,
    }
