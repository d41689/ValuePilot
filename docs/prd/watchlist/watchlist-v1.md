

# Watchlist Feature Spec (V1)

Status: Implemented baseline; Research Decision Loop evolution governed by the authoritative PRD §G
Owner: Product / Backend / Frontend
Version: v1
Last Updated: 2026-07-20

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
| Price | Canonical EOD close（来自 `stock_prices`，显示交易日、来源、币种和 freshness；缺失/过期由覆盖队列触发一次去重批量 refresh，禁止逐行页面请求） |
| User Intrinsic Value | 用户估值（可编辑；按用户/按股票全局值，跨 watchlist 共享；存储在 `metric_facts` 的 manual fact） |
| Margin of Safety | 仅当 User Intrinsic Value 与 Price 同为 USD 时计算 `(FV - Price) / FV`；否则为空并显示原因 |
| Valuation Reference | Value Line target 等系统参考值，只读，显示来源与日期 |
| Discount to Reference | 仅针对系统参考值；不得标为 Margin of Safety |
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
- currency（Research Decision Loop 迁移新增；历史未知保持 NULL）
- created_at

说明：

- 不新增行情表
- 直接复用 stock_prices
- 写入侧为 insert-only；同一 `stock_id + price_date` 可能存在多条记录。所有产品读取必须经过 canonical EOD reader：先按已配置的可信来源优先级，再按 `created_at`、`id` 确定同日权威行，并按交易所日历判断 fresh/stale/unknown。不得由各页面直接选择 `stock_prices`。
- 页面只读取已存储价格；缺失、过期或历史行缺币种时进入用户覆盖队列，由一个可观察、去重、批量的 `coverage_eod_refresh` job 处理。生产环境没有显式启用且获授权的数据源时 fail closed。

### metric_facts（已有，Fair Value 存储方式）

由于 `pool_memberships` 当前没有 `fair_value` 字段，且本 PRD 不引入迁移：
- V1 的 Fair Value 作为“用户对某只股票的估值”，存为 `metric_facts` 的一条 `manual` fact（按用户/按股票，全局共享，不区分 watchlist）。
- 注意：`metric_key / unit / period_type / period_end_date` 属于 **metric semantics**，必须以 `docs/metric_facts_mapping_spec.yml` 为权威；本 PRD 不在此处定义它们。
- Watchlist 实现时需要在 mapping spec 中新增一个“用户 Fair Value”对应的条目（unit=USD，period_type=AS_OF），并在写入时遵循 v0.1 的 `is_current` 语义。

估值展示分为两条互不替代的数据支路：

1) User Intrinsic Value：用户手动输入的 `val.fair_value`；可用于 MOS。
2) System Valuation Reference：例如 Value Line `target.price_18m.mid`；只可用于
   Discount/Premium to Reference，不得回退冒充 Fair Value 或 MOS。

手动值读取必须先按 `period_end_date DESC NULLS LAST, created_at DESC, id DESC`
选择最新一行，再检查数值。最新的显式 unavailable/null tombstone 会压住旧值，
不能继续显示旧 Fair Value。

---

## 8. API Contracts（V1）

说明：这些 API 已实现。用户身份来自认证会话；query/body 的 `user_id` 不构成
权限依据。

### Watchlists（stock_pools）

GET /api/v1/stock_pools
POST /api/v1/stock_pools
DELETE /api/v1/stock_pools/{pool_id}

### Items（pool_memberships）

GET /api/v1/stock_pools/{pool_id}/members
POST /api/v1/stock_pools/{pool_id}/members
DELETE /api/v1/stock_pools/{pool_id}/members/{membership_id}

Add Ticker 限制（V1）：
- V1 仅允许添加已存在于 `stocks` 表的 ticker（通常由 Value Line ingestion 创建）。
- 若 ticker 不存在：UI 引导用户先上传对应 Value Line PDF（或后续版本再支持创建 stub stock）。

### Fair Value（metric_facts, manual）

PUT /api/v1/stocks/{stock_id}/facts

Body:
```json
{
  "metric_key": "<fair_value_metric_key_from_mapping_spec>",
  "value_numeric": 123.45
}
```

Behavior（Research Decision Loop 迁移后）：

- 通过权威 PRD §G.4 的 canonical valuation service 保存研究 revision 并发布
  `metric_facts` manual projection；
- 只 demote 同 `(user_id, stock_id, metric_key, period_type,
  period_end_date, source_type='manual')` 的 current 行；
- 不得跨 AS-OF 日期全局 demote，也不得维护第二条直接写入路径。

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

- [x] 用户可以创建多个 watchlist
- [x] 可以添加/删除 ticker
- [x] 可以编辑 fair value（现有直接写路径将在 §G 迁移为 canonical service）
- [x] 自动计算 MOS
- [x] 默认按 MOS 排序
- [x] 页面刷新时补齐 EOD 价格
- [x] 无实时依赖
- [x] 100+ 行表格采用批量 API/客户端排序，不做逐行网络请求

---

## 11. Future Roadmap（非 V1）

- 自动估值模型（DCF/Multiples/AI）
- Notes / 标签（进入 Research Decision Loop §G）
- Alerts（进入 Research Decision Loop §G）
- Charts
- CSV 导出
- Intraday quote
- Portfolio 模块（进入 Research Decision Loop §G）

---

## 12. Design Principles

- 简单 > 花哨
- 决策优先 > 行情炫技
- EOD 足够好
- Watchlist 是 daily driver

最终目标：

👉 打开页面 10 秒内知道今天该研究/买谁
