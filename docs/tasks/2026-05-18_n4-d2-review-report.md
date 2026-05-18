# N4 D2 Pre-flight + Execution Recipe — Review Report

**Review date**: 2026-05-18
**Branch**: `docs/13f-automation-prd`
**Commit under review**: `432ec47` — N4 D2: dev pre-flight verified + production execution recipe
**Method**: Read N4 ticket (D2 section end-to-end), `thirteenf_admin.py:1022-1036` (formula-comparison endpoint), `formula_comparison.py` (full), `mvp8-01-mvp5-03-phase3-flip.md` (Phase 1 evidence + gate rationale).

---

## 1. Backend / Operations Review

**APPROVE WITH NOTES**

---

### B1 — Recipe command correctness

**Shell quoting**: safe. The Python `-c` argument is in a double-quoted multi-line string. All Python string literals inside use single quotes (`User.role == 'admin'`, `sys.path.insert(0, '/app')`). No unescaped double quotes inside the outer `"..."`. Works in bash and zsh.

**`| tail -1` correctness**: `create_access_token` returns a JWT string; `print(token)` outputs exactly one line to stdout. SQLAlchemy warnings go to `stderr` via `warnings.warn`, not stdout, so the pipe captures only the `print()` output. If the engine were configured with `echo=True`, SQL would appear on stdout and `tail -1` could capture the last SQL statement instead of the JWT — but in any normal non-debug config `echo=False`. Safe.

**No-admin-user failure**: if the staging clone has no admin user, `db.query(User).filter(User.role == 'admin').first()` returns `None`. `print(create_access_token(None.id, ...))` raises `AttributeError`. The traceback goes to stderr; `tail -1` on stdout gets an empty string. `TOKEN` becomes `""`. The subsequent curl sends `Authorization: Bearer ` with an empty token, gets a 401, and the gate-evaluation script fails with `KeyError` on `total_stocks_compared`. The failure is loud but the root cause is not obvious. A one-line guard would make it immediate and clear:

```python
if admin is None:
    raise RuntimeError("No admin user found — staging DB may be stripped of auth data")
```

**Placeholder documentation gap**: the curl uses `http://<staging-host>:<api-port>/...` with angle-bracket placeholders. A first-time operator may not know how to discover the staging host and API port. A note — "Replace `<staging-host>:<api-port>` with the staging machine's IP and the host-side API port from `docker compose ps`" — would close this gap.

---

### B2 — Gate evaluation logic

**`r.get(label.split()[0])` extraction**: correctly retrieves the field name for all three labels:
- `'total_stocks_compared >= 200'` → `'total_stocks_compared'` ✓
- `'top10_swap_count == 0'` → `'top10_swap_count'` ✓
- `'persisted_only_count <= 10'` → `'persisted_only_count'` ✓

Fragile only if label wording changes. This is a one-shot operator script; the risk is low. A comment `# label format: '<field_name> <operator> <threshold>'` would document the convention.

**Error mode on bad response**: bracket access `r['total_stocks_compared']` raises `KeyError` if the JSON is an error response (e.g., `{"detail": "Not authenticated"}`). This is the right error mode — loud and specific, not a silent wrong-value print.

**`all(gates.values())`**: correctly evaluates all three booleans. Confirmed.

---

### B3 — Response schema assumption

The three gated fields are stable contracts. Confirmed across both code paths of `build_formula_comparison`:

- **No-data path** (`target_quarter is None`, lines 120-129): returns `total_stocks_compared=0`, `top10_swap_count=0`, `persisted_only_count=0` — all three present. The gate evaluation then correctly prints `HOLD DEPLOY` (total=0 fails `≥ 200`). ✓
- **Normal path** (lines 157-161): `**comparison` unpacks `compute_formula_comparison`'s return dict, which always includes all three (lines 95-102). ✓

When `quarter` is specified but has no scored signals: `target_quarter` is non-None, the intersection is empty, `total_stocks_compared=0` → gate fails. Correct behavior for an unmeasured quarter.

The recipe calls the endpoint without a `quarter` param (uses latest). The `_latest_scored_quarter` function queries `OraclesLensSignal.report_quarter` ordered descending — it will find the most recent scored quarter regardless of calendar. Safe.

---

### B4 — Operational safety

**Filename overwrite**: the recipe writes to `/tmp/d2-prod-comparison.json` (fixed name), but the sign-off instruction says "Save to `/tmp/d2-prod-comparison-<date>.json`." The recipe and the instruction are inconsistent. If the operator runs twice (once to test, once against prod), the second run overwrites the first. The audit trail is lost. The recipe should timestamp the filename:

```bash
curl -s "..." -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool > /tmp/d2-prod-comparison-$(date +%Y%m%d-%H%M%S).json
```

Then the gate-evaluation step reads the timestamped file (or the operator copies it to a fixed name for the Python step).

**"Operator is on the staging host" assumption**: `docker compose exec -T api python -c "..."` requires the Docker socket of the staging deployment. This only works from the staging host or from a machine whose Docker context points at staging. Not documented. Add one sentence before step 1: "Run these commands from the staging host (or a machine whose Docker context targets the staging stack — confirm with `docker context ls`)."

**No `curl --max-time`**: `build_formula_comparison` runs the legacy in-memory formula for all 240+ stocks. Dev pre-flight was fast; production should be similar. But if the legacy formula path is slower against production's manager universe, the operator may wait with no feedback. Adding `--max-time 120` costs nothing.

---

### B5 — Pre-flight vs prod execution semantics

The framing "Endpoint works; gate evaluation logic is unchanged from MVP8-01" is accurate. The gate values shown (`total=240, swap=0, persisted_only=0`) are IDENTICAL to MVP8-01's Phase 1 evidence because it's the same dev DB with the same data. The pre-flight adds exactly two pieces of information:

1. **Endpoint regression check**: no PR #33 response commit broke the comparison utility.
2. **Recipe smoke-test**: the curl + JSON parse + gate eval flow functions as written.

What it does NOT add: production-data evidence, or any new signal about whether production gates will pass.

The ✓ symbols in the pre-flight output and in the sign-off child item are factually correct but visually communicate stronger evidence than the pre-flight actually provides. An operator scanning the sign-off trail sees three ✓ symbols on the exact gate labels used for the deploy decision. The distinction between "dev smoke-test" and "production gate" is in the text, not in the visual indicator.

**Recommended addition** (one line in the pre-flight section body):

> NOTE: the gate values above are from the dev DB (same data as MVP8-01 — no new information about production outcomes). This pre-flight confirms the recipe functions and the endpoint has not regressed; it is NOT evidence that production gates will pass.

---

### Should-block items

None.

---

### Future backlog

- **Add `no-admin-user` guard** (B1) — `if admin is None: raise RuntimeError(...)`. Prevents confusing auth failures.
- **Timestamp the output filename** (B4) — `$(date +%Y%m%d-%H%M%S)` so multiple runs don't overwrite each other.
- **Add `--max-time 120` to curl** (B4) — prevents silent hang.
- **Document "must be on staging host" assumption** (B4) — one sentence before step 1.
- **Add pre-flight NOTE clarifying dev evidence ≠ production evidence** (B5).
- **Add `magnitude_diff_count` informational print** to the gate evaluation output (see P3 below) — one line after the gates loop.

---

## 2. Production Readiness Review

**APPROVE WITH NOTES**

---

### P1 — Is the pre-flight meaningful evidence?

The pre-flight ran against the same dev DB as MVP8-01. The data hasn't changed; the result is identical (`total=240, swap=0, persisted_only=0, magnitude_diff=59`). The pre-flight adds:

- **Real value**: confirms no PR #33 post-review commit inadvertently broke the formula-comparison utility. Six commits have landed since MVP8-01; this rules out regression.
- **Real value**: confirms the recipe (curl invocation, JSON parsing, gate evaluation) works as written before the operator runs it against production.
- **Zero value**: regarding production gate outcomes. The dev gate values were already known.

The framing "gate evaluation logic is unchanged from MVP8-01" is accurate. The ticket's lead emphasis on "gate values green" is the least useful interpretation of the pre-flight result. **The pre-flight is primarily a recipe smoke-test**, not gate evidence.

Should the section be reframed? Yes, slightly — without changing the content. Lead with "Recipe smoke-test passed; endpoint regression-free since MVP8-01" and describe the gate values as "matches MVP8-01 baseline (expected — same dev DB)" rather than using ✓ symbols that imply fresh evidence.

---

### P2 — Operational safety of the recipe against production data

**Read-only confirmed**:
- `build_formula_comparison` (lines 105-161): only `session.query()` calls. No `session.add()`, `session.commit()`, or `session.delete()`. ✓
- `build_oracles_lens_dashboard` with `use_persisted_scores=False`: the legacy in-memory formula path — reads `OraclesLensSignal` rows and computes scores in memory. No writes. ✓
- `compute_formula_comparison` (lines 42-102): pure function, no session, no IO. ✓

Safe to run against production-shape data. No state mutation risk.

**Resource cost**: the legacy formula iterates all qualifying stocks in-memory. Dev returned results for 240 stocks quickly. Production should be the same order of magnitude (the 240 superinvestor-tracked stocks are bounded). No resource concern.

**Side effects**: none. No caching layer in the formula-comparison path. No usage metrics or audit logging beyond the standard FastAPI access log. ✓

---

### P3 — Gate values vs deploy decision

The three gates (`total >= 200`, `swap == 0`, `persisted_only <= 10`) are the exact acceptance criteria from MVP8-01's D1 spec. They are necessary and sufficient for the Phase 3 flip decision per the original design:
- `total >= 200`: meaningful universe coverage.
- `swap == 0`: the critical product gate — no ranking reversal in the top 10.
- `persisted_only <= 10`: no material universe divergence between the two formulas.

`magnitude_diff_count` is correctly classified as informational. The ~70% scale shift (documented as the base-formula divergence from MVP8-02) does not indicate a ranking problem. It is not and should not be a hard gate.

**One gap in the recipe**: `magnitude_diff_count` is present in the saved JSON but is NOT surfaced in the terminal gate-evaluation output. If production shows `magnitude_diff_count = 10` or `magnitude_diff_count = 150` (vs dev's 59), that's a meaningful finding worth operator attention even without a gate threshold. The operator currently has to open the JSON file to see it.

**Recommended one-line addition** to the gate evaluation Python snippet, after the gates loop:

```python
print(f"  magnitude_diff_count (informational, ~59 on dev): "
      f"{r.get('magnitude_diff_count', 'N/A')}")
```

Additionally: a note in the recipe text — "If `magnitude_diff_count` differs significantly from dev's 59, inspect the `items` array in the saved JSON for `MAGNITUDE_DIFF_25_PCT` flags on top-10 stocks before deploying." This keeps the gate logic clean while surfacing the informational signal.

---

### P4 — Sign-off trail clarity

The current structure:
```
- [ ] D2 Phase 1 comparison green against production data.
  - [x] D2 pre-flight (dev re-verification 2026-05-18): ...
  - [ ] D2 (prod) — operator runs the recipe ...
```

The parent `[ ]` correctly signals D2 is not overall cleared. The nesting mirrors the D1 pattern. The `[x]` child is clearly labeled "dev re-verification"; the `[ ]` child is labeled "(prod)." The distinction is explicit.

**Risk of misread**: the sign-off child item lists `(total=240, swap=0, persisted_only=0)` — three numbers that look like passing gate values. An operator who scans quickly may associate the numbers with the parent gate condition ("Phase 1 comparison green") before reading "dev re-verification." The visual is correct but slightly misleading.

**Markdown tri-state**: `[~]` is not standard Markdown checkbox syntax and would render as literal text. Not recommended. The current `[ ]` parent is the right approach.

**One small wording improvement**: in the sign-off child item, change `dev gates green (total=240, swap=0, persisted_only=0)` to `endpoint regression-free; dev gates match MVP8-01 baseline (total=240, swap=0, persisted_only=0 — same dev DB, no new prod evidence)`. This makes the "no new prod evidence" explicit at the point where an operator might misread.

---

### P5 — Net D2 readiness shift

**Before this commit**: an operator wanting to run D2 would need to locate the right endpoint, figure out admin auth, understand the three gate thresholds, and write the evaluation logic from scratch. ~30 min of preparation, with real failure modes (wrong endpoint, wrong threshold value, misread JSON).

**After this commit**: one copy-paste sequence. Gate thresholds are embedded. Auth is scripted. Output is machine-evaluable. The "wrong endpoint" and "wrong threshold" failure modes are eliminated.

**Risk reduction is real**: reduces operator preparation time and eliminates ambiguity about what constitutes a passing gate. Does not advance D2 toward actually-cleared — that requires the staging clone, which is an operational prerequisite outside engineering's control.

**D5 parallelism**: D5 (VL coverage audit) is independent of D2 results. D5 requires only a `SELECT ... FROM metric_facts` query against the staging clone. If the staging clone is being prepared for D2, D5 can share it and proceed in parallel with D2 prod execution. D5 does not need to wait for D2's `DEPLOY-SAFE` / `HOLD DEPLOY` verdict.

**D3 parallelism**: D3 (rollback runbook) is doc-only with no data dependency. It can and should start immediately — it doesn't require the staging clone, and writing the runbook while waiting for staging access is the highest-leverage use of the available engineering time. The D2 → D5 → D4 → D3 ordering optimizes data dependencies (D4 needs D2 + D5 numbers); D3 has no such dependency and should be de-sequenced from the waiting work.

---

### Should-block items

None.

---

### Future backlog

- **Reframe pre-flight section body** (P1) — lead with "recipe smoke-test passed; endpoint regression-free" and add one-line NOTE clarifying dev evidence ≠ production evidence.
- **Add `magnitude_diff_count` informational print to gate evaluation** (P3) — surfaces an unexpectedly large or small count without requiring the operator to open the JSON file.
- **Add note about reviewing `items` for `MAGNITUDE_DIFF_25_PCT` flags** (P3) — one sentence in the recipe text.
- **Update sign-off child item wording** (P4) — make "no new prod evidence" explicit at the point of the listing.
- **Start D3 now** (P5) — rollback runbook has no staging-clone dependency; writing it in parallel with D2 + D5 is the highest-leverage path.

---

## Net Across Both Reviews

The commit is correct and safe to keep. The recipe functions as intended: JWT mint → curl → gate evaluation is a valid, one-paste-from-execution sequence. The formula-comparison endpoint is read-only and stateless. The three gate fields are stable contracts present in all code paths.

**Primary note across both reviews**: the pre-flight framing over-signals gate evidence. The ✓ symbols and listed gate values in the sign-off child item look like fresh evidence, but the values are identical to MVP8-01 (same dev DB). A one-sentence disclaimer in both the section body and the sign-off child item would calibrate this correctly without changing any content.

**Secondary note**: four small hardening items (no-admin guard, timestamped filename, `--max-time`, staging-host note) plus adding `magnitude_diff_count` to the terminal output would make the recipe more robust for an operator without full context.

**D2 gate status**: still blocked on staging clone. The recipe removes all other friction from the operator's path once the clone exists.
