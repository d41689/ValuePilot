# Task T1-FU: unify active-filing selection into one policy (+ accepted_at, ties, concurrency)

**Created:** 2026-07-08 · **Origin:** T1 external review
(`2026-07-08_13f-t1-restatement-activation-fix-review-results.md`) Design Verdict
+ two P1 findings that are correct but **out of scope for the P0 crash fix**.
**Severity:** medium (correctness + robustness; no active production data loss —
see "why not now").

## Problem

"Which filing is active for a `(manager_id, quarter_end_date)`" is decided in
**four** places with **different** rules:

- `_do_ingest_holdings` (per-parse restatement activation via
  `reconcile_restatement_activation`).
- `_execute_ingest_job` Phase 4 (solo-13F-HR auto-activation heuristic).
- `_execute_ingest_job` Phase 5 (restatement reconcile loop).
- `thirteenf_filing_detail.apply_amendment_policy` (original selection, ranks by
  `(accepted_at or min, accession_no)`, deactivates all on an `accepted_at` tie +
  sets `amendment_sort_warning=True`).

T1 aligned `reconcile_restatement_activation`'s ranking KEY with
`apply_amendment_policy` (accepted_at → accession_no) but deliberately did NOT
unify the sites or replicate the tie rule. Four gaps remain:

1. **Scattered authority.** No single `select_active_filing(manager_id,
   quarter_end_date)` covering originals + NT + amendments + restatements +
   parse_status + ordering + ties. The scatter is the root cause of the T1 crash
   and will keep generating edge cases.
2. **`accepted_at` is not populated by the bulk-ingest path.** All 373 real
   filings (incl. all 17 restatements) have `accepted_at IS NULL`, so BOTH
   `apply_amendment_policy` and the T1 ranking degrade to `accession_no`
   fallback. The authoritative SEC acceptance timestamp is simply missing on the
   `ingest_holdings` / `ingest_holdings_for_filing` path (it is captured on the
   `ingest_accession` primary-doc path via `apply_primary_doc_metadata`). Until
   fixed, accepted_at ordering is inert.
3. **Equal-`accepted_at` tie rule not honored for restatements.**
   `apply_amendment_policy` deactivates all tied filings + sets
   `amendment_sort_warning=True`; `reconcile_restatement_activation` auto-resolves
   by accession_no. NOTE: this can only be implemented AFTER (2) — with
   accepted_at all-NULL today, every restatement pair is a false "tie", and
   deactivating on it would REGRESS the T1 incident fix (the latest restatement
   would never win). Sequencing: (2) before (3).
4. **Concurrency.** `reparse_accession` / `reprocess_amendment` lock **per
   accession** (`reparse_accession:{accession_no}`), while `ingest_holdings`
   locks per quarter. Two reparse jobs for two restatements of the SAME
   (manager, period) can run concurrently; the guard SELECT + demote/activate is
   not under a row/advisory lock, so under READ COMMITTED they can race to a
   silent wrong-winner or a `uq_active_filing_per_manager_period` abort.
   Pre-existing (T1 did not introduce it).

## Why not fixed in T1

T1 was a P0 **crash** fix; it stopped the `IntegrityError` that aborted the
quarterly pipeline and made the winner deterministic. (2)+(3) require a
data-backfill of accepted_at and are inert without it; (4) is a pre-existing
concurrency property spanning all activation sites; (1) is a refactor. Bundling
them into the crash fix would violate scope discipline and add risk to a P0.

## Goal / Acceptance Criteria

- One authority `select_active_filing(session, manager_id, quarter_end_date)` (or
  `apply_active_filing_policy`) that all four sites call; ranking = `(accepted_at,
  accession_no)` desc; NT excluded; parse_status respected.
- `accepted_at` populated on the bulk-ingest path (parse it from the primary doc
  in `ingest_if_needed` / `_do_ingest_holdings`, or backfill from stored docs).
- Equal-`accepted_at` ties: no auto-switch; set `amendment_sort_warning=True` +
  `amendments_pending`, consistent with `apply_amendment_policy`. Gated behind (2).
- A `(manager_id, quarter_end_date)` advisory lock (`pg_advisory_xact_lock`) or
  `SELECT … FOR UPDATE` over the period's filings taken before deciding/flipping
  active state, so concurrent per-accession reparse jobs serialize.
- Tests: accepted_at tie (no auto-activation + warning); two concurrent sessions
  reparsing different restatements of one period converge to one winner without a
  constraint abort; accepted_at populated after a real ingest.

## Test plan (Docker) — isolated test DB

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
```

## 设计决策(实现前勘察结论,2026-07-08)

**可行性(真实数据验证):** 373/373 filing 均有存储 primary doc,全部含
`<ACCEPTANCE-DATETIME>`,`parse_primary_doc` 已能正确解析(含 restatement 抽样)
——`accepted_at` 全 NULL 纯粹因为 bulk 路径解析后从不回写。无需新数据源。

**(2) accepted_at 两个挂点(同源幂等,无迁移):**
- `apply_primary_doc_metadata`(权威的 primary-doc 元数据落地函数,Phase 2.5 与
  ingest_accession 都经过):`summary.accepted_at` 非空则回写。
- `backfill_period_routing`(每次 ingest job Phase 2 全量重解析):解析后、调
  `route_period` 前回写——顺带让 routing 立即用上真实受理时间;同函数即一次性
  存量回填载体。返回 dict 增加 `accepted_at_filled`(加 key 安全,消费方用 `.get`)。

**(1) 权威函数 `apply_active_filing_policy(session, manager_id, quarter_end_date)`**
落在 `thirteenf_filing_detail.py`(amendment policy 既有归属)。规则序:
1. 入口取 `pg_advisory_xact_lock`(见 (4))→ 加载该 (manager, qend) 全部 filings。
2. amendment 判定 = `is_amendment OR form_type.endswith("/A")`(Phase 4c 教训:
   bulk 路径 is_amendment 不可靠,"/A" 后缀权威)。
3. **competing restatements** = 已解析(`parse_status=='succeeded'`)且
   `amendment_status NOT IN ('rejected','informational')` 的 RESTATEMENT:
   - 有 → 按 `(accepted_at, accession_no)` desc 取胜者;**前二 accepted_at 相等 →
     tie:不自动切换**(当前 active 保持),tied restatements 置
     `amendment_sort_warning=True` + 非 terminal 者 `amendments_pending`,交 admin。
   - 无 tie → demote 其余 active → flush → activate 胜者(T1 顺序纪律),
     `amendment_status='applied'`。被取代的早期 restatement 保持原状态(沿袭 T1)。
4. 无 competing restatement:若存在 `amendment_status=='applied'` 的 amendment
   (admin apply / activate_as_original)→ originals 全灭活,不碰该 amendment
   (尊重 admin 决定)。
5. originals 池:**HR 族优先**——有 `form_type IN ('13F-HR','13F-HR/A')` 的
   originals 则 NT 不参赛且灭活(修复现状:NT 受理时间晚可击败 HR);仅当无 HR
   originals 时 NT 竞争(保留 active-NT / `nt_only_manager_ids` 概念)。池内按
   `(accepted_at, accession_no)` desc;tie → 全灭活 + warning + `amendments_pending`
   (沿袭 apply_amendment_policy);非 tie → 胜者 active,并**修复既有死代码**:
   tie 恢复时 `amendments_pending`→`no_amendments_seen` 的判断在 warning 清零之后,
   永不触发——改为先读后清。
6. originals 不设 parse_status 门槛(管线在 Phase 2.5 解析持仓前即激活,现状);
   "parse_status respected" 仅指 restatement 门槛。

**四处收敛:**
- `apply_amendment_policy`:保留 per-filing 归一化(amendment 分支的初始状态、
  terminal 早退不变——terminal 早退不调权威,避免每次 metadata 重放都扰动组),
  originals 选择块整体替换为权威调用。
- `reconcile_restatement_activation`:守卫(RESTATEMENT + parsed + qend)后薄委托
  权威;返回"本次是否改变"。注:对非胜者调用现在会立即收敛出胜者(原为 no-op)
  ——终态相同、收敛更快,若既有测试钉中间态则更新并注释。
- `_execute_ingest_job` Phase 4c(solo-HR 启发式 bulk UPDATE)与 Phase 5
  (reconcile 循环)合并为一个 **active-filing policy sweep**:对季度内
  (manager, qend) 组排序后逐组调权威(排序保证锁获取顺序确定,防死锁);
  summary keys `filings_activated` / `restatements_applied` 语义保留(按权威
  返回的 decision 归类计数)。
- `_do_ingest_holdings` 继续经 reconcile 薄包装(accession 级 reparse 即时生效)。

**(4) 并发锁:** `pg_advisory_xact_lock(hashtextextended('active_filing:{mid}:{qend}', 0))`
——xact 级自动释放、同 session 可重入、哈希碰撞仅多序列化无正确性代价。测试:
双连接双线程,A 持锁未提交时 B 必须阻塞,A 提交后 B 收敛,终态恰一 active 且为
排名胜者、无 IntegrityError(自管理提交 + try/finally 清理,绕过回滚 fixture)。

**顺带修复的既有 bug(实现中发现,记录于此):**
- **rejected restatement 复活**:现状 Phase 5 的 reconcile 不看 amendment_status,
  admin 已 reject 的 restatement 在任意季度 job 重跑时会被重新激活并抢走 active。
  权威的 competing 过滤修复之;补回归测试。
- **NT 可击败 HR**:见上第 5 条。
- **tie 恢复死代码**:见上第 5 条。

**明确不改(记录判断):** admin 手动 apply 较早 restatement 后,管线重跑会按排名
切回较晚者——正确的 admin 流程是 reject 不要的那份(现状语义,保留;评审可挑战)。

**实现中修订(RED 阶段发现):tie ⟺ accepted_at 相等且非 NULL。** NULL-vs-NULL
不是歧义而是缺数据,按 accession_no 确定性决胜(T1 事故修复正依赖此兜底;把全 NULL
当 tie 会让每个未回填期间冻结在人工门后,回退 T1)。此规则同样收紧了 originals
分支的既有行为(旧代码把 NULL-NULL originals 当 tie 全灭活——false-tie 陷阱)。
两个既有测试按新语义更新并注明:
- `test_ingest_accession_original_filing_resolves_conflicts`:原钉"晚受理 NT 偷走
  HR active"与"NT-HR tie"——正是本票要修的行为;改为 HR 优先 + 真 tie 用 HR-HR 演示。
- `test_reconcile_restatement_ranks_by_accepted_at_over_accession`:原钉"对败者调用
  = no-op 返回 False"中间态;权威语义下对败者调用立即收敛出胜者(返回 True),终态
  不变、不再依赖调用顺序。

## 真实数据验证(2026-07-08,dev `valuepilot`)

1. **accepted_at 回填:** `backfill_period_routing(db)` → `accepted_at_filled=373`,
   剩余 NULL **0/373**(含全部 17 份 restatement)。既有 `PERIOD_SUSPICIOUSLY_STALE`
   needs_review 1 条为存量已知项,period 零变化。
2. **只读预测:** 355 个 (manager, qend) 组,预测翻转 **0**、真 tie **0** ——
   accession_no 兜底与真实受理时间序在存量数据上完全一致,权威上线零扰动。
3. **实际 sweep:** `apply_active_filing_policy` 逐组执行 → **changed=0**,
   decisions = {original: 343, restatement: 11, none_eligible: 1},354 active、
   0 重复 active 组。`none_eligible` 组核实为 manager 4031 2024-Q4 仅有一份
   NEW_HOLDINGS HR/A(amendments_pending,无原件)——非 restatement 修正案不自动
   激活,语义正确。

## 评审处置(2026-07-09,`...-review-results.md`:5 P1 + 6 P2 + 测试缺口,全部确认真实、全部修复)

先独立复现关键论断再修:admin resolve / controlled_reparse 代码与评审吻合;
**231/373** accession 前缀非 manager CIK、恰好 **3 组**字典序-受理序倒序(全为
manager 3988 换申报代理)——逐字复现,accession 作时间代理被实证推翻。

- **[P1] admin resolve 绕过权威+锁 → 重写 `resolve_amendment`**:advisory 锁**先于**
  任何行变更获取(旧 `FOR UPDATE` 先取行锁,与 sweep 的 advisory→行锁顺序倒置,
  正是评审构造的死锁);动作只表达意图(status),`apply_active_filing_policy`
  在锁下收敛——**reject 当场把 slot 交给下一个 eligible**(旧代码 rejected 仍
  active 直到未来某次 sweep)。回归:`test_admin_reject_immediately_demotes_...` /
  `test_admin_apply_activates_target_...`。
- **[P1] Rule 2 无 owner、rejected 可永久 active → owner 选择 + 全组收敛**:
  applied amendments 按同一排序键取唯一 owner 并 `_set_active`(demote 含
  rejected-active);`none_eligible` 分支 demote 一切 stray active。评审时间线
  (apply A → apply B → reject B → B 永久 active)修复。回归:
  `test_rule2_selects_unique_owner_...` / `test_none_eligible_demotes_stray_active`。
- **[P1] NULL accepted_at 静默选错 → missing-acceptance 规则**:池 ≥2 且任一
  NULL = 证据缺失,**不切换**,整个争议池 + 保持 active 者全部 flag
  (warning + 非 terminal → amendments_pending)交人工;单成员池不受影响
  (solo NULL restatement 仍可接管)。**accession_no 兜底整体移除**(前缀是申报
  代理 CIK,非时间代理——3 组真实倒序为证);两个 T1 全 NULL 测试按新语义改写并
  注明。回归:`test_missing_acceptance_does_not_flip_active` /
  `test_solo_restatement_with_null_acceptance_still_wins` + 组合级 mixed-NULL。
- **[P1] tie 不向 active filing 传播不确定性 → kept-active 也 flag**:
  tie / missing-acceptance 时保持 active 的 filing 同样置
  `amendments_pending` + warning——直接流入 Lens 既有 MVP4-05 caveat 与
  MVP5-02 排除机制,active filing 不再被当干净信号打分。terminal(applied)
  的 kept-active 只加 warning 不降级 status(不推翻 admin 决定),该窄缝记录在案。
  回归:`test_restatement_tie_flags_kept_active_filing`。
- **[P1] controlled_reparse 恢复不持久 → `_reject_validation_failed_amendment`**:
  gate 失败的 RESTATEMENT 置 `rejected`(权威尊重的排除态)+ 锁下权威收敛;
  裸指针恢复删除(下次 sweep 会确定性翻回,静默推翻验证门)。admin 修好后可
  re-apply。回归:`test_validation_failed_restatement_rejection_is_sweep_durable`
  (含"再 sweep 不翻回"断言)。
- **[P2] restatement tie 残留 → `_clear_stale_residue` 组级恢复**:任一规则胜出后
  清全组 was_warned 残留(originals→no_amendments_seen;restatements→pending_parse;
  其他 amendment 仅清 warning)。回归:`test_restatement_tie_recovery_clears_all_residue`。
- **[P2] ACCEPTANCE-DATETIME 是美东墙钟 → 解析器修正**:`America/New_York` 解释
  (DST-aware)→ 存真 UTC;`edgar_accepted_date_eastern()` 供 SEC 日历日规则
  (routing 窗口 ×2、value_units cutover)转回美东取 date。DST + 晚 8 点跨日测试。
  dev 存量经回填重写 373 条(EDT +4h / EST +5h)。
- **[P2] 三写点 merge 语义 → `merge_accepted_at`**:非 NULL 才写(裸文档不抹掉
  已知证据)、同源重解析可覆盖(解析器修正必须能传播——正是 ET 修复所需)、幂等。
  三写点(metadata / 回填 / ingest_accession)统一。回归:
  `test_merge_accepted_at_never_erases_with_null`。
- **[P2] NT/A 参赛 → rule 1 加 HR-family 守卫**:competing restatement 必须
  `form_type IN ('13F-HR','13F-HR/A')`;NT/A 摄取支持缺口记 BACKLOG(latent,
  INGESTION_FORMS 本就不含 NT/A)。回归:`test_nt_a_restatement_never_competes_...`。
- **[P2] 并发测试可空洞通过 → `pg_try_advisory_xact_lock` 直接断言**(独立探测
  session 在 A 持锁时 try=False、A 提交且 B 结束后 try=True——排除行锁假阳性;
  after-commit 探测放在 B 完成后,避免与 B 的排队获取竞争)。
- **[P2] sweep 累积全部锁 → 每组 commit**(独立幂等决策,锁即时释放,消
  head-of-line);Phase 2.5 pass-2 同理每 filing commit。
- **[测试缺口] 组合测试 ×2**:真实 `execute_job_payload('ingest_holdings')` 全链
  (Phase 2 routing 填 accepted_at → 2.5 metadata+policy → 3 parse → 5 sweep),
  断言 accepted_at 持久(含 ET→UTC)、routed、active、`active_hr_holdings_query`
  可见;mixed-NULL 组不翻转 + 全 flag。仅 stub 字节读与 EDGAR fetch。
- **[评审建议] 源码护栏**:`test_no_active_flag_writer_outside_the_authority_module`
  —— services 下 `is_active_for_manager_period =` 赋值仅允许
  `thirteenf_filing_detail.py`(admin/controlled_reparse 写点已收敛,护栏防回退)。

**真实数据复验(修复后):** 回填重写 373/373(ET→UTC);sweep 355 组
**changed=0**、354 active、0 dup、**0 warning**——全部修复对存量零扰动。

## 复审处置(2026-07-09 第二轮:1 P1 + 1 P2 + 1 非阻塞,均确认真实、P1/P2 已修复)

复审确认第一轮 11 项全部 resolved,新增两项均先独立复现(rollback repro 输出与
评审逐字一致)再修:

- **[P1] admin `defer` 被权威当场推翻(已修)。** defer 旧值 `amendments_pending`
  是**竞争态**(rule 1 只排除 rejected/informational)→ 收敛调用在同一事务里把
  刚 defer 的 parsed restatement 重新激活并改回 `applied`,操作员动作被抹掉。
  复现:`{'rst_active': True, 'rst_status': 'applied'}`。**修复**:新增专用状态
  **`deferred`** —— ① `resolve_amendment` defer 分支写 `deferred`;② 权威 rule 1
  排除集加 `deferred`;③ 加入 `_TERMINAL_AMENDMENT_STATUSES`(bulk re-ingest 的
  metadata 重放不得重置 admin 决定);④ dashboard 状态展示把 `deferred` 归入
  pending 行(前端对 amendment_status 透传,新值安全);health 的 pending 计数
  **不含** deferred——defer 的意图正是从告警/队列中搁置,记录在案。defer 一个
  active restatement = 撤下并把 slot 交给下一 eligible。dev 存量无 deferred,
  无迁移。回归:`test_admin_defer_is_honored_and_excluded_from_competition` /
  `test_admin_defer_of_active_restatement_hands_slot_back` /
  `test_bulk_reingest_does_not_reset_deferred`。修复后复现脚本输出
  `{'orig_active': True, 'rst_status': 'deferred'}` ✓。
- **[P2] admin apply 的 NT/A active 后 `nt_only_manager_ids` 漏认(已修)。**
  rule 2 尊重 admin applied(不限 form family,保留——admin 决定优先),但消费方
  只认 exact `13F-NT`。**修复**:`NT_FORM_TYPES = ("13F-NT","13F-NT/A")`,
  `nt_only_manager_ids` 按 NT-family 匹配——active NT/A 一律按 notice 对待,
  分母正确;`active_hr_holdings_query` 的 HR 过滤天然排除 NT/A(无持仓泄漏)。
  干净 manager 复现脚本:修复前 `nt_only_has_mgr: False` → 修复后 `True` ✓。
  回归:`test_admin_applied_nta_counts_as_nt_only`。BACKLOG 的 NT/A 摄取缺口条目
  保留(完整 NT-family 摄取支持仍未实现,此处只修一致性)。
- **[非阻塞] `merge_accepted_at` 对不同非 NULL 值静默覆盖(保留,PR 明示)。**
  评审认可"同源重解析授权覆盖"对 ET→UTC 迁移是刻意设计,不阻塞;要求 PR body
  点名。已记录:覆盖仅来自同一存储文档的重解析(单一来源),无跨源冲突面;若未来
  引入第二来源(如 EDGAR API),需升级为冲突审查工作流。

## 三审处置(2026-07-09 第三轮:前两项确认 fixed;1 P2 + 1 非阻塞)

- **[P2] NT/A 只部分按 NT-family 处理(已修,全仓扫净)。** 上轮只改了评审点名的
  `nt_only_manager_ids`;三审据本票自己写的注释("everywhere exact 13F-NT was")
  指出仍有 exact-NT 消费方。**全仓 grep 后一次收敛 6 处**(超出评审点名的 2 处):
  `thirteenf_user_api` ×3(holdings 入口 → `NOTICE_REPORTED_ELSEWHERE`;
  `_quarter_payload` → `reported_elsewhere`;`_filing_caveats` → NT caveat)、
  `oracles_lens/base_primitives._is_nt_quarter`(NT/A 季度断 streak + NT caveat)、
  `thirteenf_ownership_changes`(prior NT/A → `PRIOR_NT_REASON`)、
  `thirteenf_filing_detail._normalize_report_type` / `_coverage_type`
  (NT/A → notice_report / notice_reported_elsewhere)。**刻意不改**:
  `form_idx._DAILY_13F_FORM_TYPES` 与 `daily_sync.tracked_13f_nt_found_count`
  ——那是摄取范围白名单,扩 NT/A 摄取属 BACKLOG 既有条目。评审三条 repro 全部
  反转:quarter status `unavailable`→`reported_elsewhere`、holdings
  `code None`→`NOTICE_REPORTED_ELSEWHERE`、`is_nt_quarter False`→`True`。
  回归:`test_active_nta_treated_as_notice_across_consumers`(user_api 三面 +
  Lens streak)。
- **[非阻塞] `deferred` 不进 pending 计数(产品选择,已文档化)。** defer 语义 =
  "搁置且不阻塞打分/告警"——deferred 不再出现在 pending-amendments 队列与
  health/readiness pending 计数(它们仍按 `amendments_pending`/`amendment_failed`
  键控),dashboard 行级展示仍归 pending。与旧 `defer→amendments_pending` 行为的
  可见差异已在二审处置记录,PR body 将点名。

## 相位

- [x] 任务doc(本文件 + 设计决策)
- [x] (2) accepted_at 回填/摄取期填充 + 测试
- [x] (1) 单一 apply_active_filing_policy 权威 + 四处收敛
- [x] (3) tie → warning(非 NULL 相等才算 tie;依赖 2)
- [x] (4) (manager, period) 锁 + 双连接并发测试
- [x] 外部评审第一轮(5 P1 + 6 P2 全部确认并修复)
- [x] 外部复审第二轮(defer P1 + NT/A P2 确认并修复)
- [x] 外部三审第三轮(NT/A 一致性全仓收敛 6 处;deferred 产品选择文档化)
- [x] 全量 CI(backend **1151 passed** 隔离测试库;frontend 175 / lint / build 绿)
- [x] 真实数据验证(373 accepted_at 回填→ET 修正重写;sweep 零翻转零 warning;
      dev 无 deferred 存量,无迁移)
- [ ] PO 签收
- [ ] 清 `docs/BACKLOG.md` 对应条目(随 PR)

## 相位

- [x] 任务doc(本文件 + 设计决策)
- [ ] (2) accepted_at 回填/摄取期填充 + 测试
- [ ] (1) 单一 apply_active_filing_policy 权威 + 四处收敛
- [ ] (3) tie → warning(依赖 2)
- [ ] (4) (manager, period) 锁 + 并发测试
- [ ] 全量 CI
- [ ] 真实数据验证(373 accepted_at 回填 + sweep 零意外翻转报告)
- [ ] PO 签收
- [ ] 清 `docs/BACKLOG.md` 对应条目
