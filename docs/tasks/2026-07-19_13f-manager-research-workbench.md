# Task: 13F manager research workbench — Dataroma-complete views

**Created:** 2026-07-19  
**Status:** COMPLETE (2026-07-19)

## Goal / Acceptance Criteria

Turn the existing single-quarter manager detail into the complete investor workflow shown in the
Dataroma references, while preserving ValuePilot's stronger data-quality semantics.

- `/13f/managers/[id]` exposes five URL-addressable views: **Holdings, Activity, Buys, Sells,
  History**.
- The header summarizes the selected report period, quarter-end date, reported common-stock
  position count, and reported 13F common-stock value.
- Holdings includes rank, linked security, portfolio weight, recent activity, shares, implied
  reported quarter-end price, reported value, latest locally stored price, change since reported
  price, and locally available 52-week range. Missing market data remains explicitly unavailable.
- Activity spans all available computed quarters and groups rows by quarter. Buys contains new and
  increased positions; Sells contains reduced and exited positions. Rows show share change,
  share-change percentage, and change as a percentage of the reported common-stock portfolio.
- History shows each available quarter's reported portfolio value, position count, top holdings in
  rank order, and concentration (top 1 / top 5 / top 10 where computable).
- Every linked holding opens a dedicated manager × stock history page with quarterly shares,
  portfolio weight, activity, activity impact, reported value, and implied report price.
- Existing filing caveats, options separation, confidence/caveat evidence, and 13F limitation copy
  remain visible. The product never presents 13F value/share-derived prices as transaction price or
  cost basis.
- Existing manager list and stock-summary 13F holder views remain the discovery and stock-centric
  companion pages; no duplicate route is added.

## Scope

**In**

- Additive consumer API for multi-quarter manager history/activity.
- Additive holdings response fields derived from existing `holdings_13f`, active filings, linked
  stocks, and locally stored `stock_prices`.
- Frontend helper contracts, five-view manager UI, URL query-state, responsive tables/cards.
- Tests first, Docker verification, browser visual acceptance.

**Out**

- Copying Dataroma branding or page styling.
- Scraping Dataroma holdings as product data; EDGAR remains the 13F source of truth.
- Sector allocation until ValuePilot has a canonical, queryable sector taxonomy. The screenshots'
  `Sector % analysis` is documented as a product gap rather than inferred from issuer names.
- Live quote ingestion, returns/performance attribution, cost basis, trade-price inference, insider
  transactions, or export/follow-manager notifications.
- Schema changes or mutation of raw holdings / ownership-change history.

## Product decisions

- **Five views, one manager context:** use a `view` query parameter so every view can be linked and
  browser navigation works without multiplying nearly identical routes.
- **Activity is evidence, not advice:** new/add/reduce/exit labels are derived only from comparable
  consecutive filings. Caveated or unavailable rows remain visible and are never silently upgraded.
- **Reported price is implied:** `reported value / reported shares` is labeled "Implied report
  price" and never called a buy price. Current/52-week fields use only local `stock_prices` rows and
  carry their as-of date.
- **History prioritizes conviction:** portfolio value and concentration reveal more about a value
  investor than a flat ticker list. Top holdings retain their quarter-specific weights.
- **No fabricated sectors:** `stocks` currently has no canonical sector field. Adding a guessed
  taxonomy would violate the project's source-of-truth standard.

## Files to change

- `backend/app/services/thirteenf_user_api.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py`
- `backend/tests/unit/test_13f_user_api.py`
- `frontend/lib/thirteenfManagers.js`
- `frontend/lib/thirteenfManagers.d.ts`
- `frontend/lib/thirteenfManagers.test.js`
- `frontend/app/(dashboard)/13f/managers/[id]/page.tsx`
- `frontend/app/(dashboard)/13f/managers/[id]/stocks/[stockId]/page.tsx` (new)
- `frontend/components/thirteenf/ManagerResearchWorkbench.tsx` (new)
- `frontend/components/layout/AppShell.tsx` (responsive shell correction found in visual QA)
- `frontend/lib/appShellResponsive.test.js` (new)

## Test plan

Targeted iteration:

```bash
docker compose exec -T api pytest -q backend/tests/unit/test_13f_user_api.py
docker compose exec -T web sh -lc 'node --test lib/thirteenfManagers.test.js lib/uiStandard.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

Closing gate (verbatim per `AGENTS.md`):

```bash
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Sign-off trail

- 2026-07-19: Dataroma reference audit found the five manager views plus a sector-analysis block.
  Existing ValuePilot companion surfaces already cover manager discovery and stock-centric holders;
  this task closes the manager history/workflow gap without duplicating those routes.
- 2026-07-19: 390px browser QA found the global dashboard sidebar still consumed 224px on small
  screens, leaving the manager workbench about 150px wide. Scope expanded to a responsive mobile
  shell because the requested manager views are otherwise unusable on phones.
- 2026-07-19: Dataroma's holding-row history affordance was confirmed as a separate manager ×
  security timeline. Added `/13f/managers/[id]/stocks/[stockId]` and an on-demand consumer endpoint;
  real AAPL acceptance showed eight available quarters, correct weights/actions/impact and implied
  report prices.
- 2026-07-19: Real Duan Yongping acceptance (`manager_id=4011`) passed for Holdings, Activity, Buys,
  Sells, History and AAPL holding history. Activity order matches the investor workflow
  (Add → Buy → Reduce → Sell). At 390px, the page has no body-level horizontal overflow; wide tables
  scroll inside their own containers and mobile navigation remains available.

## Verification trail

- Targeted backend consumer API on isolated migrated database: `25 passed`.
- Canonical build/start and migration commands: green.
- Canonical backend `pytest -q` against the compose-configured shared dev database was run but
  stopped after widespread cross-module failures caused by the populated rehearsal corpus; the
  suite's global-delete/fixed-count assumptions are incompatible with that database and the command
  became extremely slow. The shared database was not cleared. This infrastructure defect is recorded
  in `docs/BACKLOG.md`.
- Full backend suite on a freshly migrated isolated database: `1294 passed, 3 warnings` in 91.62s.
- Canonical frontend unit suite: `198 passed`.
- Canonical frontend lint: green, no warnings or errors.
- Canonical production build: green; both `/13f/managers/[id]` and
  `/13f/managers/[id]/stocks/[stockId]` compiled as dynamic routes.
- Disposable database `valuepilot_test_manager_workbench` was dropped after verification and is not
  recoverable; it contained test data only.
