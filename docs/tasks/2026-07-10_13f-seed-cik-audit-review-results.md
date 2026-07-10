# PR #116 review results — 13F seed CIK audit and filing totals

Reviewed 2026-07-10 against `main...claude/13f-seed-cik-audit`.

## Verdict

打回：不能部署到已有 13F 数据的库。API 每次启动都会自动 re-seed，而本分支会在旧 seed 库中新增 5 个 confirmed manager、保留 5 个错误 CIK 行；另有未受保护的 reparse 会把已验证的总额替换为部分解析总额并继续产生错误的 Lens 权重。

## Findings

### P1 — 部署后自动 seed 会把旧库从 82 个 manager 变为 87 个

- 文件/行: `backend/app/main.py:37-41`; `backend/app/services/edgar_ingestion.py:320-366`; `backend/app/services/seed_data/confirmed_managers.json`。
- 精确状态或输入: 数据库先由 `main` 的旧 `confirmed_managers.json` 建好 82 行，再以本分支 JSON 启动 API（`MANAGER_SEED_ON_STARTUP=true`）。新 CIK 无法按 CIK 或 `dataroma_code` 找到旧行；名称规范化不相同的记录会走 create 路径。
- 现有代码会怎么做: 复现结果为 `created=5, updated=72, ambiguous_name_match=5`，行数 `82 -> 87`。实际创建的是 Aquamarine `0001953324`、Fundsmith `0001569205`、Greenlight/DME `0001489933`、Icahn `0000921669`、Trian `0001345471`；同一 display name 均同时保留旧 CIK 和新 CIK。另五个（Appaloosa、Chou、FPA、Third Avenue、ValueAct）因规范名碰撞被拒绝创建，因此仍只有旧的、不会申报的 CIK。作者已 defer “Icahn/Greenlight 会重复”，但该事实不完整：实际有 5 个重复、5 个继续缺席，而且不是“手动 re-seed 才会发生”——每次 API 启动都会发生。
- 错误的产品后果: 5 个 manager 同时以旧/新实体存在，已存在的持仓和新摄取持仓按不同 `manager_id` 分裂；5 个 manager 仍永远不匹配 `form.idx`。这既污染 Oracle's Lens 的 manager universe，又错误改变 `min_holders=3` 的共识和历史重算范围，且不会阻止服务启动。
- 是否已复现（贴命令 + before/after）: 已复现（隔离 `valuepilot_test`，外层事务回滚）。命令以 `git show main:...confirmed_managers.json` 的 base64 内容建立旧 82 行，调用 `seed_confirmed_managers()`；输出：`report {'seed_entries': 82, 'created': 5, 'updated': 72, 'ambiguous_name_match': 5}`、`count 82 87`。Icahn、Greenlight、Aquamarine、Fundsmith 的查询都各返回两行；Trian 位于 `created_ciks`。复现未向数据库提交。
- 建议修法: 不要仅 merge JSON 后依赖启动 seed。先交付一个审计化 CIK re-point（例如每个 entry 的 `previous_ciks`，或明确 admin action，均写 `InstitutionManagerCikReviewEvent`），只允许它把正确的既有 manager 行改指向新 CIK；在该迁移落地前，让启动 seed 检测到旧 CIK→新 CIK 映射时 fail-loud 而不是 create/refuse。加入“旧 82 行 + 新 seed”回归测试，断言 `created=0`、82 个 CIK 被更新且每个 display name 恰一行。

### P1 — 无验证 reparse 会用部分 run 覆盖正确的 portfolio 分母

- 文件/行: `backend/app/services/thirteenf_holdings_ingest.py:263-285,510-517`; `backend/app/services/thirteenf_admin_dashboard.py:3618-3626`。
- 精确状态或输入: 一个 filing 已有 current run，两个 InfoTable 行总值 `17,000,000`，primary document 已报告同样的 `17,000,000`。随后经 `reparse_accession`（admin reparse / `ingest_if_needed` 的 fingerprint 升级）提供一个格式合法、但只含 Apple `8,000,000` 的 InfoTable。`parse_infotable` 会成功；没有任何 row-count 或总额 validation gate。
- 现有代码会怎么做: `_do_ingest_holdings` 无条件执行 `filing.computed_total_value_thousands = sum(this_run)`，并将这个较小 run 标为 current。`compute_portfolio_weight` 优先选择 computed 而非 reported；generic admin job 直接返回 `status: succeeded`。
- 错误的产品后果: Apple 的权重会从正确的 `8/17 = 47.06%` 变成 `8/8 = 100%`。该 filing 的 top-10、position importance、distinctiveness 和 conviction 会按错误的集中度计算；旧的完整 holdings 虽保留在 audit trail，但不再服务产品。
- 是否已复现（贴命令 + before/after）: 已复现（隔离 `valuepilot_test`，外层事务回滚）。容器内创建 manager/filing，先 `ingest_holdings_for_filing(two_rows)`，设 reported 为 `17_000_000`，再 `reparse_accession(one_row)`；输出：`{'before_computed': 17000000, 'after_computed': 8000000, 'reported': 17000000, 'current_rows': 1, 'apple_weight': '1'}`。这是格式合法的部分输入复现，不依赖网络或破损 XML。
- 建议修法: 在任何会切换 current ParseRun 的路径上加入同一验证门：有 reported total 时，候选 computed 必须在 reconciliation 阈值内，否则候选 run 保留审计记录但不能成为 current，且不能覆盖 filing computed total；无 reported total 时至少比较前一 verified run 的行数/总额并要求显式批准。将质量检查的 warning 不能替代 activation gate，因为 generic reparse 及季度 pipeline 均会继续成功并评分。

## Missing Tests

- 旧 82 行 re-seed 新 JSON 的回归测试；必须断言无 create、无 `ambiguous_name_match`、每位 manager 只保留一个 confirmed 行，并覆盖 Aquamarine、Fundsmith、Trian（不只 Icahn/Greenlight）。
- `_do_ingest_holdings` 的端到端测试：断言 holdings 总额和 `common_holdings_count`；目前新增测试只直接调用 `apply_primary_doc_metadata`，未覆盖实际自动路径。
- 上述部分 reparse 测试：完整 run 后对一份格式合法的一行输入 reparse，断言 current pointer 与 computed denominator 不会被切换/覆盖。
- `_check_reconciliation` 测试：有 current holdings 且两个总额皆 NULL 时必须产生 warning 并持久化为 `quality_status=warning`；零 holdings filing 不应命中。

## Non-findings

- EDGAR submissions 独立复核的 11 个新 CIK 都有 13F-HR。结果如下（CIK、EDGAR entity、13F-HR 数、最近 filed date）：

  | manager | CIK | EDGAR entity | count | latest |
  | --- | --- | --- | ---: | --- |
  | Appaloosa | 0001656456 | Appaloosa LP | 41 | 2026-05-15 |
  | Aquamarine | 0001953324 | Aquamarine Zurich AG | 18 | 2026-07-10 |
  | Bridgewater | 0001350694 | Bridgewater Associates, LP | 97 | 2026-05-15 |
  | Chou | 0001389403 | Chou Associates Management Inc. | 80 | 2026-05-14 |
  | First Pacific Advisors | 0001377581 | First Pacific Advisors, LP | 79 | 2026-05-14 |
  | Fundsmith | 0001569205 | Fundsmith LLP | 58 | 2026-05-15 |
  | Greenlight | 0001489933 | DME Capital Management, LP | 9 | 2026-05-15 |
  | Icahn | 0000921669 | ICAHN CARL C | 46 | 2026-05-15 |
  | Third Avenue | 0001099281 | THIRD AVENUE MANAGEMENT LLC | 96 | 2026-05-13 |
  | Trian | 0001345471 | TRIAN FUND MANAGEMENT, L.P. | 73 | 2026-05-15 |
  | ValueAct | 0001418814 | ValueAct Holdings, L.P. | 74 | 2026-05-15 |

  Icahn 和 DME 的 EDGAR 名称确实分别是个人和不同品牌名，但 submissions 数据确认二者均为活跃 13F filer；本 review 没有得到相反证据。三个歧义选择也符合频率最大者：Aquamarine Zurich `18` vs Cayman `3`，Fundsmith LLP `58` vs Investment Services `21`，Bridgewater Associates `97` vs Advisors `24`；每个候选最近均在 2026-05（Zurich 2026-07-10）。

- 对全部 82 个当前 CIK 跑 submissions 后，没有一位最近 13F-HR 早于 2025-08；Scion `0001649339` 的 EDGAR entity 是 Scion Asset Management, LLC，33 份 13F-HR，最近 `2025-11-03`，与“正确 CIK、之后停报”的说法一致。因此没有第 12 个漏网 CIK。
- JSON 结构比对通过：82 -> 82；排除新增的 `cik_source` 后，恰好 11 项改变；每项仅为 `cik` 或 `cik, legal_name`，并恰有 11 个 `cik_source`。
- 新 reconciliation 缺总额分支工作：有 current holdings、两个总额均 NULL 的隔离 fixture 产生 `reconciliation` warning，`persist_quality_report` 得到 `warning` 而非 `passed`。零 holdings filing 因 `EXISTS(holdings)` 为假不会命中。warning 质量报告也会使 readiness 进入 `needs_review`；这修复了原来“0 comparisons 仍 passed”的具体静默路径。
- `common_holdings_count` 的消费者仅将其作为 common-stock coverage/count 展示；没有发现消费者把它当成 primary-doc `holdings_count`（该字段含期权）。
- `value_thousands` 与 reported table total 在现代路径使用同一份 filing 的同一原始单位，reconciliation 不会产生 1000x 偏差。Oracle's Lens 中这两个值只作为同一 manager/filing 的比值、排序或 top-N 输入；未发现跨 manager 的绝对值阈值。因此“六个 filer 的绝对金额仍错误、Lens 权重不受比例尺度影响”的 deferred 判断成立，仍应按 BACKLOG 处理。
- legacy `ingest_filing_holdings` 与现代路径的字段差集已核对。legacy 自身还写 raw-document links 和 period routing；现代 pipeline 的 Phase 1/2 已分别负责 `ensure_filing_infotable_doc` 和 `backfill_period_routing`。本 PR 后自动路径额外写 primary metadata、reported total、holdings count、computed total、common holdings count 与 parse status；没有发现另一项由 legacy 独占、却在现代 pipeline 漏写的 filing 级产品字段。

## Verification

- `docker compose up -d --build` — passed
- `docker compose exec -T api alembic upgrade head` — passed
- `TEST_URL=postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q` — 1220 passed, 3 existing SQLAlchemy legacy warnings
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — 179 passed
- `docker compose exec -T web npm run lint` — passed
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` — passed (Browserslist database age notice only)

---

# Round 2 — post-fix review (2026-07-10)

## Verdict

需补正后合并。上一轮的“旧库 82 → 87”和“部分 reparse 覆盖分母”两个主路径已正确修复并有回归测试；但 `previous_ciks` 没有覆盖真实 revoke 的 `cik=NULL` 状态，会重新创建 confirmed manager 并推翻人工撤销。另有 quarantine 结果在 job/pipeline 层仍被报告为成功，导致安全地保留旧 run 的同时静默留下过期数据。

## Findings

### P1 — 已撤销的旧 CIK 会绕过 `previous_ciks` 并创建新的 confirmed manager

- 文件/行: `backend/app/services/edgar_ingestion.py:261-287`；真实撤销行为在 `backend/app/services/thirteenf_admin_dashboard.py:976-1015`。
- 精确状态或输入: 已有一个由旧 seed 创建的 Icahn 行（旧 CIK `0001413902`），操作员执行 `revoke_manager_cik` 的真实语义：`cik=NULL`、`match_status='revoked'`，并写入 `revoke_confirmed_cik(old_cik='0001413902')` 事件。随后启动本分支的 seed；Icahn entry 的新 CIK 是 `0000921669`，`previous_ciks=['0001413902']`。
- 现有代码会怎么做: 当前 CIK 和 dataroma code 均无法命中；previous-CIK 查询只查 `InstitutionManager.cik`，而真实 revoke 已把它置 NULL；随后 `_cik_was_revoked_by_a_human` 错误地查询新 CIK `0000921669`，而 audit 事件保存的是旧 CIK `0001413902`。由于 `ICAHN CAPITAL MANAGEMENT LP` 与 `ICAHN CARL C` 的 normalized name 不相同，seed create 新行。
- 错误的产品后果: 人工明确撤销的 manager 仍保留在 needs-review，但自动 seed 又创建一个 active/confirmed Icahn 记录；新记录会进入 `form.idx` 白名单与 Lens universe。这违反“human wins”的生命周期契约，并会在每次自动启动 seed 时重新把未经人工确认的实体带入产品。
- 是否已复现（贴命令 + before/after）: 已复现（隔离 `valuepilot_test`，外层事务回滚）。容器内先插入真实 revoke 形态的旧 Icahn 行及 event，再调用 `seed_confirmed_managers()`；输出：`report {'created': 82, 'cik_repointed': 0, 'skipped_human_decided': 0, 'ambiguous_name_match': 0}`，Icahn 两行分别为 `(None, 'revoked', 'needs_review', 'ICAHN CAPITAL MANAGEMENT LP')` 和 `('0000921669', 'confirmed', 'active', 'ICAHN CARL C')`。
- 建议修法: 在 create 路径之前，将 `previous_ciks` 也传给 revoked-event 检查；任一 previous CIK 有 `revoke_confirmed_cik` event 时必须把新 CIK 记入 `skipped_human_decided`，绝不能 create。加入端到端回归测试，使用实际 `revoke_manager_cik` 状态（CIK 为 NULL），而不是当前测试的 `inactive + old_cik` 近似状态。

### P2 — quarantine 被 job/pipeline 吞掉，仍以成功状态完成

- 文件/行: `backend/app/services/thirteenf_holdings_ingest.py:331-359`; `backend/app/services/thirteenf_admin_dashboard.py:3623-3630,3747-3757`。
- 精确状态或输入: reparse activation gate 判断候选 run 部分解析并返回 `{'quarantined': True, 'quarantine_reason': ...}`；旧 current run 保持可服务。
- 现有代码会怎么做: 单 accession job 丢弃 `quarantined` 和 `quarantine_reason`，固定返回 `status='succeeded'`。季度 ingest 同样将 quarantine 当普通非-skip result，累加候选的 `holdings_count`，不增加 `failures`、不生成 `pipeline_warning`、不创建质量 finding。`rg` 证实没有其它 `quarantined`/`quarantine_reason` 消费者。
- 错误的产品后果: 产品继续使用旧 holdings（安全），但操作员得到全绿 job；如果候选含 parser 修复或真实更新，数据将持续过期且没有 admin task/quality status 指示。原票的目标正是阻止自动路径静默退化，此处仍留下同类静默失败。
- 是否已复现: 推理已复现于 job-adapter 代码路径：`reparse_accession` 的唯一新结果字段在 `_execute_ingest_job` 返回体和季度循环中均未读取；隔离 reparse gate 测试也已确认会返回 `quarantined=True`。尚未构造带持久 raw document 的完整 dashboard job fixture。
- 建议修法: 将 quarantine 映射为 job `partial_success`/`needs_review`，把 accession 与 reason 放入 summary 和 `pipeline_warning`；季度路径应记录 `filings_quarantined` 并使总 job 至少 `partial_success`。同时持久化可在 readiness/admin 中显示的 finding 或 parse warning，避免仅依赖日志。

## Missing Tests

- 使用 `revoke_manager_cik` 的真实 CIK=NULL + `previous_ciks` seed 回归测试，断言不创建新 confirmed 行。
- `reparse_accession` job 与 quarterly `ingest_holdings` 对 quarantine 的端到端测试：job 不得 `succeeded`，summary/readiness 必须含 accession 和原因。

## Non-findings

- 上一轮 P1 seed 主场景已修复：旧 82 行重 seed 的新增测试覆盖 `created=0`、`updated=82`、`cik_repointed=11`、0 name collision、82 → 82、11 个 audit event；定向测试 39 passed。
- 上一轮 P1 reparse 主场景已修复：17M 两行 current run 对 8M 一行 candidate reparse 会 quarantine，保留 17M 分母和两条 current holdings；可正常 reconciliation 的 reparse 仍会切换。
- `previous_ciks` 当前数据本身完整：11 个 entry、11 个 10 位数字、无重复、且与 current CIK 无交集。

## Verification

- `docker compose up -d --build` — passed
- `docker compose exec -T api alembic upgrade head` — passed
- `TEST_URL=postgresql://valuepilot:valuepilot@postgres:5432/valuepilot_test docker compose exec -T -e DATABASE_URL="$TEST_URL" api pytest -q` — 1228 passed, 3 existing SQLAlchemy legacy warnings
- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — 179 passed
- `docker compose exec -T web npm run lint` — passed
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` — passed (Browserslist database age notice only)
