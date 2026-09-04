from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError

from app.models.facts import MetricFact
from app.models.sec_publication import (
    SecEconomicClassificationReview,
    SecEconomicRiskReview,
)
from app.models.stocks import Stock
from app.services.canonical_financials import (
    apply_reviewed_method_gates,
    reviewed_method_gate,
    system_method_for_fact,
)
from app.services.method_applicability import (
    MethodApplicabilityReviewError,
    review_company_classification,
    review_company_risk_attribute,
)


RISK_ATTRIBUTES = (
    "high_sbc",
    "acquisitive",
    "cyclical",
    "commodity_exposed",
)


def _stock(db_session, ticker: str = "FT07") -> Stock:
    stock = Stock(ticker=ticker, exchange="NYSE", company_name=f"{ticker} Co")
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
    for risk_attribute in RISK_ATTRIBUTES:
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


def test_ft07_policy_schema_and_seed_are_explicit(db_session) -> None:
    columns = {
        column["name"]
        for column in inspect(db_session.bind).get_columns("sec_method_policy_rules")
    }
    assert {
        "method_version_id",
        "required_risk_reviews_json",
        "required_adjustments_json",
        "unsupported_reason_code",
    } <= columns
    policy = db_session.execute(
        text(
            "SELECT id, policy_sha256, known_at, created_at, created_txid "
            "FROM sec_method_policy_versions "
            "WHERE id='analysis-method-applicability-v2'"
        )
    ).mappings().one()
    assert len(policy.policy_sha256) == 64
    assert policy.known_at == policy.created_at
    assert policy.created_txid > 0
    rules = db_session.execute(
        text(
            "SELECT method_key, economic_class, applicability, method_version_id, "
            "required_risk_reviews_json, required_evidence_json, "
            "required_adjustments_json, required_outputs_json, "
            "unsupported_reason_code FROM sec_method_policy_rules "
            "WHERE method_policy_version_id=:policy ORDER BY method_key, economic_class"
        ),
        {"policy": policy.id},
    ).mappings().all()
    assert len(rules) == 24
    ordinary = {row.method_key: row for row in rules if row.economic_class == "ordinary"}
    assert ordinary["owner_earnings"].method_version_id == "owner-earnings-per-share-v1"
    assert ordinary["roic"].method_version_id == "value-line-return-on-total-capital-v1"
    assert ordinary["per_share_trend"].method_version_id == "value-line-per-share-rates-v1"
    assert ordinary["system_valuation"].applicability == "unsupported"
    assert ordinary["system_valuation"].unsupported_reason_code == (
        "system_valuation_method_pending_ft09"
    )
    assert all(
        row.required_risk_reviews_json == list(RISK_ATTRIBUTES)
        for row in ordinary.values()
        if row.applicability == "approved"
    )


def test_reviewed_ordinary_profile_approves_only_existing_methods(
    db_session, user_factory
) -> None:
    reviewer = user_factory("ft07-admin@example.com", role="admin")
    stock = _stock(db_session)
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)

    decisions = {
        method: reviewed_method_gate(
            db_session,
            stock_id=stock.id,
            method_key=method,
            effective_as_of=date(2026, 9, 4),
            knowledge_at=cutoff,
        )
        for method in (
            "owner_earnings",
            "roic",
            "per_share_trend",
            "system_valuation",
        )
    }

    assert decisions["owner_earnings"].status == "approved"
    assert decisions["owner_earnings"].method_version_id == (
        "owner-earnings-per-share-v1"
    )
    assert decisions["owner_earnings"].policy_sha256
    assert decisions["owner_earnings"].risk_attributes == ()
    assert len(decisions["owner_earnings"].risk_review_ids) == 4
    assert decisions["owner_earnings"].required_evidence
    assert decisions["owner_earnings"].required_adjustments == (
        "all_capex_treated_as_maintenance",
    )
    assert decisions["roic"].status == "approved"
    assert decisions["per_share_trend"].status == "approved"
    assert decisions["system_valuation"].status == "unsupported"
    assert decisions["system_valuation"].reason_code == (
        "system_valuation_method_pending_ft09"
    )
    assert decisions["system_valuation"].method_version_id is None


def test_missing_risk_reviews_never_default_to_false(db_session, user_factory) -> None:
    reviewer = user_factory("ft07-incomplete-admin@example.com", role="admin")
    stock = _stock(db_session, "FT07MISS")
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class="ordinary",
        effective_from=date(2020, 1, 1),
        review_reason="Reviewed ordinary operating company.",
    )
    db_session.commit()

    decision = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 9, 4),
    )

    assert decision.status == "unsupported"
    assert decision.reason_code == "risk_review_incomplete"
    assert decision.missing_risk_reviews == RISK_ATTRIBUTES
    assert decision.risk_review_ids == ()


@pytest.mark.parametrize(
    "economic_class",
    ["bank", "insurer", "reit", "other_financial", "unclassified"],
)
@pytest.mark.parametrize(
    "method_key",
    ["owner_earnings", "roic", "per_share_trend", "system_valuation"],
)
def test_nonordinary_classes_never_receive_ordinary_method(
    db_session, user_factory, economic_class: str, method_key: str
) -> None:
    reviewer = user_factory(
        f"ft07-{economic_class}-{method_key}@example.com", role="admin"
    )
    stock = _stock(db_session, f"X{economic_class[:3]}{method_key[:3]}")
    review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class=economic_class,
        effective_from=date(2020, 1, 1),
        review_reason="Reviewed economic class for negative method fixture.",
    )
    db_session.commit()

    decision = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key=method_key,
        effective_as_of=date(2026, 9, 4),
    )

    assert decision.status == "unsupported"
    assert decision.reason_code == f"{method_key}_unsupported_for_{economic_class}"
    assert decision.method_version_id is None
    assert decision.classification_review_id is not None


@pytest.mark.parametrize("risk_attribute", RISK_ATTRIBUTES)
@pytest.mark.parametrize(
    "method_key", ["owner_earnings", "roic", "per_share_trend", "system_valuation"]
)
def test_reviewed_present_risk_attribute_blocks_generic_method(
    db_session, user_factory, risk_attribute: str, method_key: str
) -> None:
    reviewer = user_factory(
        f"ft07-{risk_attribute}-{method_key}@example.com", role="admin"
    )
    stock = _stock(db_session, f"R{risk_attribute[:3]}{method_key[:3]}")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    prior = db_session.scalar(
        select(SecEconomicRiskReview).where(
            SecEconomicRiskReview.stock_id == stock.id,
            SecEconomicRiskReview.risk_attribute == risk_attribute,
        )
    )
    assert prior is not None
    review_company_risk_attribute(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        risk_attribute=risk_attribute,
        is_present=True,
        effective_from=prior.effective_from,
        review_reason="Reviewed attribute is material for this method.",
        supersedes_review_id=prior.id,
    )
    db_session.commit()

    decision = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key=method_key,
        effective_as_of=date(2026, 9, 4),
    )

    assert decision.status == "unsupported"
    if method_key == "system_valuation":
        assert decision.reason_code == "system_valuation_method_pending_ft09"
    else:
        assert decision.reason_code == "reviewed_risk_attribute_unsupported"
    assert risk_attribute in decision.risk_attributes


def test_classification_and_risk_supersession_replay_at_knowledge_cutoff(
    db_session, user_factory
) -> None:
    reviewer = user_factory("ft07-replay-admin@example.com", role="admin")
    stock = _stock(db_session, "FT07PIT")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    first = db_session.scalar(
        select(SecEconomicClassificationReview).where(
            SecEconomicClassificationReview.stock_id == stock.id
        )
    )
    assert first is not None
    historical_cutoff = max(
        [first.known_at]
        + list(
            db_session.scalars(
                select(SecEconomicRiskReview.known_at).where(
                    SecEconomicRiskReview.stock_id == stock.id
                )
            ).all()
        )
    )
    replacement = review_company_classification(
        db_session,
        reviewer_user_id=reviewer.id,
        stock_id=stock.id,
        economic_class="bank",
        effective_from=first.effective_from,
        review_reason="Corrected the reviewed economic classification.",
        supersedes_review_id=first.id,
    )
    db_session.commit()

    before = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 9, 4),
        knowledge_at=historical_cutoff,
    )
    after = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 9, 4),
        knowledge_at=replacement.known_at,
    )

    assert before.status == "approved"
    assert before.economic_class == "ordinary"
    assert after.status == "unsupported"
    assert after.economic_class == "bank"
    assert after.reason_code == "owner_earnings_unsupported_for_bank"


def test_operator_service_requires_active_admin_and_db_stamps_authority(
    db_session, user_factory
) -> None:
    ordinary_user = user_factory("ft07-user@example.com")
    disabled_admin = user_factory(
        "ft07-disabled-admin@example.com", role="admin", is_active=False
    )
    admin = user_factory("ft07-real-admin@example.com", role="admin")
    stock = _stock(db_session, "FT07AUTH")

    for reviewer in (ordinary_user, disabled_admin):
        with pytest.raises(MethodApplicabilityReviewError, match="active admin"):
            review_company_classification(
                db_session,
                reviewer_user_id=reviewer.id,
                stock_id=stock.id,
                economic_class="ordinary",
                effective_from=date(2020, 1, 1),
                review_reason="Attempted unauthorized review.",
            )

    review = review_company_classification(
        db_session,
        reviewer_user_id=admin.id,
        stock_id=stock.id,
        economic_class="ordinary",
        effective_from=date(2020, 1, 1),
        review_reason="Authorized operator review.",
    )
    db_session.commit()
    assert review.reviewer_user_id == admin.id
    assert review.known_at.tzinfo is not None
    assert review.created_txid > 0
    with pytest.raises(DBAPIError, match="append-only"):
        db_session.execute(
            text(
                "UPDATE sec_economic_classification_reviews "
                "SET review_reason='forged' WHERE id=:id"
            ),
            {"id": review.id},
        )
    db_session.rollback()


def test_database_rejects_forged_non_admin_review_authority(
    db_session, user_factory
) -> None:
    ordinary_user = user_factory("ft07-sql-user@example.com")
    stock = _stock(db_session, "FT07SQL")

    with pytest.raises(DBAPIError, match="requires active admin"):
        db_session.execute(
            text(
                "INSERT INTO sec_economic_classification_reviews "
                "(stock_id,economic_class,effective_from,reviewer_user_id,review_reason) "
                "VALUES (:stock,'ordinary','2020-01-01',:reviewer,'forged SQL review')"
            ),
            {"stock": stock.id, "reviewer": ordinary_user.id},
        )
    db_session.rollback()


def test_database_overwrites_forged_review_knowledge_time(
    db_session, user_factory
) -> None:
    admin = user_factory("ft07-sql-admin@example.com", role="admin")
    stock = _stock(db_session, "FT07STAMP")
    forged = datetime(2000, 1, 1, tzinfo=timezone.utc)
    row = db_session.execute(
        text(
            "INSERT INTO sec_economic_classification_reviews "
            "(stock_id,economic_class,effective_from,known_at,reviewer_user_id,"
            "review_reason,created_at,created_txid) VALUES "
            "(:stock,'ordinary','2020-01-01',:forged,:reviewer,'authorized review',"
            ":forged,1) RETURNING known_at,created_at,created_txid"
        ),
        {"stock": stock.id, "reviewer": admin.id, "forged": forged},
    ).mappings().one()

    assert row.known_at == row.created_at
    assert row.known_at > forged
    assert row.created_txid > 1


def test_policy_knowledge_cutoff_never_looks_ahead(db_session) -> None:
    policy_known_at = db_session.execute(
        text(
            "SELECT known_at FROM sec_method_policy_versions "
            "WHERE id='analysis-method-applicability-v2'"
        )
    ).scalar_one()
    stock = _stock(db_session, "FT07POLPIT")

    before = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 9, 4),
        knowledge_at=policy_known_at - timedelta(microseconds=1),
    )
    after = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2026, 9, 4),
        knowledge_at=policy_known_at,
    )

    assert before.method_policy_version_id == "sec-method-gate-v1"
    assert after.method_policy_version_id == "analysis-method-applicability-v2"


@pytest.mark.parametrize("review_kind", ["classification", *RISK_ATTRIBUTES])
def test_prospective_supersession_preserves_prior_effective_range(
    db_session, user_factory, review_kind: str
) -> None:
    reviewer = user_factory(f"ft07-range-{review_kind}@example.com", role="admin")
    stock = _stock(db_session, f"P{review_kind[:6]}")
    _review_ordinary_profile(db_session, reviewer=reviewer, stock=stock)
    if review_kind == "classification":
        prior = db_session.scalar(
            select(SecEconomicClassificationReview).where(
                SecEconomicClassificationReview.stock_id == stock.id
            )
        )
        assert prior is not None
        earlier_cutoff = datetime.now(timezone.utc)
        replacement = review_company_classification(
            db_session,
            reviewer_user_id=reviewer.id,
            stock_id=stock.id,
            economic_class="bank",
            effective_from=date(2025, 1, 1),
            review_reason="Prospective regulated-industry transition.",
            supersedes_review_id=prior.id,
        )
    else:
        prior = db_session.scalar(
            select(SecEconomicRiskReview).where(
                SecEconomicRiskReview.stock_id == stock.id,
                SecEconomicRiskReview.risk_attribute == review_kind,
            )
        )
        assert prior is not None
        earlier_cutoff = datetime.now(timezone.utc)
        replacement = review_company_risk_attribute(
            db_session,
            reviewer_user_id=reviewer.id,
            stock_id=stock.id,
            risk_attribute=review_kind,
            is_present=True,
            effective_from=date(2025, 1, 1),
            review_reason="Prospective material-risk transition.",
            supersedes_review_id=prior.id,
        )
    db_session.commit()

    historical_effective = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2024, 12, 31),
        knowledge_at=replacement.known_at,
    )
    prospective_effective = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2025, 1, 1),
        knowledge_at=replacement.known_at,
    )
    before_review = reviewed_method_gate(
        db_session,
        stock_id=stock.id,
        method_key="owner_earnings",
        effective_as_of=date(2025, 1, 1),
        knowledge_at=earlier_cutoff,
    )

    assert historical_effective.status == "approved"
    assert historical_effective.economic_class == "ordinary"
    assert before_review.status == "approved"
    if review_kind == "classification":
        assert prospective_effective.economic_class == "bank"
        assert prospective_effective.reason_code == "owner_earnings_unsupported_for_bank"
    else:
        assert prospective_effective.economic_class == "ordinary"
        assert prospective_effective.reason_code == "reviewed_risk_attribute_unsupported"
        assert review_kind in prospective_effective.risk_attributes


@pytest.mark.parametrize(
    ("metric_key", "expected"),
    [
        ("owners_earnings_per_share", "owner_earnings"),
        ("returns.roic", "roic"),
        ("returns.total_capital", "roic"),
        ("bs.return_on_total_capital", "roic"),
        ("rates.earnings.cagr_10y", "per_share_trend"),
        ("rates.cash_flow.cagr_est", "per_share_trend"),
        ("system_valuation.dcf", "system_valuation"),
        ("per_share.eps", None),
    ],
)
def test_all_current_governed_metric_shapes_share_one_classifier(
    metric_key: str, expected: str | None
) -> None:
    assert system_method_for_fact(
        MetricFact(metric_key=metric_key, value_json={}, source_type="calculated")
    ) == expected


def test_blocked_fact_has_typed_state_and_no_partial_numeric(db_session) -> None:
    stock = _stock(db_session, "FT07BLOCK")
    fact = MetricFact(
        stock_id=stock.id,
        metric_key="returns.total_capital",
        value_numeric=1,
        source_type="parsed",
        is_current=True,
    )

    kept, blocked, decisions = apply_reviewed_method_gates(
        db_session,
        stock_id=stock.id,
        facts=[fact],
        effective_as_of=date(2026, 9, 4),
    )

    assert kept == []
    assert decisions["roic"].status == "unsupported"
    assert blocked == [
        {
            **blocked[0],
            "status": "unsupported",
            "method_key": "roic",
            "metric_key": "returns.total_capital",
            "value_numeric": None,
            "unit": None,
        }
    ]
