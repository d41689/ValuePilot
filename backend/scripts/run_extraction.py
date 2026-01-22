#!/usr/bin/env python3
"""Spec-driven extraction for open-world Value Line discovery output."""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from scripts import fields_extracting


_YEAR_TOKEN_RE = re.compile(r"(?:19|20)\d{2}|\b\d{2}-\d{2}\b")


def load_spec(spec_path: str) -> Dict[str, Any]:
    with open(spec_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_row_label(label: str) -> str:
    clean = fields_extracting.clean_text(label)
    # Drop trailing single-letter footnote markers (A/B/C/D).
    clean = re.sub(r"\b[A-D]$", "", clean).strip()
    return fields_extracting.normalize_label_key(clean)


def _find_year_tokens(text: str) -> List[str]:
    return [m.group(0) for m in _YEAR_TOKEN_RE.finditer(text or "")]


def extract_year_columns(table: Dict[str, Any]) -> List[str]:
    rows = table.get("rows") or []
    # Prefer explicit header row if present.
    header_idx = table.get("header_row_index")
    if header_idx is not None and header_idx < len(rows):
        header_cells = rows[header_idx].get("cells") or []
        tokens: List[str] = []
        for cell in header_cells:
            tokens.extend(_find_year_tokens(cell))
        if len(tokens) >= 4:
            return tokens

    # Fallback: first row with many year tokens.
    for row in rows[: min(len(rows), 6)]:
        tokens: List[str] = []
        for cell in row.get("cells") or []:
            tokens.extend(_find_year_tokens(cell))
        if len(tokens) >= 4:
            return tokens

    return []


def _unit_scale(unit: Optional[str]) -> float:
    if not unit:
        return 1.0
    unit = unit.lower()
    if unit in {"usd_millions", "million_shares"}:
        return 1_000_000.0
    if unit in {"usd_billions", "billion_shares"}:
        return 1_000_000_000.0
    return 1.0


def _raw_scale(raw_value: str, normalization: Dict[str, Any]) -> float:
    tokens = normalization.get("scale_tokens", {})
    if not raw_value:
        return 1.0
    raw_lower = raw_value.lower()
    # Prefer unit tokens that appear after the numeric portion.
    suffix = ""
    match = re.search(r"[0-9][0-9,\\.]*\\s*([a-z].*)", raw_lower)
    if match:
        suffix = match.group(1)

    scan = suffix or raw_lower
    # Longer tokens first to avoid partial matches.
    for token in sorted(tokens.keys(), key=len, reverse=True):
        if token in scan:
            return float(tokens[token])
    return 1.0


def normalize_numeric(
    raw_value: str,
    unit: Optional[str],
    normalization: Dict[str, Any],
) -> Tuple[Optional[float], Optional[str]]:
    if raw_value is None:
        return None, "missing_raw_value"

    raw = fields_extracting.clean_text(raw_value)
    if raw.upper() in {"NMF", "--", ""}:
        return None, "non_numeric_marker"

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1].strip()

    if raw.startswith("d"):
        negative = True
        raw = raw[1:].strip()

    if raw.startswith("-"):
        negative = True
        raw = raw[1:].strip()

    is_percent = "%" in raw or (unit and unit.lower() == "percent")

    match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", raw)
    if not match:
        return None, "no_numeric_token"

    raw_numeric = match.group(0).replace(",", "")
    try:
        value = float(raw_numeric)
    except ValueError:
        return None, "float_parse_failed"

    if negative:
        value = -value

    if is_percent:
        value = value / 100.0
        return value, None

    scale = _unit_scale(unit)
    if scale == 1.0:
        scale *= _raw_scale(raw_value, normalization)
    return value * scale, None


def _extract_as_of_date(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    # Support "as of" with or without spaces.
    compact = fields_extracting.clean_text(text).replace(" ", "")
    m = re.search(r"asof(\d{1,2}/\d{1,2}/\d{2,4})", compact, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"as\s*of\s*(\d{1,2}/\d{1,2}/\d{2,4})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _module_key(spec: Dict[str, Any], module: Dict[str, Any]) -> str:
    name = module.get("name") or ""
    anchor = module.get("anchor_text") or ""
    name_norm = fields_extracting._compact_upper(name)
    anchor_norm = fields_extracting._compact_upper(anchor)
    for mod in spec.get("modules", []):
        key = mod.get("key")
        for alias in mod.get("anchors", []) + mod.get("aliases", []):
            alias_norm = fields_extracting._compact_upper(alias)
            if alias_norm and (alias_norm in name_norm or alias_norm in anchor_norm):
                return key
    return name or "__module__"


def build_table_row_map(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for entry in spec.get("table_fields", []):
        for label in entry.get("row_labels", []):
            mapping[_normalize_row_label(label)] = entry
    return mapping


def extract_from_discovery(discovery: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    normalization = spec.get("normalization", {})
    fields_spec = spec.get("fields", {})
    table_map = build_table_row_map(spec)

    metrics: List[Dict[str, Any]] = []
    unmapped_fields: List[Dict[str, Any]] = []
    unmapped_rows: List[Dict[str, Any]] = []

    for page in discovery.get("pages", []):
        page_num = page.get("page")
        for module in page.get("modules", []):
            module_key = _module_key(spec, module)
            as_of_date = _extract_as_of_date(module.get("anchor_text") or module.get("name"))
            # Seed with the best year header we can find in this module so we can parse
            # tables that appear before the explicit header table in reading order.
            current_years: List[str] = []
            for table in module.get("table_candidates", []):
                if table.get("merged_into"):
                    continue
                years = extract_year_columns(table)
                if len(years) > len(current_years):
                    current_years = years

            for field in module.get("field_candidates", []):
                label_key = field.get("label_key")
                spec_field = fields_spec.get(label_key)
                if not spec_field:
                    unmapped_fields.append(
                        {
                            "module": module_key,
                            "page": page_num,
                            "label": field.get("label"),
                            "label_key": label_key,
                            "value_text": field.get("value_text"),
                            "bbox": field.get("bbox"),
                            "method": field.get("method"),
                        }
                    )
                    continue

                raw_value = field.get("value_text")
                value_numeric, error = normalize_numeric(raw_value, spec_field.get("unit"), normalization)
                metrics.append(
                    {
                        "metric_key": spec_field.get("canonical"),
                        "raw_value": raw_value,
                        "value_numeric": value_numeric,
                        "unit": spec_field.get("unit"),
                        "period_type": spec_field.get("period_type"),
                        "period_label": as_of_date if spec_field.get("period_type") == "AS_OF" else None,
                        "source": {
                            "module": module_key,
                            "page": page_num,
                            "bbox": field.get("bbox"),
                            "label": field.get("label"),
                            "label_key": label_key,
                            "method": field.get("method"),
                        },
                        "normalization_error": error,
                    }
                )

            for table in module.get("table_candidates", []):
                if table.get("merged_into"):
                    continue
                years = extract_year_columns(table)
                if years:
                    current_years = years
                elif current_years:
                    rows = table.get("rows") or []
                    # Some Value Line tables (e.g. sales/net profit rows) may only include the
                    # trailing subset of years + the projection column. When we can't extract
                    # an explicit year header, reuse the most recent year tokens.
                    max_values = 0
                    has_projection_col = False
                    for r in rows:
                        cells = r.get("cells") or []
                        pre, label, post = fields_extracting._split_row_cells_for_label(cells)
                        if not label:
                            continue
                        values = [
                            fields_extracting.clean_text(v)
                            for v in (pre + post)
                            if fields_extracting.clean_text(v)
                        ]
                        post_values = [
                            fields_extracting.clean_text(v)
                            for v in post
                            if fields_extracting.clean_text(v)
                        ]
                        if post_values:
                            has_projection_col = True
                        max_values = max(max_values, len(values))

                    if max_values < 4:
                        continue

                    if max_values < len(current_years) and has_projection_col and max_values > 1:
                        # Current year headers often omit the projection-range token; drop one slot
                        # so the trailing year subset aligns and the projection column is ignored.
                        years = current_years[-(max_values - 1):]
                    else:
                        years = current_years[-max_values:] if max_values < len(current_years) else current_years
                else:
                    continue
                for row in table.get("rows", []):
                    cells = row.get("cells") or []
                    pre, label, post = fields_extracting._split_row_cells_for_label(cells)
                    if not label:
                        continue
                    label_key = _normalize_row_label(label)
                    spec_row = table_map.get(label_key)
                    if not spec_row:
                        unmapped_rows.append(
                            {
                                "module": module_key,
                                "page": page_num,
                                "label": label,
                                "label_key": label_key,
                                "bbox": row.get("bbox"),
                            }
                        )
                        continue

                    values = [fields_extracting.clean_text(v) for v in (pre + post) if fields_extracting.clean_text(v)]
                    for idx, year in enumerate(years):
                        if idx >= len(values):
                            break
                        raw_value = values[idx]
                        value_numeric, error = normalize_numeric(raw_value, spec_row.get("unit"), normalization)
                        period_type = spec_row.get("period_type")
                        if fields_extracting._RE_YEAR_RANGE.match(str(year)):
                            period_type = "PROJECTION_RANGE"
                        metrics.append(
                            {
                                "metric_key": spec_row.get("canonical"),
                                "raw_value": raw_value,
                                "value_numeric": value_numeric,
                                "unit": spec_row.get("unit"),
                                "period_type": period_type,
                                "period_label": str(year),
                                "source": {
                                    "module": module_key,
                                    "page": page_num,
                                    "bbox": row.get("bbox"),
                                    "label": label,
                                    "label_key": label_key,
                                    "method": "table_row_parse",
                                },
                                "normalization_error": error,
                            }
                        )

    metrics.sort(key=lambda m: (m.get("metric_key") or "", m.get("period_label") or "", m.get("source", {}).get("page") or 0))

    payloads = [
        {
            "metric_key": m.get("metric_key"),
            "value_numeric": m.get("value_numeric"),
            "value_text": m.get("raw_value"),
            "unit": m.get("unit"),
            "period_type": m.get("period_type"),
            "period_label": m.get("period_label"),
            "source_page": m.get("source", {}).get("page"),
            "source_bbox": m.get("source", {}).get("bbox"),
            "parser_method": m.get("source", {}).get("method"),
            "spec_version": spec.get("version"),
            "algo_version": spec.get("algo_version"),
        }
        for m in metrics
    ]

    return {
        "pdf": discovery.get("pdf"),
        "spec_version": spec.get("version"),
        "algo_version": spec.get("algo_version"),
        "metrics": metrics,
        "metric_fact_payloads": payloads,
        "unmapped": {
            "fields": unmapped_fields,
            "table_rows": unmapped_rows,
        },
    }


def extract_from_pdf(pdf_path: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    discovery = fields_extracting.discover_pdf_structure(pdf_path)
    return extract_from_discovery(discovery, spec)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run spec-driven extraction on a Value Line PDF.")
    parser.add_argument("--pdf", required=True, help="Path to PDF")
    parser.add_argument("--spec", required=True, help="Path to extracting spec JSON")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    spec = load_spec(args.spec)
    data = extract_from_pdf(args.pdf, spec)
    indent = 2 if args.pretty else None
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=indent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
