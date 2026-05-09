# 13F 数据自动化抓取与分析 PRD

| 项目名称 | ValuePilot 13F Data Automation & Ownership Signals | 版本 | v1.7 |
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
| 管线告警触达 | P1 告警 ≤ 15 分钟触达通知渠道 | 同左 | 从告警条件触发到 Discord 消息送达；人工响应时效为运营 SLA，不列入此 KPI | Discord 消息时间戳 |

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
| Filing Deadline | quarter end + 45 calendar days | 13F 通常最晚提交日期 | 判断 partial / expected incomplete |
| Valid Filing Window | quarter end to quarter end + 180 days | 13F 合理申报范围（含延迟申报） | periodOfReport 归属验证（见 §5.3） |

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

### 2.3 季度标准化规则

`periodOfReport` 字段可能出现非标准季末日期（如 2026-03-30 等因周末调整）。归一化目标：标准季末为 3/31、6/30、9/30、12/31。

| periodOfReport 偏移范围 | 处理策略 |
| --- | --- |
| ±0 日（完全匹配标准季末） | 直接归属，无 warning |
| ±1–2 日 | 满足以下**两个条件**时自动归一化，否则 needs_review：① filing 类型为 13F-HR / 13F-HR/A；② `accepted_at` 落在该 report period 的 valid filing window 内（quarter_end 后 0–180 天） |
| ±3–5 日 | `parse_status=needs_review`，`PARSE_WARNING=PERIOD_TOO_FAR_FROM_QUARTER_END` |
| > ±5 日 | 同上 |

**关键说明：** 13F 的 accepted_at 正常在 quarter_end 之后（Q1 filing 通常在 Q2 内被接受），不与 periodOfReport 所在季度相同。±1–2 日归一化的验证条件绝不能要求"accepted_at 所在季度与 report period 所在季度相同"——这会把所有正常 Q1/Q2/Q3/Q4 filing 错误标为异常。正确条件是 accepted_at ≥ quarter_end（不能在季度结束前提交）且 accepted_at ≤ quarter_end + 180 天。

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
source_url                -- nullable；candidate / 手动输入 / bulk import 场景可无
confidence_score          -- 整数 0–100；低于 60 建议进入人工确认流程
value_unit_override       -- 枚举：thousands（默认）/ dollars
                          -- 仅在 admin 明确确认（含 confirmed_by / confirmed_at）后生效
                          -- V1 仅作为 manager 级覆盖；filing 级覆盖为已知 gap（见 §3.3 注）
confirmed_by              -- nullable
confirmed_at              -- nullable
created_at
updated_at
review_note
```

注：`value_unit_override` 应用于 manager 的**所有**历史 filing，因此生效前必须有 admin 明确确认（记录 `confirmed_by` + `confirmed_at` + provenance），不能靠系统自动推断后静默写入。如仅个别 filing 单位异常，V1 标记为 `needs_review`，等待后续 filing 级覆盖支持（已知 gap）。

说明：

- `cik` 必须是经过确认的 CIK，不能只依赖模糊匹配结果。
- `manager_type` V1 支持：`fundamental_long`、`activist`、`quant`、`multi_strategy`、`index_like`、`unknown`。
- `is_featured`：Oracle's Lens 默认列表置顶；不影响数据覆盖范围（V1 已支持字段，排序 boost 后续做）。

### 3.4 Manager Universe 策略

V1 默认策略：以 Dataroma 或人工输入作为 manager discovery 起点；只有 CIK 确认后进入 active tracked universe；`featured` 不是 source of truth，也不是 ingestion filter。

### 3.5 CIK 搜索与确认

SEC EDGAR 查询接口：

- **名称搜索**：EDGAR 全文检索（EFTS）`https://efts.sec.gov/LATEST/search-index?q="manager+name"&forms=13F-HR`，通过名称查找 13F 申报记录定位 CIK。
- **CIK 已知时验证**：`https://data.sec.gov/submissions/CIK{10位}.json`，验证是否有 13F 记录。`submissions/{CIK}.json` 需要已知 CIK，不能用于名称搜索。

流程：

1. 用户输入 manager name → EFTS 搜索返回候选（名称、CIK、最近 13F 提交日期）。
2. 若无结果：提示 admin 在 EDGAR 页面手动查找，支持手动输入 CIK + EDGAR 直链核对。
3. 若多个相似结果：以表格展示，高亮最近 12 个月内有 13F 记录的候选。
4. Admin confirm CIK，记录确认人、确认时间、证据 URL、review note。

CIK 候选在确认前不得参与抓取。

确认后系统显示历史回补预览（含：默认起始季度 `DEFAULT_BACKFILL_START_QUARTER`、预估 filing 数量、预估 EDGAR 请求数和 rate limit 等待时间）；Admin 确认后才触发 backfill job，禁止静默触发。

### 3.6 批量导入

Admin 可上传 CSV，最低必填字段：`canonical_name, source_url`（source_url 可为空）；可选字段：`manager_type, is_featured`。所有候选初始状态为 `candidate`，不自动确认任何 CIK。

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
| `no_data` | 已确认该日期无 index（周末/节假日/观察窗口后仍无） | 否 |
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
   - 必须抓取 filing detail / header，从 `periodOfReport` 字段确定该 NT 所属报告季度（不使用 daily index date 或 filing date 推断）。
   - 保存 raw filing document（用于审计和 period 复查）。
   - 不抓取 information table（13F-NT 无 holdings）。
   - 按 `periodOfReport` 将该 manager + quarter 标记为 `nt_filed`（notice of non-filing）。
8. 抓取 13F-HR / 13F-HR/A 的 filing detail 和 information table。
9. 解析 holdings。
10. 根据 `periodOfReport` 归属报告季度（见第 5 节）。
11. 更新 sync status 和 job summary。

**404 处理规则：**

1. 若该日期在 `no_index_expected_dates` 列表中（已知节假日/周末），直接标记 `no_data`，不计入重试。
2. 否则进入重试队列，重试超过 3 次且当日美东 23:59 已过，再标记 `no_data`。

`no_index_expected_dates` 是系统维护的"预期无 index 日期"列表，参考 NYSE 节假日作为 proxy（非 SEC 官方日历）；SEC 临时停服或特殊发布日由 retry 机制兜底，不依赖此列表。

**每日触发时间：** Worker 采用 **hourly polling** 作为主要机制，配置参数 `DAILY_SYNC_EARLIEST_ATTEMPT_ET`（默认 `20:00` 美东）作为当日首次尝试下限，减少夜间无效请求，不作为唯一触发依据。

### 4.5 限速与稳定性

- 遵循 SEC Fair Access Policy：全局 10 requests/second，请求间隔 ≥ 100ms。
- **全局速率限制器**：所有 EDGAR 请求（daily sync、manual job、backfill、CIK 搜索）必须通过统一全局 rate limiter。
- User-Agent 格式：`{APP_NAME}/{APP_VERSION} (contact: {SEC_CONTACT_EMAIL})`，三个值均从环境变量读取，禁止硬编码。若 `SEC_CONTACT_EMAIL` 环境变量缺失，系统启动时应 fail-fast 或将 SEC client 标记为 disabled，不允许 silently fallback 到无效邮箱。
- 禁止绕过统一 SEC client 直接调用 EDGAR。
- 网络失败使用 exponential backoff，最大退避 5 分钟，最大重试 5 次。
- daily index 下载结果应保存 raw document。
- 单次 job 请求总数超过 500 时，写入 job summary 并检查是否触发限流警告。

---

## 5. Smart Routing：正确期间归属

### 5.1 核心规则

13F filing 必须根据 filing 内容中的 `periodOfReport` 归属报告季度。

```text
report_period = parsed periodOfReport
report_quarter = normalize(report_period)
```

不能使用以下字段作为报告季度：sync date、filing accepted date、SEC daily index date、当前系统日期。

### 5.2 延迟申报处理

如果某 manager 在 2026-05-10 提交 2026-03-31 的 13F：

```text
report_quarter = 2026-Q1
quarter_end_date = 2026-03-31
filing_date = 2026-05-10
```

Oracle's Lens 展示时显示：

```text
Holdings data as of 2026-03-31. Managers file 13F reports up to 45 calendar days after quarter end,
so current-quarter data may update until approximately 2026-05-15.
```

### 5.3 periodOfReport 异常处理（本节为权威定义，§2.3 为概念引用）

| 异常类型 | 处理策略 |
| --- | --- |
| 字段缺失（XML 无 `periodOfReport`） | `parse_status=needs_review`，`parse_warning=PERIOD_MISSING`，**不自动推断**，不进入 product-facing holdings，等待 admin 人工确认 |
| 日期格式不合法 | `parse_status=failed`，写入具体错误，不归属任何季度，不阻塞其他 filings |
| ±1–2 日偏移，且满足归一化条件 | 归一化到最近标准季末，`PARSE_WARNING=PERIOD_WEEKEND_ADJUSTED`，进入产品分析 |
| ±1–2 日偏移，但不满足归一化条件（如 accepted_at 超出 valid filing window） | `parse_status=needs_review`，`PARSE_WARNING=PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE` |
| ±3–5 日偏移 | `parse_status=needs_review`，`PARSE_WARNING=PERIOD_TOO_FAR_FROM_QUARTER_END` |
| > ±5 日偏移 | 同上 |
| 归属季度与 accepted_at 相差 > 3 个季度 | `PARSE_WARNING=PERIOD_SUSPICIOUSLY_STALE`，需 admin 确认后才参与分析 |

**归一化条件（±1–2 日自动归一化的两个前提）：**

1. form_type 为 `13F-HR` 或 `13F-HR/A`。
2. `accepted_at` 落在该 report period 的 valid filing window 内：`quarter_end_date ≤ accepted_at ≤ quarter_end_date + 180 days`。

**重要原则：** `periodOfReport` 缺失时绝不用 `accepted_at` 自动推断归属。13F 的 accepted_at 正常在 quarter_end 之后（Q1 filing 通常 accepted_at 在 Q2），使用 accepted_at 所在季度会导致 silently wrong 归属。

---

## 6. Filing 去重、可重入与 Amendment Policy

### 6.1 去重键

SEC accession number 是 filing 级别唯一键：

- 同一个 accession number 只能有一条 filing record。
- 同一个 accession number 的 holdings 解析必须可重入。
- 重跑同一 accession 不得产生重复 holdings。

### 6.2 两道去重防火墙

#### 第一层：Accession Number 作为申报单唯一身份

按以下状态决定是否跳过：

| 现有 accession 状态 | 处理 |
| --- | --- |
| `parse_status=succeeded` 且无 reparse flag | 跳过下载和解析，记入 `skipped_existing_accessions` |
| `parse_status=failed` | 重试 |
| `parse_status=partial_success` | 重试 |
| `parse_status=needs_review` | 跳过；系统应创建 admin review task 并在超 7 天未处理时触发 P3 告警，防止永久卡死 |
| `parser_version` 低于当前版本 | 触发 reparse |
| raw document 损坏或缺失 | 重新下载，触发 reparse |

#### 第二层：Holding Row Fingerprint（行标识指纹）

Fingerprint 是**行标识指纹**，不是纯内容哈希。`source_row_index` 必须在任何过滤、清洗、跳过无效行之前，从原始 XML 行顺序赋值（0-indexed）。

```text
holding_row_fingerprint = sha256(
  accession_number,
  source_row_index,
  normalized_name_of_issuer,
  normalized_title_of_class,
  normalized_cusip,
  value_usd_thousands,
  ssh_prnamt,
  ssh_prnamt_type,
  put_call,
  investment_discretion,
  other_managers_raw
)
```

`holdings_13f` 对 `(accession_number, holding_row_fingerprint)` 建唯一约束。系统保存 `fingerprint_version`（规则版本号），normalization 变更时识别需 reparse 的历史数据。

### 6.3 可重入要求

| 操作 | 可重入要求 |
| --- | --- |
| daily index fetch | 相同 sync date 可重复下载或复用 raw document |
| filing metadata ingest | accession number upsert |
| information table fetch | accession-level raw document replace-safe 或 versioned |
| holdings parse | accession-level atomic replace（见 §6.4） |
| quarter backfill | 已成功 accession 跳过，失败 accession 可重试 |

### 6.4 Transaction Boundary 与写入顺序

```sql
-- 同一事务内顺序执行（PostgreSQL 语法示例；其他数据库请对应调整）
BEGIN;
  DELETE FROM holdings_13f WHERE accession_number = :accession;
  INSERT INTO holdings_13f (...) VALUES (...);  -- bulk insert，先删后插避免 unique constraint 冲突
  UPDATE filings_13f
    SET parse_status = 'succeeded',
        holdings_count = :count,
        total_13f_reported_value_usd = :total_all,
        total_13f_common_value_usd = :total_common,
        parser_version = :current_parser_version,
        updated_at = now()
    WHERE accession_number = :accession;
COMMIT;
-- 任一步失败则整体回滚，filing 保持 retryable 状态
```

**Job 锁与心跳（lease token 机制）：**

- Job 启动时获取带过期时间的 lease token，定期刷新（heartbeat）。
- 只有 lease owner 才能写入；接管 failed job 前须先确认原 worker lease 已过期。
- 超时后 job 标记为 `failed`，lease 过期，允许重试。

### 6.5 Amendment Policy

**Amendment Type（13F/A XML `<amendmentType>` 字段）：**

| Amendment Type | 含义 | 处理策略 |
| --- | --- | --- |
| `RESTATEMENT` | 完整重申所有持仓 | 解析成功后原子替换 active holdings（见下方流程） |
| `NEW HOLDINGS` | filer 未提交过当季原始 13F | 默认 `parse_status=needs_review`，`amendments_pending`；admin 确认后再决定是否作为 active filing（不自动处理，原因见注） |
| `ADDITIONS CORRECTIONS DELETIONS` | 部分持仓增删改 | `amendments_pending`，不自动合并；admin 确认后手动处理 |
| 字段缺失 / 无法解析 | 无法判断替换范围 | `amendments_pending`，不自动覆盖 |

注：`NEW HOLDINGS` 不自动处理，因为它在 amendment 语境下含义较复杂（可能是 late original、可能是 amendment 分支），且若同 manager+period 存在 prior filing，直接自动激活有数据竞争风险。

**RESTATEMENT 替换流程（只有 parse 成功后才切换 active）：**

**审计保留原则（重要）：** 原始 filing 记录（`filings_13f` 行）及其 derived holdings（`holdings_13f` 中该原始 accession 的行）**永远不删除**，用于审计和历史复查。产品侧通过 `is_active_for_manager_period=true` 切换到 amendment accession 的 holdings；§6.4 的 DELETE 仅针对**新 amendment accession** 自身之前可能存在的旧解析行，不涉及原始 filing 的 holdings。

```text
1. 解析新 amendment filing 的 holdings（accession = NEW_ACCESSION）
2. 若解析成功（parse_status = succeeded）：
   BEGIN TRANSACTION
     -- 原始 filing 和其 holdings 保留，仅更新 active 标志
     旧 active filing: is_active_for_manager_period = false
     新 filing: is_active_for_manager_period = true
     -- §6.4 replace-safe：DELETE holdings WHERE accession = NEW_ACCESSION，再 bulk insert
     -- （不删除原始 filing 的 holdings）
   COMMIT
   产品查询通过 is_active_for_manager_period=true → NEW_ACCESSION → 新 holdings
3. 若解析失败：
   旧 active filing 保持不变，继续服务
   新 filing: parse_status = failed / amendment_status = amendment_failed
   Oracle's Lens readiness 降级
```

**多 RESTATEMENT 排序规则：**

- 以 `accepted_at` 最晚者为 active。
- 若 `accepted_at` 相同：**不自动切换 active**，标记 `amendment_status=amendments_pending`，`amendment_sort_warning=true`，等待 admin 人工确认，避免字典序 fallback 导致错误数据上线。

Amendment 状态：

| 状态 | 含义 |
| --- | --- |
| `no_amendments_seen` | 未发现 amendment |
| `amendments_applied` | 已发现并应用 RESTATEMENT |
| `amendments_pending` | 有未处理 amendment（PARTIAL / accepted_at 相同 / NEW HOLDINGS / 未知类型） |
| `amendment_failed` | amendment 处理失败 |

---

## 7. Holdings 数据模型与计算

### 7.1 Filing 字段

建议 `filings_13f` 至少包含：

```text
id
manager_id
cik
accession_number                      -- UNIQUE 约束
form_type
filing_date
accepted_at
period_of_report
report_quarter
quarter_end_date
is_amendment
amends_accession_number
amendment_type                        -- normalized enum: RESTATEMENT / NEW_HOLDINGS / ADDITIONS_CORRECTIONS_DELETIONS / unknown
amendment_type_raw                    -- SEC XML 原文，用于审计和对照
is_active_for_manager_period          -- PARTIAL UNIQUE: (manager_id, quarter_end_date) WHERE true
raw_filing_url
raw_infotable_url
parse_status
parse_warning
parse_error
parser_version                        -- 解析时使用的 parser 版本号，用于判断是否需要 reparse
total_13f_reported_value_usd          -- 所有 holdings（含 options）value 合计（13F 可报告范围，非完整 AUM）
total_13f_common_value_usd            -- common shares（put_call IS NULL）value 合计，portfolio_weight_pct 分母
holdings_count
common_holdings_count
amendment_status
amendment_sort_warning                -- bool；多 amendment accepted_at 相同、无法自动排序时标记
created_at
updated_at
```

说明：

- `total_13f_reported_value_usd`：前端展示时必须标注 *"Based on 13F-reported securities only; does not represent total AUM."*
- `total_13f_common_value_usd`：common shares only，是 `portfolio_weight_pct` 的分母。
- `is_active_for_manager_period`：partial unique index 使用 `(manager_id, quarter_end_date)`（normalized 日期），而非字符串 `report_quarter`，口径更稳定。
- `parser_version`：normalization 规则升级后，可识别需要 reparse 的历史 filings。

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
value_usd_thousands                   -- 保留 SEC 原始口径（通常 thousands）；换算后统一写入
value_raw                             -- SEC 原始未换算值（审计用）
value_unit_raw                        -- 原始单位（thousands / dollars）（审计用）
ssh_prnamt
ssh_prnamt_type
put_call                              -- NULL=common share; 'Put'=put option; 'Call'=call option
investment_discretion
other_managers_raw                    -- 原始 otherManager 字段，V1 保留字符串，后续结构化
voting_sole
voting_shared
voting_none
stock_id
portfolio_weight_pct                  -- (value_usd_thousands / filing.total_13f_common_value_usd) * 100
                                      -- numerator 和 denominator 均为 thousands 口径，单位一致
                                      -- 仅 common shares（put_call IS NULL）有效；options 行为 null
                                      -- MVP 1B 写入时为 null，MVP 2 计算填充
holding_row_fingerprint
fingerprint_version
source_row_index
created_at
updated_at
```

说明：

- `value_raw` + `value_unit_raw`：保留 SEC 原始值和原始单位，便于审计和验证换算逻辑。
- API label 中 `portfolio_weight_pct` 应展示为 **"13F common weight"**，绝不使用 "portfolio weight" 裸标签。
- `put_call IS NULL` = common shares（持仓分析主体）；options 单独展示，不混入权重和变化计算。

### 7.3 持仓变化计算

持仓变化必须基于同一 manager、同一证券、连续报告季度的 active filing holdings。

**安全证券匹配优先级：**

1. 若两个季度该持仓均有可信 `stock_id`（非 null）：以 `stock_id` + `ssh_prnamt_type` + `put_call` 作为主匹配键。
2. 任一季度缺少可信 `stock_id`：fallback 到 normalized CUSIP + `ssh_prnamt_type` + `put_call`。
3. CUSIP 变化但两者映射到同一 `stock_id`（corporate action / share class change）：识别为同一证券，标记 `change_caveat=CUSIP_CHANGED`，不视为 exit + new。
4. 均无法匹配：`change_status=unresolvable`，不进行变化计算。

**`put_call` 隔离规则：** options 和 common shares 必须分开计算，不得混合比较数量或价值。

**prior quarter 数据缺失规则：**

- 若因数据 gap（该 manager 当季无 active filing 且不是 13F-NT），前一季度持仓不可知：当前持仓的 `change_status=no_prior_data`，**不标记为 `new_position`**，不展示变化信号。
- 若前一季度 manager 提交 13F-NT（无应报告 holdings）：streak 中断，当前持仓可标记为 `new_position`（因为明确知道上季无持仓），并附注 "Prior quarter: no 13F holdings reported (13F-NT filed)"。

基础分类：

| 分类 | 规则 |
| --- | --- |
| `new_position` | 当前季度存在，上一季度确认不存在（包含 13F-NT 场景）；若上一季度数据 gap，改用 `no_prior_data` |
| `exited_position` | 上一季度存在，当前季度不存在 |
| `increased` | 当前数量 > 上一季度数量 |
| `reduced` | 当前数量 < 上一季度数量 |
| `unchanged` | 当前数量 = 上一季度数量 |
| `no_prior_data` | 上一季度数据 gap，无法判断变化 |

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
holding_streak_quarters               -- 见 §9 "连续"定义
streak_may_be_underestimated          -- bool
change_status                         -- new_position / exited_position / increased / reduced / unchanged / no_prior_data / unresolvable
change_caveat                         -- CUSIP_CHANGED / POSSIBLE_CORPORATE_ACTION / null
```

**Corporate action 启发式检测（无外部数据源时的 heuristic，结果为 "possible" 提示，不作为确定性判断）：**

| 阈值 | 说明 |
| --- | --- |
| `share_change_pct` > +90% 或 < -47% | 可能 2:1 拆股或合股 |
| `share_change_pct` > +190% 或 < -65% | 可能 3:1 拆股或合股 |
| `share_change_pct` > +400% 或 < -80% | 可能 5:1+ 拆股或合股 |
| CUSIP 变更（`CUSIP_CHANGED` 已标记） | 可能 merger / spin-off / share class change |

标注后前端展示变化数据时配套提示语："Share count change may reflect a corporate action (e.g., stock split). Please verify."；接入外部 corporate action 数据源后可替换 heuristic。

---

## 8. CUSIP 映射与证券关联

### 8.1 目标

将 holdings 中的 CUSIP 映射到系统内部 `stock_id`，支持跨 manager 的证券聚合分析。

### 8.2 映射优先级（序号越小优先级越高）

1. **手动映射**：admin 在后台维护的 CUSIP → ticker 映射，`source="manual"`，优先级最高，覆盖所有自动映射。
2. **OpenFIGI API**（V1 自动映射主来源）：`https://api.openfigi.com/v3/mapping`，`source="openfigi"`。
   - API key 从 `OPENFIGI_API_KEY` 读取；rate limit：有 key 100 req/min，无 key 25 req/min。
   - OpenFIGI 使用独立 rate limiter（不共享 SEC limiter）。
   - 同一 CUSIP 查询结果缓存，TTL = 30 天；不对同一 CUSIP 重复请求，除非 cache 过期或 admin 手动触发 refresh。
   - 请求失败时：不阻塞 holdings ingestion，仅降级该 CUSIP 为 `pending_mapping`，下次 `enrich_cusip` job 重试。
3. **Dataroma 持仓交叉引用**（MVP 3 实现）：`source="dataroma"`。V1 只有 manual + OpenFIGI。
4. **SEC co_tickers 交叉引用**：`company_tickers_exchange.json` 提供 CIK ↔ ticker（**不提供 CUSIP**），可在已有 CUSIP → CIK 映射后补充 ticker，`source="sec_co_tickers"`。
5. **无法映射**：`stock_id = null`，`cusip_mapping_status=unresolved`。

### 8.3 cusip_ticker_map 表结构

```text
id
cusip
ticker
exchange
stock_id
source              -- manual / openfigi / dataroma / sec_co_tickers
candidate_rank      -- 同一 (cusip, source) 下的候选排名（1 = best match）
confidence          -- 整数 0–100
evidence_url        -- 手动映射时填写
reviewed_by         -- admin user id（手动映射）
reviewed_at
is_active           -- 软删除 / 覆盖用；金融数据 mapping 不物理 DELETE（见 §8.4）
created_at
updated_at
```

**唯一约束：** `UNIQUE (cusip, source, ticker, exchange)`。允许同一 (cusip, source) 组合有多个候选（OpenFIGI / Dataroma 可能返回多候选），每个候选是独立行。最终 active mapping 通过 `is_active=true` + `candidate_rank=1` 确定。

**Active mapping 唯一性：** 同一 CUSIP 在任意时刻应最多只有一个 `is_active=true` 的行（跨所有 source）。建议在数据库层建立 partial unique index `UNIQUE (cusip) WHERE is_active = true`；若同时存在多个 source 的 active 候选，标记 `cusip_mapping_status=needs_review`，由 admin 确认唯一 active 候选。

### 8.4 CUSIP 数据质量问题

| 问题 | 处理策略 |
| --- | --- |
| CUSIP 为全零 | 忽略映射，`cusip_mapping_status=invalid_cusip` |
| CUSIP 长度不足 9 位 | `cusip_mapping_status=invalid_cusip`，不自动补零（CUSIP 有校验位，错误补齐产生无意义或错误映射） |
| 同一 CUSIP 对应多个候选 | 存入多行（`candidate_rank` 区分），标记 `cusip_mapping_status=needs_review`，由 admin 确认 `is_active=true` 候选 |
| CUSIP 对应已退市证券 | 保留映射，`stock_delisted=true`；前端展示时标注已退市，价格/估值字段标记 `unavailable`，不展示 stale 价格 |
| Admin 停用某映射 | `PATCH is_active=false`（软停用），保留历史记录用于审计，不物理 DELETE |

### 8.5 CUSIP 映射 job 与告警

- `enrich_cusip:{report_quarter}` job 在每季度 filing 解析完成后自动触发。
- 告警触发条件和阈值与 §10.1 readiness 阈值同源配置（参数 `CUSIP_MAPPING_P1_THRESHOLD=0.50`，`CUSIP_MAPPING_READY_THRESHOLD=0.70`）。
- common share CUSIP 映射率 < 70%（**filing window 已关闭**）：P2 告警，readiness 降级为 `usable_with_warning`。
- common share CUSIP 映射率 < 50%（**filing window 已关闭**）：P1 告警，readiness 降级为 `experimental`。
- window 内不触发，仅显示 partial warning。

---

## 9. 历史覆盖与 Oracle's Lens 功能门控

Oracle's Lens 不应在历史数据不足时暗示趋势洞察。

| 历史覆盖 | 可用能力 | 用户提示 |
| --- | --- | --- |
| 1 个季度 | 当前持仓快照 | 无趋势、无新增/退出/加减仓解释 |
| 2 个连续季度 | 基础变化：新增、退出、加仓、减仓 | 仅方向性变化，不代表长期趋势 |
| 4 个连续季度 | 年度趋势、持有持续性 | 可用于基础持仓行为分析 |
| 8 个连续季度 | 多年持仓模式、周期性判断 | 更适合长期 manager 行为研究 |

**"连续"与中断的定义（用于 streak 和 historical coverage 计算）：**

| 情形 | 对某证券的 streak | 对 historical coverage |
| --- | --- | --- |
| 有 active 13F-HR / 13F-HR/A，holdings 正常 | 不中断 | 计入有效季度 |
| Manager 提交 13F-NT（notice of non-filing） | 中断（该季度明确无持仓可报告） | **不视为数据 gap**；标记 `coverage_type=nt_filed`（见注） |
| Manager 应申报但无 filing（数据缺失） | 中断 | 视为 `coverage_gap` |
| Manager 为 `inactive`，不再被系统跟踪 | 不适用 | 不计入 |

注：Manager 提交 13F-NT 后，Oracle's Lens 展示该季度状态为 "No 13F holdings reported this quarter (notice filed)"，不显示为数据缺失、空持仓或 "0 positions"。

**manager 不再需要提交的处理：** 若 manager 在某时间点后不再满足 13F 报告门槛或停止运营（status 变为 `inactive`），系统停止对其历史趋势的 streak 计算；Oracle's Lens 展示该 manager 时，最后一个有效季度后的数据标注 "Manager no longer tracked"，不保留或延伸历史信号。streak 中 `holding_streak_quarters` 的相关说明请参见 §7.3。

Readiness payload 应包含：

```text
historical_coverage_quarters
consecutive_quarters_available
supports_snapshot
supports_basic_change
supports_annual_trend
supports_multi_year_pattern
data_gap_quarters               -- coverage_gap 季度列表
nt_filed_quarters               -- 13F-NT 季度列表（合法无持仓，非 gap）
```

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

- 至少 1 个季度中，**expected filers** 覆盖率 ≥ 80%（filing window 关闭后统计）。
- 该季度 filing parse 成功率 ≥ 95%。
- 该季度 common share CUSIP 映射率 ≥ 70%（参数 `CUSIP_MAPPING_READY_THRESHOLD`）。
- 无影响 latest usable quarter 的 `amendment_failed` 状态。
- 无影响 latest usable quarter 的 `amendments_pending`（**任何** pending amendment 影响到 latest usable quarter 时，立即降级为至多 `usable_with_warning`；pending 超过 48 小时后另行触发 P2 告警，见 §15.2，两者独立）。

**Expected filers 定义：**

某报告季度的 expected filers = `status=active` 的 managers，**排除**该季度已提交 **13F-NT** 的 managers。

"13F-NT"（notice of non-filing）表示 manager 在该季度主动向 SEC 提交了通知，声明不提交 holdings report（原因可能是无应报告 holdings、资产低于门槛、其他合规原因）。系统只能观察到是否提交了 13F-NT，无法进一步判断具体原因；不应将 13F-NT 称为"豁免"，前端展示应使用 "notice of non-filing"。

**13F-NT 未实现时的 readiness 行为：**

若 `nt_detection_supported=false`（13F-NT 解析尚未上线），系统无法准确排除 NT filers，denominator 可能高估。此时：

- 系统不得进入 `ready` 状态（最多 `usable_with_warning`）。
- `coverage_ratio` 字段标记 `estimated=true`，含义为"分母未排除 NT filers，覆盖率可能被低估"。
- readiness API 必须暴露 `nt_detection_supported: false`。

### 10.2 质量指标

| 指标 | Numerator | Denominator | 备注 |
| --- | --- | --- | --- |
| `manager_coverage_ratio` | expected filers 中有 is_active_for_manager_period=true（13F-HR/HR/A）的 manager 数 | 本季度 expected filers 总数（排除 13F-NT filers） | numerator 中 13F-NT filers 已从 denominator 移除，不重复计算 |
| `filing_parse_success_ratio` | `parse_status=succeeded` 的 filings 数 | 本季度所有已下载 filings 数 | |
| `linked_common_holding_ratio` | `stock_id IS NOT NULL` 的 common share holdings 行数 | 本季度 active common share holdings 行数（`null` 若无） | 主要 readiness 指标 |
| `linked_all_holding_ratio` | `stock_id IS NOT NULL` 的所有 holdings 行数（含 options） | 本季度所有 active holdings 行数（`null` 若无） | 参考指标 |
| `cusip_mapping_ratio` | CUSIP 已映射的 common share holdings 行数 | 本季度 active common share holdings 行数（`null` 若无） | |

其他指标：

```text
confirmed_manager_count
active_manager_count
expected_filer_count
filed_manager_count
nt_filer_count
amendment_handling_status
historical_coverage_quarters
latest_usable_quarter
last_successful_sync_at
nt_detection_supported
```

### 10.3 Zero vs Unavailable

- `0 failed filings` 表示检查过且失败数为 0。
- `null failed filings + unavailable_reason` 表示还没有检查。
- `0% linked holdings` 表示有 holdings，但一个都没 linked。
- `null linked holdings ratio` 表示没有 denominator（无 active holdings）。

---

## 11. Admin Dashboard

### 11.1 主要页面

| 页面 | 目标 |
| --- | --- |
| Overview | 查看 13F 管线整体健康状态 |
| Managers | 维护 tracked managers 和 CIK |
| Daily Sync | 查看每日 form.idx 同步状态 |
| Filings | 查看 filings、parse status、amendments |
| Holdings Coverage | 查看 holdings parse 和 stock link 覆盖率 |
| Jobs | 查看 job runs、失败原因、重试 |
| Readiness | 查看 Oracle's Lens 是否可用以及为什么不可用 |

### 11.2 Oracle's Lens Admin 指标

面向 admin 的 Oracle's Lens 就绪状态指标：

- 当前报告季度；filing window 是否仍打开
- active managers 数量；expected filers 数量（本季度）；nt_filer 数量
- 已申报 manager 数量；申报完成率（基于 expected filers）
- failed filings；pending amendments（超 48 小时）
- linked_common_holding_ratio；CUSIP 映射率
- historical coverage depth；latest usable quarter
- nt_detection_supported

### 11.3 Jobs 页面过滤要求

过滤维度：`job_type`、`status`（所有有效状态：`queued`、`running`、`succeeded`、`partial_success`、`failed`、`cancel_requested`、`canceled`、`skipped`）、日期范围（`started_at`）、`sync_date`、`quarter`。

分页：每页 50 条。

展示 `summary_json` 关键计数：`skipped_existing_accessions`、`new_filings_ingested`、`holdings_inserted`、`parse_errors`、`nt_filings_recorded`。

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

### 12.2 Job 状态

`queued` / `running` / `succeeded` / `partial_success` / `failed` / `cancel_requested` / `canceled` / `skipped`

### 12.3 推荐 lock_key 与冲突规则

| Job Type | lock_key | 说明 |
| --- | --- | --- |
| `fetch_daily_index` | `fetch_daily_index:{sync_date}` | |
| `process_daily_index` | `process_daily_index:{sync_date}` | |
| `ingest_filing` | `ingest_filing:{accession_number}` | accession 粒度，允许同季度不同 accession 并行 |
| `ingest_holdings_for_quarter` | `ingest_holdings:{report_quarter}` | 季度级 job 入口锁 |
| `retry_failed_filings` | `retry_failed_filings:{report_quarter}` | |
| `backfill_daily_indexes` | `backfill_daily_indexes:{start_date}:{end_date}` | |
| `enrich_cusip` | `enrich_cusip:{report_quarter}` | |
| `match_cik` | `match_cik:{manager_id}` | per manager，避免相互阻塞 |
| `quality_check` | `quality_check:{report_quarter}` | |

**冲突 lock group：** `ingest_holdings:{report_quarter}` 和 `retry_failed_filings:{report_quarter}` 不共享相同 `lock_key`，但调度层必须定义 conflict group `quarter_ingestion:{report_quarter}`。同一 conflict group 内，同一时间只允许运行一个 job；调度器在启动前检查 conflict group 是否被占用。

Conflict group 由 scheduler 派生（根据 job_type + 参数推算），**不落库到 `job_runs`**。`job_runs` 中已有 `lock_key` 字段可间接反映；若需要显式存储 conflict group，可在 `job_runs` 增加 `conflict_group` 字段（VARCHAR），scheduler 写入后用于查询互斥状态。V1 可先不落库，由 scheduler 代码约定。

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

-- Admin: Amendment review
GET  /api/v1/admin/13f/amendments/pending
POST /api/v1/admin/13f/amendments/{accession_number}/resolve
  body: { action: "apply" | "activate_as_original" | "reject" | "defer" | "mark_informational" }
  -- apply: 触发 RESTATEMENT holdings 替换，仅限 amendment_type=RESTATEMENT
  -- activate_as_original: 仅用于 NEW_HOLDINGS 类型；admin 确认该 filing 为迟报的原始申报，
  --   将其设为该 manager+quarter 的 active filing（前提：同 manager+quarter 无其他 active filing，
  --   否则系统拒绝并要求先手动解决冲突）
  -- reject: 标记 filing 为 rejected，不参与分析，保留审计记录
  -- defer: 延迟处理，保持 amendments_pending
  -- mark_informational: 标记为信息性修订，不影响 active holdings

-- Admin: CUSIP 映射
GET  /api/v1/admin/13f/cusip-mappings
POST /api/v1/admin/13f/cusip-mappings
PATCH /api/v1/admin/13f/cusip-mappings/{id}          -- 软停用（is_active=false），不物理 DELETE
GET  /api/v1/admin/13f/cusip-mappings/unresolved

-- Admin: Jobs（含 MVP 3 预留批量 reparse 端点）
GET  /api/v1/admin/13f/jobs
POST /api/v1/admin/13f/jobs
POST /api/v1/admin/13f/jobs/{id}/cancel
POST /api/v1/admin/13f/jobs/retry-failed-filings
POST /api/v1/admin/13f/jobs/reparse-by-quarter       -- MVP 3
POST /api/v1/admin/13f/jobs/reparse-by-manager       -- MVP 3

-- Oracle's Lens（用户端）
GET  /api/v1/13f/readiness
GET  /api/v1/13f/managers
GET  /api/v1/13f/managers/{manager_id}/holdings
GET  /api/v1/13f/managers/{manager_id}/holdings/changes   -- MVP 2 正式启用
GET  /api/v1/13f/managers/{manager_id}/quarters
GET  /api/v1/13f/stocks/{stock_id}/holders
```

**Holdings changes 端点在覆盖不足时（MVP 1 期间及历史数据不足时）：**

返回 **HTTP 200**（统一 status，不返回 HTTP 503），body 中 `status` 字段表达不可用状态：

```json
{
  "status": "unavailable",
  "unavailable_reason": "insufficient_consecutive_quarters",
  "available_quarters": 1,
  "required_quarters": 2,
  "supports_snapshot": true,
  "data": null
}
```

**通用 API 约定：**

- 列表接口分页：`?page=1&page_size=50`，响应含 `total_count`、`page`、`page_size`、`has_next`。
- Admin 端点需要 admin 身份验证。Admin batch job trigger 的 rate limit 应与普通 API browsing rate limit 分开配置。
- 用户端只返回用户功能所需字段，不暴露内部错误详情或敏感 job metadata。
- 普通用户 API rate limit：建议 100 req/min/user。

---

## 14. 性能要求

**注：以下 SQL 示例为 PostgreSQL 语法。如项目使用其他数据库，语法需对应调整；`partial unique index` 在非 Postgres 数据库中兼容性不同，需提前确认 migration 方案。**

| 场景 | 目标响应时间 | 说明 |
| --- | --- | --- |
| Oracle's Lens 持仓快照页加载 | P95 ≤ 500ms | 单 manager 单季度 holdings 列表 |
| Oracle's Lens 持仓变化计算 | P95 ≤ 800ms | 依赖 MVP 2 的 precomputed `ownership_changes` 表；changes endpoint 在 MVP 2 前不启用 |
| Admin dashboard overview | P95 ≤ 2s | |
| Admin filings 列表（分页） | P95 ≤ 1s | 50 条/页 |
| Daily sync job（单个 filing） | ≤ 10 分钟 | |
| 季度全量 backfill（100 managers） | ≤ 4 小时 | 含 rate limit 等待 |

关键数据库约束与索引（V1 migration 必须包含）：

```sql
-- Unique constraints
ALTER TABLE filings_13f
  ADD CONSTRAINT uq_filings_accession UNIQUE (accession_number);

ALTER TABLE holdings_13f
  ADD CONSTRAINT uq_holdings_fingerprint
  UNIQUE (accession_number, holding_row_fingerprint);

-- Partial unique: 同一 manager + quarter_end_date 最多一个 active filing
CREATE UNIQUE INDEX uq_active_filing_per_manager_period
  ON filings_13f (manager_id, quarter_end_date)
  WHERE is_active_for_manager_period = true;

-- CUSIP mapping 候选唯一（允许同一 CUSIP 有多个来源、多个候选）
ALTER TABLE cusip_ticker_map
  ADD CONSTRAINT uq_cusip_mapping UNIQUE (cusip, source, ticker, exchange);

-- Query path indexes
CREATE INDEX idx_holdings_filing_id       ON holdings_13f (filing_id);
CREATE INDEX idx_holdings_manager_quarter ON holdings_13f (manager_id, report_quarter);
CREATE INDEX idx_holdings_manager_qend    ON holdings_13f (manager_id, quarter_end_date);
CREATE INDEX idx_holdings_cusip           ON holdings_13f (cusip);
CREATE INDEX idx_holdings_stock_id        ON holdings_13f (stock_id);
CREATE INDEX idx_holdings_put_call        ON holdings_13f (put_call);
CREATE INDEX idx_filings_manager_quarter  ON filings_13f (manager_id, report_quarter);
CREATE INDEX idx_filings_manager_qend     ON filings_13f (manager_id, quarter_end_date);
CREATE INDEX idx_filings_active           ON filings_13f (is_active_for_manager_period);
CREATE INDEX idx_filings_parser_version   ON filings_13f (parser_version);
CREATE INDEX idx_sync_status              ON edgar_sync_status (status, sync_date);
CREATE INDEX idx_job_runs                 ON job_runs (status, job_type, created_at);
```

---

## 15. 监控与告警

### 15.1 告警级别

| 级别 | 含义 | 通知触达时效 | 通知渠道 |
| --- | --- | --- | --- |
| P1 | 数据管线完全中断或数据错误风险高 | ≤ 15 分钟 | Discord（MVP 1A）；Email 可选，`ALERT_EMAIL_ENABLED` 配置 |
| P2 | 部分功能降级，需要当日处理 | ≤ 2 小时 | Discord（无 @mention） |
| P3 | 非紧急问题，需要跟踪 | ≤ 1 个工作日 | Discord 低优先级频道（无 @mention） |

### 15.2 触发告警的条件

| 条件 | 级别 | 备注 |
| --- | --- | --- |
| Daily sync 连续 2 个**工作日**（排除 no_index_expected_dates）`failed` | P1 | |
| 当季度 filing window 关闭后 3 天内，expected filer 覆盖率 < 70%（参数 `COVERAGE_P1_THRESHOLD=0.70`） | P1 | 仅 window 已关闭后触发；70% 为告警警戒线，80% 为 ready 达标线 |
| 单个 filing ingest job 超时重试 3 次 | P2 | |
| Common share CUSIP 映射率 < 50%（**window 已关闭**，参数 `CUSIP_MAPPING_P1_THRESHOLD=0.50`） | P1 | |
| Common share CUSIP 映射率 50%–70%（**window 已关闭**） | P2 | |
| 存在 `amendment_failed` 状态超过 24 小时未处理 | P2 | |
| 影响 latest usable quarter 的 `amendments_pending`（RESTATEMENT 类型）超过 24 小时未处理 | P2 | RESTATEMENT pending 直接影响产品数据完整性，阈值低于一般 pending |
| 影响 latest usable quarter 的 `amendments_pending`（非 RESTATEMENT 类型）超过 48 小时未处理 | P2 | |
| `parse_status=needs_review` 的 filing 超过 7 天未被 admin 处理 | P3 | 防止 needs_review 状态永久卡死 |
| Job `running` 状态超过超时阈值（见 §12.4）未刷新 lease | P2 | |
| SEC EDGAR 请求连续收到 429 或 403 | P1 | 可能触发 IP 封禁 |
| Oracle's Lens readiness 在 **window 已关闭**的季度从 `ready` 降级 | P2 | |
| Oracle's Lens readiness 在 **window 已关闭**的季度降级至 `unavailable` | P1 | |

### 15.3 数据健康日报

每日美东时间 08:00 自动发送摘要到 Discord，包含：

- 昨日 sync 状态；当前季度 expected filer 覆盖率；nt_filer 数量
- 最新 failed filings 数量；待处理 amendments_pending 数量
- 最新 CUSIP 映射率（common shares）
- Oracle's Lens readiness 状态；nt_detection_supported 状态

---

## 16. UX Copy Principles

用户侧 13F 页面必须始终展示数据时效性。

推荐文案：

```text
Holdings data as of 2026-03-31. Managers file 13F reports up to 45 calendar days after quarter end,
so current-quarter data may update until approximately 2026-05-15.
```

规则：

- 说 "13F filings are delayed snapshots."
- 说 "Holdings data as of [quarter_end_date]."
- 说 "Current-quarter data may still update during the filing window."
- 不说 "current holdings"、"guru cost basis"、"buy signal"。
- 不把缺失数据展示成 0。
- 不把 `total_13f_reported_value_usd` 展示为完整 AUM；必须标注 *"Based on 13F-reported securities only."*
- API / 前端 label 中 `portfolio_weight_pct` 统一显示为 **"13F common weight"**，不使用裸标签 "portfolio weight"。
- Options 持仓在独立 tab 或 filter 展示，不混入 common share 主信号和权重计算；options 行不展示 "13F common weight"（字段为 null）。
- 13F-NT 季度：展示为 "No 13F holdings reported this quarter (notice filed)"，不显示为数据缺失或 "0 positions"。

---

## 17. MVP Delivery Plan

依赖顺序：1B 依赖 1A → 1C-1 依赖 1B → 1C-2 依赖 1C-1 → MVP 2 依赖 1C-2 → MVP 3 依赖 MVP 2。

### MVP 1A: Manager + Daily Index 基础设施

- Manager CRUD（含所有字段定义；`value_unit_override` 需 admin 确认才生效）
- CIK confirm / reject（EFTS name search；无结果/多结果处理）
- 批量 CSV 导入（含可选字段 `manager_type`、`is_featured`）
- `edgar_sync_status` 表（含 `tracked_13f_hr_found_count`、`tracked_13f_nt_found_count`）
- daily form.idx fetch and parse（筛选 13F-HR / 13F-HR/A / **13F-NT**；节假日 proxy；404 retry 逻辑）
- `no_index_expected_dates` 维护机制
- 全局 EDGAR rate limiter；SEC_CONTACT_EMAIL 启动时 fail-fast 验证
- job_runs + lock_key + conflict group + lease token + 超时规则
- P1/P2/P3 告警基础设施（Discord webhook；email `ALERT_EMAIL_ENABLED` 配置）

### MVP 1B: Filing + Holdings Ingestion + Amendment Replacement

- Fetch 13F-HR / 13F-HR/A filing detail / information table
- **Fetch 13F-NT filing header**，从 `periodOfReport` 归属季度，保存 raw document
- Parse holdings（`source_row_index` 在过滤前赋值；`fingerprint_version`；`parser_version`）
- `value_raw` + `value_unit_raw` 审计字段写入
- 两层去重防火墙；`needs_review` 超 7 天 P3 告警
- §6.4 原子替换写入顺序（先 DELETE 再 INSERT，同一事务）
- `periodOfReport` routing（含所有异常处理；±1–2 日归一化条件使用 valid filing window 而非季度相同）
- **Amendment type 解析**（normalized enum + raw）
- RESTATEMENT 原子替换（parse 成功后才切 active）；PARTIAL / NEW_HOLDINGS / unknown → needs_review
- **多 RESTATEMENT accepted_at 相同时不自动切 active → amendments_pending**
- `total_13f_reported_value_usd` 和 `total_13f_common_value_usd` 写入
- OpenFIGI CUSIP 映射（独立 rate limiter；缓存 TTL=30天；失败不阻塞 ingestion）
- Backfill 预览 + 确认流程（默认 `DEFAULT_BACKFILL_START_QUARTER=2023-Q1`）
- 所有 unique constraints 和 indexes（见 §14）

### MVP 1C-1: Readiness + Oracle's Lens Safe Integration

- **13F-NT notice-of-non-filing 标记 / expected filer exclusion**（MVP 1C 必须完成，否则不进入 ready）
- Readiness summary（含 expected filer denominator；`nt_detection_supported`；`coverage_ratio` estimated 标记）
- Data freshness display；snapshot-only gating；zero vs unavailable 区分
- Holdings changes endpoint：返回 HTTP 200 + `status=unavailable` + structured reason（不返回空数组）
- Options 与 common shares 分离展示；`portfolio_weight_pct` null for options
- `amendments_pending` > 48 小时降级 readiness 逻辑

### MVP 1C-2: Admin Dashboard

- Admin dashboard：Overview + Managers + Daily Sync + Jobs + Filings + Readiness 页面
- Jobs 页面完整过滤（含所有状态枚举）；amendment review 页面（含 resolve 四种 action）
- 数据健康日报（Discord 摘要）

### MVP 2: Change Analysis

- Consecutive-quarter comparison（stock_id 优先；CUSIP fallback；CUSIP_CHANGED 处理）
- `no_prior_data` vs `new_position` 区分（数据 gap 时不标 new）
- New / exit / increased / reduced calculation
- `holding_streak_quarters`（不跨 coverage_gap；引用 §9 定义）
- Corporate action heuristic（多档阈值；标记 "possible"，不作确定判断）
- Historical coverage gating；4-quarter annual trend support
- `portfolio_weight_pct` 计算填充（MVP 1B 已留字段，MVP 2 填充）
- **precomputed `ownership_changes` 表**（支撑 P95 800ms）
- Holdings changes endpoint 正式启用

### MVP 3: Resilience And Backfill

- Full historical backfill tools；partial success retry queue
- 历史 amendment 批量回补；Dataroma CUSIP 来源（source="dataroma"）
- 批量 reparse by quarter / manager API 端点
- `cusip_ticker_map` needs_review 后台 UI（多候选确认）
- 完整告警规则全覆盖；数据完整性定期校验 job
- `value_unit_override` filing 级别覆盖（已知 gap 实现）

---

## 18. Acceptance Criteria

### 18.1 Functional Acceptance Criteria

- Admin can create, edit, deactivate, and review tracked managers; `value_unit_override` requires explicit admin confirmation.
- Candidate CIKs do not participate in ingestion until confirmed.
- System shows backfill preview with default start quarter before triggering; admin must confirm.
- Daily sync identifies and processes 13F-HR, 13F-HR/A, and 13F-NT.
- 13F-NT filing header is fetched; `periodOfReport` determines which quarter the NT covers; raw document is saved; no information table is fetched.
- 13F-NT manager + quarter is marked `nt_filed`, excluded from expected filers denominator.
- System skips no_index_expected_dates without marking failed; 404 responses are retried before marking no_data.
- `periodOfReport` ±1–2 day auto-normalization only applies when form type is **13F-HR or 13F-HR/A** AND `accepted_at` is within valid filing window (quarter_end to quarter_end + 180 days). Missing or invalid period → `needs_review`, never auto-inferred from `accepted_at`.
- `needs_review` filings older than 7 days trigger a P3 alert.
- Amendment type is parsed (normalized enum + raw). RESTATEMENT triggers atomic replacement after successful parse. PARTIAL / NEW_HOLDINGS / unknown → `amendments_pending`.
- When multiple RESTATEMENT amendments have identical `accepted_at`, the system does NOT auto-switch active; marks `amendments_pending` + `amendment_sort_warning=true` for admin review.
- Active filing only switches to amendment after successful parse; failed parse leaves old active intact.
- Holdings changes endpoint returns HTTP 200 with `status=unavailable` + structured reason when coverage is insufficient — not empty array, not HTTP 503.
- `total_13f_reported_value_usd` covers all holdings including options; `total_13f_common_value_usd` covers common shares only and is the denominator for `portfolio_weight_pct`.
- `portfolio_weight_pct` is null for options holdings; API/frontend label is "13F common weight".
- Change analysis uses `stock_id` as primary match key; CUSIP change on same `stock_id` → `CUSIP_CHANGED`, not exit+new.
- When prior quarter data is a gap (not 13F-NT), current holdings are tagged `no_prior_data`, not `new_position`.
- When prior quarter is 13F-NT (no reported holdings), current position may be tagged `new_position` with caveat.
- `holding_streak_quarters` does not span data gap quarters; 13F-NT quarters are not treated as gaps.
- `amendments_pending` affecting latest usable quarter and older than 48 hours downgrades readiness to at most `usable_with_warning`.
- Without `nt_detection_supported`, system cannot reach `ready`; coverage ratio marked `estimated=true`.
- CUSIP mapping DELETE is not physical; uses soft-deactivate (`PATCH is_active=false`).
- Coverage and CUSIP mapping alerts fire only after filing window closes.

### 18.2 Testable Acceptance Criteria

- Given a daily index containing a tracked manager and form `13F-NT`, the system fetches the NT filing header, reads `periodOfReport`, marks manager as `nt_filed` for that quarter, and saves raw document; no information table is fetched.
- Given a daily index containing a tracked manager and form `13F-HR`, the system creates a filing ingestion task.
- Given a filing with `periodOfReport=2026-03-31` and `accepted_at=2026-04-15`, the system assigns it to `2026-Q1`.
- Given a filing with `periodOfReport=2026-03-30` (±1 day), form type `13F-HR`, and `accepted_at=2026-04-15` (within valid filing window), the system normalizes to `2026-03-31` with `PERIOD_WEEKEND_ADJUSTED`.
- Given a filing with `periodOfReport=2026-03-30` and `accepted_at=2026-12-01` (outside 180-day window), the system marks `needs_review` with `PERIOD_WEEKEND_ADJUSTED_UNVERIFIABLE`, not auto-normalized.
- Given a filing with missing `periodOfReport`, the system sets `parse_status=needs_review` and `PERIOD_MISSING`; assigns no quarter; excludes from active holdings; creates admin review task.
- Given `needs_review` filing is not reviewed within 7 days, a P3 alert fires.
- Given a `13F-HR/A` with `amendmentType=RESTATEMENT` and successful parse, the system atomically replaces active holdings; old filing `is_active_for_manager_period=false`.
- Given two RESTATEMENT amendments with identical `accepted_at`, the system marks `amendments_pending` + `amendment_sort_warning=true`, does not auto-switch active.
- Given a `13F-HR/A` parse fails, the old active filing retains `is_active_for_manager_period=true` and continues serving data.
- Given a `13F-HR/A` with `amendmentType=ADDITIONS CORRECTIONS DELETIONS`, the system marks `amendments_pending`; active holdings are unchanged.
- Given `amendments_pending` on the latest usable quarter is older than 48 hours, readiness is at most `usable_with_warning`.
- Given the same accession is processed twice, holdings count does not double.
- Given manager+quarter has `nt_filed=true`, that manager is excluded from expected filers denominator for that quarter.
- Given `nt_detection_supported=false`, readiness API returns at most `usable_with_warning`; `coverage_ratio.estimated=true`.
- Given holdings changes endpoint is called with only one quarter available, it returns HTTP 200 with `status=unavailable` and `unavailable_reason`, not empty array and not HTTP 503.
- Given a security's CUSIP changes between two quarters but both CUSIPs map to same `stock_id`, the system tags `CUSIP_CHANGED` and does not create exit + new position pair.
- Given prior quarter is a data gap (no active filing, no 13F-NT), the current quarter holding is `change_status=no_prior_data`, not `new_position`.
- Given prior quarter the manager filed 13F-NT and the security is held this quarter, `change_status=new_position` with NT caveat.
- Given CUSIP is 7 characters, system marks `invalid_cusip`; does not pad or create erroneous mapping.
- Given admin calls PATCH to deactivate a CUSIP mapping, `is_active=false` is set; the row is not physically deleted.
- Given CUSIP mapping rate < 50% after filing window closes, P1 alert fires within 15 minutes.
- Given CUSIP mapping rate < 50% while filing window is still open, no P1 alert fires.

---

## 19. 产品决策（已关闭）

| 问题 | 决策 |
| --- | --- |
| Manager type V1 支持范围 | `fundamental_long`、`activist`、`quant`、`multi_strategy`、`index_like`、`unknown` |
| Options 默认处理策略 | 变化分析默认仅 common shares（`put_call IS NULL`）；options 单独 tab/filter 展示，不混入主信号和 `portfolio_weight_pct` 计算；options 行 `portfolio_weight_pct = null` |
| Options value 展示口径 | Options tab 展示 `value_usd_thousands` 原始值；不计入 13F common aggregate；不展示 portfolio weight |
| 历史回补默认起始季度 | `DEFAULT_BACKFILL_START_QUARTER=2023-Q1`（环境变量，可覆盖；上线前如需调整直接改配置） |
| `featured` managers 排序 | Oracle's Lens 默认列表中置顶展示；不影响数据覆盖范围（V1 支持字段，排序 boost 实现在 V1 后） |
| 最低 linked holdings ratio 门槛 | < 50% 阻断 change analysis（仅展示 snapshot）；50%–70% 展示 warning 但不阻断 snapshot |
| Admin 告警渠道 | Discord（MVP 1A 实现 webhook）；Email 可选（`ALERT_EMAIL_ENABLED`）；P3 告警到 Discord 低优先级频道（无 @mention） |
| **13F-NT 支持** | **MVP 1C-1 必须实现**；daily sync 识别并存储 13F-NT；未实现时 readiness 不进入 `ready` |
| Holdings changes endpoint HTTP status | **HTTP 200 + body `status=unavailable`**；不返回 HTTP 503；不返回空数组 |
| Amendment accepted_at 相同时 fallback | **不自动切 active**；进入 `amendments_pending` + `amendment_sort_warning=true`，等待 admin 确认 |
| CUSIP mapping 物理删除 | **禁止**；使用 `PATCH is_active=false` 软停用，保留审计历史 |

---

## 20. Open Questions

| 优先级 | 问题 | 背景 |
| --- | --- | --- |
| MVP 2 前 | Corporate action 外部数据来源确认 | §7.3 heuristic 为临时方案；接入可靠数据源后替换 |
| MVP 2 前 | 变化计算的最低 CUSIP 映射率门槛是否需要 per-manager 设置 | 部分 manager 持有大量小市值股票，映射率天然偏低 |
| MVP 2 前 | 是否新增独立字段 `options_weight_pct`（在 options universe 内的占比） | §19 已决策 options 行 `portfolio_weight_pct = null`；若需要展示 options 内部权重，需独立字段 |
| MVP 3 前 | `value_unit_override` filing 级别覆盖实现 | V1 已标记为 known gap；MVP 1B 中 manager-level override 必须默认关闭，需 admin 明确确认（含 confirmed_by + confirmed_at）后才应用到历史 filings，防止单个 filing 异常污染全部历史数据 |
| 未来 | 是否在 Oracle's Lens 展示 manager 层面的 13F reported value 季度趋势 | 需 UI 层明确标注"13F-reported value only, not AUM" |
