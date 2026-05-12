# 13F MVP 5 End-to-End Review Prompts

Four reviewer prompts for the MVP 5 closing review. Each is
self-contained — drop the prompt into a fresh chat or hand it
to a human reviewer without needing the rest of this
repository's history. Verification baseline is in
`docs/tasks/2026-05-12_13f-mvp5-end-to-end-verification.md`.

Roles:

1. Staff Engineer — cross-task contract / correctness review.
2. Financial Data Product Reviewer (13F Domain SME) — scoring
   semantics on real-shape data + amendment-exclusion impact.
3. Product Owner — GA gate, Phase 3 sign-off, MVP6 candidate
   ordering.
4. Frontend / UX (optional) — MVP5-04 + MVP5-05 user surface
   confirmation.

---

## 1. Staff Engineer Prompt

You are the Staff Engineer conducting the MVP 5 cross-task
review for the ValuePilot 13F automation track. Six sub-tasks
have shipped on branch `docs/13f-automation-prd`:

- `MVP5-01` Wire behavior-derived manager_type into live
  scoring (`backend/app/services/oracles_lens/signal_weighted_score.py`
  + `manager_signal.py`; lazy per-manager profile cache).
- `MVP5-02` Exclude amendment-blocked holder contributions
  (`signal_weighted_score._contributions_for_stock` returns
  `(contributions, excluded)`; new `excluded_holder_count` /
  `excluded_holders` on score explanation).
- `MVP5-03` Phase 1 + 2 formula reconciliation
  (`backend/app/services/oracles_lens/formula_comparison.py` +
  new admin endpoint; dashboard action-magnitude
  normalization). Phase 3 / 4 explicitly deferred.
- `MVP5-04` Frontend trust + accessibility hardening
  (`frontend/lib/oraclesLens.js` label maps; ARIA dialog +
  focus trap on drilldown; admin Card empty-state copy +
  `overflow-x-auto`).
- `MVP5-05` Manager-type editor + priority Card deep link
  (new migration `20260512130000`; new audit table; PATCH +
  history endpoints; inline Dialog editor on managers
  section).
- `MVP5-06` Documentation + naming cleanup
  (`anti_crowding_factor` → `quality_agreement_factor`;
  CLAUDE.md write-conflict-handling note; plan §7.13.1
  caveat-tier resolution).

Verification baseline: 781 backend tests / 0 warnings;
alembic head `20260512130000`; frontend lint + 17
`oraclesLens.test.js` cases + production build all pass.

Review these cross-cutting concerns and return a verdict
plus pre-merge action items vs follow-up items:

1. **MVP5-01 cache correctness under failure.** The
   `_DerivedProfileCache` is populated lazily inside
   `compute_signal_weighted_scores`. If
   `_derive_manager_profile` raises mid-batch (e.g. DB
   timeout on the prev-quarter query), is the cache left in
   a half-populated state that would mislead subsequent
   per-stock loops in the same run? Confirm the
   None-sentinel path is hit only when the manager has zero
   eligible current-quarter holdings, not on transient
   failures.

2. **MVP5-02 partition + floor invariant.** The eligibility
   floor at `signal_weighted_score.py:285` was hardened from
   "raw contribution count" to "included contribution
   count." Walk the pre/post-MVP5-02 behavior on a stock
   with exactly `min_holders=3` raw holders, one of whom is
   amendment-pending. Pre-MVP5-02: stock scored, 3 included.
   Post-MVP5-02: stock dropped (2 < 3). Is that the correct
   semantics, or is there a use case for "score with what
   we have plus a low_confidence demotion"? PO already
   confirmed exclusion; verify the floor downgrade isn't a
   silent UX regression.

3. **MVP5-03 comparison utility math.** Open
   `formula_comparison.py:compute_formula_comparison` and
   confirm:
   - `legacy_rank` and `persisted_rank` are computed over
     each side's *full universe*, not just the intersection.
     The test pins this; reason it matches what a PO
     actually sees when sorting the dashboard.
   - The `MAGNITUDE_DIFF_25_PCT` cutoff is `> 0.25`, not
     `>= 0.25`. Inspect the threshold boundary test.
   - The `TOP10_RANK_SWAP` is symmetric (top10-in-legacy /
     below20-in-persisted OR the reverse), not one-sided.

4. **MVP5-05 audit-trail integrity.** Two specific tests
   call out subtle invariants:
   - `update_manager_type` writes the column and the audit
     row in **one transaction** so the audit log can't
     drift from the actual column value. Walk the service
     and confirm there is no early `session.commit()` that
     breaks atomicity.
   - The list endpoint's `(created_at DESC, id DESC)`
     ordering is required because `func.now()` resolves
     identically inside one transaction. Confirm the
     secondary sort is in place.

5. **MVP5-03 server-default flip is properly gated.**
   `read_oracles_lens` in the API endpoint still has
   `use_persisted_scores: bool = Query(False)`. Confirm no
   accidental flip landed in any of the MVP5 commits;
   `c7d525c` should NOT have touched that line. The flip
   is Phase 3 and must be a separate commit after PO
   sign-off.

6. **MVP5-04 frontend ARIA correctness.** Open
   `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` and
   confirm:
   - The slide-out `<Card>` has `role="dialog"`,
     `aria-modal="true"`, `aria-labelledby="oracles-lens-drilldown-title"`.
   - The title `<span>` has the matching `id`.
   - `openDrilldown` captures `document.activeElement`
     *before* changing state (correct order).
   - `useEffect` on `selectedStockId` focuses the close
     button after a `setTimeout(0)` (allows the DOM to
     mount).

7. **MVP5-06 rename completeness.** Grep the backend code
   for `anti_crowding` and confirm only inline comments
   referencing the rename audit trail remain. The
   persisted `component_name` string flip
   (`distinctive_anti_crowding_factor` →
   `distinctive_quality_agreement_factor`) is safe because
   `_replace_components` DELETEs all rows per signal before
   re-INSERTing — but confirm there is no query elsewhere
   in the codebase that filters by the old string.

8. **CLAUDE.md two-pattern rule alignment.** The new
   architecture note (MVP5-06) codifies "upsert for
   idempotent rewrites, IntegrityError translation for
   exclusive-lock guards." Spot-check that every existing
   `JobRun` write site uses the IntegrityError pattern and
   every score-row write site uses upsert. Any inconsistent
   site should be flagged.

Deliverable: APPROVE / APPROVE-WITH-FIXES / REJECT, plus a
pre-merge action list (must-land-before-Phase-3 closes) vs a
follow-up list (file as MVP6 backlog).

---

## 2. Financial Data Product Reviewer (13F Domain SME) Prompt

You are the 13F Domain SME reviewing the MVP 5 scoring
correctness. MVP 5 is the GA-readiness pass: behavior-derived
manager_type now drives the weight for un-typed managers
(MVP5-01); amendment-blocked holders are excluded from the
score (MVP5-02); the legacy in-memory formula's action
magnitudes are now aligned with the persisted constants
(MVP5-03 Phase 2); the comparison utility is live for the PO
to run before flipping the server default (MVP5-03 Phase 1).

Verification baseline:
`docs/tasks/2026-05-12_13f-mvp5-end-to-end-verification.md`.

Your goal: confirm the scoring stack is GA-ready for
investor-facing exposure.

Specifically:

1. **MVP5-01 behavior-derivation output on production data.**
   Run the persisted backfill on the current active quarter
   and inspect the resulting
   `oracles_lens_signals.score_explanation.manager_type_source_counts`
   distribution across stocks. Question for SME judgment:
   does the `admin / behavior / fallback_unknown` split match
   your expectation? If 80%+ of holders fall to
   `fallback_unknown` (because behavior derivation cannot
   classify), the conservative weight may be making rankings
   too conservative. If the split is healthy (most named
   managers resolve via behavior or admin), the rankings are
   real.

2. **MVP5-02 amendment-exclusion impact on rankings.** Pick
   the top 10 stocks under the new persisted scoring on the
   current active quarter. For each, query
   `score_explanation.excluded_holder_count`. How many
   top-10 stocks have at least one excluded holder? If many
   stocks are losing 30%+ of their holder weight to
   amendments, the V1 ranking may be biased toward stocks
   whose holders happen to have clean amendment status — a
   form of survivorship distortion. Flag if observed.

3. **MVP5-03 Phase 2 action-magnitude normalization
   sanity.** Pre-MVP5-03 the dashboard had
   `new=+0.10 / add=+0.20`; the persisted scorer has
   `new=+0.20 / add=+0.10`. SME #6 #1 argued a new position
   is the more decisive signal. Confirm this matches your
   domain reading: when a value investor opens a brand-new
   position vs adding 10% to an existing one, the new
   position is the stronger conviction signal (it survived
   the manager's full sizing process from zero). Or is there
   a contrary case where "add" is more decisive (e.g. a
   high-confidence top-up at a discount)? Pin one
   interpretation as canonical.

4. **MVP5-03 Phase 1 comparison report acceptance criteria.**
   The PO will run the comparison utility against
   production. The Phase 3 sign-off needs SME concurrence
   on what "acceptable divergence" means. Two flags exist:
   - `TOP10_RANK_SWAP` — top-10 under one path / below-20
     under the other.
   - `MAGNITUDE_DIFF_25_PCT` — 25%+ score-magnitude diff.

   Question: is `0` `TOP10_RANK_SWAP` the right bar? Or is
   `≤ 1` acceptable given that the persisted path is the
   intended canonical formula and minor reordering at the
   boundary is expected? Provide the SME-recommended
   threshold for both flags.

5. **PRE_2023_PRE_HISTORY_UNAVAILABLE tier resolution.**
   MVP5-06 records the SME-vs-SME decision (kept in
   `_MEDIUM_CAVEATS`). Walk plan §7.13.1 and confirm this is
   stable for GA. If you see a case where the medium tier
   under-claims a real product risk, flag it now — the
   purpose of recording it in the plan is so it doesn't get
   reopened at GA.

6. **MVP5-05 manager-type editor product semantics.** The
   editor commits an explicit admin classification per
   manager. Operationally, what is the threshold of evidence
   an admin should require before classifying? Should the
   inline Dialog's "Note (optional)" field be made required
   for non-`unknown` classifications? Flag as a FE follow-up
   if SME thinks free-form notes are too weak for the
   audit trail.

7. **Manager-signal-weight distribution under behavior
   derivation.** Run the persisted backfill on the current
   quarter. Inspect the distribution of
   `_HolderContribution.manager_weight` values across the
   universe. Expected: heavy weight on `1.00`
   (long_term_fundamental + value_concentrated) for
   admin-typed managers; a long tail on `0.60` (unknown
   fallback) and `0.30` (high_turnover via behavior).
   Confirm no weight value is wildly out of family
   (e.g. an inadvertent `1.20` from a bug).

Deliverable: per-item APPROVE / FLAG / BLOCK verdict.
BLOCKs require a pre-Phase-3 fix; FLAGs can be filed as MVP6
backlog. Also provide the SME-recommended
`TOP10_RANK_SWAP` / `MAGNITUDE_DIFF_25_PCT` thresholds for
Phase 3 sign-off.

---

## 3. Product Owner Prompt

You are the Product Owner reviewing MVP 5 closure for the
ValuePilot 13F automation track. Six sub-tasks shipped on
branch `docs/13f-automation-prd`; the verification baseline
is captured in
`docs/tasks/2026-05-12_13f-mvp5-end-to-end-verification.md`.

Your goal is to confirm that:

1. **All MVP5 sub-tasks closed against shipped code.**
   Walk each row of the MVP 5 Contract Checklist in the
   verification doc and open the cited commits. Particular
   attention:
   - MVP5-01 critical: does the behavior path actually run
     in production, or did the wiring miss a code path?
   - MVP5-02 critical: are amendment-blocked holders
     dropped, with the page-level caveat still visible?
   - MVP5-04: is the demotion-reason drilldown rendering
     the friendly label, or did the change accidentally
     hide the raw code from operators?
   - MVP5-05: can an admin actually go from the priority
     Card → editor → save in one flow?

2. **Scope-freeze tally is zero.** Verify by reading the
   five Track A2 / B / C / D / E deferral entries — each
   should still trace to an explicit backlog line. If any
   has silently slipped into MVP5 scope, reopen it as a
   defect.

3. **Phase 3 server-default flip decision.** This is the
   product judgment that gates GA. Inputs:
   - Run
     `GET /api/v1/admin/13f/oracles-lens/formula-comparison`
     against the current active production quarter.
   - Inspect `top10_swap_count` and `magnitude_diff_count`.
   - Decide whether the divergence is acceptable.

   Decision points to record explicitly:
   - **Acceptable `TOP10_RANK_SWAP` count for sign-off**: 0,
     ≤ 1, ≤ N. State the threshold.
   - **Acceptable `MAGNITUDE_DIFF_25_PCT` count**: similar.
   - **Sign-off statement**: "I, the PO, accept that the
     persisted formula is the canonical Oracle's Lens V1
     ranking surface and authorize the server-default
     flip." Or: "Reject — flag these specific divergences."

4. **Phase 4 retirement condition.** The
   `?persisted=0` debug flag exists for one observation
   cycle past Phase 3. Decide now:
   - How long is "one observation cycle"? One scoring run,
     one quarter, one calendar week?
   - What signal closes the observation? Zero
     `TOP10_RANK_SWAP` flags from the comparison utility
     re-run after the Phase 3 flip? PO judgment after
     reading a follow-up report?

5. **MVP5-05 editor scope is right for V1.** The inline
   Dialog with a free-text note is the V1 UX. Reviewer SME
   may flag the note as too weak for the audit trail (see
   SME prompt #6). Decide: keep optional note, or make it
   required for non-unknown classifications? Bulk
   classification UI is V2 — confirm that's still your
   call.

6. **Pre-MVP6 candidate ordering.** Four candidates surfaced
   in the verification doc Recommendation:
   - Track D Watchlist V1
   - Track A2 Quality + Valuation Overlay (Oracle's Lens
     M3)
   - Phase 4 `?persisted=0` retirement
   - Track C G1 / G9 admin gaps

   Rank these. State whether the next milestone gate
   (MVP6) opens immediately after Phase 3 closes, or
   whether you want a release window in between.

7. **GA messaging decision.** Once Phase 3 closes, the
   user-facing dashboard is operating on the canonical
   scoring formula. Is there a user-facing changelog or
   release note that needs to ship alongside? If yes,
   draft a one-paragraph note.

Deliverable: Phase 3 sign-off verdict (APPROVE /
APPROVE-WITH-CONDITIONS / REJECT), thresholds for the two
divergence flags, Phase 4 observation condition, MVP6
candidate ranking, and a recommendation on whether the
MVP6 decision gate opens this week or holds until after
Phase 3 ships.

---

## 4. Frontend / UX Reviewer Prompt (Optional)

You are the Frontend / UX reviewer for the MVP 5 user-facing
+ admin surface changes. MVP 5 introduces friendly
investor-facing labels for caveat codes (MVP5-04), the
amendment-exclusion drilldown panel (MVP5-04 + MVP5-02), the
slide-out ARIA + focus management (MVP5-04), and the inline
manager-type editor + deep link (MVP5-05).

Files in scope:

- `frontend/lib/oraclesLens.js` — `DEMOTION_REASON_LABELS`,
  `EXCLUSION_REASON_LABELS`, `normalizeOracleLensRows`
  extensions.
- `frontend/lib/oraclesLens.test.js` — 17 cases including
  the +2 new MVP5-04 cases.
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` — the
  slide-out drilldown with friendly labels + excluded
  holders section + ARIA dialog + focus management.
- `frontend/app/(dashboard)/admin/13f/page.tsx` — the
  inline manager-type editor Dialog + the priority Card
  deep-link anchor.

Review:

1. **Demotion-reason friendly labels.** Open the user
   dashboard, find a stock with `medium_confidence` and a
   `PARTIAL_COVERAGE` caveat, open the drilldown. Does the
   user read "Partial filing coverage" or
   `PARTIAL_COVERAGE`? Operator should still be able to
   reveal the raw code via the `<details>` element. Confirm
   the toggle works on touch + keyboard, not just mouse.

2. **Excluded-holders drilldown.** Find a stock with an
   amendment-pending holder. Open the drilldown. Confirm
   the "Holders excluded from score" section renders the
   manager name + an outline Badge with the friendly
   reason. Does the wording make it clear that this holder
   contributed to the caveat panel but NOT to the score?

3. **Slide-out ARIA + focus.** Tab into the ranking table,
   activate a row's "Review" button with Enter. Confirm:
   - Focus moves into the slide-out (to the close button).
   - Tab stays inside the slide-out (no escape to the
     background — though strict focus-trap is acceptable
     to defer if the current `role="dialog"` is enough
     for screenreaders to announce modality).
   - Close (Escape or close button) returns focus to the
     "Review" button on the originating row.

4. **Manager-type editor UX.** Open `/admin/13f`, scroll
   to the Managers section. Click the "Edit" button on
   any row. Confirm:
   - The current manager_type is pre-selected in the
     dropdown.
   - The dropdown options are ordered highest-signal-first
     (long_term_fundamental at the top).
   - Save with no change shows the "No change — manager_type
     stayed X" toast.
   - Save with a real change shows the "Manager type
     updated to Y" toast and the Unknown Manager Priority
     Card refreshes (test by changing an `unknown` manager
     to `long_term_fundamental` and watching the Card row
     disappear).

5. **Priority Card deep-link.** From the Unknown Manager
   Priority Card, click a manager name. Confirm:
   - The page scrolls to the corresponding row in the
     Managers section.
   - The row is visually anchored (`scroll-mt-6` is
     applied).
   - The Edit button is one click away from the landed
     position.

6. **Admin Card empty states.** Force the two empty states
   manually (e.g. drop persisted scores via DB, or admin
   classify all unknowns) and confirm:
   - State 1 reads: "No Oracle's Lens scores computed yet.
     Use the Historical Backfill section above to score a
     quarter, then return here to prioritize manager
     classification."
   - State 2 reads: "All contributing managers are typed
     for {quarter}. Signal weights are fully resolved —
     no classification debt for this quarter."

7. **`overflow-x-auto` on narrow viewports.** Resize the
   admin Priority Card area to ~700px wide. Confirm the
   table doesn't clip the worst-score-confidence column —
   the wrapper should scroll horizontally instead.

Deliverable: per-item APPROVE / RECOMMEND-CHANGE / BLOCK
with specific copy / spacing / interaction notes.
RECOMMEND-CHANGEs are MVP6 backlog candidates unless they
materially affect investor trust (in which case escalate to
the PO before Phase 3 closes).
