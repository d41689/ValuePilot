# Task: Quant Trading 1-R0A — Data Sufficiency Audit and Power Contract

**ID:** `T-2026-07-21-quant-trading-1-r0a`
**Created:** 2026-07-21
**Status:** `COMPLETE — NO_GO decision; parent Phase 1 remains blocked`
**Parent:** `T-2026-07-01-quant-trading-phase-1`

## Goal

Implement the first independently verifiable part of the blocking `1-R0` gate:
a deterministic, read-only audit of the development database plus a
pre-registered statistical-power contract for H1/H2/H3. The result must be a
versioned machine-readable snapshot and a human-readable GO/NO-GO report. It
must fail closed when the required survivorship-free fundamentals/prices data,
Value Line authorization/archive continuity, or statistical history is absent.

This task does **not** claim strategy profitability. Its purpose is to prevent
underpowered research from consuming the untouched holdout or unlocking later
quant-trading work.

## Acceptance Criteria

- Report actual, current counts and date ranges for:
  - parsed `metric_facts` / `pdf_documents`, including observed publication
    months, stock breadth and metric-key coverage;
  - active authoritative 13F filings/holdings, including quarter range,
    manager breadth, mapped-stock breadth and mapping coverage.
- Keep three concepts separate in output:
  - observed publication-vintage coverage;
  - restated fiscal-period depth embedded in reports;
  - external data-source readiness/authorization.
- Pre-register and expose the power assumptions: one-sided `t_HAC >= 3`, net
  annual alpha 2%, annual tracking-error scenarios 4% and 6%, target power 80%,
  and final-holdout fraction 30%.
- Compute required holdout years and total calendar years using a documented
  normal/HAC planning approximation. Stock breadth is reported as a separate
  cross-sectional eligibility condition; it is never treated as a fungible
  substitute for time-series observations.
- Produce an explicit status for H1/H2/H3 and an overall `1-R0` gate. H1 is the
  blocking unlock criterion. Missing evidence yields `NO_GO`, never `pending`
  or an inferred pass.
- Treat Value Line automated acquisition as blocked until an operator has
  recorded authorization under `coverage-source-policy.md`; do not add a
  crawler or downloader in this task.
- Tests cover boundary cases, optimistic/insufficient datasets, unauthorized
  Value Line state, 13F filing-delay semantics, and deterministic rendering.
- An adversarial review checks for false precision, look-ahead/survivorship
  leakage, accidental production writes, and any route-map gate bypass.

## Scope

### In

- Pure power-analysis and gate-decision functions.
- Read-only SQLAlchemy coverage queries over existing tables.
- A Docker-run CLI that writes versioned JSON and Markdown audit artifacts.
- The actual 2026-07-21 development-data audit report.
- Corrections to roadmap language where its old `T x breadth` shorthand could
  imply statistical substitutability.

### Out

- Purchasing or enabling a commercial data source.
- Automated Value Line acquisition without recorded authorization.
- Production database access or mutation.
- The weekly four-consecutive-week P1-B operational acceptance test.
- `1-R1` PIT reads, factor construction/backtests, holdout evaluation, broker
  integration, and all Phase 2 execution rails.

## PRD / Architecture References

- `docs/plans/quant_trading_system_architecture_plan.md` §14 `1-R0`
- `docs/plans/quant_product_definition_acceptance.md` P1-A/P1-B
- `docs/tasks/2026-07-01_quant-trading-phase-1-research-signal-validation.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/architecture/quant-trading-pit-read-contract.md`
- SEC Form 13F official instructions/FAQ (publication lag)
- Newey & West (1987), HAC covariance estimation
- Statsmodels official power API semantics (power = 1 - type-II error)

## Files to Change

- `backend/app/services/quant_trading/data_audit.py` (new)
- `backend/app/services/quant_trading/__init__.py` (new)
- `backend/app/cli/quant_data_audit.py` (new)
- `backend/tests/unit/test_quant_trading_data_audit.py` (new, written first)
- `docs/audits/quant/2026-07-21_1-r0-data-sufficiency.{json,md}` (generated)
- Relevant Phase 1 roadmap/acceptance documents (statistical wording/status)
- This task document (decisions, adversarial review, sign-off)

## Test Plan

Targeted iteration (Docker only):

```bash
docker compose exec -T api pytest -q tests/unit/test_quant_trading_data_audit.py
```

Closing gate (verbatim canonical commands):

```bash
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

## Decisions / Gotchas / Sign-off Trail

- 2026-07-21: Split `1-R0` into this auditable `1-R0A` and the licensed-source
  activation / four-week archive-continuity acceptance in `1-R0B`. `1-R0A`
  cannot pass H1 merely because 13F history exists.
- 2026-07-21: `coverage-source-policy.md` takes precedence over the older
  roadmap instruction to automate every downloadable Value Line report.
  Repository configuration is not evidence of a license.
- 2026-07-21: Replace the roadmap's `T x breadth` shorthand with separate time
  and breadth gates. Cross-sectional breadth may reduce portfolio noise but
  cannot be assumed independent or traded one-for-one against HAC time depth.
- 2026-07-21: Implementation completed with 14 targeted tests. The development
  snapshot is `docs/audits/quant/2026-07-21_1-r0-data-sufficiency.{json,md}`.
  It records 3 Value Line documents, 768 parsed facts for 3 stocks, two
  non-consecutive report weeks, and 3.526 years of actual 13F filing
  availability. Overall result: `NO_GO`.
- 2026-07-21: Adversarial review verdict is **APPROVE 1-R0A / REJECT opening
  1-R1…1-R4**. See
  `docs/tasks/2026-07-21_quant-trading-1-r0-data-sufficiency-adversarial-review.md`.
- 2026-07-21: Closing-gate discovery: a pre-existing Research Inbox test used
  fixed 2026-07-20 snooze-boundary dates and failed when the calendar advanced
  to 2026-07-21. Production code was correct. The test now derives the valid
  30-day and invalid 31-day boundaries from `date.today()`; targeted inbox +
  quant tests pass (18 total).
- 2026-07-21: Canonical closing gates passed in order:
  - `docker compose up -d --build`
  - `docker compose exec -T api alembic upgrade head`
  - `docker compose exec -T api pytest -q` — **1447 passed**
  - `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — **216 passed**
  - `docker compose exec -T web npm run lint` — no warnings/errors
  - `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` — passed
    (the existing stale Browserslist-data warning remains recorded in
    `docs/BACKLOG.md`).
- Sign-off: **implementation APPROVED; empirical gate NO_GO; 1-R1…1-R4 remain
  closed.**
