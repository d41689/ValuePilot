from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User
from app.services.active_report_resolver import resolve_active_reports
from app.services.actual_conflict_service import detect_actual_conflicts
from app.services.canonical_financials import database_evaluation_cutoff
from app.services.value_line_report_identity import ReportIdentityUnverifiableError


def _document(db_session, *, user_id: int, stock_id: int, name: str, report_date: date):
    document = PdfDocument(
        user_id=user_id,
        file_name=name,
        source="value_line",
        file_storage_key=f"tests/{name}",
        parse_status="parsed",
        stock_id=stock_id,
        report_date=report_date,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _actual_fact(
    db_session,
    *,
    user_id: int,
    stock_id: int,
    document_id: int,
    value: int,
    is_current: bool,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
):
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key="is.net_income",
        value_json={"fact_nature": "actual"},
        value_numeric=value,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        source_document_id=document_id,
        is_current=is_current,
        created_at=created_at,
        updated_at=updated_at,
    )
    db_session.add(fact)
    db_session.flush()
    return fact


def test_active_report_binds_fact_to_identity_known_when_fact_was_created(
    db_session,
):
    user = User(email="report-identity-active@example.com")
    stock = Stock(ticker="RIACT", exchange="NYSE", company_name="RI Active")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-active.pdf",
        report_date=date(2026, 1, 9),
    )
    _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        value=100,
        is_current=True,
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)

    document.report_date = date(2026, 7, 9)
    db_session.commit()

    active = resolve_active_reports(
        db_session,
        stock_ids=[stock.id],
        current_user_id=user.id,
        knowledge_cutoff=cutoff,
    )
    assert active[stock.id].document_id == document.id
    assert active[stock.id].report_date == date(2026, 1, 9)


def test_conflict_ranking_uses_fact_bound_identity_before_metadata_change(
    db_session,
):
    user = User(email="report-identity-conflict@example.com")
    stock = Stock(ticker="RICONF", exchange="NYSE", company_name="RI Conflict")
    db_session.add_all([user, stock])
    db_session.flush()
    old_document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-conflict-old.pdf",
        report_date=date(2026, 1, 9),
    )
    new_document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-conflict-new.pdf",
        report_date=date(2026, 4, 9),
    )
    _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=old_document.id,
        value=100,
        is_current=False,
    )
    new_fact = _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=new_document.id,
        value=120,
        is_current=True,
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)

    old_document.report_date = date(2026, 7, 9)
    new_fact.is_current = False
    db_session.commit()

    active = resolve_active_reports(
        db_session,
        stock_ids=[stock.id],
        current_user_id=user.id,
        knowledge_cutoff=cutoff,
    )[stock.id]
    conflicts = detect_actual_conflicts(
        db_session,
        stock_id=stock.id,
        active_report=active,
        current_user_id=user.id,
        knowledge_cutoff=cutoff,
    )

    assert active.document_id == new_document.id
    assert conflicts[0]["current_source_document_id"] == new_document.id
    assert conflicts[0]["current_report_date"] == "2026-04-09"
    assert conflicts[0]["previous_report_date"] == "2026-01-09"


def test_identity_unknown_at_cutoff_is_typed_unverifiable(db_session):
    user = User(email="report-identity-legacy@example.com")
    stock = Stock(ticker="RILEG", exchange="NYSE", company_name="RI Legacy")
    db_session.add_all([user, stock])
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)

    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-legacy.pdf",
        report_date=date(2026, 1, 9),
    )
    fact = _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        value=100,
        is_current=True,
        created_at=cutoff - timedelta(minutes=1),
        updated_at=cutoff - timedelta(minutes=1),
    )
    db_session.commit()

    with pytest.raises(ReportIdentityUnverifiableError) as raised:
        resolve_active_reports(
            db_session,
            stock_ids=[stock.id],
            current_user_id=user.id,
            knowledge_cutoff=cutoff,
        )
    assert raised.value.code == "historical_report_identity_unverifiable"
