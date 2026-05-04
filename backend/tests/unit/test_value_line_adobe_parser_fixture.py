from pathlib import Path

import pytest

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser


FIXTURE_PDF = Path("tests/fixtures/value_line/Adobe202501.pdf")


@pytest.fixture(scope="module")
def adobe_page_json() -> dict:
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser = ValueLineV1Parser(text, page_words=page_words)
    return build_value_line_page_json(parser, page_number=1)


def test_adobe_projections_and_capital_structure(adobe_page_json):
    high_gain = adobe_page_json["long_term_projection"]["scenarios"]["high"]["price_gain"]
    assert high_gain["display"] == "+105%"
    assert high_gain["normalized"] == pytest.approx(1.05)

    capital = adobe_page_json["capital_structure"]
    assert capital["lt_interest"]["display"] == "$150.0 mill"
    assert capital["lt_interest_percent_of_capital"]["display"] == "23%"
    assert capital["lt_interest_percent_of_capital"]["normalized"] == pytest.approx(0.23)


def test_adobe_current_position_and_quarterly_tables(adobe_page_json):
    current_position = adobe_page_json["current_position"]
    assert current_position["periods"][0]["assets"]["cash_assets"] == pytest.approx(4236.0)
    assert current_position["periods"][2]["assets"]["total_current_assets"] == pytest.approx(11232.0)
    assert current_position["periods"][2]["liabilities"]["debt_due"] == pytest.approx(1499.0)

    revenues = adobe_page_json["quarterly_revenues"]
    revenue_2022 = next(row for row in revenues["by_year"] if row["calendar_year"] == 2022)
    assert revenue_2022["quarters"]["Q1"]["value"] == pytest.approx(4262.0)
    assert revenues["by_year"][-1]["full_year"]["value"] == pytest.approx(23550.0)

    eps = adobe_page_json["earnings_per_share"]
    eps_2024 = next(row for row in eps["by_year"] if row["calendar_year"] == 2024)
    assert eps_2024["quarters"]["Q1"]["value"] == pytest.approx(1.36)
    assert eps["by_year"][-1]["full_year"]["value"] == pytest.approx(16.0)

    dividends = adobe_page_json["quarterly_dividends_paid"]
    assert dividends["note"] == "No cash dividends being paid"
    assert dividends["by_year"][0]["calendar_year"] == 2021
