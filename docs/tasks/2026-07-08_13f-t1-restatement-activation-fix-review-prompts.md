# Review prompts — T1 (13F 摄取管线多重修正案激活修复)

Task doc: [`2026-07-08_13f-t1-restatement-activation-fix.md`](./2026-07-08_13f-t1-restatement-activation-fix.md)
PO plan: [`2026-07-08_13f-real-data-findings-po-plan.md`](./2026-07-08_13f-real-data-findings-po-plan.md)
Status: **uncommitted working-tree change** (no branch/PR yet). Reviewers must
read the diff with `git diff HEAD -- backend/`.

## What changed

Single-function fix to `reconcile_restatement_activation`
(`backend/app/services/thirteenf_holdings_ingest.py`, ~L93–159):

1. **Latest-wins guard** — before demoting/activating, query for a *later-filed
   parsed RESTATEMENT* in the same `(manager_id, quarter_end_date)` (tie-break on
   `id`). If one exists, return `False` (no-op). Intent: this function converges
   to "newest successfully-parsed restatement wins" no matter which filing it is
   called on, so the caller's per-filing loop is order-independent.
2. **`session.flush()` after demotions, before self-activation** — so
   SQLAlchemy's PK-ordered UPDATE emission can't fire a lower-id activation
   before a higher-id demotion and trip `uq_active_filing_per_manager_period`.

Plus 2 new tests in `backend/tests/unit/test_13f_amendment_policy.py`
(`test_reconcile_restatement_latest_wins_regardless_of_call_order`,
`test_reconcile_restatement_demote_then_activate_is_constraint_safe`).

## Context a reviewer cannot see from the diff alone

- **The production incident that motivated this:** first real EDGAR ingest
  (2026-07-08) crashed the `ingest_holdings` job on manager 4007 / period
  2025-09-30, filings `4956`(13F-HR) → `5000`(13F-HR/A RESTATEMENT) →
  `5001`(13F-HR/A RESTATEMENT). Phase 3 left `5001` active; Phase 5 re-reconciled
  `5000` and, in one flush, tried to activate `5000` while demoting `5001` →
  `psycopg2.errors.UniqueViolation` on `uq_active_filing_per_manager_period` →
  whole quarter job rolled back.
- **Two production callers** of the function (both must stay correct):
  - `backend/app/services/thirteenf_admin_dashboard.py` `_execute_ingest_job`
    Phase 5 loop (`~L3568–3576`): `for filing in filings: reconcile...`, iterated
    `filed_at asc`, run AFTER a Phase-4 `session.commit()` barrier.
  - `backend/app/services/thirteenf_holdings_ingest.py` `_do_ingest_holdings`
    (`~L286`): called INSIDE the ingest savepoint (`session.begin_nested()`),
    after the holdings bulk-insert + `filing.parse_status="succeeded"`, before
    `sp.commit()`.
- **The dev DB `valuepilot` holds real data** (82 managers / 25k holdings /
  18k ownership_changes) and **pytest cannot run against it** (177+ tests assume
  an empty DB; `_clear` hits `ownership_changes` FKs). Run tests against the
  isolated DB instead — real data untouched:
  ```
  TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
  ```
  (If `valuepilot_test` doesn't exist:
  `docker exec projects-infra-postgres-1 sh -lc "PGPASSWORD=infra_admin psql -U infra_admin -d postgres -c 'CREATE DATABASE valuepilot_test OWNER valuepilot'"`.)
- **Already verified by the author** (independently re-confirm, don't trust):
  full backend suite **1065 passed**; both new tests go genuinely RED without the
  fix (stash the source change and re-run); the `constraint_safe` test fails on
  the *correct* constraint (`uq_active_filing_per_manager_period`) when only the
  `flush()` is removed.
- **Author's own note in the code** (pre-existing, near the Phase 5 heuristic):
  "Correct active-filing selection across amendments belongs in a single shared
  policy (tracked separately)." Treat that as an open altitude question, not a
  settled decision.

The three prompts below are for **three different external agents** reviewing the
same change from different angles. Run in parallel; collect findings under
`2026-07-08_13f-t1-restatement-activation-fix-review-results.md`.

---

## Prompt 1 — Correctness & concurrency reviewer (the critical angle)

```
You are a senior backend engineer reviewing a concurrency/ordering fix to a
Postgres-backed ingestion pipeline. A single SQLAlchemy function decides which
13F filing is the "active" one for a (manager, quarter_end_date) when a manager
files multiple RESTATEMENT amendments. A unique partial constraint
uq_active_filing_per_manager_period enforces at most one active filing per
(manager_id, quarter_end_date). The fix must (a) never crash that constraint and
(b) always converge to the latest successfully-parsed restatement.

Repository: ValuePilot (local). The change is UNCOMMITTED — read it with
`git diff HEAD -- backend/`.
Read first:
  - backend/app/services/thirteenf_holdings_ingest.py — reconcile_restatement_activation
    (the whole function) AND _do_ingest_holdings (the savepoint caller at ~L286).
  - backend/app/services/thirteenf_admin_dashboard.py — _execute_ingest_job,
    especially Phase 3 (activation during parse), Phase 4 (column heal +
    solo-HR activation), and Phase 5 (the reconcile loop, ~L3568–3576).
  - AGENTS.md → "Critical invariants" (esp. is_current per-period semantics).
  - docs/tasks/2026-07-08_13f-t1-restatement-activation-fix.md and the "Context"
    section of this review-prompts doc (production incident + the two callers).

Probe specifically, with a concrete failing input for each real finding:
  1. Does ANY ordering leave a period with NO active filing, or the WRONG one?
     Enumerate: latest restatement parse_status='failed' with an earlier
     succeeded one; latest restatement not yet ingested when an earlier one
     reconciles; restatements ingested out of filed_at order; a re-ingested
     original with a higher id than the restatement.
  2. filed_at NULL: what does the latest-wins guard do when filing.filed_at is
     NULL, or when a sibling's filed_at is NULL? Can two restatements both pass
     the guard? Is the result non-deterministic or crashing? Is filed_at
     nullable in the model?
  3. The added session.flush() runs INSIDE _do_ingest_holdings' savepoint,
     after a holdings bulk-insert. Does flushing there change failure/rollback
     semantics, surface an IntegrityError earlier, or interact badly with the
     enclosing begin_nested()? Is autoflush (triggered by the two SELECTs) doing
     anything the author didn't intend?
  4. Concurrency: two workers ingest different restatements of the same period
     at once. The guard is a SELECT, not a lock. Can the interleaving produce
     two active rows (caught only at commit as an IntegrityError that aborts a
     job), or silently the wrong winner? Is that acceptable given the job model?
  5. Is "latest filed_at wins" the correct 13F semantic for competing
     RESTATEMENTs, or should it be highest amendmentNo / latest accepted_at?
  6. Idempotency: running Phase 5 twice on the same data — any drift?

For each finding give file:line, the exact input/state, and the wrong outcome.
Rank by severity. If the logic is sound, say so and justify why each ordering
converges. Do NOT propose style changes.
```

---

## Prompt 2 — Test integrity & coverage reviewer

```
You are reviewing the TESTS for a concurrency fix, not just the code. The author
already caught one false-positive test in self-review (a "constraint safe" test
that passed even with the fix removed because it constructed a naturally-safe
id ordering) and a fixture bug (two filings defaulting is_latest_for_period=True,
colliding on a DIFFERENT unique constraint and masking a false RED). Your job is
to find any remaining false confidence.

Repository: ValuePilot (local), UNCOMMITTED change — `git diff HEAD -- backend/`.
Read first:
  - backend/tests/unit/test_13f_amendment_policy.py — the two new tests and the
    _restatement_chain helper; also the pre-existing reconcile tests they sit next to.
  - backend/app/services/thirteenf_holdings_ingest.py — reconcile_restatement_activation.
  - The "Context" section of this review-prompts doc (how to run tests against
    the isolated valuepilot_test DB — the dev DB has real data and will fail).

Do this concretely:
  1. Re-run the red/green proof yourself. Stash ONLY the source change and
     confirm both new tests fail. Then restore only the flush-removal and confirm
     the constraint_safe test fails on constraint uq_active_filing_per_manager_period
     specifically (not some fixture constraint). Report if either is not genuinely red.
  2. Coverage gaps: is there a test for 3+ restatements? equal filed_at tie-break
     on id? a latest restatement with parse_status='failed'? the _do_ingest_holdings
     savepoint caller (both current tests exercise reconcile directly, NOT through
     the ingest path or Phase 5)? Name each missing case with the input it needs.
  3. Are the assertions strong enough — do they pin the WINNER's identity and the
     losers' demotion, or just "no crash"? Could a wrong-winner bug pass?
  4. Fixture realism: do f_restate.id < f_active.id and the is_latest_for_period
     assignments reflect a state the real pipeline can actually produce?
  5. Any OTHER nearby test that is a false guard (passes regardless of the code
     path it claims to protect)?

Output: list each gap/weak test with the concrete case to add. If coverage is
adequate, justify why the enumerated hazards are each pinned by a test.
```

---

## Prompt 3 — Altitude / design reviewer

```
You are a staff engineer judging whether this fix is at the right depth or is a
band-aid. The change adds "latest restatement wins" logic plus a flush-ordering
guard INSIDE reconcile_restatement_activation. Meanwhile the codebase already has
active-filing activation logic scattered across at least three places:
_do_ingest_holdings (per-parse), _execute_ingest_job Phase 4 (solo-13F-HR
auto-activation heuristic) and Phase 5 (restatement reconcile loop) — and a code
comment admits "Correct active-filing selection across amendments belongs in a
single shared policy (tracked separately)."

Repository: ValuePilot (local), UNCOMMITTED — `git diff HEAD -- backend/`.
Read first:
  - backend/app/services/thirteenf_holdings_ingest.py — reconcile_restatement_activation.
  - backend/app/services/thirteenf_admin_dashboard.py — _execute_ingest_job
    Phases 3/4/5 (all the places that set is_active_for_manager_period).
  - backend/app/services/thirteenf_holdings_query.py — active_hr_holdings_query
    (the PRD §7.3 read contract this all feeds).
  - docs/prd/13f_automation_and_resilience_prd.md (amendment / active-filing rules).

Judge:
  1. Is "which filing is active for a period" now decided in one authority or
     several? Does this fix reduce or add to the scatter? Would a single
     select_active_filing(manager, period) function (originals + amendments +
     restatements, one ordering rule) be the correct generalization, and is that
     in scope for a P0-eng crash fix or a proper follow-up ticket?
  2. Is relying on flush() ORDERING to satisfy a unique constraint fragile?
     Compare alternatives: a DEFERRABLE INITIALLY DEFERRED constraint; an
     explicit "demote all, flush, then activate" contract documented as the
     invariant; or reworking so activation never overlaps. Recommend one.
  3. Does the latest-wins guard duplicate intent already expressed by
     version_rank / is_latest_for_period, and could those existing fields be the
     single source of truth instead of a bespoke filed_at/id query?
  4. Smallest change that removes the crash for THIS ticket vs. the right
     long-term shape — state both, and whether the diff picked the right line.

Output: a depth verdict (band-aid / acceptable-scoped-fix / correct-generalization)
with reasoning, plus one concrete recommendation for the follow-up if warranted.
Do not rewrite the code; judge the shape.
```
