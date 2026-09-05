"""Canonical, versioned DCF input selection and immutable manifests."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import (
    Decimal,
    DecimalException,
    InvalidOperation,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    localcontext,
)
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.currencies import normalize_iso4217_currency
from app.core.config import settings
from app.models.facts import MetricFact
from app.services.metric_fact_currentness import current_metric_fact_ids_at
from app.services.canonical_financials import (
    apply_reviewed_method_gates,
    guard_sec_run_availability,
    reviewed_method_gate,
    visible_metric_fact_predicate,
)
from app.services.source_reconciliation import guard_reconciled_source_selection


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
DCF_MODEL_VERSION = "dcf_model_v1"
DCF_CALCULATION_VERSION = "dcf-two-stage-finite-v1"
DCF_MAX_MODEL_YEARS = 1_000
DCF_MAX_FACT_UNIVERSE_ROWS = 500
DCF_MAX_RATE_PCT = Decimal("1000")
DCF_MAX_ABS_PER_SHARE = Decimal("1000000")
DCF_MAX_RESULT_PER_SHARE = Decimal("1000000000000")
DCF_INPUT_QUANTUM = Decimal("0.001")
DCF_RESULT_QUANTUM = Decimal("0.000001")
SHARES_UNITS = frozenset({"count", "share", "shares"})
NON_MONETARY_UNITS = frozenset(
    {"percent", "percentage", "ratio", "share", "shares", "count"}
)
ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DcfEvaluationClock:
    evaluated_at: datetime
    effective_as_of: date


@dataclass(frozen=True)
class DcfFactUniverse:
    dcf_facts: list[MetricFact]
    oeps_facts: list[MetricFact]
    method_authority: list[dict[str, Any]]
    method_decisions: dict[str, Any]


class DcfFactUniverseError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        method_decision: Any | None = None,
        reason_code: str | None = None,
        method_gate: dict[str, Any] | None = None,
    ):
        self.code = code
        self.method_decision = method_decision
        self.reason_code = reason_code or (
            method_decision.reason_code if method_decision is not None else code
        )
        self.method_gate = method_gate or (
            method_decision.as_dict() if method_decision is not None else None
        )
        super().__init__(message)


def dcf_evaluation_clock(evaluated_at: datetime) -> DcfEvaluationClock:
    instant = _aware_utc(evaluated_at)
    return DcfEvaluationClock(
        evaluated_at=instant,
        effective_as_of=instant.astimezone(ET).date(),
    )


def _stable_method_authority(decisions: dict[str, Any]) -> list[dict[str, Any]]:
    authority = []
    for _, decision in sorted(decisions.items()):
        snapshot = decision.as_dict()
        # The manifest already records ``evaluated_at``. Excluding only this
        # duplicate clock field keeps otherwise-identical manifests stable.
        snapshot.pop("knowledge_at")
        authority.append(snapshot)
    return authority


def load_canonical_dcf_fact_universe(
    session: Session,
    *,
    stock_id: int,
    user_id: int,
    evaluated_at: datetime,
    effective_as_of: date,
) -> DcfFactUniverse:
    """Load and gate the complete bounded DCF fact universe before selection."""

    method_decisions = {
        method_key: reviewed_method_gate(
            session,
            stock_id=stock_id,
            method_key=method_key,
            effective_as_of=effective_as_of,
            knowledge_at=evaluated_at,
        )
        for method_key in (
            "owner_earnings",
            "per_share_trend",
            "roic",
            "system_valuation",
        )
    }
    for required_method in ("owner_earnings", "system_valuation"):
        decision = method_decisions[required_method]
        if decision.status != "approved":
            raise DcfFactUniverseError(
                "unsupported",
                f"{required_method} is unsupported: {decision.reason_code}",
                method_decision=decision,
            )

    facts = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock_id,
            MetricFact.id.in_(
                current_metric_fact_ids_at(
                    session, knowledge_cutoff=evaluated_at
                )
            ),
            visible_metric_fact_predicate(MetricFact, user_id=user_id),
            MetricFact.period_type == "FY",
            MetricFact.metric_key.in_(
                [*DCF_INPUT_FACT_KEYS.values(), "owners_earnings_per_share"]
            ),
        )
        .order_by(
            MetricFact.metric_key.asc(),
            MetricFact.period_end_date.desc(),
            MetricFact.created_at.desc(),
            MetricFact.id.desc(),
        )
        .limit(DCF_MAX_FACT_UNIVERSE_ROWS + 1)
    ).all()
    if len(facts) > DCF_MAX_FACT_UNIVERSE_ROWS:
        raise DcfFactUniverseError(
            "dcf_fact_universe_too_large",
            "Canonical DCF fact universe exceeds the safe evaluation bound",
        )
    candidate_oeps = [
        fact for fact in facts if fact.metric_key == "owners_earnings_per_share"
    ]
    oeps_facts, blocked_oeps, _ = apply_reviewed_method_gates(
        session,
        stock_id=stock_id,
        facts=candidate_oeps,
        effective_as_of=effective_as_of,
        knowledge_at=evaluated_at,
        precomputed_decisions=method_decisions,
    )
    if blocked_oeps:
        blocked = blocked_oeps[0]
        raise DcfFactUniverseError(
            "unsupported",
            f"owner_earnings is unsupported: {blocked['reason_code']}",
            reason_code=str(blocked["reason_code"]),
            method_gate=blocked.get("method_gate"),
        )
    facts = [
        fact for fact in facts if fact.metric_key != "owners_earnings_per_share"
    ] + oeps_facts
    facts = guard_reconciled_source_selection(
        facts,
        consumer="valuation_inputs",
        knowledge_cutoff=evaluated_at,
        session=session,
        user_id=user_id,
    )
    facts = guard_sec_run_availability(
        session,
        stock_id=stock_id,
        facts=facts,
        knowledge_cutoff=evaluated_at,
    )
    dcf_facts = [fact for fact in facts if fact.metric_key in DCF_INPUT_FACT_KEYS.values()]
    oeps_facts = [fact for fact in facts if fact.metric_key == "owners_earnings_per_share"]
    return DcfFactUniverse(
        dcf_facts=dcf_facts,
        oeps_facts=oeps_facts,
        method_authority=_stable_method_authority(method_decisions),
        method_decisions=method_decisions,
    )


class DcfModelError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _model_decimal(
    inputs: dict[str, Any],
    key: str,
    *,
    nonnegative: bool = False,
) -> Decimal:
    value = inputs.get(key)
    if isinstance(value, bool):
        raise DcfModelError("dcf_model_input_invalid", f"{key} must be a finite number")
    decimal_value = _finite_decimal(value)
    if decimal_value is None or (nonnegative and decimal_value < 0):
        raise DcfModelError("dcf_model_input_invalid", f"{key} must be a finite number")
    if abs(decimal_value) > DCF_MAX_ABS_PER_SHARE:
        raise DcfModelError("dcf_model_input_out_of_range", f"{key} is out of range")
    return decimal_value


def _model_years(inputs: dict[str, Any], key: str) -> int:
    value = _model_decimal(inputs, key, nonnegative=True)
    if value > DCF_MAX_MODEL_YEARS:
        raise DcfModelError("dcf_model_input_out_of_range", f"{key} is out of range")
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _model_rate(inputs: dict[str, Any], key: str) -> Decimal:
    value = _model_decimal(inputs, key, nonnegative=True)
    if value > DCF_MAX_RATE_PCT:
        raise DcfModelError("dcf_model_input_out_of_range", f"{key} is out of range")
    return value


def calculate_dcf_model(actual_inputs: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the existing finite two-stage per-share DCF with Decimal math."""

    required = {
        "net_profit_per_share",
        "depreciation_per_share",
        "capital_spending_per_share",
        "based_on_per_share",
        "discount_rate_pct",
        "growth_years",
        "growth_rate_pct",
        "terminal_years",
        "terminal_rate_pct",
    }
    if not isinstance(actual_inputs, dict) or set(actual_inputs) != required:
        raise DcfModelError(
            "dcf_model_input_invalid",
            "dcf_model_v1 requires exactly the versioned model input fields",
        )
    normalized: dict[str, Decimal | int] = {
        "net_profit_per_share": _model_decimal(actual_inputs, "net_profit_per_share"),
        "depreciation_per_share": _model_decimal(
            actual_inputs, "depreciation_per_share"
        ),
        "capital_spending_per_share": _model_decimal(
            actual_inputs, "capital_spending_per_share"
        ),
        "based_on_per_share": _model_decimal(
            actual_inputs, "based_on_per_share", nonnegative=True
        ),
        "discount_rate_pct": _model_rate(actual_inputs, "discount_rate_pct"),
        "growth_years": _model_years(actual_inputs, "growth_years"),
        "growth_rate_pct": _model_rate(actual_inputs, "growth_rate_pct"),
        "terminal_years": _model_years(actual_inputs, "terminal_years"),
        "terminal_rate_pct": _model_rate(actual_inputs, "terminal_rate_pct"),
    }
    discount_rate_pct = normalized["discount_rate_pct"]
    terminal_rate_pct = normalized["terminal_rate_pct"]
    if not isinstance(discount_rate_pct, Decimal) or not isinstance(
        terminal_rate_pct, Decimal
    ):
        raise AssertionError("DCF rates must be decimals")
    if discount_rate_pct <= terminal_rate_pct:
        raise DcfModelError(
            "dcf_discount_not_above_terminal",
            "Discount rate must be greater than the terminal growth rate",
        )

    base = normalized["based_on_per_share"]
    growth_rate_pct = normalized["growth_rate_pct"]
    growth_years = normalized["growth_years"]
    terminal_years = normalized["terminal_years"]
    if not isinstance(base, Decimal) or not isinstance(growth_rate_pct, Decimal):
        raise AssertionError("DCF monetary inputs and rates must be decimals")
    if not isinstance(growth_years, int) or not isinstance(terminal_years, int):
        raise AssertionError("DCF year inputs must be integers")

    try:
        with localcontext() as context:
            context.prec = 50
            one = Decimal(1)
            hundred = Decimal(100)
            discount = discount_rate_pct / hundred
            growth = growth_rate_pct / hundred
            terminal = terminal_rate_pct / hundred
            growth_ratio = (one + growth) / (one + discount)
            discounted_value = base
            growth_value = Decimal(0)
            for _ in range(growth_years):
                discounted_value *= growth_ratio
                growth_value += discounted_value
            terminal_ratio = (one + terminal) / (one + discount)
            terminal_value = Decimal(0)
            for _ in range(terminal_years):
                discounted_value *= terminal_ratio
                terminal_value += discounted_value
            total = growth_value + terminal_value
            if not all(value.is_finite() for value in (growth_value, terminal_value, total)):
                raise DcfModelError(
                    "dcf_model_result_unavailable", "DCF result is not finite"
                )
            if total <= 0 or abs(total) > DCF_MAX_RESULT_PER_SHARE:
                raise DcfModelError(
                    "dcf_model_result_unavailable",
                    "DCF result is outside the publishable per-share range",
                )
            growth_value = growth_value.quantize(
                DCF_RESULT_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            terminal_value = terminal_value.quantize(
                DCF_RESULT_QUANTUM, rounding=ROUND_HALF_EVEN
            )
            total = total.quantize(DCF_RESULT_QUANTUM, rounding=ROUND_HALF_EVEN)
    except DcfModelError:
        raise
    except DecimalException as error:
        raise DcfModelError(
            "dcf_model_result_unavailable", "DCF result cannot be represented"
        ) from error

    return {
        "calculation_version": DCF_CALCULATION_VERSION,
        "normalized_inputs": normalized,
        "growth_value_per_share": growth_value,
        "terminal_value_per_share": terminal_value,
        "value_per_share": total,
    }


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
    effective_as_of: date | None = None,
    method_authority: list[dict[str, Any]] | None = None,
    provenance_for_fact: Callable[[MetricFact], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Evaluate one selectable DCF input set and emit its immutable manifest."""

    evaluated_at = _aware_utc(evaluated_at)
    effective_as_of = effective_as_of or evaluated_at.astimezone(ET).date()
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
    canonical_component_values = {
        "net_profit_per_share": eps_value,
        "depreciation_per_share": depreciation_per_share,
        "capital_spending_per_share": capex_value,
    }
    canonical_model_inputs: dict[str, str | None] = {
        key: (
            str(value.quantize(DCF_INPUT_QUANTUM, rounding=ROUND_HALF_EVEN))
            if available and value is not None
            else None
        )
        for key, value in canonical_component_values.items()
    }
    if available:
        based_on = max(
            Decimal(0),
            Decimal(canonical_model_inputs["net_profit_per_share"] or "0")
            + Decimal(canonical_model_inputs["depreciation_per_share"] or "0")
            - Decimal(canonical_model_inputs["capital_spending_per_share"] or "0"),
        )
        canonical_model_inputs["based_on_per_share"] = str(based_on)
    else:
        canonical_model_inputs["based_on_per_share"] = None

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
        "effective_as_of": effective_as_of.isoformat(),
        "method_authority": method_authority or [],
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
        "canonical_model_inputs": canonical_model_inputs,
        "input_manifest": manifest,
        "input_manifest_token": dcf_manifest_token(manifest),
        "net_profit_per_share": value_payload(eps_value, "fact", provenance(eps)),
        "depreciation_per_share": value_payload(
            depreciation_per_share, "computed", computed_provenance
        ),
        "capital_spending_per_share": value_payload(capex_value, "fact", provenance(capex)),
    }
