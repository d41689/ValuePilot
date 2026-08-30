from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    assert payload["operation_attempted_at"] == "2026-08-30T12:00:00+00:00"
    assert payload["evidence_finalized_at"] == "2026-08-30T12:00:02+00:00"
    assert payload["evidence_available_at"] == "2026-08-30T12:00:02+00:00"
    assert payload["selected_forms"] == ["10-Q"]
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
