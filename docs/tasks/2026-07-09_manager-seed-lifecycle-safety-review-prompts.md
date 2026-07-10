# Review prompts — M1(管理人 seeding 的生命周期安全)

Task doc: [`2026-07-09_manager-seed-lifecycle-safety.md`](./2026-07-09_manager-seed-lifecycle-safety.md)
Branch: `claude/manager-seed-lifecycle-safety`(未合并;基线 `main` = `0261373`)
读 diff:`git diff main...claude/manager-seed-lifecycle-safety`

## 这一票为什么危险

`seed_confirmed_managers` 目前只在 Day-0 手工跑一次。M1 的**唯一目的**是让它安全到
可以**每次部署自动执行**(M2)。一旦挂进部署流程,它的每一个写入语义都会变成
**周期性、静默**的事件——而它写的是**管理人宇宙**,那是 Oracle's Lens 的打分输入
(`oracles_lens/dashboard.py`,`min_holders = 3`)。宇宙静默变化 = 共识分静默变化
= 历史不可比。

本仓库最近一轮 13F 系列(PR #107–#113)反复出现同一种 bug:**自动收敛推翻人工决定**
(sweep 复活 admin-rejected 的修正案;code revert 复活 `deferred`)。M1 是同一模式在
管理人表上的体现。请以此为先验来审。

## 变更清单

| 文件 | 改动 |
|---|---|
| `services/edgar_ingestion.py` | `seed_confirmed_managers` 返回 **diff 报告**(非 `int`);既有行**不再写** `match_status`/`status`;人工决定行**整条跳过**;新增第三把匹配钥匙 `name_normalized`;新增 `_human_owns_lifecycle()` |
| `cli/edgar.py` | `seed-confirmed-managers` / `bootstrap-whitelist` 打印 diff 摘要(`_echo_seed_report`) |
| `services/thirteenf_admin_dashboard.py` | `bootstrap_whitelist` job summary 摊平 diff;保留 `managers_seeded` 向后兼容 |
| `tests/unit/test_13f_manager_seed_lifecycle.py` [NEW] | 10 条 |
| `tests/unit/test_13f_manager_taxonomy_v2.py` | 返回值契约 |

## 评审者看不到的上下文

- **生命周期字段有两个,语义不同,消费方也不同:**
  - `match_status`(legacy):`ingest_quarter_index` 用它挑摄取对象
    (`match_status == 'confirmed'`)。
  - `status`(PRD):`thirteenf_daily_sync:147`、`thirteenf_readiness:158,289`、
    `thirteenf_historical_backfill:517` 用它(`status == 'active'`)。
- **模型上有一个 ORM 事件监听器**(`models/institutions.py`
  `_populate_manager_prd_fields`,`before_insert` + `before_update`):
  `match_status ∈ {confirmed, revoked, rejected}` **且** `status ∈ {None, candidate}`
  时,派生 `status`(confirmed→active,revoked→needs_review,rejected→ignored)。
  它是 seeding 新建行能拿到 `status='active'` 的**唯一**原因,是一条隐式依赖。
- **人工决定的三个写入点:**
  - retire:`admin_dashboard.py:645` 写 `status='inactive'` + `match_status='inactive'`
  - revoke:`admin_dashboard.py:920+` **强制 note**、写审计事件
    `InstitutionManagerCikReviewEvent`、并 **`cik = None`** + `match_status='revoked'`
  - reject:`match_status='rejected'`(派生 `status='ignored'`)
- **匹配键:** `cik`(**unique 约束**)→ `dataroma_code`(仅 20/82 条种子有)→
  【本票新增】`name_normalized`(**无唯一约束**,用 `.order_by(id).first()`)。
- 种子文件:`services/seed_data/confirmed_managers.json`,82 条。

## 作者已自行发现并修复的问题(勿当新发现重报,但请验证修复是否完备)

1. **原以为的 P2 被实测证伪。** 我曾断言"新建行 `status='candidate'` 会被三个
   `status=='active'` 过滤器滤掉,Day-0 断链"。空库实跑 → `(active, confirmed) × 82`。
   原因是上面那个监听器。**留了一条特征化测试**
   (`test_new_rows_are_active_so_the_universe_is_actually_tracked`)钉住这条隐式依赖。
2. **P1 的加重情节:脑裂。** 旧代码无条件写 `match_status='confirmed'`;对
   `status='inactive'` 的行,监听器**不会**同步 status(因为 status 不在
   `{None, candidate}`)→ 得到 `match_status=confirmed` + `status=inactive`:被摄取进
   产品面与 Lens 共识,却不在 expected-filers 分母里。
3. **P3(写本提示词时实测发现):`revoked` 有两条被推翻的路径。**
   revoked 派生 `status='needs_review'`,**不在** `{inactive, ignored}` 里,故第一版
   跳过谓词漏了它。实测:
   - 有 `dataroma_code` → 按 code 命中 → `existing.cik = cik` **把撤销的 CIK 重新挂回**;
   - 无 `dataroma_code` → 两把钥匙都失效 → **新建重复的 `confirmed` 行**(82→83),
     被摄取,撤销彻底失效。
   修复 = 扩谓词(`_human_owns_lifecycle`)+ 加第三把钥匙(`name_normalized`)。
   **两者缺一不可**:只扩谓词挡不住重复行,只加钥匙挡不住 CIK 回挂。

## 刻意决策(judge,勿当 bug 重报)

1. **PO 裁定:seed 表达"意图",人工表达"生命周期",人工赢。** seed 永不写
   `match_status`/`status`;永不停用任何人。
2. **副作用(刻意暴露):** 一个**已存在但未 confirmed** 的管理人(如 dataroma
   加入的 candidate)被加进 seed 文件后,**不再被自动提升**,必须人工确认。为避免
   "加进 JSON 却什么都没发生"的静默失败,他们进 `awaiting_confirmation` 桶并被列出。
3. 人工决定行**整条跳过**,连身份字段都不刷新(而非"只跳过生命周期字段")。
4. `updated` 计数**包含** `awaiting_confirmation` 的行(后者是前者的子集);
   admin job 的 `managers_seeded = created + updated` 保留旧语义。
5. `name_normalized` 无唯一约束,故用 `.order_by(id).first()` 而非 `.one_or_none()`。

## 测试基础设施

dev 库 `valuepilot` 有真实数据,pytest **必须**跑隔离库:
```
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q     # 1174 passed 为基线
```
dev 真实数据现状:82 位管理人,全部 `(status=active, match_status=confirmed)`;
`revoked` / `inactive` 行数为 0(即上述缺陷在 dev 上**尚未爆发**)。

三个提示词并行;结果写入
`2026-07-09_manager-seed-lifecycle-safety-review-results.md`。每条 finding 给
`file:line` + 可构造的行状态 + 错误的产品结果;能在 `valuepilot_test` 复现的先复现
(**rollback-only**,勿污染)。

---

## Prompt 1 — 生命周期不变量的穷举(关键角度,对抗式)

```
You are reviewing a function that is about to run on EVERY production deploy and
that writes the manager universe — which is a scoring input (Oracle's Lens
requires min_holders=3 for consensus, so a silently changed universe silently
changes historical scores).

Its contract is: "the seed expresses INTENT; a human expresses LIFECYCLE; the
human wins; seeding never deactivates anyone." Your job is to break that
contract. Assume it is broken until you cannot break it.

Repository: ValuePilot (local). Read with
`git diff main...claude/manager-seed-lifecycle-safety`.
Read first:
  - backend/app/services/edgar_ingestion.py — seed_confirmed_managers,
    _human_owns_lifecycle, _DEACTIVATED_MANAGER_STATUSES,
    _HUMAN_DECIDED_MATCH_STATUSES, _normalize_name, and the three-key lookup.
  - backend/app/models/institutions.py — MANAGER_STATUSES, the `status` /
    `match_status` columns, and the `_populate_manager_prd_fields` ORM listener
    (before_insert + before_update).
  - backend/app/services/thirteenf_admin_dashboard.py — the human writers:
    retire (:645), revoke_confirmed_cik (:920+), reject, confirm (:837), and
    resolve/candidate flows.
  - The "Context" section of this doc.

Enumerate systematically — do not spot-check. Cross these axes for an EXISTING
row and ask "after a re-seed, did an automated system overwrite a human?":
  * match_status ∈ {seeded, candidate, confirmed, revoked, rejected, inactive,
    needs_review, and anything else any writer can produce — grep for every
    assignment}
  * status ∈ MANAGER_STATUSES
  * cik: present / NULL (revoke NULLs it)
  * dataroma_code: present / NULL (only 20 of 82 seed entries have one)
  * name_normalized: matches the seed entry / differs (a human renamed the row)

Probe specifically:
  1. Is `_human_owns_lifecycle` COMPLETE? Grep every assignment to
     `match_status` and `status` in the codebase. Is there a state a human can
     produce that the predicate does not recognise — e.g. `needs_review` set
     directly, or a `revoked` row whose derived status was later edited? For
     each, say what a re-seed does to it.
  2. The CREATE path is the one that bypassed every guard before (a revoked
     manager with no dataroma_code got a duplicate `confirmed` row). Are there
     OTHER row states where all three lookup keys miss and a duplicate is
     created? Consider: a human renamed the manager (name_normalized differs);
     two seed entries normalizing to the same name; a row whose cik was set to a
     DIFFERENT cik by match-cik. `cik` is UNIQUE — can the create path now raise
     IntegrityError instead of duplicating? Which is worse, and is it handled?
  3. `name_normalized` has NO unique constraint and the fallback takes
     `.order_by(id).first()`. Construct the case where it matches the WRONG
     manager and the seed then writes that manager's identity/classification (or
     attaches a CIK that belongs to someone else). How likely is it given
     `_normalize_name` strips 'capital', 'management', 'partners', 'fund', …?
     Test two real seed entries for a normalized-name collision.
  4. The ORM listener fires on before_UPDATE too. Seeding writes identity fields
     on a live row → before_update runs → can it change `status` as a side
     effect for any reachable (match_status, status) pair? Enumerate.
  5. Idempotence under mutation: run seed, mutate a row into each state above,
     run seed again, run it a THIRD time. Does anything oscillate or accumulate?
  6. `awaiting_confirmation` rows still get identity/classification refreshed
     while a human's confirmation is pending. Can that refresh contradict what
     the human is about to decide (e.g. overwrite a name an admin corrected)?

Output: for each break, `file:line`, the exact row state, what the re-seed did,
and the wrong product consequence (ingested? scored? invisible? duplicated?).
Reproduce on valuepilot_test with a rolled-back session. If you cannot break it,
prove completeness: map every reachable (match_status, status, cik,
dataroma_code) tuple to a seed outcome.
```

---

## Prompt 2 — 部署时执行的安全性(M1 存在的全部理由)

```
You are a staff SRE. M1 exists to make `seed_confirmed_managers` safe to run on
EVERY deploy (that is M2, not yet built). Judge whether it actually is. A "yes"
here authorises an automated writer against the manager universe, which is an
input to Oracle's Lens consensus scoring.

Repository: ValuePilot (local), branch claude/manager-seed-lifecycle-safety.
Read: edgar_ingestion.seed_confirmed_managers; cli/edgar.py `_echo_seed_report`;
thirteenf_admin_dashboard `bootstrap_whitelist` job branch;
.github/workflows/deploy.yml + scripts/deploy_prod_from_main.sh;
docker-compose.prod.yml (api command); backend/app/main.py (startup hooks:
scheduler, 13F job worker, THIRTEENF_START_QUARTER reconcile).

Audit:
  1. CONCURRENCY. `institution_managers.cik` is UNIQUE. Prod may start more than
     one api container, and the deploy recreates containers. If seeding runs at
     startup (M2's likely shape), two processes can seed simultaneously. Trace
     the create path: does it raise IntegrityError? Is it caught? Does it abort
     app startup? Compare with how the 13F authority solved the same class of
     problem (pg_advisory_xact_lock in
     thirteenf_filing_detail._acquire_period_lock) and with `run_locked_job` /
     JobRun lock_keys. What is the minimum M1 must add before M2 is allowed?
  2. TRANSACTION BOUNDARY. The CLI commits; the admin job returns and lets the
     job runner commit. A deploy-time caller has neither. Where should the
     commit live, and what happens if the seed partially applies and then the
     process dies? Is the function safe to re-run after a partial apply?
  3. FAILURE MODE. `derive_legacy_manager_type` raises ValueError on a bad
     `style_primary` — deliberately, to fail loud on a JSON typo. In a
     deploy-time hook, does that abort the deploy, abort startup, or get
     swallowed? Which do you want? (main.py already wraps the start-quarter
     reconcile in try/except so it "never blocks API startup" — is that the
     right precedent here, or is a bad seed file something that SHOULD stop a
     deploy?)
  4. OBSERVABILITY. The diff report is printed by the CLI and returned by the
     job. In a deploy-time hook nobody reads stdout. Where must
     `skipped_human_decided` and `awaiting_confirmation` surface so an operator
     actually sees them (Discord via thirteenf_alerts? job summary? health
     endpoint?)? What is the failure mode if they surface nowhere — argue it
     concretely with the awaiting_confirmation semantics (a curator adds a
     manager to the JSON and nothing happens).
  5. BLAST RADIUS. If a re-seed DID change the universe (added a manager), what
     downstream artefacts are now stale — ownership_changes? Lens signals?
     readiness? Is any recompute triggered, or does the universe silently
     disagree with the scores computed under the old universe?

Output: an explicit verdict — "M1 is / is not sufficient for M2", with the
concrete list of what must be added first, in priority order.
```

---

## Prompt 3 — 契约变更的下游影响与测试充分性

```
You are reviewing a return-type change and a behaviour change on a function with
several callers, plus the tests that pin it.

Repository: ValuePilot (local), branch claude/manager-seed-lifecycle-safety.
Read: edgar_ingestion.seed_confirmed_managers (return contract);
every caller (`grep -rn seed_confirmed_managers backend/`);
backend/tests/unit/test_13f_manager_seed_lifecycle.py (10 tests);
test_13f_manager_taxonomy_v2.py; test_13f_dataroma_sync.py;
README.md's Day-0 sequence.

Audit:
  1. CALLERS. `seed_confirmed_managers` returned `int` and now returns a dict.
     Find every caller (production, CLI, jobs, tests, docs, scripts) and confirm
     each was updated. Check the admin job's `managers_seeded = created +
     updated` — does any UI/quality consumer read that key, and does its meaning
     survive (it used to count every touched row; `awaiting_confirmation` rows
     are counted inside `updated` — is that double-counting or correct)?
  2. BEHAVIOUR CHANGE, DAY-0. Seeding no longer promotes an existing
     non-confirmed row. Walk the README's Day-0 order
     (seed-confirmed-managers → match-cik → backfill …) on a FRESH database and
     on a PARTIALLY bootstrapped one (e.g. `sync-dataroma` added candidates
     first, or `match-cik` ran before the seed). In which orders does a manager
     end up in the seed file yet never ingested? Is the README's order still
     correct, and does anything tell the operator to go confirm the
     `awaiting_confirmation` rows?
  3. TEST ADEQUACY. The 10 new tests pin: report shape, new rows active, no
     resurrection, no promotion, no lifecycle overwrite, identity refresh,
     no auto-deactivation, idempotence, no revoked-CIK re-attach, no duplicate
     for a revoked manager without dataroma_code. What is NOT pinned? Consider:
     the `rejected` status; a row whose name was renamed; a create-path
     IntegrityError; the ORM listener being deleted (is the characterization
     test enough — would it fail, and with a comprehensible message?); the
     `_echo_seed_report` output itself. Name the 3 highest-value missing tests
     with sketches.
  4. NAMING / SEMANTICS. The bucket was renamed `skipped_deactivated` →
     `skipped_human_decided` because `revoked` is not "deactivated". Is
     `awaiting_confirmation` the right name for "exists, not confirmed, not
     human-decided"? Does it wrongly include rows in `needs_review` (a human
     parked them) — should those be a third bucket? Check
     `test_reseed_never_overwrites_lifecycle_of_a_live_manager`, which puts a row
     in `needs_review` and expects it untouched — is it reported anywhere?
  5. DOCS. Does the task doc's claim set match the code (esp. the "P2 证伪" and
     P3 sections)? Does README's Day-0 or the admin Managers page need a note
     about `awaiting_confirmation`?

Output: findings ranked; the 3 missing tests; and an explicit answer on whether
`needs_review` rows are correctly classified today.
```
