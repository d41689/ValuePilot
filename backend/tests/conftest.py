import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.users import User

# Use an in-memory SQLite database for testing to avoid affecting the development DB
# OR use the Postgres DB but with rollbacks.
# Given we have postgres set up, let's try to use a separate test DB or just careful transaction management.
# For simplicity and speed in this environment, SQLite in-memory is great for logic tests,
# but since we use Postgres-specific types (JSON, maybe others later), we should ideally use Postgres.
# However, to avoid complexity of creating a test DB on the fly in this docker setup,
# I will use the *existing* DB but wrap everything in a transaction that always rolls back.

from app.core.config import settings

# Override the engine to use the same DB but we will manage sessions carefully
engine = create_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    # In a real scenario, we might drop/create tables here or use a separate DB.
    # For Phase 1, assuming fresh DB from docker-compose, we can just use it.
    # Base.metadata.create_all(bind=engine)
    yield
    # Base.metadata.drop_all(bind=engine)

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
