# MVP8-A2 + Track-E Four-Role Review Prompts

Four reviewer prompts for the MVP8-A2 (Watchlist drawer M3 overlay) and
Track-E (a11y sweep, manager name truncate, accession CIK link, DrawerShell
Escape) closing review. Each prompt is self-contained.

**Branch**: `docs/13f-automation-prd`
**Commits under review**:
- `f2949d6` — MVP8-A2: Watchlist 13F drawer M3 quality/valuation overlay
- `2f18e2c` — Track-E: a11y sweep, manager name truncate, accession CIK link, DrawerShell Escape

**Specs**:
- `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md`
- `docs/tasks/2026-05-13_pre-mvp8-a2-oracles-lens-m3-decision-gate.md`
- `docs/tasks/2026-05-12_post-mvp4-roadmap.md` §Track-E

Roles (priority order):

1. **13F Domain SME — HIGH.** Product intent for the M3 drawer overlay and
   data honesty (missing-data treatment, Piotroski display).
2. **Staff Engineer — MEDIUM.** Architecture: M3 panel placement, CIK
   threading design, a11y completeness.
3. **Backend Reviewer — MEDIUM.** `_m3_panel_for_stock` query, CIK
   threading, test coverage.
4. **Frontend Reviewer — MEDIUM.** QualityOverlaySection render, URL
   validation, TypeScript types, a11y attributes, Escape/focus.

---

## 1. 13F Domain SME Prompt

You are the 13F domain SME conducting the closing review for two
ValuePilot tickets: MVP8-A2 (Watchlist drawer M3 overlay) and
Track-E (engineering debt sweep). Branch is `docs/13f-automation-prd`,
commits `f2949d6` and `2f18e2c`.

**Read these files in order:**

1. `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md` — full spec
   (D1–D4 PO decisions, data sources, display contract, scope-out list).
2. `docs/tasks/2026-05-13_pre-mvp8-a2-oracles-lens-m3-decision-gate.md` —
   the decision gate that locked the scope (Option B: Watchlist drawer
   only, no persisted scoring path, explicit missing-data treatment).
3. `frontend/components/watchlist/Watchlist13FDrawer.tsx` — find the new
   `QualityOverlaySection` component (added after the Summary section, before
   Top Holders). Read both the has-data and no-data render paths.
4. `frontend/lib/watchlist13f.ts` — `Watchlist13FAvailableDetail` type, the
   new `quality_overlay` field shape, and `Watchlist13FTopHolder.cik`.

**Four product questions to answer:**

### M3 — Quality & Valuation panel

**P1 — Piotroski display.**
The panel shows Piotroski as `"{score}/{max}*"` (e.g. `"6/7*"`) with a
footnote `"* Partial score — one or more Piotroski indicators missing from
available Value Line data."` when `piotroski_status === 'partial'`. In the
dev DB all stocks have `status: 'partial'` because the VL proxy calculation
is missing the `current_ratio_improving` indicator.

Is `"6/7*"` (partial out of max available, not out of 9) the right label?
Or should it always display against the full 9-indicator scale even when
some indicators are structurally unavailable via VL data? What does "partial"
communicate to a research user vs. what they might infer?

**P2 — VL target staleness.**
The drawer shows the most-recent `is_current=True` VL target — it does NOT
show the target's as-of date or source document date. In the dev DB, some
stocks have two `is_current=True` rows for the same metric (the query picks
the first one by `period_end_date DESC, created_at DESC`). Is showing the
target without a date label acceptable for V1, or is a "as of YYYY-Q*"
label needed to prevent users from treating a stale target as current?

**P3 — Missing-data wording.**
When no VL data exists the panel shows:
`"Value Line data not yet available for this stock."`

Does this wording correctly set expectations? Could a user interpret
"not yet available" as "coming soon for this stock" when in fact some
stocks may never receive VL coverage? Suggest alternative wording if
the current text is misleading.

**P4 — EDGAR accession link (Track-E E-03).**
The Top Holders section previously showed `accession_no` as plain text.
It now renders as a clickable link to the EDGAR filing index:
`https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_no_dashes}/{accession_no_no_dashes}-index.htm`

Is this the most useful EDGAR URL for research workflows, or would a
different entry point (e.g. the EDGAR full-text search, the company filing
page) be more valuable?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

P1: ...
P2: ...
P3: ...
P4: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.

---

## 2. Staff Engineer Prompt

You are the Staff Engineer conducting the closing review for MVP8-A2 and
Track-E on branch `docs/13f-automation-prd` (commits `f2949d6`, `2f18e2c`).

**Read these files:**

1. `docs/tasks/2026-05-13_mvp8-a2-watchlist-m3-overlay.md` — spec.
2. `backend/app/api/v1/endpoints/stocks_13f.py` — find `_M3_METRIC_KEYS`,
   `_m3_panel_for_stock()`, and the `read_stock_13f_detail` call site
   where `quality_overlay=_m3_panel_for_stock(db, stock_id)` is passed.
3. `backend/app/services/oracles_lens/dashboard.py` — find the
   `ManagerHolding` dataclass (new `cik: str | None = None` field) and
   `_stock_payload` top_holders dict (new `"cik": item.cik` entry).
4. `frontend/components/admin13f/Admin13FPrimitives.tsx` — the updated
   `DrawerShell` with `useEffect` Escape listener and `autoFocus` on close
   button.
5. `frontend/components/admin13f/ManagerTypeEditorDialog.tsx` — evidence
   URL validation via `new URL()` constructor + `aria-invalid`.

**Architectural questions:**

**A1 — `_m3_panel_for_stock` placement.**
The function lives in `backend/app/api/v1/endpoints/stocks_13f.py` (the
endpoint file), not in a service module. It imports `MetricFact` directly
and runs its own ORM query. This is intentional: the function is a
13-line query wrapper specific to the drawer use case and has no other
callers. Is this placement acceptable, or should it move to a service
module (e.g. `app/services/oracles_lens/`) given that it accesses
`metric_facts` — the same table that `_quality_overlay_by_stock` in
`dashboard.py` accesses?

**A2 — Why not reuse `_quality_overlay_by_stock`?**
The existing `_quality_overlay_by_stock` (in `oracles_lens/dashboard.py`)
filters `MetricFact.value_numeric.isnot(None)`. But `score.piotroski.total`
stores its score in `value_json['partial_score']` — `value_numeric` is
NULL for 272/272 rows in the dev DB (only composite scores use value_json).
`_m3_panel_for_stock` reads from `value_json` instead. Is this the right
divergence point, or should `_quality_overlay_by_stock` be fixed to also
read Piotroski from `value_json`? If fixed, would the two functions merge?

**A3 — CIK threading depth.**
CIK is now threaded through: `ManagerHolding.cik` → `_stock_payload`
top_holders dict → `StockDetailTopHolder.cik` → `Watchlist13FTopHolder.cik`
→ `TopHolderCard` EDGAR URL. The `_load_holdings` function already queries
`InstitutionManager.cik` (it was already in the filter
`.filter(InstitutionManager.cik.isnot(None))`), so `manager.cik` is
always non-null for any row that reaches `ManagerHolding`. Despite this,
`cik: str | None = None` is typed as optional. Is the optionality correct
(defensive for future callers) or should it be `str` given the filter
guarantees it?

**A4 — DrawerShell Escape cleanup.**
The `useEffect` in `DrawerShell` adds a `keydown` listener on `document`
and removes it on cleanup. When multiple `DrawerShell` instances are
mounted simultaneously (e.g. a drawer is opened while a dialog overlay is
also open), both will fire on Escape. Is this a real risk in the current UI,
or are all overlay patterns mutually exclusive?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

A1: ...
A2: ...
A3: ...
A4: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.

---

## 3. Backend Reviewer Prompt

You are the backend engineer conducting the closing review for MVP8-A2 and
Track-E on branch `docs/13f-automation-prd` (commits `f2949d6`, `2f18e2c`).

**Read these files:**

1. `backend/app/api/v1/endpoints/stocks_13f.py` — the full
   `_m3_panel_for_stock()` function and the update to
   `_top_holder_from_payload` (new `cik` extraction).
2. `backend/app/schemas/stocks_13f_snapshot.py` — `StockDetailTopHolder`
   gains `cik: Optional[str] = None`; `AvailableStockDetail` gains
   `quality_overlay: Optional[dict] = None`.
3. `backend/app/services/oracles_lens/dashboard.py` — `ManagerHolding`
   dataclass gains `cik: str | None = None`; `_load_holdings` sets
   `cik=manager.cik`; `_stock_payload` includes `"cik": item.cik` in
   top_holders.
4. `backend/tests/unit/test_13f_mvp8_a2_m3_panel.py` — three new tests:
   `test_m3_panel_returns_has_value_line_false_when_no_facts`,
   `test_m3_panel_returns_populated_panel_with_vl_facts`,
   `test_m3_panel_handles_piotroski_only_without_other_facts`.

**Backend-specific questions:**

**B1 — Query ordering in `_m3_panel_for_stock`.**
The query orders by:
```python
MetricFact.metric_key.asc(),
MetricFact.period_end_date.desc().nullslast(),
MetricFact.created_at.desc(),
```
Then takes `by_key: dict[str, MetricFact]` — first-seen per metric_key
(most-recent period). In the dev DB, ADBE has two `is_current=True` rows
for `target.price_18m.mid` (values $538 and $310 from two different VL
documents). The query picks $310 (most-recent `period_end_date`). Is
`period_end_date DESC` the right tiebreak for VL targets? Or should it
be `created_at DESC` (most-recently ingested document wins)?

**B2 — `quality_overlay: Optional[dict]`.**
The schema field is untyped `dict`. This means Pydantic will serialize
whatever Python dict `_m3_panel_for_stock` returns without shape
validation. If the function adds a new key in the future, the API
response changes silently. Is this acceptable for an internal-use overlay
field, or should a typed `QualityOverlay` Pydantic model be defined now?

**B3 — Test fixture: `MetricFact.user_id`.**
`MetricFact` requires `user_id` (non-nullable FK to `users`). The test
file creates a fresh `User` per test. The existing `test_oracles_lens.py`
uses a `_test_user_id` convention (attached to the `Stock` object). The
new test file uses a direct `_user()` helper. Both work but are
inconsistent. Is this worth consolidating, or is the inconsistency
acceptable given tests are isolated?

**B4 — CIK `Optional[str]` on `StockDetailTopHolder`.**
`_load_holdings` already filters `.filter(InstitutionManager.cik.isnot(None))`
before constructing `ManagerHolding`, so `item.cik` is never `None` for
any qualifying holder. `StockDetailTopHolder.cik` is typed `Optional[str]`
anyway (defensive). Should the field be `str` instead, matching the
DB guarantee? Or is defensive typing correct here?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

B1: ...
B2: ...
B3: ...
B4: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

Be terse.

---

## 4. Frontend Reviewer Prompt

You are the frontend engineer conducting the closing review for MVP8-A2 and
Track-E on branch `docs/13f-automation-prd` (commits `f2949d6`, `2f18e2c`).

**Read these files:**

1. `frontend/components/watchlist/Watchlist13FDrawer.tsx` — the new
   `QualityOverlaySection` component and the updated `TopHolderCard`
   accession URL logic.
2. `frontend/lib/watchlist13f.ts` — new `quality_overlay` field on
   `Watchlist13FAvailableDetail`; new `cik` field on
   `Watchlist13FTopHolder`.
3. `frontend/components/admin13f/ManagerTypeEditorDialog.tsx` — the
   updated evidence URL validation (IIFE `new URL()` check),
   `aria-invalid`, `aria-describedby`, inline error paragraph,
   `aria-required` on Textarea.
4. `frontend/components/admin13f/Admin13FPrimitives.tsx` — `DrawerShell`
   Escape key `useEffect` and `autoFocus` on close button.
5. `frontend/app/(dashboard)/admin/13f/managers/page.tsx` — manager name
   `truncate` + `title` tooltip in the table cell.

**Frontend-specific questions:**

**F1 — `QualityOverlaySection` piotroski badge tone.**
The tone function is:
```tsx
const piotroskiTone = (score, max) => {
  if (score == null || max == null || max === 0) return 'outline';
  const ratio = score / max;
  if (ratio >= 0.78) return 'success';
  if (ratio >= 0.56) return 'secondary';
  return 'outline';
};
```
Thresholds: ≥78% → success, ≥56% → secondary, <56% → outline.
These are arbitrary. Should a low Piotroski be `'danger'` or `'warning'`
instead of `'outline'`, so a score of 2/8 visually signals concern?
The Oracle's Lens product plan (§3, §4) says "show disconfirming
evidence next to positive evidence." A low score that looks neutral
(outline) may under-signal.

**F2 — Evidence URL validation via IIFE.**
The validation is:
```tsx
const evidenceUrlInvalid =
  evidenceUrl.trim() !== '' && (() => {
    try { new URL(evidenceUrl.trim()); return false; }
    catch { return true; }
  })();
```
The `URL` constructor accepts strings like `"ftp://example.com"` and
`"javascript:alert(1)"` as valid. For an internal admin tool where the
URL is stored in `evidence_json` for audit purposes, is `URL` constructor
validation sufficient? Or should it be tightened to `https?://` only?

**F3 — DrawerShell `useEffect` dependency array.**
```tsx
useEffect(() => {
  const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
  document.addEventListener('keydown', handler);
  return () => document.removeEventListener('keydown', handler);
}, [onClose]);
```
`onClose` is in the dependency array. If the parent component does not
memoize its `onClose` callback, this effect will re-register the listener
on every render (add → cleanup → add). In the current callers
(`Watchlist13FDrawer`, admin `jobs/page.tsx`, etc.), is `onClose` stable
across renders (defined as a setter or inline arrow function)?

**F4 — `autoFocus` on DrawerShell close button.**
`autoFocus` moves focus to the close button when the drawer mounts. This
is a valid a11y pattern for dialogs (WCAG 2.1 SC 2.4.3). However,
`autoFocus` has known issues in some React re-render scenarios (double
mount in StrictMode, portals). Is `autoFocus` sufficient here, or should
a `useRef` + `ref.current.focus()` in a `useEffect` be used for
reliability?

**F5 — Accession URL format.**
The EDGAR URL constructed is:
```
https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no.replaceAll('-', '')}/{accession_no}-index.htm
```
For example: CIK `1234567`, accession `0001234567-24-001234` →
`https://www.sec.gov/Archives/edgar/data/1234567/000123456724001234/0001234567-24-001234-index.htm`

Is this URL format stable? EDGAR's filing index URLs have been stable for
years, but the `-index.htm` suffix is not always present (some older
filings use `.txt`). Is a fallback needed, or is `-index.htm` reliable
enough for 13F filings from 2020 onward?

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
