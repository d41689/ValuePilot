import os
from pathlib import Path

# The app's live-mode startup guard (app/main.py) requires RATE_GUARD_URL, and
# the `client` fixture below runs that guard via `with TestClient(app)`. Tests
# never actually call Rate Guard — they inject fake EDGAR clients — so set a
# placeholder URL before any app import to satisfy the guard. EDGAR_FETCH_MODE
# is left at its default ("live") so fetch_and_store still uses the injected
# fake clients rather than the replay-from-DB path.
os.environ.setdefault("RATE_GUARD_URL", "http://rate-guard.invalid")

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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.db import engine as app_engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.users import User

from app.core.config import settings

# Both engines resolve unqualified tables only inside the generated schema.
engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
def client(db_session):
    """
    FastAPI TestClient with overridden dependency.
    """
    def override_get_db():
        try:
            yield db_session
        finally:
            pass # Session is closed in the db_session fixture

    app.dependency_overrides[get_db] = override_get_db
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
