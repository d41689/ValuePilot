# T3 combination attribution review results

**Reviewed:** 2026-07-08  
**Diff:** `main...claude/13f-t3-combination-attribution`  
**Verdict:** **Changes requested.** The direction of attributing reportable
InfoTable positions to the filer is sound, and the `_pair_key` change fixes the
observed uniqueness crash. The implementation still excludes valid no-Column-7
shared positions, can misclassify multi-CUSIP changes, does not propagate the
new attribution caveat across the product, and has no production-safe rollout
that applies the required data and materialized-view recomputes.

## Findings

### [P1] Valid DFND/OTR holdings without Column 7 references remain excluded

**Location:** `backend/app/services/thirteenf_holdings_ingest.py:68-71`

The implementation makes `DFND`/`OTR` direct only when
`other_managers_raw` is non-empty. That condition is not a valid attribution
test. SEC Form 13F FAQ 37/46/48 says that a manager sharing discretion with an
other manager below the $100 million filing threshold aggregates those
securities into its filing and does **not** identify the other manager in
Column 7. Such a row can therefore correctly have `DFND` or `OTR` plus an empty
Column 7 and still be part of the filer's reportable position.

This is not hypothetical in the loaded 82-manager data:

- Cantillon filing `0001279936-26-000004`, 2026-Q1, is a complete
  `holdings_report`.
- Holding `53843`, Adobe (`00724F101`), is `DFND`, has
  `other_managers_raw=NULL`, and contains 628,547 shares worth $152,787,205.
- It remains `unresolved` and is excluded from holders, ownership changes, and
  Oracle's Lens.
- The same active Cantillon filing has 188 such unresolved rows versus 187
  direct DFND rows. Giverny has another 221 active DFND/no-ref unresolved rows.
  Across current active filings, 410 rows remain excluded for this reason.

This also contradicts the PO ruling's stated principle that holdings in the
filer's own InfoTable are the filer's reportable portfolio. `other_managers_raw`
should preserve sole/shared attribution detail, not determine whether the
position exists for the filer.

**Required correction:** apply the filer-attribution rule to normalized
`SOLE`/`DFND`/`OTR` regardless of Column 7 presence, while preserving
`investment_discretion` and a separate shared/included-manager caveat. Add
contract and consumer tests for DFND and OTR without references.

### [P1] Multi-CUSIP matching is order-dependent and emits false changes

**Location:** `backend/app/services/thirteenf_ownership_changes.py:298-326`

`current_by_stock` and `previous_by_stock` are dict comprehensions. Multiple
lots for one stock collapse last-wins independently in each quarter, while
`_direct_active_hr_holdings()` has no `ORDER BY`. The selected current lot can
therefore have a different CUSIP from the selected previous lot. Always using a
CUSIP key for fallback prevents the duplicate-key crash, but it does not make
the pairings correct.

Isolated review probe:

| Quarter | insertion order | holdings |
|---|---|---|
| 2025-Q4 | A, B | A=100 shares, B=200 |
| 2026-Q1 | B, A | B=220 shares, A=120 |

Both CUSIPs map to the same stock. The expected result is two `increased`
rows, A-to-A and B-to-B. The implementation produced:

- `cusip:A`: false `exited_position` (previous A=100)
- `cusip:B`: false `new_position` (current B=220)
- `stock:X`: false `cusip_changed` pairing current A=120 with previous B=200

The committed test at
`backend/tests/unit/test_13f_ownership_changes_compute.py:644` inserts lots in
the same order in both quarters, so it cannot catch this.

**Required correction:** match same-stock multi-lot positions deterministically
by exact CUSIP before any remaining stock-level corporate-action pairing, or
aggregate into the planned position read model before classifying changes. Add
the reverse-order regression above.

### [P1] Newly included shared positions are presented as uncaveated direct signals

**Locations:**

- `backend/app/services/thirteenf_user_api.py:486-491`
- `backend/app/services/thirteenf_ownership_changes.py:514-517`
- `backend/app/services/oracles_lens/signal_weighted_score.py:701-740`

The changed copy is only attached when a filing is marked partial/combination.
Many affected filers have included managers but are stored as complete
`holdings_report` filings. Their DFND/OTR rows now become `direct` without any
shared-reporting caveat:

- Berkshire filing `0001193125-26-226661` is
  `holdings_report / normal / complete`.
- Holding `57624`, Apple (`037833100`), is `DFND`, references managers `4,11`,
  and is now direct for 80,664,820 shares.
- `_filing_caveats()` does not attach `COMBINATION_REPORT`.
- `_has_combination_caveat()` is also false, so ownership changes can remain
  high-confidence primary signals.
- Oracle's Lens only inherits `PARTIAL_COVERAGE` from portfolio-weight
  calculation and has no included-manager/shared-discretion caveat for this
  complete filing.

Consequently the corrected `COMBINATION_CAVEAT` string does not appear on the
flagship Berkshire surfaces whose visibility motivated T3. The product also
loses the distinction between an independent sole manager vote and a filer
aggregating positions reported for included managers.

**Required correction:** derive and propagate a shared/included-manager caveat
from the holdings/filing data independently of `report_type`, including manager
holdings, stock holders, ownership changes, and Oracle's Lens components. Add a
consumer-level test using a complete holdings report with DFND/OTR references.

### [P1] Production deploy does not run the required backfill or recomputes

**Locations:**

- `backend/app/cli/edgar.py:467-478`
- `.github/workflows/deploy.yml:43-51`
- `scripts/deploy_prod_from_main.sh:58-65`

The command docstring says to run the backfill post-deploy and then recompute
ownership changes and Oracle's Lens, but deployment only rebuilds and health
checks services. There is no invocation of `backfill-attribution`, no exact
operator command sequence in the task doc, and no recorded affected
manager/quarter set. The command prints only a changed-row count.

After an automatic deployment, new ingests use the new rule while historical
holdings and both materialized products retain old results until an operator
performs undocumented manual work. For this ticket, that means the production
flagship behavior can remain unfixed even though deployment reports success.

The service-level backfill itself is otherwise appropriate: stored
`investment_discretion` is normalized, the source columns are sufficient
without re-reading XML, and recomputation is idempotent. A guarded command is
acceptable instead of Alembic only if rollout is explicit and verifiable.

**Required correction:** add an executable production runbook or a guarded
deploy step with this order:

1. deploy code;
2. run attribution backfill and persist affected manager/quarter scope;
3. recompute ownership changes for every affected quarter;
4. recompute Oracle's Lens only after ownership changes complete;
5. verify zero legacy statuses that should migrate, expected direct counts,
   zero per-manager compute failures, and representative API/score outputs.

## Attribution semantics and double-count review

The SEC materials support treating InfoTable rows as positions reported by the
filer, including positions reported for other included managers with whom
discretion is shared. They do **not** support the narrower code comment that all
included managers are the filer's own sub-entities: the local data includes,
for example, Wedgewood → RiverPark Advisors and Oaktree → Brookfield.

For the current universe, the deferred cross-filer double-count risk was not
found to be active:

- 82 active managers inspected.
- No active manager `parent_manager_id` links exist.
- No `other_managers_included[].cik` exactly matches a different active
  universe manager CIK.
- No credible included-manager name match to another active universe manager
  was found.

Thus no current duplicate consensus vote was demonstrated. The backlog guard
is still necessary because the database does not enforce this condition and an
added universe manager can activate it. Longer term, `direct` is carrying two
concepts: filer-level reportable exposure and independent attribution. A
first-class position/read model should aggregate multi-CUSIP lots while keeping
sole/shared/included-manager provenance available to consensus logic.

`shared` has no active producer after T3; only the stock-holder caveat query
still reads it. Existing historical rows disappear after backfill. That makes
the status effectively legacy, but it should not be removed until the revised
attribution/caveat model is decided.

## `_pair_key` verification

The change itself fixes the documented constraint crash:

- Temporarily restored the old both-stock-ID branch.
- `test_compute_multi_cusip_one_stock_both_quarters_no_crash` failed with
  `UniqueViolation` on
  `uq_ownership_changes_manager_quarter_security_position`.
- Restored always-CUSIP fallback keying; the same test passed.

CUSIP A previous → CUSIP B current for one stock still matches in the stock pass
and is classified `cusip_changed`; the fallback key change does not break that
single-lot case. No downstream consumer joins on `security_key`; it is used for
ordering, response display, and uniqueness, so the stock-to-CUSIP label change
does not break a join contract.

The remaining correctness problem is the order-dependent multi-lot pairing in
Finding 2, not `_pair_key` collision avoidance.

## Backfill and blast-radius verdict

- **Backfill data source:** sound; no XML re-ingest required.
- **Idempotence:** sound.
- **Transaction shape:** acceptable for the observed dataset, though a
  production command should batch/measure if historical volume grows.
- **Rollout safety:** not acceptable until the required downstream recomputes
  and verification are executable and recorded.
- **Mapping gate:** retaining the 0.50 block / 0.70 warning policy is honest.
  Oaktree's 0.35 linked ratio should remain unavailable rather than emit
  misleading changes; enrichment coverage is a separate remediation.
- **Consumer scoring:** manager taxonomy/weights work for newly visible
  managers, but included-manager provenance and caveats do not.
- **Test depth:** insufficient. Add no-ref attribution tests, reverse-order
  multi-CUSIP matching, a complete-filing Berkshire-style caveat test, a Lens
  contribution/caveat test, and a rollout/recompute integration test.

## Sources

- SEC, [Form 13F](https://www.sec.gov/files/form13f.pdf), Special Instructions
  7 and 11 (included managers, shared-defined/shared-other, and Column 7).
- SEC, [Frequently Asked Questions About Form 13F](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f),
  especially Questions 6, 33-37, and 46-48.

## Verification

All commands ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- Targeted attribution, ownership-change, user API, and Lens tests:
  **84 passed**.
- Full backend suite: **1078 passed, 3 warnings**.
- Review-only probes were removed; no production/test source file remains
  modified by the review.

---

## PO / author disposition (2026-07-08, after independent verification)

All four P1 findings were reproduced/queried against the code and real data,
confirmed real, and **all four fixed on branch `claude/13f-t3-combination-attribution`**
(no merge as-is). Full backend suite **1084 passed**; rollout script self-verifies
green on real dev data (exit 0).

- **#2 (multi-CUSIP matching) — FIXED.** Reproduced the reverse-order false
  exited/new/cusip_changed exactly. Real data has 0 multi-*distinct*-CUSIP-per-stock
  but **2,174 same-CUSIP duplicate lots**, so `_matched_pairs` was rewritten to (a)
  aggregate same-CUSIP lots, (b) match exact CUSIP first (deterministic,
  order-independent), (c) stock-fallback for genuine CUSIP changes, (d) leftovers
  new/exited. Dead `_pair_key` removed. Regression tests: reverse-order → two
  `increased`; same-CUSIP dup → summed.
- **#1 (no-Column-7 exclusion) — FIXED.** Confirmed the Cantillon-Adobe split
  (628,547-share lot excluded). Rule now: SOLE/DFND/OTR → `direct` regardless of
  Column 7; only unrecognized discretion → `unresolved`. PO plan §2 corrected;
  misleading "own sub-entities" comment fixed. 410 real DFND-no-ref rows recovered.
- **#3 (shared caveat) — FIXED.** New `SHARED_DISCRETION` caveat derived from
  holding `investment_discretion` (DFND/OTR — catches sub-threshold) OR filing
  `other_managers_included` (Berkshire), propagated to manager holdings /
  stock-holders (`_filing_caveats`), ownership changes, and Oracle's Lens.
  Transparency only — **not demoted** (demoting would re-suppress the flagship,
  whose shared discretion is with its own subsidiaries). Residual: the
  manager-holdings *display* misses the sub-threshold-only case (7 filings) →
  BACKLOG (signal surfaces cover it).
- **#4 (rollout) — FIXED.** `backend/scripts/t3_attribution_rollout.py` — idempotent,
  ordered (backfill → changes → Lens → verify), non-zero exit on verification
  failure; runbook in the task doc. Deploy stays build+health-check (migrations
  manual per AGENTS.md).
- **Semantics/double-count notes — agreed.** Attribution direction confirmed by
  the review + SEC; double-count guard remains deferred (verified not currently
  triggerable); `shared` status is now legacy (no producer) but retained until the
  positions read-model lands.

---

## Independent re-review (2026-07-08, commit `bc5e71d`)

**Verdict:** **Changes still requested.** Original findings #1 (no-Column-7
attribution) and #2 (order-dependent multi-CUSIP matching) are fully fixed.
Finding #3 is only partially fixed, and the new rollout implementation does not
yet satisfy finding #4's guarded, self-verifying production requirement.

### [P1] Rollout bypasses job locks and can report success without enforcing its stated invariants

**Locations:**

- `backend/scripts/t3_attribution_rollout.py:43-88`
- `backend/app/services/thirteenf_admin_dashboard.py:1237-1283`
- `backend/app/services/thirteenf_admin_dashboard.py:3106-3171`

The rollout calls `execute_job_payload()` directly. That function is the job
body, not the guarded enqueue path. It does not create an active `JobRun` or
claim the per-quarter `compute_ownership_changes:*` /
`oracles_lens_score:*` lock keys. A scheduled quarterly pipeline, an admin job,
or a second rollout invocation can therefore execute the same delete/insert or
upsert/component-replacement work concurrently. The runbook contains no
quiesce check and the script does not reject active conflicting jobs.

The self-verification also has two false-pass paths:

1. It checks only legacy `reported_for_other` / `shared` values. It does not
   assert that every recognized `SOLE`/`DFND`/`OTR` row is now `direct`. The
   exact original bug -- DFND/no-Column-7 rows left `unresolved` -- would pass
   this query.
2. It calculates and prints `zero_direct`, but never adds a failure when the
   count is non-zero. The script can print "managers with zero direct holdings:
   N" and still finish with `ROLLOUT VERIFICATION PASSED`.

There is no automated test for the rollout. The real dev run passed because the
current data is healthy (`recognized discretion non-direct = 0`,
`zero_direct = 0`), not because the script reliably detects those failures.

**Required correction:** run through the canonical locked JobRun mechanism or
explicitly acquire/check the same lock keys; reject concurrent pipeline/rollout
work. Fail on both:

```sql
investment_discretion IN ('SOLE','DFND','OTR')
AND holding_attribution_status IS DISTINCT FROM 'direct'
```

and `zero_direct > 0`. Add failure-injection tests proving each invariant and
lock conflict produces a non-zero exit.

### [P2] `SHARED_DISCRETION` still does not reach every promised product surface

**Locations:**

- `backend/app/services/thirteenf_user_api.py:73-120`
- `backend/app/services/thirteenf_user_api.py:421-427`
- `backend/app/services/thirteenf_user_api.py:490-500`
- `backend/app/services/thirteenf_ownership_changes.py:107-138`
- `backend/app/services/thirteenf_ownership_changes.py:234-239`
- `backend/app/services/oracles_lens/signal_weighted_score.py:690-727`

Manager holdings and stock-holder caveats still derive
`SHARED_DISCRETION` only from `filing.other_managers_included`. They do not
inspect the displayed holdings' `investment_discretion`. This is the
sub-threshold/no-Column-7 case fixed by finding #1:

- Giverny manager `4007`, 2026-Q1 currently returns `status=available`,
  `caveats=[]`, while the response contains 35 DFND common holdings.
- This residual was placed in BACKLOG, but it is part of the original finding
  #3 acceptance surface, so #3 cannot be marked fully fixed.

Ownership changes add `shared_discretion` only in `_compute_rows()`. Rows built
by the unavailable branch bypass that block. The recomputed dev data contains
16 affected manager-quarter groups; Oaktree 2026-Q1 alone has 147 unavailable
DFND rows without the caveat.

Oracle's Lens handles the common current data shape, but its grouped
manager/stock contribution checks only the largest-value representative
holding. For a no-cover-page group containing a large SOLE lot plus a smaller
DFND/OTR lot, the shared caveat is lost. The scorer should test `any()` holding
in the group, mirroring `_merge_holdings()` in ownership changes. No such mixed
group exists in the current active dev data, but the aggregation contract
allows it.

**Required correction:** derive the caveat from both filing metadata and all
relevant holdings on every surface; add tests for:

- manager holdings and stock holders with DFND/no included-manager metadata;
- unavailable ownership-change rows;
- a Lens manager/stock group whose representative is SOLE but another lot is
  DFND.

## Original finding disposition

| Original finding | Re-review result |
|---|---|
| #1 DFND/OTR without Column 7 excluded | **Fixed.** SOLE/DFND/OTR now always map to direct; backfill and parser tests cover no-ref cases. Dev has zero recognized-discretion non-direct rows. |
| #2 multi-CUSIP order-dependent matching | **Fixed.** Same-CUSIP aggregation plus exact-CUSIP-first matching is deterministic. Reverse-order and duplicate-lot tests pass. |
| #3 caveat propagation | **Partially fixed.** Complete Berkshire-style filings, normal ownership changes, and ordinary Lens contributions are covered; cases above remain. |
| #4 production rollout | **Not fully fixed.** The executable sequence works on healthy dev data, but it bypasses locks and its verification can false-pass. |

## Re-review verification

All tests ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- Targeted attribution, ownership-change, user API, Lens, and orchestration
  suites: **94 passed**.
- Full backend suite: **1084 passed, 3 warnings**.
- Dev rollout executed idempotently: all six quarters recomputed, zero reported
  per-manager failures, and the script exited 0.
- No source or test files were modified by this re-review.

---

## Second disposition (2026-07-08, re-review fixes — commit forthcoming)

Both re-review findings reproduced against code + real data, confirmed, and
**fully fixed**. Full backend suite **1091 passed**; rollout self-verifies green
on real dev data (exit 0); Giverny 4007 now returns `available_with_caveat`.

- **Re-review #4 (rollout locks + false-pass verify) — FIXED.** Logic moved to a
  testable `app/services/thirteenf_attribution_rollout.py`; recomputes now run
  through the canonical LOCKED `_execute_pipeline_stage_job` (per-quarter
  `compute_ownership_changes:*` / `oracles_lens_score:*` lock), aborting with a
  `RolloutConflictError` (exit 2) if a conflicting job is active. Verification now
  fails on **`investment_discretion IN ('SOLE','DFND','OTR') AND status IS
  DISTINCT FROM 'direct'`** (the exact original bug) AND on **zero_direct > 0**
  AND on per-manager recompute failures — not just legacy statuses. Tests inject
  each failure (DFND-left-unresolved, zero-direct, legacy) and a lock conflict;
  all produce the expected non-pass. The thin `scripts/t3_attribution_rollout.py`
  wrapper maps outcomes to exit 0/1/2.
- **Re-review #3 residual (caveat not on every surface) — FIXED.**
  - Manager holdings (`build_user_manager_holdings`) and stock holders
    (`_stock_holder_data_caveats`) now derive `SHARED_DISCRETION` from the
    displayed holdings' `investment_discretion` (DFND/OTR), not only
    `other_managers_included` — Giverny 4007's 35 DFND holdings now caveat.
  - Ownership-changes **unavailable branch** now adds `shared_discretion` (it
    previously bypassed `_compute_rows`).
  - Oracle's Lens now flags the caveat when **any** lot in the aggregated
    manager/stock group is DFND/OTR (was representative-only), mirroring
    `_merge_holdings`.
- **Notes accepted:** attribution direction + double-count (deferred, not
  triggerable) + `shared` legacy-until-positions-model — all agreed; the
  manager-holdings residual is no longer deferred (it is fixed here).

---

## Third independent re-review (2026-07-08, commit `4ca7630`)

**Verdict:** **Changes still requested.** The prior caveat-propagation finding
is now fixed across the inspected paths, and lock conflicts plus attribution
invariants are correctly enforced. One merge-blocking rollout false-pass
remains, plus one user-facing copy accuracy issue.

### [P1] A hard recompute-stage failure still produces a successful rollout report

**Location:** `backend/app/services/thirteenf_attribution_rollout.py:73-130`

`_run_locked_stage()` raises only for `conflict`. It returns ordinary
`failed`/`partial_success` stage results to `run_attribution_rollout()`.
The ownership loop records only `summary.failure_count`; a hard failed stage
returns no such count. The Oracle's Lens loop does not inspect status at all.
Consequently both materialization stages can fail while the final attribution
queries remain healthy and the wrapper exits 0.

Failure injection against `valuepilot_test`:

```text
_run_locked_stage -> {
  "stage": {"status": "failed", "job_id": 999},
  "summary": {"status": "failed"},
  "error": "injected hard failure"
}

run_attribution_rollout(...) ->
{"reattributed": 0, "quarters": ["2099-Q1"], "failures": []}
```

This is not covered by `test_13f_attribution_rollout.py`; its only stage-path
test is an active-lock conflict. It also matters because the latest revision
removed the previous Berkshire direct-holdings / real-changes verification and
does not verify any Lens output. Stage success is therefore the only evidence
that the two materialized products were refreshed, and that evidence is
currently ignored.

**Required correction:** treat every stage status outside the explicitly
accepted set as a rollout failure. For this production backfill, prefer
`status == "succeeded"`; if ownership `partial_success` is intentionally
accepted, require and report its non-zero failures and still exit non-zero.
Add injected hard-failure tests for both job types and restore representative
postconditions for ownership changes and Oracle's Lens (or equivalent
per-quarter freshness/output assertions).

### [P2] The shared-discretion message is inaccurate for the no-Column-7 case

**Locations:**

- `backend/app/services/thirteenf_user_api.py:34-37`
- `backend/app/services/oracles_lens/caution_flags.py:128-136`

The code now correctly applies `SHARED_DISCRETION` to DFND/OTR holdings whose
filing has no `other_managers_included` list. The displayed text nevertheless
says the positions are shared "with included managers (e.g. subsidiaries)".
For the sub-threshold case that motivated finding #1, the other manager is
specifically not an Other Included Manager and need not be a subsidiary.

Concrete result after this fix: Giverny `4007` 2026-Q1 correctly returns
`available_with_caveat` for 35 DFND holdings, but the caveat claims included
managers even though the filing's included-manager list is empty.

**Required correction:** use neutral wording such as "shared/defined
discretion with other managers, which may include affiliates or subsidiaries."
Keep the more specific combination/included-manager copy only where filing
metadata supports it.

## Third-review disposition

| Area | Result |
|---|---|
| SOLE/DFND/OTR attribution and backfill | **Fixed** |
| Deterministic duplicate/multi-CUSIP matching | **Fixed** |
| Manager holdings / stock holders caveat | **Fixed in code** |
| Normal and unavailable ownership-change caveat | **Fixed** |
| Oracle's Lens grouped-lot caveat | **Fixed** |
| Job lock conflict handling | **Fixed** |
| Positive attribution / zero-direct verification | **Fixed** |
| Hard stage failure handling and materialization verification | **Not fixed** |
| Shared-discretion copy accuracy | **Not fixed** |

## Third-review verification

All tests ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- Targeted rollout, attribution, ownership-change, user API, Lens, and
  orchestration suites: **101 passed**.
- Full backend suite: **1091 passed, 3 warnings**.
- Live dev checks: Giverny 2026-Q1 is `available_with_caveat` with
  `SHARED_DISCRETION`; unavailable DFND/OTR ownership rows missing the caveat:
  **0**.
- Injected hard stage failure reproduced the false-success report above.
- No source or test files were modified by this review.

---

## Third disposition (2026-07-08, third-review fixes)

Both third-review findings reproduced against the code, confirmed, and **fully
fixed**. Full backend suite **1095 passed**.

- **Re-review #1 (hard stage failure → false success) — FIXED.**
  `run_attribution_rollout` now treats ANY stage status other than `succeeded`
  (hard `failed` OR `partial_success`) as a rollout failure and reports it — the
  Lens loop previously ignored status entirely and the ownership loop read only
  `failure_count` (a hard-failed stage has none). Restored a representative
  materialization postcondition: `_representative_freshness_failures` asserts the
  flagship (Berkshire) has direct holdings AND real ownership changes after the
  run (guarded — skipped when the flagship is absent, e.g. an isolated test DB).
  Tests inject a hard-failed ownership stage, a hard-failed Lens stage, and a
  partial_success ownership stage; each now yields a non-empty `failures`.
- **Re-review #2 (caveat copy inaccurate) — FIXED.** Both the user-API
  `SHARED_DISCRETION_CAVEAT` and the Lens caveat label now use neutral wording —
  "shared/defined discretion with other managers (which may include affiliates,
  subsidiaries, or a manager whose holdings are aggregated into this filing)" —
  so the sub-threshold (empty `other_managers_included`) case is no longer
  described as "included managers (e.g. subsidiaries)". A copy-accuracy test
  guards it.

---

## Fourth independent re-review (2026-07-08, commit `7a4661f`)

**Verdict:** **One P2 remains.** The two direct third-review findings are fixed:
hard/partial stage statuses now fail the rollout, and the shared-discretion copy
is accurate for both included-manager and sub-threshold cases. No new
attribution, matching, caveat-propagation, or lock regression was found.

### [P2] The representative "freshness" check can pass using unrelated historical data and does not verify Lens

**Location:** `backend/app/services/thirteenf_attribution_rollout.py:143-165`

`_representative_freshness_failures()` counts all Berkshire direct holdings and
all non-unavailable ownership changes across every quarter. It is not scoped to
the quarters requested by this rollout, to the latest quarter, or to rows
written by the stage jobs. It also does not query `oracles_lens_signals` or
`oracles_lens_score_components` at all, despite Lens being one of the two
materialized products this rollout is required to refresh.

Fault injection against the populated dev database returned success when both
stage functions claimed `succeeded` but wrote nothing:

```text
quarters = ["2099-Q1"]
ownership summary = succeeded, rows_created=0
Lens summary = succeeded, filings_scored=0

report = {
  "reattributed": 0,
  "quarters": ["2099-Q1"],
  "failures": []
}
```

Old Berkshire holdings/changes from real historical quarters satisfied the
postcondition. This matters because the compute job contracts treat a zero-work
run as `succeeded`; stage-status checks alone cannot distinguish a legitimate
empty quarter from an accidentally empty/no-op recompute.

The earlier hard-failure false-pass is fixed -- injected `failed` and
`partial_success` statuses are now recorded correctly. Continuing to run Lens
after an ownership failure is best-effort rather than a scoring-corruption bug:
the current Lens add-intensity primitive reads holdings directly, not the
`ownership_changes` table, and the final rollout still exits non-zero.

**Required correction:** make postconditions run-scoped. For example:

- retain stage job IDs and verify Lens signals/components with
  `source_job_id=<this Lens stage job>` for expected populated quarters;
- verify ownership rows for the target manager/quarter were updated during this
  run (or validate expected manager/row counts from the stage summary);
- explicitly allow known legitimately empty quarters instead of using
  all-history counts;
- add a test where both stages return `succeeded` with zero output while old
  Berkshire data exists, and require a failure.

## Fourth-review disposition

| Area | Result |
|---|---|
| Hard/partial stage status handling | **Fixed** |
| Neutral shared-discretion copy | **Fixed** |
| Attribution, matching, caveat propagation, and locking | **Fixed** |
| Representative ownership/Lens run freshness | **Not fully fixed** |

## Fourth-review verification

All tests ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- Targeted rollout, attribution, ownership-change, user API, Lens, and
  orchestration suites: **105 passed**.
- Full backend suite: **1095 passed, 3 warnings**.
- Failure injection confirmed hard ownership/Lens failures and partial success
  now produce non-empty rollout failures.
- No-op-success injection against populated dev reproduced the stale
  all-history postcondition pass described above.
- No source or test files were modified by this review.

---

## Fourth disposition (2026-07-08, fourth-review fix)

The remaining P2 reproduced against the code, confirmed, and **fixed**. Full
backend suite **1097 passed**.

- **Re-review #4-b (postcondition used stale all-history data; ignored Lens) —
  FIXED.** Replaced the Berkshire all-history `_representative_freshness_failures`
  with a RUN-SCOPED `_run_freshness_failures(session, quarters,
  ownership_rows_by_quarter, lens_stage_job_ids)`:
  - Ownership: for each requested quarter, if it has active *direct* filers but
    this run's stage wrote 0 rows, that's a no-op recompute → failure. A
    genuinely empty quarter (0 active filers) is skipped, so an empty quarter is
    distinguished from an accidental no-op.
  - Lens: at least one signal must be written under THIS run's Lens stage job ids
    (`oracles_lens_signals.source_job_id`) when the universe has active direct
    filers — a no-op or a lying summary writes none. Per-quarter below-threshold
    zeros are fine; the aggregate over a populated universe cannot be zero.
  Neither check consults stale historical data. Tests: a no-op-success with a
  real active-filer quarter now fails; a genuinely empty quarter's no-op does
  NOT false-fail; the earlier hard-failed / partial-success / lock-conflict cases
  still fail. Full suite 1097 passed.
- The reviewer's note that continuing Lens after an ownership failure is
  best-effort (not scoring corruption, since add-intensity reads holdings, not
  ownership_changes) — accepted; the rollout still exits non-zero on any failure.
