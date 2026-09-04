from datetime import date

import pytest

from app.api.v1.endpoints.stocks import _build_dcf_inputs_entry
from app.models.facts import MetricFact


def _fact(metric_key: str, *, currency: str | None, unit: str | None = None, value=10) -> MetricFact:
    return MetricFact(
        user_id=1,
        stock_id=1,
        metric_key=metric_key,
        value_numeric=value,
        unit=unit if unit is not None else currency,
        currency=currency,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="manual",
        is_current=True,
    )


def _inputs(*, eps="USD", depreciation="USD", capex="USD", shares=True):
    facts = {
        "per_share.eps": _fact("per_share.eps", currency=eps),
        "is.depreciation": _fact("is.depreciation", currency=depreciation, value=100),
        "per_share.capital_spending": _fact(
            "per_share.capital_spending", currency=capex, value=2
        ),
    }
    if shares:
        facts["equity.shares_outstanding"] = _fact(
            "equity.shares_outstanding", currency=None, unit="shares", value=10
        )
    return facts


@pytest.mark.parametrize("currency", ["DKK", "EUR", "TWD", "USD"])
def test_dcf_input_entry_exposes_one_validated_iso_currency(currency):
    entry = _build_dcf_inputs_entry(
        _inputs(eps=currency, depreciation=currency, capex=currency),
        active_report=None,
        report_dates_by_doc={},
    )

    assert entry["valuation_currency"] == currency
    assert entry["currency_state"]["status"] == "available"
    assert entry["currency_state"]["reason_code"] is None
    assert {
        item["metric_key"] for item in entry["currency_state"]["provenance"]
    } == {"per_share.eps", "is.depreciation", "per_share.capital_spending"}


@pytest.mark.parametrize(
    ("inputs", "reason"),
    [
        (_inputs(eps="DKK", depreciation="EUR", capex="TWD"), "dcf_input_currency_mismatch"),
        (_inputs(eps=None), "dcf_input_currency_missing"),
        (_inputs(eps="ZZZ"), "dcf_input_currency_invalid"),
        (_inputs(eps=None), "dcf_input_currency_missing"),
        (_inputs(shares=False), "dcf_input_missing"),
    ],
)
def test_dcf_input_entry_fails_closed_for_unresolved_currency(inputs, reason):
    if reason == "dcf_input_currency_missing":
        inputs["per_share.eps"].unit = None
    if reason == "dcf_input_currency_invalid" and inputs["per_share.eps"].currency == "ZZZ":
        inputs["per_share.eps"].unit = "USD"

    entry = _build_dcf_inputs_entry(
        inputs,
        active_report=None,
        report_dates_by_doc={},
    )

    assert entry["valuation_currency"] is None
    assert entry["currency_state"]["status"] == "unavailable"
    assert entry["currency_state"]["reason_code"] == reason


def test_dcf_input_entry_rejects_non_monetary_unit_for_monetary_input():
    inputs = _inputs()
    inputs["per_share.eps"].currency = None
    inputs["per_share.eps"].unit = "ratio"

    entry = _build_dcf_inputs_entry(
        inputs,
        active_report=None,
        report_dates_by_doc={},
    )

    assert entry["currency_state"]["reason_code"] == "dcf_input_currency_non_monetary"
