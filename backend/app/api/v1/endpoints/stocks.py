from typing import Any
from fastapi import APIRouter, HTTPException, Body, Query
from sqlalchemy import select, func
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from app.api.deps import SessionDep, CurrentUser
from app.core.currencies import normalize_iso4217_currency
from app.models.artifacts import PdfDocument
from app.models.stocks import Stock
from app.models.facts import MetricFact
from app.services.valuation import USER_INTRINSIC_VALUE_KEY
from app.services.active_report_resolver import ActiveReportSelection, resolve_active_reports
from app.services.actual_conflict_service import detect_actual_conflicts
from app.services.canonical_financials import (
    CanonicalUnavailableError,
    CanonicalSourceConflictError,
    apply_reviewed_method_gates,
    current_sec_unresolved_states,
    guard_sec_run_availability,
    guard_source_selection,
    partition_sec_run_availability,
    resolve_sec_publication_evidence,
    reviewed_method_gate,
    visible_metric_fact_predicate,
)
from app.schemas.stock import ResearchValuationSave
from app.services.research_cases import (
    ResearchCaseError,
    save_product_valuation_revision,
)
from app.services.dcf_inputs import (
    DCF_CALCULATION_VERSION,
    DCF_EXPLICIT_SELECTION_RULE,
    DCF_INPUT_FACT_KEYS,
    DCF_MANIFEST_VERSION,
    DCF_MAX_MANIFEST_FACTS,
    DCF_MODEL_VERSION,
    DCF_NORMALIZED_SELECTION_RULE,
    DcfFactUniverseError,
    DcfModelError,
    calculate_dcf_model,
    dcf_evaluation_clock,
    dcf_manifest_token,
    evaluate_dcf_input_selection,
    load_canonical_dcf_fact_universe,
)
from app.services.market_data_service import (
    MarketDataService,
    read_current_eod_price,
    serialize_canonical_eod_price,
)

router = APIRouter()

ET = ZoneInfo("America/New_York")
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
        "fallback_formulas": [
            "bs.current_assets[Y] / bs.current_liabilities[Y] > bs.current_assets[Y-1] / bs.current_liabilities[Y-1]",
        ],
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


def _stock_summary_wire_number(
    value: Decimal | int | float | None,
) -> int | float | None:
    """Preserve the established JSON-number shape at the by-ticker boundary."""

    return float(value) if isinstance(value, Decimal) else value


def _stock_summary_currency(fact: MetricFact | None) -> str | None:
    if fact is None:
        return None
    if fact.currency is not None:
        return normalize_iso4217_currency(fact.currency)
    return normalize_iso4217_currency(fact.unit)


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


def _score_value(fact: MetricFact | None) -> int | float | None:
    if fact is None:
        return None
    value_json = fact.value_json if isinstance(fact.value_json, dict) else {}
    raw_value = fact.value_numeric
    if raw_value is None:
        raw_value = value_json.get("partial_score")
    if not isinstance(raw_value, (int, float, Decimal)):
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


def _used_values_for_years(
    by_year: dict[int, MetricFact],
    display_years: list[int],
) -> list[dict[str, Any]]:
    used_values: list[dict[str, Any]] = []
    for year in display_years:
        used_values.extend(_used_values(by_year.get(year)))
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
    metric_facts_by_year: dict[int, MetricFact],
    display_years: list[int],
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
        "used_values": _used_values_for_years(metric_facts_by_year, display_years),
    }


def _build_piotroski_f_score_card(
    session: SessionDep,
    stock_id: int,
    *,
    current_user_id: int,
) -> dict[str, Any]:
    metric_keys = [row["metric_key"] for row in PIOTROSKI_CARD_ROWS] + [PIOTROSKI_TOTAL_KEY]
    facts = session.scalars(
        select(MetricFact)
        .where(
            MetricFact.stock_id == stock_id,
            MetricFact.user_id == current_user_id,
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
                    metric_facts_by_year=metric_facts_by_year,
                    display_years=display_years,
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


DCF_ASSUMPTION_FIELDS = frozenset({"source", "label", "model"})
DCF_MODEL_FIELDS = frozenset(
    {
        "model_version",
        "selection",
        "input_manifest",
        "input_manifest_token",
        "actual_inputs",
        "user_override_fields",
        "growth_rate_selection",
        "client_result_per_share",
    }
)
DCF_OVERRIDEABLE_FIELDS = frozenset(
    {
        "net_profit_per_share",
        "depreciation_per_share",
        "capital_spending_per_share",
        "based_on_per_share",
    }
)
DCF_CANONICAL_COMPONENT_FIELDS = frozenset(
    {
        "net_profit_per_share",
        "depreciation_per_share",
        "capital_spending_per_share",
    }
)
DCF_OVERRIDE_LABELS = {
    "net_profit_per_share": "Net profit per share",
    "depreciation_per_share": "Depreciation per share",
    "capital_spending_per_share": "Capital spending per share",
    "based_on_per_share": "Based-on value per share",
}
DCF_CLIENT_RESULT_TOLERANCE = Decimal("0.01")
DCF_RESERVED_ASSUMPTION_FIELDS = frozenset(
    {
        "model",
        "model_version",
        "selection",
        "based_on_selection",
        "discount_rate_pct",
        "growth_years",
        "growth_rate_pct",
        "growth_rate_selection",
        "terminal_years",
        "terminal_rate_pct",
        "input_manifest",
        "input_manifest_token",
        "based_on_per_share",
        "computed_growth_value",
        "computed_terminal_value",
        "computed_total_value",
    }
)


def _dcf_selection_from_assumption(assumption: dict[str, Any]) -> str | int | None:
    model = assumption.get("model")
    selection = model.get("selection") if isinstance(model, dict) else None
    if selection == "norm":
        return "norm"
    if isinstance(selection, int) and not isinstance(selection, bool):
        return selection
    return None


def _selection_changed() -> ResearchCaseError:
    return ResearchCaseError(
        "dcf_input_selection_changed",
        "Canonical DCF inputs changed; reload the calculator before saving.",
        status_code=409,
    )


def _validated_dcf_save(
    session: SessionDep,
    *,
    stock_id: int,
    current_user_id: int,
    assumptions: list[dict[str, Any]],
    declared_currency: str | None,
    submitted_value: Decimal,
    server_evaluated_at: datetime,
) -> tuple[str, list[dict[str, Any]], Decimal]:
    dcf_assumptions = [
        item for item in assumptions if isinstance(item, dict) and item.get("source") == "dcf"
    ]
    if len(dcf_assumptions) != 1:
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "Exactly one structured DCF assumption is required.",
            status_code=409,
        )
    if any(
        item.get("source") != "dcf" and set(item) & DCF_RESERVED_ASSUMPTION_FIELDS
        for item in assumptions
        if isinstance(item, dict)
    ):
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "DCF fields may only appear in the one verified DCF assumption.",
            status_code=409,
        )
    submitted = dcf_assumptions[0]
    if set(submitted) != DCF_ASSUMPTION_FIELDS:
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "DCF assumption must contain exactly the versioned model contract.",
            status_code=409,
        )
    model = submitted.get("model")
    if not isinstance(model, dict) or set(model) != DCF_MODEL_FIELDS:
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "dcf_model_v1 must contain exactly the versioned model fields.",
            status_code=409,
        )
    if model.get("model_version") != DCF_MODEL_VERSION:
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "Unsupported DCF model version.",
            status_code=409,
        )
    growth_selection = model.get("growth_rate_selection")
    if growth_selection is not None and not isinstance(growth_selection, str):
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "DCF growth-rate selection must be a string or null.",
            status_code=409,
        )
    overrides = model.get("user_override_fields")
    if (
        not isinstance(overrides, list)
        or len(overrides) > len(DCF_OVERRIDEABLE_FIELDS)
        or any(not isinstance(field, str) for field in overrides)
        or len(set(overrides)) != len(overrides)
        or not set(overrides).issubset(DCF_OVERRIDEABLE_FIELDS)
    ):
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "DCF user overrides must be a unique bounded field list.",
            status_code=409,
        )
    actual_inputs = model.get("actual_inputs")
    if not isinstance(actual_inputs, dict):
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "DCF actual inputs must be a structured object.",
            status_code=409,
        )
    selection = _dcf_selection_from_assumption(submitted)
    manifest = model.get("input_manifest")
    submitted_token = model.get("input_manifest_token")
    if selection is None or not isinstance(manifest, dict) or not isinstance(submitted_token, str):
        raise ResearchCaseError(
            "dcf_assumption_invalid",
            "DCF assumption must include a selection and input manifest.",
            status_code=409,
        )
    if manifest.get("manifest_version") != DCF_MANIFEST_VERSION:
        raise _selection_changed()
    expected_rule = (
        DCF_NORMALIZED_SELECTION_RULE
        if selection == "norm"
        else DCF_EXPLICIT_SELECTION_RULE
    )
    if (
        manifest.get("selection") != selection
        or manifest.get("selection_rule_version") != expected_rule
        or dcf_manifest_token(manifest) != submitted_token
    ):
        raise _selection_changed()
    facts_manifest = manifest.get("facts")
    if not isinstance(facts_manifest, list) or len(facts_manifest) > DCF_MAX_MANIFEST_FACTS:
        raise _selection_changed()
    fact_ids = [item.get("id") for item in facts_manifest if isinstance(item, dict)]
    if (
        len(fact_ids) != len(facts_manifest)
        or any(not isinstance(fact_id, int) or isinstance(fact_id, bool) for fact_id in fact_ids)
        or len(set(fact_ids)) != len(fact_ids)
    ):
        raise _selection_changed()
    try:
        cutoff = datetime.fromisoformat(str(manifest.get("evaluated_at")))
    except (TypeError, ValueError) as error:
        raise _selection_changed() from error
    if cutoff.tzinfo is None or cutoff > server_evaluated_at:
        raise _selection_changed()

    cited_facts = session.scalars(
        select(MetricFact).where(
            MetricFact.id.in_(fact_ids),
            MetricFact.stock_id == stock_id,
            MetricFact.is_current.is_(True),
            MetricFact.created_at <= cutoff,
            _visible_fact_predicate(current_user_id, []),
        )
    ).all()
    if len(cited_facts) != len(fact_ids):
        raise _selection_changed()

    try:
        universe = load_canonical_dcf_fact_universe(
            session,
            stock_id=stock_id,
            user_id=current_user_id,
            evaluated_at=cutoff,
            effective_as_of=cutoff.astimezone(ET).date(),
        )
    except (CanonicalSourceConflictError, CanonicalUnavailableError) as error:
        raise _selection_changed() from error
    except DcfFactUniverseError as error:
        raise ResearchCaseError(error.code, str(error), status_code=409) from error
    entry = evaluate_dcf_input_selection(
        stock_id=stock_id,
        dcf_facts=universe.dcf_facts,
        oeps_facts=universe.oeps_facts,
        selection=selection,
        evaluated_at=cutoff,
    )
    if entry["input_manifest"] != manifest or entry["input_manifest_token"] != submitted_token:
        raise _selection_changed()
    state = entry["currency_state"]
    if state["status"] != "available" or state["currency"] is None:
        raise ResearchCaseError(
            state["reason_code"] or "dcf_input_currency_unavailable",
            "Canonical DCF inputs do not resolve to one verified currency.",
            status_code=409,
        )
    if declared_currency != state["currency"]:
        raise ResearchCaseError(
            "dcf_currency_declaration_mismatch",
            "Submitted DCF currency does not match canonical inputs.",
            status_code=409,
        )
    if state["currency"] != "USD":
        raise ResearchCaseError(
            "dcf_currency_not_supported",
            "Saving DCF valuations currently supports USD only.",
            status_code=409,
        )
    canonical_base = entry.get("canonical_model_inputs")
    if not isinstance(canonical_base, dict) or any(
        canonical_base.get(field) is None for field in DCF_OVERRIDEABLE_FIELDS
    ):
        raise ResearchCaseError(
            "dcf_input_unavailable",
            "Canonical DCF model inputs are unavailable.",
            status_code=409,
        )
    try:
        calculation = calculate_dcf_model(actual_inputs)
    except DcfModelError as error:
        raise ResearchCaseError(error.code, str(error), status_code=409) from error

    def decimal_input(field: str, source: dict[str, Any]) -> Decimal:
        try:
            value = Decimal(str(source[field]))
        except (InvalidOperation, KeyError, TypeError, ValueError) as error:
            raise ResearchCaseError(
                "dcf_assumption_invalid",
                "DCF monetary input is missing or invalid.",
                status_code=409,
            ) from error
        if not value.is_finite():
            raise ResearchCaseError(
                "dcf_assumption_invalid",
                "DCF monetary input must be finite.",
                status_code=409,
            )
        return value

    actual_components = {
        field: decimal_input(field, actual_inputs) for field in DCF_OVERRIDEABLE_FIELDS
    }
    canonical_components = {
        field: decimal_input(field, canonical_base) for field in DCF_OVERRIDEABLE_FIELDS
    }
    expected_overrides = {
        field
        for field in DCF_OVERRIDEABLE_FIELDS
        if actual_components[field] != canonical_components[field]
    }
    if set(overrides) != expected_overrides:
        raise ResearchCaseError(
            "dcf_override_unrecorded",
            "Every changed DCF component must be explicitly recorded as a user override.",
            status_code=409,
        )

    result = calculation["value_per_share"]
    try:
        client_result = Decimal(str(model.get("client_result_per_share")))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ResearchCaseError(
            "dcf_result_mismatch",
            "Client DCF result is invalid.",
            status_code=409,
        ) from error
    if (
        not client_result.is_finite()
        or not submitted_value.is_finite()
        or abs(client_result - result) > DCF_CLIENT_RESULT_TOLERANCE
        or abs(submitted_value - result) > DCF_CLIENT_RESULT_TOLERANCE
    ):
        raise ResearchCaseError(
            "dcf_result_mismatch",
            "Submitted DCF result does not match the server calculation.",
            status_code=409,
        )

    normalized_inputs = calculation["normalized_inputs"]

    def wire(value: Decimal | int) -> str | int:
        return value if isinstance(value, int) else str(value)

    def input_authority(field: str) -> str:
        if field in expected_overrides:
            return "user_override"
        if field in DCF_CANONICAL_COMPONENT_FIELDS:
            return "canonical_fact"
        if field == "based_on_per_share":
            return "derived_from_canonical_inputs"
        return "user_assumption"

    normalized_dcf: dict[str, Any] = {
        "source": "dcf",
        "label": "DCF model v1",
        "model_version": DCF_MODEL_VERSION,
        "calculation_version": DCF_CALCULATION_VERSION,
        "selection": selection,
        "growth_rate_selection": growth_selection,
        "valuation_currency": state["currency"],
        "canonical_base": {
            field: {
                "value": value,
                "authority": (
                    "canonical_fact"
                    if field in DCF_CANONICAL_COMPONENT_FIELDS
                    else "derived_from_canonical_inputs"
                ),
            }
            for field, value in canonical_base.items()
        },
        "actual_inputs": {
            field: {
                "value": wire(value),
                "authority": input_authority(field),
            }
            for field, value in normalized_inputs.items()
        },
        "user_overrides": [
            {"field": field, "label": DCF_OVERRIDE_LABELS[field]}
            for field in DCF_OVERRIDE_LABELS
            if field in expected_overrides
        ],
        "result": {
            "growth_value_per_share": str(calculation["growth_value_per_share"]),
            "terminal_value_per_share": str(calculation["terminal_value_per_share"]),
            "value_per_share": str(result),
            "currency": state["currency"],
        },
    }
    normalized_dcf["input_manifest"] = entry["input_manifest"]
    normalized_dcf["input_manifest_token"] = entry["input_manifest_token"]
    normalized_dcf["manifest_verified_at"] = server_evaluated_at.isoformat()
    normalized_assumptions = [
        normalized_dcf
        if isinstance(item, dict) and item.get("source") == "dcf"
        else item
        for item in assumptions
    ]
    return state["currency"], normalized_assumptions, result


def _visible_fact_predicate(current_user_id: int, admin_user_ids: list[int]):
    return visible_metric_fact_predicate(MetricFact, user_id=current_user_id)


def _select_stock_for_ticker(
    session: SessionDep,
    ticker_normalized: str,
    *,
    current_user_id: int,
    admin_user_ids: list[int],
) -> Stock | None:
    stocks = session.scalars(
        select(Stock)
        .where(func.lower(Stock.ticker) == ticker_normalized)
        .order_by(Stock.id.asc())
    ).all()
    if not stocks:
        return None
    if len(stocks) == 1:
        return stocks[0]

    stock_ids = [stock.id for stock in stocks]
    active_reports = resolve_active_reports(
        session,
        stock_ids=stock_ids,
        current_user_id=current_user_id,
        shared_parsed_user_ids=admin_user_ids,
    )
    fact_counts = dict(
        session.execute(
            select(MetricFact.stock_id, func.count(MetricFact.id))
            .where(
                MetricFact.stock_id.in_(stock_ids),
                MetricFact.is_current.is_(True),
                _visible_fact_predicate(current_user_id, admin_user_ids),
            )
            .group_by(MetricFact.stock_id)
        ).all()
    )

    def score(stock: Stock) -> tuple[int, date, int, int, int]:
        active_report = active_reports.get(stock.id)
        report_date = active_report.report_date if active_report and active_report.report_date else date.min
        return (
            1 if active_report else 0,
            report_date,
            int(fact_counts.get(stock.id, 0)),
            1 if stock.is_active else 0,
            -stock.id,
        )

    return max(stocks, key=score)


@router.get("/by_ticker/{ticker}", response_model=dict)
def read_stock_by_ticker(
    ticker: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Get stock overview by ticker (case-insensitive).
    """
    ticker_normalized = ticker.strip().lower()
    # Value Line and user-authored facts remain tenant-private.  SEC facts are
    # shared through the canonical visibility predicate, not through an admin
    # uploader convention.
    admin_user_ids: list[int] = []
    stock = _select_stock_for_ticker(
        session,
        ticker_normalized,
        current_user_id=current_user.id,
        admin_user_ids=admin_user_ids,
    )
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    dcf_clock = dcf_evaluation_clock()
    dcf_evaluated_at = dcf_clock.evaluated_at
    active_report = resolve_active_reports(
        session,
        stock_ids=[stock.id],
        current_user_id=current_user.id,
        shared_parsed_user_ids=admin_user_ids,
    ).get(stock.id)

    facts_stmt = select(MetricFact).where(
        MetricFact.stock_id == stock.id,
        MetricFact.is_current.is_(True),
        _visible_fact_predicate(current_user.id, admin_user_ids),
        MetricFact.metric_key.in_(
            ["mkt.price", "val.pe", "owners_earnings_per_share_normalized"]
        ),
    )
    facts = session.scalars(facts_stmt).all()

    current_price = read_current_eod_price(
        session,
        stock=stock,
        evaluated_at=dcf_evaluated_at,
    )

    oeps_facts: list[MetricFact] = []
    dcf_input_facts: list[MetricFact] = []
    canonical_input_status: dict[str, Any] = {"status": "available"}
    try:
        universe = load_canonical_dcf_fact_universe(
            session,
            stock_id=stock.id,
            user_id=current_user.id,
            evaluated_at=dcf_evaluated_at,
            effective_as_of=dcf_clock.effective_as_of,
        )
        oeps_facts = universe.oeps_facts
        dcf_input_facts = universe.dcf_facts
    except CanonicalSourceConflictError as error:
        dcf_input_facts = []
        canonical_input_status = {
            "status": "source_conflict",
            "reason_code": error.code,
            "source_types": list(error.source_types),
        }
    except CanonicalUnavailableError as error:
        canonical_input_status = error.state
    except DcfFactUniverseError as error:
        canonical_input_status = {
            "status": "unavailable",
            "reason_code": error.code,
        }
    method_gate_decisions = {
        method_key: reviewed_method_gate(
            session,
            stock_id=stock.id,
            method_key=method_key,
            effective_as_of=dcf_clock.effective_as_of,
            knowledge_at=dcf_evaluated_at,
        )
        for method_key in ("owner_earnings", "roic", "per_share_trend", "system_valuation")
    }
    dcf_inputs_series = []

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
            _visible_fact_predicate(current_user.id, admin_user_ids),
            MetricFact.metric_key.in_(growth_metric_keys),
        )
        .order_by(MetricFact.metric_key.asc(), MetricFact.period_end_date.desc())
    )
    growth_facts = session.scalars(growth_stmt).all()
    # Separate explicit user-authored outputs from legacy system-method facts
    # before any source or row selection can make authorization order-dependent.
    facts, _, _ = apply_reviewed_method_gates(
        session,
        stock_id=stock.id,
        facts=facts,
        effective_as_of=dcf_clock.effective_as_of,
        knowledge_at=dcf_evaluated_at,
    )
    try:
        summary_facts = guard_source_selection(
            [*facts, *oeps_facts, *growth_facts],
            consumer="stock_summary",
        )
        guard_sec_run_availability(
            session,
            stock_id=stock.id,
            facts=summary_facts,
        )
    except (CanonicalSourceConflictError, CanonicalUnavailableError) as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": str(error),
                "source_types": list(getattr(error, "source_types", ())),
            },
        ) from error
    facts_by_key: dict[str, MetricFact] = {}
    for fact in facts:
        current = facts_by_key.get(fact.metric_key)
        if current is None or (
            fact.period_end_date or date.min,
            fact.created_at or datetime.min.replace(tzinfo=timezone.utc),
            fact.id or 0,
        ) > (
            current.period_end_date or date.min,
            current.created_at or datetime.min.replace(tzinfo=timezone.utc),
            current.id or 0,
        ):
            facts_by_key[fact.metric_key] = fact
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
                select(PdfDocument.id, PdfDocument.report_date).where(
                    PdfDocument.id.in_(source_document_ids),
                    PdfDocument.user_id.in_(
                        sorted(set([current_user.id, *admin_user_ids]))
                    ),
                )
            ).all()
        )

    oeps_series = []
    for fact in oeps_facts:
        period_end = fact.period_end_date
        if not period_end:
            continue
        value = _stock_summary_wire_number(fact.value_numeric)
        if value is None:
            value = 0.0
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

    seen_dcf_years: set[int] = set()
    for fact in oeps_facts:
        period_end = fact.period_end_date
        if not period_end or period_end.year in seen_dcf_years:
            continue
        seen_dcf_years.add(period_end.year)
        entry = evaluate_dcf_input_selection(
            stock_id=stock.id,
            dcf_facts=dcf_input_facts,
            oeps_facts=oeps_facts,
            selection=period_end.year,
            evaluated_at=dcf_evaluated_at,
            provenance_for_fact=lambda input_fact: _fact_provenance(
                input_fact,
                active_report=active_report,
                report_dates_by_doc=report_dates_by_doc,
            ),
        )
        dcf_inputs_series.append({"year": period_end.year, **entry})
    dcf_inputs = (
        evaluate_dcf_input_selection(
            stock_id=stock.id,
            dcf_facts=dcf_input_facts,
            oeps_facts=oeps_facts,
            selection="norm",
            evaluated_at=dcf_evaluated_at,
            provenance_for_fact=lambda input_fact: _fact_provenance(
                input_fact,
                active_report=active_report,
                report_dates_by_doc=report_dates_by_doc,
            ),
        )
        if oeps_facts
        else None
    )

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
        current_user_id=current_user.id,
        shared_parsed_user_ids=admin_user_ids,
    )

    report_price_fact = facts_by_key.get("mkt.price")
    report_price_provenance = _fact_provenance(
        report_price_fact,
        active_report=active_report,
        report_dates_by_doc=report_dates_by_doc,
    )
    report_price_as_of = (
        report_price_provenance.get("source_report_date")
        or report_price_provenance.get("period_end_date")
        if report_price_provenance
        else None
    )

    return {
        "id": stock.id,
        "ticker": stock.ticker,
        "exchange": stock.listing_exchange or stock.exchange,
        "market_country": stock.market_country,
        "listing_exchange": stock.listing_exchange,
        "company_name": stock.company_name,
        "active_report_document_id": active_report.document_id if active_report else None,
        "active_report_date": active_report.report_date.isoformat() if active_report and active_report.report_date else None,
        "current_price": serialize_canonical_eod_price(current_price),
        "report_price_reference": {
            "label": "report_reference",
            "value": _stock_summary_wire_number(
                report_price_fact.value_numeric if report_price_fact else None
            ),
            "as_of_date": report_price_as_of,
            "currency": _stock_summary_currency(report_price_fact),
            "provenance": report_price_provenance,
        },
        "pe": _stock_summary_wire_number(
            facts_by_key.get("val.pe").value_numeric
            if facts_by_key.get("val.pe")
            else None
        ),
        "pe_provenance": _fact_provenance(
            facts_by_key.get("val.pe"),
            active_report=active_report,
            report_dates_by_doc=report_dates_by_doc,
        ),
        "oeps_normalized": _stock_summary_wire_number(
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
        "system_method_gates": {
            key: decision.as_dict() for key, decision in method_gate_decisions.items()
        },
        "canonical_input_status": canonical_input_status,
        "piotroski_f_score_card": _build_piotroski_f_score_card(
            session,
            stock.id,
            current_user_id=current_user.id,
        ),
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
        "exchange": stock.listing_exchange or stock.exchange,
        "market_country": stock.market_country,
        "listing_exchange": stock.listing_exchange,
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

    admin_user_ids: list[int] = []

    # Get current facts
    stmt = select(MetricFact).where(
        MetricFact.stock_id == stock_id,
        MetricFact.is_current.is_(True),
        _visible_fact_predicate(current_user.id, admin_user_ids),
    )
    facts = session.scalars(stmt).all()
    facts, _ = partition_sec_run_availability(
        session, stock_id=stock_id, facts=facts
    )
    facts, unsupported, _ = apply_reviewed_method_gates(
        session,
        stock_id=stock_id,
        facts=facts,
        effective_as_of=date.today(),
    )

    published = [
        {
            "id": f.id,
            "status": "published",
            "metric_key": f.metric_key,
            "value_numeric": f.value_numeric,
            "unit": f.unit,
            "period": f.period,
            "period_end_date": f.period_end_date,
            "source_type": f.source_type,
            "evidence_route": (
                f"/api/v1/stocks/{stock_id}/sec-publications/{f.source_ref_id}/evidence"
                if f.source_type == "sec" and f.source_ref_id is not None
                else None
            ),
        }
        for f in facts
    ]
    return published + unsupported + current_sec_unresolved_states(session, stock_id=stock_id)


@router.get("/{stock_id}/sec-publications/{publication_id}/evidence", response_model=dict)
def read_sec_publication_evidence(
    stock_id: int,
    publication_id: int,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    if session.get(Stock, stock_id) is None:
        raise HTTPException(status_code=404, detail="Stock not found")
    evidence = resolve_sec_publication_evidence(
        session,
        stock_id=stock_id,
        publication_id=publication_id,
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="SEC publication evidence not found")
    return evidence


@router.put("/{stock_id}/facts", response_model=dict)
def upsert_stock_fact(
    *,
    stock_id: int,
    session: SessionDep,
    current_user: CurrentUser,
    payload: ResearchValuationSave,
) -> Any:
    user_id = current_user.id

    stock = session.get(Stock, stock_id)
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    if payload.metric_key != USER_INTRINSIC_VALUE_KEY:
        raise HTTPException(status_code=400, detail="Unsupported metric_key")

    now_et = datetime.now(timezone.utc).astimezone(ET)
    try:
        valuation_currency = payload.valuation_currency or "USD"
        save_assumptions = payload.assumptions
        save_value = payload.value_numeric
        save_low = payload.valuation_low
        save_high = payload.valuation_high
        if payload.source == "dcf":
            if payload.as_of_date is not None and payload.as_of_date != now_et.date():
                raise ResearchCaseError(
                    "historical_dcf_save_unsupported",
                    "DCF results can only be saved for the current server date.",
                    status_code=409,
                )
            valuation_currency, save_assumptions, save_value = _validated_dcf_save(
                session,
                stock_id=stock_id,
                current_user_id=user_id,
                assumptions=payload.assumptions,
                declared_currency=payload.valuation_currency,
                submitted_value=payload.value_numeric,
                server_evaluated_at=now_et.astimezone(timezone.utc),
            )
            save_low = save_value
            save_high = save_value
        case, revision, fact = save_product_valuation_revision(
            session,
            user_id=user_id,
            stock_id=stock_id,
            value_numeric=save_value,
            valuation_low=save_low,
            valuation_high=save_high,
            as_of_date=payload.as_of_date or now_et.date(),
            source=payload.source,
            pool_id=payload.pool_id,
            assumptions=save_assumptions,
            valuation_currency=valuation_currency,
        )
    except ResearchCaseError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error

    return {
        "id": fact.id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "value_numeric": float(fact.value_numeric),
        "unit": fact.unit,
        "period_type": fact.period_type,
        "period_end_date": fact.period_end_date,
        "source_type": fact.source_type,
        "is_current": fact.is_current,
        "created_at": fact.created_at,
        "research_case_id": case.id,
        "research_revision_id": revision.id,
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
