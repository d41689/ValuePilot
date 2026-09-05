from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.services.calculated_metrics.piotroski_f_score import (
    build_piotroski_f_score_facts,
)


def seed_strict_piotroski_total(
    db: Session,
    *,
    user_id: int,
    stock_id: int,
    score: int = 8,
    period_end: date = date(2024, 12, 31),
    complete: bool = False,
    fact_nature: str = "actual",
    include_components: bool = False,
) -> MetricFact:
    """Append a server-generated strict Piotroski total for consumer tests.

    The partial form has eight available standard indicators. The complete form
    adds asset turnover and therefore has nine available indicators.
    """
    maximum = 9 if complete else 8
    if not 4 <= score <= maximum:
        raise ValueError(f"score must be between 4 and {maximum}")
    prior_end = period_end.replace(year=period_end.year - 1)
    false_count = maximum - score
    def input_fact(
        metric_key: str,
        input_period: date,
        value: float,
        *,
        nature: str,
    ) -> MetricFact:
        existing = db.scalar(
            select(MetricFact)
            .where(
                MetricFact.user_id == user_id,
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key == metric_key,
                MetricFact.period_type == "FY",
                MetricFact.period_end_date == input_period,
                MetricFact.source_type == "parsed",
                MetricFact.is_current.is_(True),
            )
            .order_by(MetricFact.id.desc())
            .limit(1)
        )
        if existing is not None:
            return existing
        created = MetricFact(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            value_numeric=value,
            value_json={"fact_nature": nature},
            unit="ratio",
            period_type="FY",
            period_end_date=input_period,
            source_type="parsed",
            is_current=True,
        )
        db.add(created)
        db.flush()
        db.refresh(created)
        return created

    prior_defaults = {
        "returns.roa": 0.08,
        "leverage.long_term_debt_to_assets": 0.3,
        "liquidity.current_ratio": 1.5,
        "equity.shares_outstanding": 10.0,
        "is.gross_margin": 0.4,
        "efficiency.asset_turnover": 1.1,
    }
    comparison_keys = [
        "leverage.long_term_debt_to_assets",
        "liquidity.current_ratio",
        "equity.shares_outstanding",
        "is.gross_margin",
    ]
    if complete:
        comparison_keys.append("efficiency.asset_turnover")
    false_keys = set(comparison_keys[:false_count])
    prior_by_key = {
        key: input_fact(key, prior_end, prior_defaults[key], nature="actual")
        for key in ["returns.roa", *comparison_keys]
    }

    def comparison_value(key: str) -> float:
        prior_value = float(prior_by_key[key].value_numeric)
        if key == "leverage.long_term_debt_to_assets":
            return prior_value + (0.1 if key in false_keys else -0.1)
        if key == "equity.shares_outstanding":
            return prior_value + (1.0 if key in false_keys else 0.0)
        return prior_value + (-0.1 if key in false_keys else 0.1)

    inputs = [
        prior_by_key["returns.roa"],
        input_fact(
            "returns.roa",
            period_end,
            float(prior_by_key["returns.roa"].value_numeric) + 0.02,
            nature=fact_nature,
        ),
        input_fact(
            "is.operating_cash_flow", period_end, 150.0, nature=fact_nature
        ),
        input_fact("is.net_income", period_end, 100.0, nature=fact_nature),
    ]
    for key in comparison_keys:
        inputs.extend(
            [
                prior_by_key[key],
                input_fact(
                    key,
                    period_end,
                    comparison_value(key),
                    nature=fact_nature,
                ),
            ]
        )
    decision = SimpleNamespace(
        status="approved",
        reason_code="approved",
        economic_class="ordinary_operating",
    )
    # A strict total is only valid while every component declared in its
    # manifest is present as a current sibling.  Persist the complete period
    # even when a consumer test only needs the returned total object.
    _ = include_components
    payloads = [
        item
        for item in build_piotroski_f_score_facts(
            inputs,
            roic_decisions_by_period={prior_end: decision, period_end: decision},
        )
        if item["period_end_date"] == period_end
    ]
    facts = [
        MetricFact(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=payload["metric_key"],
            value_numeric=payload["value_numeric"],
            value_text=payload["value_text"],
            value_json=payload["value_json"],
            unit=payload["unit"],
            period_type=payload["period_type"],
            period_end_date=payload["period_end_date"],
            source_type="calculated",
            is_current=True,
            # The strict manifest requires outputs to be created no earlier
            # than their DB-stamped parsed inputs within the same transaction.
            created_at=func.clock_timestamp(),
        )
        for payload in payloads
    ]
    db.add_all(facts)
    db.commit()
    return next(
        fact for fact in facts if fact.metric_key == "score.piotroski.total"
    )
