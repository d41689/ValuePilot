# Task T1: 13F 摄取管线多重修正案激活修复

**Created:** 2026-07-08 · **Origin:** PO plan `2026-07-08_13f-real-data-findings-po-plan.md`
(F1) · **Severity:** P0-eng(生产季度管线崩溃)

## Goal / Acceptance Criteria

`ingest_holdings` job 的 Phase 5(`_execute_ingest_job` in
`thirteenf_admin_dashboard.py`)按 `filed_at` 升序对每份 filing 调
`reconcile_restatement_activation`。当同一 `(manager_id, quarter_end_date)`
期有 ≥2 份已解析 RESTATEMENT(真实案例:manager 4007 / 2025-Q3,
HR=4956 → HR/A#1=5000 → HR/A#2=5001)时:

1. **崩溃**——Phase 3 已让最新的 5001 active;Phase 5 重新 reconcile 较早的
   5000,在同一次 flush 内 demote 5001 + activate 5000;SQLAlchemy UOW 按主键
   升序发 UPDATE,低 id 的 activate(5000)先于高 id 的 demote(5001),违反
   `uq_active_filing_per_manager_period`(psycopg2 UniqueViolation),整个季度
   job 事务回滚。
2. **即便不崩也语义错误**——会把更旧的修正案激活为 active。

**AC:**
- 同期任意份数的 RESTATEMENT,最终 active 恒为**最新 filed(filed_at,id 次序)
  的已解析 RESTATEMENT**。
- Phase 5 不再抛 IntegrityError,不论 filing 迭代顺序或 id 顺序。
- 幂等:重复运行 quarter job 不改变结果。
- 既有修正案策略测试全绿。

## Scope

**In:** `reconcile_restatement_activation`(单函数加固:①存在更晚 RESTATEMENT
时不激活自身;②demote 后 `flush()` 再 activate,顺序安全)。此单函数修复即让
Phase 5 的逐份循环同时**崩溃安全**且**语义正确**,无需改 Phase 5 循环结构。
**Out:** 归因(T3)、ownership_changes 编排(T2)、CLI(T4)、amendment 策略
其他分支的重构。

## Files to change

- `backend/app/services/thirteenf_holdings_ingest.py`（`reconcile_restatement_activation`）
- `backend/tests/unit/test_13f_amendment_policy.py`（新增多重修正案用例）

## Test plan (Docker)

```bash
docker compose exec -T api pytest -q tests/unit/test_13f_amendment_policy.py
docker compose exec -T api pytest -q            # 全量后端(closing gate)
```

## 相位

- [x] 外部评审(3 角度)+ 独立复核采纳(见
      `2026-07-08_13f-t1-restatement-activation-fix-review-results.md` 的
      "PO / author disposition";顺带析出后续票 T1-FU)
- [x] 任务doc(本文件)
- [x] 红(`test_reconcile_restatement_latest_wins_regardless_of_call_order`
      经 stash-fix 确认真红:无修复时对更早修正案 reconcile 返回 True 并抢占激活)
- [x] 绿(单函数加固:later-restatement 守卫 + demote 后 flush)
- [x] 全量 CI(**1065 passed**,隔离测试库 `valuepilot_test`)
- [ ] PO 签收
- [ ] 清 `docs/BACKLOG.md` 对应条目(随 PR)

## Log

- 2026-07-08: 开票。真实数据首摄取时 live 命中(2026-Q1 及 manager 4007 组);
  dev 已用一次性 ordering-safe 脚本临时修复,本票为生产正式修复。
- 2026-07-08: 实现完成。`reconcile_restatement_activation` 加两处:①同期存在
  更晚 filed 的已解析 RESTATEMENT 时提前返回(该函数对任意一份调用都收敛到最新
  胜出,令 Phase 5 逐份循环天然崩溃安全+语义正确);②demote 后 `flush()` 再
  activate(防 UOW 主键序把低 id 激活排在高 id 降级之前触发唯一约束)。新增 2 用例。
  `test_13f_amendment_policy.py` 12 passed;全量后端 1065 passed。真实数据零改动。
- 2026-07-08: **Code review(/code-review high)发现并修复**——原
  `constraint_safe` 测试是"假阳性护栏":抽掉 `flush()` 仍通过(它构造的是
  demote-低-id / activate-高-id 的天然安全序,没复现危险序)。已重写为
  restatement(低 id)+ active original(高 id)、断言 `id` 序,真正复现
  `uq_active_filing_per_manager_period` 危险。二次验证:抽 flush → 该测试以正确
  约束名 RED;装回 flush → GREEN;全量 1065 passed。另修一处 fixture bug
  (两 filing 默认 `is_latest_for_period=True` 撞 `uq_filings_13f_latest_per_period`,
  曾掩盖上一次"假红")。审查另确认:later-restatement 守卫对两个生产调用方
  (Phase 5 循环 + `_do_ingest_holdings` savepoint 内)在乱序/重复摄取下均收敛正确,
  `flush()` 为纯安全增量(demote 只释放唯一性压力,不新增)。
- 2026-07-08: **外部三角度评审 → 独立复核 → 采纳。** 两个 P1 均属实但已复核定级:
  ①排序键:原 `(filed_at, id)` 与 `apply_amendment_policy` 的
  `(accepted_at or min, accession_no)` 不一致 → **已改为同一键**;但评审建议的
  "accepted_at 并列即整组停用+警告"在真实数据上会**回退本次修复**(全部 373 份
  filing 的 `accepted_at` 皆 NULL,每对修正案都成"伪并列",最新件将永不胜出),
  故 accepted_at 填充+并列语义**延后到 T1-FU**;accession_no 今日仍给确定性全序。
  ②并发:`reparse_accession` 按 accession 加锁,同期两份修正案可并发竞争守卫的
  SELECT-then-mutate → 属实但**既存**(本次未引入)→ (manager, period) 锁归 T1-FU。
  采纳覆盖缺口:新增 accepted_at 优先于 accession、3+ 修正案任意调用序、
  later-failed 忽略、**摄取路径**乱序多修正案(经 `ingest_holdings_for_filing`,
  补上"只直调 reconcile"的空白)。`test_13f_amendment_policy.py` 16 passed;
  全量 **1069 passed**;真实数据零改动。后续 → `2026-07-08_13f-t1fu-active-filing-authority.md`。
