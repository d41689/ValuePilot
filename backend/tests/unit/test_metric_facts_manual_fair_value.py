import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.api.v1.endpoints import stocks as stocks_endpoint
from app.models.users import User
from app.models.stocks import PoolMembership, Stock, StockPool
from app.models.facts import MetricFact
from app.models.research import ResearchCase, ResearchCaseRevision
from app.core.security import hash_password
from app.services.dcf_inputs import (
    DcfEvaluationClock,
    calculate_dcf_model,
    dcf_manifest_token,
)


FAIR_VALUE_KEY = "val.fair_value"
ET = ZoneInfo("America/New_York")


def _make_user(db_session, email: str = "fairvalue@example.com") -> User:
    user = User(email=email, hashed_password=hash_password("TestPass123!"))
    db_session.add(user)
    db_session.commit()
    return user


def _make_stock(db_session, ticker: str) -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Inc")
    db_session.add(stock)
    db_session.commit()
    return stock


def _add_dcf_inputs(db_session, *, user, stock, currencies=("USD", "USD", "USD")):
    period_end = date(2025, 12, 31)
    facts = [
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="owners_earnings_per_share",
            value_numeric=10,
            value_json={"user_authored_formula": True},
            unit=currencies[0],
            currency=currencies[0],
            period_type="FY",
            period_end_date=period_end,
            source_type="manual",
            is_current=True,
        ),
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="per_share.eps",
            value_numeric=10,
            unit=currencies[0],
            currency=currencies[0],
            period_type="FY",
            period_end_date=period_end,
            source_type="manual",
            is_current=True,
        ),
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="is.depreciation",
            value_numeric=100,
            unit=currencies[1],
            currency=currencies[1],
            period_type="FY",
            period_end_date=period_end,
            source_type="manual",
            is_current=True,
        ),
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="equity.shares_outstanding",
            value_numeric=10,
            unit="shares",
            period_type="FY",
            period_end_date=period_end,
            source_type="manual",
            is_current=True,
        ),
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="per_share.capital_spending",
            value_numeric=2,
            unit=currencies[2],
            currency=currencies[2],
            period_type="FY",
            period_end_date=period_end,
            source_type="manual",
            is_current=True,
        ),
    ]
    db_session.add_all(facts)
    db_session.commit()
    return facts


def _dcf_assumption(client, *, user, stock, auth_headers, selection="norm"):
    response = client.get(
        f"/api/v1/stocks/by_ticker/{stock.ticker}", headers=auth_headers(user)
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    entry = (
        payload["dcf_inputs"]
        if selection == "norm"
        else next(item for item in payload["dcf_inputs_series"] if item["year"] == selection)
    )
    canonical_inputs = entry.get("canonical_model_inputs") or {}
    actual_inputs = {
        "net_profit_per_share": canonical_inputs.get("net_profit_per_share") or "10.000",
        "depreciation_per_share": canonical_inputs.get("depreciation_per_share") or "10.000",
        "capital_spending_per_share": canonical_inputs.get("capital_spending_per_share") or "2.000",
        "based_on_per_share": canonical_inputs.get("based_on_per_share") or "18.000",
        "discount_rate_pct": "10",
        "growth_years": "10",
        "growth_rate_pct": "6",
        "terminal_years": "100",
        "terminal_rate_pct": "4",
    }
    return {
        "source": "dcf",
        "label": "DCF model v1",
        "model": {
            "model_version": "dcf_model_v1",
            "selection": selection,
            "input_manifest": entry["input_manifest"],
            "input_manifest_token": entry["input_manifest_token"],
            "actual_inputs": actual_inputs,
            "user_override_fields": [],
            "growth_rate_selection": None,
        },
    }


def _dcf_save_payload(assumption, *, as_of_date=None):
    payload = {
        "metric_key": FAIR_VALUE_KEY,
        "source": "dcf",
        "valuation_currency": "USD",
        "assumptions": [assumption],
    }
    if as_of_date is not None:
        payload["as_of_date"] = as_of_date.isoformat()
    return payload


def test_put_fair_value_preserves_prior_period_and_demotes_only_same_day_slot(
    client, db_session, auth_headers
):
    user = _make_user(db_session)
    stock = _make_stock(db_session, "FVR")
    headers = auth_headers(user)

    today_et = datetime.now(timezone.utc).astimezone(ET).date()
    prior_period_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=100.0,
        unit="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 2, 1),
        source_type="manual",
        is_current=True,
    )
    same_day_fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=FAIR_VALUE_KEY,
        value_numeric=110.0,
        unit="USD",
        period_type="AS_OF",
        period_end_date=today_et,
        source_type="manual",
        is_current=True,
    )
    db_session.add_all([prior_period_fact, same_day_fact])
    db_session.commit()

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=headers,
        json={"metric_key": FAIR_VALUE_KEY, "value_numeric": 125.0},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["metric_key"] == FAIR_VALUE_KEY
    assert payload["value_numeric"] == 125.0
    assert payload["value_numeric_exact"] == "125.000000"
    assert payload["is_current"] is True
    assert payload["research_case_id"] is not None
    assert payload["research_revision_id"] is not None

    facts = (
        db_session.query(MetricFact)
        .filter(MetricFact.user_id == user.id, MetricFact.stock_id == stock.id, MetricFact.metric_key == FAIR_VALUE_KEY)
        .order_by(MetricFact.created_at.asc())
        .all()
    )
    assert len(facts) == 3
    by_value = {fact.value_numeric: fact for fact in facts}
    assert by_value[100.0].is_current is True
    assert by_value[110.0].is_current is False
    assert by_value[125.0].is_current is True
    assert by_value[125.0].source_ref_id == payload["research_revision_id"]

    case = db_session.get(ResearchCase, payload["research_case_id"])
    revision = db_session.get(ResearchCaseRevision, payload["research_revision_id"])
    assert case is not None
    assert case.user_id == user.id
    assert case.stock_id == stock.id
    assert case.head_revision_number == 1
    assert revision is not None
    assert revision.case_id == case.id
    assert revision.valuation_low == revision.valuation_base == revision.valuation_high
    assert float(revision.valuation_base) == 125.0
    assert revision.valuation_currency == "USD"


def test_put_dcf_value_copies_labeled_assumptions_into_research_revision(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fairvalue-dcf@example.com")
    stock = _make_stock(db_session, "DCFJ")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": "999.000000",
            "source": "dcf",
            "valuation_currency": "USD",
            "assumptions": [assumption],
        },
    )

    assert response.status_code == 200, response.text
    revision = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert revision is not None
    expected_result = float(calculate_dcf_model(assumption["model"]["actual_inputs"])["value_per_share"])
    assert [
        float(revision.valuation_low),
        float(revision.valuation_base),
        float(revision.valuation_high),
    ] == [expected_result, expected_result, expected_result]
    assert len(revision.assumptions_json) == 1
    saved_assumption = revision.assumptions_json[0]
    assert saved_assumption["source"] == "dcf"
    assert saved_assumption["model_version"] == "dcf_model_v1"
    assert saved_assumption["calculation_version"] == "dcf-two-stage-finite-v1"
    assert saved_assumption["selection"] == "norm"
    assert saved_assumption["manifest_verified_at"] is not None
    assert saved_assumption["input_manifest"] == assumption["model"]["input_manifest"]
    assert saved_assumption["input_manifest_token"] == assumption["model"]["input_manifest_token"]
    assert saved_assumption["result"]["value_per_share"] == str(
        calculate_dcf_model(assumption["model"]["actual_inputs"])["value_per_share"]
    )
    assert "client_result_per_share" not in saved_assumption
    assert saved_assumption["actual_inputs"]["discount_rate_pct"]["authority"] == "user_assumption"


def test_put_dcf_ignores_arbitrary_legacy_top_level_value_and_saves_server_result(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-arbitrary-result@example.com")
    stock = _make_stock(db_session, "DCFAR")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    payload = _dcf_save_payload(assumption)
    payload["value_numeric"] = "999.000000"

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=payload,
    )

    assert response.status_code == 200, response.text
    expected = calculate_dcf_model(assumption["model"]["actual_inputs"])[
        "value_per_share"
    ]
    assert response.json()["value_numeric"] == float(expected)
    revision = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert revision.valuation_base == expected
    assert revision.assumptions_json[0]["result"]["value_per_share"] == str(expected)
    assert "client_result_per_share" not in revision.assumptions_json[0]


def test_put_dcf_rejects_unrecorded_component_edit(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-unrecorded-edit@example.com")
    stock = _make_stock(db_session, "DCFUE")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    assumption["model"]["actual_inputs"]["net_profit_per_share"] = "11.000"
    assumption["model"]["actual_inputs"]["based_on_per_share"] = "19.000"
    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_override_unrecorded"


def test_put_dcf_recomputes_and_labels_recorded_user_scenario_overrides(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-recorded-override@example.com")
    stock = _make_stock(db_session, "DCFOV")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    assumption["model"]["actual_inputs"]["net_profit_per_share"] = "11.000"
    assumption["model"]["actual_inputs"]["based_on_per_share"] = "20.000"
    assumption["model"]["user_override_fields"] = [
        "net_profit_per_share",
        "based_on_per_share",
    ]
    result = calculate_dcf_model(assumption["model"]["actual_inputs"])

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 200, response.text
    assert response.json()["value_numeric"] == float(result["value_per_share"])
    revision = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    saved = revision.assumptions_json[0]
    assert saved["actual_inputs"]["net_profit_per_share"]["authority"] == "user_override"
    assert saved["actual_inputs"]["based_on_per_share"]["authority"] == "user_override"
    assert saved["canonical_base"]["based_on_per_share"] == {
        "value": "18.000",
        "authority": "derived_from_canonical_inputs",
    }
    assert saved["result"]["value_per_share"] == str(result["value_per_share"])


def test_put_dcf_accepts_maximum_bounded_scenario_and_saves_decimal_result(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-max-domain@example.com")
    stock = _make_stock(db_session, "DCFMAX")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    assumption["model"]["actual_inputs"].update(
        {
            "based_on_per_share": "1000000",
            "discount_rate_pct": "1000",
            "growth_years": "1000",
            "growth_rate_pct": "1000",
            "terminal_years": "1000",
            "terminal_rate_pct": "999.999",
        }
    )
    assumption["model"]["user_override_fields"] = ["based_on_per_share"]
    expected = calculate_dcf_model(assumption["model"]["actual_inputs"])[
        "value_per_share"
    ]

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 200, response.text
    assert response.json()["value_numeric"] == float(expected)
    revision = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert revision.valuation_base == expected
    assert revision.assumptions_json[0]["result"]["value_per_share"] == str(expected)


def test_put_dcf_preserves_exact_server_decimal_through_revision_fact_and_wire(
    client, db_session, auth_headers, monkeypatch
):
    user = _make_user(db_session, "dcf-exact-decimal@example.com")
    stock = _make_stock(db_session, "DCFEX")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    exact = Decimal("991218953812.597121")
    real_calculate = stocks_endpoint.calculate_dcf_model

    def exact_server_calculation(actual_inputs):
        result = real_calculate(actual_inputs)
        result["value_per_share"] = exact
        return result

    monkeypatch.setattr(
        stocks_endpoint, "calculate_dcf_model", exact_server_calculation
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["value_numeric_exact"] == "991218953812.597121"
    revision = db_session.get(
        ResearchCaseRevision, payload["research_revision_id"]
    )
    fact = db_session.get(MetricFact, payload["id"])
    assert revision.valuation_base == exact
    assert revision.assumptions_json[0]["result"]["value_per_share"] == str(exact)
    assert fact.value_numeric == exact


def test_put_dcf_rejects_removed_nested_client_result_field(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-client-result-field@example.com")
    stock = _make_stock(db_session, "DCFCR")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    assumption["model"]["client_result_per_share"] = "999"

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_assumption_invalid"


def test_put_dcf_value_rejects_direct_api_bypass_without_canonical_inputs(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-bypass@example.com")
    stock = _make_stock(db_session, "DCFB")

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 150.0,
            "source": "dcf",
            "valuation_currency": "USD",
            "assumptions": [{"source": "dcf", "based_on_selection": "norm"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_assumption_invalid"


def test_put_dcf_value_rejects_non_usd_and_does_not_relabel_it(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-eur@example.com")
    stock = _make_stock(db_session, "DCFE")
    _add_dcf_inputs(db_session, user=user, stock=stock, currencies=("EUR", "EUR", "EUR"))
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 150.0,
            "source": "dcf",
            "valuation_currency": "EUR",
            "assumptions": [assumption],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_currency_not_supported"
    assert db_session.query(ResearchCaseRevision).count() == 0


def test_put_dcf_value_rejects_mixed_or_invalid_canonical_input_currency(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-invalid@example.com")
    stock = _make_stock(db_session, "DCFI")
    _add_dcf_inputs(db_session, user=user, stock=stock, currencies=("USD", "TWD", "ZZZ"))
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 150.0,
            "source": "dcf",
            "valuation_currency": "USD",
            "assumptions": [assumption],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_input_currency_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stock_id", 999999),
        ("metric_key", "per_share.not_eps"),
        ("source_type", "parsed"),
        ("source_ref_id", 999999),
        ("source_document_id", 999999),
        ("period_type", "AS_OF"),
        ("period_end_date", "2024-12-31"),
        ("value_numeric", "999"),
        ("unit", "EUR"),
        ("currency", "EUR"),
        ("created_at", "2020-01-01T00:00:00+00:00"),
        ("id", 999999999),
    ],
)
def test_put_dcf_rejects_tampered_manifest_even_with_recomputed_token(
    client, db_session, auth_headers, field, value
):
    user = _make_user(db_session, f"dcf-tamper-{field}@example.com")
    stock = _make_stock(db_session, f"D{field[:3].upper()}")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    assumption["model"]["input_manifest"]["facts"][0][field] = value
    assumption["model"]["input_manifest_token"] = dcf_manifest_token(
        assumption["model"]["input_manifest"]
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_input_selection_changed"


def test_put_dcf_rejects_manifest_after_canonical_fact_correction(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-correction@example.com")
    stock = _make_stock(db_session, "DCFC")
    facts = _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    old_eps = next(fact for fact in facts if fact.metric_key == "per_share.eps")
    old_eps.is_current = False
    replacement = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=old_eps.metric_key,
        value_numeric=11,
        unit="USD",
        currency="USD",
        period_type=old_eps.period_type,
        period_end_date=old_eps.period_end_date,
        source_type=old_eps.source_type,
        is_current=True,
    )
    db_session.add(replacement)
    db_session.commit()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_input_selection_changed"


def test_put_dcf_revalidates_newer_current_fact_at_save_time(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-new-year@example.com")
    stock = _make_stock(db_session, "DCFNY")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="owners_earnings_per_share",
            value_numeric=50,
            value_json={"user_authored_formula": True},
            unit="USD",
            currency="USD",
            period_type="FY",
            period_end_date=date(2026, 12, 31),
            source_type="manual",
            is_current=True,
        )
    )
    db_session.commit()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_input_selection_changed"


def test_put_dcf_rejects_manifest_across_new_york_calendar_day(
    client, db_session, auth_headers, monkeypatch
):
    user = _make_user(db_session, "dcf-et-rollover@example.com")
    stock = _make_stock(db_session, "DCFET")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    clock = DcfEvaluationClock(
        datetime(2026, 9, 10, 1, 30, tzinfo=timezone.utc),
        date(2026, 9, 9),
    )
    monkeypatch.setattr(stocks_endpoint, "dcf_evaluation_clock", lambda: clock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    clock = DcfEvaluationClock(
        datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc),
        date(2026, 9, 10),
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_input_selection_changed"


def test_put_dcf_revalidates_classification_authority_at_save_time(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-classification-change@example.com")
    stock = _make_stock(db_session, "DCFCA")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    db_session.execute(
        text(
            """
            INSERT INTO sec_economic_classification_reviews
              (stock_id, economic_class, effective_from, reviewer_user_id,
               review_reason)
            VALUES (:stock_id, 'ordinary', :effective_from, :reviewer,
                    'R12 save-time authority regression')
            """
        ),
        {
            "stock_id": stock.id,
            "effective_from": datetime.now(timezone.utc).astimezone(ET).date(),
            "reviewer": user.id,
        },
    )
    db_session.commit()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_input_selection_changed"


def test_put_dcf_rejects_duplicate_dcf_assumptions_even_if_first_is_valid(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-duplicate@example.com")
    stock = _make_stock(db_session, "DCFD")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    fake = copy.deepcopy(assumption)
    fake["model"]["input_manifest"]["facts"][0]["id"] = 999999999

    payload = _dcf_save_payload(assumption)
    payload["assumptions"].append(fake)
    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_assumption_invalid"


@pytest.mark.parametrize(
    "reserved_field", ["computed_total_value", "client_result_per_share"]
)
def test_put_dcf_rejects_dcf_fields_smuggled_in_a_non_dcf_assumption(
    client, db_session, auth_headers, reserved_field
):
    user = _make_user(db_session, "dcf-smuggled-fields@example.com")
    stock = _make_stock(db_session, "DCFSM")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    payload = _dcf_save_payload(assumption)
    payload["assumptions"].append(
        {"source": "manual", "label": "not DCF", reserved_field: 999}
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dcf_assumption_invalid"


@pytest.mark.parametrize("offset", [-1, 1])
def test_put_dcf_rejects_past_or_future_as_of_date(
    client, db_session, auth_headers, offset
):
    user = _make_user(db_session, f"dcf-date-{offset}@example.com")
    stock = _make_stock(db_session, f"DCFDT{offset + 1}")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    today_et = datetime.now(timezone.utc).astimezone(ET).date()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(
            assumption, as_of_date=today_et + timedelta(days=offset)
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "historical_dcf_save_unsupported"


def test_put_dcf_accepts_today_and_preserves_non_dcf_assumption(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-today@example.com")
    stock = _make_stock(db_session, "DCFTO")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    today_et = datetime.now(timezone.utc).astimezone(ET).date()
    payload = _dcf_save_payload(assumption, as_of_date=today_et)
    payload["assumptions"].insert(
        0, {"source": "manual", "label": "Investor note", "value": "keep"}
    )

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=payload,
    )

    assert response.status_code == 200, response.text
    revision = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert revision.valuation_as_of_date == today_et
    assert revision.assumptions_json[0]["source"] == "manual"
    assert revision.assumptions_json[1]["source"] == "dcf"


def test_get_then_save_selects_older_eligible_facts_after_latest_are_blocked(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-gated-universe@example.com")
    stock = _make_stock(db_session, "DCFGU")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    values_by_year = {
        2027: (100, False),
        2026: (90, False),
        2024: (2, True),
        2023: (3, True),
        2022: (20, True),
        2021: (30, True),
        2020: (40, True),
    }
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="owners_earnings_per_share",
                value_numeric=value,
                value_json={"user_authored_formula": True} if eligible else {},
                unit="USD",
                currency="USD",
                period_type="FY",
                period_end_date=date(year, 12, 31),
                source_type="manual",
                is_current=True,
            )
            for year, (value, eligible) in values_by_year.items()
        ]
    )
    db_session.commit()

    fetched = client.get(
        f"/api/v1/stocks/by_ticker/{stock.ticker}", headers=auth_headers(user)
    )
    assert fetched.status_code == 200, fetched.text
    entry = fetched.json()["dcf_inputs"]
    assert entry["input_manifest"]["selected_year"] == 2025
    assert [item["year"] for item in fetched.json()["oeps_series"]] == [
        2025,
        2024,
        2023,
        2022,
        2021,
        2020,
    ]
    actual_inputs = {
        **entry["canonical_model_inputs"],
        "discount_rate_pct": "10",
        "growth_years": "10",
        "growth_rate_pct": "6",
        "terminal_years": "100",
        "terminal_rate_pct": "4",
    }
    assumption = {
        "source": "dcf",
        "label": "DCF model v1",
        "model": {
            "model_version": "dcf_model_v1",
            "selection": "norm",
            "input_manifest": entry["input_manifest"],
            "input_manifest_token": entry["input_manifest_token"],
            "actual_inputs": actual_inputs,
            "user_override_fields": [],
            "growth_rate_selection": None,
        },
    }
    saved = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )
    assert saved.status_code == 200, saved.text


def test_put_dcf_rejects_unverified_fields_and_oversized_manifest(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "dcf-shape@example.com")
    stock = _make_stock(db_session, "DCFSH")
    _add_dcf_inputs(db_session, user=user, stock=stock)
    assumption = _dcf_assumption(
        client, user=user, stock=stock, auth_headers=auth_headers
    )
    assumption["computed_total_value"] = 999
    invalid = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(assumption),
    )
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "dcf_assumption_invalid"

    oversized_assumption = copy.deepcopy(assumption)
    oversized_assumption.pop("computed_total_value")
    oversized_assumption["model"]["input_manifest"]["padding"] = "x" * 70_000
    oversized = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json=_dcf_save_payload(oversized_assumption),
    )
    assert oversized.status_code == 422


def test_put_fair_value_reopens_monitoring_case_for_explicit_review(
    client, db_session, auth_headers
):
    user = _make_user(db_session, "fairvalue-review@example.com")
    stock = _make_stock(db_session, "REVW")
    pool = StockPool(user_id=user.id, name="Review candidates")
    db_session.add(pool)
    db_session.flush()
    db_session.add(
        PoolMembership(
            user_id=user.id,
            pool_id=pool.id,
            stock_id=stock.id,
            inclusion_type="manual",
        )
    )
    case = ResearchCase(
        user_id=user.id,
        stock_id=stock.id,
        state="monitoring",
        decision="watch",
        next_review_on=date(2026, 10, 1),
        head_revision_number=1,
    )
    db_session.add(case)
    db_session.flush()
    db_session.add(
        ResearchCaseRevision(
            case_id=case.id,
            revision_number=1,
            thesis="Original monitoring thesis",
            risks_json=[{"label": "Competition"}],
            evidence_json=[{"source_type": "user_note", "label": "Note", "claim": "Evidence"}],
            case_state="monitoring",
            valuation_low=90,
            valuation_base=100,
            valuation_high=110,
            valuation_currency="USD",
            valuation_as_of_date=date(2026, 7, 17),
            decision="watch",
            next_review_on=date(2026, 10, 1),
            snapshot_stock_id=stock.id,
            stock_ticker=stock.ticker,
            stock_company_name=stock.company_name,
            stock_exchange=stock.exchange,
            created_by_user_id=user.id,
        )
    )
    db_session.commit()

    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
        json={
            "metric_key": FAIR_VALUE_KEY,
            "value_numeric": 140.0,
            "valuation_low": 120.0,
            "valuation_high": 160.0,
            "source": "watchlist",
            "pool_id": pool.id,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["value_numeric"] == 140.0
    assert response.json()["value_numeric_exact"] == "140.000000"
    db_session.refresh(case)
    assert case.state == "researching"
    assert case.decision is None
    assert case.next_review_on is None
    latest = db_session.get(
        ResearchCaseRevision, response.json()["research_revision_id"]
    )
    assert latest is not None
    assert latest.case_state == "researching"
    assert latest.decision is None


def test_put_fair_value_rejects_unknown_metric_key(client, db_session, auth_headers):
    user = _make_user(db_session, "fairvalue2@example.com")
    stock = _make_stock(db_session, "BAD")
    headers = auth_headers(user)

    resp = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=headers,
        json={"metric_key": "val.unknown", "value_numeric": 10.0},
    )
    assert resp.status_code == 400
