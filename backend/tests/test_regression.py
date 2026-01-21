import json
from pathlib import Path

from scripts import run_extraction
from scripts.json_diff import diff_json


def test_bud_extraction_regression():
    expected_path = Path("tests/fixtures/value_line/bud_extraction_expected.json")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    spec = run_extraction.load_spec("extracting_spec.json")
    actual = run_extraction.extract_from_pdf("tests/fixtures/value_line/bud.pdf", spec)

    diffs = {}
    diff_json(expected, actual["metrics"], "", diffs)
    assert diffs == {}
