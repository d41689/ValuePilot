from pathlib import Path

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser


def test_value_line_mtdr_identity_handles_ticker_glued_to_price_header():
    pdf_path = Path("tests/fixtures/value_line/mtdr.pdf")
    pages = PdfExtractor.extract_pages_with_words(pdf_path)
    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_number: words for page_number, _, words in pages}

    identity = ValueLineV1Parser(text, page_words=page_words).extract_identity()

    assert identity.ticker == "MTDR"
    assert identity.exchange == "NYSE"
    assert identity.company_name == "MATADOR RESOURCES"


def test_value_line_mtdr_identity_handles_ticker_glued_to_price_header_without_words():
    pdf_path = Path("tests/fixtures/value_line/mtdr.pdf")
    pages = PdfExtractor.extract_pages_with_words(pdf_path)
    text = "\n".join(page_text for _, page_text, _ in pages)

    identity = ValueLineV1Parser(text).extract_identity()

    assert identity.ticker == "MTDR"
    assert identity.exchange == "NYSE"
    assert identity.company_name == "MATADOR RESOURCES"
