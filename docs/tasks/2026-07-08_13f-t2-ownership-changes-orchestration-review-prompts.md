# Review prompts — T2 (ownership_changes 编排接线 + 计算去重加固)

Task doc: [`2026-07-08_13f-t2-ownership-changes-orchestration.md`](./2026-07-08_13f-t2-ownership-changes-orchestration.md)
PO plan: [`2026-07-08_13f-real-data-findings-po-plan.md`](./2026-07-08_13f-real-data-findings-po-plan.md)
Branch: `claude/13f-t2-ownership-changes-orchestration` · PR #108 (CI green).
Read the diff with `git diff main...claude/13f-t2-ownership-changes-orchestration`.

## What changed

**F2 — orchestration.** `compute_ownership_changes_for_manager_quarter` (MVP2-02)
had no production caller. Added a `compute_ownership_changes` stage to
`quarterly_pipeline` (after `quality_check`, before scoring) that loops the
quarter's active HR/HR-A managers under a per-manager `session.begin_nested()`
SAVEPOINT; plus a standalone `compute_ownership_changes` job_type + a
`compute_ownership_changes:{quarter}` lock builder. Files:
`backend/app/services/thirteenf_admin_dashboard.py`.

**F3 — aggregation.** Two holdings resolving to one effective
`(security_key, ssh_prnamt_type, position_type)` (two CUSIPs → one stock)
violated `uq_ownership_changes_manager_quarter_security_position`. Fix
**aggregates** such holdings into one additive position (sum shares + value) via
a read-only `_AggregatedHolding` wrapper fed through the existing compute
pipeline; the mapping-ratio gate stays computed on RAW per-lot holdings. Files:
`backend/app/services/thirteenf_ownership_changes.py`.

## Context a reviewer cannot see from the diff alone

- **The F3 root cause is narrower than it looks.** The crash only ever fired in
  the *unavailable (no-prior)* branch, which builds one row per holding keyed by
  `_holding_key` → `stock:<id>`. The *normal* `_matched_pairs` path does NOT
  crash: `_pair_key` only returns a stock key when BOTH current and previous have
  `stock_id`; unmatched holdings fall back to distinct `cusip:<cusip>` keys.
  Aggregation is nonetheless applied to BOTH paths (and previous-quarter
  holdings) — the reviewer should decide whether that broader behavior change is
  correct or overreach.
- **The core semantic bet: SUM, not drop.** A manager's stake in a security is
  treated as the sum of its 13F infotable rows for that security (multiple CUSIPs
  / lots). The alternative (keep one representative, drop the rest) would
  undercount. Whether summing can ever DOUBLE-COUNT — e.g. combination-report
  sub-managers reporting the same position redundantly — is the key thing to
  pressure-test. NOTE this interacts with **T3** (combination-report attribution,
  not in this PR): today combination filers' holdings are mostly excluded from
  `direct`, so most reach compute only via the unavailable branch. The
  aggregation must stay correct after T3 makes more holdings `direct`.
- **The `_AggregatedHolding` wrapper duck-types `Holding13F`.** It is only fed
  through the compute helpers, never persisted. A single attribute the wrapper
  fails to expose would be an `AttributeError` on an untested code path, not a
  test failure. The helpers that read holding attributes: `_shares`,
  `_value_usd`, `_stock_key`, `_cusip_key`, `_holding_key`, `_pair_key`,
  `_normalized_put_call`, `_position_type`, `_build_change_row`,
  `_classify_change`. (`_linked_common_mapping_ratio` runs on RAW holdings.)
- **Test isolation:** the dev DB `valuepilot` holds real data and pytest cannot
  run against it. Use the isolated DB:
  ```
  TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
  ```
- **Already verified by the author** (re-confirm, don't trust): full backend
  suite **1074 passed**; both F3 tests go genuinely red on the real
  `uq_ownership_changes_manager_quarter_security_position` without the fix; the
  new job ran all six real quarters with **0 failures** and materialized manager
  4002 for the first time (previously 100% skipped by the crash),
  ownership_changes 18,260 → 20,314. No schema change / migration.

Three prompts for three different agents. Run in parallel; collect findings in
`2026-07-08_13f-t2-ownership-changes-orchestration-review-results.md`.

---

## Prompt 1 — Aggregation correctness (the critical angle)

```
You are reviewing a change to a financial read-model compute that AGGREGATES
13F holdings sharing an effective key (security_key, ssh_prnamt_type,
position_type) into one position by SUMMING shares and value, via a read-only
_AggregatedHolding wrapper fed through the existing pipeline. Assume the data is
real SEC 13F filings; wrong sums mislead investors and wrong keys crash inserts.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t2-ownership-changes-orchestration`.
Read first:
  - backend/app/services/thirteenf_ownership_changes.py — the WHOLE module:
    compute_ownership_changes_for_manager_quarter, _aggregate_holdings,
    _merge_holdings, _AggregatedHolding, _matched_pairs, _pair_key, _stock_key,
    _cusip_key, _holding_key, _build_change_row, _classify_change, _shares,
    _value_usd, _linked_common_mapping_ratio.
  - The model: backend/app/models/institutions.py (Holding13F columns + the
    uq_ownership_changes_manager_quarter_security_position constraint).
  - The "Context" section of this review-prompts doc.

Probe, with a concrete input for each real finding:
  1. Attribute coverage: list EVERY Holding13F attribute the compute helpers
     read on a holding, and confirm _AggregatedHolding exposes each. Any gap is
     an AttributeError on a real path (e.g. a put/call position, an unlinked
     cusip position). Name the missing attribute and the triggering holding.
  2. Double-counting: can summing ever count the same shares twice? Construct a
     case (e.g. the same CUSIP appearing twice in one infotable; a combination
     report listing one position under two included managers). Is SUM correct
     there, or should it dedupe-identical vs sum-distinct?
  3. Classification after aggregation: _classify_change compares aggregated
     current vs aggregated previous. Does aggregating BOTH sides preserve
     increased/reduced/new/exited and share_delta/value_delta correctly when a
     stock is held under two CUSIPs in one quarter and one CUSIP in the other?
  4. The mapping-ratio gate runs on RAW holdings but rows build on aggregated —
     can aggregation change branch selection (unavailable vs normal) or the row
     set in a way that loses or duplicates a position?
  5. Representative selection (max by value, tie by id): current_holding_id /
     current_cusip / parse_run_id point to ONE lot. Is that misleading for
     provenance, and does any consumer assume 1:1 holding↔change?
  6. Residual dup-key: after aggregation, can ANY (matched, straggler, put/call,
     unlinked-cusip) path still produce two rows with the same unique key?

Output: file:line, concrete input, wrong result. If the aggregation is sound,
justify why sum-not-drop is correct and why no key collides. No style notes.
```

---

## Prompt 2 — Orchestration, transactions & failure semantics

```
You are reviewing new job orchestration in a Postgres-backed 13F pipeline. A new
`compute_ownership_changes` stage runs inside `quarterly_pipeline` and loops the
quarter's active managers, each under a `session.begin_nested()` SAVEPOINT,
calling an idempotent per-manager service that does DELETE + flush + insert.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t2-ownership-changes-orchestration`.
Read first:
  - backend/app/services/thirteenf_admin_dashboard.py — the new
    `compute_ownership_changes` branch in _execute_job, its entry in
    _JOB_LOCK_BUILDERS, the new stage in the quarterly_pipeline block, and
    _execute_pipeline_stage_job (how stages commit / fail).
  - backend/app/services/thirteenf_job_worker.py (job transaction boundary).
  - backend/app/services/thirteenf_ownership_changes.py
    (compute_ownership_changes_for_manager_quarter — the DELETE + flush).

Probe:
  1. Savepoint correctness: the per-manager `with session.begin_nested()` wraps
     a service that itself calls session.flush() and a bulk DELETE. Does a
     manager-level exception roll back ONLY that manager, leaving prior managers'
     work intact, given the stage's outer transaction and the worker's final
     commit? Any way a failure corrupts a sibling or the whole stage?
  2. Failure-visibility rule: the summary status is
     `"failed" if failures and not status_breakdown else "succeeded"` — i.e. any
     success masks partial failures (they live only in summary.failures[:50]).
     Is that the right contract? Should partial per-manager failures surface as
     the pipeline's partial_success, or trigger smart-retry? Is truncating
     failures at 50 with a failure_count acceptable?
  3. Manager selection: `Filing13F` distinct manager_id where report_quarter ==
     quarter AND form_type in HR_FORM_TYPES AND is_active_for_manager_period.
     Does this exactly match the managers the service can compute for? Can it
     include an NT-only or non-active-parse manager, or miss one?
  4. Idempotency & ordering: re-running the stage (or standalone job) — does it
     converge? Is stage placement (after quality_check, before scoring) right —
     does scoring read ownership_changes (it shouldn't), and is there any data
     dependency that wants changes computed before/after scoring?
  5. Locking: `compute_ownership_changes:{quarter}` — does the pipeline-stage
     lock and the standalone-job lock share this key so they can't run
     concurrently for one quarter? Any interaction with per-accession reparse
     jobs that also touch ownership_changes?

Output: file:line, concrete scenario, wrong/fragile outcome. If sound, justify
the transaction boundary and the failure contract.
```

---

## Prompt 3 — Altitude & test quality

```
You are a staff engineer judging depth and test rigor. The change adds an
in-memory aggregation wrapper at compute time and wires a new pipeline stage.
The author already caught (in self-review) that F3 only crashed in one branch
and that a "sum" semantic was chosen over "drop".

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t2-ownership-changes-orchestration`.
Read first:
  - backend/app/services/thirteenf_ownership_changes.py
  - backend/tests/unit/test_13f_ownership_changes_compute.py (F3 tests)
  - backend/tests/unit/test_13f_ownership_changes_orchestration.py (new)
  - backend/tests/unit/test_oracles_lens_score_job.py and
    test_13f_admin_dashboard.py (the 3 updated pipeline-stage assertions)
  - The "Context" section of this review-prompts doc for the isolated-DB
    test recipe.

Judge:
  1. Layer: should positions be canonicalized once at INGEST (so every consumer
     sees one row per security) instead of re-aggregated at compute time? Is the
     compute-time wrapper the right depth or a localized band-aid? What would the
     ingest-layer version cost/risk?
  2. Test gaps — name each missing case with the input it needs:
     - aggregation in the MATCHED path (increased/reduced), not just new/no-prior;
     - put/call positions (position_type separates them — does aggregation keep
       PUT vs CALL vs common distinct?);
     - previous quarter ALSO holding the security under two CUSIPs;
     - the per-manager failure-isolation path (a manager that raises mid-stage);
     - the stage running INSIDE quarterly_pipeline end-to-end (tests call
       execute_job_payload for the sub-job directly, not the full pipeline);
     - caveat handling when merged holdings carry different caveats.
  3. Re-run the F3 red/green proof yourself on valuepilot_test: stash the
     aggregation and confirm both F3 tests fail on the real uq_ constraint;
     restore and confirm green. Report if either is not genuinely red.
  4. Assertion strength: do the tests pin summed shares/value AND the single-row
     outcome, or just "no crash"?

Output: a depth verdict (band-aid / acceptable-scoped-fix / correct-
generalization) with reasoning, plus the concrete tests to add. Do not rewrite
the code; judge it.
```
