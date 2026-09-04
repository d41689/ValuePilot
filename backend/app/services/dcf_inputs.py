"""Canonical, versioned DCF input selection and immutable manifests."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from app.core.currencies import normalize_iso4217_currency
from app.core.config import settings
from app.models.facts import MetricFact


DCF_INPUT_FACT_KEYS = {
    "net_profit_per_share": "per_share.eps",
    "depreciation": "is.depreciation",
    "shares_outstanding": "equity.shares_outstanding",
    "capital_spending_per_share": "per_share.capital_spending",
}
DCF_MONETARY_INPUT_KEYS = (
    DCF_INPUT_FACT_KEYS["net_profit_per_share"],
    DCF_INPUT_FACT_KEYS["depreciation"],
    DCF_INPUT_FACT_KEYS["capital_spending_per_share"],
)
DCF_MANIFEST_VERSION = "dcf-input-manifest-v1"
DCF_EXPLICIT_SELECTION_RULE = "explicit-fy-v1"
DCF_NORMALIZED_SELECTION_RULE = "median-latest-five-oeps-v1"
DCF_MAX_MANIFEST_FACTS = 9
DCF_MAX_ASSUMPTIONS_BYTES = 65_536
SHARES_UNITS = frozenset({"count", "share", "shares"})
NON_MONETARY_UNITS = frozenset(
    {"percent", "percentage", "ratio", "share", "shares", "count"}
)


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _finite_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return decimal_value if decimal_value.is_finite() else None


def _wire_decimal(value: Any) -> str | None:
    decimal_value = _finite_decimal(value)
    return str(decimal_value) if decimal_value is not None else None


def _fact_sort_key(fact: MetricFact) -> tuple[datetime, int]:
    return (_aware_utc(fact.created_at), int(fact.id or 0))


def _fact_snapshot(fact: MetricFact, *, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "id": fact.id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "source_type": fact.source_type,
        "source_ref_id": fact.source_ref_id,
        "source_document_id": fact.source_document_id,
        "period_type": fact.period_type,
        "period_end_date": fact.period_end_date.isoformat() if fact.period_end_date else None,
        "value_numeric": _wire_decimal(fact.value_numeric),
        "unit": fact.unit,
        "currency": fact.currency,
        "created_at": _aware_utc(fact.created_at).isoformat(),
    }


def dcf_manifest_token(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(
        manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        b"valuepilot:dcf-input-manifest-v1:" + encoded,
        hashlib.sha256,
    ).hexdigest()


def _canonical_by_period(
    facts: Iterable[MetricFact],
) -> dict[date, dict[str, MetricFact]]:
    result: dict[date, dict[str, MetricFact]] = {}
    for fact in facts:
        if fact.metric_key not in DCF_INPUT_FACT_KEYS.values() or fact.period_end_date is None:
            continue
        by_key = result.setdefault(fact.period_end_date, {})
        current = by_key.get(fact.metric_key)
        if current is None or _fact_sort_key(fact) > _fact_sort_key(current):
            by_key[fact.metric_key] = fact
    return result


def _canonical_oeps_facts(facts: Iterable[MetricFact]) -> list[MetricFact]:
    by_period: dict[date, MetricFact] = {}
    for fact in facts:
        if fact.metric_key != "owners_earnings_per_share" or fact.period_end_date is None:
            continue
        current = by_period.get(fact.period_end_date)
        if current is None or _fact_sort_key(fact) > _fact_sort_key(current):
            by_period[fact.period_end_date] = fact
    return sorted(
        by_period.values(),
        key=lambda fact: (fact.period_end_date or date.min, *_fact_sort_key(fact)),
        reverse=True,
    )


def _select_period(
    *,
    by_period: dict[date, dict[str, MetricFact]],
    oeps_facts: list[MetricFact],
    selection: str | int,
) -> tuple[date | None, str, list[MetricFact]]:
    if selection == "norm":
        latest_five = oeps_facts[:5]
        ranked = sorted(
            latest_five,
            key=lambda fact: (
                _finite_decimal(fact.value_numeric) or Decimal(0),
                fact.period_end_date or date.min,
                *_fact_sort_key(fact),
            ),
        )
        selected = ranked[len(ranked) // 2] if ranked else None
        return (
            selected.period_end_date if selected else None,
            DCF_NORMALIZED_SELECTION_RULE,
            latest_five,
        )
    selected_period = max(
        (
            fact.period_end_date
            for fact in oeps_facts
            if fact.period_end_date is not None and fact.period_end_date.year == selection
        ),
        default=None,
    )
    selection_fact = next(
        (fact for fact in oeps_facts if fact.period_end_date == selected_period),
        None,
    )
    return (
        selected_period,
        DCF_EXPLICIT_SELECTION_RULE,
        [selection_fact] if selection_fact is not None else [],
    )


def _currency_and_value_state(
    inputs: dict[str, MetricFact],
    provenance_for_fact: Callable[[MetricFact], dict[str, Any] | None] | None,
) -> dict[str, Any]:
    provenance: list[dict[str, Any]] = []
    currencies: list[str] = []
    reason_code: str | None = None

    for metric_key in DCF_MONETARY_INPUT_KEYS:
        fact = inputs.get(metric_key)
        if fact is None or fact.value_numeric is None:
            reason_code = reason_code or "dcf_input_missing"
            continue
        if _finite_decimal(fact.value_numeric) is None:
            reason_code = reason_code or "dcf_input_value_invalid"

        raw_currency = fact.currency
        raw_unit = fact.unit
        currency = normalize_iso4217_currency(raw_currency)
        unit_currency = normalize_iso4217_currency(raw_unit)
        item = {
            "metric_key": metric_key,
            "declared_currency": raw_currency,
            "declared_unit": raw_unit,
            "validated_currency": currency,
        }
        if provenance_for_fact is not None:
            item.update(provenance_for_fact(fact) or {})
        provenance.append(item)

        normalized_unit = str(raw_unit or "").strip().lower()
        if raw_currency is not None and normalize_iso4217_currency(raw_currency) is None:
            reason_code = reason_code or "dcf_input_currency_invalid"
        elif normalized_unit in NON_MONETARY_UNITS:
            reason_code = reason_code or "dcf_input_currency_non_monetary"
        elif raw_currency is not None and unit_currency is not None and unit_currency != currency:
            reason_code = reason_code or "dcf_input_unit_currency_conflict"
        elif currency is None:
            reason_code = reason_code or (
                "dcf_input_currency_missing"
                if raw_currency is None
                else "dcf_input_currency_invalid"
            )
        else:
            currencies.append(currency)

    shares = inputs.get(DCF_INPUT_FACT_KEYS["shares_outstanding"])
    shares_value = _finite_decimal(shares.value_numeric) if shares is not None else None
    if shares is None or shares.value_numeric is None:
        reason_code = reason_code or "dcf_input_missing"
    elif shares_value is None or shares_value <= 0:
        reason_code = reason_code or "dcf_shares_value_invalid"
    elif shares.currency is not None or str(shares.unit or "").strip().lower() not in SHARES_UNITS:
        reason_code = reason_code or "dcf_shares_semantics_invalid"

    if reason_code is None and len(set(currencies)) > 1:
        reason_code = "dcf_input_currency_mismatch"
    currency = currencies[0] if reason_code is None and len(currencies) == 3 else None
    if currency is None and reason_code is None:
        reason_code = "dcf_input_currency_missing"
    return {
        "status": "available" if currency is not None else "unavailable",
        "reason_code": reason_code,
        "currency": currency,
        "provenance": provenance,
    }


def evaluate_dcf_input_selection(
    *,
    stock_id: int,
    dcf_facts: Iterable[MetricFact],
    oeps_facts: Iterable[MetricFact],
    selection: str | int,
    evaluated_at: datetime,
    provenance_for_fact: Callable[[MetricFact], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Evaluate one selectable DCF input set and emit its immutable manifest."""

    evaluated_at = _aware_utc(evaluated_at)
    by_period = _canonical_by_period(
        fact for fact in dcf_facts if fact.stock_id == stock_id
    )
    canonical_oeps = _canonical_oeps_facts(
        fact for fact in oeps_facts if fact.stock_id == stock_id
    )
    selected_period, rule_version, selection_facts = _select_period(
        by_period=by_period,
        oeps_facts=canonical_oeps,
        selection=selection,
    )
    inputs = by_period.get(selected_period, {}) if selected_period else {}
    state = _currency_and_value_state(inputs, provenance_for_fact)
    available = state["status"] == "available"

    eps = inputs.get(DCF_INPUT_FACT_KEYS["net_profit_per_share"])
    depreciation = inputs.get(DCF_INPUT_FACT_KEYS["depreciation"])
    shares = inputs.get(DCF_INPUT_FACT_KEYS["shares_outstanding"])
    capex = inputs.get(DCF_INPUT_FACT_KEYS["capital_spending_per_share"])
    eps_value = _finite_decimal(eps.value_numeric) if eps is not None else None
    depreciation_value = (
        _finite_decimal(depreciation.value_numeric) if depreciation is not None else None
    )
    shares_value = _finite_decimal(shares.value_numeric) if shares is not None else None
    capex_value = _finite_decimal(capex.value_numeric) if capex is not None else None
    depreciation_per_share = (
        depreciation_value / shares_value
        if available
        and depreciation_value is not None
        and shares_value is not None
        and shares_value > 0
        else None
    )

    manifest_facts = [
        _fact_snapshot(fact, role="dcf_input")
        for fact in sorted(inputs.values(), key=lambda fact: fact.metric_key)
    ] + [
        _fact_snapshot(fact, role="selection_input") for fact in selection_facts
    ]
    if len(manifest_facts) > DCF_MAX_MANIFEST_FACTS:
        raise ValueError("DCF input manifest exceeds the bounded selection contract")
    manifest = {
        "manifest_version": DCF_MANIFEST_VERSION,
        "selection_rule_version": rule_version,
        "selection": selection,
        "selected_year": selected_period.year if selected_period else None,
        "evaluated_at": evaluated_at.isoformat(),
        "facts": manifest_facts,
    }

    def value_payload(
        value: Decimal | None,
        source: str,
        fact_provenance: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "value": float(value) if available and value is not None else None,
            "source": source if available else "unavailable",
            **({"provenance": fact_provenance} if fact_provenance is not None else {}),
        }

    def provenance(fact: MetricFact | None) -> dict[str, Any] | None:
        return provenance_for_fact(fact) if fact is not None and provenance_for_fact else None

    computed_provenance = None
    if depreciation is not None or shares is not None:
        computed_provenance = {
            "inputs": [
                {
                    "metric_key": fact.metric_key,
                    **(provenance(fact) or {}),
                }
                for fact in (depreciation, shares)
                if fact is not None
            ]
        }
    return {
        "valuation_currency": state["currency"],
        "currency_state": state,
        "input_manifest": manifest,
        "input_manifest_token": dcf_manifest_token(manifest),
        "net_profit_per_share": value_payload(eps_value, "fact", provenance(eps)),
        "depreciation_per_share": value_payload(
            depreciation_per_share, "computed", computed_provenance
        ),
        "capital_spending_per_share": value_payload(capex_value, "fact", provenance(capex)),
    }
