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
- [ ] PO 签收
- [x] 清 `docs/BACKLOG.md` F4 条目;新增双计护栏 backlog(deferred)

## Log

- 2026-07-08: 规则改为「凡在本人 HR/HR-A infotable 中的持仓即该管理人可申报仓位
  → direct」;DFND/OTR + 序号引用 → direct,无引用 → unresolved。复用 `direct`,
  消费端零改动。数据核实:OTR 全 839 有引用;Engaged(零-direct 之一)的 42 行是
  OTR,故 OTR 必须纳入。backfill 复用 `_compute_attribution_status`(存储的
  discretion 已规范化)。
- 2026-07-08: **端到端验收暴露连带 crash**:归因把 5 家(Berkshire/Nygren/Gayner/
  Rogers/Hawkins,各持 18–76 只「同季一股多 CUSIP」)首次送入 changes normal 路径
  → dup-key 崩溃(T2 的 per-manager savepoint 已优雅隔离为 partial_success,无数据
  丢失,但会把这些家的 changes 退化为 unavailable = 回归)。评审曾断言 normal 路径
  不崩——对 new-position 成立,但「两季皆持、一股多 CUSIP」的 matched 情形会:
  matched pass 经 dict 去重留一 lot(stock 键),另一 lot 成 straggler,
  `_pair_key` 因两侧皆有 stock_id 回落 stock 键 → 与 matched 行撞键。**surgical 修复**:
  `_pair_key` 恒用 CUSIP 键。加回归测试(两季一股双 CUSIP 不崩、两 lot 皆在、份额不丢)。
  多 CUSIP lot 求和为单一仓位 = 延后到 positions 读模型(backlog)。
