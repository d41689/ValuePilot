from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.metric_fact_currentness import (
    CurrentnessScope,
    CurrentnessScopeError,
    HistoricalCurrentnessUnverifiableError,
    current_metric_fact_ids_at,
)
from app.services.evaluation_snapshot import database_evaluation_snapshot


def _cascade_delete_manual_fact(connection, *, fact_id: int, user_id: int, stock_id: int):
    document_id = connection.scalar(
        text(
            "INSERT INTO pdf_documents "
            "(user_id,stock_id,file_name,file_storage_key,source,parse_status,"
            "identity_needs_review) "
            "VALUES (:user,:stock,'cleanup.pdf','cleanup.pdf','upload','pending',false) "
            "RETURNING id"
        ),
        {"user": user_id, "stock": stock_id},
    )
    connection.execute(
        text("UPDATE metric_facts SET source_document_id=:doc WHERE id=:fact"),
        {"doc": document_id, "fact": fact_id},
    )
    connection.execute(
        text("DELETE FROM pdf_documents WHERE id=:doc"), {"doc": document_id}
    )


def test_currentness_reconstructs_pre_supersession_winner(
    db_session, user_factory
) -> None:
    user = user_factory("currentness-pit@example.com")
    stock = Stock(ticker="CURPIT", exchange="NYSE", company_name="Current PIT")
    db_session.add(stock)
    db_session.flush()
    prior = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.revenue",
        value_json={},
        value_numeric=100,
        source_type="manual",
        period_type="FY",
        is_current=True,
    )
    db_session.add(prior)
    db_session.commit()
    cutoff = db_session.scalar(select(text("clock_timestamp()")))

    prior.is_current = False
    replacement = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.revenue",
        value_json={},
        value_numeric=120,
        source_type="manual",
        period_type="FY",
        is_current=True,
    )
    db_session.add(replacement)
    db_session.commit()
    after = db_session.scalar(select(text("clock_timestamp()")))

    at_cutoff = db_session.scalars(
        select(MetricFact.id).where(
            MetricFact.id.in_(
                current_metric_fact_ids_at(
                    db_session,
                    knowledge_cutoff=cutoff,
                    scope=CurrentnessScope.one_stock(stock.id),
                )
            ),
            MetricFact.stock_id == stock.id,
        )
    ).all()
    at_after = db_session.scalars(
        select(MetricFact.id).where(
            MetricFact.id.in_(
                current_metric_fact_ids_at(
                    db_session,
                    knowledge_cutoff=after,
                    scope=CurrentnessScope.one_stock(stock.id),
                )
            ),
            MetricFact.stock_id == stock.id,
        )
    ).all()

    assert at_cutoff == [prior.id]
    assert at_after == [replacement.id]


def test_currentness_before_conservative_backfill_boundary_is_typed(
    db_session,
) -> None:
    authority_started_at = db_session.scalar(
        text(
            "SELECT authority_started_at FROM metric_fact_currentness_authority "
            "WHERE singleton=true"
        )
    )
    with pytest.raises(HistoricalCurrentnessUnverifiableError) as captured:
        current_metric_fact_ids_at(
            db_session,
            knowledge_cutoff=authority_started_at - timedelta(microseconds=1),
            scope=CurrentnessScope(metric_keys=("is.revenue",)),
        )
    assert captured.value.code == "historical_currentness_unverifiable"


def test_currentness_reader_does_not_observe_uncommitted_demotion(
    db_session,
) -> None:
    engine = db_session.get_bind().engine
    with engine.begin() as setup:
        user_id = setup.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) VALUES "
                "('currentness-concurrent@example.com','x',true) RETURNING id"
            )
        )
        stock_id = setup.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,company_name,is_active) VALUES "
                "('CURCON','NYSE','Current Concurrent',true) RETURNING id"
            )
        )
        fact_id = setup.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                "period_type,is_current) VALUES "
                "(:user,:stock,'is.revenue','{}',100,'manual','FY',true) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )

    writer = engine.connect()
    writer_transaction = writer.begin()
    try:
        writer.execute(
            text("UPDATE metric_facts SET is_current=false WHERE id=:fact"),
            {"fact": fact_id},
        )
        with Session(engine) as reader:
            cutoff = reader.scalar(select(text("clock_timestamp()")))
            assert reader.scalars(
                select(MetricFact.id).where(
                    MetricFact.id.in_(
                        current_metric_fact_ids_at(
                            reader,
                            knowledge_cutoff=cutoff,
                            scope=CurrentnessScope(fact_ids=(fact_id,)),
                        )
                    ),
                    MetricFact.id == fact_id,
                )
            ).all() == [fact_id]

        writer_transaction.commit()
        with Session(engine) as reader:
            after = reader.scalar(select(text("clock_timestamp()")))
            assert reader.scalars(
                select(MetricFact.id).where(
                    MetricFact.id.in_(
                        current_metric_fact_ids_at(
                            reader,
                            knowledge_cutoff=after,
                            scope=CurrentnessScope(fact_ids=(fact_id,)),
                        )
                    ),
                    MetricFact.id == fact_id,
                )
            ).all() == []
    finally:
        if writer_transaction.is_active:
            writer_transaction.rollback()
        writer.close()
        with engine.begin() as cleanup:
            _cascade_delete_manual_fact(
                cleanup, fact_id=fact_id, user_id=user_id, stock_id=stock_id
            )
            cleanup.execute(text("DELETE FROM users WHERE id=:user"), {"user": user_id})
            cleanup.execute(
                text("DELETE FROM stocks WHERE id=:stock"), {"stock": stock_id}
            )


def test_snapshot_excludes_fact_committed_after_boundary(db_session) -> None:
    engine = db_session.get_bind().engine
    with engine.begin() as setup:
        user_id = setup.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) VALUES "
                "('currentness-late-commit@example.com','x',true) RETURNING id"
            )
        )
        stock_id = setup.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,company_name,is_active) VALUES "
                "('CURLATE','NYSE','Current Late',true) RETURNING id"
            )
        )

    writer = engine.connect()
    transaction = writer.begin()
    try:
        fact_id = writer.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                "period_type,is_current) VALUES "
                "(:user,:stock,'is.revenue','{}',100,'manual','FY',true) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )
        with Session(engine) as reader:
            snapshot = database_evaluation_snapshot(reader)
            transaction.commit()
            assert reader.scalars(
                select(MetricFact.id).where(
                    MetricFact.id.in_(
                        current_metric_fact_ids_at(
                            reader,
                            knowledge_cutoff=snapshot.cutoff,
                            knowledge_txid_snapshot=snapshot.visibility_snapshot,
                            scope=CurrentnessScope(fact_ids=(fact_id,)),
                        )
                    )
                )
            ).all() == []
    finally:
        if transaction.is_active:
            transaction.rollback()
        writer.close()
        with engine.begin() as cleanup:
            _cascade_delete_manual_fact(
                cleanup, fact_id=fact_id, user_id=user_id, stock_id=stock_id
            )
            cleanup.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
            cleanup.execute(text("DELETE FROM stocks WHERE id=:id"), {"id": stock_id})


def test_evaluation_snapshot_cache_never_crosses_transaction_boundary(
    db_session,
) -> None:
    engine = db_session.get_bind().engine
    with Session(engine) as session:
        first = database_evaluation_snapshot(session)
        first_txid = session.scalar(text("SELECT txid_current()"))
        assert database_evaluation_snapshot(session, first.cutoff) is first
        session.commit()

        second = database_evaluation_snapshot(session, first.cutoff)
        second_txid = session.scalar(text("SELECT txid_current()"))

        assert second.cutoff == first.cutoff
        assert second_txid != first_txid
        assert second.visibility_snapshot != first.visibility_snapshot


def test_currentness_rejects_unbounded_and_oversized_scopes(db_session) -> None:
    snapshot = database_evaluation_snapshot(db_session)
    with pytest.raises(CurrentnessScopeError, match="explicit bounded"):
        current_metric_fact_ids_at(db_session, knowledge_cutoff=snapshot.cutoff)
    with pytest.raises(CurrentnessScopeError, match="exceeds"):
        current_metric_fact_ids_at(
            db_session,
            knowledge_cutoff=snapshot.cutoff,
            scope=CurrentnessScope(fact_ids=tuple(range(1, 1002))),
        )
