from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
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
HEAD = "20260904250000"
PARENT = "20260904190000"


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


def _seed_user_stock(connection) -> tuple[int, int]:
    user_id = connection.scalar(
        text(
            "INSERT INTO users (email,hashed_password,is_active) "
            "VALUES ('r21@example.com','x',true) RETURNING id"
        )
    )
    stock_id = connection.scalar(
        text(
            "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
            "VALUES ('R21','R21 Corp','NYSE',true) RETURNING id"
        )
    )
    return user_id, stock_id


def test_r21_schema_roundtrips_when_empty(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    assert "metric_fact_currentness_revisions" in inspect(engine).get_table_names()
    _alembic(url, "downgrade", PARENT)
    assert "metric_fact_currentness_revisions" not in inspect(engine).get_table_names()
    _alembic(url, "upgrade", HEAD)


def test_currentness_backfill_is_conservative_and_later_demotion_is_versioned(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PARENT)
    with engine.begin() as connection:
        user_id, stock_id = _seed_user_stock(connection)
        fact_id = connection.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,is_current) "
                "VALUES (:user,:stock,'is.revenue','{}',100,'manual',true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )

    _alembic(url, "upgrade", HEAD)
    with engine.connect() as connection:
        backfill = connection.execute(
            text(
                "SELECT is_current,known_at,created_txid,is_backfill "
                "FROM metric_fact_currentness_revisions WHERE fact_id=:fact"
            ),
            {"fact": fact_id},
        ).one()
        authority_started_at = connection.scalar(
            text(
                "SELECT authority_started_at FROM metric_fact_currentness_authority "
                "WHERE singleton=true"
            )
        )
        assert backfill.is_current is True
        assert backfill.is_backfill is True
        assert backfill.created_txid is None
        assert backfill.known_at == authority_started_at

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE metric_facts SET is_current=false WHERE id=:fact"),
            {"fact": fact_id},
        )
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT is_current,known_at,created_txid,is_backfill,prior_revision_id "
                "FROM metric_fact_currentness_revisions WHERE fact_id=:fact ORDER BY id"
            ),
            {"fact": fact_id},
        ).all()
        assert [row.is_current for row in rows] == [True, False]
        assert rows[1].known_at > rows[0].known_at
        assert rows[1].created_txid is not None
        assert rows[1].is_backfill is False
        assert rows[1].prior_revision_id is not None

        with pytest.raises(DBAPIError, match="currentness revisions are database-owned"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO metric_fact_currentness_revisions "
                        "(fact_id,user_id,stock_id,metric_key,source_type,is_current,"
                        "known_at,created_txid,is_backfill) VALUES "
                        "(:fact,:user,:stock,'is.revenue','manual',true,"
                        "'2000-01-01T00:00:00Z',1,false)"
                    ),
                    {"fact": fact_id, "user": user_id, "stock": stock_id},
                )
        with pytest.raises(DBAPIError, match="currentness authority is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_fact_currentness_authority "
                        "SET authority_started_at='2000-01-01T00:00:00Z'"
                    )
                )
        with pytest.raises(DBAPIError, match="canonical slot identity is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET metric_key='is.sales' WHERE id=:fact"
                    ),
                    {"fact": fact_id},
                )


def test_snapshot_clock_fields_are_database_owned_and_index_matches_order(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id, _stock_id = _seed_user_stock(connection)
        supplied_cases = [
            (
                datetime(2099, 1, 1, tzinfo=timezone.utc),
                datetime(2020, 1, 1, tzinfo=timezone.utc),
                datetime(2020, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            ),
            (
                datetime(2020, 1, 1, tzinfo=timezone.utc),
                datetime(2099, 1, 1, tzinfo=timezone.utc),
                datetime(2099, 1, 2, tzinfo=timezone.utc),
            ),
            (
                datetime(2020, 1, 1, tzinfo=timezone.utc),
                datetime(2020, 1, 1, tzinfo=timezone.utc),
                datetime(2020, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=1),
            ),
            (
                datetime(2099, 1, 1, tzinfo=timezone.utc),
                datetime(2099, 1, 1, tzinfo=timezone.utc),
                datetime(2099, 1, 2, tzinfo=timezone.utc),
            ),
        ]
        for index, (supplied_cutoff, supplied_created, supplied_expires) in enumerate(
            supplied_cases
        ):
            row = connection.execute(
                text(
                    "INSERT INTO document_list_snapshots "
                    "(id,user_id,page_limit,total_count,max_document_id,snapshot_cutoff,"
                    "expires_at,created_at,created_txid,membership_fingerprint,"
                    "visibility_snapshot) VALUES "
                    "(:id,:user,10,0,0,:cutoff,:expires,:created,1,'empty','1:2:') "
                    "RETURNING snapshot_cutoff,created_at,expires_at,created_txid,"
                    "visibility_snapshot"
                ),
                {
                    "id": f"r21-snapshot-clock-override-{index}",
                    "user": user_id,
                    "cutoff": supplied_cutoff,
                    "created": supplied_created,
                    "expires": supplied_expires,
                },
            ).one()
            assert row.snapshot_cutoff == row.created_at
            assert row.expires_at - row.created_at == timedelta(minutes=15)
            assert row.created_at not in {supplied_cutoff, supplied_created}
            assert row.expires_at != supplied_expires
            assert row.created_txid != 1
            assert row.visibility_snapshot != "1:2:"
            assert connection.scalar(
                text("SELECT CAST(:snapshot AS txid_snapshot) IS NOT NULL"),
                {"snapshot": row.visibility_snapshot},
            ) is True
        with pytest.raises(DBAPIError, match="snapshots are immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE document_list_snapshots SET expires_at=clock_timestamp() "
                        "WHERE id='r21-snapshot-clock-override-0'"
                    )
                )

        for index in range(20):
            connection.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id,file_name,source,upload_time,file_storage_key,parse_status,"
                    "identity_needs_review) VALUES "
                    "(:user,:name,'value_line',clock_timestamp(),:key,'parsed',false)"
                ),
                {"user": user_id, "name": f"{index}.pdf", "key": f"r21/{index}"},
            )
        connection.execute(text("SET LOCAL enable_seqscan=off"))
        plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN (COSTS OFF) SELECT id FROM pdf_documents "
                    "WHERE user_id=:user "
                    "ORDER BY upload_time DESC NULLS LAST,id DESC LIMIT 5"
                ),
                {"user": user_id},
            )
        )
        assert "ix_pdf_documents_user_upload_id" in plan
