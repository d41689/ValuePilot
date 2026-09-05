from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ingestion_service import IngestionService
from app.services.quant_trading.data_audit import _metric_fact_coverage
from app.services.value_line_report_identity import ReportIdentityUnverifiableError
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
HEAD = "20260904180000"
REPORT_IDENTITY_PARENT = "20260904170000"
PRE_REPORT_IDENTITY = "20260904160000"


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


def _create_identity(connection, *, email: str, ticker: str) -> tuple[int, int]:
    user_id = connection.scalar(
        text(
            "INSERT INTO users (email,hashed_password,is_active) "
            "VALUES (:email,'x',true) RETURNING id"
        ),
        {"email": email},
    )
    stock_id = connection.scalar(
        text(
            "INSERT INTO stocks "
            "(ticker,exchange,market_country,company_name,is_active) "
            "VALUES (:ticker,'NYSE','US',:name,true) RETURNING id"
        ),
        {"ticker": ticker, "name": f"{ticker} Incorporated"},
    )
    return int(user_id), int(stock_id)


def _create_document(connection, *, user_id: int, stock_id: int | None) -> int:
    return int(
        connection.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "report_date,raw_text,identity_needs_review) "
                "VALUES (:user,'authority.pdf','value_line','tests/authority.pdf',"
                "'parsed',:stock,'2026-01-09',"
                "'VALUE LINE TIMELINESS SAFETY RECENT PRICE 100',false) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )
    )


def _start_run(connection, *, user_id: int, document_id: int) -> int:
    policy_id = connection.scalar(
        text(
            "SELECT id FROM value_line_mapping_policies "
            "WHERE status='approved' ORDER BY effective_from DESC LIMIT 1"
        )
    )
    return int(
        connection.scalar(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
                "'running',0) RETURNING id"
            ),
            {"user": user_id, "document": document_id, "policy": policy_id},
        )
    )


def test_new_parsed_fact_time_and_transaction_are_database_owned(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id, stock_id = _create_identity(
            connection,
            email="fact-time-authority@example.com",
            ticker="FTIME",
        )
        document_id = _create_document(
            connection, user_id=user_id, stock_id=stock_id
        )
    with engine.connect() as connection:
        between_transactions = connection.scalar(text("SELECT clock_timestamp()"))

    forged = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with engine.begin() as connection:
        transaction_id = int(connection.scalar(text("SELECT txid_current()")))
        run_id = _start_run(
            connection, user_id=user_id, document_id=document_id
        )
        row = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "source_document_id,is_current,value_line_parse_run_id,created_at,"
                "updated_at,value_line_fact_known_at,value_line_created_txid) "
                "VALUES (:user,:stock,'custom.fact_time',1,'parsed',:document,true,"
                ":run,:forged,:forged,:forged,1) "
                "RETURNING id,created_at,updated_at,value_line_fact_known_at,"
                "value_line_created_txid"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "document": document_id,
                "run": run_id,
                "forged": forged,
            },
        ).mappings().one()
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )

    assert row.created_at > between_transactions
    assert row.updated_at == row.created_at
    assert row.value_line_fact_known_at == row.created_at
    assert row.value_line_created_txid == transaction_id

    with engine.begin() as connection:
        with pytest.raises(DBAPIError, match="immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_numeric=2,created_at=:forged "
                        "WHERE id=:id"
                    ),
                    {"id": row.id, "forged": forged},
                )
        connection.execute(
            text(
                "UPDATE metric_facts SET is_current=false,updated_at=:forged "
                "WHERE id=:id"
            ),
            {"id": row.id, "forged": forged},
        )
        demoted = connection.execute(
            text(
                "SELECT created_at,updated_at,value_line_fact_known_at,"
                "value_line_created_txid,is_current FROM metric_facts WHERE id=:id"
            ),
            {"id": row.id},
        ).mappings().one()
    assert demoted.created_at == row.created_at
    assert demoted.updated_at > row.updated_at
    assert demoted.value_line_fact_known_at == row.value_line_fact_known_at
    assert demoted.value_line_created_txid == row.value_line_created_txid
    assert demoted.is_current is False


def test_pre_authority_backdated_fact_makes_historical_coverage_unverifiable(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", REPORT_IDENTITY_PARENT)
    with engine.begin() as connection:
        user_id, stock_id = _create_identity(
            connection,
            email="fact-pre-authority@example.com",
            ticker="FPRE",
        )
        document_id = _create_document(
            connection, user_id=user_id, stock_id=stock_id
        )
    with engine.connect() as connection:
        historical_cutoff = connection.scalar(text("SELECT clock_timestamp()"))
    with engine.begin() as connection:
        run_id = _start_run(
            connection, user_id=user_id, document_id=document_id
        )
        connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "source_document_id,is_current,value_line_parse_run_id,created_at,"
                "updated_at) VALUES (:user,:stock,'custom.backdated',1,'parsed',"
                ":document,true,:run,:forged,:forged)"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "document": document_id,
                "run": run_id,
                "forged": historical_cutoff - timedelta(minutes=1),
            },
        )
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )

    _alembic(url, "upgrade", HEAD)
    with Session(engine) as session:
        coverage = _metric_fact_coverage(
            session,
            user_id=user_id,
            knowledge_cutoff=historical_cutoff,
        )
    assert coverage["status"] == "unavailable"
    assert coverage["reason_code"] == "historical_report_identity_unverifiable"
    assert coverage["documents"] == 0
    assert coverage["parsed_fact_rows"] == 0


def test_owner_mismatch_backfill_is_typed_through_reparse_service(
    isolated, monkeypatch
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PRE_REPORT_IDENTITY)
    with engine.begin() as connection:
        owner_id, document_stock_id = _create_identity(
            connection,
            email="fact-owner@example.com",
            ticker="FOWN",
        )
        new_owner_id, fact_stock_id = _create_identity(
            connection,
            email="fact-new-owner@example.com",
            ticker="FNEW",
        )
        document_id = _create_document(
            connection, user_id=owner_id, stock_id=document_stock_id
        )
        run_id = _start_run(
            connection, user_id=owner_id, document_id=document_id
        )
        fact_id = int(
            connection.scalar(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id,stock_id,metric_key,value_numeric,source_type,"
                    "source_document_id,is_current,value_line_parse_run_id) "
                    "VALUES (:user,:stock,'custom.owner_mismatch',1,'parsed',"
                    ":document,true,:run) RETURNING id"
                ),
                {
                    "user": owner_id,
                    "stock": fact_stock_id,
                    "document": document_id,
                    "run": run_id,
                },
            )
        )
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )
        connection.execute(
            text("UPDATE pdf_documents SET user_id=:user WHERE id=:document"),
            {"user": new_owner_id, "document": document_id},
        )

    _alembic(url, "upgrade", HEAD)
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT value_line_report_identity_revision_id "
                "FROM metric_facts WHERE id=:id"
            ),
            {"id": fact_id},
        ) is None

    with Session(engine) as session:
        service = IngestionService(session)
        # This regression deliberately holds the schema at revision 180;
        # revision 340 owns the later application-level erasure first lock.
        monkeypatch.setattr(
            "app.services.ingestion_service.lock_user_privacy_write",
            lambda *_args, **_kwargs: None,
        )

        def reconcile_only(**_kwargs):
            service._reconcile_parsed_fact_current_slot(
                stock_id=fact_stock_id,
                metric_key="custom.owner_mismatch",
                period_type=None,
                period_end_date=None,
            )

        monkeypatch.setattr(service, "_reparse_existing_document_revision", reconcile_only)
        with pytest.raises(ReportIdentityUnverifiableError) as raised:
            service.reparse_existing_document(
                user_id=new_owner_id,
                document_id=document_id,
            )
        assert raised.value.code == "historical_report_identity_unverifiable"


def test_empty_schema_roundtrips_fact_time_authority(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    _alembic(url, "downgrade", REPORT_IDENTITY_PARENT)
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("metric_facts")}
        assert "value_line_fact_known_at" not in columns
        assert "value_line_created_txid" not in columns
    _alembic(url, "upgrade", HEAD)
