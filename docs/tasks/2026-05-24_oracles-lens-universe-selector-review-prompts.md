# Oracle's Lens universe selector — Three-role review prompts

Three reviewer prompts for the universe-selector PR. Each is
self-contained — drop the prompt into a fresh chat or hand it to a
human reviewer without needing this repo's history.

**Branch**: `claude/oracles-lens-universe-selector`
**Main commit**: title "Oracle's Lens universe selector — filter by V2 manager taxonomy"
**Builds on**: PR #94 (manager-taxonomy-v2) — already merged to main.

**Task docs**:
- `docs/tasks/2026-05-24_oracles-lens-universe-selector.md` — this PR
- `docs/tasks/2026-05-24_manager-taxonomy-v2.md` — V2 taxonomy (merged)

**Project guide**: `AGENTS.md`

**Why this PR exists**: PR #94 split the 82 superinvestors into a
V2 taxonomy (`style_primary`, `capital_structure`, `market_cap_focus`)
and confirmed at the data layer that Tiger Cubs were misclassified in
V1 — but the Oracle's Lens UI still showed the all-managers consensus.
This PR is the consumer-facing payoff: a chip-row + Custom dialog
lets a value investor restrict the Signal / Conviction / Distinctive
scores to "Deep Value Consensus", "Activists", "Small-cap Sleuths",
"Permanent Capital", or a custom style mix. Tiger Global's holdings
are now excluded from the Deep Value scores not just by weight, but
by being structurally removed from the contributions list before the
math happens.

Roles (priority order):

1. **Value Investor PO (HIGH)**. Validates the UX flow, default
   behavior, preset compositions, and whether the "X of N managers"
   subtitle is the right affordance.
2. **Backend Reviewer (MEDIUM)**. Reviews the allowlist threading
   through `_contributions_for_stock` / `_eligible_stock_ids` /
   `_holdings_for_period`, the resolver validation, the
   live-vs-persisted branching, and conviction/distinctive
   correctness via the pure-function assumption.
3. **Frontend Reviewer (MEDIUM)**. Reviews the chip-row /
   Custom-dialog component, URL state sync via `history.replaceState`,
   the default-preset redirect effect, and the buildOracleLensQueryParams
   contract.

---

## 1. Value Investor PO Review Prompt

You are a senior value investor reviewing the UX of Oracle's Lens
after PR #94 (manager taxonomy V2) merged. Your job in PR #94 was to
sign off on the *classification*; your job here is to sign off on the
*tool* — does the universe selector actually let you do the thing it
was built for?

**Read these files / pages in order:**

1. `docs/tasks/2026-05-24_oracles-lens-universe-selector.md` — the
   design doc with PO-confirmed decisions baked in.
2. **In a browser**: open `/13f/oracles-lens` on the dev environment.
   The page should immediately redirect to
   `?style_primary=value_deep,value_concentrated,quality_compounder`.
3. `frontend/components/oraclesLens/UniverseSelector.tsx` — the
   chip-row + Custom-dialog component.
4. `frontend/lib/oraclesLens.js` lines 86–195 — `UNIVERSE_PRESETS`
   (the single source of truth for preset → filter mapping).
5. `backend/app/services/oracles_lens/manager_universe.py` — the
   resolver that turns filter params into a manager_id set.

**Eight product questions you must answer.**

### Q1 — Default landing experience

Bare-URL visit triggers `history.replaceState` to the Deep Value
preset (5 preset chips → first one selected). The URL is now explicit
and shareable.

- Is the *invisible redirect* the right UX, or should the page paint
  with "all managers" briefly and let the user click Deep Value?
  Trade-off: explicit redirect = consistent default but loses the
  "here are the raw 13F numbers" landing screen.
- The preset names: `Deep Value`, `Activists`, `Small-cap Sleuths`,
  `Permanent Capital`, `All` — would you rename any to be more
  inviting / less jargon for a non-PO user?

### Q2 — "X of N managers" subtitle

The chip row's right side shows e.g. "**65 of 83 managers**" for
Deep Value, "**7 of 83 managers**" for Activists.

- Is this the right denominator (total confirmed superinvestor count)?
  Or do you want it framed as "of 50 V2-classified value-eligible"?
  Or as "65 managers contribute to scores" without a denominator at
  all?
- Should we add a tooltip explaining what filtered-out managers do
  (they don't disappear from the page — their holdings just don't
  contribute to scores)?

### Q3 — "Custom..." dialog

The Custom dialog shows only `style_primary` checkboxes — 8 boxes.
`capital_structure` and `market_cap_focus` are accessible only via
their preset chips (Permanent Capital, Small-cap Sleuths) and not
combinable with custom style mixes.

- Is that the right V1 cut? Or do you want the Custom dialog to
  expose all three dimensions so a power user can build e.g.
  "value_concentrated + permanent_capital + small-cap" universes?
- Defer-able trade: the deferred shape is 3 sections (Style, Capital,
  Market cap) of checkboxes, more rows in the dialog.

### Q4 — "Activists" preset returned 0 candidates

End-to-end smoke: clicking Activists with the default `min_holders=3`
returned 0 candidates (there are only 7 activist managers, and
they rarely overlap on the same target).

- Should we auto-lower `min_holders` when the universe size drops
  below some threshold (e.g. `min_holders = max(2, ceil(universe_size / 10))`)?
- Or should we surface a hint when the universe + min_holders combo
  produces 0 results: "Activists only have 7 managers; lower
  Min Holders to 2 to see candidates"?
- Or do you prefer "0 results is the truth, don't hide it"?

### Q5 — Preset chip composition — last call

Re-confirm the Deep Value preset:
`value_deep + value_concentrated + quality_compounder` (~65/83 managers).

Now that you can see the actual count, is this still the right cut?
Alternatives:
- Strict value: `value_deep + value_concentrated` (~50 managers).
  Trade: Polen / Fundsmith / Lindsell Train / AKO / Brave Warrior /
  Cantillon would drop out — and they ARE genuinely value-with-a-
  quality-tilt holders.
- Add activists: `+ activist` (~72 managers). Trade: gets you
  Pershing/Trian/etc., often picking value-style targets — but mixes
  long-term value style with event-driven activist style.

### Q6 — How does the universe-selector interact with the existing Filters?

The existing Filters card (period, min_holders, min_signal_score,
superinvestor_only, sort) sits below the chip row. They are
independent filters: chip row picks the manager universe; Filters
card picks which candidates from that universe are shown.

- Is the mental model clear, or does the visual hierarchy need work
  (e.g. group them into one bigger card)?

### Q7 — Watchlist 13F columns

Deferred (per task doc Scope Out): Watchlist's 13F columns
(conviction, Δ holders, distinctiveness) still reflect the
all-managers universe even after you pick Deep Value on Oracle's Lens.

- Is that the right call for V1, or do you want the Watchlist to
  follow the same global universe selector? My V1 argument: Watchlist
  is the per-stock thesis dashboard, and you want consistent numbers
  across reloads — Oracle's Lens is the browse-time tool where the
  universe lens is appropriate. Confirm or push back.

### Q8 — Live-recompute is the default

Every page visit (default = Deep Value preset) triggers a live
recompute, not a persisted-table read. Latency target: ~300-500ms.

- Did the dev-env page feel responsive enough? If you observed > 1s
  spinning on the chip row, flag it.
- Are you OK with the architectural choice that "All" gets the
  persisted fast path but every preset is recomputed live? Or should
  we ALSO persist preset scores (separate PR) for symmetry?

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-24_oracles-lens-universe-selector-review-results.md`
with sections matching Q1–Q8. For each call-out, give the file + line
or screenshot reference + your verdict (accept / change / discuss).

---

## 2. Backend Reviewer Prompt

You are a senior backend engineer reviewing the implementation
quality of the universe-filter plumbing. Focus on correctness of the
allowlist threading, the live-vs-persisted branching, and the
test adequacy.

**Read these files in order:**

1. `docs/tasks/2026-05-24_oracles-lens-universe-selector.md`.
2. `backend/app/services/oracles_lens/manager_universe.py` — the new
   resolver. 80 lines, single function.
3. `backend/app/services/oracles_lens/signal_weighted_score.py` —
   look at `_eligible_stock_ids` (now accepts `manager_id_allowlist`)
   and `_contributions_for_stock` (same). Verify the SQL filter
   placement is correct and that existing call sites still pass
   `None` (no behavior change).
4. `backend/app/services/oracles_lens/dashboard.py` — find the new
   `manager_id_allowlist` parameter on `build_oracles_lens_dashboard`,
   the propagation into `_holdings_for_period`, and the
   "skip persisted overlay when filter is set" branch.
5. `backend/app/api/v1/endpoints/oracles_lens.py` — the endpoint's
   three new query params, the `_parse_csv` helper, and the
   `universe_metadata` assembly.
6. `backend/tests/unit/test_13f_oracles_lens_universe_filter.py` —
   13 new tests covering the resolver, the filter threading, the
   conviction/distinctive auto-follow, the hero outcome, and three
   endpoint contract tests.

**Eight code-quality questions you must answer.**

### B1 — Allowlist threading completeness

`_contributions_for_stock` and `_eligible_stock_ids` accept the
allowlist; `_top_n_stock_ids_per_manager` does NOT. The reasoning
(per task doc): "is stock X in manager M's top-10" is universe-
agnostic — filtering doesn't change a manager's own top-N ordering.

- Verify this reasoning. Could there be a downstream calculation
  that uses `top_n_by_manager` in a way that breaks under the filter?

### B2 — The "skip persisted overlay" branch

In `dashboard.py`:
```python
apply_persisted = use_persisted_scores and manager_id_allowlist is None
```

- Is "any filter set" the right trigger for forcing live-recompute?
  Or should we be more granular (e.g. only force live when the
  resulting universe size < some threshold)?
- The endpoint passes `use_persisted_scores=True` by default; this
  branch silently downgrades to live-recompute when a filter is set.
  Is "silent downgrade" the right contract, or should the response
  carry a flag indicating the score path used?

### B3 — Conviction / Distinctive correctness

The task doc claims these auto-follow because they're pure functions
of `contributions`. Verify in
`backend/app/services/oracles_lens/conviction_score.py` and
`backend/app/services/oracles_lens/distinctive_consensus.py` that
NEITHER function reads from the DB or holds external state — they
take `contributions` (or `signal_weighted_score, contributions`) and
return values.

- Confirm or flag.
- The hero test `test_conviction_and_distinctive_follow_the_allowlist`
  asserts `full.total != filtered.total` (they differ). Is that the
  strongest assertion possible? Could a future tuning of conviction
  weights make full == filtered by coincidence?

### B4 — The endpoint's `universe` shape

```json
"universe": {
  "filtered_manager_count": 65,
  "total_manager_count": 83,
  "applied_filters": { "style_primary": [...], ... }
}
```

When no filter is set, the endpoint still attaches `universe` with
`filtered_manager_count == total_manager_count` (per the
"all-managers" semantics) and empty filter arrays. The FE test
`test_endpoint_empty_filters_omit_universe_to_signal_persisted_path`
tolerates either shape.

- Is "always emit universe" cleaner than "emit only when filter set"?
  The latter would be a stronger signal of which path the server
  took, but breaks the "FE always reads the same shape" contract.

### B5 — Resolver validation

`resolve_manager_id_allowlist` raises `ValueError` on unknown values.
The endpoint catches `ValueError` and returns HTTP 400. Test
`test_endpoint_rejects_unknown_style_primary` pins this.

- The endpoint wraps the resolver call in its own try/except, AND
  the `build_oracles_lens_dashboard` call below in another try/except
  (both for ValueError → 400). Acceptable, or is it a pattern smell?

### B6 — Live-recompute performance assumption

Task doc estimates 300-500ms per request when filter is set. End-to-
end smoke showed the page felt responsive (<1s subjectively).

- Is there a smoke-test or benchmark we should add to lock this in
  (e.g. `pytest --benchmark` over 50 stocks × 50 managers)?
- The persisted table writes only happen during backfill — no
  write-amplification from the filter path. Confirm by reading
  `compute_signal_weighted_scores` (the backfill entry point);
  ensure my filter path never reaches `_upsert_signal`.

### B7 — Backward compat for existing call sites

The new optional parameter `manager_id_allowlist: set[int] | None =
None` lands on `build_oracles_lens_dashboard`, `_holdings_for_period`,
`_contributions_for_stock`, `_eligible_stock_ids`.

- `grep -rn "build_oracles_lens_dashboard" backend/` — every existing
  caller still passes the same args; the new parameter is purely
  additive. Confirm.
- The function-signature change to `_holdings_for_period` could
  affect other callers. Verify by searching for callers and
  confirming none break.

### B8 — Pre-existing test isolation issue (`_clear_13f`)

`docs/BACKLOG.md` documents that the dev DB has accumulated rows
that break some `_clear_13f` helpers in unrelated test files. This
PR does NOT touch those tests; verify by running
`pytest -q tests/unit/test_13f_oracles_lens_universe_filter.py
 tests/unit/test_oracles_lens.py
 tests/unit/test_oracles_lens_score_job.py` — all 3 files should
pass.

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-24_oracles-lens-universe-selector-review-results.md`
with sections matching B1–B8. Block / non-block + suggested fix per
finding.

---

## 3. Frontend Reviewer Prompt

You are a senior frontend engineer reviewing the chip-row + Custom
dialog implementation, the URL state sync, and the default-preset
redirect.

**Read these files in order:**

1. `docs/tasks/2026-05-24_oracles-lens-universe-selector.md`.
2. `frontend/components/oraclesLens/UniverseSelector.tsx` — the new
   component. ~200 lines.
3. `frontend/lib/oraclesLens.js` lines 60–195 — `buildOracleLensQueryParams`
   (extended to serialize the three new filter arrays),
   `UNIVERSE_PRESETS`, `presetByKey`, `matchPreset`,
   `parseUniverseFromSearchParams`, `urlHasUniverseFilter`.
4. `frontend/lib/oraclesLensUniverse.test.js` — 16 new unit tests.
5. `frontend/app/(dashboard)/13f/oracles-lens/page.tsx` —
   the mount-time `urlHasUniverseFilter` check that triggers the
   `history.replaceState` redirect, the `handleSelectUniverse`
   callback (writes URL on every chip click), and the
   `UniverseSelector` mount point above the existing Filters card.

**Seven UI / code-quality questions.**

### F1 — `history.replaceState` instead of Next.js router

The page uses `window.history.replaceState` to mutate the URL on
chip clicks and on the default-preset redirect, NOT Next.js's
`useRouter().replace`. The original page's `?persisted=0` debug flag
followed the same pattern.

- Is this the right call? Trade: `replaceState` doesn't trigger Next's
  route re-render (which we don't want — we manage state in the
  component) but it also doesn't update Next's `useSearchParams()`
  cache. Anything that reads `useSearchParams` mid-render would see
  stale data.
- Should we use `useRouter().replace(newUrl, { scroll: false })` for
  consistency with the rest of the app?

### F2 — Default-preset redirect on bare URL

Mount-time effect: if `urlHasUniverseFilter(params)` is false,
`history.replaceState` writes the Deep Value defaults. This means
visiting a bare URL silently rewrites the address bar.

- Is the silent rewrite OK, or should we leave the URL bare and let
  the chip row visually indicate Deep Value is selected?
- Edge case: what if the user lands from a deep link that has
  `?period=2025-Q3` but no universe params? The current code writes
  `?period=2025-Q3&style_primary=...` — verifies this is preserved.

### F3 — `matchPreset` JSON.stringify trick

```js
JSON.stringify(presetNorm.stylePrimary) === JSON.stringify(target.stylePrimary)
```

Uses sorted arrays + JSON.stringify for deep equality. It works but
is a code smell. A `arraysEqualUnordered` helper would be clearer.

### F4 — Tooltip via `title` HTML attribute

Chip buttons use `title={preset.description}` for the hover tooltip
(e.g. "Value + quality compounder consensus..."). Native browser
tooltip — no aria-describedby.

- For accessibility: should we use a tooltip component (Radix
  Tooltip) that announces to screen readers, or is `title` fine for
  this admin-tier feature?

### F5 — Custom dialog only edits `style_primary`

The dialog has 8 checkboxes for style_primary; clicking Apply sets
`capital_structure` and `market_cap_focus` to empty. This means
opening the Custom dialog after clicking "Permanent Capital"
silently discards the capital_structure filter.

- Is that the right V1 cut (task doc Scope Out) or should the dialog
  preserve cross-dimensional state? Trade-off captured in the task
  doc.

### F6 — Loading state on chip row

The chip row shows `<Loader2 className="animate-spin" />` when
`isLoading=true` (dashboardQuery.isFetching). The chip buttons are
disabled during loading.

- Is the disabled-during-loading right? Or do we want optimistic
  click-then-discard behavior? Today every click triggers a fresh
  query that takes 300-500ms; back-to-back clicks should arguably
  cancel the in-flight one.

### F7 — Test coverage adequacy

16 new tests in `lib/oraclesLensUniverse.test.js`:
preset → URL params, URL parse round-trip, matchPreset (deep_value /
custom / all), urlHasUniverseFilter. No tests for the
UniverseSelector component itself (no jsdom in the existing
`node --test lib/*.test.js` setup).

- Is "lib-only unit tests + browser smoke" enough, or should we add
  a component-level test (React Testing Library, etc.)? Current
  project doesn't have a component-test harness.

**Deliverable.** Write a markdown review report to
`docs/tasks/2026-05-24_oracles-lens-universe-selector-review-results.md`
with sections matching F1–F7. Severity (blocker / nit) + suggested
fix per finding.

---

## Notes for all three reviewers

- The new universe selector is opt-in for filtering but opt-out for
  the default landing: bare URL redirects to Deep Value preset on
  first paint.
- The persisted `oracles_lens_signals` table is still the source of
  truth for the "All" universe. Preset universes are recomputed live;
  no schema change, no migration in this PR.
- Run, at minimum:
  ```
  docker compose exec -T api pytest -q tests/unit/test_13f_oracles_lens_universe_filter.py
  docker compose exec -T web sh -lc 'node --test lib/oraclesLensUniverse.test.js'
  ```
  Both should be green.
- Full canonical CI (per AGENTS.md): same as PR #94.
