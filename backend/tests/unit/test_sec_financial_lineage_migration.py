from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.sec_financial_ingestion import (
    finalize_sec_financial_ingestion_operation,
    select_sec_financial_evidence_as_of,
)
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


PARENT_REVISION = "20260826130000"
PERIOD_PARENT_REVISION = "20260827120000"
HEAD_REVISION = "20260830140000"
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


def _insert_ingestion_operation(connection, identity_id: int) -> str:
    operation_id = str(uuid.uuid4())
    connection.execute(
        text(
            "INSERT INTO sec_financial_ingestion_operations "
            "(id, issuer_identity_id, attempted_at) VALUES "
            "(:id, :identity_id, clock_timestamp())"
        ),
        {"id": operation_id, "identity_id": identity_id},
    )
    return operation_id


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
                "sec_submission_snapshots",
                "sec_financial_ingestion_operations",
                "sec_financial_lineage_availabilities",
                "sec_financial_operation_snapshots",
                "sec_financial_resource_anchors",
                "sec_financial_operation_results",
                "sec_financial_acquisition_failures",
                "sec_financial_accession_attempts",
                "sec_financial_accession_attempt_artifacts",
                "sec_financial_acquisition_resolutions",
                "sec_financial_legacy_parse_runs",
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
            operation_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_ingestion_operations"
                )
            }
            availability_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_lineage_availabilities"
                )
            }
            failure_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_acquisition_failures"
                )
            }
            anchor_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_resource_anchors"
                )
            }
            resolution_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_acquisition_resolutions"
                )
            }
            attempt_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_accession_attempts"
                )
            }
            attempt_artifact_columns = {
                item["name"]
                for item in inspector.get_columns(
                    "sec_financial_accession_attempt_artifacts"
                )
            }
            assert "known_at" in link_columns
            assert "created_txid" in run_columns
            assert "created_txid" in link_columns
            assert "created_txid" in raw_columns
            assert "created_txid" in operation_columns
            assert "finalized_txid" in availability_columns
            assert {"operation_id", "resource_role", "resource_key", "created_txid"} <= anchor_columns
            assert "resource_anchor_id" in failure_columns
            assert {"resource_role", "resource_key"} <= failure_columns
            assert {
                "resource_role",
                "resource_key",
                "resolution_kind",
                "submission_snapshot_id",
                "parse_run_id",
            } <= resolution_columns
            assert {
                "operation_id",
                "filing_id",
                "accession_no",
                "index_resource_key",
                "outcome",
                "index_sha256",
                "input_manifest_hash",
                "parse_run_id",
                "acquisition_failure_id",
                "attempted_at",
                "created_at",
                "created_txid",
            } <= attempt_columns
            assert {"attempt_id", "artifact_id"} <= attempt_artifact_columns
            parse_checks = {
                item["name"]
                for item in inspector.get_check_constraints("sec_financial_parse_runs")
            }
            assert "ck_sec_financial_parse_runs_fact_count" in parse_checks
            filing_checks = {
                item["name"]
                for item in inspector.get_check_constraints("sec_financial_filings")
            }
            assert "ck_sec_financial_filings_period_order" in filing_checks
            identity_checks = {
                item["name"]
                for item in inspector.get_check_constraints("sec_issuer_identities")
            }
            assert "ck_sec_issuer_identities_cik" in identity_checks
            snapshot_unique_constraints = {
                item["name"]
                for item in inspector.get_unique_constraints(
                    "sec_submission_snapshots"
                )
            }
            assert "uq_sec_submission_snapshot_content" in snapshot_unique_constraints
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
            operation_id = _insert_ingestion_operation(connection, identity_id)
            filing_id = connection.execute(
                text(
                    "INSERT INTO sec_financial_filings "
                    "(issuer_identity_id, accession_no, form_type, is_amendment, "
                    "filed_on, report_date, accepted_at, known_at, primary_document, "
                    "index_url, source_url, submissions_source_url, discovery_payload_sha256) "
                    "VALUES (:identity_id, '0000000099-26-000001', '10-Q', false, "
                    "'2026-07-31', '2026-06-30', '2026-07-31T16:00:00+00:00', "
                    "'2026-08-27T00:01:00+00:00', 'fixture.htm', "
                    "'https://www.sec.gov/Archives/edgar/data/99/000000009926000001/index.json', "
                    "'https://www.sec.gov/Archives/edgar/data/99/000000009926000001/fixture.htm', "
                    "'https://data.sec.gov/submissions/CIK0000000099.json', :hash) "
                    "RETURNING id"
                ),
                {"identity_id": identity_id, "hash": "a" * 64},
            ).scalar_one()
            snapshot_id = connection.execute(
                text(
                    "INSERT INTO sec_submission_snapshots "
                    "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                    "storage_key, fetched_at, known_at) VALUES "
                    "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                    "'2026-08-27T00:01:00+00:00', "
                    "'2026-08-27T00:01:00+00:00') RETURNING id"
                ),
                {
                    "identity_id": identity_id,
                    "operation_id": operation_id,
                    "source_url": (
                        "https://data.sec.gov/submissions/CIK0000000099.json"
                    ),
                    "hash": "6" * 64,
                    "storage_key": "financial/66/" + "6" * 64,
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO sec_financial_operation_snapshots "
                    "(operation_id, snapshot_id) VALUES "
                    "(:operation_id, :snapshot_id)"
                ),
                {"operation_id": operation_id, "snapshot_id": snapshot_id},
            )
            other_stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('SECY', 'US', 'US', 'Other SEC Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            other_identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, review_reason, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000092', 'reviewed', 'other identity', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": other_stock_id},
            ).scalar_one()
            other_operation_id = _insert_ingestion_operation(
                connection, other_identity_id
            )
            unlinked_same_identity_operation_id = _insert_ingestion_operation(
                connection, identity_id
            )
            owned_failed_run_id = connection.execute(
                text(
                    "INSERT INTO sec_financial_parse_runs "
                    "(filing_id, operation_id, parser_name, parser_version, "
                    "input_manifest_hash, status, started_at, completed_at, "
                    "known_at, fact_count, error_code) VALUES "
                    "(:filing_id, :operation_id, 'fixture', 'owned-failure', "
                    ":hash, 'failed', '2026-08-27T00:02:00+00:00', "
                    "'2026-08-27T00:02:00+00:00', "
                    "'2026-08-27T00:02:00+00:00', 0, 'parse_failed') "
                    "RETURNING id"
                ),
                {
                    "filing_id": filing_id,
                    "operation_id": operation_id,
                    "hash": "9" * 64,
                },
            ).scalar_one()
            cross_identity_violations = (
                (
                    text(
                        "INSERT INTO sec_submission_snapshots "
                        "(issuer_identity_id, operation_id, source_url, sha256, "
                        "byte_size, storage_key, fetched_at, known_at) VALUES "
                        "(:identity_id, :operation_id, :source_url, :hash, 2, "
                        ":storage_key, '2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:02:00+00:00')"
                    ),
                    {
                        "identity_id": identity_id,
                        "operation_id": other_operation_id,
                        "source_url": "https://data.sec.gov/submissions/CIK0000000099.json",
                        "hash": "7" * 64,
                        "storage_key": "financial/77/" + "7" * 64,
                    },
                    "matching unsealed SEC operation",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_parse_runs "
                        "(filing_id, operation_id, parser_name, parser_version, "
                        "input_manifest_hash, status, started_at, completed_at, "
                        "known_at, fact_count, error_code) VALUES "
                        "(:filing_id, :operation_id, 'fixture', 'cross-owner', "
                        ":hash, 'failed', '2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:02:00+00:00', 0, 'parse_failed')"
                    ),
                    {
                        "filing_id": filing_id,
                        "operation_id": other_operation_id,
                        "hash": "8" * 64,
                    },
                    "matching unsealed SEC operation",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_acquisition_failures "
                        "(operation_id, submission_snapshot_id, stage, error_code) VALUES "
                        "(:operation_id, :snapshot_id, 'submissions_parse', "
                        "'invalid_main_submissions_payload')"
                    ),
                    {
                        "operation_id": other_operation_id,
                        "snapshot_id": snapshot_id,
                    },
                    "operation-linked snapshot",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_acquisition_failures "
                        "(operation_id, submission_snapshot_id, stage, error_code) VALUES "
                        "(:operation_id, :snapshot_id, 'submissions_parse', "
                        "'invalid_main_submissions_payload')"
                    ),
                    {
                        "operation_id": unlinked_same_identity_operation_id,
                        "snapshot_id": snapshot_id,
                    },
                    "operation-linked snapshot",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_operation_snapshots "
                        "(operation_id, snapshot_id) VALUES "
                        "(:operation_id, :snapshot_id)"
                    ),
                    {
                        "operation_id": other_operation_id,
                        "snapshot_id": snapshot_id,
                    },
                    "invalid or sealed SEC operation snapshot link",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_operation_results "
                        "(operation_id, result_kind, parse_run_id) VALUES "
                        "(:operation_id, 'parse_run', :parse_run_id)"
                    ),
                    {
                        "operation_id": other_operation_id,
                        "parse_run_id": owned_failed_run_id,
                    },
                    "unavailable parse lineage",
                ),
            )
            for statement, parameters, expected_error in cross_identity_violations:
                savepoint = connection.begin_nested()
                try:
                    connection.execute(statement, parameters)
                except Exception as exc:
                    assert expected_error in str(exc)
                    savepoint.rollback()
                else:
                    savepoint.rollback()
                    raise AssertionError("cross-stock SEC operation lineage was accepted")
            scoped_lineage_violations = (
                (
                    text(
                        "INSERT INTO sec_financial_acquisition_failures "
                        "(operation_id, submission_snapshot_id, stage, error_code, "
                        "resource_role, resource_key) VALUES "
                        "(:operation_id, :snapshot_id, 'submissions_parse', "
                        "'invalid_main_submissions_payload', 'main_submissions', "
                        "'https://evil.example/submissions.json')"
                    ),
                    "exact failed artifact observation",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_acquisition_resolutions "
                        "(operation_id, resource_role, resource_key, resolution_kind, "
                        "submission_snapshot_id) VALUES "
                        "(:operation_id, 'main_submissions', "
                        "'https://evil.example/submissions.json', "
                        "'resource_validated', :snapshot_id)"
                    ),
                    "exact operation-linked snapshot",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_acquisition_resolutions "
                        "(operation_id, resource_role, resource_key, resolution_kind, "
                        "parse_run_id, accession_no) VALUES "
                        "(:operation_id, 'accession_terminal', "
                        "'0000000099-26-999999', 'parse_failed', :parse_run_id, "
                        "'0000000099-26-999999')"
                    ),
                    "current operation accession attempt",
                ),
                (
                    text(
                        "INSERT INTO sec_financial_accession_attempts "
                        "(operation_id, filing_id, accession_no, index_resource_key, "
                        "outcome, index_sha256, input_manifest_hash, parse_run_id) "
                        "VALUES (:other_operation_id, :filing_id, "
                        "'0000000099-26-000001', "
                        "'https://www.sec.gov/Archives/edgar/data/99/000000009926000001/index.json', 'parse_failed', "
                        ":index_hash, :manifest_hash, :parse_run_id)"
                    ),
                    "owned or replayable exact run",
                ),
            )
            for statement, expected_error in scoped_lineage_violations:
                savepoint = connection.begin_nested()
                try:
                    connection.execute(
                        statement,
                        {
                            "operation_id": operation_id,
                            "snapshot_id": snapshot_id,
                            "parse_run_id": owned_failed_run_id,
                            "other_operation_id": unlinked_same_identity_operation_id,
                            "filing_id": filing_id,
                            "index_hash": "4" * 64,
                            "manifest_hash": "9" * 64,
                        },
                    )
                except Exception as exc:
                    assert expected_error in str(exc)
                    savepoint.rollback()
                else:
                    savepoint.rollback()
                    raise AssertionError("unscoped SEC acquisition lineage was accepted")
            connection.execute(
                text(
                    "INSERT INTO sec_submission_snapshots "
                    "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                    "storage_key, fetched_at, known_at) VALUES "
                    "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                    "'2026-08-27T00:01:00+00:00', "
                    "'2026-08-27T00:01:00+00:00')"
                ),
                {
                    "identity_id": identity_id,
                    "operation_id": operation_id,
                    "source_url": (
                        "https://data.sec.gov/submissions/"
                        "CIK0000000099-submissions-001.json"
                    ),
                    "hash": "5" * 64,
                    "storage_key": "financial/55/" + "5" * 64,
                },
            )
            unreviewed_identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000100', 'needs_review', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": stock_id},
            ).scalar_one()

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_ingestion_operations "
                        "(id, issuer_identity_id, attempted_at) VALUES "
                        "(:operation_id, :identity_id, clock_timestamp())"
                    ),
                    {
                        "identity_id": unreviewed_identity_id,
                        "operation_id": str(uuid.uuid4()),
                    },
                )
        except Exception as exc:
            assert "current reviewed SEC issuer identity" in str(exc)
        else:
            raise AssertionError("unreviewed SEC ingestion operation was accepted")

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_submission_snapshots "
                        "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                        "storage_key, fetched_at, known_at) VALUES "
                        "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                        "'2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:01:00+00:00')"
                    ),
                    {
                        "identity_id": identity_id,
                        "operation_id": operation_id,
                        "source_url": (
                            "https://data.sec.gov/submissions/CIK0000000099.json"
                        ),
                        "hash": "8" * 64,
                        "storage_key": "financial/88/" + "8" * 64,
                    },
                )
        except Exception as exc:
            assert "ck_sec_submission_snapshots_knowledge_order" in str(exc)
        else:
            raise AssertionError("pre-fetch SEC snapshot knowledge was accepted")

        invalid_snapshot_shapes = (
            (
                "A" * 64,
                "financial/AA/" + "A" * 64,
                "https://data.sec.gov/submissions/CIK0000000099.json",
                "ck_sec_submission_snapshots_sha256",
            ),
            (
                "1" * 64,
                "financial/ff/" + "1" * 64,
                "https://data.sec.gov/submissions/CIK0000000099.json",
                "ck_sec_submission_snapshots_storage_key",
            ),
            (
                "2" * 64,
                "financial/22/" + "2" * 64,
                "https://evil.example/submissions/CIK0000000099.json",
                "canonical SEC submissions source URL",
            ),
            (
                "3" * 64,
                "financial/33/" + "3" * 64,
                "https://data.sec.gov/submissions/../CIK0000000099.json",
                "canonical SEC submissions source URL",
            ),
        )
        for invalid_hash, invalid_key, invalid_url, expected_error in (
            invalid_snapshot_shapes
        ):
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO sec_submission_snapshots "
                            "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                            "storage_key, fetched_at, known_at) VALUES "
                            "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                            "'2026-08-27T00:03:00+00:00', "
                            "'2026-08-27T00:03:00+00:00')"
                        ),
                        {
                            "identity_id": identity_id,
                            "operation_id": operation_id,
                            "source_url": invalid_url,
                            "hash": invalid_hash,
                            "storage_key": invalid_key,
                        },
                    )
            except Exception as exc:
                assert expected_error in str(exc)
            else:
                raise AssertionError(
                    "invalid SEC snapshot shape was accepted: "
                    f"hash={invalid_hash} key={invalid_key} url={invalid_url} "
                    f"expected={expected_error}"
                )

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_submission_snapshots "
                        "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                        "storage_key, fetched_at, known_at) VALUES "
                        "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                        "'2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:02:00+00:00')"
                    ),
                    {
                        "identity_id": identity_id,
                        "operation_id": operation_id,
                        "source_url": (
                            "https://data.sec.gov/submissions/CIK0000000099.json"
                        ),
                        "hash": "6" * 64,
                        "storage_key": "financial/66/" + "6" * 64,
                    },
                )
        except Exception as exc:
            assert "uq_sec_submission_snapshot_content" in str(exc)
        else:
            raise AssertionError("duplicate SEC submissions snapshot was accepted")

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE sec_submission_snapshots SET byte_size = 3 "
                        "WHERE id = :snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
        except Exception as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("SEC submissions snapshot UPDATE unexpectedly succeeded")

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "DELETE FROM sec_submission_snapshots "
                        "WHERE id = :snapshot_id"
                    ),
                    {"snapshot_id": snapshot_id},
                )
        except Exception as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("SEC submissions snapshot DELETE unexpectedly succeeded")

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_filings "
                        "(issuer_identity_id, accession_no, form_type, is_amendment, "
                        "filed_on, report_date, accepted_at, known_at, primary_document, "
                        "index_url, source_url, submissions_source_url, "
                        "discovery_payload_sha256) VALUES "
                        "(:identity_id, '0000000099-26-000002', '10-Q', false, "
                        "'2026-08-02', '2026-08-03', "
                        "'2026-08-01T16:00:00+00:00', "
                        "'2026-08-27T00:01:00+00:00', 'invalid.htm', "
                        "'https://www.sec.gov/invalid/index.json', "
                        "'https://www.sec.gov/invalid/invalid.htm', "
                        "'https://data.sec.gov/submissions/CIK0000000099.json', :hash)"
                    ),
                    {"identity_id": identity_id, "hash": "9" * 64},
                )
        except Exception as exc:
            assert "ck_sec_financial_filings_period_order" in str(exc)
        else:
            raise AssertionError("impossible SEC filing period metadata was accepted")

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_parse_runs "
                        "(filing_id, operation_id, parser_name, parser_version, input_manifest_hash, "
                        "status, started_at, completed_at, known_at, fact_count) "
                        "VALUES (:filing_id, :operation_id, 'fixture', 'mismatch', :hash, 'succeeded', "
                        "'2026-08-27T00:02:00+00:00', '2026-08-27T00:02:00+00:00', "
                        "'2026-08-27T00:02:00+00:00', 1)"
                    ),
                    {"filing_id": filing_id, "operation_id": operation_id, "hash": "b" * 64},
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
                        "'https://www.sec.gov/Archives/edgar/data/99/000000009926000001/fixture.htm', :manifest_hash, "
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
                        "(filing_id, operation_id, parser_name, parser_version, input_manifest_hash, "
                        "status, started_at, completed_at, known_at, fact_count) "
                        "VALUES (:filing_id, :operation_id, 'fixture', 'exact-count', :hash, "
                        "'succeeded', '2026-08-27T00:03:00+00:00', "
                        "'2026-08-27T00:03:00+00:00', "
                        "'2026-08-27T00:03:00+00:00', 1) RETURNING id"
                    ),
                    {"filing_id": filing_id, "operation_id": operation_id, "hash": "e" * 64},
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
                    "'https://www.sec.gov/Archives/edgar/data/99/000000009926000001/atomic-primary.htm', :manifest_hash, "
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
                    "'https://www.sec.gov/Archives/edgar/data/99/000000009926000001/atomic-late.xml', :manifest_hash, "
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
                    "(filing_id, operation_id, parser_name, parser_version, input_manifest_hash, "
                    "status, started_at, completed_at, known_at, fact_count) "
                    "VALUES (:filing_id, :operation_id, 'fixture', 'atomic-inputs', :hash, "
                    "'succeeded', '2026-08-27T00:05:00+00:00', "
                    "'2026-08-27T00:05:00+00:00', "
                    "'2026-08-27T00:05:00+00:00', 1) "
                    "RETURNING id, known_at, created_at, created_txid"
                ),
                {"filing_id": filing_id, "operation_id": operation_id, "hash": "3" * 64},
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

        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO sec_issuer_identities "
                        "(stock_id, cik, status, effective_from, known_at) "
                        "VALUES (:stock_id, '0000000.*?', 'needs_review', "
                        "'2020-01-01', '2026-08-27T01:00:00+00:00')"
                    ),
                    {"stock_id": stock_id},
                )
        except Exception as exc:
            assert "ck_sec_issuer_identities_cik" in str(exc)
        else:
            raise AssertionError("metacharacter SEC issuer CIK was accepted")

    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_sec_filing_artifact_urls_are_exact_canonical_archives_urls(db_session) -> None:
    stock_id = db_session.execute(
        text(
            "INSERT INTO stocks "
            "(ticker, exchange, market_country, company_name, is_active) VALUES "
            "('URLGUARD', 'US', 'US', 'URL Guard Fixture', true) RETURNING id"
        )
    ).scalar_one()
    identity_id = db_session.execute(
        text(
            "INSERT INTO sec_issuer_identities "
            "(stock_id, cik, status, review_reason, effective_from, known_at) VALUES "
            "(:stock_id, '0000000091', 'reviewed', 'URL guard fixture', "
            "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
        ),
        {"stock_id": stock_id},
    ).scalar_one()
    filing_id = db_session.execute(
        text(
            "INSERT INTO sec_financial_filings "
            "(issuer_identity_id, accession_no, form_type, is_amendment, filed_on, "
            "report_date, accepted_at, known_at, primary_document, index_url, "
            "source_url, submissions_source_url, discovery_payload_sha256) VALUES "
            "(:identity_id, '0000000091-26-000001', '10-Q', false, '2026-07-31', "
            "'2026-06-30', '2026-07-31T16:00:00+00:00', "
            "'2026-08-27T00:01:00+00:00', 'fixture.htm', "
            "'https://www.sec.gov/Archives/edgar/data/91/000000009126000001/index.json', "
            "'https://www.sec.gov/Archives/edgar/data/91/000000009126000001/fixture.htm', "
            "'https://data.sec.gov/submissions/CIK0000000091.json', :sha) RETURNING id"
        ),
        {"identity_id": identity_id, "sha": "1" * 64},
    ).scalar_one()
    canonical_root = (
        "https://www.sec.gov/Archives/edgar/data/91/000000009126000001"
    )
    for sequence, filename, url in (
        (0, "__accession_index__.json", f"{canonical_root}/index.json"),
        (1, "fixture.htm", f"{canonical_root}/fixture.htm"),
    ):
        db_session.execute(
            text(
                "INSERT INTO sec_filing_artifacts "
                "(filing_id, sequence, filename, source_url, manifest_hash, state, "
                "reason_code, known_at) VALUES "
                "(:filing_id, :sequence, :filename, :url, :manifest, "
                "'manifest_only', 'artifact_type_not_in_ft03_retention_scope', "
                "'2026-08-27T00:02:00+00:00')"
            ),
            {
                "filing_id": filing_id,
                "sequence": sequence,
                "filename": filename,
                "url": url,
                "manifest": str(sequence + 2) * 64,
            },
        )
    db_session.commit()

    invalid_urls = (
        "https://evil.example/Archives/edgar/data/91/000000009126000001/evil.htm",
        "https://user@www.sec.gov/Archives/edgar/data/91/000000009126000001/evil.htm",
        "https://www.sec.gov:443/Archives/edgar/data/91/000000009126000001/evil.htm",
        f"{canonical_root}/evil.htm?download=1",
        f"{canonical_root}/evil.htm#fragment",
        "https://WWW.sec.gov/Archives/edgar/data/91/000000009126000001/evil.htm",
        "https://www.sec.gov/archives/edgar/data/91/000000009126000001/evil.htm",
        f"{canonical_root}/%2e%2e/evil.htm",
        f"{canonical_root}/../evil.htm",
    )
    for invalid_url in invalid_urls:
        nested = db_session.begin_nested()
        try:
            db_session.execute(
                text(
                    "INSERT INTO sec_filing_artifacts "
                    "(filing_id, sequence, filename, source_url, manifest_hash, state, "
                    "reason_code, known_at) VALUES "
                    "(:filing_id, 2, 'evil.htm', :url, :manifest, 'manifest_only', "
                    "'artifact_type_not_in_ft03_retention_scope', "
                    "'2026-08-27T00:02:00+00:00')"
                ),
                {
                    "filing_id": filing_id,
                    "url": invalid_url,
                    "manifest": hashlib.sha256(invalid_url.encode()).hexdigest(),
                },
            )
        except Exception as exc:
            assert "canonical SEC Archives URL" in str(exc)
            nested.rollback()
        else:
            nested.rollback()
            raise AssertionError(f"noncanonical SEC artifact URL accepted: {invalid_url}")


def test_sec_financial_lineage_empty_migration_round_trip() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", PARENT_REVISION)
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_submission_snapshots")

        engine.dispose()
        _alembic(backend_dir, database_url, "downgrade", PARENT_REVISION)
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_financial_filings") is False

        engine.dispose()
        _alembic(backend_dir, database_url, "upgrade", "head")
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            assert inspect(connection).has_table("sec_financial_parse_run_artifacts")
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_submission_snapshot_downgrade_refuses_nonempty_table() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('DOWNSEC', 'US', 'US', 'Downgrade SEC Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, review_reason, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000096', 'reviewed', 'downgrade test', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": stock_id},
            ).scalar_one()
            operation_id = _insert_ingestion_operation(connection, identity_id)
            connection.execute(
                text(
                    "INSERT INTO sec_submission_snapshots "
                    "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                    "storage_key, fetched_at, known_at) VALUES "
                    "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                    "'2026-08-27T00:01:00+00:00', "
                    "'2026-08-27T00:01:00+00:00')"
                ),
                {
                    "identity_id": identity_id,
                    "operation_id": operation_id,
                    "source_url": (
                        "https://data.sec.gov/submissions/CIK0000000096.json"
                    ),
                    "hash": "4" * 64,
                    "storage_key": "financial/44/" + "4" * 64,
                },
            )

        result = subprocess.run(
            ["alembic", "downgrade", "20260830120000"],
            cwd=backend_dir,
            env={**os.environ, "DATABASE_URL": database_url},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert "cannot downgrade with retained SEC submissions snapshots" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == HEAD_REVISION
            assert "sec_submission_snapshots" in inspect(connection).get_table_names()
            assert connection.execute(
                text("SELECT count(*) FROM sec_submission_snapshots")
            ).scalar_one() == 1
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_submission_snapshot_downgrade_locks_before_nonempty_preflight() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    _alembic(backend_dir, database_url, "upgrade", "head")
    with engine.begin() as connection:
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker, exchange, market_country, company_name, is_active) "
                "VALUES ('LOCKSEC', 'US', 'US', 'Locked Downgrade Fixture', true) "
                "RETURNING id"
            )
        ).scalar_one()
        identity_id = connection.execute(
            text(
                "INSERT INTO sec_issuer_identities "
                "(stock_id, cik, status, review_reason, effective_from, known_at) "
                "VALUES (:stock_id, '0000000094', 'reviewed', 'lock test', "
                "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
            ),
            {"stock_id": stock_id},
        ).scalar_one()
        operation_id = _insert_ingestion_operation(connection, identity_id)

    connection_a = engine.connect()
    transaction_a = connection_a.begin()
    process: subprocess.Popen[str] | None = None
    try:
        connection_a.execute(
            text(
                "INSERT INTO sec_submission_snapshots "
                "(issuer_identity_id, operation_id, source_url, sha256, byte_size, storage_key, "
                "fetched_at, known_at) VALUES "
                "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                "'2026-08-27T00:01:00+00:00', '2026-08-27T00:01:00+00:00')"
            ),
            {
                "identity_id": identity_id,
                "operation_id": operation_id,
                "source_url": (
                    "https://data.sec.gov/submissions/CIK0000000094.json"
                ),
                "hash": "3" * 64,
                "storage_key": "financial/33/" + "3" * 64,
            },
        )
        process = subprocess.Popen(
            ["alembic", "downgrade", "20260830120000"],
            cwd=backend_dir,
            env={**os.environ, "DATABASE_URL": database_url},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Event().wait(1.0)
        assert process.poll() is None, (
            "downgrade did not wait for the uncommitted snapshot writer"
        )
        transaction_a.commit()
        stdout, stderr = process.communicate(timeout=15.0)
        assert process.returncode != 0
        assert "cannot downgrade with retained SEC submissions snapshots" in (
            stdout + stderr
        )
        with engine.connect() as verify:
            assert verify.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == HEAD_REVISION
            assert inspect(verify).has_table("sec_submission_snapshots")
            assert verify.execute(
                text("SELECT count(*) FROM sec_submission_snapshots")
            ).scalar_one() == 1
    finally:
        if transaction_a.is_active:
            transaction_a.rollback()
        connection_a.close()
        if process is not None and process.poll() is None:
            process.terminate()
            process.communicate(timeout=10.0)
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_submission_snapshot_migration_rejects_existing_nondigit_cik() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260830120000")
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('BADCIK', 'US', 'US', 'Bad CIK Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000.*?', 'needs_review', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00')"
                ),
                {"stock_id": stock_id},
            )

        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=backend_dir,
            env={**os.environ, "DATABASE_URL": database_url},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "CIK is not exactly 10 ASCII digits" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "20260830120000"
            assert not inspect(connection).has_table("sec_submission_snapshots")
            checks = {
                item["name"]
                for item in inspect(connection).get_check_constraints(
                    "sec_issuer_identities"
                )
            }
            assert "ck_sec_issuer_identities_cik" not in checks
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_snapshot_insert_serializes_with_backdated_identity_retirement() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    _alembic(backend_dir, database_url, "upgrade", "head")
    with engine.begin() as connection:
        stock_id = connection.execute(
            text(
                "INSERT INTO stocks "
                "(ticker, exchange, market_country, company_name, is_active) "
                "VALUES ('RACESEC', 'US', 'US', 'Race SEC Fixture', true) "
                "RETURNING id"
            )
        ).scalar_one()
        identity_id = connection.execute(
            text(
                "INSERT INTO sec_issuer_identities "
                "(stock_id, cik, status, review_reason, effective_from, known_at) "
                "VALUES (:stock_id, '0000000095', 'reviewed', 'race test', "
                "'2020-01-01', '2026-08-27T12:00:00+00:00') RETURNING id"
            ),
            {"stock_id": stock_id},
        ).scalar_one()
        operation_id = _insert_ingestion_operation(connection, identity_id)

    connection_a = engine.connect()
    transaction_a = connection_a.begin()
    b_done = threading.Event()
    b_errors: list[Exception] = []

    def retire_in_b() -> None:
        try:
            with engine.begin() as connection_b:
                connection_b.execute(
                    text(
                        "INSERT INTO sec_issuer_identities "
                        "(stock_id, cik, status, review_reason, effective_from, "
                        "known_at, supersedes_identity_id) VALUES "
                        "(:stock_id, '0000000095', 'retired', 'race retirement', "
                        "'2020-01-01', '2026-08-27T12:05:00+00:00', :identity_id)"
                    ),
                    {"stock_id": stock_id, "identity_id": identity_id},
                )
        except Exception as exc:  # expected fail-closed result
            b_errors.append(exc)
        finally:
            b_done.set()

    thread = threading.Thread(target=retire_in_b)
    try:
        connection_a.execute(
            text(
                "INSERT INTO sec_submission_snapshots "
                "(issuer_identity_id, operation_id, source_url, sha256, byte_size, storage_key, "
                "fetched_at, known_at) VALUES "
                "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                "'2026-08-27T12:10:00+00:00', '2026-08-27T12:10:00+00:00')"
            ),
            {
                "identity_id": identity_id,
                "operation_id": operation_id,
                "source_url": (
                    "https://data.sec.gov/submissions/CIK0000000095.json"
                ),
                "hash": "9" * 64,
                "storage_key": "financial/99/" + "9" * 64,
            },
        )
        thread.start()
        assert not b_done.wait(timeout=1.0), (
            "identity retirement bypassed the snapshot identity lock"
        )
        transaction_a.commit()
        assert b_done.wait(timeout=10.0), (
            "identity retirement did not finish after snapshot commit"
        )
        thread.join(timeout=10.0)
        assert len(b_errors) == 1
        assert "predates persisted SEC lineage" in str(b_errors[0])
        with engine.connect() as verify:
            assert verify.execute(
                text(
                    "SELECT count(*) FROM sec_issuer_identities "
                    "WHERE supersedes_identity_id = :identity_id"
                ),
                {"identity_id": identity_id},
            ).scalar_one() == 0
            assert verify.execute(
                text("SELECT count(*) FROM sec_submission_snapshots")
            ).scalar_one() == 1
    finally:
        if transaction_a.is_active:
            transaction_a.rollback()
        connection_a.close()
        if thread.is_alive():
            thread.join(timeout=10.0)
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_lineage_visibility_requires_post_commit_availability_marker(
    tmp_path: Path,
) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    _alembic(backend_dir, database_url, "upgrade", "head")
    with engine.begin() as seed:
        stock_id = seed.execute(
            text(
                "INSERT INTO stocks "
                "(ticker, exchange, market_country, company_name, is_active) "
                "VALUES ('VISSEC', 'US', 'US', 'Visibility Fixture', true) "
                "RETURNING id"
            )
        ).scalar_one()
        identity_id = seed.execute(
            text(
                "INSERT INTO sec_issuer_identities "
                "(stock_id, cik, status, review_reason, effective_from, known_at) "
                "VALUES (:stock_id, '0000000093', 'reviewed', 'visibility test', "
                "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
            ),
            {"stock_id": stock_id},
        ).scalar_one()

    connection_a = engine.connect()
    transaction_a = connection_a.begin()
    operation_id = str(uuid.uuid4())
    try:
        operation_stamp = connection_a.execute(
            text(
                "INSERT INTO sec_financial_ingestion_operations "
                "(id, issuer_identity_id, attempted_at, created_txid, created_at) VALUES "
                "(:operation_id, :identity_id, '2000-01-01T00:00:00+00:00', "
                "1, '2000-01-01T00:00:00+00:00') "
                "RETURNING attempted_at, created_txid, created_at"
            ),
            {"operation_id": operation_id, "identity_id": identity_id},
        ).mappings().one()
        assert operation_stamp["attempted_at"].year != 2000
        assert operation_stamp["attempted_at"] == operation_stamp["created_at"]
        assert operation_stamp["created_txid"] != 1
        assert operation_stamp["created_at"].year != 2000
        snapshot_id = connection_a.execute(
            text(
                "INSERT INTO sec_submission_snapshots "
                "(issuer_identity_id, operation_id, source_url, sha256, byte_size, "
                "storage_key, fetched_at, known_at) VALUES "
                "(:identity_id, :operation_id, :source_url, :hash, 2, :storage_key, "
                "'2026-08-27T00:01:00+00:00', '2026-08-27T00:01:00+00:00') "
                "RETURNING id"
            ),
            {
                "identity_id": identity_id,
                "operation_id": operation_id,
                "source_url": "https://data.sec.gov/submissions/CIK0000000093.json",
                "hash": "5" * 64,
                "storage_key": "financial/55/" + "5" * 64,
            },
        ).scalar_one()
        connection_a.execute(
            text(
                "INSERT INTO sec_financial_operation_snapshots "
                "(operation_id, snapshot_id) VALUES "
                "(:operation_id, :snapshot_id)"
            ),
            {"operation_id": operation_id, "snapshot_id": snapshot_id},
        )
        filing_id = connection_a.execute(
            text(
                "INSERT INTO sec_financial_filings "
                "(issuer_identity_id, accession_no, form_type, is_amendment, "
                "filed_on, report_date, accepted_at, known_at, primary_document, "
                "index_url, source_url, submissions_source_url, discovery_payload_sha256) "
                "VALUES (:identity_id, '0000000093-26-000001', '10-Q', false, "
                "'2026-07-31', '2026-06-30', '2026-07-31T16:00:00+00:00', "
                "'2026-08-27T00:01:00+00:00', 'fixture.htm', "
                "'https://www.sec.gov/Archives/edgar/data/93/000000009326000001/index.json', "
                "'https://www.sec.gov/Archives/edgar/data/93/000000009326000001/fixture.htm', "
                "'https://data.sec.gov/submissions/CIK0000000093.json', :hash) "
                "RETURNING id"
            ),
            {"identity_id": identity_id, "hash": "1" * 64},
        ).scalar_one()
        artifact_id = connection_a.execute(
            text(
                "INSERT INTO sec_filing_artifacts "
                "(filing_id, sequence, filename, declared_size, source_url, "
                "manifest_hash, state, content_mime, sha256, byte_size, storage_key, "
                "fetched_at, known_at) VALUES "
                "(:filing_id, 0, 'index.json', 1, "
                "'https://www.sec.gov/Archives/edgar/data/93/000000009326000001/index.json', :manifest_hash, "
                "'retained', 'text/html', :sha256, 1, :storage_key, "
                "'2026-08-27T00:02:00+00:00', '2026-08-27T00:02:00+00:00') "
                "RETURNING id"
            ),
            {
                "filing_id": filing_id,
                "manifest_hash": "2" * 64,
                "sha256": "de7d1b721a1e0632b7cf04edf5032c8ecffa9f9a08492152b926f1a5a7e765d7",
                "storage_key": (
                    "sha256/de/"
                    "de7d1b721a1e0632b7cf04edf5032c8ecffa9f9a08492152b926f1a5a7e765d7"
                ),
            },
        ).scalar_one()
        retained_path = (
            tmp_path
            / "sha256/de/"
            / "de7d1b721a1e0632b7cf04edf5032c8ecffa9f9a08492152b926f1a5a7e765d7"
        )
        retained_path.parent.mkdir(parents=True)
        retained_path.write_bytes(b"i")
        run_id = connection_a.execute(
            text(
                "INSERT INTO sec_financial_parse_runs "
                "(filing_id, operation_id, parser_name, parser_version, "
                "input_manifest_hash, status, started_at, completed_at, known_at, "
                "fact_count) VALUES (:filing_id, :operation_id, 'fixture', 'v1', "
                ":hash, 'succeeded', '2026-08-27T00:03:00+00:00', "
                "'2026-08-27T00:03:00+00:00', '2026-08-27T00:03:00+00:00', 1) "
                "RETURNING id"
            ),
            {
                "filing_id": filing_id,
                "operation_id": operation_id,
                "hash": "4" * 64,
            },
        ).scalar_one()
        connection_a.execute(
            text(
                "INSERT INTO sec_financial_parse_run_artifacts "
                "(parse_run_id, artifact_id, known_at) VALUES "
                "(:run_id, :artifact_id, '2026-08-27T00:03:00+00:00')"
            ),
            {"run_id": run_id, "artifact_id": artifact_id},
        )
        attempt_stamp = connection_a.execute(
            text(
                "INSERT INTO sec_financial_accession_attempts "
                "(operation_id, filing_id, accession_no, index_resource_key, "
                "outcome, index_sha256, input_manifest_hash, parse_run_id, "
                "attempted_at, created_at, created_txid) VALUES "
                "(:operation_id, :filing_id, '0000000093-26-000001', "
                "'https://www.sec.gov/Archives/edgar/data/93/000000009326000001/index.json', 'parse_succeeded', "
                ":index_hash, :manifest_hash, :run_id, "
                "'2000-01-01T00:00:00+00:00', "
                "'2000-01-01T00:00:00+00:00', 1) "
                "RETURNING id, attempted_at, created_at, created_txid"
            ),
            {
                "operation_id": operation_id,
                "filing_id": filing_id,
                "index_hash": "de7d1b721a1e0632b7cf04edf5032c8ecffa9f9a08492152b926f1a5a7e765d7",
                "manifest_hash": "4" * 64,
                "run_id": run_id,
            },
        ).mappings().one()
        attempt_id = attempt_stamp["id"]
        assert attempt_stamp["attempted_at"].year != 2000
        assert attempt_stamp["created_at"] == attempt_stamp["attempted_at"]
        assert attempt_stamp["created_txid"] != 1
        connection_a.execute(
            text(
                "INSERT INTO sec_financial_accession_attempt_artifacts "
                "(attempt_id, artifact_id) VALUES (:attempt_id, :artifact_id)"
            ),
            {
                "attempt_id": attempt_id,
                "artifact_id": artifact_id,
            },
        )
        connection_a.execute(
            text(
                "INSERT INTO sec_financial_acquisition_resolutions "
                "(operation_id, resource_role, resource_key, resolution_kind, "
                "parse_run_id, accession_attempt_id, accession_no) VALUES "
                "(:operation_id, 'accession_terminal', '0000000093-26-000001', "
                "'parse_succeeded', :run_id, :attempt_id, "
                "'0000000093-26-000001')"
            ),
            {
                "operation_id": operation_id,
                "run_id": run_id,
                "attempt_id": attempt_id,
            },
        )
        connection_a.execute(
            text(
                "INSERT INTO sec_financial_operation_results "
                "(operation_id, result_kind, parse_run_id) VALUES "
                "(:operation_id, 'parse_run', :run_id)"
            ),
            {"operation_id": operation_id, "run_id": run_id},
        )

        invalid_finalize = connection_a.begin_nested()
        try:
            connection_a.execute(
                text(
                    "INSERT INTO sec_financial_lineage_availabilities "
                    "(operation_id, available_at, finalized_txid) VALUES "
                    "(:operation_id, '2000-01-01T00:00:00+00:00', 1)"
                ),
                {"operation_id": operation_id},
            )
        except Exception as exc:
            assert "committed ingestion operation" in str(exc)
            invalid_finalize.rollback()
        else:
            invalid_finalize.rollback()
            raise AssertionError("same-transaction availability was accepted")
        connection_a.execute(
            text(
                "INSERT INTO sec_raw_xbrl_facts "
                "(parse_run_id, artifact_id, ordinal, concept, locator_json) VALUES "
                "(:run_id, :artifact_id, 1, 'us-gaap:Assets', '{}'::jsonb)"
            ),
            {"run_id": run_id, "artifact_id": artifact_id},
        )

        with engine.connect() as observer:
            cutoff_during_ingest = observer.execute(
                text("SELECT clock_timestamp()")
            ).scalar_one()
            with Session(bind=observer) as session:
                assert select_sec_financial_evidence_as_of(
                    session,
                    stock_id=stock_id,
                    cutoff=cutoff_during_ingest,
                    storage_root=tmp_path,
                ) == []
        transaction_a.commit()

        with Session(engine) as session:
            cutoff_before_finalize = session.execute(
                text("SELECT clock_timestamp()")
            ).scalar_one()
            assert select_sec_financial_evidence_as_of(
                session,
                stock_id=stock_id,
                cutoff=cutoff_during_ingest,
                storage_root=tmp_path,
            ) == []
            assert select_sec_financial_evidence_as_of(
                session,
                stock_id=stock_id,
                cutoff=cutoff_before_finalize,
                storage_root=tmp_path,
            ) == []
            availability_stamp = session.execute(
                text(
                    "INSERT INTO sec_financial_lineage_availabilities "
                    "(operation_id, available_at, finalized_txid) VALUES "
                    "(:operation_id, '2000-01-01T00:00:00+00:00', 1) "
                    "RETURNING available_at, finalized_txid"
                ),
                {"operation_id": operation_id},
            ).mappings().one()
            available_at = availability_stamp["available_at"]
            assert available_at.year != 2000
            assert availability_stamp["finalized_txid"] != 1
            assert (
                availability_stamp["finalized_txid"]
                != operation_stamp["created_txid"]
            )
            session.commit()

        with Session(engine) as session:
            assert select_sec_financial_evidence_as_of(
                session,
                stock_id=stock_id,
                cutoff=available_at - timedelta(microseconds=1),
                storage_root=tmp_path,
            ) == []
            assert select_sec_financial_evidence_as_of(
                session,
                stock_id=stock_id,
                cutoff=available_at,
                storage_root=tmp_path,
            )
            assert finalize_sec_financial_ingestion_operation(
                session, operation_id=operation_id
            ) == available_at
            session.commit()
    finally:
        if transaction_a.is_active:
            transaction_a.rollback()
        connection_a.close()
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_upgrade_marks_only_preexisting_null_operation_parse_runs(
    tmp_path: Path,
) -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", "20260830120000")
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('LEGACYNULL', 'US', 'US', 'Legacy NULL Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, review_reason, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000088', 'reviewed', 'legacy null test', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": stock_id},
            ).scalar_one()
            filing_id = connection.execute(
                text(
                    "INSERT INTO sec_financial_filings "
                    "(issuer_identity_id, accession_no, form_type, is_amendment, "
                    "filed_on, report_date, accepted_at, known_at, primary_document, "
                    "index_url, source_url, submissions_source_url, "
                    "discovery_payload_sha256) VALUES "
                    "(:identity_id, '0000000088-26-000001', '10-Q', false, "
                    "'2026-07-31', '2026-06-30', '2026-07-31T16:00:00+00:00', "
                    "'2026-08-27T00:01:00+00:00', 'legacy.htm', "
                    "'https://www.sec.gov/Archives/edgar/data/88/000000008826000001/index.json', "
                    "'https://www.sec.gov/Archives/edgar/data/88/000000008826000001/legacy.htm', "
                    "'https://data.sec.gov/submissions/CIK0000000088.json', :hash) "
                    "RETURNING id"
                ),
                {"identity_id": identity_id, "hash": "1" * 64},
            ).scalar_one()
            artifact_id = connection.execute(
                text(
                    "INSERT INTO sec_filing_artifacts "
                    "(filing_id, sequence, filename, source_url, manifest_hash, state, "
                    "content_mime, sha256, byte_size, storage_key, fetched_at, known_at) "
                    "VALUES (:filing_id, 1, 'legacy.htm', "
                    "'https://www.sec.gov/Archives/edgar/data/88/000000008826000001/legacy.htm', :manifest, 'retained', "
                    "'text/html', :sha, 1, :storage, "
                    "'2026-08-27T00:02:00+00:00', '2026-08-27T00:02:00+00:00') "
                    "RETURNING id"
                ),
                {
                    "filing_id": filing_id,
                    "manifest": "2" * 64,
                    "sha": "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
                    "storage": (
                        "sha256/2d/"
                        "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
                    ),
                },
            ).scalar_one()
            retained_path = (
                tmp_path
                / "sha256/2d/"
                / "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
            )
            retained_path.parent.mkdir(parents=True)
            retained_path.write_bytes(b"x")
            legacy_run_id = connection.execute(
                text(
                    "INSERT INTO sec_financial_parse_runs "
                    "(filing_id, parser_name, parser_version, input_manifest_hash, "
                    "status, started_at, completed_at, known_at, fact_count) VALUES "
                    "(:filing_id, 'legacy', 'v1', :hash, 'succeeded', "
                    "'2026-08-27T00:03:00+00:00', '2026-08-27T00:03:00+00:00', "
                    "'2026-08-27T00:03:00+00:00', 1) RETURNING id"
                ),
                {"filing_id": filing_id, "hash": "4" * 64},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO sec_financial_parse_run_artifacts "
                    "(parse_run_id, artifact_id, known_at) VALUES "
                    "(:run_id, :artifact_id, '2026-08-27T00:03:00+00:00')"
                ),
                {"run_id": legacy_run_id, "artifact_id": artifact_id},
            )
            connection.execute(
                text(
                    "INSERT INTO sec_raw_xbrl_facts "
                    "(parse_run_id, artifact_id, ordinal, concept, locator_json) "
                    "VALUES (:run_id, :artifact_id, 1, 'us-gaap:Assets', '{}'::jsonb)"
                ),
                {"run_id": legacy_run_id, "artifact_id": artifact_id},
            )

        _alembic(backend_dir, database_url, "upgrade", "head")
        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT parse_run_id FROM sec_financial_legacy_parse_runs"
                )
            ).scalar_one() == legacy_run_id
            for mutation in (
                "INSERT INTO sec_financial_legacy_parse_runs (parse_run_id) "
                f"VALUES ({legacy_run_id})",
                "UPDATE sec_financial_legacy_parse_runs SET marked_at = "
                "clock_timestamp()",
                "DELETE FROM sec_financial_legacy_parse_runs",
            ):
                invalid_marker_change = connection.begin_nested()
                try:
                    connection.execute(text(mutation))
                except Exception as exc:
                    assert "append-only" in str(exc)
                    invalid_marker_change.rollback()
                else:
                    invalid_marker_change.rollback()
                    raise AssertionError("legacy parse-run marker was mutable")
            invalid_run = connection.begin_nested()
            try:
                connection.execute(
                    text(
                        "INSERT INTO sec_financial_parse_runs "
                        "(filing_id, operation_id, parser_name, parser_version, "
                        "input_manifest_hash, status, started_at, completed_at, "
                        "known_at, fact_count, error_code) VALUES "
                        "(:filing_id, NULL, 'invalid-null-operation', 'v1', :hash, 'failed', "
                        "clock_timestamp(), clock_timestamp(), clock_timestamp(), 0, "
                        "'parse_failed')"
                    ),
                    {"filing_id": filing_id, "hash": "5" * 64},
                )
            except Exception as exc:
                assert "explicit ingestion operation" in str(exc)
                invalid_run.rollback()
            else:
                invalid_run.rollback()
                raise AssertionError("new NULL-operation parse run was accepted")

        cutoff = datetime.now(timezone.utc) + timedelta(seconds=2)
        with Session(engine) as session:
            assert [row.parse_run_id for row in select_sec_financial_evidence_as_of(
                session,
                stock_id=stock_id,
                cutoff=cutoff,
                storage_root=tmp_path,
            )] == [legacy_run_id]
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_sec_financial_period_migration_fails_closed_on_existing_dirty_data() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", PERIOD_PARENT_REVISION)
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('DIRTYSEC', 'US', 'US', 'Dirty SEC Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, review_reason, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000098', 'reviewed', 'dirty fixture', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": stock_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO sec_financial_filings "
                    "(issuer_identity_id, accession_no, form_type, is_amendment, "
                    "filed_on, report_date, accepted_at, known_at, primary_document, "
                    "index_url, source_url, submissions_source_url, "
                    "discovery_payload_sha256) VALUES "
                    "(:identity_id, '0000000098-26-000001', '10-Q', false, "
                    "'2026-08-02', '2026-08-03', "
                    "'2026-08-01T16:00:00+00:00', "
                    "'2026-08-27T00:01:00+00:00', 'dirty.htm', "
                    "'https://www.sec.gov/dirty/index.json', "
                    "'https://www.sec.gov/dirty/dirty.htm', "
                    "'https://data.sec.gov/submissions/CIK0000000098.json', :hash)"
                ),
                {"identity_id": identity_id, "hash": "8" * 64},
            )
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=backend_dir,
            env={**os.environ, "DATABASE_URL": database_url},
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert "existing SEC financial filing period metadata is invalid" in (
            result.stdout + result.stderr
        )
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PERIOD_PARENT_REVISION
            checks = {
                item["name"]
                for item in inspect(connection).get_check_constraints(
                    "sec_financial_filings"
                )
            }
            assert "ck_sec_financial_filings_period_order" not in checks
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)


def test_sec_financial_period_migration_preserves_valid_after_hours_filing() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(_BASE_DATABASE_URL, schema_name)
    create_test_schema(_BASE_DATABASE_URL, schema_name)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        _alembic(backend_dir, database_url, "upgrade", PERIOD_PARENT_REVISION)
        with engine.begin() as connection:
            stock_id = connection.execute(
                text(
                    "INSERT INTO stocks "
                    "(ticker, exchange, market_country, company_name, is_active) "
                    "VALUES ('LATESEC', 'US', 'US', 'Late SEC Fixture', true) "
                    "RETURNING id"
                )
            ).scalar_one()
            identity_id = connection.execute(
                text(
                    "INSERT INTO sec_issuer_identities "
                    "(stock_id, cik, status, review_reason, effective_from, known_at) "
                    "VALUES (:stock_id, '0000000097', 'reviewed', 'late fixture', "
                    "'2020-01-01', '2026-08-27T00:00:00+00:00') RETURNING id"
                ),
                {"stock_id": stock_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO sec_financial_filings "
                    "(issuer_identity_id, accession_no, form_type, is_amendment, "
                    "filed_on, report_date, accepted_at, known_at, primary_document, "
                    "index_url, source_url, submissions_source_url, "
                    "discovery_payload_sha256) VALUES "
                    "(:identity_id, '0000000097-26-000001', '10-Q', false, "
                    "'2026-08-27', '2026-07-31', "
                    "'2026-08-26T22:54:46+00:00', "
                    "'2026-08-27T00:01:00+00:00', 'late.htm', "
                    "'https://www.sec.gov/late/index.json', "
                    "'https://www.sec.gov/late/late.htm', "
                    "'https://data.sec.gov/submissions/CIK0000000097.json', :hash)"
                ),
                {"identity_id": identity_id, "hash": "7" * 64},
            )

        _alembic(backend_dir, database_url, "upgrade", "head")

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM sec_financial_filings "
                    "WHERE accession_no = '0000000097-26-000001'"
                )
            ).scalar_one() == 1
            checks = {
                item["name"]
                for item in inspect(connection).get_check_constraints(
                    "sec_financial_filings"
                )
            }
            assert "ck_sec_financial_filings_period_order" in checks
    finally:
        engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, schema_name)
