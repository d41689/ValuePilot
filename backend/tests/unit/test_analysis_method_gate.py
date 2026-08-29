from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.stocks import Stock
from app.services.ingestion_service import _approved_owner_earnings_facts
from app.services.analysis_method_gate import (
    AnalysisMethodError,
    evaluate_analysis_method,
    register_reviewed_company_classification,
)


def test_reviewed_ordinary_company_gets_versioned_eligibility_not_a_conclusion(
    db_session,
) -> None:
    stock = Stock(ticker="METHOD", exchange="NYSE", company_name="Method Co")
    db_session.add(stock)
    db_session.flush()
    known_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="ordinary_operating",
        effective_from=date(2020, 1, 1),
        known_at=known_at,
        review_reason="Reviewed business model and regulated-industry status.",
    )
    db_session.commit()

    result = evaluate_analysis_method(
        db_session,
        stock_id=stock.id,
        analysis_kind="owner_earnings",
        cutoff=known_at + timedelta(seconds=1),
    )

    assert result.state == "eligible"
    assert result.classification == "ordinary_operating"
    assert result.method_id == "ordinary-owner-economics-v1"
    assert result.policy_version == "analysis-method-gate-v1"
    assert "maintenance_capex" in result.required_evidence
    assert "stock_based_compensation" in result.required_evidence
    assert result.output_authorized is False
    assert result.conclusion_authorized is False


def test_evidence_requirements_do_not_authorize_legacy_owner_earnings_formula(
    db_session,
) -> None:
    stock = Stock(ticker="NOFAKEOE", exchange="NYSE", company_name="No False Precision")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="ordinary_operating",
        effective_from=date(2020, 1, 1),
        known_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        review_reason="Reviewed ordinary operating company.",
    )
    db_session.commit()
    period_end = date(2025, 12, 31)
    apparent_complete_input = [
        {
            "metric_key": metric_key,
            "value_numeric": 1.0,
            "period_type": "FY",
            "period_end_date": period_end,
        }
        for metric_key in (
            "per_share.eps",
            "per_share.capital_spending",
            "is.depreciation",
            "equity.shares_outstanding",
            "is.operating_cash_flow",
            "owners_earnings.maintenance_capex_adjustment",
            "cf.change_in_working_capital",
            "is.stock_based_compensation",
            "cf.acquisitions",
            "equity.diluted_shares_outstanding",
        )
    ]

    assert (
        _approved_owner_earnings_facts(
            db_session,
            stock_id=stock.id,
            facts=apparent_complete_input,
            report_date=period_end,
        )
        == []
    )


@pytest.mark.parametrize(
    "classification",
    [
        "bank",
        "insurer",
        "reit",
        "high_sbc_acquisitive",
        "cyclical_commodity",
    ],
)
def test_generic_owner_economics_is_unsupported_for_nonordinary_strata(
    db_session, classification: str
) -> None:
    stock = Stock(
        ticker=f"M{classification[:5]}",
        exchange="NYSE",
        company_name=f"{classification} fixture",
    )
    db_session.add(stock)
    db_session.flush()
    register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification=classification,
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        review_reason="Locked FT-00 stratum reviewed by an operator.",
    )
    db_session.commit()

    result = evaluate_analysis_method(
        db_session,
        stock_id=stock.id,
        analysis_kind="owner_earnings",
        cutoff=datetime(2026, 8, 28, 13, 0, tzinfo=timezone.utc),
    )

    assert result.state == "unsupported"
    assert result.reason_code == f"owner_earnings_method_unapproved_for_{classification}"
    assert result.method_id is None
    assert result.conclusion_authorized is False


def test_classification_is_pit_and_cannot_be_inferred_or_backdated(db_session) -> None:
    stock = Stock(ticker="PITM", exchange="NYSE", company_name="PIT Method Bank")
    db_session.add(stock)
    db_session.flush()
    known_at = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="bank",
        effective_from=date(2000, 1, 1),
        known_at=known_at,
        review_reason="Reviewed regulated financial institution classification.",
    )
    db_session.commit()

    before = evaluate_analysis_method(
        db_session,
        stock_id=stock.id,
        analysis_kind="roic",
        cutoff=known_at.replace(hour=11),
    )
    after = evaluate_analysis_method(
        db_session,
        stock_id=stock.id,
        analysis_kind="roic",
        cutoff=known_at.replace(hour=13),
    )
    assert before.state == "unknown"
    assert before.reason_code == "company_classification_missing"
    assert after.state == "unsupported"

    with pytest.raises(AnalysisMethodError, match="review_reason"):
        register_reviewed_company_classification(
            db_session,
            stock_id=stock.id,
            classification="ordinary_operating",
            effective_from=date(2026, 1, 1),
            known_at=known_at.replace(hour=14),
            review_reason="",
        )


def test_database_rejects_overlapping_reviewed_classification_insert(
    db_session,
) -> None:
    stock = Stock(ticker="DBMETHOD", exchange="NYSE", company_name="DB Method")
    db_session.add(stock)
    db_session.flush()
    register_reviewed_company_classification(
        db_session,
        stock_id=stock.id,
        classification="bank",
        effective_from=date(2020, 1, 1),
        known_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        review_reason="Reviewed bank classification.",
    )
    db_session.commit()

    with pytest.raises(
        DBAPIError, match="overlapping terminal company analysis classification"
    ):
        db_session.execute(
            text(
                "INSERT INTO company_analysis_classifications "
                "(stock_id, classification, status, method_policy_version, "
                "effective_from, known_at, review_reason, evidence_json) VALUES "
                "(:stock_id, 'ordinary_operating', 'reviewed', "
                "'analysis-method-gate-v1', '2020-01-01', now(), "
                "'raw SQL bypass', '{}'::jsonb)"
            ),
            {"stock_id": stock.id},
        )
    db_session.rollback()


def test_old_classification_policy_fails_closed(db_session) -> None:
    stock = Stock(ticker="OLDPOL", exchange="NYSE", company_name="Old Policy")
    db_session.add(stock)
    db_session.flush()
    known_at = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    db_session.execute(
        text(
            "INSERT INTO company_analysis_classifications "
            "(stock_id, classification, status, method_policy_version, "
            "effective_from, known_at, review_reason, evidence_json) VALUES "
            "(:stock_id, 'ordinary_operating', 'reviewed', 'retired-v0', "
            "'2020-01-01', :known_at, 'legacy reviewed policy', '{}'::jsonb)"
        ),
        {"stock_id": stock.id, "known_at": known_at},
    )
    db_session.commit()

    result = evaluate_analysis_method(
        db_session,
        stock_id=stock.id,
        analysis_kind="roic",
        cutoff=known_at + timedelta(seconds=1),
    )

    assert result.state == "unsupported"
    assert result.reason_code == "classification_policy_unsupported"
    assert result.method_id is None
    assert result.output_authorized is False
