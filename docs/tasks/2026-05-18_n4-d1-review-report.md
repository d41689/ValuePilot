# N4 D1 + Framing Fix — Review Report

**Review date**: 2026-05-18
**Branch**: `docs/13f-automation-prd`
**Commits under review**:
- `559fbe0` — Resolve N4 vs snapshot framing inconsistency (docs-only)
- `397893b` — N4 D1: migration round-trip + 3 time-bound test fixes

**Method**: Read N4 ticket (incl. D1 results section), `20260513140000` migration file, `test_13f_user_api.py` (lines 1-111), `test_13f_admin_dashboard.py` (lines 1-120 + grep for freeze sites), `deploy.yml`, `ci.yml`, open-work snapshot, review-response addendum, comprehensive review report. Grep: `date\.today()` across `backend/app/services/`, remaining `date(2026, 5, 15)` across `backend/tests/`.

---

## 1. Backend Review

**APPROVE WITH NOTES**

---

### B1 — Migration downgrade pre-check correctness

`bind.execute(sa.text(...)).scalar()` is the correct idiom. `op.get_bind()` is the canonical Alembic connection accessor; the inline `SELECT COUNT(*)` against it is standard practice in Alembic 1.x and 2.x migrations. The `or 0` guard handles a `None` scalar return from an empty table correctly.

The `RuntimeError` fires **before** `op.alter_column()` is called — no DDL is ever applied when offending rows are present. PostgreSQL's transactional DDL would roll back any DDL that did start, but here the exception fires in Python before Alembic submits the ALTER. The migration is always left in a clean state.

**Edge case — empty table**: `scalar()` returns `0` (or `None`, coerced by `or 0`), `offending = 0`, pre-check passes, `op.alter_column()` runs. Correct.

**Edge case — absent table**: `SELECT COUNT(*)` would raise `ProgrammingError (UndefinedRelation)`. This is unreachable during a normal downgrade chain: `cusip_ticker_map` is created by `20260423000000`, which runs *after* `20260513140000` in the downgrade sequence. At the point this migration's `downgrade()` runs, the table always exists. Structurally sound.

**One nit (future-proofing only)**: Alembic 2.x emits a `LegacyAPIWarning` when `op.get_bind()` is called outside a migration-level execution context. If the project upgrades Alembic past 2.0 and warnings-as-errors is enabled, this will surface. The idiomatic 2.x replacement is `op.get_context().begin_transaction()`. Not blocking at the current Alembic version; flag if `alembic` is bumped.

---

### B2 — Test fixture relativization (`test_13f_user_api.py`)

`_filing` is a plain function; `date.today()` evaluates at call time, not at import time. Confirmed at line 100: the expression is in the function body, not a default argument. `+10 days` is robust against all timezone/clock scenarios.

**Gap not closed by this commit**: `test_13f_mvp4_unknown_manager_priority.py:103` and `test_13f_mvp5_02_amendment_exclusion.py:95` still have `official_filing_deadline=date(2026, 5, 15)`. Grep confirms neither file references `FILING_WINDOW_OPEN`, `filing_deadline`, or any deadline-conditional assertion — the hardcoded date is a dormant fixture field that doesn't influence any asserted behavior. Both tests are passing for that reason.

The pattern is the same time-bomb that caused the three failures this commit fixed. The sweep was incomplete. Filing as future-backlog: relativize those two fixtures for consistency, even though they currently pass.

---

### B3 — `_FrozenDate` monkeypatch pattern

The pattern is correct and standard for monkeypatching stdlib date:

- `isinstance(_FrozenDate.today(), date)` → True. Downstream `isinstance(x, date)` checks work correctly.
- `type(x) is date` → False for frozen instances. Unusual in production code; not a concern here.
- `_FrozenDate.today() + timedelta(N)` → returns a plain `date` (CPython's `date.__add__` does not preserve the subclass). Arithmetic results are correct.

**Coverage gap — `thirteenf_user_api.py`**: `thirteenf_user_api.py:494` calls `date.today()` directly for the `FILING_WINDOW_OPEN` caveat check. The monkeypatch does NOT cover `app.services.thirteenf_user_api`. This is acceptable: `test_13f_user_api.py` uses a different strategy — it makes `official_filing_deadline` always 10 days in the future, so `date.today() <= deadline` is always True regardless of real date. Both approaches work, but they are inconsistent: admin dashboard tests freeze the clock; user API tests advance the deadline. A future maintainer adding a third time-sensitive 13F test file may not know which pattern to follow. A one-line cross-reference comment in `_freeze_today`'s docstring would help.

**Coverage confirmed safe — `thirteenf_health.py`**: `thirteenf_health.py:82` uses `today = today or date.today()`, and the monkeypatch does NOT cover this module. This is safe because `thirteenf_admin_dashboard.py` does not import `thirteenf_health` — it defines its own `_quarter_health()` function (confirmed by grep). No coverage gap in the tested call chain.

---

### B4 — Freeze date choice (`date(2026, 5, 14)`)

The frozen date is correctly chosen and durable for the current fixture set. 2025-Q4's deadline is 2026-02-14; frozen today is 2026-05-14; 2026-02-14 ≤ 2026-05-14 → `_latest_closed_quarter` returns 2025-Q4 deterministically. The `_clear_13f()` wipe-and-reseed pattern ensures no ambient quarter data leaks between tests.

The frozen date will not become stale unless a test function that calls `_freeze_today` also seeds a later quarter's fixtures. The docstring explains the 2026-Q1 deadline relationship but does not say "update this frozen date if you add 2026-Q1 or later fixtures to these test functions." That instruction would help a future maintainer who expands the fixture set. Consider adding it.

---

### B5 — Are the 3 time-bound tests genuinely pre-existing debt?

Yes. The framing is accurate. `official_filing_deadline=date(2026, 5, 15)` was written during original MVP development when 2026-05-15 was the correct future deadline. The admin dashboard 2025-Q4 fixture seeds similarly predate this PR. Calendar advance to 2026-05-18 is what triggered the failures. The migration round-trip contributed only by running the canonical `pytest -q` post-restore verification — it was the vehicle by which pre-existing calendar debt became visible, not the cause.

The commit message's framing ("NOT caused by the migration patch or the round-trip itself") is accurate.

---

### B6 — Round-trip rigor

The D1 results section documents a complete round-trip:
- 22/23 migrations reversed cleanly in round 2 (after the fix)
- The 23rd (`20260513140000`) now fails with an actionable error when offending rows present; succeeds after operator-side prerequisite (delete offending rows)
- Re-upgrade from base to head succeeded

Running `alembic downgrade base` exercises every migration's `downgrade()` in sequence from head. No conditional `if-table-exists` skips were found in the migration chain during the prior Backend B4 review, and the round-trip's success confirms all 22 reversible migrations ran.

The caveat ("production `widen_cusip_ticker_map_source` downgrade could surface the same issue") is correctly scoped. No other asymmetrically-reversible migrations exist in the chain. The two widening migrations (`20260423120000` source VARCHAR, `20260513140000` ticker VARCHAR) are both addressed — the latter with a pre-check, the former confirmed safe on dev and noted as the prod-shape unknown. The caveat scope is complete.

---

### Should-block items

None. No merge-blockers.

---

### Future backlog

- **Relativize `official_filing_deadline` in `test_13f_mvp4_unknown_manager_priority.py` and `test_13f_mvp5_02_amendment_exclusion.py`** (B2) — currently benign (no deadline-conditional assertions), but the same pattern as the three failures just fixed. Sweep to `date.today() + timedelta(days=10)`.
- **Cross-reference comment in `_freeze_today` docstring** (B3) — note the two patching strategies (`_freeze_today` vs advance-the-deadline) so future maintainers know which to follow in new test files.
- **"Update frozen date if adding newer-quarter fixtures" note in `_freeze_today`** (B4) — prevents future confusion when 2026-Q1 or later fixture data is added.
- **Alembic `op.get_bind()` deprecation note** (B1) — comment in the migration that this may need updating if Alembic is bumped past 2.0.

---

## 2. Production Readiness Review

**APPROVE WITH NOTES**

---

### P1 — Auto-deploy coupling framing accuracy

`deploy.yml` verified end-to-end. The framing fix in `559fbe0` is accurate.

The `if:` condition (lines 21-24) is the only gate:
```yaml
if: >
  github.event_name == 'workflow_dispatch' ||
  (github.event.workflow_run.conclusion == 'success' &&
   github.event.workflow_run.head_branch == 'main')
```

There is **no `environment:` key** in the deploy job. GitHub Environments can add required-reviewer gates and deployment branch policies — their absence confirms there is no manual approval gate between CI success on `main` and production deploy. The job runs on `self-hosted` / `valuepilot-prod`, which is the production machine.

`concurrency: group: deploy-prod-main, cancel-in-progress: true` means a second CI success event (e.g., two merges in quick succession) will cancel the in-progress deploy and restart. Operationally correct but worth knowing: during N4 gate work, if two branches merge to `main` close together, the first deploy could be cancelled. Low risk for a single active branch; worth noting if the team grows.

The N4 ticket's three options are the right operational levers. A **fourth option** not mentioned: add a GitHub Environment with `required_reviewers`. This adds a one-click human approval gate before every future deploy, permanently decoupling merge from deploy at the workflow level. Recommended as a long-term architectural improvement; independent of PR #33. Not urgent for a solo/small-team repo but valuable as the team grows.

---

### P2 — D1 dev-side evidence sufficiency

"Substantially cleared on dev" is the correct characterization.

**Is dev-round-trip + actionable error sufficient for D1 dev-cleared?** Yes:
1. The forward chain is confirmed production-ready (clean in CI's fresh DB and dev DB).
2. 22/23 reverse migrations are clean on dev-shape data.
3. The 23rd is honest about being structurally one-way when offending data exists.
4. The remaining production unknown (`source` VARCHAR narrowing) is low-risk: the only valid source values are `"openfigi"` (8 chars), `"sec_co_tickers"` (16 chars), and `"manual"` (6 chars), all well under VARCHAR(20) per AGENTS.md. Unless production has received a non-standard source value outside those three, the prod round-trip for this migration will pass.

**Are there other asymmetrically-reversible migrations not named in the caveat?** No. Only two widening migrations in the chain; both are addressed. No data-backfill migrations (those live in separate scripts); no FK-cascade-dependent rollbacks that dev wouldn't exercise.

**Bar for "D1 fully cleared"**: the sign-off trail shows D1 checked with an inline caveat ("Pre-prod-deploy still needs..."). This framing correctly distinguishes dev-cleared from fully-closed. No adjustment needed.

---

### P3 — D1 fix's production implications

The "rollback requires manual prep" tradeoff is documented in the migration file's `downgrade()` comment. The comment names the prerequisite (delete or archive offending rows) and the command to re-run afterward.

**Critical gap for D3 runbook**: if production needs a code rollback (e.g., Phase 3 regression), operators should revert the **application code** (git revert), NOT run `alembic downgrade`. The ticker column stays wide; only the application code reverts. This distinction is not currently in either the migration comment or the D3 deliverable list.

Without this in D3, an operator under pressure may attempt `alembic downgrade` as the rollback path, hit the pre-check error (or the source narrowing failure), and lose time. The D3 deliverable list should explicitly add: "Clarify: application code rollback (git revert) is the deploy-rollback path; `alembic downgrade` is NOT the rollback mechanism for this deployment, and attempting it would require manual operator data prep."

---

### P4 — Time-bound test fixes operational implications

The frozen date `2026-05-14` is durable for the current 2025-Q4-only fixture set. The analysis is correct: `_latest_closed_quarter` finds the max quarter whose deadline ≤ today. 2025-Q4's deadline (2026-02-14) is always ≤ the frozen date (2026-05-14), so 2025-Q4 is returned deterministically regardless of future calendar advance. `_clear_13f()` isolates each test from ambient data.

No production-shaped data scenario affects this: fixture isolation is complete.

---

### P5 — Net pre-deploy readiness shift

The risk reduction is **material**. Before this commit: attempted emergency rollback via `alembic downgrade` would fail with an unexplained `StringDataRightTruncation`. After: the same attempt fails with a message naming the exact problem, the count of offending rows, and the resolution path. That's a genuine operational safety improvement under pressure.

**Readiness picture**:

| Gate | Before | After |
|---|---|---|
| D1 | Untested; latent truncation failure | Dev-cleared; prod round-trip pending |
| D2 | Pending | Pending — highest remaining risk |
| D3 | Pending | Pending — needs migration rollback path added to scope |
| D4 | Pending | Pending |
| D5 | Pending | Pending |

**Recommended next step**: D2 (Phase 1 comparison against production data). The Phase 3 scoring default flip affects all production users immediately on merge+deploy. If D2 surfaces `top10_swap_count > 0` against production data, deploy must be held and the flip investigated. D2 should not wait for D3/D4/D5.

The N4 ticket's D1 → D2 → D5 → D4 → D3 order remains correct. D5 (VL coverage number) before D4 (release note needs that number); D3 last (can draft in parallel with D5).

---

### Should-block items

None.

---

### Future backlog

- **GitHub Environment with `required_reviewers`** (P1) — permanent architectural improvement to decouple merge from deploy without manual `deploy.yml` edits. Separate infra ticket after PR #33 ships.
- **Add migration rollback clarification to D3 scope** (P3) — "application code revert is the path; `alembic downgrade` is NOT" should appear in the D3 deliverable list before D3 is written.

---

## 3. Documentation / Workflow Review

**APPROVE WITH NOTES**

---

### D1 — Cross-reference integrity

The three documents are internally consistent:

- **N4 ticket**: "merge to main IS production deploy" → option 1 recommended; all three options listed with tradeoffs.
- **Open-work snapshot** (Next Action): "merge to main IS production deploy" → option 1 as step 3; option 2 as alternative.
- **Review response addendum** (Update 2026-05-18): "merge to main IS production deploy" → option 1 recommended; option 2 mentioned.

Asymmetric option coverage (N4 lists all three; snapshot and review response mention only options 1 and 2) is **intentional and correct**. The N4 ticket is the operational spec where completeness matters. Option 3 (staging branch) is explicitly "not recommended" in the N4 ticket and is reasonably omitted from summary-level documents.

**Old framing check**: the review response addendum references the old framing ("blocks deploy, not merge") as the thing being corrected — not as current guidance. No document uses the old framing as active guidance. No drift.

---

### D2 — N4 D1 results section accuracy

The post-mortem tone is appropriate. Deploy-gate audit trails warrant more detail than standard MVP closing-gate sign-offs because future operators need to understand what was found, why it matters, and the recovery path. The detail is proportionate to the stakes.

**Verifiability of key numbers**:
- `110 offending rows` — reproducible by running the SELECT from the migration pre-check against any similarly-populated DB.
- `1686 / 4022 row counts` — reproducible via `SELECT COUNT(*)`.
- `823 passed` — matches the review response verification section (`548a11b`) and the prior comprehensive review.
- `Round 2 succeeded end-to-end` — auditable from the commit (migration file change + green test run).

Evidence trail is sufficient for an external reproducer.

**Sign-off caveat clarity**: the D1 checkbox includes an inline "Pre-prod-deploy still needs..." caveat. This prevents the `[x]` from being read as fully closed. It works, but a nested `[ ]` sub-item (e.g., `[ ] D1 (prod): run same round-trip against production data dump`) would make the "partially done" state visible at a glance when scanning the sign-off trail. Minor visual improvement; not substantive.

---

### D3 — Time-bound test fixes framing accuracy

The framing ("pre-existing time-bound test debt surfaced by calendar passage — NOT caused by the migration patch or the round-trip") is **accurate for the three tests that manifested as failures**. The `date(2026, 5, 15)` values were written during original MVP development when 2026-05-15 was a correct future deadline; calendar advance to 2026-05-18 expired them.

**Incomplete sweep**: Backend B2 identifies that `test_13f_mvp4_unknown_manager_priority.py:103` and `test_13f_mvp5_02_amendment_exclusion.py:95` still carry `date(2026, 5, 15)`. Those tests did not fail (no deadline-conditional assertions), so the commit message's "all three failures fixed" is accurate. But the N4 D1 results section does not note this incomplete sweep, which could give a reader the impression that all time-sensitive fixture dates were addressed. A brief clarifying sentence would close that gap.

**Placement**: mixing "migration round-trip outcome" with "test fixture tech debt sweep" in the same results section slightly muddies the audit trail. A reader interested in the migration chain's state shouldn't need to parse test fixture commentary. This is a formatting nit — the content is correct, just co-located in a way that makes each part slightly harder to find.

---

### D4 — Snapshot Next Action coherence

The "Alternative if N4 cannot land soon" paragraph correctly frames option 2 (disable `workflow_run` trigger) as a workflow-config change requiring discussion. "Discuss before applying" is explicit. This is the right calibration.

**Decision owner not stated**: the decision between options 1 and 2 has PO implications (option 2 means users don't see the change until manual deploy is triggered). Suggesting adding "Decision owner: PO + Tech Lead" to the alternative paragraph.

**Item 2 should be updated to reflect D1 progress**: as written, "Clear PR #33 pre-deploy gates (N4) — migration round-trip, Phase 1 comparison against prod data, operator runbook, release note, VL coverage audit" reads as if all five are pending. A reader scanning the snapshot today cannot tell D1 is substantially done without cross-referencing the N4 ticket. Suggested update:
> "Clear remaining PR #33 pre-deploy gates (N4) — D2 (Phase 1 comparison vs prod), D5 (VL coverage audit), D4 (release note), D3 (operator runbook). D1 substantially cleared 2026-05-18; see N4 sign-off trail."

---

### Should-block items

None.

---

### Future backlog

- **Nested `[ ]` sub-item for prod round-trip in D1 sign-off** (D2) — make the "partially done" state visible at a glance.
- **Incomplete sweep note** (D3) — add a sentence noting the two remaining `date(2026, 5, 15)` fixtures in mvp4 and mvp5 tests that were not swept (benign but inconsistent).
- **Update snapshot item 2** (D4) — reflect D1 substantially cleared so readers don't need to cross-reference the N4 ticket.
- **Decision-owner note in snapshot "Alternative" paragraph** (D4) — "PO + Tech Lead" for option 1 vs option 2.
- **Migration rollback path in D3 scope** (from Production P3) — add "application code revert is the path; `alembic downgrade` is NOT" to the D3 deliverable list before writing the runbook.

---

## Net Across All Three Reviews

Both commits are safe to merge. They introduce no production code changes and no new risk. The framing fix is accurate and verified against `deploy.yml`. The migration pre-check is correct and eliminates a class of confusing operator failure. The time-bound test fixes are correctly scoped to the three failures that manifested, with a known gap in two sibling test files that didn't fail.

**D1 gate assessment**: substantially cleared for dev. The prod round-trip to confirm `cusip_ticker_map.source` safety remains pending and is low-risk given the constrained source vocabulary. Proceed to D2 as the highest-impact remaining gate.
