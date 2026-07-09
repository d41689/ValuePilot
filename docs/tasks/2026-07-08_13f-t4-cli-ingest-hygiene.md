# Task T4: CLI 摄取卫生(委托 job 路径)

**Created:** 2026-07-08 · **Origin:** PO plan `2026-07-08_13f-real-data-findings-po-plan.md`
(F5 + F6) · **Severity:** P2

## Goal / Acceptance Criteria

Two CLI ingest defects found on first real-data ingestion:

- **F6 — product-invisible legacy holdings.** `backfill` / `ingest-holdings`
  (`backend/app/cli/edgar.py`) call legacy `ingest_filing_holdings`, which writes
  `holdings_13f` rows with `parse_run_id = NULL`. The product query contract
  (PRD §7.3 `active_hr_holdings_query`) inner-joins `parse_runs.is_current`, so
  every CLI-ingested holding is invisible to Oracle's Lens / managers API /
  ownership-change compute, and misses the job path's Phase-4 heal + solo-HR
  activation.
- **F5 — newest report quarter silently skipped.** `backfill` Step 2 selects
  pending filings by `period_of_report BETWEEN <report-quarter bounds>`, but a
  freshly-indexed filing's `period_of_report` is a proxy (= `filed_at`, in the
  *filing* quarter) until its primary doc is parsed. The newest report quarter's
  filings (filed the following quarter) fall outside every report-quarter window
  and are skipped with "0 failures". (Older quarters escape because a prior parse
  already corrected their period.)

**AC:**
- CLI ingest produces ParseRun-backed holdings (via the modern `ingest_holdings`
  job / `ingest_if_needed`), so CLI-ingested data is product-visible.
- `backfill` ingests the newest report quarter's filings (selected by their
  actual/proxy period quarter, not the not-yet-corrected report-quarter window).
- Idempotent; no legacy `parse_run_id = NULL` rows written by the CLI.

## Scope

**In:** rewrite `ingest-holdings` + `backfill` to delegate to
`_execute_ingest_job` (`ingest_holdings` job) semantics; a testable
`pending_ingest_quarters` selector; unit tests.
**Out:** the `reparse_filing` / `reparse_all` replay commands (they use stored
docs, not fresh ingest); the job's own period-window behavior (unchanged — the
pipeline calls it per report quarter and its filings are parsed).

## Files to change (indicative)

- `backend/app/services/edgar_ingestion.py` (`pending_ingest_quarters` helper).
- `backend/app/cli/edgar.py` (`ingest-holdings`, `backfill` delegate to the job).
- `backend/tests/unit/test_13f_cli_ingest.py` [NEW].

## Test plan (Docker) — isolated test DB

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q tests/unit/test_13f_cli_ingest.py
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q      # closing gate
```

## 相位

- [x] 任务doc(本文件)
- [x] 红:`pending_ingest_quarters` 覆盖 proxy-period 最新季度;CLI 委托 job
- [x] 绿:实现(`edgar_ingestion.pending_ingest_quarters` /
      `ingest_pending_holdings`;CLI `ingest-holdings` / `backfill` 委托
      `execute_job_payload('ingest_holdings', …)`)
- [x] 全量 CI(隔离 test 库 backend 1104 passed;前端 unit 175 / lint clean /
      build OK)
- [ ] PO 签收
- [x] 清 `docs/BACKLOG.md` F5/F6 条目(标记 RESOLVED T4)

## 实现要点 / 决策

- **委托而非重写摄取逻辑**:CLI 走 `execute_job_payload(db, 'ingest_holdings',
  {'quarter': q})`(= `_execute_job` → `_execute_ingest_job`,无锁同步体),
  复用 job 的 infotable 抓取 + `ingest_if_needed`(ParseRun)+ Phase-4 heal +
  solo-HR 激活。无锁是刻意的:CLI 是手动 dev/ops 工具,调度器锁是给后台
  scheduler 的。
- **F5 选择键 = proxy period**:`pending_ingest_quarters` 按每个未摄取 filing 的
  `period_of_report`(未解析前 = `filed_at` 代理值)所在日历季度分组。这样最新
  报告季(filings 在下一季度申报)按其申报季度落入正确 job 窗口,解析后
  `backfill_period_routing` 再把 period 修正回真实报告季。幂等:摄取后
  `raw_infotable_doc_id` 置位即退出集合。
- **删除 `ingest-holdings --limit`**:job 路径按季度整批处理,legacy 的 `--limit`
  调试开关无对应语义,移除以免误导(dev CLI,无脚本依赖)。
- **真实数据核验**:dev `valuepilot` 25,070 holdings 全部 parse_run_id 非空且在
  current parse_run 下,0 条 legacy NULL —— 正是本修复让 CLI 今后保持的稳态
  (此前 legacy 路径会注入不可见 holdings)。`pending_ingest_quarters(dev)` 返回
  `[]`(全部已摄取,幂等 no-op 分支)。

## Scope(未做,登记而非静默)

- 未改 job 自身的 period-window 选择(pipeline 按报告季调用,其 filings 已解析,
  window 命中——不在本票范围)。
- 未动 `reparse_filing` / `reparse_all`(用已存文档重放,非新鲜摄取)——但见下方
  评审 F7:它们仍走 legacy 路径写不可见 holdings,已登记 backlog 并上报用户。

## 评审处置(2 finder agents,recall-biased)

两个独立 finder 都各自命中同一条 #1(强信号)。逐条独立核对代码后:

- **#1 — `--quarters N` 边界丢失(两 agent 均报,已修):** 改写后
  `ingest_pending_holdings` 扫全表,`backfill --quarters 1` 会把所有历史
  未摄取季度全部重摄;且 CIK 缺失管理人的 filing `raw_infotable_doc_id` 永不置位
  (`_execute_ingest_job` 的 `no_cik` 分支)→ 永久 pending → 每次 backfill 无界
  重跑 + 反复打 EDGAR。**修复:** `ingest_pending_holdings(quarters=…)` 按调用方
  范围过滤;`backfill` 传 `{报告季} ∪ {next(报告季)}`(代理 period 落在申报季)。
  回归:`test_ingest_pending_holdings_bounds_to_requested_quarters` +
  `…_bound_still_reaches_newest_report_quarter`(证明 F5 在边界下仍成立)。
- **#2a — 单季硬失败拖垮整批(已修):** job 路径对 programming/硬错误 re-raise,
  会中止整个 backfill 跳过其余健康季度(legacy 逐 filing except 不会)。**修复:**
  `ingest_pending_holdings` 逐季 try/except、rollback、记 `{"error": …}`、继续;
  CLI 汇总后有失败则 `Exit(1)` 且打印。回归:
  `test_ingest_pending_holdings_isolates_quarter_failure`。
- **#3 — `reparse_filing`/`reparse_all` 仍写不可见 holdings(F7,已登记+上报):**
  同 F6 类,但属不同命令、超出 F5/F6 范围;`reparse_all` 的 `replace_holdings=True`
  会先删可见 holdings 再插不可见——数据可见性 footgun。按纪律**未擅自扩容**本票,
  已记 `docs/BACKLOG.md` F7 并向用户明示,建议小型后续票(委托 `reparse_accession`
  job)。
- **#2b — backfill 按缺 infotable 而非解析失败重试(已登记 backlog,低):** 窄边缘,
  admin/`reparse_accession` 才是既定恢复路径。
- **#4 — `period_of_report IS NULL` 防御性排除(不修):** form.idx 恒置
  `period=filed_at`,无产生该态的插入路径;guard 仅防 `_date_to_quarter(None)` 崩。

评审确认为非问题:`_date_to_quarter` 各月/年界正确且与 `quarter_window` 一致;
once-computed pending 列表对中途 period 修正安全(修正只后移、升序迭代、各 filing
仅在自身季度被选中);删除 `--limit` 无任何 script/CI/cron 调用方。

## 二次评审处置(third-party,`...-review-prompts.md` → `...-review-results.md`)

二次评审确认 F5 选择与事务语义正确,提出 3 条:

- **[P1] `reparse-filing`/`reparse-all` 可抹掉产品可见持仓(已修,F7 收口)。** 评审据
  **README.md:135/138/139 明确宣传**这两条命令 + `replace_holdings=True` **先删可见
  持仓再插 `parse_run_id=NULL` 不可见行**,升级为 merge blocker。裁定:虽初版按范围
  纪律外置为 F7,但"已宣传的破坏性命令"属数据可见性风险,不能带病发布 →
  **本轮修复**:两命令改委托 ParseRun-backed `reparse_accession` job(经
  `run_locked_job`),该 job **换 is_current 且保留旧 run 持仓**(无删除)。真实数据
  验证:reparse `0001325447-26-000009` → 新 current run 602 rows、旧 run 602 保留、
  全局 0 条 NULL-parse_run。**注:** 该措辞初版把 ParseRun currency 误作产品可见性——
  该 accession 是 inactive 原件,`active_hr_holdings_query` 对它返回 **0**(见下方
  三次评审处置的更正);此处保留仅记录当时改动,准确口径以三次评审为准。
  README 文案更新。清 backlog F7。
- **[P2] CLI 绕过 `ingest_holdings:{quarter}` JobRun 锁(已修)。** `execute_job_payload`
  是无锁包装;CLI 与调度管线并发同季会重复摄取/冲突激活写。**修复**:新增公共
  `run_locked_job(session, job_type, payload, *, trigger_source)`(参数化
  `_execute_pipeline_stage_job` 的 trigger_source,复用其锁 + 可见 JobRun 机制);
  CLI `ingest-holdings` / `backfill` / `reparse-*` 全部经它,冲突返回 `conflict` +
  非零退出。回归:`test_run_locked_job_reports_conflict_when_lock_held`。
- **[P2] 测试未钉 CLI→产品可见性契约(已补)。** 原 9 测均注入 `ingest_fn`,回退到
  legacy 也不会红。**补**:源码护栏
  `test_cli_commands_never_call_legacy_ingest_filing_holdings`(4 命令不得引用
  `ingest_filing_holdings`)+ `CliRunner` 接线测试(`ingest-holdings` /
  `reparse-filing` 确实调 `run_locked_job` + 错误非零退出)。job→可见 ParseRun 由既有
  `test_13f_parse_run_audit.py` 钉;组合链闭合。

二次评审确认无问题项(不复报):F5 边界/最新季可达、日期跨界、once-computed 收敛、
错误隔离 + `except typer.Exit: raise`、`--help` 语义、无 `--limit` 遗留调用方。

## 三次评审处置(P1/P2-lock 确认 resolved;1 条 P2 复开)

三次评审确认 F7 replay-safety 与 CLI 锁均已正确修复,复开 1 条 P2:

- **[P2] CLI→产品可见性契约仍未被真实路径钉,且我的真实数据核验措辞错误(已修+已纠正)。**
  评审正确指出:我之前"reparse `0001325447-26-000009` → 602 visible"**混淆了
  ParseRun currency 与产品可见性契约**。该 accession 是 First Eagle 2026-Q1 的
  **inactive 原件**(被 restatement `0001325447-26-000018` 取代,
  `is_active_for_manager_period=false`),`active_hr_holdings_query` 对它返回 **0**,
  对 active restatement 返回 **602**。reparse 实现本身正确(非破坏、保留旧 run),
  但我核验的是错的量。**修复:**
  1. 新增真实路径集成测试 `test_cli_reparse_path_is_product_visible_end_to_end`:
     走真实 `run_locked_job('reparse_accession')`(仅 stub `load_body` 原始字节读),
     断言 (a) stage/JobRun succeeded 且 `trigger_source='cli'`;(b) 新 ParseRun
     current、旧 run 保留;(c) `active_hr_holdings_query` 对该(active)filing 返回
     行;(d) 无 `parse_run_id IS NULL` 行。
  2. 反例测试 `..._inactive_filing_is_not_product_visible`:currency≠visibility——
     inactive filing 有 current ParseRun 但 `active_hr_holdings_query` 返回 0。
  3. `reparse-all` runtime 测试 `test_reparse_all_cli_nonzero_exit_on_partial_failure`:
     一成功一失败 → 计成功、记失败、非零退出。
  4. **纠正**真实数据核验措辞(本 doc + BACKLOG F7):inactive 原件 0 可见、active
     restatement 602 可见、全局 0 条 NULL-parse_run(read-only 独立复现,与评审一致)。

三次评审确认 resolved:F7 replay 安全(两命令走 `reparse_accession`、保留旧 run、
失败/冲突非零退出);CLI 锁(`run_locked_job` 复用锁键/JobRun + 唯一索引竞态回退);
选择/事务/错误/锁无新缺陷。
