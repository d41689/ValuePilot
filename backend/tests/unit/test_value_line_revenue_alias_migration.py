"""Exercise registry authority in a disposable schema, never the live schema."""

import importlib.util
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.ingestion_service import IngestionService
from app.services.source_reconciliation import _registered_mapping_spec_identity
from test_support.database_isolation import (
    build_isolated_database_url, create_test_schema, drop_test_schema, new_test_schema_name,
)


BACKEND = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "revenue_alias_migration",
    BACKEND / "alembic/versions/20260912110000-value-line-revenue-aliases.py",
)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def alembic(url, *args, succeeds=True):
    result = subprocess.run(
        ["alembic", *args], cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True,
    )
    assert (result.returncode == 0) == succeeds, result.stdout + result.stderr
    return result.stdout + result.stderr


@pytest.fixture
def isolated_registry():
    configured = make_url(settings.SQLALCHEMY_DATABASE_URI)
    base = configured.set(query={k: v for k, v in configured.query.items() if k != "options"})
    base = base.render_as_string(hide_password=False)
    name = new_test_schema_name()
    url = build_isolated_database_url(base, name)
    create_test_schema(base, name)
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        drop_test_schema(base, name)


def registry_rows(engine):
    with engine.connect() as connection:
        return {
            row.id: dict(row._mapping)
            for row in connection.execute(text("SELECT * FROM value_line_mapping_policies"))
        }


def test_revenue_registry_append_roundtrip_and_immutable_history(isolated_registry):
    url, engine = isolated_registry
    alembic(url, "upgrade", migration.down_revision)
    before = registry_rows(engine)
    with Session(engine) as session:
        assert _registered_mapping_spec_identity(session) is None
    alembic(url, "upgrade", migration.revision)
    after = registry_rows(engine)
    assert set(after) == set(before) | {migration.POLICY_ID}
    assert {key: after[key] for key in before} == before
    assert after[migration.POLICY_ID]["status"] == "approved"
    assert after[migration.POLICY_ID]["policy_sha256"] == migration.POLICY_SHA256
    with Session(engine) as session:
        assert _registered_mapping_spec_identity(session)[1] == migration.POLICY_SHA256
    with pytest.raises(DBAPIError, match="registry is immutable"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE value_line_mapping_policies SET spec_version=2"))
    alembic(url, "downgrade", migration.down_revision)
    assert registry_rows(engine) == before
    alembic(url, "upgrade", migration.revision)
    with engine.begin() as connection:
        user_id = connection.execute(text(
            "INSERT INTO users (email,hashed_password,is_active) "
            "VALUES ('revenue-registry@example.invalid','x',true) RETURNING id"
        )).scalar_one()
        document_id = connection.execute(text(
            "INSERT INTO pdf_documents "
            "(user_id,file_name,source,file_storage_key,parse_status,identity_needs_review) "
            "VALUES (:user,'revenue.pdf','upload','test/revenue.pdf','pending',false) RETURNING id"
        ), {"user": user_id}).scalar_one()
        # Both the old approved identity and the new identity remain valid;
        # terminal history is appended and must prevent a policy downgrade.
        for policy in (migration.PREVIOUS_POLICY_ID, migration.POLICY_ID):
            run_id = connection.execute(text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,created_txid) "
                "VALUES (:user,:document,'value-line-v1',:policy,'running',0) RETURNING id"
            ), {"user": user_id, "document": document_id, "policy": policy}).scalar_one()
            connection.execute(text("UPDATE value_line_parse_runs SET status='failed' WHERE id=:id"), {"id": run_id})
    retained = registry_rows(engine)
    refused = alembic(url, "downgrade", migration.down_revision, succeeds=False)
    assert "immutable parse-run history" in refused
    assert registry_rows(engine) == retained


def test_fractional_revenue_persists_exactly_through_normal_mapping_insert(db_session, user_factory):
    user = user_factory("decimal-revenue@example.invalid")
    stock = Stock(ticker="VLDEC", exchange="NYSE", company_name="Decimal Revenue")
    db_session.add(stock)
    db_session.flush()
    document = PdfDocument(
        user_id=user.id, stock_id=stock.id, file_name="decimal.pdf", source="upload",
        file_storage_key="test/decimal.pdf", parse_status="parsed", report_date=date(2026, 2, 13),
        identity_needs_review=False,
    )
    db_session.add(document)
    db_session.flush()
    service = IngestionService(db_session)
    run = service._start_value_line_parse_run(user_id=user.id, document_id=document.id)
    extraction = MetricExtraction(
        user_id=user.id, document_id=document.id, page_number=1,
        field_key="tables_time_series", raw_value_text="4204.1",
        original_text_snippet="Revenues ($mill) 4204.1", parser_version="v1",
        value_line_parse_run_id=run.id,
    )
    db_session.add(extraction)
    db_session.flush()
    facts, _, _ = service.mapping_spec.generate_facts({"annual_financials": {
        "meta": {"actual_years": [2017], "currency": "USD"},
        "income_statement_usd_millions": {"revenues": {"2017": 4204.1}},
    }})
    fact = facts[0]
    fact_id = service._insert_metric_fact_from_mapping(
        user_id=user.id, stock_id=stock.id, source_document_id=document.id,
        value_line_parse_run_id=run.id, source_extraction_ids=(extraction.id,),
        **{key: value for key, value in fact.items() if key != "source_extraction_keys"},
    )
    service._finish_value_line_parse_run(run, status="succeeded")
    stored = db_session.get(MetricFact, fact_id)
    assert stored.value_numeric == Decimal("4204100000.000000000000")
    assert stored.value_json["source_mapping_version"] == migration.POLICY_ID
    assert db_session.execute(text(
        "SELECT extraction_id FROM value_line_fact_extraction_inputs WHERE fact_id=:id"
    ), {"id": fact_id}).scalar_one() == extraction.id
