# 13F MVP 4 End-to-End Review Prompts

Four reviewer prompts for the MVP 4 end-to-end review. Each is
self-contained — drop the prompt into a fresh chat or hand it to a
human reviewer without needing the rest of this repository's history.
Verification baseline is captured in
`docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`.

Roles:

1. Tech Lead — cross-task architecture / contract consistency.
2. Product Owner — D1–D6 closure + scope-freeze + next milestone.
3. 13F Domain SME — scoring vocabulary correctness + caveat
   semantics + manager_type taxonomy.
4. Frontend / UX (optional) — Oracle's Lens persisted-mode surface
   and admin Card placement.

---

## 1. Tech Lead Prompt

You are conducting the Tech Lead cross-task review for the ValuePilot
13F automation MVP 4 milestone. Eleven sub-tasks have shipped on
branch `docs/13f-automation-prd`:

- `MVP4-01` Oracle's Lens score schema + ORM
  (`backend/alembic/versions/20260511140000-mvp4_01_oracles_lens_score_schema.py`,
  `oracles_lens_signals` + `oracles_lens_signal_components` tables,
  `score_version` column).
- `MVP4-02` holding streak + portfolio weight base primitives
  (`backend/app/services/oracles_lens/base_primitives.py`).
- `MVP4-03` signal-weighted consensus score service
  (`backend/app/services/oracles_lens/signal_weighted_score.py`).
- `MVP4-03b` dashboard endpoint `use_persisted_scores=true` opt-in.
- `MVP4-04` conviction score service
  (5-component capped 0-100, lives in the same `signal_weighted_score`
  module).
- `MVP4-05` caution flags service with Class A / Class B distinction
  (only Class A delta-only suppression is implemented; Class B
  whole-holder exclusion is backlog).
- `MVP4-06` distinctive consensus score (§7.11 multiplier).
- `MVP4-07a` frontend persisted-scores wire-up
  (`frontend/app/(dashboard)/13f/oracles-lens/page.tsx`,
  `frontend/lib/oraclesLens.js`).
- `MVP4-07b` admin unknown-manager priority surface
  (`backend/app/services/oracles_lens/unknown_manager_priority.py`,
  admin Card in `frontend/app/(dashboard)/admin/13f/page.tsx`).
- `MVP4-08` `quality_reports_13f.is_dry_run` source linkage.
- `MVP4-09` shared rule_code constants
  (`backend/app/services/thirteenf_quality_codes.py`).
- `MVP4-10` conftest savepoint hardening
  (SQLAlchemy 2.0 `join_transaction_mode="create_savepoint"`).
- `MVP4-11` manager_type taxonomy reconciliation (8-value canonical
  vocabulary; admin / behavior / fallback_unknown source labels).

Verification baseline: 754 backend tests / 0 warnings; alembic head
`20260512120000`; frontend lint + 15 `oraclesLens.test.js` cases +
production build all pass.

Review these cross-cutting concerns and return a verdict plus a list
of pre-merge action items vs follow-up items:

1. **score_version evolution path.** `SCORE_VERSION="v1.0"` is hard-
   coded in `app/services/oracles_lens/constants.py`. Walk the call
   chain — is there a clean path for shipping `v1.1` alongside `v1.0`
   without invalidating the `oracles_lens_signals` upsert key
   `(stock_id, report_quarter, score_version)` or stranding the
   admin priority queue on the old version? Anything that should
   move into MVP4-01-style design notes before the first version
   bump?
2. **ORM upsert vs IntegrityError translator consistency.** MVP4-01
   chose ORM upsert; MVP3-05 / 07 used `IntegrityError` translators
   for JobRun lock-key races. Is the inconsistency intentional and
   documented, or did MVP4 silently re-litigate the pattern?
3. **`_HolderContribution` shared dataclass.** Used by MVP4-03, 04,
   and 06 in a single pass. Look at
   `signal_weighted_score.py` for coupling debt — does adding a
   future scoring component require modifying all three call sites,
   and is that the right trade-off vs three independent scorers?
4. **Conftest savepoint hardening reality check.** `pytest -q`
   currently shows 0 warnings (was 3 SAWarnings under MVP3). Does
   the `join_transaction_mode="create_savepoint"` recipe still hold
   under MVP4-08's IntegrityError-prone backfill writer, or did
   MVP4-08 inadvertently dodge the warning class instead of
   exercising it? If you need a stress, look at
   `tests/unit/test_13f_mvp3_historical_backfill.py::test_enqueue_translates_unique_index_race`.
5. **Dashboard formula divergence backlog.** The dashboard's
   in-memory `min(weight*4, 1.0)` base differs from the persisted
   MVP4-03 `portfolio_weight` raw value. The `?persisted=0` debug
   flag is intended as a one-release escape hatch. Is the
   reconciliation backlog correctly framed, or is there an
   architectural reason to keep both paths permanently?
6. **Rule_code constants module reuse.**
   `thirteenf_quality_codes.py` now owns the five rule_codes across
   three services. Did MVP4-05's caution-flag rule_codes correctly
   route through this module, or are there literal strings still
   floating in the scoring services?
7. **`is_dry_run` filter coverage.** MVP4-08 filters dry-run rows
   out of `build_quality_reports` and `_latest_quality_report`. Are
   there other consumers of `QualityReport13F` (readiness API,
   admin dashboard rollups, frontend) that still treat dry-run rows
   as real and need the same filter?
8. **Test-suite shape.** 114 tests across 11 MVP4 files. Spot-check
   the test isolation pattern — does each test file follow the same
   `_CIK_SEQ` / `_ACC_SEQ` counter pattern, or did MVP4-07b /
   MVP4-08 introduce a new fixture style that future contributors
   would have to choose between?

Deliverable: APPROVE / APPROVE-WITH-FIXES / REJECT, plus a pre-merge
action list (must-land-before-MVP5 opens) vs a follow-up list (file
as MVP5 backlog).

---

## 2. Product Owner Prompt

You are the Product Owner reviewing the MVP 4 milestone closure for
the ValuePilot 13F automation track. The milestone shipped 11
sub-tasks plus 3 splits (03b / 07a / 07b) over the last two days; the
verification baseline is captured in
`docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`.

Your goal is to confirm that:

1. **D1–D6 closure is real, not formal.** Walk each row of the
   "Decision Gate Verification" table in the verification doc and
   open the cited file / commit to spot-check. Particular attention
   to:
   - D1: are the four score columns the only persisted metrics? Did
     anything else sneak in?
   - D3: distinctive consensus is "visible-but-off-by-default" — is
     that the actual UX in `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`,
     or did MVP4-07a make it default-on?
   - D5: `score_version="v1.0"` is in the constants module — is
     that the agreed approach (typed Python, not JSON/TOML), or did
     someone smuggle in a config file?
2. **Scope-freeze tally is zero.** The verification doc claims no
   new debt was opened. Cross-check by reading the five deferred
   items in "Scope-Freeze Tally" — each one should map to an
   explicit task-file backlog line, not a vague "we'll get to it."
3. **`?persisted=0` debug-flag lifecycle.** MVP4-07a leaves the
   legacy in-memory path behind this debug flag for "one release
   cycle." Decide now (not later) what condition retires the flag:
   - Is a release cycle one calendar window, one milestone (MVP5
     close), or one decision in a review?
   - Who confirms "no discrepancy observed"? Is the admin priority
     queue (MVP4-07b) the right surface, or do we need a different
     observability path?
4. **Class A vs Class B caveat decision is still right.** You
   personally signed off on "保留现在的设计，不要把整个
   position_signal_weight 归零" for Class A caveats. Class B
   exclusion is backlog. Now that the code is live, do you want
   Class B in MVP5 scope, or push it further?
5. **`multi_strategy=unknown=0.60` V1 fallback.** PO call: "V1 按
   unknown=0.60 保守处理，不做伪精确判断". Confirm this is still
   the right call after MVP4-11 manager_type taxonomy reconciliation
   landed — is the conservative fallback driving any
   `manager_type=unknown` visible regression that surfaces in the
   MVP4-07b admin priority queue?
6. **MVP4-07b CTA absence.** The admin Card has no "classify
   manager" button, only ranked rows. Is this the right product
   semantics ("priority queue, classification lives elsewhere"), or
   should an MVP5 task wire a manager-type edit surface?
7. **Pre-MVP5 candidate ordering.** Three are queued from the
   verification doc Recommendation section: Class B caveats,
   formula reconciliation, pre-2023 productionization. Rank them
   and assign a tentative owner. Is any of them blocked on data /
   stakeholder input you need to request now?

Deliverable: D1–D6 verdict per row, scope-freeze tally confirm or
reopen, ordered pre-MVP5 candidate list with owners, and an explicit
recommendation on whether to open the MVP5 decision gate this week.

---

## 3. 13F Domain SME Prompt

You are the 13F Domain SME reviewing the MVP 4 scoring stack. MVP 4
is the first milestone that exposes plan §7.2 / §7.9 / §7.11 / §7.13
to end users via the Oracle's Lens dashboard. Verification baseline:
`docs/tasks/2026-05-12_13f-mvp4-end-to-end-verification.md`.

Your goal is to confirm financial-data and scoring-semantics
correctness — formula fidelity, caveat propagation rules, and the
manager_type taxonomy that drives `manager_signal_weight`.

Specifically:

1. **Plan §7.2 signal-weighted consensus formula fidelity.** Open
   `backend/app/services/oracles_lens/signal_weighted_score.py`
   and verify the formula matches plan §7.2 line-for-line —
   `manager_signal_weight * portfolio_weight_factor + action_adjustment`.
   Are the manager weights in `MANAGER_SIGNAL_WEIGHTS` the actual
   approved values? Is `portfolio_weight_factor` the raw
   `portfolio_weight` (as MVP4-03 chose) or the
   `min(weight*4, 1.0)` legacy form (which now only lives in the
   dashboard in-memory path)? If the latter is correct, MVP4-03 has
   a formula bug; if the former, the dashboard formula divergence
   backlog is genuinely a divergence and needs reconciliation.
2. **Conviction score §7.9 component caps.** The
   `_HolderContribution` dataclass now carries
   `holding_streak_quarters` and `add_intensity` raw fields. Walk
   the 5 components of the conviction score and confirm each one
   is capped at the documented value, not the inferred
   sub-4-quarter precision that an earlier draft lost.
3. **Distinctive consensus §7.11 multiplier.** Three factors in
   [0,1] multiplied together. Open the distinctive-consensus
   service and confirm the three factors and their data sources
   match plan §7.11 — in particular, the "distinctive holder
   count" factor should reflect the post-MVP4-11 8-value taxonomy,
   not the pre-MVP4-11 legacy enum names.
4. **Class A caveat-propagation rules.** Plan §7.13 + the SME
   remediation specified four Class A delta-only caveats:
   `stale_until_recompute`, `HISTORICAL_BACKFILL_NEEDS_VALIDATION`,
   `PRE_2023_PRE_HISTORY_UNAVAILABLE`,
   `OWNERSHIP_CHANGE_NEEDS_RECOMPUTE_CUSIP_CORPORATE_ACTION`. Walk
   `signal_weighted_score.py`'s `_LOW_CAVEATS` and `_MEDIUM_CAVEATS`
   sets and confirm:
   - All four codes are present in the right tier.
   - The Class A behavior (suppress `action_adjustment` only;
     snapshot bonuses still apply; `score_confidence` demotes to
     low) is what the code actually does.
   - No Class B (snapshot-integrity) caveat has been promoted into
     Class A by accident.
5. **`score_confidence` demotion contract.** MVP4-01 PO P2 #4
   guaranteed `score_explanation.confidence_demotion_reasons`
   surfaces the reasons. Verify the reasons list is the full set,
   not silently truncated, and that the worst-tier wins correctly
   across multiple caveats on the same holder.
6. **Manager_type 8-value taxonomy mapping.** MVP4-11 reconciled
   to: `long_term_fundamental`, `value_concentrated`, `activist`,
   `quant`, `high_turnover`, `index_like`, `multi_strategy`,
   `unknown`. Confirm each value has the documented
   `manager_signal_weight` (especially `multi_strategy=0.60` as
   the conservative V1 fallback) and that the
   `admin / behavior / fallback_unknown` source-label precedence
   is implemented as: admin wins → admin=unknown falls back to
   behavior → no admin and no behavior → `fallback_unknown=0.60`.
7. **Kahn Brothers $-not-$K trap.** `0001039565-*` reports values
   in dollars, not thousands. Does the scoring stack assume
   `value_thousands` is always in thousands? If a Kahn-Brothers-
   like filing leaks into the corpus, does the
   `portfolio_weight` calculation mis-size by 1000x and bias the
   distinctive consensus score? Look for an explicit guard.

Deliverable: per-item APPROVE / FLAG / BLOCK verdict. BLOCKs require
a pre-MVP5-open fix; FLAGs can be filed as MVP5 backlog.

---

## 4. Frontend / UX Reviewer Prompt (Optional)

You are the Frontend / UX reviewer for the MVP 4 user-facing surface
changes. MVP 4 is the first time persisted Oracle's Lens scores hit
the user dashboard, and the first admin priority queue surfaces
manager-typing debt.

Files in scope:

- `frontend/app/(dashboard)/13f/oracles-lens/page.tsx`
  (MVP4-07a persisted-mode wire-up).
- `frontend/lib/oraclesLens.js` (normalizer).
- `frontend/lib/oraclesLens.test.js` (15 cases, +1 from 07a).
- `frontend/app/(dashboard)/admin/13f/page.tsx`
  (MVP4-07b admin Card insertion).

Review:

1. **Persisted-mode default + debug opt-out.**
   `buildOracleLensQueryParams` defaults to
   `use_persisted_scores=true`; the legacy path is behind
   `?persisted=0` for one release cycle. The implementation reads
   `window.location.search` inside `useEffect` instead of
   `useSearchParams()` to avoid forcing a Suspense boundary. Is
   this a correct trade-off, or does it create a flash of
   wrong-mode content on first paint that users will notice?
2. **Persisted badge attribution.** The persisted badge renders
   next to the existing confidence badge. Is the visual hierarchy
   right — does the user understand which signals are from the
   canonical scoring table vs the legacy compute path? Does the
   badge survive screenreader / keyboard navigation?
3. **`confidence_demotion_reasons` drilldown.** Surfaced as a
   "Confidence demoted by" panel listing `{code, demoted_to}`
   pairs. Is the format readable for non-technical users, or
   does the rule_code string (e.g.
   `HISTORICAL_BACKFILL_NEEDS_VALIDATION`) need a friendly label
   mapping?
4. **MVP4-07b admin Card placement.** The new Card is inserted
   between "Needs Validation" and "Batch Reparse" on a 3300-line
   admin page. Is this the right cognitive position
   ("validation backlog → manager-typing backlog → reparse
   ops"), or should it live near the existing managers section
   ~line 2344?
5. **Empty states.** MVP4-07b has two empty states ("no
   persisted scores yet — run a backfill" and "no unknown
   managers contribute"). Are both reachable in production
   reality, and does the copy guide the admin to the right next
   action?
6. **No CTA on the admin Card.** Each row is ranked but there's
   no "edit manager_type" button — the manager-type edit surface
   doesn't exist yet. Is this acceptable for the priority queue
   pattern, or does the admin need at least a deep link
   (`/admin/managers/{id}`) even if the target page is TBD?
7. **A11y / responsive baseline.** Run lint + build; spot-check
   that the persisted badge + drilldown panel + admin table do
   not introduce contrast / focus regressions vs MVP3.

Deliverable: per-item APPROVE / RECOMMEND-CHANGE / BLOCK, with
specific copy / spacing / interaction notes that can land as a
follow-up task.
