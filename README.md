# ValuePilot

ValuePilot is a source-traceable value-investing research system. It combines
Value Line report parsing and normalized financial facts with automated SEC 13F
ingestion, Oracle's Lens candidate discovery, Watchlists, screening, valuation,
and the Research Decision Loop roadmap.

## Prerequisites
- Docker & Docker Compose

## Quick Start

1. **Clone the repository**
2. **Start the stack**
   ```bash
   docker-compose up -d --build
   ```
3. **Access the Application**
   - Frontend: [http://localhost:3000](http://localhost:3000)
   - Backend API Docs: [http://localhost:8001/docs](http://localhost:8001/docs)

## Development

- **Backend Shell**: `docker-compose exec api bash`
- **Run Tests**: `docker-compose exec api pytest`
- **Linting**: `docker-compose exec api ruff check .`

## Document Maintenance

Use the dedupe cleanup command when duplicate Value Line documents exist for the same
user, stock, and report date. Run dry-run first to inspect the duplicate groups:

```bash
docker compose exec api python -m scripts.dedupe_documents
```

Apply the cleanup only after reviewing the dry-run output:

```bash
docker compose exec api python -m scripts.dedupe_documents --apply
```

## Key Features (v0.1)
- **PDF Ingestion**: Upload Value Line PDFs.
- **Parsing**: Auto-extract Ticker, Price, P/E, Yield.
- **Normalization**: Converts "1.2 bil", "5%" to numeric values.
- **Screener**: Filter stocks using JSON-based rules.

---

## SEC EDGAR 13F Institutional Holdings Pipeline

### Overview

13F data tracks quarterly equity holdings of institutional investors (AUM > $100M).  
The verified universe contains 82 tracked value-investor managers, with EDGAR as
the holdings source of truth. Dataroma is used only for universe discovery and
independent reconciliation, never as canonical holdings data.

All CLI commands run inside the API container:
```bash
docker compose exec api python -m app.cli.edgar <command>
```

---

### Unattended setup and operator commands

With the production switches in `.env.prod.example`, API startup migrates the
database, seeds the curated manager universe, reconciles every incomplete
quarter from `THIRTEENF_START_QUARTER`, and starts the worker/scheduler. The
hourly daily-index poll provides filing-window continuity; the weekly full
quarterly job remains a safety/reconciliation pass; watchdog and Smart Retry
recover safe failures.

The commands below remain explicit operator tools for inspection or controlled
repair. They are not required to hand-build business data on a correctly
configured empty deployment.

**Step 0 — Seed the curated manager universe (offline)**
```bash
docker compose exec api python -m app.cli.edgar seed-confirmed-managers
```
Upserts the ~82 curated value-investing managers from
`backend/app/services/seed_data/confirmed_managers.json` — offline, no Dataroma
call. New rows land `match_status='confirmed'` with their CIK already set.

Safe to re-run (and to run on every deploy): **the seed expresses intent, a human
owns lifecycle.** It never writes `match_status` / `status` on an existing row and
never deactivates anyone. Read the diff it prints:

- `skipped human-decided` — retired / revoked / rejected; seeding will not resurrect them.
- `skipped needs-review` — an operator parked these; seeding will not touch them.
- `awaiting confirmation` — in the seed file but not confirmed; **confirm them in the
  admin Managers page or they will never be ingested** (ingestion selects on
  `match_status='confirmed'`).
- `ambiguous name match` — another row normalizes to the same name, so the manager was
  NOT created; resolve the duplicate by hand.

(`bootstrap-whitelist` is a deprecated alias for this command. `sync-dataroma`
diffs Dataroma's list against ours — read-only, it proposes and never applies.)

**Step 1 — Match any remaining managers to EDGAR CIKs**
```bash
docker compose exec api python -m app.cli.edgar match-cik
```
Only scans rows with no CIK whose `match_status` is `seeded` / `candidate` — the
seeded managers above already carry theirs, so this is for managers added outside
the seed file. Searches EDGAR by name and scores candidates; high-confidence
matches are marked `confirmed`, the rest need manual review
(`match_status = 'candidate'`).

**Step 2 — Backfill historical quarters (one-time)**
```bash
docker compose exec api python -m app.cli.edgar backfill --quarters 8
```
Fetches `form.idx` indexes and downloads + parses all filings for the last N quarters. Takes 30–60 min for 5 quarters across 80 managers. Use `--quarters 8` to cover ~2 years of history.

**Step 3 — Build the CUSIP → ticker map**
```bash
# Round 1: map pending CUSIPs through OpenFIGI
docker compose exec api python -m app.cli.edgar enrich-cusip

# Round 2: bootstrap stocks table + backfill stock_id
docker compose exec api python -m app.cli.edgar bootstrap-stocks
```

**Step 4 — Data quality check**
```bash
docker compose exec api python -m app.cli.edgar quality-check
# Scope to a specific quarter:
docker compose exec api python -m app.cli.edgar quality-check --quarter 2025-Q1
```

---

### Quarterly Update

**In production, this runs automatically.** The scheduler combines:

- an hourly daily `form.idx` continuity poll;
- a Monday 06:00 UTC full-quarter reconciliation;
- a 15-minute lease/watchdog check by default;
- daily Smart Retry at 02:00 UTC when enabled;
- investor filing-season digest at 07:00 New York time;
- operational health summary at 08:00 New York time.

Jobs are durable and idempotent; already-complete work no-ops.

Smart retries are controlled separately by `THIRTEENF_SMART_RETRY_ENABLED`; production defaults it
to true, while dev leaves it off unless explicitly enabled.

Filing deadlines (when a quarter becomes available): Feb 14 (Q4), May 15 (Q1), Aug 14 (Q2), Nov 14 (Q3).

**In dev, run manually:**
```bash
# 1. Fetch new quarter's index + holdings
docker compose exec api python -m app.cli.edgar backfill --quarters 1

# 2. Refresh CUSIP mappings for any new holdings
docker compose exec api python -m app.cli.edgar enrich-cusip
docker compose exec api python -m app.cli.edgar bootstrap-stocks

# 3. Verify data quality
docker compose exec api python -m app.cli.edgar quality-check --quarter <YYYY-Qn>
```

---

### Other Useful Commands

```bash
# Re-parse a single filing from stored raw doc (ParseRun-backed; new run becomes
# current, prior holdings retained — non-destructive)
docker compose exec api python -m app.cli.edgar reparse-filing --accession 0001234567-25-000001

# Re-parse all filings from stored raw docs (after parser fixes; each accession
# swaps is_current without deleting the prior run's holdings)
docker compose exec api python -m app.cli.edgar reparse-all
docker compose exec api python -m app.cli.edgar reparse-all --quarter 2025-Q1

# Fix period_of_report for all filings (re-parses primary docs)
docker compose exec api python -m app.cli.edgar backfill-period-dates

# Backfill reported_total_value_thousands from stored primary docs
docker compose exec api python -m app.cli.edgar backfill-reported-totals
```

---

### API Endpoints

#### Institutional Holdings (Phase C)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/institutions` | List confirmed institutions (`?superinvestor=true`) |
| GET | `/api/v1/institutions/{cik}/filings` | All filing versions for an institution (`?period=2024-Q4`) |
| GET | `/api/v1/institutions/{cik}/holdings` | Latest-snapshot holdings (`?period=2024-Q4`) |
| GET | `/api/v1/filings/{accession_no}/holdings` | Holdings for a specific filing version (raw) |
| GET | `/api/v1/stocks/{ticker}/institutions` | Institutions holding a given ticker |

#### Scheduler & Filing Progress (Phase D)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/scheduler/status` | Scheduler on/off state and latest available quarter |
| GET | `/api/v1/scheduler/filing-progress` | Per-manager filed/pending status (`?quarter=2025-Q1`) |

---

### Current limitations

- 13F is a delayed report of covered long securities, not a manager's complete
  or current portfolio and not evidence of transaction price.
- Fundamental and EOD-price coverage is currently much sparser than the 13F
  universe. The approved Research Decision Loop therefore prioritizes coverage
  for open cases, Watchlists, and selected candidates instead of claiming full
  market readiness.
- Value Line v0.1 supports the configured native-text layouts. OCR and broader
  historical/template coverage remain explicit backlog work.
- User-facing research cases, Research Inbox, configurable research
  notifications, and manual portfolio journal are governed by
  `docs/plans/research_decision_loop_product_roadmap.md` and are under active
  implementation.
