# Review prompts — PR #115(prod-zero 演练:M2 + D1/D2/D3)

Task doc: [`2026-07-09_13f-prod-zero-rehearsal.md`](./2026-07-09_13f-prod-zero-rehearsal.md)
PR: https://github.com/d41689/ValuePilot/pull/115
Branch: `claude/13f-prod-zero-rehearsal`(未合并;基线 `main` = `a740e7b`)
读 diff:`git diff main...claude/13f-prod-zero-rehearsal`
按发现顺序读提交:`git log --oneline main..claude/13f-prod-zero-rehearsal --reverse`

## 这一票为什么危险

这个 PR 修的是**全自动 13F 管线**——即 M5 将要在生产上打开的那条路径
(`EDGAR_SCHEDULER_ENABLED` / `THIRTEENF_JOB_WORKER_ENABLED` /
`THIRTEENF_START_QUARTER`),外加让 API **每次启动都写 `institution_managers`**。

三个被修的缺陷有一个共同形状:**每个 job 都报绿,而产品面是空的**。第一次无人值守
跑完时,14 个 job 里 13 个绿,`dup_active_groups = 0`,`holdings_null_parse_run = 0`
——库看起来完全健康,`oracles_lens_signals` 却是 0。

所以本次评审的**核心风险不是"改错了"**,而是:

1. 修复本身在**别的季度边界 / 别的重跑顺序**下引入新的错位;
2. 新的 `pipeline_warning` 守卫**漏报**(把真实的空跑当成合法 no-op)或**误报**;
3. `enrich_metadata` 从"单批"变成"跑到收敛",在**生产规模**下的运行时长、
   OpenFIGI/Rate Guard 压力、事务边界发生了未被评估的变化;
4. M2 让**坏 seed 文件阻断启动**——这是一个可能造成 `restart: unless-stopped`
   崩溃循环的决定,请独立判断这个取舍是否成立。

作者的验证是在一个**独立沙箱**(`valuepilot_prodsim`,与 dev/test/prod 完全隔离)
里做的。请把作者报告的数字当作**待验证的主张**,不要当作已签收的事实。

## 变更清单

| 文件 | 改动 |
|---|---|
| `app/main.py` | lifespan 里新增 seeding 钩子,位于 scheduler/worker **之前**;**不包 try/except** |
| `app/core/config.py` | 新增 `MANAGER_SEED_ON_STARTUP: bool = False` |
| `app/services/manager_seed_startup.py` [NEW] | `run_startup_manager_seed()`:事务边界 + fail-loud + 宇宙变化告警 |
| `app/services/edgar_ingestion.py` | `seed_confirmed_managers` 报告新增 `created_ciks` |
| `app/services/thirteenf_admin_dashboard.py` | **D1** `_ingest_candidate_filings()`;**D2** `pipeline_warning` 跨 stage 不变量;**D3** `_execute_enrichment_metadata` 改调 `enrich_all_unmapped_holdings` |
| `tests/unit/test_13f_manager_seed_startup.py` [NEW] | 11 条 |
| `tests/unit/test_13f_pipeline_quarter_window.py` [NEW] | 8 条 |
| `tests/unit/test_13f_pipeline_enrichment_convergence.py` [NEW] | 3 条 |
| `tests/unit/test_13f_admin_dashboard.py` | 两处 monkeypatch 目标随 D3 迁移 |

## 评审者看不到的上下文

- **`Filing13F.period_of_report` 是一个双重语义的列。** index 阶段插入时,它被填成
  `filed_at` 的**代理值**;`backfill_period_routing` 在解析后把它覆盖成**真实**的
  report period。这是 D1 的全部根源。`pending_ingest_quarters`(T4 加的)的
  docstring 里写明了这个代理语义。
- **`ingest_quarter_index(Q)` 抓的是 `next_quarter_label(Q)` 的 form.idx**,因为
  period-Q 的 13F 在 Q 结束后 45 天内递交。它的 `Q` 是 **report quarter**。
- **`reconcile_start_quarter_coverage` 用"该季度是否已有 Lens signal 行"来判断
  是否跳过**(`_has_meaningful_coverage`)。这意味着一个"摄取了但没打分"的季度
  会在**下次启动**时被重新入队——这就是为什么第一次演练在**重启后**才冒出 signals。
  重启掩盖了 D1。请注意:这条自愈路径依赖 API 重启,而 prod 只在部署时重启。
- **`latest_scoreable_quarter()` 有 45 天滞后**,所以 `2026-Q2` 的 pipeline 在
  2026-08-14 之前不会入队。修复前,report quarter `2026-Q1` 的申报(2026-Q2 递交,
  代理季度 = 2026-Q2)因此**没有任何 job 够得到**。
- **`stock_id` 是产品的连接键**:Watchlist × 13F 列、个股抽屉、以及 Oracle's Lens
  的入选(`oracles_lens/*` 的 `_eligible_stock_ids`)。没有 `stock_id` 的 holding
  对这三者全都不存在。
- **两个生命周期字段**:`match_status`(`ingest_quarter_index` 用 `=='confirmed'`
  选摄取对象)与 `status`(daily_sync / readiness / historical_backfill 用
  `=='active'`)。M1(PR #114)已合并,本 PR 依赖其语义。
- **`deploy.yml` 在 `main` CI 通过后自动部署 prod**,跑在一台自建 runner 上。因此
  一个 lifespan 钩子**一 merge 就上生产**,没有单独的生产闸门。

## 作者已自行发现并修复的问题(勿当新发现重报,但请验证修复是否完备)

- **D1** `ingest_holdings(Q)` 的窗口打在 `period_of_report ∈ Q` 上,而 index 刚插入的
  行代理季度是 `Q+1` → 永不匹配。修法:`_ingest_candidate_filings` 两条互斥分支。
- **D2** stage 级状态无法察觉 D1(空查询返回 `succeeded` 是合法的)→ 新增跨 stage
  不变量 `pipeline_warning`。
- **D3** pipeline 的 `enrich_metadata` 调单批 `enrich_cusips_from_openfigi(limit=100)`,
  而独立 `enrich_cusip` job 调收敛的 `enrich_all_unmapped_holdings` → 统一到后者。
- 作者的第一版探针把 `holdings_under_current_run == holdings` 当作验收断言,这在任何
  有 reparse 历史的库上都会误报(旧 run 的 holdings 是设计保留的)。已弃用。

## 刻意决策(judge,勿当 bug 重报)

1. **坏 / 缺失的 seed 文件阻断 API 启动**(`ManagerSeedError` 不被 catch),而紧挨着
   的 start-quarter reconcile 被 `try/except` 包着。理由:reconcile 幂等、下次启动
   会重试;而空的管理人宇宙会**静默地**什么都不摄取、什么都不打分。
   `test_the_curated_seed_file_is_valid` 负责让坏文件进不了镜像。
   → **请独立判断:在 `restart: unless-stopped` 下,这个取舍是否可能造成崩溃循环?
   CI 的守卫是否真的覆盖了所有能让 seed 抛异常的输入?**
2. **宇宙变化不触发下游重算**,只打 WARNING 并点名 CIK。
3. **`MANAGER_SEED_ON_STARTUP` 默认 false**,本 PR 不在生产打开它。
4. `amendments_pending = 1` 与 `ingest_holdings:2025-Q4` 的 `partial_success` 是
   **设计状态**(一份 `NEW_HOLDINGS` 修正案等待人工裁决),不是 bug。
5. `enrich_metadata` 的 `new_stocks` 计数误导(恒为 0)——**已知**,进了 BACKLOG,
   刻意不在本 PR 修。

## 测试基础设施

**dev 库 `valuepilot` 里有真实 13F 数据,pytest 必须跑在隔离库上**:

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q \
  tests/unit/test_13f_pipeline_quarter_window.py \
  tests/unit/test_13f_pipeline_enrichment_convergence.py \
  tests/unit/test_13f_manager_seed_startup.py \
  tests/unit/test_13f_admin_dashboard.py
```

全量收口:`docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q`
(作者报告 **1200 passed**)。

`raw_infotable_doc_id` 是指向 `raw_source_documents` 的**真 FK** —— 造"已摄取"的
filing 必须先建一行 `RawSourceDocument`,否则 `IntegrityError`。

若要复现沙箱:`valuepilot_prodsim` 库仍在共享 Postgres 上(容器已停)。**只读查询
可以;不要写它,也绝对不要碰 `valuepilot` / `valuepilot_test` / `valuepilot_prod`。**

---

## Prompt 1 — 季度窗口的穷举(关键角度,对抗式)

> 你在评审 ValuePilot 的 PR #115,分支 `claude/13f-prod-zero-rehearsal`。
> 只看 **D1 / D2**:`thirteenf_admin_dashboard.py` 的 `_ingest_candidate_filings()`
> 和 `quarterly_pipeline` 的 `pipeline_warning` 守卫。
>
> 先读 `git log --oneline main..HEAD --reverse` 里的 `52c1159` 和 `10cf5ce` 两个提交,
> 再读 `pending_ingest_quarters()`(`edgar_ingestion.py`)的 docstring —— 它解释了
> `period_of_report` 对未解析行只是 `filed_at` 的代理值。
>
> **你的任务:证明修复在某个真实的季度边界或重跑顺序下仍然错。** 至少穷举:
>
> 1. **跨年边界**:`2025-Q4` → `next_quarter_label` → `2026-Q1`。`quarter_window`
>    对 `2026-Q1` 的 start/end 是否正确?12/31 与 1/1 的 filing 落在哪一侧?
> 2. **迟交 / 早交**:一份 period 2025-Q4 的 13F-HR 在 **2026-Q3** 才补交(代理季度
>    2026-Q3)。哪个 job 会摄取它?会不会永远够不到?修复是否只是把 F5 从
>    "Q+1 够不到"搬到了"Q+2 够不到"?
> 3. **修正案**:一份 2026-Q2 递交的 13F-HR/A,restate 的是 2025-Q1。它会被
>    `ingest_holdings(2026-Q1)` 摄取(因为代理季度 = 2026-Q2)。解析后 period 变成
>    2025-03-31。这对 `apply_active_filing_policy`、`amendment_status`、以及
>    `compute_ownership_changes(2026-Q1)` 各意味着什么?有没有一个季度的
>    `ownership_changes` 会因此少算或多算?
> 4. **两条分支的互斥性**:`raw_infotable_doc_id IS NULL` 真的能保证互斥吗?
>    存在 `raw_infotable_doc_id` 已设但 `parse_status='failed'` 的行吗?它会被
>    哪一条分支选中?会被选中**两次**吗(同一次查询里 `or_` 的两臂同时为真)?
> 5. **重跑顺序**:先跑 `ingest_holdings(2026-Q1)` 再跑 `ingest_holdings(2025-Q4)`
>    (admin 可以手动触发任意季度)。有没有一份 filing 被摄取进错误的季度窗口,
>    或者被两个 job 同时选中并竞争?`lock_key` 是 `ingest_holdings:{quarter}`,
>    不同季度的 job **不互斥**。
> 6. **`pipeline_warning` 的漏报**:构造一个 index 插入 0 行、但仍然应该报警的场景
>    (例如 filing 已由 `fetch_daily_index` 插入,pipeline 的 index stage 因此返回 0,
>    而 ingest 也处理了 0)。守卫会沉默吗?这个沉默正确吗?
> 7. **`pipeline_warning` 的误报**:`filings_processed` 在什么情况下会是 0 但一切正常?
>    (提示:`filings_skipped_no_cik`、`filings_failed`。读 `_execute_ingest_job` 的
>    summary 各字段。)
>
> 对每条,给出**具体的行状态**(`period_of_report` / `filed_at` /
> `raw_infotable_doc_id` / `form_type` / `parse_status`)、**哪个 job 会/不会选中它**、
> 以及**错误的产品后果**。能在 `valuepilot_test` 上以 rollback 事务复现的,请复现并
> 贴出 before/after。不能复现的,明确标注"推理未复现"。
>
> 最后回答:**这个修复是完备的,还是把 F5 挪了一格?**

## Prompt 2 — 收敛与生产规模(D3 存在的全部理由)

> 你在评审 ValuePilot 的 PR #115。只看 **D3**:`_execute_enrichment_metadata` 从
> 单批 `enrich_cusips_from_openfigi(limit=100)` 改成收敛的
> `enrich_all_unmapped_holdings()`(提交 `e9d0024`)。
>
> 作者的主张:沙箱里 20–22 批、1719–1885 个映射、17.7 秒、`holdings_still_unmapped = 0`,
> 关联率 36.5% → 95.1%,Lens signals 309 → 859。
>
> **你的任务:找出这个改动在生产规模或失败路径下会出什么问题。**
>
> 1. **事务边界。** `enrich_all_unmapped_holdings` 逐批 commit(读它的注释)。它现在
>    跑在 `_execute_pipeline_stage_job` 的 session 里。这个 stage 的 session 边界是
>    什么?逐批 commit 会不会把**同一 session 里前面 stage 未提交的工作**一并提交?
>    读 `_execute_ingest_job` 顶部那段 "Transaction-boundary contract (external
>    review R1-P1)" 的注释,判断 enrich stage 是否有同类问题。
> 2. **JobRun 租约与心跳。** `THIRTEENF_JOB_LEASE_SECONDS = 300`,
>    `THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S = 90`。收敛循环最长可跑 `max_batches=300`
>    批。一批要多久?300 批会不会超过租约,导致 watchdog 认为 job 已死并重新派发?
>    循环里有心跳吗?**这是一个可以从代码直接判定的问题,请给出结论。**
> 3. **首次部署的冷启动。** Day-0 生产库有 0 个映射、可能有 8 个季度的 holdings
>    (几万个不同 CUSIP)。`max_batches=300 × 100 = 30000`。这次 enrich stage 会跑多久?
>    它阻塞 `quarterly_pipeline` 的后续 stage 吗?阻塞 worker 处理其他 job 吗?
> 4. **失败路径。** OpenFIGI / Rate Guard 在第 17 批返回 502(演练中真的发生过 502)。
>    `enrich_all_unmapped_holdings` 的 `finally` 只关 client。异常向上抛到哪里?
>    stage 变成 `failed` 还是 `partial_success`?前 16 批的映射保住了吗?
>    `bootstrap_stocks_from_cusip_map` / `backfill_stock_ids` 跑了吗?
>    下一次 pipeline 会续跑还是从头?
> 5. **`holdings_still_unmapped` 的语义。** 它排除了 `needs_review`(504 行)。那么
>    "still_unmapped = 0" 是否可能在**仍有 504 个 holding 永远不会被链接**时成立?
>    这个字段名会误导运维吗?`needs_review` 有人工出口吗(找到那个 admin 路由)?
> 6. **幂等性。** 连续两次 `enrich_metadata`,第二次应该是 0 批。验证
>    `_count_enrichable_holdings` 的过滤条件确实让已映射的 CUSIP 掉出池子,
>    否则循环靠 "no progress" 兜底退出——那是**兜底**,不是**收敛**。
>
> 请在 `valuepilot_test` 上尽可能复现 (1)(2)(4)(6)。给出结论:**这个改动可以在
> Day-0 的生产库上安全地跑吗?如果不能,最小的补正是什么?**

## Prompt 3 — 部署态安全、契约变更与验证的可信度

> 你在评审 ValuePilot 的 PR #115。看 **M2**(`main.py` + `manager_seed_startup.py`,
> 提交 `0305312`)以及**整个 PR 的验证主张**。
>
> **A. fail-loud 的取舍。**
> `run_startup_manager_seed` 抛出的 `ManagerSeedError` **不被 catch**,会让 uvicorn
> 启动失败。prod compose 是 `restart: unless-stopped`,且 `deploy.yml` 在 `main` CI
> 通过后**自动部署**。
>
> - 列举**所有**能让 `seed_confirmed_managers` 抛异常或返回空报告的输入与环境状态
>   (JSON 语法错误、`style_primary` 拼错、文件缺失、DB 连接抖动、advisory lock 等待、
>   `name_normalized` 冲突、唯一索引冲突……)。
> - 对每一条,判断 `test_the_curated_seed_file_is_valid` 是否真的能在 CI 拦住。
>   **哪些不能?** 那些就是崩溃循环的入口。
> - 与旁边 start-quarter reconcile 的 `try/except` 对比:作者给的区分理由
>   ("reconcile 幂等、seed 不幂等")是否成立?seed 其实**也是**幂等的(第二次
>   `created=0`)。那么真正的区分依据是什么?作者的论证站得住吗?
> - 给出你的结论:**fail-loud 正确,还是应该 fail-loud 但先探活 DB / 只在
>   seed 文件损坏时才致命?**
>
> **B. 契约变更的下游影响。**
> - `seed_confirmed_managers` 的报告新增了 `created_ciks`。有别的消费方按 key 集合
>   断言吗?(`bootstrap_whitelist` job summary、`_echo_seed_report`、admin UI。)
> - `enrich_metadata_summary.v1` 的 schema 新增了 `batches_run` /
>   `holdings_still_unmapped`,但 **schema 版本号没变**。前端 / admin UI 有按
>   schema 版本做严格解析的地方吗?`new_stocks` 语义变了吗?
> - `quarterly_pipeline_summary.v1` 新增了 `pipeline_warning` 键,同样没有升版本号。
>   `frontend/lib/admin13f/*` 有没有消费它?一个 `partial_success` 的 pipeline 在
>   admin UI 上如何呈现?运维能看到 `pipeline_warning` 的文本吗,还是只看到一个
>   黄色状态?
>
> **C. 验证的可信度(最重要)。**
> 作者报告:单次无人值守从零启动后,11 条不变量全为 0,holdings 10707,
> signals 859,关联 10180/10707,`active_hr_holdings_query` 返回 9811。
>
> - **`active_hr_holdings_query` = 9811,而 holdings = 10707,差 896。** 作者没有解释
>   这个差值。请你独立算出它应该是多少(提示:被降级的原申报、非 HR 表单、
>   3 份 restate 旧季度的修正案),并判断 9811 是否**正好**等于产品契约应返回的行数。
>   **如果对不上,这就是一个未被发现的缺陷。**
> - `ownership_changes` 在两次跑法下分别是 4207/4257 与 4209/4685。**同一份 EDGAR 数据,
>   为什么 ownership_changes 的行数不同?** 作者归因为"富化收敛顺序不同"。请验证:
>   `compute_ownership_changes` 依赖 `stock_id` 吗?如果依赖,那么**在 enrich 之前跑
>   ownership_changes 会永久少算**——而 pipeline 的 stage 顺序是
>   ingest → enrich → quality → ownership → lens。顺序对吗?一次 pipeline 内,
>   enrich 收敛了才轮到 ownership,所以应该是对的。**但重跑一个旧季度时呢?**
> - 作者只跑了 **2 个季度**。哪些不变量在 2 个季度上**恒真但在 8 个季度上会破**?
>   (提示:`ownership_changes` 需要前一季度基线;`2025-Q4` 的基线 `2025-Q3` 不存在,
>   所以那一季度的所有变动都是 `new`。这会污染 Lens 的 Δ-holders 吗?)
>
> 给出结论:**这份验证是否足以支撑"所有 13F 数据都正确"这个断言?还缺哪一步?**

---

## 输出格式(三个 prompt 共用)

把结果写回 `docs/tasks/2026-07-09_13f-prod-zero-rehearsal-review-results.md`,按下列结构:

```
## Verdict
（可合并 / 需补正后合并 / 打回。一句话结论。）

## Findings
### P1 — <一句话标题>
- 文件/行:
- 精确的行状态或输入:
- 现有代码会怎么做:
- 错误的产品后果:
- 是否已复现(贴命令与 before/after 输出);若未复现,写明"推理未复现"
- 建议修法:

### P2 / P3 — 同上

## Missing Tests
（最高价值的缺失测试,按价值排序,每条说明它能挡住哪个 P 级问题。）

## Non-findings
（你检查过、确认不是问题的点。写出来,免得下一个评审者重复劳动。）
```

**规则:**

- **不要把"刻意决策"一节里的 5 条当作新发现重报**;要 judge 它们,写进 `## Verdict`
  或作为 P2/P3 反驳。
- **每个 finding 必须给出错误的产品后果**,而不只是"代码不优雅"。
- **能复现就复现。** 本仓库的历史教训:作者曾三次报告"确认存在"的问题,复现后
  发现前提为假(其中一次是 `at_risk_groups` 用了 `group_size>=2` 的代理判据,
  16 个误报里只有 2 个是真的)。**推理未复现的 finding 请显式标注。**
- 若你认为作者报告的某个数字是错的,**给出你自己的查询与结果**。
