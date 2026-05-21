# Review result — CUSIP enrichment status-filter fix + run-to-completion (PR #84)

Date: 2026-05-21
Reviewer: independent agent pass
Branch reviewed: `claude/cusip-link-rate-enrichment-fix`
Baseline: `git diff main...HEAD`
Prompt: `docs/tasks/2026-05-21_cusip-link-rate-enrichment-fix-review-prompts.md`

---

## Overall verdict

**APPROVE** — no blocker found.

The broadened filter is correct: `unresolved` holdings have never had OpenFIGI
consulted (guarded by the combined "in status set AND CUSIP not in
cusip_ticker_map" predicate), `needs_review` correctly stays excluded, and the
NOT-IN subquery is NULL-safe. The loop has a real termination argument: every
CUSIP touched — including no-match ("low" confidence, `ticker=None`) — gets a
`cusip_ticker_map` row on the first pass, removing it from the enrichable pool
permanently; combined with the hard cap and no-progress guard there is no
infinite-spin path. Downstream consumers of the changed result dict shape are
unaffected.

Two advisories recorded below (no blockers):
- **Advisory D/B**: `bootstrap_stocks_from_cusip_map` + `backfill_stock_ids`
  are called outside the `try/finally` in `enrich_all_unmapped_holdings`; an
  unexpected exception inside the loop leaves them unexecuted for that run
  (partial CUSIP mappings are still committed and a re-run resumes correctly).
- **Advisory E**: test coverage gaps — no test for the no-match CUSIP
  termination path, all-invalid-batch progress, max-batch cap, or no-progress
  guard.

---

## Prompt checklist

### A. Status-filter correctness

**Q1 — PASS with advisory comment.**

`enrich_unmapped_holdings()` now queries
`cusip_mapping_status IN ('pending_mapping', 'unresolved')` combined with
`NOT IN cusip_ticker_map` (line 199–201). The status semantics:

- `pending_mapping` — freshly ingested holdings, OpenFIGI never consulted.
- `unresolved` — set by `_apply_mappings_to_holdings()` when it finds no
  active `cusip_ticker_map` row for the holding's CUSIP (line 424–425) **or**
  when the active map row has a NULL ticker (line 434–436). In both cases
  the combined "status in set AND CUSIP not in map" predicate correctly limits
  the enrichable pool to CUSIPs that genuinely lack a mapping row.
- `needs_review` — set when a `review_needed:*` mapping exists (line 429–432);
  these hold ambiguous-result data that belong in the human queue. Excluding
  them is correct — re-running OpenFIGI would just re-flag them.

Advisory: the code comment at line 190–195 says `unresolved` means "OpenFIGI
was never consulted". That is true of the prod backlog state diagnosed in the
task doc (all 13,981 holdings were set by `_apply_mappings_to_holdings` before
any OpenFIGI run), but is not universally true of the status value. A future
no-match run creates a `low/ticker=None` row; on the next
`_apply_mappings_to_holdings` pass the holding is set to `unresolved` again
(line 434–436) because the map row exists but has no ticker. The combined
predicate still correctly excludes those CUSIPs (their CUSIP IS in the map),
but the comment would mislead a reader trying to understand what `unresolved`
means globally.

Evidence: `cusip_enrichment.py:189–203`, `cusip_enrichment.py:424–436`.

**Q2 — PASS.**

The `NOT IN` subquery is:
```python
mapped_cusips = db.query(CusipTickerMap.cusip).filter(CusipTickerMap.cusip.isnot(None))
```
The explicit `IS NOT NULL` guard on the subquery prevents the
`NULL-in-NOT-IN → always-false` trap. `Holding13F.cusip.isnot(None)` ensures
the outer predicate also excludes NULL-CUSIP holdings.

`_count_enrichable_holdings()` (lines 263–273) uses **identical** three-filter
predicates — same status set, same non-null CUSIP, same NOT-IN subquery — just
`.count()` instead of `.limit().all()`. The loop's "before/after" comparison
is therefore coherent with the batch query.

Evidence: `cusip_enrichment.py:196–203`, `cusip_enrichment.py:263–273`.

---

### B. Loop termination

**Q3 — PASS.**

Termination argument (holding-count pool strictly shrinks per batch):

1. **Valid CUSIP with an OpenFIGI match** (`confidence='high'`, ticker set):
   `upsert_cusip_mapping()` creates a `cusip_ticker_map` row (lines 100–118).
   The CUSIP is now in the subquery; holding leaves the enrichable pool via
   `NOT IN` on the next count.

2. **Valid CUSIP with no OpenFIGI match** (`evaluate_openfigi_matches([])` →
   `confidence='low', ticker=None`, lines 136–137):
   `upsert_cusip_mapping()` still creates a `cusip_ticker_map` row with
   `ticker=NULL`. The CUSIP is now in the subquery (the subquery filters
   `CusipTickerMap.cusip IS NOT NULL`, meaning the **CUSIP column** not the
   ticker column — the CUSIP string itself is always non-NULL). On the next
   pass `_apply_mappings_to_holdings()` re-sets the holding to `unresolved`
   (ticker is None → line 434–436), but the CUSIP IS excluded by the NOT-IN
   predicate. The holding is gone from the pool — no infinite retry.

3. **Invalid CUSIP** (`is_valid_cusip()` returns False):
   Status set to `invalid_cusip` and committed mid-batch (lines 214–220).
   `invalid_cusip` is not in `['pending_mapping', 'unresolved']`, so the
   holding is excluded from the count. No `cusip_ticker_map` row needed.

In all three cases, CUSIPs processed in batch N cannot re-appear in batch N+1.
Pool size is monotonically non-increasing across batches.

Evidence: `cusip_enrichment.py:136–137`, `cusip_enrichment.py:196–201`,
`cusip_enrichment.py:212–224`, `cusip_enrichment.py:230–260`,
`cusip_enrichment.py:263–273`, `cusip_enrichment.py:297–309`.

**Q4 — PASS.**

`max_batches=300` is a hard cap: the `while batches < max_batches` condition
exits the loop regardless of remaining work (lines 297, 302).

No-progress guard (lines 303–309): if `_count_enrichable_holdings(db) >= before`
after a batch (the pool did not shrink), the loop breaks with a warning. This
covers pathological cases such as advisory-lock contention causing every
`upsert_cusip_mapping()` in the batch to throw and roll back.

All-invalid-CUSIP batch: holdings are set to `invalid_cusip` and committed
(lines 214–220) before OpenFIGI is called. `mapped_count` returns 0 but the
count check still passes: `_count_enrichable_holdings()` after the batch is
**less than** `before` (invalid_cusip holdings left the set) → `< before` →
no false stall trigger.

Evidence: `cusip_enrichment.py:212–224`, `cusip_enrichment.py:297–309`.

---

### C. No regression for other callers

**Q5 — PASS.**

`enrich_cusips_from_openfigi()` (line 324–330) and `enrich_from_dataroma()`
(line 333–339) both delegate to `enrich_unmapped_holdings()`. They now benefit
from the broadened status filter and the new NOT-IN exclusion (already-mapped
CUSIPs are skipped — an idempotency improvement). `_apply_mappings_to_holdings()`
is called at the end of each batch, so holdings continue to be linked against
any existing mappings.

The `enrich_metadata` job at `thirteenf_admin_dashboard.py:3372–3391` still
calls `enrich_cusips_from_openfigi()` → single-batch path, unchanged behavior.

The CLI `enrich_cusip` command (`cli/edgar.py:385–394`) also calls
`enrich_cusips_from_openfigi()` — single-batch, unchanged.

Evidence: `cusip_enrichment.py:324–339`,
`thirteenf_admin_dashboard.py:3372–3391`, `cli/edgar.py:385–394`.

**Q6 — PASS.**

Old `enrich_cusip` result: `{"mappings_created": int, "status": "succeeded"}`.
New result: `{"mappings_created": int, "batches_run": int, "new_stocks": int,
"holdings_linked": int, "holdings_still_unmapped": int, "status": "succeeded"}`.

Consumer audit:
- **Job worker** (`thirteenf_job_worker.py:308–317`): pops `status`, stores the
  rest as `summary_json` (opaque `JSONB` column). No specific key access.
- **Notifications** (`thirteenf_job_worker.py:333–340`): passes `job` object,
  not the raw dict. Unaffected.
- **Frontend jobs page** (`admin/13f/jobs/page.tsx:949–1124`): renders
  `summary_json` via `formatJson()` (generic). Only checks `pipeline_error` and
  `stages` keys — neither present in the `enrich_cusip` result. No rigid field
  access.
- `enrich_metadata` job result (`thirteenf_admin_dashboard.py:3384–3388`): still
  emits `cusip_mappings` and `mappings_created` — unaffected.

Shape change is safe.

Evidence: `thirteenf_job_worker.py:308–317`, `thirteenf_job_worker.py:333–340`,
`admin/13f/jobs/page.tsx:949–1125`, `thirteenf_admin_dashboard.py:3384–3391`.

---

### D. Transactions and client lifecycle

**Q7 — PASS.**

Each `enrich_unmapped_holdings()` call issues up to two commits:
1. Invalid CUSIPs: `db.commit()` at line 220 (only when `invalid_count > 0`).
2. `_apply_mappings_to_holdings()`: `db.commit()` at line 456 (unconditional).

The `_count_enrichable_holdings()` probe at `enrich_all_unmapped_holdings:303`
runs after both commits, so the no-progress guard sees durable state. The loop
probe at line 298 (`before = _count_enrichable_holdings()`) runs before the
next batch starts, also seeing committed state. Partial progress is durable
across job lease expiry or process restart: a new `enrich_cusip` job run resumes
from the remaining un-mapped CUSIPs.

Evidence: `cusip_enrichment.py:219–224`, `cusip_enrichment.py:252–256`,
`cusip_enrichment.py:456`, `cusip_enrichment.py:296–303`.

**Q8 — PASS.**

`enrich_all_unmapped_holdings()` (lines 291–312):
```python
owns_client = client is None
if owns_client:
    client = OpenFigiClient()
...
try:
    while batches < max_batches:
        ...
        total_mapped += enrich_unmapped_holdings(db, client=client, ...)
        ...
finally:
    if owns_client:
        client.close()
```
The same instance is passed to all `enrich_unmapped_holdings()` calls.
`enrich_unmapped_holdings()` checks `owns_client = client is None` (line 226):
since a client is always injected by the loop, it never closes the injected
instance (line 258–260). The outer `finally` closes it exactly once. If the
caller passes an external client, neither function closes it (PR-3 C6 lesson
applied).

Advisory (minor): `bootstrap_stocks_from_cusip_map(db)` and
`backfill_stock_ids(db)` at lines 313–314 are outside the `try/finally` block.
If an unhandled exception escapes the loop (e.g., a DB connectivity failure),
`client.close()` still runs (finally), but the post-loop bootstrap and
backfill do not. The already-committed CUSIP mappings are durable; a re-run
of the `enrich_cusip` job will complete the bootstrapping on the next attempt.
This is acceptable behaviour but differs from what the docstring implies
("loops... then creates Stock rows and links holdings").

Evidence: `cusip_enrichment.py:291–321`.

---

### E. Tests

**Q9 — PASS.**

`test_enrich_picks_up_unresolved_holdings` (line 216–227):
- Seeds a `Holding13F` with `cusip_mapping_status="unresolved"` via
  `_seed_holdings()` against the real DB session.
- Calls `enrich_unmapped_holdings(db_session, client=OpenFigiClient(use_stub=True))`.
- Asserts `n == 1`, `h.cusip_mapping_status == "linked"`, `h.stock_id is not None`.

Regression-test validity: the old filter `== "pending_mapping"` would return
no rows for an `unresolved` holding → `pending_holdings = []` → `return 0` →
`n == 0`, failing the assertion. The test is a genuine regression guard.

Evidence: `test_13f_cusip_enrichment.py:216–227`,
`cusip_enrichment.py:198–207`.

**Q10 — PASS with advisory coverage gaps.**

`test_enrich_skips_cusips_already_mapped` (lines 230–244):
- Pre-inserts an AMZN mapping for CUSIP "023135106" via `upsert_cusip_mapping()`.
- Seeds both "023135106" (AMZN, pre-mapped) and "594918104" (MSFT, unmapped)
  as `unresolved` holdings.
- Asserts that exactly one new `CusipTickerMap` row is created (the unmapped
  one). Correctly exercises the NOT-IN exclusion.

`test_enrich_all_runs_to_completion` (lines 247–264):
- Seeds 4 CUSIPs (mixed `unresolved`/`pending_mapping`) with `batch_size=2`.
- Asserts `holdings_still_unmapped == 0`, `batches_run >= 2`,
  `mappings_created >= 4`, `holdings_linked >= 4`. Exercises multi-batch
  completion.

Both tests now use `_seed_holdings()` + real `db_session` rows rather than the
old `_db_with_pending()` MagicMock helper, so the query predicate shape is
fully exercised.

Client-lifecycle tests (`test_enrich_closes_a_self_constructed_client`,
`test_enrich_does_not_close_an_injected_client`): now use real DB seeds
and `monkeypatch` instead of a mock-chain db, so the full enrichment code
path runs.

**Coverage gaps (advisory, not blocking):**

| Scenario | Covered? |
|---|---|
| No-match CUSIP (`low` conf, `ticker=None`) exits pool | No — all test CUSIPs resolve via stub |
| All-invalid batch counts as progress (not a false stall) | No |
| `max_batches` cap halts the loop | No |
| No-progress guard fires and stops the loop | No |
| `needs_review` holding is NOT picked up by enrichment | No |

The gaps leave the loop backstops untested. The termination argument is sound
from code inspection (see B above), but direct test coverage would be a
meaningful robustness improvement.

Also note: `_SEED_SEQ = iter(range(1, 10_000))` is module-level state shared
across test runs. Tests that call `_seed_holdings()` advance this iterator.
This works reliably with pytest's default single-process, single-module loading
model; it would be fragile under parallel test workers or module reloads.
Not a blocking concern for the current CI setup.

Evidence: `test_13f_cusip_enrichment.py:145–264`.

---

### F. Scope

**Q11 — PASS.**

The PR does not claim the link rate has been raised. The task doc explicitly
scopes the operational prod run as "a separate, explicitly-authorised step"
(diagnosis doc lines 129–134). `docs/BACKLOG.md` entry is updated to "operational
run pending" and stays open until the `enrich_cusip` job is run against prod
and the rate is verified.

Diff scope confirmed:
- 5 backend files changed (service, admin job wiring, test), no DB migration.
- 1 new task doc (`2026-05-21_cusip-link-rate-diagnosis.md`).
- `docs/BACKLOG.md` updated.
- No frontend changes, no `rate-guard/` changes, no migration.

Evidence: `docs/tasks/2026-05-21_cusip-link-rate-diagnosis.md:129–134`,
`docs/BACKLOG.md:58–73`, `git diff --stat main...HEAD`.

---

## Pass bar evaluation

| Criterion | Result |
|---|---|
| A — broadened filter is correct; `unresolved` is the right set to re-enrich | PASS |
| B — loop provably terminates; unmapped-CUSIP pool strictly shrinks | PASS |
| C — no regression for other callers; result-dict shape change is safe | PASS |
| D — partial progress durable; client lifecycle correct | PASS |
| E — regression test genuine; lifecycle tests use real db | PASS |
| F — PR does not claim link rate raised; backlog reflects pending run | PASS |

**Verdict: APPROVE.** The OpenFIGI enrichment now correctly sees the ~13,981
unresolved prod holdings, and a single `enrich_cusip` job will drain the backlog
to completion. Safe to auto-deploy. The operational prod run remains a separate,
explicitly-authorised step.

## Verification performed

- Read `git diff main...HEAD` (all 6 changed files).
- Read full `cusip_enrichment.py` and `test_13f_cusip_enrichment.py`.
- Grepped `thirteenf_admin_dashboard.py` for all `enrich_cusip` and
  `mappings_created` references; read job-wiring context at lines 3008–3018
  and 3372–3391.
- Grepped `thirteenf_job_worker.py` for `summary_json` consumption.
- Grepped frontend for `summary_json`, `mappings_created`, `batches_run`.
- Read `openfigi/client.py` to verify `use_stub` stub behaviour.
- Confirmed no DB migration, no frontend diff, no rate-guard diff.
- Did **not** run the Docker backend test suite in this review pass.
