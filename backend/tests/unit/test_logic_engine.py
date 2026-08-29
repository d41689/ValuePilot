from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from app.services.formula_engine import FormulaEngine
from app.services.screener_service import ScreenerService
from app.models.users import User
from app.models.stocks import Stock
from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import CalculatedRun, MetricFact, Formula
from app.core.security import hash_password
from app.services.document_dedupe_service import DocumentDedupeService


def _formula_extraction(
    db_session,
    *,
    user_id: int,
    document_id: int,
    stock_id: int,
    field_key: str,
    metric_key: str,
    value_numeric: float,
    value_json: dict | None = None,
    unit: str | None = None,
    currency: str | None = None,
    period: str | None = None,
    period_type: str | None = None,
    period_end_date: date | None = None,
    as_of_date: date | None = None,
):
    extraction = MetricExtraction(
        user_id=user_id,
        document_id=document_id,
        page_number=1,
        field_key=field_key,
        raw_value_text="fixture",
        original_text_snippet=f"{field_key} fixture",
        parsed_value_json={"raw": "fixture"},
        confidence_score=1.0,
        parser_version="v1",
        parse_generation=1,
        resolved_stock_id=stock_id,
        mapping_version="value-line-v2",
        canonical_projections_json=[
            {
                "metric_key": metric_key,
                "value_numeric": value_numeric,
                "value_text": None,
                "value_json": value_json,
                "unit": unit,
                "currency": currency,
                "period": period,
                "period_type": period_type,
                "period_end_date": (
                    period_end_date.isoformat() if period_end_date else None
                ),
                "as_of_date": as_of_date.isoformat() if as_of_date else None,
            }
        ],
    )
    db_session.add(extraction)
    db_session.flush()
    return extraction


def _parsed_formula_input(
    db_session,
    *,
    user: User,
    stock: Stock,
    metric_key: str,
    value: float,
    period_type: str | None = None,
    period_end_date: date | None = None,
):
    period_token = period_end_date.isoformat() if period_end_date else "current"
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name=f"{stock.ticker}-{metric_key}-{period_token}.pdf",
        source="upload",
        file_storage_key=(
            f"test/formula/{user.id}/{stock.id}/{metric_key}/{period_token}.pdf"
        ),
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key=metric_key,
        metric_key=metric_key,
        value_numeric=value,
        value_json={},
        period_type=period_type,
        period_end_date=period_end_date,
    )
    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        parse_generation=document.current_parse_generation,
        period_type=period_type,
        period_end_date=period_end_date,
        is_current=True,
    )
    db_session.add(fact)
    return fact

def test_formula_engine_validation():
    engine = FormulaEngine(None) # No DB needed for validation logic
    
    # Valid
    deps = engine.validate_and_extract_dependencies("sales - expenses")
    assert "sales" in deps
    assert "expenses" in deps
    
    # Invalid (function call)
    with pytest.raises(ValueError):
        engine.validate_and_extract_dependencies("print(sales)")
        
    # Invalid (unsafe)
    with pytest.raises(ValueError):
        engine.validate_and_extract_dependencies("__import__('os')")

    canonical_deps = engine.validate_and_extract_dependencies(
        'metric("is.sales") - metric("cf.capital_expenditures")'
    )
    assert canonical_deps == ["is.sales", "cf.capital_expenditures"]

    with pytest.raises(ValueError):
        engine.validate_and_extract_dependencies('metric("../is.sales")')
    with pytest.raises(ValueError):
        engine.validate_and_extract_dependencies("metric(user_metric)")

def test_formula_engine_evaluation():
    engine = FormulaEngine(None)
    context = {"sales": 100.0, "expenses": 80.0}
    
    result = engine.evaluate("sales - expenses", context)
    assert result == 20.0
    
    result = engine.evaluate("sales * 1.1", context)
    assert result == pytest.approx(110.0)

    result = engine.evaluate(
        'metric("is.sales") - metric("cf.capital_expenditures")',
        {"is.sales": 100.0, "cf.capital_expenditures": 30.0},
    )
    assert result == 70.0
    assert engine.render_compiled_expression(
        engine.compile_expression('metric("is.sales")')
    ) == 'metric("is.sales")'


def test_formula_output_key_must_be_canonical_and_unique_per_user(db_session):
    user = User(email="formula-key@test.com", hashed_password=hash_password("TestPass123!"))
    db_session.add(user)
    db_session.flush()
    db_session.add(
        Formula(
            user_id=user.id,
            name="Owner Earnings!",
            output_key="owner earnings!",
            expression="revenue",
            dependencies_json=["revenue"],
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    duplicate_user = User(
        email="formula-key-duplicate@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    db_session.add(duplicate_user)
    db_session.flush()
    first = Formula(
        user_id=duplicate_user.id,
        name="Gross Profit A",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    second = Formula(
        user_id=duplicate_user.id,
        name="Gross Profit B",
        output_key="gross_profit",
        expression="sales - cogs",
        dependencies_json=["sales", "cogs"],
    )
    db_session.add_all([first, second])
    with pytest.raises(IntegrityError):
        db_session.commit()

def test_run_formula_integration(db_session):
    # Setup
    user = User(email="formula@test.com", hashed_password=hash_password("TestPass123!"))
    stock = Stock(ticker="FMLA", exchange="NYS", company_name="Formula Corp")
    db_session.add(user)
    db_session.add(stock)
    db_session.commit()
    
    # Facts
    f1 = _parsed_formula_input(
        db_session, user=user, stock=stock, metric_key="revenue", value=1000.0
    )
    f2 = _parsed_formula_input(
        db_session, user=user, stock=stock, metric_key="cogs", value=600.0
    )
    db_session.commit()
    
    # Formula
    formula = Formula(
        user_id=user.id, 
        name="Gross Profit", 
        output_key="gross_profit",
        expression="revenue - cogs", 
        dependencies_json=["revenue", "cogs"]
    )
    db_session.add(formula)
    db_session.commit()
    
    # Run
    engine = FormulaEngine(db_session)
    run = engine.run_formula(formula.id, stock.id, user.id)
    
    assert run is not None
    assert run.result_value_json["value"] == 400.0

    # Verify authoritative fact created
    output_fact = db_session.query(MetricFact).filter_by(
        stock_id=stock.id, metric_key="gross_profit"
    ).first()
    assert output_fact is not None
    assert output_fact.value_numeric == 400.0
    assert output_fact.source_type == "calculated"
    assert run.input_fact_ids_json == [f1.id, f2.id]
    assert output_fact.value_json["formula_lineage_version"] == "formula-v2"
    assert output_fact.value_json["input_fact_ids"] == [f1.id, f2.id]


def test_published_formula_owner_cannot_be_transferred(db_session):
    owner = User(
        email="formula-owner@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    other = User(
        email="formula-other@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    stock = Stock(ticker="FMOWN", exchange="NYS", company_name="Formula Owner")
    db_session.add_all([owner, other, stock])
    db_session.flush()
    _parsed_formula_input(
        db_session, user=owner, stock=stock, metric_key="revenue", value=1000
    )
    _parsed_formula_input(
        db_session, user=owner, stock=stock, metric_key="cogs", value=600
    )
    formula = Formula(
        user_id=owner.id,
        name="Gross Profit",
        output_key="gross_profit_owner_guard",
        expression='(metric("revenue") - metric("cogs"))',
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add(formula)
    db_session.commit()
    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, owner.id)
    assert run is not None

    formula.user_id = other.id
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()

    retained = db_session.get(Formula, formula.id)
    assert retained is not None
    assert retained.user_id == owner.id


def test_database_rejects_forged_formula_result(db_session):
    user = User(
        email="formula-forged-result@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    stock = Stock(ticker="FMFRG", exchange="NYS", company_name="Formula Forgery")
    db_session.add_all([user, stock])
    db_session.flush()
    revenue = _parsed_formula_input(
        db_session,
        user=user,
        stock=stock,
        metric_key="revenue",
        value=1000,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
    )
    cogs = _parsed_formula_input(
        db_session,
        user=user,
        stock=stock,
        metric_key="cogs",
        value=600,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
    )
    formula = Formula(
        user_id=user.id,
        name="Forged Gross Profit",
        output_key="forged_gross_profit",
        expression='(metric("revenue") - metric("cogs"))',
        dependencies_json=["revenue", "cogs"],
        compiled_ast_json=FormulaEngine(db_session).compile_expression(
            'metric("revenue") - metric("cogs")'
        ),
    )
    db_session.add_all([revenue, cogs, formula])
    db_session.commit()

    forged = CalculatedRun(
        user_id=user.id,
        formula_id=formula.id,
        output_key_snapshot=formula.output_key,
        stock_id=stock.id,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        input_fact_ids_json=[revenue.id, cogs.id],
        result_value_json={"value": 999999},
        is_dirty=False,
    )
    db_session.add(forged)
    with pytest.raises(DBAPIError, match="result does not match exact evaluation"):
        db_session.flush()


def test_run_formula_replaces_only_the_same_current_period_slot(db_session):
    user = User(email="formula-rerun@test.com", hashed_password=hash_password("TestPass123!"))
    stock = Stock(ticker="FMR2", exchange="NYS", company_name="Formula Rerun")
    db_session.add_all([user, stock])
    db_session.flush()
    revenue = _parsed_formula_input(
        db_session, user=user, stock=stock, metric_key="revenue", value=1000.0
    )
    cogs = _parsed_formula_input(
        db_session, user=user, stock=stock, metric_key="cogs", value=600.0
    )
    formula = Formula(
        user_id=user.id,
        name="Gross Profit",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add_all([revenue, cogs, formula])
    db_session.commit()

    first_run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)
    second_run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)

    assert first_run is not None and second_run is not None
    facts = db_session.query(MetricFact).filter_by(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="gross_profit",
        source_type="calculated",
    ).order_by(MetricFact.id).all()
    assert len(facts) == 2
    assert [fact.is_current for fact in facts] == [False, True]
    assert facts[0].source_ref_id == first_run.id
    assert facts[1].source_ref_id == second_run.id
    assert first_run.input_fact_ids_json == [revenue.id, cogs.id]
    assert second_run.input_fact_ids_json == [revenue.id, cogs.id]


def test_formula_uses_latest_complete_period_from_multi_period_current_history(
    db_session,
):
    user = User(email="formula-periods@test.com", hashed_password=hash_password("TestPass123!"))
    stock = Stock(ticker="FMPER", exchange="NYS", company_name="Formula Periods")
    formula = Formula(
        user_id=user.id,
        name="Gross Profit",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add_all([user, stock])
    db_session.flush()
    formula.user_id = user.id
    facts = []
    for year, revenue, cogs in [(2024, 900.0, 500.0), (2025, 1200.0, 650.0)]:
        slot = {
            "period_type": "FY",
            "period_end_date": date(year, 12, 31),
        }
        facts.extend(
            [
                _parsed_formula_input(
                    db_session,
                    user=user,
                    stock=stock,
                    metric_key="revenue",
                    value=revenue,
                    **slot,
                ),
                _parsed_formula_input(
                    db_session,
                    user=user,
                    stock=stock,
                    metric_key="cogs",
                    value=cogs,
                    **slot,
                ),
            ]
        )
    db_session.add(formula)
    db_session.commit()

    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)

    assert run is not None
    assert run.period_end_date == date(2025, 12, 31)
    assert run.result_value_json["value"] == 550.0
    assert run.input_fact_ids_json == [facts[2].id, facts[3].id]


def test_formula_fails_closed_on_latest_period_source_conflict(db_session):
    user = User(email="formula-conflict@test.com", hashed_password=hash_password("TestPass123!"))
    stock = Stock(ticker="FMCON", exchange="NYS", company_name="Formula Conflict")
    db_session.add_all([user, stock])
    db_session.flush()
    documents = []
    revenue_facts = []
    for sequence, value in enumerate([1200.0, 1250.0], start=1):
        document = PdfDocument(
            user_id=user.id,
            stock_id=stock.id,
            file_name=f"formula-conflict-{sequence}.pdf",
            source="upload",
            file_storage_key=f"test/formula-conflict-{sequence}.pdf",
            parse_status="parsed",
        )
        db_session.add(document)
        db_session.flush()
        extraction = _formula_extraction(
            db_session,
            user_id=user.id,
            document_id=document.id,
            stock_id=stock.id,
            field_key="revenue",
            metric_key="revenue",
            value_numeric=value,
            value_json={},
            period_type="FY",
            period_end_date=date(2025, 12, 31),
        )
        documents.append(document)
        revenue_facts.append(
            MetricFact(
                user_id=user.id,
                stock_id=stock.id,
                metric_key="revenue",
                value_numeric=value,
                value_json={},
                period_type="FY",
                period_end_date=date(2025, 12, 31),
                source_type="parsed",
                source_document_id=document.id,
                source_ref_id=extraction.id,
                parse_generation=1,
                is_current=True,
            )
        )
    cogs_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=documents[0].id,
        stock_id=stock.id,
        field_key="cogs",
        metric_key="cogs",
        value_numeric=650.0,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
    )
    cogs = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="cogs",
        value_numeric=650.0,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        source_document_id=documents[0].id,
        source_ref_id=cogs_extraction.id,
        parse_generation=1,
        is_current=True,
    )
    formula = Formula(
        user_id=user.id,
        name="Gross Profit",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add_all([*revenue_facts, cogs, formula])
    db_session.commit()

    assert FormulaEngine(db_session).run_formula(
        formula.id, stock.id, user.id
    ) is None


def test_archiving_formula_inputs_dirties_run_and_hides_output(db_session, monkeypatch):
    user = User(email="formula-archive@test.com", hashed_password=hash_password("TestPass123!"))
    stock = Stock(ticker="FMAR", exchange="NYS", company_name="Formula Archive")
    db_session.add_all([user, stock])
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="formula-inputs.pdf",
        source="upload",
        file_storage_key="test/formula-inputs.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    revenue_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="revenue",
        metric_key="revenue",
        value_numeric=1000.0,
        value_json={},
    )
    cogs_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="cogs",
        metric_key="cogs",
        value_numeric=600.0,
        value_json={},
    )
    revenue = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1000.0,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=revenue_extraction.id,
        parse_generation=1,
        is_current=True,
    )
    cogs = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="cogs",
        value_numeric=600.0,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=cogs_extraction.id,
        parse_generation=1,
        is_current=True,
    )
    formula = Formula(
        user_id=user.id,
        name="Gross Profit",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add_all([revenue, cogs, formula])
    db_session.commit()
    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)
    assert run is not None
    output = db_session.query(MetricFact).filter_by(
        source_type="calculated", source_ref_id=run.id
    ).one()
    assert output.is_current is True

    monkeypatch.setattr(
        "app.services.document_dedupe_service.ValueLineRatioCalculator.calculate_for_stock",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.document_dedupe_service.PiotroskiFScoreCalculator.calculate_for_stock",
        lambda *args, **kwargs: None,
    )
    DocumentDedupeService(db_session).delete_document(
        user_id=user.id,
        document_id=document.id,
    )
    db_session.expire_all()

    assert db_session.get(CalculatedRun, run.id).is_dirty is True
    assert db_session.get(MetricFact, output.id).is_current is False
    assert ScreenerService(db_session).execute_screen(
        {
            "type": "AND",
            "conditions": [{"metric": "gross_profit", "operator": ">", "value": 1}],
        },
        current_user_id=user.id,
    ) == []


def test_formula_resolves_current_manual_correction_over_same_slot_parsed_fact(
    db_session,
):
    user = User(email="formula-manual-override@test.com", hashed_password=hash_password("TestPass123!"))
    stock = Stock(ticker="FMOV", exchange="NYS", company_name="Formula Override")
    db_session.add_all([user, stock])
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="formula-override.pdf",
        source="upload",
        file_storage_key="test/formula-override.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    revenue_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="revenue",
        metric_key="revenue",
        value_numeric=1000.0,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        as_of_date=date(2026, 2, 1),
    )
    cogs_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="cogs",
        metric_key="cogs",
        value_numeric=600.0,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        as_of_date=date(2026, 2, 1),
    )
    slot = {
        "period_type": "FY",
        "period_end_date": date(2025, 12, 31),
        "as_of_date": date(2026, 2, 1),
    }
    parsed_revenue = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1000.0,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=revenue_extraction.id,
        parse_generation=1,
        is_current=True,
        **slot,
    )
    manual_revenue = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1200.0,
        value_json={"correction": True},
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=revenue_extraction.id,
        is_current=True,
        **slot,
    )
    cogs = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="cogs",
        value_numeric=600.0,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=cogs_extraction.id,
        parse_generation=1,
        is_current=True,
        **slot,
    )
    formula = Formula(
        user_id=user.id,
        name="Gross Profit",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add_all([parsed_revenue, manual_revenue, cogs, formula])
    db_session.commit()

    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)

    assert run is not None
    assert run.result_value_json["value"] == 600.0
    assert run.input_fact_ids_json == [manual_revenue.id, cogs.id]


def test_manual_correction_insert_dirties_prior_formula_run_and_hides_output(
    db_session,
):
    user = User(
        email="formula-late-manual-override@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    stock = Stock(ticker="FMLATE", exchange="NYS", company_name="Formula Late Override")
    db_session.add_all([user, stock])
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="formula-late-override.pdf",
        source="upload",
        file_storage_key="test/formula-late-override.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    revenue_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="revenue",
        metric_key="revenue",
        value_numeric=1000.0,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        as_of_date=date(2026, 2, 1),
    )
    cogs_extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="cogs",
        metric_key="cogs",
        value_numeric=600.0,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        as_of_date=date(2026, 2, 1),
    )
    slot = {
        "period_type": "FY",
        "period_end_date": date(2025, 12, 31),
        "as_of_date": date(2026, 2, 1),
    }
    parsed_revenue = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1000.0,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=revenue_extraction.id,
        parse_generation=1,
        is_current=True,
        **slot,
    )
    parsed_cogs = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="cogs",
        value_numeric=600.0,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=cogs_extraction.id,
        parse_generation=1,
        is_current=True,
        **slot,
    )
    formula = Formula(
        user_id=user.id,
        name="Gross Profit",
        output_key="gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add_all([parsed_revenue, parsed_cogs, formula])
    db_session.commit()

    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)
    assert run is not None
    output = db_session.scalar(
        select(MetricFact).where(
            MetricFact.source_type == "calculated",
            MetricFact.source_ref_id == run.id,
        )
    )
    assert output is not None and output.is_current is True

    db_session.add(
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="revenue",
            value_numeric=1200.0,
            value_json={"correction": True},
            source_type="manual",
            source_document_id=document.id,
            source_ref_id=revenue_extraction.id,
            is_current=True,
            **slot,
        )
    )
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(CalculatedRun, run.id).is_dirty is True
    assert db_session.get(MetricFact, output.id).is_current is False
    assert ScreenerService(db_session).execute_screen(
        {
            "type": "AND",
            "conditions": [
                {"metric": "gross_profit", "operator": ">", "value": 1}
            ],
        },
        current_user_id=user.id,
    ) == []


def test_database_rejects_current_formula_fact_with_overridden_parsed_input(
    db_session,
):
    user = User(
        email="formula-overridden-input@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    stock = Stock(ticker="FMDBO", exchange="NYS", company_name="Formula DB Override")
    db_session.add_all([user, stock])
    db_session.flush()
    document = PdfDocument(
        user_id=user.id,
        stock_id=stock.id,
        file_name="formula-db-override.pdf",
        source="upload",
        file_storage_key="test/formula-db-override.pdf",
        parse_status="parsed",
    )
    db_session.add(document)
    db_session.flush()
    extraction = _formula_extraction(
        db_session,
        user_id=user.id,
        document_id=document.id,
        stock_id=stock.id,
        field_key="revenue",
        metric_key="revenue",
        value_numeric=1000,
        value_json={},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
    )
    slot = {
        "period_type": "FY",
        "period_end_date": date(2025, 12, 31),
    }
    parsed = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1000,
        value_json={},
        source_type="parsed",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        parse_generation=1,
        is_current=True,
        **slot,
    )
    manual = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="revenue",
        value_numeric=1200,
        value_json={"correction": True},
        source_type="manual",
        source_document_id=document.id,
        source_ref_id=extraction.id,
        is_current=True,
        **slot,
    )
    formula = Formula(
        user_id=user.id,
        name="Copied Revenue",
        output_key="copied_revenue",
        expression='metric("revenue")',
        dependencies_json=["revenue"],
        compiled_ast_json=FormulaEngine(db_session).compile_expression("revenue"),
    )
    db_session.add_all([parsed, manual, formula])
    db_session.commit()

    forged_run = CalculatedRun(
        user_id=user.id,
        formula_id=formula.id,
        output_key_snapshot=formula.output_key,
        stock_id=stock.id,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        input_fact_ids_json=[parsed.id],
        result_value_json={"value": 1000},
        is_dirty=False,
    )
    db_session.add(forged_run)
    with pytest.raises(DBAPIError, match="exactly match dependencies"):
        db_session.flush()


def test_database_rejects_fractional_formula_input_fact_identity(db_session):
    user = User(
        email="formula-fractional-id@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    stock = Stock(
        ticker="FMFRAC",
        exchange="NYS",
        company_name="Formula Fractional Identity",
    )
    db_session.add_all([user, stock])
    db_session.flush()
    source = _parsed_formula_input(
        db_session,
        user=user,
        stock=stock,
        metric_key="revenue",
        value=1000,
        period_type="FY",
        period_end_date=date(2025, 12, 31),
    )
    formula = Formula(
        user_id=user.id,
        name="Copied Revenue Fractional Attack",
        output_key="copied_revenue_fractional_attack",
        expression='metric("revenue")',
        dependencies_json=["revenue"],
        compiled_ast_json=FormulaEngine(db_session).compile_expression("revenue"),
    )
    db_session.add(formula)
    db_session.commit()

    # jsonb_array_elements_text feeds a direct text-to-bigint cast. PostgreSQL
    # must reject a fractional JSON identity rather than rounding it through a
    # numeric-to-bigint conversion and binding it to a real fact.
    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                """
                INSERT INTO calculated_runs
                    (user_id, formula_id, output_key_snapshot, stock_id,
                     period_type, period_end_date, input_fact_ids_json,
                     result_value_json, is_dirty)
                VALUES
                    (:user_id, :formula_id, :output_key, :stock_id,
                     'FY', DATE '2025-12-31',
                     jsonb_build_array(CAST(:fractional_id AS numeric)),
                     jsonb_build_object('value', 1000), false)
                """
            ),
            {
                "user_id": user.id,
                "formula_id": formula.id,
                "output_key": formula.output_key,
                "stock_id": stock.id,
                "fractional_id": f"{source.id}.2",
            },
        )


def test_legacy_formula_and_screener_do_not_mix_unreconciled_public_sec_facts(
    db_session,
):
    user = User(
        email="sec-formula-gate@test.com",
        hashed_password=hash_password("TestPass123!"),
    )
    stock = Stock(ticker="SECGATE", exchange="NYS", company_name="SEC Gate")
    db_session.add_all([user, stock])
    db_session.flush()
    db_session.add(
        MetricFact(
            user_id=None,
            stock_id=stock.id,
            metric_key="revenue",
            value_numeric=1000.0,
            value_json={},
            source_type="sec",
            is_current=True,
        )
    )
    _parsed_formula_input(
        db_session, user=user, stock=stock, metric_key="cogs", value=600.0
    )
    formula = Formula(
        user_id=user.id,
        name="Unreconciled Gross Profit",
        output_key="unreconciled_gross_profit",
        expression="revenue - cogs",
        dependencies_json=["revenue", "cogs"],
    )
    db_session.add(formula)
    db_session.commit()

    assert FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id) is None
    assert (
        ScreenerService(db_session).execute_screen(
            {
                "type": "AND",
                "conditions": [{"metric": "revenue", "operator": ">", "value": 1}],
            },
            current_user_id=user.id,
        )
        == []
    )

def test_screener_service(db_session):
    # Setup
    user = User(email="screen@test.com", hashed_password=hash_password("TestPass123!"))
    s1 = Stock(ticker="A", exchange="NYS", company_name="A Corp")
    s2 = Stock(ticker="B", exchange="NYS", company_name="B Corp")
    db_session.add_all([user, s1, s2])
    db_session.commit()
    
    # Facts: A has PE 10, Yield 3%. B has PE 30, Yield 1%
    _parsed_formula_input(
        db_session, user=user, stock=s1, metric_key="pe", value=10.0
    )
    _parsed_formula_input(
        db_session, user=user, stock=s1, metric_key="yld", value=0.03
    )
    _parsed_formula_input(
        db_session, user=user, stock=s2, metric_key="pe", value=30.0
    )
    _parsed_formula_input(
        db_session, user=user, stock=s2, metric_key="yld", value=0.01
    )
    db_session.commit()
    
    service = ScreenerService(db_session)
    
    # Screen 1: PE < 20 (Should get A)
    rule1 = {
        "type": "AND",
        "conditions": [{"metric": "pe", "operator": "<", "value": 20}]
    }
    results = service.execute_screen(rule1, current_user_id=user.id)
    assert len(results) == 1
    assert results[0].ticker == "A"
    
    # Screen 2: Yield > 0.02 (Should get A)
    rule2 = {
        "type": "AND",
        "conditions": [{"metric": "yld", "operator": ">", "value": 0.02}]
    }
    results = service.execute_screen(rule2, current_user_id=user.id)
    assert len(results) == 1
    assert results[0].ticker == "A"
    
    # Screen 3: PE > 25 (Should get B)
    rule3 = {
        "type": "AND",
        "conditions": [{"metric": "pe", "operator": ">", "value": 25}]
    }
    results = service.execute_screen(rule3, current_user_id=user.id)
    assert len(results) == 1
    assert results[0].ticker == "B"
    
    # Screen 4: Combined (Should get none if strict, or specific logic)
    # PE < 20 AND Yield < 0.02 -> None
    rule4 = {
        "type": "AND",
        "conditions": [
            {"metric": "pe", "operator": "<", "value": 20},
            {"metric": "yld", "operator": "<", "value": 0.02}
        ]
    }
    results = service.execute_screen(rule4, current_user_id=user.id)
    assert len(results) == 0
