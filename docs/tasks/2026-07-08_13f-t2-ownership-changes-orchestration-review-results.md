# Review results — T2 ownership_changes orchestration + aggregation

Date: 2026-07-08

Scope reviewed:
- `backend/app/services/thirteenf_ownership_changes.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/thirteenf_job_worker.py`
- `backend/app/models/institutions.py`
- `backend/tests/unit/test_13f_ownership_changes_compute.py`
- `backend/tests/unit/test_13f_ownership_changes_orchestration.py`
- `backend/tests/unit/test_oracles_lens_score_job.py`
- `backend/tests/unit/test_13f_admin_dashboard.py`

## Findings

### [P1] Aggregating before CUSIP fallback breaks stock-mapping transition cases with multiple CUSIPs

File: `backend/app/services/thirteenf_ownership_changes.py:111`

`current_holdings` is aggregated by `_holding_key` before `_matched_pairs` gets a chance to do its CUSIP fallback. That is fine when both sides are stock-linked, but it breaks the existing PRD §7.4 behavior for holdings that gained/lost stock mapping between quarters and have multiple CUSIPs for the same eventual stock.

Concrete failing input:
- Previous quarter has two direct holdings, both unlinked: `cusip A`, 100 shares, `stock_id=NULL`; `cusip B`, 150 shares, `stock_id=NULL`.
- Current quarter has the same two CUSIPs now mapped to one stock: `cusip A`, 110 shares, `stock_id=S`; `cusip B`, 160 shares, `stock_id=S`.
- `_aggregate_holdings(current)` collapses A+B into one `_AggregatedHolding` keyed as `stock:S` with one representative CUSIP.
- `_matched_pairs` then can only match that aggregate to one previous CUSIP and treats the other previous CUSIP as an exit.

Wrong result: instead of one coherent stock-level increase from 250 to 270, or two CUSIP fallback increases, the output contains a false `exited_position` for one CUSIP and an inflated `increased` row for the representative CUSIP. The symmetric case also fails: previous linked A+B aggregated to one stock row, current unlinked A+B split by CUSIP, yielding a false `new_position`/misstated delta.

### [P1] Aggregated representative CUSIP can misclassify a real share increase/reduction as `cusip_changed`

File: `backend/app/services/thirteenf_ownership_changes.py:333`

After aggregation, `current.cusip` and `previous.cusip` are representative-lot CUSIPs, not the full set of CUSIPs in the position. `_classify_change` checks representative CUSIP inequality before comparing aggregated shares, so a change in the largest-value representative can override the real position-level share classification.

Concrete failing input:
- Previous quarter linked stock `S`: CUSIP A = 100 shares / $1,000, CUSIP B = 50 shares / $500. Aggregated previous representative is A, total shares 150.
- Current quarter linked stock `S`: CUSIP A = 100 shares / $1,000, CUSIP B = 70 shares / $2,000. Aggregated current representative is B, total shares 170.

Wrong result: `_classify_change` returns `cusip_changed` because representative CUSIPs differ (`B != A`), even though the position increased from 150 to 170 and both CUSIPs are present in both quarters. This is a direct result of using representative identity as if it were position identity.

### [P2] Aggregated `portfolio_weight_pct` is taken from one lot instead of summed

File: `backend/app/services/thirteenf_ownership_changes.py:291`

`_merge_holdings` correctly sums shares and value, but it copies `portfolio_weight_pct` from the representative holding. `_build_change_row` persists that field into `current_portfolio_weight_pct` / `previous_portfolio_weight_pct`, and the manager changes API returns it to clients.

Concrete failing input:
- Current quarter has two direct lots for the same stock/key: lot A `portfolio_weight_pct=0.01`; lot B `portfolio_weight_pct=0.02`.
- They aggregate to one position with summed shares/value.

Wrong result: the row's `current_portfolio_weight_pct` is either `0.01` or `0.02` depending on representative selection, not the position's true `0.03`.

### [P1] Per-manager failures are reported as `succeeded` when any manager succeeds

File: `backend/app/services/thirteenf_admin_dashboard.py:3145`

The new job catches per-manager exceptions and records `failure_count`, but returns `"succeeded"` whenever `status_breakdown` is non-empty. A quarter with one successful manager and one failed manager is therefore a succeeded stage. In `quarterly_pipeline`, that means the new stage does not make the pipeline `partial_success`.

Concrete failing input:
- Quarter has active managers M1 and M2.
- M1 computes successfully and inserts rows.
- M2 raises an `IntegrityError` or `AttributeError` inside its savepoint.

Wrong result: summary includes `failure_count=1`, but stage status is `succeeded`; the pipeline can finish `succeeded`; smart retry / operator alerting keyed off job status will not see a degraded stage. The savepoint isolation itself is sound: M2 rolls back without corrupting M1. The problem is failure visibility.

## Correctness Notes

Attribute coverage is complete for current helper usage. The helpers read these holding attributes: `id`, `stock_id`, `cusip`, `ssh_prnamt`, `shares`, `value_usd`, `ssh_prnamt_type`, `put_call`, `parse_run_id`, `portfolio_weight_pct`, and `holding_attribution_status`. `_AggregatedHolding` exposes each of them.

The raw mapping-ratio gate intentionally runs before aggregation. That preserves threshold behavior for linked/unlinked per-lot holdings, but it also means row construction can have different grouping semantics than readiness gating.

The per-manager `begin_nested()` transaction boundary is correct: `DELETE + flush + insert` is inside the savepoint, so a manager-level exception rolls back that manager's delete/insert while prior managers' work remains pending in the outer stage transaction. `_execute_pipeline_stage_job` commits survivors as a unit after `_execute_job` returns.

The lock key for standalone and pipeline-stage ownership-change jobs is shared (`compute_ownership_changes:{quarter}`), so two compute jobs for the same quarter should not run concurrently through the job system. It does not block concurrent quarter ingestion or accession reparse jobs for the same quarter; that is residual operational risk, not directly introduced by the aggregation logic.

## Test Review

Red/green proof:
- The branch has no uncommitted source diff, so `git stash` could not stash the aggregation. I temporarily patched `thirteenf_ownership_changes.py` back to the no-aggregation behavior, ran the two F3 tests, then restored the file.
- Without aggregation, `test_compute_aggregates_two_cusips_one_stock_no_prior` failed on `uq_ownership_changes_manager_quarter_security_position`.
- Without aggregation, `test_compute_aggregates_two_cusips_one_stock_new_position` failed, but not on the DB constraint: it produced two rows for the target `stock_id`, and the assertion `len(dup_rows) == 1` failed. So the "both F3 tests fail on the real uq constraint" claim is not accurate.
- Restored aggregation and reran both tests: 2 passed.

Assertion strength:
- The two new F3 tests pin both single-row output and summed shares/value. They are stronger than "no crash" tests.
- The orchestration tests prove the standalone job materializes rows and the lock key is quarter-scoped, but they do not cover per-manager failure isolation or partial-failure status.

Concrete tests to add:
- Matched path with aggregation on both sides: previous A+B linked to stock S, current A+B linked to stock S, assert `increased`/`reduced` uses aggregated shares and does not become `cusip_changed` due to representative CUSIP.
- Mapping transition with multiple CUSIPs: previous A+B unlinked, current A+B linked to one stock S; assert no false exit/new rows and correct deltas.
- Portfolio weight aggregation: two lots with weights 1% and 2% produce an ownership-change weight of 3%.
- Put/call aggregation: two PUT lots for one stock aggregate together, while PUT/CALL/common remain separate.
- Previous quarter also duplicated: previous and current both have two CUSIPs resolving to one stock, with a reduced/increased classification.
- Per-manager failure isolation: force one manager's compute to raise and assert prior manager rows survive, `failure_count` increments, and job status is partial/failed per the intended contract.
- Full quarterly pipeline integration: not only direct `execute_job_payload("compute_ownership_changes")`, but `quarterly_pipeline` with the stage actually running.
- Caveat/provenance behavior for merged holdings with different representative CUSIPs and caveat-relevant fields, so the representative fields are explicit product decisions.

## Design Verdict

Verdict: acceptable-scoped fix for the F3 crash shape, but not a correct generalization yet.

Compute-time aggregation is the right low-blast-radius line for this P1 stabilization ticket. Canonicalizing holdings at ingest would affect every consumer, parser fixture, holding detail view, CUSIP enrichment path, and audit/provenance semantics; that belongs in a larger design because raw infotable rows are themselves audit evidence.

The wrapper approach is a pragmatic bridge, but it needs clearer position-level semantics: aggregate numeric position fields, keep lot provenance honest, and avoid using representative CUSIP as the whole position identity. Long term, a first-class read-model layer for "positions" derived from raw holdings would be cleaner than repeatedly duck-typing `Holding13F`.

## PO / author disposition (2026-07-08, after independent verification)

Every finding reproduced against the code before acting. The review was correct
and caught two regressions I introduced.

- **[P1] #1 mapping-transition break & [P1] #2 representative-CUSIP misclassification
  — ROOT-CAUSE FIXED by scoping aggregation.** Both stem from aggregating the
  *normal* `_matched_pairs` path, which — as the reviewer's own red/green proof
  shows — never actually crashed (it produced two distinct-CUSIP rows, not a
  `uq_` violation). So aggregating it was overreach. Fix: aggregate **only in the
  unavailable branch** (the sole path that keys rows per-holding by
  `_holding_key` and thus collides); `_compute_rows`/`_matched_pairs`/
  `_classify_change` now see RAW holdings, restoring the PRD §7.4 CUSIP-fallback.
  This eliminates #1 and #2 entirely. New regression test
  `test_compute_mapping_transition_multiple_cusips_no_false_exit` (prev A+B
  unlinked → curr A+B linked to one stock) asserts `[increased, increased]`, no
  false exit.
- **[P2] #3 portfolio_weight — FIXED.** `_merge_holdings` now sums
  `portfolio_weight_pct` across lots; `test_..._no_prior` asserts `0.1+0.1=0.2`.
  (Field is NULL in MVP2 today, so no live impact, but now correct.)
- **[P1] #4 failure visibility — FIXED.** Stage status is now `succeeded` (no
  failures) / `partial_success` (some succeed, some fail) / `failed` (all fail),
  so a degraded stage propagates to the pipeline. New test
  `test_compute_ownership_changes_isolates_per_manager_failure` forces one
  manager to raise and asserts the sibling's rows survive, `failure_count=1`,
  status `partial_success`.
- **Red/green correction accepted.** The reviewer is right that the earlier
  "both F3 tests fail on the real uq constraint" claim was inaccurate — only the
  no-prior (unavailable-branch) test crashed on the constraint; the normal-path
  test failed on a row-count assertion. That normal-path test is REMOVED (it
  tested behavior now reverted).
- **Coverage — added** the mapping-transition, portfolio-weight, and
  failure-isolation tests. Deferred (see below): matched-path per-lot
  fragmentation, put/call aggregation, full-pipeline-integration — these belong
  to the positions read-model generalization.
- **Design verdict — AGREED.** Compute-time aggregation is the right scoped line;
  a first-class positions read-model derived from raw holdings is the correct
  long-term generalization → backlog.

Result after adoption: compute + orchestration suites **18 passed**; full backend
**1075 passed**; real-data recompute across 6 quarters **0 failures**, manager
4002 still fully materialized (2055 rows), ownership_changes = 20,315.

## Verification

Commands run against the isolated test DB:

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q tests/unit/test_13f_ownership_changes_compute.py tests/unit/test_13f_ownership_changes_orchestration.py tests/unit/test_oracles_lens_score_job.py
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
```

Results:
- T2-related targeted suite: 23 passed.
- Full backend suite: 1074 passed, 3 warnings.
