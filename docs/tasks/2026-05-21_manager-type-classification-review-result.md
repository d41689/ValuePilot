# Review result — Manager `manager_type` first-pass classification

Date: 2026-05-21
Branch reviewed: `claude/manager-type-classification`
Baseline: `git diff main...HEAD`
Prompt: `docs/tasks/2026-05-21_manager-type-classification-review-prompts.md`

## Overall Verdict

PASS with one tooling advisory. The already-performed prod write appears to
have gone through the audited `update_manager_type` service, is honestly marked
as a machine first pass, and is reviewable/correctable through the existing
admin editor. The methodology's key low-stakes claim holds:
`long_term_fundamental` and `value_concentrated` both carry a 1.00 Oracle's
Lens weight, so the mechanical split between those two does not move scores.

Advisory: `classify_managers_extract.py` computes `_val()` as
`value_usd or value_thousands or 0`. If a future extract ever contains a mix of
rows with `value_usd` populated and rows falling back to `value_thousands` in
the same filing, concentration weights would be distorted by 1000x for fallback
rows. This likely did not affect the committed run because 13F rows normally
carry consistent values and the output was reviewed, but before reusing the
script as a pattern, make the unit explicit.

Evidence: `backend/scripts/classify_managers_extract.py:24-25`.

## Prompt Checklist

### A. Write Path & Safety

1. PASS. `classify_managers_apply.py` uses only
   `update_manager_type()` for writes; I found no raw SQL and no direct
   `InstitutionManager.manager_type` mutation in the script. Evidence:
   `backend/scripts/classify_managers_apply.py:24-29`,
   `backend/scripts/classify_managers_apply.py:65-76`,
   `backend/app/services/manager_type_review.py:75-86`.
2. PASS. The apply script passes `reviewer_user_id=None`, which is correct for a
   machine first pass; attributing these rows to a real user would falsify the
   audit trail. All 86 JSON decisions have the required note prefix and
   `evidence_json.classified_by = "claude_first_pass"`. Evidence:
   `backend/scripts/classify_managers_apply.py:69-76`,
   `backend/scripts/classify_managers_decide.py:125-140`,
   `docs/tasks/2026-05-21_manager-type-classification.md:68-75`.
3. PASS. `update_manager_type()` no-ops when the requested type equals the
   current type and returns no audit event id, so re-running the apply script
   will not duplicate audit rows. The script defaults to dry-run and requires
   `--apply` to write. Evidence:
   `backend/app/services/manager_type_review.py:65-73`,
   `backend/scripts/classify_managers_apply.py:32-63`.
4. PASS. The extract script is read-only: it opens a session, performs queries,
   prints JSON, and closes the session; no `add`, `update`, `delete`, `flush`,
   or `commit` appears. Evidence:
   `backend/scripts/classify_managers_extract.py:28-134`.

### B. Methodology

5. PASS. The foundation claim is true:
   `MANAGER_SIGNAL_WEIGHTS["long_term_fundamental"] == Decimal("1.00")` and
   `MANAGER_SIGNAL_WEIGHTS["value_concentrated"] == Decimal("1.00")`. Evidence:
   `backend/app/services/oracles_lens/constants.py:46-49`.
6. PASS. The mechanical rule mirrors the system behavior classifier's
   concentrated condition: top-10 concentration at least 0.50 and holding count
   at most 25 maps to `value_concentrated`. Evidence:
   `backend/scripts/classify_managers_decide.py:87-104`,
   `backend/app/services/oracles_lens/manager_signal.py:22-38`.
7. PASS. I did not find an obvious wrong off-1.00 classification among the 10
   scoring-relevant calls: Pershing Square, Icahn, Third Point, Engaged, Trian,
   and ValueAct as `activist`; Bridgewater as `quant`; Appaloosa and Oaktree as
   `multi_strategy`; Scion as `high_turnover`. TCI as
   `value_concentrated` instead of `activist` is a judgement call but is marked
   medium confidence and has no scoring impact versus `long_term_fundamental`.
   The Tiger Cub funds are also marked medium and classified conservatively as
   `long_term_fundamental`. Evidence:
   `backend/scripts/classify_managers_decide.py:30-54`,
   `docs/tasks/2026-05-21_manager-type-classification.md:45-58`.

### C. Classification Spot-Check

8. PASS. The JSON has 86 decisions with the expected distribution:
   44 `long_term_fundamental`, 32 `value_concentrated`, 6 `activist`,
   2 `multi_strategy`, 1 `quant`, 1 `high_turnover`. I spot-checked the
   no-holdings/documented-strategy group and did not see an obvious
   misclassification; the obscure ones are marked medium where appropriate.
   Evidence: `docs/tasks/2026-05-21_manager-type-classifications.json:1`,
   `backend/scripts/classify_managers_decide.py:55-80`.
9. PASS. Makaira id 69 is explicitly hand-classified in `EXPLICIT`, not run
   through the mechanical rule on its incomplete one-holding extract. Vulcan
   Value id 76 is mechanically classified from concentration + holding count,
   not the turnover proxy, so the suspected CUSIP-remap turnover artifact did
   not distort the result. Evidence:
   `backend/scripts/classify_managers_decide.py:79-80`,
   `backend/scripts/classify_managers_decide.py:87-104`,
   `docs/tasks/2026-05-21_manager-type-classification.md:85-90`.

### D. Scripts — Code Quality

10. PASS with advisory. The top-10 concentration calculation, quarter ordering,
    new-position fraction, and trailing holding-period span are straightforward:
    filings are ordered ascending by `quarter_end_date`, latest/prior are taken
    from the end, concentration divides holding values by total portfolio value,
    and trailing spans walk backward through ordered quarters. Advisory noted
    above: `_val()` should make the USD vs thousands fallback explicit before
    the script is reused. Evidence:
    `backend/scripts/classify_managers_extract.py:38-46`,
    `backend/scripts/classify_managers_extract.py:64-83`,
    `backend/scripts/classify_managers_extract.py:92-130`.
11. PASS. The three scripts are standalone under `backend/scripts/`, are not
    imported by the app/tests, and their names do not match `test_*`. CI
    collection should be unaffected. Evidence:
    `backend/scripts/classify_managers_apply.py:102-103`,
    `backend/scripts/classify_managers_decide.py:145-146`,
    `backend/scripts/classify_managers_extract.py:137-138`.

### E. Scope / Deferred

12. PASS. The original medium backlog item is replaced by two low-severity
    entries: first-pass human review and duplicate manager rows. The duplicate
    pairs named in the backlog are classified identically in the decision JSON:
    Abrams 18/84, Akre 15/81, Himalaya 46/83, and Baupost 63/85 are all
    `value_concentrated` within each pair. Evidence:
    `docs/BACKLOG.md:92-126`,
    `docs/tasks/2026-05-21_manager-type-classification.md:80-84`.

## Verification Performed

- Read the review prompt and task log.
- Inspected `git diff main...HEAD` scope.
- Reviewed the three scripts, the manager type review service, Oracle's Lens
  weight constants, behavior-derived manager signal rule, committed
  classifications JSON, and backlog changes.
- Used local JSON checks to confirm count distribution, required note/evidence
  markers, medium-confidence rows, and duplicate-pair type consistency.

I did not query the local prod container or run `pytest` in this review pass.
