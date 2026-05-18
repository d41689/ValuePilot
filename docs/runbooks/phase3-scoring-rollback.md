# Phase 3 Scoring Rollback + Observation Runbook

**Owner**: Tech Lead (rollback decisions); Backend Engineer (investigation); PO (deploy direction + user comms).
**Scope**: Oracle's Lens scoring path after MVP8-01 Phase 3 flipped `use_persisted_scores` server default from `False` to `True`.
**Background context**: `docs/tasks/2026-05-13_mvp8-01-mvp5-03-phase3-flip.md` (the flip), `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` (deploy gates), `docs/tasks/2026-05-13_metric-facts-current-semantics-decision-gate.md` (related contract).

---

## 0. When to use this runbook

Use this runbook when **any** of these signals appear in production:

- A user reports that a stock's Oracle's Lens ranking or score has changed unexpectedly since the Phase 3 deploy.
- The formula-comparison utility (`/api/v1/admin/13f/oracles-lens/formula-comparison`) returns `top10_swap_count > 0` against a current-quarter run.
- A `/api/v1/13f/oracles-lens`, `/api/v1/stocks/13f-snapshots`, or `/api/v1/stocks/{id}/13f-detail` endpoint returns a 5xx or schema-mismatch error that started after the Phase 3 merge.
- Persisted scoring data appears inconsistent (e.g., `oracles_lens_signals.score_confidence` produces ValidationError at the watchlist API; see `_normalize_score_confidence` shim).

Do NOT use this runbook for:
- General 13F ingestion errors (those have their own pipeline; see admin operations console).
- Frontend rendering bugs (those don't touch the scoring path).
- Migration rollback (see §5 — this runbook explicitly does NOT use `alembic downgrade`).

---

## 1. What Phase 3 changed

Three API endpoints had their `use_persisted_scores` query-param default flipped from `False` to `True`:

| Endpoint | File | Line |
|---|---|---|
| `GET /api/v1/13f/oracles-lens` | `backend/app/api/v1/endpoints/oracles_lens.py` | ~23 |
| `POST /api/v1/stocks/13f-snapshots` | `backend/app/api/v1/endpoints/stocks_13f.py` | ~270 |
| `GET /api/v1/stocks/{stock_id}/13f-detail` | `backend/app/api/v1/endpoints/stocks_13f.py` | ~481 |

Each is `use_persisted_scores: bool = Query(True, ...)`. Pre-Phase-3 it was `Query(False, ...)`.

**Functional impact**: before the flip, scores came from the legacy in-memory formula in `_stock_payload` (`dashboard.py`); after the flip, scores come from persisted `oracles_lens_signals` rows. Rankings should be stable per MVP8-01's comparison report (`top10_swap_count=0` against 2025-Q3); absolute score magnitudes will look ~70% of pre-flip values (the base-formula divergence documented for MVP8-02).

**Escape hatch**: the query param is still exposed. Adding `?use_persisted_scores=false` to any of the three endpoints forces the legacy formula for that one request.

---

## 2. Detection

### 2.1 User-facing signal

A user opens `/13f/oracles-lens` (the admin dashboard) or `/watchlist` (the consumer surface) and reports:
- "Stock X used to be in the top 10 and now it's not."
- "All scores look smaller than before."
- "The drawer says 'unavailable' for a stock that used to have data."

The first signal is the **critical case** — ranking divergence is what MVP8-01's `top10_swap_count == 0` gate exists to prevent.

The second signal is **expected** and not a regression — absolute magnitudes are ~70% of pre-flip values (MVP8-02 base divergence). Reassure the user; do not roll back.

The third signal is likely a separate `min_holders < 3` issue (legacy_only_count rows from the comparison report); see §2.3.

### 2.2 Canonical comparison check

```bash
# Mint admin JWT
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

# Run the comparison (latest quarter)
curl --fail --show-error --silent --max-time 120 \
  "http://<prod-host>:<api-port>/api/v1/admin/13f/oracles-lens/formula-comparison" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Gate interpretation**:

| Field | Pass | Fail / investigate |
|---|---|---|
| `top10_swap_count` | `== 0` | `> 0` → **REGRESSION**, proceed to §3 |
| `total_stocks_compared` | `>= 200` | `< 200` → universe too small to evaluate; check ingestion before declaring regression |
| `persisted_only_count` | `<= 10` | `> 10` → meaningful universe divergence; investigate which stocks |
| `legacy_only_count` | (informational) | High count → mostly stocks with < 3 holders correctly excluded by `min_holders=3`; check before alarm |
| `magnitude_diff_count` | (informational) | Dev baseline 59; significant deviation = inspect `items` array for `MAGNITUDE_DIFF_25_PCT` flags on top-10 stocks |

### 2.3 Endpoint-error signal

```bash
# Tail the api container's log
docker compose logs -f api | grep -E "ERROR|ValidationError|5[0-9][0-9]"
```

Specifically watch for:
- `pydantic_core._pydantic_core.ValidationError` in the `score_confidence` path (Literal `"high"|"medium"|"low"` clashing with persisted `"high_confidence"|...`). The `_normalize_score_confidence` shim should catch this; if it doesn't, that's a real bug, not a Phase 3 issue.
- `KeyError` on `OraclesLensSignal` row lookups (stock has 13F data but no persisted score row — usually means scoring hasn't run for the current quarter).

---

## 3. Immediate mitigation (per-request)

The flip is reversible per request via the `?use_persisted_scores=false` query parameter.

### 3.1 Single-user mitigation

Tell the user (or paste into the user's request URL): append `?use_persisted_scores=false` to whichever endpoint URL is producing the wrong ranking. Examples:

```
GET /api/v1/13f/oracles-lens?use_persisted_scores=false
POST /api/v1/stocks/13f-snapshots                    {... body ...}    # add ?use_persisted_scores=false to URL
GET /api/v1/stocks/123/13f-detail?use_persisted_scores=false
```

This forces the legacy in-memory formula for that one request. No deploy required.

### 3.2 Frontend-wide mitigation

If the regression affects many users (e.g., the admin dashboard at `/13f/oracles-lens` is wrong for everyone), patch `frontend/lib/oraclesLens.js` (or the calling component) to hardcode `use_persisted_scores=false` in the query string. This is a temporary frontend hotfix; the proper full rollback is §4.

Estimated time: ~30 minutes to patch + frontend deploy.

---

## 4. Full rollback (code revert)

If §3 mitigation is insufficient (regression hits many endpoints or many user surfaces simultaneously), revert the three default-flip sites.

### 4.1 What to revert

Three lines, in two files:

```diff
# backend/app/api/v1/endpoints/oracles_lens.py (~line 23)
-    use_persisted_scores: bool = Query(True, ...),
+    use_persisted_scores: bool = Query(False, ...),

# backend/app/api/v1/endpoints/stocks_13f.py (~line 270, /stocks/13f-snapshots)
-    use_persisted_scores: bool = Query(True, ...),
+    use_persisted_scores: bool = Query(False, ...),

# backend/app/api/v1/endpoints/stocks_13f.py (~line 481, /stocks/{id}/13f-detail)
-    use_persisted_scores: bool = Query(True, ...),
+    use_persisted_scores: bool = Query(False, ...),
```

The `Query(True, description="...")` block has a multi-line description; the only character that needs to flip is `True` → `False` (and update the description if you want; not required for behavior).

### 4.2 Steps

1. Create a branch from `main`: `git checkout -b hotfix/phase3-rollback`.
2. Apply the three `True` → `False` edits.
3. Run canonical CI commands locally (per AGENTS.md Verification Discipline):
   ```bash
   docker compose exec api pytest -q                              # expect 800+ passed
   docker compose exec web sh -lc 'node --test lib/*.test.js'     # expect 143 passed
   docker compose exec web npm run lint                            # clean
   docker compose exec web npm run build                           # clean
   ```
4. Commit + push + open PR.
5. Merge to `main`. `deploy.yml` auto-fires production deploy on CI success.

**Estimated time**: ~1 hour end-to-end (edit + CI + PR + merge + auto-deploy).

### 4.3 Update communication

After the deploy lands, post a release note (or in-app banner if the user surface was affected) explaining:
- What was reverted (Phase 3 scoring default).
- What users will see (rankings restored to pre-Phase-3 state; magnitudes back to legacy values).
- That investigation is ongoing.

---

## 5. **Critical: do NOT use `alembic downgrade` for rollback**

Phase 3 is a **code change**, not a schema change. The flip from `Query(False)` to `Query(True)` does not touch any Alembic migration. Rolling back Phase 3 requires reverting the application code, not migrating the database.

If an operator under pressure types `alembic downgrade`, they will hit one of two failure modes:

1. **`cusip_ticker_map.ticker` widening downgrade fails** with an explicit `RuntimeError` (the migration's defensive pre-check; see `20260513140000-pre_mvp8_01_widen_cusip_ticker_map_ticker.py`). The message describes how to clear the offending rows BEFORE downgrading — but doing so means deleting production OpenFIGI bond / preferred / warrant mapping rows, which is itself a data-loss event.
2. **Other migrations downgrade silently** but leave the schema in a state inconsistent with the application code currently running on `main`. The next deploy may fail or, worse, succeed with subtly broken behavior.

**The widening was a one-way schema change for any populated production DB. Treat `alembic downgrade` as not available for Phase 3 rollback.** The only rollback path is §4 (revert the three Query defaults + redeploy).

If you ever genuinely need to roll back the cusip_ticker_map.ticker widening itself (rare, separate from Phase 3): coordinate with backend engineering to decide the fate of the offending rows (delete? archive? coerce?) BEFORE running the downgrade.

---

## 6. Observation-window monitoring (when can Phase 4 retire the escape hatch?)

Phase 4 deletes the legacy `_stock_payload` formula in `dashboard.py` AND the `?use_persisted_scores=false` query parameter. It is gated on **one full scoring cycle (post-2025-Q4) with zero `top10_swap_count` and no user-reported regressions**.

### 6.1 What "one scoring cycle" means

A scoring cycle is the cadence at which `oracles_lens_signals` rows are recomputed for a quarter — typically after the SEC 13F filing deadline (period_end + 45 days) when the last superinvestor's filing has landed and been parsed. For 2025-Q4 (deadline 2026-02-14), the cycle completes when all confirmed superinvestor managers have filed and been scored — typically a 2-4 week window post-deadline.

The observation window does not start the day Phase 3 ships; it starts when the **next** complete scoring cycle's signals are computed under the new persisted default.

### 6.2 Cycle-close check

```bash
# Same JWT mint as §2.2

# Run comparison for the next-complete quarter (e.g., 2026-Q1 once its deadline passes)
curl --fail --show-error --silent --max-time 120 \
  "http://<prod-host>:<api-port>/api/v1/admin/13f/oracles-lens/formula-comparison?quarter=2026-Q1" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool > /tmp/phase4-gate-$(date +%Y%m%d).json
```

Phase 4 is unblocked when **all** of these hold for the cycle's comparison:

- `top10_swap_count == 0`
- `persisted_only_count <= 10`
- `total_stocks_compared >= 200`
- No user-reported ranking regression filed against the cycle's quarter in the operational backlog.

If any condition fails, hold Phase 4. Investigate the failure mode and consider whether MVP8-02 (base divergence) work shifts the bar.

### 6.3 Who runs this check?

The Backend Engineer or PO runs the cycle-close check after the relevant quarter's filing deadline + ~2 weeks. There is no automated alarm; this is a manual cadence aligned with SEC filing deadlines.

---

## 7. Decision tree

```
Production user reports unexpected scoring behavior
                       │
                       ▼
        Is it a ranking change (top 10)?
            │                       │
           YES                      NO (magnitude / availability)
            │                       │
            ▼                       ▼
   Run §2.2 comparison         §2.1: explain magnitude shift is expected,
                               or §2.3 if it's an endpoint error.
            │
            ▼
   top10_swap_count > 0?
       │              │
       NO              YES
       │              │
       ▼              ▼
   Look at        Affects 1 user?
   magnitude       │           │
   shift (§2.1)   YES          NO (many users / endpoints)
                   │            │
                   ▼            ▼
              §3.1 per-      §4 full rollback
              request flag   (Tech Lead approves; Backend Engineer
              for the user.  executes; PO writes user comms)
```

**Decision owners**:

- **Tech Lead** decides revert vs investigate after Backend Engineer's initial triage.
- **Backend Engineer** runs the §2.2 comparison and the §4 revert.
- **PO** approves user-visible messaging and signs off on Phase 4 unblock once the observation gate is met.

---

## 8. User communication templates

### 8.1 Per-request mitigation (one user)

> Thanks for the report. While we investigate, you can see the previous scoring by appending `?use_persisted_scores=false` to the URL. Example: `/13f/oracles-lens?use_persisted_scores=false`. We'll follow up once the investigation completes.

### 8.2 Full rollback announcement

> We've temporarily rolled back the [DATE] Oracle's Lens scoring update while we investigate a ranking inconsistency reported by [N] users. Scores and rankings are restored to their pre-[DATE] state. We expect to re-roll forward within [TIMEFRAME] after the investigation completes. The underlying 13F data is unchanged.

### 8.3 Phase 4 retirement announcement (eventual; not a rollback)

> The Oracle's Lens scoring pipeline has been on the new persisted formula since [DATE]. After one full scoring cycle without regression, we've retired the legacy formula and the `?use_persisted_scores=false` debug flag. No user-visible change is expected from this retirement — the persisted formula has been the default for [DURATION].

---

## 9. Audit trail

When this runbook is used (mitigation OR rollback OR cycle-close check):

1. Save the comparison utility's JSON output to `/tmp/<context>-<date>.json` (the recipe in §2.2 / §6.2 does this).
2. Paste the decision and the JSON path into the relevant task file's sign-off trail. For pre-Phase-4-retirement gate evidence, append to `docs/tasks/2026-05-14_pr33-pre-deploy-gates-ticket.md` under the appropriate D# section. For ad-hoc production incidents, file a new task at `docs/tasks/YYYY-MM-DD_phase3-incident-<short>.md`.
3. Notify the team via the standard incident channel (Slack / Discord webhook) if §4 was triggered.

---

## 10. Known limitations

- **No automated alerting**: today's signal is user reports + the manual comparison check. A future enhancement (out of scope here) is to schedule the comparison utility to run after each scoring cycle and post the gate values to the team channel.
- **No environment flag**: the `Query(True/False)` default is in code. A future enhancement is to thread an environment variable (`ORACLES_LENS_DEFAULT_PERSISTED=true|false`) so per-environment rollback doesn't require a code change. Per PR #33 Production P3 review.
- **`alembic downgrade` is one-way for the cusip_ticker_map.ticker widening** — see §5. Not a runbook gap; a structural reality.
