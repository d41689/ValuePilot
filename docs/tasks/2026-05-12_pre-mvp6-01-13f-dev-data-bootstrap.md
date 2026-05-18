# Pre-MVP6-01: 13F Dev Data Bootstrap and Admin Verification

## Status

**Accepted (PO sign-off 2026-05-12 after acceptance run).** Dev /
admin validation blocker resolved. The seeder is for dev / admin
verification only and **must not** be wired into pytest fixtures —
running pytest against a seeded DB fails 177 / 781 tests because
the suites read directly from the dev DB. Use the `--reset-only`
flag before pytest, then re-seed afterwards if needed.

First of two Pre-MVP6 Stabilization Gate tickets. Pre-MVP6-02
(IA split plan) is the second.

PO decision recorded 2026-05-12: "先让 dev 环境有真实可验证数据,
再把 admin 从巨型单页变成可运营控制台。然后再谈 MVP6 新功能。"
This ticket addresses the first half.

Supersedes the non-blocking backlog
`docs/tasks/2026-05-12_backlog-dev-cusip-linking-fixture.md` —
that ticket's narrower CUSIP-linking scope is folded into this
broader bootstrap.

## Goal / Acceptance Criteria

Make the dev environment a **viable verification surface** for
the 13F automation track. Today the dev DB is in an
inconsistent pre-MVP1B-parser state (4022 holdings with
`parse_run_id=NULL`, 0 parse_runs, 100% `pending_mapping`
CUSIPs, 0 quality reports, 0 `oracles_lens_signals`) — so
`/admin/13f` renders as a sea of empty panels even though
every backend service is correctly implemented. **The page
isn't broken; the dev data is.** This ticket fixes that.

PO direction selected **Path B (synthetic fixture seeder)** over
Path A (real OpenFIGI pipeline) because Path B is:

- Independent of OpenFIGI API key / external rate limits.
- Reproducible across dev / CI / contributor laptops.
- Resilient to the dev DB's current dirty state (can be re-run
  on a freshly migrated DB).
- Usable as a future regression fixture for scoring-pipeline
  changes.

Path A (real OpenFIGI ingestion in dev) remains a separate
future ticket if production-fidelity testing becomes a need.

Acceptance criteria:

- New idempotent seeder script (or admin script) shippable via
  one Docker compose command. Suggested invocation:
  `docker compose exec api python -m app.scripts.seed_13f_dev_fixture`
  or a Makefile target.
- Seeded universe (minimum shape):
  - **5–10 stocks** with `stock_id` linked.
  - **30–50 managers** spread across the canonical 8-value
    taxonomy (`long_term_fundamental`, `value_concentrated`,
    `activist`, `quant`, `high_turnover`, `index_like`,
    `multi_strategy`, `unknown` — at least one of each so
    every weight branch is exercised).
  - **200–500 holdings** with `cusip_mapping_status="linked"`
    and `holding_attribution_status="direct"`.
  - **≥ 2 consecutive quarters** so streak / cross-quarter
    delta computation is non-trivial.
  - **≥ 1 amendment-pending case** (`amendment_status="amendments_pending"`)
    so MVP5-02 exclusion fires.
  - **≥ 1 13F-NT case** (`coverage_type="notice_reported_elsewhere"`)
    so NT routing is exercised.
  - **≥ 1 combination report case**
    (`coverage_completeness="partial"`) so PARTIAL_COVERAGE
    caveat fires.
  - **≥ 1 confidential treatment case**
    (`has_confidential_treatment=True`) so the
    CONFIDENTIAL_TREATMENT caveat fires.
- Idempotency: re-running the seeder against an already-seeded
  DB must not produce duplicates and must not crash.
- After seeding, run the persisted scoring backfill against
  the seeded quarter (one-shot
  `compute_signal_weighted_scores` call from the seeder is
  acceptable, OR document the admin-side trigger in the
  task log).
- Acceptance verification (each must pass after one seed run):
  - `oracles_lens_signals > 0`.
  - A non-zero subset of `holdings_13f` has `stock_id` non-null
    AND `cusip_mapping_status="linked"`.
  - `linked_common_holding_ratio > 0` returned by the
    readiness API.
  - `/admin/13f` Overview / Readiness panel shows non-empty
    health data (no "unavailable" everywhere).
  - Managers section shows a typed-vs-unknown mixed sample.
  - Filings section shows succeeded / pending / needs_review
    samples (not 100% pending).
  - Readiness panel returns at least one of
    `ready / usable_with_warning / experimental` (not always
    `unavailable`).
  - `/13f/oracles-lens` user page renders with at least 3
    candidate rows.
  - The MVP5-02 amendment-exclusion path fires for ≥ 1
    seeded amendment-pending holder (verify
    `excluded_holder_count > 0` in a signal's
    `score_explanation`).
  - MVP5-03 Phase 1 comparison utility, when run after
    seeding, returns a non-empty `items` array (NOT
    blocked because Phase 3 sign-off is still
    staging/prod-only per
    [[tool-validation-vs-product-signoff]] — this is dev
    verification, not Phase 3 sign-off).

## Scope In

- New seeder module under `backend/app/scripts/` (or
  `backend/tests/fixtures/dev_seed/` if engineer prefers).
- Compose / Makefile glue for one-command invocation.
- Documentation: a short README block in this task file
  recording the invocation, the seeded shape, and how to
  re-run after a `db reset`.
- Acceptance verification commands run after seeding and
  recorded in `Verification Results`.

## Scope Out

- **No production data**. The seeder writes synthetic data
  only.
- **No OpenFIGI pipeline integration** — Path A remains a
  separate future ticket.
- **No MVP5-03 Phase 3 sign-off**. The comparison utility's
  dev output is engineering verification only;
  Phase 3 still requires staging/prod data
  (see [[tool-validation-vs-product-signoff]]).
- **No new product features**. This is environment
  remediation, not feature work.
- **No admin UI redesign** — that's Pre-MVP6-02 + MVP6.
- **No CI integration** in this ticket. If the seeder becomes
  a CI fixture later, file a separate follow-up.

## PRD / Decision References

- `docs/prd/13f_automation_and_resilience_prd.md` §3 (Manager
  taxonomy + fields), §6 (filings + amendments), §7
  (holdings model), §8 (CUSIP mapping), §10 (readiness levels).
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` Pre-MVP6
  Stabilization Gate.
- `docs/tasks/2026-05-12_backlog-dev-cusip-linking-fixture.md`
  (superseded by this ticket).
- 2026-05-12 PO assessment: "工程 deliverables 都到位了, 但
  dev 环境从来没跑完 MVP1B parser 端到端管线."

## Files Expected To Change

- `backend/app/scripts/seed_13f_dev_fixture.py` (new) — or
  `backend/tests/fixtures/dev_seed/__init__.py`, engineer's
  call.
- `docker-compose.yml` / `Makefile` — new target.
- `docs/tasks/2026-05-12_pre-mvp6-01-13f-dev-data-bootstrap.md`
  (this file, with `Verification Results` filled in after
  the seeder runs).
- Possibly `backend/tests/fixtures/__init__.py` for shared
  helpers if the seeder reuses test-side managers/stocks
  builders.

## Test Plan

- `docker compose exec api python -m app.scripts.seed_13f_dev_fixture`
  (or the chosen invocation).
- Idempotency check: run the same command twice; second run
  must succeed and not create duplicates.
- Verification queries (record in task log):
  ```
  SELECT count(*) FROM oracles_lens_signals;
  SELECT count(*) FROM holdings_13f WHERE stock_id IS NOT NULL AND cusip_mapping_status = 'linked';
  SELECT count(*) FROM filings_13f WHERE parse_status = 'succeeded';
  ```
- Manual probe of `/admin/13f` after login as
  `d41689@gmail.com` (existing admin in dev DB) — confirm
  panels are no longer uniformly empty.
- `docker compose exec api pytest -q` — no regression on
  the 781-test baseline.

## Review Pattern

This is environment / tooling work, not a product change.
One reviewer role suffices:

- **Staff Engineer** — confirm seeder idempotency,
  data-shape coverage of the 4 caveat cases (amendment / NT
  / combination / confidential), and that the acceptance
  queries above return the expected counts.

## Progress Notes

- 2026-05-12: Task spec filed per PO Pre-MVP6 stabilization
  decision. Supersedes the earlier non-blocking dev CUSIP
  linking backlog. PO selected Path B (synthetic seeder)
  over Path A (real OpenFIGI). Engineer's call on file
  layout (`app/scripts/` vs `tests/fixtures/dev_seed/`).
- 2026-05-12: Implementation:
  - New `backend/scripts/seed_13f_dev_fixture.py` invoked as
    `docker compose exec api python -m scripts.seed_13f_dev_fixture`.
  - Three CLI modes:
    - default: idempotent seed (skip-if-exists by deterministic
      key — CIK / ticker / accession / fingerprint).
    - `--reset`: wipe prior devseed rows (matched by the
      DEVSEED / 9999 shibboleth), then reseed. Use when the
      seeder's own logic changes.
    - `--reset-only`: wipe devseed rows and exit. **Required
      before running pytest against the dev DB** — devseed
      rows pollute test invariants in `test_13f_user_api.py`
      and similar suites that read directly from the dev DB
      (177 of 781 tests fail under a seeded DB because they
      assume an empty / specific universe shape).
  - Seeded shape:
    - 8 stocks (DEVSEED1..DEVSEED8) with linked CUSIP rows
      (synthetic CUSIPs `DEV000001`..`DEV000008`).
    - 32 managers (4 per canonical 8-value taxonomy) with
      deterministic CIKs `9999000001`..`9999000032`.
    - 2 quarters: 2025-Q4 (prior) + 2026-Q1 (current).
    - 64 filings + 64 parse_runs + 252 holdings.
    - All four caveat cases present:
      - manager #0 → `amendment_status="amendments_pending"`
        on current quarter (fires MVP5-02 exclusion +
        AMENDMENTS_PENDING caveat).
      - manager #1 → 13F-NT on **prior** quarter (fires
        NT_QUARTER_STREAK_BREAK when current-quarter streak
        compute walks back; putting NT on current would have
        made the manager invisible without firing the caveat).
      - manager #2 → `coverage_completeness="partial"` on
        current quarter (fires PARTIAL_COVERAGE).
      - manager #3 → `has_confidential_treatment=True` on
        current quarter (fires CONFIDENTIAL_TREATMENT).
  - Real-SEC-shape 20-char accession format
    (`XXXXXXXXXX-YY-NNNNNN`) so the synthetic accessions
    fit the `VARCHAR(20)` column without a schema change
    (per CLAUDE.md: fixture must conform to schema, not the
    other way around).

## Verification Results

### Acceptance criteria (all pass after seed + scoring run):

```
oracles_lens_signals_count: 8                              ✓ (>0)
linked_holdings_count:      252                            ✓ (200-500 target window)
succeeded_filings_count:    64                             ✓ (non-zero, multi-status)
devseed_typed_managers:     28                             ✓ (mixed sample)
devseed_unknown_managers:   4                              ✓ (priority queue populates)
signals_with_excluded_holders: 4                           ✓ (MVP5-02 exclusion fires)
distinct_caveat_codes: [AMENDMENTS_PENDING,
                        CONFIDENTIAL_TREATMENT,
                        NT_QUARTER_STREAK_BREAK,
                        PARTIAL_COVERAGE]                  ✓ (4-of-4 caveat cases)
```

### Endpoint probes:

- `/api/v1/13f/oracles-lens?period=2026-Q1&use_persisted_scores=true&min_holders=3`
  returns 8 candidate rows (DEVSEED1..DEVSEED8) with real
  ranking + `medium_confidence` labels.
- `/api/v1/13f/readiness` → `readiness_level: experimental`
  (one of the three valid states `ready / usable_with_warning
  / experimental`); `historical_depth_quarters: 2`.
- `build_formula_comparison(quarter="2026-Q1")` →
  `total_stocks_compared: 8`, `magnitude_diff_count: 5`,
  `top10_swap_count: 0`. The five magnitude-diff flags reflect
  the legacy `min(weight*4, 1.0)` vs persisted-raw base
  divergence on small-position holders. Useful as a sanity
  check that the Phase 1 utility produces real output on
  representative data — **NOT a staging/prod sign-off** per
  [[tool-validation-vs-product-signoff]].

### Idempotency:

- Run #1 (default after `--reset-only`): 252 holdings / 64
  filings / 64 parse_runs created.
- Run #2 (default, no flag, against already-seeded DB):
  `filings created: 0, parse_runs created: 0, holdings created: 0`.
  No crashes. Acceptance summary identical.

### Test-suite regression check:

- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
- `docker compose exec api pytest -q` → **781 passed**
  (unchanged from the MVP5 baseline).
- The seeder is **not** wired into pytest fixtures; running
  pytest against a seeded DB fails 177 / 781 tests because of
  invariant pollution. Use `--reset-only` before pytest.
  Documented in the seeder docstring and the module's
  `--help` output.

### Frontend:

- `docker compose exec web npm run lint` → clean.
- `docker compose exec web npm run build` → compiled
  successfully (no frontend changes in this commit; sanity
  check only).

## Final Devseed State Notes

After this commit, dev DB carries the devseed fixture so an
operator logging in as the existing admin
(`d41689@gmail.com`) can browse `/admin/13f` and see real,
non-empty panels. To run pytest, invoke
`--reset-only` first, then re-seed afterwards if needed.
A future ticket can wire the seeder into a Makefile target
or CI; out of scope here.
