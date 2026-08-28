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
            run_columns = {
                item["name"]
                for item in inspector.get_columns("sec_financial_parse_runs")
            }
            link_columns = {
                item["name"]
                for item in inspector.get_columns("sec_financial_parse_run_artifacts")
            }
            assert "known_at" in link_columns
            assert "created_txid" in run_columns
            assert "created_txid" in link_columns
            assert "created_txid" in raw_columns
            parse_checks = {
                item["name"]
                for item in inspector.get_check_constraints("sec_financial_parse_runs")
            }
            assert "ck_sec_financial_parse_runs_fact_count" in parse_checks
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
            filing_id = connection.execute(
                text(
                    "INSERT INTO sec_financial_filings "
                    "(issuer_identity_id, accession_no, form_type, is_amendment, "
                    "filed_on, report_date, accepted_at, known_at, primary_document, "
                    "index_url, source_url, submissions_source_url, discovery_payload_sha256) "
                    "VALUES (:identity_id, '0000000099-26-000001', '10-Q', false, "
                    "'2026-07-31', '2026-06-30', '2026-07-31T16:00:00+00:00', "
                    "'2026-08-27T00:01:00+00:00', 'fixture.htm', "
                    "'https://www.sec.gov/fixture/index.json', "
                    "'https://www.sec.gov/fixture/fixture.htm', "
                    "'https://data.sec.gov/submissions/CIK0000000099.json', :hash) "
                    "RETURNING id"
                ),
                {"identity_id": identity_id, "hash": "a" * 64},
            ).scalar_one()

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_parse_runs "
                        "(filing_id, parser_name, parser_version, input_manifest_hash, "
                        "status, started_at, completed_at, known_at, fact_count) "
                        "VALUES (:filing_id, 'fixture', 'mismatch', :hash, 'succeeded', "
                        "'2026-08-27T00:02:00+00:00', '2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:02:00+00:00', 1)"
                    ),
                    {"filing_id": filing_id, "hash": "b" * 64},
                )
        except Exception as exc:
            assert "fact count mismatch" in str(exc)
        else:
            raise AssertionError("deferred parse-run fact-count validation did not fire")
        try:
            with engine.begin() as connection:
                artifact_id = connection.execute(
                    text(
                        "INSERT INTO sec_filing_artifacts "
                        "(filing_id, sequence, filename, declared_size, source_url, "
                        "manifest_hash, state, content_mime, sha256, byte_size, "
                        "storage_key, fetched_at, known_at) VALUES "
                        "(:filing_id, 1, 'fixture.htm', 1, "
                        "'https://www.sec.gov/fixture/fixture.htm', :manifest_hash, "
                        "'retained', 'text/html', :sha256, 1, :storage_key, "
                        "'2026-08-27T00:02:00+00:00', '2026-08-27T00:02:00+00:00') "
                        "RETURNING id"
                    ),
                    {
                        "filing_id": filing_id,
                        "manifest_hash": "c" * 64,
                        "sha256": "d" * 64,
                        "storage_key": "sha256/dd/" + "d" * 64,
                    },
                ).scalar_one()
                run_id = connection.execute(
                    text(
                        "INSERT INTO sec_financial_parse_runs "
                        "(filing_id, parser_name, parser_version, input_manifest_hash, "
                        "status, started_at, completed_at, known_at, fact_count) "
                        "VALUES (:filing_id, 'fixture', 'exact-count', :hash, "
                        "'succeeded', '2026-08-27T00:03:00+00:00', "
                        "'2026-08-27T00:03:00+00:00', "
                        "'2026-08-27T00:03:00+00:00', 1) RETURNING id"
                    ),
                    {"filing_id": filing_id, "hash": "e" * 64},
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_parse_run_artifacts "
                        "(parse_run_id, artifact_id, known_at) "
                        "VALUES (:run_id, :artifact_id, "
                        "'2026-08-27T00:03:00+00:00')"
                    ),
                    {"run_id": run_id, "artifact_id": artifact_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO sec_raw_xbrl_facts "
                        "(parse_run_id, artifact_id, ordinal, concept, locator_json) "
                        "VALUES (:run_id, :artifact_id, 1, 'us-gaap:Assets', "
                        "'{\"element_id\": \"fact-1\"}'::jsonb)"
                    ),
                    {"run_id": run_id, "artifact_id": artifact_id},
                )
                connection.execute(
                    text("SET CONSTRAINTS trg_sec_financial_parse_runs_fact_count IMMEDIATE")
                )
                connection.execute(
                    text(
                        "INSERT INTO sec_raw_xbrl_facts "
                        "(parse_run_id, artifact_id, ordinal, concept, locator_json) "
                        "VALUES (:run_id, :artifact_id, 2, 'us-gaap:Liabilities', "
                        "'{\"element_id\": \"fact-2\"}'::jsonb)"
                    ),
                    {"run_id": run_id, "artifact_id": artifact_id},
                )
        except Exception as exc:
            assert "requires succeeded run and retained input" in str(exc)
        else:
            raise AssertionError("raw facts exceeded the parse run's declared count")
        with engine.begin() as connection:
            first_artifact_id = connection.execute(
                text(
                    "INSERT INTO sec_filing_artifacts "
                    "(filing_id, sequence, filename, declared_size, source_url, "
                    "manifest_hash, state, content_mime, sha256, byte_size, "
                    "storage_key, fetched_at, known_at) VALUES "
                    "(:filing_id, 2, 'atomic-primary.htm', 1, "
                    "'https://www.sec.gov/fixture/atomic-primary.htm', :manifest_hash, "
                    "'retained', 'text/html', :sha256, 1, :storage_key, "
                    "'2026-08-27T00:04:00+00:00', '2026-08-27T00:04:00+00:00') "
                    "RETURNING id"
                ),
                {
                    "filing_id": filing_id,
                    "manifest_hash": "f" * 64,
                    "sha256": "1" * 64,
                    "storage_key": "sha256/11/" + "1" * 64,
                },
            ).scalar_one()
            late_artifact_id = connection.execute(
                text(
                    "INSERT INTO sec_filing_artifacts "
                    "(filing_id, sequence, filename, declared_size, source_url, "
                    "manifest_hash, state, content_mime, sha256, byte_size, "
                    "storage_key, fetched_at, known_at) VALUES "
                    "(:filing_id, 3, 'atomic-late.xml', 1, "
                    "'https://www.sec.gov/fixture/atomic-late.xml', :manifest_hash, "
                    "'retained', 'application/xml', :sha256, 1, :storage_key, "
                    "'2026-08-27T00:04:00+00:00', '2026-08-27T00:04:00+00:00') "
                    "RETURNING id"
                ),
                {
                    "filing_id": filing_id,
                    "manifest_hash": "0" * 64,
                    "sha256": "2" * 64,
                    "storage_key": "sha256/22/" + "2" * 64,
                },
            ).scalar_one()
            atomic_run = connection.execute(
                text(
                    "INSERT INTO sec_financial_parse_runs "
                    "(filing_id, parser_name, parser_version, input_manifest_hash, "
                    "status, started_at, completed_at, known_at, fact_count) "
                    "VALUES (:filing_id, 'fixture', 'atomic-inputs', :hash, "
                    "'succeeded', '2026-08-27T00:05:00+00:00', "
                    "'2026-08-27T00:05:00+00:00', "
                    "'2026-08-27T00:05:00+00:00', 1) "
                    "RETURNING id, known_at, created_at, created_txid"
                ),
                {"filing_id": filing_id, "hash": "3" * 64},
            ).mappings().one()
            connection.execute(
                text(
                    "INSERT INTO sec_financial_parse_run_artifacts "
                    "(parse_run_id, artifact_id, known_at) "
                    "VALUES (:run_id, :artifact_id, :known_at)"
                ),
                {
                    "run_id": atomic_run["id"],
                    "artifact_id": first_artifact_id,
                    "known_at": atomic_run["known_at"],
                },
            )
            connection.execute(
                text(
                    "INSERT INTO sec_raw_xbrl_facts "
                    "(parse_run_id, artifact_id, ordinal, concept, locator_json) "
                    "VALUES (:run_id, :artifact_id, 1, 'us-gaap:Assets', "
                    "'{\"element_id\": \"atomic-fact\"}'::jsonb)"
                ),
                {
                    "run_id": atomic_run["id"],
                    "artifact_id": first_artifact_id,
                },
            )

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_parse_run_artifacts "
                        "(parse_run_id, artifact_id, known_at, created_at, created_txid) "
                        "VALUES (:run_id, :artifact_id, :known_at, :created_at, :created_txid)"
                    ),
                    {
                        "run_id": atomic_run["id"],
                        "artifact_id": late_artifact_id,
                        "known_at": atomic_run["known_at"],
                        "created_at": atomic_run["created_at"],
                        "created_txid": atomic_run["created_txid"],
                    },
                )
        except Exception as exc:
            assert "invalid SEC parse-run artifact link" in str(exc)
        else:
            raise AssertionError("late parse input accepted backfilled timestamps")
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM sec_financial_parse_run_artifacts "
                    "WHERE parse_run_id = :run_id"
                ),
                {"run_id": atomic_run["id"]},
            ).scalar_one() == 1
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
