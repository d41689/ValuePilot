from __future__ import annotations

import os
from pathlib import Path
import subprocess

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


PARENT_REVISION = "20260826130000"
_configured_url = make_url(settings.SQLALCHEMY_DATABASE_URI)
_BASE_DATABASE_URL = _configured_url.set(
    query={key: value for key, value in _configured_url.query.items() if key != "options"}
).render_as_string(hide_password=False)


def _alembic(backend_dir: Path, database_url: str, *args: str) -> None:
    result = subprocess.run(
        ["alembic", *args],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_sec_financial_lineage_migration_round_trip_and_triggers() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", PARENT_REVISION)
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('SECX', 'US', 'US', 'SEC Migration Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()

        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            inspector = inspect(connection)
            expected = {
                "sec_issuer_identities",
                "sec_financial_filings",
                "sec_filing_artifacts",
                "sec_financial_parse_runs",
                "sec_financial_parse_run_artifacts",
                "sec_raw_xbrl_facts",
            }
            assert expected <= set(inspector.get_table_names())
            raw_columns = {
                item["name"]
                for item in inspector.get_columns("sec_raw_xbrl_facts")
            }
            assert {
                "concept_namespace_uri",
                "unit_measure",
                "transformation_format",
                "language",
                "continued_at",
                "locator_json",
            } <= raw_columns
            identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, review_reason, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000099', 'reviewed', 'migration test', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": stock_id},
            ).scalar_one()
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sec_issuer_identities SET cik = '0000000098' "
                        "WHERE id = :id"
                    ),
                    {"id": identity_id},
                )
        except Exception as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("append-only identity UPDATE unexpectedly succeeded")

        engine.dispose()
        _alembic(backend_dir, database_url, "downgrade", PARENT_REVISION)
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_financial_filings") is False
            assert connection.execute(
                text("SELECT count(*) FROM stocks WHERE id = :id"), {"id": stock_id}
            ).scalar_one() == 1

        engine.dispose()
        _alembic(backend_dir, database_url, "upgrade", "head")
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_financial_parse_run_artifacts")
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)
