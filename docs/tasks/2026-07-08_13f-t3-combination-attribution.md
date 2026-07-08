# Task T3: 组合/共享裁量归因修复(让巴菲特等旗舰在产品可见)

**Created:** 2026-07-08 · **Origin:** PO plan `2026-07-08_13f-real-data-findings-po-plan.md`
§2 (F4) · **Severity:** P0-product / HIGH

## Goal / Acceptance Criteria

`_compute_attribution_status` (`backend/app/services/thirteenf_holdings_ingest.py`)
maps `DFND` + `other_managers_raw` → `reported_for_other` and `OTR` → `shared`,
both **excluded** from the product query surface (`holding_attribution_status ==
'direct'`). On real data this makes **7 of 82 managers have ZERO direct
holdings** — Buffett/Berkshire, Marks/Oaktree, Burry/Scion, Watsa/Fairfax,
Cantillon, Egerton, Engaged — so the flagship product is empty for them.

Root cause (verified): `other_managers_raw` holds **cover-page included-manager
sequence numbers** (`4,8,11`), not external CIKs. Per SEC semantics, a holding
in a manager's OWN infotable is that manager's reportable position; DFND/OTR
with those refs is the standard multi-manager/combination-report pattern, not
"reported by someone else".

**Ruling (PO plan §2.2), implemented here:**

| discretion | other_managers_raw | attribution |
|---|---|---|
| SOLE | — | `direct` (unchanged) |
| DFND | has refs | **`direct`** (was `reported_for_other`) |
| OTR | has refs | **`direct`** (was `shared`) |
| DFND / OTR | none | `unresolved` (honest) |
| (any) | filing is 13F-NT | excluded (NT has no infotable) |

- **Reuse `direct`** (no new enum, no schema change) → all consumers
  (ownership_changes, `thirteenf_user_api`, Oracle's Lens ×5,
  `unknown_manager_priority`) pick it up with **zero read-site changes**.
  sole-vs-shared nuance preserved in the existing `investment_discretion` column.
- **Backfill** existing holdings via the canonical `_compute_attribution_status`
  (data update, not schema — no band-aid). Then recompute `ownership_changes` +
  Oracle's Lens scores for affected managers.
- **Fix the combination caveat copy** (`COMBINATION_CAVEAT` in
  `thirteenf_user_api.py`) — it currently says holdings are "not included here",
  now false; keep the caveat, correct the wording.

**AC (verified on real dev data):**
- `GET /13f/managers/3984/holdings/changes` returns Buffett's changes (not
  NO_COMPUTED_CHANGES); Berkshire has Oracle's Lens score components; all 7
  managers have direct holdings + changes.
- No double-count: Berkshire counts as ONE holder of a stock.
- ~4,050 holdings re-attributed (3211 DFND + 839 OTR); SOLE 20,538 unchanged;
  482 DFND-no-refs stay `unresolved`.

## Scope

**In:** `_compute_attribution_status` rule; a backfill entrypoint; combination
caveat copy; unit + integration tests; real-data backfill + recompute.
**Out:** cross-filer double-count review guard (deferred → BACKLOG, not
currently triggerable: no sub-manager is separately tracked in the 82-universe);
the positions read-model (T2 backlog); investor-workflow UI (tickets 01/02).

## Files to change (indicative)

- `backend/app/services/thirteenf_holdings_ingest.py` (`_compute_attribution_status`
  + `backfill_holding_attribution`).
- `backend/app/services/thirteenf_user_api.py` (caveat copy).
- `backend/app/cli/edgar.py` (a `backfill-attribution` command for prod).
- `backend/tests/unit/test_13f_holdings_parser.py` (attribution contract tests).

## Test plan (Docker) — isolated test DB

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q tests/unit/test_13f_holdings_parser.py
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q      # closing gate
```

## 相位

- [x] 任务doc(本文件)
- [x] 红:归因契约测试(DFND+refs→direct、OTR+refs→direct、no-refs→unresolved)
- [x] 绿:`_compute_attribution_status` 规则(SOLE/DFND/OTR 在本人 infotable → direct)
- [x] backfill 入口(`backfill_holding_attribution` + CLI `backfill-attribution`)+ 测试;修 caveat 文案
- [x] 全量 CI **1078 passed**(既有 attribution 契约测试改为新规则)
- [x] **crash 修复(T3 暴露的连带 bug)**:归因让组合申报人(Berkshire 等 5 家)
      首次进入 changes 的 normal 路径,触发同季一股多 CUSIP 的 `_matched_pairs`
      straggler 经 `_pair_key` 回落 stock 键 → 撞唯一键。改 `_pair_key` 恒用
      CUSIP 键(stock 键分支只会在该 straggler 情形触发,故安全),两 lot 各成行、
      不丢份额,mapping-transition 不受影响(评审 [P1] 的测试仍绿)。
- [x] 真实数据:backfill 4050 行 → 零零-direct;重算 changes/scores 6 季 **0 失败**;
      **巴菲特 changes API=available/62 行**(16 清仓/7 减/6 增/4 新建);7 家全部进
      Oracle's Lens;无双计(每股一 holder)。Oaktree changes 仍 unavailable = mapping-ratio
      门(55/147 已链,0.35),属 CUSIP 富化覆盖问题,非归因/非本 crash。
- [x] **评审整改(4 项 merge blocker)** — 见 `...-review-results.md` 与下方 Log:
      #2 确定性 CUSIP-优先匹配、#1 DFND/OTR 无 Column 7 也 direct、#3 持仓级共享
      caveat、#4 可执行生产 runbook。全量后端复跑绿;真实数据经 runbook 脚本自验通过。
- [ ] PO 签收
- [x] 清 `docs/BACKLOG.md` F4 条目;新增双计护栏 + sub-threshold-caveat + positions backlog

## 生产滚动 (runbook)

T3 含数据回填 + 两个物化产物重算。部署自动化只做 build+健康检查(迁移/回填按
AGENTS.md 约定手动),故部署后**运行一次**幂等自验脚本(顺序:回填 → 重算变动 →
重算 Lens → 校验,任一校验失败即非零退出):

```bash
# 代码上线后,在 prod api 容器内:
docker compose -f docker-compose.prod.yml exec -T api python -m scripts.t3_attribution_rollout
```

脚本校验:无残留 `reported_for_other`/`shared`、零零-direct、每-manager 变动重算
零失败、旗舰 Berkshire 有 direct 持仓且有真实变动。dev 上已跑通(exit 0)。

## Log

- 2026-07-08: **第三轮评审整改(2 项)。** #1 rollout:任何 stage 状态非 `succeeded`(hard `failed` 或 `partial_success`)都记为失败并上报(此前 Lens 循环完全不看状态、ownership 只看 failure_count,hard-failed 无此字段 → 假通过);恢复代表性物化后置校验(旗舰 Berkshire direct>0 且 real_changes>0,无旗舰则跳过)。加注入 hard-failed(ownership/lens)+ partial_success 测试。#2 caveat 文案改中性(“与其他管理人共享/defined 裁量,可能含关联方/子公司/被聚合申报的管理人”),不再把 sub-threshold(空 other_managers_included)误述为 included managers。加文案测试。全量 **1095 passed**。

- 2026-07-08: **第二轮评审整改(re-review 2 项)。** #4 rollout:逻辑抽到
  `app/services/thirteenf_attribution_rollout.py`(可测),重算走**加锁 JobRun**
  (`_execute_pipeline_stage_job`,冲突则 `RolloutConflictError` exit 2);校验改为
  在 `SOLE/DFND/OTR AND status<>'direct'`(原 bug 的精确不变量)与 `zero_direct>0`
  与 per-manager 失败上**失败**,不再只查 legacy;加故障注入 + 锁冲突测试。
  #3 残留:管理人页/持有人 caveat 改从**展示持仓的 discretion**派生(Giverny 4007
  的 35 只 DFND 现在带 caveat);ownership_changes **unavailable 分支**补 caveat;
  Oracle's Lens 改为组内 **any() lot** 判定(非仅 representative)。全量 **1091 passed**;
  rollout 真实数据自验 exit 0。管理人页残留 backlog 条目已消(此处修复)。

- 2026-07-08: 规则(初版)DFND/OTR + 序号引用 → direct,无引用 → unresolved。复用
  `direct`,消费端零改动。backfill 复用 `_compute_attribution_status`。
- 2026-07-08: **外部评审 4 项 merge blocker 全部整改(独立复现后采纳)。**
  **#2 匹配:** 真实数据无多-distinct-CUSIP、却有 2,174 组同-CUSIP 重复 lot(组合
  申报把一笔仓位拆到多个纳入管理人);且评审复现的"倒序插入 + `_direct_active_hr_holdings`
  无 ORDER BY"会让 dict 折叠跨-lot 错配 → 假清仓/假新建/假 cusip_changed。重写
  `_matched_pairs`:先按 CUSIP 聚合同-CUSIP lot,再 **精确 CUSIP 优先匹配**(确定性、
  与顺序无关),余量再做 stock 级(真 cusip 变更),最后 new/exited。删除死代码
  `_pair_key`。**#1 归因:** 依 SEC FAQ 37/46/48,与低于 $100M 门槛的管理人共享裁量
  时聚合进本人申报且**不列 Column 7**——空 Column 7 不是排除信号。真实数据 Cantillon
  的 Adobe 被拆成"有引用 direct / 无引用 unresolved"两半(更大的 628,547 股被误排除)。
  改为 **SOLE/DFND/OTR 一律 direct,与 Column 7 无关**;仅无法识别裁量 → unresolved。
  同步修 PO 计划 §2 与误导性注释。**#3 caveat:** 从持仓级(DFND/OTR)+ 封面
  `other_managers_included` 派生 `SHARED_DISCRETION` caveat,不再仅看
  `report_type==combination_report`——Berkshire 的 complete holdings_report 现在带
  caveat。透明标注、**不降级**(是申报人真实敞口,降级会重新压制旗舰)。接到三处:
  `_filing_caveats`(管理人页/持有人)、ownership_changes 行、Oracle's Lens
  per-holder caveats。**#4 runbook:** 新增 `backend/scripts/t3_attribution_rollout.py`
  幂等自验脚本(回填→重算变动→重算 Lens→校验)+ 任务doc runbook 段。
  **验证:** 全量后端复跑绿;rollout 脚本 dev 自验 exit 0(零-direct=0、变动重算 0 失败、
  Berkshire direct=543 / real_changes=174)。残留(backlog):7 家 sub-threshold-无封面
  列名的共享持仓,其 changes/Lens 已由持仓级 discretion 打上 caveat,但管理人页
  `_filing_caveats`(仅看 filing)未覆盖 → 记 backlog。
- 2026-07-08: **端到端验收暴露连带 crash**:归因把 5 家(Berkshire/Nygren/Gayner/
  Rogers/Hawkins,各持 18–76 只「同季一股多 CUSIP」)首次送入 changes normal 路径
  → dup-key 崩溃(T2 的 per-manager savepoint 已优雅隔离为 partial_success,无数据
  丢失,但会把这些家的 changes 退化为 unavailable = 回归)。评审曾断言 normal 路径
  不崩——对 new-position 成立,但「两季皆持、一股多 CUSIP」的 matched 情形会:
  matched pass 经 dict 去重留一 lot(stock 键),另一 lot 成 straggler,
  `_pair_key` 因两侧皆有 stock_id 回落 stock 键 → 与 matched 行撞键。**surgical 修复**:
  `_pair_key` 恒用 CUSIP 键。加回归测试(两季一股双 CUSIP 不崩、两 lot 皆在、份额不丢)。
  多 CUSIP lot 求和为单一仓位 = 延后到 positions 读模型(backlog)。
