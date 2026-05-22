# Review results — Manager `manager_type` first-pass classification

**PR:** #88, branch `claude/manager-type-classification`  
**Reviewer:** Claude Sonnet 4.6 (agent review)  
**Date:** 2026-05-21  
**Prompt:** `docs/tasks/2026-05-21_manager-type-classification-review-prompts.md`

---

## Overall verdict: **APPROVE**

The prod write was done safely through the audited service, honestly recorded as
a machine first pass, and is fully reversible via the admin editor. The
methodology's foundation (the 1.00/1.00 weight equality) is confirmed. The
mechanical rule exactly matches the live classifier's concentration branch. No
off-1.00 call is clearly wrong; the two advisory classifications (TCI,
Tiger Cubs) are flagged for priority human review. All mandatory gates (A1–A4,
B5–B7) pass.

---

## A. Write path & safety

### A1. Audited service, no raw SQL — **PASS**

Evidence: `backend/scripts/classify_managers_apply.py:26–29, 69–76`

The script imports and uses exclusively:

```python
from app.services.manager_type_review import (
    ManagerTypeUpdateError,
    update_manager_type,
)
```

Every write goes through `update_manager_type(session, mid, new_manager_type=mtype, reviewer_user_id=None, note=d["note"], evidence_json=d.get("evidence_json"))`. No raw SQL, no direct column mutation anywhere in the script. AGENTS.md invariant #4 is respected. ✓

The service itself (`manager_type_review.py:75–86`) mutates only `manager.manager_type`, appends one `InstitutionManagerTypeReviewEvent` row, and calls `session.flush()` + `session.commit()` — column and audit row in one transaction, as the docstring guarantees.

### A2. Honest audit trail — **PASS**

Evidence: `classify_managers_apply.py:73`; `classify_managers_decide.py:125–130`; `docs/tasks/2026-05-21_manager-type-classifications.json` (all 86 rows verified)

Three verifications:

1. **`reviewer_user_id=None`:** `apply.py:73` passes `reviewer_user_id=None`. Attributing machine rows to a real user ID would have falsified the audit trail. ✓

2. **Note prefix:** Every note in the JSON starts with `[auto-classified by Claude, first pass — pending human review]`. Programmatic check against all 86 rows:
   ```
   Bad note prefix: 0 []
   ```
   ✓

3. **`classified_by` claim:** Every `evidence_json` carries `"classified_by": "claude_first_pass"`. Programmatic check:
   ```
   Bad classified_by: 0 []
   ```
   ✓

The trail is honest: machine provenance is explicit, reviewers can find every auto-classified row via `evidence_json->>'classified_by' = 'claude_first_pass'`.

### A3. Idempotency — **PASS**

Evidence: `manager_type_review.py:65–73`; `classify_managers_apply.py:34`

`update_manager_type` returns `{"changed": False, "audit_event_id": None}` when
`old_manager_type == new_manager_type` — no audit row is written. A re-run of
`classify_managers_apply.py` after the first pass would produce 86 `noop`
lines and 0 new audit rows. ✓

The script defaults to dry-run mode: `apply = "--apply" in args` (line 34). The
`--apply` flag must be passed explicitly to write. The task doc confirms the
dry-run was executed first (86 rows, 0 unknown IDs) before the live pass. ✓

### A4. Extract is read-only — **PASS**

Evidence: `classify_managers_extract.py` (full file)

The extract script uses only `session.query(...)` calls — no `session.add()`,
`session.commit()`, `session.execute(UPDATE/INSERT/DELETE)`, or `session.flush()`.
The module docstring at line 14: "Makes no writes." The `finally: session.close()`
at line 134 closes the session without any write having occurred. ✓

---

## B. Methodology

### B5. The "both 1.00" claim — **PASS (verified against source)**

Evidence: `backend/app/services/oracles_lens/constants.py:47–48`

```python
MANAGER_SIGNAL_WEIGHTS: dict[str, Decimal] = {
    "long_term_fundamental": Decimal("1.00"),
    "value_concentrated":    Decimal("1.00"),
    ...
}
```

Both types carry exactly `Decimal("1.00")`. The methodology's central claim —
that the 48-manager mechanical split between `value_concentrated` and
`long_term_fundamental` has **zero scoring impact** — is verified. The full
weight table:

| Type | Weight |
|---|---|
| `long_term_fundamental` | 1.00 |
| `value_concentrated` | 1.00 |
| `activist` | 0.80 |
| `multi_strategy` | 0.60 |
| `quant` | 0.40 |
| `high_turnover` | 0.30 |
| `index_like` | 0.10 |

The "low-stakes" framing for the mechanical split is correct. All consequential
classification effort was spent on the 10 off-1.00 managers.

### B6. The mechanical rule — **PASS** with advisory

Evidence: `classify_managers_decide.py:94`; `manager_signal.py:36–37`

The mechanical rule in `decide.py`:
```python
if top10 >= 0.50 and hc <= 25:
    return "value_concentrated", ...
return "long_term_fundamental", ...
```

The live system's `derive_manager_signal_profile` condition in `manager_signal.py`:
```python
elif concentration >= 0.5 and holding_count <= 25:
    manager_type = "value_concentrated"
```

Conditions are **identical** — same threshold (≥0.50 / ≤25), same semantics.
The machine pass is consistent with how the system itself would classify these
managers from their 13F data. ✓

**Advisory (non-blocking):** The live system checks `turnover_proxy >= 0.6` for
`high_turnover` **before** the concentration branch (`manager_signal.py:33–35`).
The mechanical rule omits this guard. For a genuinely high-turnover manager in
the Dataroma universe, the mechanical rule would classify them as
`value_concentrated` or `long_term_fundamental` instead of `high_turnover`. The
risk is negligible — the Dataroma "superinvestor" list is long-only fundamental
value managers by construction — but the one edge case (Vulcan Value, id 76,
turnover proxy 0.97) is correctly handled: the task doc identifies the 0.97 as
a CUSIP-remap artifact, the mechanical rule ignores the turnover proxy and
classifies on concentration + holding count, and the result is unaffected. ✓

### B7. The 10 scoring-relevant calls — **PASS** with advisory

Evidence: `classify_managers_decide.py:31–54`; `docs/tasks/2026-05-21_manager-type-classifications.json`

**Activists (6, weight 0.80):**

| ID | Manager | Assessment |
|---|---|---|
| 5 | Pershing Square (Ackman) | PASS — archetypal activist, McDonald's / Herbalife campaigns |
| 10 | Icahn | PASS — invented the activist playbook |
| 17 | Third Point (Loeb) | PASS — board-letter activist, multiple proxy fights |
| 31 | Engaged Capital (Welling) | PASS — small/mid-cap constructive activist, 37+ campaigns |
| 52 | Trian (Peltz) | PASS — board-seat activist (GE, P&G, Disney) |
| 74 | ValueAct (Ubben) | PASS — insider board-seat activist approach |

All six are unambiguously activist. ✓

**Quant (1, weight 0.40):**
- id 86: Bridgewater (Dalio) → `quant`. PASS — systematic global-macro, computerised decision systems. ✓

**Multi-strategy (2, weight 0.60):**
- id 22: Appaloosa (Tepper) → `multi_strategy`. PASS — event-driven / distressed / credit / macro; the 13F long book is one sleeve. ✓
- id 38: Oaktree (Howard Marks) → `multi_strategy`. PASS — primarily credit / distressed / PE; the 13F equity exposure is peripheral. ✓

**High-turnover (1, weight 0.30):**
- id 50: Scion (Burry) → `high_turnover`. PASS — ~250% portfolio churn, options-heavy contrarian trading, quarterly rebuilds. ✓

**Advisory — TCI (id 12, medium confidence):**
Classified `value_concentrated`, not `activist`. The evidence: Chris Hohn
founded TCI with an activist mandate and the current book is ~10 highly
concentrated quality-growth names (low turnover). The note acknowledges the
activist heritage and cites Hohn's public statements that activism is now
"opportunistic." This is a **defensible judgement call**, but it is the most
debatable of all 10 off-1.00-adjacent calls. If TCI conducted a significant
activist campaign post-classification, the type should be corrected to
`activist` (weight 0.80 vs 1.00 — a meaningful scoring difference). 

Recommendation: flag TCI for **priority human review** before any
Oracle's Lens scoring that heavily weights TCI positions.

**Advisory — Tiger Cubs (4 managers, medium confidence):**
ids 11 (Tiger Global), 44 (Maverick), 64 (Lone Pine), 75 (Viking) →
`long_term_fundamental`. The 13F captures only the long side of each fund;
the classification reflects the long-book character (fundamental, bottom-up,
multi-year holdings) rather than the full long/short strategy. This is correct
methodology — the system can only score what is reported in 13F filings.
Medium confidence is appropriately conservative given the incomplete visibility.
No misclassification. ✓

---

## C. Classification spot-check

### C8. JSON sample — **PASS**

Evidence: `2026-05-21_manager-type-classifications.json` (all 86 rows analysed)

Distribution matches the task doc exactly:

| Type | Count (JSON) | Count (task doc) |
|---|---|---|
| `long_term_fundamental` | 44 | 44 |
| `value_concentrated` | 32 | 32 |
| `activist` | 6 | 6 |
| `multi_strategy` | 2 | 2 |
| `quant` | 1 | 1 |
| `high_turnover` | 1 | 1 |

Medium-confidence entries (8 total, all flagged appropriately):
TCI (id 12), Tiger Cubs (ids 11, 44, 64, 75), Makaira (id 69), Hillman (id 37),
Torray (id 70). ✓

**Spot-check on the mechanical boundary (id 1 — AKO Capital):**
Note text: "27 holdings, top-10 weight 66.2% → `long_term_fundamental`."
The rule: `top10 >= 0.50 AND hc <= 25`. AKO has top10 = 0.662 ≥ 0.50, but
`hc = 27 > 25`. Falls to `long_term_fundamental` — correct application of the
rule, though AKO is borderline concentrated. This is not a misclassification;
the threshold boundary is the same one the live system uses.

**27 managers with no ingested 13F holdings:** All classified on documented
strategy from `EXPLICIT` (method = `documented_strategy`), with notes stating
"no 13F holdings ingested." Strategies match known facts: Pabrai (~5-10 names),
Klarman/Baupost (concentrated deep-value), Sequoia/Ruane Cunniff (concentrated),
Dodge & Cox and Mairs & Power (diversified long-term), etc. Reasonable across
the board. ✓

### C9. Data-quality handling — **PASS**

Evidence: `classify_managers_decide.py:79–80`; `classify_managers_decide.py:87–104`

**Makaira (id 69):** Present in `EXPLICIT` at line 80 with note "prod 13F
behaviour data is incomplete (1 holding ingested) — classified on documented
strategy." The `EXPLICIT` path bypasses the mechanical rule entirely. Makaira
was not run through the mechanical rule on bad data. ✓

**Vulcan Value (id 76):** NOT in `EXPLICIT` → mechanical path. The mechanical
rule (`decide.py:94`) uses only `top10_concentration` and
`latest_holdings_count`. The `new_position_fraction_vs_prior_q` field (the
turnover proxy at 0.97) is present in the extract JSON but is **not referenced**
by the `mechanical()` function. The turnover proxy therefore did not distort the
classification. ✓

---

## D. Scripts — code quality

### D10. Extract behaviour metrics — **PASS** with advisory

Evidence: `classify_managers_extract.py:24–130`

**Quarter ordering:** Filings queried with `ORDER BY quarter_end_date.asc()`
(line 44). `filings[-1]` is the latest quarter; `filings[-2]` is the
second-latest. ✓

**`total = sum(...) or 1` (line 69):** Prevents division-by-zero when all
holdings have zero-valued positions. In this case all weights collapse to ~0
and `top10_concentration` ≈ 0, giving `long_term_fundamental` via the
mechanical rule — a safe fallback. ✓

**Turnover proxy (lines 101–106):**
```python
len(latest_cusips - prior_cusips) / len(latest_cusips)
```
"New positions as a fraction of all current positions." The guard `if
latest_cusips:` (line 101) prevents division-by-zero. ✓

**Trailing hold span (lines 108–130):** Iterates `reversed(qorder)` (latest
to earliest), incrementing the streak until a quarter is missing, then breaks.
This correctly computes trailing consecutive hold length — a CUSIP absent in
one recent quarter resets the streak, which is the intended behaviour. ✓

**Advisory — `_val` unit mixing (`classify_managers_extract.py:24–25`):**
```python
def _val(h: Holding13F) -> int:
    return int(h.value_usd or h.value_thousands or 0)
```
`value_usd` (absolute dollars) and `value_thousands` (thousands of dollars)
are in different units. If some `Holding13F` rows in the same filing have
`value_usd` populated and others do not (falling through to `value_thousands`),
concentration weights would be off by a factor of 1,000 for the mixed holdings.
The practical risk is low if the data is consistent per filing (which 13F
ingestion would enforce), and the extract is a one-shot operational script.
However, this warrants a comment or an assertion before any reuse of `_val` in
other contexts.

### D11. Scripts are standalone — **PASS**

Evidence: file names; task doc line 109

File names (`classify_managers_extract.py`, `classify_managers_decide.py`,
`classify_managers_apply.py`) do not match the `test_*` pattern — `pytest` does
not collect them. They are not imported by the app or any existing test. `pytest
-q` was green (902). ✓

---

## E. Scope / deferred

### E12. BACKLOG deferral hygiene — **PASS**

Evidence: `docs/BACKLOG.md:95–122`

1. **Original medium entry removed.** The new human-review entry at line 96
   states: "supersedes the 2026-05-20 audit #9 'all `unknown`' item, which is
   now resolved (all 86 managers are classified)." The original entry is absent.
   Two new `low` entries replace it. ✓

2. **Human-review follow-up entry:** Present (`BACKLOG.md:95–111`), severity
   `low`. Includes: problem description (first pass, null reviewer), specific
   query (`reviewed_by_user_id IS NULL`), and a prioritized review order (10
   scoring-relevant off-1.00 rows first, then ~8 medium-confidence calls). ✓

3. **Duplicate-manager entry:** Present (`BACKLOG.md:113–122`), severity `low`.
   Names all four duplicate pairs with IDs, describes the data impact (split
   history, double-counting in rollups), and defers the dedup/merge. ✓

4. **Duplicate pairs classified identically:** Verified programmatically from
   the JSON:

   | Pair | IDs | Both classified |
   |---|---|---|
   | Abrams Capital | 18 + 84 | `value_concentrated` ✓ |
   | Akre Capital | 15 + 81 | `value_concentrated` ✓ |
   | Himalaya Capital | 46 + 83 | `value_concentrated` ✓ |
   | Baupost Group | 63 + 85 | `value_concentrated` ✓ |

   All four pairs are internally consistent. ✓

---

## Summary of advisory items

| # | Item | Severity | Action |
|---|---|---|---|
| B6 | Mechanical rule omits turnover_proxy guard; Vulcan Value edge case handled | low | Harmless for Dataroma universe; no action needed |
| B7 | TCI (id 12) classified `value_concentrated` despite activist heritage | medium (advisory) | **Priority human review before Oracle's Lens scoring of TCI positions** |
| B7 | Tiger Cubs (4 funds) classified on long-side only, 13F visibility incomplete | low | Medium confidence flagged; acceptable for v0.1 |
| D10 | `_val` fallback `value_usd or value_thousands` mixes units if inconsistent per filing | low | Add comment/assertion before reusing `_val` elsewhere |

No advisory item is a blocker. The write is safe, the audit trail is honest, and
any misclassification can be corrected via the admin manager-type editor.
