from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.facts import MetricFact


CALCULATION_VERSION = "piotroski_value_line_v1"
COMPONENT_KEYS = [
    "score.piotroski.roa_positive",
    "score.piotroski.cfo_positive",
    "score.piotroski.roa_improving",
    "score.piotroski.accrual_quality",
    "score.piotroski.leverage_declining",
    "score.piotroski.current_ratio_improving",
    "score.piotroski.no_dilution",
    "score.piotroski.gross_margin_improving",
    "score.piotroski.asset_turnover_improving",
]
TOTAL_KEY = "score.piotroski.total"


@dataclass(frozen=True)
class FactSnapshot:
    id: Optional[int]
    metric_key: str
    value_numeric: Optional[float]
    value_json: dict[str, Any]
    period_type: Optional[str]
    period_end_date: date


@dataclass(frozen=True)
class ComponentResult:
    metric_key: str
    standard_metric: str
    value: int
    variant: str
    method: str
    formula: str
    inputs: list[FactSnapshot]


class FactIndex:
    def __init__(self, facts: Iterable[Any]):
        self.facts: dict[tuple[str, date], FactSnapshot] = {}
        for raw in facts:
            fact = _snapshot(raw)
            if fact is None or fact.value_numeric is None:
                continue
            key = (fact.metric_key, fact.period_end_date)
            current = self.facts.get(key)
            if current is None or (fact.id or -1) >= (current.id or -1):
                self.facts[key] = fact

    def get(self, metric_key: str, period_end: date) -> Optional[FactSnapshot]:
        return self.facts.get((metric_key, period_end))

    def dates(self) -> list[date]:
        return sorted({period_end for _, period_end in self.facts})

    def previous_date(self, period_end: date) -> Optional[date]:
        dates = [item for item in self.dates() if item < period_end]
        return dates[-1] if dates else None

    def has_any(self, metric_keys: set[str]) -> bool:
        return any(metric_key in metric_keys for metric_key, _ in self.facts)


def build_piotroski_f_score_facts(
    facts: Iterable[Any],
    *,
    company_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    index = FactIndex(facts)
    inferred_company_type = company_type or _infer_company_type(index)
    if inferred_company_type in {"bank", "financial"}:
        return []

    derived: list[dict[str, Any]] = []
    for period_end in index.dates():
        component_results = [
            result
            for result in [
                _roa_positive(index, period_end),
                _cfo_positive(index, period_end),
                _roa_improving(index, period_end),
                _accrual_quality(index, period_end),
                _leverage_declining(index, period_end),
                _current_ratio_improving(index, period_end),
                _no_dilution(index, period_end),
                _gross_margin_improving(index, period_end, inferred_company_type),
                _asset_turnover_improving(index, period_end, inferred_company_type),
            ]
            if result is not None
        ]
        derived.extend(_component_fact(result, period_end) for result in component_results)
        if component_results:
            derived.append(_total_fact(component_results, period_end, company_type=inferred_company_type))
    return derived


class PiotroskiFScoreCalculator:
    def __init__(self, db: Session):
        self.db = db

    def calculate_for_stock(self, *, user_id: int, stock_id: int) -> list[MetricFact]:
        source_facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.is_current.is_(True),
            )
        ).all()
        derived = build_piotroski_f_score_facts(source_facts)
        return [
            self._insert_calculated_fact(user_id=user_id, stock_id=stock_id, payload=payload)
            for payload in derived
        ]

    def _insert_calculated_fact(
        self,
        *,
        user_id: int,
        stock_id: int,
        payload: dict[str, Any],
    ) -> MetricFact:
        self.db.execute(
            update(MetricFact)
            .where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == payload["metric_key"],
                MetricFact.period_type == payload.get("period_type"),
                MetricFact.period_end_date == payload.get("period_end_date"),
                MetricFact.source_type == "calculated",
                MetricFact.is_current.is_(True),
            )
            .values(is_current=False)
        )
        fact = MetricFact(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=payload["metric_key"],
            value_numeric=payload.get("value_numeric"),
            value_text=payload.get("value_text"),
            value_json=payload.get("value_json"),
            unit=payload.get("unit"),
            period_type=payload.get("period_type"),
            period_end_date=payload.get("period_end_date"),
            source_type="calculated",
            source_ref_id=None,
            source_document_id=None,
            is_current=True,
        )
        self.db.add(fact)
        self.db.flush()
        return fact


def _roa_positive(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    return _first_current_rule(
        index,
        period_end,
        metric_key="score.piotroski.roa_positive",
        standard_metric="roa_positive",
        candidates=[
            ("returns.roa", "standard", "standard_roa", "returns.roa[Y] > 0", lambda cur: cur > 0),
            ("returns.total_capital", "valueline_proxy", "fallback_return_on_total_capital", "returns.total_capital[Y] > 0", lambda cur: cur > 0),
            ("is.net_income", "valueline_proxy", "fallback_net_income_positive", "is.net_income[Y] > 0", lambda cur: cur > 0),
        ],
    )


def _cfo_positive(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    return _first_current_rule(
        index,
        period_end,
        metric_key="score.piotroski.cfo_positive",
        standard_metric="cfo_positive",
        candidates=[
            ("is.operating_cash_flow", "standard", "standard_operating_cash_flow", "is.operating_cash_flow[Y] > 0", lambda cur: cur > 0),
            ("per_share.cash_flow", "valueline_proxy", "fallback_cash_flow_per_share", "per_share.cash_flow[Y] > 0", lambda cur: cur > 0),
        ],
    )


def _roa_improving(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    previous = index.previous_date(period_end)
    if not previous:
        return None
    return _first_comparison_rule(
        index,
        period_end,
        previous,
        metric_key="score.piotroski.roa_improving",
        standard_metric="roa_improving",
        candidates=[
            ("returns.roa", "standard", "standard_roa", "returns.roa[Y] > returns.roa[Y-1]", lambda cur, prev: cur > prev),
            ("returns.total_capital", "valueline_proxy", "fallback_return_on_total_capital", "returns.total_capital[Y] > returns.total_capital[Y-1]", lambda cur, prev: cur > prev),
        ],
    )


def _accrual_quality(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    standard = _two_current_inputs(
        index,
        period_end,
        "is.operating_cash_flow",
        "is.net_income",
        "standard",
        "standard_operating_cash_flow_to_net_income",
        "is.operating_cash_flow[Y] > is.net_income[Y]",
    )
    if standard:
        return _binary_component(
            "score.piotroski.accrual_quality",
            "accrual_quality",
            standard,
            lambda a, b: a > b,
        )
    proxy = _two_current_inputs(
        index,
        period_end,
        "per_share.cash_flow",
        "per_share.eps",
        "valueline_proxy",
        "fallback_cash_flow_per_share",
        "per_share.cash_flow[Y] > per_share.eps[Y]",
    )
    if proxy:
        return _binary_component(
            "score.piotroski.accrual_quality",
            "accrual_quality",
            proxy,
            lambda a, b: a > b,
        )
    return None


def _leverage_declining(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    previous = index.previous_date(period_end)
    if not previous:
        return None
    return _first_comparison_rule(
        index,
        period_end,
        previous,
        metric_key="score.piotroski.leverage_declining",
        standard_metric="leverage_declining",
        candidates=[
            ("leverage.long_term_debt_to_assets", "standard", "standard_long_term_debt_to_assets", "leverage.long_term_debt_to_assets[Y] < leverage.long_term_debt_to_assets[Y-1]", lambda cur, prev: cur < prev),
            ("leverage.long_term_debt_to_capital", "valueline_proxy", "fallback_long_term_debt_to_capital", "leverage.long_term_debt_to_capital[Y] < leverage.long_term_debt_to_capital[Y-1]", lambda cur, prev: cur < prev),
            ("cap.long_term_debt", "valueline_proxy", "fallback_absolute_long_term_debt", "cap.long_term_debt[Y] < cap.long_term_debt[Y-1]", lambda cur, prev: cur < prev),
        ],
    )


def _current_ratio_improving(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    previous = index.previous_date(period_end)
    if not previous:
        return None
    return _first_comparison_rule(
        index,
        period_end,
        previous,
        metric_key="score.piotroski.current_ratio_improving",
        standard_metric="current_ratio_improving",
        candidates=[
            ("liquidity.current_ratio", "standard", "standard_current_ratio", "liquidity.current_ratio[Y] > liquidity.current_ratio[Y-1]", lambda cur, prev: cur > prev),
        ],
    )


def _no_dilution(index: FactIndex, period_end: date) -> Optional[ComponentResult]:
    previous = index.previous_date(period_end)
    if not previous:
        return None
    return _first_comparison_rule(
        index,
        period_end,
        previous,
        metric_key="score.piotroski.no_dilution",
        standard_metric="no_dilution",
        candidates=[
            ("equity.shares_outstanding", "standard", "standard_shares_outstanding", "equity.shares_outstanding[Y] <= equity.shares_outstanding[Y-1]", lambda cur, prev: cur <= prev),
        ],
    )


def _gross_margin_improving(
    index: FactIndex,
    period_end: date,
    company_type: Optional[str],
) -> Optional[ComponentResult]:
    previous = index.previous_date(period_end)
    if not previous:
        return None
    candidates = [
        ("is.gross_margin", "standard", "standard_gross_margin", "is.gross_margin[Y] > is.gross_margin[Y-1]", lambda cur, prev: cur > prev),
    ]
    if company_type == "insurance":
        candidates.append(("ins.underwriting_margin", "insurance_adjusted", "insurance_underwriting_margin", "ins.underwriting_margin[Y] > ins.underwriting_margin[Y-1]", lambda cur, prev: cur > prev))
    candidates.append(("is.operating_margin", "valueline_proxy", "fallback_operating_margin", "is.operating_margin[Y] > is.operating_margin[Y-1]", lambda cur, prev: cur > prev))
    return _first_comparison_rule(
        index,
        period_end,
        previous,
        metric_key="score.piotroski.gross_margin_improving",
        standard_metric="gross_margin_improving",
        candidates=candidates,
    )


def _asset_turnover_improving(
    index: FactIndex,
    period_end: date,
    company_type: Optional[str],
) -> Optional[ComponentResult]:
    previous = index.previous_date(period_end)
    if not previous:
        return None
    candidates = [
        ("efficiency.asset_turnover", "standard", "standard_asset_turnover", "efficiency.asset_turnover[Y] > efficiency.asset_turnover[Y-1]", lambda cur, prev: cur > prev),
    ]
    if company_type == "insurance":
        candidates.append(("ins.premium_turnover", "insurance_adjusted", "insurance_premium_turnover", "ins.premium_turnover[Y] > ins.premium_turnover[Y-1]", lambda cur, prev: cur > prev))
    else:
        candidates.append(("efficiency.capital_turnover", "valueline_proxy", "fallback_capital_turnover", "efficiency.capital_turnover[Y] > efficiency.capital_turnover[Y-1]", lambda cur, prev: cur > prev))
    return _first_comparison_rule(
        index,
        period_end,
        previous,
        metric_key="score.piotroski.asset_turnover_improving",
        standard_metric="asset_turnover_improving",
        candidates=candidates,
    )


def _first_current_rule(
    index: FactIndex,
    period_end: date,
    *,
    metric_key: str,
    standard_metric: str,
    candidates: list[tuple[str, str, str, str, Callable[[float], bool]]],
) -> Optional[ComponentResult]:
    for source_key, variant, method, formula, predicate in candidates:
        current = index.get(source_key, period_end)
        if current and current.value_numeric is not None:
            return ComponentResult(
                metric_key=metric_key,
                standard_metric=standard_metric,
                value=1 if predicate(float(current.value_numeric)) else 0,
                variant=variant,
                method=method,
                formula=formula,
                inputs=[current],
            )
    return None


def _first_comparison_rule(
    index: FactIndex,
    period_end: date,
    previous: date,
    *,
    metric_key: str,
    standard_metric: str,
    candidates: list[tuple[str, str, str, str, Callable[[float, float], bool]]],
) -> Optional[ComponentResult]:
    for source_key, variant, method, formula, predicate in candidates:
        current = index.get(source_key, period_end)
        previous_fact = index.get(source_key, previous)
        if (
            current
            and previous_fact
            and current.value_numeric is not None
            and previous_fact.value_numeric is not None
        ):
            return ComponentResult(
                metric_key=metric_key,
                standard_metric=standard_metric,
                value=1 if predicate(float(current.value_numeric), float(previous_fact.value_numeric)) else 0,
                variant=variant,
                method=method,
                formula=formula,
                inputs=[current, previous_fact],
            )
    return None


def _two_current_inputs(
    index: FactIndex,
    period_end: date,
    left_key: str,
    right_key: str,
    variant: str,
    method: str,
    formula: str,
) -> Optional[tuple[FactSnapshot, FactSnapshot, str, str, str]]:
    left = index.get(left_key, period_end)
    right = index.get(right_key, period_end)
    if left and right and left.value_numeric is not None and right.value_numeric is not None:
        return left, right, variant, method, formula
    return None


def _binary_component(
    metric_key: str,
    standard_metric: str,
    inputs_and_meta: tuple[FactSnapshot, FactSnapshot, str, str, str],
    predicate: Callable[[float, float], bool],
) -> ComponentResult:
    left, right, variant, method, formula = inputs_and_meta
    return ComponentResult(
        metric_key=metric_key,
        standard_metric=standard_metric,
        value=1 if predicate(float(left.value_numeric), float(right.value_numeric)) else 0,
        variant=variant,
        method=method,
        formula=formula,
        inputs=[left, right],
    )


def _component_fact(result: ComponentResult, period_end: date) -> dict[str, Any]:
    return {
        "metric_key": result.metric_key,
        "value_numeric": float(result.value),
        "value_text": None,
        "value_json": {
            "status": "calculated",
            "variant": result.variant,
            "method": result.method,
            "calculation_version": CALCULATION_VERSION,
            "standard_metric": result.standard_metric,
            "fact_nature": _fact_nature(result.inputs),
            "formula": result.formula,
            "fiscal_year": period_end.year,
            "inputs": [_lineage_item(fact) for fact in result.inputs],
        },
        "unit": "score_point",
        "period_type": "FY",
        "period_end_date": period_end,
    }


def _total_fact(
    results: list[ComponentResult],
    period_end: date,
    *,
    company_type: Optional[str],
) -> dict[str, Any]:
    available_keys = {result.metric_key for result in results}
    missing = [key for key in COMPONENT_KEYS if key not in available_keys]
    complete = not missing
    variant = "insurance_adjusted" if company_type == "insurance" else _total_variant(results)
    value_json = {
        "status": "calculated" if complete else "partial",
        "variant": variant,
        "calculation_version": CALCULATION_VERSION,
        "fact_nature": _fact_nature([fact for result in results for fact in result.inputs]),
        "fiscal_year": period_end.year,
        "inputs": [
            {"metric_key": result.metric_key, "value_numeric": float(result.value), "method": result.method}
            for result in results
        ],
    }
    if not complete:
        value_json.update(
            {
                "partial_score": sum(result.value for result in results),
                "available_indicators": len(results),
                "max_available_score": len(results),
                "missing_indicators": missing,
            }
        )
    return {
        "metric_key": TOTAL_KEY,
        "value_numeric": float(sum(result.value for result in results)) if complete else None,
        "value_text": None,
        "value_json": value_json,
        "unit": "score_total",
        "period_type": "FY",
        "period_end_date": period_end,
    }


def _total_variant(results: list[ComponentResult]) -> str:
    variants = {result.variant for result in results}
    if "insurance_adjusted" in variants:
        return "insurance_adjusted"
    if variants == {"standard"}:
        return "standard"
    return "valueline_proxy"


def _infer_company_type(index: FactIndex) -> Optional[str]:
    if index.has_any({"ins.underwriting_margin", "ins.premium_turnover", "is.net_premiums_earned", "is.pc_premiums_earned"}):
        return "insurance"
    return None


def _snapshot(raw: Any) -> Optional[FactSnapshot]:
    metric_key = _get(raw, "metric_key")
    period_end = _get(raw, "period_end_date")
    period_type = _get(raw, "period_type")
    if not isinstance(metric_key, str) or not isinstance(period_end, date) or period_type != "FY":
        return None
    value_json = _get(raw, "value_json") or {}
    if not isinstance(value_json, dict):
        value_json = {}
    value_numeric = _get(raw, "value_numeric")
    return FactSnapshot(
        id=_get(raw, "id"),
        metric_key=metric_key,
        value_numeric=float(value_numeric) if isinstance(value_numeric, (int, float)) else None,
        value_json=value_json,
        period_type=period_type,
        period_end_date=period_end,
    )


def _fact_nature(inputs: list[FactSnapshot]) -> str:
    for fact in inputs:
        if fact.value_json.get("fact_nature") == "estimate":
            return "estimate"
    return "actual"


def _lineage_item(fact: FactSnapshot) -> dict[str, Any]:
    return {
        "metric_key": fact.metric_key,
        "period_end_date": fact.period_end_date.isoformat(),
        "fact_id": fact.id,
        "value_numeric": fact.value_numeric,
        "fact_nature": fact.value_json.get("fact_nature"),
    }


def _get(raw: Any, key: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(key)
    return getattr(raw, key, None)
