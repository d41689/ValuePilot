# 13F MVP4 Decision Gate

## Goal / Acceptance Criteria

Define the MVP 4 scope and decision record before any user-facing
Oracle's Lens scoring implementation begins.

Acceptance criteria:
- Enumerate all candidate MVP 4 scope items, drawn from
  `docs/plans/13f_oracles_lens_dashboard_product_plan.md` and the MVP3
  end-to-end review carryovers.
- Close or explicitly defer MVP 4 pre-implementation decisions.
- Capture carryovers from MVP3 review verdicts.
- Produce an approval checklist for Tech Lead + product owner +
  domain SME before MVP4-01 starts.
- Do not implement any MVP 4 feature in this task.

## Scope In

- MVP 4 decision record and recommendations.
- Backlog sequencing proposal.
- Explicit scope-in / scope-out boundaries.
- Carryover triage from MVP3 end-to-end review.

## Scope Out

- Schema migrations.
- Oracle's Lens scoring implementation.
- Frontend Oracle's Lens dashboard implementation.
- Pre-2023 historical backfill execution.
- PRD edits.

## Source References

- `docs/plans/13f_oracles_lens_dashboard_product_plan.md` — Oracle's
  Lens product V1 plan (signal-weighted consensus, conviction score,
  caution flags, distinctive consensus, valuation reference, etc.).
- `docs/plans/13f_admin_data_operations_dashboard_product_plan.md` —
  admin dashboard product plan; largely shipped through MVP1C-2 +
  MVP3-08.
- `docs/prd/13f_automation_and_resilience_prd.md` — 13F automation
  PRD; ends at MVP3.
- `docs/tasks/2026-05-11_13f-mvp3-decision-gate.md` D1–D6.
- `docs/tasks/2026-05-11_13f-mvp3-end-to-end-verification.md` —
  Tech Lead / Product Owner / Domain SME verdicts; carryover items
  triaged in this gate's D6.

## MVP 4 Data Safety Principles

Inherits from MVP3 plus the user-facing constraints from the Oracle's
Lens product plan §4.3 "Product Decision Hierarchy":

- Do not mislead users about 13F limitations (delayed snapshots, NT
  reported elsewhere, confidential treatment, combination reports).
- Any user-facing score must remain explainable and auditable.
  Component inputs must be exposable. No opaque "AI score" behavior in
  V1.
- Prefer explainable heuristics over opaque scores.
- Treat missing data as a first-class product state. Zero is not the
  same as unavailable.
- Disconfirming evidence must be visible next to positive evidence.
- 13F holdings are quarter-end snapshots, not transactions. UI must
  not label them as cost basis, buy signal, or current holding.
- All scores must be versioned (`score_version`) so a backfill or
  recompute can leave older labelled snapshots intact.

## Decision Record

Each decision below is a **proposal**, not a closed call. Product
owner and Tech Lead approval is required before MVP4-01 starts.

### D1. Primary MVP 4 Deliverable Framing

Proposal: MVP 4 = **Oracle's Lens V1 user-facing scoring product** as
the primary deliverable, with MVP3 carryover hardening as a parallel
tech-debt subtrack (see D6).

Rationale:
- MVP1–3 shipped the 13F ingestion contracts. The next milestone
  question is "what user-facing surface uses these contracts."
- The Oracle's Lens product plan is the most-developed candidate, with
  detailed V1 metric definitions, ranking hierarchy, and explainability
  rules.
- Bundling tech-debt hardening into the same milestone avoids opening
  a separate MVP3.5 track for items that did not block MVP3 closure.

Open question: does the product owner want a different primary
deliverable for MVP4 (e.g., manager-level analytics page,
investor-facing alerts, or a different vertical)? If yes, this entire
plan changes shape.

### D2. Pre-2023 Historical Backfill Scope

Proposal: **Keep MVP3 D1's "curated dry-run only" upper bound for
pre-2023 in MVP4.** No production backfill for periods before
2023-Q1 in this milestone.

Rationale:
- The MVP3-07 validation gate has not yet observed production data;
  expanding the source quarter range before we have confidence in the
  validation findings is premature.
- The value-unit transition risk in PRD §7.2 is real for pre-2023
  filings; production-grade ingestion of pre-2023 data needs at least
  one quarter of MVP3-07 production observation first.

Open question: does any investor-data ask require pre-2023 holdings
in MVP4? If yes, this becomes a sub-task with explicit risk
acceptance.

### D3. Oracle's Lens V1 Score Surface

Proposal: V1 ships the following metrics from the Oracle's Lens plan:

| Metric | Plan section | V1 status |
| --- | --- | --- |
| Raw consensus count | §7.1 | In — eligibility filter |
| Signal-weighted consensus score | §7.2 | In — primary ranking |
| Portfolio weight | §7.3 | In — input to signal-weighted score |
| Add intensity | §7.4 | In — secondary explainer |
| Holding duration / streak | §7.10 | In — secondary explainer |
| Conviction score | §7.9 | In — secondary explainer |
| Distinctive consensus score | §7.11 | In — advanced sort, off by default |
| Caution flags | §7.13 | In — risk / disconfirmation panel |
| Quarter-end holding price estimate | §7.5 | In — labelled estimate only |
| Signal-Weighted Consensus Score Confidence | §7.12 | In — must surface alongside score |
| Owner Earnings Yield | §7.6 | Conditional on D4 (Value Line overlay) |
| Capital Allocation Grade | §7.7 | Conditional on D4 |
| Moat Proxy | §7.8 | Conditional on D4 |
| Valuation Reference Strength | §7.14 | Conditional on D4 |

Rationale: §7.1–§7.5 + §7.9–§7.13 form a coherent 13F-only V1. The
Value Line overlay metrics (§7.6–§7.8, §7.14) require Value Line data
plumbing and are gated on D4.

Open question: any V1 metrics the product owner wants to defer to V2
to reduce surface area? Conversely, anything the plan listed that the
owner wants pulled into V1?

### D4. Value Line Overlay in V1

Proposal: **Defer the Value Line overlay (§6.4, §7.6, §7.7, §7.8,
§7.14) to V2.** V1 ships as 13F-only.

Rationale:
- The Value Line parser and normalized metric facts already exist in
  the repo, but the overlay design (§8.4 "Business Quality Overlay")
  requires per-stock data plumbing the V1 13F scoring does not need.
- A 13F-only V1 ships faster and matches the product plan §4.3
  hierarchy ("Prefer explainable heuristics over opaque scores").
- Adding the overlay later is additive — none of the 13F-only metrics
  depend on Value Line data being present.

Open question: business / commercial preference may favor shipping
the overlay together with 13F V1 as a differentiator. If so, MVP4
scope grows.

### D5. Signal-Weighted Score Heuristic Constants

Proposal: ship V1 with the plan §7.2 example constants as defaults
(`manager_signal_weight` table + `position_signal_weight` base + adds),
exposed in a configuration-file-style module so a tuning round can
update them without code rewrites. Component inputs are persisted
alongside the score so a future recalibration leaves audit history.

Rationale:
- The plan explicitly says "V1 may start with transparent heuristics."
  Locking constants in code with no audit trail makes tuning expensive
  later; exposing them in a config-style module makes V1 honest about
  its calibration state.
- Persisting component inputs is the only way to honor §4.3's
  "Component inputs must be exposable" rule.

Open question: does the owner want to invest in an initial tuning
exercise (e.g., 4-quarter retrospective comparing
signal-weighted vs raw consensus) before V1 ships, or accept the
plan's example defaults as the launch constants?

### D6. MVP3 Carryover Triage

The MVP3 end-to-end review left the following carryovers. Proposal
classification:

| Item | Proposal | Rationale |
| --- | --- | --- |
| Shared advisory-lock helper (cusip_enrichment + corporate_action_mapping) | Defer to perpetual backlog | Still only two callers; extracting is cleanup work without a forcing function. |
| Shared `IntegrityError → typed-error` helper | Defer to perpetual backlog | Same reason — two callers (batch reparse + historical backfill). |
| Shared rule_code constants module | **MVP4 backlog** (`MVP4-XX rule-code constants`) | Five rule_codes across three services now. A user-facing findings filter in the admin dashboard or readiness API will need a single source of truth. |
| Signed `holdings_rows_net_delta` field | Defer to perpetual backlog | No active consumer needs the signed delta; revisit when MVP3-08 admin UI surfaces this column. |
| `'corporate_action'` `QualityReport13F.status` vocabulary | Defer to perpetual backlog | Per MVP3-06 review; revisit when a concrete filter use case appears. |
| Conftest savepoint hardening | **MVP4 backlog** (`MVP4-XX conftest savepoint hardening`) | Three benign SAWarning events now; if MVP4 service work adds another `IntegrityError` translator the warning count will grow. |
| Dry-run vs real quality_report disambiguation | **MVP4 backlog** (`MVP4-XX backfill quality_report source linkage`) | Dashboards aggregating quality runs will conflate dry-run with real until this is resolved. |
| `_finalize_impact` shallow copy hazard | Defer to perpetual backlog | Single-call shape; flag in code comment if needed. |

Open question: any items the product owner wants to escalate to
**MVP4-01-required** rather than backlog?

## Proposed MVP 4 Task Sequence

Sequence assumes D1 = Oracle's Lens V1 + D2 = no pre-2023 production
+ D3 = the V1 metric surface above + D4 = Value Line overlay deferred
+ D5 = heuristic constants in config + D6 = three new backlog tickets.

1. `MVP4-01` Score schema + ORM (precomputed
   `oracles_lens_signals` table or column extensions on existing
   `ownership_changes` / `holdings_13f`).
2. `MVP4-02` Signal-weighted consensus score service + API contract +
   tests.
3. `MVP4-03` Conviction score + holding duration / streak service +
   API contract + tests.
4. `MVP4-04` Caution flags service + API contract + tests.
5. `MVP4-05` Distinctive consensus score service + API contract +
   tests (advanced sort, off by default).
6. `MVP4-06` Oracle's Lens dashboard frontend V1 (page layout, ranking
   table, secondary explainers, caution flags panel).
7. `MVP4-07` Shared rule_code constants module (from D6).
8. `MVP4-08` Conftest savepoint hardening (from D6).
9. `MVP4-09` Backfill quality_report source linkage (from D6).
10. `MVP4-10` MVP 4 end-to-end verification.

Note: MVP4-07 / 08 / 09 can run in parallel with MVP4-01 through
MVP4-06; they touch different surfaces.

## Approval Checklist

- [ ] D1 primary deliverable framing approved (Oracle's Lens V1 +
      tech-debt subtrack) — **product owner**.
- [ ] D2 pre-2023 historical backfill stays at "curated dry-run only"
      for MVP4 — **product owner**.
- [ ] D3 V1 score surface approved (or revised list of in / deferred
      metrics) — **product owner**.
- [ ] D4 Value Line overlay deferred to V2 — **product owner**.
- [ ] D5 heuristic constants approach approved (config-style module +
      persist component inputs) — **product owner** with Tech Lead
      review.
- [ ] D6 carryover triage approved — **Tech Lead** primary.
- [ ] Human owner approves MVP 4 scope freeze and exclusions.
- [ ] MVP4-01 Score schema explicitly approved to start.

## Progress Notes

- 2026-05-11: Created after MVP 3 final acceptance approved entry into
  MVP 4 decision gate / scope planning. Sources: MVP3-09 closure,
  PO end-to-end verdict ("recommend opening MVP4"), Oracle's Lens
  product plan, MVP3 end-to-end review carryovers.

## Verification Results

- Documentation-only decision gate; Docker verification not required.
