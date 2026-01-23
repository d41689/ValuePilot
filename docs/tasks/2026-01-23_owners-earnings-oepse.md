# Task: Owner's Earnings per Share (OEPS) derivation + normalized OEPS

## Goal / Acceptance Criteria
- Derive `owners_earnings_per_share` for each FY from Value Line facts:
  - `eps` = per_share.eps
  - `depreciation_per_share` = is.depreciation / equity.shares_outstanding
  - `capex_per_share` = per_share.capital_spending
- Missing inputs (EPS/CapEx/shares/Dep) are treated as `0`.
- `equity.shares_outstanding` is normalized to **shares** (not millions).
- ADR reports keep per-ADR units (no conversion to common shares).
- Compute `owners_earnings_per_share_normalized` as `median(last 5 usable FY)` with FY aligned by `period_end_date`.
- Metric keys use snake_case without dots:
  - `owners_earnings_per_share`
  - `owners_earnings_per_share_normalized`

## Scope
**In**
- Backend derivation of OEPS and normalized OEPS during ingestion.
- Unit tests for OEPS derivation and large coverage of missing inputs.

**Out**
- Any UI changes or DCF wiring.
- Any schema migrations.

## PRD References
- `docs/prd/value-pilot-prd-v0.1.md` → **UI & Query Semantics (V1)** (Active Value reads from `metric_facts`)
- `docs/prd/value-pilot-prd-v0.1.md` → **Normalization (V1)**

## Files To Change
- `backend/app/services/owners_earnings.py` (new)
- `backend/app/services/ingestion_service.py`
- `backend/tests/unit/test_owners_earnings_facts.py` (new)
- `docs/tasks/2026-01-23_owners-earnings-oepse.md` (this file)

## Execution Plan (Requires Approval)
1. Add unit tests for OEPS derivation and normalized median (red).
2. Implement OEPS derivation helper with stable median logic (green).
3. Hook derivation into ingestion + reparse flows.
4. Verify in Docker:
   - `docker compose exec api pytest -q tests/unit/test_owners_earnings_facts.py`

## Contract Checks
- Facts sourced only from `metric_facts` style inputs.
- `owners_earnings_per_share*` use snake_case metric keys.
- Missing inputs treated as 0 (no NaN/Inf).

## Rollback Strategy
- Remove helper + tests and revert ingestion hook.

## Notes / Results
- Implemented OEPS derivation helper + ingestion hook for parsed facts.
- Added unit test covering median over last 5 FY and missing inputs treated as 0.
- Tests:
  - `docker compose exec api pytest -q tests/unit/test_owners_earnings_facts.py` → pass
  - `docker compose exec api pytest -q` → `84 passed`
