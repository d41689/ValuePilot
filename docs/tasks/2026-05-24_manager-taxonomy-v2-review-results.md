# Manager Taxonomy V2 + Bootstrap Decouple — Review Results

**Branch**: `claude/manager-taxonomy-v2`  
**Commits reviewed**:
- `2c10fd1` — Manager taxonomy V2: two-layer style + capital_structure + metadata
- `ef4c018` — Decouple bootstrap from Dataroma; add admin "Sync with Dataroma" diff UI

**Review date**: 2026-05-24

---

## Value Investor PO Review

**Reviewer role**: Senior value investor / product owner  
**Files reviewed**:
- `docs/tasks/2026-05-24_manager-taxonomy-v2.md`
- `backend/app/services/seed_data/confirmed_managers.json` (82 entries)
- `backend/app/services/oracles_lens/manager_style.py` (STYLE_PRIMARY_TO_LEGACY map)
- `backend/app/services/oracles_lens/constants.py` lines 46–60 (MANAGER_SIGNAL_WEIGHTS)

**Overall verdict**: Ship with two minor data fixes and one rationale wording update.

---

### Q1 — Is the eight-bucket `style_primary` vocabulary the right cut?

**Verdict: Yes with two refinements.**

**`value_deep` vs `value_concentrated` — meaningful distinction, keep it**

The split is real and worth preserving. `value_deep` managers (Tweedy, Southeastern, Dodge & Cox, Pzena, Harris/Oakmark, First Eagle, First Pacific, Kahn, Yacktman, Weitz, Sound Shore) run diversified statistical-value books — often 40–80+ positions, earnings-yield or P/B discipline, systematic. `value_concentrated` managers (Baupost, Akre, Pabrai, Greenlea, Aquamarine, Abrams, AltaRock, Himalaya, Daily Journal) run 5–20 position books, sourced from qualitative conviction rather than a screen. The former tells you what the market broadly undervalues; the latter tells you what a few sharp individuals think is worth owning for years. Those are different signals and a value investor will want to filter them separately. **Keep the split.**

The one genuine edge case is Fairfax (Watsa): classified `value_concentrated` but runs a much larger book than typical concentrated managers. Given his insurance float structure it's closer in spirit to Berkshire — both are permanent-capital vehicles with a quality-tilted equity book. Fairfax staying in `value_concentrated` is defensible; I'd add `insurance_float` to his `ideology_tags` to make that visible.

**`quality_compounder` vs folding into `value_concentrated` — keep distinct**

The PR is right to keep `quality_compounder` as a separate bucket. The key difference is not price-discipline but the *source of expected return*: deep-value managers buy businesses at discounts that close via mean-reversion or catalysts; quality compounders buy businesses that earn high returns on incremental capital indefinitely. Lindsell Train / Fundsmith / Polen / Cantillon / Valley Forge / Dorsey all belong here. Folding them into `value_concentrated` would blur the signal: Klarman and Terry Smith are doing entirely different things.

One reclassification: **Akre Capital** (Chuck Akre) is correctly `quality_compounder`. But his son John Akre (AltaRock Partners) is separately classified as `value_concentrated`. AltaRock runs a similar high-quality compounder approach. I'd move AltaRock to `quality_compounder`.

**GARP bucket — do not add one**

A separate `garp` bucket is not worth the complexity. GARP is a valuation method, not an investment philosophy. Jensen Investment Management sits fine in `quality_compounder`; Ariel sits fine in `value_deep`. Adding `garp` would force borderline judgment calls on dozens of managers without improving filtering utility.

**Summary of Q1 changes:**

| Manager | Current | Proposed | Rationale |
|---|---|---|---|
| AltaRock Partners (Mark Massey) | `value_concentrated` | `quality_compounder` | Runs Akre-family philosophy; high-quality compounders, not cheapness screen |

---

### Q2 — Are the Tiger Cubs correctly classified?

**Verdict: Classification correct; weight outcome correct; label refinement worth considering.**

`growth_long_short` is accurate for the 13F read path. All five (Tiger Global, Lone Pine, Viking, Maverick, Durable) run or have run long/short books with a growth-equity tilt and meaningfully higher turnover than any value manager in the universe. The 13F captures only their long book, so the signal is already incomplete. Assigning them `growth_long_short` → `high_turnover` (weight 0.30) correctly communicates that their holdings are partial, transient, and momentum-influenced.

Dropping to 0.30 is the right call. Moving them to 0.60 (`multi_strategy`) would be too generous. The one Tiger Cub that merits a second look is **Durable Capital Partners** (Henry Ellenbogen) — he is ex-T. Rowe Price growth, not a Robertson lineage Tiger Cub — but his actual behavior makes `growth_long_short` the right bucket regardless of lineage. The tag `ex_t_rowe` in the JSON is accurate.

The `tiger_cub` ideology tag is already present in the JSON for all four Robertson-lineage managers (Tiger Global, Lone Pine, Viking, Maverick). Durable correctly has `ex_t_rowe` instead. No code change required.

---

### Q3 — Spot-check classifications

**TCI Fund Management → `activist`**: Accept with note. Chris Hohn is correctly classified as `activist`. His engagement on Visa, Charter, Moody's, and ABInBev is clearly activist. The `constructive_activist` tag in `ideology_tags` captures the nuance. Weight outcome (0.80) is appropriate.

**Berkshire → `value_concentrated`, `permanent_capital`**: Accept. Top-10 positions at ~80% of equity book, permanent capital via insurance float, very low turnover, qualitative conviction-driven picks. Accepted.

**Gates Foundation → `endowment_passive`, `index_like` weight (0.10)**: Accept. The Foundation Trust's equity position is dominated by Berkshire shares transferred as charitable donations, and its "trades" reflect gifting schedules and diversification requirements, not investment views. Treating its holdings as near-noise in Oracle's Lens is correct.

**Scion (Burry) → `special_situations`**: Accept with mild reservation. Burry's 13F history shows high turnover, frequent full portfolio rotations, macro-driven puts alongside equities, and occasional all-in sector bets. His equity longs are best described as macro-contrarian setups, not special situations in the traditional sense. That said, `special_situations` → weight 0.60 is preferable to `high_turnover` (0.30): when Burry does take a long equity position and holds it, it often represents a genuinely differentiated insight. **Accept `special_situations`, but the rationale should say "macro-contrarian with occasional high-conviction equity longs" rather than implying a traditional special-situations book.**

**Vulcan Value Partners → `value_concentrated`**: Accept. Fitzpatrick's "concentrated value with margin of safety" is exactly `value_concentrated`. Accepted.

**Markel → `quality_compounder`, `permanent_capital`**: Accept, not `value_concentrated`. Tom Gayner explicitly describes his investment approach as "buy good businesses at fair prices and hold them forever" — that is quality-compounder philosophy. The distinction: Buffett focuses on pricing (he wants a bargain); Gayner focuses on quality (he tolerates fair prices for great businesses). Markel stays `quality_compounder`.

**Pershing Square → `activist`, `permanent_capital`**: Accept. Ackman's recent style has undeniably evolved toward quality-compounding methodology, but his activist DNA remains operative. The `permanent_capital` classification via Pershing Square Holdings (Amsterdam-listed closed-end fund) is accurate. Keep `activist`.

**Oaktree → `multi_strategy_macro`**: Accept with weight concern. The classification is defensible but Oaktree's equity 13F holdings often represent *distressed* companies that have converted debt to equity, not investment views on equity value per se. Even 0.60 may be too generous. **Recommendation:** Add `distressed_credit_primary` to `ideology_tags` now; in the next Oracle's Lens weight-tuning milestone consider whether `multi_strategy_macro` with distressed-credit primary should get a direct weight override.

---

### Q4 — `capital_structure` design

**Is `permanent_capital` a useful filter for value investors? Yes.** Permanent capital managers cannot be forced to sell by redemptions — their 13F holdings are stickier signals. This filter is useful and should be surfaced in a future Oracle's Lens UI refinement.

**`standard_lp` missing — is that honest?** No. Not all hedge funds here have true multi-year lock-ups. Greenlight (Einhorn), Third Point (Loeb), and Miller Value Partners historically offered quarterly redemption windows with gates — closer to `standard_lp` than to the 2–3 year lock-up implied by `locked_lp`. Recommendation: introduce `standard_lp` for managers with quarterly or annual redemptions (candidates: Greenlight, Third Point, Miller Value Partners, Sound Shore). This is a refinement pass, not a blocker for this PR.

**Should `capital_structure` directly weight Oracle's Lens?** Not yet in this milestone, but yes in principle. The right model is a multiplicative adjustment: a permanent-capital manager's holdings get a small uplift (e.g., ×1.1). Worth tracking as a follow-up.

---

### Q5 — `market_cap_focus` and small-cap value sleuths

**Current small/micro-cap managers in the seed (7)**: Ariel Investments, Conifer Management, Engaged Capital, Greenlea Lane, Kahn Brothers, Oakcliff Capital, Punch Card.

**Should there be a small-cap weighting boost? Yes.** Small-cap value managers surface ideas in a less-efficient market. Recommendation: add an optional `market_cap_boost` multiplier (e.g., ×1.15 for `small`, ×1.25 for `micro`) in the Oracle's Lens scoring constants. Follow-up milestone.

**Missing small-cap managers?** The most significant gap is **Royce Associates** (Chuck Royce) — classic small-cap value, still files 13F. Notable omission. Flagging for the Dataroma sync review.

---

### Q6 — Does any classification feel "this is just wrong"?

**Egerton Capital (Armitage) → `quality_compounder`**: Borderline — keep. The `quality_compounder` classification is defensible. The `uk_long_bias` tag in `ideology_tags` is the right way to surface the nuance.

**Greenlight (Einhorn) → `value_concentrated`**: Accept with important caveat. The classification is correct for the 13F signal we actually receive. But Einhorn's most distinctive calls have often been his shorts (Lehman, Allied Capital, Green Mountain Coffee). The 13F signal captures only half of his intellectual output, and the half that is more likely to be hedged. This is a known, documented limitation, not a misclassification. The `short_bias_capability` ideology tag is exactly the right way to surface this.

**Cooperman (Omega Family Office) → `value_concentrated`, `permanent_capital`**: Accept. Cooperman closed Omega to outside capital and converted to family office, making `permanent_capital` correct. Accepted.

**Ariel (John Rogers) → `value_deep`, `small`**: Accept with caveat. The fund has grown to roughly $3B AUM and the holdings have drifted toward mid-large-cap names. **Recommendation:** Change `market_cap_focus` from `small` to `mid` to reflect current portfolio reality, with `small_cap_value` retained in `ideology_tags` to preserve the historical/philosophical identity.

| Manager | Current `market_cap_focus` | Proposed | Rationale |
|---|---|---|---|
| Ariel Investments (Rogers) | `small` | `mid` | Flagship portfolio has drifted to mid-large cap; `small_cap_value` ideology tag preserves heritage |

**Patient Capital (McLemore) → `value_concentrated`**: Accept. McLemore ran the Miller Opportunity Trust alongside Miller and is the named successor. The portfolio follows the same contrarian concentrated value approach. The `miller_legacy` ideology tag is appropriate.

---

### Q7 — Is the "Hero outcome" actually right?

**Yes — but Oaktree and Bridgewater deserve equal emphasis as "quiet signal polluters."**

Dropping Tiger Cubs from weight 1.00 → 0.30 is unambiguously correct and the most impactful single fix. Tiger Global and Lone Pine together represent significant AUM and filing frequency.

However, two other misclassifications in V1 that are almost as damaging:

1. **Bridgewater Associates** (Dalio) was `long_term_fundamental` (weight 1.00) in V1. It's now correctly `multi_strategy_macro` (weight 0.60). Bridgewater's 13F equity sleeve is a mechanical output of their risk-parity macro model — it has near-zero stock-pick signal. Moving it to 0.60 is still arguably too high; 0.30–0.40 would be more accurate.

2. **Appaloosa** (Tepper) similarly was `long_term_fundamental` in V1. He's now `multi_strategy_macro` (weight 0.60). Tepper's equity positions are often macro-driven event trades, not long-term fundamental conviction. 0.60 is reasonable.

The Tiger Cubs are the highest-profile fix and the right PR headline. **The hero outcome is correct.**

---

### Q8 — Bootstrap decouple — does this match value-investor workflow?

**Overall: Yes. The design is sound. Two refinements recommended.**

"Admin clicks button, sees diff, decides which to add" is the right UX gate. Auto-importing every Dataroma discovery is dangerous because Dataroma's universe includes managers that are not superinvestors by any reasonable definition. The three-bucket diff (new / known / dropped) gives the admin exactly the information needed.

One improvement: the "dropped" bucket should prompt the admin to decide whether to archive the manager or keep them. Some managers legitimately stop filing 13Fs. The current design surfaces them as "dropped" — it should clarify what action, if any, is expected.

**Should "Add as candidates" auto-classify with V2 fields?** Partial auto-classification via LLM call — yes, as an optional enhancement, not a blocker. The right initial state is `style_primary=unknown` / `capital_structure=unknown`. For this PR: "candidate with unknown V2 fields" is the correct initial state. The LLM pre-classification is a follow-up feature — add it to `docs/BACKLOG.md`.

---

### PO Review — Summary of data changes recommended

| Manager | Current `style_primary` | Proposed | Current `market_cap_focus` | Proposed | Priority |
|---|---|---|---|---|---|
| AltaRock Partners (Massey) | `value_concentrated` | `quality_compounder` | `large` | `large` (no change) | Low |
| Ariel Investments (Rogers) | `value_deep` (no change) | `value_deep` | `small` | `mid` | Medium |

Plus: Update Scion rationale wording to "macro-contrarian with episodic high-conviction equity longs."

### PO Review — Backlog items surfaced

1. **`standard_lp` capital structure**: Greenlight, Third Point, Miller Value Partners, Sound Shore should be reclassified from `locked_lp` to `standard_lp`. Low severity.
2. **Oaktree weight**: `multi_strategy_macro` at 0.60 is arguably too high for a distressed-credit-primary firm. Add `distressed_credit_primary` to `ideology_tags` now; revisit weight in next scoring milestone.
3. **Small-cap market cap boost**: Add ×1.15/×1.25 multipliers in Oracle's Lens constants for `market_cap_focus=small/micro`. Medium priority.
4. **`permanent_capital` Oracle's Lens uplift**: Add ×1.1 multiplier for permanent-capital managers in next scoring milestone. Low severity.
5. **Royce Associates missing**: Notable small-cap value manager not in the 82. Review for inclusion in next Dataroma sync.
6. **Dropped-manager action in Sync UI**: The "dropped" bucket should prompt an archive-or-keep decision, not just surface as informational.
7. **LLM-assisted draft classification for new candidates**: Draft writes `needs_human_review=true`. Never auto-confirms. Follow-up feature.
8. **Bridgewater weight**: Consider dropping `multi_strategy_macro` weight from 0.60 toward 0.30–0.40 for macro-mechanical managers with documented weak stock-pick signal. Track in scoring milestone.

---

## Staff Engineer Review

**Reviewer role**: Staff engineer (contract / architecture)  
**Task docs reviewed**:
- `docs/tasks/2026-05-24_manager-taxonomy-v2.md`
- `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md`

**Overall verdict**: Approve with two required pre-merge actions and several deferrable follow-ups. No critical invariants from `AGENTS.md` are violated.

---

### C1 — Schema migration

**File**: `backend/alembic/versions/20260524120000-manager_taxonomy_v2.py`

**Column sizing**: All seven columns are appropriately sized for their controlled vocabularies.

| Column | Migration DDL | Longest current value | Assessment |
|---|---|---|---|
| `style_primary` | `String(40)` | `multi_strategy_macro` (21 chars) | Safe — 19 chars headroom |
| `capital_structure` | `String(40)` | `endowment_foundation` (21 chars) | Safe — 19 chars headroom |
| `market_cap_focus` | `String(20)` | `mega` (4 chars) | Safe |
| `historical_turnover` | `String(10)` | `high` (4 chars) | Safe |
| `position_concentration_top10_pct` | `Numeric(6, 2)` | 999.99 max representable | Correct — percentage to 2 dp |
| `ideology_tags` | `JSONB` | unbounded list | Correct type choice |

**`server_default='unknown'` on NOT NULL columns**: Safe. PostgreSQL applies `server_default` synchronously during `ALTER TABLE ... ADD COLUMN` — it backfills every pre-existing row before the DDL transaction commits. No separate data migration step needed.

**Index justification**:
- `ix_institution_managers_style_primary` — justified. The screener and Oracle's Lens filter by `style_primary` when constructing universe subsets. Even at 100 rows today the index is cheap to create and the query pattern is clear.
- `ix_institution_managers_capital_structure` — borderline. No current query filters by `capital_structure` in isolation. The task doc mentions "filters" as a future milestone. Low-severity finding — acceptable to keep; record the intent in a comment.

**Downgrade path**: The `downgrade()` function correctly drops both indexes first (in reverse creation order) then drops all seven columns in reverse addition order. This restores the table to its prior shape cleanly. No issues.

**Should the migration include a data backfill?** No. Running service-layer code inside Alembic migrations is an anti-pattern (circular imports, session management, no rollback guarantee) that `docs/architecture/data-layer.md` explicitly warns against. The current design is correct.

**C1 verdict: No blocking issues.**

---

### C2 — Backward compat for `manager_type`

**Files**: `backend/app/models/institutions.py`, `backend/app/services/oracles_lens/manager_style.py`, `backend/app/services/edgar_ingestion.py`

**Auto-derivation at write time vs. model-layer hook**: The current design derives `manager_type` from `style_primary` inside `seed_confirmed_managers()` and writes both columns explicitly. There is no `@event.listens_for` hook. This is defensible for the V1 scope where `seed_confirmed_managers()` is the only write path for `style_primary`. A model-layer hook would be stronger but introduces a dependency from the model layer on `manager_style.py`. The trade-off is acceptable for V1 — but the hook gap must be documented.

**Drift risk**: The `update_manager()` function (`thirteenf_admin_dashboard.py`, lines 569–597) allows patching `manager_type` directly through the admin API. Neither `style_primary` nor any V2 field is in `update_manager()`'s allowed-field list today. This means an admin cannot currently update `style_primary` via the existing edit dialog. However, if a future endpoint writes `style_primary` without calling `derive_legacy_manager_type()` and setting `manager_type`, the two columns will diverge.

**Required action (pre-merge)**: Add a comment to `update_manager()` at line 573 explicitly naming this invariant: "If `style_primary` is added to this field list in a future PR, also derive and set `manager_type` from it — the two columns must stay in sync." Add a corresponding backlog entry for "add V2 fields to `update_manager()` + admin UI."

**`derive_legacy_manager_type` raising `ValueError`**: Correct contract. Fail-loud is correct because:
1. The function is called only from `seed_confirmed_managers()` with a visible exception surface.
2. The seed JSON passes through CI test `test_seed_json_classifications_use_canonical_vocabularies` which validates every entry's `style_primary` against `STYLE_PRIMARY` before the seed runs.
3. A defensive `return 'unknown'` default would silently let a mis-classified seed entry through with the wrong Oracle's Lens weight — exactly the failure mode this PR exists to fix.

One gap: `quant` is in `MANAGER_TYPES` but has no `style_primary` that maps to it. Confirm with the PO that any quant-style managers in the confirmed universe are classified under the closest V2 bucket.

**C2 verdict: One required pre-merge action (comment + backlog entry for the drift risk). The `ValueError` contract is correct as-is.**

---

### C3 — Bootstrap / sync separation

**Files**: `backend/app/services/thirteenf_admin_dashboard.py`, `backend/app/api/v1/endpoints/thirteenf_admin.py`

**Job_type name reuse `bootstrap_whitelist`**: Keeping the legacy `job_type='bootstrap_whitelist'` name while changing its handler to call `seed_confirmed_managers()` is a pragmatic compatibility decision. The handler comment clearly documents the old behavior and the change. The summary key change from `managers_seen` to `managers_seeded` is the correct signal to admin that the semantics changed. Acceptable for V1.

**Synchronous endpoints vs. job system**: The code is correct. However, there is a **material discrepancy between the task doc and the code.** The task doc (line 162) states: "The locking is still respected via the job system if admin spams the button — second click within the lock window returns 409 / 'another sync in progress' rather than racing." This is incorrect. The `/admin/13f/managers/dataroma-sync` endpoint calls `sync_dataroma_managers(session)` directly, bypassing the job system entirely. Two concurrent requests will both execute against Rate Guard simultaneously. For a pure read operation, this is safe — they will both complete and return a diff. The endpoint comment at line 463 is accurate; the task doc is not.

**Required action (pre-merge)**: Fix the task doc `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md` around line 162. Remove the claim that "second click returns 409 via the job system." Replace with the accurate description: "Two concurrent sync calls both complete — Rate Guard serializes the upstream fetches per its own rate-limit policy."

**C3 verdict: One required pre-merge action (fix task doc concurrency claim). The code itself is correct for the stated use case.**

---

### C4 — The diff algorithm

**File**: `backend/app/services/edgar_ingestion.py`, `sync_dataroma_managers()`

**Match by `dataroma_code` only**: The task doc explicitly accepts this as a V1 tradeoff. A manager we have confirmed (with no `dataroma_code`) that Dataroma starts tracking (with a code) will appear in the `new` bucket even though it may be a conceptual duplicate. The UX implication: when the admin sees a "new" entry that they recognise as a manager they already track, they can close the dialog without adding.

One edge case not documented: if the admin clicks "Add selected" on a manager that already exists with no `dataroma_code`, `add_dataroma_candidates()` will create a *second* `institution_managers` row with the `dataroma_code` set. The `dataroma_code` field is nullable and has no UNIQUE constraint. This is a known V1 limitation.

**Add to backlog**: "Dataroma sync V1 — admin may create a duplicate manager row if they click Add for a manager that already exists without a `dataroma_code`. Mitigate in V2 by either adding a UNIQUE constraint on `dataroma_code` or by showing a warning when a `new` Dataroma entry name-matches an existing confirmed manager."

**`dropped` excludes managers without `dataroma_code`**: The logic is correct and well-documented. Managers seeded from `confirmed_managers.json` without a `dataroma_code` are excluded from the dropped bucket — Dataroma never tracked them.

**C4 verdict: No blocking issues. One backlog suggestion for the duplicate-row risk.**

---

### C5 — Test coverage

**Files**: `backend/tests/unit/test_13f_manager_taxonomy_v2.py` (23 cases), `backend/tests/unit/test_13f_dataroma_sync.py` (10 cases)

Coverage is good for the core contract: the mapping, the seed JSON, and the two functional paths (seed + sync diff). The critical hero assertion (`test_derive_legacy_manager_type_tiger_cubs_become_high_turnover`) is present and correctly ties to the Oracle's Lens weight table.

**Specific gaps:**

1. **Missing auth test for the two new REST endpoints.** The task doc AC #3 states "Admin endpoints require auth (admin role)." There is no test asserting a 401/403 for unauthenticated callers. Low-severity — the `AdminUser` dependency provides the auth guard — but missing from this PR's test file.

2. **`test_bootstrap_whitelist_job_type_uses_offline_seed_path` strength.** The test monkeypatches `_fetch_dataroma_managers` to raise if called, then asserts the result contains `managers_seeded`. A stronger version would assert the count is `>= 80`. As written, a handler that returns `{"managers_seeded": 0}` would pass. The end-to-end test `test_bootstrap_whitelist_handler_actually_seeds_v2_managers` provides the stronger wiring check, so the gap is partially covered.

3. **Test isolation rewrite is the right call.** The subset check ("my fixture row's id does not appear in the dropped list") is exactly the right scope for this test. CI (empty volume) would have passed both forms; the subset form is more robust in local dev.

4. **Sample truncation untested.** `DataromaSyncDiff.to_summary_dict()` truncates each sample list to `sample_size=25`. No test exercises the truncation path. Low severity — the logic is a simple list slice.

**C5 verdict: No blocking issues. Four low-severity gaps, all deferrable.**

---

### C6 — Pre-existing test isolation issue

**Reference**: `docs/BACKLOG.md`, entry "_clear_13f test helper raises FK violation when dev DB has committed rows"

**Severity: medium (dev-only) is correct.** CI always starts from an empty volume; the FK violation cannot occur in CI. The new `test_13f_manager_taxonomy_v2.py` and `test_13f_dataroma_sync.py` tests use `db_session` (transactional rollback) and are not affected.

**Should this PR fix the issue?** No. The issue reproduces on `main` with all V2 changes stashed — it is not introduced by this PR. The test isolation architecture is a cross-cutting concern that warrants its own change, its own test plan, and its own sign-off.

**Process suggestion**: Promote the backlog entry to a GitHub Issue for human triage. There are at least three overlapping backlog entries for test isolation (the `_clear_13f` FK entry added by this PR, the "13F test suite is not isolated" entry from 2026-05-22, and the "dev-cusip-linking-fixture" task). Consolidating them into a single GitHub Issue with an owner would help.

**C6 verdict: Triage is correct. No fix required in this PR. One process suggestion (GitHub Issue consolidation).**

---

### Staff Engineer Review — Required pre-merge actions

1. **[C2]** Add a comment to `update_manager()` in `backend/app/services/thirteenf_admin_dashboard.py` (after line 583) documenting the V2 derivation invariant: "If `style_primary` is added to this list in a future PR, call `derive_legacy_manager_type(style_primary)` and set `manager_type` accordingly — the two columns must stay in sync." Also add a backlog entry for "Extend update_manager + admin PATCH endpoint to accept V2 fields + auto-derive `manager_type`."

2. **[C3]** Correct the task doc `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md` around line 162. Remove the claim that "second click returns 409 via the job system." Replace with the accurate description: the synchronous endpoint has no application-layer lock; two concurrent calls both hit Rate Guard (which serializes its own egress), both return a valid diff, and both complete safely.

### Staff Engineer Review — Deferrable findings

| ID | Severity | Finding | Suggested action |
|---|---|---|---|
| D1 | low | `capital_structure` index has no current query; forward-looking only. | Add a comment in the migration explaining the anticipated query pattern. |
| D2 | medium | `quant` manager_type is not derivable from any V2 `style_primary`. | Verify `confirmed_managers.json` has no entry intended to be `manager_type=quant`. |
| D3 | medium | `add_dataroma_candidates` may create a duplicate manager row for a manager already confirmed without a `dataroma_code`. No UNIQUE constraint on `dataroma_code`. | Add to backlog. |
| D4 | low | Auth test missing for `POST /admin/13f/managers/dataroma-sync` and `/add`. | Add test asserting 401/403 for unauthenticated callers in a follow-up. |
| D5 | low | `test_bootstrap_whitelist_job_type_uses_offline_seed_path` does not assert the seeded count is >0. | Strengthen assertion to `result["managers_seeded"] >= 80` in a follow-up. |
| D6 | low | `to_summary_dict()` sample truncation at 25 is untested. | Add a test with a >25-entry fake payload. |
| D7 | low | Three overlapping backlog entries for test isolation. | Create one GH issue linking all three backlog entries. |
| D8 | low | "Bootstrap whitelist" label in the frontend UI is an acknowledged follow-up rename. | Ensure the backlog has an entry. |

**Approval status**: Approved pending the two required pre-merge actions. No critical invariants from `AGENTS.md` are violated.

---

## Backend Reviewer Review

**Reviewer role**: Senior backend engineer (code quality)  
**Files reviewed**:
- `backend/app/services/edgar_ingestion.py`
- `backend/app/services/oracles_lens/manager_style.py`
- `backend/app/api/v1/endpoints/thirteenf_admin.py` (lines 446–525)
- `backend/app/cli/edgar.py`
- `backend/tests/unit/test_13f_manager_taxonomy_v2.py`
- `backend/tests/unit/test_13f_dataroma_sync.py`

---

### B1 — Lazy import in `seed_confirmed_managers`

**File**: `backend/app/services/edgar_ingestion.py`, line 104  
**Severity**: Nit

**The cycle claim is false. This is a premature/unnecessary lazy import.**

Tracing the actual import graph:
- `edgar_ingestion.py` imports from `app.models.institutions` at module level. That import happens regardless.
- `manager_style.py` imports only from `app.models.institutions` — specifically `MANAGER_TYPES` and `STYLE_PRIMARY`.
- `app.models.institutions` does **not** import from `edgar_ingestion` or from `manager_style`. There is no cycle anywhere in this chain.

The comment describes a diamond dependency (both modules importing from a third), not a circular dependency. Python handles diamond dependencies correctly by loading the shared module once; there is no risk. `manager_style.py` is never imported by anything in the `oracles_lens` package at module load time — the only production caller of `manager_style` is `edgar_ingestion.py` itself.

**Suggested fix**: Promote the import to the module-level block alongside the other `from app.*` imports. Remove the comment asserting an import cycle.

```python
# At module level, line ~22:
from app.services.oracles_lens.manager_style import derive_legacy_manager_type
```

---

### B2 — `derive_legacy_manager_type` error semantics

**File**: `backend/app/services/oracles_lens/manager_style.py`, lines 61–84  
**Severity**: Nit

Raising `ValueError` for any input not in `STYLE_PRIMARY_TO_LEGACY` is the right call. Fail-loud is correct because:
1. The function is called only from `seed_confirmed_managers()` (one call site) with a visible exception surface.
2. The seed JSON passes through CI test `test_seed_json_classifications_use_canonical_vocabularies` which validates every entry's `style_primary` against `STYLE_PRIMARY` before the seed runs.
3. A silent `unknown` default would mask misclassifications introduced by the exact failure mode this PR was created to fix.

The model's `@validates("style_primary")` (institutions.py line 203–205) will raise a `ValueError` first — before `derive_legacy_manager_type` is even called — because the validator checks against `STYLE_PRIMARY` on every assignment.

**Suggested fix**: Document in `manager_style.py` that `STYLE_PRIMARY` and `STYLE_PRIMARY_TO_LEGACY` must always be updated together. The existing test `test_style_to_legacy_mapping_is_exhaustive_over_style_primary` pins this invariant correctly.

---

### B3 — `DataromaSyncDiff.to_summary_dict` sample size

**File**: `backend/app/services/edgar_ingestion.py`, lines 296–319  
**Severity**: Nit/UX gap

**Is 25 the right cap?** For the `job_runs` storage path, yes — it's a correct defensive measure. In practice, Dataroma's manager universe is ~80–100 entries, so all entries fit within the cap under normal operation.

**The UX bug at the sync endpoint**: The endpoint at line 498:
```python
return diff.to_summary_dict()
```
calls with no arguments, returning at most 25 entries per bucket. If Dataroma added 30 new managers since our last sync, the `new_sample` would only contain 25. The `new_count` field would correctly show 30, but the FE cannot render Add checkboxes for all 30 — an admin who selects all 25 from the UI and clicks Add would silently miss 5 entries.

**Suggested fix**: For the API endpoint, pass a larger sample_size to ensure completeness:
```python
return diff.to_summary_dict(sample_size=500)
```
Keep the default 25 only for the `job_runs` storage path where truncation is intentional.

---

### B4 — `add_dataroma_candidates` idempotency window

**File**: `backend/app/services/edgar_ingestion.py`, lines 431–435  
**Severity**: Nit

```python
if existing is not None:
    existing.dataroma_synced_at = now
    existing.last_seen_at = now
    skipped += 1
    continue
```

Writing two timestamp columns on every call means the function is not strictly idempotent — it has observable side-effects each time. The "skipped" count and the "no writes" promise in the docstring are slightly inconsistent.

Additionally, `last_seen_at` on a row that `add_dataroma_candidates` is supposedly skipping is misleading: if the admin is calling this function with a selected subset of the diff (not all Dataroma entries), then updating `last_seen_at` on the pre-existing manager based on a different fetch's data is confusing.

**Suggested fix**: Either (a) document explicitly that "skipped" rows still get their `dataroma_synced_at` / `last_seen_at` bumped, or (b) remove the timestamp writes from the skip path and handle them in `sync_dataroma_managers`. Option (b) is cleaner: the diff function sees all Dataroma entries and is the right place to record "we saw this entry."

---

### B5 — Error handling in the API endpoint

**File**: `backend/app/api/v1/endpoints/thirteenf_admin.py`, lines 477–524

#### B5a — Missing exception types in `run_dataroma_sync`

**Severity**: Nit (no action required)

The endpoint catches `RateGuardFetchError`. Other candidates:
- `httpx.HTTPError` — already wrapped as `RateGuardFetchError` by `RateGuardClient.fetch`. Covered.
- `UnicodeDecodeError` — `parse_managers` calls `html.decode("utf-8", errors="replace")` which cannot raise. Safe.
- HTML parse errors — `_ManagerParser` uses `html.parser.HTMLParser`, which silently drops unparseable tags. Safe.
- `httpx.TimeoutException` — a subclass of `httpx.HTTPError`, already wrapped. Safe.

The exception handling is complete for all realistic failure paths. The `RateGuardFetchError` wrapper pattern is doing its job correctly. Documentation of why only `RateGuardFetchError` is needed would help future reviewers.

#### B5b — The `add` endpoint has no error handling

**Severity**: Nit

`add_dataroma_candidates` calls `db.flush()` at line 453. If the flush fails (e.g. a uniqueness constraint violation under concurrent requests), the exception propagates as an unhandled 500. The session is managed by FastAPI's dependency injection, so the transaction is rolled back, but the 500 error is not user-friendly.

**Suggested fix**: Catch `sqlalchemy.exc.IntegrityError` and return a 409 Conflict:
```python
except sqlalchemy.exc.IntegrityError as exc:
    raise HTTPException(status_code=409, detail="Entry already exists") from exc
```

---

### B6 — Test fixture `_make_existing` explicit `status="active"`

**File**: `backend/tests/unit/test_13f_dataroma_sync.py`, lines 39–56  
**Severity**: Nit

The `_populate_manager_prd_fields` SQLAlchemy event listener (institutions.py lines 234–242) fires on `before_insert` and derives `status="active"` from `match_status="confirmed"` automatically. The explicit `status="active"` in the fixture is redundant but not harmful.

**Suggested fix**: Remove `status="active"` from `_make_existing`. The fixture reads more cleanly without it and doesn't imply that callers must set `status` manually.

---

### B7 — The monkeypatch seam `_fetch_dataroma_managers`

**File**: `backend/app/services/edgar_ingestion.py`, lines 322–331

#### B7a — Is this the cleanest injection approach?

**Severity**: Acceptable as-is

The current approach extracts `_fetch_dataroma_managers` as a module-level function and patches it in tests via `monkeypatch.setattr`. This is standard pytest practice and works reliably. The `_` prefix convention signals "test seam" to future readers.

Alternative via default-parameter dependency injection:
```python
def sync_dataroma_managers(
    db: Session,
    *,
    _fetch: Callable[[], list[DataromaManager]] = _fetch_dataroma_managers,
) -> DataromaSyncDiff:
```
Tests would then pass `_fetch=lambda: fake_payload` as an argument. This has ergonomic advantages (no hidden global mutation, type-checkable) but is not materially better for a pure function with no parameters. The current approach is acceptable.

#### B7b — The return type annotation

**Severity**: Nit

```python
def _fetch_dataroma_managers() -> list:
```

The return type is `list` without a type argument. The actual returned type is `list[DataromaManager]`, which is what `sync_dataroma_managers` iterates over. `DataromaManager` is accessible via the existing import.

**Suggested fix**:
```python
from app.dataroma.parsers.managers import DataromaManager, parse_managers

def _fetch_dataroma_managers() -> list[DataromaManager]:
```

---

### Backend Review — Summary table

| Section | Severity | File | One-liner |
|---------|----------|------|-----------|
| B1 | Nit | `edgar_ingestion.py:104` | Lazy import avoids a cycle that doesn't exist; move to module level |
| B2 | Nit | `manager_style.py:61` | `ValueError` semantics are correct; add a paired-update note |
| B3 | Nit/UX gap | `edgar_ingestion.py:296` | `to_summary_dict()` at the API endpoint truncates at 25; FE may miss entries if Dataroma adds >25 new managers at once |
| B4 | Nit | `edgar_ingestion.py:431` | Timestamp side-effects on the "skip" path are not strictly idempotent; document or move to diff function |
| B5a | Nit | `thirteenf_admin.py:488` | `RateGuardFetchError` catch is sufficient; all other exceptions are already wrapped upstream |
| B5b | Nit | `thirteenf_admin.py:501` | `add` endpoint has no error handling; concurrent double-add could produce an unhandled 500 |
| B6 | Nit | `test_13f_dataroma_sync.py:49` | `status="active"` in `_make_existing` is redundant; `before_insert` event listener derives it from `match_status` |
| B7a | Nit | `edgar_ingestion.py:322` | Monkeypatch seam is acceptable; DI via default param is a cleaner but not materially better alternative |
| B7b | Nit | `edgar_ingestion.py:322` | Return type `list` should be `list[DataromaManager]`; `DataromaManager` is already accessible via the existing import |

**No blockers.** The core logic — the V2 taxonomy mapping, the seed/sync decoupling, the diff-then-add flow — is sound. The most actionable findings are B3 (potential UX data loss if Dataroma grows beyond 25 new entries) and B5b (unhandled concurrent-add race). All others are documentation-level nits.

---

## Consolidated action items

### Required before merge (Staff Engineer, C2 + C3)

1. **[C2]** Add comment to `update_manager()` in `backend/app/services/thirteenf_admin_dashboard.py` (after line 583) documenting the V2 derivation invariant. Add backlog entry for "Extend update_manager + admin PATCH endpoint to accept V2 fields + auto-derive `manager_type`."

2. **[C3]** Fix `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md` line 162 — remove the incorrect claim that concurrent sync calls return 409 via the job system.

### Recommended data fixes (PO, low priority)

3. **AltaRock Partners**: change `style_primary` from `value_concentrated` to `quality_compounder`.
4. **Ariel Investments**: change `market_cap_focus` from `small` to `mid`.
5. **Scion rationale**: update wording to "macro-contrarian with episodic high-conviction equity longs."

### Recommended code fixes (Backend, nit priority)

6. **B1**: Promote `derive_legacy_manager_type` import from lazy to module-level in `edgar_ingestion.py`.
7. **B3**: Pass `sample_size=500` (or equivalent) to `diff.to_summary_dict()` at the sync API endpoint to prevent silent truncation when Dataroma adds >25 new entries.
8. **B5b**: Add `IntegrityError` handling with 409 response to the `/dataroma-sync/add` endpoint.
9. **B7b**: Change `_fetch_dataroma_managers` return type from `list` to `list[DataromaManager]`.

---

## Re-review after `a271f90`

Review date: 2026-05-24

Reviewed commit: `a271f90` — `Address review findings (2 blockers + 4 must-fix + 2 nits)`

Targeted verification run:

```bash
docker compose exec -T api pytest -q tests/unit/test_13f_dataroma_sync.py tests/unit/test_13f_manager_taxonomy_v2.py
```

Result: `37 passed in 0.34s`.

### Previous blockers

**B3 / full Dataroma diff returned to FE: resolved.**

`backend/app/api/v1/endpoints/thirteenf_admin.py:504` now calls `diff.to_summary_dict(sample_size=None)`, and `DataromaSyncDiff.to_summary_dict()` documents the `None` behavior as "no cap." The added tests cover both the capped job-summary path and the full endpoint path:

- `test_to_summary_dict_default_caps_samples_at_25`
- `test_to_summary_dict_none_returns_full_lists`

The frontend can continue reading `new_sample`, because the endpoint now intentionally fills that field with the full list for the synchronous UI call.

**B5 / add endpoint durability: resolved.**

`add_dataroma_candidates()` now commits on success (`backend/app/services/edgar_ingestion.py:487`). The new durability test opens a fresh `SessionLocal` after the call and verifies the row persisted:

- `test_add_dataroma_candidates_commits_so_data_is_durable`

The service also wraps per-entry inserts in a nested transaction and catches `IntegrityError`, which addresses the concurrent double-add concern when the partial unique index fires.

### Required actions from the first review

**C2 / V2 derivation invariant comment: resolved.**

`backend/app/services/thirteenf_admin_dashboard.py:587` now explicitly documents that any future `style_primary` edit path must also re-derive `manager_type`.

**C3 / task-doc concurrency claim: resolved.**

`docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md:162` now correctly says the synchronous endpoints are not job-locked and that Rate Guard handles upstream rate limiting.

### New finding

**R1 — Documentation incorrectly says `dataroma_code` lacks a DB-level unique constraint.**

Severity: low / documentation correctness.

Files:

- `docs/BACKLOG.md:12`
- `backend/app/services/edgar_ingestion.py:423`
- `docs/tasks/2026-05-24_bootstrap-decouple-dataroma-sync.md:169`

These comments say `institution_managers.dataroma_code` has no DB-level unique constraint, but `backend/alembic/versions/20260423000000-add_13f_ingestion_tables.py:59` already creates a partial unique index:

```python
op.create_index(
    "uq_institution_managers_dataroma_code",
    "institution_managers",
    ["dataroma_code"],
    unique=True,
    postgresql_where=sa.text("dataroma_code IS NOT NULL"),
)
```

Impact: not a code blocker. The current SAVEPOINT + `IntegrityError` handling is actually useful because the DB should raise on duplicate non-null `dataroma_code`. But the backlog entry and comments should be corrected or removed so a future agent does not add a duplicate migration for a constraint that already exists.

Suggested fix: replace the backlog item with a narrower follow-up if desired: "Mirror the partial unique index in SQLAlchemy model metadata / add regression test for duplicate `dataroma_code`." Update the service/task-doc comments to say the DB unique index is the load-bearing protection.

### Re-review verdict

**Approved with one low-severity documentation cleanup.** The two prior blockers are resolved, targeted tests pass, and no new blocking code issues were found.
