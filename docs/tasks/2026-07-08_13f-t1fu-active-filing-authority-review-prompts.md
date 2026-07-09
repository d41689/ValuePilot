# Review prompts — T1-FU(active-filing authority:accepted_at + 单一权威 + tie + 并发锁)

Task doc: [`2026-07-08_13f-t1fu-active-filing-authority.md`](./2026-07-08_13f-t1fu-active-filing-authority.md)
(含完整设计决策 + 真实数据验证记录)。
Branch: `claude/13f-t1fu-active-filing-authority` — **未提交,评审工作树**:
`git diff HEAD` + 新增未跟踪文件 `backend/tests/unit/test_13f_active_filing_authority.py`。

## What changed

- **新权威** `apply_active_filing_policy(session, manager_id, quarter_end_date)`
  (`backend/app/services/thirteenf_filing_detail.py`):对一个 (manager, period) 组做
  **全部** `is_active_for_manager_period` 决策。优先序:①已解析且非
  rejected/informational 的 RESTATEMENT(`(accepted_at, accession_no)` desc,前二
  **相等且非 NULL** → tie:不自动切换 + warning + `amendments_pending`)→ ②存在
  `amendment_status=='applied'` 的 amendment 则拥有 slot(originals 全灭活,不碰
  admin 的选择)→ ③originals 竞争,**HR 族优先**(有 HR 则 NT 不参赛;NT 仅在无 HR
  时可 active),tie 全灭活 + warning,tie 恢复时 `amendments_pending`→
  `no_amendments_seen`。入口取 `pg_advisory_xact_lock`(键
  `active_filing:{manager_id}:{qend}` 文本哈希)。demote → flush → activate 顺序纪律。
- **四处收敛**:`apply_amendment_policy` 保留 per-filing 归一化、originals 选择块整体
  替换为权威调用(amendment 分支归一化后也调权威收敛组;terminal 早退不调);
  `reconcile_restatement_activation`(`thirteenf_holdings_ingest.py`)变薄委托;
  `_execute_ingest_job` 的 **Phase 4c solo-HR 启发式 bulk UPDATE 与 Phase 5
  reconcile 循环整体删除**,替换为按序逐组 sweep(`thirteenf_admin_dashboard.py`),
  summary keys `filings_activated` / `restatements_applied` 语义保留(按 decision 归类)。
- **accepted_at 填充**:`apply_primary_doc_metadata` 回写 `summary.accepted_at`
  (getattr 防御 partial stub);`backfill_period_routing` 解析循环内、`route_period`
  之前回写,返回 dict 新增 `accepted_at_filled`。
- **测试**:新文件 15 个(权威规则×9、accepted_at×2、并发×1、wrapper×1、solo×1、
  NT×2);`test_13f_amendment_policy.py` 两个既有测试按新语义改写(见下)。

## Context a reviewer cannot see from the diff alone

- **可行性前提(真实数据已证)**:373/373 存量 filing 的存储 primary doc 均含
  `<ACCEPTANCE-DATETIME>`,parser 已能解析——accepted_at 全 NULL 纯因 bulk 路径不回写。
- **dev 库已执行回填 + sweep**(可只读复核):`accepted_at_filled=373`、剩余 NULL 0;
  355 组 sweep **changed=0**、354 active、0 重复 active;唯一无 active 组(manager
  4031,2024-Q4)核实为仅有 pending NEW_HOLDINGS HR/A、无原件——语义正确。
  **零翻转 = accession_no 兜底与真实受理时间序在存量上一致**;评审应独立复核这一点
  (若有翻转被我漏报,属 P1)。
- **tie 规则的实现中修订(重点审)**:任务计划原文只说"相等→tie";实现改为
  **相等且非 NULL**。理由:NULL-NULL 是缺数据不是歧义,当 tie 会把每个未回填期间
  冻结在人工门后并回退 T1 事故修复(accession_no 兜底正是 T1 的确定性保证)。这同时
  **收紧了 originals 分支的既有行为**(旧代码 NULL-NULL originals → tie 全灭活)。
- **两个既有测试按新语义改写**(非回归,是本票要修的行为,判断其合理性):
  - `test_ingest_accession_original_filing_resolves_conflicts` 原钉"晚受理 **NT 偷走
    HR** 的 active"与"NT-HR tie"——改为 HR 优先 + 真 tie 用 HR-HR 演示。
  - `test_reconcile_restatement_ranks_by_accepted_at_over_accession` 原钉"对败者调用
    reconcile = no-op 返回 False"——权威语义下对败者调用**立即收敛出胜者**(返回
    True),终态不变、不依赖调用顺序(wrapper docstring 已声明此强化)。
- **顺带修复的三个既有 bug**(各有回归测试,验证其真实性):①rejected restatement
  会被 Phase 5 重跑复活(旧 reconcile 不看 amendment_status);②NT 可击败 HR;
  ③tie 恢复死代码(旧代码在 `amendment_sort_warning=False` 赋值**之后**才检查它,
  恢复分支永不触发)。
- **两个未收敛的"第五写点"(刻意留下,判断是否可接受)**:
  1. **admin resolve action**(`thirteenf_admin_dashboard.py:470-473`,
     apply/activate_as_original):直接 demote+activate,**不经权威、不持
     (manager, period) 锁**。它设置 `amendment_status='applied'`,权威规则 ②/① 事后
     尊重之;但 admin 动作与并发 sweep 之间无序列化。
  2. **controlled reparse 恢复路径**(`thirteenf_controlled_reparse.py:263-270`):
     失败恢复时直接回写原 active 状态。
  本票 scope 是任务文档定义的四处;这两处是否必须同票收口、还是 backlog,由评审裁断。
- **记录在案的产品判断(可挑战)**:admin 手动 apply 较早 restatement 后,管线重跑
  会按排名切回较晚者;既定 admin 流程 = reject 不要的那份(现状语义,保留)。
- **已知非问题**:`PERIOD_SUSPICIOUSLY_STALE` needs_review 1 条(accession
  `0000899140-26-000219`)为存量已知项,回填时重新 stamp,与本票无关。
- **测试隔离**:dev 库有真实数据,pytest 必须打隔离库:
  ```
  TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
  docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q
  ```
- **已验证(复核勿轻信)**:backend 全量 **1131 passed**;frontend unit 175 / lint /
  build 绿(前端零改动)。

三个提示词给三个 agent,可并行;发现集中写入
`2026-07-08_13f-t1fu-active-filing-authority-review-results.md`。每条 finding 给
`file:line` + 具体 filing/时序场景 + 错误结果;能在 `valuepilot_test` 上复现的先复现。

---

## Prompt 1 — 权威语义与 SEC 13F 领域正确性(关键角度)

```
You are a 13F domain expert reviewing a refactor that unifies "which filing is
active for a (manager_id, quarter_end_date)" into one authority,
apply_active_filing_policy. This flag gates the ENTIRE product surface
(active_hr_holdings_query inner-joins it → managers API, ownership changes,
Oracle's Lens consensus).

Repository: ValuePilot (local), branch claude/13f-t1fu-active-filing-authority,
UNCOMMITTED working tree: read `git diff HEAD` plus the new untracked test file
backend/tests/unit/test_13f_active_filing_authority.py.
Read first:
  - backend/app/services/thirteenf_filing_detail.py — apply_active_filing_policy
    (whole function), apply_amendment_policy (rewired), _active_filing_rank,
    _TERMINAL_AMENDMENT_STATUSES.
  - The OLD logic it replaced: `git diff HEAD` shows the deleted
    apply_amendment_policy originals block, the deleted
    reconcile_restatement_activation body (thirteenf_holdings_ingest.py), and
    the deleted Phase-4c heuristic + Phase-5 loop (thirteenf_admin_dashboard.py).
  - The "Context" section of the prompts doc (deliberate behavior changes).

Pressure-test each rule with a concrete filing timeline; for every real finding
give file:line + the timeline + the wrong active filing:
  1. Behavior-preservation audit: enumerate every behavior the FOUR deleted
     sites had (solo-HR activation, solo-HR/A non-activation, restatement
     supersedes original, applied-amendment-owns-slot, terminal early-return on
     re-ingest, originals tie deactivate-all) and verify the authority
     reproduces each. Name any lost behavior — that is the highest-risk class.
  2. Precedence order: parsed non-rejected RESTATEMENT beats EVERYTHING —
     including an admin activate_as_original'd NEW_HOLDINGS amendment
     (amendment_status='applied')? Rule 1 runs before rule 2, so a later parsed
     restatement will demote an admin-activated non-restatement amendment. Is
     that correct SEC semantics, or should an admin 'applied' always win until
     explicitly revisited? Construct the timeline and judge.
  3. The NT rule: HR-family beats NT regardless of accepted_at; NT competes only
     when no HR original exists. Check against real 13F practice (manager files
     NT, then actually files an HR for the same period — or vice versa) and
     against nt_only_manager_ids (thirteenf_readiness) semantics: does any
     consumer break when an NT that WAS active becomes inactive because an HR
     exists? Also: a 13F-NT/A amendment — the "/A" suffix routes it to the
     amendments bucket, where only RESTATEMENT competes. Can an NT/A ever
     wrongly own or lose the slot?
  4. The tie rule revision (equal AND non-NULL): argue both directions. Is
     accession_no a safe proxy for acceptance order (EDGAR accession sequences
     are per-filer-per-year — is a later acceptance ALWAYS a higher accession
     for the same filer)? If not, name a real counterexample pattern; the T1
     fallback would then pick the wrong winner silently for NULL data.
  5. amendment_status lifecycle: the authority writes 'applied' /
     'amendments_pending' / restores 'no_amendments_seen' (tie recovery). Trace
     every read of amendment_status (admin read models, _amendment_payload,
     quality checks) for a state it can now see that it couldn't before (e.g.
     an ORIGINAL with amendments_pending + warning from a restatement tie
     branch? a superseded restatement still 'applied' while inactive?). Flag
     any read-model/UI contradiction.
  6. The documented product judgment (admin applies the EARLIER restatement →
     next pipeline run switches back to the later one; the sanctioned flow is
     "reject the unwanted one"): accept or reject this judgment, with a
     concrete operator story.

Output: findings ranked by severity; empty list if the semantics hold. For each
confirmed-preserved behavior in (1), one line saying where the authority
implements it.
```

---

## Prompt 2 — 并发、锁与事务边界

```
You are reviewing the concurrency and transaction design of an active-filing
authority that takes pg_advisory_xact_lock('active_filing:{manager_id}:{qend}'
via hashtextextended) before deciding, with demote → flush → activate ordering
under partial unique index uq_active_filing_per_manager_period.

Repository: ValuePilot (local), branch claude/13f-t1fu-active-filing-authority,
UNCOMMITTED: `git diff HEAD` + new test file
backend/tests/unit/test_13f_active_filing_authority.py.
Read first:
  - backend/app/services/thirteenf_filing_detail.py — _acquire_period_lock,
    apply_active_filing_policy (_set_active, flush points, "never commits").
  - backend/app/services/thirteenf_admin_dashboard.py — the new Phase-5 sweep
    (sorted groups, commit barriers), _execute_pipeline_stage_job /
    run_locked_job (T4: job-level locks), and the admin resolve action at
    ~:455-490 which writes is_active DIRECTLY without the period lock.
  - backend/app/services/thirteenf_holdings_ingest.py — _do_ingest_holdings
    (savepoints; where reconcile_restatement_activation is called mid-ingest)
    and thirteenf_controlled_reparse.py:250-275 (direct is_active restore).
  - The two-session test test_concurrent_policy_calls_serialize_on_period_lock.

Probe, with a concrete interleaving for each finding:
  1. Lock soundness: xact-scope means locks release at COMMIT/ROLLBACK. The
     sweep loops sorted groups in ONE transaction, accumulating up to ~82 locks
     until its commit. A concurrent per-accession reparse job takes ONE period
     lock. Construct any deadlock or starvation interleaving (include the
     ingest_holdings quarter job vs two reparse_accession jobs vs the
     quarterly_pipeline). Are all in-code lock acquisition orders really
     consistent (sorted() on (manager_id, qend) — but reconcile inside
     _do_ingest_holdings acquires mid-parse in filing order)?
  2. hashtextextended collisions: two different (manager, period) keys can
     collide → spurious serialization. Confirm no correctness impact, and no
     self-deadlock via reentrancy (same session re-acquiring inside
     apply_amendment_policy → authority → reconcile chains).
  3. The authority "never commits — the caller owns the transaction boundary".
     Audit every caller: apply_amendment_policy (called inside Phase 2.5
     per-filing SAVEPOINTs), reconcile inside _do_ingest_holdings (savepoint +
     commits-per-filing), the sweep (one commit at end), ingest_accession path.
     Can a savepoint ROLLBACK undo the demote but not the activate (or vice
     versa), leaving zero or two actives committed? Remember the partial unique
     index only rejects two ACTIVE rows — zero-active is silent.
  4. The UNLOCKED writers left behind: the admin resolve action
     (thirteenf_admin_dashboard.py:470-473) and controlled_reparse's restore
     path write is_active without the period lock. Race each against a
     concurrent sweep: worst outcome (constraint abort mid-admin-action? admin
     choice silently reverted in the same second?). Judge: must these go
     through the authority/lock in THIS ticket, or is backlog acceptable?
  5. The two-session test: could it pass vacuously (e.g. B blocked on a ROW
     lock from A's uncommitted UPDATE rather than the advisory lock — proving
     serialization but not the advisory mechanism)? Does A's call in the main
     thread actually leave a transaction open under SessionLocal autobegin?
     Propose the minimal strengthening if it proves less than claimed.
  6. Failure atomicity: authority raises mid-way (e.g. flush IntegrityError
     from a concurrent writer despite the lock — can that still happen given
     the unlocked writers in (4)?). What state does the caller's
     rollback/savepoint leave, and does the next sweep self-heal every case?

Output: findings with interleaving diagrams (T1: session A / session B step
lists), ranked; empty if sound. State explicitly whether (4) blocks the PR.
```

---

## Prompt 3 — accepted_at 数据正确性、调用点完备性与爆炸半径

```
You are a staff engineer reviewing the data-population half of this change and
whether the "single authority" claim is actually complete.

Repository: ValuePilot (local), branch claude/13f-t1fu-active-filing-authority,
UNCOMMITTED: `git diff HEAD` + new test file
backend/tests/unit/test_13f_active_filing_authority.py.
Read first:
  - backend/app/edgar/parsers/primary_doc.py:79-82 — ACCEPTANCE-DATETIME regex,
    strptime + tzinfo=timezone.utc.
  - backend/app/services/edgar_ingestion.py — backfill_period_routing (the fill
    placement BEFORE route_period; early-exit flush; new return key) and its
    callers (ingest job Phase 2; anything else — grep).
  - backend/app/services/thirteenf_filing_detail.py — apply_primary_doc_metadata
    (getattr fill) and the ingest_accession path that already set accepted_at
    (line ~88): do the two writes agree?
  - grep `is_active_for_manager_period\s*=` and `amendment_status\s*=` across
    backend/app to enumerate EVERY writer not going through the authority.

Judge, with file:line evidence:
  1. accepted_at semantics: the 14-digit ACCEPTANCE-DATETIME is EDGAR EASTERN
     time, but the parser stamps tzinfo=UTC (pre-existing). For RANKING this is
     consistent across filings — but is it consistent with the ingest_accession
     path's accepted_at, with route_period's use of accepted_at, and with any
     display/deadline logic that assumes real UTC? If inconsistent anywhere,
     is it in scope here (the ticket makes accepted_at load-bearing for the
     first time) or backlog?
  2. Fill placement & idempotency: the fill runs before `if not
     summary.period_of_report: continue` — good. But on parse EXCEPTION the
     filing is skipped silently: can a filing permanently lack accepted_at
     while its siblings have it, and does NULL-vs-non-NULL ranking then behave
     sanely (NULL loses to any non-NULL — is "loses" correct for a filing
     whose doc merely failed to parse)? Also verify accepted_at is never
     OVERWRITTEN with a worse value on re-parse (`!=` comparison overwrites on
     ANY difference — when could summary.accepted_at legitimately change, and
     is last-parse-wins right?).
  3. Authority completeness: from your grep, list every writer of
     is_active_for_manager_period outside apply_active_filing_policy (expected:
     admin resolve action, controlled_reparse restore; anything else?). For
     each: is bypassing the authority correct-by-design (admin override,
     crash-restore), a latent divergence (a rule change in the authority would
     not propagate), or a bug? Would a guard test (grep-based, like T4's
     source guard) that whitelists the sanctioned writers be worth adding?
  4. Blast radius of status transitions: the authority can now set
     amendment_sort_warning + amendments_pending on RESTATEMENTS (tie branch)
     and restore no_amendments_seen on originals. Sweep the admin dashboard
     read models / payloads / quality checks for displays keyed on these
     fields; name any surface that renders a new state wrongly (e.g. "pending
     amendments" badge on a manager whose only issue is a restatement tie).
  5. Job summary drift: Phase-4c/5 → sweep changed the counting basis of
     filings_activated / restatements_applied (per-filing → per-group). Grep
     every consumer of these keys (UI, tests, quality report). Any consumer
     that treats them as per-filing counts?
  6. Test adequacy: the 15 new tests are unit-level against the authority. Is
     there a composition gap like T4's (e.g. nothing proves the INGEST JOB's
     sweep path end-to-end activates a real parsed quarter — Phase 2.5 →
     Phase 3 → sweep)? Check test_ingest_job_failloud coverage of the new sweep
     and propose the minimal missing test if any.

Output: findings ranked; for each, the minimal fix. If the population and
call-site story is complete, say so and name the evidence.
```
