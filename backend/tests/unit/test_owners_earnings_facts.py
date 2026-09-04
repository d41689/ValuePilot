from datetime import date

from app.services.owners_earnings import (
    OEPS_CALCULATION_VERSION,
    OEPS_NORMALIZATION_VERSION,
    build_normalized_owners_earnings_fact,
    build_owners_earnings_facts,
)


def _fact(
    fact_id: int,
    metric_key: str,
    value: float | None,
    period_end_date: date,
    *,
    fact_nature: str = "actual",
) -> dict:
    return {
        "id": fact_id,
        "metric_key": metric_key,
        "value_numeric": value,
        "value_text": None,
        "value_json": {"fact_nature": fact_nature},
        "unit": "shares" if metric_key == "equity.shares_outstanding" else "USD",
        "currency": None if metric_key == "equity.shares_outstanding" else "USD",
        "period_type": "FY",
        "period_end_date": period_end_date,
        "source_type": "parsed",
        "is_current": True,
    }


def test_build_owners_earnings_facts_requires_complete_persisted_inputs():
    complete = date(2024, 12, 31)
    missing_input = date(2023, 12, 31)
    facts = [
        _fact(1, "per_share.eps", 5.0, complete),
        _fact(2, "per_share.capital_spending", 2.0, complete),
        _fact(3, "is.depreciation", 10.0, complete),
        _fact(4, "equity.shares_outstanding", 20.0, complete),
        _fact(5, "per_share.eps", 4.0, missing_input),
        _fact(6, "per_share.capital_spending", 1.0, missing_input),
        _fact(7, "is.depreciation", 5.0, missing_input),
    ]

    derived = build_owners_earnings_facts(facts)

    assert len(derived) == 1
    assert derived[0]["metric_key"] == "owners_earnings_per_share"
    assert derived[0]["period_end_date"] == complete
    assert derived[0]["value_numeric"] == 3.5
    assert derived[0]["currency"] == "USD"
    assert derived[0]["value_json"]["calculation_version"] == OEPS_CALCULATION_VERSION
    assert derived[0]["value_json"]["inputs"] == [
        {"fact_id": 1, "metric_key": "per_share.eps"},
        {"fact_id": 2, "metric_key": "per_share.capital_spending"},
        {"fact_id": 3, "metric_key": "is.depreciation"},
        {"fact_id": 4, "metric_key": "equity.shares_outstanding"},
    ]


def test_build_owners_earnings_facts_rejects_unpersisted_ambiguous_or_invalid_inputs():
    period_end = date(2025, 12, 31)
    unpersisted = [
        _fact(1, "per_share.eps", 3.0, period_end),
        _fact(2, "per_share.capital_spending", 1.0, period_end),
        _fact(3, "is.depreciation", 5.0, period_end),
        _fact(0, "equity.shares_outstanding", 10.0, period_end),
    ]
    ambiguous = [
        *unpersisted[:-1],
        _fact(4, "equity.shares_outstanding", 10.0, period_end),
        _fact(5, "per_share.eps", 3.0, period_end),
    ]
    invalid_shares = [
        *unpersisted[:-1],
        _fact(4, "equity.shares_outstanding", 0.0, period_end),
    ]

    assert build_owners_earnings_facts(unpersisted) == []
    assert build_owners_earnings_facts(ambiguous) == []
    assert build_owners_earnings_facts(invalid_shares) == []


def test_build_owners_earnings_facts_marks_estimate_from_exact_inputs():
    period_end = date(2025, 12, 31)
    facts = [
        _fact(1, "per_share.eps", 3.0, period_end, fact_nature="estimate"),
        _fact(2, "per_share.capital_spending", 1.0, period_end),
        _fact(3, "is.depreciation", 5.0, period_end),
        _fact(4, "equity.shares_outstanding", 10.0, period_end),
    ]

    derived = build_owners_earnings_facts(facts)

    assert derived[0]["value_numeric"] == 2.5
    assert derived[0]["value_json"]["input_fact_nature"] == "estimate"


def test_normalized_owner_earnings_references_exact_persisted_oeps_facts():
    oeps_facts = [
        {
            "id": 100 + index,
            "metric_key": "owners_earnings_per_share",
            "value_numeric": value,
            "value_json": {"calculation_version": OEPS_CALCULATION_VERSION},
            "unit": "USD",
            "currency": "USD",
            "period_type": "FY",
            "period_end_date": date(year, 12, 31),
            "source_type": "calculated",
            "is_current": True,
        }
        for index, (year, value) in enumerate(
            [(2019, 1.0), (2020, 2.0), (2021, 3.0), (2022, 4.0), (2023, 5.0), (2024, 6.0)]
        )
    ]

    normalized = build_normalized_owners_earnings_fact(
        oeps_facts,
        report_date=date(2026, 1, 9),
    )

    assert normalized is not None
    assert normalized["value_numeric"] == 4.0
    assert normalized["value_json"]["calculation_version"] == OEPS_NORMALIZATION_VERSION
    assert normalized["value_json"]["inputs"] == [
        {"fact_id": fact_id, "metric_key": "owners_earnings_per_share"}
        for fact_id in (101, 102, 103, 104, 105)
    ]


def test_normalized_owner_earnings_fails_closed_without_persisted_current_inputs():
    invalid = {
        "id": None,
        "metric_key": "owners_earnings_per_share",
        "value_numeric": 2.0,
        "value_json": {"calculation_version": OEPS_CALCULATION_VERSION},
        "unit": "USD",
        "currency": "USD",
        "period_type": "FY",
        "period_end_date": date(2024, 12, 31),
        "source_type": "calculated",
        "is_current": True,
    }

    assert (
        build_normalized_owners_earnings_fact(
            [invalid], report_date=date(2026, 1, 9)
        )
        is None
    )
