# 13F × Dataroma 82-manager reconciliation

## Outcome

- Audited all 82 ValuePilot managers across Holdings, Activity, Buys, Sells,
  and History.
- Deterministically mapped 80 managers to the current Dataroma manager list.
- Dataroma has no current manager entry for Bridgewater Associates
  (`CIK 0001350694`) or Daily Journal Corporation (`CIK 0000783412`); both are
  reported as unavailable evidence, not silently omitted.
- The final live run had zero fetch failures.
- Every one of the 6,001 field-level evidence items is classified.
- Final suspected ValuePilot defects: **0**.
- Final unclassified material differences: **0**.

The SEC filing remains authoritative. Dataroma is used only as corroborating
evidence and no Dataroma value is written into ValuePilot holdings.

## Defects found and fixed

1. **Valid empty portfolios were treated as failed parses.** The SEC's exact
   `NONE / NONE / 000000000 / 0 / 0 / 0` sentinel is now recognized as a valid
   zero-position portfolio. Reparse activation and the user API now preserve
   and display that state correctly. Makaira Partners' Q1 2026 filing is the
   verified regression case.
2. **Some post-2023 filings still used legacy `$000` value units.** The parser
   now detects those filings using the holdings' implied-price distribution,
   while retaining the filing schema as the primary signal. Thirty-five
   affected accessions were reparsed; no active `schema_dollars` portfolio with
   at least three common-stock rows now has a median implied price below $1.
3. **A successful reparse could hide previously linked holdings.** Verified,
   unambiguous CUSIP-to-stock mappings are now carried forward across immutable
   parse runs for the same accession, including recovery after an intermediate
   bad reparse.
4. **Dataroma comparison logic mishandled real source behavior.** The parser and
   comparator now cover holdings pagination, invalid activity markup, exact
   integer split adjustments from 2:1 through 100:1, per-row `$000` rounding,
   Dataroma's 100-row activity cap, partial-filing coverage, and Dataroma's
   non-13F portfolio-impact calculation.
5. **Five seed mappings used stale/nonexistent Dataroma codes.** Baupost,
   Gates Foundation Trust, Hillman, Scion, and Pershing Square now use their
   verified current codes. Nonexistent Bridgewater and Daily Journal codes were
   removed.

## Data repaired and verified

- Backfilled the complete 2023 Q1 through 2024 Q1 history needed by the 82
  manager workbench. Every manager now has every quarter in that range; current
  history depth is 11–17 quarters.
- Computed ownership changes for all backfilled quarters and recomputed Q1 2026
  after reparses; no computation failures remained.
- Authoritative CUSIP enrichment linked 174 additional mappings across two
  passes.
- Re-ran July 1–17 daily SEC synchronization. The filings discovered on July 7,
  10, 15, and 16 were ingested successfully, including Q2 data for Aquamarine,
  Lindsell Train, and Matrix Asset Advisors.

## Residual differences, all explained

| Classification | Evidence items | Meaning |
|---|---:|---|
| `intentional_scope_boundary` | 2,197 | ValuePilot retains more SEC history than the Dataroma comparison surface exposes. |
| `intentional_coverage_caveat` | 1,377 | Partial-filing or manager-page coverage makes direct row comparison invalid. |
| `dataroma_page_limit` | 700 | Dataroma's filtered Activity/Buys/Sells surface stops at 100 rows. |
| `identity_or_coverage` | 537 | The two sources expose different ticker/identity coverage for the same filing universe. |
| `denominator_or_coverage` | 491 | Portfolio weights differ because the included position set or denominator differs. |
| `identity_or_aggregation` | 438 | Multiple SEC rows/classes aggregate differently on Dataroma. |
| `reporting_policy_or_value_unit` | 106 | Display rounding or source reporting policy differs; SEC raw value remains authoritative. |
| `identity_or_corporate_action` | 78 | Dataroma retro-adjusts historical shares for splits or identity changes; SEC reports period-as-filed shares. |
| `identity_coverage_gap` | 27 | 27 manager-level warnings cover 140 current rows whose CUSIPs remain unresolved after authoritative enrichment. |
| Other fully classified policy/source cases | 50 | Dataroma page inconsistencies, portfolio-impact policy, source identity policy, and two unavailable mappings. |

Representative deep checks:

- CRWD 4:1, BKNG 25:1, CVNA 5:1, VGT 8:1, VUG 6:1, IWF 4:1,
  MLI 2:1, and POWL 3:1 are Dataroma retroactive split adjustments; ValuePilot
  correctly preserves SEC period-as-filed shares.
- SNEX is mathematically consistent in ValuePilot: 54,035 current shares versus
  22,676 prior shares equals +138.29%. Dataroma adjusts the prior quarter for a
  3:2 split and therefore displays +58.86%.
- GLIBA is still present in the Q1 SEC filing at 127,548 shares although
  Dataroma displays a complete sale. The SEC-backed ValuePilot row is retained.
- AZN and PIPR changed CUSIPs. ValuePilot does not guess cross-CUSIP continuity
  where the prior identifier remains unresolved; Dataroma carries an adjusted
  history across the identity change.
- Dataroma's “% change to portfolio” is not a reported 13F field and does not
  reproduce from filing weights. ValuePilot uses filing-derived current and
  prior weights and labels the difference as a reporting-policy difference.

## Evidence

- Machine-readable aggregate: `2026-07-19_13f-dataroma-82-manager-reconciliation.json`
- Per-manager evidence, source URLs, and field-level explanations:
  `managers/3975.json` through `managers/4056.json`
- Reproduction command:
  `python -m app.cli.edgar reconcile-dataroma --manager-id <id> --history-quarters 13 --output <path>`

The aggregate contains 82 manager records, including the two explicit unmapped
records. Per-manager Dataroma URLs are preserved in each record alongside the
ValuePilot/SEC comparison context.

## Verification

- Targeted backend regression suite: 110 passed.
- Full backend suite on a migrated isolated PostgreSQL database: 1,315 passed,
  3 pre-existing SQLAlchemy deprecation warnings.
- Frontend unit/source-scanner suite: 198 passed.
- Frontend lint: no warnings or errors.
- Production frontend build: successful, including the manager list, manager
  workbench, and manager-by-stock routes.
- Browser acceptance: all five Duan Yongping workbench views passed; Makaira's
  Q1 2026 valid empty filing displayed 0 positions and $0; Aquamarine's latest
  Q2 2026 filing displayed $144.09M. No browser console warnings or errors.

The exact local canonical `docker compose exec -T api pytest -q` command still
binds to the populated shared development database and reproduced the existing
test-isolation defect recorded in `docs/BACKLOG.md`; it made no progress after
three early failures and was stopped without clearing development data. The
same complete suite passed in the isolated database. All other exact canonical
commands passed.
