# Review prompts — PR #116(种子 CIK 修正 + 自动管线丢失 filing 总额)

Task doc: [`2026-07-10_13f-seed-cik-audit.md`](./2026-07-10_13f-seed-cik-audit.md)
PR: https://github.com/d41689/ValuePilot/pull/116
Branch: `claude/13f-seed-cik-audit`(未合并;基线 `main`)
读 diff:`git diff main...claude/13f-seed-cik-audit`
按发现顺序读提交:`git log --oneline main..HEAD --reverse`

## 这一票为什么危险

这个 PR 修的是**数据正确性**,不是崩溃。两个缺陷都曾经**静默**:所有 job 全绿、行数对得上、
`quality_check` 报 `passed`,而产品面上的 Oracle's Lens 分数是错的。评审的核心任务是判断
**修复是否真的让它们不再静默**,以及**修复本身有没有引入新的静默错误**。

作者的所有验证都在一个**独立沙箱**(`valuepilot_prodsim`,与 dev/test/prod 完全隔离,现已停机)
里做。请把作者报告的每个数字当作**待验证的主张**。

## 变更清单

| 文件 | 改动 |
|---|---|
| `seed_data/confirmed_managers.json` | 11 个 manager 的 `cik`(+`legal_name`),新增 `cik_source` 字段 |
| `services/thirteenf_filing_detail.py` | `apply_primary_doc_metadata` 现在写 `reported_total_value_thousands` / `holdings_count` |
| `services/thirteenf_holdings_ingest.py` | `_do_ingest_holdings` 现在写 `computed_total_value_thousands` / `common_holdings_count` |
| `services/edgar_quality.py` | `_check_reconciliation`:零份比较不再报 "passed";有 holdings 无总额的 filing 告警 |
| `tests/unit/test_13f_filing_totals.py` [NEW] | 4 条 |
| `tests/unit/test_13f_manager_seed_startup.py` | +2 条离线守卫(CIK 形状、名字唯一) |

**关于 JSON 那 520 行 diff:** 作者已核对——**71 条逐字节未变,11 条只改 `cik`(+`legal_name`),
0 条动了其它字段**。行数多是因为 `json.dumps` 重排了全文。评审可用下方脚本自行复核,不必逐行读。

## 评审者看不到的上下文

- **`ingest_quarter_index` 用 confirmed manager 的 CIK 做白名单**匹配 `form.idx`。CIK 错 → 永远匹配不到 → 该 manager 静默缺席。
- **`match_cik_candidates()` 只扫 `cik IS NULL AND match_status IN ('seeded','candidate')`**,所以一个 CIK 错、状态 `confirmed` 的行**永远不会被重新校验**。
- **`compute_portfolio_weight`**(`oracles_lens/base_primitives.py`)的分母是
  `filing.computed_total_value_thousands or filing.reported_total_value_thousands`;两者皆 NULL → 返回 `None` → 该 holding 无权重。
- **Distinctiveness 与 conviction 的 position-importance 分量都依赖 portfolio weight。** 权重全 NULL → distinctiveness 恒 0、position-importance 被削顶。
- **`compute_portfolio_weight` 的尺度无关性**:权重是同一 manager 内 `value / filing_total` 的比值。所以"千美元 vs 美元"的单位错**不影响** Lens,但影响所有绝对金额展示(见下方 BACKLOG 条目)。
- **两条摄取路径**:legacy `ingest_filing_holdings`(手工/CLI,写全部 filing 总额)vs 现代 ParseRun-backed `ingest_holdings`(pipeline 用,T4 让 CLI 也用它)。本 PR 修的是现代路径缺字段。
- **`apply_primary_doc_metadata` 的 docstring** 里记着**同一个 bug 的上一次**(`accepted_at`,T1-FU):"the bulk-ingest path parsed the primary doc but never wrote it"。这是第三次。
- **`_do_ingest_holdings` 有 reparse 语义**:新 ParseRun 变 current,旧 run 的 holdings 保留。写 `computed_total_value_thousands` 时用的是**本次 run 的** holdings 列表。

## 作者已自行发现并明确不修的(judge,勿当新发现重报)

1. **本 seed 修复救不了已有的库。** seed 按 cik→dataroma_code 查找;CIK 一改,11 个里 10 个两把钥匙都找不到 → 走创建路径。名字仍冲突的会安全拒绝;Icahn 和 Greenlight 的 `legal_name` 也变了 → 会创建**重复的 confirmed manager 行**。空库无碍。→ BACKLOG,需要带审计事件的"改指向"。
2. **六个 manager(含 Baupost/Klarman)按千美元申报 dollars schema** → 绝对金额小 1000 倍。对账检查结构上抓不到(申报人自报总额同样错单位)。Lens 不受影响。→ BACKLOG。
3. **下游重算**(11 个 manager 加入 = 宇宙变化,`min_holders=3`)→ 属于那张票,不在本 PR。

## 测试基础设施

**dev 库 `valuepilot` 有真实 13F 数据,pytest 必须跑隔离库:**

```bash
TEST_URL="postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test"
docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q \
  tests/unit/test_13f_filing_totals.py \
  tests/unit/test_13f_manager_seed_startup.py \
  tests/unit/test_13f_filing_detail.py \
  tests/unit/test_13f_mvp4_quality_rule_codes.py
```

全量收口:`docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q`(作者报告 **1220 passed**)。

**核对 JSON 无污染**(只读,无网络):

```bash
docker compose exec -T api python - <<'PY'
import json, subprocess
old = json.loads(subprocess.run(["git","show","main:backend/app/services/seed_data/confirmed_managers.json"],
                                capture_output=True,text=True).stdout)
new = json.load(open("app/services/seed_data/confirmed_managers.json"))
oldby={e["display_name"]:e for e in old}; newby={e["display_name"]:e for e in new}
changed=[]
for dn in oldby:
    o={k:v for k,v in oldby[dn].items()}; n={k:v for k,v in newby[dn].items() if k!="cik_source"}
    if o!=n: changed.append((dn,[k for k in set(o)|set(n) if o.get(k)!=n.get(k)]))
print("entries:",len(old),len(new)); print("changed:",len(changed))
for dn,d in changed: print("  ",dn,d)   # every d must be ['cik'] or ['cik','legal_name']
PY
```

---

## Prompt 1 — CIK 修正的正确性与完备性(关键角度,对抗式)

> 你在评审 ValuePilot PR #116,分支 `claude/13f-seed-cik-audit`。只看 **seed 修正**
> (`confirmed_managers.json` + 提交 `3fb0680`)。
>
> 作者把 11 个 manager 的 CIK 改指向了新实体,声称每个新 CIK 都在 EDGAR 上作为 13F-HR 申报人、
> 且最近一次在 2026-05。**你的任务:独立验证,并找出错的或没修全的。**
>
> 你可以走 Rate Guard 查 EDGAR submissions:
> `from app.edgar.parsers.submissions import submissions_url, parse_submissions`,
> `parse_submissions(EdgarClient().get(submissions_url(cik)))` → `(info, filings)`;
> `info.name` 是实体名,`filings` 里 `form_type` 以 `13F-HR` 开头的是持仓申报。
>
> 逐条核:
> 1. **每个新 CIK 的 `info.name` 是否与该 manager 是同一机构?** 尤其 Icahn
>    (`0000921669` → EDGAR 名 "ICAHN CARL C",是个人不是机构)、Greenlight
>    (`0001489933` → "DME Capital Management, LP",名字完全不同)。DME 真的是 Einhorn 的申报主体吗?
> 2. **有没有更好的候选?** Aquamarine 有两个(Zurich AG vs Cayman Ltd),Fundsmith 有两个
>    (LLP vs Investment Services Ltd),Bridgewater 有两个(Associates LP vs Advisors Inc)。
>    作者选的那个,是不是持仓量/申报频率最像"这个知名 manager"的?用 13F-HR 数量和最近日期佐证。
> 3. **`legal_name` 改成了 EDGAR 实体名**——这对下游有没有副作用?`_normalize_name(legal_name)`
>    进 `name_normalized`,它是 seed 创建路径的**拒绝键**。11 个新名字的规范化结果两两不同吗?
>    和其余 71 个冲突吗?(作者说不冲突——复核。)
> 4. **Michael Burry / Scion(`0001649339`)在沙箱里零 filing。** 作者说他 CIK 正确、只是
>    2025-11-03 后停报。查 EDGAR 证实或推翻。如果他其实换了申报主体,那就是**第 12 个**没修的。
> 5. **有没有别的 manager 也该被这个审计抓到但没抓到?** 作者的判据是"沙箱两个季度里有没有 filing"。
>    一个最近才停报的 manager,在 2025-Q4/2026-Q1 里仍有 filing,却可能在未来静默消失。对全部 82 个
>    CIK 跑一遍 submissions,报告任何"最近一次 13F-HR 在 2025-08 之前"的。
>
> 对每条给出 CIK、EDGAR 实体名、13F-HR 数量、最近日期。**能查证就查证,查不到就标注"未查证"。**
> 结论:11 个修正里,哪些确凿、哪些存疑、有没有第 12 个漏网的?

## Prompt 2 — filing 总额修复:正确性、merge 语义、reparse(关键角度)

> 你在评审 ValuePilot PR #116。只看 **filing 总额修复**(提交 `f71798d`):
> `apply_primary_doc_metadata` 写 `reported_total_value_thousands`/`holdings_count`,
> `_do_ingest_holdings` 写 `computed_total_value_thousands`/`common_holdings_count`,
> `_check_reconciliation` 不再对零份比较报 "passed"。
>
> **你的任务:证明其中一个写入在某种真实序列下是错的。** 至少查:
>
> 1. **merge 语义。** 作者对 `reported_total_value_thousands` 用"非 NULL 才写"(merge,不 NULL 抹除),
>    理由同 `accepted_at`。但 `computed_total_value_thousands` 在 `_do_ingest_holdings` 里是**无条件**
>    `filing.computed = sum(this run's holdings)`。**reparse 一个 filing** 时:新 run 的 holdings 求和
>    覆盖旧值——对吗?如果新 run 因某种原因 holdings 更少(部分解析),旧的正确总额会不会被一个更小的错值覆盖?
> 2. **`common_holdings_count = sum(put_call is None)`。** 这和 `holdings_count`(= 主文档的
>    `tableEntryTotal`,含期权)语义不同。有没有别处读 `common_holdings_count` 并假设它等于持仓总数?
>    Grep 消费方。
> 3. **`computed` vs `reported` 的单位。** 两者都应是"千美元"。`_do_ingest_holdings` 求和的是
>    `h.value_thousands`。确认它确实是千美元、而不是绝对美元——否则对账会对同一份 filing 报出 1000x 偏差。
>    (提示:看沙箱里 Berkshire 的 `value_thousands` 和 `reported_total_value_thousands` 是否同量级。)
> 4. **reconciliation 的新告警会不会误报?** 新增分支:`coalesce(computed,reported) IS NULL AND EXISTS(holdings)`
>    → 告警。一个**零持仓的合法 13F-HR**(作者说沙箱里就有一份 `0001540866-26-000002`)会不会命中?
>    它没有 holdings,所以 `EXISTS` 为假——确认。那**期权-only** 的 filing 呢(有 holdings 但 `tableValueTotal`
>    可能为 0)?会不会 `reported=0` 被当成"有总额"从而漏报,或 `NULL` 被当成"无总额"从而误报?
> 5. **事务边界。** `_do_ingest_holdings` 在一个 savepoint 里跑,`apply_primary_doc_metadata` 在 Phase 2.5。
>    两个写入在不同 Phase、不同 commit barrier。一次 pipeline 内,`reported`(Phase 2.5)先写、`computed`
>    (Phase 3)后写——中间崩溃会留下"有 reported 无 computed"的行。这对 `compute_portfolio_weight` 有害吗?
>    (它 `computed or reported`,所以只有 reported 也够——确认这条推理。)
> 6. **作者的核心断言**:修复后 distinctiveness 从"0/1282"变成"1150/1282",dev(手工路径)是 1965/2135。
>    **为什么沙箱是 90%(1150/1282)而 dev 是 92%?** 剩下的 ~10% signal 为什么仍然 distinctiveness=0?
>    是合理的(如共识股票 distinctiveness 本就低),还是又一个没填的字段?抽查几个 distinctiveness=0 的 signal。
>
> 尽量在 `valuepilot_test` 上复现 (1)(4)。结论:这个修复完备吗?reparse 路径安全吗?

## Prompt 3 — 静默失败的防线,与两个 deferred 的判断

> 你在评审 ValuePilot PR #116。这一票的主题是"自动路径静默退化,手工路径正常"。这已经是**第三次**
> (`accepted_at`、`enrich_metadata`、现在的 filing 总额)。你的任务是判断**防线**够不够,以及作者
> deferred 的两条是否判断正确。
>
> **A. 防线是否真的堵住了这一类?**
> - `_check_reconciliation` 现在对"有 holdings 无总额"告警。但它是 `warning` 还是 `error`?
>   `quality_status='passed'` 是否仍然可能在有此告警时成立?(读 `QualityReport` 如何从 warning/error
>   推 status。)如果 passed 仍成立,那 pipeline 仍会静默通过——防线是漏的。
> - 两条新的离线 seed 守卫(CIK 10 位、名字唯一)只覆盖**形状**,不覆盖"CIK 是否真的申报 13F"。
>   有没有一个**运行时**检查会在"confirmed manager 连续 N 季度零 filing"时告警?(作者把它放进了那张票,
>   没进本 PR。)在此之前,下一个失效的 manager 会不会同样静默?判断这个缺口在本 PR 合并后是否可接受。
> - 更一般地:还有**几个** filing 级字段是"手工路径写、现代路径不写"?把 legacy `ingest_filing_holdings`
>   写的字段集合,与 `_do_ingest_holdings` + `apply_primary_doc_metadata` 写的集合做**差集**。差集非空就是
>   下一个潜伏的同类 bug。这是本次评审最高价值的产出。
>
> **B. deferred #1(seed 救不了已有库)判断对不对?**
> 作者说:CIK 改了之后,seed 对 Icahn/Greenlight 会创建**重复的 confirmed manager 行**(因为 cik、
> dataroma_code、name 三把钥匙都不再命中旧行)。在 `valuepilot_test` 上构造:先按**旧** seed 建好 82 行,
> 再用**新** JSON 跑 `seed_confirmed_managers`,断言 Icahn 是否真的变成两行。这条如果成立,说明**这个 PR
> 不能直接 re-seed 到 prod**——确认严重性,以及"仅本 PR 合并、不 re-seed"是否安全(空库场景 vs 已有库场景)。
>
> **C. deferred #2(千美元单位)判断对不对?**
> 作者说 Lens 不受影响,因为 portfolio weight 是同一 manager 内的比值,尺度无关。**验证这条推理**:
> 读 `compute_portfolio_weight` 和用到它的 conviction/distinctiveness 分量,确认没有任何一处用了
> **绝对** value(跨 manager 比较、或与某个绝对阈值比)。如果有一处用了绝对值,那这六个 manager
> (含 Baupost)的分数**也**是错的,deferred 的严重性就被低估了。

---

## 输出格式(三个 prompt 共用)

写回 `docs/tasks/2026-07-10_13f-seed-cik-audit-review-results.md`:

```
## Verdict
（可合并 / 需补正后合并 / 打回。一句话。）

## Findings
### P1/P2/P3 — <标题>
- 文件/行:
- 精确状态或输入:
- 现有代码会怎么做:
- 错误的产品后果:
- 是否已复现（贴命令 + before/after）；未复现则写"推理未复现"
- 建议修法:

## Missing Tests
## Non-findings（检查过、确认不是问题的，写出来避免重复劳动）
```

**规则:**
- **不要把"作者已明确不修"的 3 条当新发现重报**;要 judge 它们（进 Verdict 或 P2/P3 反驳）。
- **每个 finding 必须给出错误的产品后果**,不是"代码不优雅"。
- **能复现就复现。** 本仓库历史教训:作者曾多次报告"确认存在",复现后前提为假。**推理未复现的请显式标注。**
- CIK 类结论**必须**用 EDGAR submissions 佐证,不能只靠名字相似。
- 若你认为作者某个数字错,**给出你自己的查询与结果**。
