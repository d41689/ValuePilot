# 2026-05-20 — 13F pipeline external-review remediation

## Goal

Address the external review of PRs #45–#55
(`docs/tasks/2026-05-20_13f-pipeline-hardening-review-results.md`). Fix the
findings we agree with; record reasoning for the ones we defer.

## Findings → disposition

| Review item | Disposition |
|---|---|
| R1-P1 `_execute_ingest_job` transaction boundaries | **Fixed** — per-filing SAVEPOINTs + explicit commit barrier after each phase |
| R1-P1 Phase 2 swallows programming errors | **Fixed** — broad `except` removed; routing failure now fails the stage |
| R1-P2 scoring commits internally (split-brain window) | **Deferred** — pre-existing behavior of `compute_signal_weighted_scores`, shared with the standalone CLI path; narrow window; tracked as follow-up |
| R1-P2 `ensure_filing_infotable_doc` refetches both docs | **Accepted as-is** — reviewer agreed it's acceptable |
| R2-P1 `is_active = is_latest` heuristic unsafe for amendments | **Fixed (minimal)** — Phase 4c now heals only the unambiguous solo-filing-per-(manager,period) case; multi-filing/amendment groups untouched. Full shared active-filing policy → follow-up |
| R2-P1 Phase 4 healing should be in the write path | **Partially addressed** — phase ordering (routing before parse) already makes NEW rows correct; Phase 4 kept as a self-deactivating idempotent safety net for historical rows |
| R2-P1 routing warnings/errors not persisted | **Fixed** — `backfill_period_routing` counts needs_review/failed, stamps `parse_warning`/`parse_error`, surfaces counts → stage `partial_success` |
| R2-P2 routing recompute not concurrency-safe | **Deferred** — narrow race; quarterly pipeline serialized by quarter; tracked as follow-up |
| R2-P2 CUSIP null-quarter guard can mis-link | **Fixed** — `_apply_mappings_to_holdings` now leaves a NULL-`quarter_end_date` holding pending instead of linking without a temporal filter |
| R2-P2 reconcile zero-signal / incomplete-quarter spin | **Fixed** — `end_quarter` defaults to `latest_scoreable_quarter()` (excludes in-progress quarter). NOTE: an initial cut also accepted a succeeded scoring job as coverage; that was rejected by PR #56 re-review (see the re-review section below) and `_has_meaningful_coverage` now anchors strictly on `oracles_lens_signals` row existence |
| R3-P1 move persistent storage out of CI workspace | **Deferred** — correct end state but a prod-infra migration (compose mount paths + runner filesystem move); needs operator coordination; tracked as follow-up |
| R4 broad excepts | **Fixed** — programming errors (`ImportError`/`NameError`/`AttributeError`) re-raised in both per-filing loops |
| R4 missing tests | **Partially** — added fail-loud + reconcile + `_is_programming_error` tests; full transaction-integration & amendment-regression tests recommended as follow-up |

## Files changed

- `backend/app/services/thirteenf_admin_dashboard.py` — `_execute_ingest_job`
  four-phase rewrite (commit barriers, savepoints, fail-loud), `_is_programming_error`,
  Phase 4c solo-group restriction, routing-degradation in summary/status.
- `backend/app/services/edgar_ingestion.py` — `backfill_period_routing` counts
  + persists routing needs_review/failed.
- `backend/app/services/cusip_enrichment.py` — `_apply_mappings_to_holdings`
  refuses to link on NULL `quarter_end_date`.
- `backend/app/services/thirteenf_start_quarter.py` — `latest_scoreable_quarter`,
  reconcile `end_quarter` default, `_has_meaningful_coverage` (signal-rows-only).
- Tests: `test_ingest_job_failloud.py` (new), `test_thirteenf_start_quarter.py`.

## Test plan

`docker compose exec api pytest -q` (full suite).

## PR #56 re-review (2026-05-20)

Re-review doc: `docs/tasks/2026-05-20_13f-pipeline-hardening-pr56-rereview-results.md`.

| Re-review item | Disposition |
|---|---|
| **P1** — `_has_meaningful_coverage` treats a succeeded `oracles_lens_score_backfill` job as terminal; a zero-signal scoring success on an incomplete quarter freezes it forever | **Fixed in this PR** — reverted to signal-rows-only. A succeeded scoring job is no longer accepted as coverage; only actual `oracles_lens_signals` rows count. Incomplete quarters now self-heal; a genuinely-empty completed quarter re-enqueues per boot as a cheap idempotent no-op. |
| **P2** — Phase 3 full `session.rollback()` on a per-filing parse error can roll back the failed-parse `ParseRun13F` audit row | **Follow-up** (per operator direction) |
| **P2** — Phase 4 solo activation still bypasses the shared active-filing policy | **Follow-up** (per operator direction) |
| **P3** — `backfill_period_routing` doesn't clear stale `parse_warning`/`parse_error` on a later clean reroute | **Follow-up** — needs warning/error namespacing first so a clean reroute doesn't wipe a non-routing warning |

## Third review (independent 4-agent re-run of the #45–#55 prompts)

This review re-ran the original PR #45–#55 prompts against pre-#56 code, so
most findings were already fixed by #56. Cross-check:

| Finding | Status vs current code |
|---|---|
| R1-1 BLOCKER — Phase 1/3 `session.rollback()` discards cross-phase work | **Already fixed by #56** — commit barriers + per-filing SAVEPOINTs (the review's recommended Option A is exactly what #56 implemented) |
| R4-A HIGH — Phase 2 `except` swallows `ImportError` | **Already fixed by #56** — the broad except was removed (fail-loud) |
| R2 MEDIUM — `needs_review` filings have no visible metric | **Already fixed by #56** — counts in the job summary + `partial_success` |
| R1-4 — `route_period` import | Confirmed fixed (#52) |
| **R2-1 CRITICAL — Phase 4c can activate a real 13F-HR/A amendment** | **Newly fixed here** — #56's solo-group guard alone still let a *solo* amendment through; added `form_type == "13F-HR"` so amendments / 13F-NT are never auto-activated. `form_type` is used rather than the review's suggested `is_amendment` flag because `is_amendment` is unreliably populated; the `/A` suffix is authoritative. |
| R2-2 HIGH — Phase 4a/4b should be an Alembic migration, not per-job | **Deferred** — partial disagreement: the writes are idempotent and self-deactivating (`WHERE … IS NULL` matches 0 rows once healed; prod is already healed) and phase ordering makes new rows born-correct. Migration-vs-idempotent-job-step is a style call, not a correctness bug. Follow-up. |
| R1-2 — `ensure_filing_infotable_doc` short-circuit refetches when `raw_primary_doc_id` is None | **Deferred** — minor rate-limit inefficiency; the first review judged it "acceptable". Follow-up. |
| R1-3 — `compute_signal_weighted_scores` internal commit | **Deferred** — the review's one-line `commit→flush` would break the standalone CLI caller that relies on the commit; proper fix is a `commit=False` param. Follow-up #2. |
| R3 — `clean: false` accumulation / move storage out of workspace | **Deferred** — infra change needing runner-side coordination. Follow-up #3. |
| R2-3 — `backfill_period_routing` concurrency | **Deferred** — follow-up #4. |
| R4-B — missing `backfill_period_routing` full-chain tests | **Deferred** — follow-up #5. |
| Reconcile criterion stability | Review confirms `oracles_lens_signals` row existence is genuinely terminal — matches the #56 re-review P1 fix. |

## Deferred follow-ups (suggest GitHub issues)

1. Shared active-filing-selection policy spanning accession ingest, quarterly
   ingest, and reparse (replaces the Phase 4c heuristic for multi-filing groups,
   and the solo-filing direct activation).
2. `compute_signal_weighted_scores` — add `commit=False` so the dispatcher owns
   the transaction (closes the split-brain window).
3. Move `storage/edgar_raw` + `storage/uploads` out of the CI runner workspace.
4. Row-lock (`FOR UPDATE`) the period-routing `is_latest` recompute for
   concurrency safety with manual accession ingests.
5. Full transaction-integration + amendment-regression test coverage for
   `_execute_ingest_job`, including: a bad infotable leaves a failed
   `ParseRun13F` audit row after `ingest_holdings` returns `partial_success`.
6. `backfill_period_routing` — clear stale routing `parse_warning`/`parse_error`
   on a clean reroute (requires namespacing the warning fields first).
