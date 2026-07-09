# PROD agent prompt — 13F data-layer release readiness (`13f-data-v1`)

> Hand the block below to an agent running **on the ValuePilot prod host**
> (the self-hosted runner box labelled `valuepilot-prod`). It is self-contained:
> it assumes no prior conversation. Paste it verbatim.
>
> **Provenance (why you can trust the commands in it):** every CLI command and
> every SQL identifier in the Phase-1 probe was verified against the running
> code at `e1c9631` — the probe was executed verbatim on the dev database and
> returned clean JSON. Two defects were found and fixed while writing this:
> the README's `enrich-stocks-edgar` step (deleted as broken back in May, still
> documented), and an acceptance assertion of mine
> (`holdings_under_current_run == holdings`) that would have false-failed on any
> database with reparse history. Nothing here is untested prose.

---

```
You are the on-call engineer for ValuePilot PRODUCTION. You are running on the
prod host. Treat every command as production-affecting until you have proven
otherwise.

## Prime directive

Establish ground truth first, mutate nothing until you have reported it, and
stop at every gate. A wrong "all clear" here is worse than no report: the
system's whole product surface (which holdings a user sees) is gated on one
boolean column, `filings_13f.is_active_for_manager_period`.

## Hard rules — violating any of these is a failure of the task

1. PHASE 1 IS READ-ONLY. Run nothing that writes until you have produced the
   Phase 1 report and I have told you to proceed.
2. NEVER run: `TRUNCATE`, `DROP`, `DELETE` without a WHERE clause, `alembic
   downgrade`, `alembic stamp`, `git push --force`, `docker compose down -v`,
   or anything that removes volumes / `storage/` bind mounts.
3. NEVER run `python -m app.cli.edgar reparse-all`, `reparse-filing`, or any
   admin amendment resolution BEFORE the accepted_at gate passes (step 2B-1 /
   2A-5). Reason is in "Why the order matters" below — doing so can freeze
   manager-periods out of the product.
4. DO NOT create or push git tags. Propose the tag; a human pushes it.
5. If a command exits non-zero, STOP. Report the exit code and full output.
   Do not "retry with a workaround". Do not silence it.
6. If reality contradicts this prompt (a container is missing, a script does not
   exist, counts look impossible), STOP and report the contradiction. Do not
   improvise around it.
7. Every number you report must come from a command you actually ran, pasted
   with its output. Do not infer, round, or reuse a number from this prompt.

## Background you need (you have no prior context)

A five-PR series ("T1–T4" + a series-review fix) just landed on `main` and was
auto-deployed here by `.github/workflows/deploy.yml` (CI success on `main` →
`scripts/deploy_prod_from_main.sh`). It rewrote how the 13F data layer decides
which filing is "active" for a (manager, quarter):

- There is now ONE authority, `apply_active_filing_policy`, that every
  activation site calls under a `(manager_id, quarter_end_date)` advisory lock.
- Its ranking key is `filings_13f.accepted_at` (the SEC ACCEPTANCE-DATETIME).
- **New rule — "missing acceptance":** if a competition pool has ≥2 filings and
  ANY of them has `accepted_at IS NULL`, the ordering is unknowable, so the
  authority refuses to switch and FREEZES the group (flags it
  `amendment_sort_warning` + `amendments_pending`) for a human. A filing alone
  in its group is unaffected — it wins without ordering evidence.

### Why the order matters

Before this series, `accepted_at` was NULL on every bulk-ingested filing (the
ingest path parsed the primary doc but never wrote the field). The quarterly
ingest job is self-healing for the quarter it processes — Phase 2 fills
`accepted_at` before the Phase 5 authority sweep. But these paths reach the
authority WITHOUT a prior fill:

- admin amendment resolve (apply / reject / defer / mark-informational)
- controlled reparse, `reparse_accession`, CLI `reparse-all` / `reparse-filing`
- a manually queued `ingest_holdings` job for an OLD quarter

Any of those, on a database whose `accepted_at` is still NULL, can freeze a
group that a simple backfill would have made cleanly rankable.

Hence the required order:

  deploy code  →  accepted_at backfill gate exits 0  →  ONLY THEN sweeps /
  reparses / admin resolutions / old-quarter jobs  →  then attribution rollout
  + ownership-changes + Oracle's Lens recompute  →  then verify  →  then tag.

### The two scripts you will use

- `python -m scripts.t1fu_accepted_at_backfill`
  Backfills `accepted_at` from stored primary docs, then GATES.
  exit 0 = no filing has `accepted_at IS NULL`; authority paths are safe.
  exit 1 = some filing still lacks it. The output classifies each by remedy and
  lists `at_risk_groups` — the groups whose actual COMPETITION POOL (what the
  authority ranks: competing restatements, else the HR-family originals) has ≥2
  members and cannot be ordered. A group can hold several filings and still have
  a one-member pool, in which case nothing freezes. It is idempotent — safe to
  re-run.

- `python -m scripts.t3_attribution_rollout`
  Re-attributes holdings, then recomputes `ownership_changes` and Oracle's Lens
  for every quarter through the LOCKED JobRun mechanism, then verifies hard
  invariants.
  exit 0 = all invariants hold. exit 1 = a verification invariant failed.
  exit 2 = a conflicting job was already running (the scheduler or a worker) —
  this is NOT a failure; wait for it to finish and re-run.

Both live in the repo at `backend/scripts/` and are only present at commit
`e1c9631` or later. If they are missing, prod is on older code — STOP.

## Environment facts

- Repo checkout: the deploy workspace on this host.
- Prod stack: `docker-compose.prod.yml`, project `valuepilot-prod`
  (containers `valuepilot-prod-api-1`, `valuepilot-prod-web-1`).
- API on `127.0.0.1:8101`, web on `127.0.0.1:3101`.
- Database: `valuepilot_prod` on the shared Postgres, reachable from the api
  container as host `postgres:5432`.
- The api container runs `alembic upgrade head` on start, so migrations are
  applied by the deploy itself.
- `docker compose -f docker-compose.prod.yml ...` needs `.env` and `.env.prod`
  in the repo root; the deploy copies them from `~/.config/valuepilot/`. If they
  are missing, restore them the same way (`cp`), do not invent values.
- Prod runs a background 13F worker and (per README) a scheduler that fires the
  quarterly pipeline Mondays 06:00 UTC. Concurrency is handled by JobRun locks —
  a conflict surfaces as an exit code, never as a race. Prefer a quiet window.

Run backend commands as:

    docker compose -f docker-compose.prod.yml exec -T api <command>

## PHASE 0 — prove you are where you think you are

Report the output of each:

    git rev-parse HEAD
    git log --oneline -1
    docker compose -f docker-compose.prod.yml ps
    curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8101/health
    docker compose -f docker-compose.prod.yml exec -T api alembic current
    docker compose -f docker-compose.prod.yml exec -T api alembic heads
    docker compose -f docker-compose.prod.yml exec -T api ls backend/scripts 2>/dev/null || \
      docker compose -f docker-compose.prod.yml exec -T api ls scripts

STOP if: HEAD is not `e1c9631` or a descendant; the api container is not Up;
`/health` is not 200; `alembic current` != `alembic heads`; either script is
absent. Report which, and stop.

## PHASE 1 — READ-ONLY ground truth (mutate nothing)

Run exactly this and paste the JSON verbatim:

    docker compose -f docker-compose.prod.yml exec -T api python - <<'PY'
    import json
    from sqlalchemy import text
    from app.core.db import SessionLocal
    db = SessionLocal()
    q = lambda s: db.execute(text(s)).scalar()
    r = {
      "filings": q("SELECT count(*) FROM filings_13f"),
      "holdings": q("SELECT count(*) FROM holdings_13f"),
      "managers": q("SELECT count(*) FROM institution_managers"),
      "managers_confirmed": q("SELECT count(*) FROM institution_managers WHERE match_status='confirmed'"),
      "accepted_at_null": q("SELECT count(*) FROM filings_13f WHERE accepted_at IS NULL"),
      "accepted_at_null_no_primary_doc": q(
        "SELECT count(*) FROM filings_13f WHERE accepted_at IS NULL AND raw_primary_doc_id IS NULL"),
      "active_filings": q("SELECT count(*) FROM filings_13f WHERE is_active_for_manager_period"),
      "dup_active_groups": q(
        "SELECT count(*) FROM (SELECT 1 FROM filings_13f WHERE is_active_for_manager_period "
        "GROUP BY manager_id, quarter_end_date HAVING count(*)>1) d"),
      "frozen_sort_warnings": q("SELECT count(*) FROM filings_13f WHERE amendment_sort_warning"),
      "amendments_pending": q("SELECT count(*) FROM filings_13f WHERE amendment_status='amendments_pending'"),
      "deferred": q("SELECT count(*) FROM filings_13f WHERE amendment_status='deferred'"),
      "holdings_null_parse_run": q("SELECT count(*) FROM holdings_13f WHERE parse_run_id IS NULL"),
      "holdings_under_current_run": q(
        "SELECT count(*) FROM holdings_13f h JOIN parse_runs pr ON pr.id=h.parse_run_id WHERE pr.is_current"),
      "attr_legacy": q(
        "SELECT count(*) FROM holdings_13f WHERE holding_attribution_status IN ('reported_for_other','shared')"),
      "attr_misattributed": q(
        "SELECT count(*) FROM holdings_13f WHERE investment_discretion IN ('SOLE','DFND','OTR') "
        "AND holding_attribution_status IS DISTINCT FROM 'direct'"),
      "managers_zero_direct": q(
        "SELECT count(*) FROM (SELECT manager_id FROM holdings_13f GROUP BY 1 "
        "HAVING count(*) FILTER (WHERE holding_attribution_status='direct')=0) x"),
      "ownership_changes": q("SELECT count(*) FROM ownership_changes"),
      "lens_signals": q("SELECT count(*) FROM oracles_lens_signals"),
      "quarters": [r[0] for r in db.execute(text(
        "SELECT DISTINCT report_quarter FROM filings_13f WHERE report_quarter IS NOT NULL ORDER BY 1")).fetchall()],
      "active_jobs": [dict(zip(("id","job_type","status","lock_key"), row)) for row in db.execute(text(
        "SELECT id, job_type, status, lock_key FROM job_runs "
        "WHERE status IN ('queued','running','cancel_requested')")).fetchall()],
    }
    print(json.dumps(r, indent=2, default=str))
    db.close()
    PY

Then STOP and report. Do not continue past this point on your own.

### How to read it

- `filings == 0` → **Branch A: prod has never ingested 13F data.** The code is
  live but there is nothing to migrate, so there is no active risk. Proceed with
  the Day-0 bootstrap (Phase 2A) only if a human tells you to.
- `filings > 0` → **Branch B: prod has data.** If `accepted_at_null > 0`, the
  missing-acceptance rule is armed: any admin resolve / reparse / old-quarter
  job could freeze a group. `frozen_sort_warnings > 0` means it may ALREADY have
  happened. This is the case to escalate loudly.
- `active_jobs` non-empty → the worker/scheduler is busy. Wait; do not run the
  rollout (it will exit 2 anyway).
- `dup_active_groups > 0`, `holdings_null_parse_run > 0`, `attr_legacy > 0`, or
  `attr_misattributed > 0` are all invariant violations — report them, do not
  quietly fix them.

## PHASE 2B — prod HAS data (run only when told)

1. Close the gate FIRST. Nothing else may run before it exits 0.

       docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t1fu_accepted_at_backfill; echo "EXIT=$?"

   exit 0 → continue. exit 1 → STOP and report the classified list. Its
   `at_risk_groups` tells you whether the remaining NULLs will actually freeze
   anything (a competition pool with ≥2 members) or are harmless. Deciding to
   proceed past a non-zero exit is a HUMAN decision, never yours.

2. Re-run the Phase 1 probe. `accepted_at_null` must now be 0. Paste it.

3. If `frozen_sort_warnings > 0` in step 2, those groups were frozen while the
   gate was open. Report the list before touching them:

       docker compose -f docker-compose.prod.yml exec -T api python - <<'PY'
       from sqlalchemy import text
       from app.core.db import SessionLocal
       db = SessionLocal()
       for row in db.execute(text(
         "SELECT manager_id, quarter_end_date, accession_no, form_type, amendment_status, "
         "amendment_sort_warning, accepted_at FROM filings_13f "
         "WHERE amendment_sort_warning ORDER BY manager_id, quarter_end_date")).fetchall():
           print(dict(row._mapping))
       db.close()
       PY

   With `accepted_at` now populated, these groups become rankable again. The
   authority re-converges them the next time it runs for that group (an ingest
   job for that quarter, or an admin action). Do NOT hand-edit rows.

4. Attribution rollout + recompute + verify:

       docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t3_attribution_rollout; echo "EXIT=$?"

   exit 0 → continue. exit 2 → a job was running; wait and re-run. exit 1 →
   STOP, paste the failed invariants.

5. Go to PHASE 3.

## PHASE 2A — prod has NO data (Day-0 bootstrap; run only when told)

These call EDGAR/OpenFIGI through the Rate Guard limiter. Expect step 3 to take
30–60 minutes. Run them one at a time; STOP on any non-zero exit.

    docker compose -f docker-compose.prod.yml exec -T api python -m app.cli.edgar seed-confirmed-managers
    docker compose -f docker-compose.prod.yml exec -T api python -m app.cli.edgar match-cik
    docker compose -f docker-compose.prod.yml exec -T api python -m app.cli.edgar backfill --quarters 8
    docker compose -f docker-compose.prod.yml exec -T api python -m app.cli.edgar enrich-cusip
    docker compose -f docker-compose.prod.yml exec -T api python -m app.cli.edgar bootstrap-stocks
    docker compose -f docker-compose.prod.yml exec -T api python -m app.cli.edgar quality-check

Every command above was verified to exist in `python -m app.cli.edgar --help`
at commit e1c9631. If any is missing, prod is on different code — STOP.
(An older README told operators to run `enrich-stocks-edgar` here; that command
was deliberately deleted as broken. Do not resurrect it.)

Then, in this order:

    # 5. the gate — must exit 0 before any authority path is exercised
    docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t1fu_accepted_at_backfill; echo "EXIT=$?"

    # 6. attribution + ownership_changes + Oracle's Lens + invariant verification
    docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t3_attribution_rollout; echo "EXIT=$?"

(`backfill` already ingests through the modern job path, so its own Phase-2
routing fills `accepted_at` for the quarters it touches. Step 5 still runs: it
proves the condition for every quarter, which is the point of a gate.)

Then go to PHASE 3.

## PHASE 3 — acceptance (read-only). All must hold.

Re-run the Phase 1 probe and assert:

| Field | Required |
|---|---|
| `accepted_at_null` | 0 |
| `dup_active_groups` | 0 |
| `holdings_null_parse_run` | 0 |
| `holdings_under_current_run` | > 0 (if `holdings` > 0) — see note |
| `attr_legacy` | 0 |
| `attr_misattributed` | 0 |
| `managers_zero_direct` | 0 |
| `ownership_changes` | > 0 (if `holdings` > 0) |
| `lens_signals` | > 0 (if `holdings` > 0) |
| `frozen_sort_warnings` | 0, or every one explained in your report |

Note on `holdings_under_current_run`: it is normal for this to be LESS than
`holdings`. A reparse creates a new current ParseRun and RETAINS the previous
run's holdings (non-destructive by design), so the difference is retained
history, not loss. The invariant that matters is `holdings_null_parse_run == 0`
— a holding with no ParseRun is invisible to the product query contract.
If the difference is large and you cannot account for it with reparse history
(`SELECT accession_number, count(*) FROM parse_runs GROUP BY 1 HAVING count(*)>1`),
report it rather than waving it through.

Then smoke the product surface (read-only):

    curl -s -o /dev/null -w 'health %{http_code}\n' http://127.0.0.1:8101/health
    curl -s -o /dev/null -w 'login %{http_code}\n' http://127.0.0.1:3101/login

Any deviation → STOP and report; do not "fix" it.

## PHASE 4 — deliverables

Produce, in your final message:

1. **Branch taken** (A or B) and why, with the Phase 1 JSON.
2. **Every command you ran**, with its exit code and the decisive output.
3. **The acceptance table** filled in with real numbers.
4. **Anything that contradicted this prompt.** This is the most valuable part of
   your report — do not omit surprises to make the run look clean.
5. **Tag recommendation.** If and only if every Phase 3 assertion holds, state:
   "Recommend tagging <the exact commit sha you verified> as `13f-data-v1`."
   DO NOT create or push the tag. A human does that.
6. **Residual risks / follow-ups** you observed (frozen groups, slow steps,
   scheduler collisions, anything that needed a retry).

If you had to stop at any gate, say exactly which gate, what you saw, and what
you would need in order to continue. A truthful "stopped at 2B-1, exit 1, three
filings lack primary docs" is a successful run of this task. A clean-looking
report that skipped a gate is a failed one.
```
