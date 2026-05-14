# MVP8-03B Four-Role Review Prompts

Four reviewer prompts for the MVP8-03B (watchlist/scoring SME
fixes) closing review. Each is self-contained — drop the prompt
into a fresh chat or hand it to a human reviewer without needing
the rest of this repository's history.

**Branch**: `docs/13f-automation-prd`
**Closing commit**: `fb10b81` ("MVP8-03B watchlist/scoring SME
fixes (B1+B2+B3+B4)")
**Spec**: `docs/tasks/2026-05-13_mvp8-03b-watchlist-scoring-sme-fixes.md`
**Pre-MVP8-03 split contract**:
`docs/tasks/2026-05-13_pre-mvp8-03-sme-flag-cluster-decision-gate.md`

**Authorization gate**: MVP8-03B closing review pass is required
before MVP8-03A (admin 4 items) can open. See Pre-MVP8-03 D5.

Roles (priority order):

1. **Financial Data Product Reviewer (13F Domain SME) — HIGH.**
   Validates that the four items match the SME's product mental
   model. SME's own deferred items are what this ticket lands;
   without SME sign-off the cluster doesn't progress.
2. **Staff Engineer — MEDIUM.** Cross-cutting contract /
   scaling / scope review.
3. **Backend Reviewer — MEDIUM.** Schema design + FastAPI
   patterns + Pydantic backwards compatibility.
4. **Frontend Reviewer — MEDIUM.** TypeScript exhaustiveness +
   UX hierarchy + accessibility.

---

## 1. Financial Data Product Reviewer (13F Domain SME) Prompt

You are the 13F domain SME conducting the MVP8-03B closing
review for ValuePilot's 13F automation track. MVP8-03B
implements four watchlist/scoring SME-flagged fixes that you
(or a prior reviewer in your role) flagged during the MVP7-06
four-role review and that were deferred at that ship. Closing
commit is `fb10b81` on branch `docs/13f-automation-prd`.

**Read these files in order:**

1. `docs/tasks/2026-05-13_mvp8-03b-watchlist-scoring-sme-fixes.md`
   — full spec + Verification Results (B2 audit data + B3
   product-judgment rationale + B4 sample outputs).
2. `backend/app/services/oracles_lens/dashboard.py` lines 60–80
   (`ManagerHolding` dataclass), 378–410 (admin manager_type
   capture in `_load_holdings_for_period`), 540–610
   (`_stock_payload` aggregate computation + payload shape).
3. `backend/app/api/v1/endpoints/stocks_13f.py` lines 40–70
   (`_distinctiveness_tier` with new `admin_unknown_ratio`
   kwarg).
4. `frontend/lib/watchlist13f.ts` lines 250–315
   (`mosCrossSignal` two-tier logic + `mosCrossSignalTooltip`
   copy).
5. `frontend/components/watchlist/MosCrossSignalGlyph.tsx` —
   glyph variants for the four non-neutral signals.
6. `frontend/components/watchlist/Watchlist13FDrawer.tsx` lines
   140–250 — drawer summary recap (B4 mean position weight
   line) + TopHolderCard dual-chip rendering (B1).

**Four key product questions you must answer:**

### B1 — manager_type derived vs admin dual display

The current dev DB has **all 72 superinvestor managers with
admin `manager_type='unknown'`** (admin curation hasn't been
done yet; per Pre-MVP8-01 D3, the curation is a later track A2
ticket). So today the drawer's dual chip will fire on **every
holder** where behavior derivation found a non-unknown profile
— i.e. essentially every holder — rendering "Derived: Long term
fundamental / Admin: Unknown" pairs across the board.

- Is that the right behavior for the current state, or does it
  noise-pollute the drawer until admin curation lands?
- Would you prefer: (a) ship as-is — surfacing the gap is the
  point; (b) suppress the "Admin: Unknown" badge when admin is
  literally `unknown` (only show when admin classifies and
  diverges); (c) something else?

### B2 — distinctiveness `crowded` gate rule

The new rule: `crowded` fires when `consensus_count >= 20 AND
admin_unknown_ratio > 0.5`. The 2025-Q3 audit shows 6 stocks
flip into `crowded`: **MSFT (30 holders), GOOG (22), AMZN (20),
GOOGL (23), V (22), META (21)** — all with admin_unknown_ratio
= 1.0 because admin curation is uniformly absent.

- Does flagging MSFT/GOOG/AMZN/GOOGL/V/META as `crowded` match
  your product judgment for what `crowded` should mean? Or
  should `crowded` be reserved for "broad consensus + low
  manager quality" — in which case the rule needs a stronger
  signal than the current "admin hasn't classified them"?
- Should `crowded` also gate on derived `high_turnover_count`
  or `manager_signal_weight` quality (to avoid flagging a stock
  as crowded when it's broadly held by long-term-fundamental
  managers who simply haven't been admin-classified)?

### B3 — MOS × 13F two-tier alignment

V1 single-tier `aligned (MOS >= 0.20, Δ >= +1)` became:

- `aligned`: MOS ≥ 0.30 AND Δ ≥ +3 (new strong tier; CheckCheck
  glyph).
- `weak-aligned`: MOS ≥ 0.20 AND Δ ≥ +1 (preserved V1
  semantics; lighter Check glyph).

**No empirical audit was possible** — dev DB has no MOS data
and only one quarter of 13F data (so realistic Δ distribution
isn't observable either). This is a pure product-judgment
threshold choice.

- Are the chosen thresholds (0.30/+3 strong, 0.20/+1 weak)
  product-correct, or should one or both move?
- Is the `weak-aligned` label intuitive to a value-investing
  user, or does it sound dismissive of a legitimate signal?
  Alternatives: `nascent-aligned`, `early-aligned`, `mild-aligned`,
  `directional-aligned`. Strong preference?
- The glyph hierarchy (CheckCheck saturated emerald vs Check
  lighter emerald) — does that visual weight feel right? Or
  should `weak-aligned` use a different shape entirely (e.g.
  outline check, dot, half-circle)?

### B4 — Δ Holders portfolio-weight context

Chip tooltip + drawer recap show **mean position weight**
(sum / count) rather than the raw sum. Sample (2025-Q3):

| Ticker | adders | mean pos weight |
|--------|--------|-----------------|
| MSFT | 30 | 6.30% |
| GOOG | 22 | 5.89% |
| AMZN | 20 | 7.26% |
| GOOGL | 23 | 4.86% |
| V | 22 | 4.16% |

- Is "mean position weight" the right "depth" metric, or do
  you want a different aggregation (median, weighted-by-AUM,
  capital-flow-dollars)?
- The dev-DB state has 0 reducers for 2025-Q3 (no Q2 baseline
  to compute deltas against), so the "reducers mean position
  weight 0.0%" you see in the UI is artifactual. Is that
  ok-pending-Q2-backfill or worth a UI tweak (e.g. show "no
  prior-quarter data" instead of 0.0%)?

**Other things to spot-check:**

- The drawer dual-chip styling (Watchlist13FDrawer.tsx lines
  226–248) — does "Derived: X / Admin: Y" read clearly, or
  does it crowd the per-holder card?
- The B2 distinctiveness rule depends on the backend payload
  including `admin_unknown_manager_type_count` in
  `manager_signal_summary`. If the persisted-scores path
  (post-MVP8-01 server default) doesn't surface this field,
  `_snapshot_from_item` defaults `admin_unknown_count = 0` and
  the rule never fires. Is that an acceptable graceful
  degradation, or a real risk that needs a follow-up?

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

B1 (dual manager_type):
- [your read]

B2 (crowded gate):
- [your read]

B3 (two-tier thresholds):
- [your read]

B4 (mean position weight):
- [your read]

MVP8-03B should-block items (if any):
1. ...

MVP8-03A must-fix items (rolled into the admin cluster):
1. ...

Future backlog (separate ticket):
1. ...
```

Be terse. MVP8-03A authorization depends on your verdict.

---

## 2. Staff Engineer Prompt

You are the Staff Engineer conducting the MVP8-03B cross-ticket
review for ValuePilot's 13F automation track. MVP8-03B is a
four-fix product-trust ticket (B1+B2+B3+B4) shipped as commit
`fb10b81` on branch `docs/13f-automation-prd`. The cluster is
priority #2 on the MVP8 track per the PO-locked ranking at
MVP7-06 close.

**Read these files in order:**

1. `docs/tasks/2026-05-13_mvp8-03b-watchlist-scoring-sme-fixes.md`
   — full spec.
2. The closing commit `fb10b81` — 9 files / +520/-18 lines.
3. `backend/app/services/oracles_lens/dashboard.py` — the
   `ManagerHolding` dataclass change and `_load_holdings_for_period`
   capture site (admin manager_type now flows into the
   in-memory holdings graph).
4. `backend/app/api/v1/endpoints/stocks_13f.py` — the
   `_distinctiveness_tier` signature change + the two
   `_snapshot_from_item` / detail-builder call sites.
5. `backend/app/schemas/stocks_13f_snapshot.py` — three schema
   adds (`adders_portfolio_weight_sum`,
   `reducers_portfolio_weight_sum`,
   `manager_type_admin_classified`).
6. `frontend/lib/watchlist13f.ts` — `MosCrossSignal` enum +
   `Watchlist13FTopHolder` + `Watchlist13F*Snapshot` type
   updates.

**Review angles + accept/reject criteria:**

1. **Cross-cutting impact of the `ManagerHolding` change.**
   The dataclass got a new field (`manager_type_admin_classified`).
   Confirm: (a) no downstream consumer (e.g.
   `_apply_manager_signal_profiles`, `_caution_flags`,
   `_primary_reasons`, `_conviction_components`, or anything in
   `oracles_lens/signal_weighted_score.py` if it shares
   types) silently breaks when the field is present; (b) the
   `manager_type` field's invariant after
   `_apply_manager_signal_profiles` is unchanged (behavior-
   derived value, with admin-classified preserved separately);
   (c) no test fixture seeds ManagerHolding directly without
   the new field, which would default to `"unknown"` —
   acceptable per Python dataclass defaults but worth one grep.

2. **Schema backwards compatibility.**
   Three new fields on `AvailableStockSnapshot` /
   `AvailableStockDetail` / `StockDetailTopHolder` all have
   defaults (`0.0`, `0.0`, `"unknown"`). Existing API consumers
   that pin Pydantic shapes — frontend types,
   `oraclesLens.test.js`, any external integration — should
   tolerate the new fields. Confirm: (a) Pydantic emits the new
   fields with defaults when not set (so old callers' parse
   logic doesn't reject them as missing); (b) the new fields
   are ALSO required at runtime in the persisted-path code
   route (post-MVP8-01 server default) — check that
   `build_oracles_lens_dashboard(use_persisted_scores=True)`
   produces payloads containing the new aggregates.

3. **`_distinctiveness_tier` API surface.**
   The function now takes `admin_unknown_ratio` as a
   keyword-only arg with default `0.0`. Default `0.0` means
   "admin curation is fully complete (no unknowns)" — which
   maps to "never `crowded` under the new rule" by default.
   Is that the right default? An alternative is `1.0` (assume
   un-curated), which would fire `crowded` for all
   `consensus_count >= 20` stocks until a caller explicitly
   passes a measured ratio. Pick the safer default + document
   the choice.

4. **TypeScript exhaustiveness — MosCrossSignal enum widening.**
   The enum gained a `weak-aligned` variant. The compiler will
   catch any non-exhaustive `switch` on `MosCrossSignal` (good).
   But it WON'T catch consumers that do
   `signal === 'aligned'` boolean checks — those silently
   evaluate `false` for `weak-aligned`. Grep for any such
   patterns: `grep -rn "=== 'aligned'\\|MosCrossSignal" frontend/`.
   If found, fix or document.

5. **Persisted-path vs legacy-path consistency.**
   Post-MVP8-01, `build_oracles_lens_dashboard(use_persisted_scores=True)`
   serves the production default. Confirm that the persisted
   path produces a payload that includes the new B2/B4
   aggregates (`admin_unknown_manager_type_count`,
   `adders_portfolio_weight_sum`,
   `reducers_portfolio_weight_sum`,
   `manager_type_admin_classified` on top_holders). Look at
   how the persisted path constructs payloads — does it route
   through `_stock_payload` or take a different code path that
   bypasses the new fields? This is the highest-impact
   correctness risk for the ticket.

6. **B4 mean computation in two places.**
   `Watchlist13FColumns.tsx` and `Watchlist13FDrawer.tsx` both
   compute `sum / count` inline. If a third consumer is added
   later, the duplicated math is a small DRY leak. Consider
   pulling a helper into `frontend/lib/watchlist13f.ts`:
   `meanPortfolioWeight(side: 'adders' | 'reducers',
   snapshot)`. Non-blocking but worth a small follow-up.

7. **Test coverage gap.**
   No targeted unit test for B1 dual-display or B4 mean math.
   The MVP7-05 detail integration tests cover the new field
   presence (since they assert against the full schema shape)
   but don't pin behavior like "admin=X, derived=Y produces
   dual-chip render." Is that adequate, or should one
   regression test land before MVP8-03A?

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

MVP8-03B should-block items (before this ticket closes):
1. ...

MVP8-03A must-fix items (before the admin cluster opens):
1. ...

Follow-up tech-debt tickets to file:
1. ...
```

---

## 3. Backend Reviewer Prompt

You are the Backend Reviewer for ValuePilot's 13F automation
track. MVP8-03B shipped four watchlist/scoring SME fixes in
commit `fb10b81` on branch `docs/13f-automation-prd`. The
backend changes touch the in-memory dashboard pipeline, two
endpoint shapes, and three Pydantic schemas.

**Read these files in order:**

1. `backend/app/services/oracles_lens/dashboard.py`:
   - Lines 60–80 (`ManagerHolding` dataclass).
   - Lines 378–410 (`_load_holdings_for_period`
     ManagerHolding construction).
   - Lines 540–615 (`_stock_payload` aggregate computation +
     `top_holders` payload).
2. `backend/app/api/v1/endpoints/stocks_13f.py`:
   - Lines 40–70 (`_distinctiveness_tier` with
     `admin_unknown_ratio` kwarg).
   - Lines 95–135 (`_snapshot_from_item`).
   - Lines 275–315 (`_top_holder_from_payload`).
   - Lines 445–500 (detail-endpoint builder).
3. `backend/app/schemas/stocks_13f_snapshot.py` — three schema
   additions.
4. `backend/tests/unit/test_mvp7_01_stocks_13f_snapshots.py`
   — the three updated `_distinctiveness_tier` unit tests.

**Review angles:**

1. **`ManagerHolding` admin field capture.**
   Line ~395: `manager_type_admin_classified=manager.manager_type
   or "unknown"`. The `or "unknown"` fallback handles the
   `manager.manager_type IS NULL` DB case. Is that fallback the
   right semantic? `InstitutionManager.manager_type` has a
   default of `"unknown"` per the model — but if a row is ever
   `None` (legacy data, race condition during ingestion), do we
   want that to surface as `"unknown"` silently or surface as
   an explicit "missing" sentinel? Recommend.

2. **`_distinctiveness_tier` keyword-only default.**
   Default is `admin_unknown_ratio=0.0` (= "fully curated, no
   unknowns" = "never crowded by admin signal"). Two existing
   call sites pass a measured ratio. If a future call site
   forgets to pass it, the function silently downgrades the
   `crowded` rule. Consider: (a) leave as-is with docstring; (b)
   make it positional-required to force callers to pass it; (c)
   pick a "safer" default like `1.0` that errs toward firing
   `crowded`. Trade-offs in scope/blast-radius?

3. **Aggregate sums in `_stock_payload`.**
   `adders_portfolio_weight_sum` is computed as
   `sum(item.position_weight for item in holdings if
   item.action in {"new", "add"})`. Two concerns: (a)
   `position_weight` is a float; sum of 30+ floats may
   accumulate FP error. Is that ok at the precision the chip
   tooltip renders (1 decimal place after the % conversion)?
   (b) The set membership `{"new", "add"}` matches the
   dashboard's adders_count logic verbatim — confirm there's
   no third action code (e.g. `"new_increase"`) elsewhere in
   the dashboard that would split these counts.

4. **`_top_holder_from_payload` payload tolerance.**
   Line ~277: `manager_type_admin_classified=str(holder.get
   ("manager_type_admin_classified") or "unknown")`. If a
   cached or stale payload doesn't have the new field, it
   defaults to `"unknown"`, which makes the drawer NOT render
   the dual chip (since admin==derived if both are "unknown").
   That's the desired graceful degradation. Confirm no caller
   actually pre-builds top_holders dicts outside `_stock_payload`
   that would now be missing the field with consequence.

5. **Snapshot endpoint defaults.**
   `adders_portfolio_weight_sum=float(manager_summary.get(...)
   or 0.0)`. If `manager_signal_summary` is missing entirely
   (unlikely under the normal code path), the new fields
   default to `0.0`, which makes the chip tooltip render "mean
   0.0%" — visible but harmless. Is that acceptable?

6. **Test pin for the new tier rule.**
   `test_distinctiveness_tier_crowded_threshold` was rewritten
   to assert the new rule. The old behavior (`coverage < 0.5`
   alone) is no longer tested anywhere — is the old behavior
   officially retired, or should one assertion confirm "old
   rule no longer fires" for posterity?

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

Code-level findings:
- [path:line — finding]

MVP8-03B should-block items (if any):
1. ...

MVP8-03A backend follow-ups (rolled into admin cluster):
1. ...

Tech-debt notes:
1. ...
```

---

## 4. Frontend Reviewer Prompt

You are the Frontend Reviewer for ValuePilot's 13F automation
track. MVP8-03B shipped four watchlist/scoring SME fixes in
commit `fb10b81` on branch `docs/13f-automation-prd`. Frontend
changes: cross-signal enum widening + glyph variant + drawer
dual chip + chip tooltip enrichment.

**Read these files in order:**

1. `frontend/lib/watchlist13f.ts`:
   - Lines 22–45 (`Watchlist13FAvailableSnapshot` type with
     B4 fields).
   - Lines 250–315 (`MosCrossSignal` enum + `mosCrossSignal`
     + `mosCrossSignalTooltip`).
   - Lines 325–375 (`Watchlist13FTopHolder` +
     `Watchlist13FAvailableDetail` types).
2. `frontend/components/watchlist/MosCrossSignalGlyph.tsx` —
   glyph variants for `aligned` / `weak-aligned` /
   `exit-divergence` / `buy-divergence`.
3. `frontend/components/watchlist/Watchlist13FColumns.tsx`
   lines 100–180 (chip tooltip + Δ Holders cell).
4. `frontend/components/watchlist/Watchlist13FDrawer.tsx`
   lines 145–250 — drawer summary + TopHolderCard dual-chip
   rendering.

**Review angles:**

1. **`MosCrossSignal` enum widening — exhaustiveness.**
   The enum gained `'weak-aligned'`. Confirm:
   (a) `mosCrossSignalTooltip` switch is exhaustive (it is —
   TypeScript would error otherwise).
   (b) `MosCrossSignalGlyph` handles `weak-aligned` (added the
   variant). Verify the icon import `CheckCheck` exists in
   `lucide-react` and renders correctly.
   (c) Any other consumer of `MosCrossSignal`. Grep for it.

2. **Drawer dual-chip rendering condition.**
   `holder.manager_type_admin_classified &&
   holder.manager_type_admin_classified !== holder.manager_type`.
   When the admin field is the empty string (vs `"unknown"`),
   the truthy check fails and we'd fall to the single-chip
   branch even if `holder.manager_type` happens to be a
   non-empty value. Verify the backend never emits empty string
   for this field — it always emits `"unknown"` or a typed
   value per the `_top_holder_from_payload` `or "unknown"`
   fallback.

3. **Chip tooltip / drawer recap zero-state.**
   When `adders_count === 0`, the mean computation guards
   against div-by-zero (returns 0), then renders "mean
   position weight 0.0%". The dev-DB state has 0 reducers for
   every stock (no Q2 baseline), so today every chip tooltip
   shows "0 reducers (mean position weight 0.0%)". Is that
   visually fine, or should we suppress the parenthetical when
   the count is 0?

4. **Dual chip visual hierarchy.**
   `Derived` chip uses default outline (solid); `Admin` chip
   uses `border-dashed text-muted-foreground`. Is the contrast
   strong enough to read at a glance? Could be tighter with a
   leading icon (e.g. `User2` for admin, `Sparkles` for
   derived) — but that adds icon clutter. Recommend.

5. **Accessibility.**
   `MosCrossSignalGlyph` uses lucide icons with `aria-label` +
   `<title>` child. The dual-chip in the drawer uses native
   `title` attributes on the Badge. Both are non-blocking but
   are these the right a11y patterns for the project's
   accessibility track (which is separately queued)?

6. **Bundle-size impact.**
   Adding `CheckCheck` from `lucide-react` (already imported)
   is zero-cost since lucide tree-shakes. Confirm by running
   `npm run build` and comparing the `/watchlist` route size
   to the MVP7-06 baseline (199 kB First Load JS per memory).

7. **i18n / copy.**
   New strings: "Weakly aligned: smart money is adding (Δ ≥
   +1) and there is some margin of safety (MOS ≥ 20%), but
   neither signal is strong." + "Aligned: smart money is
   meaningfully adding (Δ ≥ +3) into a deep value setup (MOS
   ≥ 30%)." + drawer "mean position weight" copy. Are these
   on-brand for ValuePilot's voice? (Track is currently
   English-only.)

**Output format:**

```
VERDICT: APPROVE / APPROVE-WITH-CONDITIONS / REJECT

UX findings:
- [component — finding]

Code-level findings:
- [file:line — finding]

MVP8-03B should-block items (if any):
1. ...

MVP8-03A frontend follow-ups (rolled into admin cluster):
1. ...

Future backlog:
1. ...
```

---

## Dispatch Notes

- Each prompt is self-contained; you can hand any one of them
  to a fresh chat or human reviewer without sharing the
  others.
- For agent dispatch, the SME prompt is HIGH priority — it
  gates the cluster's product fidelity. The other three can
  run in parallel.
- Output bucketing: items labeled "MVP8-03B should-block" must
  be addressed before this ticket closes. Items labeled
  "MVP8-03A must-fix" get rolled into the admin cluster's
  scope when it opens. Items labeled "future backlog" file as
  separate tickets.
- After all four reviewers submit, the PO will read all four
  verdicts together, make a closure call, and then authorize
  MVP8-03A per Pre-MVP8-03 D5.
