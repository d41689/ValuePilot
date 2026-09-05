from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.services.ingestion_service import VALUE_LINE_REPARSE_LOCK_SQL
from app.services.mapping_spec import MappingSpec
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
PARENT = "20260901280000"
HEAD = "20260904180000"
APPROVED_MAPPING_VERSION = MappingSpec.load(
    BACKEND / "docs" / "metric_facts_mapping_spec.yml"
).source_mapping_version


def _alembic_result(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )


def _alembic(url: str, *args: str) -> None:
    result = _alembic_result(url, *args)
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


def test_value_line_parse_run_empty_upgrade_roundtrip(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", "head")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        assert "value_line_parse_runs" in inspect(connection).get_table_names()
        assert connection.execute(
            text(
                "SELECT id FROM value_line_mapping_policies "
                "WHERE status='approved'"
            )
        ).scalar_one() == APPROVED_MAPPING_VERSION
    _alembic(url, "downgrade", PARENT)
    _alembic(url, "upgrade", "head")


def test_value_line_parse_run_allows_history_but_rejects_late_binding(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PARENT)
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('value-line-run@example.com','x',true) RETURNING id"
            )
        ).scalar_one()
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker,exchange,market_country,company_name,is_active) "
                "VALUES ('VLRUN','NYSE','US','Value Line Run',true) RETURNING id"
            )
        ).scalar_one()
        document_id = connection.execute(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "identity_needs_review) "
                "VALUES (:user,'run.pdf','upload','private/run.pdf','parsed',:stock,false) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        old_fact_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,unit,currency,period_type,"
                "period_end_date,source_type,source_document_id,is_current) "
                "VALUES (:user,:stock,'is.net_income',100,'USD','USD','FY',"
                "'2025-12-31','parsed',:document,true) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id, "document": document_id},
        ).scalar_one()

    _alembic(url, "upgrade", "head")

    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT value_line_legacy_revision FROM metric_facts "
                "WHERE id=:id"
            ),
            {"id": old_fact_id},
        ).scalar_one() is True

    with engine.begin() as connection:
        run_id = connection.execute(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,created_txid) "
                "VALUES (:user,:document,'value-line-v1',:mapping,'running',0) "
                "RETURNING id"
            ),
            {
                "user": user_id,
                "document": document_id,
                "mapping": APPROVED_MAPPING_VERSION,
            },
        ).scalar_one()
        extraction_id = connection.execute(
            text(
                "INSERT INTO metric_extractions "
                "(user_id,document_id,page_number,field_key,parser_version,"
                "corrected_by_user,value_line_parse_run_id) "
                "VALUES (:user,:document,1,'net_profit','v1',false,:run) "
                "RETURNING id"
            ),
            {"user": user_id, "document": document_id, "run": run_id},
        ).scalar_one()
        supporting_extraction_id = connection.execute(
            text(
                "INSERT INTO metric_extractions "
                "(user_id,document_id,page_number,field_key,parser_version,"
                "corrected_by_user,value_line_parse_run_id) "
                "VALUES (:user,:document,1,'net_profit_note','v1',false,:run) "
                "RETURNING id"
            ),
            {"user": user_id, "document": document_id, "run": run_id},
        ).scalar_one()
        connection.execute(
            text("UPDATE metric_facts SET is_current=false WHERE id=:id"),
            {"id": old_fact_id},
        )
        new_fact_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,unit,currency,period_type,"
                "period_end_date,source_type,source_document_id,value_line_parse_run_id,"
                "value_json,is_current) VALUES (:user,:stock,'is.net_income',110,'USD',"
                "'USD','FY','2025-12-31','parsed',:document,:run,"
                "'{\"source_mapping_version\":\"caller:forged\"}'::jsonb,true) "
                "RETURNING id"
            ),
            {
                "user": user_id,
                "stock": stock_id,
                "document": document_id,
                "run": run_id,
            },
        ).scalar_one()
        stamped_mapping = connection.execute(
            text(
                "SELECT value_json->>'source_mapping_version' FROM metric_facts "
                "WHERE id=:id"
            ),
            {"id": new_fact_id},
        ).scalar_one()
        assert stamped_mapping == APPROVED_MAPPING_VERSION
        lineage = connection.execute(
            text(
                "INSERT INTO value_line_fact_extraction_inputs "
                "(fact_id,extraction_id,value_line_parse_run_id,input_role,"
                "input_ordinal,created_txid,created_at) "
                "VALUES (:fact,:extraction,:run,'primary',1,0,"
                "TIMESTAMPTZ '2000-01-01 00:00:00+00') "
                "RETURNING created_txid,created_at,txid_current()"
            ),
            {"fact": new_fact_id, "extraction": extraction_id, "run": run_id},
        ).one()
        assert lineage.created_txid == lineage[2]
        assert lineage.created_at.year > 2000
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:run"),
            {"run": run_id},
        )
        deleted_document_id = connection.execute(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "identity_needs_review) VALUES (:user,'delete.pdf','upload',"
                "'private/delete.pdf','parsed',:stock,false) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        deleted_run_id = connection.execute(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',"
                ":mapping,'running',0) RETURNING id"
            ),
            {
                "user": user_id,
                "document": deleted_document_id,
                "mapping": APPROVED_MAPPING_VERSION,
            },
        ).scalar_one()
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:run"),
            {"run": deleted_run_id},
        )

    with engine.begin() as connection:
        assert connection.execute(
            text(
                "SELECT array_agg(id ORDER BY id), array_agg(is_current ORDER BY id), "
                "array_agg(value_line_legacy_revision ORDER BY id) "
                "FROM metric_facts WHERE id IN (:old,:new)"
            ),
            {"old": old_fact_id, "new": new_fact_id},
        ).one() == ([old_fact_id, new_fact_id], [False, True], [True, False])
        with pytest.raises(DBAPIError, match="creating parse run"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO metric_extractions "
                        "(user_id,document_id,page_number,field_key,parser_version,"
                        "corrected_by_user,value_line_parse_run_id) "
                        "VALUES (:user,:document,2,'late','v1',false,:run)"
                    ),
                    {"user": user_id, "document": document_id, "run": run_id},
                )
        with pytest.raises(DBAPIError, match="binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_extractions SET value_line_parse_run_id=NULL "
                        "WHERE id=:id"
                    ),
                    {"id": extraction_id},
                )
        with pytest.raises(DBAPIError, match="creating run"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO value_line_fact_extraction_inputs "
                        "(fact_id,extraction_id,value_line_parse_run_id,input_role,"
                        "input_ordinal,created_txid) "
                        "VALUES (:fact,:extraction,:run,'supporting',2,0)"
                    ),
                    {
                        "fact": new_fact_id,
                        "extraction": supporting_extraction_id,
                        "run": run_id,
                    },
                )
        with pytest.raises(DBAPIError, match="append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE value_line_fact_extraction_inputs "
                        "SET input_role='supporting' WHERE fact_id=:fact"
                    ),
                    {"fact": new_fact_id},
                )
        with pytest.raises(DBAPIError, match="append-only"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "DELETE FROM value_line_fact_extraction_inputs "
                        "WHERE fact_id=:fact"
                    ),
                    {"fact": new_fact_id},
                )
        with pytest.raises(DBAPIError, match="binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_extractions SET raw_value_text='forged' "
                        "WHERE id=:id"
                    ),
                    {"id": extraction_id},
                )
        with pytest.raises(DBAPIError, match="binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_extractions SET corrected_by_user=true, "
                        "corrected_at=now() WHERE id=:id"
                    ),
                    {"id": extraction_id},
                )
        with pytest.raises(DBAPIError, match="binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_numeric=999 "
                        "WHERE id=:id"
                    ),
                    {"id": new_fact_id},
                )
        with pytest.raises(DBAPIError, match="binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_numeric=998 "
                        "WHERE id=:id"
                    ),
                    {"id": old_fact_id},
                )
        with pytest.raises(DBAPIError, match="parse runs are append-only"):
            with connection.begin_nested():
                connection.execute(
                    text("DELETE FROM value_line_parse_runs WHERE id=:run"),
                    {"run": run_id},
                )
        with pytest.raises(DBAPIError, match="requires a creating parse run"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id,stock_id,metric_key,value_numeric,unit,currency,"
                        "period_type,period_end_date,source_type,source_document_id,"
                        "value_json,value_line_legacy_revision,is_current) "
                        "VALUES (:user,:stock,'is.net_income',120,'USD','USD','FY',"
                        "'2025-12-31','parsed',:document,"
                        "'{\"source_mapping_version\":\"legacy-looking-forged\"}'::jsonb,"
                        "true,true)"
                    ),
                    {"user": user_id, "stock": stock_id, "document": document_id},
                )
        relabel_fact_id = connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,unit,currency,period_type,"
                "period_end_date,source_type,is_current) VALUES (:user,:stock,"
                "'manual.relabel_attack',1,'USD','USD','FY','2025-12-31','manual',true) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        with pytest.raises(DBAPIError, match="requires a creating parse run"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE metric_facts SET source_type='parsed', "
                        "source_document_id=:document WHERE id=:id"
                    ),
                    {"document": document_id, "id": relabel_fact_id},
                )
        with pytest.raises(DBAPIError, match="approved mapping policy"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO value_line_parse_runs "
                        "(user_id,document_id,parser_version,source_mapping_version,"
                        "status,created_txid) VALUES (:user,:document,'value-line-v1',"
                        "'caller:forged','running',0)"
                    ),
                    {"user": user_id, "document": document_id},
                )
        second_document_id = connection.execute(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
                "identity_needs_review) VALUES (:user,'second-manual.pdf','upload',"
                "'private/second-manual.pdf','parsed',:stock,false) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,unit,currency,period_type,"
                "period_end_date,source_type,source_document_id,is_current) "
                "VALUES (:user,:stock,'manual.concurrent',1,'USD','USD','FY',"
                "'2025-12-31','manual',:document,true)"
            ),
            {"user": user_id, "stock": stock_id, "document": document_id},
        )
        with pytest.raises(DBAPIError, match="uq_metric_facts_current_manual_slot"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id,stock_id,metric_key,value_numeric,unit,currency,"
                        "period_type,period_end_date,source_type,source_document_id,"
                        "is_current) VALUES (:user,:stock,'manual.concurrent',2,'USD',"
                        "'USD','FY','2025-12-31','manual',:document,true)"
                    ),
                    {
                        "user": user_id,
                        "stock": stock_id,
                        "document": second_document_id,
                    },
                )
        with pytest.raises(DBAPIError, match="registry is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO value_line_mapping_policies "
                        "(id,policy_sha256,spec_version,parser_version,status,known_at,"
                        "effective_from) VALUES ('caller:registered',repeat('0',64),2,"
                        "'value-line-v1','approved',now(),now())"
                    )
                )
        with pytest.raises(DBAPIError, match="registry is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE value_line_mapping_policies SET parser_version='forged' "
                        "WHERE id=:mapping"
                    ),
                    {"mapping": APPROVED_MAPPING_VERSION},
                )
        with pytest.raises(DBAPIError, match="registry is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "DELETE FROM value_line_mapping_policies WHERE id=:mapping"
                    ),
                    {"mapping": APPROVED_MAPPING_VERSION},
                )
        with pytest.raises(DBAPIError, match="requires a creating parse run"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO metric_extractions "
                        "(user_id,document_id,page_number,field_key,parser_version,"
                        "corrected_by_user,value_line_legacy_revision) "
                        "VALUES (:user,:document,9,'generic_runless','v1',false,true)"
                    ),
                    {"user": user_id, "document": document_id},
                )
        connection.execute(
            text("UPDATE metric_facts SET is_current=false WHERE id=:id"),
            {"id": new_fact_id},
        )
        with pytest.raises(DBAPIError, match="binding is immutable"):
            with connection.begin_nested():
                connection.execute(
                    text("UPDATE metric_facts SET is_current=true WHERE id=:id"),
                    {"id": new_fact_id},
                )
        connection.execute(
            text("DELETE FROM pdf_documents WHERE id=:document"),
            {"document": deleted_document_id},
        )
        assert connection.execute(
            text("SELECT count(*) FROM value_line_parse_runs WHERE id=:run"),
            {"run": deleted_run_id},
        ).scalar_one() == 0

    before_counts: tuple[int, int]
    with engine.connect() as connection:
        before_counts = (
            connection.execute(text("SELECT count(*) FROM metric_facts")).scalar_one(),
            connection.execute(text("SELECT count(*) FROM value_line_parse_runs")).scalar_one(),
        )
    result = _alembic_result(url, "downgrade", PARENT)
    assert result.returncode != 0
    assert "downgrade refused" in result.stdout + result.stderr
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == HEAD
        assert (
            connection.execute(text("SELECT count(*) FROM metric_facts")).scalar_one(),
            connection.execute(text("SELECT count(*) FROM value_line_parse_runs")).scalar_one(),
        ) == before_counts


def test_value_line_reparse_document_lock_serializes_concurrent_attempts(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", "head")
    first = engine.connect()
    second = engine.connect()
    try:
        first_transaction = first.begin()
        first.execute(VALUE_LINE_REPARSE_LOCK_SQL, {"document_id": 42})

        second_transaction = second.begin()
        second.execute(text("SET LOCAL lock_timeout='100ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            second.execute(VALUE_LINE_REPARSE_LOCK_SQL, {"document_id": 42})
        second_transaction.rollback()
        first_transaction.rollback()

        with second.begin():
            second.execute(VALUE_LINE_REPARSE_LOCK_SQL, {"document_id": 42})
    finally:
        first.close()
        second.close()
