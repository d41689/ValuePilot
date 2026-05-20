# 2026-05-20 — Remove the no-op `enrich_stocks_edgar` trigger surface

## Goal / Acceptance Criteria

- Remove the operator-facing trigger surface for `enrich_stocks_edgar`, which
  is a no-op: `enrich_stocks_from_edgar_tickers()` is a documented placeholder
  (`return {"new_mappings": 0}`).
- Acceptance: the admin UI no longer offers a button that silently does
  nothing; canonical CI green.

This came out of item #7 of `docs/tasks/2026-05-20_admin-13f-ops-audit.md`.

## Why

`enrich_stocks_from_edgar_tickers()` in `backend/app/services/cusip_enrichment.py`
is a deliberate compatibility placeholder — it returns `{"new_mappings": 0}` and
does no work. It is still called as a stage inside the `enrich_metadata`
pipeline (kept — that call and its test stay). But the **standalone manual
trigger surface** for it is dead and misleading:

- The admin "Enrich stocks from EDGAR" button queues an `enrich_stocks_edgar`
  job that does nothing — an operator clicking it (the readiness checklist even
  tells them to "bootstrap stocks") gets a silent no-op.
- The `enrich_stocks_edgar` CLI command is not just a no-op, it is **broken**:
  it prints `result['tickers_fetched']` etc., keys the placeholder never
  returns → `KeyError`.

## Scope

- **In:** delete the standalone `enrich_stocks_edgar` trigger surface — the
  admin button, the job-action registry entry + handler, the CLI command, the
  Jobs-page filter option, and the lock-key branch.
- **Out:** the `enrich_stocks_from_edgar_tickers()` function itself and its
  `enrich_metadata`-pipeline call stay (pipeline compatibility; covered by the
  `quarterly_pipeline` test). The actual CUSIP link-rate fix (audit item #7) is
  recorded in `docs/BACKLOG.md`, not done here.

## Files changed

- `frontend/app/(dashboard)/admin/13f/page.tsx` — remove the "Enrich stocks
  from EDGAR" button.
- `frontend/app/(dashboard)/admin/13f/jobs/page.tsx` — remove the
  `enrich_stocks_edgar` filter `SelectItem`.
- `frontend/lib/admin13f/lockKey.ts` — remove the `enrich_stocks_edgar` branch.
- `backend/app/services/thirteenf_admin_dashboard.py` — remove the
  `enrich_stocks_edgar` lock-key registry entry and the job handler block.
- `backend/app/cli/edgar.py` — remove the broken `enrich_stocks_edgar` command.
- `docs/BACKLOG.md` — record audit item #7 (CUSIP link rate).

## Test plan (Docker)

- `docker compose run --rm api sh -lc "alembic upgrade head && pytest -q"`
- `docker compose run --rm --no-deps web sh -lc 'node --test lib/*.test.js'`
- `docker compose run --rm --no-deps web npm run lint`
- `docker compose run --rm --no-deps web sh -lc 'NODE_ENV=production npm run build'`

(prod stack occupies host ports 8101/3101, so the suites run via
`docker compose run --rm` — see `2026-05-20_admin-13f-page-fixes.md`.)
