# ValuePilot Open-World Parser Design

## Overview
The open-world parser is built around a discovery-first pipeline that prioritizes recall and traceability. Discovery produces structured candidates from any Value Line report, while a spec layer converts those candidates into canonical metrics with normalization and evidence.

Key goals:
- High recall: never miss potential fields, even if noisy.
- Stable module naming: discover sections by anchors and layout, not fixed coordinates.
- Full lineage: every extracted value carries page/bbox/label/method evidence.
- Normalized numeric facts: all numeric values are converted to base units.

## Pipeline Stages
1) **Discovery (open-world)**
   - Input: PDF
   - Output: `discovery.json` with pages/modules/blocks + `field_candidates` + `table_candidates`.
   - Implementation: `scripts/fields_extracting.py`

2) **Spec-Driven Extraction**
   - Input: discovery JSON + `extracting_spec.json`
   - Output: extracted metrics with canonical keys + normalized values + evidence.
   - Implementation: `scripts/run_extraction.py`

3) **Mapping to Facts (payloads)**
   - Output: `metric_fact_payloads` ready for DB upsert (metric_key, period_type, value_numeric, evidence).

## Extracting Spec Structure
`backend/extracting_spec.json` is the authoritative spec for open-world extraction.

Required sections:
- `version`, `algo_version`
- `modules`: anchors/aliases for stable module keys
- `fields`: KV label keys -> canonical key + unit + period_type
- `table_fields`: row labels -> canonical key + unit + period_type
- `normalization`: scale tokens and percent handling
- `version_history`: spec evolution log

## Normalization Rules
All `value_numeric` outputs are normalized to base units:
- Currency amounts: absolute dollars (e.g., `75.6 bill` -> `75_600_000_000`)
- Percent values: ratios in [0,1] (e.g., `9.8%` -> `0.098`)
- Per-share metrics: absolute currency per share (no scaling)
- Scale tokens: `k`, `m/mil/mill`, `b/bil/bill`, `t/tril`
- Negative values: `d` prefix or parentheses `(...)`

If a value cannot be normalized, store the raw value and set `value_numeric = null` with an error tag.

## Iteration Workflow (Loop A)
1) Run discovery on new PDFs (`scripts/run_discovery.py`).
2) Review `discovery.json` for missing/merged rows, bad splits, or fragmentations.
3) Improve `fields_extracting.py` (layout, splits, cross-column merge).
4) Update `extracting_spec.json` for new labels.
5) Re-run extraction and verify key fields.

## Regression Workflow (Loop B)
- Run discovery/extraction on the fixture set.
- Compare outputs using `scripts/diff_outputs.py`.
- Keep `tests/fixtures/.../bud_extraction_expected.json` as a baseline.

## Common Failure Modes
- **Column splits**: year grids split across columns; use cross-column merge by label alignment.
- **Merged cells**: numeric runs + label stuck together; apply mixed-cell splitting.
- **Unit ambiguity**: table label carries the unit; ensure spec uses correct unit.
- **Footnotes**: trailing A/B/C markers; normalize label keys without footnotes.

## File Map
- Discovery: `scripts/fields_extracting.py`
- Extraction: `scripts/run_extraction.py`
- Spec: `extracting_spec.json`
- Outputs: `extracted/*.json`
- Diff tool: `scripts/diff_outputs.py`
- Tests: `tests/test_discovery.py`, `tests/test_extraction.py`, `tests/test_regression.py`
