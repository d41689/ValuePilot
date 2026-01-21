import json
from pathlib import Path

import pytest

from scripts import fields_extracting


def _get_module(data, name_contains):
    for module in data["pages"][0]["modules"]:
        if name_contains in (module.get("name") or ""):
            return module
    return None


def _iter_table_rows(module):
    for table in module.get("table_candidates", []):
        for row in table.get("rows", []):
            yield row


def _iter_block_tables(module):
    for block in module.get("blocks", []):
        if block.get("type") == "table" and block.get("table"):
            yield block.get("table")


def _is_numericish_cell(cell: str) -> bool:
    text = fields_extracting.clean_text(cell)
    if not text:
        return False
    tokens = text.split()
    for token in tokens:
        if fields_extracting._is_numeric_token(token):
            continue
        if fields_extracting._RE_YEAR.match(token):
            continue
        if fields_extracting._RE_QTR_DATE.match(token):
            continue
        return False
    return True


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
        "header": ["2020", "2021", "2022", "2023"],
        "header_row_index": 0,
        "rows": [
            {"cells": ["2020", "2021", "2022", "2023"], "bbox": [0, 100, 180, 110]},
            {"cells": ["1", "2", "3", "4", "Sales($mill)"], "bbox": [0, 111, 180, 120]},
            {"cells": ["10.0%", "11.0%", "12.0%", "13.0%", "NetProfitMargin"], "bbox": [0, 121, 180, 130]},
        ],
    }
    right_table = {
        "bbox": [220.0, 100.0, 380.0, 200.0],
        "header": ["2024", "2025", "2026", "2027"],
        "header_row_index": 0,
        "rows": [
            {"cells": ["2024", "2025", "2026", "2027"], "bbox": [220, 100, 380, 110]},
            {"cells": ["5", "6", "7", "8", "Sales($mill)"], "bbox": [220, 111, 380, 120]},
            {"cells": ["14.0%", "15.0%", "16.0%", "17.0%", "NetProfitMargin"], "bbox": [220, 121, 380, 130]},
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
    assert rows[0]["cells"] == ["2020", "2021", "2022", "2023", "2024", "2025", "2026", "2027"]
    assert rows[1]["cells"] == ["1", "2", "3", "4", "5", "6", "7", "8", "Sales($mill)"]
    assert rows[2]["cells"] == ["10.0%", "11.0%", "12.0%", "13.0%", "14.0%", "15.0%", "16.0%", "17.0%", "NetProfitMargin"]


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


def test_bud_financials_table_contains_current_assets():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    financials = _get_module(data, "__financials_table__")
    assert financials is not None

    in_fields = any(
        fc.get("label_key") == "currentassets"
        for fc in financials.get("field_candidates", [])
    )

    in_tables = False
    for row in _iter_table_rows(financials):
        cells = row.get("cells") or []
        if any("CurrentAssets" in cell for cell in cells):
            in_tables = True
            break

    assert in_fields or in_tables


def test_bud_financials_table_no_narrative_tail_cells():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    financials = _get_module(data, "__financials_table__")
    assert financials is not None

    for row in _iter_table_rows(financials):
        cells = row.get("cells") or []
        if not cells:
            continue
        # Skip the anchor/header row.
        if len(cells) == 1 and "MILL" in cells[0]:
            continue
        # First cell is label, rest should be numeric-ish.
        for cell in cells[1:]:
            assert _is_numericish_cell(cell)


def test_bud_financials_block_table_no_narrative_tail_cells():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    financials = _get_module(data, "__financials_table__")
    assert financials is not None

    for table in _iter_block_tables(financials):
        for row in table.get("rows", []):
            cells = row.get("cells") or []
            if not cells:
                continue
            if len(cells) == 1 and "MILL" in cells[0]:
                continue
            for cell in cells[1:]:
                assert _is_numericish_cell(cell)


def test_bud_retained_to_common_equity_cell_split():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    right = _get_module(data, "__right_column__")
    assert right is not None

    found = False
    for row in _iter_table_rows(right):
        cells = row.get("cells") or []
        if any("RetainedtoComEq" in cell for cell in cells):
            found = True
            assert ".6%" in cells
            assert "5.0%" in cells
            assert "6.8%" in cells
            assert not any("6.8%" in cell and "5.0%" in cell for cell in cells)
            break

    assert found, "Expected RetainedtoComEq row to be split into separate numeric cells"


def test_bud_all_divs_to_net_profit_split():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    right = _get_module(data, "__right_column__")
    assert right is not None

    found = False
    for row in _iter_table_rows(right):
        cells = row.get("cells") or []
        if any("AllDiv" in cell for cell in cells):
            found = True
            assert "AllDiv’dstoNetProf" in cells or "AllDiv'dstoNetProf" in cells
            assert any(cell.strip() == "30%" for cell in cells)
            assert not any("AllDiv" in cell and "%" in cell for cell in cells)
            break

    assert found, "Expected AllDiv’dstoNetProf label split from numeric cell"


def test_bud_projection_high_low_kv_present():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    projections = _get_module(data, "PROJECTIONS")
    assert projections is not None

    keys = {fc.get("label_key") for fc in projections.get("field_candidates", [])}
    assert "high" in keys
    assert "low" in keys


def test_bud_label_key_normalizes_stock_price_stability():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    right = _get_module(data, "__right_column__")
    assert right is not None

    keys = {fc.get("label_key") for fc in right.get("field_candidates", [])}
    assert "stock_price_stability" in keys


def test_bud_institutional_decisions_year_grid_merged():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    right = _get_module(data, "__right_column__")
    assert right is not None

    merged = [t for t in right.get("table_candidates", []) if t.get("merged_from")]
    assert merged, "Expected a merged cross-column year grid"

    year_cells = []
    for row in merged[0].get("rows", []):
        for cell in row.get("cells") or []:
            year_cells.extend(fields_extracting.clean_text(cell).split())

    assert "2015" in year_cells
    assert "2026" in year_cells


def test_bud_institutional_decisions_table_has_no_year_grid_rows():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    inst = _get_module(data, "InstitutionalDecisions")
    assert inst is not None

    for row in _iter_table_rows(inst):
        tokens = []
        for cell in row.get("cells") or []:
            tokens.extend(fields_extracting.clean_text(cell).split())
        year_count = sum(1 for t in tokens if fields_extracting._RE_YEAR.match(t))
        assert year_count < 4


def test_bud_institutional_decisions_block_table_has_no_year_grid_rows():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    inst = _get_module(data, "InstitutionalDecisions")
    assert inst is not None

    for table in _iter_block_tables(inst):
        for row in table.get("rows", []):
            tokens = []
            for cell in row.get("cells") or []:
                tokens.extend(fields_extracting.clean_text(cell).split())
            year_count = sum(1 for t in tokens if fields_extracting._RE_YEAR.match(t))
            assert year_count < 4


def test_bud_merged_year_grid_salesperadr_includes_left_values():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    right = _get_module(data, "__right_column__")
    assert right is not None

    merged = [t for t in right.get("table_candidates", []) if t.get("merged_from")]
    assert merged

    target_row = None
    for row in merged[0].get("rows", []):
        cells = row.get("cells") or []
        if any("SalesperADR" in cell for cell in cells):
            target_row = cells
            break

    assert target_row is not None
    assert "27.11" in target_row
    assert "22.54" in target_row


def test_bud_merged_year_grid_has_no_institutional_narrative():
    data = fields_extracting.discover_pdf_structure("tests/fixtures/value_line/bud.pdf")
    right = _get_module(data, "__right_column__")
    assert right is not None

    merged = [t for t in right.get("table_candidates", []) if t.get("merged_from")]
    assert merged

    for row in merged[0].get("rows", []):
        for cell in row.get("cells") or []:
            assert "Anheuser" not in cell
            assert "InBev" not in cell
