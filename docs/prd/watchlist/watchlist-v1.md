

# Watchlist Feature Spec (V1)

Status: Draft  
Owner: Product / Backend / Frontend  
Version: v1  
Last Updated: 2026-02-03

---

## 1. Goal（目标）

Watchlist 是 ValuePilot 的「每日入口页面」。

用户打开系统后：

- 快速查看自己关注的股票
- 看到当前价格 vs 估值
- 一眼判断哪些标的“便宜/值得研究”
- 支持多个策略 / 主题列表（多个 watchlist）

核心定位：

👉 Daily decision dashboard，而不是行情终端

因此：

- 不追求实时行情
- 以 EOD（日线）为主
- 强调排序 + 决策效率

---

## 2. Non‑Goals（V1 不做什么）

- ❌ 不做实时/逐笔行情
- ❌ 不做分钟级 K 线
- ❌ 不做自动估值模型（DCF/AI）
- ❌ 不做复杂回测
- ❌ 不做交易下单
- ❌ 不新增 DB 表或迁移（V1 复用现有 `stock_pools` / `pool_memberships` / `stock_prices` / `metric_facts`）

V1 仅聚焦：

👉 Watch + Fair Value + Margin of Safety

---

## 3. Information Architecture（信息架构）

页面采用三栏布局（Trading / Research 工具常见布局）：

```
┌───────────────────────────────────────────────┐
│ Top bar                                      │
├───────────────┬──────────────────────────────┤
│ Watchlists    │ Main table                   │
│ (sidebar)     │                              │
└───────────────┴──────────────────────────────┘
```

---

## 4. Layout 设计

### 4.1 Top Bar（全局操作区）

右上角：

- [+ New Watchlist]
- [+ Add Ticker]


说明：

- Add Ticker 始终作用于“当前选中的 watchlist”
- 避免在表格内部放分散按钮

---

### 4.2 Sidebar（Watchlist 列表）

形式：Notion / Slack 风格侧边栏

示例：

```
📂 My Watchlists
  ⭐ Default
  Deep Value
  Tech
  China ADR
  Dividend

+ New Watchlist
```

设计原则：

- 支持任意数量 watchlists
- 可扩展（未来支持拖拽排序/分组）
- 当前选中项高亮

不使用 tabs（数量多时不可扩展）。

---

### 4.3 Main Table（核心区域）

展示当前 watchlist 内所有股票。

默认排序：

👉 Margin of Safety DESC（越便宜越靠前）

---

## 5. Table Columns（字段设计）

V1 建议列：

| Column | Description |
|--------|------------|
| Ticker | 股票代码 |
| Name | 公司名（可选） |
| Price | 当前价格（EOD close，来自 `stock_prices`；页面打开时可触发 refresh；单位由数据源/交易所决定，V1 默认美股，通常为 USD） |
| Fair Value | Fair Value（可编辑；按用户/按股票全局值，跨 watchlist 共享；存储在 `metric_facts` 的 manual fact；若不存在，可回退展示 Value Line 的 `target.price_18m.mid`；展示优先级见 §7） |
| Margin of Safety | (FV - Price) / FV（FV 为空则 MOS 为空） |
| Δ Today | 当日涨跌（EOD；`close(target_date) - close(prev_price_date)`；`prev_price_date` 为 target_date 之前最近一次有价的 `price_date`；两天数据齐全才显示；可选） |
| Last Update | 数据更新时间 |

---

### 5.1 Margin of Safety（重点指标）

公式：

```
MOS = (fair_value - price) / fair_value
```

视觉规则：

- > 30% 绿色（安全）
- 10–30% 黄色（一般）
- < 10% 红色/灰色（接近或高估）

目标：

👉 一眼扫描

---

## 6. Key Interactions（核心交互）

### 6.1 Add Ticker

点击 “+ Add Ticker” → 弹出 Modal

```
Add Ticker
[ AAPL        🔍 ]

Apple Inc (AAPL)

[ Cancel ] [ Add ]
```

要求：

- 支持 ticker 输入
- 支持自动补全（后期可扩展）
- 防止重复添加

---

### 6.2 Edit Fair Value

- 点击 Fair Value 单元格可直接编辑
- 或 hover → Edit

更新后：

- 自动重新计算 MOS
- 自动重新排序

---

### 6.3 Remove Ticker

- 行 hover 显示 🗑
- 删除确认

---

### 6.4 Sorting

- 点击任意列排序
- 默认：MOS DESC

---

### 6.5 Empty State

```
No stocks yet.
Add your first ticker →
```

---

## 7. Data Model（后端模型建议）

本 PRD 的“watchlist”在后端复用现有概念：

- watchlist（产品名词） = `stock_pools`（DB/ORM）
- watchlist item（产品名词） = `pool_memberships`（DB/ORM）

V1 不引入新的 `watchlists` / `watchlist_items` 表，避免与 v0.1 PRD 和现有 schema 分叉。

### stock_pools（已有）

- id
- user_id
- name
- description (nullable)
- created_at

### pool_memberships（已有）

- id
- user_id
- pool_id
- stock_id
- inclusion_type (manual / rule)
- rule_id (nullable)
- created_at

### stock_prices（已有，EOD）

- id
- stock_id
- price_date
- open / high / low / close
- adj_close (nullable)
- volume (nullable)
- source
- created_at

说明：

- 不新增行情表
- 直接复用 stock_prices
- 写入侧为 insert-only；同一 `stock_id + price_date` 可能存在多条记录，读取侧以最新 `created_at` 为准。

### metric_facts（已有，Fair Value 存储方式）

由于 `pool_memberships` 当前没有 `fair_value` 字段，且本 PRD 不引入迁移：
- V1 的 Fair Value 作为“用户对某只股票的估值”，存为 `metric_facts` 的一条 `manual` fact（按用户/按股票，全局共享，不区分 watchlist）。
- 注意：`metric_key / unit / period_type / period_end_date` 属于 **metric semantics**，必须以 `docs/metric_facts_mapping_spec.yml` 为权威；本 PRD 不在此处定义它们。
- Watchlist 实现时需要在 mapping spec 中新增一个“用户 Fair Value”对应的条目（unit=USD，period_type=AS_OF），并在写入时遵循 v0.1 的 `is_current` 语义。

Fair Value 展示优先级（deterministic）：
1) 用户手动输入的 Fair Value（`metric_facts`, `source_type=manual`, `is_current=true`）
2) Value Line 的 18M Target Mid（`metric_facts.metric_key = target.price_18m.mid`, `is_current=true`，只作为只读 fallback）
3) 无（显示空值）

---

## 8. API Contracts（V1）

说明：当前 codebase 尚未提供 watchlist/stock_pools 的 API；本节定义 V1 需要新增的 endpoints（遵循现有 `/api/v1` 路由风格与 user-owned 资源的 `user_id` query 参数模式）。

### Watchlists（stock_pools）

GET /api/v1/stock_pools?user_id={user_id}  
POST /api/v1/stock_pools?user_id={user_id}  
DELETE /api/v1/stock_pools/{pool_id}?user_id={user_id}

### Items（pool_memberships）

GET /api/v1/stock_pools/{pool_id}/members?user_id={user_id}  
POST /api/v1/stock_pools/{pool_id}/members?user_id={user_id}  
DELETE /api/v1/stock_pools/{pool_id}/members/{membership_id}?user_id={user_id}

Add Ticker 限制（V1）：
- V1 仅允许添加已存在于 `stocks` 表的 ticker（通常由 Value Line ingestion 创建）。
- 若 ticker 不存在：UI 引导用户先上传对应 Value Line PDF（或后续版本再支持创建 stub stock）。

### Fair Value（metric_facts, manual）

PUT /api/v1/stocks/{stock_id}/facts?user_id={user_id}

Body:
```json
{
  "metric_key": "<fair_value_metric_key_from_mapping_spec>",
  "value_numeric": 123.45
}
```

Behavior:
- 写入 `metric_facts`（`source_type=manual`；其余语义从 mapping spec 读取）
- 置前一条同 `metric_key` 的 current 为 false，并将新值置为 current（与 v0.1 “Active Value”语义一致）

### Price Refresh（已存在）

POST /api/v1/stocks/prices/refresh

页面打开时：

- 先拉当前 watchlist 的 members（得到 stock_ids）
- 调用 refresh（传 `stock_ids`；可带 `reason` 字段用于审计/排障）
- 再拉 table data（members + price + fair value + MOS）

实现建议（非强制）：
- UI 可先用缓存数据渲染表格，同时触发 refresh（async），refresh 完成后再拉一次 table data 更新 Price/Δ Today。

---

## 9. Performance / Constraints

- 使用 EOD 数据即可
- 页面打开时触发一次 refresh
- 不做实时轮询
- 支持 100–300 支股票规模

---

## 10. Definition of Done（验收标准）

- [ ] 用户可以创建多个 watchlist
- [ ] 可以添加/删除 ticker
- [ ] 可以编辑 fair value
- [ ] 自动计算 MOS
- [ ] 默认按 MOS 排序
- [ ] 页面刷新时自动补齐当日价格
- [ ] 无实时依赖
- [ ] 100+ 行表格仍流畅

---

## 11. Future Roadmap（非 V1）

- 自动估值模型（DCF/Multiples/AI）
- Notes / 标签
- Alerts
- Charts
- CSV 导出
- Intraday quote
- Portfolio 模块

---

## 12. Design Principles

- 简单 > 花哨
- 决策优先 > 行情炫技
- EOD 足够好
- Watchlist 是 daily driver

最终目标：

👉 打开页面 10 秒内知道今天该研究/买谁
