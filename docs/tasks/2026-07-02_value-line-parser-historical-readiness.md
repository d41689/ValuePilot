# Task: Value Line parser — historical-readiness fixes

**Created:** 2026-07-02
**Branch:** `claude/value-line-parser-historical-readiness`
**Origin:** Parser review run in preparation for the quant Phase 1 (`1-R0`) historical
Value Line archive ingestion (see `docs/tasks/2026-07-01_quant-trading-phase-1-research-signal-validation.md`).
The review found the parser is validated only against 2024–2026 layouts (all 55
fixtures are modern) and has hard blockers for historical reports plus silent
accuracy defects that would corrupt backtest fiscal series.

## Goal / Acceptance Criteria

Fix the deterministic, unit-testable findings now; defer sample-dependent work
to `docs/BACKLOG.md` explicitly. Fixes F1–F9:

- **F1** `_find_year_sequence` accepts 19xx years (`(19|20)\d{2}`, plausibility
  1950–2099); dead regex `r"20\\d{2}"` in `is_row_label` fixed. Pre-2000 annual
  tables are no longer silently dropped.
- **F2** Shared `full_year(yy)` century pivot (`yy >= 50 → 19yy`) replaces the
  three `2000 + yy` sites (`parser._iso_from_mdy`, `parser._iso_from_month_year`,
  `evidence._iso_from_mdy`). `3/15/97 → 1997-03-15`.
- **F3** `report_date` fallback chain: analyst line (conf 0.8) → masthead
  "Month DD, YYYY" scan via `parse_report_date_iso` (first 30 lines, then full
  text; conf 0.6; only when the page passes the F8 marker guard) → hard fail as
  today. `doc.report_date` is set once (first page wins); later mismatching
  pages log a warning instead of overwriting.
- **F4** `percent_ratio=True` rows always divide by 100 (drop the
  `abs(value) > 1` guess) — sub-1% values no longer stored 100× too large.
- **F5** Side-row annual metrics (`_parse_annual_table_metrics`): fiscal-aware
  `period_end_date` (quarter-month-order inference, December fallback) instead
  of hardcoded `-12-31`; actual/estimate split via
  `split_actual_and_estimate_years` instead of "last column = estimate".
- **F6** `Scaler` treats pure-numeric parentheses as negatives (`(1.2) → -1.2`)
  while still stripping lettered note parentheticals.
- **F7** Near-empty text-layer pages report `requires_ocr` (existing enum,
  never used) instead of silently passing through as `unsupported_template`.
- **F8** `has_value_line_markers(text)` structural guard (≥2 of TIMELINESS /
  SAFETY / TECHNICAL / "VALUE LINE" / RECENT-price incl. glued variants /
  ≥6-year run) gates the F3 fallback and strengthens `is_company_page`.
- **F9** AGENTS.md corrected (mapping authority = `docs/metric_facts_mapping_spec.yml`;
  OCR wording made honest); five zero-byte never-imported skeleton files deleted.

## Scope

### In
- `backend/app/ingestion/parsers/v1_value_line/{parser,semantics,evidence}.py`
- `backend/app/ingestion/normalization/scaler.py`
- `backend/app/services/ingestion_service.py` (report_date overwrite, requires_ocr, is_company_page)
- AGENTS.md wording; deletion of 5 empty files; BACKLOG entries; tests.

### Out (deferred to `docs/BACKLOG.md` with rationale)
- Full OCR integration (needs real scanned samples + Docker/tesseract infra).
- x0-coordinate table column alignment rewrite (needs per-era historical fixtures).
- Fiscal column-year off-by-one verification (needs real non-calendar-FYE samples).
- Era-hardcoded JSON key rename (blast radius = mapping spec + 55 fixtures).
- Industrial-layout percent-row asymmetry investigation.

## Files to change

See the table in the approved plan (`~/.claude/plans/review-linked-tiger.md`);
new tests in `backend/tests/unit/test_value_line_parser_historical.py` plus
Scaler cases in `backend/tests/unit/test_ingestion.py`.

## Test plan (Docker)

```bash
# targeted (iteration)
docker compose exec -T api pytest -q tests/unit/test_value_line_parser_historical.py
docker compose exec -T api pytest -q tests/unit/test_ingestion.py
# fixture regression
docker compose exec -T api pytest -q tests/unit/ -k value_line
# closing gate — canonical CI, verbatim
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Decisions & gotchas

- Century pivot is **fixed at 50** (not clock-relative) for reproducibility.
- F3 keeps the hard fail when no date is found anywhere: a missing `report_date`
  poisons PIT semantics; better to fail the page loudly.
- F5 has low blast radius by design: the four side-row extractions feed only the
  `metric_extractions` audit trail today (verified — page_json reads the main
  `tables_time_series` result), so fixtures must not change.
- F4 may legitimately change insurance-fixture expected values that contain
  sub-1% percent tokens; any diff is reviewed by hand via the fixture-alignment
  workflow before the expected JSON is updated.

## Sign-off trail

- 2026-07-02: plan approved by user (plan mode), implementation started.
- 2026-07-02: F1–F9 implemented test-first (new tests red → green). One
  calibration during implementation: `MIN_PARSEABLE_PAGE_TEXT_CHARS` set to 20
  (not 200/30) — the guard targets *effectively empty* image-page text layers;
  larger thresholds misclassified legitimate short synthetic company pages in
  the existing multipage tests.
- 2026-07-02: closing gate — canonical CI verbatim, all green:
  `docker compose up -d --build` ✓; `alembic upgrade head` ✓;
  `pytest -q` **1034 passed** ✓; `node --test lib/*.test.js` ✓;
  `npm run lint` ✓; `NODE_ENV=production npm run build` ✓.
  Fixture regression: all 55 fixture PDFs pass the marker guard; all existing
  value_line/ingestion/reparse tests pass unchanged (154 in the slice).
