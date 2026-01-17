import pytest
from app.services.formula_engine import FormulaEngine
from app.services.screener_service import ScreenerService
from app.models.users import User
from app.models.stocks import Stock
from app.models.facts import MetricFact, Formula

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

def test_formula_engine_evaluation():
    engine = FormulaEngine(None)
    context = {"sales": 100.0, "expenses": 80.0}
    
    result = engine.evaluate("sales - expenses", context)
    assert result == 20.0
    
    result = engine.evaluate("sales * 1.1", context)
    assert result == pytest.approx(110.0)

def test_run_formula_integration(db_session):
    # Setup
    user = User(email="formula@test.com")
    stock = Stock(ticker="FMLA", exchange="NYS", company_name="Formula Corp")
    db_session.add(user)
    db_session.add(stock)
    db_session.commit()
    
    # Facts
    f1 = MetricFact(user_id=user.id, stock_id=stock.id, metric_key="revenue", value_numeric=1000.0, value_json={}, source_type="manual", is_current=True)
    f2 = MetricFact(user_id=user.id, stock_id=stock.id, metric_key="cogs", value_numeric=600.0, value_json={}, source_type="manual", is_current=True)
    db_session.add_all([f1, f2])
    db_session.commit()
    
    # Formula
    formula = Formula(
        user_id=user.id, 
        name="Gross Profit", 
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
    output_fact = db_session.query(MetricFact).filter_by(stock_id=stock.id, metric_key="gross_profit").first()
    assert output_fact is not None
    assert output_fact.value_numeric == 400.0
    assert output_fact.source_type == "calculated"

def test_screener_service(db_session):
    # Setup
    user = User(email="screen@test.com")
    s1 = Stock(ticker="A", exchange="NYS", company_name="A Corp")
    s2 = Stock(ticker="B", exchange="NYS", company_name="B Corp")
    db_session.add_all([user, s1, s2])
    db_session.commit()
    
    # Facts: A has PE 10, Yield 3%. B has PE 30, Yield 1%
    db_session.add(MetricFact(user_id=user.id, stock_id=s1.id, metric_key="pe", value_numeric=10.0, value_json={}, source_type="manual", is_current=True))
    db_session.add(MetricFact(user_id=user.id, stock_id=s1.id, metric_key="yld", value_numeric=0.03, value_json={}, source_type="manual", is_current=True))
    
    db_session.add(MetricFact(user_id=user.id, stock_id=s2.id, metric_key="pe", value_numeric=30.0, value_json={}, source_type="manual", is_current=True))
    db_session.add(MetricFact(user_id=user.id, stock_id=s2.id, metric_key="yld", value_numeric=0.01, value_json={}, source_type="manual", is_current=True))
    db_session.commit()
    
    service = ScreenerService(db_session)
    
    # Screen 1: PE < 20 (Should get A)
    rule1 = {
        "type": "AND",
        "conditions": [{"metric": "pe", "operator": "<", "value": 20}]
    }
    results = service.execute_screen(rule1)
    assert len(results) == 1
    assert results[0].ticker == "A"
    
    # Screen 2: Yield > 0.02 (Should get A)
    rule2 = {
        "type": "AND",
        "conditions": [{"metric": "yld", "operator": ">", "value": 0.02}]
    }
    results = service.execute_screen(rule2)
    assert len(results) == 1
    assert results[0].ticker == "A"
    
    # Screen 3: PE > 25 (Should get B)
    rule3 = {
        "type": "AND",
        "conditions": [{"metric": "pe", "operator": ">", "value": 25}]
    }
    results = service.execute_screen(rule3)
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
    results = service.execute_screen(rule4)
    assert len(results) == 0
