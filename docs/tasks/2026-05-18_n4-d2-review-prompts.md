# N4 D2 Pre-flight + Execution Recipe — Review Prompts

Two reviewer prompts for the N4 D2 work shipped at commit `432ec47`. The change is doc + recipe only (no production code or tests changed); scope is intentionally narrow.

**Branch**: `docs/13f-automation-prd`
**Commit under review**: `432ec47` — N4 D2: pre-flight verified on dev + production execution recipe
**Scale**: 1 file, +80 / -1 lines (`docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md`)

**What landed**:

- D2 pre-flight (dev re-verification) — the formula-comparison endpoint was re-exercised against the populated dev DB; gates green (total=240, swap=0, persisted_only=0); response schema matches MVP8-01.
- Production execution recipe — a ready-to-run bash sequence: mint admin JWT → call the formula-comparison endpoint → evaluate gates with a Python one-liner that prints `✓/✗` per gate and a final `DEPLOY-SAFE` / `HOLD DEPLOY` verdict.
- Sign-off trail split — D2 nested into `[x] D2 (dev pre-flight)` + `[ ] D2 (prod)`, matching the D1 pattern.

**What did NOT land**: the prod-side execution itself (blocked on data access; not engineering work). D2 remains gated on operator action.

**Why 2 reviewers (not 3 or 4)**: this is a small scoped change — recipe correctness + production-readiness lens are the only meaningful failure surfaces. The PR #33 comprehensive review and the N4 D1 review already covered architecture / SME / frontend / general docs concerns.

Reviewers:

1. **Backend / Operations Reviewer** — recipe correctness, gate-evaluation logic, brittleness concerns.
2. **Production Readiness Reviewer** — is the pre-flight meaningful evidence? Does the recipe + gate evaluation actually de-risk the prod execution?

Verdict format across both:
```
APPROVE / APPROVE WITH NOTES / REJECT
<role>-specific findings ...
Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 1. Backend / Operations Reviewer Prompt

You are the Backend / Operations Engineer reviewing the N4 D2 production execution recipe. Branch `docs/13f-automation-prd`, commit `432ec47`. The change is doc-only — no production code or tests modified.

**Read these in order:**

1. `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` — find the `## D2 — Phase 1 comparison against production data` section. Read end-to-end including the new `### D2 pre-flight (dev re-verification, 2026-05-18)` and `### D2 production execution recipe` subsections.
2. `backend/app/api/v1/endpoints/thirteenf_admin.py` — find the `/oracles-lens/formula-comparison` endpoint (line ~1022). Confirm the endpoint shape matches the recipe's curl call.
3. `backend/app/services/oracles_lens/formula_comparison.py` — find `build_formula_comparison`. Confirm the response shape matches the gate evaluation's expected fields.

**Five questions:**

### B1 — Recipe command correctness

```bash
export TOKEN=$(docker compose exec -T api python -c "
import sys; sys.path.insert(0, '/app')
from app.core.security import create_access_token
from app.core.db import SessionLocal
from app.models.users import User
db = SessionLocal()
admin = db.query(User).filter(User.role == 'admin').first()
print(create_access_token(admin.id, admin.role))
db.close()
" | tail -1)
```

- The Python code is embedded inside `docker compose exec -T api python -c "..."`. Are there shell-quoting / escaping concerns? Specifically: the inner string uses double quotes for the Python `-c` argument and contains the bash variable boundary. Test by running it in a non-trivial shell context (zsh / bash / non-interactive).
- The script grabs the FIRST admin from `User.role == 'admin'`. In production, is there a guarantee that at least one admin user exists in the staging clone? If staging is hydrated from a sanitized dump that strips admin auth, this fails silently with `None.id` → AttributeError.
- The `| tail -1` strips any preceding warning output. Are there scenarios where `print(token)` produces extra lines (e.g., SQLAlchemy deprecation warnings) that would make `tail -1` capture a non-token line?

### B2 — Gate evaluation logic

```python
gates = {
    'total_stocks_compared >= 200': r['total_stocks_compared'] >= 200,
    'top10_swap_count == 0': r['top10_swap_count'] == 0,
    'persisted_only_count <= 10': r['persisted_only_count'] <= 10,
}
for label, ok in gates.items():
    print(('✓' if ok else '✗'), label, '→', r.get(label.split()[0]))
```

- The output extracts the field value via `r.get(label.split()[0])`. For "total_stocks_compared >= 200" this returns `r['total_stocks_compared']`. Works because the label's first whitespace-separated token IS the field name. Fragile if label wording changes (e.g., to "Total stocks compared >= 200" with a space). Worth noting?
- `r['total_stocks_compared']` etc. use bracket access (KeyError on missing field) while the print uses `r.get(...)`. If the endpoint response shape changes (e.g., a field rename), the dict comprehension crashes before the print runs. Is this the right error mode (loud failure beats silent miss) or should it be defensive?
- `all(gates.values())` only sees booleans. Confirmed safe.

### B3 — Response schema assumption

The recipe assumes the response has fields `total_stocks_compared`, `top10_swap_count`, `persisted_only_count`. The pre-flight section shows the dev output has all three plus `legacy_only_count`, `magnitude_diff_count`, `quarter`, `score_version`, `items`.

- Verify in `formula_comparison.py` that these three fields are stable contracts (not implementation-internal that could be renamed).
- Are there code paths where the endpoint returns a different shape (e.g., when `quarter` has no data)? Test: call the endpoint with a quarter that doesn't exist in the DB.

### B4 — Operational safety

- `> /tmp/d2-prod-comparison.json` overwrites any previous run's output. Should the recipe timestamp the filename (`/tmp/d2-prod-comparison-$(date +%s).json`)?
- The recipe runs the JWT mint + curl on the staging host where the docker compose stack is. If the operator runs from their laptop instead of SSH'd into staging, `docker compose exec` won't reach the staging container. Is the assumption "operator is on the staging host" documented?
- No timeout on the curl. If the formula comparison takes >30s against production-scale data, the operator may wait without feedback. Worth adding `--max-time 120` or similar?

### B5 — Pre-flight vs prod execution semantics

The pre-flight asserts "the utility still works as MVP8-01 expected." It does NOT validate anything about production-data shape (that's what the prod execution is for).

- Is the framing ("Endpoint works; gate evaluation logic is unchanged from MVP8-01") accurate? Or does it over-claim by listing the dev gate values prominently, giving a casual reader the impression that production gates are also clear?
- Should the pre-flight section have a one-line "NOTE: this is endpoint smoke-test only, NOT evidence that production gates will pass" to prevent the misread?

**Verdict format:**
```
APPROVE / APPROVE WITH NOTES / REJECT

B1: ...
B2: ...
B3: ...
B4: ...
B5: ...

Should-block items (REJECT only): ...
Future backlog (not blocking): ...
```

---

## 2. Production Readiness Reviewer Prompt

You are the Production Readiness Reviewer evaluating whether the N4 D2 pre-flight + recipe actually de-risks the production execution. Branch `docs/13f-automation-prd`, commit `432ec47`.

**Read these in order:**

1. `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` — D2 section end-to-end including the pre-flight + recipe + sign-off trail.
2. `docs/tasks/2026-05-13_mvp8-01-mvp5-03-phase3-flip.md` — for context on MVP8-01's original Phase 1 comparison evidence (2025-Q3 dev DB).
3. `docs/tasks/2026-05-14_open-work-snapshot.md` — Next Action section, especially the order D2 → D5 → D4 → D3.

**Five questions:**

### P1 — Is the pre-flight meaningful evidence?

The pre-flight re-ran the formula-comparison endpoint against the same dev DB MVP8-01 used. Result: identical gate values (`total=240, swap=0, persisted_only=0`).

- Does this re-run add information beyond "the comparison utility hasn't regressed since MVP8-01"? Specifically, MVP8-01's evidence is several days old; the dev DB has not been re-scored or re-ingested since.
- Is the pre-flight value mostly about confirming the recipe works (curl + JSON parse + gate eval), or about confirming the utility produces the expected schema? Both are real but the framing in the ticket emphasizes "gate values green" — which is the LEAST useful interpretation (dev was already known green).
- Should the pre-flight section be reframed to lead with "recipe smoke-test passes" rather than "gates green"?

### P2 — Operational safety of the recipe against production data

The recipe runs admin-token-authenticated reads against the formula-comparison endpoint. The endpoint computes scoring against `oracles_lens_signals` rows + the legacy in-memory formula.

- Read-only operation? Confirm `build_formula_comparison` does not write any state. (Check for any `session.commit()` or write operations in the function.)
- Resource cost: the legacy formula path iterates all qualifying stocks. Against production-scale data (240+ stocks, hundreds of holders each), is the request likely to complete in <30s? If not, the recipe needs a longer timeout AND the operator should be warned.
- Is there any risk that running this against production-shape data triggers a side effect (e.g., a caching layer that gets warmed, a usage metric that gets recorded as if a user accessed it)? Probably not, but worth confirming.

### P3 — Gate values vs deploy decision

The recipe prints `DEPLOY-SAFE` if all three gates pass: `total >= 200 && swap == 0 && persisted_only <= 10`.

- Are these three gates necessary AND sufficient? Could a regression case slip through (e.g., `total=240, swap=0, persisted_only=2`, but `magnitude_diff_count` jumps to a level that indicates a real divergence)? Should `magnitude_diff_count` be an informational printout, or also a gate threshold?
- The dev pre-flight shows `magnitude_diff_count=59`. MVP8-01 documented this as "all ~70% scale shift" — informational. But "59 magnitude diffs" in production could mean different things (different stocks, different magnitudes). Should the recipe also surface a SAMPLE of items with `MAGNITUDE_DIFF_25_PCT` for visual review?

### P4 — Sign-off trail clarity

The trail now reads:
```
- [ ] D2 Phase 1 comparison green against production data.
  - [x] D2 pre-flight (dev re-verification 2026-05-18): ...
  - [ ] D2 (prod) — operator runs the recipe against a staging clone ...
```

- Is the parent `[ ]` (unchecked) clearly indicating D2 is NOT cleared overall, despite the child `[x]` being checked? A scanner who sees the `[x]` first could misread.
- Should the parent line be reworded to make the partial state more obvious, e.g., `[~] D2 (in progress)` or similar? Markdown checkbox syntax doesn't support a tri-state visually, but the wording could.

### P5 — Net D2 readiness shift

Before this commit: D2 was "unstarted; recipe undocumented; operator would need to figure out endpoint + auth + gate eval from scratch."

After: the recipe is one-paste-from-execution. The operator's remaining work is data hydration (the staging clone) and the actual paste.

- How much real risk did this remove? (My read: meaningful — reduces operator preparation time + eliminates the "did I call the right endpoint with the right gates" ambiguity. But it doesn't move D2 closer to actually-cleared.)
- Is the right next step D5 (VL coverage audit, which I can run on dev now) or D3 (rollback runbook, doc-only) while waiting on D2 prod execution? The user's stated order is D1 → D2 → D5 → D4 → D3; does this commit's "D2 dev pre-flight + recipe" actually unblock D5, or are they independent?

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
