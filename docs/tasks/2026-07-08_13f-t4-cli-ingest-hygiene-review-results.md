# T4 CLI ingest hygiene review results

**Reviewed:** 2026-07-08  
**Diff:** `main...claude/13f-t4-cli-ingest-hygiene`  
**Original verdict:** **Changes requested.** F5's bounded quarter selection is sound and
F6's new ingest path is product-visible, but the CLI bypasses the existing job
lock, the sibling replay commands remain an actively documented destructive
footgun, and the new tests do not pin the CLI-to-product visibility contract.

## Third review after second fix

**Re-reviewed:** 2026-07-08  
**Current verdict:** **Minor documentation change requested.** All implementation
and regression-test findings are resolved. One stale sentence in the task's
earlier disposition still repeats the incorrect product-visibility claim that
the new disposition and tests correctly refute.

### [P3] Earlier disposition still says the inactive original has 602 visible rows

**Location:** `docs/tasks/2026-07-08_13f-t4-cli-ingest-hygiene.md:128-135`

The new third-review disposition correctly explains that accession
`0001325447-26-000009` is inactive, has a current ParseRun, and contributes zero
rows through `active_hr_holdings_query`. `docs/BACKLOG.md` is also corrected.
However, the preceding second-review disposition still says:

`新 current run 602 可见`

Those statements are in the same task document and contradict each other.
Change the earlier sentence to say "602 current-ParseRun rows, 0
product-visible rows because the filing is inactive", or replace it with a link
to the corrected third-review verification.

### Resolved in this round

- The real locked runner path now parses stored XML, creates a visible JobRun,
  swaps current ParseRuns, and is checked through `active_hr_holdings_query` for
  both active and inactive filings.
- The CLI mock wiring test plus the real runner integration test form a complete
  boundary chain; invoking a real Typer command in the integration test is no
  longer necessary to establish the invariant.
- `reparse-all` now has a runtime partial-failure test proving successful
  accessions continue and the final exit is non-zero.
- The pre-existing ParseRun audit suite separately proves old-run holdings are
  retained, so the combined suite covers the non-destructive F7 contract.
- No new implementation, transaction, lock, selection, or error-propagation
  defect was found.

### Third-review verification

All commands ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- CLI, ParseRun, and fail-loud targeted suites: **35 passed**.
- Full backend suite: **1116 passed, 3 warnings**.
- `git diff --check`: passed.

## Second review after fixes

**Re-reviewed:** 2026-07-08  
**Second-review verdict:** **Changes requested.** The destructive replay path and
unlocked CLI execution are correctly fixed. The product-visibility test finding
is only partially addressed, and its recorded real-data verification is
factually incorrect.

### [P2] CLI product visibility is still not exercised, and the cited validation filing is inactive

**Locations:**

- `backend/tests/unit/test_13f_cli_ingest.py:276-348`
- `docs/BACKLOG.md:15-25`
- `docs/tasks/2026-07-08_13f-t4-cli-ingest-hygiene.md:142-147`

The added tests prove source text and mock wiring:

- the four CLI functions do not contain the literal
  `ingest_filing_holdings`;
- `ingest-holdings` and `reparse-filing` call a mocked `run_locked_job`;
- a pre-existing active lock returns a conflict.

They still never run a CLI command through the real default locked job, never
write a ParseRun through that path, and never query the result through
`active_hr_holdings_query`. `reparse-all` also has no runtime wiring test; the
source check would pass if it called the wrong job type or payload key.

The recorded real-data verification does not close that gap. Accession
`0001325447-26-000009` is the inactive original First Eagle 2026-Q1 filing:

- `is_active_for_manager_period = false`;
- restatement `0001325447-26-000018` is active;
- the original has a new current ParseRun with 602 rows, but
  `active_hr_holdings_query(... filing_id=<original>)` returns **0**, not 602.

Thus "602 visible holdings" in both docs confuses current-ParseRun membership
with the full product visibility contract, which also requires the filing to be
active. The implementation itself preserves ParseRun history and appears
correct; the requested regression proof remains absent.

**Required correction:** add one stored-XML integration test that invokes the
real CLI/default `run_locked_job` path for an active HR filing and asserts:

1. exit code is zero and the JobRun is a succeeded `cli` run;
2. the new ParseRun is current and prior-run holdings remain;
3. all expected rows are returned by `active_hr_holdings_query`;
4. no `parse_run_id IS NULL` rows are written.

Add a runtime `reparse-all` test covering one success plus one failed/conflicting
accession and its final non-zero exit. Correct the two real-data verification
claims or repeat the check with active accession `0001325447-26-000018`, which
currently returns 602 rows through `active_hr_holdings_query`.

### Resolved findings

- **F7 replay safety:** resolved. Both replay commands use the
  ParseRun-backed `reparse_accession` job. Prior holdings are retained and
  failures/conflicts produce non-zero exits.
- **CLI locking:** resolved. `run_locked_job` reuses the existing
  lock-key/JobRun implementation, including the unique-index race fallback.
  `ingest-holdings`, `backfill`, and both replay commands use it.
- No new implementation defect was found in quarter selection, transaction
  boundaries, error propagation, or lock handling.

### Re-review verification

All commands ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- CLI, ParseRun, NT, and fail-loud targeted suites: **43 passed**.
- Full backend suite: **1113 passed, 3 warnings**.
- Real dev data, read-only:
  - original `0001325447-26-000009`: current ParseRun rows 602, product-visible
    rows **0**;
  - active restatement `0001325447-26-000018`: product-visible rows **602**;
  - global legacy NULL-ParseRun holdings: **0**.

## Original findings (pre-fix)

### [P1] The actively documented replay commands can erase product-visible holdings

**Locations:**

- `backend/app/cli/edgar.py:190-205`
- `backend/app/cli/edgar.py:277-305`
- `backend/app/services/edgar_ingestion.py:920-1026`
- `README.md:131-139`

`reparse-filing` and `reparse-all` still call the deprecated
`ingest_filing_holdings(..., replace_holdings=True)`. That function deletes all
holdings for the filing, then inserts replacements without a `parse_run_id`.
`active_hr_holdings_query` inner-joins `ParseRun13F`, so every replacement is
invisible to managers, Oracle's Lens, and ownership changes.

Concrete current-data impact: Berkshire filing
`0001193125-26-226661` (2026-Q1) has 90 holdings, all 90 visible through the
current ParseRun and zero legacy NULL-run rows. Running the README's
`reparse-filing` command for that accession would delete those 90 visible rows
and replace them with 90 product-invisible rows. `reparse-all` applies this to
every stored filing.

This should block T4 despite being pre-existing and recorded as F7. It is the
same CLI surface and same visibility invariant as F6, is advertised as a useful
operator command, and causes immediate production breakage. Backlog disclosure
does not make an executable destructive command safe.

**Required correction:** delegate both commands to the existing
ParseRun-backed `reparse_accession` job path. At minimum, disable the legacy
commands and remove their README instructions until F7 lands.

### [P2] CLI ingestion bypasses the existing quarter-scoped JobRun lock

**Locations:**

- `backend/app/cli/edgar.py:175-180`
- `backend/app/services/edgar_ingestion.py:1256-1262`
- `backend/app/services/thirteenf_admin_dashboard.py:1420-1421`
- `backend/app/services/thirteenf_admin_dashboard.py:2859-2864`
- `backend/app/services/thirteenf_admin_dashboard.py:3264-3338`

Both CLI entry points call `execute_job_payload` directly. That function is only
an unlocked wrapper around `_execute_job`; it neither creates a `JobRun` nor
checks `ingest_holdings:{quarter}`. The dashboard and pipeline already use that
lock and enforce concurrent-insert conflicts.

Concrete race: an operator runs `backfill` for proxy quarter `2026-Q2` while a
scheduled pipeline is ingesting `2026-Q2`. Both select the same filings and run
fetch, routing, parsing, and activation phases. Per-filing savepoints protect
siblings, but they do not serialize the two sessions. The unique current
ParseRun constraint may turn the race into a failed/partial job rather than
duplicate current data; it does not prevent duplicate EDGAR work, conflicting
activation writes, or misleading job status.

**Required correction:** expose one public synchronous locked-job runner and
use it from CLI, dashboard, and pipeline. The CLI should report an existing
active job as a conflict instead of executing an untracked second copy.

### [P2] The tests do not prove that either CLI command preserves F6

**Location:** `backend/tests/unit/test_13f_cli_ingest.py:138-164`

All delegation tests call `ingest_pending_holdings` with an injected
`ingest_fn`. They never invoke either Typer command, never exercise the default
`execute_job_payload` path, and never assert a current `parse_run_id` or query
the result through `active_hr_holdings_query`. A future edit that changes
`edgar.py` back to `ingest_filing_holdings` would leave all nine T4 tests green.

The existing job/parser tests validate components independently, but no test
pins their composition at the CLI boundary that regressed.

**Required correction:** add `CliRunner` wiring tests for both commands and one
stored-XML integration test that executes the real default path, then asserts
the inserted holdings reference a current ParseRun and are returned by
`active_hr_holdings_query`. A source guard forbidding the legacy call from
these commands is a smaller supplementary check, not a substitute for the
visibility assertion.

## Selection and transaction verdict

The new F5 selection is sound:

- A 2026-Q1 report filed on 2026-05-15 starts with proxy period 2026-Q2.
  `backfill` scopes to report Q1 plus next Q2, and `quarter_window("2026-Q2")`
  selects it.
- Q4/year rollover and Mar/Apr, Dec/Jan boundaries agree between
  `_date_to_quarter`, `next_quarter_label`, and `quarter_window`.
- Late amendments filed two or more quarters after their report period are not
  permanently lost. The index fetch is keyed to their actual filing quarter;
  while newly indexed, their proxy equals that filing date, which is in the
  corresponding `next(report quarter)` scope. They can be delayed until that
  filing quarter becomes the indexed next quarter, but are then included.
- The pending target list is computed once and sorted. Parsing moves a proxy
  period backward to the true report quarter and sets the raw infotable link;
  it cannot make the filing execute twice in the same loop. Subsequent runs
  converge.
- `period_of_report` is DB `NOT NULL`; both production insertion paths populate
  it. The defensive NULL filter does not hide a representable production state.

The new error/transaction behavior is also sound. Per-filing data errors become
`partial_success`; hard failures are isolated per quarter, prior successful
quarters are already committed, later quarters continue, and `except
typer.Exit: raise` preserves a non-zero CLI exit. The failed-parse
recoverability edge remains real but narrow and is adequately disclosed as a
low-severity admin-retry follow-up.

Operator help accurately explains that `--quarter` follows the filing's current
`period_of_report` (filing-quarter proxy before parse, report quarter after
parse). No stale `ingest-holdings --limit` caller was found.

## Verification

All test commands ran in Docker against
`postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test`.

- `alembic upgrade head`: passed.
- T4 plus fail-loud targeted tests: **15 passed**.
- Full backend suite: **1108 passed, 3 warnings**.
- `ingest-holdings --help`: dual proxy/report-period semantics displayed;
  removed `--limit` absent.
- Review changed only this results document; no production or test source was
  modified.
