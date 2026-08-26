# Quant Trading 1-R0A Data-Sufficiency Audit

- Evaluated at: `2026-07-21T12:00:00+00:00`
- Policy: `quant-1-r0a-v1`
- Environment: `development` (read-only)
- User scope: `775`
- Overall gate: **NO_GO**

## Decision

No hypothesis research or holdout evaluation is authorized. 1-R1 through 1-R4 remain closed because H1 data sufficiency is NO_GO.

## Pre-registered power contract

One-sided threshold `t_HAC >= 3.0`, net alpha `2.0%/yr`, target power `80%`, final holdout `30%`. Breadth is a separate eligibility floor, not a substitute for return-history time.

| Hypothesis | Frequency | Selected TE | Holdout periods | Total years required | Status |
| --- | --- | ---: | ---: | ---: | --- |
| H1 | monthly | 4.0% | 709 | 197.0 | **NO_GO** |
| H2 | monthly | 4.0% | 709 | 197.0 | **NO_GO** |
| H3 | quarterly | 6.0% | 532 | 443.5 | **NO_GO** |

This is a normal/HAC planning approximation. Final power must be re-estimated from the acquired return series and its realized autocorrelation before any holdout is unlocked.

## Observed database coverage

### User-scoped Value Line facts

- Parsed Value Line documents: **3**
- Parsed fact rows / stocks / metric keys: **768 / 3 / 70**
- Strict publication range: **2025-12-19 → 2026-01-30** (0.115 years; 2 observed months)
- Weekly archive: **2** observed weeks; longest consecutive run **1**
- Embedded period range: **2011-03-31 → 2026-12-31**. This is restated/estimated depth, not independent publication-vintage depth.

### Local prices (non-qualifying inventory)

- Rows / stocks / range: **2 / 1 / 2026-07-10 → 2026-07-17**
- Sources: `{'fallback': 2}`
- These rows do not prove survivorship-free historical membership, delisted-name coverage, or licensed production use.

### SEC 13F authoritative history

- Active/current-successful filings / holdings: **1150 / 82913**
- Versioned successful filings / manager-quarters with amendments: **1204 / 49**
- Quarters / mapped stocks / mapped holding ratio: **18 / 2841 / 91.4%**
- Mature / still-open quarters at the audit date: **17 / 1**; breadth floors use mature quarters only.
- Quarter-end range: **2022-03-31 → 2026-06-30**
- Actually observable (`filed_at`) range: **2023-01-05 → 2026-07-16** (3.526 years)
- Filing lag days min / median / max: **2 / 45.000 / 518**
- Today's active filing is not a historical PIT selector. Later amendments must never be back-projected into dates before they were filed.

## Fail-closed gate reasons

- **H1 NO_GO**: `backbone_authorization_missing, backbone_not_survivorship_free, backbone_missing_delisted_names, backbone_missing_fundamentals, backbone_missing_prices, insufficient_backbone_history, insufficient_backbone_cross_sectional_breadth`
- **H2 NO_GO**: `value_line_automation_authorization_missing, value_line_four_week_continuity_not_proven, insufficient_value_line_publication_history, insufficient_value_line_cross_sectional_breadth`
- **H3 NO_GO**: `backbone_authorization_missing, backbone_not_survivorship_free, backbone_missing_delisted_names, backbone_missing_fundamentals, backbone_missing_prices, insufficient_13f_availability_history, insufficient_13f_manager_breadth, insufficient_13f_mapped_stock_breadth`

## Source and licensing state

- Value Line automated acquisition remains blocked by `coverage-source-policy.md`; only explicit user uploads are authorized today.
- A survivorship-free fundamentals + prices backbone with delisted names has no recorded authorization evidence in this audit.
- SEC 13F data is public, but holdings are delayed; every research timestamp must use `filed_at`, never quarter end.

## Reliable references

- https://www.nber.org/papers/t0055
- https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.solve_power.html
- https://www.sec.gov/files/form13f.pdf
- https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets
- docs/architecture/coverage-source-policy.md
