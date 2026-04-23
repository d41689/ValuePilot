import json
from pathlib import Path

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json


FIXTURE_PDF = Path("tests/fixtures/value_line/calm.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/calm_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_page_json() -> dict:
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser = ValueLineV1Parser(text, page_words=page_words)
    return build_value_line_page_json(parser, page_number=1)


def test_value_line_calm_page_json_matches_expected_fixture():
    expected = load_expected_json()
    actual = build_page_json()

    assert actual == expected


def test_value_line_calm_non_december_fiscal_year_estimate_boundary():
    actual = build_page_json()

    quarterly_sales = actual["quarterly_sales"]["by_year"]
    by_year = {row["calendar_year"]: row for row in quarterly_sales}
    assert "is_estimated" not in by_year[2025]["full_year"]
    assert by_year[2025]["full_year"]["fact_nature"] == "actual"
    assert "is_estimated" not in by_year[2026]["full_year"]
    assert by_year[2026]["full_year"]["fact_nature"] == "estimate"

    annual_meta = actual["annual_financials"]["meta"]
    assert annual_meta["estimate_years"] == [2026]
    assert annual_meta["actual_years"][-1] == 2025
