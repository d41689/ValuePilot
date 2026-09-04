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
HEAD = "20260904160000"
V2_REVISION = "20260904150000"
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


def test_versioned_valuation_origin_refuses_downgrade_before_mutation(isolated) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('ft07-origin-down@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('ORIGDOWN','NYSE','US','Origin Downgrade',true) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,"
                "source_ref_id,is_current) VALUES "
                "(:user,:stock,'val.fair_value',100,CAST(:payload AS jsonb),"
                "'manual',900,true)"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps(
                    {
                        "valuation_origin": {
                            "version": "research-valuation-origin-v1",
                            "source": "manual",
                            "research_revision_id": 900,
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
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname='trg_metric_facts_ft07_authority_update' "
                "AND tgrelid='metric_facts'::regclass AND NOT tgisinternal"
            )
        ).scalar_one() == 1


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
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname='trg_metric_facts_ft07_authority_update' "
                "AND tgrelid='metric_facts'::regclass AND NOT tgisinternal"
            )
        ).scalar_one() == 1

    downgraded = _alembic_result(url, "downgrade", PARENT)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname='trg_metric_facts_ft07_authority_update' "
                "AND tgrelid='metric_facts'::regclass AND NOT tgisinternal"
            )
        ).scalar_one() == 0

    restored = _alembic_result(url, "upgrade", HEAD)
    assert restored.returncode == 0, restored.stdout + restored.stderr

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
        assert connection.execute(
            text(
                "SELECT count(*) FROM pg_trigger "
                "WHERE tgname='trg_metric_facts_ft07_authority_update' "
                "AND tgrelid='metric_facts'::regclass AND NOT tgisinternal"
            )
        ).scalar_one() == 1


def test_piotroski_guard_clean_downgrade_upgrade_restores_exact_revision(
    isolated,
) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    downgraded = _alembic_result(url, "downgrade", V2_REVISION)
    assert downgraded.returncode == 0, downgraded.stdout + downgraded.stderr
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == V2_REVISION
        definition = connection.execute(
            text(
                "SELECT pg_get_functiondef('guard_ft07_metric_fact_authority_update()'::regprocedure)"
            )
        ).scalar_one()
        assert "governs_piotroski" not in definition

    restored = _alembic_result(url, "upgrade", HEAD)
    assert restored.returncode == 0, restored.stdout + restored.stderr
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        definition = connection.execute(
            text(
                "SELECT pg_get_functiondef('guard_ft07_metric_fact_authority_update()'::regprocedure)"
            )
        ).scalar_one()
        assert "governs_piotroski" in definition


def test_metric_fact_authority_cannot_be_injected_or_rewritten(isolated) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('ft07-fact-guard@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        other_user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('ft07-fact-guard-other@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('FACTGUARD','NYSE','US','FT07 Fact Guard',true) RETURNING id"
            )
        ).scalar_one()
        other_stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('FACTGUARD2','NYSE','US','FT07 Other Fact Guard',true) "
                "RETURNING id"
            )
        ).scalar_one()
        legacy_oe_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,is_current) "
                "VALUES (:user,:stock,'owners_earnings_per_share',5,'{}'::jsonb,"
                "'calculated',true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        governed_oe_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,is_current) "
                "VALUES (:user,:stock,'owners_earnings_per_share_normalized',6,"
                "CAST(:payload AS jsonb),'calculated',true) RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps({"analysis_method": {"status": "approved"}}),
            },
        ).scalar_one()
        legacy_piotroski_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,is_current) "
                "VALUES (:user,:stock,'score.piotroski.total',8,"
                "'{\"inputs\":[]}'::jsonb,'calculated',true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        governed_piotroski_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,is_current) "
                "VALUES (:user,:stock,'score.piotroski.roa_positive',1,"
                "CAST(:payload AS jsonb),'calculated',true) RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps(
                    {
                        "analysis_method": {"method_key": "roic"},
                        "inputs": [],
                    }
                ),
            },
        ).scalar_one()
        dcf_fact_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,period_type,"
                "period_end_date,source_type,source_ref_id,is_current) VALUES "
                "(:user,:stock,'val.fair_value',100,CAST(:payload AS jsonb),"
                "'AS_OF','2025-01-01','manual',501,true) RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps(
                    {
                        "valuation_origin": {
                            "version": "research-valuation-origin-v1",
                            "source": "dcf",
                            "research_revision_id": 501,
                        }
                    }
                ),
            },
        ).scalar_one()
        legacy_manual_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,period_type,"
                "period_end_date,source_type,source_ref_id,is_current) VALUES "
                "(:user,:stock,'val.fair_value',75,NULL,'AS_OF','2024-01-01',"
                "'manual',NULL,true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        unavailable_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,period_type,"
                "period_end_date,source_type,source_ref_id,is_current) VALUES "
                "(:user,:stock,'val.fair_value',NULL,CAST(:payload AS jsonb),"
                "'AS_OF','2023-01-01','manual',503,true) RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "payload": json.dumps(
                    {
                        "status": "unavailable",
                        "reason": "authored private reason",
                        "valuation_origin": {
                            "version": "research-valuation-origin-v1",
                            "source": "manual",
                            "research_revision_id": 503,
                        },
                    }
                ),
            },
        ).scalar_one()

    rejected_updates = [
        (
            "UPDATE metric_facts SET value_json=jsonb_set(value_json, "
            "'{analysis_method}', '{\"status\":\"approved\"}'::jsonb) WHERE id=:id",
            legacy_oe_id,
        ),
        ("UPDATE metric_facts SET value_numeric=998 WHERE id=:id", legacy_oe_id),
        ("UPDATE metric_facts SET value_numeric=999 WHERE id=:id", governed_oe_id),
        (
            "UPDATE metric_facts SET metric_key='custom.oe', source_type='manual', "
            "value_numeric=999 WHERE id=:id",
            governed_oe_id,
        ),
        (
            "UPDATE metric_facts SET value_json=jsonb_set(value_json, "
            "'{analysis_method}', '{\"method_key\":\"roic\"}'::jsonb) WHERE id=:id",
            legacy_piotroski_id,
        ),
        (
            "UPDATE metric_facts SET value_numeric=7 WHERE id=:id",
            legacy_piotroski_id,
        ),
        (
            "UPDATE metric_facts SET value_json='{}'::jsonb WHERE id=:id",
            governed_piotroski_id,
        ),
        (
            "UPDATE metric_facts SET metric_key='custom.piotroski', "
            "source_type='manual', value_numeric=7 WHERE id=:id",
            governed_piotroski_id,
        ),
        (
            "UPDATE metric_facts SET value_json=jsonb_set(value_json, "
            "'{valuation_origin,source}', '\"manual\"'::jsonb) WHERE id=:id",
            dcf_fact_id,
        ),
        ("UPDATE metric_facts SET value_numeric=101 WHERE id=:id", dcf_fact_id),
        ("UPDATE metric_facts SET source_ref_id=502 WHERE id=:id", dcf_fact_id),
        (
            "UPDATE metric_facts SET user_id=:other_user WHERE id=:id",
            dcf_fact_id,
        ),
        (
            "UPDATE metric_facts SET stock_id=:other_stock WHERE id=:id",
            dcf_fact_id,
        ),
        (
            "UPDATE metric_facts SET metric_key='custom.value', source_type='calculated', "
            "value_numeric=999 WHERE id=:id",
            dcf_fact_id,
        ),
        (
            "UPDATE metric_facts SET value_json=CAST(:payload AS jsonb) WHERE id=:id",
            legacy_manual_id,
        ),
    ]
    for statement, fact_id in rejected_updates:
        parameters = {"id": fact_id}
        if ":other_user" in statement:
            parameters["other_user"] = other_user_id
        if ":other_stock" in statement:
            parameters["other_stock"] = other_stock_id
        if ":payload" in statement:
            parameters["payload"] = json.dumps(
                {
                    "valuation_origin": {
                        "version": "research-valuation-origin-v1",
                        "source": "manual",
                        "research_revision_id": 700,
                    }
                }
            )
        with engine.begin() as connection:
            with pytest.raises(DBAPIError, match="FT-07 metric fact authority"):
                connection.execute(text(statement), parameters)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE metric_facts SET is_current=false "
                "WHERE id IN (:oe,:dcf,:piotroski)"
            ),
            {
                "oe": governed_oe_id,
                "dcf": dcf_fact_id,
                "piotroski": governed_piotroski_id,
            },
        )
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json=CAST(:payload AS jsonb) "
                "WHERE id=:id"
            ),
            {
                "id": unavailable_id,
                "payload": json.dumps(
                    {
                        "status": "unavailable",
                        "reason": "[redacted]",
                        "redaction_content_hash": "a" * 64,
                        "valuation_origin": {
                            "version": "research-valuation-origin-v1",
                            "source": "manual",
                            "research_revision_id": 503,
                        },
                    }
                ),
            },
        )
    with engine.connect() as connection:
        facts = connection.execute(
            text(
                "SELECT id,metric_key,value_numeric,value_json,source_type,source_ref_id,"
                "is_current FROM metric_facts WHERE id IN "
                "(:legacy_oe,:oe,:legacy_piotroski,:piotroski,:dcf,:legacy,:unavailable)"
            ),
            {
                "legacy_oe": legacy_oe_id,
                "oe": governed_oe_id,
                "legacy_piotroski": legacy_piotroski_id,
                "piotroski": governed_piotroski_id,
                "dcf": dcf_fact_id,
                "legacy": legacy_manual_id,
                "unavailable": unavailable_id,
            },
        ).mappings()
        by_id = {row["id"]: row for row in facts}
        assert "analysis_method" not in by_id[legacy_oe_id]["value_json"]
        assert by_id[governed_oe_id]["value_numeric"] == 6
        assert by_id[governed_oe_id]["metric_key"] == (
            "owners_earnings_per_share_normalized"
        )
        assert "analysis_method" not in by_id[legacy_piotroski_id]["value_json"]
        assert by_id[legacy_piotroski_id]["value_numeric"] == 8
        assert by_id[governed_piotroski_id]["value_json"]["analysis_method"] == {
            "method_key": "roic"
        }
        assert by_id[dcf_fact_id]["value_json"]["valuation_origin"]["source"] == "dcf"
        assert by_id[dcf_fact_id]["source_ref_id"] == 501
        assert by_id[legacy_manual_id]["value_json"] is None
        assert by_id[unavailable_id]["value_json"]["reason"] == "[redacted]"
        assert by_id[unavailable_id]["value_json"]["valuation_origin"]["source"] == (
            "manual"
        )
        assert by_id[governed_oe_id]["is_current"] is False
        assert by_id[governed_piotroski_id]["is_current"] is False
        assert by_id[dcf_fact_id]["is_current"] is False


def test_piotroski_authority_refuses_downgrade_before_guard_mutation(
    isolated,
) -> None:
    url, engine = isolated
    upgraded = _alembic_result(url, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('ft07-piot-down@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('PIOTDOWN','NYSE','US','Piot Downgrade',true) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,is_current) "
                "VALUES (:user,:stock,'score.piotroski.total',8,"
                "'{\"inputs\":[]}'::jsonb,'calculated',true)"
            ),
            {"user": user_id, "stock": stock_id},
        )

    refused = _alembic_result(url, "downgrade", V2_REVISION)
    assert refused.returncode != 0
    assert "cannot downgrade retained Piotroski method authority" in (
        refused.stdout + refused.stderr
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        definition = connection.execute(
            text(
                "SELECT pg_get_functiondef('guard_ft07_metric_fact_authority_update()'::regprocedure)"
            )
        ).scalar_one()
        assert "governs_piotroski" in definition
