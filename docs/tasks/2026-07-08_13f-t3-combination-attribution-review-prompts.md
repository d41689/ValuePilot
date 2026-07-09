# Review prompts — T3 (组合/共享裁量归因,让巴菲特可见)

Task doc: [`2026-07-08_13f-t3-combination-attribution.md`](./2026-07-08_13f-t3-combination-attribution.md)
PO plan: [`2026-07-08_13f-real-data-findings-po-plan.md`](./2026-07-08_13f-real-data-findings-po-plan.md)
Branch: `claude/13f-t3-combination-attribution` · PR #109 (CI green).
Read the diff with `git diff main...claude/13f-t3-combination-attribution`.

## What changed

- **Attribution rule** (`backend/app/services/thirteenf_holdings_ingest.py`
  `_compute_attribution_status`): a holding in a manager's own HR/HR-A infotable
  is that manager's reportable position. `SOLE`/`DFND`/`OTR` **with** a
  co-manager reference in `other_managers_raw` → `direct`; `DFND`/`OTR`
  **without** a reference → `unresolved`. (Was: `DFND`+refs → `reported_for_other`,
  `OTR` → `shared` — both excluded from the product surface.)
- **Backfill** (`backfill_holding_attribution` + CLI `backfill-attribution`):
  recompute existing rows via the same rule; idempotent.
- **Caveat copy** (`thirteenf_user_api.py` `COMBINATION_CAVEAT`): no longer says
  holdings are "not included here".
- **`_pair_key` crash fix** (`thirteenf_ownership_changes.py`): now always keys
  CUSIP-fallback pairs by CUSIP (removed the both-`stock_id` → stock-key branch).

## Context a reviewer cannot see from the diff alone

- **Root cause (verified on real data):** `other_managers_raw` holds cover-page
  **included-manager sequence numbers** (`4,8,11`), NOT external CIKs. So
  `DFND`/`OTR` + refs is the multi-manager / combination-report pattern, and the
  referenced managers are the filer's OWN included sub-entities, not separate
  universe filers.
- **This refines PRD §638/§646.** The PRD mapped `DFND`+parseable →
  `reported_for_other` with a planned MVP3 "attribute to that manager". That
  assumed the other manager is a distinct known filer; for combination reports it
  is a sub-entity of the filer. The PO ruling
  (`2026-07-08_13f-real-data-findings-po-plan.md` §2) makes the call to attribute
  to the filer. Treat the ruling as the product decision under review, and
  sanity-check it against SEC 13F semantics — do not treat the old PRD text as
  locked.
- **Reuses `direct`** — no new enum, no schema change. Every consumer that
  filters `holding_attribution_status == 'direct'` (ownership_changes,
  `thirteenf_user_api`, `oracles_lens/signal_weighted_score` ×5,
  `oracles_lens/unknown_manager_priority`) now includes ~4,050 more holdings with
  zero read-site change. Blast radius is the whole product surface.
- **The `_pair_key` fix is a crash T3 EXPOSED, not introduced by it.** Once
  combination filers gained `direct` holdings they entered the ownership-changes
  *normal* path, where a security held under multiple CUSIPs in BOTH quarters made
  a `_matched_pairs` straggler re-key to the stock key and collide with the
  stock-match row (`uq_ownership_changes_manager_quarter_security_position`).
  NOTE: the T2 review asserted the normal path never dup-crashes — true for
  new positions, false for this matched-both-quarters case. T2's per-manager
  savepoint isolated it (partial_success), so it degraded rather than broke.
- **Known non-issue — do NOT flag as a T3 bug:** Oaktree's changes stay
  `unavailable` because its 2026-Q1 mapping ratio is 0.35 (55/147 CUSIP-linked),
  tripping the pre-existing mapping-ratio gate in `_unavailable_reason`. That is a
  CUSIP-enrichment-coverage matter, honest degradation, separate from attribution.
- **Test isolation:** dev DB `valuepilot` holds real data; pytest must run on the
  isolated DB:
  ```
  TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
  ```
- **Already verified (re-confirm, don't trust):** full backend suite **1078
  passed**; backfill re-attributed 4,050 holdings; zero-direct managers → 0;
  recompute across 6 quarters 0 failures; Buffett's changes API returns 62 real
  moves (was NO_COMPUTED_CHANGES); all 7 flagship managers have Oracle's Lens
  components (Berkshire 268, was 0); a sample check found no stock double-counting
  Berkshire.
- **Deferred (BACKLOG):** cross-filer double-count review guard (claimed
  not-currently-triggerable); positions read-model (sum multi-CUSIP lots into one
  position).

Three prompts for three agents. Run in parallel; collect findings in
`2026-07-08_13f-t3-combination-attribution-review-results.md`.

---

## Prompt 1 — Attribution semantics (the critical angle)

```
You are a 13F domain expert reviewing an attribution-rule change that decides
which holdings count as a manager's own reportable position. The rule now treats
any SOLE/DFND/OTR holding in the manager's own HR/HR-A infotable as `direct`
(shared-discretion co-managers being the filing's own included managers);
exclusion is meant to live only at the filing level (13F-NT). This value feeds
the entire product: managers API, ownership changes, and Oracle's Lens consensus
scoring.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t3-combination-attribution`.
Read first:
  - backend/app/services/thirteenf_holdings_ingest.py (_compute_attribution_status,
    normalize_investment_discretion, backfill_holding_attribution).
  - docs/prd/13f_automation_and_resilience_prd.md §12 / §638 / §646 (the prior rule).
  - docs/tasks/2026-07-08_13f-real-data-findings-po-plan.md §2 (the ruling) and
    the "Context" section of this doc.
  - The read sites: grep `holding_attribution_status` across
    backend/app/services (ownership_changes, thirteenf_user_api,
    oracles_lens/*). 

Pressure-test, with a concrete filing/holding for each real finding:
  1. Over-inclusion: is there ANY case where a holding sits in a manager's HR
     infotable but should NOT be attributed to that manager (a genuine
     "reported on behalf of a distinct EXTERNAL manager" that is now wrongly
     `direct`)? Consider Type-2 combination filings, sub-advised assets, and
     dual-reported positions. If such a case exists, how would we detect it?
  2. Double-count: the PR defers a cross-filer guard as "not currently
     triggerable". Verify that claim — could two universe managers (a parent and
     an included sub-manager, or two managers sharing discretion) both now report
     the same (stock, quarter) as `direct` and inflate Oracle's Lens consensus?
     Check the 82-manager universe for parent/sub or shared-discretion overlaps.
  3. OTR-no-refs and DFND-no-refs → `unresolved`: is dropping to `unresolved`
     (vs the old `shared`) correct, and does any consumer still rely on `shared`?
  4. Is `holding_attribution_status` now near-vestigial (almost always `direct`)?
     Should the exclusion be modeled at the filing level instead, and does that
     change the answer for any real filing?
  5. Caveat honesty: with combination holdings now included, is the corrected
     COMBINATION_CAVEAT wording accurate, and is the caveat still attached
     wherever those holdings surface?

Output: file:line, the concrete filing/holding, and the wrong attribution or
double-count. If the rule is correct, justify why every infotable holding is the
filer's reportable position and why no universe double-count exists.
```

---

## Prompt 2 — The `_pair_key` crash fix & change classification

```
You are reviewing a one-line-ish fix to ownership-change matching. `_pair_key`
now always keys CUSIP-fallback pairs by CUSIP; previously it returned a stock key
when both sides had a stock_id, which collided with the stock-match row when a
security was held under multiple CUSIPs in both quarters (dup-key crash exposed
once combination filers gained direct holdings).

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t3-combination-attribution`.
Read first:
  - backend/app/services/thirteenf_ownership_changes.py — _matched_pairs,
    _pair_key, _stock_key, _cusip_key, _classify_change, _build_change_row, and
    the T2 aggregation in the unavailable branch.
  - The unique constraint uq_ownership_changes_manager_quarter_security_position.
  - The "Context" section of this doc (why the crash appears and what T2 already
    fixed) + the isolated-DB test recipe.

Probe:
  1. Does always-CUSIP keying HIDE a real match or change a classification?
     Specifically the cusip_changed case: a holding under CUSIP A last quarter and
     CUSIP B this quarter for the SAME stock — is it still matched (by the stock
     pass) and classified cusip_changed, or does the fallback now mis-handle it?
  2. Per-lot fragmentation: a stock under two CUSIPs in both quarters now yields
     two rows (one stock-keyed from the stock pass, one cusip-keyed from the
     fallback). Are the two rows' deltas each correct? In particular, the
     stock-match pass uses a dict (last-wins) on both sides — can it pair CUSIP-Y
     current against CUSIP-Z previous (cross-lot), producing a wrong delta?
  3. security_key label change: fallback pairs that had both stock_ids now get
     `cusip:X` instead of `stock:X`. Does any consumer, dedup, or downstream join
     key on security_key in a way this breaks?
  4. Residual dup-key: after this change, can any path (stock pass + fallback,
     put/call, unlinked cusip, T2 unavailable-branch aggregation) still emit two
     rows with the same (manager, quarter, security_key, ssh_prnamt_type,
     position_type)?
  5. Re-run the crash proof on valuepilot_test: construct a stock held under two
     CUSIPs in both quarters, revert _pair_key to the stock-branch version, and
     confirm it dup-crashes; restore and confirm it does not. Report if it does
     not reproduce.

Output: file:line, concrete holdings, wrong/duplicate/missed result. If sound,
justify why keying by CUSIP loses no correct match and why no key collides.
```

---

## Prompt 3 — Backfill, product blast radius & altitude

```
You are a staff engineer reviewing a data backfill and its product blast radius.
The rule reuses the existing `direct` value, so ~4,050 previously-excluded
holdings across 9 managers now flow into every consumer that filters `direct`,
including Oracle's Lens consensus/conviction scoring. A backfill migrates
historical rows; there is no schema migration.

Repository: ValuePilot (local). Read with
`git diff main...claude/13f-t3-combination-attribution`.
Read first:
  - backend/app/services/thirteenf_holdings_ingest.py (backfill_holding_attribution).
  - backend/app/cli/edgar.py (backfill-attribution command).
  - The Oracle's Lens consumers: backend/app/services/oracles_lens/
    signal_weighted_score.py, conviction_score.py, distinctive_consensus.py,
    unknown_manager_priority.py.
  - docs/tasks/2026-07-08_13f-t3-combination-attribution.md + the "Context" here.

Judge:
  1. Backfill correctness & prod-safety: it reads stored (already-normalized)
     `investment_discretion` and recomputes. Is a data backfill the right vehicle
     vs. re-ingesting from raw XML? Is it safe to run once post-deploy, idempotent,
     and does it need to be an Alembic data migration or a guarded command? What
     re-runs (ownership_changes, Oracle's Lens) MUST follow it, and does the PR/
     task doc make that ordering explicit for prod?
  2. Blast radius: adding ~4,050 direct holdings changes consensus counts,
     signal-weighted scores, distinctive-consensus (only-lowers) and conviction.
     Is any of these inflated or distorted by combination filers now counting? Do
     manager_signal_weight / taxonomy resolution behave for the newly-visible
     managers (Berkshire, Oaktree, ...)?
  3. Altitude: is attribution correctly a per-holding field, or should exclusion
     be a filing-level concept (NT) with holdings always attributed to the filer?
     Is the deferred positions read-model the right long-term home for multi-CUSIP
     summation, and does anything in this PR make that harder?
  4. Mapping-ratio gate: with more direct holdings, is the `_unavailable_reason`
     mapping-ratio threshold (0.50 block / 0.70 ready) still appropriate — e.g.
     Oaktree at 0.35 shows no changes. Is gating on enrichment coverage the right
     behavior, or does it now hide too much?
  5. Test adequacy: are the contract + backfill + crash tests enough, or is a
     consumer-level test missing (e.g. a combination manager appearing in
     Oracle's Lens output with the expected score contribution)?

Output: a verdict on backfill safety and blast-radius correctness, plus concrete
follow-ups (prod runbook ordering, any consumer test to add). Do not rewrite code.
```
