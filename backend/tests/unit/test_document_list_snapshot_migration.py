from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BASE = make_url(settings.SQLALCHEMY_DATABASE_URI).set(
    query={
        key: value
        for key, value in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items()
        if key != "options"
    }
).render_as_string(hide_password=False)
BACKEND = Path(__file__).resolve().parents[2]
HEAD = "20260904190000"
PARENT = "20260904180000"


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        ["alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def isolated():
    name = new_test_schema_name()
    url = build_isolated_database_url(BASE, name)
    create_test_schema(BASE, name)
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        drop_test_schema(BASE, name)


def test_document_snapshot_schema_roundtrips(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    _alembic(url, "downgrade", PARENT)
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        assert "document_list_snapshots" not in tables
        assert "document_list_snapshot_members" not in tables
    _alembic(url, "upgrade", HEAD)


def test_document_snapshot_membership_is_immutable_and_user_cascades(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id = connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES ('snapshot-migration@example.com','x',true) RETURNING id"
            )
        )
        connection.execute(
            text(
                "INSERT INTO document_list_snapshots "
                "(id,user_id,page_limit,total_count,max_document_id,"
                "snapshot_cutoff,expires_at) VALUES "
                "('snapshot-abcdefghijklmnopqrstuvwxyz012345',:user,10,1,7,"
                "clock_timestamp(),clock_timestamp()+interval '15 minutes')"
            ),
            {"user": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO document_list_snapshot_members "
                "(snapshot_id,ordinal,document_id,upload_time,source) VALUES "
                "('snapshot-abcdefghijklmnopqrstuvwxyz012345',1,7,NULL,'upload')"
            )
        )
        txids = connection.execute(
            text(
                "SELECT s.created_txid,m.created_txid AS member_txid "
                "FROM document_list_snapshots s JOIN document_list_snapshot_members m "
                "ON m.snapshot_id=s.id"
            )
        ).one()
        assert txids.created_txid == txids.member_txid
        with pytest.raises(DBAPIError, match="snapshots are immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE document_list_snapshots SET total_count=0 "
                        "WHERE id='snapshot-abcdefghijklmnopqrstuvwxyz012345'"
                    )
                )
        with pytest.raises(DBAPIError, match="members are immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "UPDATE document_list_snapshot_members SET ordinal=2 "
                        "WHERE snapshot_id='snapshot-abcdefghijklmnopqrstuvwxyz012345'"
                    )
                )
        with pytest.raises(DBAPIError, match="members are immutable"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "DELETE FROM document_list_snapshot_members "
                        "WHERE snapshot_id='snapshot-abcdefghijklmnopqrstuvwxyz012345'"
                    )
                )
    with pytest.raises(DBAPIError, match="captured atomically"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO document_list_snapshot_members "
                    "(snapshot_id,ordinal,document_id,upload_time,source) VALUES "
                    "('snapshot-abcdefghijklmnopqrstuvwxyz012345',2,8,NULL,'upload')"
                )
            )
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
        assert connection.scalar(text("SELECT count(*) FROM document_list_snapshots")) == 0
        assert connection.scalar(text("SELECT count(*) FROM document_list_snapshot_members")) == 0
