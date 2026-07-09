# Release checklist — `13f-data-v1` (13F data-layer stabilization)

**Scope:** PRs #107 (T1) · #108 (T2) · #109 (T3) · #110 (T4) · #111 (T1-FU) ·
#112 (series-review fixes) — merged range `a786cfb..47bf92a` on `main`.

**Status:** rehearsed end-to-end on a prod-topology stack against a real
pre-upgrade snapshot (2026-07-09). Two defects found and fixed by the rehearsal.
Awaiting prod ground-truth report before tagging.

---

## 0. Facts established (do not re-derive)

| Fact | Value | How established |
|---|---|---|
| Migrations in this release | **none** | restored snapshot already at head `20260524120000`; `alembic upgrade head` on boot was a no-op |
| Deploy trigger | **auto** — `deploy.yml` on CI success for `main` | `.github/workflows/deploy.yml`; run for `e1c9631` succeeded 2026-07-09 20:00 |
| Prod host | a **separate** self-hosted runner (`ValuePilot-prod`) | no runner / no prod containers / ports 8101,3101 dead on the dev machine |
| Local `valuepilot_prod` | stale April artifact (alembic `20260423120000`, 0 filings) — **not prod** | read-only inspection |
| Prod schema after deploy | migrated by the api container's `alembic upgrade head &&` command | `docker-compose.prod.yml:59` |

**Consequence:** the code is already live on prod, but the `accepted_at` gate has
never run there. The release is therefore *code-deployed, data-migration
pending*. Nothing about the tag changes that — `deploy.yml` does not listen on
tags, so the tag is a retrospective label, not a trigger.

---

## 1. Pre-release gates (all green)

- [x] Canonical CI green on `main` (`e1c9631`) — backend, frontend unit, lint,
      production build, Rate Guard.
- [x] Backend suite green locally after the rehearsal fixes: **1163 passed**.
- [x] No new Alembic revisions → no migration rollback plan required.
- [x] Every review round closed: 7 P1 + 8 P2 + 1 test gap across four T1-FU
      review rounds, plus 2 P1 + 2 P2 in the cross-ticket series review, plus a
      follow-up on the gate itself. All reproduced before being fixed.
- [x] Deferred work recorded in `docs/BACKLOG.md` (NT/A ingestion; end-to-end
      pipeline test; `Holding13F` direct-query guard; failed-parse retry;
      cross-filer double-count guard; positions read model; Rate Guard
      observability ×2).

## 2. Deployment order (validated by rehearsal — not prose)

Prod must run these in order. Steps 2–4 are *data* work; step 1 already happened
automatically.

1. **Deploy code.** (auto, on merge to `main`.)
2. **`python -m scripts.t1fu_accepted_at_backfill` → must exit 0.**
   Fills `accepted_at` from stored primary docs and gates on
   "no filing has `accepted_at IS NULL`". Idempotent.
3. **Only now** may any authority path run: the Phase-5 sweep, `reparse-all` /
   `reparse-filing`, admin amendment resolution, or an `ingest_holdings` job for
   an old quarter.
4. **`python -m scripts.t3_attribution_rollout` → must exit 0.**
   Re-attributes holdings, recomputes `ownership_changes` + Oracle's Lens for
   every quarter through the locked JobRun mechanism, verifies hard invariants.
   Exit 2 = a job was already running; wait and re-run (not a failure).

**Why the order is not negotiable.** With `accepted_at` NULL, the authority's
missing-acceptance rule refuses to rank a competition pool of ≥2 and freezes the
group (`amendment_sort_warning` + `amendments_pending`) for a human. The
quarterly ingest job self-heals the quarter it processes (Phase 2 fills
`accepted_at` before the Phase 5 sweep) — but admin resolve, controlled reparse,
CLI reparse, and old-quarter jobs reach the authority with no prior fill.

## 3. Acceptance invariants (assert after step 4)

| Field | Required | Rehearsal result |
|---|---|---|
| `accepted_at_null` | 0 | 0 ✅ |
| `dup_active_groups` | 0 | 0 ✅ |
| `holdings_null_parse_run` | 0 | 0 ✅ |
| `holdings_under_current_run` | > 0 (may be < `holdings`: retained reparse history) | 25,070 ✅ |
| `attr_legacy` (`reported_for_other`/`shared`) | 0 | 4,050 → 0 ✅ |
| `attr_misattributed` (SOLE/DFND/OTR not `direct`) | 0 | 4,532 → 0 ✅ |
| `managers_zero_direct` | 0 | 7 → 0 ✅ |
| `ownership_changes` | > 0 | 18,260 → 22,518 ✅ |
| `lens_signals` | > 0 | 1,956 → 2,135 ✅ |
| `frozen_sort_warnings` | 0, or each one explained | 0 ✅ |

Product surface, through the prod image over HTTP:

- `GET /health` → 200 ✅ · `GET /login` → 200 ✅
- `…/managers/3984/holdings/changes?quarter=2026-Q1` → `available_with_caveat`,
  45 items ✅
- `…/managers/3984/holdings?quarter=2026-Q1` → 90 `common_holdings` +
  `SHARED_DISCRETION` caveat ✅ (the payload key is `common_holdings`/`options`,
  **not** `items`)
- The seven formerly-invisible flagship managers all recovered:
  Berkshire 543 direct / 210 changes · Oaktree 1,116 / 830 · Cantillon 375 / 191 ·
  Egerton 123 / 148 · Fairfax 144 / 154 · Scion 30 / 50 · Engaged 42 / 46.

## 4. Rehearsal record (2026-07-09)

Real prod is on another host and unreachable from the dev machine, so the
rehearsal used the **prod topology** locally: the same `docker-compose.prod.yml`,
the same `alembic upgrade head && uvicorn` entrypoint, both prod images built —
pointed at a disposable `valuepilot_staging` database restored from
`valuepilot_realdata_20260708.dump` (373 filings, the real **pre-T1-FU** state:
`accepted_at` NULL ×373, 4,050 legacy-attribution holdings, 7 flagship managers
with zero direct holdings). Ports 8102/3102, project `valuepilot-staging`,
scheduler + 13F worker forced off so no background job raced the runbook for the
`(manager, quarter_end_date)` advisory lock. Torn down afterwards; the dev, prod
and test databases were never touched.

Timings: gate 373 fills, ~1s. Rollout 73s (4,532 re-attributed; 6 quarters of
ownership_changes + Lens; verification passed).

### What the rehearsal caught that tests and review did not

1. **`enrich-stocks-edgar` in the README.** Deleted as broken in May 2026
   (`docs/tasks/2026-05-20_remove-noop-enrich-stocks-edgar.md`), still printed in
   two places as a Day-0 / quarterly step. A prod operator following the README
   would have hit "command not found" mid-bootstrap. Removed from the README.

2. **The gate's `at_risk_groups` diagnostic over-reported 8×.** It approximated
   the authority's competition pool as "the group has ≥2 filings". On the real
   snapshot that flagged **16 groups as "WILL FREEZE" when only 2 could** — a
   Berkshire quarter holding one original plus one non-restatement amendment has
   a *one-member* pool and resolves without any ordering evidence. An operator
   reading an inflated blocker list either aborts a safe deploy or learns to
   ignore the diagnostic. Fixed at the root: pool selection was extracted into
   `thirteenf_filing_detail.competition_pool()`, which the authority **and** the
   gate now both call, so the diagnostic can never drift from the rule it
   describes. Re-validated on the same snapshot: **16 → 2**, both genuine
   `restatement(2)` pools. Four new tests pin it, including the Berkshire shape.

Also corrected while writing the prod prompt: an acceptance assertion of mine
(`holdings_under_current_run == holdings`) that would false-fail on any database
carrying reparse history — which is the *designed* non-destructive behaviour.

## 5. Remaining before the tag

- [ ] **Prod ground truth.** Run `docs/runbooks/13f-data-v1-prod-release-agent-prompt.md`
      on the prod host (Phase 0 + Phase 1 are read-only). Two branches:
      `filings == 0` → code-live, data never bootstrapped, no active risk;
      `filings > 0 && accepted_at_null > 0` → the missing-acceptance rule is
      armed and `frozen_sort_warnings` may already be non-zero.
- [ ] **Execute steps 2–4** above on prod, per that prompt's gates.
- [ ] **Tag** the exact verified commit as `13f-data-v1` (a human pushes it;
      the tag triggers nothing).

## 6. Rollback

No migrations, so rollback is a code revert (`git revert` the merge commits, let
`deploy.yml` redeploy). Three things a revert does **not** cleanly undo:

**a. `amendment_status = 'deferred'` becomes un-interpretable — and a deferred
restatement resurrects itself.** `deferred` is a status T1-FU introduced. The
pre-T1-FU `_TERMINAL_AMENDMENT_STATUSES` is
`{applied, rejected, informational}` — it does **not** contain `deferred`. So
after a revert, `apply_amendment_policy` treats a deferred RESTATEMENT as
non-terminal, resets it to `pending_parse`, and the old authority then
auto-applies it. **An amendment an operator explicitly parked would go live
because of a code rollback.**

> Before reverting, run:
> ```sql
> SELECT accession_no, manager_id, quarter_end_date FROM filings_13f WHERE amendment_status = 'deferred';
> ```
> If any rows come back, convert them to `rejected` first — a status the old
> code honours — or accept that they will become active. As of 2026-07-09 there
> are **0** such rows on dev; prod's count is unknown until the read-only probe
> runs.

**b. Derived data reflects the new rules.** If `t3_attribution_rollout` has
already run, `holding_attribution_status` and the recomputed `ownership_changes`
/ Oracle's Lens rows follow the post-T3 attribution ruling. They are derived:
re-running the previous code's `backfill-attribution` plus the recomputes
restores them.

**c. `accepted_at` must not be rolled back.** It is authoritative SEC metadata
parsed from the stored primary docs (Eastern wall time → UTC). Nothing in the
old code writes it, so a revert simply leaves it populated — which is harmless
and, on a re-deploy, saves running the gate again.

## 7. Concurrency with the production scheduler

Prod runs a weekly scheduler (Mondays 06:00 UTC) that fires the quarterly
pipeline, plus a background 13F job worker. Both interact with the runbook:

- **The quarterly pipeline is self-safe.** Its `ingest_holdings` job fills
  `accepted_at` in Phase 2 (`backfill_period_routing`) *before* its Phase 5
  authority sweep, so it cannot trip the missing-acceptance rule on the quarter
  it is processing — with or without this runbook having run.
- **It will, however, contend for locks.** Both the pipeline and
  `t3_attribution_rollout` take JobRun `lock_key`s and the
  `(manager, quarter_end_date)` advisory lock. A collision surfaces as the
  rollout script **exiting 2** — a conflict to wait out and re-run, never a
  failure to force past. The gate script takes no JobRun lock and is safe to run
  at any time.

So "prefer a quiet window" is an efficiency preference, not a safety
requirement. Do not disable the scheduler to run the runbook; just re-run the
rollout if it exits 2.
