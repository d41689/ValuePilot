# MVP7-01: `/stocks/13f-snapshots` Batch Endpoint

## Status

**Authorized to start (PO 2026-05-13 after Pre-MVP7-01 decision gate).** First
implementation ticket on the MVP7 Watchlist × 13F Insight track.

## Goal / Acceptance Criteria

PRD reference: `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md` D1
+ the "Backend API Contract" section.

Ship a new batch endpoint that returns the four V1 13F-derived
signals (Conviction percentile, Δ Holders, Distinctiveness tier,
Caveat severity) plus context per requested `stock_id` for a given
13F period. The endpoint reuses `build_oracles_lens_dashboard()`
for universe ranking; no new scoring logic.

Acceptance criteria:

- **New endpoint** `POST /api/v1/stocks/13f-snapshots`.
- **Request body**:
  ```json
  {
    "stock_ids": [int, ...],
    "period": "latest" | "YYYY-Qn"   // optional; defaults to "latest"
  }
  ```
- **Response shape**:
  ```json
  {
    "period": "2025-Q4",
    "period_filing_deadline": "2026-02-14",
    "universe_size": 87,
    "snapshots": [
      {
        "stock_id": 123,
        "available": true,
        "conviction_score": 4.32,
        "conviction_percentile": 0.85,
        "delta_holders": 2,
        "adders_count": 3,
        "reducers_count": 1,
        "consensus_count": 7,
        "distinctiveness_tier": "distinctive" | "mixed" | "crowded",
        "caveat_severity": "ok" | "caution" | "high-caution",
        "caveat_codes": ["unknown_manager_type_heavy", ...],
        "score_confidence": "high" | "medium" | "low"
      },
      {
        "stock_id": 456,
        "available": false,
        "unavailable_reason": "below_min_holders" | "no_holders" | "no_qualifying_period"
      }
    ]
  }
  ```
- **Universe-rank percentile**: computed across the full eligible
  set (call `build_oracles_lens_dashboard(..., limit=0)` to disable
  the default top-50 truncation). Percentile = `1.0 - (rank_position - 1) / universe_size`
  where rank is by `conviction_score` desc, ties resolved by
  insertion order (stable rank).
- **Distinctiveness tier derivation** (V1 heuristic from
  Pre-MVP7-01 D1, refinable):
  - `distinctive`: `manager_signal_quality_coverage ≥ 0.7` AND
    `consensus_count ≤ 8`.
  - `crowded`: `consensus_count ≥ 20` AND
    `manager_signal_quality_coverage < 0.5`.
  - `mixed`: everything else.
- **Caveat severity aggregation**: dashboard `_caution_flags`
  emits per-flag `severity` of `"warning"` or `"info"`.
  - `high-caution`: any flag with `severity="warning"`.
  - `caution`: all flags are `severity="info"` (and at least one
    flag exists).
  - `ok`: empty flags list.
- **Unavailable stocks** (not in the eligible set):
  - `available: false, unavailable_reason: "below_min_holders"` —
    stock has 13F holdings but fewer than `min_holders` (default
    3) qualifying ranked managers.
  - `available: false, unavailable_reason: "no_holders"` — stock
    has zero qualifying 13F holdings for the period.
  - `available: false, unavailable_reason: "no_qualifying_period"` —
    the requested period has no qualifying stocks at all (returned
    once at the top, not per-stock).
- **Period filing deadline**: 45 days after `period_end_date`.
  Format `YYYY-MM-DD`. Returned for the group header display in
  MVP7-03.
- **`use_persisted_scores=False`** (default). Per the persisted-scores
  GA-gating rule, the snapshot endpoint reads the in-memory
  dashboard formula until MVP5-03 Phase 3 closes. Frontend code
  must not assume otherwise.

## Scope In

- `backend/app/api/v1/endpoints/stocks_13f.py` (new).
- Register the new router in `backend/app/api/v1/api.py` under the
  `/stocks` prefix.
- `backend/app/schemas/stocks_13f_snapshot.py` (new) — Pydantic
  request + response models.
- New pytest file
  `backend/tests/unit/test_mvp7_01_stocks_13f_snapshots.py` with
  the test coverage listed below.
- This task file.

## Scope Out / Scope Refinements

- **SR0**: No schema migrations. The endpoint computes everything
  on read from existing data.
- **SR1**: No in-memory cache in V1. The Pre-MVP7-01 doc reserved
  a 60s cache "if observed read latency unacceptable" — V1 ships
  uncached and measures. Cache lands as a follow-up only if
  required.
- **SR2**: No new normalizer module on the frontend yet; that
  arrives in MVP7-03. This ticket is backend-only.
- **SR3**: `use_persisted_scores=True` path NOT exposed by the new
  endpoint. The persisted-scoring read path is gated on MVP5-03
  Phase 3 PO sign-off; until that closes, the new endpoint must
  not surface persisted scores even via a query param.
- **SR4**: No drawer / top-holders detail. Pre-MVP7-01 D1 reserved
  top 3 holders + per-manager magnitudes for MVP7-05; this
  endpoint returns only the four column signals plus context.
- **SR5**: Authentication. The endpoint is **public** (no auth)
  in V1 to match the existing `GET /13f/oracles-lens` and
  `GET /stocks/{ticker}/institutions` endpoints. If the
  `/watchlist` consumer is auth-gated at the page level, the
  snapshot endpoint inherits no per-user secrecy; the data
  returned is the same Oracle's Lens public data.

## PRD / Decision References

- `docs/tasks/2026-05-13_pre-mvp7-01-watchlist-13f-insight-decision-gate.md`
  D1 (four columns) + "Backend API Contract".
- `backend/app/services/oracles_lens/dashboard.py` —
  `build_oracles_lens_dashboard`, `_stock_payload`,
  `_caution_flags` (the existing scoring stack that this endpoint
  composes).
- `docs/prd/13f_automation_and_resilience_prd.md` §7 (Oracle's
  Lens scoring vocabulary).
- `backend/app/services/oracles_lens/signal_weighted_score.py`
  `_LOW_CAVEATS` / `_MEDIUM_CAVEATS` — persisted-scoring caveat
  taxonomy (referenced for context; V1 uses dashboard
  `_caution_flags` severity not these constants).

## Files Expected To Change

- `backend/app/api/v1/endpoints/stocks_13f.py` (new)
- `backend/app/schemas/stocks_13f_snapshot.py` (new)
- `backend/app/api/v1/api.py` (router registration)
- `backend/tests/unit/test_mvp7_01_stocks_13f_snapshots.py` (new)
- This task file.

## Test Plan

### Pytest coverage (`test_mvp7_01_stocks_13f_snapshots.py`)

Build on the existing `_seed_oracles_lens_fixture` pattern from
`backend/tests/unit/test_oracles_lens.py`. Tests:

1. **`available=true` happy path**: a stock with ≥ `min_holders`
   qualifying ranked managers returns a snapshot with
   `available=true`, non-null `conviction_score` and
   `conviction_percentile ∈ [0, 1]`.
2. **`available=false / no_holders`**: a stock with zero 13F
   holdings for the period returns
   `unavailable_reason="no_holders"`.
3. **`available=false / below_min_holders`**: a stock with 1–2
   ranked managers (below `min_holders=3` default) returns
   `unavailable_reason="below_min_holders"`.
4. **Conviction percentile math**: the top-ranked stock returns
   `conviction_percentile=1.0`; the bottom-ranked returns
   `(1.0 - (universe_size - 1)/universe_size)`; mid returns the
   expected interpolation.
5. **Δ Holders signed integer**: a stock where 4 managers are
   `add`/`new` and 2 are `reduce`/`exit` returns
   `delta_holders=2, adders_count=4, reducers_count=2`.
6. **Distinctiveness tier — `distinctive`**: small consensus
   (≤ 8) + high `manager_signal_quality_coverage` (≥ 0.7) returns
   `tier="distinctive"`.
7. **Distinctiveness tier — `crowded`**: high consensus (≥ 20) +
   low coverage (< 0.5) returns `tier="crowded"`.
8. **Distinctiveness tier — `mixed`**: anything else returns
   `tier="mixed"`.
9. **Caveat severity — `ok`**: a clean stock with no flags
   returns `caveat_severity="ok"` and `caveat_codes=[]`.
10. **Caveat severity — `high-caution`**: a stock that triggers a
    `severity="warning"` flag (e.g. `unknown_manager_type_heavy`)
    returns `caveat_severity="high-caution"`.
11. **Caveat severity — `caution`**: a stock that triggers only
    `severity="info"` flags (e.g. `short_holding_streak` alone)
    returns `caveat_severity="caution"`.
12. **`period_filing_deadline` is period_end + 45 days**.
13. **`universe_size` matches the count of qualifying ranked
    stocks** in the requested period.
14. **Specific `period="YYYY-Qn"`** override returns the
    requested period, not the latest.
15. **Mixed batch**: a request with `stock_ids=[A, B, C]` where
    A is available, B is below_min_holders, C is unknown returns
    three snapshots in the same order as input.

### Existing-suite regression

- `pytest -q` baseline holds at 781 passed + new MVP7-01 tests.
  Zero new warnings.

### Frontend

- No frontend changes in this ticket. `npm run lint`,
  `node --test lib/oraclesLens.test.js`, and `npm run build` are
  smoke-only.

## Verification

- `docker compose exec api pytest -q tests/unit/test_mvp7_01_stocks_13f_snapshots.py`
- `docker compose exec api pytest -q`
- `docker compose exec web npm run lint`
- `docker compose exec web node --test lib/oraclesLens.test.js`
- `docker compose exec web npm run build`
- Manual probe:
  1. Re-seed dev fixture.
  2. `curl -sX POST http://localhost:8000/api/v1/stocks/13f-snapshots
     -H 'content-type: application/json'
     -d '{"stock_ids": [1, 2, 3], "period": "latest"}'`
  3. Confirm response shape matches D1 + the four signals are
     populated for any seeded stock with ≥ 3 ranked managers.

## Progress Notes

- 2026-05-13: Task spec filed.
- 2026-05-13: Implementation:
  - **New endpoint** `POST /api/v1/stocks/13f-snapshots` at
    `backend/app/api/v1/endpoints/stocks_13f.py`. Reuses
    `build_oracles_lens_dashboard(..., limit=0, use_persisted_scores=False)`
    for universe ranking; filters dashboard items to requested
    `stock_ids` and computes per-stock percentile / Δ Holders /
    distinctiveness tier / caveat severity.
  - **Schemas** at `backend/app/schemas/stocks_13f_snapshot.py` —
    `StockSnapshotRequest`, `AvailableStockSnapshot`,
    `UnavailableStockSnapshot`, `StockSnapshotResponse` with
    `Literal` discriminators on the unavailable-reason and
    caveat-severity vocabularies.
  - **Router registration** in `backend/app/api/v1/api.py` —
    `stocks_13f.router` registered BEFORE `stocks.router` under
    the `/stocks` prefix so the literal `/stocks/13f-snapshots`
    path matches before `/stocks/{stock_id}` (which `int`-coerces
    the path param and otherwise swallows the URL).
  - **Period sentinel**: API accepts `"latest"` for the convenience
    of frontend callers; translated to `period=None` (dashboard
    default-for-latest-complete) before dispatch.
  - **Distinctiveness thresholds** materialized as module constants
    (`_DISTINCTIVE_MAX_CONSENSUS`, `_DISTINCTIVE_MIN_COVERAGE`,
    `_CROWDED_MIN_CONSENSUS`, `_CROWDED_MAX_COVERAGE`) so future
    refinement is a one-site change.
  - **Caveat severity aggregation**: dashboard `_caution_flags`
    output is iterated; `severity="warning"` → `"high-caution"`,
    any flag → `"caution"`, none → `"ok"`. Mapping matches Pre-MVP7-01
    D1 modulo the constant-name correction (dashboard uses
    `warning`/`info` severities, not `_HIGH_CAVEATS`/`_MEDIUM_CAVEATS`
    constants from `signal_weighted_score.py` which are the
    persisted-scoring caveat taxonomy).
  - **Universe rank computed by `conviction_score` desc**, ties
    broken by stable insertion order; percentile = `1.0 - (rank - 1) / universe_size`.
  - **Unavailable disambiguation**: when a requested stock isn't
    in the ranked universe, a separate query counts that stock's
    13F holdings at `period_end_date` (with
    `is_latest_for_period=True`); if > 0 → `below_min_holders`,
    else → `no_holders`. Single-stock query per unavailable
    stock; acceptable for V1 watchlist sizes (≤ 50 rows).
  - **Tests at** `backend/tests/unit/test_mvp7_01_stocks_13f_snapshots.py`
    — 19 tests covering: available-true happy path; available-false
    branches (no_holders, below_min_holders, no_qualifying_period);
    Δ Holders signed integer; distinctiveness tier via helper unit
    tests (three branches); caveat severity aggregation (three
    branches); percentile math (top rank = 1.0); period_filing_deadline
    math (+45d); explicit period override; mixed-batch order
    preservation; pydantic min_length=1 rejection.
  - **Scope refinements** (recorded in spec):
    - SR0: no schema migrations.
    - SR1: no in-memory cache in V1 (measure before adding).
    - SR2: backend-only (no frontend changes; that's MVP7-03).
    - SR3: `use_persisted_scores=True` not exposed (MVP5-03 Phase 3
      gating).
    - SR4: no top-holders detail (MVP7-05).
    - SR5: public endpoint (matches existing `/13f/oracles-lens`).
  - **Test fixture limitation**: the dashboard's
    `_apply_manager_signal_profiles` overrides the stored
    `manager_type` column at runtime based on behavior heuristics
    (concentration / holding-period / turnover-proxy). Simple
    fixtures consistently get classified as `value_concentrated`
    (single-stock managers with weight ~1.0). This makes the
    end-to-end `crowded` tier and `unknown_manager_type_heavy`
    caveat paths impractical to test without forcing pathological
    fixtures. Those branches are unit-tested against the helper
    functions directly. Documented in the test-file docstring.

## Verification Results

- `docker compose exec api pytest -q tests/unit/test_mvp7_01_stocks_13f_snapshots.py`
  → **19 passed**.
- `docker compose exec api python -m scripts.seed_13f_dev_fixture --reset-only`
  then `docker compose exec api pytest -q` → **800 passed**
  (= 781 baseline + 19 MVP7-01); 0 warnings. The MVP5-07
  baseline holds.
- `docker compose exec web npm run lint` → No ESLint warnings or
  errors.
- `docker compose exec web node --test lib/oraclesLens.test.js`
  → 17 passed.
- `docker compose exec web npm run build` → compiled successfully;
  no frontend changes in this ticket.
- Manual probe via Python urllib inside the container:
  `POST /api/v1/stocks/13f-snapshots` with body
  `{"stock_ids": [1], "period": "2031-Q4"}` returns HTTP 200 with
  shape `{period, period_filing_deadline, universe_size, snapshots: [...]}` —
  matches Pre-MVP7-01 D1 contract. (Host-side `curl` testing
  blocked by a separate stale host-side uvicorn process binding
  port 8000; not in scope.)
