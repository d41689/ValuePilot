from datetime import date, datetime, timezone

from sqlalchemy import update

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.stocks import Stock, StockPrice
from app.models.users import User


def _piotroski_fact(
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    year: int,
    value: float | None,
    value_json: dict | None = None,
) -> MetricFact:
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value,
        value_json=value_json or {
            "status": "calculated",
            "variant": "valueline_proxy",
                            "fact_nature": (
                                "estimate"
                                if metric_key == "score.piotroski.roa_positive" and year == 2026
                                else "actual"
                            ),
            "fiscal_year": year,
        },
        unit="score_component" if metric_key != "score.piotroski.total" else "score_total",
        period_type="FY",
        period_end_date=date(year, 12, 31),
        source_type="calculated",
        is_current=True,
    )


def test_lookup_stock_by_ticker_returns_dynamic_piotroski_card_from_current_stock(client, db_session):
    user = User(email="ticker_f_score@example.com")
    stock = Stock(ticker="FSC_TEST", exchange="NYSE", company_name="F SCORE INC", is_active=True)
    other_stock = Stock(ticker="OTHER_FS", exchange="NYSE", company_name="OTHER SCORE", is_active=True)
    db_session.add_all([user, stock, other_stock])
    db_session.commit()

    years = [2022, 2023, 2024, 2025, 2026]
    component_values = {
        "score.piotroski.roa_positive": [1, 1, 1, 1, 1],
        "score.piotroski.cfo_positive": [1, 1, 1, 1, 1],
        "score.piotroski.roa_improving": [1, 0, 1, 0, 1],
        "score.piotroski.accrual_quality": [1, 1, 0, 0, 0],
        "score.piotroski.leverage_declining": [0, 0, 1, 1, 1],
        "score.piotroski.current_ratio_improving": [0, 1, 1, 1, 0],
        "score.piotroski.no_dilution": [1, 1, 1, 1, 1],
        "score.piotroski.gross_margin_improving": [1, 1, 1, 0, 0],
        "score.piotroski.asset_turnover_improving": [0, 1, 1, 1, 0],
    }
    facts = []
    for metric_key, values in component_values.items():
        for year, value in zip(years, values):
            facts.append(
                _piotroski_fact(
                    user_id=user.id,
                    stock_id=stock.id,
                    metric_key=metric_key,
                    year=year,
                    value=float(value),
                    value_json={
                        "status": "calculated",
                        "variant": "valueline_proxy",
                        "fact_nature": (
                            "estimate"
                            if metric_key == "score.piotroski.roa_positive" and year == 2026
                            else "actual"
                        ),
                        "fiscal_year": year,
                        "formula": f"{metric_key}[Y] test formula",
                        "inputs": [
                            {
                                "metric_key": f"{metric_key}.input",
                                "value_numeric": float(value) * 10,
                                "period_end_date": f"{year}-12-31",
                                    "fact_nature": (
                                        "estimate"
                                        if metric_key == "score.piotroski.roa_positive" and year == 2026
                                        else "actual"
                                    ),
                            }
                        ],
                    },
                )
            )
    for year, value in zip(years, [7, 7, 8, 7, 7]):
        facts.append(
            _piotroski_fact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="score.piotroski.total",
                year=year,
                value=float(value),
            )
        )
    facts.append(
        _piotroski_fact(
            user_id=user.id,
            stock_id=other_stock.id,
            metric_key="score.piotroski.total",
            year=2026,
            value=2.0,
        )
    )
    db_session.add_all(facts)
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/fsc_test")

    assert response.status_code == 200
    card = response.json()["piotroski_f_score_card"]
    assert card["years"] == [2022, 2023, 2024, 2025, 2026]
    assert len(card["rows"]) == 10
    assert card["rows"] == [
        {
            "category": "盈利",
            "check": "ROA > 0",
            "metric_key": "score.piotroski.roa_positive",
            "formula": "score.piotroski.roa_positive[Y] test formula",
            "formula_details": {
                "standard_definition": "ROA is positive.",
                "standard_formula": "returns.roa[Y] > 0",
                "fallback_formulas": [
                    "is.net_income[Y] > 0",
                    "returns.total_capital[Y] > 0",
                ],
                "used_formula": "score.piotroski.roa_positive[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.roa_positive.input",
                        "value_numeric": 10.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "estimate",
                    }
                ],
            },
            "scores": [1, 1, 1, 1, 1],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "estimate"],
            "status": "✅",
            "status_tone": "success",
            "comment": "最近 5 年全部通过，盈利底盘稳健。",
        },
        {
            "category": "",
            "check": "CFO > 0",
            "metric_key": "score.piotroski.cfo_positive",
            "formula": "score.piotroski.cfo_positive[Y] test formula",
            "formula_details": {
                "standard_definition": "Operating cash flow is positive.",
                "standard_formula": "is.operating_cash_flow[Y] > 0",
                "fallback_formulas": ["per_share.cash_flow[Y] > 0"],
                "used_formula": "score.piotroski.cfo_positive[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.cfo_positive.input",
                        "value_numeric": 10.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [1, 1, 1, 1, 1],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "✅",
            "status_tone": "success",
            "comment": "最近 5 年全部通过，现金流为正。",
        },
        {
            "category": "",
            "check": "ROA 提升",
            "metric_key": "score.piotroski.roa_improving",
            "formula": "score.piotroski.roa_improving[Y] test formula",
            "formula_details": {
                "standard_definition": "ROA improves from the prior year.",
                "standard_formula": "returns.roa[Y] > returns.roa[Y-1]",
                "fallback_formulas": ["returns.total_capital[Y] > returns.total_capital[Y-1]"],
                "used_formula": "score.piotroski.roa_improving[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.roa_improving.input",
                        "value_numeric": 10.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [1, 0, 1, 0, 1],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "✅",
            "status_tone": "success",
            "comment": "最近年份通过，资产回报率改善。",
        },
        {
            "category": "",
            "check": "CFO>ROA",
            "metric_key": "score.piotroski.accrual_quality",
            "formula": "score.piotroski.accrual_quality[Y] test formula",
            "formula_details": {
                "standard_definition": "Operating cash flow exceeds net income.",
                "standard_formula": "is.operating_cash_flow[Y] > is.net_income[Y]",
                "fallback_formulas": ["per_share.cash_flow[Y] > per_share.eps[Y]"],
                "used_formula": "score.piotroski.accrual_quality[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.accrual_quality.input",
                        "value_numeric": 0.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [1, 1, 0, 0, 0],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "❌",
            "status_tone": "danger",
            "comment": "最近年份未通过，需要关注利润质量。",
        },
        {
            "category": "安全",
            "check": "杠杆率下降",
            "metric_key": "score.piotroski.leverage_declining",
            "formula": "score.piotroski.leverage_declining[Y] test formula",
            "formula_details": {
                "standard_definition": "Long-term leverage declines from the prior year.",
                "standard_formula": "leverage.long_term_debt_to_assets[Y] < leverage.long_term_debt_to_assets[Y-1]",
                "fallback_formulas": [
                    "leverage.long_term_debt_to_capital[Y] < leverage.long_term_debt_to_capital[Y-1]",
                    "cap.long_term_debt[Y] < cap.long_term_debt[Y-1]",
                ],
                "used_formula": "score.piotroski.leverage_declining[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.leverage_declining.input",
                        "value_numeric": 10.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [0, 0, 1, 1, 1],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "✅",
            "status_tone": "success",
            "comment": "最近年份通过，债务压力信号改善。",
        },
        {
            "category": "",
            "check": "流动比率提升",
            "metric_key": "score.piotroski.current_ratio_improving",
            "formula": "score.piotroski.current_ratio_improving[Y] test formula",
            "formula_details": {
                "standard_definition": "Current ratio improves from the prior year.",
                "standard_formula": "liquidity.current_ratio[Y] > liquidity.current_ratio[Y-1]",
                "fallback_formulas": [],
                "used_formula": "score.piotroski.current_ratio_improving[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.current_ratio_improving.input",
                        "value_numeric": 0.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [0, 1, 1, 1, 0],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "❌",
            "status_tone": "danger",
            "comment": "最近年份未通过，短期偿债能力承压。",
        },
        {
            "category": "",
            "check": "无股本稀释",
            "metric_key": "score.piotroski.no_dilution",
            "formula": "score.piotroski.no_dilution[Y] test formula",
            "formula_details": {
                "standard_definition": "Shares outstanding do not increase from the prior year.",
                "standard_formula": "equity.shares_outstanding[Y] <= equity.shares_outstanding[Y-1]",
                "fallback_formulas": [],
                "used_formula": "score.piotroski.no_dilution[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.no_dilution.input",
                        "value_numeric": 10.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [1, 1, 1, 1, 1],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "✅",
            "status_tone": "success",
            "comment": "最近 5 年全部通过，股本稀释压力低。",
        },
        {
            "category": "效率",
            "check": "毛利率提升",
            "metric_key": "score.piotroski.gross_margin_improving",
            "formula": "score.piotroski.gross_margin_improving[Y] test formula",
            "formula_details": {
                "standard_definition": "Gross margin improves from the prior year.",
                "standard_formula": "is.gross_margin[Y] > is.gross_margin[Y-1]",
                "fallback_formulas": [
                    "ins.underwriting_margin[Y] > ins.underwriting_margin[Y-1]",
                    "is.operating_margin[Y] > is.operating_margin[Y-1]",
                ],
                "used_formula": "score.piotroski.gross_margin_improving[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.gross_margin_improving.input",
                        "value_numeric": 0.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [1, 1, 1, 0, 0],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "❌",
            "status_tone": "danger",
            "comment": "最近年份未通过，成本或定价效率承压。",
        },
        {
            "category": "",
            "check": "资产周转率提升",
            "metric_key": "score.piotroski.asset_turnover_improving",
            "formula": "score.piotroski.asset_turnover_improving[Y] test formula",
            "formula_details": {
                "standard_definition": "Asset turnover improves from the prior year.",
                "standard_formula": "efficiency.asset_turnover[Y] > efficiency.asset_turnover[Y-1]",
                "fallback_formulas": [
                    "ins.premium_turnover[Y] > ins.premium_turnover[Y-1]",
                    "efficiency.capital_turnover[Y] > efficiency.capital_turnover[Y-1]",
                ],
                "used_formula": "score.piotroski.asset_turnover_improving[Y] test formula",
                "used_values": [
                    {
                        "metric_key": "score.piotroski.asset_turnover_improving.input",
                        "value_numeric": 0.0,
                        "period_end_date": "2026-12-31",
                        "fact_nature": "actual",
                    }
                ],
            },
            "scores": [0, 1, 1, 1, 0],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "❌",
            "status_tone": "danger",
            "comment": "最近年份未通过，资产使用效率承压。",
        },
        {
            "category": "总计",
            "check": "F-Score",
            "metric_key": "score.piotroski.total",
            "formula": "9 项 Piotroski 指标得分加总",
            "formula_details": {
                "standard_definition": "Total Piotroski F-Score sums the 9 binary component indicators.",
                "standard_formula": "sum(9 Piotroski component scores)",
                "fallback_formulas": ["Value Line proxy components when standard inputs are unavailable"],
                "used_formula": "9 项 Piotroski 指标得分加总",
                "used_values": [],
            },
            "scores": [7, 7, 8, 7, 7],
            "score_fact_natures": ["actual", "actual", "actual", "actual", "actual"],
            "status": "--",
            "status_tone": "secondary",
            "comment": "最新 F-Score 为 7，基本面维持强壮。",
        },
    ]


def test_lookup_stock_by_ticker_returns_summary(client, db_session):
    user = User(email="ticker_lookup@example.com")
    stock = Stock(ticker="COCO_TEST", exchange="NDQ", company_name="VITA COCO", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    doc = PdfDocument(
        user_id=user.id,
        file_name="coco.pdf",
        source="upload",
        file_storage_key="/tmp/coco.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    db_session.add(doc)
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "54.52", "normalized": 54.52, "unit": "USD"},
                value_numeric=54.52,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe",
                value_json={"raw": "43.3", "normalized": 43.3, "unit": "ratio"},
                value_numeric=43.3,
                unit="ratio",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share_normalized",
                value_json={"raw": "5.1", "normalized": 5.1, "unit": "USD"},
                value_numeric=5.1,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "5.5", "normalized": 5.5, "unit": "USD"},
                value_numeric=5.5,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "5.3", "normalized": 5.3, "unit": "USD"},
                value_numeric=5.3,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "5.1", "normalized": 5.1, "unit": "USD"},
                value_numeric=5.1,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "4.9", "normalized": 4.9, "unit": "USD"},
                value_numeric=4.9,
                unit="USD",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "4.7", "normalized": 4.7, "unit": "USD"},
                value_numeric=4.7,
                unit="USD",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_json={"raw": "4.5", "normalized": 4.5, "unit": "USD"},
                value_numeric=4.5,
                unit="USD",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"raw": "5.0", "normalized": 5.0, "unit": "USD"},
                value_numeric=5.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"raw": "4.9", "normalized": 4.9, "unit": "USD"},
                value_numeric=4.9,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"raw": "4.8", "normalized": 4.8, "unit": "USD"},
                value_numeric=4.8,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"raw": "4.7", "normalized": 4.7, "unit": "USD"},
                value_numeric=4.7,
                unit="USD",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"raw": "4.6", "normalized": 4.6, "unit": "USD"},
                value_numeric=4.6,
                unit="USD",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"raw": "4.5", "normalized": 4.5, "unit": "USD"},
                value_numeric=4.5,
                unit="USD",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.depreciation",
                value_json={"raw": "100", "normalized": 100.0, "unit": "USD"},
                value_numeric=100.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.depreciation",
                value_json={"raw": "100", "normalized": 100.0, "unit": "USD"},
                value_numeric=100.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.depreciation",
                value_json={"raw": "90", "normalized": 90.0, "unit": "USD"},
                value_numeric=90.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.depreciation",
                value_json={"raw": "80", "normalized": 80.0, "unit": "USD"},
                value_numeric=80.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.depreciation",
                value_json={"raw": "70", "normalized": 70.0, "unit": "USD"},
                value_numeric=70.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.depreciation",
                value_json={"raw": "70", "normalized": 70.0, "unit": "USD"},
                value_numeric=70.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="equity.shares_outstanding",
                value_json={"raw": "100", "normalized": 100.0, "unit": "shares"},
                value_numeric=100.0,
                unit="shares",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.5", "normalized": 0.5, "unit": "USD"},
                value_numeric=0.5,
                unit="USD",
                period_type="FY",
                period_end_date=date(2026, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
                unit="USD",
                period_type="FY",
                period_end_date=date(2023, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.6", "normalized": 0.6, "unit": "USD"},
                value_numeric=0.6,
                unit="USD",
                period_type="FY",
                period_end_date=date(2022, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.capital_spending",
                value_json={"raw": "0.7", "normalized": 0.7, "unit": "USD"},
                value_numeric=0.7,
                unit="USD",
                period_type="FY",
                period_end_date=date(2021, 12, 31),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.sales.cagr_est",
                value_json={"value": 6.5},
                value_numeric=0.065,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.cash_flow.cagr_est",
                value_json={"value": 7.5},
                value_numeric=0.075,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"value": 7.5},
                value_numeric=0.075,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )
    db_session.add(
        StockPrice(
            stock_id=stock.id,
            price_date=date(2026, 1, 10),
            open=54.0,
            high=56.5,
            low=53.5,
            close=55.25,
            adj_close=None,
            volume=123456,
            source="yfinance",
            created_at=datetime(2026, 1, 10, 21, 0, tzinfo=timezone.utc),
        )
    )
    db_session.flush()
    db_session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == user.id,
            MetricFact.stock_id == stock.id,
            MetricFact.source_type == "parsed",
        )
        .values(source_document_id=doc.id)
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/coco_test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "COCO_TEST"
    assert payload["exchange"] == "NDQ"
    assert payload["company_name"] == "VITA COCO"
    assert payload["price"] == 54.52
    assert payload["latest_price"] == 55.25
    assert payload["latest_price_date"] == "2026-01-10"
    assert payload["active_report_document_id"] == doc.id
    assert payload["active_report_date"] == "2026-01-09"
    assert payload["pe"] == 43.3
    assert payload["price_provenance"] == {
        "source_type": "parsed",
        "source_document_id": doc.id,
        "source_report_date": "2026-01-09",
        "period_end_date": "2026-01-09",
        "is_active_report": True,
    }
    assert payload["pe_provenance"] == {
        "source_type": "parsed",
        "source_document_id": doc.id,
        "source_report_date": "2026-01-09",
        "period_end_date": "2026-01-09",
        "is_active_report": True,
    }
    assert payload["oeps_normalized"] == 5.1
    assert payload["oeps_normalized_provenance"] == {
        "source_type": "parsed",
        "source_document_id": doc.id,
        "source_report_date": "2026-01-09",
        "period_end_date": "2026-01-09",
        "is_active_report": True,
    }
    assert payload["oeps_series"] == [
        {
            "year": 2026,
            "value": 5.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2025,
            "value": 5.3,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2025-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2024,
            "value": 5.1,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2024-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2023,
            "value": 4.9,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2023-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2022,
            "value": 4.7,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2022-12-31",
                "is_active_report": True,
            },
        },
        {
            "year": 2021,
            "value": 4.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2021-12-31",
                "is_active_report": True,
            },
        },
    ]
    assert payload["dcf_inputs"] == {
        "net_profit_per_share": {
            "value": 4.8,
            "source": "fact",
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2024-12-31",
                "is_active_report": True,
            },
        },
        "depreciation_per_share": {
            "value": 0.9,
            "source": "computed",
            "provenance": {
                "inputs": [
                    {
                        "metric_key": "is.depreciation",
                        "source_type": "parsed",
                        "source_document_id": doc.id,
                        "source_report_date": "2026-01-09",
                        "period_end_date": "2024-12-31",
                        "is_active_report": True,
                    },
                    {
                        "metric_key": "equity.shares_outstanding",
                        "source_type": "parsed",
                        "source_document_id": doc.id,
                        "source_report_date": "2026-01-09",
                        "period_end_date": "2024-12-31",
                        "is_active_report": True,
                    },
                ],
            },
        },
        "capital_spending_per_share": {
            "value": 0.6,
            "source": "fact",
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2024-12-31",
                "is_active_report": True,
            },
        },
    }
    assert payload["dcf_inputs_series"][0]["net_profit_per_share"]["provenance"]["period_end_date"] == "2026-12-31"
    assert payload["dcf_inputs_series"][0]["depreciation_per_share"]["provenance"]["inputs"][0]["metric_key"] == "is.depreciation"
    assert payload["dcf_inputs_series"] == [
        {
            "year": 2026,
            "net_profit_per_share": {
                "value": 5.0,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2026-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 1.0,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2026-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2026-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.5,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2026-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2025,
            "net_profit_per_share": {
                "value": 4.9,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2025-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 1.0,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2025-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2025-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2025-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2024,
            "net_profit_per_share": {
                "value": 4.8,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2024-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.9,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2024-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2024-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2024-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2023,
            "net_profit_per_share": {
                "value": 4.7,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2023-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.8,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2023-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2023-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2023-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2022,
            "net_profit_per_share": {
                "value": 4.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2022-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.7,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2022-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2022-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.6,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2022-12-31",
                    "is_active_report": True,
                },
            },
        },
        {
            "year": 2021,
            "net_profit_per_share": {
                "value": 4.5,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2021-12-31",
                    "is_active_report": True,
                },
            },
            "depreciation_per_share": {
                "value": 0.7,
                "source": "computed",
                "provenance": {
                    "inputs": [
                        {
                            "metric_key": "is.depreciation",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2021-12-31",
                            "is_active_report": True,
                        },
                        {
                            "metric_key": "equity.shares_outstanding",
                            "source_type": "parsed",
                            "source_document_id": doc.id,
                            "source_report_date": "2026-01-09",
                            "period_end_date": "2021-12-31",
                            "is_active_report": True,
                        },
                    ],
                },
            },
            "capital_spending_per_share": {
                "value": 0.7,
                "source": "fact",
                "provenance": {
                    "source_type": "parsed",
                    "source_document_id": doc.id,
                    "source_report_date": "2026-01-09",
                    "period_end_date": "2021-12-31",
                    "is_active_report": True,
                },
            },
        },
    ]
    assert payload["growth_rate_options"] == [
        {
            "key": "sales",
            "label": "Sales",
            "value": 6.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-01-09",
                "is_active_report": True,
            },
        },
        {
            "key": "cash_flow",
            "label": "Cash Flow",
            "value": 7.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-01-09",
                "is_active_report": True,
            },
        },
        {
            "key": "earnings",
            "label": "Earnings",
            "value": 7.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": doc.id,
                "source_report_date": "2026-01-09",
                "period_end_date": "2026-01-09",
                "is_active_report": True,
            },
        },
    ]


def test_lookup_stock_by_ticker_returns_active_report_metadata(client, db_session):
    user = User(email="ticker_active_report@example.com")
    stock = Stock(ticker="FICO_TEST", exchange="NYSE", company_name="Fair Isaac", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q1.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q1.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="fico-q2.pdf",
        source="upload",
        file_storage_key="/tmp/fico-q2.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 4, 9),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="mkt.price",
                value_json={"raw": "110", "fact_nature": "snapshot"},
                value_numeric=110.0,
                unit="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.pe",
                value_json={"raw": "35", "fact_nature": "snapshot"},
                value_numeric=35.0,
                unit="ratio",
                period_type="AS_OF",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/fico_test")
    assert response.status_code == 200

    payload = response.json()
    assert payload["active_report_document_id"] == new_doc.id
    assert payload["active_report_date"] == "2026-04-09"


def test_lookup_stock_by_ticker_returns_actual_conflicts(client, db_session):
    user = User(email="ticker_conflicts@example.com")
    stock = Stock(ticker="CONF_TEST", exchange="NYSE", company_name="Conflict Co", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    old_doc = PdfDocument(
        user_id=user.id,
        file_name="conf-q1.pdf",
        source="upload",
        file_storage_key="/tmp/conf-q1.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    new_doc = PdfDocument(
        user_id=user.id,
        file_name="conf-q2.pdf",
        source="upload",
        file_storage_key="/tmp/conf-q2.pdf",
        parse_status="parsed",
        stock_id=stock.id,
        report_date=date(2026, 4, 9),
    )
    db_session.add_all([old_doc, new_doc])
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual", "raw": "100"},
                value_numeric=100.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_json={"fact_nature": "actual", "raw": "120"},
                value_numeric=120.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"fact_nature": "actual", "raw": "5.0"},
                value_numeric=5.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="per_share.eps",
                value_json={"fact_nature": "actual", "raw": "5.0"},
                value_numeric=5.0,
                unit="USD",
                period_type="FY",
                period_end_date=date(2024, 12, 31),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"fact_nature": "estimate", "value": 10.0},
                value_numeric=0.10,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=old_doc.id,
                is_current=False,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"fact_nature": "estimate", "value": 12.0},
                value_numeric=0.12,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 4, 9),
                source_type="parsed",
                source_document_id=new_doc.id,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/conf_test")
    assert response.status_code == 200

    payload = response.json()
    assert payload["actual_conflict_count"] == 1
    assert payload["actual_conflicts"] == [
        {
            "metric_key": "is.net_income",
            "period_type": "FY",
            "period_end_date": "2024-12-31",
            "observations": [
                {
                    "source_document_id": new_doc.id,
                    "source_report_date": "2026-04-09",
                    "value_numeric": 120.0,
                    "value_text": None,
                    "is_active_report": True,
                },
                {
                    "source_document_id": old_doc.id,
                    "source_report_date": "2026-01-09",
                    "value_numeric": 100.0,
                    "value_text": None,
                    "is_active_report": False,
                },
            ],
        }
    ]


def test_lookup_stock_by_ticker_uses_revenues_growth_when_sales_missing(client, db_session):
    user = User(email="ticker_lookup_revenues@example.com")
    stock = Stock(ticker="REV_TEST", exchange="NDQ", company_name="REVENUES INC", is_active=True)
    db_session.add_all([user, stock])
    db_session.commit()

    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.revenues.cagr_est",
                value_json={"value": 11.0},
                value_numeric=0.11,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.cash_flow.cagr_est",
                value_json={"value": 7.5},
                value_numeric=0.075,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="rates.earnings.cagr_est",
                value_json={"value": 5.0},
                value_numeric=0.05,
                unit="ratio",
                period_type="PROJECTION_RANGE",
                period_end_date=date(2026, 1, 9),
                source_type="parsed",
                source_ref_id=None,
                is_current=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/v1/stocks/by_ticker/rev_test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "REV_TEST"
    assert payload["growth_rate_options"] == [
        {
            "key": "revenues",
            "label": "Revenues",
            "value": 11.0,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2026-01-09",
                "is_active_report": False,
            },
        },
        {
            "key": "cash_flow",
            "label": "Cash Flow",
            "value": 7.5,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2026-01-09",
                "is_active_report": False,
            },
        },
        {
            "key": "earnings",
            "label": "Earnings",
            "value": 5.0,
            "provenance": {
                "source_type": "parsed",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2026-01-09",
                "is_active_report": False,
            },
        },
    ]


def test_lookup_stock_by_ticker_not_found(client):
    response = client.get("/api/v1/stocks/by_ticker/UNKNOWN")

    assert response.status_code == 404
