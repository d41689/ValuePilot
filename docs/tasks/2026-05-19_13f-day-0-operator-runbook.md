# 13F Day-0 Operator Runbook

Audience: a brand-new ValuePilot operator who has just deployed the system and wants 13F-driven signals to appear on `/watchlist`.

## What this runbook is NOT

The PRD `docs/prd/13f_automation_and_resilience_prd.md` describes a target state of "configure a start date and walk away." That is **not** what today's code does. Two front-door pieces are still manual:

1. The manager universe is not auto-populated (no Dataroma sync job today).
2. There is no system-level "start date" config — historical backfill is a per-job parameter.

Both are tracked as separate GitHub issues; see "Known gaps" at the bottom. This runbook is the literal sequence of operator clicks/calls that the **current** code requires.

## Prerequisites (one-time)

- `EDGAR_SCHEDULER_ENABLED=true` in `~/.config/valuepilot/.env.prod` (already on in prod as of 2026-05-19).
- `THIRTEENF_JOB_WORKER_ENABLED=true` (already on).
- `THIRTEENF_SMART_RETRY_ENABLED=true` (already on).
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

## Step 3 — (Optional) Backfill historical filings

If you want filings from before today, fire one backfill job per quarter range you want. On `/admin/13f` → "Backfill" section:

- **Optional start quarter:** e.g. `2024-Q1`.
- Click **Backfill**.

The worker walks SEC quarterly `form.idx` files for each quarter in range, downloads each tracked manager's 13F-HR/A filing, parses, and ingests.

For multi-year backfill, fire several jobs — there is no single "fill from Q1-2020 to today" button today.

## Step 4 — Wait for daily sync (or trigger current quarter manually)

The scheduler runs `run_daily_sync_poll` hourly. It scans SEC's daily `form.idx`, finds 13F filings from active managers, and queues fetch + parse jobs.

To force-run the current quarter immediately, on `/admin/13f`:

1. Enter the target quarter (e.g., `2025-Q4`) in the "Quarter pipeline" section.
2. Click **Fetch quarter index** → wait for the job to complete (visible on `/admin/13f/jobs`).
3. Click **Ingest holdings** → parses 13F XML into the holdings table.

## Step 5 — CUSIP enrichment (automatic)

After holdings are ingested, an `enrich_metadata` job auto-runs to map CUSIP → ticker → `stock_id` via OpenFIGI (key in `OPENFIGI_API_KEY`) and SEC's `company_tickers.json`. Coverage shows on `/admin/13f/holdings`.

Holdings without a CUSIP map land in the "Unknown manager / unknown CUSIP" queue on `/admin/13f` → "ORACLE'S LENS" tile.

## Step 6 — Add stocks to a user's watchlist

Frontend route: `/watchlist`. A user adds tickers as normal. The watchlist page automatically fetches `POST /api/v1/stocks/13f-snapshots` for the watched stocks.

## Step 7 — Verify on `/watchlist`

Each watched stock should now render 13F columns: conviction score, conviction percentile, delta holders, distinctiveness tier, caveat severity.

Columns will show `unavailable_reason='no_holders'` or `'below_min_holders'` if no tracked manager holds that stock or coverage is too thin — that's the system telling you to either seed more managers or accept the gap.

## Troubleshooting

| Symptom | Probable cause | Where to look |
|---|---|---|
| Yellow "No managers tracked yet" banner on /admin/13f | Step 1 skipped. | `/admin/13f/managers`. |
| Filings tile stays at `0 pending` after Step 4 | All active managers had no recent filings, OR daily sync hasn't run since you activated them. | `/admin/13f/sync`, `/admin/13f/jobs`. |
| `fetch_quarter_index` fails ENOENT on a specific SHA | Stale `raw_source_documents` row from before the persistent `edgar_raw` volume was mounted (PR #35). | Fixed in PR #37: fetcher self-heals by re-fetching the URL. Re-trigger the same job; the row updates in place. |
| Holdings ingest fails with `SEC_CONTACT_EMAIL is required` | Missing env var. | Add `SEC_CONTACT_EMAIL=<inbox>` to `~/.config/valuepilot/.env.prod` and redeploy. |
| Watchlist 13F columns blank but data exists | No Oracle's Lens scoring yet for that period, OR `min_holders` threshold not met. | `/admin/13f/readiness`. |

## Known gaps (tracked separately)

- **Dataroma auto-sync** — populate the manager universe from Dataroma's tracked-investors list instead of manual CSV.
- **System-level start-date config** — configure a single "ingest from 2024-Q1 forward" knob so the operator doesn't have to fire per-quarter backfill jobs.

Both are blockers for the PRD's full "set start date and walk away" vision. Tracked in GitHub issues (linked from `docs/prd/13f_automation_and_resilience_prd.md`).
