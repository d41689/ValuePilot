from __future__ import annotations

import os
from pathlib import Path
import subprocess
import importlib.util

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.facts import MetricFact
from app.services.metric_fact_visibility import visible_metric_fact_predicate
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


def _alembic_failure(
    backend_dir: Path, database_url: str, *args: str
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["alembic", *args],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "alembic command unexpectedly succeeded"
    return result


def test_no_truncate_downgrade_preflight_covers_every_protected_table(
    monkeypatch,
) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    migration_path = (
        backend_dir
        / "alembic/versions/20260828230000-financial-truth-no-truncate.py"
    )
    spec = importlib.util.spec_from_file_location("financial_truth_no_truncate", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    preflight = statements[0]
    for table_name in migration._PROTECTED_TABLES:
        assert f"FROM {table_name}" in preflight


def _insert_published_sec_fact(
    connection,
    *,
    publication_role: str,
    mapping_known_at: str = "2026-08-28T00:00:00+00:00",
    metric_value: int = 100,
    mapping_version: str = "sec-us-gaap-v2",
    fact_nature: str = "actual",
    fact_locator_element_id: str = "downgrade-fact",
    raw_concept: str = "us-gaap:Revenues",
    source_document_id: int | None = None,
    value_text: str | None = None,
    period: str | None = None,
) -> int:
    stock_id = connection.execute(
        text(
            "INSERT INTO stocks "
            "(ticker, exchange, market_country, company_name, is_active) "
            "VALUES ('SECD', 'US', 'US', 'SEC Downgrade Fixture', true) "
            "RETURNING id"
        )
    ).scalar_one()
    identity_id = connection.execute(
        text(
            "INSERT INTO sec_issuer_identities "
            "(stock_id, cik, status, review_reason, effective_from, known_at) "
            "VALUES (:stock_id, '0000000199', 'reviewed', 'downgrade test', "
            "'2020-01-01', '2026-08-28T00:00:00+00:00') RETURNING id"
        ),
        {"stock_id": stock_id},
    ).scalar_one()
    filing_id = connection.execute(
        text(
            "INSERT INTO sec_financial_filings "
            "(issuer_identity_id, accession_no, form_type, is_amendment, "
            "filed_on, report_date, accepted_at, known_at, primary_document, "
            "index_url, source_url, submissions_source_url, discovery_payload_sha256) "
            "VALUES (:identity_id, '0000000199-26-000001', '10-Q', false, "
            "'2026-08-01', '2026-06-30', '2026-08-01T16:00:00+00:00', "
            "'2026-08-28T00:01:00+00:00', 'fixture.htm', "
            "'https://www.sec.gov/downgrade/index.json', "
            "'https://www.sec.gov/downgrade/fixture.htm', "
            "'https://data.sec.gov/submissions/CIK0000000199.json', :hash) "
            "RETURNING id"
        ),
        {"identity_id": identity_id, "hash": "4" * 64},
    ).scalar_one()
    artifact_id = connection.execute(
        text(
            "INSERT INTO sec_filing_artifacts "
            "(filing_id, sequence, filename, declared_size, source_url, "
            "manifest_hash, state, content_mime, sha256, byte_size, storage_key, "
            "fetched_at, known_at) VALUES "
            "(:filing_id, 1, 'fixture.htm', 1, "
            "'https://www.sec.gov/downgrade/fixture.htm', :manifest_hash, "
            "'retained', 'text/html', :sha256, 1, :storage_key, "
            "'2026-08-28T00:02:00+00:00', '2026-08-28T00:02:00+00:00') "
            "RETURNING id"
        ),
        {
            "filing_id": filing_id,
            "manifest_hash": "5" * 64,
            "sha256": "6" * 64,
            "storage_key": "sha256/66/" + "6" * 64,
        },
    ).scalar_one()
    run_id = connection.execute(
        text(
            "INSERT INTO sec_financial_parse_runs "
            "(filing_id, parser_name, parser_version, input_manifest_hash, status, "
            "started_at, completed_at, known_at, fact_count) VALUES "
            "(:filing_id, 'fixture', 'downgrade', :hash, 'succeeded', "
            "'2026-08-28T00:03:00+00:00', '2026-08-28T00:03:00+00:00', "
            "'2026-08-28T00:03:00+00:00', 1) RETURNING id"
        ),
        {"filing_id": filing_id, "hash": "7" * 64},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO sec_financial_parse_run_artifacts "
            "(parse_run_id, artifact_id, known_at) VALUES "
            "(:run_id, :artifact_id, '2026-08-28T00:03:00+00:00')"
        ),
        {"run_id": run_id, "artifact_id": artifact_id},
    )
    raw_fact_id = connection.execute(
        text(
            "INSERT INTO sec_raw_xbrl_facts "
            "(parse_run_id, artifact_id, ordinal, concept, raw_value, "
            "transformation_format, unit_measure, is_nil, period_start, period_end, "
            "locator_json) VALUES "
            "(:run_id, :artifact_id, 1, :raw_concept, '100', "
            "'ixt:num-dot-decimal', 'iso4217:USD', false, "
            "'2026-04-01', '2026-06-30', "
            "'{\"element_id\": \"downgrade-fact\"}'::jsonb) RETURNING id"
        ),
        {
            "run_id": run_id,
            "artifact_id": artifact_id,
            "raw_concept": raw_concept,
        },
    ).scalar_one()
    metric_fact_id = connection.execute(
        text(
            "INSERT INTO metric_facts "
            "(user_id, stock_id, metric_key, value_numeric, value_text, unit, "
            "period, period_type, period_end_date, currency, value_json, "
            "source_document_id, source_type, source_ref_id, as_of_date, is_current) "
            "VALUES (NULL, :stock_id, 'is.sales', :metric_value, :value_text, "
            "'USD', :period, 'Q', '2026-06-30', "
            "'USD', jsonb_build_object("
            "'fact_nature', :fact_nature, "
            "'source_role', 'primary_as_filed', "
            "'source_accession', '0000000199-26-000001', "
            "'filing_form', '10-Q', "
            "'filing_id', :filing_id, "
            "'parse_run_id', :run_id, "
            "'parser_version', 'downgrade', "
            "'raw_fact_id', :raw_fact_id, "
            "'artifact_id', :artifact_id, "
            "'mapping_version', :mapping_version, "
            "'mapping_known_at', :mapping_known_at, "
            "'knowledge_at', '2099-08-28T00:03:00+00:00', "
            "'period_start', '2026-04-01', "
            "'period_end', '2026-06-30', "
            "'context_id', NULL, "
            "'unit_measure', 'iso4217:USD', "
            "'decimals', NULL, "
            "'scale', NULL, "
            "'dimensions_policy', 'consolidated_only', "
            "'dimensions', '{}'::jsonb, "
            "'locator', jsonb_build_object('element_id', :fact_locator_element_id), "
            "'value_basis', 'as_filed'), :source_document_id, "
            "'sec', :raw_fact_id, '2099-08-28', true) RETURNING id"
        ),
        {
            "stock_id": stock_id,
            "filing_id": filing_id,
            "run_id": run_id,
            "raw_fact_id": raw_fact_id,
            "artifact_id": artifact_id,
            "mapping_version": mapping_version,
            "mapping_known_at": mapping_known_at,
            "metric_value": metric_value,
            "fact_nature": fact_nature,
            "fact_locator_element_id": fact_locator_element_id,
            "source_document_id": source_document_id,
            "value_text": value_text,
            "period": period,
        },
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO sec_metric_publications "
            "(raw_fact_id, metric_fact_id, mapping_version, publication_role, "
            "derivation_key, "
            "status, canonical_metric_key, canonical_unit, period_type, "
            "period_end_date, knowledge_at, decision_json) VALUES "
            "(:raw_fact_id, :metric_fact_id, :mapping_version, 'direct', "
            "'direct', 'published', 'is.sales', 'USD', 'Q', '2026-06-30', "
            "'2099-08-28T00:03:00+00:00', "
            "jsonb_build_object('filing_id', :filing_id, "
            "'parse_run_id', :run_id))"
        ),
        {
            "raw_fact_id": raw_fact_id,
            "metric_fact_id": metric_fact_id,
            "filing_id": filing_id,
            "run_id": run_id,
            "mapping_version": mapping_version,
        },
    )
    if publication_role == "derived_discrete_quarter":
        connection.execute(
            text(
                "INSERT INTO sec_metric_publications "
                "(raw_fact_id, mapping_version, publication_role, derivation_key, "
                "status, reason_code, canonical_metric_key, canonical_unit, "
                "knowledge_at, decision_json) VALUES "
                "(:raw_fact_id, 'sec-us-gaap-v2', 'derived_discrete_quarter', "
                "'downgrade-derived', 'rejected', 'prior_ytd_missing', "
                "'is.sales', 'USD', '2026-08-28T00:03:00+00:00', "
                "jsonb_build_object('filing_id', :filing_id, "
                "'parse_run_id', :run_id))"
            ),
            {
                "raw_fact_id": raw_fact_id,
                "filing_id": filing_id,
                "run_id": run_id,
            },
        )
    return metric_fact_id


def test_sec_financial_lineage_migration_and_triggers() -> None:
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
        forbidden_registry_dml = [
            (
                "INSERT INTO sec_metric_mapping_registry "
                "(mapping_version, concept, canonical_metric_key, value_kind, "
                "period_basis, known_at) VALUES "
                "('forged-v1', 'us-gaap:Assets', 'is.sales', 'monetary', "
                "'instant', '2020-01-01T00:00:00+00:00')"
            ),
            (
                "UPDATE sec_metric_mapping_registry SET canonical_metric_key = "
                "'is.sales' WHERE mapping_version = 'sec-us-gaap-v2' AND "
                "concept = 'us-gaap:Assets'"
            ),
            (
                "DELETE FROM sec_metric_mapping_registry WHERE mapping_version = "
                "'sec-us-gaap-v2' AND concept = 'us-gaap:Assets'"
            ),
            "TRUNCATE sec_metric_mapping_registry",
        ]
        for statement in forbidden_registry_dml:
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement))
            except Exception as exc:
                assert "migration-owned" in str(exc)
            else:
                raise AssertionError("runtime SEC mapping registry DML was accepted")
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id, stock_id, metric_key, value_numeric, unit, "
                        "period_type, period_end_date, source_type, source_ref_id, "
                        "is_current) VALUES "
                        "(NULL, :stock_id, 'is.revenue', 999, 'USD', 'quarter', "
                        "'2026-06-30', 'sec', 999999, true)"
                    ),
                    {"stock_id": stock_id},
                )
                connection.execute(
                    text(
                        "SET CONSTRAINTS trg_metric_facts_sec_publication IMMEDIATE"
                    )
                )
        except Exception as exc:
            assert "conflicts with approved mapping semantics" in str(exc)
        else:
            raise AssertionError("unpublished canonical SEC metric fact was accepted")
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
                    "(parse_run_id, artifact_id, ordinal, concept, raw_value, "
                    "transformation_format, unit_measure, is_nil, period_instant, "
                    "locator_json) VALUES "
                    "(:run_id, :artifact_id, 1, 'us-gaap:Assets', '100', "
                    "'ixt:num-dot-decimal', 'iso4217:USD', false, '2026-06-30', "
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
                other_stock_id = connection.execute(
                    text(
                        "INSERT INTO stocks "
                        "(ticker, exchange, market_country, company_name, is_active) "
                        "VALUES ('FAKE', 'US', 'US', 'Cross Stock Forgery', true) "
                        "RETURNING id"
                    )
                ).scalar_one()
                atomic_raw_id = connection.execute(
                    text(
                        "SELECT id FROM sec_raw_xbrl_facts "
                        "WHERE parse_run_id = :run_id"
                    ),
                    {"run_id": atomic_run["id"]},
                ).scalar_one()
                forged_fact_id = connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id, stock_id, metric_key, value_json, value_numeric, "
                        "unit, currency, period_type, period_end_date, as_of_date, "
                        "source_type, source_ref_id, is_current) VALUES "
                        "(NULL, :stock_id, 'bs.total_assets', "
                        "jsonb_build_object("
                        "'mapping_version', 'sec-us-gaap-v2', "
                        "'knowledge_at', '2026-08-27T00:05:00+00:00', "
                        "'value_basis', 'as_filed', 'raw_fact_id', :raw_fact_id, "
                        "'artifact_id', :artifact_id), "
                        "999, 'USD', 'USD', 'FY', '2026-06-30', '2026-08-27', "
                        "'sec', :raw_fact_id, true) RETURNING id"
                    ),
                    {
                        "stock_id": other_stock_id,
                        "raw_fact_id": atomic_raw_id,
                        "artifact_id": first_artifact_id,
                    },
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO sec_metric_publications "
                        "(raw_fact_id, metric_fact_id, mapping_version, "
                        "publication_role, derivation_key, status, "
                        "canonical_metric_key, canonical_unit, period_type, "
                        "period_end_date, knowledge_at, decision_json) VALUES "
                        "(:raw_fact_id, :metric_fact_id, 'sec-us-gaap-v2', "
                        "'direct', 'direct', 'published', 'bs.total_assets', "
                        "'USD', 'FY', '2026-06-30', "
                        "'2026-08-27T00:05:00+00:00', "
                        "jsonb_build_object('filing_id', :filing_id, "
                        "'parse_run_id', :run_id))"
                    ),
                    {
                        "raw_fact_id": atomic_raw_id,
                        "metric_fact_id": forged_fact_id,
                        "filing_id": filing_id,
                        "run_id": atomic_run["id"],
                    },
                )
                connection.execute(
                    text(
                        "SET CONSTRAINTS trg_metric_facts_sec_publication IMMEDIATE"
                    )
                )
        except Exception as exc:
            assert "conflicts with approved mapping semantics" in str(exc)
        else:
            raise AssertionError("cross-stock canonical SEC forgery was accepted")
        try:
            with engine.begin() as connection:
                atomic_raw_id = connection.execute(
                    text(
                        "SELECT id FROM sec_raw_xbrl_facts "
                        "WHERE parse_run_id = :run_id"
                    ),
                    {"run_id": atomic_run["id"]},
                ).scalar_one()
                forged_fact_id = connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id, stock_id, metric_key, value_json, value_numeric, "
                        "unit, currency, period_type, period_end_date, as_of_date, "
                        "source_type, source_ref_id, is_current) VALUES "
                        "(NULL, :stock_id, 'bs.total_assets', "
                        "jsonb_build_object("
                        "'mapping_version', 'sec-us-gaap-v2', "
                        "'knowledge_at', '2099-08-27T00:05:00+00:00', "
                        "'value_basis', 'as_filed', 'raw_fact_id', :raw_fact_id, "
                        "'artifact_id', :artifact_id), "
                        "999, 'USD', 'USD', 'FY', '2026-06-30', '2099-08-27', "
                        "'sec', :raw_fact_id, true) RETURNING id"
                    ),
                    {
                        "stock_id": stock_id,
                        "raw_fact_id": atomic_raw_id,
                        "artifact_id": first_artifact_id,
                    },
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO sec_metric_publications "
                        "(raw_fact_id, metric_fact_id, mapping_version, "
                        "publication_role, derivation_key, status, "
                        "canonical_metric_key, canonical_unit, period_type, "
                        "period_end_date, knowledge_at, decision_json) VALUES "
                        "(:raw_fact_id, :metric_fact_id, 'sec-us-gaap-v2', "
                        "'direct', 'direct', 'published', 'bs.total_assets', "
                        "'USD', 'FY', '2026-06-30', "
                        "'2099-08-27T00:05:00+00:00', "
                        "jsonb_build_object('filing_id', :filing_id, "
                        "'parse_run_id', :run_id))"
                    ),
                    {
                        "raw_fact_id": atomic_raw_id,
                        "metric_fact_id": forged_fact_id,
                        "filing_id": filing_id,
                        "run_id": atomic_run["id"],
                    },
                )
                connection.execute(
                    text(
                        "SET CONSTRAINTS trg_metric_facts_sec_publication IMMEDIATE"
                    )
                )
        except Exception as exc:
            assert "conflicts with approved mapping semantics" in str(exc)
        else:
            raise AssertionError("same-stock canonical SEC amount forgery was accepted")
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
        result = _alembic_failure(
            backend_dir, database_url, "downgrade", PARENT_REVISION
        )
        assert "cannot downgrade financial-truth truncate guards" in (
            result.stdout + result.stderr
        )
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_financial_filings") is True
            assert inspect(connection).has_table("sec_financial_parse_run_artifacts")
            assert connection.execute(
                text("SELECT count(*) FROM stocks WHERE id = :id"), {"id": stock_id}
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_sec_publication_role_downgrade_refuses_derived_lineage_before_mutation() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            metric_fact_id = _insert_published_sec_fact(
                connection, publication_role="derived_discrete_quarter"
            )

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE metric_facts SET value_numeric = 101 "
                        "WHERE id = :metric_fact_id"
                    ),
                    {"metric_fact_id": metric_fact_id},
                )
        except Exception as exc:
            assert "provenance and value are immutable" in str(exc)
        else:
            raise AssertionError("canonical SEC metric fact value mutation succeeded")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE metric_facts SET is_current = false "
                    "WHERE id = :metric_fact_id"
                ),
                {"metric_fact_id": metric_fact_id},
            )
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE metric_facts SET is_current = true "
                        "WHERE id = :metric_fact_id"
                    ),
                    {"metric_fact_id": metric_fact_id},
                )
        except Exception as exc:
            assert "cannot be restored to current" in str(exc)
        else:
            raise AssertionError("retired canonical SEC metric fact was resurrected")

        result = _alembic_failure(
            backend_dir, database_url, "downgrade", "20260828140000"
        )

        # The newest fail-closed boundary may refuse first. Either guard is a
        # valid pre-mutation stop; the state assertions below prove that no
        # partial downgrade occurred.
        output = result.stdout + result.stderr
        assert (
            "cannot remove metric-fact source contract" in output
            or "cannot downgrade SEC identity publication guard" in output
            or "cannot downgrade manual correction lineage" in output
            or "cannot downgrade canonical SEC column shape" in output
            or "cannot downgrade exact SEC provenance" in output
        )
        with engine.connect() as connection:
            publication_columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "sec_metric_publications"
                )
            }
            assert "publication_role" in publication_columns
            assert "derivation_key" in publication_columns
            assert connection.execute(
                text(
                    "SELECT count(*) FROM sec_metric_publications "
                    "WHERE publication_role = 'derived_discrete_quarter'"
                )
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_canonical_sec_publication_downgrade_refuses_lineage_before_mutation() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            metric_fact_id = _insert_published_sec_fact(
                connection, publication_role="direct"
            )

        result = _alembic_failure(
            backend_dir, database_url, "downgrade", "20260828120000"
        )

        output = result.stdout + result.stderr
        assert (
            "cannot remove metric-fact source contract" in output
            or "cannot downgrade SEC identity publication guard" in output
            or "cannot downgrade manual correction lineage" in output
            or "cannot downgrade canonical SEC column shape" in output
            or "cannot downgrade exact SEC provenance" in output
            or "cannot downgrade approved SEC slot uniqueness" in output
        )
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_metric_publications")
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts "
                    "WHERE id = :metric_fact_id AND source_type = 'sec'"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_metric_fact_source_contract_rejects_legacy_forged_manual_lineage() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828450000")
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password) "
                    "VALUES ('legacy-manual-forgery@example.com', 'hash') "
                    "RETURNING id"
                )
            ).scalar_one()
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks (ticker, exchange, company_name, is_active) "
                    "VALUES ('LMFORGE', 'NYSE', 'Legacy Manual Forgery', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            document_id = connection.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, stock_id, file_name, source, file_storage_key, "
                    "parse_status, identity_needs_review) VALUES "
                    "(:user_id, :stock_id, 'legacy.pdf', 'upload', "
                    "'tests/legacy-manual-forgery.pdf', 'parsed', false) "
                    "RETURNING id"
                ),
                {"user_id": user_id, "stock_id": stock_id},
            ).scalar_one()
            extraction_id = connection.execute(
                text(
                    "INSERT INTO metric_extractions "
                    "(user_id, document_id, page_number, field_key, "
                    "raw_value_text, original_text_snippet, parsed_value_json, "
                    "parser_version, parse_generation, corrected_by_user) VALUES "
                    "(:user_id, :document_id, 1, 'revenue', '100', "
                    "'Revenue 100', '{\"value\": 100}'::jsonb, 'test-v1', 1, false) "
                    "RETURNING id"
                ),
                {"user_id": user_id, "document_id": document_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_json, value_numeric, "
                    "unit, currency, period_type, period_end_date, "
                    "source_document_id, source_type, source_ref_id, "
                    "parse_generation, is_current) VALUES "
                    "(:user_id, :stock_id, 'revenue', '{}'::jsonb, 100, "
                    "'USD', 'USD', 'FY', DATE '2025-12-31', :document_id, "
                    "'parsed', :extraction_id, 1, true), "
                    "(:user_id, :stock_id, 'cogs', "
                    "'{\"correction\": true}'::jsonb, 1, 'USD', 'USD', "
                    "'FY', DATE '2025-12-31', :document_id, 'manual', "
                    ":extraction_id, NULL, true)"
                ),
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "document_id": document_id,
                    "extraction_id": extraction_id,
                },
            )

        result = _alembic_failure(backend_dir, database_url, "upgrade", "head")
        assert "unreviewed source or owner shapes" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT version_num FROM alembic_version"
                )
            ).scalar_one() == "20260828450000"
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts "
                    "WHERE source_type = 'manual' AND metric_key = 'cogs'"
                )
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_integrity_downgrade_preserves_account_erasure_deletion_ledger() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828170000")
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password) "
                    "VALUES ('migration-erasure@example.com', 'hash') RETURNING id"
                )
            ).scalar_one()
            document_id = connection.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, file_name, source, file_storage_key, parse_status, "
                    "identity_needs_review) "
                    "VALUES (:user_id, 'private.pdf', 'upload', '/tmp/private.pdf', "
                    "'parsed', false) RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO account_erasure_file_deletions "
                    "(user_id, document_id, storage_path, storage_path_hash, status) "
                    "VALUES (:user_id, :document_id, '/tmp/private.pdf', :hash, "
                    "'pending')"
                ),
                {
                    "user_id": user_id,
                    "document_id": document_id,
                    "hash": "a" * 64,
                },
            )

        result = _alembic_failure(
            backend_dir, database_url, "downgrade", "20260828130000"
        )

        assert "cannot downgrade financial-truth integrity" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert inspect(connection).has_table("account_erasure_file_deletions")
            assert connection.execute(
                text("SELECT count(*) FROM account_erasure_file_deletions")
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_erasure_ledger_rejects_active_document_queue_forgery() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")

        with pytest.raises(DBAPIError, match="verified erased document"):
            with engine.begin() as connection:
                user_id = connection.execute(
                    text(
                        "INSERT INTO users (email, hashed_password) "
                        "VALUES ('forged-erasure@example.com', 'hash') RETURNING id"
                    )
                ).scalar_one()
                document_id = connection.execute(
                    text(
                        "INSERT INTO pdf_documents "
                        "(user_id, file_name, source, file_storage_key, parse_status, "
                        "identity_needs_review) VALUES "
                        "(:user_id, 'active.pdf', 'upload', "
                        "'/code/storage/uploads/active.pdf', 'parsed', false) RETURNING id"
                    ),
                    {"user_id": user_id},
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO account_erasure_file_deletions "
                        "(user_id, document_id, storage_path, storage_path_hash, status) "
                        "VALUES (:user_id, :document_id, "
                        "'/code/storage/uploads/active.pdf', :hash, 'pending')"
                    ),
                    {
                        "user_id": user_id,
                        "document_id": document_id,
                        "hash": "a" * 64,
                    },
                )
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_erasure_transition_rejects_private_document_content_left_at_rest() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")

        with pytest.raises(DBAPIError, match="complete.*redaction"):
            with engine.begin() as connection:
                user_id = connection.execute(
                    text(
                        "INSERT INTO users (email, hashed_password) "
                        "VALUES ('partial-erasure@example.com', 'hash') RETURNING id"
                    )
                ).scalar_one()
                document_id = connection.execute(
                    text(
                        "INSERT INTO pdf_documents "
                        "(user_id, file_name, source, file_storage_key, parse_status, "
                        "identity_needs_review, raw_text) VALUES "
                        "(:user_id, 'private.pdf', 'upload', "
                        "'/code/storage/uploads/private.pdf', 'parsed', false, "
                        "'private text') RETURNING id"
                    ),
                    {"user_id": user_id},
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO account_erasure_file_deletions "
                        "(user_id, document_id, storage_path, storage_path_hash, status) "
                        "VALUES (:user_id, :document_id, "
                        "'/code/storage/uploads/private.pdf', :hash, 'pending')"
                    ),
                    {
                        "user_id": user_id,
                        "document_id": document_id,
                        "hash": "c" * 64,
                    },
                )
                connection.execute(
                    text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
                )
                connection.execute(
                    text(
                        "UPDATE users SET is_active = false, email = "
                        "'erased-' || id || '@deleted.invalid' WHERE id = :user_id"
                    ),
                    {"user_id": user_id},
                )
                connection.execute(
                    text(
                        "UPDATE pdf_documents SET lifecycle_state = 'erased', "
                        "retired_at = now(), retired_by_user_id = :user_id, "
                        "retirement_reason = 'account_erasure', "
                        "file_storage_key = :tombstone, "
                        "file_name = 'erased-document-' || id, "
                        "source = 'account_erasure_tombstone' "
                        "WHERE id = :document_id"
                    ),
                    {
                        "user_id": user_id,
                        "document_id": document_id,
                        "tombstone": f"erased/document/{document_id}",
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO account_erasure_events "
                        "(user_id, content_hash, summary_json) "
                        "VALUES (:user_id, :hash, '{}'::jsonb)"
                    ),
                    {"user_id": user_id, "hash": "b" * 64},
                )
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_financial_truth_lineage_rejects_truncate_bypass() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password) "
                    "VALUES ('truncate-guard@example.com', 'hash') RETURNING id"
                )
            ).scalar_one()
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('TRNC', 'US', 'US', 'Truncate Guard', true) RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text("SELECT set_config('valuepilot.account_erasure', 'on', true)")
            )
            connection.execute(
                text(
                    "UPDATE users SET is_active = false, email = "
                    "'erased-' || id || '@deleted.invalid' WHERE id = :user_id"
                ),
                {"user_id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO account_erasure_events "
                    "(user_id, content_hash, summary_json) "
                    "VALUES (:user_id, :hash, '{}'::jsonb)"
                ),
                {"user_id": user_id, "hash": "d" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO company_analysis_classifications "
                    "(stock_id, classification, status, method_policy_version, "
                    "effective_from, known_at, review_reason) VALUES "
                    "(:stock_id, 'ordinary_operating', 'reviewed', "
                    "'analysis-method-gate-v1', '2020-01-01', "
                    "'2026-08-28T00:00:00+00:00', 'truncate fixture')"
                ),
                {"stock_id": stock_id},
            )
            metric_fact_id = _insert_published_sec_fact(
                connection, publication_role="direct"
            )

        protected_tables = (
            "account_erasure_events",
            "company_analysis_classifications",
            "stock_prices",
            "pdf_documents",
            "document_pages",
            "metric_extractions",
            "metric_facts",
            "calculated_runs",
            "sec_issuer_identities",
            "sec_financial_filings",
            "sec_filing_artifacts",
            "sec_financial_parse_runs",
            "sec_financial_parse_run_artifacts",
            "sec_raw_xbrl_facts",
            "sec_metric_publications",
        )
        for table_name in protected_tables:
            with pytest.raises(DBAPIError, match="TRUNCATE is forbidden"):
                with engine.begin() as connection:
                    connection.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM account_erasure_events")
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM company_analysis_classifications")
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts "
                    "WHERE id = :metric_fact_id AND source_type = 'sec'"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one() == 1
            assert connection.execute(
                text("SELECT count(*) FROM sec_metric_publications")
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_sec_mapping_known_at_metadata_cannot_be_forged() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")

        with pytest.raises(DBAPIError, match="provenance is not exact"):
            with engine.begin() as connection:
                _insert_published_sec_fact(
                    connection,
                    publication_role="direct",
                    mapping_known_at="2020-01-01T00:00:00+00:00",
                )

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts "
                    "WHERE source_type = 'sec'"
                )
            ).scalar_one() == 0
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


@pytest.mark.parametrize(
    ("overrides", "case_name"),
    [
        ({"fact_locator_element_id": "wrong-element"}, "locator"),
        ({"fact_nature": "estimate"}, "fact_nature"),
    ],
)
def test_sec_exact_provenance_rejects_forged_user_visible_claims(
    overrides: dict[str, str], case_name: str
) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")

        with pytest.raises(DBAPIError, match="provenance is not exact"):
            with engine.begin() as connection:
                _insert_published_sec_fact(
                    connection,
                    publication_role="direct",
                    **overrides,
                )

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM metric_facts WHERE source_type = 'sec'")
            ).scalar_one() == 0
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


@pytest.mark.parametrize("forged_field", ["source_document_id", "value_text", "period"])
def test_sec_column_shape_rejects_private_or_noncanonical_values(
    forged_field: str,
) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with pytest.raises(DBAPIError, match="noncanonical or private columns"):
            with engine.begin() as connection:
                overrides: dict[str, object] = {}
                if forged_field == "source_document_id":
                    user_id = connection.execute(
                        text(
                            "INSERT INTO users (email, hashed_password) "
                            "VALUES ('private-sec-source@example.com', 'hash') "
                            "RETURNING id"
                        )
                    ).scalar_one()
                    overrides[forged_field] = connection.execute(
                        text(
                            "INSERT INTO pdf_documents "
                            "(user_id, file_name, source, file_storage_key, "
                            "parse_status, identity_needs_review) VALUES "
                            "(:user_id, 'private.pdf', 'upload', "
                            "'private/private.pdf', 'parsed', false) RETURNING id"
                        ),
                        {"user_id": user_id},
                    ).scalar_one()
                elif forged_field == "value_text":
                    overrides[forged_field] = "forged public narrative"
                else:
                    overrides[forged_field] = "FY2026"
                _insert_published_sec_fact(
                    connection,
                    publication_role="direct",
                    **overrides,
                )

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM metric_facts WHERE source_type = 'sec'")
            ).scalar_one() == 0
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_old_revision_forged_sec_fact_blocks_upgrade_without_mutation() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828190000")
        with engine.begin() as connection:
            metric_fact_id = _insert_published_sec_fact(
                connection,
                publication_role="direct",
                metric_value=999,
            )

        result = _alembic_failure(backend_dir, database_url, "upgrade", "head")

        assert "conflicts with approved mapping semantics" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT value_numeric, is_current FROM metric_facts "
                    "WHERE id = :metric_fact_id"
                ),
                {"metric_fact_id": metric_fact_id},
            ).one()
            assert row.value_numeric == 999
            assert row.is_current is True
            assert inspect(connection).has_table("sec_metric_mapping_registry") is False
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_old_v2_unknown_concept_blocks_upgrade_instead_of_entering_quarantine() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828190000")
        with engine.begin() as connection:
            metric_fact_id = _insert_published_sec_fact(
                connection,
                publication_role="direct",
                raw_concept="us-gaap:ForgedUnregisteredRevenue",
            )

        result = _alembic_failure(backend_dir, database_url, "upgrade", "head")

        assert "conflicts with approved mapping semantics" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts "
                    "WHERE id = :metric_fact_id"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one() == 1
            assert inspect(connection).has_table("sec_metric_mapping_registry") is False
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_unregistered_legacy_sec_mapping_is_preserved_but_not_product_visible() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828190000")
        with engine.begin() as connection:
            metric_fact_id = _insert_published_sec_fact(
                connection,
                publication_role="direct",
                mapping_version="sec-us-gaap-v1",
                mapping_known_at="2025-01-01T00:00:00+00:00",
            )

        _alembic(backend_dir, database_url, "upgrade", "head")

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts "
                    "WHERE id = :metric_fact_id AND "
                    "value_json->>'mapping_version' = 'sec-us-gaap-v1'"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one() == 1
            assert connection.execute(
                text(
                    "SELECT count(*) FROM sec_metric_publications "
                    "WHERE metric_fact_id = :metric_fact_id"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one() == 1

        with Session(engine) as session:
            visible = session.scalars(
                select(MetricFact).where(
                    MetricFact.id == metric_fact_id,
                    visible_metric_fact_predicate(MetricFact, user_id=0),
                )
            ).all()
            assert visible == []

        # Publishing the now-approved v2 mapping for the same raw observation
        # must not mutate or be blocked by the quarantined v1 row.
        with engine.begin() as connection:
            v2_fact_id = connection.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_json, value_numeric, "
                    "unit, currency, period_type, period_end_date, as_of_date, "
                    "source_type, source_ref_id, is_current) "
                    "SELECT user_id, stock_id, metric_key, "
                    "value_json || jsonb_build_object("
                    "'mapping_version', 'sec-us-gaap-v2', "
                    "'mapping_known_at', '2026-08-28T00:00:00+00:00'), "
                    "value_numeric, unit, currency, period_type, period_end_date, "
                    "as_of_date, source_type, source_ref_id, true "
                    "FROM metric_facts WHERE id = :metric_fact_id RETURNING id"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO sec_metric_publications "
                    "(raw_fact_id, metric_fact_id, mapping_version, "
                    "publication_role, derivation_key, status, "
                    "canonical_metric_key, canonical_unit, period_type, "
                    "period_end_date, knowledge_at, decision_json) "
                    "SELECT raw_fact_id, :v2_fact_id, 'sec-us-gaap-v2', "
                    "'direct', 'direct', 'published', canonical_metric_key, "
                    "canonical_unit, period_type, period_end_date, knowledge_at, "
                    "decision_json FROM sec_metric_publications "
                    "WHERE metric_fact_id = :metric_fact_id"
                ),
                {
                    "metric_fact_id": metric_fact_id,
                    "v2_fact_id": v2_fact_id,
                },
            )

        with Session(engine) as session:
            visible = session.scalars(
                select(MetricFact).where(
                    MetricFact.stock_id
                    == select(MetricFact.stock_id)
                    .where(MetricFact.id == metric_fact_id)
                    .scalar_subquery(),
                    visible_metric_fact_predicate(MetricFact, user_id=0),
                )
            ).all()
            assert [fact.id for fact in visible] == [v2_fact_id]
            assert session.get(MetricFact, metric_fact_id).is_current is True

        with pytest.raises(DBAPIError, match="canonical SEC"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE metric_facts SET is_current = is_current "
                        "WHERE id = :metric_fact_id"
                    ),
                    {"metric_fact_id": metric_fact_id},
                )
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_database_rejects_two_current_sec_facts_in_same_period_slot() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            metric_fact_id = _insert_published_sec_fact(
                connection, publication_role="direct"
            )

        with pytest.raises(
            DBAPIError, match="uq_metric_facts_current_sec_period_slot"
        ):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id, stock_id, metric_key, value_json, value_numeric, "
                        "unit, currency, period_type, period_end_date, as_of_date, "
                        "source_type, source_ref_id, is_current) "
                        "SELECT user_id, stock_id, metric_key, value_json, "
                        "value_numeric, unit, currency, period_type, "
                        "period_end_date, as_of_date, source_type, source_ref_id, true "
                        "FROM metric_facts WHERE id = :metric_fact_id"
                    ),
                    {"metric_fact_id": metric_fact_id},
                )

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM metric_facts current_fact "
                    "JOIN metric_facts original ON original.id = :metric_fact_id "
                    "WHERE current_fact.source_type = 'sec' "
                    "AND current_fact.is_current = true "
                    "AND current_fact.stock_id = original.stock_id "
                    "AND current_fact.metric_key = original.metric_key "
                    "AND current_fact.period_type = original.period_type "
                    "AND current_fact.period_end_date = original.period_end_date"
                ),
                {"metric_fact_id": metric_fact_id},
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_method_gate_downgrade_preserves_classification_history() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828140000")
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('METH', 'US', 'US', 'Method History', true) RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO company_analysis_classifications "
                    "(stock_id, classification, status, method_policy_version, "
                    "effective_from, known_at, review_reason) VALUES "
                    "(:stock_id, 'ordinary_operating', 'reviewed', "
                    "'analysis-method-gate-v1', '2020-01-01', "
                    "'2026-08-28T00:00:00+00:00', 'reviewed fixture')"
                ),
                {"stock_id": stock_id},
            )

        result = _alembic_failure(
            backend_dir, database_url, "downgrade", "20260828130000"
        )

        assert "cannot downgrade analysis method gate" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert inspect(connection).has_table("company_analysis_classifications")
            assert connection.execute(
                text("SELECT count(*) FROM company_analysis_classifications")
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_document_retirement_downgrade_preserves_lifecycle_history() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828120000")
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password) "
                    "VALUES ('migration-archive@example.com', 'hash') RETURNING id"
                )
            ).scalar_one()
            document_id = connection.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, file_name, source, file_storage_key, parse_status, "
                    "identity_needs_review, lifecycle_state, retired_at, retired_by_user_id, "
                    "retirement_reason) VALUES "
                    "(:user_id, 'archived.pdf', 'upload', '/tmp/archived.pdf', "
                    "'parsed', false, 'archived', now(), :user_id, 'migration fixture') "
                    "RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()

        result = _alembic_failure(
            backend_dir, database_url, "downgrade", PARENT_REVISION
        )

        assert "cannot downgrade document retirement" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            columns = {
                item["name"]
                for item in inspect(connection).get_columns("pdf_documents")
            }
            assert "lifecycle_state" in columns
            assert connection.execute(
                text(
                    "SELECT lifecycle_state FROM pdf_documents WHERE id = :id"
                ),
                {"id": document_id},
            ).scalar_one() == "archived"
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_document_lifecycle_guard_downgrade_refuses_retired_rows() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828160000")
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password) "
                    "VALUES ('lifecycle-guard-downgrade@example.com', 'hash') "
                    "RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, file_name, source, file_storage_key, parse_status, "
                    "identity_needs_review, lifecycle_state, retired_at, "
                    "retired_by_user_id, retirement_reason) VALUES "
                    "(:user_id, 'archived-at-1600.pdf', 'upload', "
                    "'/tmp/archived-at-1600.pdf', 'parsed', false, 'archived', "
                    "now(), :user_id, 'migration fixture')"
                ),
                {"user_id": user_id},
            )

        result = _alembic_failure(
            backend_dir, database_url, "downgrade", "20260828150000"
        )

        assert "cannot downgrade document lifecycle guard" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            trigger_names = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid = 'pdf_documents'::regclass "
                        "AND NOT tgisinternal"
                    )
                )
            }
            assert "trg_pdf_documents_lifecycle" in trigger_names
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_formula_output_key_upgrade_retires_mismatched_legacy_current_fact() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828370000")
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, hashed_password) "
                    "VALUES ('legacy-formula-key@example.com', 'hash') RETURNING id"
                )
            ).scalar_one()
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('LFKEY', 'US', 'US', 'Legacy Formula Key', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            input_fact_id = connection.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_json, value_numeric, "
                    "source_type, is_current) VALUES "
                    "(:user_id, :stock_id, 'revenue', '{}'::jsonb, 100, "
                    "'manual', true) RETURNING id"
                ),
                {"user_id": user_id, "stock_id": stock_id},
            ).scalar_one()
            formula_id = connection.execute(
                text(
                    "INSERT INTO formulas "
                    "(user_id, name, expression, dependencies_json) VALUES "
                    "(:user_id, 'Owner Earnings!', 'revenue', "
                    "'[\"revenue\"]'::jsonb) RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            run_id = connection.execute(
                text(
                    "INSERT INTO calculated_runs "
                    "(user_id, formula_id, stock_id, input_fact_ids_json, "
                    "result_value_json, is_dirty) VALUES "
                    "(:user_id, :formula_id, :stock_id, "
                    "jsonb_build_array(:input_fact_id), '{\"value\": 100}'::jsonb, "
                    "false) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "formula_id": formula_id,
                    "stock_id": stock_id,
                    "input_fact_id": input_fact_id,
                },
            ).scalar_one()
            output_fact_id = connection.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_json, value_numeric, "
                    "source_type, source_ref_id, is_current) VALUES "
                    "(:user_id, :stock_id, 'owner_earnings!', "
                    "jsonb_build_object("
                    "'value', 100, 'formula_id', CAST(:formula_id AS text), "
                    "'calculated_run_id', CAST(:run_id AS text), "
                    "'input_fact_ids', jsonb_build_array(:input_fact_id), "
                    "'formula_lineage_version', 'formula-v2'), "
                    "100, 'calculated', :run_id, true) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "formula_id": formula_id,
                    "run_id": run_id,
                    "input_fact_id": input_fact_id,
                },
            ).scalar_one()

        _alembic(backend_dir, database_url, "upgrade", "20260828380000")

        with engine.begin() as connection:
            migrated = connection.execute(
                text(
                    "SELECT formula.output_key, run.output_key_snapshot, "
                    "run.is_dirty, fact.metric_key, fact.is_current "
                    "FROM formulas formula "
                    "JOIN calculated_runs run ON run.formula_id = formula.id "
                    "JOIN metric_facts fact ON fact.source_ref_id = run.id "
                    "AND fact.source_type = 'calculated' "
                    "WHERE fact.id = :output_fact_id"
                ),
                {"output_fact_id": output_fact_id},
            ).one()
            assert tuple(migrated) == (
                "owner_earnings",
                "owner_earnings!",
                True,
                "owner_earnings!",
                False,
            )
            connection.execute(
                text(
                    "UPDATE metric_facts SET is_current = is_current "
                    "WHERE id = :output_fact_id"
                ),
                {"output_fact_id": output_fact_id},
            )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_document_retirement_serializes_with_account_erasure() -> None:
    import threading

    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.models.artifacts import PdfDocument
    from app.models.stocks import Stock
    from app.models.users import User
    from app.services.account_erasure import erase_account
    from app.services.document_dedupe_service import DocumentDedupeService

    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, autoflush=False)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with SessionFactory() as setup:
            user = User(
                email=f"retire-race-{schema_name}@example.com",
                hashed_password=hash_password("TestPass123!"),
            )
            stock = Stock(
                ticker="RTRCE",
                exchange="US",
                market_country="US",
                company_name="Retirement Race",
                is_active=True,
            )
            setup.add_all([user, stock])
            setup.flush()
            document = PdfDocument(
                user_id=user.id,
                stock_id=stock.id,
                file_name="retirement-race.pdf",
                source="upload",
                file_storage_key=str(
                    Path(settings.UPLOAD_DIR) / f"{schema_name}-retirement-race.pdf"
                ),
                parse_status="parsed",
            )
            setup.add(document)
            setup.commit()
            user_id = user.id
            document_id = document.id

        b_done = threading.Event()
        b_result: list[dict[str, object] | None] = []
        b_error: list[Exception] = []

        def retire_in_b() -> None:
            with SessionFactory() as session_b:
                try:
                    b_result.append(
                        DocumentDedupeService(session_b).delete_document(
                            user_id=user_id,
                            document_id=document_id,
                        )
                    )
                except Exception as exc:  # pragma: no cover - failure evidence
                    session_b.rollback()
                    b_error.append(exc)
                finally:
                    b_done.set()

        with SessionFactory() as session_a:
            session_a.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"
                ),
                {"key": f"account-erasure:{user_id}"},
            )
            thread = threading.Thread(target=retire_in_b)
            thread.start()
            assert not b_done.wait(timeout=1.0), (
                "ordinary retirement did not serialize on account erasure"
            )

            erase_account(
                session_a,
                user=session_a.get(User, user_id),
                password="TestPass123!",
            )

            assert b_done.wait(timeout=20.0), (
                "ordinary retirement did not resume after account erasure"
            )
            thread.join(timeout=20.0)

        assert not b_error, f"concurrent retirement raised: {b_error}"
        assert b_result == [
            {
                "archived_document_id": document_id,
                "lifecycle_state": "erased",
                "retired_at": b_result[0]["retired_at"],
                "already_retired": True,
            }
        ]
        with SessionFactory() as verify:
            assert verify.get(PdfDocument, document_id).lifecycle_state == "erased"
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_formula_run_serializes_with_manual_correction_and_is_invalidated() -> None:
    from datetime import date
    import threading

    from sqlalchemy.orm import sessionmaker

    from app.api.v1.endpoints.extractions import correct_extraction
    from app.core.security import hash_password
    from app.models.artifacts import PdfDocument
    from app.models.extractions import MetricExtraction
    from app.models.facts import CalculatedRun, Formula
    from app.models.stocks import Stock
    from app.models.users import User
    from app.services.formula_engine import FormulaEngine

    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, autoflush=False)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with SessionFactory() as setup:
            user = User(
                email=f"formula-correction-race-{schema_name}@example.com",
                hashed_password=hash_password("TestPass123!"),
            )
            stock = Stock(
                ticker="FMRCE",
                exchange="US",
                market_country="US",
                company_name="Formula Correction Race",
                is_active=True,
            )
            setup.add_all([user, stock])
            setup.flush()
            document = PdfDocument(
                user_id=user.id,
                stock_id=stock.id,
                file_name="formula-correction-race.pdf",
                source="upload",
                file_storage_key="test/formula-correction-race.pdf",
                parse_status="parsed",
            )
            setup.add(document)
            setup.flush()
            extraction = MetricExtraction(
                user_id=user.id,
                document_id=document.id,
                page_number=1,
                field_key="revenue",
                raw_value_text="1000",
                original_text_snippet="Revenue 1000",
                parser_version="v1",
                parse_generation=1,
                resolved_stock_id=stock.id,
                mapping_version="value-line-v2",
                canonical_projections_json=[
                    {
                        "metric_key": "revenue",
                        "value_numeric": 1000,
                        "value_text": None,
                        "value_json": None,
                        "unit": "USD",
                        "currency": None,
                        "period": None,
                        "period_type": "FY",
                        "period_end_date": "2025-12-31",
                        "as_of_date": None,
                    }
                ],
            )
            setup.add(extraction)
            setup.flush()
            parsed = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="revenue",
                value_numeric=1000,
                unit="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=document.id,
                source_ref_id=extraction.id,
                parse_generation=1,
                is_current=True,
            )
            formula = Formula(
                user_id=user.id,
                name="Revenue Copy",
                output_key="revenue_copy",
                expression='metric("revenue")',
                dependencies_json=["revenue"],
            )
            setup.add_all([parsed, formula])
            setup.commit()
            user_id = user.id
            stock_id = stock.id
            extraction_id = extraction.id
            formula_id = formula.id

        b_done = threading.Event()
        b_error: list[Exception] = []

        def correct_in_b() -> None:
            with SessionFactory() as session_b:
                try:
                    correct_extraction(
                        extraction_id=extraction_id,
                        session=session_b,
                        current_user=session_b.get(User, user_id),
                        corrected_value="1200",
                    )
                except Exception as exc:  # pragma: no cover - failure evidence
                    session_b.rollback()
                    b_error.append(exc)
                finally:
                    b_done.set()

        with SessionFactory() as session_a:
            run = FormulaEngine(session_a).run_formula(
                formula_id, stock_id, user_id, commit=False
            )
            assert run is not None
            run_id = run.id
            output_id = session_a.execute(
                select(MetricFact.id).where(
                    MetricFact.source_type == "calculated",
                    MetricFact.source_ref_id == run_id,
                )
            ).scalar_one()

            thread = threading.Thread(target=correct_in_b)
            thread.start()
            assert not b_done.wait(timeout=1.0), (
                "manual correction did not serialize with formula publication; "
                f"errors={b_error}"
            )

            session_a.commit()
            assert b_done.wait(timeout=20.0), (
                "manual correction did not resume after formula publication"
            )
            thread.join(timeout=20.0)

        assert not b_error, f"concurrent manual correction raised: {b_error}"
        with SessionFactory() as verify:
            assert verify.get(CalculatedRun, run_id).is_dirty is True
            assert verify.get(MetricFact, output_id).is_current is False
            manual = verify.execute(
                select(MetricFact).where(
                    MetricFact.user_id == user_id,
                    MetricFact.stock_id == stock_id,
                    MetricFact.metric_key == "revenue",
                    MetricFact.source_type == "manual",
                    MetricFact.is_current.is_(True),
                )
            ).scalar_one()
            assert manual.value_numeric == 1200
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_manual_current_fact_demotion_requires_an_authorized_transition() -> None:
    from datetime import date

    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.models.artifacts import PdfDocument
    from app.models.extractions import MetricExtraction
    from app.models.research import ResearchCase, ResearchCaseRevision
    from app.models.stocks import Stock
    from app.models.users import User

    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, autoflush=False)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with SessionFactory() as setup:
            user = User(
                email=f"manual-demotion-{schema_name}@example.com",
                hashed_password=hash_password("TestPass123!"),
            )
            stock = Stock(
                ticker="MNDEM",
                exchange="US",
                market_country="US",
                company_name="Manual Demotion Guard",
                is_active=True,
            )
            setup.add_all([user, stock])
            setup.flush()
            research_case = ResearchCase(
                user_id=user.id,
                stock_id=stock.id,
                state="researching",
                head_revision_number=2,
            )
            document = PdfDocument(
                user_id=user.id,
                stock_id=stock.id,
                file_name="manual-demotion.pdf",
                source="upload",
                file_storage_key="test/manual-demotion.pdf",
                parse_status="parsed",
            )
            setup.add_all([research_case, document])
            setup.flush()
            older_revision = ResearchCaseRevision(
                case_id=research_case.id,
                revision_number=1,
                case_state="researching",
                valuation_low=100,
                valuation_base=100,
                valuation_high=100,
                valuation_currency="USD",
                valuation_as_of_date=date(2026, 1, 1),
                snapshot_stock_id=stock.id,
                stock_ticker=stock.ticker,
                stock_company_name=stock.company_name,
                stock_exchange=stock.exchange,
                created_by_user_id=user.id,
            )
            latest_revision = ResearchCaseRevision(
                case_id=research_case.id,
                revision_number=2,
                case_state="researching",
                valuation_low=200,
                valuation_base=200,
                valuation_high=200,
                valuation_currency="USD",
                valuation_as_of_date=date(2026, 2, 1),
                snapshot_stock_id=stock.id,
                stock_ticker=stock.ticker,
                stock_company_name=stock.company_name,
                stock_exchange=stock.exchange,
                created_by_user_id=user.id,
            )
            extraction = MetricExtraction(
                user_id=user.id,
                document_id=document.id,
                page_number=1,
                field_key="revenue",
                raw_value_text="$100",
                original_text_snippet="Revenue $100",
                parsed_value_json={"value": 100},
                parse_generation=document.current_parse_generation,
                resolved_stock_id=stock.id,
                mapping_version="value-line-v2",
                canonical_projections_json=[
                    {
                        "metric_key": "revenue",
                        "value_numeric": 100,
                        "value_text": None,
                        "value_json": None,
                        "unit": "USD",
                        "currency": "USD",
                        "period": None,
                        "period_type": "FY",
                        "period_end_date": "2025-12-31",
                        "as_of_date": None,
                    }
                ],
            )
            setup.add_all([older_revision, latest_revision, extraction])
            setup.flush()
            older_fair_value = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.fair_value",
                value_numeric=100,
                unit="USD",
                currency="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 1, 1),
                source_type="manual",
                source_ref_id=older_revision.id,
                is_current=True,
            )
            latest_fair_value = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="val.fair_value",
                value_numeric=200,
                unit="USD",
                currency="USD",
                period_type="AS_OF",
                period_end_date=date(2026, 2, 1),
                source_type="manual",
                source_ref_id=latest_revision.id,
                is_current=True,
            )
            parsed = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="revenue",
                value_numeric=100,
                unit="USD",
                currency="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=document.id,
                source_ref_id=extraction.id,
                parse_generation=document.current_parse_generation,
                is_current=True,
            )
            correction = MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="revenue",
                value_numeric=101,
                value_json={"correction": True},
                unit="USD",
                currency="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="manual",
                source_document_id=document.id,
                source_ref_id=extraction.id,
                is_current=True,
            )
            setup.add_all(
                [older_fair_value, latest_fair_value, parsed, correction]
            )
            setup.commit()
            latest_fair_value_id = latest_fair_value.id
            correction_id = correction.id

        with pytest.raises(DBAPIError, match="manual current fact demotion"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE metric_facts SET is_current = false "
                        "WHERE id = :fact_id"
                    ),
                    {"fact_id": latest_fair_value_id},
                )

        with engine.connect() as verify:
            assert verify.execute(
                text("SELECT is_current FROM metric_facts WHERE id = :fact_id"),
                {"fact_id": latest_fair_value_id},
            ).scalar_one() is True

        with pytest.raises(DBAPIError, match="manual current fact demotion"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE metric_facts SET is_current = false "
                        "WHERE id = :fact_id"
                    ),
                    {"fact_id": correction_id},
                )

        with engine.connect() as verify:
            assert verify.execute(
                text("SELECT is_current FROM metric_facts WHERE id = :fact_id"),
                {"fact_id": correction_id},
            ).scalar_one() is True
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_parsed_fact_requires_exact_immutable_extraction_projection() -> None:
    """A source reference is not authority to invent a canonical fact.

    The fixture is intentionally a multi-company container, whose document-level
    stock is NULL.  The immutable extraction projection must both preserve that
    valid shape and reject a later fact that changes either the resolved stock or
    the mapped value.
    """
    from datetime import date

    from sqlalchemy.orm import sessionmaker

    from app.core.security import hash_password
    from app.models.facts import Formula
    from app.models.users import User
    from app.services.formula_engine import FormulaEngine

    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, autoflush=False)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as setup:
            user_id = setup.execute(
                text(
                    "INSERT INTO users (email, hashed_password, is_active) "
                    "VALUES (:email, :password, true) RETURNING id"
                ),
                {
                    "email": f"parsed-authority-{schema_name}@example.com",
                    "password": hash_password("TestPass123!"),
                },
            ).scalar_one()
            stock_a_id = setup.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('PRAA', 'US', 'US', 'Parsed Authority A', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            stock_b_id = setup.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('PRAB', 'US', 'US', 'Parsed Authority B', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            document_id = setup.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, stock_id, file_name, source, file_storage_key, "
                    "parse_status, identity_needs_review, lifecycle_state, "
                    "current_parse_generation) "
                    "VALUES (:user_id, NULL, 'multi-company.pdf', 'upload', "
                    "'test/multi-company.pdf', 'parsed', false, 'active', 1) "
                    "RETURNING id"
                ),
                {"user_id": user_id},
            ).scalar_one()
            projection = (
                '[{"metric_key":"is.sales","value_numeric":100.0,'
                '"value_text":null,"value_json":null,"unit":"USD",'
                '"currency":null,"period":null,"period_type":"FY",'
                '"period_end_date":"2025-12-31","as_of_date":null}]'
            )
            extraction_a_id = setup.execute(
                text(
                    "INSERT INTO metric_extractions "
                    "(user_id, document_id, page_number, field_key, raw_value_text, "
                    "original_text_snippet, parsed_value_json, unit, period_type, "
                    "period_end_date, corrected_by_user, parse_generation, resolved_stock_id, "
                    "mapping_version, canonical_projections_json) "
                    "VALUES (:user_id, :document_id, 1, 'sales', '100', "
                    "'Sales 100', CAST(:parsed AS jsonb), 'USD', 'FY', "
                    "'2025-12-31', false, 1, :stock_id, 'value-line-v2', "
                    "CAST(:projection AS jsonb)) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "document_id": document_id,
                    "stock_id": stock_a_id,
                    "parsed": '{"value":100}',
                    "projection": projection,
                },
            ).scalar_one()
            extraction_value_attack_id = setup.execute(
                text(
                    "INSERT INTO metric_extractions "
                    "(user_id, document_id, page_number, field_key, raw_value_text, "
                    "original_text_snippet, parsed_value_json, unit, period_type, "
                    "period_end_date, corrected_by_user, parse_generation, resolved_stock_id, "
                    "mapping_version, canonical_projections_json) "
                    "VALUES (:user_id, :document_id, 2, 'sales', '100', "
                    "'Sales 100', CAST(:parsed AS jsonb), 'USD', 'FY', "
                    "'2025-12-31', false, 1, :stock_id, 'value-line-v2', "
                    "CAST(:projection AS jsonb)) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "document_id": document_id,
                    "stock_id": stock_a_id,
                    "parsed": '{"value":100}',
                    "projection": projection,
                },
            ).scalar_one()

        with pytest.raises(DBAPIError, match="exact extraction projection"):
            with engine.begin() as attack:
                attack.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id, stock_id, metric_key, value_numeric, unit, "
                        "period_type, period_end_date, source_type, "
                        "source_document_id, source_ref_id, parse_generation, is_current) "
                        "VALUES (:user_id, :stock_id, 'is.sales', 100, 'USD', "
                        "'FY', '2025-12-31', 'parsed', :document_id, "
                        ":extraction_id, 1, true)"
                    ),
                    {
                        "user_id": user_id,
                        "stock_id": stock_b_id,
                        "document_id": document_id,
                        "extraction_id": extraction_a_id,
                    },
                )

        with pytest.raises(DBAPIError, match="exact extraction projection"):
            with engine.begin() as attack:
                attack.execute(
                    text(
                        "INSERT INTO metric_facts "
                        "(user_id, stock_id, metric_key, value_numeric, unit, "
                        "period_type, period_end_date, source_type, "
                        "source_document_id, source_ref_id, parse_generation, is_current) "
                        "VALUES (:user_id, :stock_id, 'is.sales', 999999999, 'USD', "
                        "'FY', '2025-12-31', 'parsed', :document_id, "
                        ":extraction_id, 1, true)"
                    ),
                    {
                        "user_id": user_id,
                        "stock_id": stock_a_id,
                        "document_id": document_id,
                        "extraction_id": extraction_value_attack_id,
                    },
                )

        with engine.begin() as valid:
            fact_id = valid.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_numeric, unit, "
                    "period_type, period_end_date, source_type, "
                    "source_document_id, source_ref_id, parse_generation, is_current) "
                    "VALUES (:user_id, :stock_id, 'is.sales', 100, 'USD', "
                    "'FY', '2025-12-31', 'parsed', :document_id, "
                    ":extraction_id, 1, true) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "stock_id": stock_a_id,
                    "document_id": document_id,
                    "extraction_id": extraction_a_id,
                },
            ).scalar_one()

        with SessionFactory() as verify:
            visible = verify.scalars(
                select(MetricFact).where(
                    MetricFact.id == fact_id,
                    visible_metric_fact_predicate(
                        MetricFact,
                        user_id=user_id,
                    ),
                )
            ).one()
            assert visible.value_numeric == 100

        downgrade = _alembic_failure(
            backend_dir,
            database_url,
            "downgrade",
            "20260828460000",
        )
        assert "cannot remove parsed exact authority" in (
            downgrade.stdout + downgrade.stderr
        )

        with SessionFactory() as verify:
            formula = Formula(
                user_id=user_id,
                name="Multi-company exact projection",
                output_key="sales_copy",
                expression='metric("is.sales")',
                dependencies_json=["is.sales"],
            )
            verify.add(formula)
            verify.flush()
            run = FormulaEngine(verify).run_formula(
                formula.id,
                stock_a_id,
                user_id,
                commit=False,
            )
            assert run is not None
            verify.commit()

        with pytest.raises(DBAPIError, match="immutable parse lineage"):
            with engine.begin() as attack:
                attack.execute(
                    text(
                        "UPDATE metric_extractions SET resolved_stock_id = :stock_id "
                        "WHERE id = :extraction_id"
                    ),
                    {
                        "stock_id": stock_b_id,
                        "extraction_id": extraction_a_id,
                    },
                )

    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_upgrade_does_not_bootstrap_parsed_authority_from_legacy_fact(
    monkeypatch,
) -> None:
    """A legacy fact cannot become its own mapping authority during upgrade."""
    from sqlalchemy.orm import sessionmaker

    from app.services.document_dedupe_service import DocumentDedupeService

    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260828460000")
        with engine.begin() as setup:
            user_id = setup.execute(
                text(
                    "INSERT INTO users (email, hashed_password, is_active) "
                    "VALUES (:email, 'not-used', true) RETURNING id"
                ),
                {"email": f"legacy-parsed-{schema_name}@example.com"},
            ).scalar_one()
            stock_id = setup.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('LPIT', 'US', 'US', 'Legacy Parsed Attack', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            document_id = setup.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, stock_id, file_name, source, file_storage_key, "
                    "parse_status, report_date, upload_time, "
                    "identity_needs_review, lifecycle_state, "
                    "current_parse_generation) VALUES "
                    "(:user_id, :stock_id, 'legacy.pdf', 'upload', "
                    "'test/legacy.pdf', 'parsed', '2025-12-31', "
                    "'2026-01-01T00:00:00+00:00', false, 'active', 1) "
                    "RETURNING id"
                ),
                {"user_id": user_id, "stock_id": stock_id},
            ).scalar_one()
            extraction_id = setup.execute(
                text(
                    "INSERT INTO metric_extractions "
                    "(user_id, document_id, page_number, field_key, "
                    "raw_value_text, original_text_snippet, parsed_value_json, "
                    "unit, period_type, period_end_date, corrected_by_user, "
                    "parse_generation) VALUES "
                    "(:user_id, :document_id, 1, 'sales', '100', 'Sales 100', "
                    "CAST(:parsed_value AS jsonb), 'USD', 'FY', '2025-12-31', "
                    "false, 1) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "document_id": document_id,
                    "parsed_value": '{"value":100}',
                },
            ).scalar_one()
            fact_id = setup.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_numeric, unit, "
                    "period_type, period_end_date, source_type, "
                    "source_document_id, source_ref_id, parse_generation, "
                    "is_current) VALUES "
                    "(:user_id, :stock_id, 'is.forged_sales', 999999999, "
                    "'USD', 'FY', '2025-12-31', 'parsed', :document_id, "
                    ":extraction_id, 1, true) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "document_id": document_id,
                    "extraction_id": extraction_id,
                },
            ).scalar_one()
            second_document_id = setup.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id, stock_id, file_name, source, file_storage_key, "
                    "parse_status, report_date, upload_time, "
                    "identity_needs_review, lifecycle_state, "
                    "current_parse_generation) VALUES "
                    "(:user_id, :stock_id, 'legacy-newer.pdf', 'upload', "
                    "'test/legacy-newer.pdf', 'parsed', '2025-12-31', "
                    "'2026-01-02T00:00:00+00:00', false, 'active', 1) "
                    "RETURNING id"
                ),
                {"user_id": user_id, "stock_id": stock_id},
            ).scalar_one()
            second_extraction_id = setup.execute(
                text(
                    "INSERT INTO metric_extractions "
                    "(user_id, document_id, page_number, field_key, "
                    "raw_value_text, original_text_snippet, parsed_value_json, "
                    "unit, period_type, period_end_date, corrected_by_user, "
                    "parse_generation) VALUES "
                    "(:user_id, :document_id, 1, 'sales', '101', 'Sales 101', "
                    "CAST(:parsed_value AS jsonb), 'USD', 'FY', '2025-12-31', "
                    "false, 1) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "document_id": second_document_id,
                    "parsed_value": '{"value":101}',
                },
            ).scalar_one()
            second_fact_id = setup.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id, stock_id, metric_key, value_numeric, unit, "
                    "period_type, period_end_date, source_type, "
                    "source_document_id, source_ref_id, parse_generation, "
                    "is_current) VALUES "
                    "(:user_id, :stock_id, 'is.forged_sales', 888888888, "
                    "'USD', 'FY', '2025-12-31', 'parsed', :document_id, "
                    ":extraction_id, 1, true) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "document_id": second_document_id,
                    "extraction_id": second_extraction_id,
                },
            ).scalar_one()

        _alembic(backend_dir, database_url, "upgrade", "head")

        with engine.connect() as verify:
            fact = verify.execute(
                text(
                    "SELECT is_current, "
                    "parsed_metric_fact_has_exact_authority(id) AS authorized "
                    "FROM metric_facts WHERE id = :fact_id"
                ),
                {"fact_id": fact_id},
            ).mappings().one()
            extraction = verify.execute(
                text(
                    "SELECT resolved_stock_id, mapping_version, "
                    "canonical_projections_json "
                    "FROM metric_extractions WHERE id = :extraction_id"
                ),
                {"extraction_id": extraction_id},
            ).mappings().one()

        assert fact["is_current"] is False
        assert fact["authorized"] is False
        assert extraction["resolved_stock_id"] is None
        assert extraction["mapping_version"] is None
        assert extraction["canonical_projections_json"] == []

        monkeypatch.setattr(
            "app.services.document_dedupe_service.ValueLineRatioCalculator.calculate_for_stock",
            lambda self, *, user_id, stock_id: None,
        )
        monkeypatch.setattr(
            "app.services.document_dedupe_service.PiotroskiFScoreCalculator.calculate_for_stock",
            lambda self, *, user_id, stock_id: None,
        )
        SessionFactory = sessionmaker(bind=engine, autoflush=False)
        with SessionFactory() as cleanup_session:
            cleanup = DocumentDedupeService(cleanup_session).cleanup_duplicates(
                apply=True
            )
            assert cleanup["archived_document_count"] == 1

        with engine.connect() as verify:
            states = verify.execute(
                text(
                    "SELECT id, is_current FROM metric_facts "
                    "WHERE id IN (:fact_id, :second_fact_id) ORDER BY id"
                ),
                {"fact_id": fact_id, "second_fact_id": second_fact_id},
            ).all()
        assert states == [(fact_id, False), (second_fact_id, False)]
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)
