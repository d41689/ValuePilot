# 13F 数据自动化抓取与分析 PRD

| 项目名称 | ValuePilot 13F Data Automation & Ownership Signals | 版本 | v1.2 |
| :--- | :--- | :--- | :--- |
| **状态** | 草案 / 待评审 | **负责人** | Product |

---

## 1. 项目背景与目标

### 1.1 背景

13F 是 ValuePilot 发现高质量投资候选的重要数据源，但它不是实时交易数据，也不提供真实买入价格。当前系统的主要问题是：

1. 机构名单维护不系统：缺少稳定的 manager / CIK 管理、确认、停用、审计机制。
2. 抓取流程依赖手工操作：无法持续自动扫描 SEC 每日索引，也无法自动重试失败日期或失败文件。
3. 季度归属容易混淆：SEC 每日索引日期、申报提交日期、报告期 `periodOfReport` 是不同概念；延迟提交或修订提交容易被归到错误期间。
4. 缺少可重入与去重设计：重复运行任务可能导致重复 filings、重复 holdings，或者覆盖逻辑不清楚。
5. 缺少分析就绪状态：Oracle's Lens 需要知道哪些季度可以展示持仓快照，哪些季度可以计算新增、加仓、减仓、清仓和持有时长。

### 1.2 产品目标

本项目要建立一套从 SEC 每日索引到 Oracle's Lens 分析信号的自动化数据管线。

目标：

- 机构管理：维护投资机构信息，包括 display name、legal name、CIK、状态、类型、是否 featured、审计记录。
- 每日增量抓取：自动抓取 SEC daily `form.idx`，按日期记录同步状态，支持失败重试和历史回补。
- 精准筛选：从每日 `form.idx` 中筛选出我们维护的机构的 13F-HR / 13F-HR/A 记录。
- 持仓抓取与解析：进一步抓取 filing detail / information table，解析持仓数据。
- 正确期间归属：以 filing 内的 `periodOfReport` 为准归属到报告季度，不以抓取日期或 filing 日期作为报告期。
- 去重与可重入：以 SEC accession number 和 manager + report period + amendment policy 确保重复运行不会污染数据。
- 修订处理：正确处理 13F-HR/A，保证产品展示使用最新 active filing。
- 分析计算：支持当前持仓、连续季度变化、新增、退出、加仓、减仓、持有时长、持仓权重等基础分析。
- 数据透明：对 admin 和用户展示数据新鲜度、覆盖率、缺失原因和 readiness 状态。

### 1.3 非目标

- 不把 13F 数据包装成实时持仓。
- 不声称 13F 代表买入价格、成本价或投资建议。
- 不用 Dataroma 或其他第三方作为 holdings source of truth。
- 不在 V1 做 AI moat score、自动买卖建议或交易执行。
- 不要求 V1 一次性覆盖所有 SEC 13F 申报机构；V1 只抓取已确认的 tracked managers。

---

## 2. 核心概念与数据口径

### 2.1 日期与季度定义

13F 系统必须区分以下日期：

| 概念 | 字段 / 来源 | 含义 | 用途 |
| --- | --- | --- | --- |
| Sync Date | SEC daily index date | 系统抓取哪一天的 `form.idx` | 增量同步和重试 |
| Filing Date | SEC filing accepted date | 机构向 SEC 提交文件的日期 | 申报时效性、filing window 判断 |
| Report Period | `periodOfReport` | 持仓所对应的季度末日期 | 产品归属季度和分析计算 |
| Quarter End Date | report period normalized | 例如 2026-03-31 | Oracle's Lens 展示“截至日期” |
| Filing Deadline | quarter end + 45 calendar days | 13F 通常最晚提交日期 | 判断 partial / expected incomplete |

核心规则：

```text
Ownership analysis must be grouped by periodOfReport, not by sync date or filing date.
```

### 2.2 Source of Truth

| 数据 | Source of Truth |
| --- | --- |
| Filing metadata | SEC EDGAR |
| Accession number | SEC EDGAR |
| 13F information table | SEC EDGAR |
| Manager legal name / CIK | SEC EDGAR, admin confirmed |
| Manager display name / featured flag | ValuePilot admin data |
| Holdings analysis | Derived from SEC filings |
| Third-party manager discovery | Dataroma or other sources may be hints only |

---

## 3. Manager Management Center

### 3.1 目标

提供一个集中管理 tracked managers 的后台页面，确保系统知道应该从 SEC daily index 中筛选哪些机构。

### 3.2 Manager 状态

| 状态 | 含义 | 是否参与自动抓取 |
| --- | --- | --- |
| `candidate` | 已发现候选，但 CIK 未确认 | 否 |
| `active` | CIK 已确认，参与抓取 | 是 |
| `inactive` | 曾经跟踪，现在停用 | 否 |
| `ignored` | 明确忽略，不再提示 | 否 |
| `needs_review` | CIK、名称或数据异常，需要人工确认 | 否或降级 |

### 3.3 Manager 字段

最低字段：

```text
id
canonical_name
display_name
edgar_legal_name
cik
status
manager_type
is_featured
source
source_url
confidence_score
created_at
updated_at
confirmed_by
confirmed_at
review_note
```

说明：

- `cik` 必须是经过确认的 CIK，不能只依赖模糊匹配结果。
- `display_name` 用于 UI 展示。
- `edgar_legal_name` 用于数据审计。
- `is_featured` 只影响展示和排序，不影响是否抓取。

### 3.4 Manager Universe 策略

V1 默认策略：

- 以 Dataroma 或人工输入作为 manager discovery 起点。
- 只有 CIK 被确认后，manager 才进入 active tracked universe。
- 默认可以从全量 Dataroma-discovered manager universe 开始确认。
- 后续允许 admin 标记 `featured` managers，让 Oracle's Lens 优先展示高信号 manager。
- `featured` 不是 source of truth，也不是 ingestion filter。

产品原因：

| 策略 | 优点 | 风险 |
| --- | --- | --- |
| 全量 discovery | 覆盖广，少漏掉潜在 manager | 噪声多 |
| 精选 20-50 家 | 信噪比高 | 人工偏差大，维护成本高 |
| 全量 active + featured priority | 覆盖和信号兼顾 | 需要后续排序规则 |

### 3.5 CIK 搜索与确认

用户输入 manager name 后，系统应：

1. 调用 SEC company / submissions / search 相关数据源。
2. 返回候选 legal name、CIK、匹配分数、最近 filing 信息。
3. 允许 admin confirm / reject。
4. 记录确认人、确认时间、证据 URL、review note。

CIK 候选在确认前不得参与抓取。

---

## 4. Daily Sync Engine

### 4.1 目标

系统每日自动扫描 SEC daily `form.idx`，发现 tracked managers 的 13F filings。

### 4.2 `edgar_sync_status` 表

建议建立以 `sync_date` 为主键的同步状态表。

最低字段：

```text
sync_date
status
started_at
finished_at
attempt_count
last_error
form_idx_url
raw_document_id
filings_seen_count
tracked_13f_found_count
created_at
updated_at
```

### 4.3 Sync 状态

| 状态 | 含义 | 是否需要重试 |
| --- | --- | --- |
| `pending` | 尚未处理 | 是 |
| `running` | 当前正在处理 | 否，除非超时 |
| `success` | 成功抓取并处理 | 否 |
| `failed` | 抓取或解析失败 | 是 |
| `no_data` | SEC 无该日期 index，例如周末/节假日 | 否 |
| `partial_success` | 部分 filing 处理失败 | 是，针对失败项 |

### 4.4 每小时任务逻辑

每小时 worker 执行：

1. 找出所有 `pending` / `failed` / retryable `partial_success` 的 sync dates。
2. 优先处理最近日期，再处理历史回补。
3. 下载 SEC daily `form.YYYYMMDD.idx`。
4. 解析 daily index，筛选 `13F-HR` 和 `13F-HR/A`。
5. 根据 CIK 匹配 active tracked managers。
6. 为命中的 records 创建或更新 filing ingestion tasks。
7. 抓取 filing detail 和 information table。
8. 解析 holdings。
9. 根据 `periodOfReport` 归属报告季度。
10. 更新 sync status 和 job summary。

### 4.5 限速与稳定性

- 遵循 SEC 10 requests / second 限制。
- 使用统一 SEC client，集中处理 rate limit、retry、User-Agent。
- 网络失败使用 exponential backoff。
- daily index 下载结果应保存 raw document，便于复查。

---

## 5. Smart Routing：正确期间归属

### 5.1 核心规则

13F filing 必须根据 filing 内容中的 `periodOfReport` 归属报告季度。

```text
report_period = parsed periodOfReport
report_quarter = normalize(report_period)
```

不能使用以下字段作为报告季度：

- sync date
- filing accepted date
- SEC daily index date
- 当前系统日期

### 5.2 延迟申报处理

如果某 manager 在 2026-05-10 提交 2026-03-31 的 13F，该 filing 应归属：

```text
report_quarter = 2026-Q1
quarter_end_date = 2026-03-31
filing_date = 2026-05-10
sync_date = 2026-05-10 or later
```

Oracle's Lens 展示时应说明：

```text
Holdings data as of 2026-03-31. Managers file 13F reports up to 45 calendar days after quarter end, so current-quarter data may update until approximately 2026-05-15.
```

---

## 6. Filing 去重、可重入与 Amendment Policy

### 6.1 去重键

SEC accession number 是 filing 级别唯一键。

规则：

- 同一个 accession number 只能有一条 filing record。
- 同一个 accession number 的 holdings 解析必须可重入。
- 重跑同一 accession 不得产生重复 holdings。

### 6.2 两道去重防火墙

系统应采用两层防重复机制：filing-level 去重优先，holding-row-level 指纹作为二级保护。二者解决的问题不同，不能互相替代。

#### 第一层：Accession Number 作为申报单唯一身份

SEC accession number 是 filing 的全球唯一编号，应作为 filing-level 幂等主键。

流程：

1. 每小时扫描 SEC daily `form.idx`。
2. 对每条命中的 `13F-HR` / `13F-HR/A` 记录读取 accession number。
3. 先查询 `filings_13f.accession_number` 是否已存在。
4. 如果该 accession 已成功处理且不需要 reparse，直接跳过下载 and 解析。
5. 如果该 accession 存在但状态为 failed / partial / needs_reparse，则进入 retry / reparse 流程。

要求：

- `filings_13f.accession_number` 必须有唯一约束。
- job summary 应记录 skipped_existing_accessions 数量。
- 不能仅因为 accession 已存在就永远跳过；失败、部分成功、parser 版本升级、raw 文档损坏时必须允许显式 reparse。

#### 第二层：Holding Row Fingerprint 作为行级保护

Holding row fingerprint 用于防止解析或写入阶段产生重复持仓行，尤其是在任务重试、partial failure、批量写入失败恢复时提供额外保护。

建议指纹字段：

```text
holding_row_fingerprint = sha256(
  accession_number,
  normalized_name_of_issuer,
  normalized_title_of_class,
  normalized_cusip,
  value_usd_thousands,
  ssh_prnamt,
  ssh_prnamt_type,
  put_call,
  investment_discretion,
  other_manager
)
```

要求：

- fingerprint 应包含 `accession_number`，避免不同 filing 中相同持仓行被错误去重。
- fingerprint 应用于同一 accession 内的行级去重，不应用来跨季度、跨 manager 去重。
- `holdings_13f` 应对 `(filing_id, holding_row_fingerprint)` 或 `(accession_number, holding_row_fingerprint)` 建唯一约束。
- fingerprint 是防重复保护，不是 amendment 合并策略。13F/A amendment 仍必须按 `manager_id + report_period` 的 active filing policy 替换产品使用的 holdings。
- 行级 fingerprint 不能替代 accession-level atomic replace。推荐写入策略仍是：对一个 accession 的 derived holdings 在同一事务内 replace-safe 写入。

注意：如果同一 filing 内合法出现两行字段完全相同的记录，系统可能会把它们识别为重复。为降低风险，parser 应优先保留 SEC infotable 的原始行序号 `source_row_index`；如果可取得，应将 `source_row_index` 纳入唯一性判断或审计字段。

### 6.3 可重入要求

所有抓取任务必须支持重复运行：

| 操作 | 可重入要求 |
| --- | --- |
| daily index fetch | 相同 sync date 可重复下载或复用 raw document |
| filing metadata ingest | accession number upsert |
| information table fetch | accession-level raw document replace-safe 或 versioned |
| holdings parse | accession-level atomic replace |
| quarter backfill | 已成功 accession 跳过，失败 accession 可重试 |

### 6.4 Transaction Boundary

持仓解析的事务边界建议为 **one accession at a time**：

- raw information table
- filing metadata
- derived holdings
- parse status

应当全部成功提交，或全部失败并保持 retryable 状态。

### 6.5 Amendment Policy

13F/A 是数据正确性问题，不只是运维细节。

规则：

- 13F-HR/A amendment 如果对应同一 manager + report period，应作为该 manager + quarter 的最新修订版本处理。
- 不得把 amendment holdings 追加到原始 filing holdings 上。
- 原始 filing 和 amendment filing 都应保留用于审计。
- 产品分析只使用 active filing set。
- 对同一 `manager_id + report_period`，应能标记哪一个 accession 是 active。
- 当 amendment 被接受时，应原子性替换该 manager + quarter 的 product-facing holdings。

建议 amendment 状态：

| 状态 | 含义 |
| --- | --- |
| `no_amendments_seen` | 未发现 amendment |
| `amendments_applied` | 已发现并应用 amendment |
| `amendments_pending` | 已发现 amendment，但尚未解析或应用 |
| `amendment_failed` | amendment 处理失败，readiness 应降级 |

---

## 7. Holdings 数据模型与计算

### 7.1 Filing 字段

建议 `filings_13f` 至少包含：

```text
id
manager_id
cik
accession_number
form_type
filing_date
accepted_at
period_of_report
report_quarter
quarter_end_date
is_amendment
amends_accession_number
is_active_for_manager_period
raw_filing_url
raw_infotable_url
parse_status
parse_error
created_at
updated_at
```

### 7.2 Holdings 字段

建议 `holdings_13f` 至少包含：

```text
id
filing_id
manager_id
accession_number
report_quarter
quarter_end_date
name_of_issuer
title_of_class
cusip
value_usd_thousands
ssh_prnamt
ssh_prnamt_type
put_call
investment_discretion
other_manager
voting_sole
voting_shared
voting_none
stock_id
holding_row_fingerprint
source_row_index
created_at
updated_at
```

说明：

- `value_usd_thousands` 要保留 SEC 原始口径，通常单位为 thousands。
- `ssh_prnamt` 是股数或 principal amount，必须结合 `ssh_prnamt_type` 使用。
- `put_call` 为空时通常代表普通持仓；不能把 option 与 common share 混算。

### 7.3 持仓变化计算

持仓变化必须基于同一 manager、同一证券、连续报告季度的 active filing holdings。

基础分类：

| 分类 | 规则 |
| --- | --- |
| `new_position` | 当前季度存在，上一季度不存在 |
| `exited_position` | 上一季度存在，当前季度不存在 |
| `increased` | 当前数量 > 上一季度数量 |
| `reduced` | 当前数量 < 上一季度数量 |
| `unchanged` | 当前数量 = 上一季度数量 |

计算字段：

```text
previous_shares
current_shares
share_change
share_change_pct
previous_value_usd_thousands
current_value_usd_thousands
value_change
value_change_pct
holding_streak_quarters
```

注意：

- 变化数量优先基于 `ssh_prnamt`，但要避免把 option、不同 share type、不同 class 混合比较。
- 如果 CUSIP 无法稳定映射到 stock_id，变化计算应降级并显示 unavailable reason。
- 如果缺少上一季度数据，不得显示 add/reduce/exit，只能显示 snapshot。

---

## 8. 历史覆盖与 Oracle's Lens 功能门控

Oracle's Lens 不应在历史数据不足时暗示趋势洞察。

| 历史覆盖 | 可用能力 | 用户提示 |
| --- | --- | --- |
| 1 个季度 | 当前持仓快照 | 无趋势、无新增/退出/加减仓解释 |
| 2 个连续季度 | 基础变化：新增、退出、加仓、减仓 | 仅方向性变化，不代表长期趋势 |
| 4 个连续季度 | 年度趋势、持有持续性 | 可用于基础持仓行为分析 |
| 8 个连续季度 | 多年持仓模式、周期性判断 | 更适合长期 manager 行为研究 |

Readiness payload 应包含：

```text
historical_coverage_quarters
consecutive_quarters_available
supports_snapshot
supports_basic_change
supports_annual_trend
supports_multi_year_pattern
```

---

## 9. Readiness 与数据质量

### 9.1 Readiness Levels

| Level | 含义 | Oracle's Lens 行为 |
| --- | --- | --- |
| `unavailable` | 无可用 holdings | 显示 setup / unavailable 状态 |
| `experimental` | 有数据但覆盖弱 | Admin only 或强提示 |
| `usable_with_warning` | 大部分数据可用但有缺口 | 展示并提示 caveat |
| `ready` | 足够完整用于用户功能 | 正常展示 |

### 9.2 质量指标

核心指标：

```text
confirmed_manager_count
active_manager_count
filed_manager_count
manager_coverage_ratio
filing_parse_success_ratio
linked_holding_ratio
cusip_mapping_ratio
amendment_handling_status
historical_coverage_quarters
latest_usable_quarter
last_successful_sync_at
```

### 9.3 Zero vs Unavailable

必须区分 0 和 unavailable：

- `0 failed filings` 表示检查过且失败数为 0。
- `null failed filings + unavailable_reason` 表示还没有检查。
- `0% linked holdings` 表示有 holdings，但一个都没 linked。
- `null linked holdings ratio` 表示没有 denominator。

---

## 10. Admin Dashboard

### 10.1 主要页面

| 页面 | 目标 |
| --- | --- |
| Overview | 查看 13F 管线整体健康状态 |
| Managers | 维护 tracked managers 和 CIK |
| Daily Sync | 查看每日 form.idx 同步状态 |
| Filings | 查看 filings、parse status、amendments |
| Holdings Coverage | 查看 holdings parse 和 stock link 覆盖率 |
| Jobs | 查看 job runs、失败原因、重试 |
| Readiness | 查看 Oracle's Lens 是否可用以及为什么不可用 |

### 10.2 Oracle's Dashboard 指标

面向 admin 的重点指标：

- 当前报告季度
- filing window 是否仍打开
- active managers 数量
- 已申报 manager 数量
- 申报完成率
- failed filings
- pending amendments
- linked holdings ratio
- historical coverage depth
- latest usable quarter

---

## 11. Job Runs、锁与重试

### 11.1 job_runs 字段

```text
id
job_type
status
requested_by_user_id
trigger_source
sync_date
quarter
input_json
summary_json
error_message
dedupe_key
lock_key
started_at
finished_at
created_at
updated_at
```

### 11.2 Job 状态

| 状态 | 含义 |
| --- | --- |
| `queued` | 已排队 |
| `running` | 正在运行 |
| `succeeded` | 成功 |
| `partial_success` | 部分成功，存在可重试失败项 |
| `failed` | 失败 |
| `cancel_requested` | 请求取消 |
| `canceled` | 已取消 |
| `skipped` | 因锁或无任务跳过 |

### 11.3 推荐 lock_key

| Job Type | 推荐 `lock_key` |
| --- | --- |
| `fetch_daily_index` | `fetch_daily_index:{sync_date}` |
| `process_daily_index` | `process_daily_index:{sync_date}` |
| `ingest_filing` | `ingest_filing:{accession_number}` |
| `ingest_holdings_for_quarter` | `ingest_holdings:{report_quarter}` |
| `retry_failed_filings` | `retry_failed_filings:{report_quarter}` |
| `backfill_daily_indexes` | `backfill_daily_indexes:{start_date}:{end_date}` |
| `enrich_cusip` | `enrich_cusip:{report_quarter}` |
| `bootstrap_whitelist` | `bootstrap_whitelist` |
| `match_cik` | `match_cik` |
| `quality_check` | `quality_check:{report_quarter}` |

---

## 12. API Requirements

建议 API：

```text
GET  /api/v1/admin/13f/status
GET  /api/v1/admin/13f/readiness
GET  /api/v1/13f/readiness
GET  /api/v1/admin/13f/managers
POST /api/v1/admin/13f/managers
PATCH /api/v1/admin/13f/managers/{id}
POST /api/v1/admin/13f/managers/{id}/confirm-cik
POST /api/v1/admin/13f/managers/{id}/deactivate
GET  /api/v1/admin/13f/sync-dates
GET  /api/v1/admin/13f/filings
GET  /api/v1/admin/13f/jobs
POST /api/v1/admin/13f/jobs
POST /api/v1/admin/13f/jobs/{id}/cancel
POST /api/v1/admin/13f/jobs/retry-failed-filings
```

非 admin readiness endpoint 只暴露用户功能需要的安全字段，不暴露内部错误详情、SEC request logs 或敏感 job metadata。

---

## 13. UX Copy Principles

用户侧 13F 页面必须始终展示数据时效性。

推荐文案：

```text
Holdings data as of 2026-03-31. Managers file 13F reports up to 45 calendar days after quarter end, so current-quarter data may update until approximately 2026-05-15.
```

规则：

- 说 “13F filings are delayed snapshots.”
- 说 “Holdings data as of [quarter_end_date].”
- 说 “Current-quarter data may still update during the filing window.”
- 不说 “current holdings”。
- 不说 “guru cost basis”。
- 不说 “buy signal”。
- 不把缺失数据展示成 0。

---

## 14. MVP Delivery Plan

### MVP 1A: Manager + Daily Index 基础设施

- Manager CRUD read/write model
- CIK confirm / reject
- `edgar_sync_status` 表
- daily form.idx fetch and parse
- tracked manager CIK filtering
- job_runs + lock_key

### MVP 1B: Filing + Holdings Ingestion

- Fetch filing detail
- Fetch information table
- Parse holdings
- Store raw documents
- Accession-level idempotency
- `periodOfReport` routing
- Basic amendment detection

### MVP 1C: Readiness + Oracle's Lens Safe Integration

- Readiness summary
- Data freshness display
- Snapshot-only gating
- Zero vs unavailable
- Basic admin dashboard

### MVP 2: Change Analysis

- Consecutive-quarter comparison
- New / exit / increased / reduced calculation
- Holding streak
- Historical coverage gating
- 4-quarter annual trend support

### MVP 3: Resilience And Backfill

- Full historical backfill tools
- Partial success retry queue
- Amendment replacement workflow
- CUSIP enrichment and stock linking improvements
- Discord / Slack alerts for failed jobs

---

## 15. Acceptance Criteria

### 15.1 Functional Acceptance Criteria

- Admin can create, edit, deactivate, and review tracked managers.
- Candidate CIKs do not participate in ingestion until confirmed.
- System can fetch SEC daily `form.idx` by date and persist sync status.
- System filters daily index records to active tracked managers.
- System fetches 13F filing detail and information table for matched records.
- System routes filings to report quarter using `periodOfReport`.
- Re-running the same sync date or accession does not duplicate filings or holdings.
- Accession-level uniqueness and holding-row fingerprints provide two layers of duplicate protection without breaking amendment replacement.
- 13F/A amendments do not append duplicate holdings and can replace active holdings for manager + quarter.
- Oracle's Lens does not show add/reduce/exit signals without enough consecutive quarters.
- User-facing 13F views always display quarter-end date and filing-window freshness copy.

### 15.2 Testable Acceptance Criteria

- Given a daily index containing a tracked manager CIK and form type `13F-HR`, the system creates a filing ingestion task.
- Given a daily index containing an untracked manager CIK, the system ignores it.
- Given a filing submitted in May with `periodOfReport=2026-03-31`, the system assigns it to `2026-Q1`.
- Given the same accession is processed twice, holdings count does not double.
- Given a duplicate daily index scan sees an already-successful accession, the system skips download and parse and records the skip in job summary.
- Given a retry reaches holding insertion for the same accession and identical holding row, the holding-row fingerprint prevents duplicate insertion.
- Given two different accessions contain identical holding rows, the rows are not incorrectly deduplicated across filings.
- Given a later 13F/A exists for the same manager and report period, product-facing active holdings come from the amendment while the original remains auditable.
- Given only one quarter of holdings exists, Oracle's Lens shows snapshot only and hides add/reduce/exit signals.
- Given two consecutive quarters exist, Oracle's Lens may show new/exit/increase/reduce.
- Given four consecutive quarters exist, Oracle's Lens may show annual trend and persistence signals.
- Given no holdings denominator exists, linked holding ratio is `null` with unavailable reason, not `0%`.
- Given SEC request failure, sync date becomes `failed` or `partial_success` and is retryable.

---

## 16. Open Questions

- What exact manager types should V1 support: long-term fundamental, activist, quant, index-like, unknown?
- What ranking boost should `featured` managers receive in Oracle's Lens?
- Should historical backfill default to 4 quarters or 8 quarters for first production release?
- What minimum linked holdings ratio should block change analysis versus only warning the user?
- Should options rows with `put_call` be included in Oracle's Lens or excluded from common-share ownership analysis by default?
- What admin alert channel should be primary: Discord, Slack, email, or in-app only?
