from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
PRODUCT_CONSUMERS = (
    "app/api/v1/endpoints/stocks.py",
    "app/api/v1/endpoints/stock_pools.py",
    "app/api/v1/endpoints/screener.py",
    "app/services/formula_engine.py",
    "app/services/screener_service.py",
    "app/services/calculated_metrics/value_line_ratios.py",
    "app/services/calculated_metrics/piotroski_f_score.py",
    "app/services/owners_earnings.py",
    "app/services/valuation.py",
    "app/services/research_workspace.py",
    "app/services/oracles_lens/dashboard.py",
)


def test_product_fundamental_consumers_never_query_raw_sec_or_retained_storage():
    for relative in PRODUCT_CONSUMERS:
        source = (BACKEND / relative).read_text()
        assert "sec_raw_xbrl_facts" not in source, relative
        assert "SecRawXbrlFact" not in source, relative
        assert "storage_key" not in source, relative
        assert "file_storage_key" not in source, relative


def test_evidence_resolver_selects_bounded_metadata_not_raw_content_or_storage():
    source = (BACKEND / "app/services/canonical_financials.py").read_text()
    assert "raw.concept_namespace_uri" in source
    assert "raw.context_id" in source
    assert "raw.unit_numerator_json" in source
    assert "raw.raw_value" not in source
    assert "raw.locator_json" not in source
    assert "storage_key" not in source
    assert "file_storage_key" not in source
    assert "signed_url" not in source
    assert "p.value_numeric" not in source
    assert "source.value_numeric" not in source
    assert "fact.value_numeric AS canonical_value_numeric" in source


def test_shared_visibility_and_source_guard_are_wired_to_real_consumers():
    stocks = (BACKEND / "app/api/v1/endpoints/stocks.py").read_text()
    screener = (BACKEND / "app/services/screener_service.py").read_text()
    formula = (BACKEND / "app/services/formula_engine.py").read_text()
    ratios = (BACKEND / "app/services/calculated_metrics/value_line_ratios.py").read_text()
    piotroski = (BACKEND / "app/services/calculated_metrics/piotroski_f_score.py").read_text()
    assert "visible_metric_fact_predicate" in stocks
    assert "guard_source_selection" in stocks
    assert "guard_source_selection" in screener
    assert "guard_source_selection" in formula
    assert "guard_source_selection" in ratios
    assert "guard_source_selection" in piotroski
    assert "guard_sec_run_availability" in screener
    assert "guard_sec_run_availability" in formula
    assert "guard_sec_run_availability" in ratios
    assert "guard_sec_run_availability" in piotroski


def test_reviewed_method_gate_and_user_valuation_boundary_are_explicit():
    ingestion = (BACKEND / "app/services/ingestion_service.py").read_text()
    stocks = (BACKEND / "app/api/v1/endpoints/stocks.py").read_text()
    workspace = (BACKEND / "app/services/research_workspace.py").read_text()
    valuation = (BACKEND / "app/services/valuation.py").read_text()
    assert "reviewed_method_gate" in ingestion
    assert "apply_reviewed_method_gates" in stocks
    assert "apply_reviewed_method_gates" in workspace
    assert 'source_type="manual"' in valuation
    assert 'source_type="parsed"' in valuation
