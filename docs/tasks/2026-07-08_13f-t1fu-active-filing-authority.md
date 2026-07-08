# Task T1-FU: unify active-filing selection into one policy (+ accepted_at, ties, concurrency)

**Created:** 2026-07-08 · **Origin:** T1 external review
(`2026-07-08_13f-t1-restatement-activation-fix-review-results.md`) Design Verdict
+ two P1 findings that are correct but **out of scope for the P0 crash fix**.
**Severity:** medium (correctness + robustness; no active production data loss —
see "why not now").

## Problem

"Which filing is active for a `(manager_id, quarter_end_date)`" is decided in
**four** places with **different** rules:

- `_do_ingest_holdings` (per-parse restatement activation via
  `reconcile_restatement_activation`).
- `_execute_ingest_job` Phase 4 (solo-13F-HR auto-activation heuristic).
- `_execute_ingest_job` Phase 5 (restatement reconcile loop).
- `thirteenf_filing_detail.apply_amendment_policy` (original selection, ranks by
  `(accepted_at or min, accession_no)`, deactivates all on an `accepted_at` tie +
  sets `amendment_sort_warning=True`).

T1 aligned `reconcile_restatement_activation`'s ranking KEY with
`apply_amendment_policy` (accepted_at → accession_no) but deliberately did NOT
unify the sites or replicate the tie rule. Four gaps remain:

1. **Scattered authority.** No single `select_active_filing(manager_id,
   quarter_end_date)` covering originals + NT + amendments + restatements +
   parse_status + ordering + ties. The scatter is the root cause of the T1 crash
   and will keep generating edge cases.
2. **`accepted_at` is not populated by the bulk-ingest path.** All 373 real
   filings (incl. all 17 restatements) have `accepted_at IS NULL`, so BOTH
   `apply_amendment_policy` and the T1 ranking degrade to `accession_no`
   fallback. The authoritative SEC acceptance timestamp is simply missing on the
   `ingest_holdings` / `ingest_holdings_for_filing` path (it is captured on the
   `ingest_accession` primary-doc path via `apply_primary_doc_metadata`). Until
   fixed, accepted_at ordering is inert.
3. **Equal-`accepted_at` tie rule not honored for restatements.**
   `apply_amendment_policy` deactivates all tied filings + sets
   `amendment_sort_warning=True`; `reconcile_restatement_activation` auto-resolves
   by accession_no. NOTE: this can only be implemented AFTER (2) — with
   accepted_at all-NULL today, every restatement pair is a false "tie", and
   deactivating on it would REGRESS the T1 incident fix (the latest restatement
   would never win). Sequencing: (2) before (3).
4. **Concurrency.** `reparse_accession` / `reprocess_amendment` lock **per
   accession** (`reparse_accession:{accession_no}`), while `ingest_holdings`
   locks per quarter. Two reparse jobs for two restatements of the SAME
   (manager, period) can run concurrently; the guard SELECT + demote/activate is
   not under a row/advisory lock, so under READ COMMITTED they can race to a
   silent wrong-winner or a `uq_active_filing_per_manager_period` abort.
   Pre-existing (T1 did not introduce it).

## Why not fixed in T1

T1 was a P0 **crash** fix; it stopped the `IntegrityError` that aborted the
quarterly pipeline and made the winner deterministic. (2)+(3) require a
data-backfill of accepted_at and are inert without it; (4) is a pre-existing
concurrency property spanning all activation sites; (1) is a refactor. Bundling
them into the crash fix would violate scope discipline and add risk to a P0.

## Goal / Acceptance Criteria

- One authority `select_active_filing(session, manager_id, quarter_end_date)` (or
  `apply_active_filing_policy`) that all four sites call; ranking = `(accepted_at,
  accession_no)` desc; NT excluded; parse_status respected.
- `accepted_at` populated on the bulk-ingest path (parse it from the primary doc
  in `ingest_if_needed` / `_do_ingest_holdings`, or backfill from stored docs).
- Equal-`accepted_at` ties: no auto-switch; set `amendment_sort_warning=True` +
  `amendments_pending`, consistent with `apply_amendment_policy`. Gated behind (2).
- A `(manager_id, quarter_end_date)` advisory lock (`pg_advisory_xact_lock`) or
  `SELECT … FOR UPDATE` over the period's filings taken before deciding/flipping
  active state, so concurrent per-accession reparse jobs serialize.
- Tests: accepted_at tie (no auto-activation + warning); two concurrent sessions
  reparsing different restatements of one period converge to one winner without a
  constraint abort; accepted_at populated after a real ingest.

## Test plan (Docker) — isolated test DB

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
```

## 相位

- [ ] 任务doc(本文件)
- [ ] (2) accepted_at 回填/摄取期填充 + 测试
- [ ] (1) 单一 select_active_filing 权威 + 四处收敛
- [ ] (3) tie → warning(依赖 2)
- [ ] (4) (manager, period) 锁 + 并发测试
- [ ] 全量 CI
- [ ] PO 签收
- [ ] 清 `docs/BACKLOG.md` 对应条目
