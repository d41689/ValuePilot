# SEC financial gold-set acceptance run

Status: Step D implementation and acceptance complete; Step E canonical closing
gate passed on final HEAD; hold isolated databases and reports

Owner: Product / Engineering

Date: 2026-08-30

## Goal

Run the locked 24-company SEC financial gold set through the normal authorized
Rate Guard path in a clean Step C acceptance database, retain and verify the
evidence, and publish stable per-case plus aggregate acceptance reports. An
immediate second pass must demonstrate idempotency without deleting first-pass
evidence or representing newly acquired evidence as known at the historical
filing-selection cutoff.

This validates the source-traceable evidence foundation for reconstructing
owner earnings and keeping missing/conflicting evidence visible. It does not
publish SEC raw facts into canonical `metric_facts`.

## Acceptance criteria

- Validate the locked manifest and local source/egress/Rate Guard guards before
  any public SEC request.
- Create a fresh isolated acceptance database/storage run through the Step C
  preflight. Never connect acceptance writes to shared `valuepilot`.
- Record the configured Rate Guard identity/route and authenticated EDGAR
  metrics before and after. All normal public filing requests use that single
  Rate Guard; no direct SEC request, scanning, enumeration, or abnormal input.
- Run all 24 locked cases sequentially, using the locked
  `filing_selection_as_of` and at most ten completed fiscal years.
- Preserve legitimate unavailable history or parse limitations as typed gaps or
  failures. Do not loosen validation to make the run pass.
- Write stable pass-specific JSON and human summaries for every case, followed
  by aggregate JSON/human reports covering identity, expected years, selected
  forms/accessions, retained artifact existence/size/SHA, parse status/raw fact
  counts, typed gaps/failures, operation attempted/finalized/available times,
  and `metric_facts` publication count.
- Run an immediate second pass through Rate Guard. Report per-case and aggregate
  lineage deltas plus duplicate semantic/artifact/run/fact checks; identical
  content must not create duplicate lineage.
- Capture exact request/error counters including 403/429 outcomes, storage size
  and integrity totals, year coverage, and report paths.
- Keep the isolated database and storage intact until Terra reviews Step D.

## Scope

### In

- A test-first batch/report aggregator if the repository lacks one.
- Normal sequential gold-case acquisition through configured Rate Guard.
- Retained-content integrity, lineage/idempotency, PIT, gap/failure, and
  no-publication audit reports.
- Local focused verification and report validators.

### Out

- Adversarial requests, security testing, external probing, or SEC enumeration.
- Direct backend-to-SEC access or bypassing Rate Guard limits/retries/pause.
- Deleting retained acceptance evidence before review.
- Mapping SEC raw facts into `metric_facts`.
- The full Step E canonical closing gate, push, PR, or merge.

## References

- `/Users/dane/.codex/attachments/cf57e9bb-fa43-48de-b1ce-3933f74bca55/goal-objective.md` Step D
- `docs/acceptance/financial_truth_beta_gold_set.yml`
- `docs/acceptance/sec-gold-environment.md`
- `docs/architecture/parsing.md`
- `docs/prd/value-pilot-prd-v0.1.md` §H
- `docs/tasks/2026-08-30_sec-gold-acceptance-environment.md`

## Planned files

- `backend/app/acceptance/sec_gold_report.py`
- `backend/app/acceptance/sec_gold_audit.py`
- `backend/app/cli/sec_financials.py`
- `backend/app/services/sec_financial_ingestion.py`
- `backend/tests/unit/test_sec_gold_acceptance.py`
- `backend/tests/unit/test_sec_financial_cli.py`
- `backend/tests/unit/test_sec_financial_history_selection.py`
- `backend/tests/unit/test_sec_financial_source_guard.py`
- `docker-compose.acceptance.yml`
- `rate-guard/app/metrics.py`
- `rate-guard/tests/test_gateway.py`
- `scripts/sec_gold_acceptance.sh`
- `docs/acceptance/sec-gold-environment.md`
- this task document

## Test and run plan

1. Run manifest, source/egress, Rate Guard client, and standalone Rate Guard
   tests locally in Docker.
2. Write failing aggregate/report/idempotency/integrity tests before the minimum
   implementation.
3. Create and verify one fresh disposable acceptance run; capture Rate Guard
   identity/metrics before acquisition.
4. Run pass 1 for all cases sequentially, recording each terminal report and
   progress. Stop and report rather than probing around blocked/offline access.
5. Run pass 2 sequentially and aggregate integrity/idempotency reports.
6. Run report validation, focused Docker suites, compile/Compose/shell/diff
   checks. Keep database/storage and hold commit for Terra.

## Decisions and sign-off trail

- The central Rate Guard identity preflight returned HTTP 530 before any SEC
  request. Per the approved Step D boundary, the run pins the existing local
  Rate Guard implementation as its one configured route, with fallback disabled,
  1 request/second, five bounded retries, and the existing global pause.
- Run `step-d-gold-20260830` uses database
  `valuepilot_acceptance_step_d_gold_20260830` and storage
  `storage/sec_gold_acceptance/step-d-gold-20260830`. Its before snapshot proves
  zero SEC lineage, zero retained bytes, zero Rate Guard requests, and zero
  `metric_facts` before acquisition.
- The missing Step D tooling was implemented test-first: cumulative Rate Guard
  counters, pass-specific JSON/text, locked sequential/resumable batch execution,
  retained-file audit, idempotency/duplicate checks, and aggregate JSON/text.
- Pass 1 exposed an ordinary local selection defect after AAPL finalized: an
  MSFT 2013 quarter predated the locked 2015 history boundary and the DB identity
  trigger correctly rejected it. A regression now requires supplemental 10-Q
  and 6-K periods to be on/after `available_start_on`; history-selection and
  lineage tests passed before the run resumed without deleting AAPL evidence.
- Pass 1 and the immediate pass 2 both finalized all 24 locked cases. Both
  passes preserved their own database-stamped attempted/finalized/available
  times. Every one of the 24 pass-two reports has an exact zero creation delta
  for filings, submission snapshots, artifacts, parse runs, and raw facts.
- The aggregate validator passed with 24/24 reports and 24/24 idempotent cases.
  It re-read 6,750 retained artifact references from controlled storage and
  verified existence, size, and SHA-256 for all of them: zero failures and
  8,873,440,395 verified bytes. The controlled store contains 6,744 content
  files; repeated content references account for the difference and no semantic
  lineage duplicates were found. Filing, artifact, parse-run, and raw-fact
  duplicate counts are all zero.
- Rate Guard recorded 13,506 upstream requests, two cache hits, and zero 403,
  429, or 503 responses. Its final policy remained one request/second, five
  retries, no active global pause, the pinned instance identity, and no
  fallback/direct SEC path.
- Twenty-two cases covered every manifest-expected completed fiscal year. AVGO
  covered its locked 8/8 expectation. JPM covered 3/10 and GS 5/10; both expose
  `history_scan_limit_exceeded` and the exact missing fiscal years rather than
  silently claiming coverage. Legitimate historical `no_inline_xbrl_facts`,
  oversized retained-document limits, required-artifact unavailability,
  invalid foreign filing period metadata, and foreign manifest failures remain
  typed. Validation was not loosened.
- The final acceptance database contains 48 finalized operations, 893 filings,
  98,837 artifact lineage rows, 890 parse runs, 1,339,476 raw facts, 89 retained
  submission snapshots, and 20 acquisition-failure projections. Raw SEC facts
  never published to `metric_facts`: before and after counts are both zero.
- Final local verification is green: the isolated acceptance
  report/CLI/lineage/migration/source/egress/client suite passed 199 tests; the
  history-selection regression passed 29 tests; standalone Rate Guard passed
  42 tests. Docker compile, normal and acceptance Compose validation, shell
  syntax, and `git diff --check` passed. The full Step E canonical closing gate
  was intentionally not run.
- The final harness used only the preflight-verified database
  `valuepilot_acceptance_step_d_gold_20260830`; pytest created and removed a
  random schema inside that acceptance database. The read-only shared
  fingerprint remains revision `20260828500000` with 68 public tables. No Step D
  command connected an acceptance writer or Alembic to shared `valuepilot`.
- Evidence remains available for review at
  `storage/sec_gold_acceptance/step-d-gold-20260830`; the database and storage
  have not been destroyed. Stable aggregate outputs are `reports/aggregate.json`
  and `reports/aggregate.txt`, with pass-specific case JSON/text and before/after
  runtime snapshots alongside them.
- Terra's Step D review identified two normal reliability gaps. The aggregate
  formerly trusted pass-two JSON creation counters, and resumed `run-pass`
  skipped existing typed-incomplete reports without restoring their exit state.
  Both were reproduced test-first and fixed without another SEC request.
- Each of the 48 pass reports is now tied to one distinct finalized operation
  with matching run/case/pass, issuer, stock, attempted/available timestamps,
  selected accessions, attempt ownership, terminal result, and ownership
  transaction IDs. Snapshot and parse-run creation use direct operation IDs;
  raw facts use the operation-owned parse run; append-only filing/artifact
  creation is counted inside operation-owned attempts by PostgreSQL `xmin`
  against the stored operation `created_txid`. All five DB counts must equal the
  report counters. The regenerated aggregate proves 48/48 counter matches, zero
  ownership-transaction mismatches, and all five DB-created counts equal zero
  for every pass-two operation.
- `run-pass` now derives its final status from all 24 stable reports after the
  loop. A local resume of the retained pass-two directory skipped all 24 cases,
  made no SEC request, re-counted 24 typed-incomplete reports, and correctly
  exited 2. Wrong run, case, or pass identities fail closed in CLI regressions.
  No real acquisition rerun is required for this follow-up.

## Step E isolated closing-gate evidence

- The closing gate did not use or migrate shared `valuepilot`, and it did not
  modify the retained Step D database or storage. The repository-external
  Compose override is
  `/tmp/valuepilot-step-e-closing-gate-20260831/docker-compose.closing-gate.yml`;
  the corrected resolved config is
  `/tmp/valuepilot-step-e-closing-gate-20260831/resolved-compose-retry.yml`.
  It pins the API to
  `valuepilot_test_closing_gate_step_e_20260831`, mounts only the exact
  `/tmp/valuepilot-step-e-closing-gate-20260831/edgar_raw` storage directory,
  selects replay mode, disables Rate Guard fallback, and disables all ingestion
  schedulers/workers/seeds. `RATE_GUARD_URL` resolves only to the project-local
  Rate Guard.
- Before Compose startup, PostgreSQL reported
  `current_database() = valuepilot_test_closing_gate_step_e_20260831` and zero
  `public` tables. The exact canonical `docker compose up -d --build` command
  passed, followed by the exact `docker compose exec -T api alembic upgrade
  head` command. The latter applied the complete migration chain from base to
  `20260830140000` without interruption.
- An initial environment attempt used the otherwise isolated empty database
  `valuepilot_closing_gate_step_e_20260831`. Its build and zero-to-head migration
  passed, but pytest correctly rejected that name during collection because the
  existing isolation helper permits only `valuepilot`, `valuepilot_test*`, or a
  strictly named acceptance database. No tests or application requests ran in
  that attempt. The guard was not loosened; the failed database remains retained
  as evidence.
- With the corrected fresh `valuepilot_test*` database, the exact canonical
  `docker compose exec -T api pytest -q` command completed with **1,687 passed,
  1 failed, 1 warning in 208.65 seconds**. The sole failure was
  `test_operational_audit_transaction_rejects_database_writes`, a pre-existing
  quant-trading test from before the SEC lineage work. It calls
  `begin_read_only_development_audit()` against the real test connection and
  asserts the database name is exactly shared `valuepilot`; the required
  isolated closing-gate database therefore fails its deliberate production
  guard before the test can exercise read-only behavior.
- This was an environment-coupled, non-SEC test incompatibility, not a Step3
  regression. Resolving it by pointing the gate at shared `valuepilot` would
  violate the Step E isolation requirement. The Step E follow-up authorized a
  minimal supporting fix: the quant audit runtime now permits only exact
  `valuepilot` or a full-string, PostgreSQL-length-safe
  `valuepilot_test_<lowercase-safe-slug>` name. It still rejects production,
  acceptance, missing/bare suffix, uppercase, punctuation, repeated/trailing
  underscore, and similar prefix/suffix names; there is no environment-variable
  bypass. The operational path still executes `SET TRANSACTION READ ONLY`, and
  its test now compares the validated name to PostgreSQL's actual
  `current_database()` instead of hard-coding shared `valuepilot`.
- Test-first evidence: the focused file was red with 16 failures and 21 passes
  before implementation, including both newly allowed test names and the real
  isolated operational connection. It is green after the minimal change with
  **37 passed, 1 warning in 1.10 seconds**. Per Terra's review boundary,
  frontend tests, lint, build, canonical `git diff --check`, and the full
  closing-gate rerun remain paused. No external SEC request or direct SEC path
  was used. Both closing-gate databases and the Step D evidence remain intact.

## Final Step E canonical closing gate

- Terra passed the isolated quant-audit supporting fix, committed by the root
  agent as `3129deb002343f20bfba68da3d279dc2e807ed83`. The final gate used a
  third, never-before-used database,
  `valuepilot_test_step_e_final_20260831`, rather than either prior diagnostic
  database. Before any migration, PostgreSQL returned that exact
  `current_database()` and zero `public` tables.
- The fixed Compose project was `valuepilot-step-e-final-20260831`. Its
  repository-external override, resolved config, and isolated storage are:
  `/tmp/valuepilot-step-e-final-20260831.ljXxTA/docker-compose.closing-gate.yml`,
  `/tmp/valuepilot-step-e-final-20260831.ljXxTA/resolved-compose.yml`, and
  `/tmp/valuepilot-step-e-final-20260831.ljXxTA/edgar_raw`. The resolved API
  configuration names only the final test database, selects replay mode, uses
  the project-local Rate Guard with fallback disabled, and disables SEC/13F,
  research-notification, manager-seed, and CUSIP-seed background work.
- With `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME`, and the non-conflicting host ports
  exported once for that fixed environment, the seven canonical commands ran
  verbatim, in the required order, and each exited zero:

  1. `docker compose up -d --build` — passed; API, web, placeholder DB, and
     local Rate Guard images built and containers started.
  2. `docker compose exec -T api alembic upgrade head` — passed; the empty
     database upgraded from base through `20260830140000`.
  3. `docker compose exec -T api pytest -q` — **1,703 passed, 1 warning in
     198.20 seconds**. The warning is the pre-existing FastAPI test-client
     compatibility deprecation notice; there were no failures.
  4. `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — **216
     passed, 0 failed** in 200.79725 milliseconds.
  5. `docker compose exec -T web npm run lint` — passed with no ESLint warnings
     or errors.
  6. `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` —
     passed; optimized compilation, type/lint validation, and all 27 static
     pages completed. The only notice was the pre-existing stale Browserslist
     data item already recorded in `docs/BACKLOG.md`.
  7. `git diff --check` — passed with no output.
- `alembic heads` and `alembic current` both report the sole head
  `20260830140000`. After the gate, the final database has 75 migrated public
  tables and zero rows in `metric_facts`, `sec_raw_xbrl_facts`, SEC financial
  ingestion operations, retained SEC artifacts, and SEC parse runs. Thus no
  SEC raw fact was published to `metric_facts`.
- The focused source/egress/Rate Guard client proof also passed **48 tests**
  with the same pre-existing test-client warning. The authenticated local Rate
  Guard metrics remained at zero total requests, zero cache hits/misses, zero
  403/429/503 responses, and no global pause. Its configured EDGAR policy stayed
  at one request/second and five retries. No direct SEC path or real SEC request
  ran during Step E.
- A final read-only fingerprint of shared `valuepilot` remained at revision
  `20260828500000` with 68 public tables. The retained Step D database still has
  its 48 operations, and its 5,908,011-byte aggregate report remains present at
  `storage/sec_gold_acceptance/step-d-gold-20260830/reports/aggregate.json`.
  Neither shared development state nor Step D evidence was modified or cleaned.
- No new unrecorded deferred finding was discovered. The isolated final
  database, temporary Compose evidence, containers, and Step D database/storage
  remain intact for final review. No commit or push was performed for this
  task-document update.

## PR #131 independent-review remediation

- The independent review's P2 was valid: crash-resume status formerly checked
  only the stable JSON run/case/pass shape before treating an existing report as
  completed. It did not independently prove that the CIK, stock, operation,
  database-stamped timestamps, selected accessions, creation counters, and
  transaction ownership still matched one finalized database operation.
- Resume now performs that same database-backed operation audit in an explicit
  PostgreSQL read-only transaction twice: once over every report already present
  before the script skips any case, and again over all 24 reports before the
  terminal exit is derived. Missing reports are allowed only during the first
  partial-resume preflight; malformed or identity-conflicting reports fail with
  an operational exit. The former shallow helper was renamed from
  `validate_case_report_identity` to `validate_case_report_structure` so callers
  cannot mistake JSON shape validation for database identity proof.
- Regression tests cover wrong CIK, stock, and operation IDs against real
  PostgreSQL lineage, plus partial resume, malformed JSON, wrong run/case/pass,
  typed-incomplete reports, and the CLI's database-audit call boundary. The SEC
  acceptance/CLI/lineage/migration/source/egress/client suite passed **203
  tests**. A read-only resume against the retained pass-two evidence validated
  24/24 reports before skipping, skipped all cases without a SEC request, and
  correctly exited 2 with `typed_incomplete=24`. Database counts were identical
  before and after: 48 operations, 893 filings, 89 submission snapshots, 98,837
  artifacts, 890 parse runs, 1,339,476 raw facts, and zero `metric_facts`.
- The independent review's P3 was also valid. The aggregate has exactly two
  cases with annual gaps—JPM 3/10 and GS 5/10—while AVGO legitimately covers its
  locked 8/8 interval. This record now says **22/24**, matching the immutable
  aggregate and all pass reports; retained evidence was not rewritten.
- The post-fix isolated closing gate passed: backend **1,707 passed** with the
  existing FastAPI warning; frontend **216 passed**; lint had no warnings or
  errors; production build generated all 27 pages with only the existing stale
  Browserslist advisory; migration-to-head and `git diff --check` passed.
- Operational caveat: the first post-fix build command unintentionally targeted
  the already-running default development Compose project before the isolated
  override was restored. No migration or pytest ran against shared `valuepilot`,
  whose revision/table fingerprint stayed `20260828500000`/68. However, hot
  reload plus the enabled development 13F worker appended parse runs 7834–7844
  between 03:41 and 03:50 UTC: 11 quarantined `is_current=false` runs and 480
  associated holdings for two pending reparses. No current run was replaced.
  The rows were not deleted or rewritten; the underlying repeat-work defect is
  recorded in `docs/BACKLOG.md` for a separate, reviewed fix.
