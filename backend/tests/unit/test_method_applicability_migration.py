from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BASE = make_url(settings.SQLALCHEMY_DATABASE_URI).set(
    query={
        key: value
        for key, value in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items()
        if key != "options"
    }
).render_as_string(hide_password=False)
BACKEND = Path(__file__).resolve().parents[2]
HEAD = "20260904150000"
PARENT = "20260904140000"


def _alembic_result(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def isolated():
    name = new_test_schema_name()
    url = build_isolated_database_url(BASE, name)
    create_test_schema(BASE, name)
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        drop_test_schema(BASE, name)


def test_v2_fact_snapshot_refuses_downgrade_before_any_schema_mutation(isolated) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('ft07-downgrade@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('FT07DOWN','NYSE','US','FT07 Downgrade',true) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,unit,period_type,"
                "period_end_date,source_type,is_current) "
                "VALUES (:user,:stock,'owners_earnings_per_share',1.5,"
                "CAST(:payload AS jsonb),'USD','FY','2025-12-31','calculated',true)"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps(
                    {
                        "analysis_method": {
                            "method_policy_version_id": (
                                "analysis-method-applicability-v2"
                            ),
                            "method_key": "owner_earnings",
                            "status": "approved",
                        }
                    }
                ),
            },
        )

    refused = _alembic_result(url, "downgrade", PARENT)
    assert refused.returncode != 0
    assert "cannot downgrade retained FT-07 method authority" in (
        refused.stdout + refused.stderr
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        assert connection.execute(
            text(
                "SELECT count(*) FROM sec_method_policy_versions "
                "WHERE id='analysis-method-applicability-v2'"
            )
        ).scalar_one() == 1
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("sec_method_policy_rules")
        }
        assert {
            "method_version_id",
            "required_risk_reviews_json",
            "required_adjustments_json",
            "unsupported_reason_code",
        } <= columns


@pytest.mark.parametrize("review_kind", ["classification", "high_sbc"])
def test_v2_upgrade_rejects_disjoint_legacy_roots_before_schema_mutation(
    isolated, review_kind: str
) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", PARENT)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        reviewer_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active,role) "
                "VALUES (:email,'x',true,'admin') RETURNING id"
            ),
            {"email": f"ft07-legacy-{review_kind}@example.com"},
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES (:ticker,'NYSE','US','FT07 Legacy Lineage',true) RETURNING id"
            ),
            {"ticker": f"LEG{review_kind[:4].upper()}"},
        ).scalar_one()
        if review_kind == "classification":
            connection.execute(
                text(
                    "INSERT INTO sec_economic_classification_reviews "
                    "(stock_id,economic_class,effective_from,effective_to,"
                    "reviewer_user_id,review_reason) VALUES "
                    "(:stock,'ordinary','2024-01-01','2024-01-31',:reviewer,'root one'),"
                    "(:stock,'ordinary','2024-03-01','2024-03-31',:reviewer,'root two')"
                ),
                {"stock": stock_id, "reviewer": reviewer_id},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO sec_economic_risk_attribute_reviews "
                    "(stock_id,risk_attribute,is_present,effective_from,effective_to,"
                    "reviewer_user_id,review_reason) VALUES "
                    "(:stock,'high_sbc',false,'2024-01-01','2024-01-31',:reviewer,'root one'),"
                    "(:stock,'high_sbc',false,'2024-03-01','2024-03-31',:reviewer,'root two')"
                ),
                {"stock": stock_id, "reviewer": reviewer_id},
            )

    refused = _alembic_result(url, "upgrade", HEAD)
    assert refused.returncode != 0
    assert "cannot adopt conflicting legacy method review lineages" in (
        refused.stdout + refused.stderr
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == PARENT
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("sec_method_policy_rules")
        }
        assert "method_version_id" not in columns
        constraints = {
            constraint["name"]
            for constraint in inspect(connection).get_check_constraints(
                "sec_economic_classification_reviews"
            )
        }
        assert "ck_sec_economic_classification_review_reason" not in constraints


def test_review_insert_serializes_against_concurrent_admin_deactivation(
    isolated,
) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        reviewer_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active,role) "
                "VALUES ('ft07-admin-lock@example.com','x',true,'admin') RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('ADMLOCK','NYSE','US','FT07 Admin Lock',true) RETURNING id"
            )
        ).scalar_one()

    first = engine.connect()
    second = engine.connect()
    first_tx = first.begin()
    second_tx = second.begin()
    try:
        first.execute(
            text(
                "INSERT INTO sec_economic_classification_reviews "
                "(stock_id,economic_class,effective_from,reviewer_user_id,review_reason) "
                "VALUES (:stock,'ordinary','2024-01-01',:reviewer,'lock reviewer')"
            ),
            {"stock": stock_id, "reviewer": reviewer_id},
        )
        second.execute(text("SET LOCAL lock_timeout='100ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            second.execute(
                text("UPDATE users SET is_active=false WHERE id=:reviewer"),
                {"reviewer": reviewer_id},
            )
        second_tx.rollback()
        first_tx.commit()
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        if second_tx.is_active:
            second_tx.rollback()
        first.close()
        second.close()

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT is_active FROM users WHERE id=:reviewer"),
            {"reviewer": reviewer_id},
        ).scalar_one() is True
        assert connection.execute(
            text(
                "SELECT count(*) FROM sec_economic_classification_reviews "
                "WHERE stock_id=:stock"
            ),
            {"stock": stock_id},
        ).scalar_one() == 1


def test_v2_clean_downgrade_upgrade_roundtrip_restores_final_review_guard(
    isolated,
) -> None:
    url, engine = isolated
    for args in (("upgrade", HEAD), ("downgrade", PARENT), ("upgrade", HEAD)):
        result = _alembic_result(url, *args)
        assert result.returncode == 0, result.stdout + result.stderr

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        trigger_functions = dict(
            connection.execute(
                text(
                    "SELECT trigger_name, action_statement "
                    "FROM information_schema.triggers WHERE trigger_name IN "
                    "('trg_sec_economic_classification_guard',"
                    " 'trg_sec_economic_risk_guard')"
                )
            ).all()
        )
        assert set(trigger_functions) == {
            "trg_sec_economic_classification_guard",
            "trg_sec_economic_risk_guard",
        }
        assert all(
            "guard_ft07_method_review_insert" in statement
            for statement in trigger_functions.values()
        )
