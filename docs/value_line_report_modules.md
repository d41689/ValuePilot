

# Value Line Report Module Specification (v0.1)

This document defines the **canonical module structure** for a Value Line Equity Report (single-company page) and the **recognition signals** used by ValuePilot parsers.

Goals:
- Provide a stable, parser-friendly decomposition of a Value Line report into modules.
- Define **module identifiers**, **keywords/anchors**, and **expected outputs**.
- Prepare for JSON output organized by module, with explicit **time dimensions** for time-series data.

Non-goals (v0.1):
- “Generic PDF parsing” across all publishers.
- Perfect OCR for scanned PDFs (fallback only).
- Full support for every industry-specific table variant (we document variants and handle incrementally).

---

## 0. Global parsing assumptions

- A Value Line “company page” is typically 1 page per company; multi-page PDFs may include industry summary pages.
- Recognition is primarily **text-layer** based. OCR is used only when text-layer extraction is insufficient.
- The parser should classify each page as one of:
  - `company_page`
  - `industry_summary_page`
  - `unknown`

### Exchange/ticker identity patterns (common)
- Often appears near the company name as: `NYSE-XXX`, `NDQ-XXX`, `NAS-XXX`, `NSDQ-XXX`, `TSX-XXX.TO`, `TSE-XXX.TO`, `PNK-XXXXY`, etc.
- Normalize:
  - `NSDQ` → `NDQ`
  - `TSE`/`TSX` → `TSX` (canonical)
  - allow dot-suffix tickers (e.g., `.TO`)

---

## 1. Module Index (canonical)

Modules are grouped into:
- **A. Header & Ratings (Snapshot)**
- **B. Targets & Projections (Range/Projection)**
- **C. Ownership & Positioning (Snapshot)**
- **D. Financial Tables (Time-series)**
- **E. Performance & Price History (Time-series / Range)**
- **F. Narrative (Text)**

Each module below includes:
- **Module ID**
- **What it contains**
- **Recognition anchors (keywords)**
- **Expected structured outputs**
- **Time dimension rules** (if applicable)

---

## A. Header & Ratings (Snapshot)

### A1. Header / Quote Block
**Contains**
- Company name
- Ticker + exchange
- Recent price (and date, if present)
- P/E ratio
- Relative P/E ratio
- Dividend yield

**Recognition anchors**
- `RECENT PRICE`
- `P/E RATIO`
- `RELATIVE P/E RATIO`
- `DIV'D YLD`
- exchange token patterns like `NYSE-`, `NDQ-`, `NAS-`, `TSX-`, `TSE-`, `PNK-`

**Outputs**
- `company_name`
- `ticker`
- `exchange`
- `recent_price_usd`
- `pe_ratio`
- `relative_pe_ratio`
- `dividend_yield_pct`

**Time**
- Snapshot values: `period_type = snapshot`, `as_of_date = report_date` (if known) else `NULL`.

---

### A2. Ranking / Ratings Block
**Contains**
- Timeliness
- Safety
- Technical
- Beta

**Recognition anchors**
- `TIMELINESS`
- `SAFETY`
- `TECHNICAL`
- `BETA`

**Outputs**
- `timeliness`
- `safety`
- `technical`
- `beta`

**Time**
- Snapshot: `period_type = snapshot`

---

### A3. Company’s Financial Strength & Predictability (small box)
**Contains**
- Company’s Financial Strength (letter grade, e.g., `B++`)
- Stock’s Price Stability (0–100)
- Price Growth Persistence (0–100)
- Earnings Predictability (0–100)

**Recognition anchors**
- `Company's Financial Strength`
- `Stock's Price Stability`
- `Price Growth Persistence`
- `Earnings Predictability`

**Outputs**
- `company_financial_strength`
- `stock_price_stability`
- `price_growth_persistence`
- `earnings_predictability`

**Time**
- Snapshot: `period_type = snapshot`

---

## B. Targets & Projections (Range/Projection)

### B1. 18-Month Target Price Range
**Contains**
- Low / High range
- Midpoint
- % to midpoint (often implied by “to midpoint”)

**Recognition anchors**
- `18-Month Target Price Range`
- `Low` and `High` near the anchor
- `Midpoint`

**Outputs**
- `target_18m_low`
- `target_18m_high`
- `target_18m_midpoint`
- (optional) `target_18m_upside_pct`

**Time**
- Projection range: `period_type = target_range`, `horizon_months = 18`, `as_of_date = report_date`.

---

### B2. Long-Term Projections (rolling year range)
**Contains**
- A rolling range like `2028-2030` (varies by report date)
- High/Low projected price and total return/gain

**Recognition anchors**
- a year-range token like `28-30`, `2028-2030`, `2029-2031` (rolling)
- `PROJECTIONS` (sometimes)
- `Annual Total Return` / `Price Gain`

**Outputs**
- `projection_year_range` (string like `2028-2030`)
- `projection_high_price`
- `projection_low_price`
- `projection_price_gain_pct` (if present)
- `projection_annual_total_return_pct` (if present)

**Time**
- Projection range: `period_type = projection_range`
- Store `projection_year_range` as a string; do **not** hardcode years into metric keys.

---

## C. Ownership & Positioning (Snapshot)

### C1. Institutional Decisions
**Contains**
- Buy/Sell/Hold actions (e.g., “to Buy”, “to Sell”)
- Institutional holdings counts

**Recognition anchors**
- `Institutional Decisions`
- `to Buy`
- `to Sell`
- `Holdings` or `Held`

**Outputs**
- `institutional_to_buy`
- `institutional_to_sell`
- (optional) `institutional_holding_shares_k` or `institutional_holding_value`

**Time**
- Snapshot: `period_type = snapshot`

---

## D. Financial Tables (Time-series)

> **Time-series rule (v0.1):**
> - Every extracted numeric cell from a time-series table MUST carry:
>   - `period_type` ∈ {`FY`, `Q`, `TTM`, `projection`}
>   - `period_end_date` (preferred) or a canonical `year`/`quarter` that can be converted to an end date.
> - Use `NULL` when the report uses `--`, `NMF`, `Nil` for a cell.

### D1. Capital Structure
**Contains**
- Total Debt / LT Debt
- Preferred
- Shares outstanding (sometimes appears elsewhere too)

**Recognition anchors**
- `CAPITAL STRUCTURE`
- `Total Debt`
- `LT Debt` or `Long-Term Debt`

**Outputs**
- `total_debt_usd_millions` (if reported in $mill)
- `long_term_debt_usd_millions`
- `preferred_stock_usd_millions` (if present)
- `common_shares_outstanding_millions` (if present)

**Time**
- Usually snapshot or recent-year; store as snapshot unless explicitly time-stamped.

---

### D2. Financial Position
**Contains**
- Balance-sheet-like items, often in $mill
- Bonds / Stocks / Total Assets, etc.

**Recognition anchors**
- `FINANCIAL POSITION`
- `Bonds`
- `Stocks`
- `Total Assets`
- (insurance variant may include `Reserves` etc.)

**Outputs**
- Extract each row as a metric with time dimension if multiple years/quarters exist.

**Time**
- If table spans periods, treat as time-series with `period_type` + `period_end_date`.

---

### D3. Annual Rates of Change
**Contains**
- Multi-year growth rates for items like premiums, investment income, etc.

**Recognition anchors**
- `Annual Rates of Change`
- `Rates of Change`

**Outputs**
- Extract each labeled line as:
  - `annual_rate_of_change_<metric_key>_<window>` (window e.g., `past_10y`, `past_5y`, `estd_next_5y`)
- Prefer storing a structured JSON value that includes the window label.

**Time**
- This is not per-year data; store as `period_type = windowed_rate` with `window_label`.

---

### D4. Insurance Revenue (industry table, annual + quarterly)
**Contains**
- Insurance-specific revenue breakdown:
  - P/C premiums earned, loss ratio, expense ratio, underwriting margin, etc.
- Often includes annual rows plus a smaller quarterly section.

**Recognition anchors**
- `P/C Premiums Earned`
- `Loss to Prem Earned`
- `Expense to Prem Writ`
- `Underwriting Margin`
- (and/or a header like `INSURANCE REVENUE`)

**Outputs**
- For each row and each year/quarter cell:
  - `field_key` is the row metric (canonicalized)
  - `parsed_value_json` includes units and whether it is percent

**Time**
- Annual cells → `period_type=FY`, `period_end_date=YYYY-12-31` (anchor)
- Quarterly cells → `period_type=Q`, `period_end_date` is quarter end.

---

### D5. Earnings Per Share (annual + quarterly)
**Contains**
- EPS annual series
- EPS quarterly series

**Recognition anchors**
- `Earnings per sh` or `Earnings per share`
- `Quarterly Earnings` (if present)

**Outputs**
- `earnings_per_share_usd` (annual)
- `quarterly_earnings_per_share_usd` (quarterly)

**Time**
- Annual: `FY` + year end
- Quarterly: `Q` + quarter end

---

### D6. Quarterly Dividends Paid
**Contains**
- Dividends paid per quarter (and sometimes annual dividends)

**Recognition anchors**
- `Quarterly Dividends Paid`
- `Dividends Paid`

**Outputs**
- `dividends_paid_per_share_usd` (quarterly)
- (optional) annual dividends per share

**Time**
- Quarterly: `Q` + quarter end

---

### D7. Annual Financials & Ratios (core table)
**Contains**
- Per-share: Sales per share, Cash Flow per share, Earnings per share, Dividends, Cap’l Spending per sh, Book Value per sh, Shares out
- Valuation: Avg P/E, Relative P/E, Avg Dividend Yield
- Financials ($mill): Sales, Op Margin, Depreciation, Net Profit, Tax Rate, Net Profit Margin, Working Cap’l, LT Debt, Shr. Equity
- Returns: Return on Total Capital, Return on Shr. Equity, Retained to Com Eq, All Div’s to Net Prof
- Plus long-term projection year-range values

**Recognition anchors**
- Year header row like `2015 2016 ... 2026` (varies)
- Row labels such as:
  - `Sales per sh`
  - `Cash Flow per sh`
  - `Earnings per sh`
  - `Div'ds Decl'd per sh`
  - `Cap'l Spending per sh`
  - `Book Value per sh`
  - `Common Shs Outst'g`
  - `Avg Ann'l P/E Ratio`
  - `Avg Ann'l Div'd Yield`
  - `Sales ($mill)`
  - `Depreciation ($mill)`
  - `Net Profit ($mill)`
  - `Long-Term Debt ($mill)`
  - `Shr. Equity ($mill)`
  - `Return on Shr. Equity`

**Outputs**
- Time-series rows: create one extraction/fact per year cell with period dimensions.
- Projection range values: store in a dedicated `projection_yyyy_yyyy` block at the module level.

**Time**
- Annual series: `FY` + year end
- Projection range: `projection_range` + `projection_year_range`

---

## E. Performance & Price History

### E1. Total Return
**Contains**
- Stock total return vs. market / category over 1, 3, 5 years (and sometimes longer)

**Recognition anchors**
- `TOT. RETURN`
- `1 yr.` / `3 yr.` / `5 yr.`

**Outputs**
- `total_return_1y_pct`
- `total_return_3y_pct`
- `total_return_5y_pct`
- (optional) benchmark returns

**Time**
- Windowed return: `period_type = trailing_window` + `window_years`

---

### E2. Historical Price Range (10–12 years)
**Contains**
- A band or table with year-by-year high/low prices

**Recognition anchors**
- `High` / `Low` with a multi-year list
- sometimes `Price Range` or `Relative Price Strength`

**Outputs**
- `historical_high_low_by_year`: list of `{year, high, low}`

**Time**
- Annual by year (year anchored)

---

## F. Narrative (Text)

### F1. Business Description
**Contains**
- Company business overview paragraph(s)

**Recognition anchors**
- `BUSINESS` (all caps)
- sometimes starts near bottom-left

**Outputs**
- `business_description` (raw text)

---

### F2. Analyst Commentary
**Contains**
- Analyst narrative text
- Analyst name
- Report date

**Recognition anchors**
- Analyst signature line (e.g., `CFA`)
- date line like `January 9, 2026`

**Outputs**
- `commentary` (raw text)
- `analyst_name`
- `report_date`

---

### F3. Footer / Notes
**Contains**
- Footnotes (A/B/C markers), disclaimers, units notes

**Recognition anchors**
- `© VALUE LINE PUB. LLC`
- footnote markers like `A`, `B`, `C` near row labels

**Outputs**
- `footnotes` (raw text)
- `copyright_notice`

---

## 2. Canonical JSON organization (module-oriented)

For parser outputs, JSON should be organized by module, e.g.:

- `header.quote_block`
- `ratings`
- `targets.target_18m`
- `projections.long_term`
- `ownership.institutional_decisions`
- `financials.annual_financials_and_ratios`
- `financials.insurance_revenue`
- `performance.total_return`
- `performance.historical_price_range`
- `narrative.business`
- `narrative.commentary`

### Time dimension payload (recommended)
For each time-series cell, include:
- `period_type`: `FY` | `Q` | `TTM` | `projection_range` | `trailing_window`
- `period_end_date`: ISO date (preferred)
- and one of:
  - `year` (for FY)
  - `quarter` (e.g., `2025Q3`)
  - `projection_year_range` (for 28–30)

---

## 3. Known industry variants (examples)

- Insurance pages: include `P/C Premiums Earned` tables and ratios like combined ratio components.
- Banks: include net interest margin, loan loss provisions, capital ratios.
- Utilities: include regulated rate base, allowed ROE, capacity metrics.
- REITs: include FFO/AFFO per share, occupancy, NAV.

We extend support by:
- adding a new module variant section
- adding new canonical metric mappings
- adding fixtures for each variant

---