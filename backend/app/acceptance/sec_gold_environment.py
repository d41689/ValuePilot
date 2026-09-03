"""Strict naming and path boundaries for disposable SEC acceptance runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat
import sys
from typing import Callable
from urllib.parse import urlsplit
import uuid

from sqlalchemy.engine import make_url


RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
DATABASE_NAME_RE = re.compile(r"^valuepilot_acceptance_[a-z0-9_]{2,32}$")
RESERVED_RUN_IDS = {"valuepilot", "postgres", "template0", "template1"}


class AcceptanceEnvironmentError(ValueError):
    pass


@dataclass(frozen=True)
class SecGoldAcceptanceEnvironment:
    run_id: str
    database_name: str
    database_url: str
    storage_root: Path
    reports_root: Path


@dataclass(frozen=True)
class AcceptanceRuntimeConfiguration:
    acceptance_mode: bool
    configured_run_id: str | None
    database_url: str
    configured_database_name: str | None
    edgar_storage_root: Path
    configured_storage_root: Path | None
    rate_guard_allow_fallback: bool
    rate_guard_fallback_url: str | None
    rate_guard_url: str | None
    rate_guard_expected_instance_id: str | None
    edgar_fetch_mode: str
    edgar_scheduler_enabled: bool
    thirteenf_job_worker_enabled: bool
    manager_seed_on_startup: bool
    notification_delivery_enabled: bool
    research_notification_scheduler_enabled: bool


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return value.st_dev, value.st_ino, value.st_mode


def prepare_acceptance_storage(*, repo_root: Path, run_id: str) -> Path:
    """Create only the exact run tree through a trusted repository descriptor."""

    validate_acceptance_run_id(run_id)
    root_path = repo_root.absolute()
    try:
        root_expected = os.stat(root_path, follow_symlinks=False)
        root_fd = os.open(root_path, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise AcceptanceEnvironmentError("repository root is not a stable directory") from exc
    descriptors = [root_fd]
    chain: list[tuple[int, str, os.stat_result]] = []
    created_run = False
    try:
        if _directory_identity(os.fstat(root_fd)) != _directory_identity(root_expected):
            raise AcceptanceEnvironmentError("repository root identity changed")
        for component in ("storage", "sec_gold_acceptance"):
            parent_fd = descriptors[-1]
            try:
                child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            except FileNotFoundError:
                os.mkdir(component, 0o750, dir_fd=parent_fd)
                child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
            except OSError as exc:
                raise AcceptanceEnvironmentError(
                    "acceptance storage component is not a safe directory"
                ) from exc
            child_identity = os.fstat(child_fd)
            chain.append((parent_fd, component, child_identity))
            descriptors.append(child_fd)
        parent_fd = descriptors[-1]
        try:
            os.mkdir(run_id, 0o750, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise AcceptanceEnvironmentError(
                "acceptance run storage already exists"
            ) from exc
        created_run = True
        run_fd = os.open(run_id, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        run_identity = os.fstat(run_fd)
        chain.append((parent_fd, run_id, run_identity))
        descriptors.append(run_fd)
        os.mkdir("reports", 0o750, dir_fd=run_fd)
        reports_fd = os.open("reports", _DIRECTORY_FLAGS, dir_fd=run_fd)
        reports_identity = os.fstat(reports_fd)
        chain.append((run_fd, "reports", reports_identity))
        descriptors.append(reports_fd)
        for parent, component, expected in reversed(chain):
            current = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if _directory_identity(current) != _directory_identity(expected):
                raise AcceptanceEnvironmentError("acceptance storage identity race")
        current_root = os.stat(root_path, follow_symlinks=False)
        if _directory_identity(current_root) != _directory_identity(root_expected):
            raise AcceptanceEnvironmentError("repository root identity race")
        return root_path / "storage" / "sec_gold_acceptance" / run_id
    except Exception:
        if created_run:
            try:
                run_parent = descriptors[2]
                run_fd = os.open(run_id, _DIRECTORY_FLAGS, dir_fd=run_parent)
                try:
                    try:
                        os.rmdir("reports", dir_fd=run_fd)
                    except OSError:
                        pass
                finally:
                    os.close(run_fd)
                os.rmdir(run_id, dir_fd=run_parent)
            except OSError:
                pass
        raise
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def remove_acceptance_storage(*, repo_root: Path, run_id: str) -> None:
    """Remove only one validated run tree without following any component."""

    validate_acceptance_run_id(run_id)
    root_fd = os.open(repo_root.absolute(), _DIRECTORY_FLAGS)
    descriptors = [root_fd]
    try:
        for component in ("storage", "sec_gold_acceptance"):
            child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptors[-1])
            descriptors.append(child_fd)
        parent_fd = descriptors[-1]
        try:
            run_fd = os.open(run_id, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            return

        def remove_tree(directory_fd: int) -> None:
            for name in os.listdir(directory_fd):
                entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISDIR(entry.st_mode):
                    child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
                    try:
                        remove_tree(child)
                    finally:
                        os.close(child)
                    os.rmdir(name, dir_fd=directory_fd)
                elif stat.S_ISREG(entry.st_mode):
                    os.unlink(name, dir_fd=directory_fd)
                else:
                    raise AcceptanceEnvironmentError(
                        "acceptance storage contains an unsafe special entry"
                    )

        try:
            remove_tree(run_fd)
        finally:
            os.close(run_fd)
        os.rmdir(run_id, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AcceptanceEnvironmentError("acceptance storage removal failed") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def validate_acceptance_run_id(run_id: str) -> None:
    if not RUN_ID_RE.fullmatch(run_id) or run_id in RESERVED_RUN_IDS:
        raise AcceptanceEnvironmentError(
            "acceptance run ID must be 2-32 lowercase letters/digits/hyphens "
            "and must not name shared PostgreSQL infrastructure"
        )


def validate_acceptance_database_name(database_name: str) -> None:
    if not DATABASE_NAME_RE.fullmatch(database_name):
        raise AcceptanceEnvironmentError(
            "acceptance database must be derived as valuepilot_acceptance_<run-id>"
        )
    if database_name in {
        "valuepilot",
        "valuepilot_prod",
        "postgres",
        "template0",
        "template1",
    }:
        raise AcceptanceEnvironmentError("shared database is never an acceptance target")


def assert_acceptance_database_identity(
    *,
    expected: str,
    configured: str,
    actual: str,
) -> None:
    validate_acceptance_database_name(expected)
    if configured != expected:
        raise AcceptanceEnvironmentError(
            f"configured database {configured!r} is not the acceptance target"
        )
    if actual != expected:
        raise AcceptanceEnvironmentError(
            f"connected database {actual!r} is not the acceptance target"
        )


def _validate_runtime_configuration(
    *,
    environment: SecGoldAcceptanceEnvironment,
    configuration: AcceptanceRuntimeConfiguration,
    require_storage: bool,
) -> None:
    if not configuration.acceptance_mode:
        raise AcceptanceEnvironmentError("explicit acceptance mode is required")
    if configuration.configured_run_id != environment.run_id:
        raise AcceptanceEnvironmentError(
            "configured acceptance run ID is not the requested run ID"
        )
    if configuration.configured_database_name != environment.database_name:
        raise AcceptanceEnvironmentError(
            "configured database is not the derived acceptance database"
        )
    try:
        configured_url = make_url(configuration.database_url)
    except Exception as exc:
        raise AcceptanceEnvironmentError("acceptance database URL is invalid") from exc
    if not configured_url.drivername.startswith("postgresql"):
        raise AcceptanceEnvironmentError("acceptance database URL must use PostgreSQL")
    if configured_url != make_url(environment.database_url):
        raise AcceptanceEnvironmentError(
            "acceptance database URL is not the exact derived acceptance URL"
        )
    if configuration.configured_storage_root is None:
        raise AcceptanceEnvironmentError("configured acceptance storage is required")
    if configuration.edgar_storage_root.absolute() != environment.storage_root:
        raise AcceptanceEnvironmentError(
            "EDGAR storage is not the derived acceptance storage root"
        )
    if configuration.configured_storage_root.absolute() != environment.storage_root:
        raise AcceptanceEnvironmentError(
            "configured acceptance storage is not the derived storage root"
        )
    if configuration.rate_guard_allow_fallback or configuration.rate_guard_fallback_url:
        raise AcceptanceEnvironmentError(
            "acceptance runtime must disable every Rate Guard fallback"
        )
    configured_rate_guard_url = (configuration.rate_guard_url or "").strip()
    if not configured_rate_guard_url:
        raise AcceptanceEnvironmentError(
            "acceptance runtime requires a pinned Rate Guard URL"
        )
    parsed_rate_guard_url = urlsplit(configured_rate_guard_url)
    if (
        parsed_rate_guard_url.scheme not in {"http", "https"}
        or not parsed_rate_guard_url.netloc
        or parsed_rate_guard_url.username is not None
        or parsed_rate_guard_url.password is not None
        or parsed_rate_guard_url.query
        or parsed_rate_guard_url.fragment
    ):
        raise AcceptanceEnvironmentError(
            "acceptance runtime requires a valid pinned Rate Guard URL"
        )
    expected_instance_id = (
        configuration.rate_guard_expected_instance_id or ""
    ).strip()
    try:
        canonical_instance_id = str(uuid.UUID(expected_instance_id))
    except ValueError as exc:
        raise AcceptanceEnvironmentError(
            "acceptance runtime requires a pinned Rate Guard instance ID"
        ) from exc
    if canonical_instance_id != expected_instance_id:
        raise AcceptanceEnvironmentError(
            "acceptance runtime requires a canonical pinned Rate Guard instance ID"
        )
    if configuration.edgar_fetch_mode != "rate_guard":
        raise AcceptanceEnvironmentError(
            "acceptance EDGAR fetch mode must be rate_guard"
        )
    if any(
        (
            configuration.edgar_scheduler_enabled,
            configuration.thirteenf_job_worker_enabled,
            configuration.manager_seed_on_startup,
            configuration.notification_delivery_enabled,
            configuration.research_notification_scheduler_enabled,
        )
    ):
        raise AcceptanceEnvironmentError(
            "acceptance runtime must disable all workers and schedulers"
        )
    validate_acceptance_storage_target(
        repo_root=environment.storage_root.parents[2],
        run_id=environment.run_id,
        storage_root=configuration.edgar_storage_root,
    )
    if require_storage and not environment.storage_root.is_dir():
        raise AcceptanceEnvironmentError(
            "derived acceptance storage does not exist as a directory"
        )


def preflight_acceptance_runtime(
    *,
    repo_root: Path,
    run_id: str,
    configuration: AcceptanceRuntimeConfiguration,
    current_database: Callable[[], str],
) -> SecGoldAcceptanceEnvironment:
    environment = build_acceptance_environment(repo_root=repo_root, run_id=run_id)
    _validate_runtime_configuration(
        environment=environment,
        configuration=configuration,
        require_storage=True,
    )
    actual_database = str(current_database())
    assert_acceptance_database_identity(
        expected=environment.database_name,
        configured=make_url(configuration.database_url).database or "",
        actual=actual_database,
    )
    return environment


def _configured_runtime() -> AcceptanceRuntimeConfiguration:
    from app.core.config import settings

    return AcceptanceRuntimeConfiguration(
        acceptance_mode=settings.VALUEPILOT_ACCEPTANCE_MODE,
        configured_run_id=settings.VALUEPILOT_ACCEPTANCE_RUN_ID,
        database_url=str(settings.SQLALCHEMY_DATABASE_URI),
        configured_database_name=settings.VALUEPILOT_ACCEPTANCE_DATABASE,
        edgar_storage_root=Path(settings.EDGAR_RAW_STORAGE_DIR),
        configured_storage_root=(
            Path(settings.VALUEPILOT_ACCEPTANCE_STORAGE)
            if settings.VALUEPILOT_ACCEPTANCE_STORAGE
            else None
        ),
        rate_guard_allow_fallback=settings.RATE_GUARD_ALLOW_LOCAL_FALLBACK,
        rate_guard_fallback_url=settings.RATE_GUARD_FALLBACK_URL,
        rate_guard_url=settings.RATE_GUARD_URL,
        rate_guard_expected_instance_id=settings.RATE_GUARD_EXPECTED_INSTANCE_ID,
        edgar_fetch_mode=settings.EDGAR_FETCH_MODE,
        edgar_scheduler_enabled=settings.EDGAR_SCHEDULER_ENABLED,
        thirteenf_job_worker_enabled=settings.THIRTEENF_JOB_WORKER_ENABLED,
        manager_seed_on_startup=settings.MANAGER_SEED_ON_STARTUP,
        notification_delivery_enabled=settings.NOTIFICATION_DELIVERY_ENABLED,
        research_notification_scheduler_enabled=(
            settings.RESEARCH_NOTIFICATION_SCHEDULER_ENABLED
        ),
    )


def preflight_configured_acceptance_runtime(
    run_id: str,
) -> SecGoldAcceptanceEnvironment:
    from sqlalchemy import create_engine, text

    configuration = _configured_runtime()
    engine = create_engine(configuration.database_url, pool_pre_ping=True)
    try:
        def current_database() -> str:
            with engine.connect() as connection:
                return str(connection.scalar(text("SELECT current_database()")))

        return preflight_acceptance_runtime(
            repo_root=Path(__file__).resolve().parents[2],
            run_id=run_id,
            configuration=configuration,
            current_database=current_database,
        )
    finally:
        engine.dispose()


def preflight_configured_acceptance_destroy(
    run_id: str,
    *,
    database_present: bool,
) -> SecGoldAcceptanceEnvironment:
    from sqlalchemy import create_engine, text

    environment = build_acceptance_environment(
        repo_root=Path(__file__).resolve().parents[2],
        run_id=run_id,
    )
    configuration = _configured_runtime()
    _validate_runtime_configuration(
        environment=environment,
        configuration=configuration,
        require_storage=False,
    )
    if database_present:
        engine = create_engine(configuration.database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                actual = str(connection.scalar(text("SELECT current_database()")))
        finally:
            engine.dispose()
        assert_acceptance_database_identity(
            expected=environment.database_name,
            configured=make_url(configuration.database_url).database or "",
            actual=actual,
        )
    return environment


def validate_acceptance_storage_target(
    *,
    repo_root: Path,
    run_id: str,
    storage_root: Path,
) -> None:
    validate_acceptance_run_id(run_id)
    resolved_repo_root = repo_root.resolve()
    storage_base = resolved_repo_root / "storage"
    acceptance_parent = storage_base / "sec_gold_acceptance"
    expected = acceptance_parent / run_id
    if storage_root.absolute() != expected:
        raise AcceptanceEnvironmentError(
            "acceptance storage must be the exact run-derived repository target"
        )
    for candidate in (storage_base, acceptance_parent, expected):
        if candidate.is_symlink():
            raise AcceptanceEnvironmentError(
                "acceptance storage path must not contain a symlink"
            )


def build_acceptance_environment(
    *,
    repo_root: Path,
    run_id: str,
) -> SecGoldAcceptanceEnvironment:
    validate_acceptance_run_id(run_id)
    database_name = f"valuepilot_acceptance_{run_id.replace('-', '_')}"
    validate_acceptance_database_name(database_name)
    storage_root = (
        repo_root.resolve() / "storage" / "sec_gold_acceptance" / run_id
    )
    validate_acceptance_storage_target(
        repo_root=repo_root,
        run_id=run_id,
        storage_root=storage_root,
    )
    return SecGoldAcceptanceEnvironment(
        run_id=run_id,
        database_name=database_name,
        database_url=(
            "postgresql://valuepilot:valuepilot@postgres:5432/" + database_name
        ),
        storage_root=storage_root,
        reports_root=storage_root / "reports",
    )


def _main(argv: list[str]) -> int:
    if len(argv) not in {2, 3} or argv[0] not in {
        "preflight", "destroy", "prepare-storage", "cleanup-storage"
    }:
        print(
            "usage: python -m app.acceptance.sec_gold_environment "
            "{preflight|destroy} <run-id> [database-present] or "
            "{prepare-storage|cleanup-storage} <repo-root> <run-id>",
            file=sys.stderr,
        )
        return 64
    try:
        action = argv[0]
        if action in {"prepare-storage", "cleanup-storage"} and len(argv) == 3:
            repo_root, run_id = Path(argv[1]), argv[2]
            if action == "prepare-storage":
                storage = prepare_acceptance_storage(repo_root=repo_root, run_id=run_id)
            else:
                remove_acceptance_storage(repo_root=repo_root, run_id=run_id)
                storage = repo_root.absolute() / "storage" / "sec_gold_acceptance" / run_id
            print(f"acceptance_storage_identity={storage}")
            return 0
        run_id = argv[1]
        if action == "preflight" and len(argv) == 2:
            environment = preflight_configured_acceptance_runtime(run_id)
        elif action == "destroy" and len(argv) in {2, 3}:
            if len(argv) == 3 and argv[2] != "database-present":
                raise AcceptanceEnvironmentError("invalid destroy database state")
            environment = preflight_configured_acceptance_destroy(
                run_id,
                database_present=len(argv) == 3,
            )
        else:
            raise AcceptanceEnvironmentError("invalid acceptance preflight arguments")
    except Exception as exc:
        print(f"acceptance runtime preflight failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"acceptance_run_id={environment.run_id} "
        f"acceptance_database_identity={environment.database_name} "
        f"acceptance_storage_identity={environment.storage_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
