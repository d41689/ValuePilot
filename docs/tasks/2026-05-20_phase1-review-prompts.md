# Review prompts — Phase 1 PRs (#73, #74, #75)

Three small, independent PRs from the `/admin/13f` follow-up work. Each section
below is self-contained — paste one into a fresh reviewer session (human or
agent). They do not depend on each other and may be reviewed / merged in any
order.

================================================================================

## PR #73 — Isolate dev host ports from prod

### Reviewer brief

Branch **`claude/dev-prod-port-isolation`**. The dev `docker-compose.yml` mapped
host ports via `HOST_WEB_PORT` / `HOST_API_PORT` — the *same* variable names
`docker-compose.prod.yml` uses. A shared `.env` sets those to the prod values
(3101 / 8101), so `docker compose up` for the dev stack tried to bind the prod
ports and failed whenever prod was running. This PR renames the dev mappings to
`DEV_HOST_WEB_PORT` / `DEV_HOST_API_PORT` (defaults 3001 / 8001).

Files: `docker-compose.yml` only. Baseline: `git diff main...HEAD`.

### Answer with a verdict + evidence

1. The rename fully decouples the dev stack from the shared `.env` — confirm
   nothing in the dev compose still reads `HOST_WEB_PORT` / `HOST_API_PORT`.
2. Defaults 3001 / 8001 do not collide with prod (3101 / 8101) or the other
   stacks on the host. Confirm.
3. **`docker-compose.prod.yml` is untouched** and still uses `HOST_*_PORT` —
   confirm prod is unaffected.
4. **CI interaction (important).** `.github/workflows/ci.yml` sets
   `HOST_WEB_PORT: 13001` / `HOST_API_PORT: 18001` for its `docker compose up`.
   After this rename the dev compose no longer reads those, so CI falls back to
   3001 / 8001. On a clean GitHub runner those ports are free, so CI still
   passes — but `ci.yml` now carries two dead env vars. Flag whether `ci.yml`
   should be updated in this PR (rename to `DEV_HOST_*` or drop the vars).

### Pass bar

Approve if 1–3 hold. 4 is a finding to record — block only if CI actually
breaks.

================================================================================

## PR #74 — Color the Jobs page STATUS column

### Reviewer brief

Branch **`claude/jobs-status-colors`**. The `/admin/13f/jobs` STATUS column
rendered job status as plain text; this PR renders it as a colored `Badge`.

Files: `components/ui/badge.tsx`, `lib/thirteenfAdmin.js`,
`lib/thirteenfAdmin.test.js`, `app/(dashboard)/admin/13f/jobs/page.tsx`.
Baseline: `git diff main...HEAD`.

### Answer with a verdict + evidence

5. `badge.tsx` gains an `info` variant (`bg-sky-500/15 text-sky-700`) — confirm
   it matches the existing tinted `success`/`warning`/`danger` style and the
   `cva` entry is well-formed; adding a variant does not affect existing usages.
6. `jobStatusTone(status)` in `thirteenfAdmin.js` — confirm every job status is
   mapped (`succeeded`/`failed`/`partial_success`/`running`/`queued`/
   `cancel_requested`/`cancelled`/`skipped`) and the colors are sensible
   (`succeeded`→green per the requirement; others a reasonable distinct
   palette). The unit test in `thirteenfAdmin.test.js` covers it.
7. `jobs/page.tsx` — the STATUS cell renders `<Badge>`; the `badgeVariant`
   allowlist gains `info`. Confirm no raw HTML control is introduced (the
   `uiStandard.test.js` scanner must stay green).

### Pass bar

Approve if 5–7 hold; `node --test lib/*.test.js`, `lint`, `build` green.

================================================================================

## PR #75 — Fix `_check_period_alignment`

### Reviewer brief

Branch **`claude/fix-period-alignment-check`**. `_check_period_alignment`
(`backend/app/services/edgar_quality.py`) compared a filing's
`period_of_report` against the **filing** quarter and raised a `warning` when
they differed. That is wrong for 13F: a 13F-HR is filed ~45 days after a
quarter-end — in the *following* calendar quarter — so `period_of_report` never
falls in the filing quarter. The check thus warned on essentially every 13F
(2026-Q1: 63/63), which left the readiness "Quality checked" item permanently
`blocked`. The fix expects `period_of_report` in the quarter *before* the
filing quarter, and downgrades older-than-expected filings (late filings /
amendments) to `info`.

Files: `backend/app/services/edgar_quality.py`,
`backend/tests/unit/test_edgar_quality_period_alignment.py`, `docs/BACKLOG.md`,
`docs/tasks/2026-05-20_admin-13f-ops-audit.md`. Baseline: `git diff main...HEAD`.

### Answer with a verdict + evidence

8. The "previous quarter" computation — `(year-1, 4)` when `qtr == 1`, else
   `(year, qtr-1)` — and the resulting SQL date window are correct, including
   the year rollover and month/last-day arithmetic.
9. Severity: older-than-X-1 filings are now `info`, not `warning`. Confirm this
   is sound — a late filing is not a data-quality defect — and that it means
   the check no longer contributes a `warning`, so the readiness item can clear
   (after a fresh `quality_check` runs post-deploy).
10. The two new tests cover the normal (prior-quarter) and the late-filing
    cases; `pytest -q` is green (870). Are there gaps worth adding (e.g. a
    Q1 year-rollover case)?
11. `docs/BACKLOG.md` item #8 is removed in this PR (resolved here) and the
    audit doc's item #8 is updated — confirm the backlog hygiene is correct.

### Pass bar

Approve if 8–9 hold and the tests are adequate (10) and the backlog is cleared
(11).
