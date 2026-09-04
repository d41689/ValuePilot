from __future__ import annotations

import os
import json
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.facts import Formula, MetricFact
from app.services.formula_engine import FormulaEngine
from app.services.numeric_persistence import persist_numeric_38_12
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BASE = make_url(settings.SQLALCHEMY_DATABASE_URI).set(
    query={k: v for k, v in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items() if k != "options"}
).render_as_string(hide_password=False)
BACKEND = Path(__file__).resolve().parents[2]
PARENT = "20260831120000"
HEAD = "20260904160000"


def test_unresolved_guard_keeps_published_unit_strict() -> None:
    migration = (BACKEND / "alembic/versions/20260901160000-sec-unresolved-publication-guard.py").read_text()
    assert "NEW.status='published' AND NEW.unit=rule.target_unit" in migration
    assert "NEW.status<>'published' AND NEW.unit IS NULL AND NEW.currency IS NULL" in migration
    assert "cannot downgrade unresolved SEC publication evidence" in migration
    assert "NEW.fiscal_quarter_ordinal=2 AND right_decision.period_type='Q'" in migration
    assert "NEW.fiscal_quarter_ordinal=3 AND right_decision.period_type='YTD'" in migration
    assert "s.publication_run_id<>p.publication_run_id" in migration
    assert "issuer.stock_id<>pub.stock_id" in migration
    assert "n.mapping_rule_id=p.mapping_rule_id AND n.mapping_version_id=pub.mapping_version_id" in migration
    assert "p.reason_code IN ('unresolved_unit','unresolved_currency','unresolved_conflicting_candidates')" in migration
    assert "fact.value_json::jsonb->>'publication_run_id'" in migration
    assert "fact.value_json::jsonb->>'decision_id'" in migration
    assert "min_ordinal<>1 OR max_ordinal<>evidence_count OR distinct_ordinals<>evidence_count" in migration
    assert "jsonb_agg(raw_fact_id ORDER BY input_ordinal)" in migration
    assert "p.audit_json->'raw_fact_ids' IS DISTINCT FROM evidence_raw_ids" in migration
    assert "p.audit_json->'parse_run_ids' IS DISTINCT FROM evidence_parse_ids" in migration
    assert "jsonb_object_keys(p.locator_json" in migration
    assert "->>'normalization_id')::bigint IS DISTINCT FROM ui.normalization_id" in migration
    assert "jsonb_typeof(p.locator_json->key) IS DISTINCT FROM 'number'" in migration
    assert "~ '^[1-9][0-9]*$'" in migration
    assert "jsonb_typeof(p.locator_json->'normalization_id') NOT IN ('number','null')" in migration
    assert "jsonb_typeof(p.locator_json->'locator_json') IS DISTINCT FROM 'object'" in migration
    assert "jsonb_typeof(p.locator_json->'ordered_input_occurrences'->(ui.input_ordinal-1)->key) IS DISTINCT FROM 'number'" in migration


def test_publication_arithmetic_uses_source_decisions_not_caller_operands() -> None:
    foundation = (BACKEND / "alembic/versions/20260901120000-sec-publication-foundation.py").read_text()
    integrity = (BACKEND / "alembic/versions/20260901130000-sec-publication-integrity.py").read_text()
    assert "operand_value_numeric" not in foundation + integrity
    assert "source_publication_id" in foundation
    assert "source_decision.value_numeric" not in integrity  # arithmetic is a relational SQL join
    assert "sum(i.arithmetic_sign*s.value_numeric)" in integrity
    assert "current_ytd_minus_prior_ytd" in integrity
    assert "fiscal_year_minus_nine_month_ytd" in integrity
    assert "input_count<>2" in integrity and "input_count<>0" in integrity


def alembic(url: str, *args: str, succeeds: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["alembic", *args], cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True,
    )
    assert (result.returncode == 0) is succeeds, result.stdout + result.stderr
    return result


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


def test_publication_schema_empty_upgrade_downgrade_upgrade(isolated) -> None:
    url, engine = isolated
    alembic(url, "upgrade", "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
        tables = set(inspect(connection).get_table_names())
        assert {"sec_metric_mapping_versions", "sec_metric_publications", "sec_method_policy_versions"} <= tables
        columns = {c["name"]: c for c in inspect(connection).get_columns("metric_facts")}
        assert str(columns["value_numeric"]["type"]) == "NUMERIC(38, 12)"
        assert columns["user_id"]["nullable"] is True
        input_columns = {c["name"]: c for c in inspect(connection).get_columns("sec_metric_publication_inputs")}
        decision_columns = {c["name"]: c for c in inspect(connection).get_columns("sec_metric_publications")}
        assert decision_columns["mapping_rule_id"]["nullable"] is False
        assert input_columns["arithmetic_sign"]["nullable"] is False
        assert "operand_value_numeric" not in input_columns
        assert input_columns["raw_fact_id"]["nullable"] is True
        assert input_columns["source_publication_id"]["nullable"] is True
        input_checks = " ".join(c["sqltext"] for c in inspect(connection).get_check_constraints("sec_metric_publication_inputs"))
        assert "'direct'" in input_checks and "arithmetic_sign = 1" in input_checks
        assert "'right_operand'" in input_checks and "arithmetic_sign = '-1'" in input_checks
    alembic(url, "downgrade", PARENT)
    alembic(url, "upgrade", "head")


def test_mapping_and_method_authorities_stamp_and_fail_closed(isolated) -> None:
    url, engine = isolated
    alembic(url, "upgrade", "head")
    with engine.begin() as connection:
        user_id = connection.execute(text("INSERT INTO users (email,hashed_password,is_active,role) VALUES ('schema@example.com','x',true,'admin') RETURNING id")).scalar_one()
        stock_id = connection.execute(text("INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) VALUES ('SCH','US','US','Schema',true) RETURNING id")).scalar_one()
        other_stock_id = connection.execute(text("INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) VALUES ('SCHB','US','US','Schema B',true) RETURNING id")).scalar_one()
        assert connection.execute(text("SELECT count(*) FROM sec_metric_mapping_rules WHERE mapping_version_id='sec-us-gaap-v1'")).scalar_one() == 21
        assert connection.execute(text("SELECT count(*) FROM sec_metric_mapping_version_namespaces WHERE mapping_version_id='sec-us-gaap-v1'")).scalar_one() == 24
        assert connection.execute(text("SELECT count(*) FROM sec_method_policy_rules WHERE method_policy_version_id='sec-method-gate-v1' AND applicability='unsupported'")).scalar_one() == 24
        contract_known_at = datetime(2026, 8, 31, tzinfo=timezone.utc)
        assert connection.execute(text("SELECT known_at FROM sec_metric_mapping_versions WHERE id='sec-us-gaap-v1'")).scalar_one() == contract_known_at
        assert connection.execute(text("SELECT known_at FROM sec_method_policy_versions WHERE id='sec-method-gate-v1'")).scalar_one() == contract_known_at
        for table in ("sec_metric_mapping_versions", "sec_method_policy_versions"):
            assert connection.execute(text(f"SELECT count(*) FROM {table} WHERE known_at<=:cutoff"), {"cutoff": contract_known_at - timedelta(microseconds=1)}).scalar_one() == 0
            assert connection.execute(text(f"SELECT count(*) FROM {table} WHERE known_at<=:cutoff"), {"cutoff": contract_known_at}).scalar_one() == 1
        with pytest.raises(DBAPIError, match="approved mapping authorities are migration-owned"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO sec_metric_mapping_versions
                      (id,status,effective_from,known_at,spec_sha256,currency_registry_id,currency_serialization,currency_sha256,reviewer_user_id,review_reason)
                    VALUES ('forged','approved',now(),now(),:sha,'fake','[]',:sha,:user,'forged')
                """), {"sha": "a" * 64, "user": user_id})
        with pytest.raises(DBAPIError, match="approved method policies are migration-owned"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO sec_method_policy_versions
                      (id,status,effective_from,known_at,policy_sha256,reviewer_user_id,review_reason)
                    VALUES ('forged','approved',now(),now(),:sha,:user,'forged')
                """), {"sha": "b" * 64, "user": user_id})
        identity_id = connection.execute(text("""
            INSERT INTO sec_issuer_identities
              (stock_id,cik,status,review_reason,effective_from,known_at,reviewer_user_id)
            VALUES (:stock,'0000000999','reviewed','reviewed','2020-01-01','2026-08-30T00:00:00Z',:user)
            RETURNING id
        """), {"stock": stock_id, "user": user_id}).scalar_one()
        with pytest.raises(DBAPIError, match="publication run authority mismatch"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO sec_metric_publication_runs
                      (id,stock_id,issuer_identity_id,mapping_version_id,requested_cutoff,amendment_policy,source_set_sha256,status)
                    VALUES (:id,:other,:identity,'sec-us-gaap-v1',clock_timestamp()+interval '1 minute','latest_amendment',:sha,'pending')
                """), {"id": str(uuid.uuid4()), "other": other_stock_id, "identity": identity_id, "sha": "c" * 64})
        pit_identity_id = identity_id
        with pytest.raises(DBAPIError, match="publication run authority mismatch"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO sec_metric_publication_runs
                      (id,stock_id,issuer_identity_id,mapping_version_id,requested_cutoff,amendment_policy,source_set_sha256,status)
                    VALUES (:id,:stock,:identity,'sec-us-gaap-v1',:cutoff,'latest_amendment',:sha,'pending')
                """), {"id": str(uuid.uuid4()), "stock": stock_id, "identity": pit_identity_id, "cutoff": contract_known_at - timedelta(microseconds=1), "sha": "d" * 64})
        connection.execute(text("""
            INSERT INTO sec_metric_publication_runs
              (id,stock_id,issuer_identity_id,mapping_version_id,requested_cutoff,amendment_policy,source_set_sha256,status)
            VALUES (:id,:stock,:identity,'sec-us-gaap-v1',:cutoff,'latest_amendment',:sha,'pending')
        """), {"id": str(uuid.uuid4()), "stock": stock_id, "identity": pit_identity_id, "cutoff": contract_known_at, "sha": "e" * 64})
        classification_id = connection.execute(text("""
            INSERT INTO sec_economic_classification_reviews
              (stock_id,economic_class,effective_from,known_at,reviewer_user_id,review_reason,created_at,created_txid)
            VALUES (:stock,'ordinary','2020-01-01','2000-01-01',:user,'review','2000-01-01',1)
            RETURNING id
        """), {"stock": stock_id, "user": user_id}).scalar_one()
        connection.execute(text("""
            INSERT INTO sec_economic_risk_attribute_reviews
              (stock_id,risk_attribute,is_present,effective_from,known_at,reviewer_user_id,review_reason,created_at,created_txid)
            VALUES (:stock,'cyclical',true,'2020-01-01','2000-01-01',:user,'review','2000-01-01',1)
        """), {"stock": stock_id, "user": user_id})
        with pytest.raises(DBAPIError, match="exact terminal supersession"):
            with connection.begin_nested():
                connection.execute(text("""
                    INSERT INTO sec_economic_classification_reviews
                      (stock_id,economic_class,effective_from,reviewer_user_id,review_reason)
                    VALUES (:stock,'bank','2021-01-01',:user,'bad overlap')
                """), {"stock": stock_id, "user": user_id})
        connection.execute(text("""
            INSERT INTO sec_economic_classification_reviews
              (stock_id,economic_class,effective_from,reviewer_user_id,review_reason,supersedes_review_id)
            VALUES (:stock,'bank','2020-01-01',:user,'reviewed correction',:prior)
        """), {"stock": stock_id, "user": user_id, "prior": classification_id})
        connection.execute(text("""
            INSERT INTO sec_economic_risk_attribute_reviews
              (stock_id,risk_attribute,is_present,effective_from,reviewer_user_id,review_reason)
            VALUES (:stock,'commodity_exposed',true,'2020-01-01',:user,'orthogonal risk')
        """), {"stock": stock_id, "user": user_id})
        assert connection.execute(text("""
            SELECT economic_class FROM sec_economic_classification_reviews r
            WHERE stock_id=:stock AND effective_from<='2022-01-01'
              AND known_at<=(SELECT max(known_at) FROM sec_economic_classification_reviews WHERE stock_id=:stock)
            ORDER BY known_at DESC,id DESC LIMIT 1
        """), {"stock": stock_id}).scalar_one() == "bank"
        assert connection.execute(text("SELECT count(DISTINCT risk_attribute) FROM sec_economic_risk_attribute_reviews WHERE stock_id=:stock"), {"stock": stock_id}).scalar_one() == 2
        with pytest.raises(DBAPIError):
            with connection.begin_nested():
                connection.execute(text("UPDATE sec_metric_mapping_versions SET status='retired' WHERE id='sec-us-gaap-v1'"))


def test_precision_sensitive_metric_fact_blocks_downgrade(isolated) -> None:
    url, engine = isolated
    alembic(url, "upgrade", "head")
    with engine.begin() as connection:
        user_id = connection.execute(text("INSERT INTO users (email,hashed_password,is_active) VALUES ('precision@example.com','x',true) RETURNING id")).scalar_one()
        stock_id = connection.execute(text("INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) VALUES ('PRE','US','US','Precision',true) RETURNING id")).scalar_one()
        connection.execute(text("""
            INSERT INTO metric_facts
              (user_id,stock_id,metric_key,value_numeric,source_type,is_current,created_at,updated_at)
            VALUES (:user,:stock,'precision_probe',12345678901234567890123456.123456789012,'manual',false,now(),now())
        """), {"user": user_id, "stock": stock_id})
    result = alembic(url, "downgrade", PARENT, succeeds=False)
    assert "precision-sensitive metric facts" in result.stdout + result.stderr
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
        assert str(connection.execute(text("SELECT value_numeric FROM metric_facts WHERE metric_key='precision_probe'")).scalar_one()) == "12345678901234567890123456.123456789012"


def test_db_owned_numeric_normalization_exact_lexical_contract(isolated) -> None:
    url, engine = isolated
    alembic(url, "upgrade", "head")
    cases = [
        ({"raw_value": "1,234.50", "transformation_format": "ixt:num-dot-decimal", "scale": 0}, "1234.500000000000"),
        ({"raw_value": "1.234,50", "transformation_format": "ixt:num-comma-decimal", "scale": 0}, "1234.500000000000"),
        ({"raw_value": "-", "transformation_format": "ixt:zerodash", "scale": 4}, "0E-12"),
        ({"raw_value": "10", "transformation_format": None, "scale": 2, "sign": "-"}, "-1000.000000000000"),
        ({"raw_value": "99999999999999999999999999.999999999999", "transformation_format": None, "scale": 0}, "99999999999999999999999999.999999999999"),
    ]
    with engine.begin() as connection:
        for raw, expected in cases:
            raw["is_nil"] = False
            value = connection.execute(text("""
                SELECT compute_sec_numeric_v1(jsonb_populate_record(NULL::sec_raw_xbrl_facts, CAST(:raw AS jsonb)))
            """), {"raw": json.dumps(raw)}).scalar_one()
            assert str(value) == expected
        for raw in (
            {"raw_value": "123", "transformation_format": "ixt:numwordsen", "scale": 0, "is_nil": False},
            {"raw_value": "", "transformation_format": None, "scale": 0, "is_nil": False},
            {"raw_value": "1.2345678901234", "transformation_format": None, "scale": 0, "is_nil": False},
            {"raw_value": "1", "transformation_format": None, "scale": 0, "is_nil": True},
            {"raw_value": "1e3", "transformation_format": None, "scale": 0, "is_nil": False},
            {"raw_value": "9" * 300, "transformation_format": None, "scale": 0, "is_nil": False},
            {"raw_value": "9" * 65, "transformation_format": None, "scale": 0, "is_nil": False},
            {"raw_value": "99999999999999999999999999", "transformation_format": None, "scale": 1, "is_nil": False},
        ):
            with pytest.raises(DBAPIError, match="unsupported SEC numeric normalization|exceeds exact"):
                with connection.begin_nested():
                    connection.execute(text("SET LOCAL statement_timeout='500ms'"))
                    connection.execute(text("SELECT compute_sec_numeric_v1(jsonb_populate_record(NULL::sec_raw_xbrl_facts, CAST(:raw AS jsonb)))"), {"raw": json.dumps(raw)})


def test_metric_fact_orm_and_formula_keep_decimal_precision(isolated) -> None:
    url, engine = isolated
    alembic(url, "upgrade", "head")
    exact = Decimal("9007199254740993.000000000001")
    with engine.begin() as connection:
        user_id = connection.execute(text("INSERT INTO users (email,hashed_password,is_active) VALUES ('decimal@example.com','x',true) RETURNING id")).scalar_one()
        stock_id = connection.execute(text("INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) VALUES ('DEC','US','US','Decimal',true) RETURNING id")).scalar_one()
        fact_id = connection.execute(text("INSERT INTO metric_facts (user_id,stock_id,metric_key,value_numeric,source_type,is_current,created_at,updated_at) VALUES (:user,:stock,'decimal_probe',:value,'manual',true,now(),now()) RETURNING id"), {"user": user_id, "stock": stock_id, "value": exact}).scalar_one()
    with Session(engine) as session:
        loaded = session.get(MetricFact, fact_id)
        assert isinstance(loaded.value_numeric, Decimal)
        assert loaded.value_numeric == exact
        formula_row = Formula(user_id=user_id, name="Decimal Result", expression="decimal_probe + 0.000000000001", dependencies_json=["decimal_probe"])
        session.add(formula_row)
        session.commit()
        run = FormulaEngine(session).run_formula(formula_row.id, stock_id, user_id)
        assert run.result_value_json["value"] == "9007199254740993.000000000002"
        output = session.query(MetricFact).filter_by(stock_id=stock_id, metric_key="decimal_result").one()
        assert output.value_numeric == Decimal(run.result_value_json["value"])
        assert output.value_json["value"] == run.result_value_json["value"]
    formula = FormulaEngine(None)
    context = {"a": exact, "b": Decimal("0.000000000001")}
    assert formula.evaluate("a + b - b", context) == exact
    assert formula.evaluate("a * 2 / 2", context) == exact
    assert formula.evaluate("a > 9007199254740993.000000000000", context) is True
    assert format(formula.evaluate("a + b", context), "f") == "9007199254740993.000000000002"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.333333333333333333", "0.333333333333"),
        ("-0.333333333333333333", "-0.333333333333"),
        ("1.0000000000005", "1.000000000001"),
        ("-1.0000000000005", "-1.000000000001"),
        ("1.2", "1.200000000000"),
        ("99999999999999999999999999.999999999999", "99999999999999999999999999.999999999999"),
    ],
)
def test_numeric_38_12_persistence_boundary_matches_postgres(raw: str, expected: str, isolated) -> None:
    url, engine = isolated
    alembic(url, "upgrade", "head")
    persisted = persist_numeric_38_12(Decimal(raw))
    assert format(persisted, "f") == expected
    with engine.connect() as connection:
        db_value = connection.execute(text("SELECT CAST(:raw AS numeric(38,12))"), {"raw": raw}).scalar_one()
    assert persisted == db_value


@pytest.mark.parametrize("raw", ["100000000000000000000000000", "NaN", "Infinity", "-Infinity"])
def test_numeric_38_12_persistence_boundary_rejects_overflow_and_nonfinite(raw: str) -> None:
    with pytest.raises(ValueError):
        persist_numeric_38_12(Decimal(raw))
