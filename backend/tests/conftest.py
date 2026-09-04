import os
from pathlib import Path

# The app's live-mode startup guard (app/main.py) requires RATE_GUARD_URL, and
# the `client` fixture below runs that guard via `with TestClient(app)`. Tests
# never actually call Rate Guard — they inject fake EDGAR clients — so set a
# placeholder URL before any app import to satisfy the guard. EDGAR_FETCH_MODE
# is left at its default ("live") so fetch_and_store still uses the injected
# fake clients rather than the replay-from-DB path.
os.environ.setdefault("RATE_GUARD_URL", "http://rate-guard.invalid")
os.environ["EDGAR_FETCH_MODE"] = "live"
os.environ.setdefault(
    "RATE_GUARD_EXPECTED_INSTANCE_ID", "11111111-1111-4111-8111-111111111111"
)

# The canonical compose command runs inside the normal API container, whose
# DATABASE_URL intentionally points at the shared development database. Derive
# a unique PostgreSQL schema before importing the app so every app-level engine
# and SessionLocal uses the isolated search_path. The session fixture migrates
# and later drops only this generated schema; public dev data is never visible.
from test_support.database_isolation import (  # noqa: E402
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)

_BASE_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _BASE_DATABASE_URL:
    raise RuntimeError(
        "pytest must run in Docker with the compose-provided DATABASE_URL"
    )
_TEST_SCHEMA_NAME = new_test_schema_name()
os.environ["DATABASE_URL"] = build_isolated_database_url(
    _BASE_DATABASE_URL,
    _TEST_SCHEMA_NAME,
)

# Never let a developer's unattended-ingestion settings start background work
# inside the ephemeral test schema. Individual scheduler/worker tests invoke or
# monkeypatch those paths explicitly.
os.environ["EDGAR_SCHEDULER_ENABLED"] = "false"
os.environ["THIRTEENF_JOB_WORKER_ENABLED"] = "false"
os.environ["THIRTEENF_SMART_RETRY_ENABLED"] = "false"
os.environ["MANAGER_SEED_ON_STARTUP"] = "false"
os.environ["CUSIP_OVERRIDE_SEED_ENABLED"] = "false"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from app.api.deps import get_db
from app.core.db import engine as app_engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.users import User

from app.core.config import settings

# Both engines resolve unqualified tables only inside the generated schema.
engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _fixture_value_line_owner_and_document(connection, target) -> tuple[int, int]:
    document_id = getattr(target, "document_id", None) or getattr(
        target, "source_document_id", None
    )
    if document_id is not None:
        document = connection.execute(
            text("SELECT user_id FROM pdf_documents WHERE id=:id"),
            {"id": document_id},
        ).mappings().one()
        if getattr(target, "user_id", None) is None:
            target.user_id = int(document.user_id)
        return int(target.user_id), int(document_id)

    user_id = getattr(target, "user_id", None)
    if user_id is None:
        user_id = connection.execute(
            text("SELECT id FROM users ORDER BY id DESC LIMIT 1")
        ).scalar_one_or_none()
    if user_id is None:
        user_id = connection.execute(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES (:email,'fixture',true) RETURNING id"
            ),
            {"email": f"value-line-fixture-{uuid4().hex}@example.invalid"},
        ).scalar_one()
    target.user_id = int(user_id)
    document_id = connection.execute(
        text(
            "INSERT INTO pdf_documents "
            "(user_id,file_name,source,file_storage_key,parse_status,stock_id,"
            "identity_needs_review) VALUES (:user,'fixture-value-line.pdf','upload',"
            ":storage,'parsed',:stock,false) RETURNING id"
        ),
        {
            "user": user_id,
            "stock": getattr(target, "stock_id", None),
            "storage": f"test-only/value-line/{uuid4().hex}.pdf",
        },
    ).scalar_one()
    target.source_document_id = int(document_id)
    return int(user_id), int(document_id)


def _fixture_value_line_run(connection, target) -> int:
    user_id, document_id = _fixture_value_line_owner_and_document(connection, target)
    mapping_id = connection.execute(
        text(
            "SELECT id FROM value_line_mapping_policies "
            "WHERE status='approved'"
        )
    ).scalar_one()
    run_id = connection.execute(
        text(
            "INSERT INTO value_line_parse_runs "
            "(user_id,document_id,parser_version,source_mapping_version,status,"
            "created_txid) VALUES (:user,:document,'value-line-v1',:mapping,"
            "'running',0) RETURNING id"
        ),
        {"user": user_id, "document": document_id, "mapping": mapping_id},
    ).scalar_one()
    target.value_line_parse_run_id = int(run_id)
    return int(run_id)


# Older tests construct canonical rows directly instead of exercising ingestion.
# Give only those ORM fixtures a real DB-approved, same-transaction run so the
# production trigger remains strict. Raw-SQL migration tests bypass these
# listeners and prove that callers cannot manufacture runless/forged lineage.
@event.listens_for(MetricExtraction, "before_insert")
def _bind_fixture_extraction_run(_mapper, connection, target) -> None:
    if target.value_line_parse_run_id is None:
        target._test_value_line_run_id = _fixture_value_line_run(connection, target)


@event.listens_for(MetricExtraction, "after_insert")
def _finalize_fixture_extraction_run(_mapper, connection, target) -> None:
    run_id = getattr(target, "_test_value_line_run_id", None)
    if run_id is not None:
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )


@event.listens_for(MetricFact, "before_insert")
def _bind_fixture_parsed_fact_run(_mapper, connection, target) -> None:
    if target.source_type == "parsed" and target.value_line_parse_run_id is None:
        target._test_value_line_run_id = _fixture_value_line_run(connection, target)


@event.listens_for(MetricFact, "after_insert")
def _finalize_fixture_parsed_fact_run(_mapper, connection, target) -> None:
    run_id = getattr(target, "_test_value_line_run_id", None)
    if run_id is not None:
        connection.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location", str(backend_dir / "alembic")
    )

    create_test_schema(_BASE_DATABASE_URL, _TEST_SCHEMA_NAME)
    try:
        command.upgrade(alembic_config, "head")
        yield
    finally:
        engine.dispose()
        app_engine.dispose()
        drop_test_schema(_BASE_DATABASE_URL, _TEST_SCHEMA_NAME)

@pytest.fixture(scope="function")
def db_session():
    """Yield a Session whose writes are wrapped in a connection-level
    transaction that is always rolled back at teardown.

    MVP4-10 hardening: production-code paths called inside tests may
    invoke ``session.commit()`` (e.g. ``enqueue_batch_reparse``),
    ``session.rollback()`` (e.g. the ``IntegrityError → typed-error``
    translators in MVP3-05 / MVP3-07 / MVP4-01), or
    ``session.begin_nested()`` (e.g. the holdings ingest savepoint).
    Without SAVEPOINT nesting at the fixture layer those calls
    deassociate the session from the outer connection-level
    transaction and SQLAlchemy emits
    ``SAWarning('transaction already deassociated from connection')``
    at teardown.

    Fix: open the connection-level transaction explicitly, then bind
    the Session with ``join_transaction_mode='create_savepoint'``
    (SQLAlchemy 2.0 recipe). Every Session-level
    ``commit()`` / ``rollback()`` then operates on a SAVEPOINT
    instead of touching the outer connection transaction.
    Production-side ``begin_nested()`` calls stack as nested
    SAVEPOINTs as they would in production.

    The fixture API is unchanged; tests continue to receive a
    ``Session`` object with the same call semantics.
    """
    connection = engine.connect()
    transaction = connection.begin()

    session = TestingSessionLocal(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()

@pytest.fixture(scope="function")
def client(db_session, monkeypatch):
    """
    FastAPI TestClient with overridden dependency.
    """
    def override_get_db():
        try:
            yield db_session
        finally:
            pass # Session is closed in the db_session fixture

    app.dependency_overrides[get_db] = override_get_db
    # App tests never contact external infrastructure. The dedicated Rate Guard
    # startup tests exercise the real fail-closed verifier with a fake transport.
    monkeypatch.setattr(
        "app.main.verify_live_rate_guard",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def user_factory(db_session):
    def _factory(
        email: str = "user@example.com",
        *,
        password: str = "TestPass123!",
        role: str = "user",
        tier: str = "free",
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=role,
            tier=tier,
            is_active=is_active,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _factory


@pytest.fixture(scope="function")
def auth_headers():
    def _headers(user: User) -> dict[str, str]:
        token = create_access_token(user.id, user.role)
        return {"Authorization": f"Bearer {token}"}

    return _headers
