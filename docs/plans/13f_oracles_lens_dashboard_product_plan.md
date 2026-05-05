# Oracle's Lens 13F Dashboard Product Plan

Status: Draft  
Owner: Product / Tech Lead  
Version: v0.1  
Last Updated: 2026-05-05  

---

## 1. Product Positioning

Oracle's Lens is a 13F-informed research candidate discovery system for ValuePilot.

The product goal is not to build a trading terminal. The goal is to help long-term investors answer three questions quickly:

1. Which high-quality businesses are held by multiple selected superinvestors?
2. Which of those ownership signals are meaningful rather than noisy copycat bait?
3. Which of those businesses are worth deeper research based on Value Line fundamentals, valuation references, and disconfirming evidence?

The dashboard should be honest about data limitations. 13F filings are delayed, do not disclose transaction prices, and only report long positions in reportable securities. ValuePilot must not present inferred values as facts.

Oracle's Lens is a research candidate discovery system, not a trading signal or copycat system. Its job is to reduce low-value research work by surfacing a smaller set of companies that deserve careful independent analysis.

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

1. **Coverage and Data Freshness**
2. **Signal-Weighted Consensus**
3. **Business Quality Overlay**
4. **Valuation Reference**
5. **Caution Flags**

The original product wording uses "Smart Money", "Oracle", and "Master" language. In the product UI, avoid overclaiming. Prefer precise labels:

- `Superinvestor Consensus`
- `13F Holder Cluster`
- `Quarter-End Holding Price Estimate`
- `Value Line Quality Overlay`
- `Valuation Reference`
- `Caution Flags`

---

## 4. Goals

### 4.1 User Goals

- See a short list of stocks held by multiple selected superinvestors.
- Understand whether managers are adding, reducing, entering, or exiting.
- Compare 13F consensus against Value Line business quality data.
- Identify potential research candidates where current price is below a clearly labeled valuation reference.
- See why a 13F signal may be stale, weak, crowded, or otherwise misleading.
- Drill into a company without losing provenance.

### 4.2 Business Goals

- Turn raw 13F ingestion into a premium research workflow.
- Reuse ValuePilot's existing Value Line parser and normalized metric facts.
- Create a defensible wedge that combines 13F behavior, manager signal quality, holding duration, business quality, valuation references, and disconfirming evidence.
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
- Buy / sell recommendations.
- Copycat ranking based only on which manager bought what.

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
- V1 ranking must not treat every manager as equally informative. It must include a manager signal profile, even if some fields start as derived proxies or manually seeded metadata.
- If manager type is unknown, display it as `Unknown` and use neutral or reduced signal weight rather than silently treating it as a high-quality long-term fundamental manager.

### 6.3 Manager Signal Profile

The Munger-style product principle is that a 13F filing is not equally valuable from every institution. A concentrated long-term fundamental investor carries a different signal than a high-turnover quant or index-like manager.

V1 should create a minimal manager signal profile from available data and explicit metadata:

| Field | V1 Source | Usage |
| --- | --- | --- |
| `manager_type` | seeded metadata, initially nullable | classify long-term fundamental, value concentrated, activist, quant, index-like, unknown |
| `portfolio_concentration` | latest 13F holdings distribution | higher concentration means stronger signal |
| `average_holding_period` | historical 13F streaks | longer holding periods mean stronger signal |
| `turnover_proxy` | quarter-to-quarter holding churn | high turnover reduces signal weight |
| `position_weight_rank` | rank within manager portfolio | top holdings are stronger than tail positions |
| `historical_style_relevance` | seeded metadata or later backtest | optional V2 refinement |

Default V1 manager type weights:

| Manager Type | Default Consensus Treatment |
| --- | --- |
| Long-term fundamental | full weight |
| Value-oriented concentrated | full weight |
| Activist | included, clearly marked |
| Quant | reduced weight or separate filter |
| Index / ETF-like | excluded or near-zero weight |
| Very high turnover | reduced weight |
| Unknown | neutral-to-reduced weight with visible coverage warning |

Do not hardcode exclusions by manager name in product logic. Use manager metadata or derived profile fields.

### 6.4 Value Line Overlay Rules

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

### 7.1 Raw Consensus Count

Number of superinvestor managers holding the stock in the selected quarter.

```text
consensus_count = count(distinct manager_id)
```

Eligibility:

```text
consensus_count >= 3
```

Raw holder count is useful for explainability, but it must not be the primary ranking signal. Three concentrated long-term managers are more informative than three index-like or high-turnover holders.

### 7.2 Signal-Weighted Consensus Score

Primary V1 ranking metric:

```text
signal_weighted_consensus_score =
  sum(manager_signal_weight * position_signal_weight)
```

Where:

```text
manager_signal_weight = f(manager_type, portfolio_concentration, average_holding_period, turnover_proxy)
position_signal_weight = f(position_weight, position_weight_rank, holding_streak_quarters, action_score)
```

V1 may start with transparent heuristics. It must expose component inputs and avoid opaque "AI score" behavior.

### 7.3 Portfolio Weight

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

This can drive bubble size in the later visual radar enhancement.

### 7.4 Add Intensity

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

### 7.5 Quarter-End Holding Price Estimate

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

### 7.6 Owner Earnings Yield

```text
owner_earnings_yield = owners_earnings_per_share_normalized / current_price
```

Requirements:

- `owners_earnings_per_share_normalized` current fact exists.
- EOD price exists.

If price is missing, show unavailable with reason.

### 7.7 Capital Allocation Grade

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

### 7.8 Moat Proxy

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

### 7.9 Conviction Score

Conviction is different from simple add/reduce behavior. The product should show whether a holding is a core position or a small tail position.

Suggested V1 formula:

```text
conviction_score =
  position_weight_score
  + position_rank_score
  + holding_duration_score
  + action_score
  + manager_signal_weight
```

Inputs:

| Input | Reason |
| --- | --- |
| Position weight | Larger weight suggests higher conviction |
| Position rank | Top 10 positions matter more than small tail positions |
| Holding duration | Persistent ownership is more meaningful than one quarter |
| Recent action | New/Add/Flat/Reduce/Exit adds context |
| Manager signal weight | Better managers should carry more signal |

The UI should prefer explanations such as:

```text
2 high-signal managers hold this as a top 10 position, with a median holding streak of 7 quarters.
```

over:

```text
5 managers hold this stock.
```

### 7.10 Holding Duration and Streak

13F data is especially useful for studying persistent ownership behavior.

Per manager / stock:

```text
manager_holding_duration = count(consecutive quarters with current holding present)
```

Stock-level summary:

```text
median_holding_streak_quarters
max_holding_streak_quarters
long_term_holder_count = count(manager_holding_duration >= threshold)
```

Suggested V1 long-term threshold:

```text
4 quarters
```

Drilldown table should include:

| Manager | Current Weight | Action | Holding Streak |
| --- | ---: | --- | ---: |
| Fund A | 8.2% | Add | 9 quarters |
| Fund B | 3.1% | Flat | 6 quarters |
| Fund C | 1.4% | New | 1 quarter |

### 7.11 Distinctive Consensus Score

High raw consensus can be weak if it simply reflects mega-cap popularity. V1 should include a distinctiveness layer:

```text
distinctive_consensus_score =
  signal_weighted_consensus_score
  * concentration_factor
  * persistence_factor
  * anti_crowding_factor
```

V1 anti-crowding proxy:

- reduce score for stocks where consensus is driven mostly by small position weights
- reduce score when holders are mostly low-signal or unknown manager types
- flag mega-cap / broadly held names as potentially crowded when market cap data becomes available

This score is a research prioritization aid, not an alpha claim.

### 7.12 Caution Flags

Every candidate should carry negative evidence, not only positive signals.

Initial V1 flags:

| Flag | Meaning |
| --- | --- |
| `stale_filing` | 13F filing is a delayed snapshot |
| `low_conviction` | many holders, but mostly small weights |
| `crowded_mega_cap` | consensus may reflect broad market exposure rather than insight |
| `weak_quality_coverage` | Value Line facts are missing or sparse |
| `price_moved_up` | current price is far above quarter-end holding price estimate |
| `mixed_actions` | high-signal managers disagree: some add, others reduce |
| `short_holding_streak` | position is recent and not yet persistent |
| `high_turnover_holders` | signal comes mostly from managers with high churn |
| `valuation_reference_missing` | no reliable valuation reference is available |

Caution flags should appear in both the table and the stock drilldown. They are part of the product's value, not edge-case warnings.

---

## 8. User Experience

### 8.1 Page Layout

Use a dense research-funnel layout:

```text
┌──────────────────────────────────────────────────────────┐
│ Header: Oracle's Lens                                    │
│ Fixed 13F delay notice                                   │
│ Period selector | Signal filter | Coverage status        │
├───────────────┬──────────────────────────────────────────┤
│ Sidebar       │ Coverage & Data Freshness                │
│ Filters       │ Signal-Weighted Consensus                │
│               │ Business Quality Overlay                 │
│               │ Valuation Reference                      │
│               │ Caution Flags                            │
└───────────────┴──────────────────────────────────────────┘
```

The page must show this notice in a visible fixed area, not only in a tooltip:

```text
13F filings are delayed snapshots. They show reported quarter-end holdings, not current holdings, transaction prices, or buy recommendations.
```

Design constraints:

- Use shadcn/ui and Tailwind.
- Use compact cards only for repeated entities or tool panels.
- Avoid marketing-style hero sections.
- Use 4px to 8px radius.
- Avoid decorative gradients, orbs, and oversized headings.
- Prioritize readable tables, controls, and provenance.

### 8.2 Coverage and Data Freshness

This section appears above the stock list.

Fields:

- latest complete 13F period
- filing date range
- manager coverage
- holding coverage
- CUSIP-to-stock linkage coverage
- price coverage
- Value Line coverage
- partial period warning

Purpose:

- Make data freshness and missingness impossible to miss.
- Prevent users from treating partial 13F periods as current market intelligence.

### 8.3 Signal-Weighted Consensus

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
| Signal Score | Signal-weighted consensus score |
| Raw Holders | Number of superinvestors holding |
| Top Holders | Highest-signal manager names |
| Adders | Managers classified as New or Add |
| Reducers | Managers classified as Reduce or Exit |
| Conviction | Position rank, weight, duration, and manager quality composite |
| Holding Streak | Median / max consecutive holding quarters |
| Aggregate Weight | Sum of position weights |
| Latest 13F Period | Quarter |
| Caution | Highest-priority caution flag |
| Coverage | Value Line / price coverage |

Hover / detail popover:

- Manager display name
- Current shares
- Previous shares
- Action classification
- Position weight
- Position rank
- Manager signal profile
- Holding streak
- Quarter-end holding price estimate
- Filing date

### 8.4 Business Quality Overlay

Table view with quality metrics:

| Column | Description |
| --- | --- |
| Ticker | Stock |
| Signal Score | Signal-weighted ownership score |
| Owner Earnings Yield | OEPS / price |
| Piotroski | Latest total and trend |
| ROTC / ROE | Value Line return proxy |
| Margin | Net profit margin |
| Capital Allocation | Transparent grade |
| Debt | Long-term debt to capital |

Click behavior:

- Open a side panel.
- Side panel should show:
  - 13F manager-by-manager history
  - holding duration and action changes
  - Value Line quality facts
  - valuation reference inputs
  - caution flags
  - active report provenance
  - historical restatement warnings if available
  - link to document review

### 8.5 Valuation Reference

Each stock row can show a valuation strip.

V1 endpoints:

- Left marker: quarter-end holding price estimate range from 13F holders.
- Middle marker: current EOD price.
- Right marker: selected valuation reference.

Valuation reference priority:

1. Manual valuation reference fact if user supplied one.
2. Value Line `target.price_18m.mid`.
3. DCF result only if a persisted/manual DCF value exists in future.

Visual state:

| State | Rule |
| --- | --- |
| Below holder estimate | `current_price < min(quarter_end_holding_price_estimate)` |
| Below selected valuation reference | `current_price < valuation_reference` |
| Missing price | neutral with unavailable reason |
| Missing valuation reference | no discount calculation |

Do not imply immediate buy signals. Value Line `target.price_18m.mid` is not intrinsic value by default. UI copy must say `Below selected valuation reference` or `Below Value Line 18-month target midpoint`, not `Below fair value`.

### 8.6 Caution Flags Panel

Every stock drilldown should include a panel titled:

```text
Why This Signal May Be Misleading
```

or:

```text
Caution Flags
```

Example flags:

- 13F data is stale or partial.
- Current price moved materially above quarter-end holding price estimate.
- Value Line quality coverage is missing.
- Holdings are low weight despite high holder count.
- Signal comes mostly from high-turnover managers.
- High-signal managers are mixed: some added, others reduced.
- Holding streak is too short to infer long-term ownership.
- Valuation reference is missing or weak.

This panel should be visible in the drilldown, not hidden behind a tooltip.

### 8.7 Noise Filter

V1:

- Toggle: `Superinvestors only`
- Toggle: `Long-term / concentrated signal only` if manager signal profile coverage is sufficient.
- Default on.

V2:

- Add manager taxonomy:
  - value investor
  - quant
  - index manager
  - activist
  - family office

The original "hide Renaissance, Two Sigma, BlackRock, Vanguard" behavior requires this taxonomy. Do not hardcode name exclusions in product code.

### 8.8 Time-Machine Sync

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
| `min_signal_score` | float | null | Optional signal-weighted score floor |
| `limit` | int | 50 | Result limit |
| `sort` | string | `signal_weighted_consensus` | `signal_weighted_consensus`, `conviction`, `distinctive_consensus`, `add_intensity`, `aggregate_weight`, `quality` |

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
      "signal_weighted_consensus_score": 3.12,
      "distinctive_consensus_score": 2.48,
      "conviction_score": 78,
      "adders_count": 2,
      "reducers_count": 1,
      "aggregate_weight": 0.082,
      "add_intensity": 0.41,
      "median_holding_streak_quarters": 6,
      "max_holding_streak_quarters": 11,
      "holder_price_estimate_low": 248.63,
      "holder_price_estimate_high": 312.40,
      "current_price": 248.63,
      "valuation_reference": 326.50,
      "valuation_reference_label": "Value Line 18-month target midpoint",
      "owner_earnings_yield": 0.061,
      "piotroski_total": 7,
      "manager_signal_summary": {
        "high_signal_holder_count": 3,
        "unknown_manager_type_count": 1,
        "high_turnover_holder_count": 0
      },
      "quality_coverage": {
        "value_line": true,
        "price": true,
        "owner_earnings": true
      },
      "caution_flags": [
        {
          "key": "stale_filing",
          "severity": "info",
          "label": "13F filing is a delayed quarter-end snapshot"
        }
      ]
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
- manager signal profiles
- holding duration and streaks
- Value Line quality metrics
- valuation strip inputs
- caution flags and disconfirming evidence
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

- Produce stock-level raw consensus rows from latest and previous holdings.

Tasks:

- Create `app/services/oracles_lens/consensus.py`.
- Join `holdings_13f`, `filings_13f`, `institution_managers`, `stocks`.
- Compute:
  - consensus count
  - aggregate position weight
  - manager action classification
  - adders / reducers
  - quarter-end holding price estimate range
  - holding duration / streaks
- Add unit tests with synthetic holdings.

Acceptance criteria:

- Same stock held by at least 3 managers appears.
- New/Add/Flat/Reduce/Exit classification is deterministic.
- Put/call rows and unlinked holdings are excluded by default.
- Consecutive holding streaks are computed from canonical 13F periods.

### Phase 2: Manager Signal and Conviction Service

Goal:

- Rank ownership signals by manager quality, concentration, persistence, and position importance rather than raw holder count.

Tasks:

- Create `app/services/oracles_lens/manager_signal.py`.
- Compute or load:
  - manager type, initially `unknown` when not seeded
  - portfolio concentration
  - turnover proxy
  - average holding period
  - position weight rank
  - manager signal weight
- Create transparent `conviction_score` and `signal_weighted_consensus_score`.
- Add tests for manager type weights, unknown manager handling, high-turnover downweighting, and position-rank effects.

Acceptance criteria:

- Unknown manager types do not receive full long-term fundamental weight silently.
- Signal-weighted ranking differs from raw holder count when holdings are low-conviction or high-turnover.
- Every score exposes enough components for UI explanation.

### Phase 3: Quality Overlay Service

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

### Phase 4: Caution Flags Service

Goal:

- Add disconfirming evidence to every candidate.

Tasks:

- Create `app/services/oracles_lens/caution_flags.py`.
- Emit flags for stale filing, partial coverage, low conviction, weak quality coverage, price moved up, mixed actions, short streak, high-turnover holders, and missing valuation reference.
- Add tests for each flag condition.

Acceptance criteria:

- Drilldown and table payloads include caution flags.
- Flags are deterministic and do not block candidate inclusion unless explicitly filtered.
- Missing data is surfaced as an unavailable reason rather than converted to zero.

### Phase 5: Dashboard API

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
- Default sort uses signal-weighted consensus rather than raw holder count.
- Query uses current facts and EOD prices, not JSON-only comparisons.

### Phase 6: Frontend Dashboard V1

Goal:

- Build usable table-first dashboard.

Tasks:

- Add route `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`.
- Add components:
  - `OraclesLensHeader`
  - `CoverageFreshnessPanel`
  - `SignalWeightedConsensusTable`
  - `QualityOverlayColumns`
  - `ValuationReferenceStrip`
  - `CautionFlagsPanel`
  - `HolderDrilldownPanel`
- Use shadcn/ui components.
- Add empty states and unavailable reasons.

Acceptance criteria:

- User can scan ranked stocks.
- User can see holders and add/reduce actions.
- User can see signal-weighted consensus, conviction, and holding duration.
- User can see caution flags before opening the drilldown.
- User can see data coverage.
- No unsupported "cost basis" copy appears.

### Phase 7: Bubble Chart Enhancement

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

### Phase 8: Price and Historical Expansion

Goal:

- Support richer valuation reference and historical period navigation.

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
| Positive | `#2F7D5F` | discount to selected reference |
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

- Always show the fixed notice: "13F filings are delayed snapshots. They show reported quarter-end holdings, not current holdings, transaction prices, or buy recommendations."
- Use "13F reported holding value" instead of "cost basis".
- Use "quarter-end holding price estimate" instead of "average buy price".
- Use "reported after quarter end" where timing matters.
- Use "valuation reference" instead of "fair value" unless the value is explicitly user-entered as a fair value estimate.
- Use "discount to selected valuation reference" instead of "margin of safety" for system-derived references.
- Show filing period and filing date.
- Show unavailable reasons:
  - missing price
  - missing Value Line report
  - unlinked CUSIP
  - incomplete 13F period
  - unknown manager type
  - missing valuation reference

Forbidden copy in V1:

- "guru cost"
- "master purchase price"
- "actual buy price"
- "real-time smart money"
- "AI moat score"
- "now cheaper than their cost" unless the value is clearly labeled as an estimate
- "below fair value" for Value Line target or system-derived references
- "margin of safety" unless the reference is explicitly a user-provided intrinsic value estimate
- "buy signal"

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
| Sparse price coverage | Valuation reference section appears empty | Start with coverage summary and refresh workflow |
| Value Line coverage sparse | Quality overlay inconsistent | Sort/filter by coverage but do not hide missingness |
| Cost basis misinterpretation | Product trust risk | Strict copy rules and labels |
| Raw consensus creates false confidence | Users may follow crowded or low-conviction holdings | Default sort by signal-weighted consensus and show caution flags |
| Manager taxonomy incomplete | High-quality and noisy managers may be blended | Use derived signal proxies, unknown manager warnings, and manual metadata review |
| Valuation reference overread as intrinsic value | Users may infer a false margin of safety | Use conservative valuation reference language |
| Query performance | Dashboard slow | Aggregate service, indexes, pagination |

---

## 14. Milestone Plan

### Milestone 1: Data-Truth MVP

Deliver:

- Coverage audit service.
- Consensus service.
- Manager signal profile service.
- Holding duration / streak calculations.
- Dashboard API without frontend.
- Unit tests.

Estimated scope:

- Backend only.
- No schema change unless indexes are required.

### Milestone 2: Table-First Dashboard

Deliver:

- `/13f/oracles-lens` route.
- Ranked signal-weighted consensus table.
- Superinvestor-only toggle.
- Period selector for available complete periods.
- Fixed 13F delay notice.
- Caution flag column.
- Holder drilldown panel.

Estimated scope:

- Frontend + API integration.

### Milestone 3: Quality and Valuation Reference Overlay

Deliver:

- Owner earnings yield where available.
- Piotroski / ROTC / net margin / debt overlay.
- Selected valuation reference and discount-to-reference strip.
- Caution flags panel in drilldown.
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
3. `docs/tasks/YYYY-MM-DD_oracles-lens-manager-signal-profile.md`
4. `docs/tasks/YYYY-MM-DD_oracles-lens-caution-flags.md`
5. `docs/tasks/YYYY-MM-DD_oracles-lens-dashboard-api.md`
6. `docs/tasks/YYYY-MM-DD_oracles-lens-table-ui.md`
7. `docs/tasks/YYYY-MM-DD_oracles-lens-quality-overlay.md`
8. `docs/tasks/YYYY-MM-DD_oracles-lens-valuation-reference.md`

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
- The default ranking uses signal-weighted consensus, not raw holder count.
- The user can see manager signal quality, conviction, and holding streak.
- The user can see whether Value Line quality data is available.
- The user can see current price vs selected valuation reference where price exists.
- The user can see caution flags that explain why the signal may be misleading.
- Unsupported values are clearly labeled as unavailable or estimated.
- The dashboard never claims to know actual 13F transaction prices.

---

## 17. Product Decision Summary

The original "Oracle's Lens" concept is directionally strong, but V1 must be grounded in the data ValuePilot actually has.

Approved V1 framing:

```text
13F behavior signal + manager quality weighting + holding pattern + Value Line quality overlay + valuation reference + caution flags
```

Deferred:

```text
actual guru cost basis
AI moat score
full historical time-machine replay
real-time market behavior
```

This produces a credible premium research dashboard without overstating the precision of 13F data.
