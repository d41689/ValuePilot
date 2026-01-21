# Goal / Acceptance Criteria
- Improve left-column module assignment so the financial position mini-table (from "($MILL.)" anchor through CurrentLiab) stays in `__financials_table__` instead of BUSINESS narrative.
- Enhance table cell splitting for mixed numeric + label cells (e.g., RetainedtoComEq, AllDiv’dstoNetProf).
- Extend cross-column merge to join InstitutionalDecisions year tables (2015-2019 left + 2020-2026 right) into a single grid when labels align.
- Improve label_key normalization (e.g., "Stock’sPriceStability" -> `stock_price_stability`).
- Broaden 2028-30PROJECTIONS KV extraction to capture High/Low rows.

# Scope (In)
- `backend/scripts/fields_extracting.py` discovery logic (module assignment, table splitting, KV extraction, label normalization).
- Update or add focused tests for discovery stability and regression.
- Refresh discovery output for bud.pdf if needed.

# Scope (Out)
- Schema/PRD changes.
- Non-Value Line templates.

# PRD References
- ValuePilot PRD v0.1: parsing scope, data lineage, normalization rules.
- AGENTS.md: discovery-first pipeline, test-first workflow, Docker-only execution.

# Files to Change
- `backend/scripts/fields_extracting.py`
- `backend/tests/test_discovery.py`
- `backend/tests/test_regression.py` (if needed)
- `backend/discovery.json` (if regenerated)

# Test Plan (Docker)
- `docker compose exec api pytest -q tests/test_discovery.py`
- `docker compose exec api pytest -q tests/test_regression.py`

# Execution Plan
1. Add tests capturing the left-column financials module assignment, InstitutionalDecisions cross-column merge, and mixed-cell splits for RetainedtoComEq / AllDiv’dstoNetProf (tests should fail against current discovery.json).
2. Implement discovery changes in `fields_extracting.py` to pass those tests: anchor-based left-table expansion, enhanced mixed-cell splitting, label_key normalization, and cross-column merge for InstitutionalDecisions.
3. Re-run discovery on bud.pdf, update discovery output if required, and verify tests are green.

# Notes
- Plan approved by human.

# Progress
- Added failing tests for left-column financials assignment, mixed-cell splits, label_key normalization, projections High/Low, and cross-column merge.
- Implemented financial-row reassignment into `__financials_table__`, enhanced numeric token handling, and improved label normalization.
- Extended cross-column merge to use year-grid row extraction and updated mixed-cell splitting for numeric+label cells.
- Added financials table decontamination and InstitutionalDecisions year-grid split (year rows removed from the module, merged grid kept in right column).
- Added year-grid numeric row filtering, label-prefix numeric splitting, and index-based alignment so left 2015–2019 values merge into labeled right rows.
- Updated block-level tables for financials and InstitutionalDecisions to reflect cleaned/split rows.
- Regenerated `backend/discovery.json` for bud.pdf via container run.

# Verification
- `docker compose exec api pytest -q tests/test_discovery.py`
  - Result: 17 passed
