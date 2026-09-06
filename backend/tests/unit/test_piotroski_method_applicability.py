from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.api.v1.endpoints import stocks as stocks_endpoint
from app.api.v1.endpoints.stock_pools import _guard_piotroski_display_facts
from app.api.v1.endpoints.stocks import _build_piotroski_f_score_card
from app.api.v1.endpoints.stocks_13f import _m3_panel_for_stock
from app.models.facts import Formula, MetricFact
from app.models.research import ResearchCase
from app.models.sec_publication import SecEconomicClassificationReview
from app.models.stocks import Stock
from app.services.calculated_metrics.piotroski_f_score import (
    PiotroskiFScoreCalculator,
)
from app.services.canonical_financials import (
    PiotroskiMethodAuthorityError,
    apply_reviewed_method_gates,
    evaluation_business_date,
    guard_piotroski_method_authority,
    reviewed_method_gate,
)
from app.services.formula_engine import FormulaEngine
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.method_applicability import (
    RISK_ATTRIBUTES,
    review_company_classification,
    review_company_risk_attribute,
)
from app.services.oracles_lens.dashboard import _m3_facts_by_stock
from app.services.research_workspace import build_research_workspace
from app.services.screener_service import ScreenerService


PERIOD_0 = date(2023, 12, 31)
PERIOD_1 = date(2024, 12, 31)


def test_stock_piotroski_card_uses_new_york_business_date(
    monkeypatch, db_session, user_factory
):
    owner = user_factory("stock-piot-clock@example.com")
    stock = _stock(db_session, "SPCLOCK")
    fact = MetricFact(
        user_id=owner.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_numeric=7,
        value_json={"fiscal_year": 2024, "status": "calculated"},
        unit="score_total",
        period_type="FY",
        period_end_date=PERIOD_1,
        source_type="calculated",
        is_current=True,
    )
    db_session.add(fact)
    db_session.commit()
    evaluated_at = datetime.combine(
        datetime.now(timezone.utc).date() + timedelta(days=2),
        datetime.min.time(),
        tzinfo=timezone.utc,
    ) + timedelta(minutes=30)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        stocks_endpoint,
        "guard_reconciled_source_selection",
        lambda facts, **_kwargs: facts,
    )

    def capture_guard(_session, **kwargs):
        captured.update(kwargs)
        return kwargs["facts"], []

    monkeypatch.setattr(
        stocks_endpoint, "guard_piotroski_method_authority", capture_guard
    )

    card = _build_piotroski_f_score_card(
        db_session,
        stock.id,
        current_user_id=owner.id,
        evaluated_at=evaluated_at,
    )

    assert card["state"]["status"] == "available"
    assert captured["knowledge_at"] is evaluated_at
    assert captured["effective_as_of"] == evaluated_at.date() - timedelta(days=1)


def _stock(db_session, ticker: str) -> Stock:
    stock = Stock(
        ticker=ticker,
        exchange="NYSE",
        company_name=f"{ticker} Piotroski Corp",
        is_active=True,
    )
    db_session.add(stock)
    db_session.commit()
    return stock


def _review_profile(
    db_session,
    *,
    reviewer,
    stock: Stock,
    economic_class: str,
    missing_risk: str | None = None,
    present_risk: str | None = None,
) -> None:
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class=economic_class,
        effective_from=date(2020, 1, 1),
        review_reason="Reviewed Piotroski economic classification.",
    )
    if economic_class == "ordinary":
        for risk_attribute in sorted(RISK_ATTRIBUTES):
            if risk_attribute == missing_risk:
                continue
            review_company_risk_attribute(
                db_session,
                reviewer_user_id=reviewer.id,
                stock_id=stock.id,
                risk_attribute=risk_attribute,
                is_present=risk_attribute == present_risk,
                effective_from=date(2020, 1, 1),
                review_reason=f"Reviewed Piotroski {risk_attribute}.",
            )
    db_session.commit()


def _input_fact(
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    value: float,
    period_end: date,
    source_type: str = "parsed",
) -> MetricFact:
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={"fact_nature": "actual", "fiscal_year": period_end.year},
        unit="ratio",
        period_type="FY",
        period_end_date=period_end,
        source_type=source_type,
        is_current=True,
    )


def _add_total_capital_inputs(db_session, *, user, stock: Stock) -> list[MetricFact]:
    facts = [
        _input_fact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="returns.total_capital",
            value=value,
            period_end=period_end,
        )
        for period_end, value in ((PERIOD_0, 0.1), (PERIOD_1, 0.12))
    ]
    db_session.add_all(facts)
    db_session.commit()
    return facts


BLOCKED_PROFILES = [
    ("unreviewed", None, None, None, "classification_unreviewed"),
    ("bank", "bank", None, None, "roic_unsupported_for_bank"),
    ("insurer", "insurer", None, None, "roic_unsupported_for_insurer"),
    ("reit", "reit", None, None, "roic_unsupported_for_reit"),
    (
        "other_financial",
        "other_financial",
        None,
        None,
        "roic_unsupported_for_other_financial",
    ),
    (
        "explicit_unclassified",
        "unclassified",
        None,
        None,
        "roic_unsupported_for_unclassified",
    ),
    *[
        (
            f"missing_{risk_attribute}",
            "ordinary",
            risk_attribute,
            None,
            "risk_review_incomplete",
        )
        for risk_attribute in sorted(RISK_ATTRIBUTES)
    ],
    *[
        (
            f"present_{risk_attribute}",
            "ordinary",
            None,
            risk_attribute,
            "reviewed_risk_attribute_unsupported",
        )
        for risk_attribute in sorted(RISK_ATTRIBUTES)
    ],
]


@pytest.mark.parametrize(
    ("label", "economic_class", "missing_risk", "present_risk", "reason_code"),
    BLOCKED_PROFILES,
)
def test_generation_excludes_unapproved_return_on_total_capital_proxy(
    db_session,
    user_factory,
    label: str,
    economic_class: str | None,
    missing_risk: str | None,
    present_risk: str | None,
    reason_code: str,
) -> None:
    reviewer = user_factory(f"piot-blocked-{label}@example.com", role="admin")
    stock = _stock(db_session, f"PB{len(label)}{label[:3]}")
    if economic_class is not None:
        _review_profile(
            db_session,
            reviewer=reviewer,
            stock=stock,
            economic_class=economic_class,
            missing_risk=missing_risk,
            present_risk=present_risk,
        )
    _add_total_capital_inputs(db_session, user=reviewer, stock=stock)

    written = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=reviewer.id, stock_id=stock.id
    )

    if economic_class in {"bank", "other_financial"}:
        assert written == []
        return

    assert not any(
        fact.metric_key
        in {
            "score.piotroski.roa_positive",
            "score.piotroski.roa_improving",
        }
        for fact in written
    )
    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    assert total.value_numeric is None
    assert total.value_json["status"] == "unavailable"
    assert total.value_json["reason_code"] == reason_code
    assert "partial_score" not in total.value_json
    assert all(
        component.get("method") != "fallback_return_on_total_capital"
        for component in total.value_json.get("components", [])
    )


@pytest.mark.parametrize("economic_class", ["bank", "other_financial"])
def test_financial_class_does_not_generate_piotroski_even_with_standard_roa(
    db_session, user_factory, economic_class: str
) -> None:
    reviewer = user_factory(f"piot-standard-{economic_class}@example.com", role="admin")
    stock = _stock(db_session, f"PS{economic_class[:5]}")
    _review_profile(
        db_session,
        reviewer=reviewer,
        stock=stock,
        economic_class=economic_class,
    )
    db_session.add_all(
        [
            _input_fact(
                user_id=reviewer.id,
                stock_id=stock.id,
                metric_key="returns.roa",
                value=value,
                period_end=period_end,
            )
            for period_end, value in ((PERIOD_0, 0.08), (PERIOD_1, 0.10))
        ]
    )
    db_session.commit()

    assert PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=reviewer.id, stock_id=stock.id
    ) == []


def test_generation_persists_exact_roic_authority_on_proxy_components_and_total(
    db_session, user_factory
) -> None:
    reviewer = user_factory("piot-approved@example.com", role="admin")
    stock = _stock(db_session, "PIOTAPP")
    _review_profile(
        db_session,
        reviewer=reviewer,
        stock=stock,
        economic_class="ordinary",
    )
    source_facts = _add_total_capital_inputs(
        db_session, user=reviewer, stock=stock
    )

    written = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=reviewer.id, stock_id=stock.id
    )

    affected = [
        fact
        for fact in written
        if fact.period_end_date == PERIOD_1
        and fact.metric_key
        in {
            "score.piotroski.roa_positive",
            "score.piotroski.roa_improving",
            "score.piotroski.total",
        }
    ]
    assert {fact.metric_key for fact in affected} == {
        "score.piotroski.roa_positive",
        "score.piotroski.roa_improving",
        "score.piotroski.total",
    }
    snapshots = [fact.value_json["analysis_method"] for fact in affected]
    assert all(snapshot == snapshots[0] for snapshot in snapshots)
    assert snapshots[0]["method_key"] == "roic"
    assert snapshots[0]["status"] == "approved"
    assert snapshots[0]["effective_as_of"] == PERIOD_1.isoformat()
    assert snapshots[0]["economic_class"] == "ordinary"
    assert all(
        datetime.fromisoformat(snapshots[0]["knowledge_at"]) <= fact.created_at
        for fact in affected
    )
    total_inputs = {
        item["fact_id"]
        for item in next(
            fact for fact in affected if fact.metric_key == "score.piotroski.total"
        ).value_json["inputs"]
    }
    assert total_inputs == {fact.id for fact in source_facts}
    post_publication_snapshot = database_evaluation_snapshot(db_session)
    kept, blocked = guard_piotroski_method_authority(
        db_session,
        facts=affected,
        effective_as_of=date.today(),
        evaluation_snapshot=post_publication_snapshot,
    )
    assert kept == affected
    assert blocked == []


def test_standard_roa_path_does_not_require_roic_proxy_approval(
    db_session, user_factory
) -> None:
    user = user_factory("piot-standard-unreviewed@example.com")
    stock = _stock(db_session, "PIOTSTD")
    values = [
        ("returns.roa", 0.08, PERIOD_0),
        ("returns.roa", 0.10, PERIOD_1),
        ("is.operating_cash_flow", 150, PERIOD_1),
        ("is.net_income", 100, PERIOD_1),
        ("leverage.long_term_debt_to_assets", 0.30, PERIOD_0),
        ("leverage.long_term_debt_to_assets", 0.20, PERIOD_1),
        ("liquidity.current_ratio", 1.5, PERIOD_0),
        ("liquidity.current_ratio", 2.0, PERIOD_1),
        ("equity.shares_outstanding", 10, PERIOD_0),
        ("equity.shares_outstanding", 9, PERIOD_1),
        ("is.gross_margin", 0.40, PERIOD_0),
        ("is.gross_margin", 0.45, PERIOD_1),
        ("efficiency.asset_turnover", 1.1, PERIOD_0),
        ("efficiency.asset_turnover", 1.2, PERIOD_1),
    ]
    db_session.add_all(
        [
            _input_fact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key=key,
                value=value,
                period_end=period_end,
            )
            for key, value, period_end in values
        ]
    )
    db_session.commit()

    written = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=user.id, stock_id=stock.id
    )

    total = next(
        fact
        for fact in written
        if fact.metric_key == "score.piotroski.total"
        and fact.period_end_date == PERIOD_1
    )
    assert total.value_numeric == 9
    assert total.value_json["status"] == "calculated"
    assert "analysis_method" not in total.value_json
    assert {
        component["method"] for component in total.value_json["components"]
    } >= {"standard_roa"}


def _approved_roic_snapshot(db_session, *, reviewer, stock: Stock) -> dict:
    _review_profile(
        db_session,
        reviewer=reviewer,
        stock=stock,
        economic_class="ordinary",
    )
    return reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="roic",
        effective_as_of=PERIOD_1,
        knowledge_at=datetime.now(timezone.utc),
    ).as_dict()


def _retained_total(
    *,
    user_id: int,
    stock_id: int,
    input_fact: MetricFact | None,
    snapshot,
    partial: bool = False,
) -> MetricFact:
    inputs = []
    if input_fact is not None:
        inputs = [
            {
                "fact_id": input_fact.id,
                "metric_key": input_fact.metric_key,
                "period_end_date": input_fact.period_end_date.isoformat(),
                "value_numeric": format(input_fact.value_numeric, "f"),
                "source_type": input_fact.source_type,
                "fact_nature": "actual",
            }
        ]
    value_json = {
        "status": "partial" if partial else "calculated",
        "calculation_version": "piotroski_value_line_v1",
        "fiscal_year": PERIOD_1.year,
        "inputs": inputs,
        "components": [
            {
                "metric_key": "score.piotroski.roa_positive",
                "value_numeric": 1,
                "method": "fallback_return_on_total_capital",
            }
        ],
    }
    if partial:
        value_json.update(partial_score=1, max_available_score=1)
    if snapshot is not None:
        value_json["analysis_method"] = snapshot
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key="score.piotroski.total",
        value_numeric=None if partial else 1,
        value_json=value_json,
        unit="score_total",
        period_type="FY",
        period_end_date=PERIOD_1,
        source_type="calculated",
        is_current=True,
    )


def _clone_fact(fact: MetricFact) -> MetricFact:
    return MetricFact(
        user_id=fact.user_id,
        stock_id=fact.stock_id,
        metric_key=fact.metric_key,
        value_numeric=fact.value_numeric,
        value_text=fact.value_text,
        value_json=deepcopy(fact.value_json),
        unit=fact.unit,
        currency=fact.currency,
        period_type=fact.period_type,
        period_end_date=fact.period_end_date,
        source_type=fact.source_type,
        is_current=True,
        created_at=fact.created_at,
    )


def _persist_forged_replacement(
    db_session, *, original: MetricFact, replacement: MetricFact
) -> MetricFact:
    db_session.execute(
        update(MetricFact)
        .where(MetricFact.id == original.id)
        .values(is_current=False)
    )
    db_session.add(replacement)
    db_session.commit()
    return replacement


def _strict_lineage_item(fact: MetricFact) -> dict:
    return {
        "fact_id": fact.id,
        "user_id": fact.user_id,
        "stock_id": fact.stock_id,
        "metric_key": fact.metric_key,
        "period_type": fact.period_type,
        "period_end_date": fact.period_end_date.isoformat(),
        "value_numeric": format(fact.value_numeric, "f"),
        "source_type": fact.source_type,
        "fact_nature": fact.value_json["fact_nature"],
        "created_at": fact.created_at.isoformat(),
    }


@pytest.mark.parametrize(
    ("snapshot_kind", "reason_code"),
    [
        ("missing", "piotroski_method_authority_snapshot_missing"),
        ("malformed", "piotroski_method_authority_snapshot_invalid"),
        ("forged", "piotroski_method_authority_snapshot_invalid"),
        ("future", "piotroski_method_authority_snapshot_invalid"),
        ("mismatch", "piotroski_method_authority_snapshot_invalid"),
    ],
)
def test_retained_total_capital_proxy_requires_exact_origin_authority(
    db_session,
    user_factory,
    snapshot_kind: str,
    reason_code: str,
) -> None:
    reviewer = user_factory(f"piot-retained-{snapshot_kind}@example.com", role="admin")
    stock = _stock(db_session, f"PR{snapshot_kind[:5]}")
    _approved_roic_snapshot(db_session, reviewer=reviewer, stock=stock)
    _add_total_capital_inputs(db_session, user=reviewer, stock=stock)
    generated = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=reviewer.id, stock_id=stock.id
    )
    original = next(
        item
        for item in generated
        if item.metric_key == "score.piotroski.total"
        and item.period_end_date == PERIOD_1
    )
    fact = _clone_fact(original)
    if snapshot_kind == "missing":
        fact.value_json.pop("analysis_method")
    elif snapshot_kind == "malformed":
        fact.value_json["analysis_method"] = ["not", "authority"]
    elif snapshot_kind == "forged":
        fact.value_json["analysis_method"]["policy_sha256"] = "0" * 64
    elif snapshot_kind == "future":
        fact.value_json["analysis_method"]["knowledge_at"] = (
            fact.created_at + timedelta(days=1)
        ).isoformat()
    else:
        fact.value_json["analysis_method"]["effective_as_of"] = (
            PERIOD_0.isoformat()
        )
    fact = _persist_forged_replacement(
        db_session, original=original, replacement=fact
    )

    post_publication_snapshot = database_evaluation_snapshot(db_session)
    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
        evaluation_snapshot=post_publication_snapshot,
    )

    assert kept == []
    assert len(blocked) == 1
    assert blocked[0]["reason_code"] == reason_code
    assert blocked[0]["value_numeric"] is None
    assert "partial_score" not in blocked[0]
    assert "components" not in blocked[0]


@pytest.mark.parametrize(
    "lineage_state",
    [
        "missing",
        "cross_stock",
        "cross_user",
        "wrong_key",
        "wrong_date",
        "wrong_value",
        "wrong_source",
    ],
)
def test_retained_piotroski_requires_verifiable_input_lineage(
    db_session, user_factory, lineage_state: str
) -> None:
    owner = user_factory(f"piot-lineage-owner-{lineage_state}@example.com", role="admin")
    other = user_factory(f"piot-lineage-other-{lineage_state}@example.com")
    stock = _stock(db_session, f"PL{lineage_state[:5]}")
    other_stock = _stock(db_session, f"PX{lineage_state[:5]}")
    _approved_roic_snapshot(db_session, reviewer=owner, stock=stock)
    _add_total_capital_inputs(db_session, user=owner, stock=stock)
    generated = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=owner.id, stock_id=stock.id
    )
    original = next(
        item
        for item in generated
        if item.metric_key == "score.piotroski.total"
        and item.period_end_date == PERIOD_1
    )
    fact = _clone_fact(original)
    if lineage_state == "missing":
        fact.value_json["inputs"] = []
    elif lineage_state in {"cross_stock", "cross_user"}:
        input_fact = _input_fact(
            user_id=other.id if lineage_state == "cross_user" else owner.id,
            stock_id=other_stock.id if lineage_state == "cross_stock" else stock.id,
            metric_key="returns.total_capital",
            value=0.12,
            period_end=PERIOD_1,
            source_type="parsed",
        )
        db_session.add(input_fact)
        db_session.commit()
        fact.value_json["inputs"][0] = _strict_lineage_item(input_fact)
    elif lineage_state == "wrong_key":
        fact.value_json["inputs"][0]["metric_key"] = "returns.roa"
    elif lineage_state == "wrong_date":
        fact.value_json["inputs"][0]["period_end_date"] = date(2022, 12, 31).isoformat()
    elif lineage_state == "wrong_value":
        fact.value_json["inputs"][0]["value_numeric"] = "0.13"
    elif lineage_state == "wrong_source":
        fact.value_json["inputs"][0]["source_type"] = "manual"
    fact = _persist_forged_replacement(
        db_session, original=original, replacement=fact
    )

    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_invalid"
    )


def test_legacy_total_with_verified_non_proxy_inputs_is_still_quarantined(
    db_session, user_factory
) -> None:
    user = user_factory("piot-legacy-standard@example.com")
    stock = _stock(db_session, "PIOTLEG")
    input_fact = _input_fact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="returns.roa",
        value=0.12,
        period_end=PERIOD_1,
        source_type="manual",
    )
    db_session.add(input_fact)
    db_session.flush()
    fact = _retained_total(
        user_id=user.id,
        stock_id=stock.id,
        input_fact=input_fact,
        snapshot=None,
    )
    fact.value_json["components"][0]["method"] = "standard_roa"
    db_session.add(fact)
    db_session.commit()

    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_manifest_missing"
    )


def test_non_calculated_piotroski_namespace_is_never_numeric_authority(
    db_session, user_factory
) -> None:
    user = user_factory("piot-manual-forgery@example.com")
    stock = _stock(db_session, "PIOTMAN")
    input_fact = _input_fact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="returns.roa",
        value=0.12,
        period_end=PERIOD_1,
        source_type="manual",
    )
    db_session.add(input_fact)
    db_session.flush()
    fact = _retained_total(
        user_id=user.id,
        stock_id=stock.id,
        input_fact=input_fact,
        snapshot=None,
    )
    fact.source_type = "manual"
    fact.value_json["components"][0]["method"] = "standard_roa"
    db_session.add(fact)
    db_session.commit()

    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
    )

    assert kept == []
    assert blocked[0]["reason_code"] == (
        "piotroski_method_authority_source_invalid"
    )
    assert blocked[0]["value_numeric"] is None


def test_retained_proxy_requires_current_roic_gate_to_remain_approved(
    db_session, user_factory
) -> None:
    reviewer = user_factory("piot-current-gate@example.com", role="admin")
    stock = _stock(db_session, "PIOTCUR")
    _approved_roic_snapshot(db_session, reviewer=reviewer, stock=stock)
    _add_total_capital_inputs(db_session, user=reviewer, stock=stock)
    generated = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=reviewer.id,
        stock_id=stock.id,
    )
    fact = next(
        item
        for item in generated
        if item.metric_key == "score.piotroski.total"
        and item.period_end_date == PERIOD_1
    )

    post_publication_snapshot = database_evaluation_snapshot(db_session)
    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
        evaluation_snapshot=post_publication_snapshot,
    )
    assert kept == [fact]
    assert blocked == []

    terminal = db_session.query(SecEconomicClassificationReview).filter_by(
        stock_id=stock.id
    ).one()
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class="bank",
        effective_from=date.today(),
        review_reason="Current reviewed classification no longer supports ROIC proxy.",
        supersedes_review_id=terminal.id,
    )
    db_session.commit()

    post_reclassification_snapshot = database_evaluation_snapshot(db_session)
    kept, blocked, _ = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date.today(),
        evaluation_snapshot=post_reclassification_snapshot,
    )
    assert kept == []
    assert blocked[0]["reason_code"] == "roic_unsupported_for_bank"


def test_proxy_without_authority_is_hidden_from_all_numeric_consumers(
    client, db_session, user_factory, auth_headers
) -> None:
    owner = user_factory("piot-consumer-owner@example.com")
    stock = _stock(db_session, "PCONS")
    db_session.add_all(
        [
            _input_fact(
                user_id=owner.id,
                stock_id=stock.id,
                metric_key="returns.total_capital",
                value=0.12,
                period_end=PERIOD_1,
            ),
            _input_fact(
                user_id=owner.id,
                stock_id=stock.id,
                metric_key="is.operating_cash_flow",
                value=150,
                period_end=PERIOD_1,
            ),
        ]
    )
    db_session.commit()
    generated = PiotroskiFScoreCalculator(db_session).calculate_for_stock(
        user_id=owner.id,
        stock_id=stock.id,
    )
    total = next(
        fact for fact in generated if fact.metric_key == "score.piotroski.total"
    )
    research_case = ResearchCase(
        user_id=owner.id,
        stock_id=stock.id,
        state="queued",
    )
    formula = Formula(
        user_id=owner.id,
        name="Custom Piot Consumer",
        expression="score.piotroski.total",
        dependencies_json=["score.piotroski.total"],
    )
    db_session.add_all([research_case, formula])
    db_session.commit()
    evaluated_at = database_evaluation_snapshot(db_session).cutoff

    card = _build_piotroski_f_score_card(
        db_session,
        stock.id,
        current_user_id=owner.id,
        evaluated_at=evaluated_at,
    )
    assert card["years"] == []
    assert card["state"]["reason_code"] == (
        "classification_unreviewed"
    )

    pool_facts, pool_state = _guard_piotroski_display_facts(
        db_session,
        user_id=owner.id,
        stock_id=stock.id,
        facts=[total],
        evaluated_at=evaluated_at,
    )
    assert pool_facts == []
    assert pool_state["reason_code"] == (
        "classification_unreviewed"
    )

    oracle_facts, oracle_states = _m3_facts_by_stock(
        db_session,
        [stock.id],
        ["score.piotroski.total"],
        user_id=owner.id,
        effective_as_of=date.today(),
        knowledge_at=evaluated_at,
    )
    assert oracle_facts[stock.id] == {}
    assert oracle_states[stock.id]["reason_code"] == (
        "classification_unreviewed"
    )

    drawer = _m3_panel_for_stock(db_session, stock.id, user_id=owner.id)
    assert drawer.piotroski_score is None
    assert drawer.piotroski_max is None
    assert drawer.canonical_source_status.reason_code == (
        "classification_unreviewed"
    )

    workspace = build_research_workspace(
        db_session,
        user_id=owner.id,
        case_id=research_case.id,
        as_of=evaluation_business_date(evaluated_at),
        evaluated_at=evaluated_at,
    )
    assert workspace["piotroski_f_score"] == []
    blocked = [
        item
        for item in workspace["fundamentals"]
        if item.get("metric_key") == "score.piotroski.total"
    ]
    assert len(blocked) == 1
    assert blocked[0]["value_numeric"] is None
    assert blocked[0]["reason_code"] == (
        "classification_unreviewed"
    )

    with pytest.raises(PiotroskiMethodAuthorityError) as formula_error:
        FormulaEngine(db_session).run_formula(
            formula.id, stock.id, owner.id
        )
    assert formula_error.value.code == (
        "classification_unreviewed"
    )

    with pytest.raises(PiotroskiMethodAuthorityError) as screener_error:
        ScreenerService(db_session).execute_screen(
            {
                "type": "AND",
                "conditions": [
                    {
                        "metric": "score.piotroski.total",
                        "operator": ">=",
                        "value": 1,
                    }
                ],
            },
            current_user_id=owner.id,
        )
    assert screener_error.value.code == (
        "classification_unreviewed"
    )

    response = client.post(
        "/api/v1/screener/run",
        headers=auth_headers(owner),
        json={
            "type": "AND",
            "conditions": [
                {
                    "metric": "score.piotroski.total",
                    "operator": ">=",
                    "value": 1,
                }
            ],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "classification_unreviewed"
    )
