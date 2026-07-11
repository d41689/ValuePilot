# Task: 13F data-trust guardrails — make silent data gaps loud

## Goal / Acceptance Criteria

Two aggregate readiness/quality ratios each hid a distinct, real, silent data
loss. This task adds two **admin tasks** that name the specific offenders so an
operator (or the next agent) sees WHO is missing and WHICH widely-owned stock is
invisible — not just a green aggregate.

- **Guardrail 1 — `CONFIRMED_MANAGERS_NOT_FILING` (P1).** A confirmed + active
  manager that has never produced a `Filing13F` is flagged, naming each CIK. The
  readiness coverage check is a *ratio* (80% threshold); 71/82 = 86.6% cleared it
  while 11 curated superinvestors carried a wrong CIK that never files and were
  absent from every quarter. A ratio cannot see a persistent per-manager absence;
  a per-manager absolute check can.
- **Guardrail 2 — `HIGH_IMPACT_CUSIP_UNRESOLVED` (P1).** A common-stock CUSIP
  held by ≥ 3 managers in the latest quarter (on the active HR filing's current
  parse run) that has no `stock_id` is flagged, naming each CUSIP + issuer +
  holder count + dollar impact. The linked-common ratio is aggregate too — a high
  ratio hid that ExxonMobil (~10 managers, ~$1.2B) sat unresolved and was
  therefore absent from Oracle's Lens entirely.
- Both tasks render on `/admin/13f` with the offender list, and each maps to a
  concrete next action (`Review managers` anchor / `Run CUSIP enrichment` job).
- Full canonical CI green in-container.

## Scope

### In scope
- `backend/app/services/thirteenf_admin_dashboard.py` — two query helpers
  (`_confirmed_managers_never_filed`, `_high_impact_unresolved_cusips`) + wiring
  into `build_admin_tasks` as `_task_with_metadata` P1 tasks.
- `backend/tests/unit/test_13f_data_trust_guardrails.py` — 8 tests (test-first).
- `frontend/app/(dashboard)/admin/13f/page.tsx` — render the `managers` and
  `cusips` metadata lists + a compact-USD helper.
- `frontend/lib/thirteenfAdmin.js` + `.test.js` — `taskPrimaryAction` CTA mapping
  for the two new codes.

### Out of scope (deferred — see `docs/BACKLOG.md`)
- **Resolving** the mega-cap CUSIPs (XOM/Honeywell/…) — a dev/prod **data op**,
  not a code change. Done operationally on dev and reported in the PR; the
  guardrail is what makes the gap visible.
- **Managers page per-manager data-health column** — additive UI; the acute
  per-manager gap (never-filed) is already surfaced by guardrail 1.
- **Consensus-vs-distinctiveness ranking philosophy** and the
  **"13F-unrepresentative" manager flag** (Icahn/Bridgewater) — product/PO
  decisions, not a unilateral code change.
- **Daily-sync failure** decision.

## Design notes / gotchas

- **Never a ratio for a per-entity invariant.** Both guardrails are *absolute,
  per-entity* checks precisely because the ratios that were supposed to catch
  these passed while the specific entities were missing.
- **Canonical current-holdings join.** Guardrail 2 joins each holding to its own
  parse run by PK (`Holding13F.parse_run_id == ParseRun13F.id`) then the active
  HR filing via that run's accession — matching `thirteenf_holdings_query`. An
  earlier accession-based join risked double-counting when an active accession
  has both a current and a superseded parse run.
- **Dollar impact uses `value_usd`, not `value_thousands`.** Post-2023 SEC 13F
  values are reported in dollars; the misnamed `value_thousands` column stores
  the raw filing value verbatim (dollars for recent filings). `value_usd` is the
  normalized, fully-populated dollar field for recent quarters — unit-safe.
- **Options excluded** (`put_call IS NULL`): Lens excludes them, so an unresolved
  option CUSIP is not a lost common-stock consensus signal.
- **Human decisions are not data gaps.** Guardrail 1 excludes managers that are
  `status != active` or `match_status != confirmed` (retired/revoked) and
  managers with no CIK (that's the match-CIK queue, a different task).

## Test plan (Docker)

```
docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api pytest -q tests/unit/test_13f_data_trust_guardrails.py
docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Verification against real dev data

- `CONFIRMED_MANAGERS_NOT_FILING`: **absent** (0) — the 11-CIK re-point applied to
  dev means every confirmed active manager now files. Before the fix this would
  have named all 11.
- `HIGH_IMPACT_CUSIP_UNRESOLVED`: fires on **XOM (10 managers, ~$1.24B)** and
  **Honeywell (4 managers, ~$49.2M)** before the CUSIP resolution data op.
