from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.users import User
from app.services.account_erasure import erase_account
from app.services.privacy_erasure import privacy_erasure_db_capability
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
HEAD = "20260904340000"
PARENT = "20260904330000"


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


def _seed_user(connection, suffix: str) -> int:
    return int(
        connection.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) "
                "VALUES (:email,'x',true) RETURNING id"
            ),
            {"email": f"r26-{suffix}@example.com"},
        )
    )


def _seed_stock(connection, suffix: str) -> int:
    return int(
        connection.scalar(
            text(
                "INSERT INTO stocks (ticker,company_name,exchange,is_active) "
                "VALUES (:ticker,'R26 Privacy','NYSE',true) RETURNING id"
            ),
            {"ticker": f"R26{suffix.upper()}"},
        )
    )


def _begin_erasure(connection, user_id: int) -> int:
    return int(
        connection.scalar(
            text(
                "SELECT begin_privacy_erasure_operation("
                ":user,'account_erasure',:capability)"
            ),
            {
                "user": user_id,
                "capability": privacy_erasure_db_capability(),
            },
        )
    )


def test_r26_empty_schema_roundtrips(isolated) -> None:
    url, _ = isolated
    _alembic(url, "upgrade", HEAD)
    _alembic(url, "downgrade", PARENT)
    _alembic(url, "upgrade", HEAD)


def test_r26_permanent_barrier_rejects_late_private_writes_and_reactivation(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id = _seed_user(connection, "permanent")
        stock_id = _seed_stock(connection, "perm")
        case_id = int(
            connection.scalar(
                text(
                    "INSERT INTO research_cases (user_id,stock_id,state) "
                    "VALUES (:user,:stock,'queued') RETURNING id"
                ),
                {"user": user_id, "stock": stock_id},
            )
        )
        _begin_erasure(connection, user_id)

    with engine.begin() as connection:
        assert connection.scalar(
            text("SELECT is_active FROM users WHERE id=:user"),
            {"user": user_id},
        ) is False
        assert connection.scalar(
            text(
                "SELECT count(*) FROM account_erasure_barriers "
                "WHERE user_id=:user"
            ),
            {"user": user_id},
        ) == 1
        mutations = [
            (
                "UPDATE users SET is_active=true WHERE id=:user",
                {"user": user_id},
            ),
            (
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "period_type,period_end_date,is_current) VALUES "
                "(:user,:stock,'is.revenue',1,'manual','FY','2025-12-31',true)",
                {"user": user_id, "stock": stock_id},
            ),
            (
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "period_type,period_end_date,is_current) VALUES "
                "(:user,:stock,'calc.r26',1,'calculated','FY','2025-12-31',true)",
                {"user": user_id, "stock": stock_id},
            ),
            (
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "period_type,period_end_date,is_current) VALUES "
                "(:user,:stock,'derived.r26',1,'derived','FY','2025-12-31',true)",
                {"user": user_id, "stock": stock_id},
            ),
            (
                "INSERT INTO research_cases (user_id,stock_id,state) "
                "VALUES (:user,:stock,'queued')",
                {"user": user_id, "stock": stock_id},
            ),
            (
                "INSERT INTO research_case_origins "
                "(case_id,origin_type,origin_key,source_version) VALUES "
                "(:case,'manual','late-origin','r26')",
                {"case": case_id},
            ),
            (
                "INSERT INTO research_case_revisions "
                "(case_id,revision_number,case_state,is_qualified_decision,"
                "snapshot_stock_id,stock_ticker,stock_company_name,stock_exchange,"
                "created_by_user_id) VALUES "
                "(:case,1,'queued',false,:stock,'R26PERM','R26 Privacy','NYSE',:user)",
                {"case": case_id, "stock": stock_id, "user": user_id},
            ),
            (
                "INSERT INTO research_case_events "
                "(case_id,event_type,actor_user_id,payload_json) VALUES "
                "(:case,'late_write',:user,'{}'::jsonb)",
                {"case": case_id, "user": user_id},
            ),
        ]
        for sql, params in mutations:
            with pytest.raises(DBAPIError, match="permanently erased"):
                with connection.begin_nested():
                    connection.execute(text(sql), params)


def test_r26_erasure_event_requires_exact_current_operation(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        owner_id = _seed_user(connection, "event-owner")
        other_id = _seed_user(connection, "event-other")

    with engine.begin() as connection:
        with pytest.raises(DBAPIError, match="not authorized"):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO account_erasure_events "
                        "(user_id,content_hash,summary_json) "
                        "VALUES (:user,:hash,'{}'::jsonb)"
                    ),
                    {"user": owner_id, "hash": "a" * 64},
                )

        with pytest.raises(DBAPIError, match="capability rejected"):
            with connection.begin_nested():
                connection.scalar(
                    text(
                        "SELECT begin_privacy_erasure_operation("
                        ":user,'account_erasure','wrong-capability')"
                    ),
                    {"user": owner_id},
                )

        operation_id = _begin_erasure(connection, owner_id)
        for target, supplied_operation in (
            (other_id, operation_id),
            (owner_id, operation_id + 999),
        ):
            with pytest.raises(DBAPIError, match="not authorized|operation"):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            "INSERT INTO account_erasure_events "
                            "(user_id,content_hash,summary_json,"
                            "privacy_erasure_operation_id) VALUES "
                            "(:user,:hash,'{}'::jsonb,:operation)"
                        ),
                        {
                            "user": target,
                            "hash": "b" * 64,
                            "operation": supplied_operation,
                        },
                    )

        connection.execute(
            text(
                "INSERT INTO account_erasure_events "
                "(user_id,content_hash,summary_json,privacy_erasure_operation_id) "
                "VALUES (:user,:hash,'{}'::jsonb,:operation)"
            ),
            {
                "user": owner_id,
                "hash": "c" * 64,
                "operation": operation_id,
            },
        )
        event = connection.execute(
            text(
                "SELECT privacy_erasure_operation_id,created_txid,created_at "
                "FROM account_erasure_events WHERE user_id=:user"
            ),
            {"user": owner_id},
        ).one()
        assert event.privacy_erasure_operation_id == operation_id
        assert event.created_txid == connection.scalar(text("SELECT txid_current()"))
        assert event.created_at is not None


def test_r26_different_user_erasure_operations_do_not_take_a_global_lock(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        first_id = _seed_user(connection, "parallel-first")
        second_id = _seed_user(connection, "parallel-second")

    first = engine.connect()
    second = engine.connect()
    first_tx = first.begin()
    second_tx = second.begin()
    try:
        _begin_erasure(first, first_id)
        second.execute(text("SET LOCAL statement_timeout='750ms'"))
        started = time.monotonic()
        _begin_erasure(second, second_id)
        assert time.monotonic() - started < 0.7
    finally:
        second_tx.rollback()
        first_tx.rollback()
        second.close()
        first.close()


def test_r26_active_user_write_precedes_same_user_erasure_without_deadlock(
    isolated,
) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", HEAD)
    with engine.begin() as connection:
        user_id = _seed_user(connection, "ordered")

    writer = engine.connect()
    eraser = engine.connect()
    writer_tx = writer.begin()
    try:
        assert writer.scalar(
            text("SELECT lock_user_privacy_write(:user)"), {"user": user_id}
        ) is True
        eraser_tx = eraser.begin()
        try:
            eraser.execute(text("SET LOCAL statement_timeout='250ms'"))
            with pytest.raises(DBAPIError, match="statement timeout"):
                _begin_erasure(eraser, user_id)
        finally:
            eraser_tx.rollback()
        writer_tx.commit()

        with eraser.begin():
            _begin_erasure(eraser, user_id)
    finally:
        if writer_tx.is_active:
            writer_tx.rollback()
        eraser.close()
        writer.close()


def test_r26_real_erasure_tombstones_legacy_research_reason_fields(isolated) -> None:
    url, engine = isolated
    _alembic(url, "upgrade", PARENT)
    with engine.begin() as connection:
        user_id = int(
            connection.scalar(
                text(
                    "INSERT INTO users (email,hashed_password,is_active) "
                    "VALUES ('r26-legacy@example.com',:password,true) RETURNING id"
                ),
                {"password": hash_password("ErasePass123!")},
            )
        )
        stock_id = _seed_stock(connection, "legacy")
        case_id = int(
            connection.scalar(
                text(
                    "INSERT INTO research_cases "
                    "(user_id,stock_id,state,void_reason,head_revision_number,closed_at) "
                    "VALUES (:user,:stock,'voided','private void reason',1,:now) "
                    "RETURNING id"
                ),
                {
                    "user": user_id,
                    "stock": stock_id,
                    "now": datetime.now(timezone.utc),
                },
            )
        )
        revision_id = int(
            connection.scalar(
                text(
                    "INSERT INTO research_case_revisions "
                    "(case_id,revision_number,thesis,case_state,"
                    "is_qualified_decision,snapshot_stock_id,stock_ticker,"
                    "stock_company_name,stock_exchange,created_by_user_id,"
                    "is_redacted,redaction_content_hash,redaction_reason,"
                    "redacted_by_user_id,redacted_at) VALUES "
                    "(:case,1,'[redacted]','voided',false,:stock,'R26LEGACY',"
                    "'R26 Privacy','NYSE',:user,true,:hash,"
                    "'private revision reason',:user,:now) RETURNING id"
                ),
                {
                    "case": case_id,
                    "stock": stock_id,
                    "user": user_id,
                    "hash": "a" * 64,
                    "now": datetime.now(timezone.utc),
                },
            )
        )
        event_id = int(
            connection.scalar(
                text(
                    "INSERT INTO research_case_events "
                    "(case_id,event_type,actor_user_id,payload_json) VALUES "
                    "(:case,'revision_redacted',:user,CAST(:payload AS jsonb)) "
                    "RETURNING id"
                ),
                {
                    "case": case_id,
                    "user": user_id,
                    "payload": (
                        '{"revision_id":%d,"reason":"private event reason"}'
                        % revision_id
                    ),
                },
            )
        )

    _alembic(url, "upgrade", HEAD)
    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        result = erase_account(
            session, user=user, password="ErasePass123!"
        )
        assert result["status"] == "erased"

    with engine.begin() as connection:
        case = connection.execute(
            text(
                "SELECT void_reason,void_reason_content_hash FROM research_cases "
                "WHERE id=:id"
            ),
            {"id": case_id},
        ).one()
        revision = connection.execute(
            text(
                "SELECT redaction_reason,redaction_reason_content_hash "
                "FROM research_case_revisions WHERE id=:id"
            ),
            {"id": revision_id},
        ).one()
        event = connection.scalar(
            text("SELECT payload_json FROM research_case_events WHERE id=:id"),
            {"id": event_id},
        )
        assert case.void_reason == "[redacted]"
        assert len(case.void_reason_content_hash) == 64
        assert revision.redaction_reason == "[redacted]"
        assert len(revision.redaction_reason_content_hash) == 64
        assert event["reason"] == "[redacted]"
        assert len(event["redaction_reason_content_hash"]) == 64

    downgrade = subprocess.run(
        ["alembic", "downgrade", PARENT],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert downgrade.returncode != 0
    assert "cannot discard permanent account erasure barriers" in (
        downgrade.stdout + downgrade.stderr
    )
