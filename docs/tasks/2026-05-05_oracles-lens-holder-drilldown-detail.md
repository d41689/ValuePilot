# Oracle's Lens Holder Drilldown Detail

## Goal / Acceptance Criteria

- Expand Oracle's Lens holder drilldown to match the product document's V1 detail expectations.
- API top holder rows include current shares, previous shares, share delta, position weight, position rank, holder price estimate, filing date, accession, manager signal weight, turnover proxy, and high-turnover flag.
- Frontend drilldown panel displays these holder details in a compact research format.
- Do not infer actual transaction prices.

## Scope

In:
- Backend Oracle's Lens holder payload.
- Backend unit tests for holder detail fields.
- Frontend drilldown display.

Out:
- Full side-panel route.
- Manager taxonomy table/schema.
- Actual trade price or cost basis inference.
- Watchlist/reject workflow.

## Files To Change

- `backend/app/services/oracles_lens/dashboard.py`
- `backend/tests/unit/test_oracles_lens.py`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`

## Test Plan

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`

## Notes

- Holder price estimate remains `13F reported value / shares`, not transaction cost.

## Implementation Notes

- Expanded `ManagerHolding` with filing date, accession, and previous shares.
- `top_holders` now includes:
  - current shares
  - previous shares
  - share delta percentage
  - current value in thousands
  - holder price estimate
  - position weight/rank
  - filing date/accession
  - manager signal weight
  - turnover proxy and high-turnover flag
- Frontend review panel now shows holder details in a compact grid.

## Verification

- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py::test_oracles_lens_defaults_to_latest_complete_period_and_signal_rows` - passed
- `docker compose exec api pytest -q tests/unit/test_oracles_lens.py` - 6 passed
- `docker compose exec web npm run lint` - passed
- `docker compose exec web node --test lib/oraclesLens.test.js` - 10 passed
- `docker compose exec api pytest -q` - 209 passed
- `git diff --check` - passed

## Contract Checklist

- [x] No actual transaction price or cost basis inferred.
- [x] Holder estimate remains a reported-value/share proxy.
- [x] No schema migration.
- [x] Drilldown includes provenance-like filing date and accession.
