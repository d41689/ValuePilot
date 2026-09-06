from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.services.privacy_erasure import privacy_erasure_db_capability
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
HEAD = "20260904330000"
PARENT = "20260904320000"


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        ["alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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


def _seed_user_and_valuation(connection, *, suffix: str) -> tuple[int, int]:
    user_id = int(
        connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES (:email,'x',true) RETURNING id"
            ),
            {"email": f"r25-{suffix}@example.com"},
        )
    )
    stock_id = int(
        connection.scalar(
            text(
                "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
                "VALUES (:ticker,'R25 Privacy','NYSE',true) RETURNING id"
            ),
            {"ticker": f"R25{suffix.upper()}"},
        )
    )
    fact_id = int(
        connection.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,value_text,"
                "unit,currency,source_type,source_ref_id,period_type,period_end_date,"
                "is_current) VALUES (:user,:stock,'val.fair_value',"
                "CAST(:value_json AS jsonb),100,'retained','USD','USD','manual',"
                "77,'AS_OF','2026-01-31',true) RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "value_json": (
                    '{"status":"available","reason":"private reason",'
                    '"note":"private note","raw":"100",'
                    '"valuation_origin":{"version":"research-valuation-origin-v1",'
                    '"source":"manual","research_revision_id":77}}'
                ),
            },
        )
    )
    return user_id, fact_id


def _seed_calculated_fact(connection, *, user_id: int, suffix: str) -> int:
    stock_id = int(
        connection.scalar(
            text(
                "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
                "VALUES (:ticker,'R25 Calculated','NYSE',true) RETURNING id"
            ),
            {"ticker": f"R25C{suffix.upper()}"},
        )
    )
    return int(
        connection.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,unit,"
                "source_type,period_type,period_end_date,is_current) VALUES "
                "(:user,:stock,'calc.r25_other',CAST(:value_json AS jsonb),1,"
                "'count','calculated','FY','2025-12-31',true) RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "value_json": '{"reason":"calculated rationale"}',
            },
        )
    )


def test_r25_empty_schema_roundtrips(isolated) -> None:
    url, _ = isolated
    _alembic(url, "upgrade", HEAD)
    _alembic(url, "downgrade", PARENT)
    _alembic(url, "upgrade", HEAD)


def test_r25_rejects_guc_direct_dml_and_cross_tenant_capability_reuse(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        owner_id, owner_fact_id = _seed_user_and_valuation(connection, suffix="owner")
        other_id, other_fact_id = _seed_user_and_valuation(connection, suffix="other")
        calculated_fact_id = _seed_calculated_fact(
            connection,
            user_id=owner_id,
            suffix="owner",
        )
        reason_hash = hashlib.sha256(b"private reason").hexdigest()

        connection.execute(
            text("SELECT set_config('valuepilot.account_erasure','on',true)")
        )
        update_reason = text(
            "UPDATE metric_facts SET value_json="
            "jsonb_set(jsonb_set(value_json,'{reason}',"
            "'\"[redacted]\"'::jsonb,true),'{redaction_content_hash}',"
            "to_jsonb(CAST(:hash AS text)),true) WHERE id=:fact"
        )
        with pytest.raises(DBAPIError, match="immutable|authorized"):
            with connection.begin_nested():
                connection.execute(
                    update_reason,
                    {"hash": reason_hash, "fact": owner_fact_id},
                )

        with pytest.raises(DBAPIError, match="database-owned append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO privacy_erasure_operations "
                        "(user_id,operation_kind,created_at,created_txid) "
                        "VALUES (:user,'account_erasure',now(),txid_current())"
                    ),
                    {"user": owner_id},
                )

        with pytest.raises(DBAPIError, match="capability rejected"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "SELECT begin_privacy_erasure_operation("
                        ":user,'account_erasure','db-credential-only')"
                    ),
                    {"user": other_id},
                )

        operation_id = int(
            connection.scalar(
                text(
                    "SELECT begin_privacy_erasure_operation("
                    ":user,'account_erasure',:capability)"
                ),
                {
                    "user": owner_id,
                    "capability": privacy_erasure_db_capability(),
                },
            )
        )
        operation = connection.execute(
            text(
                "SELECT user_id,operation_kind,created_txid FROM "
                "privacy_erasure_operations WHERE id=:id"
            ),
            {"id": operation_id},
        ).one()
        assert operation == (
            owner_id,
            "account_erasure",
            connection.scalar(text("SELECT txid_current()")),
        )

        # Even possession of the process capability cannot retarget an already
        # authorized transaction to a different tenant or purpose.
        with pytest.raises(DBAPIError, match="cannot change target or purpose"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "SELECT begin_privacy_erasure_operation("
                        ":user,'account_erasure',:capability)"
                    ),
                    {
                        "user": other_id,
                        "capability": privacy_erasure_db_capability(),
                    },
                )

        with pytest.raises(DBAPIError, match="immutable|authorized"):
            with connection.begin_nested():
                connection.execute(
                    update_reason,
                    {"hash": reason_hash, "fact": other_fact_id},
                )

        with pytest.raises(DBAPIError, match="database-owned append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE privacy_erasure_operations SET user_id=:other "
                        "WHERE id=:id"
                    ),
                    {"other": other_id, "id": operation_id},
                )

        # Privacy authority never weakens non-manual calculated/derived facts.
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    update_reason,
                    {"hash": reason_hash, "fact": calculated_fact_id},
                )

        connection.execute(
            update_reason,
            {"hash": reason_hash, "fact": owner_fact_id},
        )
        row = connection.execute(
            text(
                "SELECT value_numeric,value_text,source_ref_id,value_json->>'reason',"
                "value_json->>'raw',value_json->'valuation_origin' AS valuation_origin "
                "FROM metric_facts WHERE id=:fact"
            ),
            {"fact": owner_fact_id},
        ).one()
        assert row[:5] == (100, "retained", 77, "[redacted]", "100")
        assert row.valuation_origin["research_revision_id"] == 77

        for mutation in (
            "value_json=jsonb_set(value_json,'{reason}','\"restored\"'::jsonb,true)",
            "value_json=jsonb_set(value_json,'{redaction_content_hash}',"
            "'\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"'::jsonb,true)",
            "value_numeric=101",
            "source_ref_id=78",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                with connection.begin_nested():
                    connection.execute(
                        text(f"UPDATE metric_facts SET {mutation} WHERE id=:fact"),
                        {"fact": owner_fact_id},
                    )

        live_guards = connection.execute(
            text(
                "SELECT pg_get_functiondef(p.oid),p.prosecdef,p.proconfig "
                "FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND p.proname=ANY(:names)"
            ),
            {
                "names": [
                    "guard_ft07_metric_fact_authority_update",
                    "guard_governed_metric_fact_immutability",
                    "guard_prehashed_manual_rationale_immutability",
                    "guard_manual_rationale_erasure_anomaly",
                    "reject_research_append_only_mutation",
                ]
            },
        ).all()
        assert len(live_guards) == 5
        assert all(
            "valuepilot.account_erasure" not in guard.pg_get_functiondef
            for guard in live_guards
        )
        assert all(guard.prosecdef is True for guard in live_guards)
        assert all(
            any(setting.startswith("search_path=pg_catalog,") for setting in guard.proconfig)
            for guard in live_guards
        )
