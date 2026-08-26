# 13F × Dataroma 82-manager reconciliation

## Goal

Build a repeatable, evidence-preserving reconciliation of ValuePilot's tracked
82-manager 13F universe against the corresponding Dataroma manager pages, cover
Holdings / Activity / Buys / Sells / History, explain every material mismatch,
and fix discrepancies caused by ValuePilot without treating Dataroma as the
holdings source of truth.

## Acceptance criteria

- The 82 seeded managers are mapped to Dataroma deterministically where a
  corresponding Dataroma manager exists; unmapped and ambiguous entries are
  reported explicitly rather than silently skipped.
- Dataroma parsers capture the fields required to compare Holdings, Activity,
  Buys, Sells, and History, with fixture tests that fail on malformed or changed
  page structure.
- A read-only audit command produces a machine-readable and human-readable
  report for every mapped manager and quarter, including source URLs/fetch time,
  tolerances, missing records, and field-level differences.
- Every material difference from a full 82-manager run is classified as one of:
  ValuePilot defect, Dataroma/reporting-policy difference, source-timing
  difference, identity/corporate-action ambiguity, or unavailable evidence.
- Confirmed ValuePilot defects are covered by regression tests and fully fixed.
- Dataroma remains corroborating evidence only. SEC filings and the active-filing
  policy remain the authoritative holdings source; no third-party value is
  written over SEC-derived holdings.
- The final full reconciliation and all canonical Docker verification commands
  are green, with any genuine external-evidence limitation explicitly recorded.

## Scope

### In

- The seed universe in `backend/app/services/seed_data/confirmed_managers.json`.
- Dataroma holdings, activity, buys, sells, portfolio history, and
  manager-by-stock history pages needed to explain differences.
- Active 13F-HR-family filings and their current parse-run holdings.
- Manager mapping, security/ticker normalization, quarter alignment, holding
  aggregation, change classification, portfolio-impact calculations, and
  reported portfolio value/count comparisons.
- Read-only audit artifacts and targeted correctness fixes.

### Out

- Replacing SEC/EDGAR with Dataroma as source of truth.
- Scraping around the shared Rate Guard or bypassing its limits.
- Guessing mappings, sectors, CUSIPs, or corporate actions without evidence.
- Production writes, destructive database cleanup, or auto-correcting live data
  from Dataroma.

## PRD / architecture references

- `docs/prd/13f_automation_and_resilience_prd.md` (Dataroma is discovery and
  cross-reference evidence only; EDGAR remains authoritative)
- `docs/architecture/parsing.md`
- `docs/architecture/rate-guard-public-exposure.md`
- `docs/tasks/2026-07-19_13f-manager-research-workbench.md`

## Files expected to change

- `backend/app/dataroma/client.py`
- `backend/app/dataroma/parsers/*`
- `backend/app/services/*dataroma*` or a dedicated reconciliation service
- `backend/app/cli/edgar.py` or a dedicated read-only audit script/command
- `backend/tests/unit/test_13f_dataroma_*.py`
- `backend/tests/fixtures/13f/dataroma/*`
- Seed/mapping data only where mappings are proven by Dataroma + SEC identity
- 13F parsing/query/UI code only when the audit proves a ValuePilot defect
- This task log and `docs/BACKLOG.md` for explicitly deferred non-critical work

## Test plan

Test-first targeted iteration in Docker, then exact closing gates:

1. `docker compose up -d --build`
2. `docker compose exec -T api alembic upgrade head`
3. `docker compose exec -T api pytest -q`
4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'`
5. `docker compose exec -T web npm run lint`
6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'`

Full reconciliation command:
`python -m app.cli.edgar reconcile-dataroma --manager-id <id> --history-quarters 13 --output <path>`.
The aggregate report is
`docs/audits/2026-07-19_13f-dataroma-82-manager-reconciliation.json`.

## Decision log / sign-off trail

- 2026-07-19: Started from the current dirty `codex/13f-daily-continuity`
  worktree. Existing changes belong to the user/current task chain and will not
  be discarded or rewritten wholesale.
- 2026-07-19: Initial inspection found only manager-list sync plus a shallow
  ticker/name holdings parser. No existing numeric Holdings / Activity / Buys /
  Sells / History reconciliation exists.
- 2026-07-19: Reconciliation is read-only and routes Dataroma HTTP through the
  shared Rate Guard. The audit will never write Dataroma values into
  `holdings_13f`.
- 2026-07-19: Dataroma's current list maps 80 of the 82 seeded managers.
  Bridgewater Associates (`CIK 0001350694`) and Daily Journal Corporation
  (`CIK 0000783412`) have no current Dataroma entry, so they remain explicit
  `unmapped` evidence records.
- 2026-07-19: Confirmed and fixed three ValuePilot data-path defects: explicit
  SEC empty portfolios were quarantined, some post-2023 legacy `$000` filings
  were interpreted as dollars, and a successful reparse could discard verified
  stock mappings from a prior immutable parse run. Regression tests cover all
  three paths.
- 2026-07-19: Reparsing corrected 35 affected accessions. A complete active-run
  scan now finds no `schema_dollars` portfolio with at least three common-stock
  rows and a median implied price below $1.
- 2026-07-19: Backfilled every manager through 2023 Q1, computed ownership
  changes for all added quarters, enriched 174 additional CUSIP mappings, and
  re-ran July 1–17 daily SEC synchronization. Every manager has every quarter
  from 2023 Q1 through 2024 Q1; history depth is 11–17 quarters.
- 2026-07-19: Final live reconciliation completed for all 82 managers with 80
  mapped, two explicitly unmapped, zero fetch failures, 6,001 classified
  field-level evidence items, zero suspected ValuePilot defects, and zero
  unclassified material differences. Aggregate and per-manager evidence are in
  `docs/audits/2026-07-19_13f-dataroma-82-manager-reconciliation.*` and
  `docs/audits/managers/`.
- 2026-07-19: Browser acceptance passed for all five Duan views, Makaira's
  valid zero-position Q1 filing, and Aquamarine's corrected $144.09M Q2 filing;
  the browser console had no warnings or errors.
- 2026-07-19: Verification passed with 110 targeted backend tests, 1,315 full
  backend tests on a migrated isolated PostgreSQL database, 198 frontend tests,
  clean lint, and a successful production build. The exact local canonical
  backend command reproduced the already-registered test-isolation defect when
  pointed at the populated shared development database and was stopped without
  deleting development data; every other exact canonical command passed. The
  disposable `valuepilot_test_dataroma` database was removed after verification.
