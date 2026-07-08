# Review results — T1 13F restatement activation fix

Date: 2026-07-08

Scope reviewed:
- `backend/app/services/thirteenf_holdings_ingest.py`
- `backend/app/services/thirteenf_admin_dashboard.py`
- `backend/app/services/thirteenf_holdings_query.py`
- `backend/tests/unit/test_13f_amendment_policy.py`
- `docs/prd/13f_automation_and_resilience_prd.md`

## Findings

### [P1] Multi-RESTATEMENT winner uses `filed_at/id`, but the PRD requires `accepted_at` and review on ties

File: `backend/app/services/thirteenf_holdings_ingest.py:124`

The latest-wins guard chooses a later parsed restatement by `(filed_at, id)`. That matches the task doc's local AC, but it conflicts with PRD §7.3 / amendment policy: multi-RESTATEMENT ordering is by latest `accepted_at`; equal `accepted_at` must not auto-switch and should be marked `amendments_pending + amendment_sort_warning=true`.

Concrete failing state:
- Same `(manager_id, quarter_end_date)`.
- `R1`: RESTATEMENT, `parse_status='succeeded'`, `filed_at=2024-05-16`, `accepted_at=2024-05-16T10:00Z`, `id=100`.
- `R2`: RESTATEMENT, `parse_status='succeeded'`, `filed_at=2024-05-16`, `accepted_at=2024-05-16T11:00Z`, `id=99`.
- Calling `reconcile_restatement_activation(session, R1)` finds no later restatement because `R2.id < R1.id`, then activates `R1`.

Wrong outcome: the older accepted restatement becomes active. A same-`accepted_at` tie with different ids is also auto-resolved by id, contrary to the PRD's "do not auto cut active; require admin review" rule. This is also inconsistent with the original-filing policy in `thirteenf_filing_detail.py`, which sorts originals by `accepted_at`.

### [P1] The guard is not concurrency-safe across accession-level amendment jobs

File: `backend/app/services/thirteenf_holdings_ingest.py:116`

The "later restatement exists" check is a normal SELECT, and the subsequent demote/activate query is another statement. The job lock model serializes one `ingest_holdings:{quarter}` job, but `reprocess_amendment` and `reparse_accession` are locked per accession, so two workers can process different restatements for the same manager/period concurrently.

Concrete interleaving:
- `R1` older RESTATEMENT and `R2` newer RESTATEMENT for the same period.
- Worker A starts `R1`, runs the guard before `R2` has committed `parse_status='succeeded'`, so it decides `R1` may activate.
- Worker B commits `R2` active.
- Worker A then runs the superseded-active SELECT under READ COMMITTED, sees `R2` active, demotes it, flushes, activates `R1`, and commits.

Wrong outcome: the older restatement can silently finish active. A slightly different interleaving may instead hit `uq_active_filing_per_manager_period`, but the silent wrong-winner case is possible because the decision is not protected by a row lock/advisory lock or rechecked immediately before activation.

## Correctness Notes

No finding on the new `session.flush()` inside `_do_ingest_holdings`' savepoint. The function already issues SELECTs that trigger autoflush, and the explicit flush only emits the demotions before promotion. If it fails, the existing savepoint rollback path still rolls back the in-progress parse. The pattern is also consistent with existing non-deferrable-index handling in `thirteenf_controlled_reparse.py`.

`filed_at` is not nullable in the ORM (`Filing13F.filed_at`, `nullable=False`), so the NULL filed-at branch in the prompt is not a currently reachable state unless data bypasses the model/schema.

For non-concurrent Phase 5 execution, the new guard converges for the production incident shape: earlier restatements no-op when a later parsed restatement exists, and the later restatement remains or becomes active. A latest failed restatement is ignored by the guard, so an earlier succeeded restatement can remain the active source.

## Test Review

Red/green proof:
- Stashed only `backend/app/services/thirteenf_holdings_ingest.py`, leaving the new tests in place.
- Ran the two new tests against `valuepilot_test`; both failed.
- `test_reconcile_restatement_latest_wins_regardless_of_call_order` failed because the old function returned `True` and stole activation.
- `test_reconcile_restatement_demote_then_activate_is_constraint_safe` failed on `uq_active_filing_per_manager_period`.
- Restored the source change, then temporarily removed only the `session.flush()` block. The constraint-safe test failed again on `uq_active_filing_per_manager_period`.

Coverage gaps to add:
- `accepted_at` ordering: two RESTATEMENTs with the same `filed_at` but different `accepted_at`, with ids intentionally reversed from accepted order. Expected winner: latest `accepted_at`.
- `accepted_at` tie: two parsed RESTATEMENTs with identical `accepted_at`. Expected behavior per PRD: no auto activation; set pending/sort warning or defer to admin policy.
- 3+ restatements: `R1`, `R2`, `R3` all succeeded; call reconcile on `R1`, `R2`, `R3` in non-sorted order and assert only `R3` is active.
- Later restatement failed: `R1` succeeded, `R2` later but `parse_status='failed'`; assert `R1` can remain/become active and `R2` does not block it.
- Ingest-path coverage: exercise `_do_ingest_holdings` / `ingest_holdings_for_filing` with multiple restatements, not only direct calls to `reconcile_restatement_activation`.
- Concurrency coverage: two sessions processing different restatement accessions for one period, or a lower-level policy test that proves the function locks/rechecks before activation.

The two added tests do pin winner identity and loser demotion for their constructed cases; they are not mere "no crash" tests. The `constraint_safe` fixture is realistic enough for the UOW hazard because id ordering is not a domain ordering guarantee, and the active original with higher id reproduces the exact partial-index failure mode.

## Design Verdict

Verdict: acceptable-scoped crash fix, not the correct generalization.

The diff picks a reasonable narrow line for the production P0 crash: keep Phase 5's loop intact, make earlier restatements no-op when a later parsed restatement is present, and explicitly flush demotions before promotion. That is a pragmatic fix for the known incident and matches existing handling of non-deferrable partial unique indexes.

It does not make "which filing is active for a period" a single authority. Active selection still lives in `_do_ingest_holdings`, Phase 4's solo-original heuristic, Phase 5's restatement loop, and `thirteenf_filing_detail.apply_amendment_policy`. The follow-up should create one `select_active_filing(manager_id, quarter_end_date)` / `apply_active_filing_policy(...)` authority covering originals, NT, amendments, parse status, `accepted_at` ordering, tie handling, and concurrency locking. That policy should either lock all filings in the manager-period group with `FOR UPDATE` or take an advisory lock keyed by `(manager_id, quarter_end_date)` before deciding and flipping active state.

## PO / author disposition (2026-07-08, after independent verification)

Every finding was reproduced against the code and real data before deciding.

- **[P1] accepted_at ordering — ADOPTED (key), tie rule DEFERRED.** Confirmed
  `apply_amendment_policy` (`thirteenf_filing_detail.py:413`) ranks by
  `(accepted_at or min, accession_no)` and my `filed_at/id` key was inconsistent.
  Changed the guard to rank by the SAME key. **However**, the reviewer's
  "equal accepted_at → deactivate all + warn" rule cannot be applied yet:
  `accepted_at IS NULL` on all 373 real filings, so every restatement pair is a
  false tie and deactivating on it would REGRESS the T1 incident fix (latest
  restatement would never win). accession_no keeps a deterministic total order
  today. accepted_at population + tie handling → **T1-FU**.
- **[P1] concurrency — CONFIRMED, DEFERRED.** Verified `reparse_accession` /
  `reprocess_amendment` lock per-accession while `ingest_holdings` locks per
  quarter (`_JOB_LOCK_BUILDERS`). The race is real and **pre-existing** (T1 did
  not introduce it). (manager, period) locking → **T1-FU**.
- **accepted_at unpopulated** surfaced as its own root finding → T1-FU / backlog.
- **Coverage gaps — ADOPTED the in-scope ones.** Added: accepted_at-over-accession
  ordering, 3+ restatements any call order, later-failed restatement ignored,
  and an **ingest-path** multi-restatement test (out-of-order via
  `ingest_holdings_for_filing`, exercising the savepoint caller — closing the
  "tests only call reconcile directly" gap). Concurrency + accepted_at-tie tests
  → T1-FU.
- **Design verdict — AGREED.** T1 stays the scoped crash fix; single-authority
  `select_active_filing()` + locking is `docs/tasks/2026-07-08_13f-t1fu-active-filing-authority.md`.
- **Correctness notes — agreed** (flush safe; filed_at not nullable).

Result after adoption: `tests/unit/test_13f_amendment_policy.py` **16 passed**;
full backend suite **1069 passed**; real dev data untouched.

## Verification

Commands run against the isolated test DB:

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q tests/unit/test_13f_amendment_policy.py
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
```

Results:
- `tests/unit/test_13f_amendment_policy.py`: 12 passed.
- Full backend suite: 1065 passed, 3 warnings.
