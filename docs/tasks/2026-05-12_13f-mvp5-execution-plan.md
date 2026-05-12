# 13F MVP 5 Execution Plan

Compiled 2026-05-12 from the Post-MVP4 roadmap survey
(`docs/tasks/2026-05-12_post-mvp4-roadmap.md`) and the PO MVP5
sequencing decision (same date).

This is an **execution plan**, not a survey. Every item listed
here is in scope for MVP 5; every item from the roadmap that is
*not* listed here is explicitly out of scope.

## Goal

Ship Oracle's Lens V1 GA-ready: scoring correctness fixes
(MVP5-01 / 02), formula reconciliation and persisted-default
cutover (MVP5-03), user-trust hardening (MVP5-04), the admin
classification loop closure (MVP5-05), and a docs/naming pass
(MVP5-06), gated by an end-to-end GA readiness review
(MVP5-07).

## Non-Goals (do not start until MVP5-07 closes)

- **Track A2** Oracle's Lens Milestone 3 (quality / valuation
  overlay). Mixing a new signal layer with formula reconciliation
  is undebuggable.
- **Track A3 / A4 / A5 / A6** later Oracle's Lens milestones and
  V2 deferreds.
- **Track B** pre-2023 historical backfill productionization.
  PO: no investor demand signal; stays curated dry-run.
- **Track C** admin G1 (email alerts) and G9 (external ticket
  creation). Slack / Discord are sufficient unless production
  observation says otherwise.
- **Track D** Watchlist V1, Value Line ingestion, F-Score
  formalization. Revisit Watchlist after MVP5-03 lands.
- **Track E** engineering-debt items (`_HolderContribution` data
  loader extraction, generic score-input sanity guards,
  `score_version` admin query param) — stay deferred until their
  triggering condition appears.

## Task Sequence

GA-blocking correctness (must finish before formula
reconciliation can run cleanly):

1. `MVP5-01` Wire behavior-derived manager_type into live
   scoring path.
2. `MVP5-02` Exclude amendment-blocked holder contributions
   (backend-only; UI surface lands in MVP5-04).

Formula reconciliation cutover:

3. `MVP5-03` Reconcile Oracle's Lens persisted vs legacy
   formula; flip API server default; define `?persisted=0`
   retirement condition.

User-trust hardening + admin loop closure:

4. `MVP5-04` Frontend trust + accessibility hardening.
5. `MVP5-05` Manager-type editor on manager detail page.

Documentation:

6. `MVP5-06` Documentation + naming cleanup.

Closing gate:

7. `MVP5-07` MVP 5 end-to-end GA readiness review.

## Per-Task Scope

### MVP5-01 — Wire Behavior-Derived Manager Type Into Live Scoring

**Why:** `resolve_manager_type(manager, derived_profile=None)` at
`signal_weighted_score.py:510` hardcodes the behavior tier to
None. The MVP4-11 three-tier precedence (admin → behavior →
fallback_unknown) collapses to two tiers in production. Real
impact: long-term-fundamental managers who haven't been admin-typed
get the 0.60 unknown fallback instead of 1.00 weight;
high-turnover managers get 0.60 instead of 0.30. Source:
SME #6 #6 in `docs/13f/mvp4-reviews.md`.

**Acceptance criteria:**

- `resolve_manager_type` receives a non-None
  `derived_profile` in the live scoring path when admin
  `manager_type` is None or `unknown`.
- Admin non-unknown `manager_type` still wins (regression
  protection — already covered by MVP4-11 tests).
- Admin `unknown` correctly falls back to the behavior-derived
  profile, not to `fallback_unknown`.
- When neither admin nor behavior produces a typed result, the
  fallback is `unknown=0.60` with `manager_type_source =
  "fallback_unknown"`.
- Tests cover all three resolution paths (long-term-fundamental
  via behavior, high-turnover via behavior, no-data
  fallback_unknown) end-to-end through
  `compute_signal_weighted_scores`.
- `score_explanation` exposes `manager_type_source` per holder so
  the admin priority queue (MVP4-07b) can be interpreted.
- **Fixture audit:** all existing scoring test fixtures whose
  managers have no admin `manager_type` set (or have it set to
  `unknown`) must either be updated to set an explicit admin
  type or have their expected score values re-baselined to
  reflect the derived profile output. This is mechanical but
  must be exhaustive; the regression risk is silent score
  drift in unrelated test files.

**Out of scope:**

- New behavior-derivation heuristics. Use the existing
  `derive_manager_signal_profile` as-is; tuning is V2.
- Admin UI changes (no new admin override path).

**Dependencies:** none — first ticket of MVP5.

---

### MVP5-02 — Exclude Amendment-Blocked Holder Contributions

**Why:** Class A caveat propagation (MVP4-05) keeps amendment-blocked
holders in the signal-weighted aggregate and only demotes
`score_confidence`. PO + SME consensus: when
`AMENDMENTS_PENDING` or `AMENDMENT_FAILED` is set on the holder's
filing, the snapshot itself is potentially wrong (positions may
change materially when the amendment lands), and the contribution
should be excluded from the score, not just caveat-flagged.

**Scope (Class B narrow):**

- Backend-only ticket.
- Excludes only `AMENDMENTS_PENDING` and `AMENDMENT_FAILED`.
- **Verify first** whether the `cusip_mapping_status == "linked"`
  eligibility filter already excludes the unresolved-CUSIP case;
  if yes, no extra work needed. If not, document but defer the
  exclusion to MVP6.

**Acceptance criteria:**

- A holder whose filing has `AMENDMENTS_PENDING` is omitted from
  the score-side aggregate (`signal_weighted_consensus_score`,
  `conviction_score`, `distinctive_consensus_score`).
- A holder whose filing has `AMENDMENT_FAILED` is omitted from
  the score-side aggregate.
- The API response includes:
  - `excluded_holder_count: int` on the per-stock signal payload.
  - `excluded_holders: list[{manager_id, manager_canonical_name,
    exclusion_reason}]` so MVP5-04 can render the drilldown
    without a new query.
  - `exclusion_reason` is a stable string constant; pick from
    `{"AMENDMENT_PENDING_EXCLUDED", "AMENDMENT_FAILED_EXCLUDED"}`.
- Excluded holders still appear in `caution_flags` so the
  page-level caveat panel keeps the existing signal.
- Tests pin: an `AMENDMENTS_PENDING` holder is missing from the
  aggregate; the `excluded_holder_count` matches; same stock with
  3 holders (1 amendment-pending + 2 clean) still scores with
  the 2 clean holders only.

**Out of scope (deferred to V2):**

- NT (`coverage_type=notice_reported_elsewhere`) exclusion.
- Combination report exclusion (`PARTIAL_COVERAGE`).
- Confidential treatment exclusion.
- UI rendering of the excluded-holders drilldown — that lands in
  MVP5-04.

**Dependencies:** none — can run in parallel with MVP5-01 but the
test fixtures must be re-baselined for MVP5-01 first if they
overlap.

---

### MVP5-03 — Reconcile Oracle's Lens Persisted vs Legacy Formula

**Why:** Three reviewer threads converged on the same fix
(TL #1 #5, PO #3 #3 / PO #4 #3, SME #6 #1): the dashboard
in-memory path uses `min(weight*4, 1.0)` base + inverted action
magnitudes (`new=+0.10, add=+0.20`) while the persisted MVP4-03
path uses raw `portfolio_weight` + correct action magnitudes
(`new=+0.20, add=+0.10`). The frontend defaults to persisted, but
the backend API server default is still `False` — direct API
consumers hit the legacy formula. The `?persisted=0` debug flag
is a one-release escape hatch with no defined retirement
condition.

**Phased acceptance criteria:**

Phase 1 — comparison utility:

- New script / admin endpoint (whichever is cheaper) computes the
  signal-weighted ranking under both formulas for the latest
  scored quarter and outputs a side-by-side report.
- Report shows top-50 ranking under each path with a delta
  column.
- "Material discrepancy" is defined as: a stock appearing in the
  top 10 under one path and below position 20 under the other,
  or a >25% score-magnitude difference for the same stock.
- Run the report at least once against the current active
  quarter; archive the output to
  `docs/tasks/YYYY-MM-DD_mvp5-03-comparison-report.md`.

Phase 2 — action-magnitude normalization:

- Update the dashboard in-memory `_position_signal_weight` so its
  `new` / `add` magnitudes match the persisted constants
  (`new=+0.20, add=+0.10`).
- Document the inversion in the task log so future archaeology
  finds the rationale (SME #6 #1: a new position is a more
  decisive signal than adding to an existing one).

Phase 3 — PO sign-off + server default flip:

- PO reviews the comparison report. Sign-off is **mandatory**;
  it cannot be automated.
- After sign-off: flip
  `/api/v1/oracles-lens?use_persisted_scores` server default
  from `False` to `True` (FastAPI `Query` default change).
- The frontend already defaults to true (MVP4-07a); this only
  affects direct API consumers (curl / Postman / future API
  clients).

Phase 4 — `?persisted=0` retirement:

- Define retirement condition in the task log: "after one full
  scoring cycle under the new default with no material
  discrepancy observed."
- Retirement itself does NOT happen in MVP5-03 — it's filed as
  a follow-up ticket to land after the observation period.

**Out of scope:**

- Deleting the legacy in-memory path. Stays available behind
  `?persisted=0` for the observation period.

**Dependencies:** **MVP5-01 must be deployed first.** The
comparison utility must compare persisted scores *post*
MVP5-01 manager-weight correction, otherwise the ranking diff
mixes "behavior path enabled" with "formula difference" and
becomes uninterpretable.

---

### MVP5-04 — Frontend Trust + Accessibility Hardening

**Why:** FE #8 #2/#3/#5/#7 + the MVP5-02 backend drilldown
contract. Polish-tier items, but the demotion-reason label
mapping is the most consequential because it directly affects
how investors interpret confidence demotion.

**Acceptance criteria:**

- `DEMOTION_REASON_LABELS` constant added to
  `frontend/lib/oraclesLens.js` mapping every rule_code in
  `_LOW_CAVEATS ∪ _MEDIUM_CAVEATS ∪ {CONFIDENTIAL_TREATMENT}` to a
  human-readable string. Unmapped codes fall back to the raw
  string in `<details>` with `font-mono`.
- Drilldown panel surfaces every active caveat, not just the
  tier-winning ones. (MVP4 review pass already fixed the backend
  side in `_build_score_explanation`; this confirms the UI
  renders the full set.)
- Demoted-to underscores replaced with spaces:
  `medium_confidence` → "medium confidence".
- MVP5-02 `excluded_holders` rendered in the holder drilldown
  with the exclusion reason as a tag.
- Empty states on the admin Unknown Manager Priority Card:
  - State 1 ("no persisted scores yet") includes a directional
    hint pointing at the historical backfill section.
  - State 2 ("no unknowns contribute") reframed as a positive
    all-clear with the quarter label injected.
- Slide-out drilldown panel: `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby` pointing at the title, focus moves to the
  close button on open, restores focus to the triggering row
  button on close.
- Admin priority `<Table>` wrapped in `<div className="overflow-x-auto">`
  so narrow viewports don't clip the worst-confidence column.
- Persisted-mode retirement comment added inline in
  `oracles-lens/page.tsx`: when `?persisted=0` retires, delete
  the `useEffect` reading `window.location.search` and inline
  `usePersistedScores=true` in `buildOracleLensQueryParams`.

**Out of scope:**

- Persisted badge label rename. "Persisted" stays for V1; renaming
  belongs in a UX consultation, not a unilateral PR.
- New visualization (Track A3 Visual Radar is the bubble chart
  ticket).

**Dependencies:** MVP5-02 backend ships first so the
`excluded_holders` field is available for rendering.

---

### MVP5-05 — Manager Type Editor

**Why:** The MVP4-07b admin priority Card shows which managers
to classify but provides no path to do it. PO + Frontend
reviewers agreed: no stub routes, no fake CTAs — wait until the
real editor exists, then deep-link to it.

**Acceptance criteria:**

- New page or panel at `/admin/managers/{id}` (or a modal on the
  existing managers section, whichever fits the admin
  information architecture better — engineer's call).
- Renders the canonical 8-value taxonomy as a dropdown:
  `long_term_fundamental`, `value_concentrated`, `activist`,
  `quant`, `high_turnover`, `index_like`, `multi_strategy`,
  `unknown`.
- Current `manager_type` value is pre-selected.
- Save action writes `InstitutionManager.manager_type` and
  records an audit event with the reviewer + timestamp +
  optional note (reuse existing audit pattern from CIK review
  if available).
- MVP4-07b admin priority Card rows now deep-link to the editor
  via the manager name.
- Tests cover: open the editor, change the value, save, verify
  the DB row and audit trail, verify the priority queue updates
  on next refresh.

**Out of scope:**

- Bulk classification UI. One-at-a-time per V1.
- Behavior-derived `manager_type` admin override workflow.
- Wider admin manager management redesign.

**Dependencies:** none. Independent of MVP5-01/02/03 but tracks
the same MVP5 milestone.

---

### MVP5-06 — Documentation + Naming Cleanup

**Why:** Accumulated SME / TL flags that don't justify
standalone tickets but should not be lost.

**Acceptance criteria:**

- Rename `anti_crowding_factor` to `quality_agreement_factor`
  in §7.11 distinctive-consensus implementation, doc strings,
  any dashboard tooltip references, and the variable name in
  `distinctive_consensus.py`. Naming-only; formula unchanged.
- Add a `CLAUDE.md` architecture note codifying the two-pattern
  rule: "ORM upsert for idempotent rewrites
  (e.g. `oracles_lens_signals`); IntegrityError translation for
  exclusive-lock guards (e.g. JobRun lock_key races)."
- Add a short note in the Oracle's Lens scoring docs (whichever
  is the authoritative location) recording the SME-vs-SME tier
  resolution for `PRE_2023_PRE_HISTORY_UNAVAILABLE`: it stays
  in `_MEDIUM_CAVEATS` because pre-2023 history unavailability
  degrades the cross-quarter delta but the current-quarter
  snapshot remains valid. Cite SME #6 #4 reasoning.
- Add a ratio-design note at the `compute_portfolio_weight` site
  is already done in the MVP4 review-fix commit (`ab7afeb`); no
  re-do.

**Out of scope:**

- Larger doc reorganization. Surgical edits only.

**Dependencies:** none — can land any time.

---

### MVP5-07 — MVP 5 End-to-End GA Readiness Review

**Why:** Mirrors the MVP3 / MVP4 end-to-end verification pattern.
This is the **release gate** — Oracle's Lens V1 only goes
investor-facing GA after this passes.

**Verification commands** (same shape as MVP3 / MVP4):

- `docker compose exec api alembic upgrade head`
- `docker compose exec api pytest -q tests/unit/test_13f_mvp5_*.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run build`

**Review roles** (four prompts, mirror MVP4 review-prompts pattern):

- **Staff Engineer** — cross-task contract review, especially
  the MVP5-01 / 02 / 03 interaction (does the comparison report
  actually compare apples to apples post-correction?), the
  Class B exclusion correctness, the `excluded_holder_count`
  surface contract.
- **Financial Data Product Reviewer** (Domain SME) — formula
  correctness post-action-magnitude normalization, behavior
  path output sanity-check on a real production quarter (does
  the manager-weight distribution match SME expectations?),
  amendment-exclusion impact on ranking (are too many holders
  being excluded?).
- **Product Owner** — final GA sign-off, comparison-report
  acceptance, retirement-condition observation period decision,
  approval to flip the API server default.
- **Frontend / UX (optional)** — confirm the MVP5-04 hardening
  items land cleanly; check screenreader narration of the new
  caveat labels.

**Acceptance criteria:**

- All MVP5-01 through MVP5-06 tickets closed with passing tests.
- Full backend pytest suite passes with no new warnings vs the
  MVP4 baseline (755 + new MVP5 tests).
- Frontend lint + build + node tests pass.
- Comparison report archived and PO-signed.
- Server default flipped to `use_persisted_scores=true`.
- `?persisted=0` retirement condition documented; retirement
  ticket filed for the post-observation window.
- Scope-freeze tally for MVP5 is **zero new debt**.
- Deferred items in `docs/tasks/2026-05-12_post-mvp4-roadmap.md`
  remain deferred unless explicitly reopened.

**Out of scope:**

- Track A2 / A3 / A4 / A5 / B / C / D / E items — those are
  post-GA milestones.

## Sequencing and Parallelism

Strict ordering:

- MVP5-01 → MVP5-03 (MVP5-03 comparison utility requires
  MVP5-01 behavior-path correction landed).
- MVP5-02 → MVP5-04 (MVP5-04 renders the `excluded_holders`
  field that MVP5-02 introduces).
- MVP5-01 / 02 / 03 / 04 / 05 / 06 → MVP5-07 (closing gate).

Safe parallelism:

- MVP5-01 and MVP5-02 are independent (different files / different
  behavior).
- MVP5-05 (manager-type editor) is independent of the scoring
  fixes; can run in parallel.
- MVP5-06 (docs / naming) can run any time.

## Watchlist Revisit Trigger

If MVP5-03 lands cleanly (comparison report passes PO sign-off,
server default flipped without ranking regression), open the
**Watchlist V1 decision gate** at that point. Watchlist work can
then run in parallel with MVP5-04 / 05 / 06 since the surfaces
are independent and the engineering teams need not overlap.

If MVP5-03 surfaces a discrepancy requiring rework, hold
Watchlist until MVP5-03 closes.

## Review Pattern

Each MVP5 sub-task follows the same TDD + verification cadence
as MVP3 / MVP4:

1. Task log filed under `docs/tasks/YYYY-MM-DD_mvp5-NN_*.md`
   before code changes.
2. Tests-first.
3. Docker-only verification commands.
4. Commit with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`.
5. Per-task verification log appended to the task file.

MVP5-07 closing review uses dedicated review prompts (modeled
after `docs/tasks/2026-05-12_13f-mvp4-review-prompts.md`).
