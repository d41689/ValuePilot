# Task: Align SPOT20260123 parser output with expected fixture

## Goal / Acceptance Criteria
- Generate `backend/tests/fixtures/value_line/spot20260123_v1.parser.json` using `scripts/value_line_dump.py`.
- Generate a key-by-key diff JSON using `scripts/json_diff.py`.
- Update parser-related code so `spot20260123_v1.diff.json` becomes `{}` (i.e., parser output matches `spot20260123_v1.expected.json`).
- All tests pass in Docker.

## Scope
### In
- Parser + page JSON builder + normalization/mapping adjustments needed for this fixture.
- Updating `spot20260123_v1.expected.json` only if it is provably incorrect (must be documented in Notes).

### Out
- Schema changes.
- Supporting non–Value Line templates.

## Files To Change (Expected)
- `backend/app/ingestion/parsers/v1_value_line/parser.py`
- `backend/app/ingestion/parsers/v1_value_line/page_json.py`
- `backend/app/ingestion/normalization/*` or `docs/metric_facts_mapping_spec.yml` (only if required)
- `backend/tests/fixtures/value_line/spot20260123_v1.expected.json` (only if incorrect)

## Test Plan (Docker)
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/SPOT20260123.pdf --out tests/fixtures/value_line/spot20260123_v1.parser.json`
- `docker compose exec api python -m scripts.json_diff tests/fixtures/value_line/spot20260123_v1.expected.json tests/fixtures/value_line/spot20260123_v1.parser.json tests/fixtures/value_line/spot20260123_v1.diff.json`
- Iterate until `spot20260123_v1.diff.json` is `{}`.
- `docker compose exec api pytest -q`

## Notes / Findings
- Diff results (2026-01-26):
  - `annual_financials.valuation_metrics.avg_annual_pe_ratio` and `annual_financials.valuation_metrics.relative_pe_ratio` were missing from parser output because the page JSON builder dropped all-null series; the SPOT PDF includes the row labels but values are NMF/Nil.
  - `ratings.safety.value`: PDF visual/layout has `SAFETY 3 Raised 7/31/20`, but the text layer contains a misleading `SAFETY 2 Raised7/31/20` token elsewhere. Fixed the parser to prefer word-layout ratings (value=3) and kept expected at 3.

## Verification Results
- `docker compose exec api python -m scripts.value_line_dump --pdf tests/fixtures/value_line/SPOT20260123.pdf --out tests/fixtures/value_line/spot20260123_v1.parser.json` ✅
- `docker compose exec api python -m scripts.json_diff ...` ✅ (`spot20260123_v1.diff.json` is `{}`)
- `docker compose exec api pytest -q` ✅ (89 passed)
