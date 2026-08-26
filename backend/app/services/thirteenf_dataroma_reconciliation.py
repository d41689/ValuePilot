"""Read-only ValuePilot × Dataroma 13F reconciliation.

SEC filings and ValuePilot's active-filing/current-parse-run policy remain the
authority.  Dataroma values are never persisted into product tables; they are
used only to surface and classify discrepancies for investigation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.dataroma.client import (
    ACTIVITY_URL,
    HOLDINGS_URL,
    PORTFOLIO_HISTORY_URL,
    DataromaClient,
)
from app.dataroma.parsers.activity import DataromaActivity, parse_activity
from app.dataroma.parsers.history import DataromaPortfolioHistory, parse_portfolio_history
from app.dataroma.parsers.portfolio import (
    DataromaPageChanged,
    DataromaPortfolio,
    merge_portfolio_pages,
    parse_portfolio,
)
from app.models.institutions import InstitutionManager
from app.services.thirteenf_user_api import (
    build_user_manager_holding_changes,
    build_user_manager_holdings,
    build_user_manager_history,
)


@dataclass(frozen=True)
class ReconciliationDifference:
    scope: str
    field: str
    quarter: str | None
    ticker: str | None
    valuepilot: Any
    dataroma: Any
    classification: str
    valuepilot_defect: bool | None
    severity: str
    explanation: str


def compare_holdings(
    valuepilot: dict[str, Any],
    dataroma: DataromaPortfolio,
) -> list[ReconciliationDifference]:
    differences: list[ReconciliationDifference] = []
    vp_quarter = valuepilot.get("quarter")
    if vp_quarter != dataroma.quarter:
        differences.append(
            _difference(
                "holdings", "quarter", None, None, vp_quarter, dataroma.quarter,
                "source_timing", False, "warning",
                "The two sources expose different latest report quarters; numeric rows were not compared.",
            )
        )
        return differences

    summary = valuepilot.get("summary") or {}
    vp_count = summary.get("common_position_count")
    if vp_count != dataroma.position_count:
        differences.append(
            _difference(
                "holdings", "position_count", vp_quarter, None, vp_count,
                dataroma.position_count, "identity_or_coverage", None, "error",
                "The common-position counts differ after ValuePilot aggregation; inspect missing tickers, options, and coverage caveats.",
            )
        )
    vp_total = summary.get("reported_common_value_usd")
    source_row_count = sum(
        max(int(item.get("constituent_row_count") or 1), 1)
        for item in valuepilot.get("common_holdings") or []
    )
    total_tolerance = max(1_000, source_row_count * 1_000)
    if not _close(vp_total, dataroma.portfolio_value_usd, total_tolerance):
        differences.append(
            _difference(
                "holdings", "portfolio_value_usd", vp_quarter, None, vp_total,
                dataroma.portfolio_value_usd, "reporting_policy_or_value_unit", None, "error",
                f"Portfolio values differ beyond the ${total_tolerance:,} maximum row-rounding allowance.",
            )
        )

    vp_positions: dict[str, dict[str, Any]] = {}
    unlinked = 0
    for item in valuepilot.get("common_holdings") or []:
        ticker = _ticker((item.get("stock") or {}).get("ticker"))
        if ticker:
            vp_positions[ticker] = item
        else:
            unlinked += 1
    dr_positions = {_ticker(item.ticker): item for item in dataroma.holdings}
    if unlinked:
        differences.append(
            _difference(
                "holdings", "unlinked_position_count", vp_quarter, None, unlinked, 0,
                "identity_coverage_gap", None, "warning",
                "ValuePilot has common holdings whose CUSIPs remain unresolved or under review after authoritative enrichment; they cannot be reconciled by ticker without guessing from Dataroma.",
            )
        )

    for ticker in sorted(set(vp_positions) | set(dr_positions)):
        vp = vp_positions.get(ticker)
        dr = dr_positions.get(ticker)
        if vp is None or dr is None:
            differences.append(
                _difference(
                    "holdings", "position_presence", vp_quarter, ticker,
                    "missing" if vp is None else "present",
                    "missing" if dr is None else "present",
                    "identity_or_coverage", None, "error",
                    "A ticker exists in only one normalized holdings set; inspect SEC row identity, options, amendments, and Dataroma policy.",
                )
            )
            continue
        split_factor = _split_factor(vp.get("ssh_prnamt"), dr.shares)
        row_rounding_tolerance = max(
            1_000,
            int(vp.get("constituent_row_count") or 1) * 1_000,
        )
        value_matches = _close(
            vp.get("value_usd"),
            dr.value_usd,
            row_rounding_tolerance,
        )
        if vp.get("ssh_prnamt") != dr.shares:
            if split_factor and value_matches:
                explanation = (
                    f"Dataroma has {split_factor}-for-1 more shares while reported value is unchanged; "
                    "this is consistent with Dataroma retroactively split-adjusting the SEC-reported position."
                )
                classification, defect, severity = "identity_or_corporate_action", False, "info"
            else:
                explanation = "Share counts differ after normalization; inspect fractional splits, CUSIP transitions, amendments, and source adjustment policy."
                classification, defect, severity = "identity_or_source_policy", None, "warning"
            differences.append(
                _difference(
                    "holdings", "shares", vp_quarter, ticker, vp.get("ssh_prnamt"),
                    dr.shares, classification, defect, severity, explanation,
                )
            )
        if not value_matches:
            value_classification = (
                "identity_or_source_policy"
                if vp.get("ssh_prnamt") != dr.shares
                else "value_unit_or_aggregation"
            )
            value_severity = (
                "warning"
                if value_classification == "identity_or_source_policy"
                else "error"
            )
            differences.append(
                _difference(
                    "holdings", "value_usd", vp_quarter, ticker, vp.get("value_usd"),
                    dr.value_usd, value_classification, None, value_severity,
                    "Reported values differ beyond Dataroma's per-source-row $1,000 display precision.",
                )
            )
        vp_weight = _nested_number(vp, "portfolio_weight_pct", "value")
        if not _close(vp_weight, dr.portfolio_weight_pct, Decimal("0.01")):
            weight_reason = (vp.get("portfolio_weight_pct") or {}).get(
                "unavailable_reason"
            )
            if weight_reason == "PARTIAL_COVERAGE":
                classification, defect, severity = (
                    "intentional_coverage_caveat",
                    False,
                    "info",
                )
                explanation = (
                    "ValuePilot intentionally withholds portfolio weights for a partial filing; "
                    "Dataroma displays a denominator-derived estimate."
                )
            else:
                classification, defect, severity = (
                    "denominator_or_coverage",
                    None,
                    "error",
                )
                explanation = (
                    "Portfolio weights differ beyond the displayed 0.01 percentage-point precision."
                )
            differences.append(
                _difference(
                    "holdings", "portfolio_weight_pct", vp_quarter, ticker, vp_weight,
                    dr.portfolio_weight_pct, classification, defect, severity,
                    explanation,
                )
            )
        vp_price = vp.get("implied_report_price")
        price_tolerance = max(
            Decimal("0.01"),
            (Decimal(row_rounding_tolerance) / _decimal(vp.get("ssh_prnamt")))
            if vp.get("ssh_prnamt") else Decimal("0.01"),
        )
        if not _close(vp_price, dr.reported_price, price_tolerance):
            if split_factor and value_matches and vp_price is not None:
                classification, defect, severity = "identity_or_corporate_action", False, "info"
                explanation = (
                    f"The reported-price ratio is the inverse of the {split_factor}-for-1 share adjustment; "
                    "ValuePilot preserves raw SEC shares/value while Dataroma adjusts history."
                )
            else:
                classification, defect, severity = "value_unit_or_aggregation", None, "error"
                explanation = "Value ÷ shares does not match Dataroma's displayed reported price."
            differences.append(
                _difference(
                    "holdings", "reported_price", vp_quarter, ticker, vp_price,
                    dr.reported_price, classification, defect, severity, explanation,
                )
            )
    return differences


def compare_activity(
    valuepilot: dict[str, Any],
    dataroma: Iterable[DataromaActivity],
    *,
    current_portfolio_value_usd: int | None,
) -> list[ReconciliationDifference]:
    differences: list[ReconciliationDifference] = []
    quarter = valuepilot.get("quarter")
    dataroma = tuple(dataroma)
    dataroma_page_capped = len(dataroma) >= 100
    dr_rows = [row for row in dataroma if row.quarter == quarter]
    vp_rows = [
        item for item in (valuepilot.get("items") or [])
        if item.get("position_type") == "common"
        and item.get("change_status") in {"new_position", "increased", "reduced", "exited_position"}
    ]
    vp_by_ticker = {
        _ticker((item.get("stock") or {}).get("ticker")): item
        for item in vp_rows
        if _ticker((item.get("stock") or {}).get("ticker"))
    }
    dr_by_ticker = {_ticker(item.ticker): item for item in dr_rows}
    action_map = {
        "new_position": "buy",
        "increased": "add",
        "reduced": "reduce",
        "exited_position": "sell",
    }
    for ticker in sorted(set(vp_by_ticker) | set(dr_by_ticker)):
        vp = vp_by_ticker.get(ticker)
        dr = dr_by_ticker.get(ticker)
        if vp is None or dr is None:
            if vp is not None and dr is None and dataroma_page_capped:
                classification, defect, severity = (
                    "dataroma_page_limit",
                    False,
                    "info",
                )
                explanation = (
                    "ValuePilot has an activity row omitted from Dataroma's 100-row capped Activity page."
                )
            else:
                classification, defect, severity = (
                    "identity_or_coverage",
                    None,
                    "error",
                )
                explanation = "An activity row exists in only one normalized set."
            differences.append(
                _difference(
                    "activity", "position_presence", quarter, ticker,
                    "missing" if vp is None else "present",
                    "missing" if dr is None else "present", classification, defect,
                    severity, explanation,
                )
            )
            continue
        vp_action = action_map.get(vp.get("change_status"))
        if vp_action != dr.action:
            differences.append(
                _difference(
                    "activity", "action", quarter, ticker, vp_action, dr.action,
                    "identity_or_source_policy", None, "warning",
                    "The sources classify the quarter-over-quarter transition differently; inspect CUSIP changes, corporate actions, and source carry-forward policy.",
                )
            )
        vp_share_change = abs(vp.get("share_delta")) if vp.get("share_delta") is not None else None
        if vp_share_change != dr.share_change:
            factor = _split_factor(vp_share_change, dr.share_change)
            if factor and _activity_pct_matches(vp, dr):
                classification, defect, severity = "identity_or_corporate_action", False, "info"
                explanation = f"Share change differs by a {factor}-for-1 factor while activity percent matches."
            else:
                classification, defect, severity = "identity_or_source_policy", None, "warning"
                explanation = "Share-change amounts differ; inspect fractional splits, CUSIP transitions, amendments, and source carry-forward policy."
            differences.append(
                _difference(
                    "activity", "share_change", quarter, ticker, vp_share_change,
                    dr.share_change, classification, defect, severity, explanation,
                )
            )
        vp_pct = _expected_activity_pct(vp)
        if not _close(vp_pct, dr.activity_pct, Decimal("0.02")):
            pct_classification = (
                "calculation_policy_difference"
                if vp_pct is not None
                else "identity_or_source_policy"
            )
            pct_defect = False if vp_pct is not None else None
            differences.append(
                _difference(
                    "activity", "activity_pct", quarter, ticker, vp_pct,
                    dr.activity_pct, pct_classification, pct_defect, "warning",
                    "The displayed share-change percentage differs; ValuePilot uses SEC current/previous shares while Dataroma may use adjusted identity or a different denominator.",
                )
            )
        vp_impact = _portfolio_impact(vp, current_portfolio_value_usd)
        if not _close(vp_impact, dr.portfolio_impact_pct, Decimal("0.05")):
            differences.append(
                _difference(
                    "activity", "portfolio_impact_pct", quarter, ticker, vp_impact,
                    dr.portfolio_impact_pct, "reporting_policy_difference", False, "info",
                    "Portfolio-impact denominators are not standardized in 13F; ValuePilot uses filing-derived current/previous weights while Dataroma applies its own adjusted denominator.",
                )
            )
    return differences


def validate_activity_views(
    activity: Iterable[DataromaActivity],
    buys: Iterable[DataromaActivity],
    sells: Iterable[DataromaActivity],
) -> list[ReconciliationDifference]:
    activity = tuple(activity)
    buys = tuple(buys)
    sells = tuple(sells)
    # The all-activity page is capped by row count and can end halfway through
    # its oldest displayed quarter, whereas filtered pages often extend farther.
    # The latest quarter is complete on all three pages and is the only sound
    # internal-consistency window.
    latest_quarter = max((row.quarter for row in activity), default=None)
    expected_buys = {
        _activity_key(row) for row in activity
        if row.quarter == latest_quarter and row.action in {"add", "buy"}
    }
    expected_sells = {
        _activity_key(row) for row in activity
        if row.quarter == latest_quarter and row.action in {"reduce", "sell"}
    }
    actual_buys = {_activity_key(row) for row in buys if row.quarter == latest_quarter}
    actual_sells = {_activity_key(row) for row in sells if row.quarter == latest_quarter}
    differences: list[ReconciliationDifference] = []
    for field, expected, actual in (
        ("buys_filter", expected_buys, actual_buys),
        ("sells_filter", expected_sells, actual_sells),
    ):
        if expected != actual:
            differences.append(
                _difference(
                    "dataroma_internal", field, None, None, sorted(expected), sorted(actual),
                    "dataroma_page_inconsistency", False, "warning",
                    "Dataroma's filtered page does not equal its Activity page over their shared quarter window.",
                )
            )
    return differences


def compare_history(
    valuepilot: dict[str, Any],
    dataroma: Iterable[DataromaPortfolioHistory],
) -> list[ReconciliationDifference]:
    differences: list[ReconciliationDifference] = []
    vp_by_quarter = {row.get("quarter"): row for row in valuepilot.get("quarters") or []}
    for dr in dataroma:
        vp = vp_by_quarter.get(dr.quarter)
        if vp is None:
            continue
        vp_value = vp.get("reported_common_value_usd")
        tolerance = _display_money_tolerance(dr.portfolio_value_display)
        if not _close(vp_value, dr.portfolio_value_usd, tolerance):
            differences.append(
                _difference(
                    "history", "portfolio_value_usd", dr.quarter, None, vp_value,
                    dr.portfolio_value_usd, "reporting_policy_or_value_unit", None, "error",
                    f"History value differs beyond the precision implied by {dr.portfolio_value_display!r}.",
                )
            )
        vp_top_items = (vp.get("top_holdings") or [])[: len(dr.top_holdings)]
        vp_top = [
            (
                _ticker((item.get("stock") or {}).get("ticker")),
                _nested_number(item, "portfolio_weight_pct", "value"),
            )
            for item in vp_top_items
        ]
        vp_weight_reasons = {
            _ticker((item.get("stock") or {}).get("ticker")): (
                (item.get("portfolio_weight_pct") or {}).get("unavailable_reason")
            )
            for item in vp_top_items
        }
        dr_top = [( _ticker(item.ticker), item.portfolio_weight_pct) for item in dr.top_holdings]
        vp_tickers = [x[0] for x in vp_top]
        dr_tickers = [x[0] for x in dr_top]
        if set(vp_tickers) != set(dr_tickers) or _has_material_order_inversion(vp_tickers, dr_top):
            differences.append(
                _difference(
                    "history", "top_holdings_order", dr.quarter, None,
                    vp_tickers, dr_tickers,
                    "identity_or_aggregation", None, "error",
                    "Top-holding ticker order differs after normalizing share-class separators.",
                )
            )
            continue
        vp_weights = dict(vp_top)
        for ticker, dr_weight in dr_top:
            vp_weight = vp_weights.get(ticker)
            if dr_weight is not None and not _close(vp_weight, dr_weight, Decimal("0.01")):
                if vp_weight_reasons.get(ticker) == "PARTIAL_COVERAGE":
                    classification, defect, severity = (
                        "intentional_coverage_caveat",
                        False,
                        "info",
                    )
                    explanation = (
                        "ValuePilot intentionally withholds historical weights for a partial filing."
                    )
                else:
                    classification, defect, severity = (
                        "denominator_or_coverage",
                        None,
                        "error",
                    )
                    explanation = (
                        "Historical portfolio weight differs beyond displayed precision."
                    )
                differences.append(
                    _difference(
                        "history", "portfolio_weight_pct", dr.quarter, ticker,
                        vp_weight, dr_weight, classification, defect, severity,
                        explanation,
                    )
                )
    return differences


def reconcile_all_managers(
    session: Session,
    *,
    client: DataromaClient | None = None,
    manager_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Fetch and reconcile every active tracked manager, without database writes."""
    managers_q = session.query(InstitutionManager).filter(
        InstitutionManager.status == "active",
        InstitutionManager.cik.isnot(None),
    )
    if manager_ids:
        managers_q = managers_q.filter(InstitutionManager.id.in_(sorted(manager_ids)))
    managers = managers_q.order_by(InstitutionManager.id).all()
    owned_client = client is None
    client = client or DataromaClient()
    results: list[dict[str, Any]] = []
    try:
        for manager in managers:
            results.append(_reconcile_manager(session, client, manager))
    finally:
        if owned_client:
            client.close()
    counts = {
        "managers_total": len(results),
        "managers_mapped": sum(item["status"] != "unmapped" for item in results),
        "managers_unmapped": sum(item["status"] == "unmapped" for item in results),
        "managers_fetch_failed": sum(item["status"] == "fetch_failed" for item in results),
        "managers_with_differences": sum(bool(item["differences"]) for item in results),
        "differences_total": sum(len(item["differences"]) for item in results),
        "suspected_valuepilot_defects": sum(
            1 for item in results for difference in item["differences"]
            if difference["valuepilot_defect"] is True
        ),
        "unclassified_material_differences": sum(
            1 for item in results for difference in item["differences"]
            if difference["classification"] == "unclassified_material_difference"
        ),
    }
    return {
        "schema": "thirteenf_dataroma_reconciliation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authority": "SEC/EDGAR via ValuePilot active filing and current parse run",
        "corroborating_source": "Dataroma",
        "counts": counts,
        "managers": results,
    }


def _reconcile_manager(
    session: Session,
    client: DataromaClient,
    manager: InstitutionManager,
) -> dict[str, Any]:
    base = {
        "manager_id": manager.id,
        "cik": manager.cik,
        "display_name": manager.display_name or manager.canonical_name,
        "dataroma_code": manager.dataroma_code,
        "status": "compared",
        "source_urls": {},
        "differences": [],
    }
    if not manager.dataroma_code:
        base["status"] = "unmapped"
        base["differences"] = [
            asdict(_difference(
                "manager_mapping", "dataroma_code", None, None, None, None,
                "unavailable_evidence", False, "info",
                "This tracked manager is not listed in Dataroma's current manager universe.",
            ))
        ]
        return base
    code = manager.dataroma_code
    base["source_urls"] = {
        "holdings": f"{HOLDINGS_URL}?m={code}",
        "activity": f"{ACTIVITY_URL}?m={code}&typ=a",
        "buys": f"{ACTIVITY_URL}?m={code}&typ=b",
        "sells": f"{ACTIVITY_URL}?m={code}&typ=s",
        "history": f"{PORTFOLIO_HISTORY_URL}?f={code}",
    }
    try:
        portfolio = _fetch_portfolio(client, code)
        activity = parse_activity(client.get_activity(code, "a"))
        buys = parse_activity(client.get_activity(code, "b"))
        sells = parse_activity(client.get_activity(code, "s"))
        history = parse_portfolio_history(client.get_portfolio_history(code))
        # Quotes and 52-week ranges are not SEC/Dataroma filing evidence and can
        # load years of local prices for 200+ position managers. Keep this
        # audit on the filing contract only.
        vp_holdings = build_user_manager_holdings(
            session,
            manager.id,
            portfolio.quarter,
            include_market_context=False,
        )
        vp_changes = build_user_manager_holding_changes(session, manager.id, portfolio.quarter)
        vp_history = build_user_manager_history(session, manager.id)
        differences = validate_activity_views(activity, buys, sells)
        if vp_holdings.get("status") == "unavailable":
            differences.append(_difference(
                "holdings", "availability", portfolio.quarter, None,
                vp_holdings.get("reason"), "available", "valuepilot_coverage_gap", True,
                "error", "Dataroma has holdings for this quarter but ValuePilot has no active product-visible filing.",
            ))
        else:
            differences.extend(compare_holdings(vp_holdings, portfolio))
        if vp_changes.get("status") == "unavailable":
            differences.append(_difference(
                "activity", "availability", portfolio.quarter, None,
                vp_changes.get("reason"), "available", "valuepilot_coverage_gap", True,
                "error", "Dataroma has activity for this quarter but ValuePilot has no product-visible ownership changes.",
            ))
        else:
            differences.extend(
                compare_activity(
                    vp_changes,
                    activity,
                    current_portfolio_value_usd=portfolio.portfolio_value_usd,
                )
            )
        differences.extend(compare_history(vp_history, history))
        vp_quarters = {row.get("quarter") for row in vp_history.get("quarters") or []}
        for missing in sorted({row.quarter for row in history} - vp_quarters, reverse=True):
            if missing < "2023-Q1":
                classification, defect, severity = "intentional_scope_boundary", False, "info"
                explanation = (
                    "Dataroma exposes history before ValuePilot's locked default production "
                    "backfill boundary (2023-Q1); this is an intentional scope difference."
                )
            else:
                classification, defect, severity = "valuepilot_coverage_gap", True, "error"
                explanation = (
                    "Dataroma exposes this in-scope manager-quarter but ValuePilot has no "
                    "active filing history for it."
                )
            differences.append(_difference(
                "history", "quarter_coverage", missing, None, "missing", "available",
                classification, defect, severity, explanation,
            ))
        base["dataroma_latest_quarter"] = portfolio.quarter
        base["valuepilot_latest_quarter"] = vp_holdings.get("quarter")
        base["differences"] = [asdict(item) for item in differences]
    except Exception as exc:  # report per-manager failure; do not erase the other 81 results
        base["status"] = "fetch_failed"
        base["error"] = f"{type(exc).__name__}: {exc}"
        base["differences"] = [
            asdict(_difference(
                "fetch", "page_contract", None, None, None, None,
                "unavailable_evidence", False, "error", base["error"],
            ))
        ]
    return base


def _fetch_portfolio(client: DataromaClient, code: str) -> DataromaPortfolio:
    first = parse_portfolio(client.get_holdings(code), allow_partial=True)
    if len(first.holdings) == first.position_count:
        return first
    if not first.holdings:
        raise DataromaPageChanged("Dataroma paginated holdings first page is empty")
    page_size = len(first.holdings)
    page_count = (first.position_count + page_size - 1) // page_size
    if page_count > 20:
        raise DataromaPageChanged(
            f"Dataroma holdings pagination unexpectedly requires {page_count} pages"
        )
    pages = [first]
    for page in range(2, page_count + 1):
        pages.append(parse_portfolio(client.get_holdings(code, page), allow_partial=True))
    return merge_portfolio_pages(tuple(pages))


def _difference(
    scope: str,
    field: str,
    quarter: str | None,
    ticker: str | None,
    valuepilot: Any,
    dataroma: Any,
    classification: str,
    valuepilot_defect: bool | None,
    severity: str,
    explanation: str,
) -> ReconciliationDifference:
    return ReconciliationDifference(
        scope, field, quarter, ticker, _json_value(valuepilot),
        _json_value(dataroma), classification, valuepilot_defect, severity, explanation,
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _ticker(value: str | None) -> str | None:
    return value.upper().replace("/", ".").replace("-", ".") if value else None


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _close(left: Any, right: Any, tolerance: Any) -> bool:
    if left is None or right is None:
        return left is right
    return abs(_decimal(left) - _decimal(right)) <= _decimal(tolerance)


def _nested_number(item: dict[str, Any], outer: str, inner: str) -> Any:
    value = item.get(outer)
    return value.get(inner) if isinstance(value, dict) else None


def _split_factor(valuepilot_shares: Any, dataroma_shares: Any) -> int | None:
    if not valuepilot_shares or not dataroma_shares:
        return None
    vp, dr = int(valuepilot_shares), int(dataroma_shares)
    larger, smaller = max(vp, dr), min(vp, dr)
    factor, remainder = divmod(larger, smaller)
    # Exchange-listed securities can use less familiar ratios (for example
    # Booking's 25-for-1 and Vanguard funds' 6/8-for-1 splits). Exact share
    # multiplication plus the caller's unchanged-value / matching-activity
    # check is stronger evidence than a brittle allow-list of common ratios.
    if remainder == 0 and 2 <= factor <= 100:
        return factor
    return None


def _expected_activity_pct(item: dict[str, Any]) -> Decimal | None:
    status = item.get("change_status")
    if status == "new_position":
        return None
    if status == "exited_position":
        return Decimal("100")
    value = item.get("share_change_pct")
    return abs(_decimal(value) * 100) if value is not None else None


def _activity_pct_matches(item: dict[str, Any], dataroma: DataromaActivity) -> bool:
    return _close(_expected_activity_pct(item), dataroma.activity_pct, Decimal("0.02"))


def _portfolio_impact(item: dict[str, Any], portfolio_value: int | None) -> Decimal | None:
    status = item.get("change_status")
    if status == "new_position":
        value = item.get("current_portfolio_weight_pct")
        return _decimal(value) if value is not None else None
    if status == "exited_position":
        value = item.get("previous_portfolio_weight_pct")
        return _decimal(value) if value is not None else None
    shares = item.get("current_shares")
    current_value = item.get("current_value_usd")
    delta = item.get("share_delta")
    if not portfolio_value or not shares or current_value is None or delta is None:
        return None
    reported_price = _decimal(current_value) / _decimal(shares)
    return (abs(_decimal(delta)) * reported_price / _decimal(portfolio_value)) * 100


def _activity_key(row: DataromaActivity) -> tuple[Any, ...]:
    return (
        row.quarter,
        _ticker(row.ticker),
        row.action,
        row.activity_pct,
        row.share_change,
        row.portfolio_impact_pct,
    )


def _has_material_order_inversion(
    valuepilot_tickers: list[str | None],
    dataroma_rows: list[tuple[str | None, Decimal | None]],
) -> bool:
    vp_rank = {ticker: rank for rank, ticker in enumerate(valuepilot_tickers)}
    for left_index, (left_ticker, left_weight) in enumerate(dataroma_rows):
        for right_ticker, right_weight in dataroma_rows[left_index + 1:]:
            # Dataroma orders equal displayed weights arbitrarily; exact-value
            # ValuePilot ordering inside that displayed tie is equally valid.
            if left_weight is None or right_weight is None or left_weight == right_weight:
                continue
            if vp_rank.get(left_ticker, -1) > vp_rank.get(right_ticker, -1):
                return True
    return False


def _display_money_tolerance(display: str) -> Decimal:
    import re

    match = re.fullmatch(r"\$?\s*([0-9,]+)(?:\.([0-9]+))?\s*([KMBT])?", display.strip(), re.IGNORECASE)
    if not match:
        return Decimal("0")
    decimals = len(match.group(2) or "")
    scale = {None: 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}
    unit = Decimal(scale[match.group(3).upper() if match.group(3) else None])
    # Dataroma's history total is a market-price reconstruction rather than the
    # SEC table's nearest-$1,000 sum. One full displayed unit accommodates that
    # reconstruction plus its published rounding without masking a material
    # change at the shown precision.
    return unit * (Decimal(10) ** -decimals)
