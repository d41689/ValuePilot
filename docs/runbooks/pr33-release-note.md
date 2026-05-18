# PR #33 Release Note (final draft)

**Status**: ENGINEERING-DRAFT COMPLETE. Placeholders filled with PO-accepted dev evidence (treated as production-equivalent per PO direction 2026-05-18: "我们的生产数据库和 dev 数据库没有明显的区别"). Awaiting PO approval to publish + a confirmed `<DEPLOY_DATE>`.

**Template source**: `docs/runbooks/pr33-release-note-template.md` (structure / decision branches / placeholder slots locked there; reusable for future similar releases).

**Resolved values**:

| Placeholder | Value | Source |
|---|---|---|
| `<TOTAL_STOCKS_COMPARED>` | 240 | D2 dev pre-flight |
| `<TOP10_SWAP_COUNT>` | 0 | D2 dev pre-flight |
| `<PERSISTED_ONLY_COUNT>` | 0 | D2 dev pre-flight |
| `<MAGNITUDE_DIFF_COUNT>` | 59 | D2 dev pre-flight |
| `<RANKED_WITH_M3>` | 3 | D5 dev baseline |
| `<TOTAL_RANKED>` | 240 | D5 dev baseline |
| `<COVERAGE_PCT>` | 1.25% | computed |
| `<COVERAGE_TIER>` | "small curated subset" | D5 interpretation guide (1.25% ≤ 5%) |
| `<DEPLOY_VERDICT>` | DEPLOY-SAFE | all three D2 gates pass |
| `<DEPLOY_DATE>` | TBD | set at merge time |

§1A decision (D2 verdict = `DEPLOY-SAFE`) → proceed with template §2 sections below.

---

## §2.1 Internal team channel (Slack / Discord webhook)

```
:rocket: PR #33 deployed <DEPLOY_DATE>

What changed:
• Watchlist now has 13F insight columns (Conviction / Δ Holders /
  Distinctiveness / Caveats), click-to-sort, and a per-row drawer
  with Quality & Valuation overlay.
• Oracle's Lens scoring uses the persisted formula by default. Phase
  1 comparison vs 2025-Q3 production-equivalent data:
  top10_swap_count=0, persisted_only_count=0,
  total_stocks_compared=240, magnitude_diff_count=59 (informational,
  documented base-formula divergence).
• Absolute scores now ~70% of pre-flip values (rankings stable per
  the comparison report). MVP8-02 will resolve the magnitude shift.

Coverage: VL quality/valuation overlay is available for a small
curated subset of stocks (3/240 = 1.25%). The drawer shows "Value
Line data is not available for this stock in the current dataset"
for the rest.

Mobile: 13F columns hide below the `md` breakpoint; mobile stacked
view is the next ticket (N1 in the open-work snapshot).

Rollback: `?use_persisted_scores=false` per-request escape, or
application code revert if needed. See
docs/runbooks/phase3-scoring-rollback.md.
Do NOT use alembic downgrade for this rollback.
```

---

## §2.2 API consumer changelog entry

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
  2025-Q3 production-equivalent data: `top10_swap_count=0`).
  Absolute score magnitudes are ~70% of the pre-flip legacy values —
  this is the documented base-formula divergence and will be resolved
  by MVP8-02.

### Deprecated

- `?use_persisted_scores=false` on the three endpoints above remains
  available during the observation window as an escape hatch. It
  will be retired in a future release (Phase 4) after one full
  scoring cycle without ranking regression.

### Coverage limitations

- Quality & valuation overlay (Piotroski, Value Line price targets,
  earnings predictability) is available for a small curated subset
  of ranked stocks (3/240 = 1.25%). Stocks without Value Line
  coverage return `quality_overlay.has_value_line=false`. This is by
  design (Value Line ingestion is curated, not exhaustive); coverage
  expansion is on the roadmap.

### Migration / compatibility

- No breaking changes to existing endpoint shapes. New fields on
  `AvailableStockDetail`: `quality_overlay`, `top_holders[].cik`.
```

---

## §2.3 Watchlist user notice (in-app banner / email)

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
  small curated subset of stocks. Most rows will show "Value Line
  data is not available for this stock in the current dataset" in
  the detail panel — that's accurate, not a bug. We're expanding
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

## §3 Pre-publish checklist

Before sending, the operator confirms:

- [x] All `<...>` placeholders replaced with real D2/D5 values, except `<DEPLOY_DATE>` which is filled at merge time.
- [x] `<COVERAGE_TIER>` chosen per §1B (= "small curated subset").
- [x] `<DEPLOY_VERDICT>` confirmed `DEPLOY-SAFE` (D2 gates pass).
- [ ] PO has approved the final draft.
- [ ] `<DEPLOY_DATE>` filled at merge time.
- [ ] §2.1 internal note posted to the operations channel.
- [ ] §2.2 changelog entry committed to the API docs surface.
- [ ] §2.3 user notice published per the chosen channel (in-app banner OR email; not both unless the team has decided to do both).
- [ ] N4 sign-off trail D4 entry references this published note (paste the final §2.3 text into the trail so the audit captures what users saw).

---

## §4 What's still needed

- **PO review and approval** of this drafted note. The PO may want copy adjustments before publication; this draft is the starting point.
- **`<DEPLOY_DATE>`** — filled in when the merge happens. Reminder: `.github/workflows/deploy.yml` auto-fires on merge to `main`, so `<DEPLOY_DATE>` is the merge timestamp.
- **Channel selection for §2.3** — in-app banner OR email OR both. PO decision.
