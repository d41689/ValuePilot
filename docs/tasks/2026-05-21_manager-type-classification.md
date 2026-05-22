# 2026-05-21 — Manager `manager_type` first-pass classification

Resolves the `docs/BACKLOG.md` item **"Manager `manager_type` classification
(all `unknown`)"** (medium, from the 2026-05-20 /admin/13f audit, item #9).

## Goal & authorization

All 86 `institution_managers` rows had `manager_type = unknown`, which feeds
Oracle's Lens signal weighting. The user explicitly authorized a **first-pass
machine classification written directly to the prod database**, accepting that
inaccurate rows would be corrected manually afterward.

## Method

Four stages, all reproducible from the committed scripts:

1. **Extract** (`backend/scripts/classify_managers_extract.py`, read-only) —
   dumped every manager + its 13F portfolio behaviour from the prod DB:
   holdings count, top-10 concentration, option usage, a turnover proxy, a
   trailing holding-period span. 86 managers; 59 have ingested 13F filings, 27
   do not.
2. **Research** — 15 web searches for the managers whose type is
   identity-driven (activists, quant, multi-strategy, high-turnover) rather
   than derivable from portfolio behaviour.
3. **Decide** (`backend/scripts/classify_managers_decide.py`) — produced
   `docs/tasks/2026-05-21_manager-type-classifications.json`.
4. **Apply** (`backend/scripts/classify_managers_apply.py`, run in the prod
   `api` container) — wrote each row through the audited
   `update_manager_type` service (column + `institution_manager_type_review_events`
   audit row, one transaction). `reviewed_by_user_id` is **NULL** — this is a
   machine pass, not a human review.

### The classification rule

The taxonomy has 8 values. Key fact: **`value_concentrated` and
`long_term_fundamental` both carry a 1.00 Oracle's Lens signal weight**, so the
split between them has *no scoring impact* — it is descriptive only. The
scoring-relevant calls are the off-1.00 types: `activist` 0.80,
`multi_strategy` 0.60, `quant` 0.40, `high_turnover` 0.30, `index_like` 0.10.

- **Explicit (38 managers)** — decided by web research, or, for the 27 managers
  with no ingested 13F holdings, by documented strategy. Hand-curated in
  `classify_managers_decide.py::EXPLICIT`.
- **Mechanical (48 managers)** — all are long-only fundamental value managers
  (the Dataroma "superinvestor" universe). The system's own behaviour rule is
  reused: top-10 weight ≥ 0.50 **and** ≤ 25 holdings → `value_concentrated`,
  else `long_term_fundamental`.

### The 10 scoring-relevant (off-1.00) classifications

| Manager | Type | Basis |
|---|---|---|
| Pershing Square, Icahn, Third Point, Engaged Capital, Trian, ValueAct | `activist` | documented activist hedge funds |
| Bridgewater Associates | `quant` | systematic global-macro, algorithmic |
| Appaloosa Management | `multi_strategy` | event-driven / distressed / credit / macro |
| Oaktree Capital | `multi_strategy` | credit / distressed / PE alternative manager |
| Scion Asset Management | `high_turnover` | Burry — ~250% churn, quarterly portfolio rebuilds |

Judgement calls worth noting: **TCI** (Chris Hohn) — activist heritage but the
current book is a stable concentrated quality-growth portfolio and Hohn calls
activism "opportunistic" → `value_concentrated`. The four **Tiger Cub** long/short
funds (Tiger Global, Maverick, Lone Pine, Viking) — fundamental bottom-up
stock-pickers, moderate turnover, not quant/activist → `long_term_fundamental`.

## Result

86 / 86 classified, 0 remain `unknown`. 86 audit rows written.

| Type | Count | Weight |
|---|---|---|
| `long_term_fundamental` | 44 | 1.00 |
| `value_concentrated` | 32 | 1.00 |
| `activist` | 6 | 0.80 |
| `multi_strategy` | 2 | 0.60 |
| `quant` | 1 | 0.40 |
| `high_turnover` | 1 | 0.30 |

Confidence: 78 high, 8 medium (TCI, the 4 Tiger Cubs, Makaira, Hillman, Torray —
judgement calls, incomplete data, or obscure with no 13F holdings).

## How the team reviews / corrects this

Every row is a first pass. To find them: `institution_manager_type_review_events`
rows with `reviewed_by_user_id IS NULL`, or `evidence_json->>'classified_by' =
'claude_first_pass'`; every note is prefixed
`[auto-classified by Claude, first pass — pending human review]`. Correct any
row via the admin manager-type editor — a human edit writes a new audit row
with a real `reviewed_by_user_id`, superseding the machine pass.

## Findings (deferred to `docs/BACKLOG.md`)

- **Duplicate managers** — 4 firms appear twice under different CIKs: Abrams
  Capital (ids 18 + 84), Akre Capital (15 + 81), Himalaya Capital (46 + 83),
  Baupost Group (63 + 85). Both rows of each pair were classified identically;
  a dedup/merge is a separate concern.
- **Makaira Partners (id 69)** — the prod extract returned only 1 holding
  (incomplete data); classified `value_concentrated` on documented strategy.
- **Vulcan Value (id 76)** — turnover proxy 0.97 looks like a CUSIP-remap
  artifact, not real churn; did not affect its classification (the rule uses
  concentration + holding count, not the turnover proxy).

## Verification

- Re-queried prod: 86 managers, 0 `unknown`; 86 audit events, all
  `reviewed_by_user_id` NULL, all `old=unknown`, all carrying the
  `claude_first_pass` evidence flag.
- The apply script is idempotent (`update_manager_type` no-ops on an unchanged
  value) and was dry-run first (86 rows, 0 unknown ids).
- `pytest -q` green — the new `backend/scripts/` files are standalone, not
  imported by the app or tests. Frontend untouched.

## Sign-off trail

- 2026-05-21 — extract → research (15 web searches) → decide → apply.
  86/86 written to prod and verified. First pass; team refines via the editor.
