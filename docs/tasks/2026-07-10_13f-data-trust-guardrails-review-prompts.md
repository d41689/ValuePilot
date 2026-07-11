# Review prompt — PR #119(13F 数据信任护栏:点名从不申报的 manager 与无法链接的大盘股 CUSIP)

PR: https://github.com/d41689/ValuePilot/pull/119
Branch: `claude/13f-data-trust-guardrails`(未合并;基线 `main`)
读 diff:`git diff main...claude/13f-data-trust-guardrails`

你是独立第三方审查者。目标是**召回真实缺陷**:任何会导致护栏漏报(该响的不响)、
误报(不该响的响)、或前端渲染/CTA 崩坏的问题。不要复述作者已说明的内容(见下"作者
已自行发现"一节)。发现问题请给出**能触发的具体输入/状态 → 错误输出**,并尽量在隔离的
`valuepilot_test` 上复现(外层事务回滚,勿污染 dev 真实数据)。

## 这一票为什么值得审

两个**聚合比率**各自掩盖了一处静默数据丢失:readiness 覆盖率(80% 阈值)在 86.6% 时
通过,却有 11 个 confirmed superinvestor 因 CIK 错误从不申报、缺席每个季度;linked-common
比率很高,却把 ExxonMobil / Honeywell 这样被 10 个/4 个 manager 持有的大盘股藏在缺失的
那几个百分点里,使它们在 Oracle's Lens 里彻底不可见。本 PR 用两个 P1 admin task **点名
具体的缺失实体**取代绿色聚合。

**风险不在"多了两个 task",而在两个 SQL 查询的正确性**:一个 `NOT IN` 子查询、一个跨
`Holding13F/ParseRun13F/Filing13F` 的当前持仓 join + 聚合。查询写错的表现是"静默漏报"
——护栏看起来在跑、实际永远不响。请把审查重心放在这两个查询上。

## 变更清单

| 文件 | 改动 |
|---|---|
| `backend/app/services/thirteenf_admin_dashboard.py` | 新增 `_confirmed_managers_never_filed`、`_high_impact_unresolved_cusips`;在 `build_admin_tasks` 里接线为两个 P1 `_task_with_metadata`;模块级 `import HR_FORM_TYPES` |
| `backend/tests/unit/test_13f_data_trust_guardrails.py`(新) | 8 个测试(test-first) |
| `frontend/app/(dashboard)/admin/13f/page.tsx` | 渲染 `metadata.managers` / `metadata.cusips` 两个列表 + `formatCompactUsd` helper |
| `frontend/lib/thirteenfAdmin.js` + `.test.js` | 两个新 code 的 `taskPrimaryAction` CTA 映射 + 测试 |
| `docs/BACKLOG.md` | 5 条 deferred(含 1 条 high) |
| `docs/tasks/2026-07-10_13f-data-trust-guardrails.md` | 任务文档 |

## 请重点独立证伪的断言

1. **护栏 1 的 `NOT IN` 子查询在真实 schema 上不会漏报。**
   `_confirmed_managers_never_filed` 用 `~InstitutionManager.id.in_(session.query(Filing13F.manager_id).filter(...isnot(None)))`。
   作者已加 `isnot(None)` 防 `NOT IN NULL` 三值逻辑陷阱。请验证:(a) 该 filter 确实
   消除了陷阱;(b) 子查询选的是 `Filing13F.manager_id`(任意 form_type / 任意 period 的
   **任何**申报都算"申报过")——这对"从不申报"的语义是否正确?一个只提交过 13F-NT
   (notice)而无 HR 的 manager 会不会被误判为"申报过"从而漏报?这是有意还是缺陷?

2. **护栏 2 的 join 不会重复计数,也不会漏算。**
   `_high_impact_unresolved_cusips` 用**主键 join**(`Holding13F.parse_run_id == ParseRun13F.id`)
   接当前 parse run,再经 `Filing13F.accession_number == ParseRun13F.accession_number`
   接 active HR filing。作者声称这消除了"同一 accession 上既有 current 又有 superseded
   parse run 时的重复计数"。请验证:(a) 一个 manager 在同一 CUSIP 上有多行合法持仓
   (不同 lot)时,`count(distinct manager_id)` 只算一次(应该);(b) `sum(value_usd)`
   会不会被 `Filing13F` 一侧的 join 扇出放大(是否存在同一 accession 对应多个 active
   Filing13F 行的情况)?

3. **`value_usd` 而非 `value_thousands` 是对的。**
   作者的判断:2023 年后 SEC 13F 以**美元**申报,`value_thousands` 列名有误导、实际存
   原始申报值;`value_usd` 是归一化美元字段、近季度 100% 填充。护栏只看最新季度,故恒为
   美元。请证伪:是否存在最新季度 `value_usd` 为 NULL 的 active 持仓,使金额被低估?
   (作者在 dev 上测得 2026-Q1 6170/6170 非空。)

4. **护栏语义边界(测试是否覆盖真实情形)。**
   - 护栏 1 排除:CIK 为空(match-CIK 队列的活)、`status != active`、
     `match_status != confirmed`(人为退休/撤销,不是数据缺口)。
   - 护栏 2 排除:期权(`put_call` 非空)、已链接(`stock_id` 非空)、单一持有人
     (< `min_holders=3`)。
   请找出任一"该响却不响"或"不该响却响"的真实数据路径。

4b. **前端 blast radius。** `metadata.managers` / `metadata.cusips` 的渲染插在
   `/admin/13f` 那一大段 `task.metadata` 条件块里(与既有 `retry_targets`、
   `affected_quarters` 等并列)。`taskPrimaryAction` 新增两个分支
   (`HIGH_IMPACT_CUSIP_UNRESOLVED` → enrich_metadata job;`CONFIRMED_MANAGERS_NOT_FILING`
   → managers anchor)。请确认没有改坏既有 task 的渲染或 CTA;anchor target `managers`
   在页面上确有对应可滚动元素。

## 评审者看不到的上下文

- **本 PR 只加"让缺口变响"的护栏,不包含"修复缺口"的代码。** 大盘股 CUSIP 无法链接的
  **根因是一个系统性 matcher bug**(见下),作者判断它是独立的、更高风险的一改,**不
  应捆进本 PR**。请评估这个 scope 拆分是否合理。
- **根因(已 backlog 为 high):** `evaluate_openfigi_matches` 只在存在 `exchCode=="US"`
  合成列时自动确认 CUSIP→ticker。2026-07-10 实测:OpenFIGI 对 XOM `30231G102` 返回 14
  条、6 条一致为 `XOM` 但都在 venue code(PE/CB/CX/UZ/OU/QU)下、**零条 `US`**;对 HON
  `438516106` 返回 4 条全是外币变体、**零条 `US`**。于是两只大盘股永远落到
  `review_needed:low`、永不链接。**重跑 enrichment 修不了**。
- **dev 数据已用"设计内的手动覆盖路径"修复(非 raw SQL、有审计):**
  `upsert_cusip_mapping(source="manual", confidence="manual")` → `bootstrap_stocks_from_cusip_map`
  → `backfill_stock_ids` → 对 8 个季度重算 `compute_ownership_changes` +
  `oracles_lens_score_backfill`。因此**现在 dev 上两个护栏都不响**(11-CIK 已修 → 护栏 1
  为 0;XOM/HON 已链接 → 护栏 2 清空),这是正确状态,不是护栏坏了。要在 dev 上看到护栏
  1 响,需要一个 confirmed+active、CIK 却从不申报的 manager;要看到护栏 2 响,需要一个
  ≥3 manager 持有、未链接的普通股 CUSIP。测试文件用隔离 fixture 构造了这两种情形。
- **手动映射是 dev 止血,不是系统修复。** prod 与未来每个季度仍会命中 matcher bug。

## 作者已自行发现并说明的(judge,勿当新发现重报)

- `value_thousands` 列名误导、实存美元 → 已改用 `value_usd`,并在护栏说明与 BACKLOG 记录。
- 早前护栏 2 曾用基于 `accession_number` 的 `Holding→ParseRun` join,存在"active
  accession 同时有 current+superseded parse run 时重复计数"的潜在扇出 → 已改为主键 join,
  与 `thirteenf_holdings_query` 的规范当前持仓 join 对齐。
- 护栏说明注释里的"~10 managers, ~\$1.2B"是对 XOM 最新季度的真实观测(非旧的
  "14 managers/\$12B" 占位)。
- 5 条 deferred 已逐条写入 `docs/BACKLOG.md` 并在 PR 描述点名(含 high 级 matcher bug)。

## 测试基础设施

后端测试**必须**打隔离库 `valuepilot_test`(dev 库 `valuepilot` 有真实 13F 数据,勿污染):

```bash
docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api pytest -q tests/unit/test_13f_data_trust_guardrails.py
docker compose exec -T -e DATABASE_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test" api pytest -q   # 作者报告 1240 pass
```

前端(**不要**在活着的 dev 容器里跑 `npm run build` —— 生产构建会覆盖 `next dev` 的
`.next`,本机踩过;若必须跑,跑完 `rm -rf /app/.next/*` + `docker compose restart web` 还原):

```bash
docker compose exec -T web sh -lc 'node --test lib/*.test.js'   # 作者报告 185 pass
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

在真实 dev 数据上直接看护栏输出(只读):

```bash
docker compose exec -T api python - <<'PY'
from app.core.db import SessionLocal
from app.services.thirteenf_admin_dashboard import build_admin_tasks
s = SessionLocal()
for t in build_admin_tasks(s):
    if t["code"] in ("CONFIRMED_MANAGERS_NOT_FILING","HIGH_IMPACT_CUSIP_UNRESOLVED"):
        print(t["code"], t["priority"], t["metadata"])
s.close()
PY
```

## 交付

- 判定:可合并 / 打回,并说明理由。
- 每个确认的缺陷:`file:line` + 可触发输入/状态 + 错误后果 + 是否已复现(贴命令与
  before/after)+ 建议修法。
- 把结果写入 `docs/tasks/2026-07-10_13f-data-trust-guardrails-review-results.md`。
