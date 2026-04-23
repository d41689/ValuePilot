from app.services.ingestion_service import IngestionService


def test_ingestion_service_does_not_expose_legacy_expansion_helpers():
    assert not hasattr(IngestionService, "_expand_time_series_facts")
    assert not hasattr(IngestionService, "_expand_quarterly_series")
    assert not hasattr(IngestionService, "_expand_current_position_facts")
    assert not hasattr(IngestionService, "_expand_financial_position_facts")
    assert not hasattr(IngestionService, "_expand_annual_financials_facts")
