from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.facts import MetricFact


CALCULATION_VERSION = "piotroski_value_line_v1"


@dataclass(frozen=True)
class FactSnapshot:
    id: Optional[int]
    metric_key: str
    value_numeric: Optional[float]
    value_json: dict[str, Any]
    period_type: Optional[str]
    period_end_date: date


def build_value_line_ratio_facts(facts: Iterable[Any]) -> list[dict[str, Any]]:
    source = _group_facts(facts)
    period_dates = sorted({period_end for _, period_end in source})
    derived: list[dict[str, Any]] = []

    for period_end in period_dates:
        derived.extend(
            _build_ratio(
                source,
                period_end,
                metric_key="returns.roa",
                numerator_key="is.net_income",
                denominator_key="bs.total_assets",
                method="net_income_to_total_assets",
            )
        )
        derived.extend(
            _build_ratio(
                source,
                period_end,
                metric_key="liquidity.current_ratio",
                numerator_key="bs.current_assets",
                denominator_key="bs.current_liabilities",
                method="current_assets_to_current_liabilities",
            )
        )
        derived.extend(
            _build_ratio(
                source,
                period_end,
                metric_key="leverage.long_term_debt_to_assets",
                numerator_key="cap.long_term_debt",
                denominator_key="bs.total_assets",
                method="long_term_debt_to_total_assets",
            )
        )
        derived.extend(_build_long_term_debt_to_capital(source, period_end))
        derived.extend(
            _build_ratio(
                source,
                period_end,
                metric_key="efficiency.asset_turnover",
                numerator_key="is.sales",
                denominator_key="bs.total_assets",
                method="sales_to_total_assets",
            )
        )
        derived.extend(_build_capital_turnover(source, period_end))
        premium = _first_available(
            source,
            period_end,
            ["is.net_premiums_earned", "is.pc_premiums_earned", "ins.premium_income"],
        )
        assets = source.get(("bs.total_assets", period_end))
        if premium and assets and _is_positive(assets.value_numeric):
            derived.append(
                _ratio_fact(
                    metric_key="ins.premium_turnover",
                    value=float(premium.value_numeric) / float(assets.value_numeric),
                    period_end=period_end,
                    inputs=[premium, assets],
                    method="insurance_premiums_to_assets",
                    extra={"revenue_equivalent_metric": premium.metric_key},
                )
            )

    return derived


class ValueLineRatioCalculator:
    def __init__(self, db: Session):
        self.db = db

    def calculate_for_stock(self, *, user_id: int, stock_id: int) -> list[MetricFact]:
        source_facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.is_current.is_(True),
                MetricFact.source_type.in_(["parsed", "manual"]),
            )
        ).all()
        derived = build_value_line_ratio_facts(source_facts)
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


def _build_ratio(
    source: dict[tuple[str, date], FactSnapshot],
    period_end: date,
    *,
    metric_key: str,
    numerator_key: str,
    denominator_key: str,
    method: str,
) -> list[dict[str, Any]]:
    numerator = source.get((numerator_key, period_end))
    denominator = source.get((denominator_key, period_end))
    if not numerator or not denominator or not _is_positive(denominator.value_numeric):
        return []
    return [
        _ratio_fact(
            metric_key=metric_key,
            value=float(numerator.value_numeric) / float(denominator.value_numeric),
            period_end=period_end,
            inputs=[numerator, denominator],
            method=method,
        )
    ]


def _build_long_term_debt_to_capital(
    source: dict[tuple[str, date], FactSnapshot],
    period_end: date,
) -> list[dict[str, Any]]:
    debt = source.get(("cap.long_term_debt", period_end))
    equity = source.get(("bs.total_equity", period_end))
    if not debt or not equity:
        return []
    denominator = float(debt.value_numeric) + float(equity.value_numeric)
    if not _is_positive(denominator):
        return []
    return [
        _ratio_fact(
            metric_key="leverage.long_term_debt_to_capital",
            value=float(debt.value_numeric) / denominator,
            period_end=period_end,
            inputs=[debt, equity],
            method="long_term_debt_to_total_capital",
            extra={
                "denominator_formula": "cap.long_term_debt + bs.total_equity",
                "standard_metric": "long_term_debt_to_assets_proxy",
            },
        )
    ]


def _build_capital_turnover(
    source: dict[tuple[str, date], FactSnapshot],
    period_end: date,
) -> list[dict[str, Any]]:
    sales = source.get(("is.sales", period_end))
    debt = source.get(("cap.long_term_debt", period_end))
    equity = source.get(("bs.total_equity", period_end))
    if not sales or not debt or not equity:
        return []
    denominator = float(debt.value_numeric) + float(equity.value_numeric)
    if not _is_positive(denominator):
        return []
    return [
        _ratio_fact(
            metric_key="efficiency.capital_turnover",
            value=float(sales.value_numeric) / denominator,
            period_end=period_end,
            inputs=[sales, equity, debt],
            method="sales_to_total_capital",
            extra={
                "denominator_formula": "bs.total_equity + cap.long_term_debt",
                "standard_metric": "asset_turnover_proxy",
            },
        )
    ]


def _ratio_fact(
    *,
    metric_key: str,
    value: float,
    period_end: date,
    inputs: list[FactSnapshot],
    method: str,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    value_json = {
        "status": "calculated",
        "method": method,
        "calculation_version": CALCULATION_VERSION,
        "fact_nature": _fact_nature(inputs),
        "inputs": [_lineage_item(fact) for fact in inputs],
    }
    if extra:
        value_json.update(extra)
    return {
        "metric_key": metric_key,
        "value_numeric": value,
        "value_text": None,
        "value_json": value_json,
        "unit": "ratio",
        "period_type": _period_type(inputs),
        "period_end_date": period_end,
    }


def _group_facts(facts: Iterable[Any]) -> dict[tuple[str, date], FactSnapshot]:
    grouped: dict[tuple[str, date], FactSnapshot] = {}
    for raw in facts:
        fact = _snapshot(raw)
        if fact is None or fact.value_numeric is None:
            continue
        key = (fact.metric_key, fact.period_end_date)
        current = grouped.get(key)
        if current is None or (fact.id or -1) >= (current.id or -1):
            grouped[key] = fact
    return grouped


def _snapshot(raw: Any) -> Optional[FactSnapshot]:
    metric_key = _get(raw, "metric_key")
    period_end = _get(raw, "period_end_date")
    if not isinstance(metric_key, str) or not isinstance(period_end, date):
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
        period_type=_get(raw, "period_type"),
        period_end_date=period_end,
    )


def _first_available(
    source: dict[tuple[str, date], FactSnapshot],
    period_end: date,
    metric_keys: list[str],
) -> Optional[FactSnapshot]:
    for metric_key in metric_keys:
        fact = source.get((metric_key, period_end))
        if fact and fact.value_numeric is not None:
            return fact
    return None


def _fact_nature(inputs: list[FactSnapshot]) -> str:
    for fact in inputs:
        if fact.value_json.get("fact_nature") == "estimate":
            return "estimate"
    return "actual"


def _period_type(inputs: list[FactSnapshot]) -> Optional[str]:
    for fact in inputs:
        if fact.period_type == "FY":
            return "FY"
    return inputs[0].period_type if inputs else None


def _lineage_item(fact: FactSnapshot) -> dict[str, Any]:
    return {
        "metric_key": fact.metric_key,
        "period_end_date": fact.period_end_date.isoformat(),
        "fact_id": fact.id,
        "value_numeric": fact.value_numeric,
        "fact_nature": fact.value_json.get("fact_nature"),
    }


def _is_positive(value: Optional[float]) -> bool:
    return isinstance(value, (int, float)) and float(value) > 0


def _get(raw: Any, key: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(key)
    return getattr(raw, key, None)
