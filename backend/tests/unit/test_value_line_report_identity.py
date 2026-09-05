from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import sessionmaker

from app.models.artifacts import PdfDocument
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User
from app.services import active_report_resolver
from app.services.active_report_resolver import (
    ActiveReportAuthorityBoundExceededError,
    resolve_active_reports,
)
from app.services import actual_conflict_service
from app.services.actual_conflict_service import (
    ActualConflictAuthorityAmbiguousError,
    ActualConflictAuthorityBoundExceededError,
    detect_actual_conflicts,
)
from app.services.canonical_financials import database_evaluation_cutoff
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.ingestion_service import IngestionService
from app.services.metric_fact_currentness import (
    CurrentnessScope,
    current_metric_fact_ids_at,
)
from app.services.source_reconciliation import (
    CanonicalReconciliationError,
    guard_reconciled_source_selection,
)
from app.services.value_line_report_identity import ReportIdentityUnverifiableError
from app.services.value_line_source_visibility import ValueLineSourceUnavailableError


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
    metric_key: str = "is.net_income",
):
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
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


def test_ingestion_preserves_divergent_same_date_report_identities_as_ambiguity(
    db_session,
):
    user = User(email="r24-ingestion-ambiguity@example.com")
    stock = Stock(ticker="R24AMB", exchange="NYSE", company_name="R24 Ambiguity")
    db_session.add_all([user, stock])
    db_session.flush()
    documents = [
        _document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            name=f"r24-ambiguity-{ordinal}.pdf",
            report_date=date(2026, 1, 9),
        )
        for ordinal in (1, 2)
    ]
    service = IngestionService(db_session)
    for document, value in zip(documents, (100, 120), strict=True):
        run = service._start_value_line_parse_run(
            user_id=user.id,
            document_id=document.id,
        )
        service._insert_metric_fact_from_mapping(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="is.net_income",
            value_numeric=value,
            value_text=None,
            value_json={"fact_nature": "actual"},
            unit="currency",
            currency="USD",
            period_type="FY",
            period_end_date=date(2025, 12, 31),
            source_document_id=document.id,
            value_line_parse_run_id=run.id,
        )
        service._finish_value_line_parse_run(run, status="succeeded")

    snapshot = database_evaluation_snapshot(db_session)
    current_ids = list(
        db_session.scalars(
            current_metric_fact_ids_at(
                db_session,
                knowledge_cutoff=snapshot.cutoff,
                knowledge_txid_snapshot=snapshot.visibility_snapshot,
                scope=CurrentnessScope.one_stock(
                    stock.id,
                    metric_keys=("is.net_income",),
                    user_ids=(user.id,),
                    source_types=("parsed",),
                ),
            )
        )
    )
    assert len(current_ids) == 2
    current_facts = list(
        db_session.scalars(
            select(MetricFact)
            .where(MetricFact.id.in_(current_ids))
            .order_by(MetricFact.id)
        )
    )
    # Exercise the real consumer contract: divergent current parsed
    # observations are an explicit typed block, never an ID-based winner.
    with pytest.raises(CanonicalReconciliationError) as raised:
        guard_reconciled_source_selection(
            current_facts,
            consumer="r24_ingestion_transaction",
            evaluation_snapshot=snapshot,
            session=db_session,
            user_id=user.id,
        )
    assert raised.value.code == "unresolved_source_reconciliation"


def test_ingestion_collapses_equal_same_date_observations_to_one_current_fact(
    db_session,
):
    user = User(email="r24-ingestion-equal@example.com")
    stock = Stock(ticker="R24EQ", exchange="NYSE", company_name="R24 Equal")
    db_session.add_all([user, stock])
    db_session.flush()
    documents = [
        _document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            name=f"r24-equal-{ordinal}.pdf",
            report_date=date(2026, 1, 9),
        )
        for ordinal in (1, 2)
    ]
    service = IngestionService(db_session)
    inserted: list[int] = []
    for document in documents:
        run = service._start_value_line_parse_run(
            user_id=user.id,
            document_id=document.id,
        )
        inserted.append(
            service._insert_metric_fact_from_mapping(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_numeric=100,
                value_text=None,
                value_json={"fact_nature": "actual"},
                unit="currency",
                currency="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_document_id=document.id,
                value_line_parse_run_id=run.id,
            )
        )
        service._finish_value_line_parse_run(run, status="succeeded")

    current = db_session.execute(
        text(
            "SELECT id FROM metric_facts WHERE id = ANY(:ids) AND is_current=true "
            "ORDER BY id"
        ),
        {"ids": inserted},
    ).scalars().all()
    assert current == [max(inserted)]


def test_ingestion_reparse_within_exact_identity_has_one_current_fact(db_session):
    user = User(email="r24-ingestion-reparse@example.com")
    stock = Stock(ticker="R24REP", exchange="NYSE", company_name="R24 Reparse")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="r24-exact-identity.pdf",
        report_date=date(2026, 1, 9),
    )
    service = IngestionService(db_session)
    inserted: list[int] = []
    for value in (100, 120):
        run = service._start_value_line_parse_run(
            user_id=user.id,
            document_id=document.id,
        )
        inserted.append(
            service._insert_metric_fact_from_mapping(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="is.net_income",
                value_numeric=value,
                value_text=None,
                value_json={"fact_nature": "actual"},
                unit="currency",
                currency="USD",
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_document_id=document.id,
                value_line_parse_run_id=run.id,
            )
        )
        service._finish_value_line_parse_run(run, status="succeeded")

    rows = db_session.execute(
        text(
            "SELECT id,is_current,value_line_report_identity_revision_id "
            "FROM metric_facts WHERE id = ANY(:ids) ORDER BY id"
        ),
        {"ids": inserted},
    ).all()
    assert len({row.value_line_report_identity_revision_id for row in rows}) == 1
    assert [(row.id, row.is_current) for row in rows] == [
        (min(inserted), False),
        (max(inserted), True),
    ]


def test_actual_conflicts_reject_501_observations_without_orm_hydration(
    db_session,
):
    user = User(email="actual-conflict-observation-bound@example.com")
    stock = Stock(ticker="ACBOUND", exchange="NYSE", company_name="AC Bound")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="actual-conflict-bound.pdf",
        report_date=date(2026, 1, 9),
    )
    db_session.add_all(
        [
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="custom.repeated_actual",
                value_json={"fact_nature": "actual"},
                value_numeric=100,
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=document.id,
                is_current=False,
            )
            for _ in range(501)
        ]
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)
    stock_id = stock.id
    user_id = user.id
    db_session.expunge_all()

    active_report = resolve_active_reports(
        db_session,
        stock_ids=[stock_id],
        current_user_id=user_id,
        knowledge_cutoff=cutoff,
    )[stock_id]

    loaded_metric_facts = 0

    def count_metric_fact_load(_session, instance):
        nonlocal loaded_metric_facts
        if isinstance(instance, MetricFact):
            loaded_metric_facts += 1

    event.listen(db_session, "loaded_as_persistent", count_metric_fact_load)
    try:
        with pytest.raises(ActualConflictAuthorityBoundExceededError) as raised:
            detect_actual_conflicts(
                db_session,
                stock_id=stock_id,
                active_report=active_report,
                current_user_id=user_id,
                knowledge_cutoff=cutoff,
            )
    finally:
        event.remove(db_session, "loaded_as_persistent", count_metric_fact_load)

    assert raised.value.code == "actual_conflict_authority_bound_exceeded"
    assert raised.value.dimension == "observations"
    assert raised.value.limit == 500
    assert loaded_metric_facts == 0


def test_actual_conflict_bound_counts_duplicate_multi_revision_observations_and_is_tenant_scoped(
    db_session, monkeypatch
):
    owner = User(email="actual-conflict-owner@example.com")
    intruder = User(email="actual-conflict-intruder@example.com")
    stock = Stock(ticker="ACREV", exchange="NYSE", company_name="AC Revisions")
    db_session.add_all([owner, intruder, stock])
    db_session.flush()
    owner_document = _document(
        db_session,
        user_id=owner.id,
        stock_id=stock.id,
        name="actual-conflict-revisions.pdf",
        report_date=date(2026, 1, 9),
    )
    _actual_fact(
        db_session,
        user_id=owner.id,
        stock_id=stock.id,
        document_id=owner_document.id,
        value=100,
        is_current=False,
    )
    db_session.commit()
    owner_document.report_date = date(2026, 4, 9)
    db_session.flush()
    _actual_fact(
        db_session,
        user_id=owner.id,
        stock_id=stock.id,
        document_id=owner_document.id,
        value=100,
        is_current=False,
    )
    intruder_document = _document(
        db_session,
        user_id=intruder.id,
        stock_id=stock.id,
        name="actual-conflict-intruder.pdf",
        report_date=date(2026, 7, 9),
    )
    _actual_fact(
        db_session,
        user_id=intruder.id,
        stock_id=stock.id,
        document_id=intruder_document.id,
        value=999,
        is_current=False,
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)
    monkeypatch.setattr(
        actual_conflict_service,
        "MAX_ACTUAL_CONFLICT_OBSERVATIONS",
        2,
    )

    assert detect_actual_conflicts(
        db_session,
        stock_id=stock.id,
        active_report=None,
        current_user_id=owner.id,
        knowledge_cutoff=cutoff,
    ) == []

    _actual_fact(
        db_session,
        user_id=owner.id,
        stock_id=stock.id,
        document_id=owner_document.id,
        value=100,
        is_current=False,
    )
    db_session.commit()

    with pytest.raises(ActualConflictAuthorityBoundExceededError):
        detect_actual_conflicts(
            db_session,
            stock_id=stock.id,
            active_report=None,
            current_user_id=owner.id,
            knowledge_cutoff=database_evaluation_cutoff(db_session),
        )


def test_actual_conflicts_keep_all_queries_inside_the_captured_fact_universe(
    db_session, monkeypatch
):
    """A pre-cutoff write committed after T is not visible in that replay.

    PostgreSQL READ COMMITTED starts a fresh statement snapshot for each query.
    The currentness snapshot therefore has to bind every later identity,
    source, and observation query to the exact fact IDs it admitted.
    """

    engine = db_session.get_bind().engine
    with engine.begin() as setup:
        user_id = int(
            setup.scalar(
                text(
                    "INSERT INTO users (email,hashed_password,is_active) VALUES "
                    "('actual-conflict-snapshot@example.com','x',true) RETURNING id"
                )
            )
        )
        stock_id = int(
            setup.scalar(
                text(
                    "INSERT INTO stocks (ticker,exchange,company_name,is_active) VALUES "
                    "('ACSNAP','NYSE','AC Snapshot',true) RETURNING id"
                )
            )
        )

    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as setup_session:
        base_document = _document(
            setup_session,
            user_id=user_id,
            stock_id=stock_id,
            name="actual-conflict-snapshot-base.pdf",
            report_date=date(2026, 1, 9),
        )
        _actual_fact(
            setup_session,
            user_id=user_id,
            stock_id=stock_id,
            document_id=base_document.id,
            value=100,
            is_current=True,
        )
        setup_session.commit()

    WriterSession = sessionmaker(bind=engine)
    writer = WriterSession()
    reader = SessionLocal()
    try:
        late_document = _document(
            writer,
            user_id=user_id,
            stock_id=stock_id,
            name="actual-conflict-snapshot-late.pdf",
            report_date=date(2026, 4, 9),
        )
        _actual_fact(
            writer,
            user_id=user_id,
            stock_id=stock_id,
            document_id=late_document.id,
            value=120,
            is_current=True,
        )
        # The fact and its database-owned timestamps exist before T, but this
        # transaction is deliberately absent from T's visibility snapshot.
        writer.flush()

        original_require = actual_conflict_service.require_currentness_authority
        committed = False

        def commit_after_scope(*args, **kwargs):
            nonlocal committed
            if not committed:
                writer.commit()
                committed = True
            return original_require(*args, **kwargs)

        monkeypatch.setattr(
            actual_conflict_service,
            "require_currentness_authority",
            commit_after_scope,
        )
        cutoff = database_evaluation_cutoff(reader)
        historical = detect_actual_conflicts(
            reader,
            stock_id=stock_id,
            active_report=None,
            current_user_id=user_id,
            knowledge_cutoff=cutoff,
        )
        assert historical == []
        assert committed is True

        # A new evaluation snapshot after the writer commits sees both facts.
        reader.commit()
        fresh = detect_actual_conflicts(
            reader,
            stock_id=stock_id,
            active_report=None,
            current_user_id=user_id,
        )
        assert len(fresh) == 1
        assert fresh[0]["current_value_numeric"] == 120.0
        assert fresh[0]["previous_value_numeric"] == 100.0

        read_your_writes_document = _document(
            reader,
            user_id=user_id,
            stock_id=stock_id,
            name="actual-conflict-snapshot-read-your-writes.pdf",
            report_date=date(2026, 7, 9),
        )
        _actual_fact(
            reader,
            user_id=user_id,
            stock_id=stock_id,
            document_id=read_your_writes_document.id,
            value=140,
            is_current=True,
        )
        reader.flush()
        read_your_writes = detect_actual_conflicts(
            reader,
            stock_id=stock_id,
            active_report=None,
            current_user_id=user_id,
        )
        assert len(read_your_writes) == 1
        assert read_your_writes[0]["current_value_numeric"] == 140.0
    finally:
        writer.rollback()
        writer.close()
        reader.rollback()
        reader.close()
        with engine.begin() as cleanup:
            cleanup.execute(
                text("DELETE FROM pdf_documents WHERE user_id=:user"),
                {"user": user_id},
            )
            cleanup.execute(
                text("DELETE FROM users WHERE id=:user"), {"user": user_id}
            )
            cleanup.execute(
                text("DELETE FROM stocks WHERE id=:stock"), {"stock": stock_id}
            )


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
    assert active.report_identity_revision_id == (
        new_fact.value_line_report_identity_revision_id
    )
    assert conflicts[0]["current_source_document_id"] == new_document.id
    assert conflicts[0]["current_report_identity_revision_id"] == (
        new_fact.value_line_report_identity_revision_id
    )
    assert conflicts[0]["current_report_date"] == "2026-04-09"
    assert conflicts[0]["previous_report_date"] == "2026-01-09"


def test_same_latest_report_date_across_documents_fails_closed(db_session):
    user = User(email="report-identity-same-date@example.com")
    stock = Stock(ticker="RISAME", exchange="NYSE", company_name="RI Same Date")
    db_session.add_all([user, stock])
    db_session.flush()
    first = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="same-date-first.pdf",
        report_date=date(2026, 1, 9),
    )
    second = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="same-date-second.pdf",
        report_date=date(2026, 1, 9),
    )
    _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=first.id,
        value=100,
        is_current=True,
    )
    _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=second.id,
        value=120,
        is_current=True,
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)

    with pytest.raises(ActualConflictAuthorityAmbiguousError):
        resolve_active_reports(
            db_session,
            stock_ids=[stock.id],
            current_user_id=user.id,
            knowledge_cutoff=cutoff,
        )
    with pytest.raises(ActualConflictAuthorityAmbiguousError):
        detect_actual_conflicts(
            db_session,
            stock_id=stock.id,
            active_report=None,
            current_user_id=user.id,
            knowledge_cutoff=cutoff,
        )


def test_same_older_report_dates_do_not_block_unique_latest_report(db_session):
    user = User(email="report-identity-old-tie@example.com")
    stock = Stock(ticker="RIOLDT", exchange="NYSE", company_name="RI Old Tie")
    db_session.add_all([user, stock])
    db_session.flush()
    documents = [
        _document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            name=f"old-tie-{index}.pdf",
            report_date=report_date,
        )
        for index, report_date in enumerate(
            [date(2025, 10, 9), date(2025, 10, 9), date(2026, 1, 9)]
        )
    ]
    for index, document in enumerate(documents):
        _actual_fact(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            document_id=document.id,
            value=100 + index,
            is_current=True,
        )
    db_session.commit()

    active = resolve_active_reports(
        db_session,
        stock_ids=[stock.id],
        current_user_id=user.id,
        knowledge_cutoff=database_evaluation_cutoff(db_session),
    )
    assert active[stock.id].document_id == documents[-1].id


def test_same_report_date_equal_values_are_not_an_actual_value_conflict(db_session):
    user = User(email="report-identity-same-value@example.com")
    stock = Stock(ticker="RIEQUAL", exchange="NYSE", company_name="RI Equal")
    db_session.add_all([user, stock])
    db_session.flush()
    for suffix in ("one", "two"):
        document = _document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            name=f"same-value-{suffix}.pdf",
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

    assert detect_actual_conflicts(
        db_session,
        stock_id=stock.id,
        active_report=None,
        current_user_id=user.id,
        knowledge_cutoff=database_evaluation_cutoff(db_session),
    ) == []


@pytest.mark.parametrize("visibility_loss", ["source", "owner"])
def test_report_authority_requires_current_source_visibility(
    db_session, visibility_loss
):
    user = User(email=f"report-source-{visibility_loss}@example.com")
    other = User(email=f"report-source-{visibility_loss}-other@example.com")
    stock = Stock(
        ticker=f"RIV{visibility_loss[0]}",
        exchange="NYSE",
        company_name="RI Visibility",
    )
    db_session.add_all([user, other, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name=f"source-{visibility_loss}.pdf",
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

    if visibility_loss == "source":
        document.source = "unlicensed"
    else:
        document.user_id = other.id
    db_session.commit()

    with pytest.raises(ValueLineSourceUnavailableError) as active_error:
        resolve_active_reports(
            db_session,
            stock_ids=[stock.id],
            current_user_id=user.id,
            knowledge_cutoff=cutoff,
        )
    assert active_error.value.code == "source_unavailable"
    with pytest.raises(ValueLineSourceUnavailableError):
        detect_actual_conflicts(
            db_session,
            stock_id=stock.id,
            active_report=None,
            current_user_id=user.id,
            knowledge_cutoff=cutoff,
        )


def test_same_document_reparse_uses_only_current_canonical_observation(db_session):
    user = User(email="report-identity-reparse-canonical@example.com")
    stock = Stock(ticker="RIREP", exchange="NYSE", company_name="RI Reparse")
    db_session.add_all([user, stock])
    db_session.flush()
    prior_document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-reparse-prior.pdf",
        report_date=date(2025, 10, 9),
    )
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-reparse-current.pdf",
        report_date=date(2026, 1, 9),
    )
    _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=prior_document.id,
        value=90,
        is_current=False,
    )
    stale = _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        value=100,
        is_current=False,
    )
    current = _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        value=120,
        is_current=True,
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)

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

    assert active.report_identity_revision_id == (
        current.value_line_report_identity_revision_id
    )
    observations = conflicts[0]["observations"]
    assert [item["value_numeric"] for item in observations] == [120.0, 90.0]
    assert stale.id not in [item["fact_id"] for item in observations]
    assert observations[0]["fact_id"] == current.id
    assert observations[0]["is_active_report"] is True


def test_old_identity_revision_on_same_document_is_not_active(db_session):
    user = User(email="report-identity-same-document-revision@example.com")
    stock = Stock(ticker="RIREV", exchange="NYSE", company_name="RI Revision")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-revision.pdf",
        report_date=date(2026, 1, 9),
    )
    old_fact = _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        value=100,
        is_current=False,
    )
    db_session.commit()
    document.report_date = date(2026, 4, 9)
    db_session.flush()
    new_fact = _actual_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        value=120,
        is_current=True,
    )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)

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

    assert old_fact.value_line_report_identity_revision_id != (
        new_fact.value_line_report_identity_revision_id
    )
    assert active.report_identity_revision_id == (
        new_fact.value_line_report_identity_revision_id
    )
    by_revision = {
        item["source_report_identity_revision_id"]: item
        for item in conflicts[0]["observations"]
    }
    assert by_revision[old_fact.value_line_report_identity_revision_id][
        "is_active_report"
    ] is False
    assert by_revision[new_fact.value_line_report_identity_revision_id][
        "is_active_report"
    ] is True


def test_same_report_duplicate_without_canonical_winner_fails_closed(db_session):
    user = User(email="report-identity-ambiguous-canonical@example.com")
    stock = Stock(ticker="RIAMB", exchange="NYSE", company_name="RI Ambiguous")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-ambiguous.pdf",
        report_date=date(2026, 1, 9),
    )
    policy_id = db_session.scalar(
        text(
            "SELECT id FROM value_line_mapping_policies "
            "WHERE status='approved' ORDER BY effective_from DESC LIMIT 1"
        )
    )
    run_id = db_session.scalar(
        text(
            "INSERT INTO value_line_parse_runs "
            "(user_id,document_id,parser_version,source_mapping_version,status,"
            "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
            "'running',0) RETURNING id"
        ),
        {"user": user.id, "document": document.id, "policy": policy_id},
    )
    for value in (100, 120):
        db_session.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,period_type,"
                "period_end_date,source_type,source_document_id,is_current,"
                "value_line_parse_run_id) VALUES "
                "(:user,:stock,'is.net_income','{\"fact_nature\":\"actual\"}',"
                ":value,'FY','2025-12-31','parsed',:document,false,:run)"
            ),
            {
                "user": user.id,
                "stock": stock.id,
                "value": value,
                "document": document.id,
                "run": run_id,
            },
        )
    db_session.execute(
        text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
        {"id": run_id},
    )
    db_session.commit()

    with pytest.raises(ActualConflictAuthorityAmbiguousError) as raised:
        detect_actual_conflicts(
            db_session,
            stock_id=stock.id,
            active_report=None,
            current_user_id=user.id,
            knowledge_cutoff=database_evaluation_cutoff(db_session),
        )

    assert raised.value.code == "actual_conflict_authority_ambiguous"


def test_separate_successful_reparses_without_current_winner_fail_closed(db_session):
    user = User(email="report-identity-ambiguous-reparses@example.com")
    stock = Stock(ticker="RIAMBR", exchange="NYSE", company_name="RI Reparses")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-ambiguous-reparses.pdf",
        report_date=date(2026, 1, 9),
    )
    policy_id = db_session.scalar(
        text(
            "SELECT id FROM value_line_mapping_policies "
            "WHERE status='approved' ORDER BY effective_from DESC LIMIT 1"
        )
    )
    db_session.commit()

    for value in (100, 120):
        run_id = db_session.scalar(
            text(
                "INSERT INTO value_line_parse_runs "
                "(user_id,document_id,parser_version,source_mapping_version,status,"
                "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
                "'running',0) RETURNING id"
            ),
            {"user": user.id, "document": document.id, "policy": policy_id},
        )
        db_session.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_json,value_numeric,period_type,"
                "period_end_date,source_type,source_document_id,is_current,"
                "value_line_parse_run_id) VALUES "
                "(:user,:stock,'is.net_income','{\"fact_nature\":\"actual\"}',"
                ":value,'FY','2025-12-31','parsed',:document,false,:run)"
            ),
            {
                "user": user.id,
                "stock": stock.id,
                "value": value,
                "document": document.id,
                "run": run_id,
            },
        )
        db_session.execute(
            text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
            {"id": run_id},
        )
        db_session.commit()

    with pytest.raises(ActualConflictAuthorityAmbiguousError) as raised:
        detect_actual_conflicts(
            db_session,
            stock_id=stock.id,
            active_report=None,
            current_user_id=user.id,
            knowledge_cutoff=database_evaluation_cutoff(db_session),
        )

    assert raised.value.code == "actual_conflict_authority_ambiguous"


def test_database_stamped_future_fact_is_absent_at_earlier_cutoff(db_session):
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

    assert resolve_active_reports(
        db_session,
        stock_ids=[stock.id],
        current_user_id=user.id,
        knowledge_cutoff=cutoff,
    ) == {}


def test_active_report_does_not_hydrate_one_orm_fact_per_duplicate_observation(
    db_session,
):
    user = User(email="report-identity-bounded@example.com")
    stock = Stock(ticker="RIBOUND", exchange="NYSE", company_name="RI Bounded")
    db_session.add_all([user, stock])
    db_session.flush()
    document = _document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        name="ri-bounded.pdf",
        report_date=date(2026, 1, 9),
    )
    policy_id = db_session.scalar(
        text(
            "SELECT id FROM value_line_mapping_policies "
            "WHERE status='approved' ORDER BY effective_from DESC LIMIT 1"
        )
    )
    run_id = db_session.scalar(
        text(
            "INSERT INTO value_line_parse_runs "
            "(user_id,document_id,parser_version,source_mapping_version,status,"
            "created_txid) VALUES (:user,:document,'value-line-v1',:policy,"
            "'running',0) RETURNING id"
        ),
        {"user": user.id, "document": document.id, "policy": policy_id},
    )
    for offset in range(250):
        db_session.execute(
            text(
                "INSERT INTO metric_facts "
                "(user_id,stock_id,metric_key,value_numeric,source_type,"
                "source_document_id,is_current,value_line_parse_run_id) "
                "VALUES (:user,:stock,:key,:value,'parsed',:document,true,:run)"
            ),
            {
                "user": user.id,
                "stock": stock.id,
                "key": f"custom.duplicate_{offset}",
                "value": offset,
                "document": document.id,
                "run": run_id,
            },
        )
    db_session.execute(
        text("UPDATE value_line_parse_runs SET status='succeeded' WHERE id=:id"),
        {"id": run_id},
    )
    db_session.commit()
    stock_id = stock.id
    user_id = user.id
    document_id = document.id
    cutoff = database_evaluation_cutoff(db_session)
    db_session.expunge_all()

    loaded_metric_facts = 0

    def count_metric_fact_load(_session, instance):
        nonlocal loaded_metric_facts
        if isinstance(instance, MetricFact):
            loaded_metric_facts += 1

    event.listen(db_session, "loaded_as_persistent", count_metric_fact_load)
    try:
        active = resolve_active_reports(
            db_session,
            stock_ids=[stock_id],
            current_user_id=user_id,
            knowledge_cutoff=cutoff,
        )
    finally:
        event.remove(db_session, "loaded_as_persistent", count_metric_fact_load)

    assert active[stock_id].document_id == document_id
    assert loaded_metric_facts == 0


@pytest.mark.parametrize("scope_name", ["document_ids", "stock_ids"])
def test_active_report_rejects_oversized_explicit_scope_before_query(
    db_session, monkeypatch, scope_name
):
    monkeypatch.setattr(
        active_report_resolver,
        "MAX_ACTIVE_REPORT_AUTHORITY_ITEMS",
        2,
    )

    with pytest.raises(ActiveReportAuthorityBoundExceededError) as raised:
        resolve_active_reports(
            db_session,
            **{scope_name: [1, 2, 3]},
        )

    assert raised.value.code == "active_report_authority_bound_exceeded"
    assert raised.value.dimension == scope_name
    assert raised.value.limit == 2


def test_active_report_rejects_oversized_shared_tenant_scope_before_query(
    db_session, monkeypatch
):
    monkeypatch.setattr(
        active_report_resolver,
        "MAX_ACTIVE_REPORT_AUTHORITY_ITEMS",
        2,
    )

    with pytest.raises(ActiveReportAuthorityBoundExceededError) as raised:
        resolve_active_reports(
            db_session,
            current_user_id=1,
            shared_parsed_user_ids=[2, 3, 4],
        )

    assert raised.value.dimension == "shared_parsed_user_ids"
    assert raised.value.limit == 2


def test_active_report_rejects_distinct_multi_stock_document_revision_candidates(
    db_session, monkeypatch
):
    user = User(email="report-authority-candidate-bound@example.com")
    db_session.add(user)
    db_session.flush()

    for offset in range(3):
        stock = Stock(
            ticker=f"RIB{offset}",
            exchange="NYSE",
            company_name=f"RI Bound {offset}",
        )
        db_session.add(stock)
        db_session.flush()
        document = _document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            name=f"ri-bound-{offset}.pdf",
            report_date=date(2026, offset + 1, 9),
        )
        _actual_fact(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            document_id=document.id,
            value=100 + offset,
            is_current=True,
        )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)
    monkeypatch.setattr(
        active_report_resolver,
        "MAX_ACTIVE_REPORT_AUTHORITY_ITEMS",
        2,
    )

    with pytest.raises(ActiveReportAuthorityBoundExceededError) as raised:
        resolve_active_reports(
            db_session,
            current_user_id=user.id,
            knowledge_cutoff=cutoff,
        )

    assert raised.value.dimension == "candidates"
    assert raised.value.limit == 2


def test_active_report_candidate_bound_is_tenant_scoped_without_leakage(
    db_session, monkeypatch
):
    owner = User(email="report-bound-owner@example.com")
    intruder = User(email="report-bound-intruder@example.com")
    db_session.add_all([owner, intruder])
    db_session.flush()

    owner_stock = Stock(
        ticker="RIOWN",
        exchange="NYSE",
        company_name="RI Owner",
    )
    db_session.add(owner_stock)
    db_session.flush()
    owner_document = _document(
        db_session,
        user_id=owner.id,
        stock_id=owner_stock.id,
        name="ri-owner.pdf",
        report_date=date(2026, 1, 9),
    )
    owner_fact = _actual_fact(
        db_session,
        user_id=owner.id,
        stock_id=owner_stock.id,
        document_id=owner_document.id,
        value=100,
        is_current=True,
    )

    intruder_stock_ids = []
    for offset in range(3):
        stock = Stock(
            ticker=f"RIX{offset}",
            exchange="NYSE",
            company_name=f"RI Intruder {offset}",
        )
        db_session.add(stock)
        db_session.flush()
        intruder_stock_ids.append(stock.id)
        document = _document(
            db_session,
            user_id=intruder.id,
            stock_id=stock.id,
            name=f"ri-intruder-{offset}.pdf",
            report_date=date(2026, offset + 1, 9),
        )
        _actual_fact(
            db_session,
            user_id=intruder.id,
            stock_id=stock.id,
            document_id=document.id,
            value=200 + offset,
            is_current=True,
        )
    db_session.commit()
    cutoff = database_evaluation_cutoff(db_session)
    monkeypatch.setattr(
        active_report_resolver,
        "MAX_ACTIVE_REPORT_AUTHORITY_ITEMS",
        2,
    )

    active = resolve_active_reports(
        db_session,
        current_user_id=owner.id,
        knowledge_cutoff=cutoff,
    )

    assert active == {
        owner_stock.id: active_report_resolver.ActiveReportSelection(
            stock_id=owner_stock.id,
            document_id=owner_document.id,
            report_identity_revision_id=(
                owner_fact.value_line_report_identity_revision_id
            ),
            report_date=date(2026, 1, 9),
        )
    }
    assert not set(active).intersection(intruder_stock_ids)
