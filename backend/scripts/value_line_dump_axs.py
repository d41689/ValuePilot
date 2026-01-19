import argparse
import json
from pathlib import Path

from app.ingestion.pdf_extractor import PdfExtractor
from app.ingestion.parsers.v1_value_line.page_json import build_value_line_page_json
from app.ingestion.parsers.v1_value_line.parser import ValueLineV1Parser


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump Value Line AXS page JSON.")
    parser.add_argument(
        "--pdf",
        default="tests/fixtures/value_line/axs.pdf",
        help="Path to the AXS Value Line PDF fixture.",
    )
    parser.add_argument(
        "--out",
        default="tests/fixtures/value_line/axs_v1.parser.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    pages = PdfExtractor.extract_pages_with_words(pdf_path)
    if not pages:
        raise SystemExit(f"No pages extracted from {pdf_path}")

    text = "\n".join(page_text for _, page_text, _ in pages)
    page_words = {page_num: words for page_num, _, words in pages}
    parser_obj = ValueLineV1Parser(text, page_words=page_words)
    payload = build_value_line_page_json(parser_obj, page_number=1)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    main()
