# Adversarial Review — Quant Trading 1-R0A Data Sufficiency Audit

**Review date:** 2026-07-21
**Scope:** `T-2026-07-21-quant-trading-1-r0a`
**Verdict:** **APPROVE the audit implementation; REJECT opening 1-R1…1-R4**

## Review standard

Try to turn an invalid dataset into a false `GO`, introduce look-ahead or
survivorship leakage, combine user-owned proprietary data across users, mistake
13F quarter end for public availability, run against production, or present a
planning approximation as guaranteed statistical power.

## Findings and disposition

| ID | Severity | Attack / finding | Resolution |
| --- | --- | --- | --- |
| R0A-01 | Critical | The old roadmap solved only for expected `t=3`, which gives roughly 50% probability of clearing that threshold under the alternative; it did not pre-register target power. | Fixed. Policy v1 uses 80% target power and adds `Phi^-1(0.8)` to the required noncentrality. Tests prove the requirement is stricter than the 50%-power shortcut. |
| R0A-02 | Critical | The old `T × breadth` wording makes time and stocks look fungible. Correlated cross-sectional names cannot replace HAC time observations for the spanning-regression alpha. | Fixed. Time and operational breadth are separate gates; output explicitly says breadth is not statistically fungible with time. |
| R0A-03 | Critical | Aggregating all `metric_facts` would combine user-owned proprietary Value Line reports and inflate coverage. | Fixed. The audit requires a positive `user_id`, filters both facts and documents to that owner, and only emits aggregates. A cross-user trap test passes. |
| R0A-04 | Critical | Treating a 13F quarter end as signal availability creates up-to-45-day look-ahead. | Fixed. Coverage and lag reporting use `filed_at`; SEC instructions are linked. Negative lags are quality errors. |
| R0A-05 | High | Today's `is_active_for_manager_period` filing is safe for a current product snapshot but not for historical research: a later amendment could be back-projected into earlier dates. | Fixed in the audit/contract. The report separately inventories 1,204 versioned successful filings and 49 manager-quarters with multiple versions, and warns that H3 PIT reads must select the version observable at T. 1-R1 scope is amended accordingly. |
| R0A-06 | High | The partially filed 2026-Q2 cross-section could depress the minimum breadth before its filing deadline and create a false data-quality failure. | Fixed. The audit labels mature vs still-open quarters from `official_filing_deadline`; breadth floors use mature quarters only. At 2026-07-21 the result is 17 mature and 1 open quarter. |
| R0A-07 | High | Merely printing “development/read-only” does not prevent a mistaken production read or accidental mutation. | Fixed. The operational CLI accepts only database `valuepilot` (rejects `valuepilot_prod`) and starts a PostgreSQL read-only transaction before queries. |
| R0A-08 | High | Three parsed PDFs contain fiscal periods back to 2011; naïve code could call that 15 years of PIT history. | Fixed. Publication-vintage depth is reported separately as only 2025-12-19 to 2026-01-30 (0.115 years); embedded/restated periods are explicitly ineligible for absolute-return gates. |
| R0A-09 | Medium | In-memory source readiness could be asserted by a future trusted caller with a weak evidence string. | Current CLI has no readiness override and therefore cannot launder authorization. A durable operator authorization/source-contract registry remains 1-R0B scope before any external backbone can produce `GO`. |
| R0A-10 | Critical / product | Proper 80%-power math makes the accepted contract infeasible with the currently proposed data path: H1 needs 709 holdout months and about 197 total years at a 30% holdout; H3 needs 532 holdout quarters and about 443.5 total years. | Recorded as an explicit `NO_GO`, not tuned away. The next authorized work must be a statistical-design/data-procurement decision, not 1-R1 implementation. The 30% split is a conservative PO governance assumption, not a universal theorem, and may only change in a new pre-registered policy version before any holdout is opened. |
| R0A-11 | Medium | The resource roadmap called the Value Line archive “weekly/growing” and H3 “testable now,” neither of which matches the database. | Corrected to the measured state: 3 documents, 2 non-consecutive weeks, 18 quarter labels but only 3.526 years of actual filing availability; both hypotheses are underpowered under policy v1. |

## Evidence-backed checks

- Newey–West defines HAC covariance for autocorrelated/heteroskedastic time
  series; the audit therefore refuses to multiply raw stock count into time:
  https://www.nber.org/papers/t0055
- Statsmodels defines power as `1 - type-II error` and solves for sample size
  given effect, significance and desired power:
  https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.solve_power.html
- SEC Form 13F is due up to 45 days after quarter end, so `filed_at` is the
  earliest admissible signal timestamp:
  https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f
- SEC's official structured 13F datasets begin in May 2013 and are as-filed,
  with amendments/redundancies possible:
  https://www.sec.gov/files/form_13f.pdf
- CRSP documents US stock history from 1925 and explicit delisting returns:
  https://www.crsp.org/crsp_pdf/crsp-us-stock-indexes-databases-data-descriptions-guide-crspaccess/
- WRDS lists S&P Compustat Point in Time coverage from 1980-02-29. That is much
  deeper than the local corpus but still below policy v1's 197-year H1 total
  requirement under a 30% final holdout:
  https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/sp-global-market-intelligence/

## Residual risks / next decision

1. **Do not buy a dataset yet.** First choose a statistically coherent policy
   that can be satisfied by an independently verified source: retain the exact
   2%/`t>=3`/80% hurdle and redesign the genuinely OOS allocation, raise the
   minimum detectable alpha, or explicitly accept lower power. This must be a
   new version before data inspection, never a post-result relaxation.
2. If a source is selected, 1-R0B must persist license/terms evidence, exact
   PIT fields, delisted-name handling, date range, and monthly breadth; a sales
   page or API key alone cannot mark it ready.
3. H3 needs an as-of filing/amendment reader in 1-R1. The current product-facing
   active filing query must not be reused for historical research.
4. P1-B remains empirically unpassed: only two non-consecutive Value Line weeks
   exist and automated acquisition is unauthorized.
