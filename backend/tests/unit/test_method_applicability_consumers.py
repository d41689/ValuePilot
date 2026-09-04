from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models.facts import MetricFact
from app.models.stocks import Stock
import pytest

from app.services.dcf_inputs import (
    DCF_MANIFEST_VERSION,
    DCF_NORMALIZED_SELECTION_RULE,
    DcfFactUniverseError,
    _stable_method_authority,
    dcf_manifest_token,
    load_canonical_dcf_fact_universe,
)
from app.services.ingestion_service import IngestionService
from app.services.method_applicability import (
    RISK_ATTRIBUTES,
    review_company_classification,
    review_company_risk_attribute,
)
from app.services.canonical_financials import reviewed_method_gate
from app.services.oracles_lens.dashboard import _quality_overlay_by_stock


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NYSE",
        company_name=f"{ticker} Incorporated",
        is_active=True,
    )
    db_session.add(stock)
    db_session.commit()
    return stock


def _review_ordinary_profile(db_session, *, reviewer, stock: Stock) -> None:
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class="ordinary",
        effective_from=date(2020, 1, 1),
        review_reason="Reviewed operating model and regulated-industry status.",
    )
    for risk_attribute in sorted(RISK_ATTRIBUTES):
        review_company_risk_attribute(
            db_session,
            reviewer_user_id=reviewer.id,
            stock_id=stock.id,
            risk_attribute=risk_attribute,
            is_present=False,
            effective_from=date(2020, 1, 1),
            review_reason=f"Reviewed {risk_attribute} against retained evidence.",
        )
    db_session.commit()


def _owner_earnings_inputs(*, user_id: int, stock_id: int) -> list[MetricFact]:
    rows = [
        ("per_share.eps", 5.0, "USD"),
        ("per_share.capital_spending", 2.0, "USD"),
        ("is.depreciation", 10.0, "USD"),
        ("equity.shares_outstanding", 20.0, "shares"),
    ]
    return [
        MetricFact(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            value_numeric=value,
            value_json={"fact_nature": "actual"},
            unit=unit,
            currency="USD" if unit == "USD" else None,
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            source_type="parsed",
            is_current=True,
        )
        for metric_key, value, unit in rows
    ]


def test_owner_earnings_persistence_requires_reviewed_method_authority(
    db_session, user_factory
) -> None:
    user = user_factory("consumer-oe-unreviewed@example.com")
    stock = _stock(db_session, "OEUNREVIEWED")
    db_session.add_all(_owner_earnings_inputs(user_id=user.id, stock_id=stock.id))
    db_session.commit()

    created = IngestionService(db_session)._persist_owner_earnings_facts(
        user_id=user.id,
        stock_id=stock.id,
        report_date=date.today(),
    )

    assert created == []
    assert not db_session.query(MetricFact).filter(
        MetricFact.stock_id == stock.id,
        MetricFact.metric_key.startswith("owners_earnings_per_share"),
    ).count()


def test_owner_earnings_persists_exact_reviewed_authority_snapshot(
    db_session, user_factory
) -> None:
    reviewer = user_factory("consumer-oe-reviewed@example.com", role="admin")
    stock = _stock(db_session, "OEREVIEWED")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    db_session.add_all(
        _owner_earnings_inputs(user_id=reviewer.id, stock_id=stock.id)
    )
    db_session.commit()
    created = IngestionService(db_session)._persist_owner_earnings_facts(
        user_id=reviewer.id,
        stock_id=stock.id,
        report_date=date.today(),
    )

    assert created
    for fact in created:
        authority = fact.value_json["analysis_method"]
        assert authority["method_key"] == "owner_earnings"
        assert authority["status"] == "approved"
        assert authority["method_policy_version_id"] == (
            "analysis-method-applicability-v2"
        )
        assert authority["policy_sha256"]
        assert authority["method_version_id"] == "owner-earnings-per-share-v1"
        assert authority["economic_class"] == "ordinary"
        assert authority["classification_review_id"]
        assert len(authority["risk_review_ids"]) == 4
        risk_reviews = {
            review["risk_attribute"]: review
            for review in authority["risk_reviews"]
        }
        assert set(risk_reviews) == set(RISK_ATTRIBUTES)
        assert {
            review["review_id"] for review in risk_reviews.values()
        } == set(authority["risk_review_ids"])
        assert all(
            review["is_present"] is False for review in risk_reviews.values()
        )
        assert authority["required_evidence"]
        assert authority["required_adjustments"] == [
            "all_capex_treated_as_maintenance"
        ]
        assert authority["effective_as_of"] == date.today().isoformat()
        assert authority["knowledge_at"]


def test_stock_facts_publish_method_authority_and_block_unreviewed_numeric(
    client, db_session, user_factory, auth_headers
) -> None:
    reviewer = user_factory("consumer-facts-reviewed@example.com", role="admin")
    reviewed = _stock(db_session, "FACTREVIEWED")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=reviewed)
    unreviewed = _stock(db_session, "FACTUNREVIEWED")
    db_session.add_all(
        [
            MetricFact(
                user_id=reviewer.id,
                stock_id=stock.id,
                metric_key="returns.total_capital",
                value_numeric=0.2,
                value_json={"fact_nature": "actual"},
                unit="ratio",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="manual",
                is_current=True,
            )
            for stock in (reviewed, unreviewed)
        ]
    )
    db_session.commit()

    approved_response = client.get(
        f"/api/v1/stocks/{reviewed.id}/facts", headers=auth_headers(reviewer)
    )
    blocked_response = client.get(
        f"/api/v1/stocks/{unreviewed.id}/facts", headers=auth_headers(reviewer)
    )

    assert approved_response.status_code == 200, approved_response.text
    approved = next(
        row
        for row in approved_response.json()
        if row["metric_key"] == "returns.total_capital"
    )
    assert approved["status"] == "published"
    assert approved["value_numeric"] == "0.200000000000"
    assert approved["method_gate"]["status"] == "approved"
    assert approved["method_gate"]["policy_sha256"]
    assert approved["method_gate"]["classification_review_id"]
    assert len(approved["method_gate"]["risk_review_ids"]) == 4

    assert blocked_response.status_code == 200, blocked_response.text
    blocked = next(
        row
        for row in blocked_response.json()
        if row["metric_key"] == "returns.total_capital"
    )
    assert blocked["status"] == "unsupported"
    assert blocked["reason_code"] == "classification_unreviewed"
    assert blocked["value_numeric"] is None


def test_stock_summary_never_offers_unreviewed_per_share_growth_numeric(
    client, db_session, user_factory, auth_headers
) -> None:
    user = user_factory("consumer-growth-unreviewed@example.com")
    stock = _stock(db_session, "GROWTHUNREVIEWED")
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="rates.earnings.cagr_est",
            value_numeric=0.08,
            value_json={"value": 8.0, "fact_nature": "estimate"},
            unit="ratio",
            period_type="PROJECTION_RANGE",
            period_end_date=date.today(),
            source_type="manual",
            is_current=True,
        )
    )
    db_session.commit()

    response = client.get(
        "/api/v1/stocks/by_ticker/GROWTHUNREVIEWED", headers=auth_headers(user)
    )

    assert response.status_code == 200, response.text
    assert response.json()["growth_rate_options"] == []
    gate = response.json()["system_method_gates"]["per_share_trend"]
    assert gate["status"] == "unsupported"
    assert gate["reason_code"] == "classification_unreviewed"


def test_research_workspace_publishes_review_authority_with_governed_fact(
    client, db_session, user_factory, auth_headers
) -> None:
    reviewer = user_factory("consumer-workspace-reviewed@example.com", role="admin")
    stock = _stock(db_session, "WORKSPACEMETHOD")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    db_session.add(
        MetricFact(
            user_id=reviewer.id,
            stock_id=stock.id,
            metric_key="returns.total_capital",
            value_numeric=0.21,
            value_json={"fact_nature": "actual"},
            unit="ratio",
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            source_type="manual",
            is_current=True,
        )
    )
    db_session.commit()
    created = client.post(
        "/api/v1/research/cases",
        headers=auth_headers(reviewer),
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": "method-consumer-test",
                "source_version": "user-action-v1",
                "source_ref": {"entry_point": "test"},
            },
        },
    )
    assert created.status_code == 201, created.text

    response = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=auth_headers(reviewer),
    )

    assert response.status_code == 200, response.text
    fact = next(
        row
        for row in response.json()["fundamentals"]
        if row["metric_key"] == "returns.total_capital"
    )
    assert fact["value_numeric"] == "0.210000000000"
    assert fact["method_gate"]["status"] == "approved"
    assert fact["method_gate"]["policy_sha256"]
    assert response.json()["system_method_gates"]["roic"] == fact["method_gate"]


def test_oracles_lens_exposes_typed_roic_gate_when_numeric_is_blocked(
    db_session, user_factory
) -> None:
    user = user_factory("consumer-oracle-unreviewed@example.com")
    stock = _stock(db_session, "ORACLEMETHOD")
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="bs.return_on_total_capital",
            value_numeric=0.25,
            value_json={"fact_nature": "actual"},
            unit="ratio",
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            source_type="manual",
            is_current=True,
        )
    )
    db_session.commit()

    overlay = _quality_overlay_by_stock(
        db_session, [stock.id], user_id=user.id
    )[stock.id]

    assert overlay["return_on_total_capital"] is None
    assert overlay["system_method_gates"]["roic"]["status"] == "unsupported"
    assert overlay["system_method_gates"]["roic"]["reason_code"] == (
        "classification_unreviewed"
    )


def test_dcf_manifest_method_authority_carries_complete_stable_contract(
    db_session, user_factory
) -> None:
    reviewer = user_factory("consumer-dcf-reviewed@example.com", role="admin")
    stock = _stock(db_session, "DCFMETHOD")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    evaluated_at = datetime.now(timezone.utc) + timedelta(seconds=1)

    decisions = {
        method_key: reviewed_method_gate(
            db_session,
            stock_id=stock.id,
            method_key=method_key,
            knowledge_at=evaluated_at,
            effective_as_of=date.today(),
        )
        for method_key in (
            "owner_earnings",
            "roic",
            "per_share_trend",
            "system_valuation",
        )
    }

    owner = next(
        row
        for row in _stable_method_authority(decisions)
        if row["method_key"] == "owner_earnings"
    )
    assert owner["policy_sha256"]
    assert owner["method_version_id"] == "owner-earnings-per-share-v1"
    assert owner["required_evidence"]
    assert owner["required_adjustments"] == ["all_capex_treated_as_maintenance"]
    assert len(owner["risk_review_ids"]) == 4
    assert {
        row["risk_attribute"]: (row["review_id"], row["is_present"])
        for row in owner["risk_reviews"]
    } == {
        risk_attribute: (review_id, False)
        for risk_attribute, review_id in zip(
            sorted(RISK_ATTRIBUTES), sorted(owner["risk_review_ids"]), strict=True
        )
    }
    assert "knowledge_at" not in owner


def test_dcf_universe_blocks_pending_system_valuation_without_partial_inputs(
    db_session, user_factory
) -> None:
    reviewer = user_factory("consumer-dcf-blocked@example.com", role="admin")
    stock = _stock(db_session, "DCFBLOCKED")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    db_session.add_all(
        _owner_earnings_inputs(user_id=reviewer.id, stock_id=stock.id)
    )
    db_session.commit()

    with pytest.raises(DcfFactUniverseError) as captured:
        load_canonical_dcf_fact_universe(
            db_session,
            stock_id=stock.id,
            user_id=reviewer.id,
            evaluated_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            effective_as_of=date.today(),
        )

    assert captured.value.code == "unsupported"
    assert captured.value.reason_code == "system_valuation_method_pending_ft09"
    assert captured.value.method_gate["method_key"] == "system_valuation"
    assert captured.value.method_gate["status"] == "unsupported"


def test_stock_page_and_save_block_pending_system_valuation_without_numeric(
    client, db_session, user_factory, auth_headers
) -> None:
    reviewer = user_factory("consumer-dcf-api-blocked@example.com", role="admin")
    stock = _stock(db_session, "DCFAPIBLOCK")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    db_session.add_all(
        _owner_earnings_inputs(user_id=reviewer.id, stock_id=stock.id)
    )
    db_session.commit()
    created = IngestionService(db_session)._persist_owner_earnings_facts(
        user_id=reviewer.id,
        stock_id=stock.id,
        report_date=date.today(),
    )
    assert created
    db_session.commit()

    summary = client.get(
        f"/api/v1/stocks/by_ticker/{stock.ticker}", headers=auth_headers(reviewer)
    )

    assert summary.status_code == 200, summary.text
    assert summary.json()["dcf_inputs"] is None
    assert summary.json()["dcf_inputs_series"] == []
    assert summary.json()["oeps_series"] == [
        {
            "year": 2025,
            "value": 3.5,
            "provenance": {
                "source_type": "calculated",
                "source_document_id": None,
                "source_report_date": None,
                "period_end_date": "2025-12-31",
                "is_active_report": False,
            },
        }
    ]
    assert summary.json()["canonical_input_status"]["status"] == "unsupported"
    assert summary.json()["canonical_input_status"]["reason_code"] == (
        "system_valuation_method_pending_ft09"
    )
    assert summary.json()["canonical_input_status"]["method_gate"][
        "method_key"
    ] == "system_valuation"

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    manifest = {
        "manifest_version": DCF_MANIFEST_VERSION,
        "selection_rule_version": DCF_NORMALIZED_SELECTION_RULE,
        "selection": "norm",
        "selected_year": None,
        "evaluated_at": cutoff.isoformat(),
        "effective_as_of": cutoff.astimezone().date().isoformat(),
        "method_authority": [],
        "facts": [],
    }
    response = client.put(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(reviewer),
        json={
            "metric_key": "val.fair_value",
            "source": "dcf",
            "valuation_currency": "USD",
            "assumptions": [
                {
                    "source": "dcf",
                    "label": "stale DCF",
                    "model": {
                        "model_version": "dcf_model_v1",
                        "selection": "norm",
                        "input_manifest": manifest,
                        "input_manifest_token": dcf_manifest_token(manifest),
                        "actual_inputs": {},
                        "user_override_fields": [],
                        "growth_rate_selection": None,
                    },
                }
            ],
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == (
        "system_valuation_method_pending_ft09"
    )
    assert db_session.query(MetricFact).filter(
        MetricFact.stock_id == stock.id,
        MetricFact.metric_key == "val.fair_value",
    ).count() == 0
