# Review results — 13F data-trust guardrails (PR #119)

## Verdict

**Send back — one P2 correctness issue.** The two guardrail queries otherwise
have the intended current-holdings semantics, and the admin page/CTA wiring does
not introduce a runtime failure. But the high-impact-CUSIP task can state a
silently incomplete dollar impact as if it were exact. This is contrary to the
task's purpose of making data-trust gaps explicit.

## Findings

### P2 — nullable normalized values are silently reported as a complete dollar impact

- **Location:** `backend/app/services/thirteenf_admin_dashboard.py:1828`,
  `backend/app/services/thirteenf_admin_dashboard.py:1854`, and
  `frontend/app/(dashboard)/admin/13f/page.tsx:873`.
- **Trigger:** a latest-quarter, active, current HR holding has a valid unresolved
  CUSIP but `value_usd IS NULL`. This is a valid model state: the column is
  nullable and the ingestion path deliberately leaves it NULL when the unit rule
  is not known. Three managers holding the same unresolved CUSIP meet the
  `min_holders=3` threshold; only one has `value_usd=100`, while two have an
  unnormalised raw value of 100.
- **Observed result:** the isolated-transaction reproduction returned
  `{'manager_count': 3, 'value_usd': 100}`. PostgreSQL `SUM` ignores NULL and
  `int(r.value_usd or 0)` additionally turns an all-NULL group into zero. The UI
  then renders that partial value as an unqualified dollar amount (or `$0`).
- **Impact:** the P1 task still fires, but its stated "dollar impact" can be
  materially understated and can mis-prioritize a high-impact data gap. It does
  not identify the value-normalisation gap, so the loss is silent.
- **Reproduction (rolled back; no dev data changed):**

  ```bash
  docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api python - <<'PY'
  from datetime import date
  from app.core.db import SessionLocal
  from app.models.institutions import InstitutionManager, Filing13F, ParseRun13F, Holding13F
  from app.services.thirteenf_admin_dashboard import _high_impact_unresolved_cusips

  s = SessionLocal()
  try:
      for i, value_usd in enumerate((100, None, None)):
          cik, accession = f"08888888{i:02d}", f"08888888{i:02d}-26-000001"
          manager = InstitutionManager(canonical_name=f"review null usd {i}", cik=cik,
              legal_name=f"Review Null USD {i}", display_name=f"Review Null USD {i}",
              name_normalized=f"review null usd {i}", match_status="confirmed", status="active")
          s.add(manager); s.flush()
          filing = Filing13F(manager_id=manager.id, accession_no=accession,
              accession_number=accession, cik=cik, form_type="13F-HR",
              period_of_report=date(2026, 3, 31), filed_at=date(2026, 5, 15),
              report_quarter="2026-Q1", quarter_end_date=date(2026, 3, 31),
              is_active_for_manager_period=True)
          s.add(filing); s.flush()
          run = ParseRun13F(accession_number=accession, parser_version="review",
              fingerprint_version="v1", status="succeeded", is_current=True)
          s.add(run); s.flush()
          s.add(Holding13F(filing_id=filing.id, parse_run_id=run.id, manager_id=manager.id,
              accession_number=accession, cusip="888888888", issuer_name="Unknown Unit Co",
              value_thousands=100, value_usd=value_usd, row_fingerprint=accession,
              stock_id=None, cusip_mapping_status="unresolved"))
      s.flush()
      print(next(row for row in _high_impact_unresolved_cusips(s, "2026-Q1")
                 if row["cusip"] == "888888888"))
  finally:
      s.rollback(); s.close()
  # {'cusip': '888888888', 'issuer_name': 'Unknown Unit Co',
  #  'manager_count': 3, 'value_usd': 100}
  PY
  ```

- **Suggested fix:** carry a `value_usd_missing_count` (or a boolean completeness
  flag) in the aggregate. If any row is NULL, return `value_usd=None` rather than
  a partial sum, and render `impact unavailable — N values unnormalised` in the
  task card. Do not fall back to `value_thousands`: its unit is intentionally not
  safe as USD. Add tests for both partial-NULL and all-NULL groups.

## Checks that passed

- **Guardrail 1 / `NOT IN`:** the subquery excludes NULL `manager_id` values, so
  it is not vulnerable to SQL three-valued `NOT IN` suppression. A manager whose
  only filing is 13F-NT is deliberately treated as having filed; this is correct
  for this guardrail because the established 13F contract says NT-only managers
  have no direct holdings and are excluded from the expected-HR denominator.
  The isolated NT-only reproduction returned `flagged: false` as intended.
- **Guardrail 2 joins and counting:** it uses the same holding→current-parse-run
  primary-key join and active-HR filters as `active_hr_holdings_query`. Database
  constraints make `Filing13F.accession_number` unique and permit one current
  parse run per accession, preventing the claimed filing-side fan-out. A
  reproduction with three managers and two legal rows each returned
  `manager_count=3`, `value_usd=600`, confirming distinct-manager counting and
  full row-value aggregation.
- **Current data:** dev's current active HR holdings in 2026-Q1 have zero NULL
  `value_usd` rows; both new guardrails are absent after the documented data
  remediation. This does not remove the nullable-column future-data defect.
- **Semantic boundaries:** confirmed/active/CIK-bearing filtering, CIK-less and
  retired exclusion, `stock_id IS NULL`, and option exclusion agree with the
  documented contract.
- **Frontend:** browser check of `http://localhost:3001/admin/13f` mounted with
  no console errors; dev correctly showed `No admin tasks`. The `#managers`
  anchor exists, and both new CTA mappings have the expected safe operation.
- **Scope:** separating the OpenFIGI matcher repair is reasonable. It is a
  heuristic/identity change with an existing high-severity backlog record; this
  PR is correctly limited to surfacing the gap.

## Verification

| Check | Result |
|---|---|
| Targeted guardrail tests on `valuepilot_test` | 8 passed |
| Full backend suite on `valuepilot_test` | 1240 passed (3 pre-existing SQLAlchemy legacy warnings) |
| Frontend unit tests | 185 passed |
| Frontend lint | passed |
| Production frontend build | passed (Browserslist data-age notice only) |
| `git diff --check main...HEAD` | passed |

The production build's `.next` output was cleared and the `web` container was
restarted after verification, as required for the live dev server.

## Resolution (2026-07-10)

**P2 confirmed and fixed.** The finding is real and aligns with the project
invariant "financial data: unknown is not zero" — a partial `SUM(value_usd)` (or
`0` for an all-NULL group) was presented as a complete dollar impact.

- **Backend** (`_high_impact_unresolved_cusips`): the aggregate now also returns
  `value_usd_missing_count = count(*) - count(value_usd)` — the number of holdings
  whose value could not be normalized and were silently skipped by `SUM`. When
  that count is > 0, `value_usd` is documented (and rendered) as a lower bound,
  never the complete impact.
- **Frontend** (`/admin/13f`): new `formatCusipImpact(value_usd, missing)` renders
  `$X` when complete, `≥ $X · N unnormalized` when partial, and
  `impact unavailable · N unnormalized` when every value is missing — so a
  partial/zero sum is never shown as exact.
- **Tests:** the widely-held test now asserts `value_usd_missing_count == 0`, plus
  two new tests — partial-NULL (`value_usd=100`, `missing=2`) and all-NULL
  (`value_usd=0`, `missing=3`). The reviewer's exact repro now returns
  `{'manager_count': 3, 'value_usd': 100, 'value_usd_missing_count': 2}`.
- **Gates re-run green:** backend **1242 passed** (2 new), frontend **185
  passed**, lint clean, production build succeeded, dev `.next` restored.

## Re-review (2026-07-10)

**Verdict: mergeable.** The P2 is correctly fixed and this follow-up found no
new defect.

- The query now returns `value_usd_missing_count = count(*) - count(value_usd)`.
  This correctly exposes every holding that PostgreSQL omitted from the nullable
  sum without reintroducing the unsafe `value_thousands` fallback.
- Independent rollback-transaction reproduction confirmed both boundaries:
  partial normalized data returns `value_usd=100, value_usd_missing_count=2`;
  all unnormalized data returns `value_usd=0, value_usd_missing_count=3`.
  The UI's formatter renders these as a qualified lower bound and an unavailable
  impact respectively, rather than as a complete dollar value.
- Regression tests: targeted guardrail suite **10 passed**; full backend suite
  **1242 passed** (the same three pre-existing SQLAlchemy legacy warnings);
  frontend unit suite **185 passed**, lint and production build passed. The
  production build output was cleared and the dev web container restarted.
