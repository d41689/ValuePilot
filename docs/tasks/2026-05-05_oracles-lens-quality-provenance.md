# Oracle's Lens Quality Provenance

## Goal / Acceptance Criteria

- Add Value Line quality fact provenance to the Oracle's Lens dashboard API.
- Surface source document IDs and per-metric lineage for quality overlay facts.
- Let the frontend drilldown link from a 13F research candidate to the source document review page.
- Preserve Oracle's Lens positioning as a research funnel, not a recommendation system.

## Scope

In:
- Backend quality overlay payload provenance.
- Unit tests for source document IDs and fact-level provenance.
- Frontend normalization and drilldown display.
- Frontend helper tests for provenance shape.

Out:
- New database schema.
- New document ingestion behavior.
- New valuation formulas.
- Any hardcoded ticker/report behavior.

## Files to Change

- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/lib/oraclesLens.js`
- `frontend/lib/oraclesLens.test.js`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run lint`
- `docker compose exec api pytest -q`

## Progress Notes

- 2026-05-05: Started after Oracle's Lens manager profile derivation. Next product-document step is linking quality evidence to the document review workflow.
- 2026-05-05: Added failing backend contract for `quality_overlay.provenance`, then implemented source document IDs and fact-level metric lineage from current `metric_facts`.
- 2026-05-05: Added frontend normalization coverage and a drilldown link to `/documents/{id}/review` for the primary source document.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - passed, 6 tests.
- `docker compose exec web node --test lib/oraclesLens.test.js` - passed, 10 tests.
- `docker compose exec web npm run lint` - passed.
- `docker compose exec api pytest -q` - passed, 209 tests.
- `git diff --check` - passed.
