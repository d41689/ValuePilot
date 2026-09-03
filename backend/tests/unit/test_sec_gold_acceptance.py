from __future__ import annotations

from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from app.acceptance.sec_gold_environment import (
    AcceptanceEnvironmentError,
    AcceptanceRuntimeConfiguration,
    assert_acceptance_database_identity,
    build_acceptance_environment,
    prepare_acceptance_storage,
    preflight_acceptance_runtime,
    validate_acceptance_database_name,
    validate_acceptance_storage_target,
)
from app.acceptance.sec_gold_storage import secure_atomic_write_bytes, secure_read_bytes
from app.acceptance import sec_gold_storage as gold_storage
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
from app.acceptance.sec_gold_publication import (
    ACCEPTANCE_AMENDMENT_POLICY_ID,
    ACCEPTANCE_MAPPING_VERSION_ID,
    ACCEPTANCE_METHOD_POLICY_VERSION_ID,
    ACCEPTANCE_PARSER_VERSION,
    MetricGapEvidence,
    V1_METRIC_DENOMINATOR,
    build_metric_outcome_matrix,
    classify_metric_gap_evidence,
    publication_idempotency_delta,
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


def test_acceptance_storage_prepare_is_exact_and_rejects_symlink_components(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    prepared = prepare_acceptance_storage(repo_root=repo, run_id="round-four")
    assert prepared == repo / "storage" / "sec_gold_acceptance" / "round-four"
    assert (prepared / "reports").is_dir()
    with pytest.raises(AcceptanceEnvironmentError, match="already exists"):
        prepare_acceptance_storage(repo_root=repo, run_id="round-four")

    unsafe_repo = tmp_path / "unsafe"
    external = tmp_path / "external"
    unsafe_repo.mkdir()
    external.mkdir()
    (unsafe_repo / "storage").symlink_to(external, target_is_directory=True)
    with pytest.raises(AcceptanceEnvironmentError, match="safe directory"):
        prepare_acceptance_storage(repo_root=unsafe_repo, run_id="round-four")
    assert list(external.iterdir()) == []


def test_acceptance_storage_prepare_detects_component_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    parent = repo / "storage" / "sec_gold_acceptance"
    parent.mkdir(parents=True)
    displaced = parent.with_name("sec_gold_acceptance-displaced")
    original_mkdir = os.mkdir
    swapped = False

    def swap_before_run_create(path, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "round-four" and dir_fd is not None and not swapped:
            swapped = True
            os.rename(parent, displaced)
            original_mkdir(parent, 0o750)
        return original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", swap_before_run_create)
    with pytest.raises(AcceptanceEnvironmentError, match="identity race"):
        prepare_acceptance_storage(repo_root=repo, run_id="round-four")
    assert not (parent / "round-four").exists()
    assert not (displaced / "round-four").exists()


def test_acceptance_authority_io_rejects_symlink_and_detects_read_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    external = tmp_path.parent / f"{tmp_path.name}-external.json"
    external.write_text('{"outside":true}\n', encoding="utf-8")
    linked = reports / "runtime-before.json"
    linked.symlink_to(external)
    with pytest.raises(ValueError, match="unsafe"):
        secure_read_bytes(storage_root=tmp_path, source=linked)

    unsafe_root = tmp_path / "unsafe-root"
    external_directory = tmp_path / "external-directory"
    unsafe_root.mkdir()
    external_directory.mkdir()
    (unsafe_root / "reports").symlink_to(external_directory, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        write_stable_json(
            {"blocked": True},
            destination=unsafe_root / "reports" / "runtime-before.json",
            storage_root=unsafe_root,
        )
    assert list(external_directory.iterdir()) == []

    linked.unlink()
    stable = reports / "runtime-before.json"
    stable.write_text('{"stable":true}\n', encoding="utf-8")
    original_read = os.read
    changed = False

    def mutate_after_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            stable.write_text('{"changed":true}\n', encoding="utf-8")
        return chunk

    monkeypatch.setattr(os, "read", mutate_after_read)
    with pytest.raises(ValueError, match="file changed during read"):
        secure_read_bytes(storage_root=tmp_path, source=stable)


def test_acceptance_authority_io_detects_parent_directory_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    source = reports / "runtime-after.json"
    encoded = b'{"stable":true}\n'
    source.write_bytes(encoded)
    displaced = tmp_path / "reports-displaced"
    original_read = os.read
    swapped = False

    def swap_parent_after_read(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        chunk = original_read(descriptor, size)
        if chunk and not swapped:
            swapped = True
            os.rename(reports, displaced)
            reports.mkdir()
            (reports / source.name).write_bytes(encoded)
        return chunk

    monkeypatch.setattr(os, "read", swap_parent_after_read)
    with pytest.raises(ValueError, match="component changed"):
        secure_read_bytes(storage_root=tmp_path, source=source)


@pytest.mark.parametrize("replacement_kind", ("symlink", "regular"))
def test_acceptance_atomic_writer_rejects_temp_replacement_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_kind: str,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    destination = reports / "aggregate.json"
    expected = b'{"authority":true}\n'
    external = tmp_path / "external"
    external.write_bytes(b"external")
    original_open = os.open
    original_fsync = os.fsync
    held_identity: tuple[int, int] | None = None
    replacement_path: Path | None = None
    replacement_identity: tuple[int, int] | None = None
    replaced = False

    def force_named_temporary(path, flags, mode=0o777, *, dir_fd=None):
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if temporary_flag and flags & temporary_flag == temporary_flag:
            raise OSError(errno.EOPNOTSUPP, "fixture forces named fallback")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def replace_named_temp(descriptor: int) -> None:
        nonlocal held_identity
        nonlocal replacement_identity
        nonlocal replacement_path
        nonlocal replaced
        info = os.fstat(descriptor)
        if stat.S_ISREG(info.st_mode) and not replaced:
            names = [name for name in os.listdir(reports) if name.endswith(".tmp")]
            if names:
                replaced = True
                held_identity = (info.st_dev, info.st_ino)
                temporary = reports / names[0]
                replacement_path = temporary
                temporary.unlink()
                if replacement_kind == "symlink":
                    temporary.symlink_to(external)
                else:
                    temporary.write_bytes(b"attacker replacement")
                replacement = temporary.stat(follow_symlinks=False)
                replacement_identity = (replacement.st_dev, replacement.st_ino)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "open", force_named_temporary)
    monkeypatch.setattr(os, "fsync", replace_named_temp)
    with pytest.raises(ValueError, match="descriptor-based"):
        secure_atomic_write_bytes(
            storage_root=tmp_path,
            destination=destination,
            content=expected,
        )
    assert held_identity is not None
    assert not os.path.lexists(destination)
    assert external.read_bytes() == b"external"
    assert replacement_path is not None
    assert os.path.lexists(replacement_path)
    retained = replacement_path.stat(follow_symlinks=False)
    assert (retained.st_dev, retained.st_ino) == replacement_identity
    if replacement_kind == "symlink":
        assert replacement_path.is_symlink()
        assert replacement_path.readlink() == external
    else:
        assert replacement_path.read_bytes() == b"attacker replacement"


def test_acceptance_atomic_writer_publishes_the_held_descriptor_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    destination = reports / "aggregate.json"
    expected = b'{"authority":true}\n'
    original_open = os.open
    original_fsync = os.fsync
    held_identity: tuple[int, int] | None = None

    def force_named_temporary(path, flags, mode=0o777, *, dir_fd=None):
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if temporary_flag and flags & temporary_flag == temporary_flag:
            raise OSError(errno.EOPNOTSUPP, "fixture forces named fallback")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def capture_held_inode(descriptor: int) -> None:
        nonlocal held_identity
        info = os.fstat(descriptor)
        if stat.S_ISREG(info.st_mode) and held_identity is None:
            held_identity = (info.st_dev, info.st_ino)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "open", force_named_temporary)
    monkeypatch.setattr(os, "fsync", capture_held_inode)
    secure_atomic_write_bytes(
        storage_root=tmp_path,
        destination=destination,
        content=expected,
    )
    published = destination.stat(follow_symlinks=False)
    assert (published.st_dev, published.st_ino) == held_identity
    assert destination.read_bytes() == expected
    assert not any(name.endswith(".tmp") for name in os.listdir(reports))


def test_acceptance_atomic_writer_destination_race_and_existing_file_are_no_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    destination = reports / "aggregate.json"
    original_fsync = os.fsync
    raced = False

    def create_destination_before_publish(descriptor: int) -> None:
        nonlocal raced
        info = os.fstat(descriptor)
        if stat.S_ISREG(info.st_mode) and not raced:
            raced = True
            destination.write_bytes(b"raced authority")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", create_destination_before_publish)
    with pytest.raises(ValueError, match="existing acceptance authority"):
        secure_atomic_write_bytes(
            storage_root=tmp_path,
            destination=destination,
            content=b"new authority",
        )
    assert destination.read_bytes() == b"raced authority"
    assert not any(name.endswith(".tmp") for name in os.listdir(reports))

    monkeypatch.setattr(os, "fsync", original_fsync)
    with pytest.raises(ValueError, match="overwrite existing"):
        secure_atomic_write_bytes(
            storage_root=tmp_path,
            destination=destination,
            content=b"different authority",
        )


def test_acceptance_atomic_writer_removes_its_publication_on_post_link_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    destination = reports / "aggregate.json"
    original_open = os.open
    original_fsync = os.fsync
    calls = 0

    def force_named_temporary(path, flags, mode=0o777, *, dir_fd=None):
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if temporary_flag and flags & temporary_flag == temporary_flag:
            raise OSError(errno.EOPNOTSUPP, "fixture forces named fallback")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def fail_directory_sync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OSError(errno.EIO, "simulated directory sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "open", force_named_temporary)
    monkeypatch.setattr(os, "fsync", fail_directory_sync)
    with pytest.raises(ValueError, match="descriptor-based"):
        secure_atomic_write_bytes(
            storage_root=tmp_path,
            destination=destination,
            content=b"authority",
        )
    assert not os.path.lexists(destination)


def test_acceptance_atomic_writer_cleans_only_its_owned_temp_on_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    destination = reports / "aggregate.json"
    original_open = os.open

    def force_named_temporary(path, flags, mode=0o777, *, dir_fd=None):
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if temporary_flag and flags & temporary_flag == temporary_flag:
            raise OSError(errno.EOPNOTSUPP, "fixture forces named fallback")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def fail_descriptor_publish(**_kwargs):
        raise OSError(errno.ENOSYS, "simulated descriptor publish failure")

    monkeypatch.setattr(os, "open", force_named_temporary)
    monkeypatch.setattr(
        gold_storage, "_publish_held_descriptor", fail_descriptor_publish
    )
    with pytest.raises(ValueError, match="descriptor-based"):
        secure_atomic_write_bytes(
            storage_root=tmp_path,
            destination=destination,
            content=b"authority",
        )
    assert not os.path.lexists(destination)
    assert not any(name.endswith(".tmp") for name in os.listdir(reports))

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
        "rate_guard_url": "https://rate-guard.example.test",
        "rate_guard_expected_instance_id": "11111111-1111-4111-8111-111111111111",
        "edgar_fetch_mode": "rate_guard",
        "edgar_scheduler_enabled": False,
        "thirteenf_job_worker_enabled": False,
        "manager_seed_on_startup": False,
        "notification_delivery_enabled": False,
        "research_notification_scheduler_enabled": False,
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
        ({"edgar_scheduler_enabled": True}, None, "workers and schedulers"),
        ({"rate_guard_url": None}, None, "pinned Rate Guard URL"),
        ({"rate_guard_url": "rate-guard.invalid"}, None, "valid pinned Rate Guard URL"),
        ({"rate_guard_expected_instance_id": None}, None, "instance ID"),
        ({"rate_guard_expected_instance_id": "wrong-instance"}, None, "instance ID"),
        ({"edgar_fetch_mode": "live"}, None, "rate_guard"),
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


def test_retained_file_audit_rejects_object_and_parent_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"descriptor-owned retained bytes"
    digest = hashlib.sha256(content).hexdigest()
    retained = tmp_path / "financial" / digest[:2] / digest
    retained.parent.mkdir(parents=True)
    retained.write_bytes(content)
    displaced_parent = retained.parent.with_name(retained.parent.name + "-old")
    original_read = os.read
    replaced = False

    def replace_parent_after_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and not replaced:
            replaced = True
            os.rename(retained.parent, displaced_parent)
            retained.parent.mkdir()
            retained.write_bytes(content)
        return chunk

    monkeypatch.setattr(os, "read", replace_parent_after_read)
    with pytest.raises(ValueError, match="component changed"):
        audit_retained_file(
            storage_root=tmp_path,
            storage_key=f"financial/{digest[:2]}/{digest}",
            expected_size=len(content),
            expected_sha256=digest,
        )


def test_retained_file_audit_rejects_regular_object_to_external_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"descriptor-owned retained bytes"
    digest = hashlib.sha256(content).hexdigest()
    retained = tmp_path / "financial" / digest[:2] / digest
    retained.parent.mkdir(parents=True)
    retained.write_bytes(content)
    external = tmp_path / "external"
    external.write_bytes(content)
    original_read = os.read
    replaced = False

    def replace_object_after_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and not replaced:
            replaced = True
            retained.unlink()
            retained.symlink_to(external)
        return chunk

    monkeypatch.setattr(os, "read", replace_object_after_read)
    with pytest.raises(ValueError, match="file changed during read"):
        audit_retained_file(
            storage_root=tmp_path,
            storage_key=f"financial/{digest[:2]}/{digest}",
            expected_size=len(content),
            expected_sha256=digest,
        )
    assert external.read_bytes() == content


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


def test_ft04_publication_acceptance_authorities_are_not_caller_configurable() -> None:
    assert ACCEPTANCE_MAPPING_VERSION_ID == "sec-us-gaap-v1"
    assert ACCEPTANCE_METHOD_POLICY_VERSION_ID == "sec-method-gate-v1"
    assert ACCEPTANCE_AMENDMENT_POLICY_ID == "latest-known-v1"
    assert ACCEPTANCE_PARSER_VERSION == "xbrl-lineage-v2.7"
    assert V1_METRIC_DENOMINATOR == 21


def test_metric_outcome_matrix_keeps_typed_gaps_out_of_published_coverage() -> None:
    rows = build_metric_outcome_matrix(
        expected_fiscal_years=(2025,),
        metric_keys=("is.revenue", "is.gross_profit"),
        decisions=(
            {
                "id": 11,
                "metric_key": "is.revenue",
                "fiscal_year": 2025,
                "period_type": "FY",
                "status": "published",
                "reason_code": "published",
                "metric_fact_id": 31,
            },
            {
                "id": 12,
                "metric_key": "is.gross_profit",
                "fiscal_year": 2025,
                "period_type": "FY",
                "status": "unresolved",
                "reason_code": "unresolved_dimensions",
                "metric_fact_id": None,
            },
        ),
    )

    assert rows["metric_denominator"] == 2
    assert rows["issuer_year_metric_denominator"] == 2
    assert rows["published_count"] == 1
    assert rows["typed_gap_count"] == 1
    assert rows["missing_count"] == 0
    assert rows["coverage_count"] == 1
    assert rows["outcomes"][1]["outcome"] == "typed_gap"


def test_metric_outcome_matrix_never_hides_absent_locked_metric() -> None:
    rows = build_metric_outcome_matrix(
        expected_fiscal_years=(2025,),
        metric_keys=("is.revenue",),
        decisions=(),
    )

    assert rows["coverage_count"] == 0
    assert rows["missing_count"] == 1
    assert rows["outcomes"] == [
        {
            "fiscal_year": 2025,
            "metric_key": "is.revenue",
            "outcome": "missing",
            "decision_ids": [],
            "metric_fact_ids": [],
            "typed_reasons": ["missing_canonical_outcome"],
        }
    ]


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (
            MetricGapEvidence(),
            "unresolved_annual_filing_authority_unavailable",
        ),
        (
            MetricGapEvidence(failed_parse_codes=("statement_authority_parse_failed",)),
            "unresolved_annual_filing_parse_failed:statement_authority_parse_failed",
        ),
        (
            MetricGapEvidence(annual_source_ids=(11,)),
            "unresolved_mapped_raw_absent",
        ),
        (
            MetricGapEvidence(annual_source_ids=(11,), mapped_raw_ids=(21,)),
            "unresolved_statement_authority",
        ),
    ],
)
def test_metric_gap_evidence_uses_most_specific_bounded_stage(
    evidence: MetricGapEvidence,
    reason: str,
) -> None:
    assert classify_metric_gap_evidence(evidence) == (reason,)


def test_metric_gap_evidence_rejects_complete_candidate_without_decision() -> None:
    evidence = MetricGapEvidence(
        annual_source_ids=(11,),
        mapped_raw_ids=(21,),
        statement_authority_ids=(31,),
        normalization_ids=(41,),
    )

    with pytest.raises(
        ValueError,
        match="canonical publication decision missing despite complete authority",
    ):
        classify_metric_gap_evidence(evidence)


def test_metric_outcome_matrix_preserves_gap_when_same_pair_also_published() -> None:
    rows = build_metric_outcome_matrix(
        expected_fiscal_years=(2024,),
        metric_keys=("revenue",),
        decisions=(
            {
                "id": 1,
                "fiscal_year": 2024,
                "period_type": "FY",
                "metric_key": "revenue",
                "status": "published",
                "reason_code": "published",
                "metric_fact_id": 9,
            },
            {
                "id": 2,
                "fiscal_year": 2024,
                "period_type": "FY",
                "metric_key": "revenue",
                "status": "unresolved",
                "reason_code": "conflicting_evidence",
                "metric_fact_id": None,
            },
        ),
    )

    assert rows["coverage_count"] == 0
    assert rows["typed_gap_count"] == 1
    assert rows["outcomes"][0]["outcome"] == "typed_gap"
    assert rows["outcomes"][0]["typed_reasons"] == ["conflicting_evidence"]


def test_publication_idempotency_delta_requires_every_persistent_evidence_delta_zero() -> None:
    fields = {
        "issuer_identities": 0,
        "filings": 0,
        "submission_snapshots": 0,
        "artifacts": 0,
        "parse_runs": 0,
        "parse_run_artifacts": 0,
        "raw_facts": 0,
        "statement_report_references": 0,
        "statement_occurrences": 0,
        "statement_authorities": 0,
        "numeric_normalizations": 0,
        "publication_runs": 0,
        "publication_run_sources": 0,
        "publication_decisions": 0,
        "publication_inputs": 0,
        "publication_unresolved_inputs": 0,
        "publication_audits": 0,
        "publication_availabilities": 0,
        "metric_facts": 0,
    }

    assert publication_idempotency_delta(fields)["idempotent"] is True
    fields["publication_inputs"] = 1
    assert publication_idempotency_delta(fields)["idempotent"] is False
    del fields["publication_inputs"]
    with pytest.raises(ValueError, match="incomplete"):
        publication_idempotency_delta(fields)


def test_acceptance_aggregate_payload_is_stable_and_validates() -> None:
    source_path_proof = {
        "configured_route": "https://rate-guard.example.test",
        "expected_instance_id": "11111111-1111-4111-8111-111111111111",
        "fetch_mode": "rate_guard",
        "fallback_enabled": False,
        "fallback_url": None,
        "config_digest": "a" * 64,
        "manifest_digest": "b" * 64,
    }
    before = {
        "run_id": "step-d-test",
        "database": "valuepilot_acceptance_step_d_test",
        "metric_facts": 0,
        "source_path_proof": source_path_proof,
        "rate_guard": {
            "instance_id": "11111111-1111-4111-8111-111111111111",
            "url": "https://rate-guard.example.test",
            "expected_instance_id": "11111111-1111-4111-8111-111111111111",
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
        "run_id": "step-d-test",
        "database": "valuepilot_acceptance_step_d_test",
        "metric_facts": 21,
        "source_path_proof": source_path_proof,
        "rate_guard": {
            "instance_id": "11111111-1111-4111-8111-111111111111",
            "url": "https://rate-guard.example.test",
            "expected_instance_id": "11111111-1111-4111-8111-111111111111",
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
            "pass_1": {
                "typed_gaps": [],
                "typed_failures": [],
                "mapping_version_id": "sec-us-gaap-v1",
                "method_policy_version_id": "sec-method-gate-v1",
                "publication_requested_cutoff": "2026-09-01T12:00:00+00:00",
                "metric_outcomes": {
                    "metric_denominator": 21,
                    "issuer_year_metric_denominator": 21,
                    "published_count": 21,
                    "typed_gap_count": 0,
                    "missing_count": 0,
                    "coverage_count": 21,
                },
            },
            "pass_2": {"typed_gaps": [], "typed_failures": []},
            "metric_outcomes": {
                "metric_denominator": 21,
                "issuer_year_metric_denominator": 21,
                "published_count": 21,
                "typed_gap_count": 0,
                "missing_count": 0,
                "coverage_count": 21,
            },
            "idempotency_delta": {"idempotent": True},
            "retained_integrity": {"checked": 2, "failed": 0, "bytes": 40},
            "duplicates": {
                "filings": 0,
                "artifacts": 0,
                "parse_runs": 0,
                "raw_facts": 0,
                "current_sec_slots": 0,
            },
        }
    ]

    payload = build_aggregate_payload(
        run_id="step-d-test",
        expected_case_ids=("aapl-primary",),
        before=before,
        after=after,
        cases=cases,
        source_path_proof=source_path_proof,
    )

    validate_aggregate_payload(payload)
    assert payload["shared_observed_window_delta"]["requests"] == 17
    assert "rate_guard_delta" not in payload
    assert payload["schema_version"] == 2
    assert payload["shared_observed_window_delta"]["429"] == 1
    assert payload["retained_integrity"]["checked"] == 2
    assert payload["idempotent_case_count"] == 1
    assert "cases=1/1" in render_human_aggregate_summary(payload)

    regressed_before = json.loads(json.dumps(before))
    regressed_before["rate_guard"]["metrics"]["total_request_count"] = 18
    with pytest.raises(ValueError, match="counter decreased"):
        build_aggregate_payload(
            run_id="step-d-test",
            expected_case_ids=("aapl-primary",),
            before=regressed_before,
            after=after,
            cases=cases,
            source_path_proof=source_path_proof,
        )


def test_acceptance_aggregate_validator_rejects_integrity_or_publication() -> None:
    payload = {
        "schema_version": 2,
        "run_id": "step-d-test",
        "expected_case_ids": ["aapl-primary"],
        "cases": [{"case_id": "aapl-primary"}],
        "case_count": 1,
        "metric_facts_before": 0,
        "metric_facts_after": 1,
        "metric_outcomes": {
            "metric_denominator": 21,
            "issuer_year_metric_denominator": 2,
            "published_count": 2,
            "typed_gap_count": 0,
            "missing_count": 0,
            "coverage_count": 2,
        },
        "retained_integrity": {"checked": 1, "failed": 1, "bytes": 4},
        "duplicate_totals": {
            "filings": 0,
            "artifacts": 0,
            "parse_runs": 0,
            "raw_facts": 0,
            "current_sec_slots": 0,
        },
        "mapping_versions": ["sec-us-gaap-v1"],
        "method_policy_versions": ["sec-method-gate-v1"],
        "rate_guard_before": {"instance_id": "same"},
        "rate_guard_after": {"instance_id": "same"},
        "shared_observed_window_delta": {
            "requests": 0,
            "403": 0,
            "429": 0,
            "503": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        },
        "source_path_proof": {
            "configured_route": "https://rate-guard.example.test",
            "expected_instance_id": "11111111-1111-4111-8111-111111111111",
            "fetch_mode": "rate_guard",
            "fallback_enabled": False,
            "fallback_url": None,
        },
    }
    with pytest.raises(ValueError, match="metric_facts"):
        validate_aggregate_payload(payload)


def test_acceptance_aggregate_validator_rejects_non_idempotent_second_pass() -> None:
    payload = {
        "schema_version": 2,
        "run_id": "step-d-test",
        "expected_case_ids": ["aapl-primary"],
        "cases": [{"case_id": "aapl-primary"}],
        "case_count": 1,
        "idempotent_case_count": 0,
        "metric_facts_before": 0,
        "metric_facts_after": 0,
        "metric_outcomes": {
            "metric_denominator": 21,
            "issuer_year_metric_denominator": 0,
            "published_count": 0,
            "typed_gap_count": 0,
            "missing_count": 0,
            "coverage_count": 0,
        },
        "retained_integrity": {"checked": 1, "failed": 0, "bytes": 4},
        "duplicate_totals": {
            "filings": 0,
            "artifacts": 0,
            "parse_runs": 0,
            "raw_facts": 0,
            "current_sec_slots": 0,
        },
        "mapping_versions": ["sec-us-gaap-v1"],
        "method_policy_versions": ["sec-method-gate-v1"],
        "rate_guard_before": {"instance_id": "same"},
        "rate_guard_after": {
            "instance_id": "same",
            "metrics": {"rate_per_sec": 1.0},
        },
        "source_path_proof": {
            "configured_route": "https://rate-guard.example.test",
            "expected_instance_id": "11111111-1111-4111-8111-111111111111",
            "fetch_mode": "rate_guard",
            "fallback_enabled": False,
            "fallback_url": None,
        },
    }

    with pytest.raises(ValueError, match="idempotent"):
        validate_aggregate_payload(payload)


def test_acceptance_aggregate_validator_rejects_metric_outcome_mismatch() -> None:
    payload = {
        "schema_version": 2,
        "run_id": "step-d-test",
        "expected_case_ids": ["aapl-primary"],
        "cases": [{"case_id": "aapl-primary"}],
        "case_count": 1,
        "idempotent_case_count": 1,
        "metric_facts_before": 0,
        "metric_facts_after": 21,
        "metric_outcomes": {
            "metric_denominator": 21,
            "issuer_year_metric_denominator": 21,
            "published_count": 20,
            "typed_gap_count": 0,
            "missing_count": 0,
            "coverage_count": 20,
        },
        "retained_integrity": {"checked": 1, "failed": 0, "bytes": 4},
        "duplicate_totals": {
            "filings": 0,
            "artifacts": 0,
            "parse_runs": 0,
            "raw_facts": 0,
            "current_sec_slots": 0,
        },
        "mapping_versions": ["sec-us-gaap-v1"],
        "method_policy_versions": ["sec-method-gate-v1"],
        "rate_guard_before": {"instance_id": "same"},
        "rate_guard_after": {
            "instance_id": "same",
            "metrics": {"rate_per_sec": 1.0},
        },
        "source_path_proof": {
            "configured_route": "https://rate-guard.example.test",
            "expected_instance_id": "11111111-1111-4111-8111-111111111111",
            "fetch_mode": "rate_guard",
            "fallback_enabled": False,
            "fallback_url": None,
        },
    }

    with pytest.raises(ValueError, match="denominator mismatch"):
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
