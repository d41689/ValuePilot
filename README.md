# ValuePilot

ValuePilot is a financial analysis engine designed to parse Value Line equity reports, extract key metrics, and enable powerful screening and formula-based analysis.

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

## Key Features (v0.1)
- **PDF Ingestion**: Upload Value Line PDFs.
- **Parsing**: Auto-extract Ticker, Price, P/E, Yield.
- **Normalization**: Converts "1.2 bil", "5%" to numeric values.
- **Screener**: Filter stocks using JSON-based rules.

---

## SEC EDGAR 13F Institutional Holdings Pipeline

### Overview

13F data tracks quarterly equity holdings of institutional investors (AUM > $100M).  
The pipeline covers ~80 "superinvestors" sourced from Dataroma, with EDGAR as the authoritative data source.

All CLI commands run inside the API container:
```bash
docker compose exec api python -m app.cli.edgar <command>
```

---

### Initial Setup (run once, in order)

**Step 0 — Seed the superinvestor whitelist from Dataroma**
```bash
docker compose exec api python -m app.cli.edgar bootstrap-whitelist
```
Parses Dataroma's manager list and inserts ~80 superinvestors into `institution_managers`.

**Step 1 — Match managers to EDGAR CIKs**
```bash
docker compose exec api python -m app.cli.edgar match-cik
```
Searches EDGAR for each manager by name and scores candidates. High-confidence matches are marked `confirmed` automatically; the rest need manual review in the DB (`match_status = 'candidate'`).

**Step 2 — Backfill historical quarters (one-time)**
```bash
docker compose exec api python -m app.cli.edgar backfill --quarters 8
```
Fetches `form.idx` indexes and downloads + parses all filings for the last N quarters. Takes 30–60 min for 5 quarters across 80 managers. Use `--quarters 8` to cover ~2 years of history.

**Step 3 — Build the CUSIP → ticker map**
```bash
# Round 1: match by name against Dataroma holdings pages
docker compose exec api python -m app.cli.edgar enrich-cusip

# Round 2: bootstrap stocks table + backfill stock_id
docker compose exec api python -m app.cli.edgar bootstrap-stocks

# Round 3: match remaining CUSIPs against SEC company_tickers.json
docker compose exec api python -m app.cli.edgar enrich-stocks-edgar
```

**Step 4 — Data quality check**
```bash
docker compose exec api python -m app.cli.edgar quality-check
# Scope to a specific quarter:
docker compose exec api python -m app.cli.edgar quality-check --quarter 2025-Q1
```

---

### Quarterly Update

**In production, this runs automatically.** The scheduler (`EDGAR_SCHEDULER_ENABLED=true` in
`docker-compose.prod.yml`) triggers every Monday at 06:00 UTC, checks whether a new quarter's
filings are available, and runs the full pipeline if so. It is idempotent — if the quarter is
already ingested, it skips.

Filing deadlines (when a quarter becomes available): Feb 14 (Q4), May 15 (Q1), Aug 14 (Q2), Nov 14 (Q3).

**In dev, run manually:**
```bash
# 1. Fetch new quarter's index + holdings
docker compose exec api python -m app.cli.edgar backfill --quarters 1

# 2. Refresh CUSIP mappings for any new holdings
docker compose exec api python -m app.cli.edgar enrich-cusip
docker compose exec api python -m app.cli.edgar bootstrap-stocks
docker compose exec api python -m app.cli.edgar enrich-stocks-edgar

# 3. Verify data quality
docker compose exec api python -m app.cli.edgar quality-check --quarter <YYYY-Qn>
```

---

### Other Useful Commands

```bash
# Re-parse a single filing from stored raw doc (no network call)
docker compose exec api python -m app.cli.edgar reparse-filing --accession 0001234567-25-000001

# Re-parse all filings from stored raw docs (after parser fixes)
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

### Known Limitations

- **~10% of holdings have no `stock_id`** — small, foreign, or delisted securities not found in Dataroma or SEC `company_tickers.json`. Appear in API responses with `ticker: null`.
- **Kahn Brothers reconciliation warnings are expected** — they report values in dollars, not thousands (genuine filer non-compliance; not a pipeline bug).
- **2025-Q1 has limited data** — the original backfill ran `--quarters 5` from April 2026, which excludes 2025-Q1. Run `backfill --quarters 8` to fill the gap.
