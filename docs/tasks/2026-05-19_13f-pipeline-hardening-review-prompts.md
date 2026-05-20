# 13F Pipeline Hardening — Review Prompts (PRs #45–#55)

This round shipped **11 PRs** that took the prod 13F pipeline from "completely
non-functional" to "end-to-end automatic: set `THIRTEENF_START_QUARTER`, the
system ingests filings → holdings → CUSIP enrichment → Oracle's Lens scoring →
`/watchlist` renders 13F columns." It also accumulated real churn (the reconcile
skip criterion was rewritten three times) and at least one bug that reached prod
behind a swallowed exception. It deserves a careful second pass.

These prompts are written for **independent external review agents**. Each is
self-contained — an agent with no session memory can act on it. Run them as
separate agents; they intentionally overlap a little so each is complete alone.

---

## Shared context (read first — applies to every review below)

- **Repo**: ValuePilot. Backend is Python / FastAPI / SQLAlchemy 2.x / PostgreSQL.
- **Project rules**: read `AGENTS.md` and `CLAUDE.md` at repo root before
  reviewing. Two rules matter especially here:
  - *"Schema changes — no band-aids"*: DB constraint/shape problems must be fixed
    with an Alembic migration, never a code-level workaround.
  - The locked `metric_facts.is_current` note: this team treats **per-period
    currency contracts** as load-bearing. `Filing13F.is_active_for_manager_period`
    is an analogous per-(manager, period) currency flag — scrutinise any change
    to how it is set.
- **The 11 PRs** (all merged to `main`):

  | PR | Title |
  |----|-------|
  | #45 | Auto-fetch missing infotable XML in `ingest_holdings` job |
  | #46 | Add `THIRTEENF_START_QUARTER`: enqueue quarterly pipeline on boot |
  | #47 | CUSIP enrichment: don't crash on holdings with NULL `quarter_end_date` |
  | #48 | Deploy: preserve untracked files in workspace (`actions/checkout` clean:false) |
  | #49 | `ingest_holdings`: route `period_of_report` / `quarter_end_date` / `report_quarter` |
  | #50 | `ensure_filing_infotable_doc`: self-heal when body files missing on disk |
  | #51 | `ingest_holdings`: drop guard so `ensure_filing_infotable_doc` always runs |
  | #52 | Fix import: `route_period` (no underscore prefix) |
  | #53 | Reconcile: skip criterion uses data state, not job status |
  | #54 | Wire `oracles_lens_score_backfill` into dispatcher + `quarterly_pipeline` |
  | #55 | Reconcile: anchor skip criterion on `oracles_lens_signals` |

- **How to inspect**: `gh pr view <N>`, `gh pr diff <N>`. For the full combined
  diff: `git diff 8a67920..origin/main`. Primary files:
  - `backend/app/services/edgar_ingestion.py` (`ensure_filing_infotable_doc`,
    `backfill_period_routing`, `backfill_period_of_report`)
  - `backend/app/services/thirteenf_admin_dashboard.py` (`_execute_ingest_job`
    4-phase rewrite, `_execute_job` dispatcher, `quarterly_pipeline` stage 5,
    `_JOB_LOCK_BUILDERS`)
  - `backend/app/services/thirteenf_start_quarter.py` (reconcile, `_has_meaningful_coverage`)
  - `backend/app/services/cusip_enrichment.py` (#47 null fix)
  - `backend/app/core/config.py`, `backend/app/main.py` (boot-time reconcile hook)
  - `.github/workflows/deploy.yml` (#48)
- **Run tests**: `docker compose exec api pytest -q` (full suite, inside the container).

---

## Review 1 — Pipeline & job-orchestration correctness

**Reviewer profile:** senior backend engineer fluent in SQLAlchemy session /
transaction semantics and the 13F job worker.

You are reviewing the correctness of the 13F ingestion pipeline changes in
PRs #45, #49, #50, #51, #52, #54. Focus on **transaction boundaries and
orchestration**, not style.

Critical things to verify:

1. **`_execute_ingest_job` four-phase structure** (`thirteenf_admin_dashboard.py`).
   The function now runs Phase 1 (fetch XML) → Phase 2 (`backfill_period_routing`)
   → Phase 3 (parse holdings) → Phase 4 (bulk heal UPDATEs), all on a single
   `session`. Phases 1 and 3 contain per-filing `try/except` blocks that call
   **`session.rollback()`** on failure. Determine precisely: does a `session.rollback()`
   inside the Phase 3 loop discard the `body_path` / routing writes made in
   Phases 1–2? `session.flush()` is called between phases but not `commit()`.
   Trace where the surrounding transaction actually commits (the job worker in
   `thirteenf_job_worker.py`, and `_execute_pipeline_stage_job`). State definitively
   whether mid-loop rollback can lose earlier-phase work, and if so, how to fix it
   (e.g. SAVEPOINT per filing, or commit between phases).

2. **`ensure_filing_infotable_doc`** (`edgar_ingestion.py`) — the self-heal added
   in #50 and the guard removed in #51. Confirm: when the DB row is linked but the
   on-disk file is gone, it re-fetches; when both are present, it short-circuits
   without a network call; when the manager has no CIK, it returns `None`. Check
   for redundant re-fetches now that #51 calls it unconditionally for every filing.

3. **`quarterly_pipeline` stage 5** (#54). `oracles_lens_score_backfill` calls
   `compute_signal_weighted_scores`. Verify the commit semantics: does that
   function commit internally, and does that interact badly with
   `_execute_pipeline_stage_job`'s own commit / the worker's lease lifecycle?
   Confirm a scoring failure leaves the quarter `partial_success` without undoing
   stages 1–4.

4. **`route_period` import** (#52). PR #49 imported `_route_period`; the real
   name is `route_period`. The `ImportError` was swallowed for a full deploy
   cycle. Verify #52 fixed every call site and that nothing else imports a
   wrong name from `thirteenf_filing_detail`.

Deliverable: a findings list ranked by severity (blocker / should-fix / nit),
each with file:line and a concrete recommendation. Explicitly answer the
transaction-boundary question in item 1 — it is the highest-value output.

---

## Review 2 — Data-healing & data-contract safety

**Reviewer profile:** engineer who owns data integrity / the `metric_facts` &
13F data contracts; comfortable judging Alembic-migration-vs-code tradeoffs.

You are reviewing the data-mutation safety of PRs #47, #49, #53, #54, #55.

Critical things to verify:

1. **Phase 4 bulk healing UPDATEs** in `_execute_ingest_job`
   (`thirteenf_admin_dashboard.py`). The job issues bulk `UPDATE` statements that
   backfill `Holding13F.quarter_end_date`, `Holding13F.report_quarter`, and
   `Filing13F.is_active_for_manager_period`. `AGENTS.md` says data/shape problems
   should be fixed with an Alembic migration, not a code-level workaround. Judge:
   is per-job idempotent healing the right call here, or should the one-time
   backfill of pre-existing rows have been a migration? Consider that the healing
   also has to apply to *future* rows the modern ingest path leaves unset — so
   the real question may be "fix the ingest path so the columns are never NULL,"
   not "heal repeatedly." Recommend the correct end state.

2. **`is_active_for_manager_period = is_latest_for_period` heuristic** (#54,
   Phase 4c). The modern `_do_ingest_holdings` only sets
   `is_active_for_manager_period` for `RESTATEMENT` amendments; #54 mirrors
   `is_latest_for_period` onto it for plain HR/HR-A filings, justified by "the V1
   universe has 0 real amendments." Stress-test this: what happens the first time
   a genuine `13F-HR/A` amendment lands with `is_amendment=True`? Does the
   heuristic corrupt the active-filing contract (two active filings for one
   manager+period, or the wrong one active)? Compare against the per-period
   currency discipline in the `CLAUDE.md` `metric_facts.is_current` note. State
   whether this heuristic is safe to leave in place or needs a follow-up.

3. **`backfill_period_routing`** (`edgar_ingestion.py`, #49). It rewrites
   `Filing13F.period_of_report` and runs an `is_latest_for_period` recompute dance
   (clear-all → apply → `_recalculate_version_ranks`). Verify this is correct and
   safe under partial failure / concurrent pipeline runs for the same manager.
   Check the `route_period` `needs_review` / `PERIOD_TOO_FAR_FROM_QUARTER_END`
   branches are handled (not silently dropped).

4. **#47 CUSIP enrichment null guard.** `_apply_mappings_to_holdings` skips the
   temporal-validity filter when `quarter_end_date IS NULL`. Confirm this can't
   mis-link a CUSIP across a corporate-action boundary once real `valid_from` /
   `valid_to` ranges exist.

5. **Reconcile criterion** (#53 → #55). The skip criterion changed twice in one
   session (`JobRun.status` → `Filing13F.quarter_end_date` → `oracles_lens_signals`).
   Confirm the final anchor (`oracles_lens_signals` rows exist for the quarter) is
   genuinely terminal and won't repeat the "intermediate signal satisfied but
   pipeline incomplete" failure. Flag the known edge case (a quarter where no
   stock clears `min_holders` stays at 0 signals and re-enqueues every boot) —
   is that acceptable, or should it be bounded?

Deliverable: findings ranked by severity, each with file:line. Items 1 and 2
are the highest-value — give a clear yes/no on whether the healing approach and
the `is_active` heuristic are safe to keep, and what the proper fix is if not.

---

## Review 3 — Deploy & infrastructure

**Reviewer profile:** DevOps engineer familiar with GitHub Actions self-hosted
runners and Docker bind mounts.

You are reviewing PR #48 (`.github/workflows/deploy.yml`) and the broader
persistent-storage design it patches.

Context: the prod 13F pipeline writes raw EDGAR files under
`storage/edgar_raw/`, bind-mounted into the `api` container. PR #35 (earlier
round) added the bind mount; #48 adds `clean: false` to `actions/checkout`
because the default `git clean -ffdx` was wiping that directory on every deploy.

Verify:

1. **`clean: false` accumulation risk.** With clean disabled, untracked files
   in the runner workspace are never garbage-collected. Over many deploys, will
   stale artifacts accumulate (orphaned `.pyc`, removed-but-not-deleted source
   files, old build output, deleted `storage/` subtrees)? Could a stale untracked
   file ever shadow a tracked file or change build behavior? Recommend whether
   `clean: false` is acceptable long-term or whether a more targeted approach is
   warranted.

2. **Storage location.** Is bind-mounting persistent data *inside* a CI/CD
   workspace the right design at all? Evaluate moving `storage/edgar_raw` and
   `storage/uploads` to a stable path outside the runner workspace (e.g.
   `~/valuepilot-data/`) so deploys physically cannot touch it. Weigh the
   migration cost against the recurring fragility.

3. Confirm #48 does not weaken runner isolation or affect the `.env` /
   `.env.prod` install step.

Deliverable: a short recommendation (keep `clean: false` as-is / harden it /
move storage out of the workspace), with reasoning.

---

## Review 4 — Error-masking & test-adequacy audit

**Reviewer profile:** quality-focused engineer; treat this as a process review,
not just a code review.

This round had warning signs worth a dedicated pass:

- The reconcile skip criterion was rewritten **three times** (#46 → #53 → #55).
- A `route_period` vs `_route_period` `ImportError` (#52) reached prod because a
  broad `try/except` in `_execute_ingest_job` Phase 2 swallowed it — CI was green.
- Multiple layered self-heals (#50, #51) were needed because earlier fixes
  didn't cover the post-deploy storage-wipe path.

Audit, across the diff `git diff 8a67920..origin/main`:

1. **Broad `except Exception` blocks added or relied on this round.** For each,
   determine whether it can swallow a programming error (ImportError, AttributeError,
   TypeError) and mask it as a benign "stage failed, continue." Recommend
   narrowing each to the expected exception types, or at minimum asserting that
   genuine bugs surface (fail-loud in tests / non-prod).

2. **Test adequacy.** Several bugs reached prod despite green CI because the
   tests mocked the very component that was broken (e.g. there is no direct unit
   test exercising `backfill_period_routing` end-to-end, which is why the
   `route_period` import bug slipped). Identify the highest-value missing tests —
   especially integration-level tests that would exercise `_execute_ingest_job`'s
   four phases against a real (test) DB without mocking the routing/scoring
   internals. List concrete test cases to add.

3. **Reconcile-criterion stability.** Read #46, #53, #55 in sequence. Confirm the
   final criterion is sound and that no *other* part of the codebase still
   anchors "is this done?" logic on an intermediate signal that a future change
   could satisfy prematurely.

4. **Idempotency claims.** Several PRs assert their operations are idempotent
   ("re-running a near-complete quarter is cheap / a no-op"). Spot-check that
   claim for `backfill_period_routing`, `ensure_filing_infotable_doc`, and
   `compute_signal_weighted_scores` — is re-running genuinely side-effect-free, or
   does it re-issue EDGAR network calls / rewrite rows unnecessarily?

Deliverable: (a) a list of broad-except blocks with narrowing recommendations,
(b) a prioritised list of missing tests with concrete cases, (c) a yes/no on
whether the final reconcile criterion is stable.

---

## Suggested dispatch

| Review | Reviewer profile | Priority |
|--------|------------------|----------|
| 1 — Pipeline & orchestration correctness | Senior backend / SQLAlchemy txn semantics | **High** — the transaction-boundary question is load-bearing |
| 2 — Data-healing & data-contract safety | Data-integrity owner | **High** — the `is_active` heuristic can corrupt a contract |
| 3 — Deploy & infrastructure | DevOps | Medium |
| 4 — Error-masking & test adequacy | Quality / process | **High** — directly explains the churn this round |

Security review was considered and judged low-value for this batch: the changes
touch no auth, no user-input parsing, and no new external-facing surface (EDGAR
fetches are server→SEC, server-initiated). A quick scan can be folded into
Review 3 if desired.
