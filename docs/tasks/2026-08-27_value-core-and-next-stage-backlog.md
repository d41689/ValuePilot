# ValuePilot product north star and next-stage backlog

## Goal

Make ValuePilot's enduring user value explicit in the cross-agent contract and
record the next product stage, **Financial Truth & Decision Loop Beta**, as
independently closable backlog work with objective acceptance criteria.

## Acceptance criteria

- `AGENTS.md` states the product north star and the six user jobs every agent
  must optimize for.
- The north star makes clear that ValuePilot supports independent, traceable
  long-term investment decisions; it does not optimize for stock tips, trading
  activity, or data volume.
- `docs/BACKLOG.md` contains one entry per independently closable next-stage
  problem rather than combining unrelated completion states.
- Every new backlog entry includes severity, problem, intended outcome,
  measurable acceptance criteria, context, and issue placeholder.
- The stage-level exit gate prevents a collection of partially complete items
  from being represented as a product beta.
- A versioned acceptance protocol owns the gold-set selection rules, evidence
  interaction definition, moderated usability rubric, and consumer-settling
  SLO without redefining PRD, mapping, source, or architecture contracts.

## Scope

### In

- Cross-agent product principles in `AGENTS.md`.
- Backlog entries for canonical prices, evidence retention, SEC financial
  identity/raw lineage/PIT, canonical publication, historical comparability,
  SEC/Value Line reconciliation, industry applicability, the research
  workspace, valuation, automatic case coverage, Oracle's Lens consumer
  consistency, monitoring/notification, portfolio journaling, and postmortem.
  The stage also includes a separately closable licensed EOD-history,
  corporate-action, and optional-live-quote foundation.
- A delivery-owned beta acceptance protocol; the locked issuer manifest itself
  remains the first implementation gate rather than being selected from current
  parser results during this documentation change.
- A roadmap delegation and cross-item dependency gates for the follow-on beta.

### Out

- Production code, database migrations, API or schema contracts.
- Detailed implementation sequencing below the cross-item dependency-gate level.
- Closing or rewriting pre-existing backlog entries.

## PRD and architecture references

- `docs/architecture/research-decision-support.md`
- `docs/architecture/coverage-source-policy.md`
- `docs/prd/value-pilot-prd-v0.1.md` §G
- `docs/plans/research_decision_loop_product_roadmap.md`
- `docs/plans/financial_truth_decision_loop_beta_acceptance.md`

## Files to change

- `AGENTS.md`
- `docs/BACKLOG.md`
- `docs/plans/research_decision_loop_product_roadmap.md`
- `docs/plans/financial_truth_decision_loop_beta_acceptance.md`
- `docs/tasks/2026-08-27_value-core-and-next-stage-backlog.md`

## Test plan

- Review the rendered Markdown structure and cross-links.
- Run `git diff --check`.
- Run the exact canonical closing gate from `AGENTS.md`, including Docker build,
  migrations, backend tests, frontend unit tests, lint, and production build.

## Sign-off trail

- 2026-08-27: Task opened from the PO product-value acceptance findings.
- 2026-08-27: Added the product north star and six user jobs to the cross-agent
  contract. Added a separate stage exit gate so partial delivery cannot be
  presented as the beta outcome.
- 2026-08-27: Third-party review returned `CHANGES REQUIRED` with VG-01 through
  VG-06. All were accepted as real: source revocation/account erasure,
  `metric_facts` single-truth ownership, industry applicability and historical
  comparability, permanent impairment versus volatility, repeatable acceptance,
  and oversized work-item boundaries.
- 2026-08-27: Clarified the north star, added the delivery acceptance protocol,
  and split the stage into independently closable entries. SEC work now separates
  authorization/identity/raw/PIT, canonical mapping/publication, comparability,
  and reconciliation. Post-decision work now separates monitoring/notification,
  portfolio journal, and postmortem/calibration.
- 2026-08-27: Adversarial loop 1 found that the new delivery protocol lacked an
  explicit delegation from the authoritative roadmap. Added that delegation and
  dependency gates, and tightened issuer uniqueness, usability scoring,
  acceptance-evidence privacy, company-classification authority, and maintenance-
  capex uncertainty.
- 2026-08-27: Adversarial loop 2 corrected the authoritative roadmap's stale
  status/version and found that canonical-current-price repair did not cover the
  requested historical market-data foundation. Added FT-15 for licensed EOD
  history, corporate actions, PIT corrections, delisted cases, and an explicitly
  separate optional live-quote boundary.
- 2026-08-27: Adversarial loop 3 corrected the roadmap's FT range and Markdown
  metadata formatting, and locked FT-15's changing research universe to a dated
  scope snapshot and provider-entitled/listing-life denominator.
- 2026-08-27: Adversarial loop 4 narrowed the single-truth language to
  fundamental/financial-statement facts so it cannot absorb the separate EOD,
  research, or portfolio contracts. Added a full locked-fixture provenance audit;
  the 30-fact/two-interaction check is now an additional manual sample, not the
  only evidence of traceability.
- 2026-08-27: Adversarial loop 5 found that the task's documentation-only test
  exception contradicted the unconditional canonical closing gate in
  `AGENTS.md`. Removed the exception and restored the full required verification.
- 2026-08-27: Canonical closing gate passed: Docker build, Alembic head, 1,461
  backend tests, 216 frontend tests, frontend lint, and production build. The
  build emitted only the pre-existing Browserslist age warning already recorded
  in `docs/BACKLOG.md`.
- 2026-08-27: Adversarial loop 6 rechecked authority ownership, source
  revocation/erasure, single fundamental-fact truth, industry applicability,
  historical and price comparability, independent delivery boundaries,
  repeatable protocols, dependency gates, and document structure. No new valid
  finding remained.
