from pathlib import Path

import pytest

from scripts import run_extraction


def _find_metric(metrics, key, period_label=None):
    for metric in metrics:
        if metric.get("metric_key") != key:
            continue
        if period_label is not None and metric.get("period_label") != period_label:
            continue
        return metric
    return None


def test_bud_extraction_key_fields():
    spec_path = Path("extracting_spec.json")
    spec = run_extraction.load_spec(str(spec_path))
    data = run_extraction.extract_from_pdf("tests/fixtures/value_line/bud.pdf", spec)

    assert data["spec_version"] == "0.1.0"

    total_debt = _find_metric(data["metrics"], "total_debt")
    assert total_debt is not None
    assert total_debt["value_numeric"] == pytest.approx(75_600_000_000.0)

    sales_2024 = _find_metric(data["metrics"], "sales", "2024")
    assert sales_2024 is not None
    assert sales_2024["value_numeric"] == pytest.approx(59_768_000_000.0)

    margin_2024 = _find_metric(data["metrics"], "net_profit_margin", "2024")
    assert margin_2024 is not None
    assert margin_2024["value_numeric"] == pytest.approx(0.098)
