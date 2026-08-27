"""Safe PostgreSQL schema isolation for the canonical pytest command."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


_TEST_SCHEMA_PATTERN = re.compile(r"^valuepilot_pytest_[0-9a-f]{12}$")


def new_test_schema_name() -> str:
    return f"valuepilot_pytest_{uuid.uuid4().hex[:12]}"


def validate_test_schema_name(schema_name: str) -> None:
    if not _TEST_SCHEMA_PATTERN.fullmatch(schema_name):
        raise RuntimeError(
            "pytest schema must be an internally generated "
            "valuepilot_pytest_<12 hex chars> name"
        )


def build_isolated_database_url(base_url: str, schema_name: str) -> str:
    """Return a URL whose unqualified SQL is confined to ``schema_name``.

    The normal compose API points at the shared development database. Tests may
    share that PostgreSQL server, but they must never see or mutate ``public``.
    Production databases and PostgreSQL's maintenance database are rejected.
    """

    validate_test_schema_name(schema_name)
    url = make_url(base_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("pytest database isolation requires PostgreSQL")

    database = url.database or ""
    if database != "valuepilot" and not database.startswith("valuepilot_test"):
        raise RuntimeError(
            "pytest may only use the valuepilot dev database or a "
            "valuepilot_test* database"
        )
    if "options" in url.query:
        raise RuntimeError(
            "pytest base DATABASE_URL must not already override PostgreSQL options"
        )

    isolated = url.update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    )
    return isolated.render_as_string(hide_password=False)


def create_test_schema(base_url: str, schema_name: str) -> None:
    validate_test_schema_name(schema_name)
    engine = create_engine(base_url, pool_pre_ping=True)
    quoted = engine.dialect.identifier_preparer.quote_identifier(schema_name)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {quoted}")
    finally:
        engine.dispose()


def drop_test_schema(base_url: str, schema_name: str) -> None:
    validate_test_schema_name(schema_name)
    engine = create_engine(base_url, pool_pre_ping=True)
    quoted = engine.dialect.identifier_preparer.quote_identifier(schema_name)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {quoted} CASCADE")
    finally:
        engine.dispose()
