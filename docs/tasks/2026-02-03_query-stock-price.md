

---
# Task: 股票池“按需刷新（Lazy Refresh）”日线行情机制（V1）

**Task ID**：T-2026-02-03-stock-pool-lazy-refresh  
**Priority**：P1  
**Type**：Data Pipeline / Market Data  
**Status**：PROPOSED  
**Owner**：Data / Backend  
**Created**：2026-02-03  

---

## 1. Goal（目标）

为股票池页面实现一个**非实时（EOD）、按需触发**的行情刷新机制：

- 不做持续轮询、不追求实时行情  
- **仅在用户打开股票池页面时**，如果本地还没有“当日交易日”的日线数据，才刷新  
- 如果**当日已收盘，且收盘数据已经存在**，则**不再刷新**（见 §6 的“收盘后确认刷新”上限）  
- 支撑免费/低配额行情源（开发期），同时为未来升级交易系统级数据留好接口

---

## 2. Non-Goals / Out of Scope（明确不做什么）

- ❌ 不提供交易所授权的实时行情  
- ❌ 不做分钟级 / tick 级行情  
- ❌ 不在 V1 引入 corporate actions（拆股/分红）的统一调整或 total return 口径  
- ❌ 不新增交易日历表（holiday/half-day 等复杂日历在后续版本解决；V1 采用近似策略，见 §5.2）

---

## 3. Core Assumptions（前提假设）

- 行情粒度：**日线（EOD bars）为主**
- V1 默认只支持美股（NYSE/NDQ 等），以 **US/Eastern** 的“收盘后”判定近似处理（不覆盖所有节假日/半日交易）
- 行情源通过可插拔 provider 接口接入（具体供应商在本任务中不锁定；只要求具备 daily OHLC 能力）
- 行情数据存在轻微延迟、收盘后短时间内可能有修订，V1 可接受

---

## 4. Data Model（数据模型）

本任务不引入新表，直接使用现有 schema/ORM 中的 `stock_prices`：

- PRD: `docs/prd/value-pilot-prd-v0.1.md` 中的 `stock_prices` 表定义
- Code: `backend/app/models/stocks.py` 中的 `StockPrice` ORM

说明：
- `stock_prices.price_date` 是交易日（date），不存 intraday 时间。
- V1 不新增 `is_final` 字段；“是否最终收盘”按 ingestion 时间启发式推断（见 §6）。
- V1 不新增“刷新状态表”；节流/幂等通过查询 `stock_prices`（同一天是否已拉取、最近一次拉取时间）实现。

---

## 5. Refresh Decision Logic（刷新判定逻辑）

### 5.1 触发时机

- **仅在用户打开股票池页面时触发**
- 不做后台定时轮询
- 若股票池 UI/API 尚未落地，本任务允许先提供“按 stock_id 列表刷新”的等价接口（见 §8）。

---

### 5.2 判定步骤（单个 stock_id）

**Step 1：确定目标交易日 `target_date`（V1 近似）**
- 使用 US/Eastern 当前日期 `today_et`
- 若 `today_et` 是周六/周日，则 `target_date` 取上一个周五
- 若 `today_et` 是周一且在开盘前（V1 以常规美股开盘 09:30 ET 为准），则 `target_date` 取上一个周五
- 其他工作日：
  - 若当前时间 < 收盘后缓冲（默认 16:30 ET），`target_date = yesterday_et`
  - 否则 `target_date = today_et`

> 注：holiday/half-day 未覆盖，V1 允许少量误判（最终由节流与“有数据就不再拉”的规则兜底）。

**Step 2：判断是否需要刷新**

需要刷新当日日线的条件（全部满足）：
- 数据缺失：不存在 `stock_prices` 记录满足：
  - `stock_id = <id>` 且 `price_date = target_date`
- 或（收盘后允许一次“确认刷新”）：存在 `price_date = target_date` 的记录，但其 `created_at` 早于收盘后缓冲阈值（见 §6），且该 symbol 当天尚未执行过确认刷新

不需要刷新：
- 已存在 `price_date = target_date` 且已满足“收盘后确认刷新”条件（见 §6），或距离上次拉取未超过节流阈值（见 §7）

---

### 5.3 刷新策略

- 仅对“需要刷新”的 stock 发起行情请求
- 批量刷新（按行情源支持能力）
- 写入 `stock_prices`：
  - V1 采用 insert-only：每次刷新插入一条新记录（不做 UPDATE）
  - 读取侧以“同一 `stock_id + price_date` 的最新 `created_at`”作为当日 EOD 的当前值（收盘后确认刷新写入的新记录自然覆盖旧记录）

---

## 6. “Final” 收盘数据判定规则（V1）

V1 不在表结构中持久化 `is_final`。我们采用启发式规则控制“收盘后确认刷新”的次数：

### 收盘后确认刷新（最多一次）

- 若当前时间 ≥ 16:30 ET（收盘后缓冲）
  - 如果 `stock_prices(price_date = today_et)` 的最新 `created_at` < 16:30 ET，则允许再刷新一次作为“确认刷新”
  - 确认刷新成功后，当天不再刷新

> 注：half-day/holiday 未覆盖，后续可通过引入交易日历或供应商 session 信息增强。

---

## 7. Rate Limit & Guardrails（限流与护栏）

### 7.1 Symbol 级限流
- 单个 stock：**每个 target_date 最多 1 次正常刷新 + 1 次收盘后确认刷新**
- 额外节流：同一个 stock 的连续两次拉取间隔不小于 10 分钟（可配置）

### 7.2 页面级限流
- 同一股票池：**10 分钟内最多触发一次 refresh**（前端层防抖 + 后端幂等兜底）
- 防止用户频繁刷新页面消耗配额

### 7.3 数据源失败降级
- 主源失败 → 允许使用备源（如果配置了备源）
- 失败记录写入日志，不阻塞页面展示（展示已有数据）

---

## 8. API / Service Contract（内部）

注意：当前代码库尚未提供 stock_pools 相关 API。本任务会新增 v1 API（路径与现有风格对齐，均在 `/api/v1` 下）。

### 推荐（解耦股票池）：`POST /api/v1/stocks/prices/refresh`

**Input**
```json
{
  "stock_ids": [1, 2, 3],
  "reason": "pool_page_open"
}
```

**Behavior**
- 对 `stock_ids` 逐个按本任务定义的判定逻辑决定是否调用行情源
- 幂等：若无需刷新，不应产生外部 API 调用，也不应写入新的 `stock_prices`
- 返回每个 stock 的刷新结果摘要（例如：skipped/refreshed/failed + target_date）

### 可选（股票池落地后）：`POST /api/v1/stock_pools/{pool_id}/prices/refresh`

**Input**
```json
{
  "reason": "pool_page_open"
}
```

**Behavior**
- 根据本任务定义的判定逻辑，对该 pool 的成员 stock 逐个决定是否实际调用行情源
- 幂等：若无需刷新，不应产生外部 API 调用，也不应写入新的 `stock_prices`
- 返回每个 stock 的刷新结果摘要（例如：skipped/refreshed/failed + target_date）

---

## 9. UI Semantics（前端展示语义）

股票池页面应显示数据状态：

- `数据截至：YYYY-MM-DD 收盘（已确认）`
- 或 `数据截至：YYYY-MM-DD（收盘后待确认）`
- 若今日未收盘：
  - `数据截至：昨日收盘`

避免让用户误以为系统是“实时行情”。

---

## 10. Definition of Done（验收标准）

- [ ] 打开股票池页面时，仅在缺失 target_date 的日线数据或满足“收盘后确认刷新”条件时触发刷新  
- [ ] 收盘后确认刷新最多一次（无需 `is_final` 字段）  
- [ ] 周末不会误判为“缺数据”（holiday/half-day 允许少量误判，V1 不要求完全正确）  
- [ ] 单 stock 当天刷新次数符合限流规则  
- [ ] 不要求实时行情即可正确工作  
- [ ] 所有逻辑以“交易日近似规则 + 数据存在性”为准（V1 不引入交易日历表）  

---

## 11. Rollback Strategy（回滚）

- 若发现刷新逻辑导致：
  - 配额异常消耗
  - 高频重复刷新
  - 交易日判断错误  
→ 回滚至“仅展示已有日线、不做自动刷新”的保守策略

---

## 12. Notes / Future Upgrade Path

- V2：引入交易日历/半日交易支持（或使用供应商的 session 信息），消除 holiday 误判
- V2：接入券商/交易所授权的实时/延迟行情（quote），并明确合规与缓存策略
- V2：引入 corporate actions（分红/拆股）统一调整与 total return 口径
- V3：分钟级行情与回测口径统一

---

## 13. PRD / Codebase Alignment（对齐说明）

- Schema/ORM 中已存在 `stock_pools` / `pool_memberships` / `stock_prices` / `price_alerts`：
  - PRD: `docs/prd/value-pilot-prd-v0.1.md`
  - Code: `backend/app/models/stocks.py`
- 本任务不新增 `daily_bars` / `symbol_refresh_state` / `market_calendar` 等表，避免与既有 schema 分叉。

## 14. Test Plan（Docker）

- `docker compose exec api pytest -q`
-（建议新增/更新单测）覆盖：
  - 周末 target_date 回退
  - 收盘后确认刷新最多一次
  - 10 分钟节流（同 stock 同日不重复外部调用）
---
