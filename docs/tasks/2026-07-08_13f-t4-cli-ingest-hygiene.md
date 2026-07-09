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
