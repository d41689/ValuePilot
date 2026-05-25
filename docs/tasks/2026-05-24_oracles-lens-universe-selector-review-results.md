# Oracle's Lens universe selector — Review results

**Branch**: `claude/oracles-lens-universe-selector`
**Review date**: 2026-05-24
**Reviewers**: Claude (three-role sweep — Value Investor PO, Backend, Frontend)

## Re-review update - 2026-05-24 after `e2b7db0`

**Current status: approved.**

The previous provenance finding is resolved. Filtered universe mode still uses
the canonical live recompute and marks per-item `score_source` as
`live_filtered`, but `_apply_live_filtered_scores()` now returns `0` for the
second tuple value so `coverage.persisted_score_count` remains reserved for
rows actually read from `oracles_lens_signals`. That keeps the frontend's
"persisted" attribution honest.

No new blocking or medium-severity findings found in this pass.

Verification run:

```bash
docker compose exec -T api pytest -q \
  tests/unit/test_13f_oracles_lens_universe_filter.py \
  tests/unit/test_oracles_lens.py \
  tests/unit/test_oracles_lens_score_job.py
docker compose exec -T api pytest -q tests/unit/test_13f_mvp4_dashboard_persisted_scores.py
docker compose exec -T web sh -lc 'node --test lib/oraclesLensUniverse.test.js'
```

- Backend Oracle's Lens universe / score tests: **33 passed in 10.81s**
- Backend persisted dashboard attribution tests: **6 passed in 1.92s**
- Frontend universe tests: **16 passed**

---

## Re-review update - 2026-05-24 after `86d4acd`

**Current status: changes requested.**

The two original findings are addressed:

- **Resolved P0**: filtered universe mode now overlays dashboard rows with a
  live canonical recompute via `_apply_live_filtered_scores()` instead of
  leaving the legacy `_stock_payload` formula in place.
- **Resolved P1**: `resolve_manager_id_allowlist()` now filters to confirmed,
  CIK-backed managers and honors `superinvestor_only`, so the "X of N managers"
  numerator is aligned with score-eligible managers.

Verification run:

```bash
docker compose exec -T api pytest -q \
  tests/unit/test_13f_oracles_lens_universe_filter.py \
  tests/unit/test_oracles_lens.py \
  tests/unit/test_oracles_lens_score_job.py
docker compose exec -T web sh -lc 'node --test lib/oraclesLensUniverse.test.js'
```

- Backend: **32 passed in 10.46s**
- Frontend: **16 passed**

### New P1 - filtered live recompute is reported as persisted coverage

**Severity:** medium

**Files:**
- `backend/app/services/oracles_lens/dashboard.py:216–275`
- `backend/app/services/oracles_lens/dashboard.py:293–397`
- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx:531–540`

Filtered mode now correctly sets each item to `score_source = "live_filtered"`,
but `_apply_live_filtered_scores()` returns `len(out)` as the second tuple
value. `build_oracles_lens_dashboard()` stores that value in
`coverage["persisted_score_count"]`. The frontend treats any positive
`persisted_score_count` as persisted-table coverage and renders:

> `{count} persisted` / `items use the canonical Oracle's Lens score table`

For a Deep Value / Activists / Custom request, those rows are not persisted
`oracles_lens_signals` rows; they are live canonical recomputes over a filtered
manager universe. The math is now correct, but the operator-facing provenance is
wrong, and it reintroduces ambiguity around live-vs-persisted mode.

**Suggested fix:** keep `persisted_score_count` strictly for rows read from
`oracles_lens_signals` (return `0` from the live-filtered tuple or split the
variable before writing coverage). If the UI needs observability for filtered
mode, add a separate field such as `live_filtered_score_count` or
`score_source_summary` and render copy that says "live filtered canonical
recompute" rather than "persisted".

---

Reviewed commits:
- `3820fe2` — Oracle's Lens universe selector — filter by V2 manager taxonomy
- `b6a41d5` — Add three-role review prompts for oracles-lens-universe-selector PR
- `3de1c86` — Fix CI: attach universe metadata in the empty-period early-return path

Verification run:
```bash
docker compose exec -T api pytest -q \
  tests/unit/test_13f_oracles_lens_universe_filter.py \
  tests/unit/test_oracles_lens.py \
  tests/unit/test_oracles_lens_score_job.py
docker compose exec -T web sh -lc 'node --test lib/oraclesLensUniverse.test.js'
```
- Backend: **28 passed in 4.17s**
- Frontend: **16 passed**

Browser smoke (dev env):
- Bare URL `http://localhost:3001/13f/oracles-lens` → immediately rewrites to
  `?style_primary=value_deep%2Cvalue_concentrated%2Cquality_compounder`
- Deep Value chip shows **65 of 83 managers**
- Activists chip shows **7 of 83 managers**, 0 candidates at `min_holders=3`
- Clicking Permanent Capital then opening Custom dialog: dialog shows no style
  boxes checked, footer says "No styles selected — equivalent to the All preset."

---

## Overall status: changes requested

The UX direction is correct and the allowlist threading through
`_eligible_stock_ids` / `_contributions_for_stock` is sound. Two issues must be
addressed before shipping:

**P0 (blocker)** — The filtered endpoint still uses the legacy in-memory
`_stock_payload` formula, not the canonical `signal_weighted_score.py`
formula. Switching from "All" to a preset changes both the universe *and*
the scoring formula — the user cannot distinguish universe effects from formula
artifacts.

**P1 (medium)** — The resolver count includes managers that cannot contribute
to scores (not filtered by `match_status`, CIK presence, or `superinvestor_only`),
so "X of N managers" can overstate the effective filtered universe.

---

## Critical findings

### P0 — Filtered endpoint uses legacy dashboard scoring, not canonical signal-weighted recompute

**Severity:** blocker

**Files:**
- `backend/app/services/oracles_lens/dashboard.py:192–211`
- `backend/app/api/v1/endpoints/oracles_lens.py:123–138`

The PR adds `manager_id_allowlist` to `_eligible_stock_ids()` and
`_contributions_for_stock()` in `signal_weighted_score.py`, and the 13 new
tests exercise those helpers directly. However, the actual API endpoint calls
`build_oracles_lens_dashboard()`, which builds filtered results through
`_holdings_for_period()` + `_stock_payload()` (the legacy in-memory formula
in `dashboard.py`). When a filter is present, `dashboard.py:211` sets
`apply_persisted = False`, causing filtered mode to use the legacy formula.

Impact: "All" uses persisted canonical `oracles_lens_signals` scores; any
preset (Deep Value, Activists, etc.) uses the legacy dashboard score formula.
The user cannot distinguish a ranking change caused by removing Tiger Cubs from
one caused by a formula difference.

**Suggested fix**: Add a non-upserting read path that reuses `_eligible_stock_ids()`
and `_contributions_for_stock()` (canonical formula) without calling `_upsert_signal()`,
and have `build_oracles_lens_dashboard()` invoke this path when
`manager_id_allowlist is not None`.

---

### P1 — Resolver count includes managers that cannot contribute

**Severity:** medium

**File:** `backend/app/services/oracles_lens/manager_universe.py:70`

`resolve_manager_id_allowlist()` queries all `InstitutionManager` rows matching
taxonomy fields but does not filter by `match_status='confirmed'`, `cik IS NOT NULL`,
or `is_superinvestor=True`. The actual holdings query in `_holdings_for_period()`
applies all three filters. As a result, `filtered_manager_count` in the response
can include managers whose holdings will never appear in scores — overstating the
"X of N" numerator.

**Suggested fix**: Accept a `superinvestor_only` flag in the resolver (mirroring
`_superinvestor_universe_size`) and apply `match_status == "confirmed"` and
`cik IS NOT NULL` unconditionally.

---

## 1. Value Investor PO Review (Q1–Q8)

### Q1 — Default landing experience

**Verdict: Accept.**

The page initialises `universeFilters` to Deep Value before the first render
(`page.tsx:215`) so the first API call already carries the preset params. The
mount-time `useEffect` (`page.tsx:217–235`) then writes those params into the
URL via `replaceState`, making the view bookmarkable without a second network
round-trip. Browser smoke confirmed.

The alternative (paint all-managers first, let the user click Deep Value) would
display incorrect scores by default and add friction for every session.

**Nit**: `Small-cap Sleuths` is playful for an institutional tool. Consider
`Small-cap Focused`. Not blocking.

---

### Q2 — "X of N managers" subtitle

**Verdict: Accept concept; fix backend eligibility (P1).**

`65 of 83 managers` is a useful signal of lens narrowness. The denominator
(`_superinvestor_universe_size`) is the correct total. The numerator must be
reconciled with P1 — see above.

**Recommended follow-up (non-blocking):** Add a tooltip to the badge explaining
that filtered-out managers remain in the database but their holdings do not
contribute to current Signal / Conviction / Distinctive scores.

---

### Q3 — "Custom…" dialog

**Verdict: Accept V1 scope; add one-line dialog note.**

Style-only Custom is correct for V1. A 3-section dialog (Style + Capital +
Market cap) is a natural V2 but is not needed to ship the preset workflow.

**UX bug to document**: After clicking Permanent Capital, opening Custom shows
no style boxes checked and footer says "No styles selected — equivalent to the
All preset." That text is true only *after* Apply discards the capital filter;
*while the dialog is open* the current universe is still Permanent Capital.
Add a one-line note at the top of the dialog:
> "Custom only filters by style. Applying will clear any active capital-structure
> or market-cap preset."

---

### Q4 — "Activists" preset returned 0 candidates

**Verdict: Surface a hint; do not auto-lower `min_holders` silently.**

0 results is the truth for 7 activist managers at `min_holders=3`. Auto-lowering
would make the tool lie. Add an empty-state hint when `universe.filtered_manager_count`
is small and `items` is empty, e.g.:
> "Activists only has 7 managers — try lowering Min Holders to 2."

Deferred to BACKLOG; not a blocker for this PR.

---

### Q5 — Preset chip composition — last call

**Verdict: Accept `value_deep + value_concentrated + quality_compounder`.**

Strict value (`value_deep + value_concentrated` only) would drop Polen, Fundsmith,
Lindsell Train, AKO, Cantillon — managers every value investor would expect in
a consensus view. Adding activists to the default would mix event-driven campaigns
with intrinsic-value conviction; the separate Activists chip is the right model.
The current composition is correct.

---

### Q6 — Interaction between universe selector and Filters card

**Verdict: Accept separation; optional UX bridge.**

Universe selector first (who contributes to scores), Filters card second (which
candidates to show from that universe). The mental model is clear.

**Optional enhancement**: Add a subtitle to the Filters card header:
"Applies within the selected universe" — makes the two-layer model explicit
without restructuring the layout.

---

### Q7 — Watchlist 13F columns

**Verdict: Accept V1 deferral.**

Watchlist is a per-position thesis dashboard where consistent numbers across
reloads matter. Silently carrying a global universe selector into Watchlist
would confuse users ("why did my conviction score change?") without enough
explanatory UI. Defer.

---

### Q8 — Live-recompute is the default

**Verdict: Revisit after P0 is fixed.**

Browser smoke felt responsive (<1s subjectively). The architectural choice
(live recompute for presets, persisted fast path for "All") is acceptable
only if the live path uses the same canonical formula as persisted All.
Today it does not (see P0). Once fixed, persisting preset scores can remain
deferred unless production latency exceeds ~1s.

---

## 2. Backend Review (B1–B8)

### B1 — Allowlist threading completeness

**Verdict: Accept. Reasoning is correct.**

`_top_n_stock_ids_per_manager` correctly does NOT take the allowlist. Within
`_contributions_for_stock`, the allowlist filters the query that fetches holdings
(`signal_weighted_score.py:674–675`). Excluded managers are never added to the
contributions list, so their `is_top_10` lookup in `top_n_by_manager` is never
reached. No downstream breakage.

---

### B2 — The "skip persisted overlay" branch

**Verdict: Logic is correct; live path is wrong — see P0.**

`apply_persisted = use_persisted_scores and manager_id_allowlist is None`
(`dashboard.py:211`) is the right gate. Forcing live recompute on any filter is
correct because persisted rows reflect the all-managers universe. The problem is
that "live recompute" currently means the legacy `_stock_payload` formula, not
the canonical `signal_weighted_score.py` computation. Fix P0.

**Non-blocking improvement**: Add a `score_source: "persisted_all" | "live_filtered"`
field to the `universe` response object for observability.

---

### B3 — Conviction / Distinctive correctness

**Verdict: Pure functions confirmed; endpoint integration incomplete pending P0.**

- `conviction_score.py:83–171` — no `Session`, no DB queries; pure function ✓
- `distinctive_consensus.py:59–107` — no `Session`, no DB queries; pure function ✓

Both correctly derive from `contributions` only.

**Test assertion is fragile (nit)**: `test_conviction_and_distinctive_follow_the_allowlist`
asserts `full_conviction.total != filtered_conviction.total`. This happens to hold
because the `agreement` component scales as `min(holder_count / 5, 1) × 10`
(4 holders → 8, 2 holders → 4). A future tuning change could make the total
coincidentally equal while the composition differs.

**Recommended stronger assertion:**
```python
assert full_conviction.agreement != filtered_conviction.agreement
```
This pins the specific mechanism. Non-blocking.

After P0 is fixed, add endpoint-level tests that verify the API response carries
conviction/distinctive values computed from the canonical `conviction_score.py`
functions when a filter is active.

---

### B4 — Endpoint's `universe` shape

**Verdict: Accept "always emit". Minor test name mismatch.**

The endpoint always emits `universe_metadata` (`oracles_lens.py:108–121`) and
`build_oracles_lens_dashboard` always attaches it (`dashboard.py:273–277`).
"Always emit" is cleaner for the FE — one shape to read, no conditional.

**Test name mismatch (nit)**: `test_endpoint_empty_filters_omit_universe_to_signal_persisted_path`
implies the code should omit `universe` when no filter is set, but the code
always emits it. The test body is correct (handles both presence/absence), but
the name is misleading. Consider renaming to
`test_endpoint_empty_filters_universe_signals_all_managers_path`. Non-blocking.

---

### B5 — Resolver validation

**Verdict: Accept. Two `try/except` blocks are not a smell.**

- First (`oracles_lens.py:98–106`): catches resolver `ValueError` (unknown vocabulary values)
- Second (`oracles_lens.py:123–138`): catches dashboard `ValueError` (e.g. bad period format)

These guard different code paths and do not overlap. Acceptable.

---

### B6 — Live-recompute performance assumption

**Verdict: Write path confirmed clean; no benchmark for V1.**

The filter path calls `_holdings_for_period` and `_stock_payload` — neither
calls `_upsert_signal`. `compute_signal_weighted_scores` (the backfill entry
point, which calls `_upsert_signal`) is not invoked from the filter path.
No write-amplification.

No formal benchmark exists. Add a BACKLOG entry for request-duration telemetry
once in production.

---

### B7 — Backward compat for existing call sites

**Verdict: Confirmed additive.**

All existing callers of `build_oracles_lens_dashboard`:
- `stocks_13f.py:287` — no `manager_id_allowlist` → defaults to `None` ✓
- `stocks_13f.py:502` — same ✓
- `formula_comparison.py:131` — same ✓

`_holdings_for_period` called inside `_holding_streaks` (`dashboard.py:499–525`)
does NOT pass `manager_id_allowlist`. This is safe: the streak key
`(excluded_manager_id, stock_id)` will never be looked up because that manager's
holding was never added to `current_holdings`. No behavioral breakage.

---

### B8 — Pre-existing test isolation issue (`_clear_13f`)

**Verdict: No PR blocker.**

Backend test set passed: **28 passed in 4.17s**. The known `_clear_13f` dev DB
accumulation issue is unrelated to this PR's new tests (`db_session` fixture,
isolated transactions).

---

## 3. Frontend Review (F1–F7)

### F1 — `history.replaceState` instead of Next.js router

**Verdict: Accept.**

The page does not use `useSearchParams()` anywhere — it reads the URL only via
`window.location.search` in `useEffect` and `handleSelectUniverse`. There is no
stale-cache risk with the current architecture. `replaceState` correctly avoids
triggering a Next.js route re-render.

**Note for future reviewers**: If a child component ever needs `useSearchParams()`
for universe params, migrate to `useRouter().replace()` at that point.

---

### F2 — Default-preset redirect on bare URL

**Verdict: Accept. Edge cases handled correctly.**

The mount-time redirect (`page.tsx:217–235`) operates on the *existing*
`URLSearchParams` object, so `?period=2025-Q3` → `?period=2025-Q3&style_primary=...`.
Period and `persisted` params survive. Browser smoke confirmed.

**Minor note**: Line 227 only sets `style_primary`, not `capital_structure` or
`market_cap_focus`. This is correct for the Deep Value preset (which only sets
`stylePrimary`). If `DEFAULT_PRESET_KEY` were changed to a multi-dimension
preset, the redirect would be silently incomplete. Add a comment to document
the assumption. Non-blocking.

---

### F3 — `matchPreset` JSON.stringify trick

**Verdict: Accept for V1; nit for follow-up.**

`oraclesLens.js:181–186`: both sides sort the arrays via `norm()` before
`JSON.stringify`, making the comparison deterministic. It works and is covered
by tests (order-invariant test at line 122).

**Nit**: Replace with a named helper:
```js
const arraysEqual = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
```
Non-blocking; add to backlog.

---

### F4 — Tooltip via `title` HTML attribute

**Verdict: Accept for V1 admin-tier feature.**

`UniverseSelector.tsx:118` uses `title={preset.description}`. Known limitations
(touch devices, screen readers) are acceptable for a small set of informed
investors. Add a BACKLOG entry for Radix Tooltip migration if the tool broadens
its audience.

---

### F5 — Custom dialog only edits `style_primary`

**Verdict: Accept V1 scope-out; address UX copy per Q3 above.**

`applyCustom` (`UniverseSelector.tsx:79–87`) correctly zeros `capitalStructure`
and `marketCapFocus` per the task doc Scope (Out). The code comment documents it.

The UX surprise (Permanent Capital → Custom → Apply discards capital filter)
is addressed in Q3. Non-blocking for the PR if the dialog note is added.

---

### F6 — Loading state on chip row

**Verdict: Accept.**

Disabling buttons during loading (`disabled={isLoading}`, `UniverseSelector.tsx:104–123`)
is conservative but correct for 300–500ms responses. Optimistic click-then-cancel
requires React Query `cancelQueries` + debounce and is not warranted for V1.

---

### F7 — Test coverage adequacy

**Verdict: Acceptable for V1; note missing component tests.**

16 lib tests in `oraclesLensUniverse.test.js` cover preset enumeration,
compositions, serialization, parsing, `matchPreset` (exact, order-invariant,
custom, all), and `urlHasUniverseFilter`. All pass.

**Gap**: The task doc (AC #14) specifies
`frontend/components/oraclesLens/UniverseSelector.test.js` — this file does
not exist. The project has no React Testing Library setup, so component tests
require infra investment. Add to BACKLOG.

---

## Required fixes

1. **(P0)** Implement a non-upserting canonical live-recompute read path using
   `_eligible_stock_ids()` + `_contributions_for_stock()` from `signal_weighted_score.py`
   and wire it into `build_oracles_lens_dashboard()` when `manager_id_allowlist is not None`.
2. **(P1)** Apply `match_status == "confirmed"`, `cik IS NOT NULL`, and
   `is_superinvestor=True` (when applicable) in `resolve_manager_id_allowlist()`
   to align the `filtered_manager_count` with the actual contributing-manager set.

## Non-blocking items for this PR

- Q3 / F5: Add one-line note in Custom dialog about clearing capital/market-cap filters
- B3: Strengthen hero test assertion to `full_conviction.agreement != filtered_conviction.agreement`
- B4: Rename misleading test `test_endpoint_empty_filters_omit_universe_...`

## BACKLOG entries

1. Activists empty-state hint when `filtered_manager_count < 15` and `items.length == 0`
2. Request-duration telemetry for filtered live-recompute path (target 300–500ms)
3. Radix Tooltip for chip `title` attributes (accessibility)
4. `UniverseSelector` component-level tests when React Testing Library is added
5. Custom dialog V2: expose `capital_structure` + `market_cap_focus` checkboxes
6. `matchPreset`: replace JSON.stringify with named `arraysEqual` helper
7. `score_source: "persisted_all" | "live_filtered"` field on the `universe` response object
