# PR #33 Release Note — Template

**Status**: DRAFT TEMPLATE. Structure, risk language, channels, and decision branches are locked. Final release note is blocked on D2 + D5 production values landing — the placeholders below must be replaced with real numbers before this is sent to any channel.

**When this template activates**: after the operator runs the N4 D2 + D5 prod execution recipes against the staging clone and pastes the verdicts into the N4 sign-off trail. At that point, the operator (or PO) walks through this template, fills in the placeholders, picks the right framing tier, and publishes to each channel.

**Do NOT publish this template as-is.** The placeholders look like `<...>` and the decision branches use `[option A | option B]` syntax. Both must be resolved before send.

---

## 0. Placeholder inputs

Filled in by the operator after D2 + D5 prod execution. Source the values from `/tmp/d2-prod-comparison-<TS>.json` (D2 recipe output) and `/tmp/d5-prod-vl-coverage-<TS>.txt` (D5 recipe output).

| Placeholder | Source | Example dev value |
|---|---|---|
| `<TOTAL_STOCKS_COMPARED>` | D2 JSON `.total_stocks_compared` | 240 |
| `<TOP10_SWAP_COUNT>` | D2 JSON `.top10_swap_count` | 0 |
| `<PERSISTED_ONLY_COUNT>` | D2 JSON `.persisted_only_count` | 0 |
| `<MAGNITUDE_DIFF_COUNT>` | D2 JSON `.magnitude_diff_count` | 59 |
| `<RANKED_WITH_M3>` | D5.6 result | 3 |
| `<TOTAL_RANKED>` | D5.5 result | 240 |
| `<COVERAGE_PCT>` | `<RANKED_WITH_M3>` / `<TOTAL_RANKED>` × 100, rounded to 1 decimal | 1.25% |
| `<COVERAGE_TIER>` | Picked per D5 interpretation guide | "small curated subset" |
| `<DEPLOY_VERDICT>` | D2 recipe's final line | `DEPLOY-SAFE` |
| `<DEPLOY_DATE>` | The date the merge-to-main happens (auto-deploys) | TBD |

---

## 1. Decision branches (resolve BEFORE filling placeholders)

### 1A — Deploy verdict from D2

```
IF <DEPLOY_VERDICT> == "DEPLOY-SAFE":
    Proceed with this template. Section 2 applies.
ELIF <DEPLOY_VERDICT> == "HOLD DEPLOY":
    DO NOT use this template. The release is held; no user-facing
    note is required. File a new task at
    docs/tasks/YYYY-MM-DD_pr33-d2-divergence.md documenting the
    failure mode and the investigation plan instead.
```

### 1B — Coverage framing tier from D5

```
ratio = <RANKED_WITH_M3> / <TOTAL_RANKED>

IF ratio <= 0.05:    <COVERAGE_TIER> = "small curated subset"
ELIF ratio <= 0.25:  <COVERAGE_TIER> = "meaningful minority"
ELSE:                <COVERAGE_TIER> = "broad coverage"
```

Use the corresponding pre-written sentence from §2.3 ("Limitations") below — do not freelance new framing language; the three tiers were calibrated against the missing-data-honesty contract.

---

## 2. Channel-specific release notes

Three audiences. Each gets a different length and register. Send all three on `<DEPLOY_DATE>`.

### 2.1 Internal team channel (Slack / Discord webhook)

Concise, technical-aware. Posted to the operations channel by the deploy operator.

```
:rocket: PR #33 deployed <DEPLOY_DATE>

What changed:
• Watchlist now has 13F insight columns (Conviction / Δ Holders /
  Distinctiveness / Caveats), click-to-sort, and a per-row drawer
  with Quality & Valuation overlay.
• Oracle's Lens scoring uses the persisted formula by default. Phase
  1 comparison vs prod (2025-Q3): top10_swap_count=<TOP10_SWAP_COUNT>,
  persisted_only_count=<PERSISTED_ONLY_COUNT>,
  total_stocks_compared=<TOTAL_STOCKS_COMPARED>,
  magnitude_diff_count=<MAGNITUDE_DIFF_COUNT> (informational,
  documented base-formula divergence).
• Absolute scores now ~70% of pre-flip values (rankings stable per
  the comparison report). MVP8-02 will resolve the magnitude shift.

Coverage: VL quality/valuation overlay is available for a
<COVERAGE_TIER> of stocks (<RANKED_WITH_M3>/<TOTAL_RANKED> =
<COVERAGE_PCT>). The drawer shows "Value Line data is not available
for this stock in the current dataset" for the rest.

Mobile: 13F columns hide below the `md` breakpoint; mobile stacked
view is the next ticket (N1 in the open-work snapshot).

Rollback: `?use_persisted_scores=false` per-request escape, or
application code revert if needed. See
docs/runbooks/phase3-scoring-rollback.md.
Do NOT use alembic downgrade for this rollback.
```

### 2.2 API consumer changelog entry

Formal, structured. Goes to the API changelog page (or equivalent docs surface).

```markdown
## <DEPLOY_DATE> — Oracle's Lens Phase 3 + Watchlist 13F Insight

### Added

- `POST /api/v1/stocks/13f-snapshots` — batch endpoint returning 13F
  insight columns (Conviction percentile, Δ Holders, Distinctiveness
  tier, Caveat severity) for a requested stock set.
- `GET /api/v1/stocks/{stock_id}/13f-detail` — detail payload with
  top-3 holders, caveat flags, and the M3 Quality & Valuation overlay
  (Piotroski score, Value Line price targets, earnings predictability)
  when Value Line data is available for that stock.

### Changed

- `GET /api/v1/13f/oracles-lens`, `POST /api/v1/stocks/13f-snapshots`,
  `GET /api/v1/stocks/{stock_id}/13f-detail`: `use_persisted_scores`
  query parameter default flipped from `false` to `true`. Scores now
  read from the persisted `oracles_lens_signals` rows by default.
  Rankings are stable vs the legacy formula (Phase 1 comparison vs
  2025-Q3 production data: `top10_swap_count=<TOP10_SWAP_COUNT>`).
  Absolute score magnitudes are ~70% of the pre-flip legacy values —
  this is the documented base-formula divergence and will be
  resolved by MVP8-02.

### Deprecated

- `?use_persisted_scores=false` on the three endpoints above remains
  available during the observation window as an escape hatch. It
  will be retired in a future release (Phase 4) after one full
  scoring cycle without ranking regression.

### Coverage limitations

- Quality & valuation overlay (Piotroski, Value Line price targets,
  earnings predictability) is available for a <COVERAGE_TIER> of
  ranked stocks (<RANKED_WITH_M3>/<TOTAL_RANKED> = <COVERAGE_PCT>).
  Stocks without Value Line coverage return
  `quality_overlay.has_value_line=false`. This is by design (Value
  Line ingestion is curated, not exhaustive); coverage expansion is
  on the roadmap.

### Migration / compatibility

- No breaking changes to existing endpoint shapes. New fields on
  `AvailableStockDetail`: `quality_overlay`, `top_holders[].cik`.
```

### 2.3 Watchlist user notice (in-app banner / email)

Plain language, no jargon, no internal flag names. The user does not need to know about `use_persisted_scores`.

```
What's new in your watchlist (<DEPLOY_DATE>)

We've added 13F signals to your watchlist rows so you can see at a
glance which stocks are held — and being added or trimmed — by the
superinvestors you follow.

Each row now shows four new columns:
• Conviction — how strongly the consensus favors this stock.
• Δ Holders — how many superinvestors added or reduced this quarter.
• Distinctiveness — whether the position is distinctive, mixed, or
  crowded among the universe.
• Caveats — flags for signals that warrant extra care.

Click any row to open a detail panel with the top holders and, when
we have Value Line coverage for the stock, a compact Quality &
Valuation overlay (Piotroski F-Score, 18-month price target, and
earnings predictability).

A few honest caveats:

• Value Line quality & valuation data is currently available for a
  <COVERAGE_TIER> of stocks. Most rows will show "Value Line data
  is not available for this stock in the current dataset" in the
  detail panel — that's accurate, not a bug. We're expanding
  coverage; this is the curated baseline.

• On mobile, the 13F columns are hidden because they need horizontal
  space to be readable. A mobile-friendly stacked view is the next
  feature we're shipping.

• Our scoring formula was updated in the background. Stock rankings
  are stable, but absolute score numbers may look smaller than
  before — that's expected (the formula uses a more conservative
  base now). What ranks first today should still rank first.

Questions or something looking off? [Contact link / Feedback button].
```

---

## 3. Pre-publish checklist

Before sending, the operator confirms:

- [ ] All `<...>` placeholders replaced with real D2/D5 values.
- [ ] `<COVERAGE_TIER>` chosen per the §1B decision branch (not freelanced).
- [ ] §2.1 internal note posted to the operations channel.
- [ ] §2.2 changelog entry committed to the API docs surface.
- [ ] §2.3 user notice published per the chosen channel (in-app banner OR email; not both unless the team has decided to do both).
- [ ] N4 sign-off trail D4 entry references this published note (paste the final §2.3 text into the trail so the audit captures what users saw).
- [ ] If `<DEPLOY_VERDICT>` was `HOLD DEPLOY` (per §1A), do NOT publish; instead file the divergence task.

---

## 4. Activation status

This template is currently **NOT ACTIVATED**. Activation requires:

- [x] Template structure drafted (this file, 2026-05-18).
- [ ] D2 prod execution complete (`<TOP10_SWAP_COUNT>` value available).
- [ ] D5 prod execution complete (`<RANKED_WITH_M3>` / `<TOTAL_RANKED>` available).
- [ ] D3 runbook reviewed by PO + backend (rollback path validated).
- [ ] PO approves the channel send.
- [ ] Operator fills placeholders and resolves decision branches.

Until all of the above are checked, this file is a template. The N4 D4 sign-off remains `[ ]`.
