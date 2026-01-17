import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.main import app

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
    """
    Creates a fresh sqlalchemy session for each test that rolls back changes on exit.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
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
