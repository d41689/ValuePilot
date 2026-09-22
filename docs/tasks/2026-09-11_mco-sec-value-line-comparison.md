# MCO SEC / Value Line independent comparison

> Historical record preserved during 2026-09-22 consolidation. Its status describes that checkpoint, not the current PR. See [final acceptance](../reports/2026-09-12_mco-plan-a-stable-acceptance.md) and [delivery record](../tasks/2026-09-12_mco-plan-a-delivery.md) for subsequent fixes and limitations.

## Goal and authorization

User requested acquisition with the project's existing SEC code, parsing, comparison against `/Users/dane/Downloads/mco-0206.pdf`, and recommendations. This is an analysis/data experiment, not authorization to fix the parser, change mappings, publish to shared development, commit, push, or deploy.

## Acceptance

- Verify Moody's MCO/NYSE identity from SEC submissions before ingestion.
- Use existing EdgarClient / verified Rate Guard, ingestion parser, database normalizations and approved canonical publication unchanged.
- Keep downloads and all database writes isolated from development, retained acceptance environments and production.
- Compare source dates and definitions before values; report unavailable, rejected, adjusted and forecast cells honestly.
- Preserve accession, fact/publication identity, exact values and relevant source evidence in the analysis artifacts.
- Distinguish parser/extraction correctness, canonical coverage, normalization differences, and Value Line analyst adjustments; no unsupported claims of error or complete accuracy.

## Scope and limits

- Value Line edition dated 2026-02-13; annual FY2025 and later are forecasts in this report. SEC filing selection cutoff is 2026-02-13T00:00:00Z, not the current evidence-knowledge timestamp.
- Existing historical selector supports at most ten completed FYs. Initial target FY2016–FY2025; expected FY2025 annual absence at report cutoff remains explicit. At most ten selected filings: available annual reports take precedence, then latest quarterly supplement. Earlier FY2010–FY2015 in the PDF are outside this initial ten-year acquisition; no silent complete-history claim.
- New database `valuepilot_mco_compare_20260911` on existing shared PostgreSQL, existing application role. No shared PostgreSQL restart, no migrations or data writes to existing databases.
- New storage `storage/mco_sec_comparison/2026-09-11/`; do not overwrite previous evidence. Cumulative database-plus-retained-file budget 2 GiB from one captured empty/migrated baseline, with stop reserve. No full-universe acquisition, 13F jobs, worker activation or SEC transport fallback around a rejection.
- Runtime override is confined to a one-off process/container. Shared API stays in replay mode.
- Value Line PDF is read-only and locally analyzed, not imported as user-owned product facts or redistributed.

## Contract references

AGENTS.md; docs/architecture/{parsing,data-layer,metric-facts-is-current,coverage-source-policy}.md; PRD H.2–H.9; docs/metric_facts_mapping_spec.yml. Product financial truth is only metric_facts. Raw inspection is diagnostic evidence, never substituted for missing canonical values.

## Files / resources

- This task and a final comparison report.
- One-off orchestration/analysis files in the new experiment directory; call existing code, do not modify product code.
- Isolated database and retained SEC files stay available for audit; no cleanup of existing resources.

## Verification plan

Run Python only in Docker. Record HEAD/parser/mapping, live database identity, baseline counts and resource usage, pinned Rate Guard identity, actual acquisition/failure results, canonical publication outcomes, precision-aware comparison, original-statement spot checks and shared-database before/after counts. An independent read-only agent checks metric semantics. This is not a code release: do not run write-bearing closing gates against shared databases or claim full CI was rerun.

## Execution record

- Before acquisition, shared development: database `valuepilot`, MCO stock 45 with legacy exchange `US` and no canonical listing, metric_facts 2390, SEC parse runs 84. That legacy value is not MCO listing authority and will not be changed.
- A one-off live EdgarClient verified the configured primary Rate Guard instance `34dc3fda-80e2-4260-9f29-848eedabde63`; shared API configuration is unchanged. SEC identity verified as CIK 0001059556, MOODYS CORP /DE/, MCO, NYSE, fiscal year end 1231.
- Code HEAD `1065f692a3b1453fa221c1da42cedbc4ab85a9fb`; parser `xbrl-lineage-v2.9`, existing migration head `20260909150000`, approved mapping `sec-us-gaap-v1`. No product code or mapping changes.
- Initialized only the new isolated database. Existing acquisition selected nine FY2016–2024 annual filings plus 2025Q3: nine annual parse failures (seven invalid_label_arc; two unproven_prior_fiscal_cycle_anchor), one quarterly success. FY2025 absence at the historical cutoff is separately retained as a coverage gap.
- Existing publication created 23 canonical facts (Q 16 / YTD 7 / FY 0) from 24 normalizations. Exact publication replay returned the same run, with facts remaining 23. No second network ingestion replay was performed.
- Read-only diagnostics of SHA-verified retained files yielded 28,974 raw candidates, explicitly not canonical. Seven directly comparable canonical cells matched the PDF; annual revenue and equity candidates each matched nine displayed years, but annual product availability remains zero.
- Confirmed FY2024 empty non-rendered documentation label rejection and VL revenues mapping omission. FY2016/2017 anchor root cause, FY2022 EPS adjustment residual and remaining accounting-definition differences are not silently resolved. Findings/deferred work recorded in BACKLOG; no fixes authorized or made.
- Final shared-development counts remained metric_facts 2390 / SEC parse runs 84; stock 45 identity fields unchanged. Final measured cumulative experiment increment was 348,178,013 bytes (about 332 MiB), including diagnostic output, below the fixed 2 GiB budget. Experiment evidence and database retained.
- Two independent read-only agents checked semantics/label and mapping behavior, and all 23 exported facts / seven comparisons / 123 original annual XML occurrences, respectively. PDF values were visually checked by root, not independently by the verifier. Full CI and browser product acceptance were not run for this analysis-only task.
- Outcome: analysis delivered; MCO annual ingestion is not product-ready. Detailed results, exact command forms, failures and limitations: [comparison report](../reports/2026-09-11_mco-sec-value-line-comparison.md).
