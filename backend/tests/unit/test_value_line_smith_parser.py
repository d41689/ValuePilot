import pytest

from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.normalization.scaler import Scaler


SMITH_TEXT = """
SMITH (A.O.) RECENT 68.11 P/E 17.4(Trailing:17.9)RELATIVE 0.93 DIV’D 2.0% VALUE
NYSE-AOS PRICE RATIO Median:22.0 P/ERATIO YLD LINE
TIMELINESS 3 Lowered1/2/26
TECHNICAL 3 Raised1/2/26
BETA 1.00 (1.00=Market)

18-MonthTargetPriceRange
$55-$97 $76(10%)

2028-30PROJECTIONS
High 130 (+90%) 19%
Low 90 (+30%) 9%

CAPITALSTRUCTUREasof9/30/25
TotalDebt$185.8mill. Duein5Yrs$90.2mill.
LTDebt$166.8mill. LTInterest$10.0mill.
(8%ofCap’l)
Leases,UncapitalizedAnnualrentals$12.4mill.
PensionAssets-12/24$18.6mill.
Oblig.$27.7mill.
CommonStock139,237,818shares.
asof10/24/25
MARKETCAP:$9.5billion(MidCap)

CURRENTPOSITION 2023 2024 9/30/25
($MILL.)
CashAssets 363.4 276.1 172.8
Receivables 596.0 541.4 589.0
Inventory (LIFO) 497.4 532.1 507.3
Other 43.5 43.3 47.0
CurrentAssets 1500.3 1392.9 1316.1
AcctsPayable 600.4 588.7 521.4
DebtDue 10.0 10.0 19.0
Other 334.9 298.5 312.1
CurrentLiab. 945.3 897.2 852.5

ANNUALRATES Past Past Est’d’22-’24
ofchange(persh) 10Yrs. 5Yrs. to’28-’30
Sales 8.0% 7.0% 6.5%
‘‘CashFlow’’ 12.0% 8.0% 7.5%
Earnings 13.5% 9.0% 7.5%
Dividends 18.0% 10.5% 6.0%
BookValue 5.5% 4.5% 6.5%

QUARTERLYSALES($mill.) Full
endar Mar.31 Jun.30 Sep.30 Dec.31 Year
2022 977.7 965.9 874.2 936.1 3753.9
2023 966.4 960.8 937.5 988.1 3852.8
2024 978.8 1024.3 902.6 912.4 3818.1
2025 963.9 1011.3 942.5 912.3 3830
2026 985 1050 995 1000 4030

EARNINGSPERSHAREA Full
endar Mar.31 Jun.30 Sep.30 Dec.31 Year
2022 .77 .82 .69 .86 3.14
2023 .94 1.01 .90 .97 3.81
2024 1.00 1.06 .82 .85 3.73
2025 .95 1.07 .94 .79 3.75
2026 1.01 1.12 1.02 1.05 4.20

QUARTERLYDIVIDENDSPAIDB■ Full
endar Mar.31 Jun.30 Sep.30 Dec.31 Year
2021 .26 .26 .26 .28 1.06
2022 .28 .28 .28 .30 1.14
2023 .30 .30 .30 .32 1.22
2024 .32 .32 .32 .34 1.30
2025 .34 .34 .34 .36

BUSINESS:A.O.SmithCorp.isaleadingmanufacturerofresidential and commercial water heaters.
Telephone:414-359-4130.Internet:www.aosmith.com.

NilsC.VanLiew January2,2026
""".strip()


SMITH_WORDS = {
    1: [
        {"text": "InstitutionalDecisions", "x0": 46.9, "top": 168.7},
        {"text": "1Q", "x0": 74.6, "top": 177.3},
        {"text": "20", "x0": 79.9, "top": 177.3},
        {"text": "2", "x0": 84.4, "top": 177.3},
        {"text": "5", "x0": 86.6, "top": 177.3},
        {"text": "3", "x0": 78.8, "top": 184.3},
        {"text": "4", "x0": 82.2, "top": 184.3},
        {"text": "0", "x0": 85.5, "top": 184.3},
        {"text": "3", "x0": 78.9, "top": 190.3},
        {"text": "2", "x0": 82.2, "top": 190.3},
        {"text": "4", "x0": 85.5, "top": 190.3},
        {"text": "2Q", "x0": 98.6, "top": 177.3},
        {"text": "20", "x0": 103.9, "top": 177.3},
        {"text": "2", "x0": 108.3, "top": 177.3},
        {"text": "5", "x0": 110.6, "top": 177.3},
        {"text": "2", "x0": 102.8, "top": 184.3},
        {"text": "9", "x0": 106.1, "top": 184.3},
        {"text": "9", "x0": 109.5, "top": 184.3},
        {"text": "3", "x0": 102.9, "top": 190.3},
        {"text": "6", "x0": 106.2, "top": 190.3},
        {"text": "1", "x0": 109.5, "top": 190.3},
        {"text": "3Q", "x0": 122.5, "top": 177.3},
        {"text": "20", "x0": 127.9, "top": 177.3},
        {"text": "2", "x0": 132.3, "top": 177.3},
        {"text": "5", "x0": 134.5, "top": 177.3},
        {"text": "2", "x0": 126.8, "top": 184.3},
        {"text": "9", "x0": 130.1, "top": 184.3},
        {"text": "9", "x0": 133.5, "top": 184.3},
        {"text": "3", "x0": 126.9, "top": 190.3},
        {"text": "0", "x0": 130.2, "top": 190.3},
        {"text": "3", "x0": 133.5, "top": 190.3},
        {"text": "Hld’s(000)111520", "x0": 45.0, "top": 205.0},
        {"text": "109371", "x0": 92.0, "top": 205.0},
        {"text": "107276", "x0": 135.0, "top": 205.0},
    ]
}


def _index(results):
    return {r.field_key: r for r in results}


def test_scaler_handles_attached_scale_tokens():
    val, unit = Scaler.normalize("$185.8mill.", "number")
    assert val == 185_800_000.0
    assert unit == "USD"

    val, unit = Scaler.normalize("$9.5billion(MidCap)", "number")
    assert val == 9_500_000_000.0
    assert unit == "USD"


def test_value_line_v1_parser_smith_extracts_key_sections():
    parser = ValueLineV1Parser(SMITH_TEXT, page_words=SMITH_WORDS)
    results = parser.parse()
    by_key = _index(results)

    assert by_key["recent_price"].raw_value_text == "68.11"
    assert by_key["pe_ratio"].raw_value_text == "17.4"
    assert by_key["pe_ratio_trailing"].raw_value_text == "17.9"
    assert by_key["pe_ratio_median"].raw_value_text == "22.0"
    assert by_key["relative_pe_ratio"].raw_value_text == "0.93"
    assert by_key["dividend_yield"].raw_value_text == "2.0%"
    assert by_key["beta"].raw_value_text == "1.00"

    assert by_key["target_18m_low"].raw_value_text == "55"
    assert by_key["target_18m_high"].raw_value_text == "97"
    assert by_key["target_18m_mid"].raw_value_text == "76"
    assert by_key["target_18m_upside_pct"].raw_value_text == "10%"

    assert by_key["long_term_projection_year_range"].raw_value_text == "2028-2030"
    assert by_key["long_term_projection_high_price"].raw_value_text == "130"
    assert by_key["long_term_projection_high_price_gain_pct"].raw_value_text == "90%"
    assert by_key["long_term_projection_high_total_return_pct"].raw_value_text == "19%"
    assert by_key["long_term_projection_low_price"].raw_value_text == "90"
    assert by_key["long_term_projection_low_price_gain_pct"].raw_value_text == "30%"
    assert by_key["long_term_projection_low_total_return_pct"].raw_value_text == "9%"

    assert by_key["total_debt"].raw_value_text == "$185.8 mill"
    assert by_key["debt_due_in_5_years"].raw_value_text == "$90.2 mill"
    assert by_key["lt_debt"].raw_value_text == "$166.8 mill"
    assert by_key["lt_interest"].raw_value_text == "$10.0 mill"
    assert by_key["debt_percent_of_capital"].raw_value_text == "8%"
    assert by_key["leases_uncapitalized_annual_rentals"].raw_value_text == "$12.4 mill"
    assert by_key["pension_assets"].raw_value_text == "$18.6 mill"
    assert by_key["pension_obligations"].raw_value_text == "$27.7 mill"
    assert by_key["common_stock_shares_outstanding"].raw_value_text == "139237818"
    assert by_key["market_cap"].raw_value_text == "$9.5 billion"

    assert by_key["current_position_usd_millions"].parsed_value_json["years"] == [
        "2023",
        "2024",
        "2025-09-30",
    ]
    assert by_key["annual_rates_of_change"].parsed_value_json["sales"]["past_10y"] == pytest.approx(0.08)

    assert by_key["quarterly_sales_usd_millions"].parsed_value_json[0]["calendar_year"] == 2022
    assert by_key["earnings_per_share"].parsed_value_json[-1]["full_year"] == pytest.approx(4.2)
    assert by_key["quarterly_dividends_paid_per_share"].parsed_value_json[0]["calendar_year"] == 2021

    assert by_key["report_date"].parsed_value_json["iso_date"] == "2026-01-02"
    assert by_key["analyst_name"].parsed_value_json["value"] == "Nils C. Van Liew"

    inst = by_key["institutional_decisions"].parsed_value_json["quarterly"]
    assert inst[0] == {"period": "1Q2025", "to_buy": 340, "to_sell": 324, "holds_000": 111520}
    assert inst[1]["period"] == "2Q2025"
    assert inst[2]["holds_000"] == 107276

