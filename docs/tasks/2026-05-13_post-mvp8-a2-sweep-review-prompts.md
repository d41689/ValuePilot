# Post-MVP8-A2 + Track-E Sweep — Four-Role Review Prompts

Four reviewer prompts for the closing review of the post-MVP8-A2 +
Track-E backlog sweep (D1–D4). Each prompt is self-contained — drop
into a fresh chat or hand to an external reviewer without prior context.

**Branch**: `docs/13f-automation-prd`

**Commits under review**:
- `900a9f0` — D2: unify M3 read path — shared `_m3_facts_by_stock` helper +
  Piotroski `value_json` fallback in `_fact_value`.
- `65efdb1` — D3: DrawerShell `useRef` stable-callback + explicit focus +
  focus restoration.
- `ef9bbee` — D4: deferred to design gate (`metric_facts.is_current`
  semantics) — doc-only, no code change.
- `d056052` — D1: typed `QualityOverlay` Pydantic schema + VL target as-of
  date provenance.
- `a11ac45` — Close ticket (internal four-role pass + sign-off).

**Specs**:
- `docs/tasks/2026-05-13_post-mvp8-a2-track-e-backlog-sweep.md` — sweep
  ticket (closed, full D1–D4 contracts + verification + final sign-off).
- `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`
  — D4's escalation target.
- `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md` — original
  MVP8-A2 spec (closed) the sweep follows from.

Roles (priority order):

1. **13F Domain SME — HIGH.** Did the as-of date semantics land correctly?
   Are the legacy Oracle's Lens dashboard and Watchlist drawer now
   consistent for Piotroski? Was D4's deferral the right product call?
2. **Staff Engineer — MEDIUM.** Abstraction boundaries (shared helper
   placement, `_fact_value` fallback generality), schema-typing tradeoffs
   (Literal vs open str), `is_current` deferral framing.
3. **Backend Reviewer — MEDIUM.** ORM query correctness, Pydantic shape,
   regression test coverage, OpenAPI emission.
4. **Frontend Reviewer — MEDIUM.** TypeScript contract, render
   conditional logic, DrawerShell `useRef` pattern, focus restoration
   correctness under StrictMode.

---

## 1. 13F Domain SME Prompt

You are the 13F domain SME conducting the closing review for the
post-MVP8-A2 + Track-E backlog sweep (D1–D4). Branch
`docs/13f-automation-prd`. Sweep ticket already closed via internal
four-role pass at commit `a11ac45`; this is an external second-look.

**Read these in order:**

1. `docs/tasks/2026-05-13_post-mvp8-a2-track-e-backlog-sweep.md` — full
   sweep spec with D1–D4 root causes, fix contracts, and sign-off trail.
2. `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`
   — D4's escalation target (the design question that displaced D4's
   original "dedup" framing).
3. `frontend/components/watchlist/Watchlist13FDrawer.tsx` — find
   `QualityOverlaySection`. Confirm the as-of label `"(as of YYYY-MM-DD)"`
   appears under the VL 18-month target line in muted styling and is
   omitted when `vl_target_period_end` is null.
4. `backend/app/services/oracles_lens/dashboard.py` — find the new
   `_m3_facts_by_stock` helper (around the previous
   `_quality_overlay_by_stock` location) and the extended `_fact_value`
   that now falls back to `value_json['partial_score']`.

**Four product questions you must answer:**

### Q1 — As-of label semantics

The drawer renders `"(as of 2026-02-13)"` (in muted text) under the
VL 18-month target line, sourced from the winning
`target.price_18m.mid` MetricFact's `period_end_date`. In Value
Line's data model, this field stores the publication / report date
(not a fiscal period).

- Is "as of {date}" the right phrasing for this date? Alternatives:
  "VL report dated …", "Published …", "Updated …". The current
  wording leaves it ambiguous between "report date" and "data effective
  date" — does that ambiguity matter to a research user?
- Should we surface the source_document_id anywhere (e.g., a click-to-
  open link to the underlying VL doc), or is the date alone enough
  context? The provenance field is in the API but unused on the surface.

### Q2 — Legacy / Watchlist consistency

D2 fixes a 2-year-old bug where `_quality_overlay_by_stock` filtered
`value_numeric.isnot(None)` and silently dropped 269/272 Piotroski
rows. Before D2, the legacy `/13f/oracles-lens` page showed
`piotroski_total: null` even when a score existed in `value_json`. After
D2 the legacy page surfaces the same scores the Watchlist drawer
shows.

- Is there any user workflow that *relied* on the legacy page showing
  `null` Piotroski (e.g., a screening rule, a manual data-quality
  signal)? If yes, the D2 fix changes outputs for that workflow.
- The fix is generic: `_fact_value` now reads `value_json['partial_score']`
  for ANY metric whose value_numeric is null. Other "composite-score"
  metrics besides Piotroski would also be picked up. Audit the dev DB
  for other metrics with this storage pattern — anything we
  unintentionally turned on?

### Q3 — D4 deferral

D4 originally asked for "dedup metric_facts.is_current=True duplicates
to enforce one current row per (stock, metric_key)". Pre-implementation
data check showed:

| Metric | is_current rows | distinct stocks | extra per-stock |
|---|---|---|---|
| `per_share.eps` | 194 | 7 | ≈27/stock |
| `is.net_income` | 86 | 7 | ≈11/stock |
| `score.piotroski.total` | 74 | 6 | ≈11/stock |

These are intentional fiscal-period time series (ADBE has 42
`is_current=True` rows for EPS — one per fiscal year of VL history).
The two ADBE rows for `target.price_18m.mid` that triggered the
original report are at different `period_end_date`s (2025-01-31 vs
2026-05-01) — both "current for their own period" under the schema's
existing semantics.

Implementing D4 literally would wipe ~99% of metric_facts time series.
The fix was deferred to a design gate that proposes 4 options
(status quo + tiebreak, opinion-key allowlist, schema column,
split column).

- Is the deferral the right product call? Or should we ship the
  opinion-key allowlist option immediately because opinion metrics
  (target / projection / quality rating) are an active staleness risk?
- For VL opinion metrics specifically, what's the right semantic:
  "all publications are current and the consumer picks the most recent"
  (display-layer guard, status quo), or "only the latest publication is
  current" (write-side dedup)? This is a product decision, not an
  engineering one.

### Q4 — Drawer focus restoration (D3)

D3 changes DrawerShell so that when the drawer closes, focus returns
to the element that opened it (typically the row button). This
satisfies WCAG 2.4.3 (Focus Order) but adds a behavior users may
notice — e.g., after closing the drawer the row button has a focus
ring.

- Is this a desired UX or a surprise? Users who clicked the row with a
  mouse don't expect a keyboard focus ring afterward. Acceptable?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

Q1: ...
Q2: ...
Q3: ...
Q4: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.

---

## 2. Staff Engineer Prompt

You are the Staff Engineer reviewing the closed post-MVP8-A2 +
Track-E sweep. Branch `docs/13f-automation-prd`. Commits `900a9f0`
(D2), `65efdb1` (D3), `ef9bbee` (D4 defer), `d056052` (D1), `a11ac45`
(close).

**Read these:**

1. `docs/tasks/2026-05-13_post-mvp8-a2-track-e-backlog-sweep.md` —
   sweep spec.
2. `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`
   — D4 escalation.
3. `backend/app/services/oracles_lens/dashboard.py` — find
   `_m3_facts_by_stock`, the refactored `_quality_overlay_by_stock`,
   and the extended `_fact_value`.
4. `backend/app/api/v1/endpoints/stocks_13f.py` — find `_M3_METRIC_KEYS`
   constant (still in this file) and `_m3_panel_for_stock` (now returns
   typed `QualityOverlay`).
5. `backend/app/schemas/stocks_13f_snapshot.py` — new `QualityOverlay`
   model.
6. `frontend/components/admin13f/Admin13FPrimitives.tsx` — `DrawerShell`
   with the new useRef pattern + focus restoration.

**Architectural questions:**

### A1 — `_M3_METRIC_KEYS` placement

The constant stayed in the endpoint file (`stocks_13f.py`) after D2's
extraction. The pre-review prompt for the prior round (MVP8-A2 +
Track-E) raised the concern that the endpoint module imported
`MetricFact` for raw ORM access — domain leak. D2 removed the
`MetricFact` import. But `_M3_METRIC_KEYS` (the metric_key set the
drawer cares about) is still defined next to the endpoint. Moving it
to `oracles_lens/dashboard.py` near `QUALITY_METRIC_KEYS` would be more
consistent.

- Is keeping `_M3_METRIC_KEYS` in the endpoint file acceptable
  (drawer-specific, only one caller), or should it move to the service
  module for symmetry with `QUALITY_METRIC_KEYS` and
  `VALUATION_REFERENCE_KEYS`?

### A2 — `_fact_value` fallback generality

The function now reads `value_json['partial_score']` when
`value_numeric` is null. This is generic, not Piotroski-specific —
any composite score using the `partial_score` convention is covered.

- Is the generic fallback the right move, or should there be a
  per-metric whitelist? Risk: a future metric writes `partial_score`
  in value_json with a different semantics (e.g., a "partial fill"
  status counter) and gets accidentally read as a score.
- An alternative is a `MetricFact` model method like
  `fact.numeric_value() -> float | None` that encapsulates the
  fallback logic. Worth refactoring?

### A3 — Typed `QualityOverlay`: open vs closed status vocabulary

The spec proposed `piotroski_status: Literal["partial", "complete"] | None`.
Dev DB analysis showed two values: `"partial"` (72 rows) and
`"calculated"` (2 rows). The implementation widened to `Optional[str]`
to avoid a 500 on the existing `"calculated"` rows.

- Is opening the vocabulary the right move, or should we have
  audited and either (a) cleaned up the "calculated" rows or
  (b) added "calculated" to the Literal? The current state keeps a
  contract pin that's wider than the documented vocabulary.

### A4 — D4 deferral framing

The sweep spec's D4 originally specified a parser fix. Investigation
revealed it was actually a schema-semantics conflict between fiscal
metrics (per-period currency) and opinion metrics (single-living-value).
Deferred to a design gate.

- Is escalating to a design gate the right move, or should the sweep
  have implemented the opinion-key allowlist (Option B in the gate) as
  the safer middle ground?
- The design gate's recommended option is A (status quo + tiebreak).
  Does that match your engineering view, or would you push for B?

### A5 — DrawerShell focus restoration semantics

D3 captures `document.activeElement` in a `useEffect` that runs after
the drawer mounts. If the parent unmounts the trigger element while
the drawer is still open (e.g., the row gets filtered out of the
watchlist), `previouslyFocused?.focus()` on close is a no-op — focus
lands on `<body>`. Is this an acceptable failure mode, or should we
maintain a "fallback focus target" (e.g., the page's main heading)?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

A1: ...
A2: ...
A3: ...
A4: ...
A5: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.

---

## 3. Backend Reviewer Prompt

You are the backend engineer reviewing the closed post-MVP8-A2 +
Track-E sweep. Branch `docs/13f-automation-prd`, commits `900a9f0`,
`d056052`, `ef9bbee`.

**Read these:**

1. `backend/app/services/oracles_lens/dashboard.py` — `_m3_facts_by_stock`
   (new), `_quality_overlay_by_stock` (refactored), `_fact_value`
   (extended).
2. `backend/app/api/v1/endpoints/stocks_13f.py` — `_m3_panel_for_stock`
   returning typed `QualityOverlay`; provenance population from
   `target.price_18m.mid` fact.
3. `backend/app/schemas/stocks_13f_snapshot.py` — `QualityOverlay`
   Pydantic model, `AvailableStockDetail.quality_overlay` field swap.
4. `backend/tests/unit/test_13f_mvp8_a2_m3_panel.py` — 3 tests migrated
   to attribute access + provenance assertion.
5. `backend/tests/unit/test_oracles_lens.py` — search for
   `test_oracles_lens_reads_piotroski_from_value_json_when_value_numeric_null`
   (D2 regression test).

**Backend-specific questions:**

### B1 — `_m3_facts_by_stock` query

The shared helper's ORM query orders by:
```python
.order_by(
    MetricFact.stock_id.asc(),
    MetricFact.metric_key.asc(),
    MetricFact.period_end_date.desc().nullslast(),
    MetricFact.created_at.desc(),
)
```
Then takes first-seen per (stock_id, metric_key). For fiscal metrics
this returns the most-recent fiscal period; for opinion metrics this
returns the most-recent publication. Single tiebreak definition for
both callers (`_quality_overlay_by_stock` and `_m3_panel_for_stock`).

- Is the ordering correct? Specifically, does `period_end_date DESC
  NULLS LAST` correctly handle the case where some rows have NULL
  `period_end_date` (e.g., manual metric_facts)?
- Should the query also filter by `source_type` (e.g., only "parsed"
  and "calculated", excluding "manual")? Currently it doesn't.

### B2 — `_fact_value` fallback

```python
def _fact_value(fact: MetricFact | None) -> float | None:
    if fact is None:
        return None
    if fact.value_numeric is not None:
        return float(fact.value_numeric)
    if isinstance(fact.value_json, dict):
        raw = fact.value_json.get("partial_score")
        if raw is not None:
            return float(raw)
    return None
```

- The fallback uses `value_json.get("partial_score")` — string key.
  Postgres JSONB can also have integer indices for arrays, but the
  isinstance check guards against that. Good.
- Should the function also try `value_json.get("value")` or
  `value_json.get("score")` for other composite-fact storage
  conventions? Or is `partial_score` the only one currently in use?
- The `float(raw)` cast: if `raw` is a string (e.g., from a parser
  that stringified the integer), `float("6")` works. If it's a list
  or dict, `float()` raises. Should there be a try/except?

### B3 — `QualityOverlay` Pydantic shape

The model uses `Optional[int]`, `Optional[float]`, `Optional[str]` for
all 11 nullable fields. FastAPI/Pydantic emits these as nullable in
OpenAPI. The frontend type
(`frontend/lib/watchlist13f.ts.quality_overlay`) is now redundant with
what FastAPI could generate.

- Should the frontend type be generated from the OpenAPI spec (via
  openapi-typescript or similar) instead of hand-maintained? Today
  both must be kept in sync manually.
- The model has no Pydantic validators (e.g., `piotroski_score <=
  piotroski_max`). Worth adding, or trust the producer?

### B4 — Provenance: `target_mid` only

`_m3_panel_for_stock` sources `vl_target_period_end` and
`vl_target_source_document_id` from the
`target.price_18m.mid` MetricFact. The other VL facts in the same
panel (`target.price_18m.low`, `proj.long_term.high_price`, etc.)
could come from different source documents in principle.

- In the dev DB, do all VL panel facts for a given stock come from
  the same source_document_id? If yes, sourcing provenance from
  target_mid alone is fine. If no, the panel mixes data from multiple
  publications and the as-of date is misleading.
- Should the helper return a `dict[source_document_id, list[str]]` of
  which facts came from which doc, so the panel can render multi-doc
  provenance honestly?

### B5 — D2 regression test

The regression test
(`test_oracles_lens_reads_piotroski_from_value_json_when_value_numeric_null`)
seeds a single MetricFact row with `value_numeric=None` and
`value_json={partial_score: 6, max_available_score: 8, status: "partial"}`,
then asserts the legacy Oracle's Lens dashboard surfaces
`piotroski_total=6.0`. The test covers the value_json path but doesn't
test the value_numeric path (which the existing
`test_oracles_lens_adds_value_line_quality_overlay` test already
covers).

- Coverage adequate? Or should there be a third test asserting that
  when BOTH value_numeric and value_json['partial_score'] exist with
  different values, value_numeric wins (i.e., the fallback only fires
  when value_numeric is null)?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

B1: ...
B2: ...
B3: ...
B4: ...
B5: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.

---

## 4. Frontend Reviewer Prompt

You are the frontend engineer reviewing the closed post-MVP8-A2 +
Track-E sweep. Branch `docs/13f-automation-prd`, commits `65efdb1`
(D3) and `d056052` (D1 frontend pieces).

**Read these:**

1. `frontend/components/admin13f/Admin13FPrimitives.tsx` — `DrawerShell`
   with stable callback ref + explicit focus + restoration.
2. `frontend/components/watchlist/Watchlist13FDrawer.tsx` — find
   `QualityOverlaySection`. Note the new `(as of YYYY-MM-DD)` label
   inserted into the VL 18-month target line.
3. `frontend/lib/watchlist13f.ts` — the `quality_overlay` type now
   has 12 fields including `vl_target_period_end` and
   `vl_target_source_document_id`.

**Frontend-specific questions:**

### F1 — DrawerShell stable callback ref

```tsx
const onCloseRef = useRef(onClose);
useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if (e.key === 'Escape') onCloseRef.current();
  };
  document.addEventListener('keydown', handler);
  return () => document.removeEventListener('keydown', handler);
}, []);
```

- The two-effect pattern: the first effect updates `onCloseRef.current`
  on every render where `onClose` changes; the second (no-deps) effect
  registers the listener once. This is the React-recommended stable-
  callback pattern. Correct?
- Alternative: `useCallback` at the parent level so `onClose` itself is
  stable. Would moving the burden to callers be cleaner, or is the
  inside-DrawerShell pattern preferable?
- Under React StrictMode (development), the no-deps effect runs:
  mount → cleanup → mount. Each mount re-registers the document
  listener and each cleanup removes it. Net effect at the end of the
  StrictMode cycle is one active listener. Confirm this is what
  happens.

### F2 — Focus management

```tsx
const closeBtnRef = useRef<HTMLButtonElement>(null);
useEffect(() => {
  const previouslyFocused = document.activeElement as HTMLElement | null;
  closeBtnRef.current?.focus();
  return () => {
    previouslyFocused?.focus();
  };
}, []);
```

- Edge case: `document.activeElement` could be `<body>` if no element
  is focused when the drawer mounts. `body.focus()` is a no-op
  visually but doesn't throw. Acceptable?
- Edge case: if `previouslyFocused` is removed from the DOM while the
  drawer is open (e.g., parent re-renders the trigger button), the
  ref still points to the detached element. `detached.focus()` is a
  no-op. Acceptable, or should we re-query / fall back to a known
  focus target?
- Under StrictMode, the effect runs twice on mount. First run
  captures `previouslyFocused`, focuses close button. First cleanup
  restores focus to `previouslyFocused`. Second run captures the
  *now-refocused* `previouslyFocused` (same element), focuses close
  button. On real unmount: cleanup restores to `previouslyFocused`
  again. Result: correct behavior under StrictMode. Confirm.

### F3 — As-of label render

```tsx
{overlay.vl_target_period_end ? (
  <span className="text-muted-foreground/70">
    {' '}(as of {overlay.vl_target_period_end})
  </span>
) : null}
```

The label uses `text-muted-foreground/70` — 70% opacity of the
muted-foreground color. The parent line uses `text-xs
text-muted-foreground` (full muted intensity).

- The `/70` opacity reduction makes the date scan as auxiliary
  context. Intended hierarchy, or is the visual difference too subtle
  to be perceived?
- The date format is the raw ISO string `2026-02-13` (no localization,
  no "Feb 13, 2026"). For an internal admin/research tool this is
  fine, but if the surface goes to external users a localized format
  may be expected. Worth filing as a backlog item?

### F4 — TypeScript type maintenance

The frontend `quality_overlay` type now has 12 fields, hand-mirrored
from the backend Pydantic `QualityOverlay` model. Any backend addition
requires a matching frontend type update.

- Is this duplication acceptable for V1, or should the type be
  generated from OpenAPI (via openapi-typescript or similar)? File as
  backlog if generation is preferred.

### F5 — Source document ID not displayed

The API exposes `vl_target_source_document_id` but the drawer doesn't
render it. The provenance flows API → type → unused.

- Should the source_document_id surface in the UI (e.g., a tooltip
  or expand-to-see-source link)? Or is this a typed-but-not-yet-
  consumed field intentionally left for future surface evolution?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

F1: ...
F2: ...
F3: ...
F4: ...
F5: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.
