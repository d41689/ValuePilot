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
HEAD = "20260904320000"
PARENT = "20260904310000"


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


def _seed_manual(connection, *, email: str, value_json: str) -> int:
    user_id = connection.scalar(
        text(
            "INSERT INTO users (email,hashed_password,is_active) "
            "VALUES (:email,'x',true) RETURNING id"
        ),
        {"email": email},
    )
    stock_id = connection.scalar(
        text(
            "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
            "VALUES (:ticker,'R24 Privacy','NYSE',true) RETURNING id"
        ),
        {"ticker": email[:5].upper()},
    )
    return int(
        connection.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                "period_type,is_current) VALUES "
                "(:user,:stock,'is.revenue',CAST(:value_json AS jsonb),100,"
                "'manual','FY',true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id, "value_json": value_json},
        )
    )


def test_r24_empty_schema_roundtrips(isolated) -> None:
    url, _ = isolated
    _alembic(url, "upgrade", HEAD)


def test_r24_backfills_retained_same_date_divergence_as_current_ambiguity(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PARENT)
    with engine.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) VALUES "
                "('r24-backfill@example.com','x',true) RETURNING id"
            )
        )
        stock_id = connection.scalar(
            text(
                "INSERT INTO stocks (ticker,company_name,exchange,is_active) VALUES "
                "('R24BF','R24 Backfill','NYSE',true) RETURNING id"
            )
        )
        policy_id = connection.scalar(
            text(
                "SELECT id FROM value_line_mapping_policies "
                "WHERE status='approved' ORDER BY effective_from DESC LIMIT 1"
            )
        )
        fact_ids: list[int] = []
        for ordinal, (value, current) in enumerate(((100, False), (120, True)), 1):
            document_id = connection.scalar(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id,stock_id,file_name,file_storage_key,source,parse_status,"
                    "identity_needs_review,report_date) VALUES "
                    "(:user,:stock,:name,:name,'value_line','parsed',false,"
                    "'2026-01-09') RETURNING id"
                ),
                {"user": user_id, "stock": stock_id, "name": f"r24-{ordinal}.pdf"},
            )
            run_id = connection.scalar(
                text(
                    "INSERT INTO value_line_parse_runs "
                    "(user_id,document_id,parser_version,source_mapping_version,"
                    "status,created_txid) VALUES "
                    "(:user,:document,'value-line-v1',:policy,'running',0) "
                    "RETURNING id"
                ),
                {"user": user_id, "document": document_id, "policy": policy_id},
            )
            fact_ids.append(
                int(
                    connection.scalar(
                        text(
                            "INSERT INTO metric_facts "
                            "(user_id,stock_id,metric_key,value_json,value_numeric,"
                            "unit,currency,source_type,source_document_id,period_type,"
                            "period_end_date,is_current,value_line_parse_run_id) VALUES "
                            "(:user,:stock,'is.net_income',"
                            "'{\"fact_nature\":\"actual\"}',:value,'currency','USD',"
                            "'parsed',:document,'FY','2025-12-31',:current,:run) "
                            "RETURNING id"
                        ),
                        {
                            "user": user_id,
                            "stock": stock_id,
                            "value": value,
                            "document": document_id,
                            "current": current,
                            "run": run_id,
                        },
                    )
                )
            )
            connection.execute(
                text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:run"),
                {"run": run_id},
            )

    _alembic(url, "upgrade", HEAD)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id,is_current FROM metric_facts WHERE id = ANY(:facts) "
                "ORDER BY id"
            ),
            {"facts": fact_ids},
        ).all()
        assert [(row.id, row.is_current) for row in rows] == [
            (fact_ids[0], True),
            (fact_ids[1], True),
        ]
    _alembic(url, "downgrade", PARENT)
    _alembic(url, "upgrade", HEAD)


def test_prehashed_plaintext_has_only_verified_erasure_transition(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    plaintext = "prehashed private reason"
    retained_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    with engine.begin() as connection:
        fact_id = _seed_manual(
            connection,
            email="r24-verified@example.com",
            value_json=(
                '{"reason":"' + plaintext + '","redaction_content_hash":"'
                + retained_hash
                + '","raw":"100"}'
            ),
        )
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_json=jsonb_set("
                        "value_json,'{reason}','\"[redacted]\"'::jsonb,true) "
                        "WHERE id=:fact"
                    ),
                    {"fact": fact_id},
                )
        connection.execute(
            text("SELECT set_config('valuepilot.account_erasure','on',true)")
        )
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json=jsonb_set("
                "value_json,'{reason}','\"[redacted]\"'::jsonb,true) "
                "WHERE id=:fact"
            ),
            {"fact": fact_id},
        )
        reason, actual_hash, anomaly_count = connection.execute(
            text(
                "SELECT value_json->>'reason',value_json->>'redaction_content_hash',"
                "(SELECT count(*) FROM manual_rationale_erasure_anomalies "
                " WHERE fact_id=:fact) FROM metric_facts WHERE id=:fact"
            ),
            {"fact": fact_id},
        ).one()
        assert reason == "[redacted]"
        assert actual_hash == retained_hash
        assert anomaly_count == 0

        for mutation in (
            "value_json=jsonb_set(value_json,'{reason}','\"restored\"'::jsonb,true)",
            "value_json=jsonb_set(value_json,'{redaction_content_hash}',"
            "'\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"'::jsonb,true)",
            "value_numeric=101",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                with connection.begin_nested():
                    connection.execute(
                        text(f"UPDATE metric_facts SET {mutation} WHERE id=:fact"),
                        {"fact": fact_id},
                    )


def test_mismatched_prehashed_plaintext_is_redacted_with_typed_anomaly(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        fact_id = _seed_manual(
            connection,
            email="r24-mismatch@example.com",
            value_json=(
                '{"note":"private note","redaction_note_content_hash":"'
                + ("f" * 64)
                + '","raw":"100"}'
            ),
        )
        connection.execute(
            text("SELECT set_config('valuepilot.account_erasure','on',true)")
        )
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json=jsonb_set("
                "value_json,'{note}','\"[redacted]\"'::jsonb,true) "
                "WHERE id=:fact"
            ),
            {"fact": fact_id},
        )
        note, actual_hash = connection.execute(
            text(
                "SELECT value_json->>'note',value_json->>'redaction_note_content_hash' "
                "FROM metric_facts WHERE id=:fact"
            ),
            {"fact": fact_id},
        ).one()
        anomaly = connection.execute(
            text(
                "SELECT field_name,reason_code,observed_hash "
                "FROM manual_rationale_erasure_anomalies WHERE fact_id=:fact"
            ),
            {"fact": fact_id},
        ).one()
        assert note == "[redacted]"
        assert actual_hash == "f" * 64
        assert anomaly == (
            "note",
            "retained_hash_mismatch",
            "f" * 64,
        )

        with pytest.raises(DBAPIError, match="database-owned append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO manual_rationale_erasure_anomalies "
                        "(fact_id,user_id,field_name,reason_code,observed_hash,"
                        "created_at,created_txid) VALUES "
                        "(:fact,NULL,'reason','retained_hash_mismatch',NULL,now(),1)"
                    ),
                    {"fact": fact_id},
                )
