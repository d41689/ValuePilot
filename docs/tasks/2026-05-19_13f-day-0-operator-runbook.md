# 13F Day-0 Operator Runbook

Audience: a brand-new ValuePilot operator who has just deployed the system and wants 13F-driven signals to appear on `/watchlist`.

## Current contract

The 13F pipeline now supports the PRD's "set a start date and walk away" operator path once the manager universe exists:

```
THIRTEENF_START_QUARTER
  -> boot reconcile
  -> quarterly_pipeline
  -> fetch_quarter_index
  -> ingest_holdings
  -> enrich_metadata
  -> quality_check
  -> oracles_lens_score_backfill
  -> /watchlist 13F columns
```

The one remaining Day-0 front-door manual step is the manager universe: seed managers and confirm CIKs before expecting EDGAR scans to find anything. Dataroma auto-sync remains a future enhancement.

## Prerequisites (one-time)

- `EDGAR_SCHEDULER_ENABLED=true` in `~/.config/valuepilot/.env.prod` (already on in prod as of 2026-05-19).
- `THIRTEENF_JOB_WORKER_ENABLED=true` (already on).
- `THIRTEENF_SMART_RETRY_ENABLED=true` (already on).
- `THIRTEENF_START_QUARTER=<YYYY-QN>` in `~/.config/valuepilot/.env.prod`, for example `THIRTEENF_START_QUARTER=2025-Q3`.
- `SEC_CONTACT_EMAIL=<reachable inbox>` in `~/.config/valuepilot/.env.prod`. SEC requires this in the User-Agent or live EDGAR calls will fail with `RuntimeError: SEC_CONTACT_EMAIL is required for EDGAR requests`. Documented in `.env.prod.example`.

## Step 1 — Seed the manager universe

On a fresh database the Managers table is empty. `/admin/13f` will show a yellow "No managers tracked yet" banner and `0 managers`. Daily sync runs but has nothing to scan.

Pick one of:

**Option A — Bulk CSV import (preferred for >5 managers):**

CSV columns: `canonical_name` (required), `source_url`, `manager_type`, `is_featured` (optional). Post to:

```
POST /api/v1/admin/13f/managers/bulk-import
Content-Type: multipart/form-data
file=<your.csv>
```

Each row creates a manager with `status="candidate"` and no CIK confirmed yet.

**Option B — Add one at a time via the Managers page:**

`/admin/13f/managers` → "Add manager" form. Same end state.

## Step 2 — Confirm each manager's CIK

`status="candidate"` managers are ignored by the daily sync. To activate them, confirm their SEC Central Index Key.

On `/admin/13f/managers`, for each candidate:

1. Open the manager detail.
2. Use the SEC search workflow to find the manager's CIK on EDGAR.
3. Confirm — the system records the CIK and flips `status="active"`.

Watch for `match_status="ambiguous"` — multiple SEC entities matched. Resolve by picking the right one (the audit trail records who confirmed).

## Step 3 — Configure the start quarter

Set the first quarter the system should cover:

```
THIRTEENF_START_QUARTER=2025-Q3
```

Then redeploy or restart the API process so the boot-time reconcile runs. On each boot, `reconcile_start_quarter_coverage` walks from `THIRTEENF_START_QUARTER` through the latest scoreable quarter and enqueues a `quarterly_pipeline` job for any quarter that has not produced Oracle's Lens signal rows yet.

The reconcile intentionally anchors on the terminal output (`oracles_lens_signals`), not intermediate job success. If a quarter is partially healed later, the next boot can enqueue it again and let the idempotent pipeline finish the missing work.

## Step 4 — Let the quarterly pipeline run

The worker processes each queued `quarterly_pipeline` through five stages:

1. `fetch_quarter_index` — walks SEC quarterly `form.idx` files for active managers.
2. `ingest_holdings` — downloads missing primary-doc and infotable XML, routes report period/quarter, parses holdings, and heals historical rows.
3. `enrich_metadata` — maps CUSIP -> ticker -> `stock_id`.
4. `quality_check` — records ingestion quality findings.
5. `oracles_lens_score_backfill` — writes persisted Oracle's Lens signal rows that `/watchlist` reads.

Monitor:

- `/admin/13f/jobs` — top-level `quarterly_pipeline` and child stage jobs.
- `/admin/13f/readiness` — latest usable quarter, manager coverage, holdings coverage, and scoring readiness.
- `/admin/13f/holdings` — linked/unlinked holdings and CUSIP coverage.

## Step 5 — Daily sync after Day-0

After the historical range is caught up, the scheduler runs `run_daily_sync_poll` hourly. It scans SEC's daily `form.idx`, finds new 13F filings from active managers, and queues the same pipeline stages for newly available data.

Manual quarter buttons on `/admin/13f` still exist for targeted recovery or operator testing, but they are no longer the primary Day-0 path.

## Step 6 — Add stocks to a user's watchlist

Frontend route: `/watchlist`. A user adds tickers as normal. The watchlist page automatically fetches `POST /api/v1/stocks/13f-snapshots` for the watched stocks.

## Step 7 — Verify on `/watchlist`

Each watched stock should now render 13F columns: conviction score, conviction percentile, delta holders, distinctiveness tier, caveat severity.

Columns will show `unavailable_reason='no_holders'` or `'below_min_holders'` if no tracked manager holds that stock or coverage is too thin — that's the system telling you to either seed more managers or accept the gap.

## Admin Tasks panel vs retry controls

The Admin Tasks panel on `/admin/13f` is **diagnostic, not a control panel** — cards summarize what failed and why, but have no inline retry button. Where retries actually live:

- **To retry an entire quarter** — prefer the automatic reconcile path: fix the underlying data/config issue, then restart/redeploy the API so `THIRTEENF_START_QUARTER` reconciliation can enqueue any quarter still missing Oracle's Lens signal rows.
- **To retry one stage manually** — use the **Manual Controls** section of `/admin/13f`. Enter the target quarter in the textbox, then click the matching pipeline button (e.g. **Fetch quarter index**, **Ingest holdings**) to create a fresh `JobRun`.
- **For per-job details and review** — `/admin/13f/jobs` → **Review** button on the row. Use this to inspect what a particular job did or failed on.
- **Stale failure cards** — a later succeeded `JobRun` for the same lock key (e.g. `fetch_quarter_index:2025-Q4`) supersedes earlier failures operationally; the quarter is healthy even if old failure cards linger in the Admin Tasks panel. The panel currently doesn't fold them automatically — see [#41](https://github.com/d41689/ValuePilot/issues/41).
- **Rule of thumb** — check the Jobs page top row for the same lock key before treating an Admin Tasks card as an active incident.

## Troubleshooting

| Symptom | Probable cause | Where to look |
|---|---|---|
| Yellow "No managers tracked yet" banner on /admin/13f | Step 1 skipped. | `/admin/13f/managers`. |
| No `quarterly_pipeline` jobs appear after deploy | `THIRTEENF_START_QUARTER` is missing or malformed, API did not restart, or the requested quarters already have signal rows. | `.env.prod`, API logs, `/admin/13f/jobs`. |
| Pipeline succeeds but `/watchlist` still shows dashes | The watched stocks are not held by tracked managers, CUSIP coverage is thin, or the stock is below the Oracle's Lens `min_holders` threshold. | `/admin/13f/readiness`, `/admin/13f/holdings`, `/admin/13f/jobs`. |
| `fetch_quarter_index` fails ENOENT on a specific SHA | Stale `raw_source_documents` row from before the persistent `edgar_raw` volume was mounted (PR #35). | Fixed in PR #37: fetcher self-heals by re-fetching the URL. Re-trigger the same job; the row updates in place. |
| Holdings ingest fails with `SEC_CONTACT_EMAIL is required` | Missing env var. | Add `SEC_CONTACT_EMAIL=<inbox>` to `~/.config/valuepilot/.env.prod` and redeploy. |
| Admin Tasks panel still shows old failures | The panel can show stale alert cards even after a later same-lock-key job succeeds. | `/admin/13f/jobs`; tracked by [#41](https://github.com/d41689/ValuePilot/issues/41). |

## Known gaps (tracked separately)

- **Dataroma auto-sync** — populate the manager universe from Dataroma's tracked-investors list instead of manual CSV.
- **OpenFIGI throughput / CUSIP coverage** — mainstream names are covered, but full coverage needs pagination / higher throughput.
- **Admin Tasks stale-card folding** — see [#41](https://github.com/d41689/ValuePilot/issues/41).

The system-level start-quarter config is no longer a gap; it is the canonical Day-0 path.
