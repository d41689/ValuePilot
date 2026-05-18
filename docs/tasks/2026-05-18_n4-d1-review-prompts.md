# N4 D1 + Framing Fix — Review Prompts

Three reviewer prompts for the small post-PR-#33-review work that landed since the last comprehensive review (commits `559fbe0` and `397893b`). Each prompt is self-contained — drop into a fresh chat or hand to an external agent without prior context.

**Branch**: `docs/13f-automation-prd`
**Commits under review**:
- `559fbe0` — Resolve N4 vs snapshot framing inconsistency. Docs-only. Captures that `.github/workflows/deploy.yml` auto-fires on `main` CI success, so for THIS repo "merge to main IS production deploy" and N4 effectively gates merge, not just deploy. N4 ticket updated; snapshot Next Action explained the coupling.
- `397893b` — N4 D1: migration round-trip executed against populated dev DB. Surfaced a structural one-way downgrade in `cusip_ticker_map.ticker` widening + 3 pre-existing time-bound test failures (calendar advance to 2026-05-18). All four fixed; N4 ticket D1 results documented.

**Scale**: 6 files changed, ~178 line additions, no production code paths touched outside the migration's `downgrade()`.

**Why a focused 3-reviewer review (not 4 or 6)**: this is a small post-PR-review hotfix; the comprehensive 6-reviewer pass already happened on `548a11b`. This review only needs to catch failure modes specific to N4 D1's narrow scope:

1. **Backend Reviewer** — migration downgrade fix correctness + test fixture engineering quality.
2. **Production Readiness Reviewer** — does this actually clear D1 to the bar the gate claims? Auto-deploy framing call.
3. **Documentation / Workflow Reviewer** — N4 ticket accuracy, framing-fix coherence, cross-reference integrity.

Verdict format across all three (matches prior reviews):
```
APPROVE / APPROVE WITH NOTES / REJECT
<role>-specific findings ...
Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 1. Backend Reviewer Prompt

You are the Backend Engineer reviewing two small commits on branch `docs/13f-automation-prd`: `559fbe0` (docs-only framing fix) and `397893b` (migration downgrade fix + 3 time-bound test fixes). The comprehensive PR #33 review already passed; this review covers ONLY the post-review hotfix work.

**Read these in order:**

1. `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` — find the `### D1 results (2026-05-18, dev DB)` section appended to D1. This is the narrative of what happened.
2. `backend/alembic/versions/20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker.py` — the patched `downgrade()` with pre-check + actionable `RuntimeError`.
3. `backend/tests/unit/test_13f_user_api.py` — find the `_filing` helper's `official_filing_deadline` line (around line 96). Changed from `date(2026, 5, 15)` to `date.today() + timedelta(days=10)`.
4. `backend/tests/unit/test_13f_admin_dashboard.py` — find the new `_freeze_today(monkeypatch)` helper near the top and three test sites that call it: `test_amendment_pending_creates_p1_task_and_needs_review_health`, `test_persisted_quality_report_surfaces_in_quarter_and_tasks`, `test_readiness_thresholds_are_configurable`.

**Six questions:**

### B1 — Migration downgrade pre-check correctness

```python
def downgrade() -> None:
    bind = op.get_bind()
    offending = (
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM cusip_ticker_map "
                "WHERE length(ticker) > 10"
            )
        ).scalar()
        or 0
    )
    if offending > 0:
        raise RuntimeError(...)
    op.alter_column(...)
```

- Is `bind.execute(sa.text(...)).scalar()` the correct API for an inline COUNT in an Alembic `downgrade()`? Some Alembic versions deprecate direct `bind.execute` on text — should this be `op.get_bind().execute(sa.text(...))` or wrapped in `with op.get_context().bind.begin() as conn`?
- The `RuntimeError` propagates and aborts the alembic command. Does that leave the migration in a clean state (no partial DDL applied), or could it half-apply? (The migration is single-statement so should be transactional, but worth confirming.)
- Edge case: empty `cusip_ticker_map` table → `scalar()` returns 0 → `offending = 0` → proceed with narrow. Correct.
- Edge case: `cusip_ticker_map` table doesn't exist (deeper rollback below this migration) → `SELECT COUNT(*)` raises. The pre-check assumes the table exists, which is true at this revision point but worth flagging if the migration ever has to handle absent state.

### B2 — Test fixture relativization (`test_13f_user_api.py`)

```python
official_filing_deadline=date.today() + timedelta(days=10),
```

- Is this evaluated at fixture-import time or at test-execution time? `_filing` is a function — `date.today()` evaluates each call. Confirm.
- `+ timedelta(days=10)` chosen arbitrarily. Will any timezone / clock-skew scenario produce a deadline ≤ today within 10 days? (E.g., test runs at 23:59 local, `date.today()` returns today; 10 days hence is comfortably future. Safe.)
- Are there OTHER fixtures in this file (or sibling test files) using the same hardcoded `date(2026, 5, 15)` pattern that I missed? Specifically grep for `date(2026,` across `backend/tests/`.

### B3 — `_FrozenDate` monkeypatch pattern (`test_13f_admin_dashboard.py`)

```python
class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return cls(frozen.year, frozen.month, frozen.day)

monkeypatch.setattr("app.services.thirteenf_admin_dashboard.date", _FrozenDate)
monkeypatch.setattr("app.services.thirteenf_readiness.date", _FrozenDate)
```

- `_FrozenDate` subclasses `date`. Python's `datetime.date` is immutable but allows subclassing. Does subclassing introduce any surprises for downstream code that does `isinstance(x, date)` (returns True for `_FrozenDate` instances) or `type(x) is date` (returns False for `_FrozenDate` instances)? Audit consumers if relevant.
- `_FrozenDate.today()` returns `cls(year, month, day)`. This creates a `_FrozenDate` instance, not a plain `date`. Arithmetic like `_FrozenDate.today() + timedelta(days=N)` returns a `date` (the result of `__add__` does NOT preserve the subclass), but `_FrozenDate.today() - other_date` returns a `timedelta`. Are any consumers comparing the result's `type()` rather than using `isinstance`? Likely safe but worth a check.
- Two `monkeypatch.setattr` calls — one for `thirteenf_admin_dashboard.date`, one for `thirteenf_readiness.date`. Did I miss any other module that imports `from datetime import date` and calls `date.today()` in the call chain from the readiness/tasks endpoints? Grep for `from datetime import date` across `backend/app/services/` and check.

### B4 — Freeze date choice (`date(2026, 5, 14)`)

- The frozen date `2026-05-14` is BEFORE 2026-Q1's filing deadline (2026-05-15), so the readiness service computes "latest usable quarter = 2025-Q4" deterministically.
- Future risk: when 2026-Q2 lands (deadline 2026-08-14), THIS frozen date `2026-05-14` is BEFORE 2026-Q2's deadline too. So latest_usable stays 2025-Q4 forever? Or does the service compute it as max of "all quarters whose deadline ≤ today"? Confirm the service logic — `_latest_closed_quarter` returns the FIRST quarter (in the sorted list) whose max deadline ≤ today. As long as 2025-Q4's deadline (2026-02-14) ≤ frozen_today (2026-05-14), 2025-Q4 is returned. ✓
- Is the frozen date documented in the `_freeze_today` helper docstring? Yes — references the 2026-Q1 deadline relationship.

### B5 — Are the 3 time-bound tests genuinely pre-existing debt vs caused by the round-trip?

The N4 D1 commit message states these failures are pre-existing and "surfaced by calendar passage to 2026-05-18, NOT caused by the migration patch or the round-trip." Verify this claim:

- Run `git log --oneline -p tests/unit/test_13f_user_api.py | grep "date(2026, 5, 15)"` to confirm when the absolute date was introduced.
- Same for the admin dashboard fixtures.
- Is the framing in the commit message ("unrelated to migration changes") accurate, or did the round-trip somehow contribute (e.g., by clearing a fixture that was masking the issue)?

### B6 — Round-trip rigor

The D1 results section claims:
- Forward chain (upgrade base → head): fully tested. ✓
- Reverse chain (downgrade head → base): tested after fix; succeeded end-to-end.
- Re-upgrade (base → head): tested; succeeded.

- Was each migration's `downgrade()` actually exercised, or did some get skipped (e.g., conditional `if-table-exists`)?
- The N4 ticket caveat says "production round-trip still needed to verify `cusip_ticker_map.source` downgrade doesn't surface the same issue." Is the caveat correctly scoped, or are there OTHER asymmetrically-reversible migrations I'd flag for production-shape verification?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

B1: ...
B2: ...
B3: ...
B4: ...
B5: ...
B6: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 2. Production Readiness Reviewer Prompt

You are the Production Readiness Reviewer evaluating whether the N4 D1 work clears D1 to the bar the gate actually needs. Branch `docs/13f-automation-prd`, commits `559fbe0` and `397893b`.

**Read these in order:**

1. `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` — entire file (the N4 ticket).
2. `.github/workflows/deploy.yml` — verify the auto-deploy coupling described in the framing fix.
3. `.github/workflows/ci.yml` — confirm CI's branch triggers.
4. `docs/tasks/2026-05-14_open-work-snapshot.md` — find the Next Action section.

**Five questions:**

### P1 — Auto-deploy coupling framing accuracy

The framing fix (`559fbe0`) claims `deploy.yml` triggers production deploy on every successful CI run on `main`:

```yaml
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
if: github.event.workflow_run.conclusion == 'success' && head_branch == 'main'
```

- Read `.github/workflows/deploy.yml` end-to-end. Are there ANY additional guards (manual approval, environment protection rules, branch protection rules requiring a separate review) that would mean `main` merge does NOT auto-deploy? Check the `environment:` key and any conditional skips.
- The `concurrency` group is `deploy-prod-main` — does this mean only one deploy runs at a time but doesn't gate the trigger? Confirm.
- The N4 ticket's three options for handling the coupling: (1) clear N4 first, (2) temporarily disable `workflow_run` trigger, (3) staging branch. Are these the right operational levers, or is there a fourth (e.g., GitHub Environment requiring manual approval)?

### P2 — D1 dev-side evidence sufficiency

The N4 D1 results section claims "D1 substantially cleared on dev" based on:
- Full round-trip executed against populated dev DB (1686 + 4022 rows).
- Migration downgrade pre-check fix verified (110 offending rows → actionable error).
- Sister `widen_cusip_ticker_map_source` downgrade safe-on-dev (zero source rows > 20 chars).

D1's gate language is "zero failures across the round-trip." The dev round-trip now passes (with the fix); production-shape data is the remaining unknown.

- Is "dev round-trip green + actionable error for the structurally-irreversible migration" sufficient evidence for D1 to be considered cleared FOR DEV, with a known caveat for prod?
- The caveat names `cusip_ticker_map.source` narrowing as the remaining production-shape risk. Is that the only one, or are there other migrations whose downgrade would surface different failures against prod data shape? (E.g., are there foreign-key cascades or trigger-dependent rollbacks that dev doesn't exercise?)
- What's the bar for "D1 fully cleared" vs "D1 cleared for dev with caveat"? Per the N4 ticket's gate language, does the caveat block the gate from closing entirely, or is it a known-risk note for the deploy step?

### P3 — D1 fix's production implications

The patched `downgrade()` raises `RuntimeError` on any populated DB with bond / preferred identifiers > 10 chars. In production this means:

- A future rollback attempt of this specific schema change requires operator intervention (decide what to do with the offending rows: delete, archive, coerce) BEFORE running the downgrade.
- Is this "rollback requires manual prep" tradeoff documented anywhere operators would find it? (The migration docstring covers it; the operator runbook in D3 should mirror it.)
- If the production deploy of PR #33 needs to be rolled back, the rollback path is `git revert` of the application code, NOT `alembic downgrade` (which would now fail with the actionable error). Confirm this is the intended pattern.

### P4 — Time-bound test fixes operational implications

Three tests were fixed to use frozen / relative dates so calendar advance doesn't break them.

- The `_freeze_today` helper pins to `date(2026, 5, 14)`. This is ALSO a hardcoded date. It works today (Q4 still latest usable) but: when will it next break? Compute: 2025-Q4's deadline was 2026-02-14. The frozen-today value would have to fall BEFORE that for 2025-Q4 to NOT be the latest usable. Since 2026-05-14 > 2026-02-14, latest_usable will always be 2025-Q4 regardless of frozen_today moving forward in time as long as we don't seed newer-quarter fixtures. So the frozen date is durable.
- Is there any production-shaped data scenario (e.g., a real customer's dev DB seeded with fixtures from a later quarter) where the frozen date would mismatch the test's seeded period? The tests `_clear_13f` and reseed, so this is internal-fixture-only.

### P5 — Net pre-deploy readiness shift

After this commit pair (`559fbe0` + `397893b`):

- D1: substantially cleared (dev evidence + structural downgrade caveat noted; prod round-trip remains).
- D2-D5: unchanged, still pending.

- Does the team's deploy-readiness picture get materially better or just clearer? (Both are valuable; this question is about how much actual risk reduction happened.)
- Is the right next step D2 (production Phase 1 comparison), D3 (runbook), D5 (VL coverage audit), or something else? The N4 ticket suggests D1 → D2 → D5 → D4 → D3 order; is that still right after this commit's findings?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

P1: ...
P2: ...
P3: ...
P4: ...
P5: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 3. Documentation / Workflow Reviewer Prompt

You are the Documentation / Workflow Reviewer verifying that the N4 ticket update + framing fix are internally consistent and don't introduce new doc drift. Branch `docs/13f-automation-prd`, commits `559fbe0` and `397893b`.

**Read these in order:**

1. `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` — entire file. Note both the "Repo-specific note: merge ≡ deploy" section (from `559fbe0`) and the "D1 results (2026-05-18, dev DB)" section (from `397893b`).
2. `docs/tasks/2026-05-14_open-work-snapshot.md` — find Next Action section.
3. `docs/tasks/2026-05-14_pr33-review-response.md` — find the "Update 2026-05-18" addendum at the bottom.
4. `docs/tasks/2026-05-14_pr33-comprehensive-review-report.md` — the original Action Register that this commit pair responds to.

**Four questions:**

### D1 — Cross-reference integrity

Three documents now reference the auto-deploy coupling (N4 ticket / snapshot / review response). Read them in sequence:

- Are they consistent in their framing? (All three say "merge ≡ deploy" for this repo; all three recommend option 1 — clear N4 first.)
- The N4 ticket lists THREE options (clear first / disable workflow_run / staging branch). The snapshot mentions only the first and the disable-workflow_run alternative. The review-response addendum mentions both. Is the asymmetric option coverage intentional or accidental?
- Does any other doc still reference the old framing ("blocks deploy, not merge") that would now be contradictory? Grep `docs/tasks/` for `not merge` and `deploy gate, not` to be sure.

### D2 — N4 D1 results section accuracy

The D1 results section narrates: "Round 1 ... FAILED at ... transactional DDL rolled back; DB state intact." → "Fix applied: ... pre-check + actionable RuntimeError" → "Round 2 ... succeeded end-to-end." → "Dev DB restored from pg_dump backup ... 1686 + 4022 row counts restored."

- Is the narrative tone calibrated? It reads like a post-mortem, which is appropriate for a deploy-gate audit trail. Compare with how MVP closing-gate task files narrate verification results.
- Are the numbers (110 offending rows, 1686 cusip rows, 4022 holdings, 823 passed, 67.65s) verifiable from the commit's evidence trail? An external reviewer should be able to reproduce.
- The sign-off trail's D1 entry now reads `[x] D1 migration round-trip executed 2026-05-18 against populated dev DB. Surfaced a structural one-way constraint ... pytest 823 passed post-restore. Pre-prod-deploy still needs: run the same round-trip against a production data dump or fresh staging clone ...`. Is the caveat at the end clear enough that the gate isn't accidentally read as "fully closed"?

### D3 — Time-bound test fixes — framing accuracy

The commit message states the 3 test failures are "pre-existing time-bound test debt that calendar passage surfaced — NOT caused by the migration patch or the round-trip itself. The N4 D1 round-trip is what made them visible at the right time to fix before merge."

- Is this framing honest? Verify by checking the test fixture dates in `git blame`: were `date(2026, 5, 15)` and the 2025-Q4 fixture seeds present BEFORE this PR's first commit, or did they enter during the PR's development?
- If they entered DURING the PR, the framing is technically incorrect (the PR introduced the debt that calendar passage then exposed). If they were pre-existing on `main`, the framing is accurate.
- Is the right place to document the fix the N4 D1 results section (current placement), or a separate "tech debt swept" note? The N4 ticket conflates "migration round-trip outcome" with "test fixture relativization" — clear or muddled?

### D4 — Snapshot Next Action coherence

The snapshot's Next Action section now reads:

```
PR #33 is open and code-review-clean. Note: deploy.yml auto-deploys
on every successful CI run on main, so merge to main IS production
deploy in this repo. N4 therefore gates merge, not just deploy.
Order:
1. Address PR #33 review findings (DONE).
2. Clear PR #33 pre-deploy gates (N4) — ...
3. Merge PR #33 to main once N4 gates clear ...
[plus alternative: disable workflow_run trigger]
```

- Does the "Alternative if N4 cannot land soon" paragraph correctly position option 2 (disable workflow_run) as a workflow-config change requiring discussion, not a routine choice?
- Is there ambiguity about WHO decides between options 1 and 2? (Probably PO / Tech Lead, but the snapshot doesn't say.)
- The Next Action lists items 1-7 (post-review fixes through N5). After this commit (which clears D1 substantially), should item 2 be updated to say "Clear D2-D5 ..." instead of "Clear N4 gates ..."?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

D1: ...
D2: ...
D3: ...
D4: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```
