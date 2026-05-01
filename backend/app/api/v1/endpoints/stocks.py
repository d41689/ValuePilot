from typing import Any
from fastapi import APIRouter, HTTPException, Body, Query
from sqlalchemy import select, func, update, and_, or_
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from app.api.deps import SessionDep, CurrentUser
from app.models.artifacts import PdfDocument
from app.models.stocks import Stock, StockPrice
from app.models.facts import MetricFact
from app.models.users import User
from app.services.active_report_resolver import ActiveReportSelection, resolve_active_reports
from app.services.actual_conflict_service import detect_actual_conflicts
from app.services.market_data_service import MarketDataService
from app.services.market_data_service import compute_target_date

router = APIRouter()

ET = ZoneInfo("America/New_York")
FAIR_VALUE_KEY = "val.fair_value"
DCF_INPUT_FACT_KEYS = {
    "net_profit_per_share": "per_share.eps",
    "depreciation": "is.depreciation",
    "shares_outstanding": "equity.shares_outstanding",
    "capital_spending_per_share": "per_share.capital_spending",
}
PIOTROSKI_CARD_ROWS = [
    {
        "category": "盈利",
        "check": "ROA > 0",
        "metric_key": "score.piotroski.roa_positive",
        "standard_definition": "ROA is positive.",
        "formula": "returns.roa[Y] > 0",
        "fallback_formulas": ["is.net_income[Y] > 0", "returns.total_capital[Y] > 0"],
        "all_pass_comment": "最近 5 年全部通过，盈利底盘稳健。",
        "pass_comment": "最近年份通过，盈利底盘保持稳健。",
        "fail_comment": "最近年份未通过，需要关注盈利质量。",
        "missing_comment": "数据不足，暂无法判断盈利底盘。",
    },
    {
        "category": "",
        "check": "CFO > 0",
        "metric_key": "score.piotroski.cfo_positive",
        "standard_definition": "Operating cash flow is positive.",
        "formula": "is.operating_cash_flow[Y] > 0",
        "fallback_formulas": ["per_share.cash_flow[Y] > 0"],
        "all_pass_comment": "最近 5 年全部通过，现金流为正。",
        "pass_comment": "最近年份通过，经营现金流为正。",
        "fail_comment": "最近年份未通过，需要关注现金流质量。",
        "missing_comment": "数据不足，暂无法判断现金流正负。",
    },
    {
        "category": "",
        "check": "ROA 提升",
        "metric_key": "score.piotroski.roa_improving",
        "standard_definition": "ROA improves from the prior year.",
        "formula": "returns.roa[Y] > returns.roa[Y-1]",
        "fallback_formulas": ["returns.total_capital[Y] > returns.total_capital[Y-1]"],
        "all_pass_comment": "最近 5 年全部通过，资产回报率持续改善。",
        "pass_comment": "最近年份通过，资产回报率改善。",
        "fail_comment": "最近年份未通过，需要关注资产回报率趋势。",
        "missing_comment": "数据不足，暂无法判断 ROA 趋势。",
    },
    {
        "category": "",
        "check": "CFO>ROA",
        "metric_key": "score.piotroski.accrual_quality",
        "standard_definition": "Operating cash flow exceeds net income.",
        "formula": "is.operating_cash_flow[Y] > is.net_income[Y]",
        "fallback_formulas": ["per_share.cash_flow[Y] > per_share.eps[Y]"],
        "all_pass_comment": "最近 5 年全部通过，利润质量稳定。",
        "pass_comment": "最近年份通过，现金流质量改善。",
        "fail_comment": "最近年份未通过，需要关注利润质量。",
        "missing_comment": "数据不足，暂无法判断利润质量。",
    },
    {
        "category": "安全",
        "check": "杠杆率下降",
        "metric_key": "score.piotroski.leverage_declining",
        "standard_definition": "Long-term leverage declines from the prior year.",
        "formula": "leverage.long_term_debt_to_assets[Y] < leverage.long_term_debt_to_assets[Y-1]",
        "fallback_formulas": [
            "leverage.long_term_debt_to_capital[Y] < leverage.long_term_debt_to_capital[Y-1]",
            "cap.long_term_debt[Y] < cap.long_term_debt[Y-1]",
        ],
        "all_pass_comment": "最近 5 年全部通过，债务压力持续减轻。",
        "pass_comment": "最近年份通过，债务压力信号改善。",
        "fail_comment": "最近年份未通过，需要关注债务压力。",
        "missing_comment": "数据不足，暂无法判断杠杆趋势。",
    },
    {
        "category": "",
        "check": "流动比率提升",
        "metric_key": "score.piotroski.current_ratio_improving",
        "standard_definition": "Current ratio improves from the prior year.",
        "formula": "liquidity.current_ratio[Y] > liquidity.current_ratio[Y-1]",
        "fallback_formulas": [],
        "all_pass_comment": "最近 5 年全部通过，短期偿债能力持续改善。",
        "pass_comment": "最近年份通过，短期偿债能力改善。",
        "fail_comment": "最近年份未通过，短期偿债能力承压。",
        "missing_comment": "数据不足，暂无法判断流动性趋势。",
    },
    {
        "category": "",
        "check": "无股本稀释",
        "metric_key": "score.piotroski.no_dilution",
        "standard_definition": "Shares outstanding do not increase from the prior year.",
        "formula": "equity.shares_outstanding[Y] <= equity.shares_outstanding[Y-1]",
        "fallback_formulas": [],
        "all_pass_comment": "最近 5 年全部通过，股本稀释压力低。",
        "pass_comment": "最近年份通过，股本稀释压力低。",
        "fail_comment": "最近年份未通过，需要关注股本稀释。",
        "missing_comment": "数据不足，暂无法判断股本稀释。",
    },
    {
        "category": "效率",
        "check": "毛利率提升",
        "metric_key": "score.piotroski.gross_margin_improving",
        "standard_definition": "Gross margin improves from the prior year.",
        "formula": "is.gross_margin[Y] > is.gross_margin[Y-1]",
        "fallback_formulas": [
            "ins.underwriting_margin[Y] > ins.underwriting_margin[Y-1]",
            "is.operating_margin[Y] > is.operating_margin[Y-1]",
        ],
        "all_pass_comment": "最近 5 年全部通过，成本和定价效率稳定。",
        "pass_comment": "最近年份通过，成本或定价效率改善。",
        "fail_comment": "最近年份未通过，成本或定价效率承压。",
        "missing_comment": "数据不足，暂无法判断效率趋势。",
    },
    {
        "category": "",
        "check": "资产周转率提升",
        "metric_key": "score.piotroski.asset_turnover_improving",
        "standard_definition": "Asset turnover improves from the prior year.",
        "formula": "efficiency.asset_turnover[Y] > efficiency.asset_turnover[Y-1]",
        "fallback_formulas": [
            "ins.premium_turnover[Y] > ins.premium_turnover[Y-1]",
            "efficiency.capital_turnover[Y] > efficiency.capital_turnover[Y-1]",
        ],
        "all_pass_comment": "最近 5 年全部通过，资产使用效率持续改善。",
        "pass_comment": "最近年份通过，资产使用效率改善。",
        "fail_comment": "最近年份未通过，资产使用效率承压。",
        "missing_comment": "数据不足，暂无法判断资产周转趋势。",
    },
]
PIOTROSKI_TOTAL_KEY = "score.piotroski.total"


def _dcf_value(value: float, source: str, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"value": float(value), "source": source}
    if provenance is not None:
        payload["provenance"] = provenance
    return payload


def _fact_provenance(
    fact: MetricFact | None,
    *,
    active_report: ActiveReportSelection | None,
    report_dates_by_doc: dict[int, date | None],
) -> dict[str, Any] | None:
    if fact is None:
        return None
    document_id = fact.source_document_id
    report_date = report_dates_by_doc.get(document_id) if document_id is not None else None
    return {
        "source_type": fact.source_type,
        "source_document_id": document_id,
        "source_report_date": report_date.isoformat() if report_date else None,
        "period_end_date": fact.period_end_date.isoformat() if fact.period_end_date else None,
        "is_active_report": bool(
            active_report is not None
            and document_id is not None
            and active_report.document_id == document_id
        ),
    }


def _computed_dcf_provenance(
    facts: list[tuple[str, MetricFact | None]],
    *,
    active_report: ActiveReportSelection | None,
    report_dates_by_doc: dict[int, date | None],
) -> dict[str, Any] | None:
    inputs = []
    for metric_key, fact in facts:
        provenance = _fact_provenance(
            fact,
            active_report=active_report,
            report_dates_by_doc=report_dates_by_doc,
        )
        if provenance is None:
            continue
        inputs.append({"metric_key": metric_key, **provenance})
    if not inputs:
        return None
    return {"inputs": inputs}


def _score_value(fact: MetricFact | None) -> int | float | None:
    if fact is None:
        return None
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    raw_value = fact.value_numeric
    if raw_value is None:
        raw_value = value_json.get("partial_score")
    if not isinstance(raw_value, (int, float)):
        return None
    value = float(raw_value)
    return int(value) if value.is_integer() else value


def _score_fact_nature(fact: MetricFact | None) -> str | None:
    value_json = fact.value_json if fact and isinstance(fact.value_json, dict) else {}
    inputs = value_json.get("inputs")
    if isinstance(inputs, list) and any(
        isinstance(item, dict) and item.get("fact_nature") == "estimate" for item in inputs
    ):
        return "estimate"
    fact_nature = value_json.get("fact_nature")
    if isinstance(fact_nature, str) and fact_nature:
        return fact_nature
    if isinstance(inputs, list) and inputs:
        return "actual"
    return None


def _score_year(fact: MetricFact) -> int | None:
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    fiscal_year = value_json.get("fiscal_year")
    if isinstance(fiscal_year, int):
        return fiscal_year
    if fact.period_end_date:
        return fact.period_end_date.year
    return None


def _piotroski_status_and_comment(
    values: list[int | float | None],
    row_config: dict[str, str],
) -> tuple[str, str, str]:
    numeric_values = [value for value in values if isinstance(value, (int, float))]
    if not numeric_values:
        return "⚠️", "warning", row_config["missing_comment"]
    latest = values[-1]
    if latest == 1:
        if len(numeric_values) == len(values) and all(value == 1 for value in numeric_values):
            return "✅", "success", row_config["all_pass_comment"]
        return "✅", "success", row_config["pass_comment"]
    if latest == 0:
        return "❌", "danger", row_config["fail_comment"]
    return "⚠️", "warning", row_config["missing_comment"]


def _row_formula(
    by_year: dict[int, MetricFact],
    display_years: list[int],
    fallback_formula: str,
) -> str:
    for year in reversed(display_years):
        fact = by_year.get(year)
        value_json = fact.value_json if fact and isinstance(fact.value_json, dict) else {}
        formula = value_json.get("formula")
        if isinstance(formula, str) and formula.strip():
            return formula
    return fallback_formula


def _used_values(fact: MetricFact | None) -> list[dict[str, Any]]:
    value_json = fact.value_json if fact and isinstance(fact.value_json, dict) else {}
    inputs = value_json.get("inputs")
    if not isinstance(inputs, list):
        return []
    used_values = []
    for item in inputs:
        if not isinstance(item, dict):
            continue
        used_values.append(
            {
                "metric_key": item.get("metric_key"),
                "value_numeric": item.get("value_numeric"),
                "period_end_date": item.get("period_end_date"),
                "fact_nature": item.get("fact_nature"),
            }
        )
    return used_values


def _latest_fact(by_year: dict[int, MetricFact], display_years: list[int]) -> MetricFact | None:
    for year in reversed(display_years):
        fact = by_year.get(year)
        if fact is not None:
            return fact
    return None


def _formula_details(
    *,
    row_config: dict[str, Any],
    formula: str,
    latest_fact: MetricFact | None,
) -> dict[str, Any]:
    fallback_formulas = []
    seen_fallbacks = set()
    for fallback_formula in row_config["fallback_formulas"]:
        if fallback_formula == formula or fallback_formula in seen_fallbacks:
            continue
        seen_fallbacks.add(fallback_formula)
        fallback_formulas.append(fallback_formula)
    return {
        "standard_definition": row_config["standard_definition"],
        "standard_formula": row_config["formula"],
        "fallback_formulas": fallback_formulas,
        "used_formula": formula,
        "used_values": _used_values(latest_fact),
    }


def _build_piotroski_f_score_card(session: SessionDep, stock_id: int) -> dict[str, Any]:
    metric_keys = [row["metric_key"] for row in PIOTROSKI_CARD_ROWS] + [PIOTROSKI_TOTAL_KEY]
    facts = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key.in_(metric_keys),
            MetricFact.source_type == "calculated",
            MetricFact.is_current.is_(True),
            MetricFact.period_type == "FY",
        )
        .order_by(MetricFact.period_end_date.desc(), MetricFact.created_at.desc())
    ).all()

    by_key_year: dict[str, dict[int, MetricFact]] = {metric_key: {} for metric_key in metric_keys}
    years: list[int] = []
    for fact in facts:
        year = _score_year(fact)
        if year is None:
            continue
        by_year = by_key_year.setdefault(fact.metric_key, {})
        if year not in by_year:
            by_year[year] = fact
        if year not in years:
            years.append(year)

    display_years = sorted(years, reverse=True)[:5]
    display_years.sort()
    rows = []
    for row_config in PIOTROSKI_CARD_ROWS:
        metric_facts_by_year = by_key_year[row_config["metric_key"]]
        scores = [_score_value(metric_facts_by_year.get(year)) for year in display_years]
        score_fact_natures = [_score_fact_nature(metric_facts_by_year.get(year)) for year in display_years]
        status, status_tone, comment = _piotroski_status_and_comment(scores, row_config)
        formula = _row_formula(metric_facts_by_year, display_years, row_config["formula"])
        rows.append(
            {
                "category": row_config["category"],
                "check": row_config["check"],
                "metric_key": row_config["metric_key"],
                "formula": formula,
                "formula_details": _formula_details(
                    row_config=row_config,
                    formula=formula,
                    latest_fact=_latest_fact(metric_facts_by_year, display_years),
                ),
                "scores": scores,
                "score_fact_natures": score_fact_natures,
                "status": status,
                "status_tone": status_tone,
                "comment": comment,
            }
        )

    total_scores = [_score_value(by_key_year[PIOTROSKI_TOTAL_KEY].get(year)) for year in display_years]
    total_score_fact_natures = [_score_fact_nature(by_key_year[PIOTROSKI_TOTAL_KEY].get(year)) for year in display_years]
    latest_total = next(
        (value for value in reversed(total_scores) if isinstance(value, (int, float))),
        None,
    )
    total_comment = (
        f"最新 F-Score 为 {latest_total}，基本面维持强壮。"
        if isinstance(latest_total, (int, float)) and latest_total >= 7
        else (
            f"最新 F-Score 为 {latest_total}，需要继续观察。"
            if isinstance(latest_total, (int, float))
            else "暂无可用 F-Score 总分。"
        )
    )
    rows.append(
        {
            "category": "总计",
            "check": "F-Score",
            "metric_key": PIOTROSKI_TOTAL_KEY,
            "formula": "9 项 Piotroski 指标得分加总",
            "formula_details": {
                "standard_definition": "Total Piotroski F-Score sums the 9 binary component indicators.",
                "standard_formula": "sum(9 Piotroski component scores)",
                "fallback_formulas": ["Value Line proxy components when standard inputs are unavailable"],
                "used_formula": "9 项 Piotroski 指标得分加总",
                "used_values": [],
            },
            "scores": total_scores,
            "score_fact_natures": total_score_fact_natures,
            "status": "--",
            "status_tone": "secondary",
            "comment": total_comment,
        }
    )

    return {"years": display_years, "rows": rows}


def _build_dcf_inputs_entry(
    inputs_by_key: dict[str, MetricFact | None],
    *,
    active_report: ActiveReportSelection | None,
    report_dates_by_doc: dict[int, date | None],
) -> dict[str, dict[str, Any]]:
    eps_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["net_profit_per_share"])
    capex_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["capital_spending_per_share"])
    depreciation_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["depreciation"])
    shares_fact = inputs_by_key.get(DCF_INPUT_FACT_KEYS["shares_outstanding"])

    eps_value = float(eps_fact.value_numeric) if eps_fact and eps_fact.value_numeric is not None else 0.0
    eps_source = "fact" if eps_fact and eps_fact.value_numeric is not None else "missing"

    capex_value = float(capex_fact.value_numeric) if capex_fact and capex_fact.value_numeric is not None else 0.0
    capex_source = "fact" if capex_fact and capex_fact.value_numeric is not None else "missing"

    depreciation_value = (
        float(depreciation_fact.value_numeric)
        if depreciation_fact and depreciation_fact.value_numeric is not None
        else 0.0
    )
    shares_value = float(shares_fact.value_numeric) if shares_fact and shares_fact.value_numeric is not None else 0.0
    depreciation_per_share = depreciation_value / shares_value if shares_value > 0 else 0.0
    depreciation_source = (
        "computed"
        if depreciation_fact and depreciation_fact.value_numeric is not None and shares_value > 0
        else "missing"
    )

    return {
        "net_profit_per_share": _dcf_value(
            eps_value,
            eps_source,
            _fact_provenance(
                eps_fact,
                active_report=active_report,
                report_dates_by_doc=report_dates_by_doc,
            ),
        ),
        "depreciation_per_share": _dcf_value(
            depreciation_per_share,
            depreciation_source,
            _computed_dcf_provenance(
                [
                    (DCF_INPUT_FACT_KEYS["depreciation"], depreciation_fact),
                    (DCF_INPUT_FACT_KEYS["shares_outstanding"], shares_fact),
                ],
                active_report=active_report,
                report_dates_by_doc=report_dates_by_doc,
            ),
        ),
        "capital_spending_per_share": _dcf_value(
            capex_value,
            capex_source,
            _fact_provenance(
                capex_fact,
                active_report=active_report,
                report_dates_by_doc=report_dates_by_doc,
            ),
        ),
    }


def _resolve_normalized_dcf_inputs(
    oeps_facts: list[MetricFact],
    dcf_inputs_series_by_year: dict[int, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]] | None:
    latest_five = [fact for fact in oeps_facts if fact.period_end_date is not None][:5]
    if not latest_five:
        return None

    ranked = sorted(
        latest_five,
        key=lambda fact: (
            float(fact.value_numeric) if fact.value_numeric is not None else 0.0,
            fact.period_end_date,
        ),
    )
    median_fact = ranked[len(ranked) // 2]
    median_year = median_fact.period_end_date.year if median_fact.period_end_date else None
    if median_year is None:
        return None
    return dcf_inputs_series_by_year.get(median_year)


def _visible_fact_predicate(current_user_id: int, admin_user_ids: list[int]):
    return or_(
        and_(
            MetricFact.source_type == "parsed",
            or_(
                MetricFact.user_id == current_user_id,
                MetricFact.user_id.in_(admin_user_ids),
            ),
        ),
        and_(
            MetricFact.user_id == current_user_id,
            MetricFact.source_type.in_(["manual", "calculated"]),
        ),
    )


@router.get("/by_ticker/{ticker}", response_model=dict)
def read_stock_by_ticker(
    ticker: str,
    session: SessionDep,
) -> Any:
    """
    Get stock overview by ticker (case-insensitive).
    """
    ticker_normalized = ticker.strip().lower()
    stmt = (
        select(Stock)
        .where(func.lower(Stock.ticker) == ticker_normalized)
        .order_by(Stock.id.asc())
        .limit(1)
    )
    stock = session.scalars(stmt).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    active_report = resolve_active_reports(session, stock_ids=[stock.id]).get(stock.id)

    facts_stmt = select(MetricFact).where(
        MetricFact.stock_id == stock.id,
        MetricFact.is_current.is_(True),
        MetricFact.metric_key.in_(
            ["mkt.price", "val.pe", "owners_earnings_per_share_normalized"]
        ),
    )
    facts = session.scalars(facts_stmt).all()
    facts_by_key = {fact.metric_key: fact for fact in facts}

    now_et = datetime.now(timezone.utc).astimezone(ET)
    target_date = compute_target_date(now_et)
    latest_price = session.scalars(
        select(StockPrice)
        .where(StockPrice.stock_id == stock.id, StockPrice.price_date == target_date)
        .order_by(StockPrice.created_at.desc())
        .limit(1)
    ).first()
    if latest_price is None:
        latest_price = session.scalars(
            select(StockPrice)
            .where(StockPrice.stock_id == stock.id)
            .order_by(StockPrice.price_date.desc(), StockPrice.created_at.desc())
            .limit(1)
        ).first()

    oeps_stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            MetricFact.metric_key == "owners_earnings_per_share",
            MetricFact.period_type == "FY",
        )
        .order_by(MetricFact.period_end_date.desc())
        .limit(6)
    )
    oeps_facts = session.scalars(oeps_stmt).all()

    dcf_inputs_stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            MetricFact.period_type == "FY",
            MetricFact.metric_key.in_(list(DCF_INPUT_FACT_KEYS.values())),
        )
        .order_by(MetricFact.metric_key.asc(), MetricFact.period_end_date.desc())
    )
    dcf_input_facts = session.scalars(dcf_inputs_stmt).all()
    dcf_inputs_by_date: dict[date, dict[str, MetricFact | None]] = {}
    for fact in dcf_input_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        by_key = dcf_inputs_by_date.setdefault(period_end, {})
        if fact.metric_key not in by_key:
            by_key[fact.metric_key] = fact

    dcf_inputs_series = []
    dcf_inputs_series_by_year: dict[int, dict[str, dict[str, Any]]] = {}

    growth_metric_keys = [
        "rates.sales.cagr_est",
        "rates.revenues.cagr_est",
        "rates.cash_flow.cagr_est",
        "rates.earnings.cagr_est",
    ]
    growth_stmt = (
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock.id,
            MetricFact.is_current.is_(True),
            MetricFact.metric_key.in_(growth_metric_keys),
        )
        .order_by(MetricFact.metric_key.asc(), MetricFact.period_end_date.desc())
    )
    growth_facts = session.scalars(growth_stmt).all()
    growth_by_metric_key: dict[str, float] = {}
    growth_fact_by_metric_key: dict[str, MetricFact] = {}

    def _growth_value_pct(fact: MetricFact) -> float | None:
        raw_value = None
        if isinstance(fact.value_json, dict):
            raw_value = fact.value_json.get("value")
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if fact.value_numeric is not None:
            return float(fact.value_numeric) * 100.0
        return None

    for fact in growth_facts:
        if fact.metric_key in growth_by_metric_key:
            continue
        value = _growth_value_pct(fact)
        if value is not None:
            growth_by_metric_key[fact.metric_key] = value
            growth_fact_by_metric_key[fact.metric_key] = fact

    provenance_facts = [*facts, *oeps_facts, *dcf_input_facts, *growth_facts]
    source_document_ids = sorted(
        {
            fact.source_document_id
            for fact in provenance_facts
            if fact.source_document_id is not None
        }
    )
    report_dates_by_doc: dict[int, date | None] = {}
    if source_document_ids:
        report_dates_by_doc = dict(
            session.execute(
                select(PdfDocument.id, PdfDocument.report_date).where(PdfDocument.id.in_(source_document_ids))
            ).all()
        )

    oeps_series = []
    for fact in oeps_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        value = fact.value_numeric if fact.value_numeric is not None else 0.0
        oeps_series.append(
            {
                "year": period_end.year,
                "value": value,
                "provenance": _fact_provenance(
                    fact,
                    active_report=active_report,
                    report_dates_by_doc=report_dates_by_doc,
                ),
            }
        )

    for fact in oeps_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        entry = _build_dcf_inputs_entry(
            dcf_inputs_by_date.get(period_end, {}),
            active_report=active_report,
            report_dates_by_doc=report_dates_by_doc,
        )
        dcf_inputs_series.append({"year": period_end.year, **entry})
        dcf_inputs_series_by_year[period_end.year] = entry
    dcf_inputs = _resolve_normalized_dcf_inputs(oeps_facts, dcf_inputs_series_by_year)

    growth_rate_options = []

    if "rates.sales.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {
                "key": "sales",
                "label": "Sales",
                "value": growth_by_metric_key["rates.sales.cagr_est"],
                "provenance": _fact_provenance(
                    growth_fact_by_metric_key.get("rates.sales.cagr_est"),
                    active_report=active_report,
                    report_dates_by_doc=report_dates_by_doc,
                ),
            }
        )
    elif "rates.revenues.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {
                "key": "revenues",
                "label": "Revenues",
                "value": growth_by_metric_key["rates.revenues.cagr_est"],
                "provenance": _fact_provenance(
                    growth_fact_by_metric_key.get("rates.revenues.cagr_est"),
                    active_report=active_report,
                    report_dates_by_doc=report_dates_by_doc,
                ),
            }
        )

    if "rates.cash_flow.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {
                "key": "cash_flow",
                "label": "Cash Flow",
                "value": growth_by_metric_key["rates.cash_flow.cagr_est"],
                "provenance": _fact_provenance(
                    growth_fact_by_metric_key.get("rates.cash_flow.cagr_est"),
                    active_report=active_report,
                    report_dates_by_doc=report_dates_by_doc,
                ),
            }
        )
    if "rates.earnings.cagr_est" in growth_by_metric_key:
        growth_rate_options.append(
            {
                "key": "earnings",
                "label": "Earnings",
                "value": growth_by_metric_key["rates.earnings.cagr_est"],
                "provenance": _fact_provenance(
                    growth_fact_by_metric_key.get("rates.earnings.cagr_est"),
                    active_report=active_report,
                    report_dates_by_doc=report_dates_by_doc,
                ),
            }
        )

    actual_conflicts = detect_actual_conflicts(
        session,
        stock_id=stock.id,
        active_report=active_report,
    )

    return {
        "id": stock.id,
        "ticker": stock.ticker,
        "exchange": stock.exchange,
        "company_name": stock.company_name,
        "active_report_document_id": active_report.document_id if active_report else None,
        "active_report_date": active_report.report_date.isoformat() if active_report and active_report.report_date else None,
        "price": facts_by_key.get("mkt.price").value_numeric if facts_by_key.get("mkt.price") else None,
        "price_provenance": _fact_provenance(
            facts_by_key.get("mkt.price"),
            active_report=active_report,
            report_dates_by_doc=report_dates_by_doc,
        ),
        "latest_price": float(latest_price.close) if latest_price and latest_price.close is not None else None,
        "latest_price_date": latest_price.price_date.isoformat() if latest_price else None,
        "latest_price_updated_at": latest_price.created_at.isoformat() if latest_price else None,
        "pe": facts_by_key.get("val.pe").value_numeric if facts_by_key.get("val.pe") else None,
        "pe_provenance": _fact_provenance(
            facts_by_key.get("val.pe"),
            active_report=active_report,
            report_dates_by_doc=report_dates_by_doc,
        ),
        "oeps_normalized": (
            facts_by_key.get("owners_earnings_per_share_normalized").value_numeric
            if facts_by_key.get("owners_earnings_per_share_normalized")
            else None
        ),
        "oeps_normalized_provenance": _fact_provenance(
            facts_by_key.get("owners_earnings_per_share_normalized"),
            active_report=active_report,
            report_dates_by_doc=report_dates_by_doc,
        ),
        "oeps_series": oeps_series,
        "dcf_inputs": dcf_inputs,
        "dcf_inputs_series": dcf_inputs_series,
        "growth_rate_options": growth_rate_options,
        "piotroski_f_score_card": _build_piotroski_f_score_card(session, stock.id),
        "actual_conflict_count": len(actual_conflicts),
        "actual_conflicts": actual_conflicts,
    }

@router.get("/{stock_id}", response_model=dict)
def read_stock(
    stock_id: int,
    session: SessionDep,
) -> Any:
    """
    Get stock overview by ID.
    """
    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    return {
        "id": stock.id,
        "ticker": stock.ticker,
        "exchange": stock.exchange,
        "company_name": stock.company_name,
        "is_active": stock.is_active,
        "created_at": stock.created_at
    }

@router.get("/{stock_id}/facts", response_model=list[dict])
def read_stock_facts(
    stock_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Get normalized metric facts for a stock.
    """
    # Verify stock exists
    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    admin_user_ids = list(session.scalars(select(User.id).where(User.role == "admin")).all())

    # Get current facts
    stmt = select(MetricFact).where(
        MetricFact.stock_id == stock_id,
        MetricFact.is_current.is_(True),
        _visible_fact_predicate(current_user.id, admin_user_ids),
    )
    facts = session.scalars(stmt).all()

    return [
        {
            "id": f.id,
            "metric_key": f.metric_key,
            "value_numeric": f.value_numeric,
            "unit": f.unit,
            "period": f.period,
            "period_end_date": f.period_end_date,
            "source_type": f.source_type
        }
        for f in facts
    ]


@router.put("/{stock_id}/facts", response_model=dict)
def upsert_stock_fact(
    *,
    stock_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    payload: dict = Body(...),
) -> Any:
    user_id = current_user.id

    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    metric_key = payload.get("metric_key")
    value_numeric = payload.get("value_numeric")
    if metric_key != FAIR_VALUE_KEY:
        raise HTTPException(status_code=400, detail="Unsupported metric_key")
    if value_numeric is None or not isinstance(value_numeric, (int, float)):
        raise HTTPException(status_code=400, detail="value_numeric must be a number")

    session.execute(
        update(MetricFact)
        .where(
            MetricFact.user_id == user_id,
            MetricFact.stock_id == stock_id,
            MetricFact.metric_key == metric_key,
            MetricFact.is_current.is_(True),
        )
        .values(is_current=False)
    )

    now_et = datetime.now(timezone.utc).astimezone(ET)
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=float(value_numeric),
        unit="USD",
        period_type="AS_OF",
        period_end_date=now_et.date(),
        source_type="manual",
        is_current=True,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)

    return {
        "id": fact.id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "value_numeric": fact.value_numeric,
        "unit": fact.unit,
        "period_type": fact.period_type,
        "period_end_date": fact.period_end_date,
        "source_type": fact.source_type,
        "is_current": fact.is_current,
        "created_at": fact.created_at,
    }


@router.post("/prices/refresh", response_model=list[dict])
def refresh_stock_prices(
    session: SessionDep,
    current_user: CurrentUser,
    payload: dict = Body(...),
) -> Any:
    stock_ids = payload.get("stock_ids")
    reason = payload.get("reason", "unspecified")
    if not isinstance(stock_ids, list) or not stock_ids:
        raise HTTPException(status_code=400, detail="stock_ids must be a non-empty list")

    service = MarketDataService(session)
    return service.refresh_stock_prices(stock_ids, reason=reason)
