from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.facts import MetricFact
from app.models.stocks import PoolMembership, Stock, StockPool
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
from app.services.evaluation_snapshot import (
    EvaluationSnapshot,
    database_evaluation_snapshot,
)
from app.services.method_applicability import (
    RISK_ATTRIBUTES,
    review_company_classification,
    review_company_risk_attribute,
)
from app.services.canonical_financials import (
    apply_reviewed_method_gates,
    database_evaluation_cutoff,
    reviewed_method_gate,
)
from app.services import dcf_inputs
from app.services.oracles_lens import dashboard as oracles_dashboard
from app.services.oracles_lens.dashboard import (
    _m3_facts_by_stock,
    _quality_overlay_by_stock,
    _valuation_reference_by_stock,
)
from app.services.research_cases import (
    redact_revision,
    save_product_valuation_revision,
)
from app.services.valuation import (
    read_valuation_context,
    read_valuation_facts_by_stock,
)


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


def test_valuation_context_uses_db_currentness_time_not_caller_fact_time(
    db_session, user_factory
) -> None:
    user = user_factory("valuation-cutoff@example.com")
    stock = _stock(db_session, "VALCUTOFF")
    cutoff = datetime.now(timezone.utc) + timedelta(days=1)
    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="val.fair_value",
            value_numeric=123,
            value_json={"manual_role": "direct_intrinsic_value"},
            unit="USD",
            currency="USD",
            period_type="AS_OF",
            period_end_date=cutoff.date(),
            source_type="manual",
            is_current=True,
            created_at=cutoff + timedelta(minutes=1),
            updated_at=cutoff + timedelta(minutes=1),
        )
    )
    db_session.commit()

    at_cutoff = read_valuation_context(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        knowledge_cutoff=cutoff,
    )

    assert at_cutoff.user_intrinsic_value == 123
    assert at_cutoff.user_intrinsic_value_status == "available"
    assert read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    ).user_intrinsic_value == 123


def _legacy_owner_earnings_facts(
    *, user_id: int, stock_id: int, analysis_method=None
) -> list[MetricFact]:
    value_json = {"calculation_version": "owners-earnings-per-share-v1"}
    if analysis_method is not None:
        value_json["analysis_method"] = analysis_method
    return [
        MetricFact(
            user_id=user_id,
            stock_id=stock_id,
            metric_key=metric_key,
            value_numeric=value,
            value_json=dict(value_json),
            unit="USD",
            currency="USD",
            period_type=period_type,
            period_end_date=date(2025, 12, 31),
            source_type="calculated",
            is_current=True,
        )
        for metric_key, value, period_type in (
            ("owners_earnings_per_share", 3.5, "FY"),
            ("owners_earnings_per_share_normalized", 3.5, "AS_OF"),
        )
    ]


def _legacy_linked_valuation_fact(
    db_session,
    *,
    published: MetricFact,
    user_id: int | None = None,
    stock_id: int | None = None,
    source_ref_id: int | None = None,
) -> MetricFact:
    """Create retained pre-origin lineage without rewriting a newer fact."""

    published.is_current = False
    db_session.commit()
    fact = MetricFact(
        user_id=published.user_id if user_id is None else user_id,
        stock_id=published.stock_id if stock_id is None else stock_id,
        metric_key="val.fair_value",
        value_numeric=published.value_numeric,
        unit=published.unit,
        currency=published.currency,
        period_type=published.period_type,
        period_end_date=published.period_end_date,
        source_type="manual",
        source_ref_id=(
            published.source_ref_id if source_ref_id is None else source_ref_id
        ),
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()
    return fact
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


@pytest.mark.parametrize(
    ("snapshot_kind", "reason_code"),
    [
        ("missing", "method_authority_snapshot_missing"),
        ("malformed", "method_authority_snapshot_invalid"),
        ("forged", "method_authority_snapshot_invalid"),
        ("future", "method_authority_snapshot_invalid"),
    ],
)
def test_calculated_owner_earnings_requires_exact_origin_authority_snapshot(
    db_session, user_factory, snapshot_kind: str, reason_code: str
) -> None:
    reviewer = user_factory(f"oe-origin-{snapshot_kind}@example.com", role="admin")
    stock = _stock(db_session, f"OE{snapshot_kind[:6]}")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    evaluation_cutoff = datetime.now(timezone.utc) + timedelta(seconds=2)
    snapshot = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date.today(),
        knowledge_at=evaluation_cutoff,
    ).as_dict()
    if snapshot_kind == "missing":
        snapshot = None
    elif snapshot_kind == "malformed":
        snapshot = ["not", "a", "decision"]
    elif snapshot_kind == "forged":
        snapshot["policy_sha256"] = "0" * 64
    else:
        future_cutoff = datetime.now(timezone.utc) + timedelta(days=1)
        snapshot = reviewed_method_gate(
            db_session,
            stock_id=stock.id,
            method_key="owner_earnings",
            effective_as_of=date.today(),
            knowledge_at=future_cutoff,
        ).as_dict()
        evaluation_cutoff = future_cutoff
    fact = _legacy_owner_earnings_facts(
        user_id=reviewer.id,
        stock_id=stock.id,
        analysis_method=snapshot,
    )[0]
    db_session.add(fact)
    db_session.commit()

    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
        knowledge_at=evaluation_cutoff,
    )

    assert kept == []
    assert len(blocked) == 1
    assert blocked[0]["reason_code"] == reason_code
    assert blocked[0]["value_numeric"] is None


def test_legacy_owner_earnings_without_origin_snapshot_is_quarantined_everywhere(
    client, db_session, user_factory, auth_headers, monkeypatch
) -> None:
    reviewer = user_factory("oe-origin-consumers@example.com", role="admin")
    stock = _stock(db_session, "OEORIGIN")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    db_session.add_all(
        _legacy_owner_earnings_facts(user_id=reviewer.id, stock_id=stock.id)
    )
    db_session.commit()

    stock_facts = client.get(
        f"/api/v1/stocks/{stock.id}/facts", headers=auth_headers(reviewer)
    )
    assert stock_facts.status_code == 200, stock_facts.text
    legacy_states = [
        row
        for row in stock_facts.json()
        if row["metric_key"].startswith("owners_earnings_per_share")
    ]
    assert legacy_states
    assert all(row["value_numeric"] is None for row in legacy_states)
    assert {row["reason_code"] for row in legacy_states} == {
        "method_authority_snapshot_missing"
    }

    created = client.post(
        "/api/v1/research/cases",
        headers=auth_headers(reviewer),
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": "legacy-owner-earnings-origin-test",
                "source_version": "user-action-v1",
                "source_ref": {"entry_point": "test"},
            },
        },
    )
    assert created.status_code == 201, created.text
    workspace = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=auth_headers(reviewer),
    )
    assert workspace.status_code == 200, workspace.text
    workspace_states = [
        row
        for row in workspace.json()["fundamentals"]
        if row["metric_key"].startswith("owners_earnings_per_share")
    ]
    assert workspace_states
    assert all(row["value_numeric"] is None for row in workspace_states)
    assert {row["reason_code"] for row in workspace_states} == {
        "method_authority_snapshot_missing"
    }

    overlay = _quality_overlay_by_stock(
        db_session, [stock.id], user_id=reviewer.id
    )[stock.id]
    assert overlay["owner_earnings_yield"] is None
    assert overlay["owner_earnings_method"]["status"] == "unsupported"
    assert overlay["owner_earnings_method"]["reason_code"] == (
        "method_authority_snapshot_missing"
    )

    original_gate = dcf_inputs.reviewed_method_gate

    def ft09_test_gate(session, **kwargs):
        decision = original_gate(session, **kwargs)
        if decision.method_key != "system_valuation":
            return decision
        return replace(
            decision,
            status="approved",
            reason_code="approved",
            method_version_id="test-system-valuation-v1",
        )

    monkeypatch.setattr(dcf_inputs, "reviewed_method_gate", ft09_test_gate)
    with pytest.raises(DcfFactUniverseError) as captured:
        load_canonical_dcf_fact_universe(
            db_session,
            stock_id=stock.id,
            user_id=reviewer.id,
            evaluated_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            effective_as_of=date.today(),
        )
    assert captured.value.code == "unsupported"
    assert captured.value.reason_code == "method_authority_snapshot_missing"


@pytest.mark.parametrize(
    ("economic_class", "reason_code"),
    [
        (None, "classification_unreviewed"),
        ("bank", "owner_earnings_unsupported_for_bank"),
        ("reit", "owner_earnings_unsupported_for_reit"),
    ],
)
def test_legacy_user_formula_flag_cannot_bypass_owner_earnings_gate(
    client,
    db_session,
    user_factory,
    auth_headers,
    economic_class: str | None,
    reason_code: str,
) -> None:
    reviewer = user_factory(
        f"legacy-formula-{economic_class or 'unreviewed'}@example.com",
        role="admin",
    )
    stock = _stock(db_session, f"LF{(economic_class or 'none')[:5]}")
    if economic_class is not None:
        review_company_classification(
            db_session,
            reviewer_user_id=reviewer.id,
            stock_id=stock.id,
            economic_class=economic_class,
            effective_from=date(2020, 1, 1),
            review_reason="Reviewed regulated industry classification.",
        )
        db_session.commit()
    fact = _legacy_owner_earnings_facts(
        user_id=reviewer.id, stock_id=stock.id
    )[1]
    fact.value_json["user_authored_formula"] = True
    db_session.add(fact)
    db_session.commit()

    stock_response = client.get(
        f"/api/v1/stocks/{stock.id}/facts", headers=auth_headers(reviewer)
    )
    assert stock_response.status_code == 200, stock_response.text
    stock_state = next(
        row
        for row in stock_response.json()
        if row["metric_key"] == "owners_earnings_per_share_normalized"
    )
    assert stock_state["value_numeric"] is None
    assert stock_state["reason_code"] == reason_code

    created = client.post(
        "/api/v1/research/cases",
        headers=auth_headers(reviewer),
        json={
            "stock_id": stock.id,
            "origin": {
                "origin_type": "manual",
                "origin_key": f"legacy-formula-{economic_class or 'unreviewed'}",
                "source_version": "user-action-v1",
                "source_ref": {"entry_point": "test"},
            },
        },
    )
    assert created.status_code == 201, created.text
    workspace = client.get(
        f"/api/v1/research/cases/{created.json()['case']['id']}/workspace",
        headers=auth_headers(reviewer),
    )
    assert workspace.status_code == 200, workspace.text
    workspace_state = next(
        row
        for row in workspace.json()["fundamentals"]
        if row["metric_key"] == "owners_earnings_per_share_normalized"
    )
    assert workspace_state["value_numeric"] is None
    assert workspace_state["reason_code"] == reason_code

    overlay = _quality_overlay_by_stock(
        db_session, [stock.id], user_id=reviewer.id
    )[stock.id]
    assert overlay["owner_earnings_yield"] is None
    assert overlay["owner_earnings_method"]["status"] == "unsupported"
    assert overlay["owner_earnings_method"]["reason_code"] == reason_code


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


def test_oracles_lens_current_gate_uses_new_york_date_and_preserves_historical_date(
    db_session, user_factory, monkeypatch
) -> None:
    reviewer = user_factory("oracle-et-boundary@example.com", role="admin")
    stock = _stock(db_session, "ORACLEET")
    db_now = database_evaluation_cutoff(db_session)
    effective_date = db_now.date() + timedelta(days=2)
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class="ordinary",
        effective_from=effective_date,
        review_reason="Oracle boundary classification review.",
    )
    for risk_attribute in sorted(RISK_ATTRIBUTES):
        review_company_risk_attribute(
            db_session,
            reviewer_user_id=reviewer.id,
            stock_id=stock.id,
            risk_attribute=risk_attribute,
            is_present=False,
            effective_from=effective_date,
            review_reason=f"Oracle boundary review for {risk_attribute}.",
        )
    fact = MetricFact(
        user_id=reviewer.id,
        stock_id=stock.id,
        metric_key="returns.total_capital",
        value_numeric=0.25,
        value_json={"fact_nature": "actual"},
        unit="ratio",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="manual",
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()
    early = datetime.combine(
        effective_date, datetime.min.time(), tzinfo=timezone.utc
    ) + timedelta(minutes=30)
    late = datetime.combine(
        effective_date,
        datetime.min.time(),
        tzinfo=ZoneInfo("America/New_York"),
    ).astimezone(timezone.utc) + timedelta(minutes=30)
    clock = [early]
    visibility_snapshot = database_evaluation_snapshot(db_session).visibility_snapshot
    monkeypatch.setattr(
        oracles_dashboard,
        "database_evaluation_snapshot",
        lambda _session, supplied=None: EvaluationSnapshot(
            cutoff=supplied or clock[0],
            visibility_snapshot=visibility_snapshot,
        ),
    )

    current, states = _m3_facts_by_stock(
        db_session,
        [stock.id],
        ["returns.total_capital"],
        user_id=reviewer.id,
    )
    assert current[stock.id] == {}
    assert states[stock.id]["reason_code"] == "classification_unreviewed"

    clock[0] = late
    current, states = _m3_facts_by_stock(
        db_session,
        [stock.id],
        ["returns.total_capital"],
        user_id=reviewer.id,
    )
    assert current[stock.id]["returns.total_capital"].id == fact.id
    assert states[stock.id]["status"] == "available"

    historical, states = _m3_facts_by_stock(
        db_session,
        [stock.id],
        ["returns.total_capital"],
        user_id=reviewer.id,
        effective_as_of=effective_date - timedelta(days=1),
        knowledge_at=late,
    )
    assert historical[stock.id] == {}
    assert states[stock.id]["reason_code"] == "classification_unreviewed"


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
    input_facts = _owner_earnings_inputs(
        user_id=reviewer.id, stock_id=stock.id
    )
    db_session.add_all(input_facts)
    db_session.commit()
    created = IngestionService(db_session)._persist_owner_earnings_facts(
        user_id=reviewer.id,
        stock_id=stock.id,
        report_date=date.today(),
    )
    assert created
    db_session.commit()
    created_snapshot = created[0].value_json["analysis_method"]
    assert reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date.fromisoformat(created_snapshot["effective_as_of"]),
        knowledge_at=datetime.fromisoformat(created_snapshot["knowledge_at"]),
    ).as_dict() == created_snapshot

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

    cutoff = min(fact.created_at for fact in input_facts) - timedelta(
        microseconds=1
    )
    manifest = {
        "manifest_version": DCF_MANIFEST_VERSION,
        "selection_rule_version": DCF_NORMALIZED_SELECTION_RULE,
        "selection": "norm",
        "selected_year": None,
        "evaluated_at": cutoff.isoformat(),
        "effective_as_of": cutoff.astimezone(
            ZoneInfo("America/New_York")
        ).date().isoformat(),
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


def test_legacy_dcf_revision_is_quarantined_across_valuation_consumers(
    client, db_session, user_factory, auth_headers
) -> None:
    user = user_factory("legacy-dcf-reader@example.com")
    stock = _stock(db_session, "LEGACYDCF")
    case, revision, fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=125,
        valuation_low=100,
        valuation_high=150,
        as_of_date=date.today(),
        source="dcf",
        pool_id=None,
        assumptions=[{"source": "dcf", "label": "Legacy system DCF"}],
        valuation_currency="USD",
    )
    assert fact.value_numeric == 125

    projected = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )[stock.id]["val.fair_value"]
    assert projected.id == fact.id
    assert projected.source_ref_id == revision.id
    assert projected.value_numeric is None
    assert projected.value_json == {
        "status": "unsupported",
        "reason_code": "system_valuation_method_pending_ft09",
    }
    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    assert context.user_intrinsic_value is None
    assert context.user_intrinsic_value_status == "unsupported"
    assert context.user_intrinsic_value_reason_code == (
        "system_valuation_method_pending_ft09"
    )

    workspace = client.get(
        f"/api/v1/research/cases/{case.id}/workspace",
        headers=auth_headers(user),
    )
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["valuation"]["user_intrinsic_value"] is None
    assert workspace.json()["valuation"]["user_intrinsic_value_status"] == (
        "unsupported"
    )
    assert workspace.json()["valuation"]["user_intrinsic_value_reason_code"] == (
        "system_valuation_method_pending_ft09"
    )

    pool = client.post(
        "/api/v1/stock_pools",
        headers=auth_headers(user),
        json={"name": "Legacy DCF quarantine"},
    )
    assert pool.status_code == 200, pool.text
    membership = client.post(
        f"/api/v1/stock_pools/{pool.json()['id']}/members",
        headers=auth_headers(user),
        json={"stock_id": stock.id},
    )
    assert membership.status_code == 200, membership.text
    rows = client.get(
        f"/api/v1/stock_pools/{pool.json()['id']}/members",
        headers=auth_headers(user),
    )
    assert rows.status_code == 200, rows.text
    row = next(item for item in rows.json() if item["stock_id"] == stock.id)
    assert row["fair_value"] is None
    assert row["fair_value_status"] == "unsupported"
    assert row["fair_value_reason_code"] == (
        "system_valuation_method_pending_ft09"
    )

    oracle = _valuation_reference_by_stock(
        db_session,
        {stock.id: (90, 140)},
        user_id=user.id,
    )[stock.id]
    assert oracle["valuation_reference"] is None
    assert "system_valuation_method_pending_ft09" in oracle[
        "valuation_unavailable_reasons"
    ]

    manual_stock = _stock(db_session, "MANUALIV")
    _, _, manual_fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=manual_stock.id,
        value_numeric=80,
        valuation_low=70,
        valuation_high=90,
        as_of_date=date.today(),
        source="manual",
        pool_id=None,
        assumptions=[{"source": "manual", "label": "Human valuation"}],
        valuation_currency="USD",
    )
    manual_context = read_valuation_context(
        db_session, user_id=user.id, stock_id=manual_stock.id
    )
    assert manual_context.user_intrinsic_value == 80
    assert manual_context.user_intrinsic_value_status == "available"
    assert manual_context.user_intrinsic_value_reason_code is None
    assert manual_context.user_intrinsic_value_fact_id == manual_fact.id

    _, replacement_revision, replacement_fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=130,
        valuation_low=120,
        valuation_high=140,
        as_of_date=date.today(),
        source="manual",
        pool_id=None,
        assumptions=[{"source": "manual", "label": "Human replacement"}],
        valuation_currency="USD",
    )
    assert {item["source"] for item in replacement_revision.assumptions_json} == {
        "dcf",
        "manual",
    }
    replacement_context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    assert replacement_context.user_intrinsic_value == 130
    assert replacement_context.user_intrinsic_value_status == "available"
    assert replacement_context.user_intrinsic_value_reason_code is None
    assert replacement_context.user_intrinsic_value_fact_id == replacement_fact.id


@pytest.mark.parametrize("source", ["manual", "watchlist"])
def test_new_human_valuation_with_empty_assumptions_has_server_origin(
    db_session, user_factory, source: str
) -> None:
    user = user_factory(f"server-origin-{source}@example.com")
    stock = _stock(db_session, f"ORIGIN{source[:3].upper()}")
    pool_id = None
    if source == "watchlist":
        pool = StockPool(user_id=user.id, name="Origin test watchlist")
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
        db_session.commit()
        pool_id = pool.id

    _, revision, fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=95,
        valuation_low=90,
        valuation_high=100,
        as_of_date=date.today(),
        source=source,
        pool_id=pool_id,
        assumptions=[],
        valuation_currency="USD",
    )

    assert fact.value_json == {
        "valuation_origin": {
            "version": "research-valuation-origin-v1",
            "source": source,
            "research_revision_id": revision.id,
        }
    }
    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    assert context.user_intrinsic_value == 95
    assert context.user_intrinsic_value_status == "available"
    assert context.user_intrinsic_value_reason_code is None


def test_new_dcf_origin_cannot_be_overridden_by_assumption_order(
    db_session, user_factory
) -> None:
    user = user_factory("server-dcf-origin@example.com")
    stock = _stock(db_session, "DCFORIGIN")
    case, revision, fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=105,
        valuation_low=100,
        valuation_high=110,
        as_of_date=date.today(),
        source="dcf",
        pool_id=None,
        assumptions=[
            {"source": "dcf", "label": "System model"},
            {"source": "manual", "label": "Attempted source override"},
        ],
        valuation_currency="USD",
    )

    assert fact.source_ref_id == revision.id
    projected = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )[stock.id]["val.fair_value"]
    assert projected.value_numeric is None
    assert projected.value_json["reason_code"] == (
        "system_valuation_method_pending_ft09"
    )
    redact_revision(
        db_session,
        user_id=user.id,
        case_id=case.id,
        revision_number=revision.revision_number,
        reason="Redact user-controlled assumptions.",
    )
    projected_after_redaction = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )[stock.id]["val.fair_value"]
    assert projected_after_redaction.id == fact.id
    assert projected_after_redaction.value_numeric is None
    assert projected_after_redaction.value_json["reason_code"] == (
        "system_valuation_method_pending_ft09"
    )


@pytest.mark.parametrize("lineage_state", ["missing", "cross_user", "wrong_stock"])
def test_server_valuation_origin_still_requires_matching_revision_identity(
    db_session, user_factory, lineage_state: str
) -> None:
    owner = user_factory(f"server-origin-owner-{lineage_state}@example.com")
    reader = (
        user_factory(f"server-origin-reader-{lineage_state}@example.com")
        if lineage_state == "cross_user"
        else owner
    )
    revision_stock = _stock(db_session, f"SOR{lineage_state[:4]}")
    fact_stock = (
        _stock(db_session, f"SOF{lineage_state[:4]}")
        if lineage_state == "wrong_stock"
        else revision_stock
    )
    _, revision, published = save_product_valuation_revision(
        db_session,
        user_id=owner.id,
        stock_id=revision_stock.id,
        value_numeric=115,
        valuation_low=110,
        valuation_high=120,
        as_of_date=date.today(),
        source="manual",
        pool_id=None,
        assumptions=[],
        valuation_currency="USD",
    )
    published.is_current = False
    db_session.commit()
    source_ref_id = (
        revision.id + 1_000_000 if lineage_state == "missing" else revision.id
    )
    fact = MetricFact(
        user_id=reader.id,
        stock_id=fact_stock.id,
        metric_key="val.fair_value",
        value_numeric=115,
        value_json={
            "valuation_origin": {
                "version": "research-valuation-origin-v1",
                "source": "manual",
                "research_revision_id": source_ref_id,
            }
        },
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date.today(),
        source_type="manual",
        source_ref_id=source_ref_id,
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()

    projected = read_valuation_facts_by_stock(
        db_session, user_id=reader.id, stock_ids=[fact_stock.id]
    )[fact_stock.id]["val.fair_value"]

    assert projected.id == fact.id
    assert projected.value_numeric is None
    assert projected.value_json == {
        "status": "unsupported",
        "reason_code": "valuation_origin_unverifiable",
    }


def test_server_human_valuation_origin_survives_revision_content_redaction(
    db_session, user_factory
) -> None:
    user = user_factory("server-human-origin-redacted@example.com")
    stock = _stock(db_session, "SORREDACT")
    case, revision, fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=88,
        valuation_low=80,
        valuation_high=95,
        as_of_date=date.today(),
        source="manual",
        pool_id=None,
        assumptions=[],
        valuation_currency="USD",
    )
    redact_revision(
        db_session,
        user_id=user.id,
        case_id=case.id,
        revision_number=revision.revision_number,
        reason="Remove authored research narrative.",
    )

    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )

    assert context.user_intrinsic_value == 88
    assert context.user_intrinsic_value_status == "available"
    assert context.user_intrinsic_value_fact_id == fact.id


@pytest.mark.parametrize(
    "lineage_state", ["redacted", "missing", "cross_user", "wrong_stock"]
)
def test_unverifiable_legacy_linked_valuation_never_exposes_numeric(
    db_session, user_factory, lineage_state: str
) -> None:
    owner = user_factory(f"legacy-origin-owner-{lineage_state}@example.com")
    reader = (
        user_factory(f"legacy-origin-reader-{lineage_state}@example.com")
        if lineage_state == "cross_user"
        else owner
    )
    revision_stock = _stock(db_session, f"RV{lineage_state[:5]}")
    fact_stock = (
        _stock(db_session, f"FV{lineage_state[:5]}")
        if lineage_state == "wrong_stock"
        else revision_stock
    )
    case, revision, published = save_product_valuation_revision(
        db_session,
        user_id=owner.id,
        stock_id=revision_stock.id,
        value_numeric=115,
        valuation_low=110,
        valuation_high=120,
        as_of_date=date.today(),
        source="dcf",
        pool_id=None,
        assumptions=[{"source": "dcf", "label": "Legacy DCF"}],
        valuation_currency="USD",
    )
    if lineage_state == "redacted":
        fact = _legacy_linked_valuation_fact(
            db_session, published=published
        )
        redact_revision(
            db_session,
            user_id=owner.id,
            case_id=case.id,
            revision_number=revision.revision_number,
            reason="Remove user-authored valuation inputs.",
        )
    elif lineage_state == "missing":
        fact = _legacy_linked_valuation_fact(
            db_session,
            published=published,
            source_ref_id=revision.id + 1_000_000,
        )
    else:
        published.is_current = False
        fact = MetricFact(
            user_id=reader.id,
            stock_id=fact_stock.id,
            metric_key="val.fair_value",
            value_numeric=115,
            unit="USD",
            currency="USD",
            period_type="AS_OF",
            period_end_date=date.today(),
            source_type="manual",
            source_ref_id=revision.id,
            is_current=True,
        )
        db_session.add(fact)
        db_session.commit()

    projected = read_valuation_facts_by_stock(
        db_session, user_id=reader.id, stock_ids=[fact_stock.id]
    )[fact_stock.id]["val.fair_value"]
    assert projected.id == fact.id
    assert projected.source_ref_id == fact.source_ref_id
    assert projected.value_numeric is None
    assert projected.value_json == {
        "status": "unsupported",
        "reason_code": "valuation_origin_unverifiable",
    }


def test_legacy_dcf_assumption_cannot_be_hidden_by_later_manual_marker(
    db_session, user_factory
) -> None:
    user = user_factory("legacy-dcf-order@example.com")
    stock = _stock(db_session, "LEGDCFORDER")
    _, revision, fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=120,
        valuation_low=110,
        valuation_high=130,
        as_of_date=date.today(),
        source="dcf",
        pool_id=None,
        assumptions=[
            {"source": "dcf", "label": "Legacy DCF"},
            {"source": "manual", "label": "Later user marker"},
        ],
        valuation_currency="USD",
    )
    fact = _legacy_linked_valuation_fact(db_session, published=fact)

    projected = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock.id]
    )[stock.id]["val.fair_value"]
    assert projected.source_ref_id == revision.id
    assert projected.value_numeric is None
    assert projected.value_json["reason_code"] == (
        "system_valuation_method_pending_ft09"
    )


def test_direct_legacy_manual_value_without_revision_remains_available(
    db_session, user_factory
) -> None:
    user = user_factory("direct-legacy-manual@example.com")
    stock = _stock(db_session, "DIRECTMAN")
    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="val.fair_value",
        value_numeric=75,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date.today(),
        source_type="manual",
        source_ref_id=None,
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()

    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    assert context.user_intrinsic_value == 75
    assert context.user_intrinsic_value_status == "available"
    assert context.user_intrinsic_value_fact_id == fact.id


def test_legacy_linked_explicit_human_origin_remains_available(
    db_session, user_factory
) -> None:
    user = user_factory("linked-legacy-manual@example.com")
    stock = _stock(db_session, "LINKEDMAN")
    _, revision, fact = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        value_numeric=85,
        valuation_low=80,
        valuation_high=90,
        as_of_date=date.today(),
        source="manual",
        pool_id=None,
        assumptions=[{"source": "manual", "label": "Legacy human value"}],
        valuation_currency="USD",
    )
    fact = _legacy_linked_valuation_fact(db_session, published=fact)

    context = read_valuation_context(
        db_session, user_id=user.id, stock_id=stock.id
    )
    assert context.user_intrinsic_value == 85
    assert context.user_intrinsic_value_status == "available"
    assert context.user_intrinsic_value_fact_id == fact.id
    assert fact.source_ref_id == revision.id


def test_batch_valuation_revision_identity_is_checked_per_fact(
    client, db_session, user_factory, auth_headers
) -> None:
    user = user_factory("batch-valuation-lineage@example.com")
    stock_a = _stock(db_session, "BATCHA")
    stock_b = _stock(db_session, "BATCHB")
    _, revision_b, fact_b = save_product_valuation_revision(
        db_session,
        user_id=user.id,
        stock_id=stock_b.id,
        value_numeric=90,
        valuation_low=85,
        valuation_high=95,
        as_of_date=date.today(),
        source="manual",
        pool_id=None,
        assumptions=[{"source": "manual", "label": "Legacy human value"}],
        valuation_currency="USD",
    )
    fact_b = _legacy_linked_valuation_fact(db_session, published=fact_b)
    fact_a = MetricFact(
        user_id=user.id,
        stock_id=stock_a.id,
        metric_key="val.fair_value",
        value_numeric=150,
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date.today(),
        source_type="manual",
        source_ref_id=revision_b.id,
        is_current=True,
    )
    pool = StockPool(user_id=user.id, name="Batch lineage watchlist")
    db_session.add_all([fact_a, pool])
    db_session.flush()
    db_session.add_all(
        [
            PoolMembership(
                user_id=user.id,
                pool_id=pool.id,
                stock_id=stock.id,
                inclusion_type="manual",
            )
            for stock in (stock_a, stock_b)
        ]
    )
    db_session.commit()

    projected = read_valuation_facts_by_stock(
        db_session, user_id=user.id, stock_ids=[stock_a.id, stock_b.id]
    )
    assert projected[stock_a.id]["val.fair_value"].value_numeric is None
    assert projected[stock_a.id]["val.fair_value"].value_json["reason_code"] == (
        "valuation_origin_unverifiable"
    )
    assert projected[stock_b.id]["val.fair_value"].value_numeric == 90

    oracle = _valuation_reference_by_stock(
        db_session,
        {stock_a.id: (100, 140), stock_b.id: (80, 100)},
        user_id=user.id,
    )
    assert oracle[stock_a.id]["valuation_reference"] is None
    assert "valuation_origin_unverifiable" in oracle[stock_a.id][
        "valuation_unavailable_reasons"
    ]
    assert oracle[stock_b.id]["valuation_reference"] == 90

    response = client.get(
        f"/api/v1/stock_pools/{pool.id}/members",
        headers=auth_headers(user),
    )
    assert response.status_code == 200, response.text
    rows = {row["stock_id"]: row for row in response.json()}
    assert rows[stock_a.id]["fair_value"] is None
    assert rows[stock_a.id]["fair_value_reason_code"] == (
        "valuation_origin_unverifiable"
    )
    assert rows[stock_b.id]["fair_value"] == 90
