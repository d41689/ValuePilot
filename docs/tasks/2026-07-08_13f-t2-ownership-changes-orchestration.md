# Task T2: ownership_changes 编排接线 + 计算去重加固

**Created:** 2026-07-08 · **Origin:** PO plan `2026-07-08_13f-real-data-findings-po-plan.md`
(F2 + F3) · **Severity:** P1

## Goal / Acceptance Criteria

Two coupled gaps found on first real-data ingestion:

- **F2 — orchestration never wired.** `compute_ownership_changes_for_manager_quarter`
  (MVP2-02) has **no production caller** — only tests. The `quarterly_pipeline`
  job (index → ingest → enrich → quality → lens-score) never materializes
  `ownership_changes`, so `GET /13f/managers/{id}/holdings/changes` returns
  `NO_COMPUTED_CHANGES` after a full pipeline run. Blocks investor-workflow
  tickets 01/02.
- **F3 — compute crashes on two CUSIPs → one stock.** When a filing holds ≥2
  holdings that resolve to the same effective key `(security_key,
  ssh_prnamt_type, position_type)` (e.g. two CUSIPs mapped to one `stock_id`,
  or repeated lots), row construction produces duplicate keys and violates
  `uq_ownership_changes_manager_quarter_security_position`. Hit live: manager
  4002, 5 quarters, ~177 groups/quarter. Present in BOTH the unavailable branch
  (rows built 1:1 per holding) AND the normal path (`_matched_pairs`' by-stock
  dict collapses one holding into `current_remaining`, whose `_pair_key`
  resolves back to `stock:<id>` → dup).

**AC:**
- `quarterly_pipeline` gains a `compute_ownership_changes` stage (after
  quality_check, before lens scoring) that loops managers with an active HR/HR-A
  filing for the quarter and calls the idempotent per-manager/quarter service;
  plus a standalone `compute_ownership_changes` job_type for targeted recompute.
- Compute **aggregates** holdings sharing an effective key (sum shares + value),
  not merely dedups — a manager's position in a stock is the sum across its
  CUSIPs/lots (13F infotable rows are additive). One row per key; no crash.
  Deterministic representative (largest value, tie by id) supplies provenance
  fields (holding_id / cusip / parse_run_id).
- Idempotent; re-running replaces rows per manager/quarter.

## Scope

**In:** the pipeline stage + job_type + lock builder; `_aggregate_holdings`
helper + read-only wrapper in `thirteenf_ownership_changes.py`; unit tests.
**Out:** attribution semantics (T3 — which holdings are `direct`); the
single-authority active-filing policy (T1-FU); UI (tickets 01/02).

## Files to change (indicative)

- `backend/app/services/thirteenf_ownership_changes.py` (aggregation).
- `backend/app/services/thirteenf_admin_dashboard.py` (`quarterly_pipeline`
  stage, `_execute_job` `compute_ownership_changes` branch, `_JOB_LOCK_BUILDERS`).
- `backend/tests/unit/test_13f_ownership_changes_compute.py` (F3 cases).
- new/existing pipeline test for the stage.

## Test plan (Docker) — isolated test DB

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q tests/unit/test_13f_ownership_changes_compute.py
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q      # closing gate
```

## 相位

- [x] 任务doc(本文件)
- [x] 红:F3 两 CUSIP→一 stock(真红:`uq_ownership_changes_manager_quarter_security_position`)
- [x] 绿:`_aggregate_holdings` 聚合求和(读性 wrapper,pipeline 不改)
- [x] 红/绿:编排阶段(pipeline 第 5 阶段)+ `compute_ownership_changes` job_type + lock builder
- [x] 全量后端 CI(**1074 passed**,隔离测试库);更新 3 个受影响的 pipeline 阶段断言
- [x] **真实数据端到端验证**:新 job 跑 6 个季度 0 失败;manager 4002(F3 前被跳过 5 季)
      现全量物化(411/392/404/423/425 行);ownership_changes 18,260 → 20,314
- [ ] 前端金标准命令(后端-only 改动,交 CI)
- [ ] PO 签收
- [ ] 清 `docs/BACKLOG.md` F2/F3 条目 ✅(已清)

## Log

- 2026-07-08: F3 根因比初判更广——`_matched_pairs` 的 by-stock dict 会把同 stock 的
  第二份 holding 挤入 `current_remaining`,但 `_pair_key` 仅在 current+previous 都有
  stock_id 时才用 stock 键,故 normal 路径实际不崩(cusip 键相异);真正崩溃只在
  unavailable(no-prior)分支(按 `_holding_key` 每 holding 建行 → stock:X 重复)。
  采用**聚合求和**(而非丢弃去重)修复:一个证券的持仓=其各 CUSIP/lot 之和(13F
  infotable 行可加)。`_AggregatedHolding` 只读 wrapper 喂入既有 pipeline,零侵入。
- 2026-07-08: 编排——quarterly_pipeline 在 quality 后插 `compute_ownership_changes`
  阶段(每 manager 一个 SAVEPOINT 隔离失败);另注册独立 job_type + lock builder 供
  单独重算。真实数据端到端:新 job 6 季 0 失败,4002 healed。
- 2026-07-08: **外部三角度评审 → 独立复现 → 采纳**(见 `...-review-results.md` 的
  PO/author disposition)。评审逮到我引入的两个回归:对 **normal 路径**做聚合会破坏
  PRD §7.4 的跨季 CUSIP-fallback(#1 假清仓)并让 representative CUSIP 冒充仓位身份
  误判 cusip_changed(#2)。**根因修复:把聚合收窄到唯一会撞 unique key 的
  unavailable 分支**;`_compute_rows` 恢复吃 RAW holdings,#1/#2 随之消失。另修
  #3(portfolio_weight 改求和)、#4(部分失败→partial_success,不再被成功掩盖)。
  新增回归测试:mapping-transition 无假清仓、weight 求和、per-manager 失败隔离;
  删除测本已回退行为的 normal-path 聚合测试。全量 1075 passed;真实数据重算 6 季
  0 失败,4002 仍 2055 行。positions 读模型泛化 → backlog(low)。
