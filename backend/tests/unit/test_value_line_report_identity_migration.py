from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import bindparam, create_engine, inspect, text
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
HEAD = "20260904170000"
PARENT = "20260904160000"


def _alembic(
    url: str, *args: str, succeeds: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if succeeds:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
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


def test_empty_schema_roundtrips_report_identity_head(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    _alembic(url, "downgrade", PARENT)
    with engine.connect() as connection:
        assert "value_line_document_report_identity_revisions" not in inspect(
            connection
        ).get_table_names()
    _alembic(url, "upgrade", HEAD)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


def test_report_identity_is_db_stamped_append_only_and_tracks_metadata(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('report-identity@example.com','x',true) RETURNING id"
            )
        )
        first_stock_id = connection.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('RID1','NYSE','US','Report Identity One',true) RETURNING id"
            )
        )
        second_stock_id = connection.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('RID2','NYSE','US','Report Identity Two',true) RETURNING id"
            )
        )
        document_id = connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "report_date,identity_needs_review) "
                "VALUES (:user,'rid.pdf','value_line','tests/rid.pdf','parsed',"
                ":stock,'2026-01-09',false) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": first_stock_id},
        )
        connection.execute(
            text(
                "UPDATE pdf_documents SET stock_id=:stock,report_date='2026-04-09' "
                "WHERE id=:document"
            ),
            {"stock": second_stock_id, "document": document_id},
        )
        rows = connection.execute(
            text(
                "SELECT id,user_id,stock_id,report_date,known_at,created_txid "
                "FROM value_line_document_report_identity_revisions "
                "WHERE document_id=:document ORDER BY id"
            ),
            {"document": document_id},
        ).mappings().all()
        assert [(row.stock_id, row.report_date.isoformat()) for row in rows] == [
            (first_stock_id, "2026-01-09"),
            (second_stock_id, "2026-04-09"),
        ]
        assert all(row.user_id == user_id for row in rows)
        assert all(row.known_at.tzinfo is not None for row in rows)
        assert all(row.created_txid is not None for row in rows)

        policy_id = connection.scalar(
            text(
                "SELECT id FROM value_line_mapping_policies "
                "WHERE status='approved' ORDER BY effective_from DESC LIMIT 1"
            )
        )
        parse_run_id = connection.scalar(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
                "'running',0) "
                "RETURNING id"
            ),
            {"user": user_id, "document": document_id, "policy": policy_id},
        )
        fact_binding = connection.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "source_document_id,is_current,value_line_parse_run_id,"
                "value_line_report_identity_revision_id) "
                "VALUES (:user,:stock,'custom.report_identity',1,'parsed',"
                ":document,true,:run,:forged) "
                "RETURNING value_line_report_identity_revision_id"
            ),
            {
                "user": user_id,
                "stock": second_stock_id,
                "document": document_id,
                "run": parse_run_id,
                "forged": rows[0].id,
            },
        )
        assert fact_binding == rows[1].id

        with pytest.raises(
            DBAPIError, match="requires current report identity authority"
        ):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id,stock_id,metric_key,value_numeric,source_type,"
                        "source_document_id,is_current,value_line_parse_run_id) "
                        "VALUES (:user,:stale_stock,'custom.stale_identity',1,'parsed',"
                        ":document,true,:run)"
                    ),
                    {
                        "user": user_id,
                        "stale_stock": first_stock_id,
                        "document": document_id,
                        "run": parse_run_id,
                    },
                )

        with pytest.raises(DBAPIError, match="report identity is document-generated"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO value_line_document_report_identity_revisions "
                        "(document_id,user_id,stock_id,report_date,known_at,created_txid) "
                        "VALUES (:document,:user,:stock,'2026-04-09',"
                        "'2000-01-01',1)"
                    ),
                    {
                        "document": document_id,
                        "user": user_id,
                        "stock": second_stock_id,
                    },
                )

        with pytest.raises(DBAPIError, match="report identity revisions are append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE value_line_document_report_identity_revisions "
                        "SET report_date='2026-06-01' WHERE id=:id"
                    ),
                    {"id": rows[1].id},
                )
        with pytest.raises(DBAPIError, match="fact report identity binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET "
                        "value_line_report_identity_revision_id=:forged "
                        "WHERE metric_key='custom.report_identity'"
                    ),
                    {"forged": rows[0].id},
                )
        with pytest.raises(DBAPIError, match="report identity revisions are append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "DELETE FROM value_line_document_report_identity_revisions "
                        "WHERE id=:id"
                    ),
                    {"id": rows[1].id},
                )


def test_upgrade_binds_consistent_retained_facts_and_quarantines_mismatch(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PARENT)
    with engine.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('report-backfill@example.com','x',true) RETURNING id"
            )
        )
        other_user_id = connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('report-backfill-other@example.com','x',true) RETURNING id"
            )
        )
        first_stock_id = connection.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('RBF1','NYSE','US','Report Backfill One',true) RETURNING id"
            )
        )
        second_stock_id = connection.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('RBF2','NYSE','US','Report Backfill Two',true) RETURNING id"
            )
        )
        document_id = connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "report_date,identity_needs_review) VALUES "
                "(:user,'backfill.pdf','value_line','tests/backfill.pdf','parsed',"
                ":stock,'2026-01-09',false) RETURNING id"
            ),
            {"user": user_id, "stock": first_stock_id},
        )
        policy_id = connection.scalar(
            text(
                "SELECT id FROM value_line_mapping_policies "
                "WHERE status='approved'"
            )
        )
        run_id = connection.scalar(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
                "'running',0) RETURNING id"
            ),
            {"user": user_id, "document": document_id, "policy": policy_id},
        )
        user_mismatch_document_id = connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "report_date,identity_needs_review) VALUES "
                "(:user,'backfill-user.pdf','value_line','tests/backfill-user.pdf',"
                "'parsed',:stock,'2026-01-09',false) RETURNING id"
            ),
            {"user": user_id, "stock": first_stock_id},
        )
        user_mismatch_run_id = connection.scalar(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
                "'running',0) RETURNING id"
            ),
            {
                "user": user_id,
                "document": user_mismatch_document_id,
                "policy": policy_id,
            },
        )
        container_document_id = connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "report_date,identity_needs_review) VALUES "
                "(:user,'backfill-container.pdf','value_line',"
                "'tests/backfill-container.pdf','parsed',NULL,'2026-01-09',false) "
                "RETURNING id"
            ),
            {"user": user_id},
        )
        container_run_id = connection.scalar(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
                "'running',0) RETURNING id"
            ),
            {
                "user": user_id,
                "document": container_document_id,
                "policy": policy_id,
            },
        )
        ids = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "source_document_id,is_current,value_line_parse_run_id) VALUES "
                "(:user,:first,'custom.match',1,'parsed',:document,true,:run),"
                "(:user,:second,'custom.mismatch',2,'parsed',:document,true,:run) "
                "RETURNING id,metric_key"
            ),
            {
                "user": user_id,
                "first": first_stock_id,
                "second": second_stock_id,
                "document": document_id,
                "run": run_id,
            },
        ).all()
        ids.append(
            connection.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id,stock_id,metric_key,value_numeric,source_type,"
                    "source_document_id,is_current,value_line_parse_run_id) "
                    "VALUES (:user,:first,'custom.user_mismatch',3,'parsed',"
                    ":document,true,:run) RETURNING id,metric_key"
                ),
                {
                    "user": user_id,
                    "first": first_stock_id,
                    "document": user_mismatch_document_id,
                    "run": user_mismatch_run_id,
                },
            ).one()
        )
        ids.append(
            connection.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id,stock_id,metric_key,value_numeric,source_type,"
                    "source_document_id,is_current,value_line_parse_run_id) "
                    "VALUES (:user,:first,'custom.container',4,'parsed',"
                    ":document,true,:run) RETURNING id,metric_key"
                ),
                {
                    "user": user_id,
                    "first": first_stock_id,
                    "document": container_document_id,
                    "run": container_run_id,
                },
            ).one()
        )
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": user_mismatch_run_id},
        )
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": container_run_id},
        )
        # Before revision authority existed, document ownership remained
        # mutable after a successful parse. The migration must not reinterpret
        # that older tenant's fact as belonging to the document's new owner.
        connection.execute(
            text("UPDATE pdf_documents SET user_id=:user WHERE id=:document"),
            {"user": other_user_id, "document": user_mismatch_document_id},
        )
    _alembic(url, "upgrade", HEAD)

    with engine.connect() as connection:
        bindings = dict(
            connection.execute(
                text(
                    "SELECT metric_key,value_line_report_identity_revision_id "
                    "FROM metric_facts WHERE id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": [row.id for row in ids]},
            ).all()
        )
        assert bindings["custom.match"] is not None
        assert bindings["custom.container"] is not None
        assert bindings["custom.mismatch"] is None
        assert bindings["custom.user_mismatch"] is None


def test_downgrade_refuses_retained_report_identity_before_mutation(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PARENT)
    with engine.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('report-downgrade@example.com','x',true) RETURNING id"
            )
        )
        stock_id = connection.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('RDOWN','NYSE','US','Report Downgrade',true) RETURNING id"
            )
        )
        connection.execute(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "report_date,identity_needs_review) "
                "VALUES (:user,'down.pdf','value_line','tests/down.pdf','parsed',"
                ":stock,'2026-01-09',false)"
            ),
            {"user": user_id, "stock": stock_id},
        )
    _alembic(url, "upgrade", HEAD)

    refused = _alembic(url, "downgrade", PARENT, succeeds=False)
    assert "cannot downgrade retained Value Line report identity" in (
        refused.stdout + refused.stderr
    )
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert "value_line_document_report_identity_revisions" in inspect(
            connection
        ).get_table_names()
