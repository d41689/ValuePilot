from __future__ import annotations

from datetime import date, datetime, timezone

from app.models.artifacts import DocumentPage, PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.models.users import User
from app.services.document_dedupe_service import DocumentDedupeService


def _make_user_stock(db_session, *, email: str, ticker: str) -> tuple[User, Stock]:
    user = User(email=email)
    stock = Stock(ticker=ticker, exchange="NASDAQ", company_name=f"{ticker} Inc.")
    db_session.add_all([user, stock])
    db_session.commit()
    return user, stock


def _make_document(
    db_session,
    *,
    user_id: int,
    stock_id: int,
    file_name: str,
    report_date: date,
    parse_status: str,
    upload_time: datetime,
) -> PdfDocument:
    document = PdfDocument(
        user_id=user_id,
        stock_id=stock_id,
        file_name=file_name,
        source="upload",
        file_storage_key=f"test/{file_name}",
        report_date=report_date,
        parse_status=parse_status,
        upload_time=upload_time,
    )
    db_session.add(document)
    db_session.commit()
    return document


def _make_fact(
    db_session,
    *,
    user_id: int,
    stock_id: int,
    metric_key: str,
    value_numeric: float,
    source_type: str,
    period_end_date: date,
    source_document_id: int | None = None,
    is_current: bool = True,
) -> MetricFact:
    fact = MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value_numeric,
        value_json={"value": value_numeric},
        source_type=source_type,
        source_document_id=source_document_id,
        period_type="FY",
        period_end_date=period_end_date,
        is_current=is_current,
    )
    db_session.add(fact)
    db_session.commit()
    return fact


def test_cleanup_duplicates_dry_run_keeps_newest_parsed_document_without_mutation(db_session):
    user, stock = _make_user_stock(db_session, email="dedupe-dry@example.com", ticker="DRY")
    old_doc = _make_document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        file_name="dry-old.pdf",
        report_date=date(2025, 12, 31),
        parse_status="parsed",
        upload_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    keep_doc = _make_document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        file_name="dry-new.pdf",
        report_date=date(2025, 12, 31),
        parse_status="parsed",
        upload_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    result = DocumentDedupeService(db_session).cleanup_duplicates(apply=False)

    assert result["mode"] == "dry_run"
    assert result["duplicate_group_count"] == 1
    assert result["deleted_document_count"] == 1
    assert result["groups"][0]["keep_document"]["id"] == keep_doc.id
    assert result["groups"][0]["duplicate_documents"][0]["id"] == old_doc.id
    assert db_session.get(PdfDocument, old_doc.id) is not None
    assert db_session.get(PdfDocument, keep_doc.id) is not None


def test_cleanup_duplicates_apply_deletes_document_dependents_and_reconciles_current(
    db_session,
    monkeypatch,
):
    user, stock = _make_user_stock(db_session, email="dedupe-apply@example.com", ticker="APP")
    duplicate_doc = _make_document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        file_name="apply-old.pdf",
        report_date=date(2025, 12, 31),
        parse_status="parsed",
        upload_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    keep_doc = _make_document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        file_name="apply-new.pdf",
        report_date=date(2025, 12, 31),
        parse_status="parsed",
        upload_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    page = DocumentPage(
        document_id=duplicate_doc.id,
        page_number=1,
        page_text="duplicate",
        text_extraction_method="native_text",
    )
    extraction = MetricExtraction(
        user_id=user.id,
        document_id=duplicate_doc.id,
        page_number=1,
        field_key="is.net_income",
        raw_value_text="100",
        original_text_snippet="Net Income 100",
    )
    db_session.add_all([page, extraction])
    db_session.commit()
    page_id = page.id
    extraction_id = extraction.id

    duplicate_fact = _make_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=100,
        source_type="parsed",
        source_document_id=duplicate_doc.id,
        period_end_date=date(2025, 12, 31),
        is_current=True,
    )
    keep_fact = _make_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=110,
        source_type="parsed",
        source_document_id=keep_doc.id,
        period_end_date=date(2025, 12, 31),
        is_current=False,
    )
    stale_calculated_fact = _make_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_numeric=99,
        source_type="calculated",
        period_end_date=date(2025, 12, 31),
        is_current=True,
    )
    duplicate_fact_id = duplicate_fact.id
    keep_fact_id = keep_fact.id
    stale_calculated_fact_id = stale_calculated_fact.id
    calculator_calls: list[tuple[str, int, int]] = []

    def _record_ratio_call(self, *, user_id: int, stock_id: int) -> None:
        calculator_calls.append(("ratios", user_id, stock_id))

    def _record_fscore_call(self, *, user_id: int, stock_id: int) -> None:
        calculator_calls.append(("fscore", user_id, stock_id))

    monkeypatch.setattr(
        "app.services.document_dedupe_service.ValueLineRatioCalculator.calculate_for_stock",
        _record_ratio_call,
    )
    monkeypatch.setattr(
        "app.services.document_dedupe_service.PiotroskiFScoreCalculator.calculate_for_stock",
        _record_fscore_call,
    )

    result = DocumentDedupeService(db_session).cleanup_duplicates(apply=True)
    db_session.expire_all()

    assert result["mode"] == "apply"
    assert result["deleted_document_count"] == 1
    assert db_session.get(PdfDocument, duplicate_doc.id) is None
    assert db_session.get(DocumentPage, page_id) is None
    assert db_session.get(MetricExtraction, extraction_id) is None
    assert db_session.get(MetricFact, duplicate_fact_id) is None
    assert db_session.get(MetricFact, stale_calculated_fact_id) is None

    refreshed_keep_fact = db_session.get(MetricFact, keep_fact_id)
    assert refreshed_keep_fact is not None
    assert refreshed_keep_fact.is_current is True
    assert calculator_calls == [
        ("ratios", user.id, stock.id),
        ("fscore", user.id, stock.id),
    ]


def test_cleanup_duplicates_refreshes_each_affected_user_stock_pair(db_session, monkeypatch):
    user_a, stock_a = _make_user_stock(db_session, email="dedupe-a@example.com", ticker="AONE")
    user_b, stock_b = _make_user_stock(db_session, email="dedupe-b@example.com", ticker="BTWO")
    for user, stock, prefix in [(user_a, stock_a, "a"), (user_b, stock_b, "b")]:
        _make_document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            file_name=f"{prefix}-old.pdf",
            report_date=date(2025, 12, 31),
            parse_status="parsed",
            upload_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        _make_document(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            file_name=f"{prefix}-new.pdf",
            report_date=date(2025, 12, 31),
            parse_status="parsed",
            upload_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

    calculator_calls: list[tuple[str, int, int]] = []

    def _record_ratio_call(self, *, user_id: int, stock_id: int) -> None:
        calculator_calls.append(("ratios", user_id, stock_id))

    def _record_fscore_call(self, *, user_id: int, stock_id: int) -> None:
        calculator_calls.append(("fscore", user_id, stock_id))

    monkeypatch.setattr(
        "app.services.document_dedupe_service.ValueLineRatioCalculator.calculate_for_stock",
        _record_ratio_call,
    )
    monkeypatch.setattr(
        "app.services.document_dedupe_service.PiotroskiFScoreCalculator.calculate_for_stock",
        _record_fscore_call,
    )

    result = DocumentDedupeService(db_session).cleanup_duplicates(apply=True)

    assert result["affected_user_stock_pairs"] == [
        {"user_id": user_a.id, "stock_id": stock_a.id},
        {"user_id": user_b.id, "stock_id": stock_b.id},
    ]
    assert calculator_calls == [
        ("ratios", user_a.id, stock_a.id),
        ("fscore", user_a.id, stock_a.id),
        ("ratios", user_b.id, stock_b.id),
        ("fscore", user_b.id, stock_b.id),
    ]


def test_cleanup_duplicates_preserves_manual_facts_by_moving_them_to_kept_document(
    db_session,
    monkeypatch,
):
    user, stock = _make_user_stock(db_session, email="dedupe-manual@example.com", ticker="MAN")
    duplicate_doc = _make_document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        file_name="manual-old.pdf",
        report_date=date(2025, 12, 31),
        parse_status="parsed",
        upload_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    keep_doc = _make_document(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        file_name="manual-new.pdf",
        report_date=date(2025, 12, 31),
        parse_status="parsed",
        upload_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    _make_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.sales",
        value_numeric=100,
        source_type="parsed",
        source_document_id=duplicate_doc.id,
        period_end_date=date(2025, 12, 31),
        is_current=True,
    )
    keep_parsed_fact = _make_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=110,
        source_type="parsed",
        source_document_id=keep_doc.id,
        period_end_date=date(2025, 12, 31),
        is_current=False,
    )
    manual_fact = _make_fact(
        db_session,
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=120,
        source_type="manual",
        source_document_id=duplicate_doc.id,
        period_end_date=date(2025, 12, 31),
        is_current=True,
    )
    keep_parsed_fact_id = keep_parsed_fact.id
    manual_fact_id = manual_fact.id

    monkeypatch.setattr(
        "app.services.document_dedupe_service.ValueLineRatioCalculator.calculate_for_stock",
        lambda self, *, user_id, stock_id: None,
    )
    monkeypatch.setattr(
        "app.services.document_dedupe_service.PiotroskiFScoreCalculator.calculate_for_stock",
        lambda self, *, user_id, stock_id: None,
    )

    result = DocumentDedupeService(db_session).cleanup_duplicates(apply=True)
    db_session.expire_all()

    assert result["preserved_non_parsed_fact_count"] == 1
    refreshed_manual_fact = db_session.get(MetricFact, manual_fact_id)
    refreshed_keep_parsed_fact = db_session.get(MetricFact, keep_parsed_fact_id)
    assert refreshed_manual_fact is not None
    assert refreshed_manual_fact.source_document_id is None
    assert refreshed_manual_fact.is_current is True
    assert refreshed_keep_parsed_fact is not None
    assert refreshed_keep_parsed_fact.is_current is False
