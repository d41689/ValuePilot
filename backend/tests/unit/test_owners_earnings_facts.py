from datetime import date

from app.services.owners_earnings import build_owners_earnings_facts


def _fact(metric_key: str, value: float | None, period_end_date: date) -> dict:
    return {
        "metric_key": metric_key,
        "value_numeric": value,
        "value_text": None,
        "value_json": None,
        "unit": None,
        "period_type": "FY",
        "period_end_date": period_end_date,
    }


def test_build_owners_earnings_facts_median_last_5_years():
    dates = [
        date(2019, 12, 31),
        date(2020, 12, 31),
        date(2021, 12, 31),
        date(2022, 12, 31),
        date(2023, 12, 31),
        date(2024, 12, 31),
    ]
    facts = [
        _fact("per_share.eps", 1.0, dates[0]),
        _fact("per_share.eps", 2.0, dates[1]),
        _fact("per_share.eps", 3.0, dates[2]),
        _fact("per_share.eps", None, dates[3]),
        _fact("per_share.eps", 4.0, dates[4]),
        _fact("per_share.eps", 5.0, dates[5]),
        _fact("per_share.capital_spending", 1.0, dates[1]),
        _fact("per_share.capital_spending", 1.0, dates[2]),
        _fact("per_share.capital_spending", 1.0, dates[3]),
        _fact("per_share.capital_spending", None, dates[4]),
        _fact("per_share.capital_spending", 2.0, dates[5]),
        _fact("is.depreciation", 5.0, dates[1]),
        _fact("is.depreciation", None, dates[2]),
        _fact("is.depreciation", 5.0, dates[3]),
        _fact("is.depreciation", 0.0, dates[4]),
        _fact("is.depreciation", 10.0, dates[5]),
        _fact("equity.shares_outstanding", 10.0, dates[1]),
        _fact("equity.shares_outstanding", 10.0, dates[2]),
        _fact("equity.shares_outstanding", 10.0, dates[3]),
        _fact("equity.shares_outstanding", None, dates[4]),
        _fact("equity.shares_outstanding", 20.0, dates[5]),
    ]

    derived = build_owners_earnings_facts(facts, report_date=date(2026, 1, 9))
    derived_by_key = {
        (f["metric_key"], f["period_type"], f["period_end_date"]): f for f in derived
    }

    # OEPS values for FY 2020-2024 (last 5 usable FY)
    assert derived_by_key[("owners_earnings_per_share", "FY", dates[1])]["value_numeric"] == 1.5
    assert derived_by_key[("owners_earnings_per_share", "FY", dates[2])]["value_numeric"] == 2.0
    assert derived_by_key[("owners_earnings_per_share", "FY", dates[3])]["value_numeric"] == -0.5
    assert derived_by_key[("owners_earnings_per_share", "FY", dates[4])]["value_numeric"] == 4.0
    assert derived_by_key[("owners_earnings_per_share", "FY", dates[5])]["value_numeric"] == 3.5

    normalized = derived_by_key[
        ("owners_earnings_per_share_normalized", "AS_OF", date(2026, 1, 9))
    ]["value_numeric"]
    assert normalized == 2.0
