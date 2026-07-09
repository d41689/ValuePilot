# Review prompts — PR #113(release readiness:池定义提取 + 门禁诊断 + runbooks)

Branch: `claude/13f-release-readiness` · **PR #113**(CI green)· base `main` = `e1c9631`
读 diff:`git diff main...claude/13f-release-readiness`

这个 PR **小但危险**:它重构了 `apply_active_filing_policy` —— 那个决定整个产品面
可见性的单一 boolean(`filings_13f.is_active_for_manager_period`)的权威函数,而该
函数刚刚经历四轮外部评审。同时它新增两份**会被真正执行在生产上**的 runbook。

## 变更清单

| 文件 | 改动 |
|---|---|
| `thirteenf_filing_detail.py` | **提取 `competition_pool(filings) -> (kind, pool)` 与 `is_amendment_filing()`**;`apply_active_filing_policy` 改为按 `kind` 分支(rule 1 用 `_pool`、rule 2 用 `_pool`、rule 3 用 `_pool`)。**声称行为完全不变。** |
| `thirteenf_accepted_at_rollout.py` | `_at_risk_groups` 从 `group_size >= 2` 代理改为调用 `competition_pool`;新增 `pool_kind` / `pool_size` / `pool_missing_accepted_at` 字段 |
| `scripts/t1fu_accepted_at_backfill.py` | 打印跟随新字段 |
| `tests/unit/test_13f_accepted_at_rollout.py` | +4 测试(Berkshire 形状、两个竞争 restatement、两个 original、admin-applied 槽位) |
| `README.md` | 删除两处已不存在的 `enrich-stocks-edgar` |
| `docs/runbooks/13f-data-v1-release-checklist.md` [NEW] | 既定事实 + 部署顺序 + 验收表 + 回滚 |
| `docs/runbooks/13f-data-v1-prod-release-agent-prompt.md` [NEW] | 交给 prod 侧 agent 执行的自包含提示词 |

## 触发这次改动的真实数据事实(评审可复核)

在 prod 拓扑 + 真实升级前快照(373 filings,`accepted_at` 全 NULL)上:

- 旧诊断(`group_size >= 2`)报 **16 组 "WILL FREEZE"**;
- 真正能冻结的只有 **2 组**(均为 `restatement(2)` 池);
- 反例:Berkshire 2025-Q1 有 2 份 filing(1 份 HR 原件 + 1 份**非-restatement**
  HR/A 修正案),竞争池只有 **1 个成员**,`apply_active_filing_policy` 在
  `accepted_at` 全 NULL 时仍返回 `decision='original'`、**不冻结**。

## 评审者看不到的上下文

- **`is_active_for_manager_period` 是产品面的唯一闸门**:`active_hr_holdings_query`
  (PRD §7.3)内联 join 它。判错 = 用户看到错的持仓,或看不到持仓。
- **missing-acceptance 规则**(T1-FU):竞争池 ≥2 且任一成员 `accepted_at IS NULL`
  → 顺序不可知 → **不切换 + 打标冻结**(`amendment_sort_warning` +
  `amendments_pending`),交人工。单个成员的池无需排序证据即可裁决。
- **`amendment_owned` 槽位不需要排序证据**(admin 已决定),故诊断刻意跳过它。
- 本 PR **无数据库迁移**(整个 13f-data-v1 系列都没有)。
- prod 在另一台自托管机器上,**本次改动未触碰 prod**;prod 已通过 auto-deploy 拿到
  `e1c9631` 代码,但 accepted_at 门禁从未在 prod 跑过。
- **演练库已删除**。如需复现:`valuepilot_realdata_20260708.dump`(pre-T1-FU 快照)
  在会话 scratchpad,可能已不可访问;可用 `pg_dump` 从 dev `valuepilot` 自制近似
  快照(但 dev 的 `accepted_at` 已被回填,需手动置 NULL 才能复现旧态)。

## 测试基础设施

dev 库 `valuepilot` 持真实数据,pytest **必须**跑在隔离库:
```
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q     # 1163 passed 为基线
```

## 刻意决策(judge,勿当"发现"重报)

1. `competition_pool` 同时被权威与门禁调用 —— 这是**目的**,不是耦合意外:代理漂移
   正是本次要修的 bug。
2. 门禁的 pass/fail **只看** `accepted_at IS NULL` 总数;`at_risk_groups` 纯诊断,
   不参与退出码。
3. `amendment_owned` 与 `none` 两类 kind 永不进 at-risk 列表。
4. 权威函数里仍分别计算 `amendments` / `originals`(rule 2/3 的 demote 与 tie 处理
   需要),与 `competition_pool` 内部有重复遍历 —— 为可读性接受。
5. tag `13f-data-v1` 不触发任何部署(`deploy.yml` 只监听 CI-on-main / dispatch)。

三个提示词并行;结果写入 `2026-07-09_13f-release-readiness-review-results.md`。
每条 finding 给 `file:line` + 可构造的输入 + 错误产品结果;能在 `valuepilot_test`
复现的先复现。

---

## Prompt 1 — 权威函数重构的行为保持性(关键角度,对抗式)

```
You are reviewing a refactor of the ONE function that decides which 13F filing
is "active" for a (manager, quarter) — the boolean the entire product surface is
gated on (`active_hr_holdings_query` inner-joins it). The author CLAIMS the
extraction is behaviour-preserving. Your job is to prove it isn't, or to prove
it is by construction. Assume the claim is false until you can't break it.

Repository: ValuePilot (local). Read the diff with
`git diff main...claude/13f-release-readiness -- backend/app/services/thirteenf_filing_detail.py`.
Read BOTH versions of `apply_active_filing_policy` side by side (`git show
main:backend/app/services/thirteenf_filing_detail.py`), plus the new
`competition_pool` / `is_amendment_filing`.

Reconstruct the OLD control flow exactly:
  competing = [amendments where amendment_type=='RESTATEMENT' and form in HR
               and parse_status=='succeeded' and status not in
               ('rejected','informational','deferred')]
  if competing: <missing-acceptance | tie | winner>
  applied_amendments = [amendments where status=='applied']
  if applied_amendments: owner = max(applied, rank); ...
  hr_originals = [originals where form in HR]; pool = hr_originals or originals
  if not pool: none_eligible (demote stray)
  <missing-acceptance | tie | winner> on pool

...and the NEW one, which branches on `pool_kind` from `competition_pool`.

Find any group composition where OLD and NEW diverge. Enumerate systematically —
do not spot-check. Cross the axes:
  * form_type: 13F-HR, 13F-HR/A, 13F-NT, 13F-NT/A
  * is_amendment True/False vs the "/A" suffix (they DISAGREE in real bulk data)
  * amendment_type: RESTATEMENT / NEW_HOLDINGS / None
  * amendment_status: no_amendments_seen, pending_parse, amendments_pending,
    applied, rejected, informational, deferred
  * parse_status: succeeded / failed / pending
  * quarter_end_date NULL vs set; group size 0, 1, 2, 3
Specifically probe:
  1. A group with BOTH a competing restatement AND an `applied` amendment.
     Which rule fires in each version?
  2. A group whose only filings are amendments that are neither competing nor
     applied (e.g. a lone `deferred` restatement, or a rejected one). Old:
     originals==[] -> pool==[] -> none_eligible + demote stray. New: kind=="none".
     Does the NEW code still demote a stray active row?
  3. NT-only originals (`hr_originals` empty). Does `pool = hr_originals or
     originals` survive as kind=="originals" with the NT pool?
  4. A group where `_pool` is used in rule 3 while `originals` (still computed
     separately) is used for the tie/demote loops — can those two lists ever
     disagree about membership in a way that changes which rows get demoted or
     flagged?
  5. `is_amendment_filing` is now module-level and used by BOTH the authority and
     `competition_pool`. Confirm the authority's local `amendments`/`originals`
     split uses the same predicate as the pool it now trusts.
  6. Any path where the OLD code recomputed `competing`/`applied` AFTER mutating
     rows, and the NEW code reuses a pool captured BEFORE mutation.

Then write, or find, the test that would have caught each divergence you claim.
Run the full authority + amendment suites on valuepilot_test and report.

Output: for each divergence, `file:line`, the exact group composition, OLD
decision vs NEW decision, and the wrong product result. If you find none, state
precisely why the extraction is total (map every OLD branch to a NEW `kind`) —
a hand-wave is not an answer.
```

---

## Prompt 2 — 门禁诊断的正确性与运维语义

```
You are reviewing a PRODUCTION DEPLOY GATE's diagnostic. Its pass/fail is simple
("no filing has accepted_at IS NULL"), but it also prints `at_risk_groups`: the
(manager, period) groups whose ordering is unknowable and that will therefore be
FROZEN out of the product by the authority's missing-acceptance rule. An operator
uses that list to decide whether to proceed.

The previous version approximated the pool as "group has >=2 filings" and, on a
real 373-filing snapshot, reported 16 groups when only 2 could freeze. This PR
makes it call the authority's own `competition_pool`.

Repository: ValuePilot (local). Read:
  - backend/app/services/thirteenf_accepted_at_rollout.py (_at_risk_groups,
    verify_accepted_at_populated, run_accepted_at_backfill)
  - backend/app/services/thirteenf_filing_detail.py (competition_pool, and the
    missing-acceptance / tie branches of apply_active_filing_policy)
  - backend/scripts/t1fu_accepted_at_backfill.py (exit codes + printed guidance)
  - backend/tests/unit/test_13f_accepted_at_rollout.py

Probe, with a constructible group for each finding:
  1. UNDER-REPORT (the dangerous direction). Is there ANY group the authority
     would freeze that this diagnostic omits? Compare the gate's condition
     (`kind in ('restatement','originals') and len(pool)>=2 and any(accepted_at
     is None)`) against EVERY place the authority calls `_flag_pending` /
     returns `missing_acceptance`. Include the originals branch AND the
     restatement branch. What about a pool of >=2 where the NULL member is not
     in the top-2 by rank — does the authority still freeze?
  2. TIME-OF-CHECK vs TIME-OF-USE. The gate snapshots pool membership. Between
     the gate and the authority, a filing can finish parsing (`parse_status`
     pending -> succeeded), turning a 1-member competing pool into a 2-member
     one. Does that matter, given the gate's pass condition is a GLOBAL
     `accepted_at IS NULL == 0`? Construct the interleaving where it does.
  3. `amendment_owned` and `none` are skipped. Prove the authority never applies
     the missing-acceptance rule in those kinds. Check rule 2's `max(_pool,
     key=_active_filing_rank)` — with NULL accepted_at, `_active_filing_rank`
     falls back to `_MIN_ACCEPTED_AT` then accession_no. Is silently ranking
     admin-applied amendments by accession_no acceptable, or is that the same
     "accession is not a time proxy" bug the series removed elsewhere?
  4. Exit-code contract. `verify_accepted_at_populated` fails on ANY NULL,
     including filings with `quarter_end_date IS NULL` (which belong to no group
     and can never freeze). Is a gate that cannot pass until those are fixed the
     right call, or does it make the gate unusable on a real prod? Read the
     script's printed remediation guidance and judge whether an operator can act
     on it.
  5. Idempotence + the merge rule. `run_accepted_at_backfill` re-parses stored
     primary docs every run and `merge_accepted_at` overwrites a differing
     non-NULL value. On a second run, can a value flap?
  6. Test adequacy. Do the 4 new tests pin the SEMANTICS or just the current
     implementation? What test would fail if someone re-inlined the pool logic
     into the authority and let it drift again? Propose it.

Output: findings ranked, under-reports first (an omitted freeze is far worse than
an over-report). Reproduce on valuepilot_test where feasible.
```

---

## Prompt 3 — Runbook 与 prod 提示词的安全性(它们会被真的执行)

```
You are a staff SRE reviewing two operational artifacts that will be executed
against PRODUCTION — one by a human, one by an AI agent. Treat them as code.

Repository: ValuePilot (local), branch claude/13f-release-readiness. Read:
  - docs/runbooks/13f-data-v1-release-checklist.md
  - docs/runbooks/13f-data-v1-prod-release-agent-prompt.md
  - backend/scripts/t1fu_accepted_at_backfill.py and
    backend/scripts/t3_attribution_rollout.py (+ their service modules)
  - .github/workflows/deploy.yml, scripts/deploy_prod_from_main.sh,
    docker-compose.prod.yml
  - backend/app/services/thirteenf_admin_dashboard.py (_execute_ingest_job
    phases; run_locked_job) and thirteenf_filing_detail.apply_active_filing_policy

Audit:
  1. IS THE ORDER COMPLETE? The runbook says: deploy -> accepted_at gate exits 0
     -> only then sweeps / reparses / admin resolutions / old-quarter jobs ->
     then t3 rollout. Enumerate EVERY code path that reaches
     `apply_active_filing_policy` and check each is either (a) named in the
     runbook's prohibition, or (b) provably safe before the gate. Candidates:
     the Phase-5 sweep inside `ingest_holdings`; Phase 2.5 `apply_amendment_policy`;
     `reconcile_restatement_activation`; `reparse_accession` /
     `reprocess_amendment` / `ingest_accession` jobs; controlled reparse; batch
     reparse; admin `resolve_amendment`; the SCHEDULER's weekly quarterly
     pipeline. Does the prod prompt tell the agent to quiesce or check the
     scheduler? What happens if the scheduler fires mid-runbook?
  2. IS THE ORDER NECESSARY? The quarterly ingest job fills accepted_at in Phase
     2 before the Phase 5 sweep. So which paths are genuinely unsafe pre-gate,
     and does the runbook overstate or understate the risk?
  3. THE PROD PROMPT AS A SAFETY DOCUMENT. Read it as an adversary: can an agent
     following it literally do something destructive, skip a gate while looking
     compliant, or misread a number? Check: the Phase-1 probe's SQL (table names,
     NULL handling, behaviour on a database with ZERO 13F rows); the Phase-0
     stop conditions; the DO-NOT list (is anything dangerous missing — e.g.
     `docker compose down`, `alembic stamp`, editing rows by hand?); the branch
     decision (`filings == 0` vs `> 0`); the tag instruction; the "a truthful
     stop is a successful run" framing.
  4. THE CHECKLIST'S FACTUAL CLAIMS. Verify each against the repo, not the prose:
     "this release contains no migrations"; "deploy.yml does not listen on tags";
     "prod runs `alembic upgrade head` on container start"; the acceptance table's
     required values; the rollback section's claim that `accepted_at` is
     authoritative SEC metadata that should never be rolled back, and that
     attribution / ownership_changes / Lens are derived and re-derivable.
  5. THE ROLLBACK PLAN. There are no migrations, so rollback is a code revert.
     But the t3 rollout has already rewritten `holding_attribution_status` and
     recomputed ownership_changes + Lens under the NEW rules. Walk the actual
     revert: which rows are wrong under the OLD code, what re-derives them, and
     is there any state (e.g. `deferred` amendment_status, which older code does
     not know) that a revert leaves un-interpretable? Is `deferred` written
     anywhere yet on real data?
  6. WHAT THE REHEARSAL DID NOT COVER. The author lists: the prod host itself,
     real `.env.prod` secrets, Rate Guard prod quota, scheduler/worker
     concurrency. Is that list complete and honest? Name anything else the
     local prod-topology rehearsal could not have exercised, and say whether it
     matters.

Output: findings ranked by "could this hurt production"; an explicit verdict on
whether the deployment order is complete and necessary; and the minimal edits
you would require before an agent is allowed to run the prod prompt.
```
