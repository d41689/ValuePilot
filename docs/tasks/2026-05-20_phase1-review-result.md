# Review result — Phase 1 PRs (#73, #74, #75)

Date: 2026-05-20
Prompt: `docs/tasks/2026-05-20_phase1-review-prompts.md`

## Summary

- **PR #73 — Isolate dev host ports from prod:** approved, with one CI cleanup
  note.
- **PR #74 — Color the Jobs page STATUS column:** approved.
- **PR #75 — Fix `_check_period_alignment`:** approved after remediation.

## PR #73 — Isolate dev host ports from prod

Verdict: **approved**.

1. **Dev/prod variable decoupling: pass.** `docker-compose.yml` now maps dev web
   and API ports via `DEV_HOST_WEB_PORT` and `DEV_HOST_API_PORT`. The dev
   compose file no longer reads `HOST_WEB_PORT` / `HOST_API_PORT` for port
   binding. Note: those old vars still appear in the rendered service
   environment because `.env` contains them, but they no longer affect dev
   published ports.
2. **Defaults: pass.** `docker compose config` on the #73 branch renders dev
   web as `3001:3000` and dev API as `8001:8000`, so it no longer collides with
   prod defaults `3101:3000` and `8101:8000`.
3. **Prod untouched: pass.** The branch diff is only `docker-compose.yml`.
   `docker-compose.prod.yml` still uses `HOST_WEB_PORT` and `HOST_API_PORT`.
4. **CI interaction: cleanup finding, not blocking.** `.github/workflows/ci.yml`
   still sets `HOST_WEB_PORT=13001` and `HOST_API_PORT=18001`, but #73's dev
   compose no longer reads those names. CI should still pass on a clean runner
   because ports 3001/8001 are normally free, but those env vars are now dead.
   Prefer either renaming them to `DEV_HOST_WEB_PORT` / `DEV_HOST_API_PORT` or
   deleting them.

## PR #74 — Color the Jobs page STATUS column

Verdict: **approved**.

5. **Badge `info` variant: pass.** `components/ui/badge.tsx` adds
   `info: 'border-transparent bg-sky-500/15 text-sky-700'`, matching the
   existing tinted semantic style used by `success`, `warning`, and `danger`.
   The `cva` entry is well-formed and does not alter default variants.
6. **`jobStatusTone`: pass.** The helper maps all statuses named in the prompt:
   `succeeded -> success`, `failed -> danger`, `partial_success` and
   `cancel_requested -> warning`, `running -> info`, `queued -> secondary`,
   `cancelled` and `skipped -> outline`, unknown -> `secondary`. The palette is
   sensible and the unit test covers the full list plus unknown fallback.
7. **Jobs page rendering / UI standard: pass.** The STATUS cell now renders a
   shared `<Badge>` and `badgeVariant` allows `info`. No raw HTML control was
   introduced; `uiStandard.test.js` stayed green as part of the full node test
   glob.

Verification on `claude/jobs-status-colors`:

- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'` —
  passed, 153 tests.
- `docker compose run --rm --no-deps web npm run lint` — passed.
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run build'`
  — passed.

## PR #75 — Fix `_check_period_alignment`

Verdict: **approved after remediation**.

The original blocker was fixed. `_check_period_alignment` now splits mismatches
by direction:

- `period_of_report < prev_start`: `info` for late filing / old-period
  amendment.
- `period_of_report > prev_end`: `warning` for a period in the filing quarter
  itself or the future.

The new too-new-period test covers the case that was missing in the first
review.

8. **Previous-quarter computation: pass.** The date window arithmetic is correct
   for normal quarters and for Q1 year rollover.
9. **Older-than-X-1 filings as info: pass for the intended case.** The late
   filing test verifies an older period is informational and does not contribute
   a warning, which should allow readiness to clear after a fresh quality check.
   The blocker above is that the implementation also downgrades newer-than-X-1
   anomalies.
10. **Tests: pass.** The tests now cover normal prior-quarter filings, late
    filings downgraded to info, and too-new / filing-quarter periods preserved
    as warning. The normal test uses `2026-Q1` / `2025-Q4`, so it covers year
    rollover.
11. **Backlog hygiene: pass.** Removing the BACKLOG item is correct once this
    PR lands, because the false-positive readiness blocker is addressed. The
    ops audit item #8 is updated with the new behavior and post-deploy quality
    check requirement.

Verification on `claude/fix-period-alignment-check`:

- `docker compose run --rm api sh -lc "alembic upgrade head && pytest -q"` —
  initially passed, 870 tests, 3 SQLAlchemy legacy warnings.
- Remediation recheck:
  - `docker compose run --rm api pytest -q tests/unit/test_edgar_quality_period_alignment.py`
    — passed, 3 tests.
  - `docker compose run --rm api sh -lc "alembic upgrade head && pytest -q"` —
    passed, 871 tests, 3 SQLAlchemy legacy warnings.

## Worktree note

Review was performed by switching among the three local branches and then
returning to `claude/rate-guard-service`. The only file added by this review is
this result file.
