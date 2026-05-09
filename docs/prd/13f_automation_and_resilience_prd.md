# 13F 数据自动化抓取与分析 PRD

| 项目名称 | ValuePilot 13F Data Automation & Ownership Signals | 版本 | v1.11 |
| :--- | :--- | :--- | :--- |
| **状态** | Ready for Engineering Review | **负责人** | Product |

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
- 精准筛选：从每日 `form.idx` 中筛选出我们维护的机构的 13F-HR / 13F-HR/A / 13F-NT 记录。
- 持仓抓取与解析：进一步抓取 filing detail / information table，解析持仓数据。
- 正确期间归属：以 filing 内的 `periodOfReport` 为准归属到报告季度，不以抓取日期或 filing 日期作为报告期。
- 去重与可重入：以 SEC accession number 和 manager + report period + amendment policy 确保重复运行不会污染数据。
- 修订处理：正确处理 13F-HR/A，区分全量修订与部分修订，保证产品展示使用最新可信 active filing。
- 分析计算：支持当前持仓、连续季度变化、新增、退出、加仓、减仓、持有时长、持仓权重等基础分析。
- 数据透明：对 admin 和用户展示数据新鲜度、覆盖率、缺失原因和 readiness 状态。

### 1.3 成功指标（KPI）

| 指标 | MVP 1 目标 | MVP 2 目标 | 说明 | 观测来源 |
| --- | --- | --- | --- | --- |
| Active manager 覆盖率 | ≥ 80% expected filers 每季度有 filing | ≥ 95% | filing window 关闭后 T+3 天内统计；expected filers 定义见 §10.1 | `quality_check` job 输出 |
| Filing parse 成功率 | ≥ 95% | ≥ 99% | 每季度 filing 解析成功比例 | `filings_13f.parse_status` 统计 |
| Holdings 链接率 | ≥ 70% holdings 可映射 stock_id | ≥ 85% | CUSIP → stock_id 映射率（common shares only） | `holdings_13f` 统计 |
| Daily sync 延迟 | SEC 发布后 ≤ 4 小时 | ≤ 2 小时 | 仅统计 SEC 有发布的工作日；以 `edgar_sync_status.finished_at` - SEC index 首次 200 响应 timestamp 推算；no-index 日不计 | `edgar_sync_status` |
| Oracle's Lens readiness | ≥ 1 个季度 ready | ≥ 4 个连续季度 ready | filing window 关闭后 T+5 天内达到 | readiness API |
| 重复数据率 | 0% | 0% | 重复 filing / holdings 行为 0 容忍 | unique constraint 违反次数 |
| 管线告警触达 | P1 告警 ≤ 15 分钟触达通知渠道 | 同左 | 从告警条件触发到 Discord 消息送达 | Discord 消息时间戳 |

### 1.4 非目标

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
| Quarter End Date | report period normalized | 例如 2026-03-31 | Oracle's Lens 展示"截至日期" |
| Filing Deadline | quarter end + 45 calendar days | 13F 通常最晚提交日期（SEC 规则） | 基准日期 |
| Official Filing Deadline | Filing Deadline 调整到下一个 SEC/EDGAR operational business day（若落在周末、SEC federal holiday 或 EDGAR 特别关闭日）；使用 SEC/EDGAR federal holiday calendar，不使用 NYSE market holiday calendar（Good Friday 通常为 NYSE 休市但 EDGAR 可开放；Veterans Day / Columbus Day 为 federal holiday 且 EDGAR 关闭） | 实际最晚合规提交日期（SEC FAQ Q25） | filing window 判断、告警触发、readiness 计算 |
| Valid Filing Window | quarter end to quarter end + 180 days | 13F 合理申报范围（含延迟申报） | periodOfReport 归属验证（见 §5.3） |

核心规则：

```text
Ownership analysis must be grouped by periodOfReport, not by sync date or filing date.
Filing window close date = official_filing_deadline (business-day adjusted), not bare quarter_end + 45.
```

### 2.2 13F Filing 类型

SEC Form 13F 有三种 form type 和两种 report type，必须正确区分：

| Form Type | Report Type | 含义 | holdings 完整性 |
| --- | --- | --- | --- |
| 13F-HR | Holdings Report | Manager 直接申报其全部 13(f) 持仓 | 完整（本 manager 视角） |
| 13F-HR | Combination Report | Manager 直接申报部分持仓，其余由其他 manager 代报 | **部分**（需 caveat） |
| 13F-HR/A | Holdings Report / Combination Report 的修订 | 同上 | 同上 |
| 13F-NT | Notice（通知） | Manager 所有 13(f) 持仓均由其他 manager 代报，本 filing 只有 cover page | **无直接持仓数据**，持仓存在于其他 manager 的 filing 中 |

**重要：** 13F-NT（Notice）不代表 manager 无持仓，而是 manager 的所有 13(f) 持仓已包含在其他 manager 的 13F-HR / 13F-Combination Report 中（SEC FAQ）。系统不得将 13F-NT 解读为"该 manager 当季无持仓"。

### 2.3 Source of Truth

| 数据 | Source of Truth |
| --- | --- |
| Filing metadata | SEC EDGAR |
| Accession number | SEC EDGAR |
| 13F information table | SEC EDGAR |
| Manager legal name / CIK | SEC EDGAR, admin confirmed |
| Manager display name / featured flag | ValuePilot admin data |
| Holdings analysis | Derived from SEC filings |
| Third-party manager discovery | Dataroma or other sources may be hints only |

### 2.4 季度标准化规则

`periodOfReport` 字段可能出现非标准季末日期（如 2026-03-30 等因周末调整）。

| periodOfReport 偏移范围 | 处理策略 |
| --- | --- |
| ±0 日（完全匹配标准季末） | 直接归属，无 warning |
| ±1–2 日 | 满足以下**两个条件**时自动归一化：① form_type 为 13F-HR / 13F-HR/A；② `accepted_at` 落在 valid filing window 内（quarter_end 后 0–180 天） |
| ±3–5 日 | `parse_status=needs_review`，`PARSE_WARNING=PERIOD_TOO_FAR_FROM_QUARTER_END` |
| > ±5 日 | 同上 |

**关键说明：** 13F 的 accepted_at 正常在 quarter_end 之后（Q1 filing 通常 accepted_at 在 Q2），±1–2 日归一化条件绝不要求"accepted_at 所在季度与 report period 所在季度相同"，正确条件是 `quarter_end_date ≤ accepted_at ≤ quarter_end_date + 180 days`。

异常处理详情见 §5.3。

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
confidence_score          -- 整数 0–100；低于 60 建议进入人工确认流程
value_unit_override       -- 枚举：infer（默认）/ thousands / dollars
                          -- infer：parser 按 form_spec_version 和 XML 语义自动判断（推荐）
                          -- thousands / dollars：admin 强制覆盖，仅在 admin 明确确认后生效
confirmed_by
confirmed_at
created_at
updated_at
review_note
```

注：`value_unit_override` 的默认值应为 `infer`，即让 parser 按 filing 的 form_spec_version 和 XML schema 自动判断单位，不要用 manager-level 覆盖作为主判断路径。filing-level `value_unit_override` 为已知 gap，V1 不实现。

### 3.4 Manager Universe 策略

V1 默认策略：以 Dataroma 或人工输入作为 manager discovery 起点；只有 CIK 确认后进入 active tracked universe；`featured` 不是 source of truth，也不是 ingestion filter。

### 3.5 CIK 搜索与确认

SEC EDGAR 查询接口：

- **名称搜索**：EDGAR 全文检索（EFTS）`https://efts.sec.gov/LATEST/search-index?q="manager+name"&forms=13F-HR`。
- **CIK 已知时验证**：`https://data.sec.gov/submissions/CIK{10位}.json`，`submissions/{CIK}.json` 需要已知 CIK，不能用于名称搜索。

流程：Admin confirm CIK 后，系统显示历史回补预览（含预估 filing 数量、EDGAR 请求数、rate limit 等待时间）；Admin 确认后才触发 backfill job，禁止静默触发。

### 3.6 批量导入

Admin 可上传 CSV，最低必填字段：`canonical_name`；可选字段：`source_url, manager_type, is_featured`。所有候选初始状态为 `candidate`，不自动确认任何 CIK。

---

## 4. Daily Sync Engine

### 4.1 目标

系统每日自动扫描 SEC daily `form.idx`，发现 tracked managers 的 13F filings。

### 4.2 `edgar_sync_status` 表

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
tracked_13f_hr_found_count      -- 当日发现的 13F-HR + 13F-HR/A 数量
tracked_13f_nt_found_count      -- 当日发现的 13F-NT 数量
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
| `no_data` | 已确认该日期无 index | 否 |
| `partial_success` | 部分 filing 处理失败 | 是，针对失败项 |

### 4.4 每小时任务逻辑

每小时 worker 执行：

1. 找出所有 `pending` / `failed` / retryable `partial_success` 的 sync dates。
2. 优先处理最近日期，再处理历史回补。
3. 下载 SEC daily `form.YYYYMMDD.idx`。
4. 解析 daily index，筛选 **`13F-HR`、`13F-HR/A` 和 `13F-NT`**。
5. 根据 CIK 匹配 active tracked managers。
6. 为命中的 **13F-HR / 13F-HR/A** 创建或更新 filing ingestion tasks。
7. 为命中的 **13F-NT**：
   - 必须抓取 filing detail / header，从 `periodOfReport` 确定报告季度（不使用 daily index date 推断）。
   - 保存 raw filing document（用于审计和 period 复查）。
   - 解析 cover page 中的 `otherManagersInfo`，获取代报该 manager 持仓的 other_managers 列表；能解析到 CIK / 13F file number 时必须保存，不能只存展示名称。
   - 不抓取 information table（13F-NT 无 holdings table）。
   - 按 `periodOfReport` 将该 manager + quarter 标记为 `coverage_type=notice_reported_elsewhere`，并存储包含可解析 identifier 的 `other_managers_reporting` 列表。
   - **不得将 13F-NT 解读为"该 manager 当季无持仓"**：13F-NT 表示持仓由其他 manager 代报，持仓数据客观存在于那些 manager 的 filing 中。
8. 抓取 13F-HR / 13F-HR/A 的 filing detail 和 information table。
9. 解析 holdings。
10. 根据 `periodOfReport` 归属报告季度（见第 5 节）。
11. 更新 sync status 和 job summary。

**404 处理规则：**

1. 若该日期在 `no_index_expected_dates` 列表中（已知周末、SEC federal holiday 或 EDGAR 特别关闭日），直接标记 `no_data`。
2. 否则重试超过 3 次且当日美东 23:59 已过，再标记 `no_data`。

**每日触发时间：** Worker 采用 hourly polling，配置参数 `DAILY_SYNC_EARLIEST_ATTEMPT_ET`（默认 `20:00` 美东）作为当日首次尝试下限。

### 4.5 限速与稳定性

- 全局 10 requests/second；所有 EDGAR 请求通过统一全局 rate limiter。
- User-Agent 从环境变量读取；`SEC_CONTACT_EMAIL` 缺失时系统启动 fail-fast。
- 禁止绕过统一 SEC client 直接调用 EDGAR。
- 网络失败使用 exponential backoff，最大退避 5 分钟，最大重试 5 次。
- daily index 下载结果保存 raw document。

---

## 5. Smart Routing：正确期间归属

### 5.1 核心规则

```text
report_period = parsed periodOfReport
report_quarter = normalize(report_period)
```

不能使用 sync date、filing accepted date、daily index date、当前系统日期作为报告季度。

### 5.2 延迟申报处理

13F-HR for 2026-03-31 在 2026-05-10 提交：

```text
report_quarter = 2026-Q1
quarter_end_date = 2026-03-31
filing_date = 2026-05-10
```

Oracle's Lens 展示时显示：

```text
Holdings data as of 2026-03-31. Managers file 13F reports up to 45 calendar days after quarter end,
so current-quarter data may update until approximately [official_filing_deadline].
```

### 5.3 periodOfReport 异常处理（权威定义）

| 异常类型 | 处理策略 |
| --- | --- |
| 字段缺失 | `parse_status=needs_review`，`PERIOD_MISSING`，不进入 product-facing holdings，等待 admin 人工确认 |
| 日期格式不合法 | `parse_status=failed`，写入具体错误，不阻塞其他 filings |
| ±1–2 日，满足归一化条件 | 归一化到最近标准季末，`PERIOD_WEEKEND_ADJUSTED` |
| ±1–2 日，不满足归一化条件 | `needs_review`，`PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE` |
| ±3–5 日 | `needs_review`，`PERIOD_TOO_FAR_FROM_QUARTER_END` |
| > ±5 日 | 同上 |
| accepted_at 与归属季度相差 > 3 个季度 | `PERIOD_SUSPICIOUSLY_STALE`，需 admin 确认后才参与分析 |

**±1–2 日归一化的两个前提：**

1. form_type 为 13F-HR 或 13F-HR/A。
2. `accepted_at` 落在 valid filing window 内：`quarter_end_date ≤ accepted_at ≤ quarter_end_date + 180 days`。

---

## 6. Filing 去重、可重入与 Amendment Policy

### 6.1 去重键

SEC accession number 是 filing 级别唯一键：

- 同一个 accession number 只能有一条 filing record。
- 同一个 accession number 的 holdings 解析必须可重入。
- 重跑同一 accession 不得产生重复 holdings。

### 6.2 两道去重防火墙

#### 第一层：Accession Number

按以下状态决定是否跳过：

| 现有 accession 状态 | 处理 |
| --- | --- |
| `parse_status=succeeded` 且无 reparse flag | 跳过，记入 `skipped_existing_accessions` |
| `parse_status=failed` | 重试 |
| `parse_status=partial_success` | 重试 |
| `parse_status=needs_review` | 跳过；超 7 天未处理触发 P3 告警 |
| `parser_version` 低于当前版本 | 触发 reparse |
| raw document 损坏或缺失 | 重新下载，触发 reparse |

#### 第二层：Holding Row Fingerprint（行标识指纹）

`source_row_index` 必须在任何过滤/清洗之前，从原始 XML 行顺序赋值（0-indexed）。

```text
holding_row_fingerprint = sha256(
  parse_run_id,              -- 纳入 parse_run_id，确保不同 parse run 的相同内容可独立存储
  source_row_index,
  normalized_name_of_issuer,
  normalized_title_of_class,
  normalized_cusip,
  value_raw,                 -- 使用 SEC XML 原始值，避免 derived value 修复导致 fingerprint 漂移
  value_unit_raw,
  ssh_prnamt,
  ssh_prnamt_type,
  put_call,
  investment_discretion,
  other_managers_raw
)
```

唯一约束：`UNIQUE (parse_run_id, holding_row_fingerprint)`。

### 6.3 Parse Runs：审计版本化（解决 reparse 与审计保留的冲突）

每次解析一个 accession，创建一个 `parse_run` 记录。Holdings 通过 `parse_run_id` 关联到具体的解析运行，从而支持：

- 完整审计历史（每次 reparse 的输出均保留）。
- 不需要 DELETE 旧 holdings（消除 §6.4 原子替换与审计保留之间的冲突）。
- 产品查询通过 `is_current=true` 的 parse_run 访问当前 holdings。

**`parse_runs` 表：**

```text
id
accession_number
job_run_id          -- FK → job_runs.id（触发本次 parse 的 job；watchdog 通过此字段查 lease 状态）
parser_version
fingerprint_version
started_at
finished_at
status              -- running / succeeded / failed / abandoned
holdings_count
error
is_current          -- 仅一个 parse_run per accession 可为 true（partial unique）
created_at
```

**PARTIAL UNIQUE index:** `UNIQUE (accession_number) WHERE is_current = true`

**Reparse 写入顺序（两阶段，不再需要 DELETE）：**

```sql
-- 阶段 1：立即持久化 parse_run 记录（独立事务，失败也保留审计）
BEGIN;
  INSERT INTO parse_runs (accession_number, parser_version, fingerprint_version, status, started_at)
    VALUES (:accession, :parser_version, :fingerprint_version, 'running', now())
    RETURNING id INTO :new_parse_run_id;
COMMIT;
-- 此时 is_current=false（新 parse_run 尚未激活），旧 parse_run 仍为 is_current=true

-- 阶段 2：holdings 写入 + is_current 切换（独立事务）
BEGIN;
  -- 2a. bulk insert new holdings（不删除旧 holdings）
  INSERT INTO holdings_13f (parse_run_id, ...) VALUES (:new_parse_run_id, ...);

  -- 2b. 切换 current parse_run
  UPDATE parse_runs SET is_current = false WHERE accession_number = :accession AND is_current = true;
  UPDATE parse_runs SET is_current = true, status = 'succeeded', finished_at = now(),
                        holdings_count = :count WHERE id = :new_parse_run_id;

  -- 2c. 更新 filing 状态
  UPDATE filings_13f
    SET parse_status = 'succeeded', parser_version = :parser_version,
        total_13f_reported_value_usd = :total_all,
        total_13f_common_value_usd = :total_common,
        updated_at = now()
    WHERE accession_number = :accession;
COMMIT;

-- 阶段 2 失败时：外层 catch 执行以下清理（不影响 is_current 状态）
UPDATE parse_runs
  SET status = 'failed', finished_at = now(), error = :error_message
  WHERE id = :new_parse_run_id;
-- 旧 parse_run 保持 is_current=true；filing 保持 retryable 状态；失败审计永久保留
```

**两阶段设计说明：**
- 阶段 1 独立提交：确保即使阶段 2 失败，`parse_run.status=failed` + `error` 也能持久保存，提供完整的失败审计记录。
- 阶段 2 整体回滚：holdings 写入和 is_current 切换仍在同一事务，保证原子性；不会出现部分 holdings 可见的中间状态。

**Orphan parse_run 处理（进程崩溃场景）：**

若进程在阶段 1 commit 后、阶段 2 完成前崩溃，catch 不会执行，`parse_run.status` 会永久停在 `running`。必须有 watchdog 机制处理此场景：

- **Watchdog 规则：** `parse_run.status=running` 且 `started_at < now() - :parse_job_timeout` 且 `job_runs[job_run_id].lease_expires_at < now()`（即关联 job 的 lease 已过期）→ 标记 `parse_run.status='abandoned'`，`error='process_crash_or_timeout'`，`finished_at=now()`。
- `abandoned` 状态在审计、Admin UI、告警中与 `failed` 相同处理（不阻断 is_current，可重新触发 parse）。
- 实现位置：`quality_check` job 定期扫描，或 `ingest_holdings_for_quarter` 启动时先清理同 accession 的 stale running parse_runs。
- `:parse_job_timeout` 与 §12.4 的 `ingest_filing` job 超时配置同源（默认 10 分钟）。

### 6.4 可重入要求

| 操作 | 可重入要求 |
| --- | --- |
| daily index fetch | 相同 sync date 可重复下载或复用 raw document |
| filing metadata ingest | accession number upsert |
| information table fetch | accession-level raw document versioned |
| holdings parse | 创建新 parse_run，不删除旧 holdings |
| quarter backfill | 已成功 accession 跳过，失败 accession 可重试 |

### 6.5 Job 锁与心跳

- Job 启动时获取带过期时间的 lease token，定期刷新（heartbeat）。
- 只有 lease owner 才能写入；接管 failed job 前须先确认原 worker lease 已过期。

### 6.6 Amendment Policy

**Amendment Type（13F/A XML `<amendmentType>` 字段）：**

| Amendment Type | 含义 | 处理策略 |
| --- | --- | --- |
| `RESTATEMENT` | 完整重申所有持仓 | 解析成功后原子替换 active filing（见下方流程） |
| `NEW HOLDINGS` | filer 未提交过当季原始 13F | 默认 `needs_review`，`amendments_pending`；admin 通过 `activate_as_original` action 确认后才激活 |
| `ADDITIONS CORRECTIONS DELETIONS` | 部分持仓增删改 | `amendments_pending`，不自动合并 |
| 字段缺失 / 无法解析 | 无法判断替换范围 | `amendments_pending`，不自动覆盖 |

**RESTATEMENT 替换流程（审计保留原则）：**

**原始 filing 记录（`filings_13f` 行）及其关联的所有 `parse_runs` 和 `holdings_13f` 行永远不删除，用于审计。** 产品侧通过 `is_active_for_manager_period=true` 切换到 amendment accession 的当前 parse_run 的 holdings；amendment 和原始 filing 是两个独立的 accession，各自有独立的 parse_runs。

```text
1. 解析新 amendment filing，创建新 parse_run，bulk insert holdings
2. 若解析成功（parse_status = succeeded）：
   BEGIN TRANSACTION
     旧 active filing: is_active_for_manager_period = false
     新 filing: is_active_for_manager_period = true
     -- 原始 filing 的 parse_runs 和 holdings 保留，仅修改 active 标志
   COMMIT
   产品查询: is_active_for_manager_period=true → 新 accession → is_current parse_run → holdings
3. 若解析失败：
   旧 active filing 保持不变，继续服务
   新 filing: parse_status = failed / amendment_status = amendment_failed
```

**多 RESTATEMENT 排序：** 以 `accepted_at` 最晚者为 active；`accepted_at` 相同时，不自动切换，标记 `amendments_pending` + `amendment_sort_warning=true`，等待 admin 确认。

Amendment 状态：`no_amendments_seen` / `amendments_applied` / `amendments_pending` / `amendment_failed`

---

## 7. Holdings 数据模型与计算

### 7.1 Filing 字段

建议 `filings_13f` 至少包含：

```text
id
manager_id
cik
accession_number                      -- UNIQUE 约束
form_type                             -- 13F-HR / 13F-HR/A / 13F-NT
report_type                           -- holdings_report | combination_report | notice_report
                                      -- 解析自 cover page <reportType>，是 form_type 的子分类
coverage_completeness                 -- complete | partial | unknown
                                      -- holdings_report → complete
                                      -- combination_report → partial
                                      -- notice_report → 无直接 holdings（reported elsewhere）
coverage_type                         -- normal | combination_partial | notice_reported_elsewhere | confidential_treatment_applied | coverage_gap
                                      -- manager-quarter 覆盖语义；用于 readiness / Oracle's Lens caveat，不替代 report_type
other_managers_included               -- JSON 数组：combination_report 中由其他 manager 代报的 manager 列表（name / manager_number / CIK / file_number，能解析多少存多少）
other_managers_reporting              -- JSON 数组：13F-NT 中代报本 manager 持仓的 manager 列表（name / CIK / file_number，能解析多少存多少）
has_confidential_treatment            -- bool：cover page Summary Page 中 confidential treatment checkbox
confidential_treatment_status         -- none | applied | amendment_expected
                                      -- applied: 当前 public filing 已省略部分持仓
                                      -- amendment_expected: 预期后续 amendment 补充 confidential holdings
filing_date
accepted_at
period_of_report
report_quarter
quarter_end_date
official_filing_deadline              -- quarter_end + 45 days，调整到下一工作日（若落在周末/节假日）
is_amendment
amends_accession_number
amendment_type                        -- RESTATEMENT | NEW_HOLDINGS | ADDITIONS_CORRECTIONS_DELETIONS | unknown
amendment_type_raw
is_active_for_manager_period          -- PARTIAL UNIQUE: (manager_id, quarter_end_date) WHERE true
raw_filing_url
raw_infotable_url
parse_status
parse_warning
parse_error
parser_version
form_spec_version                     -- SEC EDGAR 提交的 schema/spec 版本，用于值单位解析（见 §7.2）
xml_schema_version                    -- 从 XML root / namespace / schemaLocation 提取的 schema version；与 form_spec_version 一起审计单位判断
total_13f_reported_value_usd          -- 所有 holdings value 合计（仅 report_type=holdings_report 的 complete filings 有意义）
total_13f_common_value_usd            -- common shares value 合计
holdings_count
common_holdings_count
amendment_status
amendment_sort_warning
created_at
updated_at
```

说明：

- `report_type=combination_report` 时，`coverage_completeness=partial`；此类 filing 在 Oracle's Lens 中必须展示 caveat，不能作为完整 manager portfolio。
- `has_confidential_treatment=true` 时，readiness 至多 `usable_with_warning`；用户侧显示 "Some holdings may be omitted due to confidential treatment applied to this filing."
- `form_spec_version` / `xml_schema_version`：从 EDGAR XML header、root element、namespace 或 schemaLocation 提取，用于 parser 判断值单位（见 §7.2）；不得只按 filing date 推断。
- `official_filing_deadline` 应在 filing 入库时计算并存储，后续 filing window 判断、告警触发均引用此字段，不使用裸 `quarter_end + 45`。

### 7.2 Holdings 字段

建议 `holdings_13f` 至少包含：

```text
id
parse_run_id                          -- FK to parse_runs.id（关键：holdings 通过 parse_run 而非直接 accession 关联）
filing_id
manager_id
accession_number
report_quarter
quarter_end_date
name_of_issuer
title_of_class
cusip
value_raw                             -- SEC XML 中的原始值（未换算）
value_unit_raw                        -- 原始声明单位（thousands / dollars / unknown）
value_parse_rule                      -- 解析时使用的规则（schema_thousands / schema_dollars / manager_override / inferred）
value_usd                             -- 标准化 USD 值（以 dollars 为单位，非 thousands）
                                      -- 所有金额分析均使用此字段；如原始单位为 thousands，此处已 ×1000
ssh_prnamt
ssh_prnamt_type
put_call                              -- NULL=common share; 'Put'; 'Call'
investment_discretion
other_managers_raw                    -- Column 7 原始值（逗号分隔 manager numbers）
holding_attribution_status            -- 持仓归因状态：direct | shared | reported_for_other | unresolved
voting_sole
voting_shared
voting_none
stock_id
cusip_mapping_status                  -- holding-level CUSIP enrichment result: linked | invalid_cusip | unresolved | pending_mapping | needs_review
                                      -- 不等同于 cusip_ticker_map.mapping_status（mapping lifecycle）
portfolio_weight_pct                  -- (value_usd / filing.total_13f_common_value_usd) * 100
                                      -- 分母和 numerator 均为 USD（dollars）口径，单位一致
                                      -- 仅 common shares（put_call IS NULL）有效；options 行为 null
                                      -- 仅 coverage_completeness=complete 时可用于跨 manager 权重比较；partial filing 中为 null 或仅 caveated 展示
                                      -- MVP 1B 写入时为 null，MVP 2 计算填充
holding_row_fingerprint
fingerprint_version
source_row_index
created_at
updated_at
```

**金额单位处理规则（关键）：**

SEC Form 13F Information Table 的值单位随 filing schema 版本变化。Parser 必须按以下规则处理，不能假设所有 filing 都是 thousands：

1. **优先**：从 EDGAR XML root / namespace / schemaLocation / form_spec_version 确定单位声明；parser 必须显式识别 2023-01-03 起 amended Form 13F 的 nearest-dollar 口径（而非 nearest-thousand）。
2. **次之**：若 schema 无明确单位声明，参考 SEC Form 13F Instructions 对应年份的单位规定（工程实现时必须测试 2022 及以前、2023 及以后两套 fixtures）。
3. **最后**：若无法确定，标记 `value_parse_rule=inferred`，`parse_warning=VALUE_UNIT_UNCERTAIN`。
4. Manager-level `value_unit_override ≠ infer` 时：作为强制覆盖，`value_parse_rule=manager_override`。
5. `manager_override` 在 MVP 1 表示 manager-level override；filing-level override 是 MVP 3 扩展，同一枚举值保留用于后续 filing-level audit。

`value_usd` 是产品和分析层的唯一金额字段，统一以 USD（dollars）存储；`value_raw` + `value_unit_raw` + `value_parse_rule` 用于审计和 reparse。

**持仓归因规则（`holding_attribution_status` 计算）：**

13F Information Table Column 6（Investment Discretion）决定该持仓的投资决策归属。Parser 在写入 holdings 时必须同时计算 `holding_attribution_status`。

**XML 原始值 → 规范化映射（必须在 parser 层实施）：**

| SEC XML 原始值 | 含义（SEC Form 13F Column 6 说明） | normalized `investment_discretion` |
| --- | --- | --- |
| `SOLE` | Sole discretion | `SOLE` |
| `DFND` | Defined（由封面页定义，如 Combination Report 子 manager） | `DFND` |
| `DEFINED` | 同 `DFND`（部分 filer 使用完整拼写） | `DFND`（normalize 到 `DFND`） |
| `OTR` | Other（与封面页以外的其他 manager 共享） | `OTR` |
| `OTHER` | 同 `OTR`（部分 filer 使用完整拼写） | `OTR`（normalize 到 `OTR`） |
| `SHARED` | 同 `OTR`（非标准但出现在实际 XML 中） | `OTR`（normalize 到 `OTR`） |

Parser 必须将所有变体 normalize 到规范值（`SOLE / DFND / OTR`）再存储；未知值存原始并标 `unresolved`。

**`holding_attribution_status` 计算规则：**

| normalized `investment_discretion` | `other_managers_raw` | `holding_attribution_status` | 含义 |
| --- | --- | --- | --- |
| `SOLE` | any | `direct` | 申报机构独立持有，可直接用于共识分析 |
| `OTR` | any | `shared` | 与其他机构共享投资决策，可能重复计算 |
| `DFND` | parseable manager numbers | `reported_for_other` | 由封面页定义，申报机构代其他机构报告（Combination Report 常见） |
| `DFND` | empty / unparseable | `unresolved` | 无法确定实际持有方，需排除或加 caveat |
| unknown / parse error | any | `unresolved` | 字段异常，归因不可用 |

**产品端归因使用规则：**

- `/stocks/{stock_id}/holders` 和共识信号（manager consensus、superinvestor overlap）**默认仅使用 `holding_attribution_status=direct` 的 holdings**。
- `shared` 和 `unresolved` 持仓：从共识计数中排除，或在 UI 显示 "Attribution uncertain" caveat 后单独展示。
- `reported_for_other`：如 `other_managers_raw` 中的 manager number 可解析为已知 manager，归因到该 manager（MVP 3 扩展）；MVP 1–2 中视同 `unresolved` 处理。
- **目的：** 防止 parent/subsidiary 共同申报、Combination Report 代报等场景导致的"同一持仓被计为多个独立 value manager 共识"的误读。

### 7.3 Parse Runs 表

见 §6.3。产品查询 holdings 时必须 JOIN `parse_runs` 并过滤 `is_current=true`，不得直接查询所有 `holdings_13f` 行。

### 7.4 持仓变化计算

持仓变化必须基于同一 manager、同一证券、连续报告季度的 active filing 的 current parse_run holdings。

**仅 `coverage_completeness=complete` 的 filing 可用于变化计算和 total value 计算；`partial` 的 Combination Report 只展示 snapshot，需标注 caveat。**

**安全证券匹配优先级：**

1. 两季度均有可信 `stock_id`：以 `stock_id` + `ssh_prnamt_type` + `put_call` 作为主匹配键。
2. 任一季度缺少 `stock_id`：fallback 到 normalized CUSIP + `ssh_prnamt_type` + `put_call`。
3. CUSIP 变化但映射到同一 `stock_id`：识别为同一证券，标记 `CUSIP_CHANGED`，不视为 exit + new。
4. 均无法匹配：`change_status=unresolvable`。

**prior quarter 数据缺失规则：**

- 若因数据 gap，前一季度持仓不可知：`change_status=no_prior_data`，**不标记为 `new_position`**。
- 若前一季度 manager 提交 13F-NT（holdings reported elsewhere）：**不能据此断言上一季度无持仓**；`change_status=no_prior_data`（因为我们没有直接的 prior holdings 数据）。
- 若 manager 当季和前季均有 active filing，且前季 filing 的 information table 确认该证券不在其中：`change_status=new_position`。

**`put_call` 隔离规则：** options 和 common shares 必须分开计算。

基础分类：`new_position` / `exited_position` / `increased` / `reduced` / `unchanged` / `no_prior_data` / `unresolvable`

**Corporate action 启发式检测（heuristic，仅供参考，标记 "possible"，不作确定性判断）：**

| 阈值 | 说明 |
| --- | --- |
| `share_change_pct` > +90% 或 < -47% | 可能 2:1 拆股或合股 |
| `share_change_pct` > +190% 或 < -65% | 可能 3:1 拆股或合股 |
| `share_change_pct` > +400% 或 < -80% | 可能 5:1+ 拆股或合股 |
| CUSIP 变更（`CUSIP_CHANGED` 已标记） | 可能 corporate action |

---

## 8. CUSIP 映射与证券关联

### 8.1 目标

将 holdings 中的 CUSIP 映射到系统内部 `stock_id`，支持跨 manager 的证券聚合分析。

### 8.2 映射优先级（序号越小优先级越高）

1. **手动映射（最高优先级）**：admin 维护，`source="manual"`，覆盖所有自动映射。
2. **OpenFIGI API**：`https://api.openfigi.com/v3/mapping`，`source="openfigi"`。API key 从 `OPENFIGI_API_KEY` 读取；独立 rate limiter；同一 CUSIP 查询结果缓存 TTL=30 天；请求失败时降级为 `pending_mapping`，不阻塞 ingestion。
3. **Dataroma 持仓交叉引用**（MVP 3 实现）：`source="dataroma"`。
4. **SEC co_tickers 交叉引用**：提供 CIK ↔ ticker（不提供 CUSIP），可补充 ticker，`source="sec_co_tickers"`。
5. **无法映射**：`stock_id=null`，`cusip_mapping_status=unresolved`。

### 8.3 cusip_ticker_map 表结构

```text
id
cusip
ticker
exchange
security_type               -- common_stock | etf | option | preferred | bond | other | unknown
                            -- 必须校验 security_type，不能把 option/bond CUSIP 映射为 common stock stock_id
stock_id
source
candidate_rank              -- 同一 (cusip, source) 下的候选排名（1 = best match）
confidence
effective_from_quarter      -- YYYY-QN，映射生效的起始季度（处理 corporate action、share class 变化）
effective_to_quarter        -- YYYY-QN or null（null = 至今有效）
evidence_url
reviewed_by
reviewed_at
mapping_status              -- confirmed | superseded | needs_review | deleted（见下方说明）
created_at
updated_at
```

**`mapping_status` 语义：**

| 值 | 含义 | 历史查询可返回 | 共识统计可用 |
| --- | --- | --- | --- |
| `confirmed` | admin 审核通过、当前有效 | ✓ | ✓ |
| `superseded` | 曾有效，因 corporate action 被新 mapping 取代；历史查询仍须返回它 | ✓ | 按时间区间判断 |
| `needs_review` | 多 source 有候选但尚未 admin 确认 | ✗（不用于产品） | ✗ |
| `deleted` | admin 手动停用，永久排除 | ✗ | ✗ |

**唯一约束（候选行级别）：** `UNIQUE (cusip, source, ticker, exchange, effective_from_quarter)`

**有效区间不重叠约束：** 同一 CUSIP 的 `mapping_status IN ('confirmed', 'superseded')` 行，其 `(effective_from_quarter, effective_to_quarter)` 有效区间不得重叠。纯应用层 overlap check 有并发窗口（两个并发写入均通过检查后同时提交），必须配合以下机制之一消除竞争：

- **MVP 方案（推荐）：** 写入 cusip_ticker_map 前，在同一事务内取 `pg_advisory_xact_lock(hashtext(cusip))`，再做 overlap 检查，再 INSERT。事务结束时锁自动释放；同一 CUSIP 的并发写入序列化执行。
- **长期方案（P2）：** 将 `effective_from_quarter / effective_to_quarter` 转换为 `daterange` 并加 `EXCLUDE USING gist (cusip WITH =, quarter_range WITH &&) WHERE (mapping_status IN ('confirmed','superseded'))`；DB 层原生互斥。

工程实现时选择 MVP 方案，并在注释中标注 long-term exclusion constraint 升级路径。

**时间有效性查询（as-of 季度查询）：**

```sql
SELECT * FROM cusip_ticker_map
WHERE cusip = :cusip
  AND mapping_status IN ('confirmed', 'superseded')
  AND effective_from_quarter <= :query_quarter
  AND (effective_to_quarter IS NULL OR effective_to_quarter >= :query_quarter)
ORDER BY candidate_rank ASC
LIMIT 1
```

此查询同时返回当前有效的 `confirmed` mapping 和历史已 superseded 的 mapping（用于历史季度查询），不需要将 `superseded` 行排除。

**Corporate action 处理：** 当公司发生拆股、合并、share class 变化时：
1. 关闭旧 mapping：`UPDATE ... SET effective_to_quarter = :last_valid_quarter, mapping_status = 'superseded'`（不是 `deleted`；历史季度仍可查到它）
2. 创建新 mapping（新 CUSIP → ticker），`effective_from_quarter = :change_effective_quarter, mapping_status = 'confirmed'`

### 8.4 CUSIP 数据质量问题

| 问题 | 处理策略 |
| --- | --- |
| CUSIP 为全零 | `cusip_mapping_status=invalid_cusip` |
| CUSIP 长度不足 9 位 | `cusip_mapping_status=invalid_cusip`，不自动补零 |
| 同一 CUSIP 对应多个候选 | 存入多行（`candidate_rank` 区分），标记 `needs_review` |
| CUSIP 对应已退市证券 | 保留映射，`stock_delisted=true`；前端标注已退市，价格字段 `unavailable` |
| Admin 停用某映射 | `PATCH mapping_status=deleted`，保留历史记录；区别于 `superseded`（corporate action 自动设置） |

### 8.5 CUSIP 映射 job 与告警

- `enrich_cusip:{report_quarter}` job 在每季度 filing 解析完成后自动触发。
- 告警阈值与 readiness 阈值同源配置（`CUSIP_MAPPING_P1_THRESHOLD=0.50`，`CUSIP_MAPPING_READY_THRESHOLD=0.70`）。
- common share CUSIP 映射率 < 70%（**filing window 已关闭**）：P2 告警。
- common share CUSIP 映射率 < 50%（**filing window 已关闭**）：P1 告警。

---

## 9. 历史覆盖与 Oracle's Lens 功能门控

Oracle's Lens 不应在历史数据不足时暗示趋势洞察。

| 历史覆盖 | 可用能力 | 备注 |
| --- | --- | --- |
| 1 个季度 | 当前持仓快照 | 无趋势、无变化信号 |
| 2 个连续季度 | 基础变化：新增、退出、加仓、减仓 | 仅 `coverage_completeness=complete` 的季度参与 |
| 4 个连续季度 | 年度趋势、持有持续性 | |
| 8 个连续季度 | 多年持仓模式、周期性判断 | |

**"连续"与中断的定义：**

| 情形 | 对 streak | 对 historical coverage |
| --- | --- | --- |
| 有 active filing，`coverage_completeness=complete` | 不中断 | 计入有效季度 |
| 有 active filing，`coverage_completeness=partial`（Combination Report） | 不中断，但该季度变化计算受限 | 标记 `coverage_type=combination_partial`，需 caveat |
| Manager 提交 13F-NT（holdings reported elsewhere） | streak 上下文依赖：因无直接持仓数据，某证券的 streak 视为需要中断确认 | 标记 `coverage_type=notice_reported_elsewhere`，**不视为 data gap** |
| Manager 应申报但无 filing | 中断 | `coverage_gap` |
| `has_confidential_treatment=true` | 不中断，但该季度 holdings 可能不完整 | 标记 `coverage_type=confidential_treatment_applied`，需 caveat |

**13F-NT 的 streak 处理：** 因 13F-NT manager 的持仓由其他 manager 代报，系统无法直接从 13F-NT 获取该 manager 的持仓信息。对于 streak 计算，应标记为 `no_direct_holdings_data`，不能断言持仓中断或新增。

Readiness payload 应包含：

```text
historical_coverage_quarters
consecutive_quarters_available
supports_snapshot
supports_basic_change
supports_annual_trend
supports_multi_year_pattern
data_gap_quarters
nt_quarters                           -- 13F-NT 季度列表（notice_reported_elsewhere）
confidential_treatment_quarters       -- 有 confidential treatment 的季度
partial_coverage_quarters             -- combination report 季度
```

### 9.2 Oracle's Lens 价值投资者信号定义

Oracle's Lens 的定位是**高质量投资人关注列表 + 行为变化提示**，不是结论型推荐或买卖信号。13F 数据只负责发现"谁在关注这只股票、行为如何变化"，最终候选排序须叠加估值、财务质量等基本面字段才有意义。

#### 9.2.1 可展示的信号类型

| 信号 | 说明 | 所需数据最低版本 |
| --- | --- | --- |
| Manager 持仓快照 | 某季度末 direct holdings（`holding_attribution_status=direct`），含持仓数量、权重、价值 | MVP 1B |
| 首次进入（New Position） | 上季度无持仓、本季度有持仓（`change_status=new_position`） | MVP 2 |
| 完全退出（Exit） | 上季度有持仓、本季度无持仓（`change_status=exited_position`） | MVP 2 |
| 连续加仓（Consecutive Adds） | 连续 N 季度 `change_status=increased`，N ≥ 2 | MVP 2 |
| 持有季度数（Holding Duration） | 该 manager 持有该股的连续季度数 | MVP 2 |
| Portfolio Weight（13F Common Weight） | `portfolio_weight_pct`（仅 common shares，分母为 `total_13f_common_value_usd`） | MVP 2 |
| Manager Consensus / Overlap | 同一股票的 direct-holder 数量，按 `manager_type` 过滤 | MVP 2 |
| Superinvestor Overlap | `featured=true` manager 中持有该股的数量和变化方向 | MVP 2 |

#### 9.2.2 默认降权 / 排除规则

下列场景的 holdings **不计入共识统计**，或须显示 caveat：

| 场景 | 排除原因 | 处理 |
| --- | --- | --- |
| `manager_type=index_like` | 被动持仓，不反映主动 conviction | 从共识计数排除；可单独展示 |
| `manager_type=quant` | 高换手量化，13F 滞后性使信号失效（45 天延迟时头寸可能已清仓） | 同上 |
| `put_call IS NOT NULL`（options） | 期权头寸结构复杂，无法直接对比 common shares | 分离展示，不计入 common weight |
| `holding_attribution_status=shared` | 可能重复计算（parent/subsidiary 共同申报） | 排除共识计数，UI 显示 "Attribution uncertain" |
| `holding_attribution_status=unresolved` | 归因不明 | 同上 |
| `coverage_type=notice_reported_elsewhere`（13F-NT） | 持仓由其他 manager 代报，本 manager 无直接 holdings table | 不计入 direct consensus；保留 reported-by 关系用于 MVP 3+ 归并视图 |
| `coverage_completeness=partial`（Combination Report） | 持仓不完整，无法用于 total portfolio value | 加 caveat，不参与跨 manager 权重比较 |
| `has_confidential_treatment=true` | 部分持仓被保密，快照不完整 | 加 caveat |
| `change_status=cusip_changed` | CUSIP 因 corporate action 变化，不是真实退出+新建 | UI 标注 "CUSIP Changed (Corporate Action)" |

#### 9.2.3 候选股页面（Stock Holder Aggregation）

`GET /api/v1/13f/stocks/{stock_id}/holders` 聚合结果须包含：

```text
direct_holder_count            -- holding_attribution_status=direct 的 manager 数
value_manager_direct_count     -- manager_type IN (fundamental_long, activist) 且 direct 的数量
featured_holder_count          -- featured=true 且 direct 的数量
top_holders[]                  -- 前 N 名 direct holders（按 portfolio_weight_pct DESC）
recent_changes[]               -- 本季 vs 上季变化（new_position / increased / reduced / exited_position）
attribution_caveat_count       -- shared + unresolved 的 holder 数（UI 提示）
data_caveats[]                 -- 适用的 caveat 列表（confidential/partial/nt_quarter 等）
as_of_quarter                  -- 数据对应季度
```

**前端展示原则：**
- 页面顶部显示 `as_of_quarter` 和数据 caveat（confidential、partial、13F-NT 等）。
- 明确注明"本页数据为 13F 季度快照，存在最长 45 天披露延迟；不构成投资建议。"
- `featured_holder_count` 和共识信号定位为"高质量投资人关注度参考"，不翻译为"买入推荐"。

#### 9.2.4 与 Value Line 数据的集成原则

13F 负责发现**兴趣信号和行为变化**；最终候选股排序须叠加基本面维度，不能单独依赖 13F：

| 13F 信号（行为） | Value Line 基本面维度（质量） | 集成方式 |
| --- | --- | --- |
| direct holder count / consensus | 财务强度（Financial Strength） | 过滤 / 加权 |
| 首次进入 / 连续加仓 | 盈利稳定性（Earnings Stability） | 信号叠加 |
| portfolio_weight_pct | 估值排名（Price/Earnings Ranking） | 联合排序 |
| superinvestor overlap | 安全边际（Safety Rank） | 上层候选筛选条件 |

MVP 1–2 中，13F 信号和 Value Line 字段在数据层共存（均以 `stock_id` 关联），但 Oracle's Lens UI 不自动合并成"评分"；该逻辑推迟到 MVP 3 或独立 product track。
上表所有集成方式均为 MVP 3+ roadmap；MVP 1–2 只展示 13F 行为信号本身和必要 caveat，不做联合评分或联合排序。

---

## 10. Readiness 与数据质量

### 10.1 Readiness Levels

| Level | 含义 | Oracle's Lens 行为 |
| --- | --- | --- |
| `unavailable` | 无可用 holdings | 显示 setup / unavailable 状态 |
| `experimental` | 有数据但覆盖弱 | Admin only 或强提示 |
| `usable_with_warning` | 大部分数据可用但有缺口 | 展示并提示 caveat |
| `ready` | 足够完整用于用户功能 | 正常展示 |

**`ready` 的最低标准（V1）：**

- 至少 1 个季度中，**expected filers** 覆盖率 ≥ 80%（`official_filing_deadline` 后统计）。
- 该季度 filing parse 成功率 ≥ 95%。
- 该季度 common share CUSIP 映射率 ≥ 70%。
- 无影响 latest usable quarter 的 `amendment_failed` 状态。
- 无影响 latest usable quarter 的 `amendments_pending`（任何 pending → 立即至多 `usable_with_warning`；超阈值后告警独立触发，见 §15.2）。
- latest usable quarter 中无 `has_confidential_treatment=true` 的 active filings（有则至多 `usable_with_warning`）。
- latest usable quarter 中无 `coverage_completeness=partial` 的 active filings 作为主要数据源（有则至多 `usable_with_warning`）。

**Expected filers 定义：**

某报告季度的 expected filers = `status=active` 的 managers，**排除**该季度已提交 **13F-NT** 的 managers（因其持仓由其他 manager 代报，属于合规提交，不应计入 coverage 缺口）。

**13F-NT 实现要求（MVP 1C-1 必须完成）：** 未实现 13F-NT 前，系统不得进入 `ready`；readiness API 暴露 `nt_detection_supported: false`；`coverage_ratio.estimated=true`。

### 10.2 质量指标

| 指标 | Numerator | Denominator |
| --- | --- | --- |
| `manager_coverage_ratio` | expected filers 中有 is_active_for_manager_period=true（13F-HR/HR/A）的 manager 数 | 本季度 expected filers 总数（排除 13F-NT） |
| `filing_parse_success_ratio` | `parse_status=succeeded` 的 filings 数 | 本季度所有已下载 filings 数 |
| `linked_common_holding_ratio` | `stock_id IS NOT NULL` 的 common share holdings 行数 | 本季度 active common share holdings 行数 |
| `linked_all_holding_ratio` | `stock_id IS NOT NULL` 的所有 holdings 行数 | 本季度所有 active holdings 行数 |
| `cusip_mapping_ratio` | CUSIP 已映射的 common share holdings 行数 | 本季度 active common share holdings 行数 |

其他指标：

```text
confirmed_manager_count
active_manager_count
expected_filer_count
filed_manager_count
nt_filer_count
combination_report_count          -- 本季度 combination report 数量
confidential_treatment_count      -- 本季度有 confidential treatment 的 filing 数量
amendment_handling_status
historical_coverage_quarters
latest_usable_quarter
last_successful_sync_at
nt_detection_supported
```

### 10.3 Zero vs Unavailable

- `0 failed filings` 表示检查过且失败数为 0。
- `null failed filings + unavailable_reason` 表示还没有检查。
- `null linked holdings ratio` 表示没有 denominator。

---

## 11. Admin Dashboard

### 11.1 主要页面

| 页面 | 目标 |
| --- | --- |
| Overview | 查看 13F 管线整体健康状态 |
| Managers | 维护 tracked managers 和 CIK |
| Daily Sync | 查看每日 form.idx 同步状态 |
| Filings | 查看 filings、parse status、amendments、report type |
| Holdings Coverage | 查看 holdings parse 和 stock link 覆盖率 |
| Jobs | 查看 job runs、失败原因、重试 |
| Readiness | 查看 Oracle's Lens 是否可用以及为什么不可用 |

### 11.2 Oracle's Lens Admin 指标

面向 admin 的就绪状态指标：

- 当前报告季度；`official_filing_deadline`；window 是否打开
- active managers 数量；expected filers 数量；nt_filer 数量
- combination_report 数量；confidential_treatment 数量
- 已申报 manager 数量；申报完成率（基于 expected filers）
- failed filings；pending amendments（按类型区分）
- linked_common_holding_ratio；CUSIP 映射率
- historical coverage depth；latest usable quarter
- nt_detection_supported

### 11.3 Jobs 页面过滤要求

过滤维度：`job_type`、`status`（所有有效状态：`queued`、`running`、`succeeded`、`partial_success`、`failed`、`cancel_requested`、`canceled`、`skipped`）、日期范围（`started_at`）、`sync_date`、`quarter`。分页：每页 50 条。

---

## 12. Job Runs、锁与重试

### 12.1 job_runs 字段

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
lease_token
lease_expires_at
started_at
finished_at
created_at
updated_at
```

注：conflict_group 由 scheduler 派生，不落库（V1）；如需可观测，MVP 2/3 可加入 `summary_json`。

### 12.2 Job 状态

`queued` / `running` / `succeeded` / `partial_success` / `failed` / `cancel_requested` / `canceled` / `skipped`

### 12.3 推荐 lock_key 与冲突规则

| Job Type | lock_key | 说明 |
| --- | --- | --- |
| `fetch_daily_index` | `fetch_daily_index:{sync_date}` | |
| `process_daily_index` | `process_daily_index:{sync_date}` | |
| `ingest_filing` | `ingest_filing:{accession_number}` | accession 粒度，同季度不同 accession 可并行 |
| `ingest_holdings_for_quarter` | `ingest_holdings:{report_quarter}` | 季度级入口锁；实际 filing 由 `ingest_filing` 子锁控制 |
| `retry_failed_filings` | `retry_failed_filings:{report_quarter}` | 与 `ingest_holdings_for_quarter` 共享 conflict group `quarter_ingestion:{report_quarter}` |
| `backfill_daily_indexes` | `backfill_daily_indexes:{start_date}:{end_date}` | |
| `enrich_cusip` | `enrich_cusip:{report_quarter}` | |
| `match_cik` | `match_cik:{manager_id}` | per manager |
| `quality_check` | `quality_check:{report_quarter}` | |

### 12.4 Job 超时规则

| Job Type | 建议超时 |
| --- | --- |
| `fetch_daily_index` | 5 分钟 |
| `ingest_filing`（单个 filing） | 10 分钟 |
| `ingest_holdings_for_quarter` | 60 分钟 |
| `backfill_daily_indexes` | 4 小时 |
| `enrich_cusip` | 30 分钟 |

---

## 13. API Requirements

```text
-- Admin: 系统状态
GET  /api/v1/admin/13f/status
GET  /api/v1/admin/13f/readiness

-- Admin: Manager 管理
GET  /api/v1/admin/13f/managers
POST /api/v1/admin/13f/managers
PATCH /api/v1/admin/13f/managers/{id}
POST /api/v1/admin/13f/managers/{id}/confirm-cik
POST /api/v1/admin/13f/managers/{id}/deactivate
POST /api/v1/admin/13f/managers/bulk-import
GET  /api/v1/admin/13f/managers/{id}/backfill-preview

-- Admin: Sync 状态与操作
GET  /api/v1/admin/13f/sync-dates
POST /api/v1/admin/13f/sync-dates/{date}/trigger

-- Admin: Filings 与 reparse
GET  /api/v1/admin/13f/filings
GET  /api/v1/admin/13f/filings/{accession_number}
POST /api/v1/admin/13f/filings/{accession_number}/reparse
PATCH /api/v1/admin/13f/filings/{accession_number}/period

-- Admin: Parse runs（审计）
GET  /api/v1/admin/13f/filings/{accession_number}/parse-runs   -- 查看某 accession 的所有 parse 历史

-- Admin: Amendment review
GET  /api/v1/admin/13f/amendments/pending
POST /api/v1/admin/13f/amendments/{accession_number}/resolve
  body: { action: "apply" | "activate_as_original" | "reject" | "defer" | "mark_informational" }
  -- apply: 触发 RESTATEMENT holdings 替换（仅限 amendment_type=RESTATEMENT）
  -- activate_as_original: 仅用于 NEW_HOLDINGS 类型，admin 确认后激活为 late original filing
  -- reject / defer / mark_informational: 见 §6.6

-- Admin: CUSIP 映射
GET  /api/v1/admin/13f/cusip-mappings
POST /api/v1/admin/13f/cusip-mappings
PATCH /api/v1/admin/13f/cusip-mappings/{id}    -- 软停用或更新 effective_to_quarter
GET  /api/v1/admin/13f/cusip-mappings/unresolved

-- Admin: Jobs（含 MVP 3 预留批量端点）
GET  /api/v1/admin/13f/jobs
POST /api/v1/admin/13f/jobs
POST /api/v1/admin/13f/jobs/{id}/cancel
POST /api/v1/admin/13f/jobs/retry-failed-filings
POST /api/v1/admin/13f/jobs/reparse-by-quarter     -- MVP 3
POST /api/v1/admin/13f/jobs/reparse-by-manager     -- MVP 3

-- Oracle's Lens（用户端）
GET  /api/v1/13f/readiness
GET  /api/v1/13f/managers
GET  /api/v1/13f/managers/{manager_id}/holdings
GET  /api/v1/13f/managers/{manager_id}/holdings/changes   -- MVP 2 启用；MVP 1 返回 HTTP 200 + status=unavailable
GET  /api/v1/13f/managers/{manager_id}/quarters
GET  /api/v1/13f/stocks/{stock_id}/holders
```

**Holdings changes 端点在覆盖不足时：** HTTP 200 + body `status=unavailable` + structured reason（不返回 HTTP 503，不返回空数组）。

**通用约定：** 列表接口分页（`?page=1&page_size=50`）；Admin 端点需要认证；用户端只返回用户功能所需字段；普通用户 API rate limit 100 req/min；Admin batch job trigger 的 rate limit 单独配置。

---

## 14. 性能要求

**注：以下 SQL 示例为 PostgreSQL 语法；非 Postgres 数据库需提前确认兼容性。**

| 场景 | 目标响应时间 | 说明 |
| --- | --- | --- |
| Oracle's Lens 持仓快照页加载 | P95 ≤ 500ms | 单 manager 单季度 holdings 列表 |
| Oracle's Lens 持仓变化计算 | P95 ≤ 800ms | 依赖 MVP 2 的 precomputed `ownership_changes` 表 |
| Admin dashboard overview | P95 ≤ 2s | |
| Admin filings 列表（分页） | P95 ≤ 1s | 50 条/页 |
| Daily sync job（单个 filing） | ≤ 10 分钟 | |
| 季度全量 backfill（100 managers） | ≤ 4 小时 | 含 rate limit 等待 |

关键数据库约束与索引（V1 migration 必须包含）：

```sql
-- Unique constraints
ALTER TABLE filings_13f ADD CONSTRAINT uq_filings_accession UNIQUE (accession_number);

-- parse_runs: 同一 accession 最多一个 is_current=true
CREATE UNIQUE INDEX uq_parse_run_current
  ON parse_runs (accession_number)
  WHERE is_current = true;

-- holdings: fingerprint per parse_run
ALTER TABLE holdings_13f
  ADD CONSTRAINT uq_holdings_fingerprint UNIQUE (parse_run_id, holding_row_fingerprint);

-- Active filing per manager+quarter
CREATE UNIQUE INDEX uq_active_filing_per_manager_period
  ON filings_13f (manager_id, quarter_end_date)
  WHERE is_active_for_manager_period = true;

-- CUSIP mapping: 候选行唯一（同 source + ticker + exchange + 起始季度只有一行）
ALTER TABLE cusip_ticker_map
  ADD CONSTRAINT uq_cusip_mapping UNIQUE (cusip, source, ticker, exchange, effective_from_quarter);

-- CUSIP mapping 有效区间不重叠（应用层校验，不走 DB partial unique）
-- 约束语义：同一 CUSIP，mapping_status IN ('confirmed','superseded') 的行，
--   (effective_from_quarter, effective_to_quarter) 区间不得重叠。
-- 由写入前 overlap 检查实施；违反则拒绝写入并告警。
-- 原有 UNIQUE(cusip) WHERE is_active=true 索引已删除：
--   is_active=false 语义不明（superseded vs deleted）；历史有效 mapping 不能以 inactive 排除出查询。

-- Query path indexes
CREATE INDEX idx_holdings_parse_run      ON holdings_13f (parse_run_id);
CREATE INDEX idx_holdings_manager_qend   ON holdings_13f (manager_id, quarter_end_date);
CREATE INDEX idx_holdings_manager_quarter ON holdings_13f (manager_id, report_quarter);
CREATE INDEX idx_holdings_cusip          ON holdings_13f (cusip);
CREATE INDEX idx_holdings_stock_id       ON holdings_13f (stock_id);
CREATE INDEX idx_holdings_put_call       ON holdings_13f (put_call);
CREATE INDEX idx_holdings_attribution    ON holdings_13f (holding_attribution_status);
CREATE INDEX idx_parse_runs_accession    ON parse_runs (accession_number);
CREATE INDEX idx_filings_manager_qend    ON filings_13f (manager_id, quarter_end_date);
CREATE INDEX idx_filings_manager_quarter ON filings_13f (manager_id, report_quarter);
CREATE INDEX idx_filings_active          ON filings_13f (is_active_for_manager_period);
CREATE INDEX idx_filings_parser_version  ON filings_13f (parser_version);
CREATE INDEX idx_sync_status             ON edgar_sync_status (status, sync_date);
CREATE INDEX idx_job_runs                ON job_runs (status, job_type, created_at);
CREATE INDEX idx_cusip_map_temporal
  ON cusip_ticker_map (cusip, effective_from_quarter, effective_to_quarter)
  WHERE mapping_status IN ('confirmed', 'superseded');
```

---

## 15. 监控与告警

### 15.1 告警级别

| 级别 | 含义 | 通知触达时效 | 通知渠道 |
| --- | --- | --- | --- |
| P1 | 数据管线完全中断或数据错误风险高 | ≤ 15 分钟 | Discord；Email 可选（`ALERT_EMAIL_ENABLED`） |
| P2 | 部分功能降级，需要当日处理 | ≤ 2 小时 | Discord（无 @mention） |
| P3 | 非紧急问题，需要跟踪 | ≤ 1 个工作日 | Discord 低优先级频道（无 @mention） |

### 15.2 触发告警的条件

| 条件 | 级别 | 备注 |
| --- | --- | --- |
| Daily sync 连续 2 个工作日 `failed` | P1 | 排除 no_index_expected_dates |
| 当季度 `official_filing_deadline` 后 3 天内，expected filer 覆盖率 < 70% | P1 | 70% 为告警警戒线，80% 为 ready 达标线 |
| 单个 filing ingest job 超时重试 3 次 | P2 | |
| Common share CUSIP 映射率 < 50%（window 已关闭） | P1 | |
| Common share CUSIP 映射率 50%–70%（window 已关闭） | P2 | |
| 存在 `amendment_failed` 超过 24 小时未处理 | P2 | |
| 影响 latest usable quarter 的 `amendments_pending`（RESTATEMENT 类型）超过 24 小时 | P2 | |
| 影响 latest usable quarter 的 `amendments_pending`（非 RESTATEMENT）超过 48 小时 | P2 | |
| `parse_status=needs_review` 超过 7 天未处理 | P3 | 防止 needs_review 永久卡死 |
| Job `running` 超过超时阈值未刷新 lease | P2 | |
| SEC EDGAR 请求连续收到 429 或 403 | P1 | 可能触发 IP 封禁 |
| Oracle's Lens readiness 在 window 已关闭季度从 `ready` 降级 | P2 | |
| Oracle's Lens readiness 在 window 已关闭季度降级至 `unavailable` | P1 | |

### 15.3 数据健康日报

每日美东时间 08:00 自动发送摘要到 Discord，包含：

- 昨日 sync 状态；当前季度 expected filer 覆盖率；nt_filer 数量
- combination_report 数量；confidential_treatment 数量
- 最新 failed filings 数量；待处理 amendments_pending 数量
- 最新 CUSIP 映射率（common shares）
- Oracle's Lens readiness 状态；nt_detection_supported 状态

---

## 16. UX Copy Principles

用户侧 13F 页面必须始终展示数据时效性。

推荐文案：

```text
Holdings data as of 2026-03-31. Managers file 13F reports up to 45 calendar days after quarter end,
so current-quarter data may update until approximately [official_filing_deadline].
```

规则：

- 说 "13F filings are delayed snapshots."；不说 "current holdings"、"guru cost basis"、"buy signal"。
- 不把缺失数据展示成 0。
- `total_13f_reported_value_usd` 标注：*"Based on 13F-reported securities only; does not represent total AUM."*
- API / 前端 label 中 `portfolio_weight_pct` 统一显示为 **"13F common weight"**。

**13F-NT Manager：** 展示为 *"This manager filed a 13F Notice; its 13(f) holdings are reported by other manager(s)."* 不得显示为数据缺失、空持仓、或 "No holdings"（因 holdings 客观存在，只是在其他 manager 的 filing 中）。

**Combination Report（coverage_completeness=partial）：** 展示 caveat：*"This is a 13F Combination Report. Some holdings are reported by other manager(s) and are not included here."*

**Confidential Treatment：** 展示 caveat：*"Some holdings may be omitted from this filing due to confidential treatment. Additional holdings may be disclosed in a future amendment."*

**Options：** 持仓变化信号默认仅基于 common shares；options 独立 tab 展示，不展示 "13F common weight"（null）。

---

## 17. MVP Delivery Plan

依赖顺序：1B 依赖 1A → 1C-1 依赖 1B → 1C-2 依赖 1C-1 → MVP 2 依赖 1C-2 → MVP 3 依赖 MVP 2。

### MVP 1A: Manager + Daily Index 基础设施

- Manager CRUD（含 `value_unit_override=infer` 默认；CIK EFTS search）
- 批量 CSV 导入
- `edgar_sync_status` 表
- daily form.idx fetch and parse（筛选 13F-HR / 13F-HR/A / **13F-NT**）
- `no_index_expected_dates` 维护机制
- 全局 EDGAR rate limiter；`SEC_CONTACT_EMAIL` fail-fast
- job_runs + lock_key + conflict group + lease token
- P1/P2/P3 告警基础设施（Discord webhook；email 可选）

### MVP 1B: Filing + Holdings Ingestion + Amendment Replacement

- Fetch 13F-HR / 13F-HR/A filing detail / information table
- **Fetch 13F-NT filing header**，从 `periodOfReport` 归属季度，解析 `other_managers_reporting`（含 CIK / 13F file number，能解析多少存多少），保存 raw document，标记 `coverage_type=notice_reported_elsewhere`
- **解析 cover page：** `report_type`（holdings_report / combination_report / notice_report）、`coverage_completeness`、`other_managers_included`、`has_confidential_treatment`
- **`form_spec_version` / `xml_schema_version` 解析；value 单位按 XML schema/root 版本确定，存储 `value_raw` + `value_unit_raw` + `value_parse_rule` + `value_usd`**
- `parse_runs` 表 + 软版本化写入（不 DELETE 旧 holdings）
- `source_row_index` 在过滤前赋值；`fingerprint_version`；`parser_version`
- 两层去重防火墙（accession-level + parse_run fingerprint）
- `periodOfReport` routing（含异常处理；±1–2 日归一化用 valid filing window）
- Amendment type 解析（normalized enum + raw）；RESTATEMENT 原子替换（成功后才切 active）；非 RESTATEMENT amendment_type → needs_review
- `official_filing_deadline` 计算（含工作日调整，使用 SEC/EDGAR federal holiday calendar + EDGAR 特别关闭日）
- `total_13f_reported_value_usd` 和 `total_13f_common_value_usd` 写入
- **`holding_attribution_status` 计算**（按 investment_discretion + other_managers_raw 规则，见 §7.2）
- OpenFIGI CUSIP 映射（含时间有效性字段初始化；有效区间 overlap 检查 + advisory lock）
  - **Auto-confirm 条件（同时满足才可 `mapping_status=confirmed`）：** ①单一候选（OpenFIGI 返回唯一结果）；②CUSIP 与 FIGI 精确匹配；③`security_type IN (common_stock, etf)`；④exchange / market sector 可验证（非空且非 unknown）。
  - 多候选、`security_type=unknown`、ADR / share class 歧义、exchange 未知 → `mapping_status=needs_review`，不自动确认。
- Backfill 预览 + 确认流程
- 所有 unique constraints 和 indexes（见 §14）
- **工程任务必须包含：** 2022 前 thousands / 2023+ 单位格式的测试 fixtures

### MVP 1C-1: Readiness + Oracle's Lens Safe Integration

- **13F-NT `notice_reported_elsewhere` 标记 / expected filer exclusion**（MVP 1C 必须完成，否则不进入 ready；13F-NT 表示"持仓由其他机构代报"，不是"未申报"或"无持仓"）
- Readiness summary（含 confidential_treatment、combination_report 对 readiness 的影响）
- Data freshness display（使用 `official_filing_deadline`，非裸 `+45 days`）
- Snapshot-only gating；zero vs unavailable 区分
- Holdings changes endpoint：HTTP 200 + `status=unavailable`（MVP 2 前）
- Options 与 common shares 分离展示
- `amendments_pending` → 立即降级 readiness

### MVP 1C-2: Admin Dashboard

- Admin dashboard：所有主要页面（含 Filings 页面展示 report_type / coverage_completeness / confidential_treatment）
- Parse runs 查询 API 和 Admin UI
- 数据健康日报（Discord 摘要，含 combination/confidential 数量）

### MVP 2: Change Analysis + Holder Aggregation

- Consecutive-quarter comparison（stock_id 优先；`coverage_completeness=complete` 限制参与变化计算）
- CUSIP_CHANGED 场景处理
- `change_status=no_prior_data`（13F-NT 前季不能断言无持仓）
- Precomputed `ownership_changes` 表（P95 800ms）
- Holdings changes endpoint 正式启用
- CUSIP 时间有效性查询（按 `quarter_end_date` 选择有效 mapping，使用 `mapping_status IN ('confirmed','superseded')`）
- **`/stocks/{stock_id}/holders` 聚合实现**（`direct_holder_count`、`value_manager_direct_count`、`featured_holder_count`、`top_holders`、`recent_changes`、`attribution_caveat_count`，见 §9.2.3）
- Oracle's Lens 价值投资者信号展示（§9.2.1 定义的信号；§9.2.2 排除规则实施）

### MVP 3: Resilience And Backfill

- Full historical backfill；Dataroma CUSIP 来源
- 批量 reparse by quarter / manager
- CUSIP corporate action temporal mapping 管理 UI
- 完整告警规则全覆盖；数据完整性校验 job

---

## 18. Acceptance Criteria

### 18.1 Functional Acceptance Criteria

- Admin can create, edit, deactivate, and review tracked managers; `value_unit_override` defaults to `infer`.
- Daily sync identifies and processes 13F-HR, 13F-HR/A, and 13F-NT.
- 13F-NT filing header is fetched; `periodOfReport` determines which quarter; `other_managers_reporting` is parsed with CIK / 13F file number when available; raw document is saved; system marks `coverage_type=notice_reported_elsewhere` — NOT "no holdings."
- System parses cover page `report_type` for all 13F-HR / 13F-HR/A filings; Combination Reports marked `coverage_completeness=partial`.
- System parses `has_confidential_treatment` from Summary Page; filings with confidential treatment cause readiness to cap at `usable_with_warning`.
- `form_spec_version` / `xml_schema_version` is extracted from XML root / namespace / schema metadata; `value_raw` + `value_unit_raw` + `value_parse_rule` + `value_usd` are stored; value_usd is always in dollars regardless of source unit.
- `official_filing_deadline` is computed with business-day adjustment; all filing window logic uses `official_filing_deadline`, not bare `quarter_end + 45`.
- Each parse of an accession creates a new `parse_run`; product queries use `is_current=true` parse_run; old parse_run rows are retained for audit.
- `periodOfReport` ±1–2 day auto-normalization only applies when form type is 13F-HR or 13F-HR/A AND `accepted_at` is within valid filing window. Missing or invalid period → `needs_review`, never auto-inferred.
- Amendment type is parsed; RESTATEMENT triggers atomic active filing switch after successful parse; original filing and all its parse_runs/holdings are retained.
- Changes endpoint returns HTTP 200 + `status=unavailable` + structured reason when coverage insufficient.
- `total_13f_common_value_usd` (common shares only) is the denominator for `portfolio_weight_pct`; value_usd is in dollars.
- CUSIP mapping queries use temporal validity (`effective_from_quarter`, `effective_to_quarter`, `quarter_end_date`).
- Oracle's Lens caveat copy for 13F-NT, Combination Report, and Confidential Treatment is displayed correctly.

### 18.2 Testable Acceptance Criteria

- Given a daily index containing a tracked manager and form `13F-NT`, the system fetches the NT filing header, reads `periodOfReport`, parses `other_managers_reporting` with CIK / 13F file number when available, marks `coverage_type=notice_reported_elsewhere` — not "no holdings."
- Given a 13F-HR filing with `report_type=COMBINATION REPORT` in cover page XML, the system sets `report_type=combination_report` and `coverage_completeness=partial`.
- Given a filing with `has_confidential_treatment=true` in Summary Page, readiness for that quarter is at most `usable_with_warning`.
- Given a pre-2023 filing with value in thousands, `value_usd = value_raw * 1000`, `value_unit_raw=thousands`, `value_parse_rule=schema_thousands`.
- Given `form_spec_version` indicates dollars unit, `value_usd = value_raw`, `value_unit_raw=dollars`, `value_parse_rule=schema_dollars`.
- Given XML root / namespace / schema metadata indicates amended 2023+ Form 13F, parser uses dollars even if filing date heuristics would be ambiguous.
- Given a filing is reparsed (same accession), a new `parse_run` is created with `is_current=true`; the old `parse_run` retains `is_current=false`; old holdings rows are NOT deleted.
- Given a product query for a holding's `value_usd`, it always returns dollars regardless of source filing unit.
- Given `official_filing_deadline` falls on a Saturday and the following Monday is a SEC federal holiday or EDGAR special closure, it is adjusted to the following EDGAR operational business day (e.g., Tuesday when Monday is closed).
- Given `official_filing_deadline` falls on a Saturday and the following Monday is a normal business day, it is adjusted to Monday.
- Implementation must use the SEC/EDGAR federal holiday calendar plus documented EDGAR special closures, not weekday-only logic and not the NYSE market holiday calendar.
- Given a 13F-NT manager, the system user-facing copy shows "This manager filed a 13F Notice; its 13(f) holdings are reported by other manager(s)." — not empty holdings or "no positions."
- Given a Combination Report is the active filing for a manager+quarter, Oracle's Lens shows caveat and does not use it for total_portfolio_value or cross-manager comparison.
- Given CUSIP A mapped to stock X before 2025-Q3 (mapping_status=superseded, effective_to_quarter=2025-Q2), and a new mapping to stock Y from 2025-Q3 (mapping_status=confirmed, effective_from_quarter=2025-Q3), a temporal query for Q3 2025 returns stock Y, a query for Q2 2025 returns stock X.
- Given a corporate action closes CUSIP A's old mapping, `mapping_status=superseded` (not `deleted`); the old mapping is still returned by historical temporal queries.
- Given a holding with `investment_discretion=SOLE` and empty `other_managers_raw`, `holding_attribution_status=direct`.
- Given a holding with `investment_discretion=SHARED`, `holding_attribution_status=shared`; this holding is excluded from manager consensus counts.
- Given `/stocks/{stock_id}/holders` is called without filters, the response only includes holdings with `holding_attribution_status=direct` in consensus counts; `shared` and `unresolved` are separately flagged.
- Given a filing with missing `periodOfReport`, `parse_status=needs_review` and `PERIOD_MISSING`; no quarter assigned; excluded from active holdings.
- Given holdings changes endpoint called with one quarter available, returns HTTP 200 with `status=unavailable`, not empty array and not HTTP 503.
- Given a 13F-NT manager from the prior quarter, `change_status=no_prior_data` for current quarter holdings (not `new_position`).
- Given CUSIP is 7 characters, system marks `invalid_cusip`; does not pad.
- Given CUSIP mapping rate < 50% after `official_filing_deadline`, P1 alert fires within 15 minutes.
- Given `nt_detection_supported=false`, readiness API returns at most `usable_with_warning`; `coverage_ratio.estimated=true`.
- Given a `parse_run` with `status=running`, `started_at` older than job timeout, and its `job_run_id` pointing to a `job_runs` row with `lease_expires_at` in the past, the watchdog marks it `status=abandoned`, `error='process_crash_or_timeout'`; the old `is_current=true` parse_run is unchanged; the abandoned run is retryable.
- Given a holding with `investment_discretion=OTR` (SEC canonical), `holding_attribution_status=shared`.
- Given a holding with `investment_discretion=DFND` and parseable `other_managers_raw`, `holding_attribution_status=reported_for_other`.
- Given a holding with `investment_discretion=SHARED` (non-canonical alias), parser normalizes to `OTR` before computing attribution; result is `holding_attribution_status=shared`.

---

## 19. 产品决策（已关闭）

| 问题 | 决策 |
| --- | --- |
| Manager type V1 支持范围 | `fundamental_long`、`activist`、`quant`、`multi_strategy`、`index_like`、`unknown` |
| Options 默认处理策略 | 变化分析默认仅 common shares；options 单独 tab/filter，`portfolio_weight_pct=null` |
| Options value 展示口径 | Options tab 展示 `value_usd` 原始值；不计入 13F common aggregate；不展示 portfolio weight |
| 历史回补默认起始季度 | `DEFAULT_BACKFILL_START_QUARTER=2023-Q1`，环境变量可覆盖；该默认值与 2023-01-03 Form 13F value unit 切换相关，早于该季度的 backfill 必须启用 thousands/dollars 双口径 fixtures |
| `featured` managers 排序 | Oracle's Lens 默认列表置顶展示，不影响数据覆盖范围 |
| 最低 linked holdings ratio 门槛 | < 50% 阻断 change analysis；50%–70% 展示 warning 不阻断 snapshot |
| Admin 告警渠道 | Discord（MVP 1A）；Email 可选（`ALERT_EMAIL_ENABLED`） |
| 13F-NT 语义 | 13F-NT = notice_reported_elsewhere（持仓客观存在，由其他 manager 代报）；**不等于"无持仓"** |
| 13F-NT 支持 | MVP 1C-1 必须实现；否则不进入 `ready` |
| Holdings changes endpoint HTTP status | HTTP 200 + body `status=unavailable`；不返回 HTTP 503；不返回空数组 |
| Amendment accepted_at 相同时 fallback | 不自动切 active；`amendments_pending + amendment_sort_warning=true`，等待 admin 确认 |
| CUSIP mapping 状态管理 | `is_active` boolean 已废弃；改用 `mapping_status` enum（`confirmed / superseded / needs_review / deleted`）；`superseded` 保留历史查询可访问；`deleted` 为 admin 手动停用；物理 DELETE 禁止 |
| CUSIP active mapping 唯一性约束 | 废弃 `UNIQUE(cusip) WHERE is_active=true`；改为应用层有效区间不重叠校验（`confirmed + superseded` 行的 effective 区间不重叠） |
| Holding attribution | `holding_attribution_status` 计算规则见 §7.2；`direct` 才计入共识统计；`shared / unresolved` 排除或加 caveat；防止 parent/subsidiary 共同申报误读 |
| 金额单位 | `value_usd` 统一以 dollars 存储；parser 按 `form_spec_version` / `xml_schema_version` 和 XML schema 确定单位，不以 manager-level override 为主判断路径 |
| Filing deadline 计算 | 使用 `official_filing_deadline`（quarter_end + 45 days，调整到下一个 SEC/EDGAR operational business day）；calendar 口径：SEC/EDGAR federal holidays + documented EDGAR special closures，非 NYSE market holiday list |
| parse_run 失败审计 | parse_run 两阶段写入：阶段 1 独立事务立即持久化 `status=running`；阶段 2 holdings + is_current 切换，失败后 catch 更新 `status=failed + error`；任何情况下 failed parse_run 都有持久记录 |
| parse_run orphan 处理 | `status=running` 超过 job timeout 且 lease 过期 → 标记 `status=abandoned`；watchdog 由 quality_check job 或 ingest 启动时清理；`abandoned` 等同 `failed` 可重试 |
| investment_discretion 规范化 | SEC XML 原始值 `SOLE / DFND / DEFINED / OTR / OTHER / SHARED` 在 parser 层 normalize 到 `SOLE / DFND / OTR`；`DEFINED→DFND`、`OTHER/SHARED→OTR`；`DFND→reported_for_other`（或 unresolved），`OTR→shared`，`SOLE→direct` |
| OpenFIGI auto-confirm 条件 | 必须同时满足：单一候选 + CUSIP/FIGI 精确匹配 + security_type ∈ {common_stock, etf} + exchange 可验证；否则 `needs_review`；ADR / share class 歧义一律 needs_review |
| CUSIP overlap 并发控制 | MVP: `pg_advisory_xact_lock(hashtext(cusip))` 在同一事务内，overlap 检查后再写入；长期: daterange + EXCLUDE USING gist exclusion constraint |

---

## 20. Open Questions

| 优先级 | 问题 | 背景 |
| --- | --- | --- |
| MVP 1B 前 | SEC EDGAR 13F XML schema 的 value 单位跨年份规则确认 | 工程必须测试 2022 及以前、2023 及以后两套 fixtures，确认 `form_spec_version` / `xml_schema_version` 映射规则；如 SEC FAQ Q36 或 XML schema 有明确说明，以 SEC 官方文档为准 |
| MVP 2 前 | Corporate action 外部数据来源确认 | §7.4 heuristic 为临时方案；接入可靠数据源后替换 |
| MVP 2 前 | 变化计算的最低 CUSIP 映射率门槛是否需要 per-manager 设置 | 部分 manager 持有大量小市值股票，映射率天然偏低 |
| MVP 2 前 | 13F-NT manager 的持仓变化计算策略 | 其持仓在其他 manager 的 filing 中；V1 不做跨 manager 合并，change_status=no_prior_data；MVP 2 前讨论是否支持 cross-reference |
| MVP 3 前 | `value_unit_override` filing 级别覆盖实现 | V1 manager-level 为已知 gap |
| 未来 | 是否在 Oracle's Lens 展示 manager 的 13F reported value 季度趋势 | 需 UI 层明确标注"13F-reported value only, not AUM" |
