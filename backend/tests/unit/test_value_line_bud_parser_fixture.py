import json
from pathlib import Path

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json


FIXTURE_PDF = Path("tests/fixtures/value_line/bud.pdf")
EXPECTED_JSON = Path("tests/fixtures/value_line/bud_v1.expected.json")


def load_expected_json() -> dict:
    with EXPECTED_JSON.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_page_json() -> dict:
    pages = PdfExtractor.extract_pages_with_words(FIXTURE_PDF)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser = ValueLineV1Parser(text, page_words=page_words)
    return build_value_line_page_json(parser, page_number=1)


def test_value_line_bud_page_json_matches_expected_fixture():
    expected = load_expected_json()
    actual = build_page_json()

    assert actual == expected


def test_bud_v1_1_quarterly_dividends_have_period_end_and_narrative_has_commentary_key():
    actual = build_page_json()

    year = actual["quarterly_dividends_paid"]["by_year"][0]
    assert year["quarters"]["Q1"]["period_end"] is not None
    assert year["quarters"]["Q2"]["period_end"] is not None
    assert year["quarters"]["Q3"]["period_end"] is not None
    assert year["quarters"]["Q4"]["period_end"] is not None

    assert "analyst_commentary" in actual["narrative"]
