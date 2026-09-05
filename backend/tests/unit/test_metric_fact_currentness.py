from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.metric_fact_currentness import (
    HistoricalCurrentnessUnverifiableError,
    current_metric_fact_ids_at,
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
                    db_session, knowledge_cutoff=cutoff
                )
            ),
            MetricFact.stock_id == stock.id,
        )
    ).all()
    at_after = db_session.scalars(
        select(MetricFact.id).where(
            MetricFact.id.in_(
                current_metric_fact_ids_at(db_session, knowledge_cutoff=after)
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
                            reader, knowledge_cutoff=cutoff
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
                            reader, knowledge_cutoff=after
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
            cleanup.execute(
                text("DELETE FROM metric_facts WHERE id=:fact"), {"fact": fact_id}
            )
            cleanup.execute(text("DELETE FROM users WHERE id=:user"), {"user": user_id})
            cleanup.execute(
                text("DELETE FROM stocks WHERE id=:stock"), {"stock": stock_id}
            )
