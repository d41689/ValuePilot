from __future__ import annotations

import json
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
HEAD = "20260904310000"
PARENT = "20260904260000"


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


def _seed_numeric_manual(
    connection,
    *,
    value_json: str = '{"reason":"private reason","note":"private note","raw":"100"}',
) -> int:
    user_id = connection.scalar(
        text(
            "INSERT INTO users (email,hashed_password,is_active) "
            "VALUES ('r23-privacy@example.com','x',true) RETURNING id"
        )
    )
    stock_id = connection.scalar(
        text(
            "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
            "VALUES ('R23P','R23 Privacy','NYSE',true) RETURNING id"
        )
    )
    return connection.scalar(
        text(
            "INSERT INTO metric_facts "
            "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
            "period_type,is_current) VALUES "
            "(:user,:stock,'is.revenue',CAST(:value_json AS jsonb),100,"
            "'manual','FY',true) RETURNING id"
        ),
        {"user": user_id, "stock": stock_id, "value_json": value_json},
    )


def test_r23_migration_roundtrips_when_no_tombstones_exist(isolated) -> None:
    url, _ = isolated
    _alembic(url, "upgrade", HEAD)
    _alembic(url, "downgrade", PARENT)
    _alembic(url, "upgrade", HEAD)


def test_r23_candidate_indexes_cover_keyset_prefixes(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.connect() as connection:
        indexes = {
            row["indexname"]: row["indexdef"]
            for row in connection.execute(
                text(
                    "SELECT indexname,indexdef FROM pg_indexes "
                    "WHERE schemaname=current_schema() "
                    "AND tablename='metric_facts'"
                )
            ).mappings()
        }
        connection.execute(text("SET enable_seqscan=off"))
        plans = {
            "stock": "\n".join(
                row[0]
                for row in connection.execute(
                    text(
                        "EXPLAIN (COSTS OFF) SELECT id FROM metric_facts "
                        "WHERE stock_id=1 ORDER BY stock_id,id LIMIT 1001"
                    )
                )
            ),
            "metric": "\n".join(
                row[0]
                for row in connection.execute(
                    text(
                        "EXPLAIN (COSTS OFF) SELECT id FROM metric_facts "
                        "WHERE metric_key='is.revenue' "
                        "ORDER BY metric_key,id LIMIT 1001"
                    )
                )
            ),
            "document": "\n".join(
                row[0]
                for row in connection.execute(
                    text(
                        "EXPLAIN (COSTS OFF) SELECT id FROM metric_facts "
                        "WHERE source_document_id=1 "
                        "ORDER BY source_document_id,id LIMIT 1001"
                    )
                )
            ),
        }
    assert "(stock_id, id)" in indexes["ix_metric_facts_candidate_stock_id"]
    assert "(metric_key, id)" in indexes["ix_metric_facts_candidate_metric_id"]
    assert "(source_document_id, id)" in indexes[
        "ix_metric_facts_candidate_document_id"
    ]
    assert "ix_metric_facts_candidate_stock_id" in plans["stock"]
    assert "ix_metric_facts_candidate_metric_id" in plans["metric"]
    assert "ix_metric_facts_candidate_document_id" in plans["document"]


def test_numeric_manual_reason_has_exactly_one_legal_tombstone(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        fact_id = _seed_numeric_manual(connection)
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json="
                "'{\"reason\":\"[redacted]\",\"redaction_content_hash\":\""
                + ("a" * 64)
                + "\",\"note\":\"[redacted]\","
                "\"redaction_note_content_hash\":\""
                + ("c" * 64)
                + "\",\"raw\":\"100\"}' WHERE id=:fact"
            ),
            {"fact": fact_id},
        )
        # A byte-for-byte no-op remains safe for an idempotent erasure retry.
        connection.execute(
            text("UPDATE metric_facts SET value_json=value_json WHERE id=:fact"),
            {"fact": fact_id},
        )
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_json="
                        "'{\"reason\":\"[redacted]\","
                        "\"redaction_content_hash\":\""
                        + ("b" * 64)
                        + "\",\"note\":\"[redacted]\","
                        "\"redaction_note_content_hash\":\""
                        + ("c" * 64)
                        + "\",\"raw\":\"100\"}' WHERE id=:fact"
                    ),
                    {"fact": fact_id},
                )
        value, reason, note, raw, content_hash, note_hash = connection.execute(
            text(
                "SELECT value_numeric,value_json->>'reason',"
                "value_json->>'note',value_json->>'raw',"
                "value_json->>'redaction_content_hash',"
                "value_json->>'redaction_note_content_hash' FROM metric_facts "
                "WHERE id=:fact"
            ),
            {"fact": fact_id},
        ).one()
        assert value == 100
        assert reason == "[redacted]"
        assert note == "[redacted]"
        assert raw == "100"
        assert content_hash == "a" * 64
        assert note_hash == "c" * 64


def test_reason_and_note_tombstones_are_independently_one_way(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        fact_id = _seed_numeric_manual(connection)
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json="
                "'{\"reason\":\"[redacted]\",\"redaction_content_hash\":\""
                + ("a" * 64)
                + "\",\"note\":\"private note\",\"raw\":\"100\"}' "
                "WHERE id=:fact"
            ),
            {"fact": fact_id},
        )
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json="
                "'{\"reason\":\"[redacted]\",\"redaction_content_hash\":\""
                + ("a" * 64)
                + "\",\"note\":\"[redacted]\","
                "\"redaction_note_content_hash\":\""
                + ("b" * 64)
                + "\",\"raw\":\"100\"}' WHERE id=:fact"
            ),
            {"fact": fact_id},
        )
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_json="
                        "jsonb_set(value_json,'{redaction_note_content_hash}',"
                        "to_jsonb(CAST(:replacement AS text))) WHERE id=:fact"
                    ),
                    {"replacement": "c" * 64, "fact": fact_id},
                )


@pytest.mark.parametrize(
    ("field", "hash_field"),
    (
        ("reason", "redaction_content_hash"),
        ("note", "redaction_note_content_hash"),
    ),
)
def test_preexisting_field_hash_cannot_be_replaced_during_tombstone(
    isolated, field: str, hash_field: str
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        fact_id = _seed_numeric_manual(
            connection,
            value_json=json.dumps(
                {
                    "reason": "private reason",
                    "note": "private note",
                    "raw": "100",
                    hash_field: "a" * 64,
                }
            ),
        )
        # INSERT is the only boundary where a legacy/imported manual fact can
        # already carry a field hash.  Once present, it is immutable even when
        # the associated text has not yet been tombstoned.
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_json="
                        "jsonb_set(value_json, CAST(:path AS text[]), "
                        "'\"[redacted]\"'::jsonb, true) || "
                        "jsonb_build_object(:hash_field, :replacement_hash) "
                        "WHERE id=:fact"
                    ),
                    {
                        "path": [field],
                        "hash_field": hash_field,
                        "replacement_hash": "b" * 64,
                        "fact": fact_id,
                    },
                )


def test_r23_refuses_downgrade_that_would_weaken_tombstone(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        fact_id = _seed_numeric_manual(connection)
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json="
                "'{\"reason\":\"[redacted]\",\"redaction_content_hash\":\""
                + ("c" * 64)
                + "\",\"note\":\"[redacted]\","
                "\"redaction_note_content_hash\":\""
                + ("d" * 64)
                + "\",\"raw\":\"100\"}' WHERE id=:fact"
            ),
            {"fact": fact_id},
        )
    result = subprocess.run(
        ["alembic", "downgrade", PARENT],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "cannot weaken retained one-way privacy tombstones" in (
        result.stdout + result.stderr
    )
