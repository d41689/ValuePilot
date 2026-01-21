import json
from pathlib import Path

import pytest

from scripts import fields_extracting


@pytest.mark.parametrize(
    "cell,expected",
    [
        (
            "3.0% 8.6% 10.3% 9.0% 9.8% 9.5% 11.5% NetProfitMargin",
            [
                "3.0%",
                "8.6%",
                "10.3%",
                "9.0%",
                "9.8%",
                "9.5%",
                "11.5%",
                "NetProfitMargin",
            ],
        ),
        (
            "d5833 d10235 d11197 d13789 d10067 d11500 d10000 WorkingCap'l($mill) d5000",
            [
                "d5833",
                "d10235",
                "d11197",
                "d13789",
                "d10067",
                "d11500",
                "d10000",
                "WorkingCap'l($mill)",
                "d5000",
            ],
        ),
    ],
)
def test_split_mixed_numeric_label_cells(cell, expected):
    assert fields_extracting._split_mixed_numeric_label_cells([cell]) == expected


def test_merge_cross_column_year_tables_merges_by_label():
    left_table = {
        "bbox": [0.0, 100.0, 180.0, 200.0],
        "header": ["2020", "2021"],
        "header_row_index": 0,
        "rows": [
            {"cells": ["2020", "2021", "Sales($mill)"], "bbox": [0, 100, 180, 110]},
            {"cells": ["10.0%", "11.0%", "NetProfitMargin"], "bbox": [0, 111, 180, 120]},
        ],
    }
    right_table = {
        "bbox": [220.0, 100.0, 380.0, 200.0],
        "header": ["2022", "2023"],
        "header_row_index": 0,
        "rows": [
            {"cells": ["2022", "2023", "Sales($mill)"], "bbox": [220, 100, 380, 110]},
            {"cells": ["12.0%", "13.0%", "NetProfitMargin"], "bbox": [220, 111, 380, 120]},
        ],
    }
    modules = [
        {
            "name": "LEFT",
            "table_candidates": [left_table],
        },
        {
            "name": "__right_column__",
            "table_candidates": [right_table],
        },
    ]

    fields_extracting.merge_cross_column_year_tables(modules, x_split=200.0)

    right_mod = next(m for m in modules if m["name"] == "__right_column__")
    merged_tables = [t for t in right_mod["table_candidates"] if t.get("merged_from")]
    assert merged_tables, "Expected a merged table appended to right column"

    merged = merged_tables[0]
    rows = merged["rows"]
    assert rows[0]["cells"] == ["2020", "2021", "2022", "2023", "Sales($mill)"]
    assert rows[1]["cells"] == ["10.0%", "11.0%", "12.0%", "13.0%", "NetProfitMargin"]


def test_discovery_stability():
    pdfs = [
        "tests/fixtures/value_line/bud.pdf",
        "tests/fixtures/value_line/axs.pdf",
    ]
    for pdf in pdfs:
        data = fields_extracting.discover_pdf_structure(pdf)
        modules = [m.get("name") for page in data["pages"] for m in page.get("modules", [])]
        assert "__right_column__" in modules
        assert len(modules) >= 5


def test_bud_discovery_splits_net_profit_margin_row():
    pdf_path = Path("tests/fixtures/value_line/bud.pdf")
    data = fields_extracting.discover_pdf_structure(str(pdf_path))
    right_mods = [m for m in data["pages"][0]["modules"] if m.get("name") == "__right_column__"]
    assert right_mods, "Expected a right column module"
    right = right_mods[0]

    found = False
    for table in right.get("table_candidates", []):
        for row in table.get("rows", []):
            cells = row.get("cells") or []
            if "NetProfitMargin" in cells:
                found = True
                assert "9.0%" in cells
                assert "9.8%" in cells
                assert "9.5%" in cells
                assert "11.5%" in cells
                break
        if found:
            break

    assert found, "Expected NetProfitMargin to be split into its own cell"
