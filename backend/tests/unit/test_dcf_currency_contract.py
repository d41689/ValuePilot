from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.facts import MetricFact
from app.services.dcf_inputs import evaluate_dcf_input_selection


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


def _entry(inputs):
    oeps = _fact("owners_earnings_per_share", currency="USD", value=1)
    return evaluate_dcf_input_selection(
        stock_id=1,
        dcf_facts=list(inputs.values()),
        oeps_facts=[oeps],
        selection=2025,
        evaluated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("currency", ["DKK", "EUR", "TWD", "USD"])
def test_dcf_input_entry_exposes_one_validated_iso_currency(currency):
    entry = _entry(_inputs(eps=currency, depreciation=currency, capex=currency))

    assert entry["valuation_currency"] == currency
    assert entry["currency_state"]["status"] == "available"
    assert entry["currency_state"]["reason_code"] is None
    assert {
        item["metric_key"] for item in entry["currency_state"]["provenance"]
    } == {"per_share.eps", "is.depreciation", "per_share.capital_spending"}
    assert entry["canonical_model_inputs"] == {
        "net_profit_per_share": "10.000",
        "depreciation_per_share": "10.000",
        "capital_spending_per_share": "2.000",
        "based_on_per_share": "18.000",
    }


@pytest.mark.parametrize(
    ("inputs", "reason"),
    [
        (_inputs(eps="DKK", depreciation="EUR", capex="TWD"), "dcf_input_currency_mismatch"),
        (_inputs(eps=None), "dcf_input_currency_missing"),
        (_inputs(eps="ZZZ"), "dcf_input_currency_invalid"),
        (_inputs(eps="XAU"), "dcf_input_currency_invalid"),
        (_inputs(eps=None), "dcf_input_currency_missing"),
        (_inputs(shares=False), "dcf_input_missing"),
    ],
)
def test_dcf_input_entry_fails_closed_for_unresolved_currency(inputs, reason):
    if reason == "dcf_input_currency_missing":
        inputs["per_share.eps"].unit = None
    if reason == "dcf_input_currency_invalid" and inputs["per_share.eps"].currency == "ZZZ":
        inputs["per_share.eps"].unit = "USD"

    entry = _entry(inputs)

    assert entry["valuation_currency"] is None
    assert entry["currency_state"]["status"] == "unavailable"
    assert entry["currency_state"]["reason_code"] == reason


def test_dcf_input_entry_rejects_non_monetary_unit_for_monetary_input():
    inputs = _inputs()
    inputs["per_share.eps"].currency = None
    inputs["per_share.eps"].unit = "ratio"

    entry = _entry(inputs)

    assert entry["currency_state"]["reason_code"] == "dcf_input_currency_non_monetary"


def test_dcf_input_entry_does_not_promote_legacy_unit_to_currency():
    inputs = _inputs()
    inputs["per_share.eps"].currency = None
    inputs["per_share.eps"].unit = "USD"

    entry = _entry(inputs)

    assert entry["currency_state"]["status"] == "unavailable"
    assert entry["currency_state"]["reason_code"] == "dcf_input_currency_missing"


@pytest.mark.parametrize("shares", [0, -1, Decimal("NaN")])
def test_dcf_input_entry_rejects_nonpositive_or_nonfinite_shares(shares):
    inputs = _inputs()
    inputs["equity.shares_outstanding"].value_numeric = shares

    entry = _entry(inputs)

    assert entry["currency_state"]["status"] == "unavailable"
    assert entry["currency_state"]["reason_code"] == "dcf_shares_value_invalid"
    assert entry["depreciation_per_share"]["value"] is None


def test_dcf_input_entry_rejects_currency_on_shares_and_ratio_unit_on_money():
    shares_currency = _inputs()
    shares_currency["equity.shares_outstanding"].currency = "USD"
    ratio_money = _inputs()
    ratio_money["per_share.eps"].unit = "ratio"

    assert _entry(shares_currency)["currency_state"]["reason_code"] == "dcf_shares_semantics_invalid"
    assert _entry(ratio_money)["currency_state"]["reason_code"] == "dcf_input_currency_non_monetary"


def test_dcf_input_entry_keeps_finite_zero_and_negative_money_without_defaulting():
    inputs = _inputs()
    inputs["per_share.eps"].value_numeric = -2
    inputs["per_share.capital_spending"].value_numeric = 0

    entry = _entry(inputs)

    assert entry["currency_state"]["status"] == "available"
    assert entry["net_profit_per_share"]["value"] == -2
    assert entry["capital_spending_per_share"]["value"] == 0


def test_dcf_input_entry_never_silently_defaults_missing_money_to_zero():
    inputs = _inputs()
    inputs["per_share.eps"].value_numeric = None

    entry = _entry(inputs)

    assert entry["currency_state"]["reason_code"] == "dcf_input_missing"
    assert entry["net_profit_per_share"]["value"] is None


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_dcf_input_entry_rejects_nonfinite_monetary_values(value):
    inputs = _inputs()
    inputs["per_share.eps"].value_numeric = value

    entry = _entry(inputs)

    assert entry["currency_state"]["reason_code"] == "dcf_input_value_invalid"
    assert entry["net_profit_per_share"]["value"] is None


def test_dcf_input_entry_never_selects_facts_from_another_stock():
    inputs = _inputs()
    for fact in inputs.values():
        fact.stock_id = 2

    entry = _entry(inputs)

    assert entry["currency_state"]["status"] == "unavailable"
    assert entry["currency_state"]["reason_code"] == "dcf_input_missing"
    assert entry["input_manifest"]["facts"] == [
        entry["input_manifest"]["facts"][0]
    ]
    assert entry["input_manifest"]["facts"][0]["role"] == "selection_input"
