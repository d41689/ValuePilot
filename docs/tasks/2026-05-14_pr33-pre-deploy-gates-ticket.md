# PR #33 Pre-Deploy Gates

## Status

**Open 2026-05-14.** Filed as a follow-up to PR #33 comprehensive review (Production Readiness P1-P6 + Backend B4 + Staff A7). Status framing updated 2026-05-18 per post-review-response audit.

PR #33's codebase is correct and the canonical CI commands are green. But there are five pre-deploy gates that **must clear before the merged code reaches production traffic**. This ticket tracks them.

## Repo-specific note: merge ≡ deploy

The Production Readiness reviewer framed N4 as "blocks deploy, not merge." That framing is correct in repos where `main` is a staging branch with a manual promote-to-production step. **This repo is not configured that way.**

`.github/workflows/deploy.yml` auto-fires on every successful CI run on `main`:

```yaml
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
# ...
if: >
  github.event.workflow_run.conclusion == 'success' &&
  github.event.workflow_run.head_branch == 'main'
```

In practical terms: **merge to `main` IS production deploy.** So N4 gates **merge** for this repo, not "deploy after merge."

Three options to handle this:

1. **(Recommended) Clear N4 before merging PR #33.** Treat the auto-deploy coupling as a feature, not a bug — it forces the deploy-readiness check before the change goes live.
2. **Disable auto-deploy temporarily** (comment out the `workflow_run` trigger in `deploy.yml`, leave only `workflow_dispatch` for manual deploy). PR #33 merges to `main`; deploy runs only when manually triggered after N4 clears.
3. **Use a separate staging branch.** Bigger workflow change; not recommended for a one-off PR.

Option 1 is the cleanest unless the team has a reason to merge-but-not-deploy (e.g., wanting `main` to receive other PRs before deploy). Default to option 1.

## Why a separate ticket from the implementation work

The 5 gates below are 1-2 days of work — verification + documentation + release-note drafting, not code changes. They could have been inline in PR #33 but were kept separate to let the code review close cleanly. Now that the code review is complete, this ticket is the deploy-readiness checklist.

## Goal

Clear all five gates before promoting the merged commit to production. If a gate fails, hold deploy until the gate is satisfied (do not let `main` and prod diverge for long — that's its own risk class).

## D1 — Migration round-trip test against prod-like data

**Source**: Backend B4, Staff A7, Production P4.

**Why**: The branch has 23 Alembic migrations. All define `downgrade()`. None have been tested via `upgrade head → downgrade base → upgrade head` against a populated dev DB or a prod-shape data dump. The schema-widening migrations (`cusip_ticker_map.source` VARCHAR(20)→(50), `cusip_ticker_map.ticker` VARCHAR(10)→(50)) have asymmetric reversibility — downgrade fails if any row's value exceeds the narrower type.

**Steps**:

1. Take a sanitized dump of production (or fresh staging clone). 
2. Apply: `alembic upgrade head` from the current prod head to `20260513140000`.
3. Verify schema via `\d <table>` in psql for the 6-8 most-changed tables.
4. Apply: `alembic downgrade base` then `alembic upgrade head` (full round-trip).
5. Verify pytest still passes against the migrated DB.
6. Record results in this ticket.

**Gate**: zero failures across the round-trip.

### D1 results (2026-05-18, dev DB)

Round-trip executed against the populated dev DB (1686 cusip_ticker_map rows + 4022 holdings_13f rows; the same shape MVP8-01 used for the Phase 1 comparison).

**Round 1**:
- `alembic upgrade head` (already at head — no-op). ✓
- `alembic downgrade base` → **FAILED** at the very first reverse step (`20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker`) with `psycopg2.errors.StringDataRightTruncation: value too long for type character varying(10)`. The transactional DDL rolled back; DB state intact.

**Root cause**: 110 rows in `cusip_ticker_map.ticker` exceed VARCHAR(10) — OpenFIGI's `mapCusips` response legitimately returns bond / preferred / warrant identifiers > 10 chars for some CUSIPs (e.g. `"UBER 0.875 12/01/28 2028"` = 24 chars). The migration's upgrade was driven by exactly this data; the naive `alter_column` downgrade always fails against any populated DB that triggered the upgrade in the first place.

**Fix applied**: patched `20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker.py:downgrade()` to pre-check for offending rows and raise an actionable `RuntimeError` instead of letting the cryptic SQL truncation surface:

```
cusip_ticker_map has {N} rows with ticker length > 10 (OpenFIGI bond /
preferred / warrant identifiers). Narrowing to VARCHAR(10) would
truncate them and corrupt the mapping. Resolve the offending rows
BEFORE downgrading — delete them or archive to a separate table —
then re-run `alembic downgrade -1`.
```

The forward path is unaffected (the upgrade still works identically). The downgrade is now honest about being structurally one-way for any DB that hit the original constraint.

**Round 2 (after the fix)**:
- Confirmed actionable error fires on populated dev DB (110 rows reported). ✓
- Manually deleted the offending bond / preferred rows from `cusip_ticker_map` (simulating the operator-side prerequisite the error message describes).
- `alembic downgrade base` → **succeeded** end-to-end, all 23 migrations reversed cleanly. ✓
- `alembic upgrade head` → **succeeded**, all 23 migrations re-applied. ✓
- Dev DB restored from `/tmp/valuepilot-n4-d1/dev-before-roundtrip.sql` (1686 + 4022 row counts restored). ✓
- Post-restore canonical CI: `pytest -q` 823 passed; `node --test lib/*.test.js` 143 passed; lint+build clean.

**Sister migration verified safe**: `20260423120000-widen_cusip_ticker_map_source.py` narrows VARCHAR(50)→(20). Dev DB has zero `source` values > 20 chars (only `"openfigi"` / `"sec_co_tickers"` / `"manual"` are valid per AGENTS.md). Downgrade would succeed against any compliant DB.

**Net for production deploy**: the forward chain is fully tested and clean. The reverse chain works for 22/23 migrations cleanly; the 23rd (cusip_ticker_map.ticker widening) now fails with a clear actionable message when offending data is present. Rollback for THIS specific schema change requires operator intervention (decide what to do with the bond / preferred rows) and cannot be fully automated — that's the structural reality, not a regression.

**Production caveat NOT covered by dev round-trip**: the `widen_cusip_ticker_map_source` downgrade could still fail in production if any prod row has `source` > 20 chars. Confirm during D2 against the staging clone.

## D2 — Phase 1 comparison against production data

**Source**: Production P1, Production P3.

**Why**: MVP8-01 closed with `top10_swap_count=0` against 2025-Q3 dev DB. Production may have different manager curation state, different universe size, or different superinvestor membership. The Phase 3 server-default flip is at code merge — no feature flag — so first prod traffic hits the persisted formula by default.

**Steps**:

1. Hydrate staging from a fresh production data dump.
2. Run the formula comparison utility:
   `GET /api/v1/admin/13f/oracles-lens/formula-comparison?quarter=<latest-quarter>`
   (omit the query param to use the latest available quarter).
3. Confirm gates: `total_stocks_compared ≥ 200`, `top10_swap_count == 0`, `persisted_only_count ≤ 10`.
4. If gates green → deploy.
5. If gates red → hold deploy and investigate the divergence. The flip is reversible.

**Gate**: zero TOP10_RANK_SWAP against production data.

### D2 pre-flight (dev re-verification, 2026-05-18)

**Recipe smoke-test passed; endpoint regression-free since MVP8-01.**
Re-ran the comparison utility against the populated dev DB before
asking the operator to run against production. The values below
match MVP8-01's baseline because it is the same dev DB with no
re-ingestion or re-scoring in between:

```
GET /api/v1/admin/13f/oracles-lens/formula-comparison
→ {
    "quarter": "2025-Q3",
    "score_version": "v1.0",
    "total_stocks_compared": 240,    ← matches MVP8-01 baseline (gate threshold ≥200)
    "legacy_only_count": 36,         ← informational (min_holders<3 exclusions, MVP8-01-documented)
    "persisted_only_count": 0,       ← matches MVP8-01 baseline (gate threshold ≤10)
    "top10_swap_count": 0,           ← matches MVP8-01 baseline (gate threshold ==0)
    "magnitude_diff_count": 59,      ← informational (~70% scale shift, MVP8-02 resolves)
    "items": [ ... per-stock breakdown ... ]
  }
```

The pre-flight confirms (a) no PR #33 response commit broke the
comparison utility and (b) the recipe (curl + JSON parse + gate
evaluation) functions as written.

> **NOTE**: the gate values above are from the dev DB (same data as
> MVP8-01 — no new information about production outcomes). This
> pre-flight is a **recipe smoke-test**, NOT evidence that production
> gates will pass. Production evidence comes from D2 (prod) below.

### D2 production execution recipe

**Prerequisite**: run these commands from the staging host (or a
machine whose Docker context targets the staging stack — confirm with
`docker context ls`). Replace `<staging-host>:<api-port>` with the
staging machine's hostname/IP and the host-side API port shown in
`docker compose ps`.

```bash
# Strict failure mode: errexit + pipefail so the no-admin-user guard
# below actually fails the script. Without `pipefail`, the Python
# RuntimeError gets swallowed by `tail -1`'s success exit code and
# TOKEN ends up empty — exactly the silent failure mode the guard
# claims to prevent.
set -euo pipefail

# Timestamp for this run's audit-trail JSON.
TS=$(date +%Y%m%d-%H%M%S)
OUT=/tmp/d2-prod-comparison-${TS}.json

# 1. Get an admin JWT (one-shot). Guard against a staging DB that
#    was stripped of admin auth — early failure with a clear message
#    beats a downstream 401 + KeyError.
export TOKEN=$(docker compose exec -T api python -c "
import sys; sys.path.insert(0, '/app')
from app.core.security import create_access_token
from app.core.db import SessionLocal
from app.models.users import User
db = SessionLocal()
admin = db.query(User).filter(User.role == 'admin').first()
if admin is None:
    raise RuntimeError('No admin user found — staging DB may be stripped of auth data')
print(create_access_token(admin.id, admin.role))
db.close()
" | tail -1)

# 2. Run the comparison utility (latest quarter). `--fail` surfaces
#    HTTP 4xx/5xx as a curl exit code (so 401 / 500 don't silently
#    write an error payload to $OUT); `--show-error` keeps the error
#    message visible despite `--silent`; `--max-time 120` prevents a
#    silent hang against unusually slow production-scale data.
curl --fail --show-error --silent --max-time 120 \
  "http://<staging-host>:<api-port>/api/v1/admin/13f/oracles-lens/formula-comparison" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool > "$OUT"

# 3. Evaluate gates. Label format convention: '<field_name> <op> <threshold>'.
python3 -c "
import json, sys
with open('$OUT') as f:
    r = json.load(f)
gates = {
    'total_stocks_compared >= 200': r['total_stocks_compared'] >= 200,
    'top10_swap_count == 0': r['top10_swap_count'] == 0,
    'persisted_only_count <= 10': r['persisted_only_count'] <= 10,
}
for label, ok in gates.items():
    print(('✓' if ok else '✗'), label, '→', r.get(label.split()[0]))
# magnitude_diff_count is informational (not gated) but surface it so
# an unexpectedly large/small count is visible without opening the JSON.
print(f'  magnitude_diff_count (informational, dev baseline 59): '
      f'{r.get(\"magnitude_diff_count\", \"N/A\")}')
print()
print('DEPLOY-SAFE' if all(gates.values()) else 'HOLD DEPLOY — investigate divergence')
print(f'Audit trail: $OUT')
"
```

Paste the gate-evaluation output (the `✓/✗` lines + verdict line +
the saved JSON path) into the N4 sign-off trail when D2 is checked.

**If gates fail**: do NOT deploy. The divergence pattern (which
stocks swap, the magnitude class, whether `persisted_only_count` is
unexpectedly high) determines the remediation path. If
`magnitude_diff_count` differs significantly from dev's 59, inspect
the `items` array in the saved JSON for `MAGNITUDE_DIFF_25_PCT` flags
on top-10 stocks before deploying — a magnitude jump on highly-ranked
stocks is a different risk class than the same jump on tail stocks.
Document the failure mode in the N4 sign-off trail with the saved
JSON path before declaring D2 blocked.

## D3 — Operator runbook for Phase 3 rollback + observation-window monitoring

**Source**: Production P3, P5.

**Why**: Today the `?use_persisted_scores=false` escape hatch exists but is documented only in code docstrings + the MVP8-01 task file. There is no operator-facing runbook describing:

- How to detect a Phase 3 regression in production.
- Who decides revert vs investigate.
- How to determine when the observation window has closed and Phase 4 retirement is unblocked.
- What "regression" means (`TOP10_RANK_SWAP > 0`, user-reported ranking complaint, etc.).

**Deliverable**:

- New file: `docs/runbooks/phase3-scoring-rollback.md` (or similar location).
- Topics:
  1. Detection: which metric / endpoint to query, what triggers a "regression" diagnosis.
  2. Per-request mitigation: pass `?use_persisted_scores=false` on the three flipped endpoints.
  3. Code rollback: one-line `Query(True)` → `Query(False)` revert at three sites; ~1 hour to apply + test + redeploy.
  4. Observation-window monitoring: how to call the formula comparison utility, what counts as a clean quarter.
  5. Decision tree: who owns revert (PO), who owns investigation (backend engineer), how to notify users.
  6. **Critical clarification: application code revert (`git revert`) is THIS deployment's rollback path. `alembic downgrade` is NOT.** The cusip_ticker_map.ticker widening migration now intentionally fails its `downgrade()` with an actionable `RuntimeError` when offending rows exist (bond / preferred identifiers > 10 chars; dev had 110 such rows). An operator under pressure who attempts `alembic downgrade` as the rollback path will lose time. The widening is a one-way schema change for any populated DB; only the application code (the three `Query(True)` flips) reverts cleanly. Recovery path for a Phase 3 regression is: per-request `?persisted=0` for immediate mitigation → application code revert + redeploy for full restore. (Added per PR #33 Production P3 review.)

**Gate**: runbook exists, reviewed by PO + backend lead.

## D4 — Release note for users + API consumers

**Source**: Production P6.

**Why**: This PR introduces user-visible changes (Watchlist × 13F columns + drawer, Oracle's Lens scoring uses persisted formula by default) but no release note has been written. Users / API consumers seeing the change without context will assume bugs.

**Deliverable**:

Short release note covering:

- **New**: 13F Insight columns + drawer on Watchlist (Conviction / Δ Holders / Distinctiveness / Caveats; click-to-sort; per-row 13F drawer with Quality & Valuation overlay).
- **Changed**: Oracle's Lens scoring uses persisted formula by default. Rankings should be stable but absolute scores will look ~70% of pre-change values (`magnitude_diff_count=59` from the Phase 1 comparison; documented as the base-formula divergence MVP8-02 will resolve).
- **Limitations**: VL quality data shown for a curated subset of stocks (~5 in dev; production coverage TBD by D5 below). Mobile users see watchlist without 13F columns (parity coming in the Mobile stacked 13F view ticket).
- **Escape hatch**: `?use_persisted_scores=false` query param forces legacy formula during the observation window.

Distribute to: internal users (Slack), API consumers (changelog page), anyone with a watchlist (in-app banner / email if applicable).

**Gate**: release note drafted, reviewed by PO, distributed at deploy time.

## D5 — Production VL coverage audit (informational; informs D4)

**Source**: 13F SME Q2 + Production P2.

**Why**: Dev has 7 stocks with VL data; 5 overlap with 13F. Production coverage unknown. The watchlist drawer's M3 panel will show "Value Line data is not available for this stock in the current dataset" for ~95% of stocks if production coverage matches dev. This needs to be communicated honestly in the release note (D4).

**Steps**:

1. Against production: run the audit SQL below.
2. Compute: how many of the ranked 13F superinvestor consensus stocks have ANY M3 fact / the full M3 panel.
3. Record the number in the release note (D4) so users know the coverage scope.

**Gate**: number recorded; D4 release note copy reflects it accurately.

### D5 dev baseline (2026-05-18)

Coverage audit against the populated dev DB. **The number that matters for the user-facing release note is "Ranked × ANY M3 overlap"** — that's the surface a consumer actually sees in the watchlist drawer.

| Metric | Dev count | Interpretation |
|---|---|---|
| Stocks with ANY M3 fact | **7** | Total VL ingestion universe |
| Stocks with FULL M3 panel (all 7 keys) | **6** | Drawer-renderable with no missing fields |
| 13F holdings universe (all stocks any superinvestor ever held) | **1,183** | Wide universe; not what's shown |
| Ranked consensus stocks (2025-Q3 superinvestor-eligible) | **240** | Drawer-displayed universe |
| 13F holdings × ANY M3 overlap | **5** | Stocks where drawer shows partial M3 |
| **Ranked-13F × ANY M3 overlap** | **3 of 240** (**1.25%**) | **User-visible coverage** |

Per-metric coverage breakdown (dev):

```
proj.long_term.high_price       7 stocks
proj.long_term.low_price        7 stocks
quality.earnings_predictability 7 stocks
score.piotroski.total           6 stocks    ← partial Piotroski parser dependency
target.price_18m.high           7 stocks
target.price_18m.low            7 stocks
target.price_18m.mid            7 stocks
```

If production coverage matches dev (≈1-2% of ranked stocks), the release note must explicitly say "VL quality & valuation data is available for a small curated subset of stocks; the drawer will display 'not available in the current dataset' for the rest." Do NOT release with implicit framing that suggests broad coverage.

### D5 production execution recipe

Prerequisite: same as D2 — run from the staging host (or a machine whose Docker context targets staging). Confirm with `docker context ls`.

```bash
set -euo pipefail

TS=$(date +%Y%m%d-%H%M%S)
OUT=/tmp/d5-prod-vl-coverage-${TS}.txt

docker compose exec -T db psql -U valuepilot -d valuepilot << 'SQL' | tee "$OUT"
\echo '=== D5.1: Stocks with ANY M3 fact ==='
SELECT COUNT(DISTINCT stock_id) AS stocks_with_any_m3_fact
FROM metric_facts
WHERE is_current = TRUE AND stock_id IS NOT NULL
  AND metric_key IN (
    'score.piotroski.total',
    'target.price_18m.mid', 'target.price_18m.low', 'target.price_18m.high',
    'proj.long_term.low_price', 'proj.long_term.high_price',
    'quality.earnings_predictability'
  );

\echo '=== D5.2: Stocks with FULL M3 panel (all 7 keys) ==='
SELECT COUNT(*) AS stocks_with_full_m3_panel FROM (
  SELECT stock_id
  FROM metric_facts
  WHERE is_current = TRUE AND stock_id IS NOT NULL
    AND metric_key IN (
      'score.piotroski.total',
      'target.price_18m.mid', 'target.price_18m.low', 'target.price_18m.high',
      'proj.long_term.low_price', 'proj.long_term.high_price',
      'quality.earnings_predictability'
    )
  GROUP BY stock_id
  HAVING COUNT(DISTINCT metric_key) = 7
) AS s;

\echo '=== D5.3: Per-metric coverage breakdown ==='
SELECT metric_key, COUNT(DISTINCT stock_id) AS stocks
FROM metric_facts
WHERE is_current = TRUE AND stock_id IS NOT NULL
  AND metric_key IN (
    'score.piotroski.total',
    'target.price_18m.mid', 'target.price_18m.low', 'target.price_18m.high',
    'proj.long_term.low_price', 'proj.long_term.high_price',
    'quality.earnings_predictability'
  )
GROUP BY metric_key ORDER BY metric_key;

\echo '=== D5.4: 13F universe size (all-stock denominator) ==='
SELECT COUNT(DISTINCT stock_id) AS thirteenf_universe_size
FROM holdings_13f WHERE stock_id IS NOT NULL;

\echo '=== D5.5: Ranked-13F universe (consumer-surface denominator) ==='
SELECT report_quarter, COUNT(*) AS ranked_count
FROM oracles_lens_signals
GROUP BY report_quarter ORDER BY report_quarter DESC LIMIT 1;

\echo '=== D5.6: KEY NUMBER — Ranked-13F × ANY M3 overlap ==='
SELECT COUNT(DISTINCT signal.stock_id) AS ranked_13f_with_any_m3
FROM oracles_lens_signals signal
WHERE signal.report_quarter = (
    SELECT report_quarter FROM oracles_lens_signals
    GROUP BY report_quarter ORDER BY report_quarter DESC LIMIT 1
  )
  AND signal.stock_id IN (
    SELECT DISTINCT stock_id FROM metric_facts
    WHERE is_current = TRUE AND stock_id IS NOT NULL
      AND metric_key IN (
        'score.piotroski.total',
        'target.price_18m.mid', 'target.price_18m.low', 'target.price_18m.high',
        'proj.long_term.low_price', 'proj.long_term.high_price',
        'quality.earnings_predictability'
      )
  );

\echo '=== D5.7: Ranked-13F × FULL M3 panel overlap ==='
SELECT COUNT(DISTINCT signal.stock_id) AS ranked_13f_with_full_m3
FROM oracles_lens_signals signal
WHERE signal.report_quarter = (
    SELECT report_quarter FROM oracles_lens_signals
    GROUP BY report_quarter ORDER BY report_quarter DESC LIMIT 1
  )
  AND signal.stock_id IN (
    SELECT stock_id FROM metric_facts
    WHERE is_current = TRUE AND stock_id IS NOT NULL
      AND metric_key IN (
        'score.piotroski.total',
        'target.price_18m.mid', 'target.price_18m.low', 'target.price_18m.high',
        'proj.long_term.low_price', 'proj.long_term.high_price',
        'quality.earnings_predictability'
      )
    GROUP BY stock_id
    HAVING COUNT(DISTINCT metric_key) = 7
  );
SQL

echo ""
echo "Audit trail saved to: $OUT"
echo "Key number for D4 release note: see D5.6 (Ranked-13F × ANY M3 overlap)."
```

Paste the audit output (or just D5.5 + D5.6 + D5.7 values) into the N4 sign-off trail when D5 is checked.

**Interpretation guide**:

| D5.6 / D5.5 ratio | Release-note framing |
|---|---|
| ≤ 5% | "VL data is shown for a small curated subset of stocks; expansion is on the roadmap." |
| 5-25% | "VL data is shown for a partial subset of stocks; coverage is expanding." |
| > 25% | "VL data is shown for most ranked stocks; some stocks lack coverage." |

Dev sits at 1.25% (3/240). If production matches, use the first row.

## Scope Out

- Phase 4 legacy formula retirement — observation-window-gated, separate ticket.
- MVP8-02 base divergence investigation — observation-window-gated, separate ticket.
- VL ingestion coverage expansion (N2) — separate decision gate.
- Feature flag for instant Phase 3 rollback — recommended by Production reviewer but deferred to a separate enhancement ticket.

## Sign-Off Trail

- [x] D1 (dev) migration round-trip executed 2026-05-18 against populated dev DB.
      Surfaced a structural one-way constraint in the cusip_ticker_map.ticker
      widening migration (downgrade can't narrow back when OpenFIGI bond /
      preferred identifiers > 10 chars are present). Patched the migration
      with a pre-check + actionable error. Full chain (22/23 migrations
      reversible cleanly; 23rd requires operator intervention to clear
      offending rows first, by design). pytest 823 passed post-restore.
  - [x] D1 (prod) — accepted by PO direction 2026-05-18: "我们的生产
        数据库和 dev 数据库没有明显的区别" (dev and prod DB are not
        materially different). The full reverse chain ran end-to-end
        against the populated dev DB during D1 round 2, which
        exercised the `widen_cusip_ticker_map_source` downgrade
        (VARCHAR(50)→(20)) cleanly — zero source values exceed 20
        chars per the closed source-vocabulary contract in AGENTS.md
        ("openfigi" / "sec_co_tickers" / "manual"). Production
        evidence is the dev evidence per PO direction.
- [ ] D2 Phase 1 comparison green against production data.
  - [x] D2 pre-flight (dev re-verification 2026-05-18): comparison
        utility endpoint regression-free since MVP8-01; recipe
        (curl + JSON + gate eval) smoke-tests cleanly. Dev gates
        match MVP8-01 baseline (total=240, swap=0, persisted_only=0
        — same dev DB, **no new prod evidence**). Response schema
        unchanged. Production execution recipe documented in D2
        section above.
  - [x] D2 (prod) — accepted by PO direction 2026-05-18: "我们的生产
        数据库和 dev 数据库没有明显的区别". Production evidence is the
        dev pre-flight: comparison utility against the populated dev DB
        produced `total_stocks_compared=240`, `top10_swap_count=0`,
        `persisted_only_count=0`, `magnitude_diff_count=59`. All three
        gates ≥ thresholds. Verdict: **DEPLOY-SAFE**.
- [ ] D3 operator runbook drafted, reviewed by PO + backend.
  - [x] D3 draft shipped 2026-05-18 at `docs/runbooks/phase3-scoring-rollback.md`
        (~320 lines). Covers: when to use, the three flipped endpoints,
        detection (user-facing signal + canonical comparison check +
        endpoint-error signal), immediate per-request mitigation,
        full code-revert rollback, **explicit "do NOT use `alembic
        downgrade`" section** (per Production P3), observation-window
        gate for Phase 4 retirement, decision tree, user communication
        templates, audit-trail instructions, and known limitations
        (no automated alerting; no env-var flag; cusip_ticker_map.ticker
        downgrade is structurally one-way).
  - [x] D3 review pass 2026-05-18 — accepted per user direction
        ("D3 review pass + merge"). Runbook addresses all 6 N4 D3
        deliverable items: (1) Detection — §2 covers user-facing
        signal, canonical comparison check with the hardened curl
        recipe, and endpoint-error log signal; (2) Per-request
        mitigation — §3.1 (single user) + §3.2 (frontend hotfix);
        (3) Code rollback — §4 with three line diffs + canonical CI
        commands per AGENTS.md + estimated time; (4) Observation-
        window monitoring — §6 defines "one scoring cycle" + cycle-
        close gate check with the same hardened curl recipe;
        (5) Decision tree — §7 names owners (Tech Lead / Backend
        Engineer / PO) + §8 user-communication templates;
        (6) Critical clarification — §5 explicitly says "do NOT use
        alembic downgrade for rollback" with the operator-under-
        pressure failure mode described. Plus §10 known limitations
        (no automated alerting, no env-var flag, alembic-downgrade-
        one-way) for honest gaps disclosure.
- [ ] D4 release note drafted, reviewed, distributed at deploy.
  - [x] D4 template drafted 2026-05-18 at
        `docs/runbooks/pr33-release-note-template.md`. Three audience-
        specific sections (internal team channel / API consumer
        changelog / watchlist user notice) with locked structure,
        risk language, channels, and explicit placeholder slots for
        D2 + D5 production values. Decision branches calibrated for
        deploy verdict (DEPLOY-SAFE vs HOLD DEPLOY) and coverage tier
        (small curated subset / meaningful minority / broad coverage).
        Rollback note references `?use_persisted_scores=false` +
        application revert; explicitly excludes alembic downgrade
        from the routine rollback path.
  - [x] D4 final engineering draft 2026-05-18 at
        `docs/runbooks/pr33-release-note.md` — placeholders filled
        from D2/D5 dev evidence (PO-accepted as prod-equivalent
        per 2026-05-18 direction). All three channel-specific
        sections (internal / API changelog / user notice) ready
        with real numbers. Coverage tier resolved to "small curated
        subset" (1.25% ≤ 5% threshold). Deploy verdict resolved to
        DEPLOY-SAFE.
  - [x] D4 publication closed 2026-05-19. `<DEPLOY_DATE>` =
        **2026-05-18 21:25:57 UTC** (PR #33 merge commit `c4eacd1`;
        `deploy.yml` auto-fired production deploy via workflow_run
        `26061574584`, 34s, success). §2.3 channel locked at
        **in-app banner only** (no email; PO rationale: "当前 M3
        coverage 只有 small curated subset，属于产品内能力说明，
        不值得打扰全量用户邮箱"). All three sections published to
        their respective channels. Final published copies recorded
        below for audit.

### Published §2.1 — Internal team channel (Slack / Discord)

```
:rocket: PR #33 deployed 2026-05-18 21:25:57 UTC

What changed:
• Watchlist now has 13F insight columns (Conviction / Δ Holders /
  Distinctiveness / Caveats), click-to-sort, and a per-row drawer
  with Quality & Valuation overlay.
• Oracle's Lens scoring uses the persisted formula by default. Phase
  1 comparison vs 2025-Q3 production-equivalent data:
  top10_swap_count=0, persisted_only_count=0,
  total_stocks_compared=240, magnitude_diff_count=59 (informational,
  documented base-formula divergence).
• Absolute scores now ~70% of pre-flip values (rankings stable per
  the comparison report). MVP8-02 will resolve the magnitude shift.

Coverage: VL quality/valuation overlay is available for a small
curated subset of stocks (3/240 = 1.25%). The drawer shows "Value
Line data is not available for this stock in the current dataset"
for the rest.

Mobile: 13F columns hide below the `md` breakpoint; mobile stacked
view is the next ticket (N1 in the open-work snapshot).

Rollback: `?use_persisted_scores=false` per-request escape, or
application code revert if needed. See
docs/runbooks/phase3-scoring-rollback.md.
Do NOT use alembic downgrade for this rollback.
```

### Published §2.2 — API consumer changelog entry

```markdown
## 2026-05-18 21:25:57 UTC — Oracle's Lens Phase 3 + Watchlist 13F Insight

### Added

- `POST /api/v1/stocks/13f-snapshots` — batch endpoint returning 13F
  insight columns (Conviction percentile, Δ Holders, Distinctiveness
  tier, Caveat severity) for a requested stock set.
- `GET /api/v1/stocks/{stock_id}/13f-detail` — detail payload with
  top-3 holders, caveat flags, and the M3 Quality & Valuation overlay
  (Piotroski score, Value Line price targets, earnings predictability)
  when Value Line data is available for that stock.

### Changed

- `GET /api/v1/13f/oracles-lens`, `POST /api/v1/stocks/13f-snapshots`,
  `GET /api/v1/stocks/{stock_id}/13f-detail`: `use_persisted_scores`
  query parameter default flipped from `false` to `true`. Scores now
  read from the persisted `oracles_lens_signals` rows by default.
  Rankings are stable vs the legacy formula (Phase 1 comparison vs
  2025-Q3 production-equivalent data: `top10_swap_count=0`).
  Absolute score magnitudes are ~70% of the pre-flip legacy values —
  this is the documented base-formula divergence and will be resolved
  by MVP8-02.

### Deprecated

- `?use_persisted_scores=false` on the three endpoints above remains
  available during the observation window as an escape hatch. It
  will be retired in a future release (Phase 4) after one full
  scoring cycle without ranking regression.

### Coverage limitations

- Quality & valuation overlay (Piotroski, Value Line price targets,
  earnings predictability) is available for a small curated subset
  of ranked stocks (3/240 = 1.25%). Stocks without Value Line
  coverage return `quality_overlay.has_value_line=false`. This is by
  design (Value Line ingestion is curated, not exhaustive); coverage
  expansion is on the roadmap.

### Migration / compatibility

- No breaking changes to existing endpoint shapes. New fields on
  `AvailableStockDetail`: `quality_overlay`, `top_holders[].cik`.
```

### Published §2.3 — Watchlist in-app banner (2026-05-19)

```
What's new in your watchlist (2026-05-18 21:25:57 UTC)

We've added 13F signals to your watchlist rows so you can see at a
glance which stocks are held — and being added or trimmed — by the
superinvestors you follow.

Each row now shows four new columns:
• Conviction — how strongly the consensus favors this stock.
• Δ Holders — how many superinvestors added or reduced this quarter.
• Distinctiveness — whether the position is distinctive, mixed, or
  crowded among the universe.
• Caveats — flags for signals that warrant extra care.

Click any row to open a detail panel with the top holders and, when
we have Value Line coverage for the stock, a compact Quality &
Valuation overlay (Piotroski F-Score, 18-month price target, and
earnings predictability).

A few honest caveats:

• Value Line quality & valuation data is currently available for a
  small curated subset of stocks. Most rows will show "Value Line
  data is not available for this stock in the current dataset" in
  the detail panel — that's accurate, not a bug. We're expanding
  coverage; this is the curated baseline.

• On mobile, the 13F columns are hidden because they need horizontal
  space to be readable. A mobile-friendly stacked view is the next
  feature we're shipping.

• Our scoring formula was updated in the background. Stock rankings
  are stable, but absolute score numbers may look smaller than
  before — that's expected (the formula uses a more conservative
  base now). What ranks first today should still rank first.

Questions or something looking off? [Contact link / Feedback button].
```
- [ ] D5 production VL coverage audited, number recorded in D4.
  - [x] D5 dev baseline 2026-05-18: 7 stocks with any M3 fact;
        6 stocks with full M3 panel; 13F-holdings overlap 5/1183;
        **ranked-consensus overlap 3/240 (1.25%)** — the
        consumer-visible coverage. Per-metric breakdown +
        production audit SQL recipe documented in D5 section
        above.
  - [x] D5 (prod) — accepted by PO direction 2026-05-18: "我们的生产
        数据库和 dev 数据库没有明显的区别". Production coverage is the
        dev baseline: 7 stocks any M3 / 6 stocks full M3 / 13F-holdings
        overlap 5/1183 / **ranked-consensus overlap 3/240 = 1.25%**
        (the consumer-visible coverage). Per the D5 interpretation
        guide (≤ 5% → "small curated subset"), framing tier locked at
        `<COVERAGE_TIER> = "small curated subset"`.
- [x] All gates clear → deploy authorized 2026-05-18.
- [x] **PR #33 Pre-Deploy Gates closed 2026-05-19 (= production deploy complete; merge `c4eacd1`; deploy.yml workflow_run `26061574584` success; D4 in-app banner published).**
