# Review prompt — Manager `manager_type` first-pass classification

Paste the section below into a fresh reviewer session (human or agent). It is
self-contained. Pair it with the task log
`docs/tasks/2026-05-21_manager-type-classification.md` and the diff on branch.

---

## Reviewer brief

You are reviewing **PR #88**, branch `claude/manager-type-classification`. It
applies a first-pass `manager_type` classification to **all 86 institution
managers in the production database**.

This is unusual: **the prod write has already happened** (a user-authorized
operational step). You cannot block it — but you *can* (a) catch
misclassifications the team should correct, (b) review the tooling and
methodology before they become the established pattern, and (c) confirm the
write was done safely and is honestly recorded. Corrections happen through the
admin manager-type editor, which supersedes a machine row with a human one.

### What changed and why

- Before: all 86 `institution_managers` rows had `manager_type = 'unknown'`,
  which feeds Oracle's Lens signal weighting.
- After: every manager has a type. Method — extract prod 13F portfolio
  behaviour → web-research the identity-driven types → decide → apply via the
  audited `update_manager_type` service. `reviewed_by_user_id` is NULL (machine
  pass); every note is flagged as a first pass pending human review.
- The PR adds 3 reusable scripts under `backend/scripts/`, the decision-record
  JSON, the task doc, and BACKLOG updates. The scripts are standalone — not
  imported by the app or tests.

### Files in scope

- `backend/scripts/classify_managers_extract.py` — read-only prod dump.
- `backend/scripts/classify_managers_decide.py` — the classification logic.
- `backend/scripts/classify_managers_apply.py` — the audited writer.
- `docs/tasks/2026-05-21_manager-type-classifications.json` — the 86 decisions.
- `docs/tasks/2026-05-21_manager-type-classification.md`, `docs/BACKLOG.md`.

### Baseline

`git diff main...HEAD`. The prod DB is local — `valuepilot-prod-api-1`.

## Answer every question below with a verdict (PASS / FAIL / advisory) + evidence

### A. Write path & safety — MANDATORY

1. **Audited service, no raw SQL.** Every write went through
   `app.services.manager_type_review.update_manager_type`, which writes the
   `manager_type` column **and** an `institution_manager_type_review_events`
   row in one transaction. Confirm `classify_managers_apply.py` uses only that
   service — no raw SQL, no direct column mutation (AGENTS.md invariant #4).
2. **Honest audit trail.** All 86 audit rows have `reviewed_by_user_id = NULL`.
   Confirm this is correct — these are machine classifications, not human
   reviews — and that attributing them to a real user would have falsified the
   trail. Confirm every note is prefixed
   `[auto-classified by Claude, first pass — pending human review]` and every
   `evidence_json` carries `classified_by: claude_first_pass`.
3. **Idempotency.** `update_manager_type` no-ops when the new value equals the
   old, writing no audit row. Confirm a re-run of `classify_managers_apply.py`
   is therefore safe (no duplicate audit rows) and that the script defaults to
   dry-run, requiring `--apply` to write.
4. **Extract is read-only.** Confirm `classify_managers_extract.py` issues no
   writes/commits.

### B. Methodology — MANDATORY

5. **The "both 1.00" claim.** The classification effort rests on: `value_concentrated`
   and `long_term_fundamental` carry an **identical 1.00** Oracle's Lens signal
   weight, so the split between them has *no scoring impact*. Verify this against
   `backend/app/services/oracles_lens/constants.py` (`MANAGER_SIGNAL_WEIGHTS`).
   If the two weights differ, the whole "low-stakes" framing — and the use of a
   mechanical rule for 48 managers — is wrong.
6. **The mechanical rule.** 48 long-only value managers were split by: top-10
   weight ≥ 0.50 **and** holdings ≤ 25 → `value_concentrated`, else
   `long_term_fundamental`. Confirm this mirrors the system's own
   `manager_signal.py::derive_manager_signal_profile` `value_concentrated`
   condition, so the machine pass is consistent with the behaviour classifier.
7. **The 10 scoring-relevant calls.** Only the off-1.00 types move scores:
   6 `activist` (Pershing Square, Icahn, Third Point, Engaged, Trian, ValueAct),
   `quant` (Bridgewater), `multi_strategy` (Appaloosa, Oaktree), `high_turnover`
   (Scion). Review each — is any wrong? In particular assess **TCI** (classified
   `value_concentrated`, not `activist`, as a judgement call — activist heritage
   but a currently stable concentrated book) and the four **Tiger Cub** long/short
   funds (`long_term_fundamental`).

### C. Classification spot-check

8. Sample `docs/tasks/2026-05-21_manager-type-classifications.json` — flag any
   obvious misclassification. Are the 27 managers with no ingested 13F holdings
   (classified on documented strategy) reasonable?
9. **Data-quality handling.** Makaira (id 69) — prod extract returned only 1
   holding (incomplete); confirm it was hand-classified rather than run through
   the mechanical rule on bad data. Vulcan Value (id 76) — turnover proxy 0.97
   looks like a CUSIP-remap artifact; confirm it did not distort the result (the
   rule uses concentration + holding count, not the turnover proxy).

### D. Scripts — code quality

10. Review `classify_managers_extract.py`'s behaviour metrics — top-10
    concentration, the new-position turnover proxy, the trailing holding-period
    span. Any bug (value fallback, quarter ordering, division)?
11. Confirm the 3 scripts are standalone — `pytest` does not collect them (name
    does not match `test_*`) and they are not imported by the app, so CI is
    unaffected. `pytest -q` was green (902).

### E. Scope / deferred

12. Confirm the original medium BACKLOG item ("manager_type all unknown") is
    removed and replaced by two **low** entries — the human-review follow-up and
    the duplicate-manager finding (4 firms under 2 CIKs each: Abrams, Akre,
    Himalaya, Baupost). Confirm both rows of each duplicate pair were classified
    identically.

## Verification

The prod stack runs locally. Re-check the write:

```
docker exec -i valuepilot-prod-api-1 python - <<'PY'
from collections import Counter
from app.core.db import SessionLocal
from app.models.institutions import InstitutionManager, InstitutionManagerTypeReviewEvent
s = SessionLocal()
print(dict(Counter(m.manager_type for m in s.query(InstitutionManager))))
evs = s.query(InstitutionManagerTypeReviewEvent).all()
print("audit rows:", len(evs), "| reviewer NULL:", sum(e.reviewed_by_user_id is None for e in evs))
s.close()
PY
```

Reproduce the decisions (the decide step is pure — needs only the extract JSON):

```
docker exec -i valuepilot-prod-api-1 python - < backend/scripts/classify_managers_extract.py > /tmp/x.json
python3 backend/scripts/classify_managers_decide.py /tmp/x.json | diff - docs/tasks/2026-05-21_manager-type-classifications.json
```

`pytest -q` for CI sanity.

## Pass bar

Approve only if: **A1–A4** confirm the write was audited, honest, idempotent,
and used no raw SQL; **B5** confirms the 1.00/1.00 weight equality (the
methodology's foundation); **B6–B7** find the mechanical rule sound and no
off-1.00 call clearly wrong; **C/D/E** findings are recorded. The bar is: "the
prod write was done safely and is honestly recorded as a reviewable first pass,
the methodology is defensible, and any misclassification a reviewer spots is
captured for the team to correct via the editor."
