# Oracle's Lens 13F Dashboard Product Plan

Status: Draft  
Owner: Product / Tech Lead  
Version: v0.1  
Last Updated: 2026-05-05  

---

## 1. Product Positioning

Oracle's Lens is a 13F-informed value investing dashboard for ValuePilot.

The product goal is not to build a trading terminal. The goal is to help long-term investors answer three questions quickly:

1. Which high-quality businesses are held by multiple selected superinvestors?
2. Which of those holdings are improving or increasing across recent 13F quarters?
3. Which of those businesses are currently worth deeper research based on Value Line fundamentals and valuation proxies?

The dashboard should be honest about data limitations. 13F filings are delayed, do not disclose transaction prices, and only report long positions in reportable securities. ValuePilot must not present inferred values as facts.

---

## 2. Current Data Reality

As of local development data checked on 2026-05-05:

| Dataset | Current Availability |
| --- | ---: |
| Confirmed institution managers | 80 |
| Managers flagged as superinvestors | 80 |
| 13F filings | 477 |
| Latest 13F filings per period | 459 |
| 13F holding rows | 32,703 |
| Holdings linked to `stocks.id` | 15,778 |
| CUSIP ticker map rows | 1,912 |
| Stocks | 1,690 |
| Stock prices | 23 |
| Current metric facts | 2,317 |

Important implications:

- We can build a useful 13F consensus MVP.
- We cannot yet support a reliable full-market historical price backtest.
- We cannot claim to know superinvestor transaction costs.
- We can combine 13F holdings with Value Line facts only where stock identity and ticker mapping are resolved.
- Quality and valuation coverage must be shown explicitly rather than hidden.

---

## 3. Product Name and Navigation

Product name: **Oracle's Lens**

Primary route:

```text
/13f/oracles-lens
```

Navigation group:

```text
Research
  - Watchlists
  - Documents
  - Oracle's Lens
```

Dashboard sections:

1. **Consensus Radar**
2. **Compounding Engines**
3. **Sweet Spot Monitor**

The original product wording uses "Smart Money", "Oracle", and "Master" language. In the product UI, avoid overclaiming. Prefer precise labels:

- `Superinvestor Consensus`
- `13F Holder Cluster`
- `Quarter-End Holding Price Estimate`
- `Value Line Quality Overlay`

---

## 4. Goals

### 4.1 User Goals

- See a short list of stocks held by multiple selected superinvestors.
- Understand whether managers are adding, reducing, entering, or exiting.
- Compare 13F consensus against Value Line business quality data.
- Identify potential research candidates where current price is below a valuation proxy.
- Drill into a company without losing provenance.

### 4.2 Business Goals

- Turn raw 13F ingestion into a premium research workflow.
- Reuse ValuePilot's existing Value Line parser and normalized metric facts.
- Create a defensible wedge that combines holdings, quality, and valuation.
- Avoid misleading users with unsupported "guru cost basis" claims.

---

## 5. Non-Goals for V1

V1 must not include:

- Real-time market data.
- Intraday charting or complex K-line views.
- Actual superinvestor transaction price or cost basis.
- AI moat score based on 10-K or research reports.
- 2008 / 2020 time-machine replay.
- Broker integration or trading actions.
- Any claim that 13F additions are fresh buys after quarter end.

V1 may include clearly labeled estimates:

- Quarter-end holding price estimate:

```text
value_thousands * 1000 / shares
```

This is not a transaction cost. It is a reported quarter-end holding value per reported share.

---

## 6. Data Contracts

### 6.1 Source of Truth

13F source of truth:

- `institution_managers`
- `filings_13f`
- `holdings_13f`
- `cusip_ticker_map`

Financial metric source of truth:

- `metric_facts`
- Always query `metric_facts.is_current = true`
- Always use `value_numeric` for numeric comparisons
- Preserve provenance through `source_document_id`, `source_type`, `period_type`, and `period_end_date`

Price source:

- `stock_prices`
- EOD close only
- Current local price coverage is too sparse for full dashboard coverage

### 6.2 13F Rules

- Only include `InstitutionManager.match_status = 'confirmed'`.
- Default filter uses `InstitutionManager.is_superinvestor = true`.
- Only include canonical filings where `Filing13F.is_latest_for_period = true`.
- Default holding universe excludes:
  - rows where `put_call` is not null
  - rows with missing `shares`
  - rows with missing `stock_id`
- Default ranking uses latest complete quarter, not partially ingested quarters.
- A period is "complete enough" only if it has configurable minimum manager coverage.

### 6.3 Value Line Overlay Rules

Quality overlay may use existing facts:

| Product Metric | Current Data Source | V1 Status |
| --- | --- | --- |
| Owner Earnings Yield | `owners_earnings_per_share_normalized` / EOD price | Partial |
| Piotroski F-Score | `score.piotroski.total` | Available where Value Line facts exist |
| Net Profit Margin | `is.net_profit_margin` | Available where parsed |
| Return on Total Capital | `bs.return_on_total_capital` | Available as Value Line proxy |
| Return on Equity | `bs.return_on_equity` | Available where parsed |
| Debt to Capital | `leverage.long_term_debt_to_capital` | Available where parsed |
| Dividend growth | `per_share.dividends_paid` or declared dividends | Partial |
| Buyback rate | `equity.shares_outstanding` change | Partial |
| Moat Score | Not available | Out of V1 |

---

## 7. Core Metrics

### 7.1 Consensus Count

Number of superinvestor managers holding the stock in the selected quarter.

```text
consensus_count = count(distinct manager_id)
```

Eligibility:

```text
consensus_count >= 3
```

### 7.2 Portfolio Weight

Per manager:

```text
manager_position_weight = holding.value_thousands / filing.computed_total_value_thousands
```

Fallback:

```text
filing.reported_total_value_thousands
```

Dashboard aggregate:

```text
aggregate_weight = sum(manager_position_weight)
```

This drives bubble size in Consensus Radar.

### 7.3 Add Intensity

Use shares rather than value when possible.

Per manager / stock:

```text
share_delta_pct = (current_shares - previous_shares) / previous_shares
```

Classify:

| State | Rule |
| --- | --- |
| New | previous holding missing, current holding present |
| Add | shares increased by more than threshold |
| Flat | change within threshold |
| Reduce | shares decreased by more than threshold |
| Exit | previous holding present, current holding missing |

Suggested default threshold:

```text
5%
```

Dashboard aggregate:

```text
add_intensity = weighted average of manager action scores
```

Suggested action scores:

| Action | Score |
| --- | ---: |
| New | 1.00 |
| Add | 0.70 |
| Flat | 0.00 |
| Reduce | -0.50 |
| Exit | -1.00 |

Weight by prior or current position weight.

### 7.4 Quarter-End Holding Price Estimate

```text
quarter_end_holding_price = holding.value_thousands * 1000 / holding.shares
```

Display label:

```text
13F quarter-end holding price estimate
```

Do not label this as:

- cost basis
- average buy price
- transaction price
- guru cost

### 7.5 Owner Earnings Yield

```text
owner_earnings_yield = owners_earnings_per_share_normalized / current_price
```

Requirements:

- `owners_earnings_per_share_normalized` current fact exists.
- EOD price exists.

If price is missing, show unavailable with reason.

### 7.6 Capital Allocation Grade

V1 should use a transparent score, not an opaque AI score.

Inputs:

- share count decline: `equity.shares_outstanding`
- dividend growth: `per_share.dividends_paid`
- capital return proxy: `bs.return_on_total_capital`
- leverage control: `leverage.long_term_debt_to_capital`

Initial grade:

```text
A: 80-100
B: 65-79
C: 50-64
D: 35-49
F: <35
```

Every grade must expose input coverage and raw values.

### 7.7 Moat Proxy

V1 must not implement the proposed AI moat score.

Alternative V1 label:

```text
Quality Evidence
```

Possible inputs:

- stable high margins
- high return on capital
- positive / improving Piotroski score
- Value Line price stability
- Value Line price growth persistence

---

## 8. User Experience

### 8.1 Page Layout

Use a dense research dashboard layout:

```text
┌──────────────────────────────────────────────────────────┐
│ Header: Oracle's Lens                                    │
│ Period selector | Superinvestor filter | Coverage status │
├───────────────┬──────────────────────────────────────────┤
│ Sidebar       │ Consensus Radar                          │
│ Filters       │ Compounding Engines table                │
│               │ Sweet Spot Monitor                       │
└───────────────┴──────────────────────────────────────────┘
```

Design constraints:

- Use shadcn/ui and Tailwind.
- Use compact cards only for repeated entities or tool panels.
- Avoid marketing-style hero sections.
- Use 4px to 8px radius.
- Avoid decorative gradients, orbs, and oversized headings.
- Prioritize readable tables, controls, and provenance.

### 8.2 Consensus Radar

V1 visualization options:

1. Table-first implementation.
2. Bubble chart as enhancement after data contract is stable.

Recommended V1:

- Start with a ranked table.
- Add compact circle markers for aggregate weight and add intensity.
- Defer full bubble chart until performance and responsive behavior are verified.

Columns:

| Column | Description |
| --- | --- |
| Ticker | Resolved stock ticker |
| Company | Stock company name |
| Consensus | Number of superinvestors holding |
| Adders | Managers classified as New or Add |
| Reducers | Managers classified as Reduce or Exit |
| Aggregate Weight | Sum of position weights |
| Latest 13F Period | Quarter |
| Coverage | Value Line / price coverage |

Hover / detail popover:

- Manager display name
- Current shares
- Previous shares
- Action classification
- Position weight
- Quarter-end holding price estimate
- Filing date

### 8.3 Compounding Engines

Table view with quality metrics:

| Column | Description |
| --- | --- |
| Ticker | Stock |
| Consensus | Number of managers |
| Owner Earnings Yield | OEPS / price |
| Piotroski | Latest total and trend |
| ROTC / ROE | Value Line return proxy |
| Margin | Net profit margin |
| Capital Allocation | Transparent grade |
| Debt | Long-term debt to capital |

Click behavior:

- Open a side panel.
- Side panel should show:
  - 13F manager list
  - Value Line quality facts
  - active report provenance
  - historical restatement warnings if available
  - link to document review

### 8.4 Sweet Spot Monitor

Each stock row can show a valuation strip.

V1 endpoints:

- Left marker: quarter-end holding price estimate range from 13F holders.
- Middle marker: current EOD price.
- Right marker: fair value proxy.

Fair value priority:

1. Manual fair value fact if user supplied one.
2. Value Line `target.price_18m.mid`.
3. DCF result only if a persisted/manual DCF value exists in future.

Visual state:

| State | Rule |
| --- | --- |
| Below holder estimate | `current_price < min(quarter_end_holding_price_estimate)` |
| Below fair value | `current_price < fair_value_proxy` |
| Missing price | neutral with unavailable reason |
| Missing fair value | no MOS calculation |

Do not imply immediate buy signals.

### 8.5 Noise Filter

V1:

- Toggle: `Superinvestors only`
- Default on.

V2:

- Add manager taxonomy:
  - value investor
  - quant
  - index manager
  - activist
  - family office

The original "hide Renaissance, Two Sigma, BlackRock, Vanguard" behavior requires this taxonomy. Do not hardcode name exclusions in product code.

### 8.6 Time-Machine Sync

V1:

- Period selector for available 13F quarters.
- Allow moving across ingested quarters only.

Out of V1:

- 2008 / 2020 replay.
- historical price-synchronized replay before price coverage is expanded.

---

## 9. API Plan

### 9.1 New Endpoint: Dashboard Summary

```text
GET /api/v1/13f/oracles-lens
```

Query params:

| Param | Type | Default | Description |
| --- | --- | --- | --- |
| `period` | string | latest complete | `YYYY-Qn` |
| `lookback_quarters` | int | 4 | Used for action classification |
| `min_holders` | int | 3 | Consensus threshold |
| `superinvestor_only` | bool | true | Filter managers |
| `limit` | int | 50 | Result limit |
| `sort` | string | `consensus` | `consensus`, `add_intensity`, `aggregate_weight`, `quality` |

Response sketch:

```json
{
  "period": "2025-Q4",
  "coverage": {
    "manager_count": 66,
    "holding_count": 4609,
    "linked_holding_count": 3723,
    "price_coverage_count": 4,
    "value_line_coverage_count": 12
  },
  "items": [
    {
      "stock_id": 4333,
      "ticker": "ADBE",
      "company_name": "Adobe Inc.",
      "consensus_count": 4,
      "adders_count": 2,
      "reducers_count": 1,
      "aggregate_weight": 0.082,
      "add_intensity": 0.41,
      "holder_price_estimate_low": 248.63,
      "holder_price_estimate_high": 312.40,
      "current_price": 248.63,
      "fair_value_proxy": 326.50,
      "owner_earnings_yield": 0.061,
      "piotroski_total": 7,
      "quality_coverage": {
        "value_line": true,
        "price": true,
        "owner_earnings": true
      }
    }
  ]
}
```

### 9.2 New Endpoint: Stock Drilldown

```text
GET /api/v1/13f/oracles-lens/stocks/{stock_id}
```

Response sections:

- 13F holders by quarter
- action classifications
- Value Line quality metrics
- valuation strip inputs
- provenance and unavailable reasons

### 9.3 Reuse Existing Endpoints

Existing institutional endpoints remain useful for raw views:

- `GET /api/v1/institutions`
- `GET /api/v1/institutions/{cik}/holdings`
- `GET /api/v1/stocks/{ticker}/institutions`

Oracle's Lens should not force the frontend to assemble all analytics by calling raw endpoints repeatedly. It needs a dashboard-specific aggregate endpoint.

---

## 10. Backend Implementation Plan

### Phase 0: Data Audit and Coverage Gate

Goal:

- Make sure the dashboard only uses sufficiently complete 13F periods.

Tasks:

- Add a service that computes 13F period coverage.
- Define "latest complete period" based on manager count and holding count.
- Add tests for partially ingested periods.
- Add indexes if query performance requires them.

Acceptance criteria:

- API can identify latest complete period.
- 2026-Q1 partial data does not become default if it has insufficient manager coverage.

### Phase 1: 13F Consensus Service

Goal:

- Produce stock-level consensus rows from latest and previous holdings.

Tasks:

- Create `app/services/oracles_lens/consensus.py`.
- Join `holdings_13f`, `filings_13f`, `institution_managers`, `stocks`.
- Compute:
  - consensus count
  - aggregate position weight
  - manager action classification
  - adders / reducers
  - quarter-end holding price estimate range
- Add unit tests with synthetic holdings.

Acceptance criteria:

- Same stock held by at least 3 managers appears.
- New/Add/Flat/Reduce/Exit classification is deterministic.
- Put/call rows and unlinked holdings are excluded by default.

### Phase 2: Quality Overlay Service

Goal:

- Enrich consensus rows with Value Line facts.

Tasks:

- Create `app/services/oracles_lens/quality_overlay.py`.
- Query current `metric_facts` by stock IDs.
- Compute:
  - owner earnings yield when price exists
  - Piotroski latest score
  - ROTC / ROE
  - net profit margin
  - debt to capital
  - capital allocation grade V1
- Return coverage flags and unavailable reasons.

Acceptance criteria:

- Missing facts do not hide the stock.
- Missing facts do not produce fake zero values.
- Every displayed derived metric exposes input coverage.

### Phase 3: Dashboard API

Goal:

- Provide frontend-ready payloads.

Tasks:

- Add `backend/app/api/v1/endpoints/oracles_lens.py`.
- Add routes to `api.py`.
- Add response schemas.
- Add query params for period, min holders, lookback, and filters.
- Add tests for endpoint response shape and filters.

Acceptance criteria:

- `GET /api/v1/13f/oracles-lens` returns ranked rows.
- Response includes coverage summary.
- Query uses current facts and EOD prices, not JSON-only comparisons.

### Phase 4: Frontend Dashboard V1

Goal:

- Build usable table-first dashboard.

Tasks:

- Add route `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`.
- Add components:
  - `OraclesLensHeader`
  - `ConsensusRadarTable`
  - `QualityOverlayColumns`
  - `SweetSpotStrip`
  - `HolderDrilldownPanel`
- Use shadcn/ui components.
- Add empty states and unavailable reasons.

Acceptance criteria:

- User can scan ranked stocks.
- User can see holders and add/reduce actions.
- User can see data coverage.
- No unsupported "cost basis" copy appears.

### Phase 5: Bubble Chart Enhancement

Goal:

- Add visual cluster view after table data is stable.

Tasks:

- Evaluate charting library or implement lightweight SVG/canvas.
- Bubble size = aggregate weight.
- Bubble color = add intensity.
- Tooltip = holders and estimates.

Acceptance criteria:

- Bubble chart is responsive and accessible.
- Table remains the primary exact-data view.
- Visual encoding is documented and tested.

### Phase 6: Price and Historical Expansion

Goal:

- Support richer Sweet Spot and historical period navigation.

Tasks:

- Expand EOD price coverage for all resolved 13F stock IDs.
- Backfill price history for ingested 13F periods.
- Add period timeline.
- Add historical price-at-period-end comparisons.

Acceptance criteria:

- Period selector has price coverage metadata.
- Time navigation is limited to periods with adequate 13F and price data.
- No 2008/2020 UI is exposed until data exists.

---

## 11. Frontend Visual Direction

The original "modern luxury" direction is acceptable if kept restrained.

Recommended palette:

| Token | Color | Usage |
| --- | --- | --- |
| Graphite | `#1A1A1B` | dark mode surface |
| Warm paper | `#F2EEE7` | light mode background |
| Champagne | `#B89B4A` | restrained accent |
| Positive | `#2F7D5F` | margin of safety positive |
| Warning | `#A66A2A` | incomplete coverage |
| Negative | `#8A3D3D` | reduce / overvalued |

Implementation notes:

- Do not make the whole page dark-only unless the app supports theme consistently.
- Use champagne only as a small accent, not as dominant text.
- Data tables should use high contrast and compact spacing.
- Numeric columns should align right and use tabular numbers.

---

## 12. Data Integrity and Product Copy Rules

Required copy rules:

- Use "13F reported holding value" instead of "cost basis".
- Use "quarter-end holding price estimate" instead of "average buy price".
- Use "reported after quarter end" where timing matters.
- Show filing period and filing date.
- Show unavailable reasons:
  - missing price
  - missing Value Line report
  - unlinked CUSIP
  - incomplete 13F period

Forbidden copy in V1:

- "guru cost"
- "master purchase price"
- "actual buy price"
- "real-time smart money"
- "AI moat score"
- "now cheaper than their cost" unless the value is clearly labeled as an estimate

---

## 13. Dependencies and Risks

### 13.1 Dependencies

- 13F ingestion and CUSIP enrichment must run reliably.
- More EOD prices must be refreshed for 13F-linked stocks.
- Value Line parsing coverage must grow for quality overlay to be meaningful.
- Manager taxonomy is needed for advanced noise filtering.

### 13.2 Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| 13F delay creates stale signals | Users may overtrust old data | Display period and filed date prominently |
| CUSIP mapping errors | Wrong stock linkage | Show confidence and allow review workflow later |
| Sparse price coverage | Sweet Spot appears empty | Start with coverage summary and refresh workflow |
| Value Line coverage sparse | Quality overlay inconsistent | Sort/filter by coverage but do not hide missingness |
| Cost basis misinterpretation | Product trust risk | Strict copy rules and labels |
| Query performance | Dashboard slow | Aggregate service, indexes, pagination |

---

## 14. Milestone Plan

### Milestone 1: Data-Truth MVP

Deliver:

- Coverage audit service.
- Consensus service.
- Dashboard API without frontend.
- Unit tests.

Estimated scope:

- Backend only.
- No schema change unless indexes are required.

### Milestone 2: Table-First Dashboard

Deliver:

- `/13f/oracles-lens` route.
- Ranked consensus table.
- Superinvestor-only toggle.
- Period selector for available complete periods.
- Holder drilldown panel.

Estimated scope:

- Frontend + API integration.

### Milestone 3: Quality and Sweet Spot Overlay

Deliver:

- Owner earnings yield where available.
- Piotroski / ROTC / net margin / debt overlay.
- Fair value proxy and MOS strip.
- Unavailable reason display.

Estimated scope:

- Backend enrichment + frontend columns.

### Milestone 4: Visual Radar

Deliver:

- Bubble chart or compact cluster visualization.
- Tooltip with holder actions.
- Responsive QA.

Estimated scope:

- Frontend visualization.

### Milestone 5: Historical Expansion

Deliver:

- EOD price backfill for 13F-linked stocks.
- Period timeline.
- Historical snapshot mode for available periods.

Estimated scope:

- Data pipeline + API + frontend.

---

## 15. First Engineering Tasks

Recommended task files:

1. `docs/tasks/YYYY-MM-DD_oracles-lens-coverage-audit.md`
2. `docs/tasks/YYYY-MM-DD_oracles-lens-consensus-service.md`
3. `docs/tasks/YYYY-MM-DD_oracles-lens-dashboard-api.md`
4. `docs/tasks/YYYY-MM-DD_oracles-lens-table-ui.md`
5. `docs/tasks/YYYY-MM-DD_oracles-lens-quality-overlay.md`
6. `docs/tasks/YYYY-MM-DD_oracles-lens-sweet-spot.md`

Each implementation task must follow the project workflow:

- Write task file first.
- Write tests first.
- Run verification inside Docker Compose.
- Preserve metric facts contract.
- Do not introduce raw SQL from user input.
- Do not infer unsupported transaction prices.

---

## 16. MVP Success Criteria

Oracle's Lens V1 is successful when:

- The user can open one dashboard and see 10-50 consensus candidates.
- Each candidate shows which superinvestors hold it.
- The user can distinguish adding, reducing, new, and exited positions.
- The user can see whether Value Line quality data is available.
- The user can see current price vs fair value proxy where price exists.
- Unsupported values are clearly labeled as unavailable or estimated.
- The dashboard never claims to know actual 13F transaction prices.

---

## 17. Product Decision Summary

The original "Oracle's Lens" concept is directionally strong, but V1 must be grounded in the data ValuePilot actually has.

Approved V1 framing:

```text
13F consensus + Value Line quality overlay + valuation proxy
```

Deferred:

```text
actual guru cost basis
AI moat score
full historical time-machine replay
real-time market behavior
```

This produces a credible premium research dashboard without overstating the precision of 13F data.
