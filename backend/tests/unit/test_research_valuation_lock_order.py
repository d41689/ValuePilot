from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.research import ResearchCaseRevision
from app.models.stocks import PoolMembership, Stock, StockPool
from app.models.users import User
from app.services.metric_fact_locking import acquire_metric_fact_stock_lock
from app.services.research_cases import save_product_valuation_revision
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BACKEND = Path(__file__).resolve().parents[2]
BASE_DATABASE_URL = make_url(settings.SQLALCHEMY_DATABASE_URI).set(
    query={
        key: value
        for key, value in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items()
        if key != "options"
    }
).render_as_string(hide_password=False)


@pytest.fixture
def isolated_session_factory():
    schema_name = new_test_schema_name()
    database_url = build_isolated_database_url(BASE_DATABASE_URL, schema_name)
    create_test_schema(BASE_DATABASE_URL, schema_name)
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine, sessionmaker(bind=engine, autoflush=False)
    finally:
        engine.dispose()
        drop_test_schema(BASE_DATABASE_URL, schema_name)


def _wait_until_advisory_wait(engine, backend_pid: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as observer:
            wait_event = observer.execute(
                text(
                    "SELECT wait_event FROM pg_stat_activity "
                    "WHERE pid=:backend_pid"
                ),
                {"backend_pid": backend_pid},
            ).scalar_one_or_none()
        if str(wait_event or "").lower() == "advisory":
            return
        threading.Event().wait(0.02)
    raise AssertionError("competing valuation did not reach the expected advisory wait")


def test_dcf_and_manual_watchlist_saves_follow_metric_then_research_lock_order(
    isolated_session_factory,
):
    engine, SessionFactory = isolated_session_factory

    for ordinal, source in enumerate(("manual", "watchlist"), start=1):
        bootstrap = SessionFactory()
        user = User(email=f"lock-order-{source}@example.com")
        stock = Stock(
            ticker=f"LK{ordinal}",
            exchange="NYSE",
            company_name=f"Lock order {source}",
        )
        bootstrap.add_all([user, stock])
        bootstrap.flush()
        pool_id = None
        if source == "watchlist":
            pool = StockPool(user_id=user.id, name="Lock order")
            bootstrap.add(pool)
            bootstrap.flush()
            pool_id = pool.id
            bootstrap.add(
                PoolMembership(
                    user_id=user.id,
                    pool_id=pool.id,
                    stock_id=stock.id,
                    inclusion_type="manual",
                )
            )
        bootstrap.commit()
        user_id = user.id
        stock_id = stock.id
        bootstrap.close()

        owner = SessionFactory()
        contender_started = threading.Event()
        contender_finished = threading.Event()
        contender_pid: list[int] = []
        errors: list[BaseException] = []

        def save_competing_valuation() -> None:
            contender = SessionFactory()
            try:
                contender_pid.append(
                    contender.execute(text("SELECT pg_backend_pid()"))
                    .scalar_one()
                )
                contender_started.set()
                save_product_valuation_revision(
                    contender,
                    user_id=user_id,
                    stock_id=stock_id,
                    value_numeric=Decimal("90"),
                    valuation_low=None,
                    valuation_high=None,
                    as_of_date=date(2026, 9, 3),
                    source=source,
                    pool_id=pool_id,
                    assumptions=[],
                    valuation_currency="USD",
                )
            except BaseException as error:  # pragma: no cover - assertion reports it
                contender.rollback()
                errors.append(error)
            finally:
                contender.close()
                contender_finished.set()

        worker = threading.Thread(target=save_competing_valuation, daemon=True)
        try:
            acquire_metric_fact_stock_lock(owner, stock_id=stock_id)
            worker.start()
            assert contender_started.wait(timeout=2)
            _wait_until_advisory_wait(engine, contender_pid[0])

            try:
                save_product_valuation_revision(
                    owner,
                    user_id=user_id,
                    stock_id=stock_id,
                    value_numeric=Decimal("100"),
                    valuation_low=None,
                    valuation_high=None,
                    as_of_date=date(2026, 9, 3),
                    source="dcf",
                    pool_id=None,
                    assumptions=[],
                    valuation_currency="USD",
                )
            except BaseException as error:  # pragma: no cover - assertion reports it
                owner.rollback()
                errors.append(error)
        finally:
            owner.rollback()
            owner.close()
            if worker.ident is not None:
                worker.join(timeout=10)

        assert contender_finished.wait(timeout=10)
        worker.join(timeout=10)
        assert not errors

        verify = SessionFactory()
        revisions = verify.scalars(
            select(ResearchCaseRevision).where(
                ResearchCaseRevision.snapshot_stock_id == stock_id
            )
        ).all()
        assert len(revisions) == 2
        assert {revision.valuation_base for revision in revisions} == {
            Decimal("90"),
            Decimal("100"),
        }
        verify.close()
