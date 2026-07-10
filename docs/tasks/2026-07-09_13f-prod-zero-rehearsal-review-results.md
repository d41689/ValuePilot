## Verdict

需补正后合并。D3 的收敛实现大体安全，M2 本 PR 默认关闭；但 D1/D2 的季度窗口修复仍不完备，会让相邻季度或迟交 filing 被错误季度的 pipeline 吃掉，并且 `pipeline_warning` 不会报警。

## Findings

### [P1] `_ingest_candidate_filings()` 仍会把未解析的 Q+1 代理行选进 Q+1 pipeline，季度 job 不互斥

位置：`backend/app/services/thirteenf_admin_dashboard.py:124-138`, `backend/app/services/thirteenf_admin_dashboard.py:2940-2948`, `backend/app/services/thirteenf_admin_dashboard.py:3007-3014`

根因：第一臂仍是裸的 `Filing13F.period_of_report.between(window.start, window.end)`。对未解析行，`period_of_report` 是 `filed_at` 代理值，不是真实 report period。第二臂加了 `raw_infotable_doc_id IS NULL`，但第一臂没有排除未解析代理行，所以“report Q 的 Q+1 代理 filing”会同时被 `ingest_holdings(Q)` 的第二臂和 `ingest_holdings(Q+1)` 的第一臂选中。不同季度的 lock key 是 `ingest_holdings:{quarter}`，不会互斥。

我在 `valuepilot_test` rollback 事务里复现：

```text
2025-Q4 ['9999999999-26-000001']
2026-Q1 ['9999999999-26-000001', '9999999999-26-000003', '9999999999-26-000004']
2026-Q2 ['9999999999-26-000004', '9999999999-26-000002']
2026-Q3 ['9999999999-26-000002']
```

行状态：

| accession | intended meaning | row state | selected by |
|---|---|---|---|
| `...000001` | 2025-Q4 HR filed in 2026-Q1 | `period_of_report=2026-02-17`, `filed_at=2026-02-17`, `raw_infotable_doc_id=NULL`, `parse_status=pending` | both `ingest_holdings(2025-Q4)` and `ingest_holdings(2026-Q1)` |
| `...000004` | 13F-HR/A filed in 2026-Q2, later routes to an older report period | `period_of_report=2026-05-14`, `raw_infotable_doc_id=NULL`, `form_type=13F-HR/A` | both `ingest_holdings(2026-Q1)` and `ingest_holdings(2026-Q2)` |
| `...000002` | late 2025-Q4 HR filed in 2026-Q3 | `period_of_report=2026-07-15`, `raw_infotable_doc_id=NULL` | `ingest_holdings(2026-Q2)` and `ingest_holdings(2026-Q3)`, not `ingest_holdings(2025-Q4)` |

产品后果：

如果 admin 或 scheduler 先跑 `quarterly_pipeline(2026-Q1)`，它可以处理 2025-Q4 的代理行；Phase 2 会把 filing/holding 路由回 2025-Q4，但后续 stage 仍按 2026-Q1 跑 `compute_ownership_changes` 和 Oracle's Lens。于是真实 2025-Q4 的产品输出保持 stale，错误的 2026-Q1 pipeline 还会是 green/partial-green。`pipeline_warning` 只看 `inserted > 0 && filings_processed == 0`，这里 `filings_processed > 0`，所以不会报警。

迟交 filing 说明这不是只差一个正常 Q+1 window：2025-Q4 的 Q+3 迟交行不会被 `quarterly_pipeline(2025-Q4)` 够到，而会被某个 filed-quarter pipeline 误处理。修复把 F5 从“Q+1 够不到”扩成了“错误 filed-quarter 够得到”，不是完备修复。

最小补正：

Parsed/heal 分支不要再用裸 `period_of_report`。应使用已路由字段，例如 `report_quarter == quarter` 或 `quarter_end_date` 落在 report-quarter window；未解析代理行只走 filed-window 分支。另加一个 pipeline 后置不变量：`ingest_holdings(Q)` 处理的 filing 在路由后若 `report_quarter != Q`，必须 warning/fail，而不是只看 processed count。

### [P2] `holdings_still_unmapped=0` 会掩盖仍然产品不可见的 `needs_review` holding

位置：`backend/app/services/cusip_enrichment.py:315-324`, `backend/app/services/thirteenf_admin_dashboard.py:3835-3845`, `backend/app/api/v1/endpoints/thirteenf_admin.py:893-914`

`_count_enrichable_holdings()` 只统计 `pending_mapping/unresolved` 且没有任何 `cusip_ticker_map` 的 CUSIP，明确排除了 `needs_review`。但 pipeline summary 注释说这个字段用于暴露“仍不能 map、因此从 Oracle's Lens 消失”的 holdings。这个说法对 `needs_review` 不成立：它们同样 `stock_id IS NULL`，同样产品不可见，却能在 `holdings_still_unmapped=0` 时存在。

测试库 rollback 复现：

```text
enrichable_count 0
unlinked_needs_review 1
```

只读 `valuepilot_prodsim` 也验证了同类状态：

```text
holdings_still_unmapped equivalent count = 0
stock_id IS NULL by status:
needs_review 504
unresolved 21
invalid_cusip 2
```

`/cusip-mappings?needs_review=true` 和 `/cusips?needs_review=true` 有人工出口，所以这不是没有处理路径；问题是 `enrich_metadata` summary 的字段名和注释会让运维把“OpenFIGI 队列清零”误读成“没有产品不可见的未链接 holding”。

最小补正：保留当前字段但改名或补字段，例如 `holdings_still_enrichable`、`holdings_needs_review_unlinked`、`holdings_invalid_cusip_unlinked`。Oracle's Lens 验收应看总的 `stock_id IS NULL` 分桶，而不是只看 OpenFIGI 队列。

### [P3] `pipeline_warning` 在 admin UI 里没有一等展示，运维只能在 raw JSON 里找

位置：`frontend/app/(dashboard)/admin/13f/jobs/page.tsx:948-959`, `frontend/app/(dashboard)/admin/13f/jobs/page.tsx:1013-1063`, `frontend/app/(dashboard)/admin/13f/jobs/page.tsx:1119-1125`

后端会把 warning 变成 parent `partial_success`，但 job detail 的醒目 alert 只展示 `error_message` 或 `summary_json.pipeline_error`，不展示 `summary_json.pipeline_warning`。Pipeline stages 区域也只列每个 stage 的 status；D2 的典型形态正是“每个 stage 都 green，但 parent 有 warning”。最后只有 Summary raw JSON 里能看到文本。

这削弱了 D2 的修复目标：它把 silent green 变成了 partial_success，但没有把“为什么 partial”变成可操作信息。最小补正是在 error/warning alert 区域同时渲染 `pipeline_warning`，使用 warning 样式。

## Missing Tests

- `_ingest_candidate_filings("2026-Q1")` 不应选中 `period_of_report=2026-Q1`、`raw_infotable_doc_id=NULL`、真实 report quarter 为 2025-Q4 的代理行。现有测试只断言 2025-Q4 不会偷 2026-Q1 的 Q+2 代理行，没有断言反方向。
- 迟交/补交用例：真实 2025-Q4、代理 2026-Q3 的 HR/HR-A，必须明确由哪个 job 摄取，以及摄取后哪个 report quarter 被 recompute。
- 修正案用例：2026-Q2 递交、解析后 period 为 2025-Q1 的 13F-HR/A，断言 active filing policy 和 ownership/Lens recompute 针对 2025-Q1，而不是 filed-quarter pipeline 的 payload quarter。
- `pipeline_warning` 漏报用例：`fetch_quarter_index` 插入 0 行，但 DB 已有 daily/index 插入的 pending filing，且 ingest 处理 0 或处理了错误 report quarter。
- `enrich_metadata` summary 应覆盖 `needs_review`/`invalid_cusip`/mapped-but-unlinked 分桶，至少避免把 `holdings_still_unmapped=0` 当作产品链接完成。
- Frontend job detail 应有 `pipeline_warning` 展示测试。
- M5 打开生产开关前还缺启动态测试：DB 不可用、seed advisory lock 长时间等待、既有 prod 数据触发 ambiguous/awaiting bucket 时，API 是 fail loud、hang，还是降级启动。

## Non-findings

- `quarter_window("2026-Q1")` 的跨年边界正确：`2026-01-01` 到 `2026-03-31`；`2025-12-31` 落在 2025-Q4，`2026-01-01` 落在 2026-Q1。
- 同一次 SQL 查询不会因为 OR 两臂都为真而返回重复 ORM row；`raw_infotable_doc_id` 已设但 `parse_status='failed'` 的行会通过第一臂进入 heal/rerun 路径，不是重复选择问题。
- D3 的事务边界没有发现同类 R1-P1 问题。`_execute_pipeline_stage_job` 在进入 stage 逻辑前已经提交 stage JobRun；`_execute_ingest_job` 各 phase 也有显式 commit barrier。`enrich_all_unmapped_holdings()` 的逐批 commit 不会提交前一个 pipeline stage 的未提交工作。
- D3 的 queued job lease 不会因 300 批循环自然过期：父 `quarterly_pipeline` job 由 worker 的独立 heartbeat 线程续租。子 stage JobRun 没有 lease，不会被 lease watchdog 重新派发；它只是可见记录。
- D3 失败路径基本可恢复：OpenFIGI/Rate Guard 第 N 批抛异常时，stage 被 `_execute_pipeline_stage_job` 标为 failed；此前批次已经 commit；`bootstrap_stocks_from_cusip_map`/`backfill_stock_ids` 不在异常路径上运行；下一次会跳过已存在 mapping 的 CUSIP 继续。
- `valuepilot_prodsim` 的 `holdings=10707` 与 `active_hr_holdings_query=9811` 差值 896 对得上产品查询契约。只读分解结果：896 全部是 inactive filing holdings，分别为 602、142、142、9、1 行；没有发现 active HR 查询漏掉应展示行。
- Pipeline stage 顺序对 ownership 是正确的：`ingest -> enrich -> quality -> ownership -> lens`。`compute_ownership_changes` 通过 `active_hr_holdings_query` 读取当前 holding，stock_id 会影响 matched-pair 质量；因此旧季度如果在 enrichment 收敛前已经算过，仍需要显式 rerun，但单次 pipeline 内顺序是对的。
- 本次 validation 证明了独立 `valuepilot_prodsim` 从零路径，而不是“所有 13F 数据都正确”。两季度演练无法覆盖 8 个季度里的 baseline 变化、迟交 amendment、跨季度重跑顺序和历史 recompute 策略。

验证记录：

- `valuepilot_test` rollback 复现 `_ingest_candidate_filings` 相邻季度重叠和 `needs_review` 未链接计数。
- `valuepilot_prodsim` 只读事务核对 holdings/product-query 差值与未链接分桶。
- Targeted tests: `docker compose exec -T -e DATABASE_URL=postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test api pytest -q tests/unit/test_13f_pipeline_quarter_window.py tests/unit/test_13f_pipeline_enrichment_convergence.py tests/unit/test_13f_manager_seed_startup.py tests/unit/test_13f_admin_dashboard.py` -> `74 passed`.
