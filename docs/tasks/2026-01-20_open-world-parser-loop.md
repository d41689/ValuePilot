# Goal / Acceptance Criteria
- Fix missing `merge_cross_column_year_tables` in `backend/scripts/fields_extracting.py` and make cross-column merge stable for Value Line tables (e.g., CAPITALSTRUCTURE).
- Produce discovery and extraction outputs for bud.pdf that meet stated acceptance criteria (stable module identification, usable table splits, correct key fields).
- Introduce spec-driven extraction (`backend/extracting_spec.json`) and load it in extraction.
- Add regression tests for discovery/extraction behavior and diff reporting.

# Scope (In)
- Implement/repair cross-column merge logic and table cell splitting in discovery/extraction.
- Add/extend spec-driven extraction, normalized outputs, and evidence metadata.
- Add scripts for discovery/extraction/diffing and tests with fixtures.

# Scope (Out)
- Schema changes or PRD modifications.
- Non-Value Line report support.

# PRD References
- ValuePilot PRD v0.1: parsing scope (Value Line), data lineage, normalization, and audit trail requirements.
- AGENTS.md: three-layer storage, normalization rules, and test-first workflow.

# Files to Change
- `backend/scripts/fields_extracting.py`
- `backend/extracting_spec.json` (new)
- `backend/spec_history/` (new)
- `backend/extracted/` (new output)
- `backend/scripts/run_discovery.py` (new)
- `backend/scripts/run_extraction.py` (new)
- `backend/scripts/diff_outputs.py` (new)
- `backend/tests/` (new/updated)
- `backend/docs/parser_design.md` (new)

# Test Plan (Docker)
- `docker compose exec api pytest -q tests/test_discovery.py`
- `docker compose exec api pytest -q tests/test_extraction.py`
- `docker compose exec api pytest -q tests/test_regression.py`

# Execution Plan
1. Baseline the current discovery/extraction pipeline on bud.pdf and record failure modes (missing cross-column merge, table split issues) and expected test assertions.
2. Implement/adjust cross-column year table merge logic and table cell splitting in `fields_extracting.py`, adding focused unit tests first.
3. Introduce spec-driven extraction (`backend/extracting_spec.json` + loader) and wire outputs with evidence metadata.
4. Add regression tests + diff tooling and update task log with verification results.

# Notes
- Plan approved by human.

# Progress
- Baseline discovery on `bud.pdf`; identified mixed numeric+label cells and missing year header propagation.
- Added tests for mixed-cell splitting, cross-column merge by label, and bud discovery stability.
- Implemented spec-driven extraction with normalization and year-grid propagation.

# Verification
- `docker compose exec api pytest -q tests/test_discovery.py tests/test_extraction.py tests/test_regression.py`

# Open Items
- Only 4 Value Line PDF fixtures present; need a 5th to meet the fixture requirement.
