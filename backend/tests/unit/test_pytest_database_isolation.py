from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import text

from test_support.database_isolation import (
    build_isolated_database_url,
    validate_test_schema_name,
)


def test_isolated_database_url_moves_postgres_search_path_off_public():
    isolated = build_isolated_database_url(
        "postgresql://valuepilot:secret@postgres:5432/valuepilot",
        "valuepilot_pytest_0123456789ab",
    )

    parsed = urlsplit(isolated)
    assert parsed.path == "/valuepilot"
    assert parse_qs(parsed.query)["options"] == [
        "-csearch_path=valuepilot_pytest_0123456789ab"
    ]


def test_isolated_database_url_preserves_unrelated_postgres_options():
    isolated = build_isolated_database_url(
        "postgresql://valuepilot:secret@postgres:5432/valuepilot?sslmode=disable",
        "valuepilot_pytest_0123456789ab",
    )

    query = parse_qs(urlsplit(isolated).query)
    assert query["sslmode"] == ["disable"]
    assert query["options"] == ["-csearch_path=valuepilot_pytest_0123456789ab"]


def test_canonical_pytest_session_can_only_resolve_generated_schema(db_session):
    current_schema, visible_schemas = db_session.execute(
        text("select current_schema(), current_schemas(false)")
    ).one()

    validate_test_schema_name(current_schema)
    assert visible_schemas == [current_schema]


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://valuepilot:secret@postgres:5432/valuepilot_prod",
        "postgresql://valuepilot:secret@postgres:5432/postgres",
        "sqlite:///valuepilot.db",
    ],
)
def test_isolated_database_url_refuses_unsafe_database_targets(database_url):
    with pytest.raises(RuntimeError):
        build_isolated_database_url(
            database_url,
            "valuepilot_pytest_0123456789ab",
        )


@pytest.mark.parametrize(
    "schema_name",
    [
        "public",
        "valuepilot_test",
        "valuepilot_pytest_bad-name",
        "valuepilot_pytest_0123456789ab;drop schema public",
    ],
)
def test_test_schema_name_must_be_narrow_and_generated(schema_name):
    with pytest.raises(RuntimeError):
        validate_test_schema_name(schema_name)
