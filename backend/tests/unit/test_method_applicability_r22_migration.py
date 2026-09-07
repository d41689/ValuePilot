from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.canonical_financials import reviewed_method_gate
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.method_applicability import review_company_classification
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
HEAD = "20260904260000"
PARENT = "20260904250000"


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


def _seed(connection, *, source_type: str = "manual") -> tuple[int, int, int]:
    user_id = connection.scalar(
        text(
            "INSERT INTO users (email,hashed_password,is_active) "
            "VALUES (:email,'x',true) RETURNING id"
        ),
        {"email": f"r22-{source_type}@example.com"},
    )
    stock_id = connection.scalar(
        text(
            "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
            "VALUES (:ticker,'R22 Corp','NYSE',true) RETURNING id"
        ),
        {"ticker": f"R22{source_type[:1].upper()}"},
    )
    fact_id = connection.scalar(
        text(
            "INSERT INTO metric_facts "
            "(user_id,stock_id,metric_key,value_json,value_numeric,value_text,"
            "unit,currency,period_type,source_type,is_current) VALUES "
            "(:user,:stock,'is.revenue','{}',100,'100','USD','USD','FY',"
            ":source,true) RETURNING id"
        ),
        {"user": user_id, "stock": stock_id, "source": source_type},
    )
    return user_id, stock_id, fact_id


def test_r22_schema_roundtrips_when_empty(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    assert "ix_metric_fact_currentness_scope_known" in {
        row["name"]
        for row in inspect(engine).get_indexes("metric_fact_currentness_revisions")
    }
    _alembic(url, "downgrade", PARENT)
    _alembic(url, "upgrade", HEAD)


def test_method_gate_excludes_review_committed_after_evaluation_snapshot(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as setup:
        reviewer_id = setup.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active,role) VALUES "
                "('r22-late-commit@example.com','x',true,'admin') RETURNING id"
            )
        )
        stock_id = setup.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,company_name,is_active) VALUES "
                "('R22LATE','NYSE','R22 Late Co',true) RETURNING id"
            )
        )
    writer = Session(engine)
    reader = Session(engine)
    later_reader = Session(engine)
    try:
        review_company_classification(
            writer,
            reviewer_user_id=reviewer_id,
            stock_id=stock_id,
            economic_class="ordinary",
            effective_from=date(2020, 1, 1),
            review_reason="Concurrent classification awaiting commit.",
        )
        snapshot = database_evaluation_snapshot(reader)
        writer.commit()

        at_snapshot = reviewed_method_gate(
            reader,
            stock_id=stock_id,
            method_key="owner_earnings",
            effective_as_of=date(2026, 9, 4),
            knowledge_at=snapshot.cutoff,
        )
        after_commit = reviewed_method_gate(
            later_reader,
            stock_id=stock_id,
            method_key="owner_earnings",
            effective_as_of=date(2026, 9, 4),
        )

        assert at_snapshot.reason_code == "classification_unreviewed"
        assert after_commit.reason_code == "risk_review_incomplete"
    finally:
        writer.close()
        reader.close()
        later_reader.close()


def test_currentness_scope_indexes_cover_stock_metric_and_document_plans(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL enable_seqscan=off"))
        stock_plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT fact_id,known_at,id FROM "
                    "metric_fact_currentness_revisions "
                    "WHERE stock_id=1 AND metric_key='is.revenue' "
                    "ORDER BY fact_id,known_at DESC,id DESC"
                )
            )
        )
        metric_plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT fact_id,known_at,id FROM "
                    "metric_fact_currentness_revisions "
                    "WHERE metric_key='is.revenue' "
                    "ORDER BY fact_id,known_at DESC,id DESC"
                )
            )
        )
        document_plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT fact_id,known_at,id FROM "
                    "metric_fact_currentness_revisions "
                    "WHERE source_document_id=1 "
                    "ORDER BY fact_id,known_at DESC,id DESC"
                )
            )
        )
    assert "ix_metric_fact_currentness_scope_known" in stock_plan
    assert "ix_metric_fact_currentness_metric_known" in metric_plan
    assert "ix_metric_fact_currentness_document_known" in document_plan


@pytest.mark.parametrize("source_type", ["manual", "calculated", "derived"])
def test_governed_fact_content_is_immutable_but_demotion_is_append_only(
    isolated, source_type: str
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        _, _, fact_id = _seed(connection, source_type=source_type)
        for assignment in (
            "value_numeric=999",
            "value_text='forged'",
            "value_json=jsonb_build_object('forged',true)",
            "unit='shares'",
            "is_current=false, value_numeric=999",
        ):
            with pytest.raises(DBAPIError, match="content and provenance are immutable"):
                with connection.begin_nested():
                    connection.execute(
                        text(f"UPDATE metric_facts SET {assignment} WHERE id=:fact"),
                        {"fact": fact_id},
                    )
        connection.execute(
            text("UPDATE metric_facts SET is_current=false WHERE id=:fact"),
            {"fact": fact_id},
        )
        with pytest.raises(DBAPIError, match="cannot be reactivated"):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE metric_facts SET is_current=true WHERE id=:fact"),
                    {"fact": fact_id},
                )
        with pytest.raises(DBAPIError, match="cannot be deleted directly"):
            with connection.begin_nested():
                connection.execute(
                    text("DELETE FROM metric_facts WHERE id=:fact"),
                    {"fact": fact_id},
                )


def test_only_manual_fact_supports_ft06_document_relocation(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id, stock_id, manual_id = _seed(connection, source_type="manual")
        _, _, calculated_id = _seed(connection, source_type="calculated")
        _, _, derived_id = _seed(connection, source_type="derived")
        document_id = connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,stock_id,file_name,file_storage_key,source,parse_status,"
                "identity_needs_review) VALUES "
                "(:user,:stock,'r22-relocation.pdf','r22-relocation.pdf',"
                "'value_line','pending',false) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )
        connection.execute(
            text(
                "UPDATE metric_facts SET source_document_id=:document WHERE id=:fact"
            ),
            {"document": document_id, "fact": manual_id},
        )
        for fact_id in (calculated_id, derived_id):
            with pytest.raises(DBAPIError, match="content and provenance are immutable"):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE metric_facts SET source_document_id=:document "
                            "WHERE id=:fact"
                        ),
                        {"document": document_id, "fact": fact_id},
                    )


def test_manual_privacy_tombstone_is_narrow_and_hash_is_validated(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id, stock_id, _ = _seed(connection)
        fact_id = connection.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                "period_type,is_current) VALUES (:user,:stock,'val.fair_value',"
                "'{\"status\":\"unavailable\",\"reason\":\"private\"}',NULL,"
                "'manual','AS_OF',true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_json="
                        "'{\"status\":\"unavailable\",\"reason\":\"[redacted]\","
                        "\"redaction_content_hash\":\"invalid\"}' WHERE id=:fact"
                    ),
                    {"fact": fact_id},
                )
        connection.execute(
            text(
                "UPDATE metric_facts SET value_json="
                "'{\"status\":\"unavailable\",\"reason\":\"[redacted]\","
                "\"redaction_content_hash\":\""
                + ("a" * 64)
                + "\"}' WHERE id=:fact"
            ),
            {"fact": fact_id},
        )


def test_governed_fact_is_removed_only_by_document_cascade(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id, stock_id, fact_id = _seed(connection)
        document_id = connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,stock_id,file_name,file_storage_key,source,parse_status,"
                "identity_needs_review) "
                "VALUES (:user,:stock,'r22.pdf','r22.pdf','value_line','pending',false) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )
        connection.execute(
            text(
                "UPDATE metric_facts SET source_document_id=:document WHERE id=:fact"
            ),
            {"fact": fact_id, "document": document_id},
        )
        connection.execute(
            text("DELETE FROM pdf_documents WHERE id=:document"),
            {"document": document_id},
        )
        assert connection.scalar(
            text("SELECT count(*) FROM metric_facts WHERE id=:fact"),
            {"fact": fact_id},
        ) == 0
