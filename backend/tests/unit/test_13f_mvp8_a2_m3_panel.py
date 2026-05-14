"""MVP8-A2: unit tests for ``_m3_panel_for_stock``.

Two paths:
1. Stock with VL metric facts → panel returned with piotroski + valuation.
2. Stock with no VL facts → ``{"has_value_line": False}``.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.api.v1.endpoints.stocks_13f import _m3_panel_for_stock
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User


def _user(db_session, email: str) -> User:
    u = User(email=email)
    db_session.add(u)
    db_session.flush()
    return u


def _stock(db_session, ticker: str) -> Stock:
    s = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Corp", is_active=True)
    db_session.add(s)
    db_session.flush()
    return s


def _fact(
    db_session,
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    value_numeric: float | None = None,
    value_json: dict | None = None,
    period_end: date = date(2024, 12, 31),
) -> MetricFact:
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value_numeric,
        value_json=value_json or {"fact_nature": "actual"},
        source_type="parsed",
        is_current=True,
        period_type="FY",
        period_end_date=period_end,
    )
    db_session.add(fact)
    db_session.flush()
    return fact


def test_m3_panel_returns_has_value_line_false_when_no_facts(db_session):
    stock = _stock(db_session, "NOVL")
    result = _m3_panel_for_stock(db_session, stock.id)
    assert result.has_value_line is False
    # No VL data → all value fields default to None including provenance.
    assert result.vl_target_period_end is None
    assert result.vl_target_source_document_id is None


def test_m3_panel_returns_populated_panel_with_vl_facts(db_session):
    user = _user(db_session, "mvp8-a2-m3-panel@example.com")
    stock = _stock(db_session, "GRVT")

    # Piotroski stored in value_json (value_numeric left null — matches prod pattern)
    _fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_json={
            "partial_score": 7,
            "max_available_score": 8,
            "status": "partial",
            "fact_nature": "actual",
        },
    )
    # Numeric-backed facts. The target_mid fact carries the as-of period
    # that D1 surfaces as provenance in the QualityOverlay.
    _fact(db_session, user_id=user.id, stock_id=stock.id,
          metric_key="quality.earnings_predictability", value_numeric=75.0)
    _fact(db_session, user_id=user.id, stock_id=stock.id,
          metric_key="target.price_18m.mid", value_numeric=538.0,
          period_end=date(2026, 5, 1))
    _fact(db_session, user_id=user.id, stock_id=stock.id,
          metric_key="target.price_18m.low", value_numeric=355.0)
    _fact(db_session, user_id=user.id, stock_id=stock.id,
          metric_key="target.price_18m.high", value_numeric=721.0)
    _fact(db_session, user_id=user.id, stock_id=stock.id,
          metric_key="proj.long_term.low_price", value_numeric=405.0)
    _fact(db_session, user_id=user.id, stock_id=stock.id,
          metric_key="proj.long_term.high_price", value_numeric=885.0)

    result = _m3_panel_for_stock(db_session, stock.id)

    assert result.has_value_line is True
    assert result.piotroski_score == 7
    assert result.piotroski_max == 8
    assert result.piotroski_status == "partial"
    assert result.earnings_predictability == 75.0
    assert result.vl_target_mid == 538.0
    assert result.vl_target_low == 355.0
    assert result.vl_target_high == 721.0
    assert result.vl_3y_low == 405.0
    assert result.vl_3y_high == 885.0
    # D1 provenance — period_end_date of the target_mid fact rendered as ISO.
    assert result.vl_target_period_end == "2026-05-01"


def test_m3_panel_handles_piotroski_only_without_other_facts(db_session):
    user = _user(db_session, "mvp8-a2-m3-piotroski-only@example.com")
    stock = _stock(db_session, "PNLY")
    _fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_json={"partial_score": 5, "max_available_score": 8, "status": "partial",
                    "fact_nature": "actual"},
    )

    result = _m3_panel_for_stock(db_session, stock.id)

    assert result.has_value_line is True
    assert result.piotroski_score == 5
    assert result.vl_target_mid is None
    assert result.earnings_predictability is None
    # No VL target fact → provenance fields stay None even though
    # has_value_line is True (piotroski alone is enough to flip the flag).
    assert result.vl_target_period_end is None
    assert result.vl_target_source_document_id is None
