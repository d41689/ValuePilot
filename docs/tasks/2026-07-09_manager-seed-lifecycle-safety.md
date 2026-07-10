# Task M1: manager seeding must never overwrite a human lifecycle decision

**Created:** 2026-07-09 · **Origin:** PO 决策(自动化管理人宇宙的前置条件)·
**Severity:** medium(数据正确性 + 打分输入完整性;当前无自动调用方,故未爆发)

## 背景 / 为什么现在做

PO 的目标形态:

1. 手工策展 ~82 位价值投资管理人 → 冻结为种子数据 → **每次部署自动 seeding**;
2. 定时任务检测宇宙漂移(新增 / 退出)→ **提议**,人工批准后应用;
3. 13F pipeline 保持全自动;
4. 两条自动化的问题统一记录、定期消化。

(2) 已有骨架(`sync-dataroma` 是只读 diff,`dataroma_sync` job + admin 端点已存在),
(3) 已经实现(`quarterly_pipeline` 六阶段 + 周一调度 + `THIRTEENF_START_QUARTER`
启动自举)。**(1) 的种子文件也已存在**(`seed_data/confirmed_managers.json`,82 条,
含 v2 分类)。真正缺的是把 seeding 挂进部署 —— 但**在挂进去之前必须先修它的写入语义**,
否则等于把一个已知缺陷自动化。

## 问题(实测)

### P1 — re-seed 会复活管理员停用的管理人

`seed_confirmed_managers`(`edgar_ingestion.py`)对既有行**无条件写**:

```python
existing.match_status = "confirmed"      # 不看当前值
```

而管理员停用一位管理人时写的是(`thirteenf_admin_dashboard.py:645`):

```python
manager.status = "inactive"
manager.match_status = "inactive"
```

于是:**管理员今天停用,下次 seeding 就把他复活成 `confirmed`。** 摄取按
`match_status == 'confirmed'` 挑人(`ingest_quarter_index`),所以被复活者会重新进入
摄取与产品面。

这与本轮 13F 系列反复出现的病同源:*自动收敛推翻人工决定*(T1-FU:sweep 复活
admin-rejected 的修正案;#113:revert 复活 `deferred`)。区别在于这一次,它一旦挂进
部署流程就会**静默、周期性**地发生。

**为什么这不是小事:** 管理人宇宙是 Oracle's Lens 的打分输入
(`dashboard.py` `min_holders = 3`)。宇宙里多一个 holder,共识分就变。宇宙静默变化
= 分数静默变化 = 历史不可比。

### P1 的加重情节 — 复活会造成**脑裂**,而非简单复活

模型上有一个 ORM 事件监听器(`institutions.py:_populate_manager_prd_fields`,
`before_insert` + `before_update`):

```python
if manager.match_status in {"confirmed","revoked","rejected"} and manager.status in {None, "candidate"}:
    manager.status = _status_from_legacy_match_status(manager.match_status)   # confirmed -> active
```

它只在 `status ∈ {None, candidate}` 时派生。被管理员停用的行 `status='inactive'`,
所以 seed 把 `match_status` 改回 `confirmed` 之后,监听器**不会**同步 `status`,
最终得到自相矛盾的一对:

```
match_status = 'confirmed'   →  ingest_quarter_index 会抓他(只看 match_status)
status       = 'inactive'    →  daily_sync / readiness / historical_backfill 看不见他
```

**脑裂**:该管理人的 filing 会被摄取、进入产品面与 Lens 共识,却不出现在
expected-filers 分母与每日跟踪里。

### 曾疑为 P2、经实测证伪 — 新建行的 `status`

创建分支确实从不写 `status`(模型默认 `candidate`),而 daily_sync
(`:147`)、readiness(`:158,289`)、historical_backfill(`:517`)都按
`status == "active"` 过滤。**看起来**全新 prod 上 Day-0 seed 会产出一批不可见的管理人。

**实测否定了这个假设**:上面那个监听器在 `before_insert` 就把
`confirmed → active` 派生好了。实跑 `seed_confirmed_managers` 于空库,得到
`(status, match_status) = (active, confirmed) × 82`。

保留一条**特征化测试**(`test_new_rows_are_active_so_the_universe_is_actually_tracked`)
把这个隐式依赖钉住:seeding 之所以能闭环,靠的是那个监听器;若有人改动它,
Day-0 会静默断链。

### P3 — `revoked` 是最重的人工决定,而 seeding 有两条路径推翻它(写 review 提示词时实测发现)

`revoke_confirmed_cik`(`thirteenf_admin_dashboard.py:920+`)**强制要求 note**、写
`InstitutionManagerCikReviewEvent` 审计事件,并把 `manager.cik = None` +
`match_status='revoked'` —— 语义是"这个 CIK **不是**这位管理人"。

它派生出的 `status` 是 `needs_review`,**不在** `{inactive, ignored}` 里,所以第一版
M1 的跳过谓词漏掉了它。实测(`valuepilot_test`,已回滚)两条推翻路径:

| 场景 | 结果 |
|---|---|
| revoked 且**有** `dataroma_code`(20/82) | seed 按 code 命中 → 写 `existing.cik = cik` → **把人工摘掉的 CIK 重新挂回**,行与自己的审计日志矛盾 |
| revoked 且**无** `dataroma_code`(62/82) | 两把钥匙(cik 已置空、无 code)都找不到他 → **新建一条 `confirmed` 的重复行**(82→83)→ 被摄取 → 撤销彻底失效,同一人两条记录 |

第二条尤其严重:它从 `create` 路径绕过了 M1 在 `update` 路径上设的所有防线。

**最终修复:** ① 跳过谓词扩为
`status ∈ {inactive, ignored} ∨ match_status ∈ {inactive, revoked, rejected}`;
② 对 revoke 后 `cik=NULL` 的 create 漏洞,不用模糊名字写入,而用审计事件
`InstitutionManagerCikReviewEvent.old_cik == seed.cik AND event_type='revoke_confirmed_cik'`
做精确识别;③ `name_normalized` 只用于**拒绝创建并上报**
`ambiguous_name_match`,永不作为写入钥匙。这样同时阻止 CIK 回挂、重复 confirmed 行,
以及同名弱匹配劫持无关管理人。桶名相应改为 `skipped_human_decided`
(revoked 不是"停用",是"人工决定")。

## PO 裁定(2026-07-09)

- **seed 永不写 `match_status` / `status`**;只写身份与分类字段。新建时才置
  `match_status='confirmed'`。
- **冲突时人工赢**:被人工停用的管理人,seeding 整条跳过。
- **永不自动停用**:seed 不存在的管理人不会被 seeding 改动(dropped 的处理属 M3
  的"提议",不在本票)。
- seeding 输出 **diff 摘要**(created / updated / skipped_human_decided /
  skipped_needs_review / awaiting_confirmation / ambiguous_name_match),
  不再静默返回一个整数。

## Goal / Acceptance Criteria

- `seed_confirmed_managers` 返回结构化报告,而非 `int`。
- 既有行:**不写** `match_status`、**不写** `status`;仅更新身份/分类字段。
- 人工决定态(`status ∈ {inactive, ignored}` 或
  `match_status ∈ {inactive, revoked, rejected}`)的行:**整条跳过**
  (连身份字段也不动),计入 `skipped_human_decided`。
- 人工搁置态(`status='needs_review'` 或 `match_status='needs_review'`)的行:
  **整条跳过**,计入 `skipped_needs_review`。判断顺序在人工决定之后,因为 revoked
  会派生 `status='needs_review'`,仍应归入 `skipped_human_decided`。
- 新建行:`match_status='confirmed'`;`status='active'` 由既有 ORM 监听器派生
  (不重复写),并有特征化测试钉住这条隐式依赖。
- **不静默地"什么也没发生"**:seed 文件里已存在但**尚未 confirmed**(如 dataroma
  同步加入的 candidate)的管理人,身份/分类照常刷新,但**不提升** `match_status`,
  计入 `awaiting_confirmation` 并在摘要中列出 —— 否则策展人把某人加进 JSON 后
  "什么都没发生"会成为静默失败。
- CLI 与 admin job 打印/返回该摘要。
- 幂等:二次运行 created=0、updated 稳定、无重复行。
- create 路径遇到 normalized-name 冲突时拒绝创建并上报 `ambiguous_name_match`;
  名字永不作为自动写入钥匙。
- 整个 seed 在事务级 advisory lock 下运行,防止部署时并发 create 撞 unique CIK。

## 本票带来的行为变化(刻意,需 PO 知晓)

按"seed 永不写 `match_status`"的裁定,一个**已存在且未 confirmed** 的管理人被加入
seed 文件后,不会再被 seeding 自动提升为 confirmed —— 必须由人在 admin 页面确认。
这与"人工拥有生命周期"一致,但它改变了旧行为。摘要里的 `awaiting_confirmation`
就是为此存在:让这件事**可见**,而不是静默。

## Scope

**In:** `seed_confirmed_managers` 写入语义 + 返回契约;其 4 处调用方;测试。
**Out:** 部署时自动调用(M2)、`dataroma_sync` 调度(M3)、统一问题视图(M4)、
prod 开关(M5)。dropped 桶的处理属 M3。

## Files to change

- `backend/app/services/edgar_ingestion.py`(`seed_confirmed_managers`)
- `backend/app/cli/edgar.py`(`seed-confirmed-managers`、`bootstrap-whitelist`)
- `backend/app/services/thirteenf_admin_dashboard.py`(`bootstrap_whitelist` job summary)
- `backend/tests/unit/test_13f_manager_taxonomy_v2.py`(返回契约)
- `backend/tests/unit/test_13f_manager_seed_lifecycle.py` [NEW]

## Test plan(隔离测试库)

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q tests/unit/test_13f_manager_seed_lifecycle.py
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q          # 闭门
```

## 外部评审处置(2026-07-09,Codex;5 条全部确认为真、全部修复)

评审裁定 "M1 not sufficient for M2"。逐条独立复现后处置:

- **[P1] 并发 seed 撞 unique CIK → 启动崩溃循环(已修)。** `cik` 唯一;M2 若挂进
  startup,两个 api 容器可同时走 create 路径,输者 IntegrityError → `restart:
  unless-stopped` 崩溃循环。**修复**:整个 seed 置于
  `pg_advisory_xact_lock('seed_confirmed_managers')`(与 13F 权威的
  `_acquire_period_lock` 同机制,事务级,调用方提交即释放)。回归:
  `test_concurrent_seed_serializes_on_the_advisory_lock`(双 session +
  `pg_try_advisory_xact_lock` 直接探测,并断言无重复 CIK)。
- **[P1] `name_normalized` 兜底会把种子 CIK 写进无关的行(已修,方向性错误)。**
  评审用 `Ariel Capital LLC` 复现。我实测更广:`_normalize_name` 剥掉
  capital/management/investments/…,**35/82 条种子名折叠成单 token**
  (`ariel`、`atlantic`、`cas`、`chou`)。若被撞的行是 `confirmed/active` 且带别的
  CIK,seed 会**覆盖它的 CIK** → 摄取并给错的申报人打分。
  **修复**:① 删掉这条写入路径;② 改用**审计事件精确匹配** ——
  `InstitutionManagerCikReviewEvent.old_cik == cik AND event_type='revoke_confirmed_cik'`
  (revoke 强制写事件,是非模糊的真相来源);③ 名字**只用于拒绝并上报**
  (`ambiguous_name_match`),永不用于写。create 路径遇到同名即 **refuse**,这同时
  兜住"revoked 但缺审计事件"的遗留行。回归:
  `test_seed_never_writes_through_a_normalized_name_match`。
- **[P2] `needs_review` 被错分进 `awaiting_confirmation`(已修)。** admin PATCH
  可显式把行置为 `needs_review`(人工搁置),而 seed 仍刷新其身份/分类 ——
  会覆盖操作员正在裁决的字段。**修复**:新增 `_human_parked_for_review` +
  独立桶 `skipped_needs_review`,**整条跳过**。判断顺序在 `_human_owns_lifecycle`
  之后(revoked 派生的 status 也是 needs_review,它属"人工决定"桶)。回归两条:
  `test_needs_review_row_is_skipped_whole_in_its_own_bucket` +
  `test_revoked_row_lands_in_human_decided_not_needs_review`。
- **[P2] admin job summary 丢掉可操作的 CIK 清单(已修)。** 只有计数,操作员看到
  `awaiting_confirmation: 3` 无从下手。**修复**:summary 保留四份**有上限**的 CIK
  清单(`_SEED_SUMMARY_CIK_CAP = 25`,防止病态种子文件写出无界 JSONB)。
- **[P3] README 的 Day-0 说明失实(已修)。** 它声称 `bootstrap-whitelist` 解析
  Dataroma 插入 ~80 位、`match-cik` 再标 confirmed。实际:前者是**离线 JSON 的废弃
  别名**,种子行**已是 confirmed 且带 CIK**;`match_cik_candidates` 只扫
  `cik IS NULL AND match_status IN ('seeded','candidate')`,根本不会处理它们。
  **修复**:重写 Step 0/1,并把四个桶的**操作含义**写进去(尤其
  `awaiting_confirmation` 不确认就永远不会被摄取)。

**测试助手的教训**:我原来的 `_revoke()` 只改行、不写审计事件,导致新检测在测试里
"看不见"撤销。改为忠实模拟(写 `InstitutionManagerCikReviewEvent`)后才真实。
一个不忠实的测试助手会让正确的实现显得错误,反之亦然。

## 评审提出但**不在本票**的 M2 前置(已确认为真,留给 M2)

- **部署时调用方的事务边界**:开 session → 取锁 → seed → commit;失败 rollback。
  本票只保证函数自身可重入且持锁,不决定谁提交。
- **坏种子文件应当阻断部署**(`derive_legacy_manager_type` 对非法 `style_primary`
  抛 ValueError,刻意 fail loud)。`main.py` 的 start-quarter reconcile 用 try/except
  "永不阻塞启动" —— 该先例**不适用**于种子文件,M2 需明确裁定。
- **宇宙变化的下游重算**:若某次 seed 真的新增了管理人,既有 `ownership_changes` /
  Lens 分数 / readiness 是在旧宇宙下算的。M2 需给出策略:要么保证 seeding 不自动改变
  active 宇宙,要么把宇宙 diff 排成重算 job 并在运维面可见。

## 相位

- [x] 任务doc(本文件)
- [ ] 红:停用者不被复活 / 不写生命周期字段 / 新建置 active / diff 摘要
- [ ] 绿:实现 + 4 处调用方
- [ ] 全量 CI
- [ ] 真实数据验证(dev 82 位:re-seed 后 created=0、生命周期字段零变化)
- [ ] PO 签收 → 之后才可开 M2(部署时自动 seeding)
