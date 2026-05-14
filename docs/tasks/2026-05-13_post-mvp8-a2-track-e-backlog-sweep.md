# Post-MVP8-A2 + Track-E Backlog Sweep

## Status

**Open 2026-05-13.** Child of the MVP8-A2 + Track-E four-role review
(verdicts SME / Staff / Backend APPROVE WITH NOTES, Frontend REJECT
on F2 — already addressed in hardening commit `a51ffd7`). This ticket
bundles the **non-blocking** future-backlog items recorded in
`docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md` §Sign-Off Trail.

**Parent reviews / specs:**
- `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md`
- `docs/tasks/2026-05-13_mvp8-a2-track-e-review-prompts.md`

## Goal

Close the four backlog buckets from the review so the drawer M3 overlay
and DrawerShell primitive reach a clean steady state before any further
surface work. Strict scope: no new product features, no surface
extensions. Every D-section has its own root cause + fix contract + verify
step so items can ship sequentially or in one commit.

## D1 — Typed `QualityOverlay` schema + VL target as-of date

**Sources**: Backend B2, SME P2.

**Root cause**:
- `AvailableStockDetail.quality_overlay: Optional[dict]` at
  `backend/app/schemas/stocks_13f_snapshot.py:146` ships as untyped
  `dict`. Pydantic does not validate the shape; FastAPI's OpenAPI
  emits `{}`; the frontend type in `frontend/lib/watchlist13f.ts` is the
  only contract pin and can drift silently.
- The drawer displays VL targets with no as-of date. In the dev DB,
  ADBE has two `is_current=True` rows for `target.price_18m.mid` at
  different period_end_dates ($310 @ 2026-05-01, $538 @ 2025-01-31) —
  the query picks the most recent, but the user has no visibility into
  which cycle they're seeing. Stale VL targets viewed without a date
  label are materially misleading.

**Fix contract**:

- New Pydantic model `QualityOverlay` in
  `backend/app/schemas/stocks_13f_snapshot.py`. Shape matches the 10
  fields `_m3_panel_for_stock` already returns, plus two provenance
  fields:
  ```python
  class QualityOverlay(BaseModel):
      has_value_line: bool
      piotroski_score: int | None = None
      piotroski_max: int | None = None
      piotroski_status: Literal["partial", "complete"] | None = None
      earnings_predictability: float | None = None
      vl_target_mid: float | None = None
      vl_target_low: float | None = None
      vl_target_high: float | None = None
      vl_3y_low: float | None = None
      vl_3y_high: float | None = None
      # NEW: provenance for VL targets.
      vl_target_period_end: str | None = None   # ISO date of the VL doc period
      vl_target_source_document_id: int | None = None
  ```
- `AvailableStockDetail.quality_overlay: QualityOverlay | None = None`
  (replaces `Optional[dict]`).
- `_m3_panel_for_stock` (`backend/app/api/v1/endpoints/stocks_13f.py`)
  extends the return dict with the two provenance fields, sourced from
  the same `target.price_18m.mid` MetricFact that wins the tiebreak.
  Period_end is the row's `period_end_date.isoformat()`; source_doc_id
  is `fact.source_document_id`.
- Frontend `Watchlist13FAvailableDetail.quality_overlay` (in
  `frontend/lib/watchlist13f.ts`) gains the two new fields.
- `QualityOverlaySection` in `Watchlist13FDrawer.tsx` renders an inline
  `as of {vl_target_period_end}` label appended to the
  "VL 18-month target" line when `vl_target_period_end` is non-null.
  Format: `(as of 2026-05-01)` in muted text.

**Scope**:

- `backend/app/schemas/stocks_13f_snapshot.py` — new model + field swap.
- `backend/app/api/v1/endpoints/stocks_13f.py` —
  `_m3_panel_for_stock` extended; return type annotation updates.
- `frontend/lib/watchlist13f.ts` — type extension.
- `frontend/components/watchlist/Watchlist13FDrawer.tsx` —
  date label render.
- `backend/tests/unit/test_13f_mvp8_a2_m3_panel.py` —
  one test asserts `vl_target_period_end` populated when VL target
  exists; one test asserts both fields null when no VL data.

## D2 — Unify `_quality_overlay_by_stock` + `_m3_panel_for_stock`

**Source**: Staff Engineer A2.

**Root cause**: `_quality_overlay_by_stock` in
`backend/app/services/oracles_lens/dashboard.py:790` filters
`MetricFact.value_numeric.isnot(None)`. The `score.piotroski.total`
metric stores its composite score in `value_json['partial_score']`;
`value_numeric` is NULL for 269/272 rows in dev (only 3 rows have it
populated — likely a stale ingestion artifact). The legacy helper
silently drops all Piotroski data. `_m3_panel_for_stock` works around
this by reading `value_json` directly, creating two functions reading
the same table with opposite assumptions.

**Fix contract**:

- Extend `_quality_overlay_by_stock` to read Piotroski from
  `value_json['partial_score']` when `value_numeric` is null. Match the
  same `partial_score` / `max_available_score` / `status` extraction
  that `_m3_panel_for_stock` does today.
- Add a regression test asserting the legacy Oracle's Lens dashboard
  surfaces Piotroski for the 5 overlap stocks (ADBE, FICO, FNV, GOOG,
  MTDR) after the fix.
- Refactor `_m3_panel_for_stock` to call into a shared helper
  (`_m3_facts_by_stock(session, stock_id) -> dict[str, MetricFact]`)
  used by both functions, so the read logic exists once. The two
  functions diverge only in their response shapes.
- The shared helper lives in `oracles_lens/dashboard.py` next to the
  existing helpers; `stocks_13f.py` imports it. Resolves the "endpoint
  module imports `MetricFact` for raw ORM access" domain leak
  (Staff A1).

**Scope**:

- `backend/app/services/oracles_lens/dashboard.py` —
  `_quality_overlay_by_stock` value_json fallback + new
  `_m3_facts_by_stock` shared helper.
- `backend/app/api/v1/endpoints/stocks_13f.py` —
  `_m3_panel_for_stock` calls the shared helper; remove direct
  `MetricFact` import if no longer needed (`_M3_METRIC_KEYS` can move
  to the service module too).
- `backend/tests/unit/test_oracles_lens.py` (or a new test file) —
  regression test that legacy Oracle's Lens dashboard includes
  Piotroski for stocks where the score is in `value_json`.
- `backend/tests/unit/test_13f_mvp8_a2_m3_panel.py` — no behavior
  change; tests must still pass.

## D3 — DrawerShell stable-callback + explicit focus + focus restoration

**Sources**: Frontend F3, F4.

**Root cause**:
- `DrawerShell` in `frontend/components/admin13f/Admin13FPrimitives.tsx`
  registers a `document.addEventListener('keydown', handler)` in a
  `useEffect` with `[onClose]` as the dependency. Current callers
  (`Watchlist13FDrawer`, admin/13f/jobs, admin/13f/holdings,
  admin/13f/filings) pass `onClose` as an inline arrow
  `onClose={() => setX(null)}` — a new function identity per parent
  render. The effect tears down + re-registers on every parent
  re-render. Functionally correct (cleanup runs first, no listener
  leak), but wasteful under React Query polling or parent input
  re-renders.
- `autoFocus` on the close button moves focus into the dialog on mount
  but does not run reliably under React StrictMode (double-mount) and
  has no symmetric focus-restoration. When the drawer closes, focus
  is dropped (lands on `<body>`) instead of returning to the row
  button that opened it — a WCAG 2.4.3 gap.

**Fix contract**:

- `DrawerShell` introduces a `useRef` for `onClose` so the keydown
  effect captures a stable reference and registers exactly once per
  mount:
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
- Drop `autoFocus` on the close button. Replace with an explicit
  `useRef<HTMLButtonElement>` + `useEffect(() => ref.current?.focus(), [])`
  pattern that runs reliably under StrictMode.
- Capture the previously-focused element on mount and restore focus on
  unmount:
  ```tsx
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeBtnRef.current?.focus();
    return () => { prev?.focus(); };
  }, []);
  ```
- No new prop surface — the focus-restoration is transparent to
  callers.

**Scope**:

- `frontend/components/admin13f/Admin13FPrimitives.tsx` — only file.
- No new tests (a11y behavior verified manually: open drawer →
  Tab/Shift+Tab cycles inside, Escape closes, close button receives
  initial focus, focus returns to opener button on close).

## D4 — `metric_facts` `is_current` ingestion dedup

**Status: DEFERRED 2026-05-13 to design gate
`docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`.
This sweep ticket no longer implements D4.**

**Why the original framing was wrong:**

The spec's premise — "at most one `is_current=True` row per
`(stock_id, metric_key)`" — assumed the duplicates were a VL parser
bug. Pre-implementation investigation against the dev DB showed the
duplicates are **intentional fiscal-period time series**, not a parser
defect:

| Metric | is_current rows | distinct stocks | extra per-stock |
|---|---|---|---|
| `per_share.eps` | 194 | 7 | ≈27/stock |
| `is.net_income` | 86 | 7 | ≈11/stock |
| `score.piotroski.total` | 74 | 6 | ≈11/stock |

ADBE has 42 `is_current=True` rows for `per_share.eps` — one for
each fiscal year of Value Line history. The existing
`_reconcile_parsed_fact_current_slot` in `ingestion_service.py:953`
enforces uniqueness scoped to
`(stock_id, metric_key, period_type, period_end_date, source_type)`.
The two ADBE `target.price_18m.mid` rows that triggered the review
have **different** `period_end_date`s (2025-01-31 and 2026-05-01) —
both correctly current under the per-period semantics.

The real issue is a schema-semantics conflict between two kinds of
metrics that share the same `is_current` column:

- **Fiscal time series** (`per_share.eps`, `is.net_income`,
  `score.piotroski.total`, etc.): per-period currency is correct —
  each FY/Q row is genuinely "current for that period".
- **Opinion / as-of** (`target.price_18m.*`, `proj.long_term.*`,
  `quality.earnings_predictability`, etc.): `period_end_date` is
  effectively the VL publication date; older targets shouldn't
  remain "current" once a newer publication supersedes them.

Implementing D4 literally (global uniqueness per `(stock_id,
metric_key)`) would wipe out 99% of the time series. Narrowing it to
an opinion-metric allowlist requires a schema-level contract change.
Both belong in a proper design gate, not a Track-E sweep.

**Display-layer guard retained**: The M3 panel's
`_m3_facts_by_stock` tiebreak ordering
(`period_end_date DESC NULLS LAST, created_at DESC`) correctly picks
the most recent VL target / projection at read time. No drawer
regression from leaving the duplicates in place.

**MVP8-A2 P2 backlog (VL target as-of date)** ships independently
via D1 of this sweep — D1 reads the existing `period_end_date`
column for the winning fact and renders it as
`(as of YYYY-MM-DD)`. No schema change required.

## Scope Out (this ticket)

- New product features on the drawer or Oracle's Lens page.
- Persisted scoring path changes (MVP8-01 Phase 3 stays frozen).
- MVP8-02 base divergence — observation-window-gated.
- Manager-name truncate (Track-E E-02) — already shipped at `2f18e2c`.
- Accession URL CIK threading (Track-E E-03) — already shipped at
  `2f18e2c`.
- F1 piotroski tone, P3 wording, F2 URL validation — already shipped at
  `a51ffd7`.

## Verification Plan

- `docker compose exec api pytest -q` — full suite green.
- `docker compose exec web npm run lint` — clean.
- `docker compose exec web npm run build` — clean.
- D1 curl probe:
  ```
  curl /api/v1/stocks/1254/13f-detail | jq .detail.quality_overlay
  ```
  → `vl_target_period_end` is an ISO date string when VL data exists;
  `null` when not.
- D2 regression: legacy Oracle's Lens dashboard
  (`GET /api/v1/admin/13f/oracles-lens`) returns Piotroski in the
  quality overlay for ADBE, FICO, GOOG (where the score is in
  `value_json`).
- D3 manual probe: open `/watchlist` drawer →
  (a) Tab from a row button into the drawer → focus lands on close
  button;
  (b) Escape closes drawer → focus returns to the row button;
  (c) parent state churn (e.g., typing in a sibling input) does not
  trigger DrawerShell keydown re-registration (verify with React
  DevTools Profiler or a `console.log` in the effect).
- D4 SQL check:
  ```sql
  SELECT stock_id, metric_key, COUNT(*) AS dups
  FROM metric_facts
  WHERE is_current = TRUE
  GROUP BY stock_id, metric_key
  HAVING COUNT(*) > 1;
  ```
  → returns zero rows after cleanup migration.

## Files Expected to Change

- `backend/app/schemas/stocks_13f_snapshot.py`
- `backend/app/api/v1/endpoints/stocks_13f.py`
- `backend/app/services/oracles_lens/dashboard.py`
- `backend/app/services/<vl_parser>.py` (D4)
- `backend/scripts/` or `backend/migrations/versions/` (D4 cleanup)
- `backend/tests/unit/test_13f_mvp8_a2_m3_panel.py` (D1 tests)
- `backend/tests/unit/test_oracles_lens.py` (D2 regression)
- `backend/tests/unit/test_<vl_parser>.py` (D4 regression)
- `frontend/lib/watchlist13f.ts`
- `frontend/components/watchlist/Watchlist13FDrawer.tsx`
- `frontend/components/admin13f/Admin13FPrimitives.tsx`
- `docs/tasks/2026-05-13_post-mvp8-a2-track-e-backlog-sweep.md` (this)

## Sign-Off Trail

- [ ] D1 typed `QualityOverlay` schema + VL target as-of date shipped.
- [x] D2 shipped 2026-05-13: `_quality_overlay_by_stock` reads
      `value_json['partial_score']` for Piotroski via the extended
      `_fact_value` fallback; shared `_m3_facts_by_stock(session,
      stock_ids, metric_keys)` helper added to
      `oracles_lens/dashboard.py`; `_m3_panel_for_stock` in
      `stocks_13f.py` calls the shared helper (drops direct `MetricFact`
      import); regression test
      `test_oracles_lens_reads_piotroski_from_value_json_when_value_numeric_null`
      asserts Piotroski surfaces with `value_numeric=NULL` +
      `value_json['partial_score']=6`. pytest 822 passed.
- [x] D3 shipped 2026-05-13: DrawerShell uses `useRef<onClose>` stable
      callback (keydown listener registers once per mount instead of
      every parent re-render); `useRef<HTMLButtonElement>` + explicit
      `useEffect` focus call replaces `autoFocus` (StrictMode-safe);
      previously-focused element captured on mount and restored on
      unmount (WCAG 2.4.3 Focus Order). No new prop surface; no test
      changes (manual a11y verification). lint + build clean.
- [x] D4 deferred 2026-05-13 — pre-implementation investigation showed
      the duplicates are intentional fiscal-period time series, not a
      parser bug. Implementing the spec literally would wipe ~99% of
      `metric_facts` time-series rows. Schema-semantics conflict
      between fiscal and opinion metrics escalated to design gate
      `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md`.
      M3 panel tiebreak ordering retained as display-layer guard for
      VL target staleness.
- [ ] pytest -q green; lint + build clean.
- [ ] Four-role review pass (optional — bundled small sweep, may be
      single-reviewer if no domain shift).
- [ ] **Post-MVP8-A2 + Track-E Backlog Sweep closed.**
