# Task: T1–T4 系列评审修复(2 P1 + 2 P2)

**Created:** 2026-07-09 · **Origin:**
[`2026-07-09_13f-t1-t4-series-review-results.md`](./2026-07-09_13f-t1-t4-series-review-results.md)
(系列级跨票评审,scope `a786cfb..47bf92a`)· **Branch:** `claude/13f-series-review-fixes`

四项发现全部独立确认真实后修复;评审的其余结论(锁分层无死锁、Lens 无泄漏、
PO 验收数字健康、7 项刻意决策接受)无需动作。

## 处置

- **[P1] 权威冻结后 stale ownership_changes 当现势数据(已修,双层)。** 确认:
  compute stage 只枚举当前 active HR 的 manager;冻结(original_tie /
  none_eligible / missing-acceptance)后该 manager 掉出枚举,per-manager compute
  的 delete-at-start + unavailable 返回(本身正确)永远不跑;changes API 读行不查
  active 状态。**修复**:① stage 枚举 = active HR managers ∪ 该季已有 changes 行
  的 managers(冻结者进入 → 旧行被清,`status_breakdown['unavailable']` 运维可见);
  ② API 纵深防线:行存在但该季无 active HR filing → `NO_ACTIVE_FILING`
  unavailable,不渲染争议数据("unknown is not zero")。评审 repro 反转:
  `before:1 → after:0`,冻结窗口 API 即时 withhold。回归:
  `test_compute_stage_clears_stale_rows_after_authority_freeze` /
  `test_changes_api_withholds_rows_without_active_filing`(= 评审 missing test #2)。
  三个既有 user_api 测试的 fixture 补 `_ensure_active_hr_filing`(生产行永远伴随
  active filing;防线负例在 orchestration 测试里显式覆盖)。
- **[P1] 失败 reparse 的已提交无-current-ParseRun 窗口(已修)。** 确认:
  `reparse_accession` 先 demote 旧 current(flush 未提交);`_do_ingest_holdings`
  失败路径写 failed-run 审计并 **commit**(连带持久化 demote);恢复在外层 except
  的**下一个** commit —— 两 commit 之间产品可见"active filing 无 current run",
  崩溃即永久。**修复**:恢复逻辑移进失败审计的同一事务(`_do_ingest_holdings`
  已持有 `old_current_run_id`:恢复 is_current + parse_status='succeeded' 后一次
  commit,原子);外层 except 保留为 bootstrap 异常的幂等兜底。bulk 路径
  (old_current_run_id=None)行为不变。回归:
  `test_failed_reparse_restores_old_current_in_same_commit`(模拟崩溃:内层失败
  commit 后不做任何外层恢复,断言旧 run 已恢复 current;= 评审 missing test #3)。
- **[P2] prod 部署需显式 accepted_at 回填(已落 runbook)。** 接受评审裁定
  (裸部署只收敛下次 job 触及的季度;admin/reparse/旧季 job 先行会误触
  missing-acceptance 冻结)。**生产顺序:部署 → `t1fu_accepted_at_backfill` exit 0
  → 才允许 sweep/reparse/admin/旧季 job → T3 rollout/重算**。

  **第二轮评审补正(门禁曾自身带病):** 初版脚本把门禁埋在 `main()` 里,且只检
  `raw_primary_doc_id IS NOT NULL AND accepted_at IS NULL` —— 无 primary doc 的
  NULL 行直接漏过,**能在 NULL 残留时返回 exit 0**,即"部署闸门证明不了它声称的
  条件"。这正是 T3 把 rollout 验证放进可单测服务模块的原因,初版没照做。
  **修复**:逻辑提取到 `app/services/thirteenf_accepted_at_rollout.py`
  (`run_accepted_at_backfill` / `verify_accepted_at_populated`),契约收紧为
  **门禁通过 ⇔ 无任何 filing 的 `accepted_at IS NULL`**;失败时按补救路径分类
  (无 doc → 跑该季 ingest_holdings;有 doc 无 ACCEPTANCE-DATETIME → 重取 doc),
  并额外列出 `at_risk_groups`(≥2 成员组才真会冻结;solo NULL 无害——权威无需排序
  证据即可裁决,见 `test_solo_restatement_with_null_acceptance_still_wins`)——
  让"仍要放行"成为**显式操作员决定**而非静默通过。
  回归:`test_13f_accepted_at_rollout.py` 6 例,含评审精确复现用例
  `test_gate_fails_on_null_filing_without_primary_doc`。
  双向实测:评审 repro → **exit 1** + 可操作诊断;健康 dev(373 全填)→ exit 0。
- **[P2] BACKLOG NT/A 条目过时(已收窄)。** 条目改为仅剩摄取范围(consumers
  半句已由 T1-FU 三审修复,注明 RESOLVED 部分)。

## 评审建议的登记(不在本轮做)

- missing test #1(quarterly_pipeline 真实 stage 链端到端)→ BACKLOG 新条目。
- 第三护栏(Holding13F 直查白名单)→ BACKLOG 新条目(评审确认当前无违例)。

## 验证

- Backend 全量 **1154 passed**(隔离测试库;+3 回归测试);frontend 175 / lint /
  build 绿。
- 评审两个 P1 repro 均反转;部署脚本 dev 实测。

## 相位

- [x] 逐条独立确认(P1-1 全链、P1-2 时序、P2×2)
- [x] 修复 + 回归测试(评审 missing tests #2/#3 一并落地)
- [x] 部署 runbook 脚本 + 生产顺序文档化
- [x] BACKLOG 收窄 + 2 新条目
- [x] 全量 CI
- [ ] PO 签收 / PR
