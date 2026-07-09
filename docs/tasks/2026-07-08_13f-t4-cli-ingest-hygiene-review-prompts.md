# Review prompts — T4 (CLI 摄取卫生:委托 job 路径,F5+F6)

Task doc: [`2026-07-08_13f-t4-cli-ingest-hygiene.md`](./2026-07-08_13f-t4-cli-ingest-hygiene.md)
PO plan: [`2026-07-08_13f-real-data-findings-po-plan.md`](./2026-07-08_13f-real-data-findings-po-plan.md)
Branch: `claude/13f-t4-cli-ingest-hygiene` · **PR #110** (CI green).
Read the diff with `git diff main...claude/13f-t4-cli-ingest-hygiene`.

## What changed

- **CLI delegates to the job** (`backend/app/cli/edgar.py`): `ingest-holdings`
  and `backfill` no longer call legacy `ingest_filing_holdings`; they call the
  modern `ingest_holdings` job via `execute_job_payload(db, "ingest_holdings",
  {"quarter": q})` (→ `_execute_ingest_job` → `ingest_if_needed`). Removed the
  `ingest-holdings --limit` option.
- **New selectors** (`backend/app/services/edgar_ingestion.py`):
  - `pending_ingest_quarters(db)` — distinct calendar quarters of un-ingested
    filings (`raw_infotable_doc_id IS NULL`), keyed on each filing's *current*
    `period_of_report`.
  - `ingest_pending_holdings(db, *, quarters=None, ingest_fn=None, log=None)` —
    delegates each pending quarter to the job; `quarters=` restricts scope;
    per-quarter failures are isolated (caught, rolled back, recorded, loop
    continues).
  - `next_quarter_label(label)` / `_date_to_quarter(d)` — quarter-label helpers.
- **`backfill` Step 2** bounds the ingest to `{report quarters Step 1 indexed}
  ∪ {next_quarter of each}` and exits non-zero if any quarter failed.

## Context a reviewer cannot see from the diff alone

- **The F5 proxy mechanism.** A filing indexed from `form.idx` is inserted with
  `period_of_report = filed_at` — a *proxy*. It is corrected to the true report
  quarter-end only after its primary doc is parsed (`backfill_period_routing`).
  A 13F-HR reporting quarter Q is filed within 45 days of Q-end, i.e. in the
  **following** calendar quarter. So an un-ingested newest-quarter filing's proxy
  period sits one quarter *ahead* of its report quarter. Selecting pending
  filings by a *report-quarter* window (the old `backfill`) therefore never
  matched fresh filings for the newest quarter → all silently skipped (F5). The
  fix keys on the proxy period instead, and delegates to the job whose window
  (`_execute_ingest_job`: `period_of_report.between(quarter_window(q))`) matches
  that same proxy.
- **Why the `--quarters N` bound matters (do not remove it).**
  `_execute_ingest_job`'s Phase 1 returns `no_cik` for a filing whose manager
  has no confirmed CIK — its infotable can never be fetched, so
  `raw_infotable_doc_id` stays `NULL` **forever**. Without the scope bound,
  `pending_ingest_quarters` would surface that filing's quarter on *every* run,
  so `backfill --quarters 1` would re-invoke the job across every historical
  quarter that has any stuck filing, re-hitting EDGAR unboundedly. The
  `{report Q} ∪ {next Q}` bound is the fix — pressure-test that it (a) still
  reaches the newest report quarter and (b) never exceeds N-ish quarters of work.
- **F6 = product visibility.** The legacy path wrote `holdings_13f` rows with
  `parse_run_id = NULL`; the product query contract (PRD §7.3
  `active_hr_holdings_query`) inner-joins `parse_runs.is_current`, so those rows
  are invisible to Oracle's Lens / managers API / ownership-changes. The job path
  writes ParseRun-backed holdings and does the Phase-4 column heal + solo-HR
  activation the CLI lacked.
- **Two regressions were ALREADY found and fixed in this branch** by an internal
  review (both pinned by regression tests). You are reviewing the **post-fix**
  state — pressure-test the fixes; only report them if they are still wrong, not
  as new discoveries:
  1. The scope bound above (initially `ingest_pending_holdings` scanned the whole
     table).
  2. Per-quarter failure isolation (initially one hard-failing quarter aborted
     the whole backfill; the job path re-raises programming/hard errors).
- **Deliberately deferred (judge whether that was correct):**
  - **F7 — `reparse-filing` / `reparse-all` still write invisible holdings.**
    They still call legacy `ingest_filing_holdings` (`parse_run_id = NULL`), and
    `reparse-all` passes `replace_holdings=True` → deletes visible holdings then
    re-inserts invisible ones. Same class as F6 but a *different* pair of
    commands; scoped OUT of F5/F6 and recorded as **F7** in `docs/BACKLOG.md`.
    The PO chose "ship T4, F7 as a small follow-up (delegate to the existing
    `reparse_accession` job type)".
  - **Recoverability edge:** `backfill` decides pending-ness by
    `raw_infotable_doc_id IS NULL`, not by failed-parse. A filing whose infotable
    is fetched+committed (Phase 1) but whose holdings then fail to parse leaves
    `raw_infotable_doc_id` set and no current ParseRun, so it drops out of
    `pending_ingest_quarters`; if it is the last pending filing in its quarter,
    `backfill` won't retry it (the admin / `reparse_accession` retry surface is
    the intended recovery). Backlogged (low).
- **Test isolation:** dev DB `valuepilot` holds real data; pytest must run on the
  isolated DB:
  ```
  TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
  ```
- **Already verified (re-confirm, don't trust):** full backend suite **1108
  passed**; 9 new tests in `test_13f_cli_ingest.py`; on real dev data 25,070
  holdings are all ParseRun-backed with **0** legacy `parse_run_id = NULL` rows;
  `pending_ingest_quarters(dev)` returns `[]` (idempotent steady state).

Three prompts for three agents. Run in parallel; collect findings in
`2026-07-08_13f-t4-cli-ingest-hygiene-review-results.md`. For every finding give
`file:line`, a concrete filing/quarter/state, and the wrong outcome — and where
you can, reproduce it on `valuepilot_test` before asserting it.

---

## Prompt 1 — Ingest selection & scope-bound correctness (the critical angle)

```
You are reviewing the quarter-selection logic that decides which filings a CLI
backfill (re)ingests. The commands now delegate to the modern ingest_holdings
job; correctness rests entirely on two new pure functions and one bound.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t4-cli-ingest-hygiene`.
Read first:
  - backend/app/services/edgar_ingestion.py — pending_ingest_quarters,
    ingest_pending_holdings, next_quarter_label, _date_to_quarter.
  - backend/app/cli/edgar.py — backfill (Step 2, the `scoped` set) and
    ingest_holdings.
  - backend/app/services/thirteenf_admin_dashboard.py — _execute_ingest_job
    (filing selection `period_of_report.between(quarter_window(q))`; the no_cik /
    failure phases) and quarter_window.
  - The "Context" section of this doc (the F5 proxy mechanism; why the bound).

Pressure-test, with a concrete filing/quarter for each finding:
  1. Newest-quarter reachability vs. bound tightness. `backfill` scopes Step 2 to
     `{report quarters} ∪ {next_quarter(each)}`. Prove BOTH directions on real
     dates: (a) a newest-report-quarter filing (proxy period = filed_at in the
     following quarter) is INCLUDED; (b) a filing whose proxy period is TWO
     quarters after its report quarter (late/amended filing, filed >90 days after
     quarter-end) is EXCLUDED and thus silently skipped by backfill — is that a
     real coverage hole, and how common is it in the 82-manager universe?
  2. Proxy vs. corrected period. `pending_ingest_quarters` keys on the CURRENT
     period_of_report. For a filing ingested in a PRIOR run (period corrected to
     the report quarter) that later becomes pending again (e.g. re-index), does
     the corrected period land it in a quarter the bound still covers? Can a
     filing be both "pending" and outside every `{report Q}∪{next Q}` window?
  3. next_quarter_label / _date_to_quarter edge cases: Q4→next-year-Q1, month
     boundaries (Mar/Apr, Dec/Jan), case-insensitivity, and that the quarter a
     filing is grouped into ALWAYS falls inside that quarter's
     `quarter_window(...)` (so the job actually selects it). Any date where
     grouping and the job window disagree is a silent miss.
  4. Idempotency & convergence. The pending list is computed ONCE before the
     loop while each ingest commits and mutates period_of_report /
     raw_infotable_doc_id. Can a filing be processed twice, or skipped, or can a
     quarter oscillate in/out across runs and never converge? Consider a filing
     whose parse moves its period from quarter A (proxy) to quarter B (corrected)
     mid-loop.
  5. ingest-holdings --quarter Q semantics. Q is now "the calendar quarter the
     (proxy) period falls in" = effectively the FILING quarter for fresh filings,
     but the REPORT quarter for already-parsed ones. Is that dual meaning a
     footgun for an operator, and is it correctly documented in --help / the
     docstring?

Output: file:line, the concrete filing/date, and the missed/duplicated/
never-converging outcome. Reproduce on valuepilot_test where feasible. If the
selection is sound, justify why every pending filing lands in exactly one
in-scope quarter whose job window selects it.
```

---

## Prompt 2 — Removed behavior, job-path delegation & error/transaction semantics

```
You are reviewing a rewrite that replaces a per-filing CLI ingest loop with a
per-quarter delegation to the ingest_holdings job. Focus on what the old code
did that the new code must still do, and on transaction/error behavior.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t4-cli-ingest-hygiene`.
Read first:
  - backend/app/cli/edgar.py — the DELETED bodies of ingest_holdings/backfill
    (per-filing try/except + db.commit; the --limit option) and the new bodies.
  - backend/app/services/edgar_ingestion.py — ingest_pending_holdings
    (per-quarter try/except + db.rollback; the default ingest_fn that commits).
  - backend/app/services/thirteenf_admin_dashboard.py — execute_job_payload /
    _execute_job / _execute_ingest_job: does it run UNLOCKED (no JobRun, no
    lock_key) on this path? Per-filing SAVEPOINTs, phase commit barriers,
    _is_programming_error re-raise, the deliberate Phase-2 fail-loud
    (test_ingest_job_failloud.py).
  - The "Context" section (the two already-applied fixes; the F7 deferral).

Probe:
  1. Error resilience parity. The old loop caught EVERY per-filing exception and
     continued. The job isolates per-filing DATA errors (savepoint→partial_success)
     but re-raises programming/hard errors; ingest_pending_holdings now catches
     per-QUARTER. Is a single bad filing still non-fatal end-to-end, and is a hard
     quarter failure surfaced loudly (non-zero exit) while NOT abandoning healthy
     quarters? Confirm the `except typer.Exit: raise` guard in backfill actually
     lets the failed-quarter Exit(1) through instead of being swallowed by the
     generic `except Exception`.
  2. Transaction safety of the per-quarter `db.rollback()` in
     ingest_pending_holdings: with the default ingest_fn (which commits on
     success), does a mid-quarter raise + rollback ever discard a PRIOR quarter's
     already-committed work, or leave the session in a bad state for the next
     quarter? Check against the isolated-DB fixture's create_savepoint mode too
     (do the new tests actually exercise the rollback path safely?).
  3. Concurrency / locking. The CLI path calls execute_job_payload with no JobRun
     and no lock_key, whereas the dashboard/pipeline ingest and the T3 runbook
     (backend/scripts/run_historical_backfill.py) create a JobRun + lock. Can a
     CLI `backfill` racing a scheduled ingest_holdings for the same quarter
     corrupt or double-write? Was this gap introduced here or pre-existing?
  4. Orphaned / stale references. Grep the ENTIRE repo for `--limit` with
     ingest-holdings, for callers of the old CLI selection, and for docs/runbooks
     that invoke these commands with the old flags/semantics. Report every stale
     reference. Confirm `ingest_filing_holdings` is still legitimately used
     (reparse_filing/reparse_all) and not left half-orphaned.
  5. The F7 deferral is a JUDGMENT you must independently make, not accept:
     reparse-all with replace_holdings=True deletes product-visible holdings and
     re-inserts parse_run_id=NULL invisible ones. Given this is a live footgun in
     the same CLI file the PR touches, is deferring it to a follow-up (backlog
     F7) acceptable, or should it block this PR? State your call and why. Also
     judge whether the deferral is adequately DISCLOSED (PR body + BACKLOG).

Output: file:line, concrete scenario, wrong/lost/duplicated result. If sound,
justify parity with the old behavior and why the deferral is safe to ship.
```

---

## Prompt 3 — Altitude, product-visibility invariant & test adequacy

```
You are a staff engineer judging whether this fix is implemented at the right
depth and whether its tests would actually catch a regression of F5/F6.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t4-cli-ingest-hygiene`.
Read first:
  - backend/tests/unit/test_13f_cli_ingest.py (all 9 tests + the fixtures:
    note they inject ingest_fn / stub raw_infotable_doc_id via a real
    RawSourceDocument, and never actually run the job or hit EDGAR).
  - backend/app/services/edgar_ingestion.py + backend/app/cli/edgar.py.
  - docs/BACKLOG.md (F5/F6 marked resolved; F7 + recoverability edge open) and
    the task doc.

Judge:
  1. Altitude. The CLI now delegates to execute_job_payload rather than
     re-implementing ingest. Is that the right seam, or should the CLI go through
     the SAME locked JobRun path the dashboard/runbook use (so all ingest entry
     points share one concurrency-safe mechanism)? Is `pending_ingest_quarters`
     duplicating quarter-enumeration logic that already exists
     (quarter_label_for_date / previous_quarter_label in
     thirteenf_admin_dashboard, _quarter_labels_for_display)? Would a single
     shared "which quarters need ingest" authority be the deeper fix?
  2. Test adequacy for the INVARIANT that matters. F6's whole point is
     "CLI-ingested holdings are ParseRun-backed / product-visible", but the tests
     inject a stub ingest_fn and never assert a real parse_run_id is written or
     that active_hr_holdings_query returns the rows. Is there a meaningful gap
     between "the CLI calls the job" (tested) and "the job produces visible
     holdings" (untested here)? Would a regression that silently reverts to the
     legacy path be caught? Propose the minimal test that would close the gap
     (e.g. an integration test asserting a current parse_run_id, or a guard test
     that the CLI never imports/calls ingest_filing_holdings).
  3. The `period_of_report IS NULL` exclusion in pending_ingest_quarters silently
     drops any un-ingested filing with a null proxy period. The claim is "form.idx
     always sets period = filed_at so this can't happen". Verify that claim across
     ALL insert paths for Filing13F; if any path can leave it null, this is a
     silent coverage hole (no log, no error).
  4. Operator ergonomics. On a fully-ingested DB `backfill` prints "no pending
     holdings in the requested quarters" — is that accurate/clear when there ARE
     pending filings but outside the N-quarter scope? Does the removed per-quarter
     "ingesting N filings…" progress output make the command materially harder to
     operate/monitor for a real 300-filing backfill?

Output: file:line and the concrete altitude/coverage gap, with the minimal
change that would close it. If the depth and tests are adequate, say so and
justify why a silent F5/F6 regression would be caught.
```
