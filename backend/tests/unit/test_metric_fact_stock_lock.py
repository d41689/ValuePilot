from __future__ import annotations

import threading
from uuid import uuid4
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal
from app.models.stocks import Stock
from app.models.users import User


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic/versions/20260901280000-metric-fact-stock-lock.py"
)
LOCKING_SERVICE = (
    Path(__file__).resolve().parents[2]
    / "app/services/metric_fact_locking.py"
)
RESEARCH_SERVICE = (
    Path(__file__).resolve().parents[2]
    / "app/services/research_cases.py"
)


def _bootstrap_lock_entities() -> tuple[int, int, int]:
    suffix = uuid4().hex[:12]
    bootstrap = SessionLocal()
    user = User(email=f"metric-fact-lock-{suffix}@example.com")
    first = Stock(ticker=f"LA{suffix[:4]}", exchange="NYSE", company_name="Lock A")
    second = Stock(ticker=f"LB{suffix[:4]}", exchange="NYSE", company_name="Lock B")
    bootstrap.add_all([user, first, second])
    bootstrap.commit()
    identities = (user.id, first.id, second.id)
    bootstrap.close()
    return identities


def _cleanup_lock_entities(user_id: int, first_id: int, second_id: int) -> None:
    cleanup = SessionLocal()
    try:
        for stock_id in (first_id, second_id):
            document_id = cleanup.execute(
                text(
                    "INSERT INTO pdf_documents "
                    "(user_id,stock_id,file_name,file_storage_key,source,parse_status,"
                    "identity_needs_review) VALUES (:user_id,:stock_id,:file,:file,"
                    "'value_line','pending',false) RETURNING id"
                ),
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "file": f"lock-cleanup-{stock_id}.pdf",
                },
            ).scalar_one()
            cleanup.execute(
                text(
                    "UPDATE metric_facts SET source_document_id=:document_id "
                    "WHERE stock_id=:stock_id"
                ),
                {"document_id": document_id, "stock_id": stock_id},
            )
            cleanup.execute(
                text("DELETE FROM pdf_documents WHERE id=:document_id"),
                {"document_id": document_id},
            )
        cleanup.execute(
            text("DELETE FROM stocks WHERE id IN (:first_id, :second_id)"),
            {"first_id": first_id, "second_id": second_id},
        )
        cleanup.execute(text("DELETE FROM users WHERE id=:user_id"), {"user_id": user_id})
        cleanup.commit()
    finally:
        cleanup.close()


def _assert_mutation_waits_for_stock_lock(
    *,
    locked_stock_id: int,
    statement: str,
    parameters: dict[str, int],
    expected_error: str | None = None,
) -> None:
    owner = SessionLocal()
    finished = threading.Event()
    started = threading.Event()
    errors: list[Exception] = []

    def mutate() -> None:
        contender = SessionLocal()
        try:
            started.set()
            contender.execute(text(statement), parameters)
            contender.commit()
        except Exception as error:  # pragma: no cover - assertion reports it
            contender.rollback()
            errors.append(error)
        finally:
            contender.close()
            finished.set()

    worker = threading.Thread(target=mutate, daemon=True)
    try:
        owner.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('valuepilot:metric-facts-stock:' || "
                "CAST(:stock_id AS text), 0))"
            ),
            {"stock_id": locked_stock_id},
        )
        worker.start()
        assert started.wait(timeout=2)
        assert not finished.wait(timeout=0.25)
        owner.commit()
        assert finished.wait(timeout=10)
        worker.join(timeout=10)
        if expected_error is None:
            assert not errors
        else:
            assert len(errors) == 1
            assert expected_error in str(errors[0])
    finally:
        owner.rollback()
        owner.close()
        if worker.ident is not None:
            worker.join(timeout=10)


def test_metric_fact_stock_lock_migration_handles_every_mutation_identity():
    source = MIGRATION.read_text()
    locking_source = LOCKING_SERVICE.read_text()

    assert "BEFORE INSERT OR UPDATE OR DELETE ON metric_facts" in source
    assert "OLD.stock_id" in source
    assert "NEW.stock_id" in source
    assert "LEAST(old_stock_id, new_stock_id)" in source
    assert "GREATEST(old_stock_id, new_stock_id)" in source
    assert "pg_advisory_xact_lock" in source
    assert "valuepilot:metric-facts-stock:" in source
    assert "valuepilot:metric-facts-stock:" in locking_source
    assert "DROP TRIGGER IF EXISTS trg_metric_facts_stock_lock" in source


def test_dcf_save_acquires_matching_stock_lock_before_validation_reads():
    endpoint = (
        Path(__file__).resolve().parents[2]
        / "app/api/v1/endpoints/stocks.py"
    ).read_text()
    save = endpoint[endpoint.index("def upsert_stock_fact(") :]

    assert save.index("acquire_metric_fact_stock_lock(") < save.index(
        "stock = session.get(Stock, stock_id)"
    )


def test_research_revision_paths_take_metric_lock_before_research_locks():
    source = RESEARCH_SERVICE.read_text()
    product_save = source[source.index("def save_product_valuation_revision(") :]
    revision_save = source[
        source.index("def save_revision(") : source.index("def research_decision_metrics(")
    ]

    assert product_save.index("acquire_metric_fact_stock_lock(") < product_save.index(
        "create_or_open_case("
    )
    assert revision_save.index("acquire_metric_fact_stock_lock(") < revision_save.index(
        "case = _owned_case("
    )


def test_metric_fact_trigger_serializes_same_stock_but_not_other_stock():
    # Use a committed bootstrap transaction because the lock contract must be
    # exercised by independent database sessions, not the test fixture's
    # intentionally uncommitted outer transaction.
    user_id, first_id, second_id = _bootstrap_lock_entities()

    owner = SessionLocal()
    finished = threading.Event()
    started = threading.Event()
    errors: list[Exception] = []

    def insert_same_stock() -> None:
        contender = SessionLocal()
        try:
            started.set()
            contender.execute(
                text(
                    """
                    INSERT INTO metric_facts
                      (user_id, stock_id, metric_key, value_numeric,
                       source_type, is_current)
                    VALUES (:user_id, :stock_id, 'test.locked', 1,
                            'manual', true)
                    """
                ),
                {"user_id": user_id, "stock_id": first_id},
            )
            contender.commit()
        except Exception as error:  # pragma: no cover - assertion reports it
            contender.rollback()
            errors.append(error)
        finally:
            contender.close()
            finished.set()

    worker = threading.Thread(target=insert_same_stock, daemon=True)
    try:
        owner.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('valuepilot:metric-facts-stock:' || "
                "CAST(:stock_id AS text), 0))"
            ),
            {"stock_id": first_id},
        )
        worker.start()
        assert started.wait(timeout=2)
        assert not finished.wait(timeout=0.25)

        other = SessionLocal()
        try:
            other.execute(
                text(
                    """
                    INSERT INTO metric_facts
                      (user_id, stock_id, metric_key, value_numeric,
                       source_type, is_current)
                    VALUES (:user_id, :stock_id, 'test.unlocked', 1,
                            'manual', true)
                    """
                ),
                {"user_id": user_id, "stock_id": second_id},
            )
            other.commit()
        finally:
            other.close()

        owner.commit()
        assert finished.wait(timeout=10)
        worker.join(timeout=10)
        assert not errors
    finally:
        owner.rollback()
        owner.close()
        if worker.ident is not None:
            worker.join(timeout=10)
        _cleanup_lock_entities(user_id, first_id, second_id)


def test_metric_fact_trigger_locks_both_update_identities_and_delete():
    user_id, first_id, second_id = _bootstrap_lock_entities()
    try:
        bootstrap = SessionLocal()
        update_fact_id = bootstrap.execute(
            text(
                """
                INSERT INTO metric_facts
                  (user_id, stock_id, metric_key, value_numeric, source_type, is_current)
                VALUES (:user_id, :stock_id, 'test.update-lock', 1, 'manual', true)
                RETURNING id
                """
            ),
            {"user_id": user_id, "stock_id": first_id},
        ).scalar_one()
        delete_fact_id = bootstrap.execute(
            text(
                """
                INSERT INTO metric_facts
                  (user_id, stock_id, metric_key, value_numeric, source_type, is_current)
                VALUES (:user_id, :stock_id, 'test.delete-lock', 1, 'manual', true)
                RETURNING id
                """
            ),
            {"user_id": user_id, "stock_id": first_id},
        ).scalar_one()
        bootstrap.commit()
        bootstrap.close()

        _assert_mutation_waits_for_stock_lock(
            locked_stock_id=second_id,
            statement="UPDATE metric_facts SET stock_id=:new_stock_id WHERE id=:fact_id",
            parameters={"new_stock_id": second_id, "fact_id": update_fact_id},
            expected_error="canonical slot identity is immutable",
        )
        _assert_mutation_waits_for_stock_lock(
            locked_stock_id=first_id,
            statement="DELETE FROM metric_facts WHERE id=:fact_id",
            parameters={"fact_id": delete_fact_id},
            expected_error="metric facts cannot be deleted directly",
        )
    finally:
        _cleanup_lock_entities(user_id, first_id, second_id)
