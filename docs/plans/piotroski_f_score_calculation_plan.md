# Value Line-adjusted Piotroski F-Score Calculation Plan

## Status
Revised after detailed review. Still draft until implementation task approval.

## Goal
Add a Value Line-adjusted Piotroski F-Score as calculated yearly facts derived from parsed Value Line facts.

The implementation should:
- Calculate the 9 component indicators for each fiscal year.
- Use standard Piotroski definitions when all standard inputs are available.
- Use documented Value Line proxies when v0.1 facts do not expose the standard input.
- Store each component and the total score in `metric_facts`.
- Preserve fiscal year, period, estimate/actual semantics, variant, method, calculation version, and input lineage.
- Support future recalculation after manual corrections by reading active facts from `metric_facts`.

## Agreed Decisions
- Insert base parsed facts first.
- Generate reusable calculated ratio facts where possible.
- Then run an F-Score calculator that reads active facts from the database.
- Then write calculated F-Score facts back to `metric_facts`.
- Keep stable Piotroski component metric keys and record `variant` / `method` in `value_json` instead of splitting the metric key namespace into standard and adjusted variants.
- If the total score has missing components, write a diagnostic total fact with `value_numeric = null`.

## Non-Goals
- Do not change the raw parser contract unless required source fields are missing from `metric_facts`.
- Do not put this into the current generic `FormulaEngine`; it is not expressive enough for yearly multi-output comparisons.
- Do not create a new query source outside `metric_facts`.
- Do not implement TTM F-Score in v0.1. This plan is annual only.
- Do not implement F-Score trend scoring, Guru Score integration, buy/sell thresholds, or anomaly radar screens in this calculation task.
- Do not implement bank-specific scoring in v0.1.

## Score Variants
This service computes a Value Line-adjusted Piotroski F-Score.

Component and total facts must record:
- `value_json.variant = standard | valueline_proxy | insurance_adjusted`
- `value_json.method`, such as `standard_roa`, `fallback_net_income_positive`, `fallback_return_on_total_capital`, `fallback_cash_flow_per_share`, `fallback_absolute_long_term_debt`, or `insurance_premiums_to_assets`
- `value_json.calculation_version`, initially `piotroski_value_line_v1`
- `value_json.standard_metric`, such as `roa_positive` or `gross_margin_improving`
- `value_json.proxy_inputs`, when a non-standard Value Line proxy is used

Variant rules:
- `standard`: all inputs for that component use the standard Piotroski definition.
- `valueline_proxy`: at least one non-insurance Value Line proxy is used.
- `insurance_adjusted`: insurance-specific revenue or margin substitutes are used.
- When multiple inputs are available, the calculator must always choose the highest-priority method listed in this plan. It must not use lower-priority proxies when the standard input is available.

The total score's variant is:
- `standard` only when all 9 components are standard.
- `insurance_adjusted` when any component uses the insurance-adjusted method.
- `valueline_proxy` otherwise, when one or more components use non-standard Value Line proxies.

## Storage Model
Use existing `metric_facts`.

Common fields:
- `source_type = calculated`
- `period_type = FY`
- `fiscal_year = source fiscal year`, stored in `value_json.fiscal_year` until a first-class column exists
- `period_end_date` is derived from the company's fiscal year end when available, not hardcoded to December 31
- `value_json.fiscal_year_end = MM-DD`, when known from the Value Line report
- `value_json.period_end_date_basis = value_line_fiscal_year_end | calendar_year_default | unknown`
- `unit = score_point` for 0/1 component indicators
- `unit = score_total` for the total score
- `value_numeric = 0` or `1` for components
- `value_numeric = 0..9` for total, only when all 9 components are available
- `value_json.fact_nature = actual | estimate`
- `value_json.inputs` records source fact ids and values
- `value_json.missing_inputs` records unavailable inputs
- `value_json.status = calculated | partial | missing_input | unsupported_company_type`

Example for FICO:
- If Value Line says the fiscal year ends September 30, FY 2025 uses `period_end_date = 2025-09-30`.
- Do not store that fact as `2025-12-31`.

Recommended metric keys:

```text
score.piotroski.roa_positive
score.piotroski.cfo_positive
score.piotroski.roa_improving
score.piotroski.accrual_quality
score.piotroski.leverage_declining
score.piotroski.current_ratio_improving
score.piotroski.no_dilution
score.piotroski.gross_margin_improving
score.piotroski.asset_turnover_improving
score.piotroski.total
```

## Source Facts
Required or preferred inputs:

```text
is.net_income
is.operating_cash_flow
per_share.cash_flow
per_share.eps
cap.long_term_debt
bs.current_assets
bs.current_liabilities
liquidity.current_ratio
equity.shares_outstanding
is.gross_margin
is.operating_margin
is.sales
bs.total_assets
returns.total_capital
is.net_premiums_earned
is.pc_premiums_earned
ins.underwriting_margin
```

Notes:
- `returns.roa = is.net_income / bs.total_assets` is the preferred reusable calculated ROA fact.
- `returns.total_capital` maps Value Line `Return on Total Capital` and is only a proxy for ROA-based components.
- Canonical CFO should use `is.operating_cash_flow` if mapped later. Current Value Line v0.1 may only expose `per_share.cash_flow`, which is a proxy.
- `cap.long_term_debt` should map the yearly `Long-term Debt` row from Capital Structure.
- `leverage.long_term_debt_to_assets = cap.long_term_debt / bs.total_assets` is the preferred reusable calculated leverage fact.
- `bs.current_assets` and `bs.current_liabilities` should map totals from Current Position.
- `liquidity.current_ratio = bs.current_assets / bs.current_liabilities`.
- Prefer `is.gross_margin` for the Piotroski margin signal. If Value Line does not expose gross margin, `is.operating_margin` may be used as a documented Value Line proxy for non-financial operating companies.
- For insurers, use premiums earned as the revenue equivalent and underwriting margin as the margin equivalent only under `variant = insurance_adjusted`.

## Company Type Scope
Piotroski's original research excluded financial firms, so financial-company handling must not be silent.

For non-financial operating companies:
- Calculate `standard` components where all standard inputs are available.
- Calculate `valueline_proxy` components where documented Value Line proxies are needed.

For insurers:
- Allow `insurance_adjusted` components and totals.
- Record the exact revenue equivalent and margin metric used.
- Do not label these facts as `standard`.

For banks and other financial companies:
- Do not calculate numeric F-Score facts in v0.1.
- Either omit F-Score facts or write a diagnostic fact with `value_json.status = unsupported_company_type`.

Insurance revenue priority:
1. `is.net_premiums_earned`
2. `is.pc_premiums_earned`
3. `ins.premium_income`, if added later

Insurance adjusted ratio examples:
- `ins.premium_turnover = premiums_earned / bs.total_assets`
- `ins.underwriting_margin_improving = ins.underwriting_margin[Y] > ins.underwriting_margin[Y-1]`

## Standard vs Value Line Proxy Mapping

| Standard Piotroski item | Standard input | Value Line preferred input | Proxy status |
|---|---|---|---|
| ROA positive | `is.net_income / bs.total_assets > 0` | `Net Profit / Total Assets`; fallback `Return on Total Capital > 0`; fallback `Net Profit > 0` | Standard if both net income and total assets are available; otherwise proxy |
| CFO positive | Operating cash flow > 0 | Value Line `"Cash Flow"` per share > 0 | Proxy until true operating cash flow is available |
| ROA improving | ROA Y vs Y-1 | `Return on Total Capital` Y vs Y-1 | Proxy if total assets unavailable |
| Accrual quality | Operating cash flow > net income | `"Cash Flow"` per share > EPS | Proxy |
| Leverage declining | Long-term debt / total assets declines | `Long-Term Debt / Total Assets`; fallback absolute long-term debt decline | Standard if total assets available; otherwise proxy |
| Current ratio improving | Current assets / current liabilities improves | Current Position table | Standard if both inputs are available |
| No dilution | Shares outstanding did not increase | Common Shares Outstanding | Standard |
| Gross margin improving | Gross margin improves | Operating Margin; insurer Underwriting Margin | Proxy or insurance-adjusted |
| Asset turnover improving | Sales / total assets improves | Sales / Total Assets; insurer premiums earned / Total Assets | Standard for sales; insurance-adjusted for premiums |

## Indicator Rules
For fiscal year `Y`:

| Key | Rule | Required comparison |
|---|---|---|
| `roa_positive` | Primary: `returns.roa[Y] > 0`; fallback 1: `returns.total_capital[Y] > 0`; fallback 2: `is.net_income[Y] > 0` | Current year |
| `cfo_positive` | Primary: `is.operating_cash_flow[Y] > 0`; fallback: `per_share.cash_flow[Y] > 0` | Current year |
| `roa_improving` | Primary: `returns.roa[Y] > returns.roa[Y-1]`; fallback: `returns.total_capital[Y] > returns.total_capital[Y-1]` | Current vs previous year |
| `accrual_quality` | Primary: `is.operating_cash_flow[Y] > is.net_income[Y]`; fallback: `per_share.cash_flow[Y] > per_share.eps[Y]` | Current year |
| `leverage_declining` | Primary: `leverage.long_term_debt_to_assets[Y] < leverage.long_term_debt_to_assets[Y-1]`; fallback: `cap.long_term_debt[Y] < cap.long_term_debt[Y-1]` | Current vs previous year |
| `current_ratio_improving` | Primary: `liquidity.current_ratio[Y] > liquidity.current_ratio[Y-1]`; fallback: `bs.current_assets[Y] / bs.current_liabilities[Y] > bs.current_assets[Y-1] / bs.current_liabilities[Y-1]` | Current vs previous year |
| `no_dilution` | `equity.shares_outstanding[Y] <= equity.shares_outstanding[Y-1]` | Current vs previous year |
| `gross_margin_improving` | Primary: `is.gross_margin[Y] > is.gross_margin[Y-1]`; fallback: `is.operating_margin[Y] > is.operating_margin[Y-1]`; insurance-adjusted: `ins.underwriting_margin[Y] > ins.underwriting_margin[Y-1]` | Current vs previous year |
| `asset_turnover_improving` | Non-insurance: `revenue[Y] / bs.total_assets[Y] > revenue[Y-1] / bs.total_assets[Y-1]`; insurance-adjusted: `premiums_earned[Y] / bs.total_assets[Y] > premiums_earned[Y-1] / bs.total_assets[Y-1]` | Current vs previous year |

Total:
- Sum the 9 component values only when all 9 components are available.
- If one or more components are missing, write a diagnostic total fact with `value_numeric = null`, not a numeric total.
- Numeric screener filters such as `score.piotroski.total >= 7` must only match facts where `value_json.status = calculated` and `value_numeric is not null`.

Partial total diagnostic example:

```json
{
  "status": "partial",
  "variant": "valueline_proxy",
  "calculation_version": "piotroski_value_line_v1",
  "fiscal_year": 2025,
  "partial_score": 6,
  "available_indicators": 8,
  "max_available_score": 8,
  "missing_indicators": ["score.piotroski.current_ratio_improving"]
}
```

## Estimate Semantics
Each component should be marked `estimate` if any input fact used by that component has `value_json.fact_nature = estimate`.

Otherwise it is `actual`.

For example:
- If 2025 EPS is estimate, `accrual_quality` for 2025 is estimate.
- If a comparison uses 2025 estimate and 2024 actual, the component is estimate.
- If all inputs are actual, the component is actual.

The total score is estimate if any included component is estimate.

For partial diagnostic total facts, `fact_nature` should also be `estimate` if any available component or missing-dependent component uses estimate inputs; otherwise it should be `actual`.

## Lineage
Each calculated fact should include enough input lineage for audit/debug:

```json
{
  "status": "calculated",
  "variant": "valueline_proxy",
  "method": "fallback_cash_flow_per_share",
  "calculation_version": "piotroski_value_line_v1",
  "standard_metric": "accrual_quality",
  "fact_nature": "estimate",
  "formula": "per_share.cash_flow[Y] > per_share.eps[Y]",
  "fiscal_year": 2025,
  "fiscal_year_end": "09-30",
  "period_end_date_basis": "value_line_fiscal_year_end",
  "inputs": [
    {
      "metric_key": "per_share.cash_flow",
      "period_end_date": "2025-09-30",
      "fact_id": 123,
      "value_numeric": 5.2,
      "fact_nature": "estimate"
    }
  ]
}
```

Insurance-adjusted total example:

```json
{
  "status": "calculated",
  "variant": "insurance_adjusted",
  "calculation_version": "piotroski_value_line_v1",
  "revenue_equivalent_metric": "is.net_premiums_earned",
  "margin_metric": "ins.underwriting_margin"
}
```

Missing component example:

```json
{
  "status": "missing_input",
  "fiscal_year": 2025,
  "missing_inputs": ["bs.current_assets", "bs.current_liabilities"],
  "formula": "liquidity.current_ratio[Y] > liquidity.current_ratio[Y-1]"
}
```

## Calculation Flow
Recommended services:

```text
backend/app/services/calculated_metrics/value_line_ratios.py
backend/app/services/calculated_metrics/piotroski_f_score.py
```

`value_line_ratios.py` responsibilities:
1. Load active source facts for a user and stock.
2. Derive reusable calculated ratios when inputs are available.
3. Write ratio facts such as `returns.roa`, `liquidity.current_ratio`, `leverage.long_term_debt_to_assets`, `efficiency.asset_turnover`, `margin.gross_margin`, `margin.operating_margin`, `ins.premium_turnover`, and `ins.underwriting_margin`.
4. Preserve fiscal year, period end date, estimate semantics, and lineage.

`piotroski_f_score.py` responsibilities:
1. Load active facts for a user and stock, including reusable ratio facts.
2. Determine company type eligibility and variant.
3. Group facts by `metric_key` and fiscal year.
4. Compute the 9 component facts per fiscal year.
5. Compute a numeric total only when all components are available.
6. Write a partial diagnostic total when components are missing.
7. Insert/update calculated facts.
8. Reconcile `is_current` for calculated facts by stock, key, and period.

Ingestion flow:

```text
parse Value Line document
build page_json
generate parsed metric facts from mapping spec
insert parsed facts
run ValueLineRatioCalculator for the stock
run PiotroskiFScoreCalculator for the stock
insert calculated F-Score facts
```

Future manual-correction flow:

```text
insert manual correction fact
mark previous current fact false
run ValueLineRatioCalculator for the affected stock
run PiotroskiFScoreCalculator for the affected stock
insert new calculated ratio and F-Score facts
```

## Implementation Phases
1. Mapping coverage
   - Add missing mappings for yearly Total Assets, Long-term Debt, Current Assets, Current Liabilities, Gross Margin where available, and any operating cash flow field that can be mapped reliably.
   - Add insurance mappings for `is.pc_premiums_earned` and `ins.underwriting_margin` where the Value Line insurance layout exposes them.
   - Keep `Return on Total Capital`, `Cash Flow per share`, and `Operating Margin` as explicitly marked proxy inputs when canonical inputs are unavailable.
   - Add tests in `test_metric_facts_mapping_spec.py`.

2. Reusable ratio service
   - Add pure calculation functions with unit tests.
   - Add DB integration tests for calculated ratio facts and lineage.

3. F-Score calculator service
   - Add pure calculation functions with unit tests for `standard`, `valueline_proxy`, `insurance_adjusted`, `partial`, and `unsupported_company_type`.
   - Add DB integration tests for inserting calculated `metric_facts`.

4. Ingestion integration
   - Trigger ratio and F-Score calculation after parsed facts are inserted.
   - Verify uploaded Value Line fixtures create the expected variant and component facts.

5. Recalculation hook
   - Trigger after manual fact correction.
   - Keep calculated facts current without mutating parsed facts.

6. UI / screener exposure
   - Expose `score.piotroski.total` and components through existing metric facts APIs.
   - Display score variant in UI, for example `Value Line adjusted` or `Value Line adjusted, insurance`.
   - Numeric screeners must use `value_numeric` and only calculated complete totals.
   - Add review/watchlist display only after backend facts are stable.

## Open Review Questions
1. Confirm whether `score_point` and `score_total` should be added as accepted unit values, or whether existing unit validation requires another naming convention.
2. Confirm where company fiscal year end should live long term: `stocks`, `pdf_documents`, a dedicated fiscal calendar table, or only `value_json` for v0.1.
3. Confirm whether `is.gross_margin` is reliably available from current Value Line fixtures or should remain future mapping coverage.
4. Confirm the exact company-type classifier for insurers versus banks before enabling `insurance_adjusted`.

## Review Decisions
Accepted:
- Rename the plan to Value Line-adjusted Piotroski F-Score.
- Treat standard Piotroski definitions as the baseline and Value Line shortcuts as documented proxies.
- Derive `period_end_date` from the source fiscal year end instead of hardcoding December 31.
- Use `score_point` and `score_total` semantics instead of `ratio` / `count` for score facts.
- Rename component keys to the standard concepts: `roa_positive`, `roa_improving`, and `gross_margin_improving`.
- Use leverage ratio as the primary leverage signal and absolute debt decline only as a fallback.
- Write partial diagnostic total facts with `value_numeric = null`.
- Split reusable ratio calculation from F-Score calculation.
- Allow `insurance_adjusted` F-Score for insurers, with explicit variant and method metadata.

Rejected or deferred:
- Do not split metric keys into `score.piotroski.standard.*` and `score.piotroski.valueline_adjusted.*`; use stable keys plus `value_json.variant`.
- TTM F-Score is useful but out of scope for this annual Value Line v0.1 implementation.
- F-Score trend, Guru Score blending, high/low score thresholds, and anomaly radar screens belong in future screening or portfolio layers, not this calculation service.
- Bank-specific scoring remains out of scope for v0.1.
