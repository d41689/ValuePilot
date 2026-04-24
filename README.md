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
docker compose exec api python -m app.cli.edgar backfill --quarters 5
```
Fetches `form.idx` indexes and downloads + parses all filings for the last N quarters. Takes 30–60 min for 5 quarters across 80 managers.

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

### Quarterly Update (run each quarter, ~45 days after quarter-end)

Approximate filing deadlines: Feb 14 (Q4), May 15 (Q1), Aug 14 (Q2), Nov 14 (Q3).

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

> **Note:** Quarterly updates are currently manual. Phase D will automate this with a scheduler
> (`EDGAR_SCHEDULER_ENABLED=true` in prod).

---

### Other Useful Commands

```bash
# Re-parse a single filing from stored raw doc (no network call)
docker compose exec api python -m app.cli.edgar reparse-filing --accession 0001234567-25-000001

# Re-parse all filings from stored raw docs (after parser fixes)
docker compose exec api python -m app.cli.edgar reparse-all
docker compose exec api python -m app.cli.edgar reparse-all --quarter 2025-Q1

# Backfill reported_total_value_thousands from stored primary docs
docker compose exec api python -m app.cli.edgar backfill-reported-totals
```

---

### API Endpoints (Phase C)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/institutions` | List confirmed institutions (`?superinvestor=true`) |
| GET | `/api/v1/institutions/{cik}/filings` | All filing versions for an institution |
| GET | `/api/v1/institutions/{cik}/holdings` | Latest-snapshot holdings (`?period=2024-Q4`) |
| GET | `/api/v1/filings/{accession_no}/holdings` | Holdings for a specific filing version |
| GET | `/api/v1/stocks/{ticker}/institutions` | Institutions holding a given ticker |

---

### Known Limitations

- **10.4% of holdings have no `stock_id`** — these are small, foreign, or delisted securities not found in Dataroma or SEC `company_tickers.json`. They appear in API responses with `ticker: null`.
- **Kahn Brothers reconciliation warnings are expected** — they report values in dollars, not thousands (genuine filer non-compliance; not a pipeline bug).
- **Quarterly updates are manual** until Phase D (scheduler) is implemented.
