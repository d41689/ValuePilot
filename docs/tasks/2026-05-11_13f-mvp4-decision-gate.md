# 13F MVP4 Decision Gate

## Status

- **Gate status:** CLOSED (2026-05-11).
- **MVP4-01 status:** Approved to start; task log at
  `docs/tasks/2026-05-11_13f-mvp4-01-score-schema-orm.md`.
- **Approvals:** Product Owner ✓ (initial + re-review),
  Tech Lead ✓ (REVISED-APPROVE conditional, conditions met),
  13F Domain SME ✓ (HOLD CLOSED), Human Owner ✓ (delegated
  scope freeze + start authorization 2026-05-11).
- This document is now an immutable decision record. Subsequent
  scope changes reopen the gate.

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

**SME remediation (2026-05-11):** Because pre-2023 holdings are absent
from production data, any holder whose true position began before
2023-Q1 will show `streak=1` in 2023-Q1 with no `new_position` flag
(per PRD §7.4 `no_prior_data` semantics). The §7.10 streak and §7.9
persistence component will therefore understate conviction silently
for right-censored holders. V1 must emit a new per-row caveat code
when the holder's earliest observed quarter equals the data-window
floor:

  `PRE_2023_PRE_HISTORY_UNAVAILABLE` — "Holding duration and
  'New' classification reflect data starting 2023-Q1; pre-2023
  ownership for this holder is not observed."

The code is row-level (carried on the per-holder explanation payload)
and may roll up to readiness as a structural caveat analogous to
`NT_DETECTION_UNSUPPORTED`. The scoring services in MVP4-03 / MVP4-04
must consume it before producing the streak / persistence component.

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

**PO clarification (2026-05-11):** Distinctive Consensus Score (§7.11)
ships as a **visible-but-off-by-default sort option in the UI** — it
appears in the sort dropdown as a selectable column/sort key, not
hidden behind an admin toggle. Hiding it behind an admin toggle would
make it uncommunicable to users and untestable in production. The
plan's own caveat (anti-crowding is a weak proxy in V1) supports the
off-by-default posture without removing user accessibility.

**SME remediations (2026-05-11) — caveat propagation rules.** D3's
V1 metrics must each handle the existing 13F caveats explicitly.
Without these rules the surface lies about precision:

a) **Partial-coverage holdings (`coverage_completeness='partial'`,
   PRD §7.2 line 588–592):** `portfolio_weight_pct` is mandated NULL
   on Combination Reports. Plan §7.2's
   `position_signal_weight` adders (`+0.40 if top 10`, `+0.30 if
   position weight >= 5%`) are silently unevaluable for these
   holders. V1 must drop partial-coverage holdings from the
   signal-weighted sum and emit a per-holding caveat
   (`PARTIAL_COVERAGE`), and §7.12 score_confidence must demote to
   at most `medium` whenever any contributing row carries
   `coverage_completeness='partial'`.

b) **Open `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`
   findings (from MVP3-06).** Stored `change_status` may be
   `exited_position + new_position` for the same economic security
   pre-recompute. §7.4 add intensity and §7.10 streak must either
   exclude affected rows until recompute completes, or snap the
   contribution to flat with a `stale_until_recompute` per-holding
   caveat. §7.12 score_confidence demotes to at most `low` whenever
   any contributing row has an open finding.

c) **Confidential treatment
   (`has_confidential_treatment=true`).** PRD §9.2.2 keeps these
   in the consensus count but tags the row. V1 score payload's
   per-holder explanation must propagate the `CONFIDENTIAL_TREATMENT`
   flag at the row level (not only at the quarter-level readiness
   warning) so a user looking at one stock can tell which of the
   N holders are on a confidential-treatment filing. §7.12
   score_confidence demotes to at most `medium` when any
   contributing row is confidential.

d) **NT quarter in streak (PRD §9.1).** An NT quarter is
   `no_direct_holdings_data` — neither a break nor a continuation.
   §7.10 streak must reset to the post-NT run, must not classify
   the holding as exit, and must emit an explicit
   `NT_QUARTER_STREAK_BREAK` caveat on that row. §7.12
   score_confidence demotes to at most `medium` when any
   contributing manager had an NT quarter inside the lookback
   window.

e) **Open `HISTORICAL_BACKFILL_NEEDS_VALIDATION` findings (from
   MVP3-07).** V1 scores must either exclude unvalidated backfill
   data or demote `score_confidence` to at most `low` while emitting
   `HISTORICAL_BACKFILL_NEEDS_VALIDATION` at the row level.

**SME remediation (2026-05-11) — caution-flags surface (§7.13)
vocabulary.** Plan §7.13's V1 list uses code names that do not match
existing readiness codes (e.g. `partial_period` vs
`PARTIAL_COVERAGE`). V1 must consume the canonical readiness
vocabulary as a transparent pass-through rather than inventing a
parallel namespace. Per-row caution_flags must surface, in addition
to plan §7.13's own codes, the following readiness-derived codes
when applicable:

  - `CONFIDENTIAL_TREATMENT`
  - `PARTIAL_COVERAGE`
  - `AMENDMENTS_PENDING`
  - `AMENDMENT_FAILED`
  - `NT_DETECTION_UNSUPPORTED` (page-level banner; row-level when
    a contributing manager is NT-affected in the lookback window)
  - `OWNERSHIP_CHANGES_NEEDS_RECOMPUTE` (MVP3-09)
  - `HISTORICAL_BACKFILL_NEEDS_VALIDATION` (MVP3-09)
  - `PRE_2023_PRE_HISTORY_UNAVAILABLE` (D2 above)

The §7.13 service in MVP4-05 must consume `thirteenf_readiness.warnings`
and per-holding `QualityFinding13F` rows, and use the same canonical
code names in the score payload as the readiness API.

**SME re-confirm note for MVP4-05 task file (2026-05-11, non-blocking):**
MVP4-05's caution-flags surface includes **both** readiness pass-through
codes (the 8 above) **and** score-service-emitted row-level codes
(`NT_QUARTER_STREAK_BREAK` from rule (d), `stale_until_recompute` from
rule (b), and any future score-derived row codes). When the MVP4-05
task file is authored, it must call out both channels explicitly —
pass-throughs flow on the readiness channel, score-emitted codes flow
on the per-holder explanation channel.

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

**PO clarifications (2026-05-11):**
- **No pre-launch tuning.** Plan §7.2 example constants are
  well-reasoned, transparent, and documented; pre-launch tuning
  against the current 477-filing / 80-manager dataset would not
  produce statistically robust calibration and would delay shipping
  without materially improving V1 outcomes. The right forcing
  function for tuning is observed production signal data, not a
  pre-ship retrospective on the same synthetic baseline.
- **Component inputs MUST be exposed in the UI drilldown** (not in
  the main ranking table). The main table exposes only the composite
  score with 1–2 reason chips per plan §8.3; the
  `HolderDrilldownPanel` component must include the per-manager
  component breakdown. This is required by the Data Safety Principle
  "Component inputs must be exposable" and matches the plan §7.9 /
  §9.1 API response sketch (`score_explanation.conviction_components`).

**TL revisions (2026-05-11) — module / storage / versioning shape:**
- **Constants module shape: typed Python module**
  (`app/services/oracles_lens/constants.py`) with named module-level
  constants, not a `.json` / `.toml` file. Type-safe, importable in
  tests, automatically git-audited. A DB-table form would require
  per-row timestamping or versioning to preserve the same audit
  property, and tuning still requires re-running the scoring job
  regardless of where constants live — the deploy requirement is the
  only thing that changes.
- **Component audit shape: separate
  `oracles_lens_score_components` table** keyed on
  `(score_id, component_name)`, not a JSONB blob on the score row.
  Same pattern as `quality_findings_13f` so component-level queries
  ("which stocks had `position_importance > 25` on V1 scores")
  and backfill validation are first-class.
- **`score_version` shipped from day one** as a `VARCHAR(20)` string
  label (e.g. `"v1.0"`) on the score row. Already mandated by the
  "MVP 4 Data Safety Principles" section above. No separate
  `versions` FK table needed in V1.

**SME remediation (2026-05-11) — manager_type taxonomy prerequisite
(blocking).** D5's "ship plan §7.2 example constants as defaults" is
currently **undefined** because the existing manager_type surfaces do
not agree with the plan's weight keys:

| Surface | Values | Notes |
| --- | --- | --- |
| `InstitutionManager.manager_type` (admin-set column) | `fundamental_long`, `activist`, `quant`, `multi_strategy`, `index_like`, `unknown` | Default `unknown`; admin-tunable |
| `oracles_lens.manager_signal.derive_manager_signal_profile()` (behavior-derived) | `long_term_fundamental`, `value_concentrated`, `high_turnover`, `unknown` | Computed |
| Plan §7.2 weight keys | `long_term_fundamental`, `value_concentrated`, `activist`, `unknown`, `quant`, `high_turnover`, `index_like` | Spans both other surfaces |

Three plan-weight keys (`long_term_fundamental` vs admin's
`fundamental_long` naming, `value_concentrated`, `high_turnover`)
have no admin path; the admin's `multi_strategy` has no plan weight.
D5 cannot ship until a new MVP4 sub-task reconciles these to one
canonical vocabulary and decides admin-set vs behavior-derived
precedence. **This is filed as `MVP4-11 manager_type taxonomy
reconciliation` in the revised task sequence below and must complete
before MVP4-03 starts.**

**SME re-confirm note for MVP4-11 task file (2026-05-11,
non-blocking):** when MVP4-11's task file is opened, include
"admin UI exposes which managers' `manager_type=unknown` status
materially affects `score_confidence` on the latest usable quarter"
as an explicit sub-deliverable. The user-facing surface already
exists (`oracles_lens/dashboard.py` emits `unknown_manager_type_count`
and `unknown_manager_type_heavy`), so this is an admin-side
prioritization aid: it lets admins decide which managers to
type-classify rather than guessing.

### D6. MVP3 Carryover Triage

The MVP3 end-to-end review left the following carryovers. Proposal
classification:

| Item | Proposal | Rationale |
| --- | --- | --- |
| Shared advisory-lock helper (cusip_enrichment + corporate_action_mapping) | Defer to perpetual backlog | Still only two callers; extracting is cleanup work without a forcing function. |
| Shared `IntegrityError → typed-error` helper | **MVP4-01 design note** | TL revision: MVP4-01 must decide scoring insert conflict strategy (ORM upsert vs IntegrityError translator) before MVP4-03 starts. If upsert is chosen the third-caller rule does not trigger and the helper stays perpetual; if not, extract before MVP4-03 merges. Not a standalone backlog ticket. |
| Shared rule_code constants module | **MVP4 backlog** (`MVP4-XX rule-code constants`) | Five rule_codes across three services now. A user-facing findings filter in the admin dashboard or readiness API will need a single source of truth. |
| Signed `holdings_rows_net_delta` field | Defer to perpetual backlog | No active consumer needs the signed delta; revisit when MVP3-08 admin UI surfaces this column. |
| `'corporate_action'` `QualityReport13F.status` vocabulary | Defer to perpetual backlog | Per MVP3-06 review; revisit when a concrete filter use case appears. |
| Conftest savepoint hardening | **MVP4 backlog** (`MVP4-XX conftest savepoint hardening`) | Three benign SAWarning events now; if MVP4 service work adds another `IntegrityError` translator the warning count will grow. |
| Dry-run vs real quality_report disambiguation | **MVP4 backlog** (`MVP4-XX backfill quality_report source linkage`) | Dashboards aggregating quality runs will conflate dry-run with real until this is resolved. |
| `_finalize_impact` shallow copy hazard | Defer to perpetual backlog | Single-call shape; flag in code comment if needed. |

Open question: any items the product owner wants to escalate to
**MVP4-01-required** rather than backlog?

**TL sequencing constraint (2026-05-11):**
- `MVP4-09 shared rule_code constants module` must land **before
  MVP4-03 starts** (scoring services may define new rule_codes and
  drift would force a retrofit).
- `MVP4-10 conftest savepoint hardening` must land **before MVP4-03
  test authoring begins** to avoid pattern divergence across
  scoring-service test files.
- The `IntegrityError translator` decision moved out of D6 and into
  MVP4-01 acceptance criteria (see "MVP4-01 Pre-Start Conditions"
  below).

## Proposed MVP 4 Task Sequence

**Revised 2026-05-11** after Tech Lead review identified a
dependency inversion (signal-weighted score §7.2 consumes
`holding_streak_quarters` from §7.10) and SME review added the
manager_type taxonomy prerequisite. The original ordering would have
shipped an incomplete signal-weighted score at MVP4-02 merge that
would need a retrofit later.

Sequence assumes D1 = Oracle's Lens V1 + D2 = no pre-2023 production
+ D3 = the revised V1 metric surface (with SME caveat propagation
rules) + D4 = Value Line overlay deferred + D5 = config module +
separate component-audit table + score_version + manager_type
taxonomy prerequisite + D6 = three new backlog tickets +
IntegrityError as MVP4-01 design note.

> **Numbering does not imply chronological order.** `MVP4-08`,
> `MVP4-09`, `MVP4-10`, and `MVP4-11` are **parallel prerequisites
> that must complete before `MVP4-03` starts** (see
> "Parallel pre-MVP4-03 prerequisites" below). In particular,
> **`MVP4-11 manager_type taxonomy reconciliation` is a hard
> blocker for MVP4-03** despite its high number — the
> signal-weighted score's manager-weight table is undefined until
> the taxonomy is reconciled. The numbering reflects functional
> grouping (main path vs parallel tickets vs verification), not
> calendar order.

Main path (sequential):

1. `MVP4-01` Score schema + ORM. Must resolve the pre-start
   conditions below (precomputed `oracles_lens_signals` table vs
   column extension; JobRun integration; scoring source-of-truth;
   IntegrityError vs upsert) before opening the migration.
2. `MVP4-02` Holding streak + portfolio weight base service
   (plan §7.3 / §7.4 / §7.10). These are shared primitive inputs
   consumed by MVP4-03 and MVP4-04.
3. `MVP4-03` Signal-weighted consensus score service + API +
   tests (plan §7.2). Depends on MVP4-02 streak. Primary ranking
   metric.
4. `MVP4-04` Conviction score service + API + tests (plan §7.9).
   Depends on MVP4-02 streak. Parallel-safe with MVP4-03.
5. `MVP4-05` Caution flags service + API + tests (plan §7.13 +
   D3's caveat-propagation pass-throughs from
   `thirteenf_readiness`). Scope is conditional on the scoring
   source-of-truth decision in MVP4-01 (see pre-start conditions).
   Starts after MVP4-03 and MVP4-04.
6. `MVP4-06` Distinctive consensus score service + API + tests
   (plan §7.11). Depends on MVP4-03. Parallel-safe with
   MVP4-04 / MVP4-05.
7. `MVP4-07` Oracle's Lens dashboard frontend V1 (page layout,
   ranking table, distinctive-consensus as visible-but-off
   sort option, secondary explainers, caution flags panel,
   drilldown component-input exposure per PO clarification).
   G4 contract boundary: the four backend service APIs
   (MVP4-03 / 04 / 05 / 06) must have passed response-shape review
   before this task file opens.

Parallel pre-MVP4-03 prerequisites (must complete before MVP4-03
starts):

8. `MVP4-08` Backfill `quality_report` source linkage. Fully
   independent of scoring work; parallel throughout MVP4.
9. `MVP4-09` Shared rule_code constants module. Must land before
   MVP4-03 starts to avoid rule_code drift across scoring services.
10. `MVP4-10` Conftest savepoint hardening. Must land before
    MVP4-03 test authoring begins to avoid pattern divergence.
11. `MVP4-11` Manager_type taxonomy reconciliation. Must land
    before MVP4-03 starts; resolves the three-surface mismatch
    documented in D5 SME remediation. Picks one canonical
    taxonomy, defines admin-set vs behavior-derived precedence,
    and updates `derive_manager_signal_profile` + admin UI to a
    single vocabulary.

Closing task:

12. `MVP4-12` MVP 4 end-to-end verification.

### MVP4-01 Pre-Start Conditions

MVP4-01's task file must resolve four design decisions before its
migration work begins. Tech Lead review identified the first two;
the second pair is required by the gate's prior decisions.

1. **Storage shape (TL note):** precomputed
   `oracles_lens_signals` table vs column extensions on existing
   `ownership_changes` / `holdings_13f`. PO noted this is a TL
   schema call that must be explicit in MVP4-01 before migration
   work begins.
2. **JobRun integration (TL cross-cutting #1):** the scoring
   backfill follows the same write-path-under-failure pattern as
   MVP3-07 historical backfill. MVP4-01 must include:
   - a new `job_type` constant for `oracles_lens_score_backfill`,
   - a new `lock_key` prefix
     (e.g. `"oracles_lens_score:{period}:{score_version}"`),
   - a `JobRun` row per recompute run for audit-trail parity with
     MVP3-07.
3. **Scoring source-of-truth (TL cross-cutting #2):** plan §6.1
   lists `holdings_13f` as the scoring source of truth, but the
   gate must confirm that no scoring input flows through
   `ownership_changes`. If anything does, then open
   `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`
   findings from MVP3-06 can produce silently incorrect scores;
   MVP4-05 caution flag scope must then include a
   `stale_recompute_pending` flag wired to those findings.
4. **Insert conflict strategy (TL D6 revision):** decide whether
   scoring inserts use ORM upsert (`INSERT ... ON CONFLICT DO
   UPDATE`) or the IntegrityError → typed-error translator pattern
   from MVP3-05 / MVP3-07. Upsert is cleaner for idempotent
   recompute; translator extracted-as-helper is only needed if
   upsert is rejected. Decide before MVP4-03 starts.
5. **Row-level caveat + confidence-demotion representation
   (PO re-review P2 #4):** MVP4-01 schema must explicitly leave
   room for the D3 caveat-propagation surface that MVP4-05 will
   consume. The schema MUST support:
   - **Row-level caveat codes** — the per-row payload must carry
     the canonical readiness pass-through codes (the 8 listed in
     D3's caution-flags vocabulary block) **and** score-service-
     emitted row codes (`NT_QUARTER_STREAK_BREAK`,
     `stale_until_recompute`). Both flow on the same per-holder
     channel.
   - **Confidence demotion reasons** — when `score_confidence` is
     demoted below `high_confidence`, the schema must carry the
     reason(s) that caused the demotion so an admin / user can
     answer "why is this score's confidence only `medium`?"
     without re-running the demotion table by hand.
   No new column needed: `caution_flag_codes JSONB` carries the
   row-level code array, and `score_explanation JSONB` carries a
   `confidence_demotion_reasons` key with the shape
   `[{"code": "<flag>", "demoted_to": "<level>"}, ...]`. MVP4-05's
   service is responsible for populating that key consistently.
   MVP4-01's acceptance must call this out so MVP4-03 / MVP4-05 do
   not invent a parallel mechanism.

### MVP4-01 Pre-Start Condition Resolutions (2026-05-11)

Human owner delegated the four resolutions to the implementation
engineer; recorded here so the source of truth lives on the gate.

1. **Storage shape — RESOLVED: precomputed `oracles_lens_signals`
   table.**
   Rationale: aligns with MVP3-06's no-mutation principle (scoring
   is derived, not a property of the audit row); supports
   `score_version` as a clean column on the score row; recompute
   replaces rows without touching `holdings_13f` or
   `ownership_changes`. The plan §6.1 source-of-truth list also
   implies scoring is a separate concept from ingestion. The added
   table + FK cost is already accepted under D5's separate
   `oracles_lens_score_components` audit table.

2. **JobRun integration — RESOLVED: accept TL's spec exactly.**
   - `job_type = "oracles_lens_score_backfill"`.
   - `lock_key = f"oracles_lens_score:{period}:{score_version}"`.
   - One `JobRun` row per recompute run.
   The `score_version` segment in the lock_key permits a future
   v1.0 production run and a v1.1 shadow run to proceed
   concurrently without collision.

3. **Scoring source-of-truth — RESOLVED: read `holdings_13f`
   (PRD §7.3 query contract: active HR/HR-A + current parse_run),
   compute cross-quarter joins inside the scoring service.**
   Rationale: keeps the source of truth single; avoids coupling
   the scoring pipeline to the `ownership_changes` recompute
   pipeline; honors MVP3-06's no-silent-rewrite principle. The
   `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`
   finding still affects MVP4-05 caution-flag scope — D3 rule (b)
   already specifies `stale_until_recompute` per-holding caveat
   when an open finding exists for the holder × period
   combination. No new condition added to MVP4-05.

4. **Insert conflict strategy — RESOLVED: ORM upsert
   (`INSERT ... ON CONFLICT (stock_id, period, score_version) DO
   UPDATE SET ...`).** The IntegrityError translator stays
   perpetual; D6's "third-caller rule" does not trigger. Score
   recompute is by-design idempotent, so upsert is both the
   simpler write path and the cleaner failure-mode story.

5. **Row-level caveats + confidence demotion reasons — RESOLVED:
   reuse the existing JSONB pair, no new column.**
   - `caution_flag_codes JSONB` (array of strings) carries the
     row-level caveat codes (canonical readiness pass-through plus
     score-service-emitted row codes per D3).
   - `score_explanation JSONB` carries a
     `confidence_demotion_reasons` key with the shape
     `[{"code": "<flag>", "demoted_to": "<level>"}, ...]` populated
     by MVP4-05 whenever `score_confidence` is demoted below
     `high_confidence`.
   Rationale: the demotion mapping is deterministic given the D3
   rules, so the codes plus a stable JSON key let MVP4-05 surface
   "why was confidence demoted" without adding a normalized column.
   If a future filter use case requires querying by demotion code
   relationally, the field can be promoted to a separate table at
   that point; MVP4 does not have that consumer.

## Approval Checklist

- [x] D1 primary deliverable framing approved (Oracle's Lens V1 +
      tech-debt subtrack) — **product owner**.
- [x] D2 pre-2023 historical backfill stays at "curated dry-run only"
      for MVP4 — **product owner**. SME remediation
      (`PRE_2023_PRE_HISTORY_UNAVAILABLE` caveat code) applied.
- [x] D3 V1 score surface approved (10 metrics, distinctive consensus
      visible-but-off-by-default in UI dropdown per PO clarification)
      — **product owner**. SME caveat-propagation remediations (a–e)
      and caution-flags vocabulary pass-through applied; awaiting SME
      re-confirm.
- [x] D4 Value Line overlay deferred to V2 — **product owner**.
- [x] D5 heuristic constants approach approved (typed Python module +
      separate `oracles_lens_score_components` audit table +
      `score_version` from day one + drilldown component exposure
      per PO and TL revisions) — **product owner** and **Tech Lead**.
      SME prerequisite — manager_type taxonomy reconciliation —
      filed as `MVP4-11`; awaiting SME re-confirm that the new
      sub-task adequately addresses the three-surface mismatch.
- [x] D6 carryover triage approved with TL revision — IntegrityError
      moved to MVP4-01 design note; sequencing constraints on
      MVP4-09 / MVP4-10 — **Tech Lead** primary.
- [x] SME re-confirm on D3 caveat propagation, D2 caveat code, and
      D5 manager_type taxonomy sub-task framing. **HOLD CLOSED**
      2026-05-11. Two non-blocking notes captured inline for the
      future MVP4-05 and MVP4-11 task files.
- [x] Human owner approves MVP 4 scope freeze and exclusions.
      Delegated to implementation engineer 2026-05-11; scope
      frozen at the 12-task list above (Oracle's Lens V1 + three
      MVP3 carryover items + manager_type taxonomy + e2e
      verification). No additions accepted in MVP4 without
      reopening this gate.
- [x] MVP4-01 task file lands with the four pre-start conditions
      resolved (storage shape, JobRun integration, scoring
      source-of-truth, insert conflict strategy). See
      `docs/tasks/2026-05-11_13f-mvp4-01-score-schema-orm.md`.
- [x] MVP4-01 Score schema explicitly approved to start.
      Delegated 2026-05-11.
- [x] MVP4-12 end-to-end verification complete.
      `docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`
      records 754 passed / 0 warnings, all eleven MVP4 sub-tasks
      shipped, D1–D6 individually verified against shipped code,
      scope-freeze tally zero. 2026-05-12.

## Progress Notes

- 2026-05-11: Created after MVP 3 final acceptance approved entry into
  MVP 4 decision gate / scope planning. Sources: MVP3-09 closure,
  PO end-to-end verdict ("recommend opening MVP4"), Oracle's Lens
  product plan, MVP3 end-to-end review carryovers.
- 2026-05-11: Three cross-task reviews complete (Product Owner, Tech
  Lead, 13F Domain SME). Gate revised inline with all accepted
  feedback; details below.
  - **Product Owner verdict: APPROVE TO START MVP4-01** with two
    clarifications, applied above:
    - D3: Distinctive Consensus Score (§7.11) ships as
      visible-but-off-by-default sort option in the UI dropdown,
      not behind an admin toggle.
    - D5: No pre-launch tuning; component inputs must be exposed in
      the `HolderDrilldownPanel` (not the main ranking table).
    - PO also flagged that MVP4-01 must explicitly resolve the
      precomputed-table-vs-column-extension storage shape, since
      D5 / the gate left that open. Captured as pre-start condition #1.
  - **Tech Lead verdict: APPROVE TO START MVP4-01 once PO lands
    D1–D4, with REVISED D5, REVISED D6, and a REVISED task
    sequence.** Applied above:
    - D5: typed Python `constants.py` module (not JSON/TOML); separate
      `oracles_lens_score_components` audit table (not JSONB blob);
      `score_version` from day one (already mandated by Data Safety
      Principles, now closed as a resolved decision).
    - D6: `IntegrityError → typed-error` translator is **not** a
      perpetual deferral and **not** a standalone backlog ticket.
      Decide ORM upsert vs translator in MVP4-01 before MVP4-03
      starts. MVP4-09 rule_code constants must land before
      MVP4-03 starts; MVP4-10 conftest hardening before MVP4-03
      test authoring begins.
    - Task sequence: original `MVP4-02 signal-weighted before
      MVP4-03 conviction+streak` was a dependency inversion. New
      sequence introduces `MVP4-02 holding streak + portfolio
      weight base` shared primitives consumed by both
      `MVP4-03 signal-weighted` and `MVP4-04 conviction`. Frontend
      promoted to `MVP4-07`; carryovers renumbered to
      `MVP4-08 / 09 / 10`; verification is `MVP4-12`.
    - Two cross-cutting items must be added to MVP4-01 acceptance
      criteria (captured as pre-start conditions #2 and #3): JobRun
      integration for score recompute, and scoring source-of-truth
      vs `ownership_changes` stale-recompute dependency.
  - **13F Domain SME verdict: HOLD pending four remediations,
    all applied above:**
    - D2: New per-row caveat code
      `PRE_2023_PRE_HISTORY_UNAVAILABLE` for right-censored holders
      whose earliest observation falls on the data-window floor.
    - D3: Per-row caveat propagation rules (a–e) for
      `coverage_completeness='partial'`,
      `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE`, `has_confidential_treatment`,
      NT quarter in streak, and `HISTORICAL_BACKFILL_NEEDS_VALIDATION`.
      Each rule specifies how `score_confidence` (§7.12) demotes
      and which row-level caveat propagates.
    - D3 caution-flags vocabulary: plan §7.13 must consume the
      canonical readiness vocabulary as a transparent pass-through
      rather than inventing parallel codes.
    - D5: New `MVP4-11 manager_type taxonomy reconciliation`
      sub-task; the three existing manager_type surfaces
      (`InstitutionManager.manager_type` admin enum,
      `derive_manager_signal_profile` behavior output, plan §7.2
      weight keys) do not agree. Resolved by MVP4-11 picking one
      canonical taxonomy before MVP4-03 starts.
  - SME re-confirm is pending on the applied D2 / D3 / D5
    remediations; the approval checklist tracks two unchecked SME
    items. PO and TL approvals are recorded as checked.
- 2026-05-11: **SME re-confirm verdict: HOLD CLOSED — MVP4 gate
  financially-correct.** All four remediations confirmed:
  - D2 `PRE_2023_PRE_HISTORY_UNAVAILABLE` caveat code: confirmed,
    including the MVP4-03 / MVP4-04 consumer scope and the optional
    readiness roll-up.
  - D3 caveat propagation rules (a–e): all five confirmed, including
    the strict-drop interpretation for rule (a) (PRD §7.2 line
    588–592 makes the fallback structurally unevaluable), and the
    fifth rule (e) on `HISTORICAL_BACKFILL_NEEDS_VALIDATION`
    confirmed as a correct extrapolation from rule (b)'s pattern
    with `score_confidence` demoted to `low` (data may be wrong tier,
    not the snapshot-incomplete tier).
  - D3 caution-flags vocabulary: confirmed against the readiness
    service's actual exports. One non-blocking note captured inline:
    MVP4-05 task file must call out that the caution-flags surface
    includes both readiness pass-through codes and score-service-
    emitted row-level codes (`NT_QUARTER_STREAK_BREAK`,
    `stale_until_recompute`).
  - D5 `MVP4-11 manager_type taxonomy reconciliation`: confirmed,
    including the three-surface mismatch table. One non-blocking
    note captured inline: MVP4-11's task file should include
    "admin UI exposes which managers' `manager_type=unknown`
    materially affects `score_confidence` on the latest usable
    quarter" as a sub-deliverable so admins can prioritize
    type-classification work.
  - MVP4 is now unblocked from the 13F-domain-correctness
    standpoint. The only remaining checklist items are
    human-owner scope freeze and MVP4-01 pre-start condition
    resolution.
- 2026-05-11: **Human owner delegated the final three checklist
  items to the implementation engineer.** All three are resolved
  here:
  - Scope freeze: MVP4 is frozen at the 12-task list above.
    Future additions reopen this gate.
  - MVP4-01 pre-start conditions: all four resolved in the new
    "MVP4-01 Pre-Start Condition Resolutions" section above
    (precomputed `oracles_lens_signals` table; TL's JobRun spec
    accepted; scoring reads `holdings_13f`; ORM upsert).
  - MVP4-01 task file: filed at
    `docs/tasks/2026-05-11_13f-mvp4-01-score-schema-orm.md`,
    approved to start.
- 2026-05-11: **Product Owner re-review pass on the closed gate.**
  Approved. Four documentation-consistency fixes applied:
  - P1 #1: numbering note added in front of the task sequence
    making it explicit that MVP4-08/09/10/11 are parallel
    prerequisites despite their high numbers, with MVP4-11 called
    out as a hard blocker for MVP4-03.
  - P1 #2: added the Status block at the top of the document so
    future readers see at a glance that the gate is CLOSED and
    MVP4-01 is approved.
  - P1 #3: restored the missing `### D6. MVP3 Carryover Triage`
    header that was lost during the post-review revisions; the
    multiple references to "D6" elsewhere now have a matching
    section anchor.
  - P2 #4: added a fifth pre-start condition (row-level caveats +
    confidence-demotion reasons) and a matching fifth resolution.
    No schema change — `caution_flag_codes JSONB` plus a
    standardized `score_explanation.confidence_demotion_reasons`
    JSONB key cover the surface MVP4-05 needs.
  MVP4-01 task log will be updated in the same commit to mirror
  the new condition.

## Verification Results

- Documentation-only decision gate; Docker verification not required.
