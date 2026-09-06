from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.api.v1.endpoints import stocks as stocks_endpoint
from app.services.metric_fact_currentness import (
    CurrentnessScope,
    CurrentnessScopeError,
    HistoricalCurrentnessUnverifiableError,
    current_metric_fact_ids_at,
    iter_current_metric_fact_id_chunks_at,
)
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.valuation import read_valuation_contexts


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


def test_candidate_visibility_keeps_current_transaction_read_your_writes(
    db_session, user_factory
) -> None:
    user = user_factory("r24-currentness-ryw@example.com")
    stock = Stock(ticker="R24RYW", exchange="NYSE", company_name="R24 RYW")
    db_session.add(stock)
    db_session.flush()
    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="r24.ryw",
        value_json={},
        value_numeric=1,
        source_type="fixture",
        period_type="FY",
        is_current=True,
    )
    db_session.add(fact)
    db_session.flush()
    snapshot = database_evaluation_snapshot(db_session)

    assert db_session.scalars(
        current_metric_fact_ids_at(
            db_session,
            knowledge_cutoff=snapshot.cutoff,
            knowledge_txid_snapshot=snapshot.visibility_snapshot,
            scope=CurrentnessScope(fact_ids=(fact.id,)),
        )
    ).all() == [fact.id]


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


def test_post_snapshot_facts_do_not_consume_candidate_scope_bound(db_session) -> None:
    """The N+1 guard is applied to facts visible at T, not the live table."""

    engine = db_session.get_bind().engine
    with engine.begin() as setup:
        user_id = setup.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) VALUES "
                "('r24-candidate-visibility@example.com','x',true) RETURNING id"
            )
        )
        stock_id = setup.scalar(
            text(
                "INSERT INTO stocks (ticker,exchange,company_name,is_active) VALUES "
                "('R24VIS','NYSE','R24 Visibility',true) RETURNING id"
            )
        )
        visible_id = setup.scalar(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                "period_type,is_current) VALUES "
                "(:user,:stock,'r24.visibility','{}',1,'fixture','FY',true) "
                "RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )

    with Session(engine) as reader:
        snapshot = database_evaluation_snapshot(reader)
        with engine.begin() as writer:
            writer.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                    "period_type,is_current,created_at) "
                    "SELECT :user,:stock,'r24.visibility','{}',g,'fixture','FY',true,"
                    "'2000-01-01T00:00:00Z'::timestamptz "
                    "FROM generate_series(1,1001) AS g"
                ),
                {"user": user_id, "stock": stock_id},
            )

        selected = reader.scalars(
            current_metric_fact_ids_at(
                reader,
                knowledge_cutoff=snapshot.cutoff,
                knowledge_txid_snapshot=snapshot.visibility_snapshot,
                scope=CurrentnessScope.one_stock(
                    stock_id, metric_keys=("r24.visibility",)
                ),
            )
        ).all()
        assert selected == [visible_id]

    with engine.begin() as cleanup:
        document_id = cleanup.scalar(
            text(
                "INSERT INTO pdf_documents "
                "(user_id,stock_id,file_name,file_storage_key,source,parse_status,"
                "identity_needs_review) VALUES "
                "(:user,:stock,'r24-cleanup.pdf','r24-cleanup.pdf','upload',"
                "'pending',false) RETURNING id"
            ),
            {"user": user_id, "stock": stock_id},
        )
        cleanup.execute(
            text(
                "UPDATE metric_facts SET source_document_id=:document "
                "WHERE user_id=:user AND metric_key='r24.visibility'"
            ),
            {"document": document_id, "user": user_id},
        )
        cleanup.execute(
            text("DELETE FROM pdf_documents WHERE id=:document"),
            {"document": document_id},
        )
        cleanup.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
        cleanup.execute(text("DELETE FROM stocks WHERE id=:id"), {"id": stock_id})


def test_multi_stock_keyset_excludes_post_snapshot_backdated_facts(db_session) -> None:
    engine = db_session.get_bind().engine
    with engine.begin() as setup:
        user_id = setup.scalar(
            text(
                "INSERT INTO users (email,hashed_password,is_active) VALUES "
                "('r24-keyset-visibility@example.com','x',true) RETURNING id"
            )
        )
        stock_ids = list(
            setup.scalars(
                text(
                    "INSERT INTO stocks (ticker,exchange,company_name,is_active) "
                    "SELECT 'R24KS' || g,'NYSE','R24 Keyset ' || g,true "
                    "FROM generate_series(1,1001) AS g RETURNING id"
                )
            )
        )
        setup.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                "period_type,is_current) "
                "SELECT :user,id,'r24.keyset','{}',1,'fixture','FY',true "
                "FROM stocks WHERE id = ANY(:stocks)"
            ),
            {"user": user_id, "stocks": stock_ids},
        )

    with Session(engine) as reader:
        snapshot = database_evaluation_snapshot(reader)
        with engine.begin() as writer:
            writer.execute(
                text(
                    "INSERT INTO metric_facts "
                    "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
                    "period_type,is_current,created_at) "
                    "SELECT :user,id,'r24.keyset','{}',2,'fixture','FY',true,"
                    "'2000-01-01T00:00:00Z'::timestamptz "
                    "FROM stocks WHERE id = ANY(:stocks)"
                ),
                {"user": user_id, "stocks": stock_ids},
            )
        selected = [
            fact_id
            for chunk in iter_current_metric_fact_id_chunks_at(
                reader,
                evaluation_snapshot=snapshot,
                scope=CurrentnessScope(
                    stock_ids=tuple(stock_ids),
                    metric_keys=("r24.keyset",),
                    user_ids=(user_id,),
                ),
            )
            for fact_id in chunk
        ]
        assert len(selected) == 1001
        assert reader.scalar(
            select(func.count()).select_from(MetricFact).where(
                MetricFact.id.in_(selected), MetricFact.value_numeric == 1
            )
        ) == 1001

    with engine.begin() as cleanup:
        cleanup.execute(
            text(
                "DELETE FROM metric_facts WHERE user_id=:user "
                "AND metric_key='r24.keyset'"
            ),
            {"user": user_id},
        )
        cleanup.execute(
            text("DELETE FROM stocks WHERE id = ANY(:stocks)"),
            {"stocks": stock_ids},
        )
        cleanup.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})


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


def test_metric_scope_fails_at_n_plus_one_but_large_stock_consumer_chunks(
    db_session, user_factory
) -> None:
    user = user_factory("currentness-1001-stocks@example.com")
    stock_ids = tuple(
        db_session.scalars(
            text(
                "INSERT INTO stocks (ticker,exchange,company_name,is_active) "
                "SELECT 'R23S' || g::text,'NYSE','R23 Stock ' || g::text,true "
                "FROM generate_series(1,1001) AS g RETURNING id"
            )
        )
    )
    db_session.execute(
        text(
            "INSERT INTO metric_facts "
            "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,"
            "period_type,period_end_date,is_current) "
            "SELECT :user,id,'val.fair_value',id,'{}','manual','AS_OF','2025-12-31',true "
            "FROM stocks WHERE id=ANY(:stocks)"
        ),
        {"user": user.id, "stocks": list(stock_ids)},
    )
    snapshot = database_evaluation_snapshot(db_session)

    with pytest.raises(CurrentnessScopeError) as overflow:
        current_metric_fact_ids_at(
            db_session,
            knowledge_cutoff=snapshot.cutoff,
            knowledge_txid_snapshot=snapshot.visibility_snapshot,
            scope=CurrentnessScope(metric_keys=("val.fair_value",)),
        )
    assert overflow.value.code == "metric_fact_currentness_scope_bound_exceeded"

    # Tenant/source predicates constrain the compact candidate query itself;
    # they are not applied only after an unrelated tenant could force overflow.
    globally_visible_ids = db_session.scalars(
        current_metric_fact_ids_at(
            db_session,
            knowledge_cutoff=snapshot.cutoff,
            knowledge_txid_snapshot=snapshot.visibility_snapshot,
            scope=CurrentnessScope(
                metric_keys=("val.fair_value",),
                user_ids=(None,),
            ),
        )
    ).all()
    assert globally_visible_ids == []

    chunks = list(
        iter_current_metric_fact_id_chunks_at(
            db_session,
            evaluation_snapshot=snapshot,
            scope=CurrentnessScope(
                stock_ids=stock_ids,
                metric_keys=("val.fair_value",),
                user_ids=(user.id,),
            ),
        )
    )
    assert sum(len(chunk) for chunk in chunks) == 1001
    assert all(0 < len(chunk) <= 1000 for chunk in chunks)
    contexts = read_valuation_contexts(
        db_session,
        user_id=user.id,
        stock_ids=list(stock_ids),
        knowledge_cutoff=snapshot.cutoff,
    )
    assert len(contexts) == 1001
    assert all(
        context.user_intrinsic_value_status == "available"
        for context in contexts.values()
    )


def test_stock_facts_api_returns_typed_currentness_overflow(
    client, db_session, user_factory, auth_headers
) -> None:
    user = user_factory("currentness-api-overflow@example.com")
    stock = Stock(ticker="R23API", exchange="NYSE", company_name="R23 API Bound")
    db_session.add(stock)
    db_session.flush()
    db_session.execute(
        text(
            "INSERT INTO metric_facts "
            "(user_id,stock_id,metric_key,value_numeric,value_json,source_type,"
            "period_type,is_current) "
            "SELECT :user,:stock,'r23.api.bound',g,'{}','fixture','FY',true "
            "FROM generate_series(1,1001) AS g"
        ),
        {"user": user.id, "stock": stock.id},
    )
    db_session.commit()

    response = client.get(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == (
        "metric_fact_currentness_scope_bound_exceeded"
    )


def test_stock_facts_api_returns_typed_historical_currentness_failure(
    client, db_session, user_factory, auth_headers, monkeypatch
) -> None:
    user = user_factory("r24-currentness-api@example.com")
    stock = Stock(ticker="R24CUR", exchange="NYSE", company_name="R24 Current")
    db_session.add(stock)
    db_session.commit()

    def unavailable(*_args, **_kwargs):
        raise HistoricalCurrentnessUnverifiableError()

    monkeypatch.setattr(stocks_endpoint, "current_metric_fact_ids_at", unavailable)
    response = client.get(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(user),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "historical_currentness_unverifiable"
    )


def test_history_inflation_is_ranked_only_after_exact_fact_candidate_bound(
    db_session, user_factory
) -> None:
    user = user_factory("currentness-history-inflation@example.com")
    stock = Stock(ticker="R23HIST", exchange="NYSE", company_name="R23 History")
    db_session.add(stock)
    db_session.flush()
    fact_id = db_session.scalar(
        text(
            "INSERT INTO metric_facts "
            "(user_id,stock_id,metric_key,value_json,value_numeric,source_type,"
            "period_type,is_current) VALUES "
            "(:user,:stock,'r23.history','{}',1,'fixture','FY',true) RETURNING id"
        ),
        {"user": user.id, "stock": stock.id},
    )
    for ordinal in range(200):
        db_session.execute(
            text("UPDATE metric_facts SET is_current=:state WHERE id=:fact"),
            {"state": ordinal % 2 == 1, "fact": fact_id},
        )
    snapshot = database_evaluation_snapshot(db_session)
    statement = current_metric_fact_ids_at(
        db_session,
        knowledge_cutoff=snapshot.cutoff,
        knowledge_txid_snapshot=snapshot.visibility_snapshot,
        scope=CurrentnessScope.one_stock(
            stock.id, metric_keys=("r23.history",)
        ),
    )
    timeline_sql = str(statement)
    assert "metric_fact_currentness_revisions.fact_id IN" in timeline_sql
    assert "metric_fact_currentness_revisions.stock_id IN" not in timeline_sql
    assert "metric_fact_currentness_revisions.metric_key IN" not in timeline_sql
    assert db_session.scalars(statement).all() == [fact_id]
    assert db_session.scalar(
        text(
            "SELECT count(*) FROM metric_fact_currentness_revisions "
            "WHERE fact_id=:fact"
        ),
        {"fact": fact_id},
    ) == 201
