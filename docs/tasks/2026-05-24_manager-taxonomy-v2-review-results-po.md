# PO Review — Manager Taxonomy V2
**Date:** 2026-05-24  
**Branch:** `claude/manager-taxonomy-v2`  
**Reviewer role:** Senior value investor / product owner  
**Files reviewed:**
- `docs/tasks/2026-05-24_manager-taxonomy-v2.md`
- `backend/app/services/seed_data/confirmed_managers.json` (82 entries)
- `backend/app/services/oracles_lens/manager_style.py` (STYLE_PRIMARY_TO_LEGACY map)
- `backend/app/services/oracles_lens/constants.py` lines 46–60 (MANAGER_SIGNAL_WEIGHTS)

---

## Q1 — Is the eight-bucket `style_primary` vocabulary the right cut?

**Verdict: Yes with two refinements.**

### `value_deep` vs `value_concentrated` — meaningful distinction, keep it

The split is real and worth preserving. `value_deep` managers (Tweedy, Southeastern, Dodge & Cox, Pzena, Harris/Oakmark, First Eagle, First Pacific, Kahn, Yacktman, Weitz, Sound Shore) run diversified statistical-value books — often 40–80+ positions, earnings-yield or P/B discipline, systematic. `value_concentrated` managers (Baupost, Akre, Pabrai, Greenlea, Aquamarine, Abrams, AltaRock, Himalaya, Daily Journal) run 5–20 position books, sourced from qualitative conviction rather than a screen. The former tells you what the market broadly undervalues; the latter tells you what a few sharp individuals think is worth owning for years. Those are different signals and a value investor will want to filter them separately. **Keep the split.**

The one genuine edge case is Fairfax (Watsa): classified `value_concentrated` but runs a much larger book than typical concentrated managers. Given his insurance float structure it's closer in spirit to Berkshire — both are permanent-capital vehicles with a quality-tilted equity book. Fairfax staying in `value_concentrated` is defensible (he's still qualitative/concentrated by method); I'd add `insurance_float` to his `ideology_tags` to make that visible. The current rationale calls it "Canadian Berkshire analogue" which is accurate.

### `quality_compounder` vs folding into `value_concentrated` — keep distinct

The PR is right to keep `quality_compounder` as a separate bucket. The key difference is not price-discipline (both camps care about price) but the *source of expected return*: deep-value managers buy businesses at discounts that close via mean-reversion or catalysts; quality compounders buy businesses that earn high returns on incremental capital indefinitely, so the holding period itself generates return. Lindsell Train / Fundsmith / Polen / Cantillon / Valley Forge / Dorsey all belong here — their thesis is capital-light compounding, not mean-reversion. Folding them into `value_concentrated` would blur the signal: Klarman and Terry Smith are doing entirely different things.

One reclassification I'd make: **Akre Capital** (Chuck Akre) is currently `quality_compounder` — that is correct per his "three-legged stool" philosophy of reinvestment runway. But his son John Akre (AltaRock Partners) is separately classified as `value_concentrated`. AltaRock actually runs a similar high-quality compounder approach to Akre Capital. I'd move AltaRock to `quality_compounder`. This is a refinement, not a critical fix.

### GARP bucket — do not add one

A separate `garp` bucket is not worth the complexity. GARP is a valuation method, not an investment philosophy — nearly every manager here buys "growth at a reasonable price" in some sense. Jensen Investment Management (with its 15-year ROE ≥ 15% screen) sits fine in `quality_compounder` because the selection mechanism is quality first, and the holding period is long. Ariel (Rogers) sits fine in `value_deep` because the primary discipline is cheapness in small/mid-cap names. Adding `garp` would force borderline judgment calls on dozens of managers without improving filtering utility. **Do not add it.**

**Summary of Q1 changes:**

| Manager | Current | Proposed | Rationale |
|---|---|---|---|
| AltaRock Partners (Mark Massey) | `value_concentrated` | `quality_compounder` | Runs Akre-family philosophy; high-quality compounders, not cheapness screen |

---

## Q2 — Are the Tiger Cubs correctly classified?

**Verdict: Classification correct; weight outcome correct; label refinement worth considering.**

### `growth_long_short` as style label

The label is accurate for the 13F read path. All five (Tiger Global, Lone Pine, Viking, Maverick, Durable) run or have run long/short books with a growth-equity tilt and meaningfully higher turnover than any of the value managers in the universe. The 13F captures only their long book, so the signal is already incomplete. Assigning them `growth_long_short` → `high_turnover` (weight 0.30) correctly communicates that their holdings are partial, transient, and momentum-influenced.

The case for a `tiger_cub` label as the primary style is weak: it's lineage, not philosophy. The case for `growth_long_only` is also weak because all five still run (or have historically run) meaningful short books. `growth_long_short` is the most accurate factual description. **Keep it.**

### Weight outcome: `high_turnover` at 0.30 vs `multi_strategy` at 0.60

Dropping to 0.30 is the right call. The concern with 0.60 (`multi_strategy`) is that it implies a modest but meaningful signal contribution. Tiger Cubs at 0.30 is a deliberate downgrade that says: "we can see roughly a third of their book, it turns over frequently, and their thesis is momentum/growth, not long-term value." That is the honest read. Moving them to 0.60 would be too generous.

The one Tiger Cub that merits a second look is **Durable Capital Partners** (Henry Ellenbogen). He is ex-T. Rowe Price growth, not a Robertson lineage Tiger Cub, so lumping him with the Tiger Cubs on `ideology_tags` is slightly imprecise — but his actual behavior (high turnover, growth-TMT concentration) makes `growth_long_short` the right style bucket regardless of lineage. The tag `ex_t_rowe` in the JSON is accurate.

### Tiger Cub tag in `ideology_tags`

**Yes — add `tiger_cub` to the four Robertson-lineage managers** (Tiger Global, Lone Pine, Viking, Maverick) as an `ideology_tags` entry. It already exists in the JSON for all four, so this is done. Durable correctly has `ex_t_rowe` instead. This enables future filtering (e.g., "show me what Tiger Cub generation two is buying") without affecting weight logic. No code change required beyond confirming the tag is present (it is).

---

## Q3 — Spot-check classifications

### TCI Fund Management → `activist` | Accept with note

Chris Hohn is correctly classified as `activist`. His engagement on Visa, Charter, Moody's, and ABInBev is clearly activist — he files letters, demands board changes, pushes on capital return. The fact that he describes himself as a "constructive long-term holder" does not change what he actually does: he takes concentrated positions and pressures management. The `constructive_activist` tag in `ideology_tags` captures the nuance well. The weight outcome (0.80) is appropriate — activists' 13F holdings do signal long-term conviction, just with engagement overhead.

That said, Hohn's turnover is classified `low` and `capital_structure` as `locked_lp`, both correct. His holdings are more sticky than a typical activist like Icahn. If Oracle's Lens later differentiates activist sub-styles, Hohn belongs in a "long-hold constructive" sub-bucket. For now, `activist` is right.

### Berkshire → `value_concentrated`, `permanent_capital` | Accept

Correct on both dimensions. Top-10 positions at ~80% of equity book, permanent capital via insurance float, very low turnover, qualitative conviction-driven picks. The `position_concentration_top10_pct: 80.0` field surfacing this is a nice touch. **Accepted.**

### Gates Foundation → `endowment_passive`, `index_like` weight (0.10) | Accept

The premise is sound. The Gates Foundation Trust's equity position is dominated by Berkshire shares transferred as charitable donations, and its "trades" reflect gifting schedules and diversification requirements, not investment views. Treating its holdings as near-noise in Oracle's Lens is correct. The `endowment_foundation` capital structure is also the right bucket. **Accepted.**

One future consideration: if Gates Foundation ever materially reduces Berkshire and deploys capital into equities as genuine investment positions, the classification would need revisiting. The `classification_rationale` makes the assumption explicit, which is exactly right.

### Scion (Burry) → `special_situations` | Accept with mild reservation

The rationale ("quality of insight is high — special_situations captures it better than 'high_turnover'") is sympathetic but slightly self-serving. Burry's 13F history shows: high turnover, frequent full portfolio rotations, macro-driven puts alongside equities, and occasional all-in sector bets. His equity longs are best described as macro-contrarian setups, not special situations in the traditional sense (merger arbitrage, spin-offs, liquidations).

That said, `special_situations` → `multi_strategy` (weight 0.60) is preferable to `high_turnover` (0.30) for a different reason: when Burry does take a long equity position and holds it, it often represents a genuinely differentiated insight (e.g., small-cap financials, Japanese net-nets). Giving him 0.60 rather than 0.30 reflects that his longs, while infrequent, are worth attention. **Accept `special_situations`, but the rationale should say "macro-contrarian with occasional high-conviction equity longs" rather than implying he runs a traditional special-situations book.**

**Suggested rationale update:** "Macro-contrarian; very high turnover but episodic equity longs represent high-conviction sector calls — special_situations bucket (weight 0.60) is a better proxy than high_turnover (0.30) for those positions."

### Vulcan Value Partners → `value_concentrated` | Accept

Fitzpatrick's "concentrated value with margin of safety" is exactly `value_concentrated`. The PO review's original concern (that Vulcan was in `long_term_fundamental` in V1) is the issue this fixes. **Accepted.**

### Markel → `quality_compounder`, `permanent_capital` | Accept, not `value_concentrated`

Tom Gayner explicitly describes his investment approach as "buy good businesses at fair prices and hold them forever" — that is quality-compounder philosophy, not value-concentrated. The insurance float structure earns `permanent_capital`. The "Baby Berkshire" analogy in the rationale is accurate: Berkshire itself is `value_concentrated` (Buffett's method is conviction-value), while Gayner is explicitly quality-first. The distinction: Buffett focuses on pricing (he wants a bargain); Gayner focuses on quality (he tolerates fair prices for great businesses). **Markel stays `quality_compounder`.** The current classification is correct.

### Pershing Square → `activist`, `permanent_capital` | Accept with note

Ackman's recent style has undeniably evolved: PSTH, the concentrated bets on Hilton / Restaurant Brands / Universal Music Group, and his public market commentary all point to a quality-compounding methodology. But his activist DNA remains operative — the Chipotle engagement, the HHC restructuring, and his willingness to go public with investment theses are all activist behaviors. The `permanent_capital` classification via Pershing Square Holdings (the Amsterdam-listed closed-end fund) is accurate.

The `quality_compounder` influence is real but I would not reclassify: his 13F holdings reflect activist-driven selections even when he holds for years. **Keep `activist`.** If a future `ideology_tags` value of `quality_activist` becomes useful, Ackman is the prototype.

### Oaktree → `multi_strategy_macro` | Accept with weight concern

The classification is defensible: Oaktree's mandate is global across credit, equities, real assets — it is genuinely multi-strategy. The 13F equity sleeve is a small fraction of their total AUM, so the `multi_strategy` weight of 0.60 already signals conservatism.

However, the more important point is that Oaktree's equity 13F holdings often represent *distressed* companies that have converted debt to equity, not investment views on equity value per se. This means even 0.60 may be too generous. A weight of 0.30–0.40 would be more honest.

**Recommendation:** Keep `multi_strategy_macro` for now, but add `distressed_credit_primary` to `ideology_tags` (it already has `distressed` and `credit`). In the next Oracle's Lens weight-tuning milestone, consider whether `multi_strategy_macro` with distressed-credit primary should get a separate sub-bucket or a direct weight override. Flag this in the backlog.

---

## Q4 — `capital_structure` design

### Is `permanent_capital` a useful filter for value investors? Yes.

Permanent capital managers (Berkshire, Fairfax, Markel, Daily Journal, Icahn Enterprises, Appaloosa-converted-family-office, H&H International, Pershing Square Holdings, Icahn Capital) have a structural advantage: they cannot be forced to sell by redemptions. This means their 13F holdings are stickier signals. A value investor screening Oracle's Lens will rationally want to up-weight holdings that come from permanent-capital vehicles because those managers can wait out short-term dislocations. **The filter is useful and should be surfaced in a future Oracle's Lens UI refinement.**

### `standard_lp` missing — is that honest?

No standard LP appears in the 82-manager seed. Every hedge fund is classified as `locked_lp`, every mutual fund as `mutual_fund_etf`. This overstates the lock-up reality: not all hedge funds here have true multi-year lock-ups. Greenlight (Einhorn), Third Point (Loeb), and Appaloosa (Tepper, though now family office) historically offered quarterly redemption windows with gates — closer to `standard_lp` than to the 2–3 year lock-up implied by `locked_lp`. The distinction between locked and standard LP matters when comparing the capital stickiness signal.

**Recommendation:** Introduce `standard_lp` for managers with quarterly or annual redemptions (no hard multi-year lock). Candidates to reclassify from `locked_lp` to `standard_lp`: Greenlight, Third Point, Miller Value Partners (open-end fund wrapper in Miller Opportunity Trust), Sound Shore. This is a refinement pass, not a blocker for this PR.

### Should `capital_structure` directly weight Oracle's Lens?

Not yet in this milestone, but yes in principle. The right model is a multiplicative adjustment: a permanent-capital manager's holdings get a small uplift (e.g., ×1.1) and a standard-LP manager's get a slight haircut (×0.9) relative to the base `style_primary` weight. This is worth tracking as a follow-up after the V2 schema lands, since the field now exists in the DB.

---

## Q5 — `market_cap_focus` and small-cap value sleuths

### Current small/micro-cap managers in the seed (7):

1. Ariel Investments (Rogers) — `value_deep`, `small`
2. Conifer Management — `value_concentrated`, `small`
3. Engaged Capital (Welling) — `activist`, `small`
4. Greenlea Lane (Tarasoff) — `value_concentrated`, `small`
5. Kahn Brothers — `value_deep`, `small`
6. Oakcliff Capital (Lawrence) — `value_concentrated`, `small`
7. Punch Card (Lou) — `value_concentrated`, `small`

### Should there be a small-cap weighting boost?

Yes. Small-cap value managers surface ideas in a less-efficient market. A position added by Norbert Lou (Punch Card) or Josh Tarasoff (Greenlea Lane) is, on average, more distinctively sourced than a position added by Harris Associates in a large-cap name. The signal-to-noise ratio is higher because fewer institutions are competing for the same alpha.

**Recommendation:** Add an optional `market_cap_boost` multiplier (e.g., ×1.15 for `small`, ×1.25 for `micro`) in the Oracle's Lens scoring constants, applied multiplicatively on top of the `style_primary` weight. This should be a follow-up milestone (same BACKLOG.md entry as the `capital_structure` direct-weighting item above).

### Missing small-cap managers?

Reviewing the universe, the following well-known US-filing small-cap value investors are absent from the 82:
- **Tweedy Browne** is in the seed but focused on global mid — Tweedy's small-cap heritage is now partly historical.
- **Royce Associates** (Chuck Royce) — classic small-cap value, still files 13F. Notable omission.
- **Third Avenue Management** is in the seed (Whitman legacy) and does include small-cap.

The most significant gap is **Royce Associates** if small-cap signal quality is a priority. Flagging for the Dataroma sync review.

---

## Q6 — Classifications that feel wrong

### Egerton Capital (Armitage) → `quality_compounder` | Borderline — suggest keeping

The argument for `growth_long_short`: Egerton runs a long/short book, is UK-based with high AUM, and Armitage's background is fundamental growth. The argument for `quality_compounder`: Egerton's long book is concentrated in high-quality businesses (luxury, consumer staples, technology franchises), turnover is classified `med` (not high), and the UK long-bias structure is closer to a quality-holding fund than to a Tiger Cub. The `quality_compounder` classification is defensible. The `uk_long_bias` tag in `ideology_tags` is the right way to surface this nuance. **Keep `quality_compounder`.**

If Egerton's empirical behavior (derived from 13F) shows high turnover or low overlap with quality names, revisit in V2 behavior-derived classification.

### Greenlight (Einhorn) → `value_concentrated` | Accept with important caveat documented

The classification is correct for the 13F signal we actually receive: Einhorn's longs are concentrated, held with value conviction, sourced from fundamental research. But the rationale in the JSON calls out the critical limitation: "13F only shows longs." Einhorn's most distinctive calls have often been his shorts (Lehman, Allied Capital, Green Mountain Coffee). The 13F signal captures only half of his intellectual output, and the half that is more likely to be hedged.

**This is a known, documented limitation, not a misclassification.** The `short_bias_capability` ideology tag is exactly the right way to surface this. Future product work could add a `long_short_signal_completeness` flag for managers whose 13F tells a materially incomplete story. **Accept `value_concentrated`, but flag the short-bias limitation prominently in any Oracle's Lens UI display for Greenlight.**

### Cooperman (Omega Family Office) → `value_concentrated`, `permanent_capital` | Accept

Cooperman closed Omega to outside capital and converted to family office, making the `permanent_capital` classification correct even without a formal closed-end structure. His investment style remains concentrated long-bias value with moderate turnover. **Accepted.**

### Ariel (John Rogers) → `value_deep`, `small` | Accept with caveat

The historical characterization is accurate. Ariel's flagship (Ariel Fund) started in small/mid-cap value. However, the fund has grown to roughly $3B AUM and the holdings have drifted toward mid-large-cap names including well-known companies. The `small` tag for `market_cap_focus` may be increasingly stale for the flagship, though Ariel's self-presentation still emphasizes small/mid value roots.

**Recommendation:** Change `market_cap_focus` from `small` to `mid` for Ariel Investments to reflect current portfolio reality, with `small_cap_value` retained in `ideology_tags` to preserve the historical/philosophical identity. The current `small` tag will cause Ariel to appear in small-cap filters where its actual holdings are now predominantly mid-cap.

| Manager | Current `market_cap_focus` | Proposed | Rationale |
|---|---|---|---|
| Ariel Investments (Rogers) | `small` | `mid` | Flagship portfolio has drifted to mid-large cap; `small_cap_value` ideology tag preserves heritage |

### Patient Capital (McLemore) → `value_concentrated` | Accept with note

McLemore ran the Miller Opportunity Trust alongside Miller and is the named successor. The portfolio follows the same contrarian concentrated value approach. `value_concentrated` is right. The `miller_legacy` ideology tag is appropriate. Note that this is a relatively new independent vehicle (2021 spin-off), so behavior-derived classification may update this when sufficient 13F history accumulates.

---

## Q7 — Is the "Hero outcome" actually right?

**Yes, Tiger Cub reclassification is the right pri-one outcome — but Oaktree and Bridgewater deserve equal emphasis as "quiet signal polluters."**

Dropping Tiger Cubs from weight 1.00 → 0.30 is unambiguously correct and the most impactful single fix. Tiger Global and Lone Pine together represent significant AUM and filing frequency. Their holdings rotating into growth names at high valuations (2020–2021 cohort) were actively *hurting* Oracle's Lens signal quality by contaminating the value-consensus with momentum picks.

However, I'd argue there are two other misclassifications in V1 that are almost as damaging and get less emphasis in the PR narrative:

1. **Bridgewater Associates** (Dalio) was `long_term_fundamental` (weight 1.00) in V1. It's now correctly `multi_strategy_macro` (weight 0.60). Bridgewater's 13F equity sleeve is a mechanical output of their risk-parity macro model — it has near-zero stock-pick signal. Moving it to 0.60 is still arguably too high; 0.30 or even 0.10 would be more accurate. The rationale in the JSON says "weak stock-pick signal" — that phrasing should be stronger.

2. **Appaloosa** (Tepper) similarly was a `long_term_fundamental` manager in V1. He's now `multi_strategy_macro` (weight 0.60). Tepper's equity positions are often macro-driven event trades (distressed, crisis recovery, rate bets) rather than long-term fundamental conviction. 0.60 is reasonable but directionally right.

The Tiger Cubs are the highest-profile fix and the right PR headline. **The hero outcome is correct.**

---

## Q8 — Bootstrap decouple — does this match value-investor workflow?

**Overall: Yes. The design is sound. Two refinements recommended.**

### "Admin clicks button, sees diff, decides which to add" — right UX?

Yes. The alternative — auto-importing every Dataroma discovery — is dangerous because Dataroma's universe includes managers that are not superinvestors by any reasonable definition (e.g., small RIAs, ETF issuers, index managers). The explicit human gate prevents signal dilution. The three-bucket diff (new / known / dropped) gives the admin exactly the information needed to make the decision.

One improvement: the "dropped" bucket (managers in ValuePilot but no longer in Dataroma) should prompt the admin to decide whether to archive the manager or keep them. Some managers legitimately stop filing 13Fs (closed funds, converted to separate accounts, deceased). The current design presumably just surfaces them as "dropped" — it should clarify what action, if any, is expected.

### Should "Add as candidates" auto-classify with V2 fields?

**Partial auto-classification via LLM call — yes, as an optional enhancement, not a blocker.**

The right initial state for a newly discovered manager is `style_primary=unknown` / `capital_structure=unknown`. However, if a simple LLM call (given the manager's legal name, CIK, and a brief description fetched from their SEC registration or Dataroma profile) can pre-populate a draft classification with a confidence flag, that saves the admin meaningful review time. The admin would still confirm or override before the manager is promoted from candidate to confirmed.

**The implementation constraint**: the auto-classification call should never write `is_confirmed=true` directly. It writes a draft with `needs_human_review=true`. The V2 fields would be pre-populated but flagged as LLM-suggested. This keeps the human in the loop while reducing blank-slate friction.

**For this PR**: "candidate with unknown V2 fields" is the correct initial state and requires no additional work. The LLM pre-classification is a follow-up feature. Add it to `docs/BACKLOG.md`.

---

## Summary of classification changes recommended

| Manager | Current `style_primary` | Proposed | Current `market_cap_focus` | Proposed | Priority |
|---|---|---|---|---|---|
| AltaRock Partners (Massey) | `value_concentrated` | `quality_compounder` | `large` | `large` (no change) | Low |
| Ariel Investments (Rogers) | `value_deep` | `value_deep` (no change) | `small` | `mid` | Medium |

All other spot-checked classifications are accepted as-is.

## Backlog items surfaced by this review

1. **`standard_lp` capital structure**: Greenlight, Third Point, Miller Value Partners, Sound Shore should be reclassified from `locked_lp` to `standard_lp` when that bucket is populated. Low severity.
2. **Oaktree weight**: `multi_strategy_macro` at 0.60 is arguably too high for a distressed-credit-primary firm whose equity 13F is largely debt-converted-to-equity. Add `distressed_credit_primary` to `ideology_tags` now; revisit weight in next scoring milestone.
3. **Small-cap market cap boost**: Add ×1.15/×1.25 multipliers in Oracle's Lens constants for `market_cap_focus=small/micro`. Medium priority.
4. **`permanent_capital` Oracle's Lens uplift**: Add ×1.1 multiplier for permanent-capital managers in next scoring milestone. Low severity.
5. **Royce Associates missing**: Notable small-cap value manager not in the 82. Review for inclusion in next Dataroma sync.
6. **Dropped-manager action in Sync UI**: The "dropped" bucket in the Dataroma sync diff should prompt an archive-or-keep decision, not just surface as informational.
7. **LLM-assisted draft classification for new candidates**: Add as optional enhancement to the "Add as candidates" flow. Draft writes `needs_human_review=true`.
8. **Bridgewater weight**: Consider dropping `multi_strategy_macro` weight from 0.60 toward 0.30–0.40 for macro-mechanical managers with documented weak stock-pick signal. Track in scoring milestone.

## Overall verdict

**Ship with two minor data fixes (AltaRock style, Ariel market_cap_focus) and the Scion rationale wording update.** The taxonomy design is sound, the Tiger Cubs fix is the correct hero outcome, the `STYLE_PRIMARY_TO_LEGACY` map is clean and exhaustive, and the 82-entry seed is the most material quality improvement to Oracle's Lens since the manager-type field was introduced. The backlog items above are genuine refinements but none block correctness of the V2 schema.
