# 13F 真实数据摄取 — PO 方案与执行计划

**日期:** 2026-07-08 · **作者:** PO(价值投资 / 13F 业务视角) · **触发:** 首次把真实
EDGAR 13F 数据灌入 dev(经公网 Rate Guard),暴露 6 个合成 seeder 永远测不到的
正确性 / 管线缺陷。

> 数据事实(2026-07-08 dev):82 管理人 · 373 filings/parse-runs · 25,070 holdings
> (94.6% 已链股)· 18,260 ownership_changes · 5 季度 Lens 打分。原始 XML 在
> `storage/edgar_raw`,holdings 以下各层数分钟可重算。

---

## 1. 缺陷清单

| # | 缺陷 | 层 | 严重度 | 归属票 |
|---|---|---|---|---|
| F1 | `ingest_holdings` job Phase 5 在同季 ≥2 份 RESTATEMENT 时崩溃(唯一约束) | 摄取管线 | **P0-eng** | **T1** |
| F2 | `compute_ownership_changes` 无生产调用方(编排从未接线) | 变动预计算 | P1 | **T2** |
| F3 | `compute_ownership_changes` 两 CUSIP→一 stock 时唯一键崩溃 | 变动预计算 | P1 | **T2** |
| F4 | **组合/共享裁量归因错误 → 巴菲特等 7 家旗舰管理人全产品不可见** | 归因 / 打分 | **P0-product / HIGH** | **T3** |
| F5 | CLI `backfill` 静默跳过最新报告季的 holdings | CLI/ops | P2 | **T4** |
| F6 | CLI 摄取写无 ParseRun 的产品不可见 holdings | CLI/ops | P2 | **T4** |

(Rate Guard 可观测性 / 分环境密钥两条为既有 backlog,pre-existing,不在本轮范围。)

---

## 2. PO 裁定:组合 / 共享裁量归因(F4 — 旗舰决策)

### 2.1 根因(已被真实数据证实)

产品查询契约(PRD §7.3 `active_hr_holdings_query`)只认
`holding_attribution_status='direct'`。摄取期 `_compute_attribution_status`
(`backend/app/services/thirteenf_holdings_ingest.py:46`)把
**`DFND`(defined/shared-defined 裁量)+ 任意 `other_managers_raw`** 一律判为
`reported_for_other`(= 由他人申报,排除),把 `OTR` 判为 `shared`(同样排除)。

真实数据证明这个判定系统性错误:

- `other_managers_raw` 的取值是 **`4,8,11` / `4,11` / `4`** 这类**封面页
  "List of Other Included Managers" 的序号**,不是外部 CIK。这正是伯克希尔这类
  **多管理人 / 组合申报**的标准结构:一张 13F 封面列出申报人及其纳入的子管理人
  (National Indemnity=#4、GEICO=#11 …),每行持仓用序号标注由哪个纳入子管理人持有。
- 关键 SEC 语义:**"谁的 infotable 里列了这行,谁就是申报人"**——共享裁量的持仓,
  只由其中一方在自己表里申报以避免重复计数,其余同裁量方列在 `OTHERMANAGER`。
  既然这行出现在伯克希尔自己的 infotable 里,它**就是**伯克希尔可申报组合的一部分。
- `report_type` **不是可靠信号**:7 家里只有 Oaktree 被标 `combination_report`,
  伯克希尔/伯里/沃萨/Cantillon/Egerton/Engaged 全标 `holdings_report`。信号必须
  取自 holding 级的 `investment_discretion` + `other_managers_raw`。

### 2.2 裁定

**原则:凡出现在管理人自己 infotable 中的持仓,即该管理人的可申报组合 →
`direct`。** `reported_for_other` 的排除语义只保留给**申报级 13F-NT 通知**
(管理人根本不报持仓表、由他人代报)。据此:

| 裁量码 | Column 7 (`other_managers_raw`) | 归因 | 说明 |
|---|---|---|---|
| SOLE | — | `direct` | 不变 |
| **DFND** | 有或无 | **`direct`** | 组合/共享裁量,在本人表内申报 → 计入 |
| **OTR** | 有或无 | **`direct`** | 同上(shared-other 裁量,仍在本人表内) |
| 无法识别 / 空裁量 | — | `unresolved` | 唯一真正无法归因的情形 |
| (任意) | 申报级为 13F-NT | 排除 | 通知件无持仓表,本就不摄取为其持仓 |

> **T3 评审修订(2026-07-08):** 初版裁定曾要求 `DFND/OTR` **有 Column 7 引用**才
> 归 `direct`、无引用 → `unresolved`。评审据 SEC Form 13F FAQ 37/46/48 指出:与
> **低于 $100M 申报门槛**的管理人共享裁量时,持仓聚合进本人申报且**不在 Column 7
> 列出对方**——故空 Column 7 是合法的、不能作为排除信号。真实数据佐证:Cantillon
> 的 Adobe 同一只票被拆成"有引用 direct / 无引用 unresolved"两半(628,547 股的更大
> 一笔被误排除),明显错误。**修订:`SOLE/DFND/OTR` 一律 `direct`,与 Column 7
> 无关;仅无法识别的裁量码 → `unresolved`。** 这也与本节"凡在本人 infotable 中即
> 可申报仓位"的原则一致(初版表格自相矛盾)。

- **不新增枚举值**:`holding_attribution_status` 是 varchar,复用现有 `direct`,
  一次性让所有下游消费者(managers API、ownership_changes、Oracle's Lens 5 处
  `=='direct'` 过滤、consensus)同时看到,零查询层改动风险。sole vs shared 的
  细分不丢失——已存 `investment_discretion` 列可供任何分析区分。**不做 schema
  band-aid**(遵循既有约定)。
- **重复计数护栏**:SEC 规则天然防单申报人内重复(只一方在表内申报)。跨申报人
  重复仅当我们把某母公司**和**其纳入子管理人**同时**作为独立 universe 管理人跟踪
  才可能——当前 82 家宇宙不存在此情况。加一条 review 断言:若两家 universe
  管理人在同一 (stock, quarter) 经组合关联同时申报,标记人工核查而非双计。
- **Caveat 文案修正**:现有 combination caveat "Some holdings are reported by
  other manager(s) and are not included here" 与"计入"矛盾,改为诚实表述
  (如"本组合申报含与申报人纳入子管理人共同持有的仓位")。caveat 本身**保留**
  (honesty 文化),只改措辞。

### 2.3 影响面(精确)

- **7 家旗舰管理人 0 → 全量可见**:Oaktree(1116)、Berkshire(543)、Cantillon
  (187)、Fairfax(144)、Egerton(123)、Engaged(42)、Scion(30)。
- 重归因为 `direct`:DFND 3,693 + OTR 839(**含无 Column 7 引用者**,评审修订后
  纳入,如 DFND-无引用 410+ 行)。SOLE 20,538 行不动;仅无法识别裁量 → `unresolved`。
- 重算受影响管理人的 `ownership_changes` 与 Lens 打分组件(伯克希尔当前为 0)。

### 2.4 验收(F4)

有数据的 dev 上:`GET /13f/managers/3984/holdings/changes` 返回巴菲特的季度
变动(非 NO_COMPUTED_CHANGES);伯克希尔在 Oracle's Lens 有打分组件;7 家在
managers 页均有持仓与变动;combination caveat 措辞正确;**抽查不产生重复计数**
(伯克希尔计为 1 个 holder)。

---

## 3. 执行计划(4 票,顺序,门禁)

**排序原则:先让自动化季度管线在真实数据上"不崩、能产出",再上最高业务价值的
归因修复并经真实管线端到端验收(不再用一次性脚本自证——"工具验证≠产品签收")。**

### T1 — 摄取管线修正案激活修复(F1) · P0-eng · ~0.5d
- **范围:** `_execute_ingest_job` Phase 5 每 (manager, quarter_end_date) 组只
  reconcile 最新 filed 的已解析 RESTATEMENT;`reconcile_restatement_activation`
  内 demote 后 `flush()` 再 activate(顺序安全)。
- **测试先行:** 同季两份 RESTATEMENT,跑两遍 quarter job,断言最终 active 为
  最新且不抛 IntegrityError。
- **相位:** [ ] 任务doc [ ] 红 [ ] 绿 [ ] 全量CI [ ] PO签收 [ ] backlog清条目

### T2 — ownership_changes 编排接线 + 计算加固(F2+F3) · P1 · ~1d
- **范围:** quarterly_pipeline 在 quality_check 后加 `compute_ownership_changes`
  阶段(对该季有 active filing 的 manager 循环幂等调用)+ 独立 job_type 供单独
  重算;计算前按 `(security_key, ssh_prnamt_type, position_type)` 聚合去重
  (F3),两 CUSIP→一 stock 合并 shares/value、并集 caveat。
- **测试先行:** 端到端一个季度产出非空 changes;两 CUSIP→一 stock 两分支
  (正常 + unavailable)不崩。
- **相位:** [ ] 任务doc [ ] 红 [ ] 绿 [ ] 全量CI [ ] PO签收 [ ] backlog清条目

### T3 — 组合/共享裁量归因修复(F4) · P0-product/HIGH · ~2–3d
- **范围:** 依 §2 裁定改 `_compute_attribution_status`(DFND/OTR+引用→direct);
  一次性 re-attribution 回填(有原始 XML,纯数据+逻辑,无 migration);重算受影响
  管理人 changes+scores;修 combination caveat 文案;加重复计数 review 护栏。
- **依赖:** T1+T2(经真实管线端到端验收巴菲特可见)。
- **相位:** [ ] 设计裁定(本doc §2 ✅) [ ] 任务doc [ ] 红 [ ] 绿 [ ] 回填 [ ]
  全量CI [ ] **PO签收(巴菲特可见+无双计)** [ ] backlog清条目

### T4 — CLI 摄取卫生(F5+F6) · P2 · ~1d(可并行)
- **范围:** 让 CLI `backfill`/`ingest-holdings` 委托 job 路径语义(或弃用),
  消除无-ParseRun 写入与最新季窗口漏摄。
- **相位:** [ ] 任务doc [ ] 红 [ ] 绿 [ ] 全量CI [ ] PO签收 [ ] backlog清条目

**顺序:** T1 → T2 → T3(T4 并行/其后)。每票独立 PR、独立 review gate、独立
PO 签收(遵循 strict scope discipline:小票勤签,不捆绑)。

---

## 3.1 本地测试库(隔离 pytest,顺带解决 Pre-MVP6-01 痛点)

真实数据现常驻 dev 库 `valuepilot`(供 PO 点验),pytest 不能对其运行(177+
测试假设空库,`_clear` 会撞 `ownership_changes` FK)。已建独立测试库,真实数据
零改动:

```bash
# 一次性建库(infra 超级用户,owner=valuepilot 角色)
docker exec projects-infra-postgres-1 sh -lc \
  "PGPASSWORD=infra_admin psql -U infra_admin -d postgres -c 'CREATE DATABASE valuepilot_test OWNER valuepilot'"
# 迁移 + 跑测试(DATABASE_URL 覆盖指向 _test 库)
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
```

CI 仍在自己的空 volume 上跑金标准命令;此库仅为本地在"有真实数据的 dev"旁
并行跑测试。真实数据快照留存于会话 scratchpad(`valuepilot_realdata_20260708.dump`,
`pg_restore` 可还原)。

## 4. 与路线图的关系

这 6 项均为**真实数据暴露的正确性/管线缺陷 = Pre-MVP6 稳定化闸的应有内容**
(PO 既定"先让 dev 有真实可验证数据"),不改动 MVP6(Admin Ops Console)与
investor-workflow 包(票 01/02/03)的既定排序;反而 **T2+T3 直接解锁**票 01
(管理人页需要 changes)与票 02(新建仓聚类依赖 `change_status='new_position'`
且需要巴菲特这类旗舰进入)。稳定化三票(T1→T2→T3)约一个短迭代即可让旗舰产品
在真实数据上成立。
```
