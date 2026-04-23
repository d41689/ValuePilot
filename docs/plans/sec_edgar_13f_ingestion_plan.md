# SEC EDGAR + Dataroma 13F 数据抓取方案

## 1. 背景与目标

13F 是美国 SEC 要求机构投资者（AUM > $100M）每季度申报的持仓报告，包含所有长仓股票持仓。抓取该数据的目标是：

- 追踪知名机构（Buffett、Ackman 等）持仓变化
- 与 ValuePilot 现有股票数据关联，支持持仓覆盖度分析
- 为未来的 smart money 信号提供原始数据

数据源：**SEC EDGAR**（官方）+ **Dataroma**（第三方聚合），两者互补。

---

## 2. 双数据源对比与策略

### 2.1 两个数据源的特性对比

| 维度 | SEC EDGAR | Dataroma |
|------|-----------|----------|
| 数据权威性 | **官方原始数据** | 第三方处理，来源自 EDGAR |
| 机构覆盖范围 | 全部 6000+ 13F 申报机构 | 约 150 位精选"超级投资者" |
| Ticker 标识符 | ❌ 只有 CUSIP，需自行映射 | ✅ 直接提供 ticker 符号 |
| 季度环比变化 | ❌ 需自行计算 | ✅ 已标注 New/Add/Reduce/Exit |
| 访问方式 | 官方 JSON/XML API | HTML 页面（需解析） |
| 数据稳定性 | **长期可靠**，格式有版本控制 | 非官方，页面结构随时可能变化 |
| 速率限制 | 10 req/s，强制执行 | 无明确限制，需保守抓取 |
| 历史数据深度 | 1993 年至今，完整归档 | 较近期数据，历史有限 |
| 数据时效 | 与 SEC 申报同步 | 依赖定期更新，可能有额外延迟 |

### 2.2 双源策略：EDGAR 为主，Dataroma 为辅

推荐策略：**"Dataroma 做发现与引导，EDGAR 做权威数据"**

```
Dataroma 的职责（Discovery Layer）：
  1. 维护"超级投资者"白名单 → 从 managers.php 自动同步
  2. 提供 Dataroma manager code → CIK 的映射种子
  3. 提供现成的 ticker 符号，加速 CUSIP 映射冷启动

EDGAR 的职责（Source of Truth）：
  1. 所有持仓数据的权威来源
  2. 完整历史归档（回溯任意季度）
  3. 超出 Dataroma 白名单的机构覆盖
```

**策略决策树**——遇到具体问题时如何选择数据源：

```
需要某机构的持仓数据？
  └─ 该机构在 Dataroma 白名单中？
       ├─ 是 → 优先从 EDGAR 获取，用 Dataroma ticker 辅助映射
       └─ 否 → 仅从 EDGAR 获取（Dataroma 无此数据）

需要 CUSIP → ticker 映射？
  └─ 先查本地 cusip_ticker_map 缓存
       ├─ 命中 → 直接使用
       └─ 未命中 → 查 Dataroma holdings（如果该机构在白名单）→ 再查 EDGAR company search

发现数据不一致（EDGAR vs Dataroma）？
  └─ 以 EDGAR 为准，记录差异日志，触发人工 review
```

### 2.3 Dataroma 的访问限制与合规判断

**robots.txt**：不存在（URL 重定向到主页），即无任何爬取禁止指令。

**Terms of Service 关键条款（Clause 4）**：
> "No republishing, reproducing, redistributing or selling of the content is allowed."

**个人使用合规判断**：

| 条件 | 结论 |
|------|------|
| robots.txt 有禁止指令？ | ✅ 无（文件不存在） |
| ToS 明确禁止爬取/自动访问？ | ✅ 未提及 scraping/crawling/bots |
| ToS 禁止"再发布/转售" | ⚠️ 明确禁止——数据不得对外发布或出售 |
| 个人私用、不对外分发 | ✅ 不违反 Clause 4 核心禁止项 |
| 商业用途 | ❌ 需另行获得授权 |

**结论**：个人私用（数据存入本地数据库、不对外分发）属于**灰色区域，但实际风险极低**。ToS 明确禁止的是"再发布/出售"，而非私人存储分析。

**降低风险的架构原则**（已体现在设计中）：
- Dataroma 仅用于 Discovery，每季度请求量极小（约 150 个页面）
- 持仓权威数据来自 EDGAR，不依赖 Dataroma 的持仓内容
- ToS 变化时可一键切换到纯 EDGAR 流程，零影响核心功能

| 访问限制项 | 情况 | 策略 |
|--------|------|------|
| robots.txt | 不存在 | 无需遵守 |
| 速率限制 | 无明文规定 | 保守设置 **1 req/2s** |
| 反爬措施 | 目前无 Cloudflare/登录墙 | 做好降级方案 |
| 页面结构变化 | 随时可能改变 | 解析失败时告警，不静默失败 |

---

## 3. EDGAR 官方限制与合规要求

### 2.1 速率限制（强制执行）

| 限制项 | 值 | 说明 |
|--------|-----|------|
| 最大请求频率 | **10 req/s** | 超过会被 IP 封禁（429 或直接断连） |
| 推荐安全频率 | **≤ 5 req/s** | 官方建议留有余量 |
| 并发连接数 | **1 个 IP 不超过 2** | 多线程须注意 |

> 封禁通常为临时性（数小时），但频繁触发可能导致永久 IP 封禁并需向 SEC 申诉解封。

### 2.2 User-Agent 强制要求

每个 HTTP 请求**必须**包含 User-Agent 头，格式：

```
User-Agent: <公司名/应用名> <联系邮件>
```

例：`User-Agent: ValuePilot dane@example.com`

缺少或使用通用 User-Agent（如 `python-requests/2.x`）会被直接拒绝（403）。

### 2.3 数据特性限制

| 特性 | 说明 |
|------|------|
| 只含多头持仓 | 不披露空仓、期权 delta 调整后净头寸 |
| 滞后 45 天 | 季末后 45 日内申报，信息存在时效性 |
| 价值单位 | `value` 字段单位为 **千美元（$1,000s）** |
| CUSIP 标识符 | 部分 CUSIP 为过期或非标准值，需映射到 ticker |
| 持仓阈值豁免 | 价值 < $200K 且股数 < 10,000 的仓位可不申报 |
| 保密申请 | 机构可申请延迟披露特定持仓（confidential treatment） |
| 仅覆盖美国上市证券 | ADR 会出现，但外国普通股通常不在列 |

---

## 3. EDGAR API 端点

### 3.1 主要使用的端点

```
# 查机构 CIK 和历史申报列表
GET https://data.sec.gov/submissions/CIK{cik:010d}.json

# 全文检索（按 form 类型、日期范围搜 13F）
GET https://efts.sec.gov/LATEST/search-index?q=&forms=13F-HR&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD

# 季度索引（批量获取所有 13F 申报元数据）
GET https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{n}/form.idx

# 具体申报文件目录
GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/

# 申报 XML（信息表，含实际持仓）
GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/infotable.xml
```

### 3.2 13F 申报文件结构

每份 13F-HR 申报包含两个关键文件：

```
primary-doc.xml   ← 封面信息（机构名、申报日期、季度等）
infotable.xml     ← 持仓明细（每行一个持仓）
```

`infotable.xml` 的核心字段：

```xml
<infoTable>
  <nameOfIssuer>APPLE INC</nameOfIssuer>
  <titleOfClass>COM</titleOfClass>
  <cusip>037833100</cusip>
  <value>1234567</value>          <!-- 千美元 -->
  <shrsOrPrnAmt>
    <sshPrnamt>5000000</sshPrnamt>
    <sshPrnamtType>SH</sshPrnamtType>
  </shrsOrPrnAmt>
  <investmentDiscretion>SOLE</investmentDiscretion>
  <votingAuthority>
    <Sole>5000000</Sole>
    <Shared>0</Shared>
    <None>0</None>
  </votingAuthority>
</infoTable>
```

---

## 4. 数据模型设计

### 4.1 新增表结构

```sql
-- 机构管理人
CREATE TABLE institution_managers (
    id              SERIAL PRIMARY KEY,
    cik             VARCHAR(10) UNIQUE NOT NULL,   -- EDGAR CIK，10位补零
    name            TEXT NOT NULL,
    name_normalized TEXT,                           -- 去噪后的标准名
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 13F 申报元数据
CREATE TABLE filings_13f (
    id              SERIAL PRIMARY KEY,
    manager_id      INTEGER REFERENCES institution_managers(id),
    accession_no    VARCHAR(20) UNIQUE NOT NULL,   -- 格式: 0001234567-24-000001
    period_of_report DATE NOT NULL,                -- 持仓截止日（季末）
    filed_at        DATE NOT NULL,                  -- 实际申报日
    form_type       VARCHAR(10) NOT NULL,           -- 13F-HR 或 13F-HR/A
    total_value     BIGINT,                         -- 封面页汇总值（千美元）
    ingested_at     TIMESTAMPTZ DEFAULT NOW()
);

-- 持仓明细
CREATE TABLE holdings_13f (
    id                  SERIAL PRIMARY KEY,
    filing_id           INTEGER REFERENCES filings_13f(id),
    cusip               VARCHAR(9) NOT NULL,
    issuer_name         TEXT NOT NULL,
    title_of_class      TEXT,
    value_thousands     BIGINT NOT NULL,            -- 千美元
    shares              BIGINT,
    investment_discretion VARCHAR(10),              -- SOLE/SHARED/OTHER
    -- 关联到 stocks 表（按 CUSIP 或 ticker 映射，可空）
    stock_id            INTEGER REFERENCES stocks(id),
    INDEX (filing_id),
    INDEX (cusip),
    INDEX (stock_id)
);
```

### 4.2 Dataroma 元数据表

```sql
-- Dataroma 超级投资者元数据（与 institution_managers 关联）
ALTER TABLE institution_managers ADD COLUMN dataroma_code VARCHAR(20);  -- e.g. "BRK"
ALTER TABLE institution_managers ADD COLUMN is_superinvestor BOOLEAN DEFAULT FALSE;
ALTER TABLE institution_managers ADD COLUMN dataroma_synced_at TIMESTAMPTZ;
```

`institution_managers` 中 `cik` 仍是主键，`dataroma_code` 是可空的附加标识，用于关联 Dataroma 页面 URL（`holdings.php?m={dataroma_code}`）。

### 4.3 CUSIP → Ticker 映射

```sql
CREATE TABLE cusip_ticker_map (
    cusip       VARCHAR(9) PRIMARY KEY,
    ticker      VARCHAR(10),
    issuer_name TEXT,
    source      VARCHAR(20),    -- 'dataroma' | 'edgar_search' | 'manual'
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

映射填充优先级：
1. **Dataroma holdings 页**（直接有 ticker，覆盖白名单机构持仓的 CUSIP）
2. **EDGAR company search** API
3. 手动补充

---

---

## 5. 抓取流程设计

### Step 0：白名单引导（Dataroma → EDGAR，一次性）

```
1. 抓取 dataroma.com/m/managers.php
   → 解析所有 superinvestor 的 name + dataroma_code
   → 写入 institution_managers（is_superinvestor=true, dataroma_code）

2. 对每个 superinvestor，查 EDGAR submissions API 补充 CIK：
   GET https://efts.sec.gov/LATEST/search-index?q="{manager_name}"&forms=13F-HR
   → 匹配 CIK，更新 institution_managers.cik

3. 结果：institution_managers 表里有 ~150 条带 CIK + dataroma_code 的超级投资者
```

### Step 1：机构申报元数据抓取（EDGAR，季度批量）

```
1. 从 full-index 季度索引获取所有 13F-HR 申报元数据
   GET https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{n}/form.idx
   → 过滤 CIK 在白名单中的申报（Phase A）
   → 写入 filings_13f（仅元数据，不含持仓明细）
```

### Step 2：持仓数据抓取（EDGAR，按申报）

```
1. 查询 filings_13f 中 holdings 未抓取的记录
2. 构建文件目录 URL，定位 infotable.xml
3. 解析 XML → 写入 holdings_13f
4. 对每个新 CUSIP，触发 cusip_ticker_map 填充（先查 Dataroma，再查 EDGAR）
```

### Step 3：CUSIP 映射填充（Dataroma 优先）

```
对每个白名单机构：
  1. 抓取 dataroma.com/m/holdings.php?m={dataroma_code}
  2. 解析 HTML 表格：ticker + cusip（如页面有） + issuer_name
  3. 写入 cusip_ticker_map（source='dataroma'）
  
对剩余未映射的 CUSIP：
  4. 查 EDGAR company search API（source='edgar_search'）
```

### Step 4：增量更新（定期）

```
触发条件：每季度（Q1→5/15, Q2→8/14, Q3→11/14, Q4→2/14）
EDGAR 侧：抓取最新季度 form.idx，只处理新 accession_no
Dataroma 侧：重新抓取 managers.php，同步白名单新增/移除的机构
注意：13F-HR/A（修订版）需按 (manager_id, period_of_report) upsert holdings
```

---

## 6. 限速与重试策略

```python
# EDGAR（data.sec.gov / www.sec.gov）
EDGAR_REQUEST_DELAY_S = 0.2     # 5 req/s，低于 10 req/s 上限
EDGAR_MAX_RETRIES     = 3
EDGAR_RETRY_BACKOFF_S = [5, 30, 120]

# Dataroma（非官方，保守抓取）
DATAROMA_REQUEST_DELAY_S = 2.0  # 0.5 req/s，避免触发反爬
DATAROMA_MAX_RETRIES     = 2
DATAROMA_RETRY_BACKOFF_S = [10, 60]

# 通用规则：
# 遇到 429 / 503：全局暂停 60s，以 1 req/s 重启
# 遇到 403：检查 User-Agent（EDGAR）或页面结构变化（Dataroma），不自动重试
# Dataroma 解析失败（HTML 结构变化）：告警 + 降级到纯 EDGAR 流程，不静默失败
```

---

## 7. 实施阶段

### Phase A（MVP）— 超级投资者白名单 + EDGAR 持仓
- [ ] 数据库 migration（`institution_managers`、`filings_13f`、`holdings_13f`、`cusip_ticker_map`）
- [ ] EDGAR HTTP client（User-Agent、限速 5 req/s、退避重试）
- [ ] Dataroma HTTP client（限速 0.5 req/s、HTML 解析失败告警）
- [ ] `managers.php` 解析器 → 填充超级投资者白名单 + CIK 映射（约 80 位）
- [ ] `form.idx` 解析器（季度索引）
- [ ] `infotable.xml` 解析器
- [ ] Dataroma `holdings.php` 解析器 → 填充 `cusip_ticker_map`
- [ ] CLI 命令：
  - `edgar bootstrap-whitelist` — 从 Dataroma 初始化超级投资者列表
  - `edgar fetch-holdings --quarter 2025-Q1` — 按季度抓取持仓
  - `edgar backfill --quarters 4` — 回溯最近 4 个季度（2024-Q2 → 2025-Q1）

**回溯范围**：最近 4 个季度（从运行时当前季度往前推 4 个）。80 位机构 × 4 季度 ≈ 320 次 EDGAR 申报抓取，约 32,000 条持仓记录，可在 1-2 小时内完成。

### Phase B — CUSIP 映射完善
- [ ] EDGAR company search 补充未映射 CUSIP
- [ ] 自动关联 `holdings_13f.stock_id`

### Phase C — API 层
- [ ] `GET /api/v1/institutions` — 机构列表（支持 `?superinvestor=true` 过滤）
- [ ] `GET /api/v1/institutions/{cik}/holdings?period=2024-Q4` — 持仓快照
- [ ] `GET /api/v1/stocks/{ticker}/institutions` — 某股票的机构持仓者

### Phase D — 定期增量
- [ ] 定时任务每季度自动运行：Dataroma 白名单同步 + EDGAR 新申报抓取

---

## 8. 关键风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| EDGAR IP 封禁 | 严格限速 5 req/s + 退避；生产用独立 IP |
| Dataroma 页面结构变化 | 解析失败时告警，自动降级到纯 EDGAR 流程 |
| Dataroma 下线或反爬升级 | 系统设计上 Dataroma 只是 Discovery 层，降级影响有限 |
| CUSIP 映射缺失 | 允许 stock_id 为空，异步补充；Dataroma 可覆盖大部分白名单持仓 |
| infotable.xml 格式变化 | 容错 XML 解析，记录解析失败行 |
| 13F-HR/A 修订覆盖 | 按 (manager_id, period_of_report) 做 upsert，保留修订历史 |
| 数据量规模 | 全量约 6000+ 机构，Phase A 只做 ~150 白名单机构 |

---

## 9. 不在此次范围内

- 13D/13G（大股东披露）
- Form 4（内部人交易）
- 期权持仓解析（13F 包含但格式复杂）
- 实时/日内数据（13F 本身是季度数据）
