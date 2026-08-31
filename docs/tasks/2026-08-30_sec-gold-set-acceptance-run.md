# SEC financial gold-set acceptance run

Status: Step D implementation and acceptance complete; hold commit, database,
and reports for Terra review

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
- Twenty-one cases covered every manifest-expected completed fiscal year. AVGO
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
