from datetime import date
from io import BytesIO
import json
from unittest.mock import patch

from fastapi import UploadFile
import pytest
from sqlalchemy import event

from app.models.artifacts import PdfDocument, ValueLineParseRun
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.stocks import Stock
from app.services.ingestion_service import (
    CALCULATION_OUTCOMES_PREFIX,
    COMPARISON_BLOCK_REASONS,
    IngestionService,
    document_calculation_outcomes,
)
from app.services.source_reconciliation import (
    CanonicalReconciliationError,
    guard_reconciled_source_selection,
)
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.calculated_metrics.piotroski_f_score import PiotroskiFScoreCalculator
from app.services.calculated_metrics.value_line_ratios import ValueLineRatioCalculator
from app.api.v1.endpoints.stock_pools import _guard_piotroski_display_facts


PAGE = (1, "TESTCO RECENT 68.11\nNYSE-PFY\nVALUE LINE\n"
        "AnalystX January 2, 2026\n", [])
CALCULATORS = {
    "value_line_ratios": "ValueLineRatioCalculator",
    "piotroski_f_score": "PiotroskiFScoreCalculator",
}


def _blocked(calculation, reason="period_identity_unavailable"):
    return CanonicalReconciliationError(
        consumer=calculation,
        blocking_items=[{
            "reason_code": reason, "blocking": True,
            "metric_key": "per_share.eps", "source_types": ["parsed", "sec"],
        }],
    )


def _outcome(calculation, reason="period_identity_unavailable"):
    return {
        "calculation": calculation, "status": "unavailable",
        "reason_code": "unresolved_source_reconciliation",
        "blocking_reasons": [reason],
    }


def _upload(service, user_id):
    # Direct application-service call: no HTTP and no retained files touched.
    with patch.object(service.storage, "save_upload_file", return_value="/tmp/test.pdf"), \
         patch.object(service, "_archive_single_company_value_line_pdf"), \
         patch("app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
               return_value=[PAGE]):
        return service.process_upload(user_id, UploadFile(
            filename="test.pdf", file=BytesIO(b"%PDF-test")
        ))


def test_65_page_calculation_diagnostics_keep_first_page_warning_and_normal_notes():
    service = IngestionService(None)
    ordinary_notes = "Private identity note\n\ncalculation_outcomes: malformed note\n"
    doc = PdfDocument(notes=ordinary_notes)
    for page in range(1, 66):
        calculation = "value_line_ratios" if page == 1 else "piotroski_f_score"
        service._record_calculation_outcomes(
            doc, outcomes=[_outcome(calculation)]
        )
    assert document_calculation_outcomes(doc.notes) == [
        _outcome("piotroski_f_score"), _outcome("value_line_ratios")
    ]
    assert doc.notes.startswith(ordinary_notes)
    diagnostics = [line for line in doc.notes.splitlines()
                   if document_calculation_outcomes(line)]
    assert len(diagnostics) == 1
    assert len(diagnostics[0]) < 8192
    assert "Private identity note" not in json.dumps(document_calculation_outcomes(doc.notes))


def test_writer_compacts_legacy_page_diagnostics_and_bounds_reason_union():
    service = IngestionService(None)
    doc = PdfDocument(notes="ordinary note\n" + "\n".join(
        CALCULATION_OUTCOMES_PREFIX + json.dumps({"outcomes": [
            _outcome("value_line_ratios" if page == 0 else "piotroski_f_score")
        ]}) for page in range(65)
    ))
    for reason in sorted(COMPARISON_BLOCK_REASONS):
        service._record_calculation_outcomes(doc, outcomes=[
            _outcome(calculation, reason) for calculation in CALCULATORS
        ])
    reopened = document_calculation_outcomes(doc.notes)
    assert len(reopened) == 2
    assert all(item["blocking_reasons"] == sorted(COMPARISON_BLOCK_REASONS)
               for item in reopened)
    assert doc.notes.startswith("ordinary note\n")
    assert doc.notes.count(CALCULATION_OUTCOMES_PREFIX) == 1
    assert len(doc.notes) < 8192


def test_upload_finalizes_warning_after_64_successful_pages_append_identity_notes(
    db_session, user_factory
):
    user = user_factory("late-identity-notes@example.com")
    stock = Stock(ticker="PFY", exchange="NYSE", company_name="TESTCO")
    db_session.add(stock)
    db_session.commit()
    service = IngestionService(db_session)
    pages = [(page, PAGE[1], PAGE[2]) for page in range(1, 66)]
    identity_results = [(stock, False, None)] + [
        (stock, True, f"Private identity review for page {page}")
        for page in range(2, 66)
    ]
    with patch.object(service.storage, "save_upload_file", return_value="/tmp/test.pdf"), \
         patch("app.services.ingestion_service.PdfExtractor.extract_pages_with_words",
               return_value=pages), \
         patch.object(service.identity_service, "resolve_stock", side_effect=identity_results), \
         patch("app.services.ingestion_service.ValueLineRatioCalculator.calculate_for_stock",
               side_effect=[_blocked("value_line_ratios")] + [[] for _ in range(64)]), \
         patch("app.services.ingestion_service.PiotroskiFScoreCalculator.calculate_for_stock",
               return_value=[]):
        doc, reports = service.process_upload(user.id, UploadFile(
            filename="65-pages.pdf", file=BytesIO(b"%PDF-test")
        ))
    assert doc.parse_status == "parsed"
    assert len(reports) == 65
    assert all(report["status"] == "parsed" for report in reports)
    assert reports[0]["calculation_outcomes"] == [_outcome("value_line_ratios")]
    assert all("calculation_outcomes" not in report for report in reports[1:])
    db_session.expire(doc)
    assert document_calculation_outcomes(doc.notes) == [_outcome("value_line_ratios")]
    for page in range(2, 66):
        assert f"[page {page}] Private identity review for page {page}" in doc.notes
    assert len(document_calculation_outcomes(doc.notes.splitlines()[-1])) == 1
    assert "Private identity" not in json.dumps(document_calculation_outcomes(doc.notes))


@pytest.mark.parametrize("notes", [None, "", "Private ordinary note\n\n"])
def test_record_without_any_outcome_leaves_ordinary_notes_exactly_unchanged(notes):
    doc = PdfDocument(notes=notes)
    IngestionService(None)._record_calculation_outcomes(doc, outcomes=[])
    assert doc.notes == notes


@pytest.mark.parametrize("calculation,reason", [
    ("value_line_ratios", "period_identity_unavailable"),
    ("piotroski_f_score", "period_identity_unavailable"),
    ("piotroski_f_score", "material_value_difference"),
])
def test_upload_retains_base_facts_and_exposes_blocked_calculation(
    db_session, user_factory, calculation, reason
):
    user = user_factory("blocked-upload@example.com")
    service = IngestionService(db_session)
    with patch(
        "app.services.ingestion_service."
        + CALCULATORS[calculation] + ".calculate_for_stock",
        side_effect=_blocked(calculation, reason),
    ):
        doc, reports = _upload(service, user.id)
    assert doc.parse_status == "parsed"
    assert reports[0]["status"] == "parsed"
    assert reports[0]["calculation_outcomes"] == [_outcome(calculation, reason)]
    assert _outcome(calculation, reason) in json.loads(doc.notes.split("calculation_outcomes: ")[-1])["outcomes"]
    assert db_session.query(MetricExtraction).filter_by(document_id=doc.id).count() > 0
    assert db_session.query(MetricFact).filter_by(
        source_document_id=doc.id, source_type="parsed", is_current=True
    ).count() > 0
    assert db_session.query(ValueLineParseRun).filter_by(
        document_id=doc.id, status="succeeded"
    ).count() == 1
    assert db_session.query(MetricFact).filter(
        MetricFact.stock_id == doc.stock_id,
        MetricFact.metric_key.like("score.piotroski.%"),
        MetricFact.value_numeric.is_not(None),
    ).count() == 0


def test_reparse_retains_new_revision_with_visible_calculation_block(
    db_session, user_factory
):
    user = user_factory("blocked-reparse@example.com")
    service = IngestionService(db_session)
    doc, _ = _upload(service, user.id)
    prior_ids = {row.id for row in db_session.query(MetricFact).filter_by(
        source_document_id=doc.id, source_type="parsed"
    )}
    with patch(
        "app.services.ingestion_service.PiotroskiFScoreCalculator.calculate_for_stock",
        side_effect=_blocked("piotroski_f_score"),
    ):
        reparsed = service.reparse_existing_document(
            user_id=user.id, document_id=doc.id, reextract_pdf=False
        )
    assert reparsed.parse_status == "parsed"
    assert "unresolved_source_reconciliation" in reparsed.notes
    assert "period_identity_unavailable" in reparsed.notes
    revisions = list(db_session.query(MetricFact).filter_by(
        source_document_id=doc.id, source_type="parsed"
    ))
    assert prior_ids < {row.id for row in revisions}
    assert any(row.is_current and row.id not in prior_ids for row in revisions)
    assert db_session.query(ValueLineParseRun).filter_by(
        document_id=doc.id, status="succeeded"
    ).count() == 2


@pytest.mark.parametrize("calculation", CALCULATORS)
def test_upload_execution_failure_still_rolls_back_the_page(
    db_session, user_factory, calculation
):
    user = user_factory("failed-calculation-upload@example.com")
    service = IngestionService(db_session)
    with patch(
        "app.services.ingestion_service."
        + CALCULATORS[calculation] + ".calculate_for_stock",
        side_effect=RuntimeError("execution failed after base writes"),
    ):
        doc, reports = _upload(service, user.id)
    assert doc.parse_status == "failed"
    assert reports[0]["error_code"] == "parse_error"
    assert "calculation_outcomes" not in reports[0]
    assert db_session.query(MetricExtraction).filter_by(document_id=doc.id).count() == 0
    assert db_session.query(MetricFact).filter_by(source_document_id=doc.id).count() == 0


@pytest.mark.parametrize("reasons", [
    ["mapping_policy_unavailable"],
    ["period_identity_unavailable", "lineage_cycle_detected"],
    ["unknown_future_reason"],
    [],
])
def test_upload_does_not_downgrade_authority_failure_to_calculation_warning(
    db_session, user_factory, reasons
):
    user = user_factory("authority-failure-upload@example.com")
    error = CanonicalReconciliationError(
        consumer="piotroski", blocking_items=[
            {"reason_code": reason, "blocking": True} for reason in reasons
        ],
    )
    with patch(
        "app.services.ingestion_service.PiotroskiFScoreCalculator.calculate_for_stock",
        side_effect=error,
    ):
        doc, reports = _upload(IngestionService(db_session), user.id)
    assert doc.parse_status == "failed"
    assert "calculation_outcomes" not in reports[0]
    assert db_session.query(MetricFact).filter_by(source_document_id=doc.id).count() == 0


@pytest.mark.parametrize("calculator_class", [ValueLineRatioCalculator, PiotroskiFScoreCalculator])
def test_calculator_reconciliation_guard_runs_before_any_data_write(
    db_session, user_factory, calculator_class
):
    user = user_factory("prewrite-guard@example.com")
    stock = Stock(ticker="PRE", exchange="NYSE", company_name="Prewrite")
    db_session.add(stock)
    db_session.commit()
    writes = []
    connection = db_session.connection()

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        with patch(calculator_class.__module__ + ".guard_reconciled_source_selection",
                   side_effect=_blocked("prewrite")), pytest.raises(CanonicalReconciliationError):
            calculator_class(db_session).calculate_for_stock(user_id=user.id, stock_id=stock.id)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert writes == []


def test_real_reconciliation_block_keeps_upload_but_never_displays_old_score(
    db_session, user_factory
):
    user = user_factory("real-blocked-score@example.com")
    stock = Stock(ticker="PFY", exchange="NYSE", company_name="TESTCO")
    db_session.add(stock)
    db_session.flush()
    annual = MetricFact(
        user_id=user.id, stock_id=stock.id, metric_key="per_share.eps",
        value_numeric=10, unit="USD", currency="USD", period_type="FY",
        period_end_date=date(2024, 12, 31), source_type="parsed", is_current=True,
        value_json={"fact_nature": "actual", "fiscal_year": 2024,
                    "period_duration_kind": "fiscal_year",
                    "definition_basis": "adjusted", "dimensions_identity": "empty"},
    )
    db_session.add(annual)
    db_session.flush()
    old_score = MetricFact(
        user_id=user.id, stock_id=stock.id, metric_key="score.piotroski.total",
        value_numeric=7, unit="score_total", period_type="FY",
        period_end_date=date(2024, 12, 31), source_type="calculated", is_current=True,
        value_json={"status": "calculated", "fact_nature": "derived_actual",
                    "fiscal_year": 2024, "period_duration_kind": "fiscal_year",
                    "definition_basis": "derived", "dimensions_identity": "empty",
                    "calculation_version": "piotroski_value_line_v2",
                    "inputs": [{"fact_id": annual.id, "metric_key": annual.metric_key}]},
    )
    db_session.add(old_score)
    db_session.commit()
    # Establish that the retained score was readable before the competitor.
    guarded = guard_reconciled_source_selection(
        [old_score], consumer="stock_pool_piotroski_display", session=db_session,
        user_id=user.id, evaluation_snapshot=database_evaluation_snapshot(db_session),
    )
    assert guarded == [old_score]
    quarterly = MetricFact(
        user_id=user.id, stock_id=stock.id, metric_key="per_share.eps",
        value_numeric=2, unit="USD", currency="USD", period_type="Q",
        period_end_date=date(2024, 3, 31), source_type="parsed", is_current=True,
        value_json={"fact_nature": "actual", "definition_basis": "adjusted",
                    "dimensions_identity": "empty"},
    )
    correction = MetricFact(
        user_id=user.id, stock_id=stock.id, metric_key="per_share.eps",
        value_numeric=11, unit="USD", currency="USD", period_type="FY",
        period_end_date=date(2024, 12, 31), source_type="manual", is_current=True,
        value_json={"fact_nature": "manual", "corrects_fact_id": annual.id,
                    "fiscal_year": 2024, "period_duration_kind": "fiscal_year",
                    "definition_basis": "adjusted", "dimensions_identity": "empty"},
    )
    db_session.add_all([quarterly, correction])
    db_session.commit()
    doc, reports = _upload(IngestionService(db_session), user.id)
    assert doc.parse_status == "parsed"
    assert reports[0]["calculation_outcomes"] == [_outcome("piotroski_f_score")]
    assert db_session.query(MetricFact).filter_by(
        stock_id=stock.id, metric_key="score.piotroski.total"
    ).count() == 1
    db_session.refresh(old_score)
    assert old_score.is_current is True  # History is not rewritten to hide it.
    guarded, state = _guard_piotroski_display_facts(
        db_session, user_id=user.id, stock_id=stock.id, facts=[old_score]
    )
    assert guarded == []
    assert state["status"] == "unavailable"
    assert state["reason_code"] == "unresolved_source_reconciliation"
    assert "period_identity_unavailable" in state["blocking_reasons"]
