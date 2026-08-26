from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from app.dataroma.parsers.activity import parse_activity
from app.dataroma.parsers.history import parse_portfolio_history
from app.dataroma.parsers.portfolio import (
    DataromaPageChanged,
    DataromaPortfolio,
    DataromaPortfolioHolding,
    merge_portfolio_pages,
    parse_portfolio,
)
from app.services.thirteenf_dataroma_reconciliation import (
    compare_activity,
    compare_holdings,
    compare_history,
    validate_activity_views,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "13f" / "dataroma"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_dataroma_portfolio_captures_summary_and_numeric_holdings():
    result = parse_portfolio(_fixture("holdings_HH.html"))

    assert result.manager_name == "Duan Yongping - H&H International Investment"
    assert result.quarter == "2026-Q1"
    assert result.portfolio_date.isoformat() == "2026-03-31"
    assert result.position_count == 2
    assert result.portfolio_value_usd == 11_729_730_000
    assert [row.ticker for row in result.holdings] == ["AAPL", "BRK.B"]
    assert result.holdings[0].portfolio_weight_pct == Decimal("62.63")
    assert result.holdings[0].activity == "reduce"
    assert result.holdings[0].activity_pct == Decimal("10.55")
    assert result.holdings[0].shares == 28_945_607
    assert result.holdings[0].reported_price == Decimal("253.79")
    assert result.holdings[0].value_usd == 7_346_106_000
    assert result.holdings[0].current_price == Decimal("333.74")
    assert result.holdings[0].change_since_report_pct == Decimal("31.50")
    assert result.holdings[0].week_52_low == Decimal("200.70")
    assert result.holdings[0].week_52_high == Decimal("334.99")


def test_portfolio_parser_fails_loudly_when_grid_or_count_changes():
    with pytest.raises(DataromaPageChanged, match="holdings grid"):
        parse_portfolio(b"<html><p id='p2'><span>Q1 2026</span></p></html>")

    broken = _fixture("holdings_HH.html").replace(b"<span>2</span>", b"<span>3</span>")
    with pytest.raises(DataromaPageChanged, match="declares 3 positions but parsed 2"):
        parse_portfolio(broken)


def test_portfolio_parser_can_merge_explicit_paginated_evidence():
    first = parse_portfolio(
        _fixture("holdings_HH.html").replace(b"<span>2</span>", b"<span>3</span>"),
        allow_partial=True,
    )
    second = DataromaPortfolio(
        manager_name=first.manager_name,
        quarter=first.quarter,
        portfolio_date=first.portfolio_date,
        position_count=3,
        portfolio_value_usd=first.portfolio_value_usd,
        holdings=(
            DataromaPortfolioHolding(
                ticker="NVDA",
                issuer_name="NVIDIA Corp.",
                portfolio_weight_pct=Decimal("0"),
                activity=None,
                activity_pct=None,
                shares=1,
                reported_price=Decimal("1"),
                value_usd=1,
                current_price=None,
                change_since_report_pct=None,
                week_52_low=None,
                week_52_high=None,
            ),
        ),
    )

    merged = merge_portfolio_pages((first, second))

    assert merged.position_count == 3
    assert [row.ticker for row in merged.holdings] == ["AAPL", "BRK.B", "NVDA"]


def test_portfolio_parser_treats_bare_percent_quote_change_as_unavailable():
    html = _fixture("holdings_HH.html").replace(b"31.50%", b"%")

    result = parse_portfolio(html)

    assert result.holdings[0].change_since_report_pct is None


def test_portfolio_parser_accepts_explicit_zero_position_filing():
    html = b"""<html><body>
    <div id='f_name'>Tom Bancroft - Makaira Partners</div>
    <p id='p2'>Period: <span>Q1 2026</span><br>
    Portfolio date: <span>31 Mar 2026</span><br>
    No. of stocks: <span>0</span><br>Portfolio value: <span>$</span></p>
    <table id='grid'><thead><tr><td>History</td></tr></thead><tbody></tbody></table>
    </body></html>"""

    result = parse_portfolio(html)

    assert result.position_count == 0
    assert result.portfolio_value_usd == 0
    assert result.holdings == ()


def test_parse_activity_handles_dataromas_unwrapped_td_markup():
    result = parse_activity(_fixture("activity_HH.html"))

    assert len(result) == 5
    assert [(row.quarter, row.ticker, row.action) for row in result] == [
        ("2026-Q1", "NVDA", "add"),
        ("2026-Q1", "TSLA", "buy"),
        ("2026-Q1", "AAPL", "reduce"),
        ("2026-Q1", "BABA", "sell"),
        ("2025-Q4", "NVDA", "add"),
    ]
    assert result[0].activity_pct == Decimal("91.29")
    assert result[0].share_change == 6_606_675
    assert result[0].portfolio_impact_pct == Decimal("5.76")
    assert result[1].activity_pct is None
    assert result[3].activity_pct == Decimal("100.00")


def test_parse_portfolio_history_preserves_display_precision_and_top_order():
    result = parse_portfolio_history(_fixture("history_HH.html"))

    assert [row.quarter for row in result] == ["2026-Q1", "2025-Q4"]
    assert result[0].portfolio_value_usd == Decimal("20000000000")
    assert result[0].portfolio_value_display == "$20 B"
    assert [(x.ticker, x.portfolio_weight_pct) for x in result[0].top_holdings] == [
        ("AAPL", Decimal("36.72")),
        ("BRK.B", Decimal("21.91")),
    ]


def test_seed_universe_has_current_dataroma_mapping_for_80_of_82_managers():
    seed = json.loads(
        (Path(__file__).parents[2] / "app" / "services" / "seed_data" / "confirmed_managers.json").read_text()
    )
    mapped = {item["cik"]: item.get("dataroma_code") for item in seed}

    assert len(seed) == 82
    assert sum(bool(code) for code in mapped.values()) == 80
    assert mapped["0001759760"] == "HH"
    assert mapped["0001166559"] == "GFT"
    assert mapped["0001314620"] == "HCM"
    assert mapped["0001649339"] == "SAM"
    assert {cik for cik, code in mapped.items() if not code} == {
        "0001350694",  # Bridgewater is not listed on current Dataroma.
        "0000783412",  # Daily Journal is not listed on current Dataroma.
    }


def test_compare_holdings_accepts_dataroma_rounding_and_ticker_separator():
    dataroma = parse_portfolio(_fixture("holdings_HH.html"))
    valuepilot = {
        "quarter": "2026-Q1",
        "summary": {
            "common_position_count": 2,
            "reported_common_value_usd": 11_729_729_444,
        },
        "common_holdings": [
            {
                "stock": {"ticker": "AAPL"},
                "issuer_name": "Apple Inc.",
                "ssh_prnamt": 28_945_607,
                # Dataroma rounds/truncates each source lot to $1,000 before
                # displaying an aggregated ticker value.
                "value_usd": 7_346_104_501,
                "constituent_row_count": 2,
                "portfolio_weight_pct": {"value": 62.63},
                "implied_report_price": 253.791,
            },
            {
                "stock": {"ticker": "BRK/B"},
                "issuer_name": "Berkshire Hathaway CL B",
                "ssh_prnamt": 9_147_796,
                "value_usd": 4_383_623_843,
                "portfolio_weight_pct": {"value": 37.37},
                "implied_report_price": 479.204,
            },
        ],
    }

    assert compare_holdings(valuepilot, dataroma) == []

    partial = json.loads(json.dumps(valuepilot))
    for holding in partial["common_holdings"]:
        holding["portfolio_weight_pct"] = {
            "value": None,
            "unavailable_reason": "PARTIAL_COVERAGE",
        }
    partial_differences = compare_holdings(partial, dataroma)
    assert {item.field for item in partial_differences} == {"portfolio_weight_pct"}
    assert all(item.classification == "intentional_coverage_caveat" for item in partial_differences)
    assert all(item.valuepilot_defect is False for item in partial_differences)

    unlinked = json.loads(json.dumps(valuepilot))
    unlinked["common_holdings"].append(
        {
            "stock": {"ticker": None},
            "cusip": "UNKNOWN01",
            "ssh_prnamt": 1,
            "value_usd": 1,
            "portfolio_weight_pct": {"value": 0},
        }
    )
    identity_gap = next(
        item
        for item in compare_holdings(unlinked, dataroma)
        if item.field == "unlinked_position_count"
    )
    assert identity_gap.classification == "identity_coverage_gap"
    assert identity_gap.valuepilot_defect is None


@pytest.mark.parametrize("split_factor", [4, 25])
def test_compare_holdings_classifies_post_report_split_without_calling_it_our_bug(split_factor):
    dataroma = DataromaPortfolio(
        manager_name="Example",
        quarter="2026-Q1",
        portfolio_date=parse_portfolio(_fixture("holdings_HH.html")).portfolio_date,
        position_count=1,
        portfolio_value_usd=3_904_000,
        holdings=(
            DataromaPortfolioHolding(
                ticker="CRWD",
                issuer_name="CrowdStrike Holdings Inc.",
                portfolio_weight_pct=Decimal("100.00"),
                activity="buy",
                activity_pct=None,
                shares=10_000 * split_factor,
                reported_price=Decimal("390.41") / split_factor,
                value_usd=3_904_000,
                current_price=None,
                change_since_report_pct=None,
                week_52_low=None,
                week_52_high=None,
            ),
        ),
    )
    valuepilot = {
        "quarter": "2026-Q1",
        "summary": {"common_position_count": 1, "reported_common_value_usd": 3_904_100},
        "common_holdings": [
            {
                "stock": {"ticker": "CRWD"},
                "issuer_name": "CrowdStrike Holdings Inc.",
                "ssh_prnamt": 10_000,
                "value_usd": 3_904_100,
                "portfolio_weight_pct": {"value": 100.0},
                "implied_report_price": 390.41,
            }
        ],
    }

    differences = compare_holdings(valuepilot, dataroma)

    assert {(x.field, x.classification) for x in differences} == {
        ("shares", "identity_or_corporate_action"),
        ("reported_price", "identity_or_corporate_action"),
    }
    assert all(x.valuepilot_defect is False for x in differences)
    assert f"{split_factor}-for-1" in differences[0].explanation


def test_compare_activity_and_filtered_views_match_valuepilot_semantics():
    all_rows = parse_activity(_fixture("activity_HH.html"))
    buys = tuple(row for row in all_rows if row.action in {"add", "buy"})
    sells = tuple(row for row in all_rows if row.action in {"reduce", "sell"})
    valuepilot = {
        "quarter": "2026-Q1",
        "items": [
            {"stock": {"ticker": "NVDA"}, "position_type": "common", "change_status": "increased", "share_delta": 6_606_675, "share_change_pct": 0.9129, "current_value_usd": 2_414_354_000, "current_shares": 13_843_775, "previous_portfolio_weight_pct": 7.72, "current_portfolio_weight_pct": 12.07},
            {"stock": {"ticker": "TSLA"}, "position_type": "common", "change_status": "new_position", "share_delta": 3_408_900, "share_change_pct": None, "current_value_usd": 1_267_259_000, "current_shares": 3_408_900, "previous_portfolio_weight_pct": None, "current_portfolio_weight_pct": 6.34},
            {"stock": {"ticker": "AAPL"}, "position_type": "common", "change_status": "reduced", "share_delta": -3_412_900, "share_change_pct": -0.1055, "current_value_usd": 7_346_106_000, "current_shares": 28_945_607, "previous_portfolio_weight_pct": 50.30, "current_portfolio_weight_pct": 62.63},
            {"stock": {"ticker": "BABA"}, "position_type": "common", "change_status": "exited_position", "share_delta": -2_560_500, "share_change_pct": None, "current_value_usd": None, "current_shares": None, "previous_portfolio_weight_pct": 2.15, "current_portfolio_weight_pct": None},
        ],
    }

    assert validate_activity_views(all_rows, buys, sells) == []
    assert compare_activity(valuepilot, all_rows, current_portfolio_value_usd=20_003_997_000) == []

    nvda = next(row for row in all_rows if row.ticker == "NVDA")
    policy_difference = replace(
        nvda,
        portfolio_impact_pct=nvda.portfolio_impact_pct + Decimal("1.00"),
    )
    differences = compare_activity(
        {"quarter": "2026-Q1", "items": [valuepilot["items"][0]]},
        (policy_difference,),
        current_portfolio_value_usd=20_003_997_000,
    )
    assert [
        (item.field, item.classification, item.valuepilot_defect)
        for item in differences
    ] == [("portfolio_impact_pct", "reporting_policy_difference", False)]

    identity_difference = replace(nvda, action="buy")
    differences = compare_activity(
        {"quarter": "2026-Q1", "items": [valuepilot["items"][0]]},
        (identity_difference,),
        current_portfolio_value_usd=20_003_997_000,
    )
    assert [
        (item.field, item.classification, item.valuepilot_defect)
        for item in differences
    ] == [("action", "identity_or_source_policy", None)]

    capped_page = tuple(replace(nvda, ticker=f"CAP{i:03d}") for i in range(100))
    only_valuepilot = json.loads(json.dumps(valuepilot["items"][0]))
    only_valuepilot["stock"]["ticker"] = "ONLYVP"
    capped_difference = next(
        item
        for item in compare_activity(
            {"quarter": "2026-Q1", "items": [only_valuepilot]},
            capped_page,
            current_portfolio_value_usd=20_003_997_000,
        )
        if item.ticker == "ONLYVP"
    )
    assert capped_difference.classification == "dataroma_page_limit"
    assert capped_difference.valuepilot_defect is False


def test_activity_filter_validation_uses_latest_complete_quarter_only():
    all_rows = parse_activity(_fixture("activity_HH.html"))
    buys = tuple(row for row in all_rows if row.action in {"add", "buy"})
    sells = tuple(row for row in all_rows if row.action in {"reduce", "sell"})
    # Dataroma's all-activity page is capped by row count and can stop halfway
    # through its oldest displayed quarter, while the filtered page reaches
    # farther. That is not an upstream inconsistency in the current quarter.
    older_extra = sells[-1].__class__(
        quarter="2025-Q4",
        ticker="OLD",
        issuer_name="Older Position",
        action="sell",
        activity_pct=Decimal("100"),
        share_change=1,
        portfolio_impact_pct=Decimal("0.01"),
    )

    assert validate_activity_views(all_rows, buys, (*sells, older_extra)) == []


def test_compare_history_respects_dataromas_display_rounding_and_top_order():
    dataroma = parse_portfolio_history(_fixture("history_HH.html"))
    valuepilot = {
        "quarters": [
            {
                "quarter": "2026-Q1",
                "reported_common_value_usd": 20_003_996_234,
                "top_holdings": [
                    {"stock": {"ticker": "AAPL"}, "portfolio_weight_pct": {"value": 36.723}},
                    {"stock": {"ticker": "BRK/B"}, "portfolio_weight_pct": {"value": 21.914}},
                ],
            },
            {
                "quarter": "2025-Q4",
                "reported_common_value_usd": 17_488_569_921,
                "top_holdings": [
                    {"stock": {"ticker": "AAPL"}, "portfolio_weight_pct": {"value": 50.301}},
                    {"stock": {"ticker": "BRK/B"}, "portfolio_weight_pct": {"value": 20.626}},
                ],
            },
        ]
    }

    assert compare_history(valuepilot, dataroma) == []

    partial = json.loads(json.dumps(valuepilot))
    for quarter in partial["quarters"]:
        for holding in quarter["top_holdings"]:
            holding["portfolio_weight_pct"] = {
                "value": None,
                "unavailable_reason": "PARTIAL_COVERAGE",
            }
    differences = compare_history(partial, dataroma)
    assert {item.field for item in differences} == {"portfolio_weight_pct"}
    assert all(item.classification == "intentional_coverage_caveat" for item in differences)
    assert all(item.valuepilot_defect is False for item in differences)


def test_compare_history_allows_reordering_inside_same_displayed_weight_tie():
    dataroma = parse_portfolio_history(_fixture("history_HH.html"))
    tied = dataroma[0].__class__(
        quarter=dataroma[0].quarter,
        portfolio_value_usd=dataroma[0].portfolio_value_usd,
        portfolio_value_display=dataroma[0].portfolio_value_display,
        top_holdings=(
            dataroma[0].top_holdings[0].__class__("TEM", Decimal("0.00")),
            dataroma[0].top_holdings[0].__class__("INOD", Decimal("0.00")),
        ),
    )
    valuepilot = {
        "quarters": [{
            "quarter": "2026-Q1",
            "reported_common_value_usd": 20_003_996_234,
            "top_holdings": [
                {"stock": {"ticker": "INOD"}, "portfolio_weight_pct": {"value": 0.004}},
                {"stock": {"ticker": "TEM"}, "portfolio_weight_pct": {"value": 0.003}},
            ],
        }]
    }

    assert compare_history(valuepilot, (tied,)) == []
