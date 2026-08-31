from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from app.acceptance.sec_gold_environment import (
    AcceptanceEnvironmentError,
    AcceptanceRuntimeConfiguration,
    assert_acceptance_database_identity,
    build_acceptance_environment,
    preflight_acceptance_runtime,
    validate_acceptance_database_name,
    validate_acceptance_storage_target,
)
from app.acceptance.sec_gold_report import (
    SecGoldAcceptanceCaseReport,
    SecGoldSelectedFiling,
    render_human_case_summary,
    write_case_report,
)
from app.acceptance.sec_gold_audit import (
    audit_retained_file,
    build_aggregate_payload,
    build_idempotency_delta,
    render_human_aggregate_summary,
    validate_aggregate_payload,
    write_stable_json,
)
from test_support.database_isolation import build_isolated_database_url


def test_acceptance_environment_derives_exact_isolated_targets(tmp_path: Path) -> None:
    environment = build_acceptance_environment(
        repo_root=tmp_path,
        run_id="step-c-20260830",
    )

    assert environment.run_id == "step-c-20260830"
    assert environment.database_name == "valuepilot_acceptance_step_c_20260830"
    assert environment.database_url == (
        "postgresql://valuepilot:valuepilot@postgres:5432/"
        "valuepilot_acceptance_step_c_20260830"
    )
    assert environment.storage_root == (
        tmp_path / "storage" / "sec_gold_acceptance" / "step-c-20260830"
    )
    assert environment.reports_root == environment.storage_root / "reports"
    validate_acceptance_database_name(environment.database_name)
    validate_acceptance_storage_target(
        repo_root=tmp_path,
        run_id=environment.run_id,
        storage_root=environment.storage_root,
    )


@pytest.mark.parametrize(
    "run_id",
    (
        "valuepilot",
        "UPPERCASE",
        "has_underscore",
        "../escape",
        "a",
        "x" * 33,
    ),
)
def test_acceptance_environment_rejects_ambiguous_run_ids(
    tmp_path: Path,
    run_id: str,
) -> None:
    with pytest.raises(AcceptanceEnvironmentError):
        build_acceptance_environment(repo_root=tmp_path, run_id=run_id)


@pytest.mark.parametrize(
    "database_name",
    ("valuepilot", "valuepilot_prod", "postgres", "template0", "other"),
)
def test_acceptance_database_validator_rejects_non_acceptance_targets(
    database_name: str,
) -> None:
    with pytest.raises(AcceptanceEnvironmentError):
        validate_acceptance_database_name(database_name)


def test_acceptance_runtime_database_identity_requires_configured_and_actual_target() -> None:
    expected = "valuepilot_acceptance_step_c_local_01"

    assert_acceptance_database_identity(
        expected=expected,
        configured=expected,
        actual=expected,
    )
    with pytest.raises(AcceptanceEnvironmentError, match="configured database"):
        assert_acceptance_database_identity(
            expected=expected,
            configured="valuepilot",
            actual=expected,
        )
    with pytest.raises(AcceptanceEnvironmentError, match="connected database"):
        assert_acceptance_database_identity(
            expected=expected,
            configured=expected,
            actual="valuepilot",
        )


def _runtime_configuration(
    tmp_path: Path,
    **overrides,
) -> AcceptanceRuntimeConfiguration:
    environment = build_acceptance_environment(
        repo_root=tmp_path,
        run_id="step-c-runtime",
    )
    if not environment.storage_root.is_symlink():
        environment.storage_root.mkdir(parents=True, exist_ok=True)
    values = {
        "acceptance_mode": True,
        "configured_run_id": environment.run_id,
        "database_url": (
            "postgresql://valuepilot:valuepilot@postgres:5432/"
            + environment.database_name
        ),
        "configured_database_name": environment.database_name,
        "edgar_storage_root": environment.storage_root,
        "configured_storage_root": environment.storage_root,
        "rate_guard_allow_fallback": False,
        "rate_guard_fallback_url": None,
    }
    values.update(overrides)
    return AcceptanceRuntimeConfiguration(**values)


def test_acceptance_runtime_preflight_accepts_only_exact_derived_environment(
    tmp_path: Path,
) -> None:
    environment = preflight_acceptance_runtime(
        repo_root=tmp_path,
        run_id="step-c-runtime",
        configuration=_runtime_configuration(tmp_path),
        current_database=lambda: "valuepilot_acceptance_step_c_runtime",
    )

    assert environment.database_name == "valuepilot_acceptance_step_c_runtime"
    assert environment.storage_root.is_dir()


@pytest.mark.parametrize(
    ("overrides", "actual_database", "message"),
    (
        ({"acceptance_mode": False}, None, "acceptance mode"),
        ({"configured_run_id": "wrong-run"}, None, "run ID"),
        ({"configured_database_name": "valuepilot"}, None, "database"),
        (
            {"database_url": "postgresql://valuepilot:valuepilot@postgres/valuepilot"},
            None,
            "database URL",
        ),
        (
            {
                "database_url": (
                    "postgresql://valuepilot:valuepilot@other-postgres:5432/"
                    "valuepilot_acceptance_step_c_runtime"
                )
            },
            None,
            "database URL",
        ),
        ({"rate_guard_allow_fallback": True}, None, "fallback"),
        ({"rate_guard_fallback_url": "http://rate-guard-local:9000"}, None, "fallback"),
        ({}, "valuepilot", "connected database"),
    ),
)
def test_acceptance_runtime_preflight_rejects_mode_database_and_fallback_mismatch(
    tmp_path: Path,
    overrides: dict,
    actual_database: str | None,
    message: str,
) -> None:
    configuration = _runtime_configuration(tmp_path, **overrides)

    with pytest.raises(AcceptanceEnvironmentError, match=message):
        preflight_acceptance_runtime(
            repo_root=tmp_path,
            run_id="step-c-runtime",
            configuration=configuration,
            current_database=lambda: actual_database
            or "valuepilot_acceptance_step_c_runtime",
        )


def test_acceptance_runtime_preflight_rejects_missing_wrong_and_symlink_storage(
    tmp_path: Path,
) -> None:
    configuration = _runtime_configuration(tmp_path)
    expected = configuration.edgar_storage_root
    expected.rmdir()
    with pytest.raises(AcceptanceEnvironmentError, match="does not exist"):
        preflight_acceptance_runtime(
            repo_root=tmp_path,
            run_id="step-c-runtime",
            configuration=configuration,
            current_database=lambda: "valuepilot_acceptance_step_c_runtime",
        )

    expected.mkdir()
    neighbor = expected.parent / "neighbor"
    neighbor.mkdir()
    wrong = _runtime_configuration(
        tmp_path,
        edgar_storage_root=neighbor,
        configured_storage_root=neighbor,
    )
    with pytest.raises(AcceptanceEnvironmentError, match="storage"):
        preflight_acceptance_runtime(
            repo_root=tmp_path,
            run_id="step-c-runtime",
            configuration=wrong,
            current_database=lambda: "valuepilot_acceptance_step_c_runtime",
        )

    expected.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    expected.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AcceptanceEnvironmentError, match="symlink"):
        preflight_acceptance_runtime(
            repo_root=tmp_path,
            run_id="step-c-runtime",
            configuration=configuration,
            current_database=lambda: "valuepilot_acceptance_step_c_runtime",
        )


def test_pytest_schema_isolation_accepts_only_derived_acceptance_database() -> None:
    isolated = build_isolated_database_url(
        "postgresql://valuepilot:valuepilot@postgres:5432/"
        "valuepilot_acceptance_step_c_local_01",
        "valuepilot_pytest_0123456789ab",
    )

    assert "valuepilot_acceptance_step_c_local_01" in isolated
    assert "search_path%3Dvaluepilot_pytest_0123456789ab" in isolated


def test_acceptance_storage_validator_rejects_symlink_and_neighbor(
    tmp_path: Path,
) -> None:
    environment = build_acceptance_environment(
        repo_root=tmp_path,
        run_id="safe-run",
    )
    neighbor = environment.storage_root.parent / "neighbor"
    with pytest.raises(AcceptanceEnvironmentError):
        validate_acceptance_storage_target(
            repo_root=tmp_path,
            run_id=environment.run_id,
            storage_root=neighbor,
        )

    environment.storage_root.parent.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    environment.storage_root.symlink_to(target, target_is_directory=True)
    with pytest.raises(AcceptanceEnvironmentError, match="symlink"):
        validate_acceptance_storage_target(
            repo_root=tmp_path,
            run_id=environment.run_id,
            storage_root=environment.storage_root,
        )

    repo_with_symlinked_storage = tmp_path / "repo-with-symlinked-storage"
    repo_with_symlinked_storage.mkdir()
    outside_storage = tmp_path / "outside-storage"
    outside_storage.mkdir()
    (repo_with_symlinked_storage / "storage").symlink_to(
        outside_storage,
        target_is_directory=True,
    )
    with pytest.raises(AcceptanceEnvironmentError, match="symlink"):
        build_acceptance_environment(
            repo_root=repo_with_symlinked_storage,
            run_id="safe-run",
        )


def _case_report() -> SecGoldAcceptanceCaseReport:
    attempted_at = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    available_at = attempted_at + timedelta(seconds=2)
    return SecGoldAcceptanceCaseReport(
        schema_version=1,
        acceptance_pass=1,
        run_id="step-c-20260830",
        case_id="aapl-primary",
        stock_id=77,
        cik="0000320193",
        filing_selection_as_of=datetime(
            2026, 8, 26, 23, 59, 59, tzinfo=timezone.utc
        ),
        operation_id="11111111-1111-4111-8111-111111111111",
        operation_attempted_at=attempted_at,
        evidence_finalized_at=available_at,
        evidence_available_at=available_at,
        expected_completed_fiscal_years=(2025, 2024, 2023),
        selected_filings=(
            SecGoldSelectedFiling(
                accession_no="0000320193-26-000079",
                form_type="10-Q",
                accepted_at=datetime(
                    2026, 7, 31, 16, 5, 28, tzinfo=timezone.utc
                ),
                report_date=datetime(2026, 6, 27).date(),
            ),
        ),
        typed_gaps=("annual_coverage_gap:2024,2023",),
        typed_failures=("historical_submissions_sec_temporarily_unavailable",),
        filings_discovered=1,
        filings_created=1,
        artifacts_created=3,
        parse_runs_created=1,
        raw_facts_created=4,
        metric_facts_published=0,
    )


def test_acceptance_report_is_stable_machine_and_human_output(
    tmp_path: Path,
) -> None:
    report = _case_report()
    destination = tmp_path / "reports" / "aapl-primary.json"

    write_case_report(report, destination=destination, storage_root=tmp_path)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    human = render_human_case_summary(report)

    assert payload["filing_selection_as_of"] == "2026-08-26T23:59:59+00:00"
    assert payload["acceptance_pass"] == 1
    assert payload["operation_attempted_at"] == "2026-08-30T12:00:00+00:00"
    assert payload["evidence_finalized_at"] == "2026-08-30T12:00:02+00:00"
    assert payload["evidence_available_at"] == "2026-08-30T12:00:02+00:00"
    assert payload["selected_forms"] == ["10-Q"]
    assert payload["selected_filings"][0]["report_date"] == "2026-06-27"
    assert payload["typed_gaps"] == ["annual_coverage_gap:2024,2023"]
    assert payload["typed_failures"] == [
        "historical_submissions_sec_temporarily_unavailable"
    ]
    assert payload["metric_facts_published"] == 0
    assert "filing_selection_as_of=2026-08-26T23:59:59+00:00" in human
    assert "operation_attempted_at=2026-08-30T12:00:00+00:00" in human
    assert "evidence_available_at=2026-08-30T12:00:02+00:00" in human
    assert "selected_forms=10-Q" in human
    assert "typed_gap=annual_coverage_gap:2024,2023" in human
    assert (
        "typed_failure=historical_submissions_sec_temporarily_unavailable"
        in human
    )


def test_acceptance_report_rejects_backdated_or_external_destination(
    tmp_path: Path,
) -> None:
    report = _case_report()
    with pytest.raises(ValueError, match="availability cannot precede"):
        SecGoldAcceptanceCaseReport(
            **{
                **report.__dict__,
                "evidence_available_at": report.operation_attempted_at
                - timedelta(microseconds=1),
            }
        )
    with pytest.raises(ValueError, match="inside isolated storage"):
        write_case_report(
            report,
            destination=tmp_path.parent / "escaped.json",
            storage_root=tmp_path,
        )


def test_retained_file_audit_checks_existence_size_and_sha(tmp_path: Path) -> None:
    content = b"retained SEC bytes"
    digest = hashlib.sha256(content).hexdigest()
    retained = tmp_path / "financial" / digest[:2] / digest
    retained.parent.mkdir(parents=True)
    retained.write_bytes(content)

    valid = audit_retained_file(
        storage_root=tmp_path,
        storage_key=f"financial/{digest[:2]}/{digest}",
        expected_size=len(content),
        expected_sha256=digest,
    )
    assert valid["integrity_ok"] is True
    assert valid["actual_size"] == len(content)
    assert valid["actual_sha256"] == digest

    retained.write_bytes(b"X" * len(content))
    corrupt = audit_retained_file(
        storage_root=tmp_path,
        storage_key=f"financial/{digest[:2]}/{digest}",
        expected_size=len(content),
        expected_sha256=digest,
    )
    assert corrupt["integrity_ok"] is False
    assert corrupt["exists"] is True
    assert corrupt["sha256_ok"] is False

    retained.unlink()
    missing = audit_retained_file(
        storage_root=tmp_path,
        storage_key=f"financial/{digest[:2]}/{digest}",
        expected_size=len(content),
        expected_sha256=digest,
    )
    assert missing == {
        "actual_sha256": None,
        "actual_size": None,
        "exists": False,
        "integrity_ok": False,
        "sha256_ok": False,
        "size_ok": False,
    }


def test_idempotency_delta_uses_database_owned_second_pass_lineage() -> None:
    database_created = {
        "filings_created": 0,
        "artifacts_created": 0,
        "parse_runs_created": 0,
        "raw_facts_created": 0,
        "submission_snapshots_created": 0,
    }

    assert build_idempotency_delta(database_created) == {
        "artifacts_created": 0,
        "filings_created": 0,
        "idempotent": True,
        "parse_runs_created": 0,
        "raw_facts_created": 0,
        "submission_snapshots_created": 0,
    }

    database_created["parse_runs_created"] = 1
    assert build_idempotency_delta(database_created)["idempotent"] is False


def test_acceptance_aggregate_payload_is_stable_and_validates() -> None:
    before = {
        "metric_facts": 0,
        "rate_guard": {
            "instance_id": "11111111-1111-4111-8111-111111111111",
            "url": "http://rate-guard-local:9000",
            "metrics": {
                "rate_per_sec": 1.0,
                "total_request_count": 0,
                "total_403_count": 0,
                "total_429_count": 0,
                "total_503_count": 0,
            },
        },
    }
    after = {
        "metric_facts": 0,
        "rate_guard": {
            "instance_id": "11111111-1111-4111-8111-111111111111",
            "url": "http://rate-guard-local:9000",
            "metrics": {
                "rate_per_sec": 1.0,
                "total_request_count": 17,
                "total_403_count": 0,
                "total_429_count": 1,
                "total_503_count": 2,
            },
        },
    }
    cases = [
        {
            "case_id": "aapl-primary",
            "ticker": "AAPL",
            "cik": "0000320193",
            "expected_completed_fiscal_years": [2025],
            "covered_completed_fiscal_years": [2025],
            "pass_1": {"typed_gaps": [], "typed_failures": []},
            "pass_2": {"typed_gaps": [], "typed_failures": []},
            "idempotency_delta": {"idempotent": True},
            "retained_integrity": {"checked": 2, "failed": 0, "bytes": 40},
            "duplicates": {
                "filings": 0,
                "artifacts": 0,
                "parse_runs": 0,
                "raw_facts": 0,
            },
        }
    ]

    payload = build_aggregate_payload(
        run_id="step-d-test",
        expected_case_ids=("aapl-primary",),
        before=before,
        after=after,
        cases=cases,
        source_path_proof={
            "configured_route": "http://rate-guard-local:9000",
            "direct_sec_path": False,
            "fallback_enabled": False,
        },
    )

    validate_aggregate_payload(payload)
    assert payload["rate_guard_delta"]["requests"] == 17
    assert payload["rate_guard_delta"]["429"] == 1
    assert payload["retained_integrity"]["checked"] == 2
    assert payload["idempotent_case_count"] == 1
    assert "cases=1/1" in render_human_aggregate_summary(payload)


def test_acceptance_aggregate_validator_rejects_integrity_or_publication() -> None:
    payload = {
        "schema_version": 1,
        "run_id": "step-d-test",
        "expected_case_ids": ["aapl-primary"],
        "cases": [{"case_id": "aapl-primary"}],
        "case_count": 1,
        "metric_facts_before": 0,
        "metric_facts_after": 1,
        "retained_integrity": {"checked": 1, "failed": 1, "bytes": 4},
        "duplicate_totals": {
            "filings": 0,
            "artifacts": 0,
            "parse_runs": 0,
            "raw_facts": 0,
        },
        "rate_guard_before": {"instance_id": "same"},
        "rate_guard_after": {"instance_id": "same"},
        "rate_guard_delta": {"requests": 0, "403": 0, "429": 0, "503": 0},
        "source_path_proof": {
            "direct_sec_path": False,
            "fallback_enabled": False,
        },
    }
    with pytest.raises(ValueError, match="metric_facts"):
        validate_aggregate_payload(payload)


def test_acceptance_aggregate_validator_rejects_non_idempotent_second_pass() -> None:
    payload = {
        "schema_version": 1,
        "run_id": "step-d-test",
        "expected_case_ids": ["aapl-primary"],
        "cases": [{"case_id": "aapl-primary"}],
        "case_count": 1,
        "idempotent_case_count": 0,
        "metric_facts_before": 0,
        "metric_facts_after": 0,
        "retained_integrity": {"checked": 1, "failed": 0, "bytes": 4},
        "duplicate_totals": {
            "filings": 0,
            "artifacts": 0,
            "parse_runs": 0,
            "raw_facts": 0,
        },
        "rate_guard_before": {"instance_id": "same"},
        "rate_guard_after": {
            "instance_id": "same",
            "metrics": {"rate_per_sec": 1.0},
        },
        "source_path_proof": {
            "direct_sec_path": False,
            "fallback_enabled": False,
        },
    }

    with pytest.raises(ValueError, match="idempotent"):
        validate_aggregate_payload(payload)


def test_acceptance_stable_json_writer_rejects_external_target(tmp_path: Path) -> None:
    destination = tmp_path / "reports" / "aggregate.json"
    write_stable_json({"ok": True}, destination=destination, storage_root=tmp_path)
    assert destination.read_text(encoding="utf-8") == '{\n  "ok": true\n}\n'

    with pytest.raises(ValueError, match="isolated storage"):
        write_stable_json(
            {"ok": False},
            destination=tmp_path.parent / "outside.json",
            storage_root=tmp_path,
        )
