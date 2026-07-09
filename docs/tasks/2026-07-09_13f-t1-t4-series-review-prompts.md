# Review prompts — T1–T4 稳定化系列完整评审(含 T1-FU)

真实数据摄取暴露的 6 缺陷修复系列**整体**评审:5 个已合并 PR 作为一个系统看,
找**跨票交互缺陷、组合语义漏洞、部署断档**——单票评审(每票 1–5 轮,全部 resolved)
已覆盖票内正确性,本轮不重复票内逐行审查。

**Scope(全部已合并,基线 `a786cfb` → tip `47bf92a` = 当前 main):**

| PR | 票 | 一句话 |
|---|---|---|
| #107 | T1 | 同季多 RESTATEMENT 激活崩溃修复(demote→flush→activate + 确定性胜者) |
| #108 | T2 | `compute_ownership_changes` 接入 quarterly_pipeline + 计算按 security 聚合去重 |
| #109 | T3 | 组合/共享裁量归因:SOLE/DFND/OTR 一律 `direct`(巴菲特等 7 旗舰可见)+ SHARED_DISCRETION caveat 全表面 |
| #110 | T4 | CLI `backfill`/`ingest-holdings`/`reparse-*` 委托 ParseRun-backed job 路径 + `run_locked_job`(JobRun 锁) |
| #111 | T1-FU | 单一 active-filing 权威 + accepted_at 填充(ET→UTC)+ tie/缺证据规则 + (manager, period) advisory 锁 + admin 生命周期 |

**Read first(按此顺序):**
- `docs/tasks/2026-07-08_13f-real-data-findings-po-plan.md` — 系列源头(6 缺陷 + PO 归因裁定 §2)
- 各票 task doc + `*-review-results.md`(T3 五轮、T1-FU 四轮处置全在内)
- 代码入口:`thirteenf_filing_detail.apply_active_filing_policy`、
  `thirteenf_admin_dashboard._execute_ingest_job`(Phase 1→2→2.5→3→4→5 sweep)+
  `run_locked_job`、`thirteenf_ownership_changes.compute_manager_ownership_changes`、
  `thirteenf_holdings_ingest._compute_attribution_status`、
  `thirteenf_holdings_query`(HR/NT_FORM_TYPES + `active_hr_holdings_query`)

**评审基础设施:**
```
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api alembic upgrade head
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q     # 1151 passed 为基线
```
dev 库 `valuepilot` 持真实数据(只读核验用,勿 truncate):373 filings / 355
(manager, qend) 组 / 354 active / 0 dup / 25,070 holdings 全 ParseRun-backed /
accepted_at 373/373 已填(ET→UTC 已重写)/ 0 sort_warnings。旗舰事实(T3 验收):
Berkshire 543 direct holdings、62 变动、268 Lens 组件;7 旗舰全可见。

**刻意决策清单(judge,勿当"发现"重报;出处在各票处置):**
1. 归因:`SOLE/DFND/OTR` 一律 `direct`,与 Column 7 无关;排除语义仅留 13F-NT
   (PO 裁定 §2,评审修订版)。
2. admin apply 可被更高排名的 parsed restatement 压过——既定流程 = 先 reject 不要的。
3. `deferred` 不进 pending 队列/health 计数(defer = 搁置且不阻塞)。
4. `merge_accepted_at` 同源重解析可覆盖非 NULL(ET 修正传播所需;单一来源)。
5. tie/缺证据时 kept-active 若为 terminal(applied)只加 warning 不降级 status
   (不推翻 admin;该窄缝 Lens 只见 warning 不排除)。
6. Phase-4c/5 → sweep 后 `filings_activated`/`restatements_applied` 计数基准
   per-filing → per-group(无现存消费方)。
7. NT/A 摄取白名单不含(`INGESTION_FORMS`/`_DAILY_13F_FORM_TYPES`)——一等摄取
   支持在 BACKLOG;已入库/admin-applied 的 NT/A 行为已全消费方一致。

**BACKLOG 现存(deferral 诚实性的审计对象):** NT/A 一等摄取(低)、backfill 按
failed-parse 重试(低)、跨申报人双计 review 护栏(T3)、positions 读模型(T2)、
Rate Guard 可观测性 ×2(pre-existing)。

三个提示词并行;结果写入 `2026-07-09_13f-t1-t4-series-review-results.md`。每条
finding:`file:line` + 跨票交互时序/组合场景 + 错误产品结果;能在 `valuepilot_test`
复现的先复现,dev 只读核验。

---

## Prompt 1 — 跨票集成与管线组合正确性(关键角度)

```
You are reviewing the COMPOSITION of five merged changes to a 13F pipeline, not
any single one. Each passed its own multi-round review; your job is the seams.
Repository: ValuePilot (local), current main. Series diff:
`git diff a786cfb..47bf92a`. Read the header doc's entry points first.

Hunt cross-ticket interaction bugs, each with a concrete timeline:
 1. LOCK LAYERING (T4 × T1-FU). Two locking layers now exist: JobRun lock_keys
    (run_locked_job / _execute_pipeline_stage_job — per job, e.g.
    ingest_holdings:{quarter}, reparse_accession:{acc}) and
    pg_advisory_xact_lock per (manager, period) inside
    apply_active_filing_policy. Map every path that holds BOTH (quarter job →
    sweep per-group; reparse job → _do_ingest_holdings → reconcile → period
    lock; admin resolve → period lock, NO JobRun lock; CLI via run_locked_job).
    Construct any deadlock/starvation interleaving across layers (job A holds
    JobRun lock X + waits period lock P; job B holds P + waits X?). Verify
    every multi-period path acquires period locks in sorted order — INCLUDING
    Phase 3's per-filing reconcile calls (filed_at order, NOT sorted by
    (manager, qend)!) vs the Phase 5 sweep and a concurrent quarter job.
 2. ACTIVATION × CHANGES (T1-FU × T2). compute_ownership_changes reads active
    filings per (manager, quarter). T1-FU can now leave a period with NO
    active filing (original tie, none_eligible, missing-acceptance freeze with
    nothing active). Trace T2's compute + the pipeline stage for that state:
    correct unavailable reason, no crash, no stale rows left from a previous
    compute? Same for a period whose active filing carries the new
    amendments_pending flag.
 3. ACTIVATION × ATTRIBUTION × LENS (T1-FU × T3). Oracle's Lens excludes
    amendments_pending holders (MVP5-02) — T1-FU's tie/missing flags now
    TRIGGER that machinery. On real dev data: 0 warnings today, but construct
    the synthetic case and verify the score-side aggregate + caution panel
    behave (holder excluded, caveat surfaces, min_holders eligibility not
    corrupted). Then the reverse seam: T3 made DFND/OTR holdings `direct` —
    does any T1-FU state (deferred restatement active? applied NT/A owner)
    leak non-HR or non-direct rows into consensus?
 4. PIPELINE ORDERING GUARANTEE. The missing-acceptance rule only stays quiet
    because Phase 2 (backfill_period_routing → fills accepted_at) runs BEFORE
    Phase 5's sweep in the same job. Audit EVERY path that reaches
    apply_active_filing_policy WITHOUT a prior routing pass in the same
    transaction scope (admin resolve, controlled reparse, reparse_accession
    job, T3's rollout script backend/scripts/t3_attribution_rollout.py,
    quarterly_pipeline stage order): on a database where accepted_at is still
    NULL (prod before its first post-deploy ingest run), which of these paths
    would flag/freeze groups that the very next quarter job would then heal?
    Is that transient noise acceptable, or does prod need an explicit
    accepted_at backfill step BEFORE any sweep-bearing path runs (a T1-FU
    runbook analogous to T3's)? State the deployment order you would require.
 5. CLI × PIPELINE (T4 × T1-FU). backfill's quarter-scoped ingest jobs run the
    full Phase 1-5 including the sweep. Two overlapping quarters in one
    backfill (report Q ∪ next(Q)) → the same (manager, period) group swept
    twice in two jobs — idempotent under the JobRun+period locks? And
    reparse-all looping reparse_accession jobs while a scheduled quarter job
    runs: any window where a filing's ParseRun swap (is_current) and its
    activation flip are observed OUT of sync by active_hr_holdings_query
    (which joins BOTH)?
 6. End-to-end REAL-DATA replay (read-only dev): pick Berkshire 2025-Q4 and
    manager 3988 (the 3 accession-vs-time inversion groups): walk filings →
    attribution → active filing → holdings visibility → ownership_changes →
    Lens components and confirm every layer agrees. Report any layer whose
    numbers disagree with the header doc's flagship facts.

Output: findings ranked (interleaving/timeline + wrong product result), plus
an explicit verdict on 4 (prod deployment ordering). Empty list only if every
seam above is argued sound.
```

---

## Prompt 2 — 13F 领域语义与 PO 验收(整体产品视角)

```
You are a 13F domain expert + PO doing FINAL acceptance of a five-PR series
that made real EDGAR data product-ready. Judge the COMBINED rule system
against SEC semantics and the PO plan's acceptance criteria — not individual
diffs. Repository: ValuePilot (local), current main.
Read: docs/tasks/2026-07-08_13f-real-data-findings-po-plan.md (esp. §2 ruling
+ §2.4 acceptance), each ticket's task doc, then the code entry points in the
header doc. SEC refs: Form 13F FAQ; EDGAR accession/acceptance semantics.

Judge, with concrete filings/timelines:
 1. THE COMBINED AMENDMENT LIFECYCLE. Write out the full state machine now
    implemented (statuses: no_amendments_seen, pending_parse,
    amendments_pending, applied, rejected, informational, deferred ×
    is_active × parse_status × form family). Find any state pair that is
    reachable but semantically contradictory for a user (e.g. an inactive
    'applied' restatement next to an active 'applied' NEW_HOLDINGS after a
    reject-then-apply sequence; a deferred restatement whose original shows
    no_amendments_seen — should the period carry a visible "deferred
    amendment exists" signal?). Is the admin mental model teachable in one
    paragraph? If not, what single simplification would you demand?
 2. ATTRIBUTION RULING under the new activation rules. The §2 ruling (all
    SOLE/DFND/OTR → direct) was accepted per-filing; T1-FU decides WHICH
    filing. Combined: a combination-report RESTATEMENT superseding a
    holdings_report original — do included-manager holdings, SHARED_DISCRETION
    caveats, and double-count protections survive the switch? Check the
    cross-filer double-count deferral (BACKLOG) is still not triggerable in
    the 82-manager universe AFTER T1-FU's activation changes.
 3. PO ACCEPTANCE RE-VERIFICATION (read-only dev): §2.4 criteria — Buffett
    changes non-empty via the changes API, 7 flagships have Lens components +
    manager-page holdings/changes, combination caveat wording honest, no
    double count (Berkshire counts as ONE holder per stock). Re-verify each
    and report actual numbers vs the header doc's claims. Any regression
    since T3's sign-off (T4/T1-FU landed after) is a finding.
 4. HONESTY OF DEGRADED STATES end to end. unavailable_reasons (T2), NT
    notice semantics (NT/A now family-wide), missing-acceptance freezes,
    restatement-tie freezes: for each, what does the END USER see on the
    manager page / stock page / Lens caution panel, and is it truthful about
    WHY data is absent (per the "unknown is not zero" doctrine)? Flag any
    surface that renders a frozen/disputed period as merely empty.
 5. Judge the seven deliberate-decision list items in the header doc — accept
    or challenge each as a PRODUCT position, with the operator story that
    would break it.

Output: PO verdict per §2.4 criterion (pass/fail + numbers), findings ranked,
and an explicit accept/challenge on each deliberate decision.
```

---

## Prompt 3 — 工程卫生、测试充分性与运维就绪(系列级)

```
You are a staff engineer auditing a five-PR series for engineering hygiene:
test adequacy, deferral honesty, docs-vs-code accuracy, and ops readiness.
Repository: ValuePilot (local), current main. Series diff
`git diff a786cfb..47bf92a`; docs under docs/tasks/2026-07-08_* and
2026-07-09_*; backlog docs/BACKLOG.md.

Audit:
 1. TEST PYRAMID ACROSS THE SERIES. ~90 new tests landed (authority 35, CLI
    17, amendment policy, ownership changes, attribution, rollout). Map them
    against the failure modes the series actually fixed: which fixes are
    pinned ONLY at unit level with no composition coverage (e.g. is there any
    test running quarterly_pipeline END TO END — quality_check +
    compute_ownership_changes + Lens scoring — on a multi-manager fixture?
    T4's job-level tests + T1-FU's ingest-job composition tests cover ingest;
    what covers the pipeline ABOVE it?). Name the 3 highest-value missing
    tests, with sketches.
 2. GUARD COVERAGE. Two source guards exist (CLI never calls legacy ingest;
    is_active writes only in the authority module). What third guard would
    pay for itself (e.g. amendment_status writers whitelist? NT form
    string-literal guard now that NT_FORM_TYPES exists? active_hr_holdings_
    query bypass detection — services querying Holding13F directly)?
    Check TODAY for violations of each candidate before proposing it.
 3. DEFERRAL HONESTY. Cross-check every review round's findings (all
    *-review-results.md) against code + BACKLOG: is anything marked
    fixed that is only partially fixed, or deferred WITHOUT a backlog entry?
    Conversely, any backlog entry actually resolved by a later ticket but
    still listed open? The BACKLOG discipline says entries clear in the PR
    that resolves them.
 4. DOCS-VS-CODE DRIFT. The five task docs + PO plan contain specific claims
    (counts, function names, rule statements — e.g. the PO plan §2 table,
    T1-FU's design-decision section). Spot-check ~15 claims against merged
    code; stale docs that survived multiple reworks are likely. Also
    AGENTS.md / docs/architecture/*: does any architecture doc now contradict
    the authority/locking reality and need a pointer update?
 5. OPS READINESS. T3 shipped a prod rollout runbook + verification script
    (backend/scripts/t3_attribution_rollout.py, run_attribution_rollout).
    T4/T1-FU shipped none. Decide what prod actually needs on deploy of this
    series, in order: migrations? none exist — verify. accepted_at backfill
    before first sweep (see Prompt 1 item 4)? re-run of T3 rollout? Lens/
    changes recompute? Write the minimal ordered prod deployment checklist,
    or state explicitly that plain deploy + next scheduled quarter job
    converges everything (and prove the ordering that makes it safe).
 6. OBSERVABILITY. After this series, when the authority freezes a group
    (tie/missing-acceptance) or the sweep changes an active filing on prod,
    HOW does an operator find out — job summary keys, health counts,
    sort_warning queues? Trace one freeze event to its operator-visible
    surface; if it dies in a log line, propose the minimal surfacing.

Output: findings ranked; the 3 missing tests; the prod deployment checklist
(or the proven "plain deploy converges" argument); explicit answers per item.
```
