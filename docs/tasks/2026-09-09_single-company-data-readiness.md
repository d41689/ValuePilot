# 单家公司研究 S1 — AAPL 数据可用性

日期：2026-09-09

状态：已批准的 negatedLabel 修复已通过完整代码验收，开发库已升级。
AAPL 离线导入及 canonical publication 已实际执行并验证重复运行；零外部拉取。
S1 未通过：年度净利润的维度歧义、currentness 全公司 1,000 条上限阻塞最低验收；见末尾实测与待审方案。

## Goal / Acceptance Criteria

执行已批准的[最小计划 S1](../plans/single-company-research-minimal-plan.md)，
使已有真实财务由当前应用正常读取。锁定样本为 AAPL，不以失败为由更换公司或缩减期间。

- Identity：AAPL / CIK `0000320193` / XNAS，非金融、USD；目标 stock ID 在写入前重新核实。
- Filing-selection cutoff：`2026-09-09T00:00:00Z`；known-at/创建时间使用真实数据库时钟，不伪造截止前关系。
- 年度窗口：FY2016–FY2025；最低完整分析基础为 FY2023、FY2024、FY2025。
  已保留最新季度截至 2026-06-27；其他年或季度缺口显式记录。
- 核心指标：已批准定义的收入、净利润、CFO、capex、现金、债务组成及股数。
  不混用股数种类，不把 cash/restricted cash 或债务组件自动相加。
- 当前应用中的 canonical 数据有证据定位、可比性/缺失状态，重复执行不产生语义重复或错误 current。

## Scope / Authority

In：定位为何已有现金流和资产负债 raw facts 未能发布；复用现有 parser、statement authority、mapping/publication；
必要的局部修复、负向测试及经确认的 AAPL 数据准备。
Out：新表、通用导入平台、其他公司、新模型、AI、价格源、账户注销、生产或保留验收库修改。

PRD §H.3–H.7、§H.9–H.11；mapping spec；source policy；
`docs/architecture/parsing.md` 与数据层/研究架构是执行权威。不能从 raw facts 直接绕过发布提供 UI 数字。

## Files to inspect / potentially change

- `backend/app/services/sec_financial_ingestion.py`
- `backend/app/services/sec_statement_authority.py`
- 现有对应单元测试/fixtures；确认根因后在此记录实际最小 diff。
- 本任务记录和既有计划进度。若需语义或 schema 变更，先请求审查，不修改旧 migration。

## Preflight evidence

2026-09-09 只读重新确认：

- 当前开发 DB `valuepilot` revision `20260909120000`，`metric_facts=0`。
- 保留 DB `valuepilot_acceptance_ft04_gold_20260901_b` revision `20260901230000`，metric facts 为 2,414。
- AAPL 原始 CFO、capex、现金、长期债务数据存在，包含 FY2023–FY2025。
  但 statement authorities 的类型只有 income_statement、comprehensive_income、equity，未见 cash_flow/balance_sheet。
  这是待定位的来源证明缺口，不能据此直接发布未证明的数字。
- 最近保留 ingestion operation：`8f73d2b9-041c-4a6e-8f13-2174bda2ff8b`，44 个 accession attempts。
- AAPL retained artifact 按行累加约 318 MB（包含重复，不是准确新增磁盘需求）；磁盘可用约 301 GiB。
- 普通 API 容器未挂载旧 gold 存储；诊断可使用临时容器的只读挂载，不能搬整库解决。

用户于 2026-09-09 明确批准：只读源库和 `/Users/dane/projects/ValuePilot/storage/sec_gold_acceptance/ft04-gold-20260901-b`；
目标开发 DB `valuepilot` 与 `/Users/dane/projects/ValuePilot/storage/edgar_raw`；
新增持久数据最多 2 GiB，超限停止；零外部 SEC 请求，不触生产。
用户同时授权按小步 commit/push/Draft PR；merge 和生产部署仍需另行确认。

## 根因复核与工作树检查

- 已建立 Draft PR #147；初始文档提交 `6ebb1506`。
- 保留 AAPL 的成功 parse 为 v2.4。现有 v2.7 已能恢复 2025 报表的 balance-sheet 和部分 cash-flow occurrence，
  无需为这些已修复问题再开发代码。
- 当前代码对 FY2025 capex 仍拒绝：原始 XBRL 为正 `12715000000`，生成报表为 `(12,715)`（millions）。
  presentation arc 的 exact preferredLabel 为 `http://www.xbrl.org/2009/role/negatedLabel`，
  label 文本精确对应。FY2024/2023 同一行也采用反号显示；这不是 raw 金额冲突。
- [XBRL 官方说明](https://www.xbrl.org/guidance/label-roles/)确认 negated label 控制显示符号而非改写原值。
  随后已获用户明确批准最小 parser/PRD/新增 guard migration 修复。
- 现有 `build_retained_financial_replay_client` 成功只读验证 AAPL 的 2,902 个 URL、318,544,064 bytes，
  missing instances=0，external requests=0。可复用现有路径，不需要通用导入平台。
- 常驻 `valuepilot-dev-api-1` 实际挂载 `ValuePilot-source-contract/backend`，不是本工作树。
  首次 `docker compose exec ... -k negated_label` 只得到 79 deselected（exit 5），不构成 red/green 证据。
  迭代使用当前 compose 的一次性容器；closing gate 再核实并重建到当前工作树。
- 已加入 8 个 negated-label 参数化测试。当前工作树执行
  `docker compose run --rm --no-deps -T api pytest -q tests/unit/test_sec_statement_authority.py -k negated_label`
  得到 8 failed / 79 deselected：新增显式 opt-in 参数尚未实现（TypeError），属于 test-first red，
  不替代上面的真实报表复现，也不是应用原有测试回归；这是实现前记录。

### negatedLabel 实现与验证进度

- 新 parser `xbrl-lineage-v2.8` 仅对 exact negatedLabel 启用反号比较；v2.7 及此前的解析行为保持不变。
  原始文本、规范化金额、正 scale 和既有证据绑定规则均不改变。
- 新 migration `20260909140000` 扩展四个既有数据库 guard 的 parser 版本识别，
  occurrence guard 仅对 v2.8 的 exact negatedLabel 使用反号数值恒等式。
  未改旧 migration；存在 v2.8 lineage 时拒绝降级，空历史 upgrade/downgrade 字节级还原函数定义。
- 12 个定向测试通过：8 个数值/角色/旧语义场景、migration round-trip、实际数据库发布/降级保护、
  两个数据库错误角色或错误金额拒绝场景。数据库测试使用临时隔离 schema，不写保留验收库。
- 保留 AAPL `0000320193-25-000079` 的只读实测：R8.htm 在旧语义下 capex occurrence 为 0，
  启用新语义后为 3。FY2025/2024/2023 分别显示 `(12,715)` / `(9,447)` / `(10,959)`，
  对应原始正金额 12,715 / 9,447 / 10,959 millions。整个现金流报告匹配 occurrence 从 39 增至 69。
  原文由既有 hash/byte-size 校验读取，无源库或文件修改，无外部请求。
- 开发环境默认开启 EDGAR scheduler、13F worker/retry 和 startup seed。closing gate 使用仅运行期的
  `/tmp/valuepilot-s1-offline.ZdCsgo/compose.offline.yml`，通过 `COMPOSE_FILE` 与原 compose 合并：
  `EDGAR_FETCH_MODE=replay`，关闭上述四项及研究/通知调度；不修改仓库默认配置或生产。
  已重建并确认 api 挂载本工作树；开发库已从 `20260909120000` 升至 `20260909140000`。
  后续重启若不指定这个 override 会恢复默认配置；本轮验收期间保留离线运行。
- 聚焦四文件回归与全套启动重叠时，读取 `pg_database_size` 出现一次 `Cannot allocate memory`。
  已用 SIGINT 停止本任务自己的重复聚焦容器（167 passed 后中断，不计为全套通过），
  仅保留 canonical 后端测试；未停止其他项目容器、未重启共享 Postgres。
  后续同一只读查询成功返回 4,887,606,975 bytes。此时开发库 SEC parse/facts 仍为 0，
  目标已有存储为 1,323,339,985 bytes，未开始 AAPL 导入；这些读数不是导入完成证据。
- 修复 checkpoint `1e69c899` 已 commit/push 至 Draft PR #147；完整测试结果待下方 closing sign-off。
- 全套回归发现 gold acceptance 的静态当前版本断言仍为 v2.7。
  单独重现为 `ACCEPTANCE_PARSER_VERSION` 实际 v2.8、期望 v2.7 的失败；
  该常量原本就引用当前 parser，更新测试的明确版本锁定至本次已批准的 v2.8。
  不更改 mapping/method-policy/21-metric 分母，不改写任何旧 gold 运行或报告。
- 第一轮 canonical 后端完整结果：2,756 passed / 1 failed，耗时 1,146.35 秒；
  唯一失败即上述版本断言，单独修正复测 1 passed。补充提交 `d2957032` 已 push；
  已重新开始完整 closing gate，不将第一轮结果称为通过。

### 数据准备仍未执行的检查点

- 开发库唯一 AAPL 记录为 stock 66，`exchange/market_country=US`、
  `listing_exchange=NULL`、公司名 `APPLE INC`，尚无该 CIK 的 reviewed issuer identity。
  数据准备时须将已批准的 AAPL / XNAS / CIK 0000320193 与该现有记录明确核对，
  不能把 legacy `US` 标签声称为已经验证的 listing，也不能为绕过它换公司。
- 新增 AAPL lineage、normalization、canonical publication、重复执行和页面可读性仍待验证。
  此次 negatedLabel 修复通过不等于 S1 或完整 Beta 已完成。

## Test plan / sign-off

### 已批准的最小契约变更

用户已明确批准 `negatedLabel` 显示反号及对应新数据库校验迁移，现开始实现。

仅为新的 parser 版本启用精确 URI `http://www.xbrl.org/2009/role/negatedLabel`：
当既有 presentation arc 与 label 校验通过时，比较 `-display × scale` 与原始规范化值；
其他 label 保持既有比较。原始金额、canonical mapping、正 scale、证据身份均不改。
禁止 `abs()`、按名称猜符号、接受相似 URI，或为了通过而接受两种符号。
新 migration 只扩展版本识别及对应数值校验，不改旧 migration；旧 parser 保持原语义。
迁移测试须证明升级/空历史降级可逆、存在新版本 lineage 时拒绝破坏性降级，
并实际验证数据库拒绝错误符号/金额而接受证据明确的显示反号。不能只检查 SQL 字符串。
范围仅限这项必要修复，不授权其他符号推断或扩大 mapping。

先对保留证据做只读最小复现，再写回归测试（red），只修根因（green）。
不重签旧 gold acceptance，不改变 locked manifest，不因为缺数据把 unavailable 当 S1 成功。
聚焦命令在具体测试确定后记录。实现 closing gate 必须原样运行：

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

另做 `git diff --check`、实际数据证据核对及用户浏览器验收；代码修复的结果如下。
浏览器流程和开发库真实财务发布仍未验收，不能据此宣布 S1 完成。

## negatedLabel 修复 closing sign-off

2026-09-09，应用代码/测试提交 `d2957032`（包含 `1e69c899`），使用上文离线运行期 override。
第二轮按顺序原样执行 canonical commands：

| 检查 | 结果 |
| --- | --- |
| `docker compose up -d --build` | PASS |
| `docker compose exec -T api alembic upgrade head` | PASS；head `20260909140000` |
| `docker compose exec -T api pytest -q` | **2,757 passed**，940.12 秒 |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | **233 passed** |
| `docker compose exec -T web npm run lint` | PASS |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | PASS |
| `git diff --check` | PASS |

后端只有既有 Starlette/httpx 与 anyio deprecation warnings；本轮前端构建成功。
自审检查了精确角色、反号/金额不匹配、旧版本行为、实际数据库拒绝、迁移可逆性及有历史时拒绝降级；
版本断言修正后未发现其他本项范围内问题。这是本 agent 自审，不声称第三方已独立 review。

代码修复 checkpoint 的只读确认（不是下方数据执行后的状态）：开发库 SEC parse runs=0、metric facts=0；运行模式为 replay，SEC/13F 调度和 worker 关闭。
保留验收库/文件未修改、SEC 外部请求为零、生产未修改、未 merge。
PR #147 保持 Draft：S1 数据回放、canonical publication 和用户可读性尚未完成。

## S1 继续执行 — 离线数据准备

用户指出停得过早后，继续原已批准 S1；不重新请求同一项权限。
仅使用一次性固定 AAPL operator 调用 `/tmp/valuepilot-s1-replay.oBd3cP/aapl_replay.py`，
串联既有 retained replay client、ingestion、normalization 和 publication 服务；不开发通用导入平台。

- 只读 preflight：保留 SEC submissions 明确 `cik=320193`、`tickers=[AAPL]`、
  `name=Apple Inc.`、`exchanges=[Nasdaq]`。与开发库唯一 AAPL/APPLE INC 的 stock 66 核对一致。
  Nasdaq/XNAS 在现有应用 listing alias 中使用 `NDQ`；准备时补充该已核实 listing，
  保留原有 `exchange/market_country/raw_exchange=US`，不创建第二个股票。
- 锁定 cutoff 下既有 history selector 选中 42 份 filing，覆盖 FY2016–2025 十份年报，
  discovery failures=0。全部来自已保留的 318,544,064 bytes，单个文件最大 3,842,300 bytes。
  没有外部请求，缺失资源不允许启动上游 client。
- 写前基线：开发库 public 表及索引 267,796,480 bytes；目标原有存储 1,323,339,985 bytes。
  所有后续阶段共享这个基线计算累计增量；每份 filing 解析前后、提交和发布前后核对。
  2 GiB 是新增数据硬上限，另保留 512 MiB 停止余量，不把每个阶段重新当成独立预算。
- 新 reviewed identity 的 knowledge time 使用当前数据库时间；既有 filing 的 source dates 保留，
  不把这次本地回放伪称为 cutoff 前已入库或一次新的 SEC 网络抓取。

### 实际数据结果（本地日期 2026-09-09，数据库 UTC 日期 2026-09-10）

- Ingest operation `a5a99e68-44b2-47f6-8fbe-6bad6937ed8c`：42 filings、3,321 artifacts、
  42 v2.8 parse runs、41,374 raw facts；failures=[]，已 finalized。
  第二次 operation `6b3e09cb-454e-4a0c-a1df-954f1245cd83` 已 finalized；
  filing/artifact/parse/raw 的语义记录总数均未增加，零外部请求。
- Publication run `a33b3bd8-408c-5ac2-8249-1185406a1342`：42 个完整 source，
  1,210 database-owned normalizations，1,126 published facts、258 unresolved decisions、
  4,502 audit dispositions；run succeeded 且已另事务 finalized。
  最初 receipt.available=false 是 finalize 前的回执状态，不是 finalized 状态；
  相同 request/cutoff 的 replay 返回相同 run ID，未新增 facts。
- 当前 `metric_facts` 共 1,126 条、747 条 current；全量事实与 publication 绑定/金额不一致=0，
  同 metric/period/end/source 的重复 current 槽位=0，其他股票 facts=0。
  没有手工写入或修改 raw/facts，没有删除历史版本以压低查询数量。
- 累计新增持久数据：public 表/索引 379,584,512 − 267,796,480，
  文件 1,627,454,114 − 1,323,339,985，总计 **415,902,161 bytes（约 397 MiB）**。
  未超 2 GiB，未改保留证据或生产；测试 schema/构建缓存不是此数据增量口径。

| Canonical 指标 | FY2016–2025 当前覆盖 | FY2023 / FY2024 / FY2025（USD millions，股数除外） |
| --- | --- | --- |
| is.revenue | 10/10 | 383,285 / 391,035 / 416,161 |
| is.net_income | 0/10 | 缺失，不能用 raw 绕过 publication |
| is.operating_cash_flow | 10/10 | 110,543 / 118,254 / 111,482 |
| cf.capital_expenditures | 10/10 | 10,959 / 9,447 / 12,715 |
| bs.cash_and_equivalents | 7/10（2019–2025） | 29,965 / 29,943 / 35,934 |
| cap.long_term_debt_current | 10/10 | 9,822 / 10,912 / 12,350 |
| cap.long_term_debt_noncurrent | 10/10 | 95,281 / 85,750 / 78,328 |
| equity.weighted_average_diluted_shares | 10/10 | 15,812,547,000 / 15,408,095,000 / 15,004,697,000 shares |

表中债务是长期债务的流动/非流动部分，不是总债务；股数是稀释加权平均，不是期末发行股数。
SBC 年度 canonical 10/10；FY2023–25 为 10,833 / 11,688 / 12,863 millions。
`equity.shares_outstanding` 仅有季度发布；现金 FY2016–18 缺口仍保留。
最新 filing 为截至 2026-06-27 的 10-Q；42 份选择结果不构成所有离散季度完整覆盖。
derived quarter 的 `unresolved_derived_context_mismatch` 等拒绝未放宽；不伪称自动季报序列完整。

### 实际未通过项与待审最小方案

1. **年度净利润缺少 statement authority（S1 阻塞）。**
   只读重跑 FY2025 的既有 resolver：R3/R4/R8 三个报表对 NetIncomeLoss 返回
   `ambiguous_generated_statement_occurrence`，R7 有未解析单元。
   同一期间/金额 112,010,000,000 同时存在无维度 c-1 和带
   `StatementEquityComponentsAxis=RetainedEarningsMember` 的 c-34。
   前者在四个 raw occurrence 重复本身可等价去重；真正歧义来自后者的不同 context/维度。
   当前 matching 不先证明显示单元的维度身份，且跨报表 concept 级拒绝会撤销全部 occurrence。
   不能简单排除所有带维度候选或选最小 ID，否则可能把真实分项误当合并数据。
   **待审方案：** 对明确证明为合并口径的主报表单元，按其报表/行/列维度证据缩小候选；
   拒绝范围只有在证明比较单元独立时才缩小。无法证明或同维度仍冲突继续 fail closed。
   需先批准精确语义，再加新 parser 版本、对应新 DB guard migration 和正/负向回归；
   不改 v2.8 历史，不手工补净利润，不借机支持分部 canonical 发布。
2. **currentness 1,000 条公司级候选上限（与 S2 同一查询边界问题，提前阻塞 S1）。**
   使用只读 Session 对真实 public SEC 数据调用现有 `read_stock_facts` handler，
   在 reconciliation 前返回 HTTP 409 `metric_fact_currentness_scope_bound_exceeded`：
   该 guard 计算全部 1,126 条历史 facts，不是 747 条 current。
   这是 handler 诊断，不是认证 HTTP/browser 验收；没有绕过认证建立会话。
   **待审方案：** 把原 S2 的完整比较单元有界查询提案一并涵盖 currentness 的 1,000 条限制，
   再处理 workspace 250 / UI 60。不得提高常量、只取 current 前缀或删历史；
   每个单元仍检查完整 currentness 历史、同槽位竞争、权限和 PIT，跨单元使用同一读取边界。
   审查通过后才实现；这是原计划依赖的实测修正，不把 S1 提前标成 PASS。
3. **UI 验收未完成。** 内部浏览器 `/home` 重定向 `/login`，已请用户登录；
   没有读取或输出凭据。即使登录，仍需解决上面的真实接口阻塞。
   独立 public evidence resolver 可读取 capex publication 338/344/349，金额为 canonical facts，
   包含 FY、币种、actual/source role 和来源引用；未点击 SEC 链接发起外部请求。

上述两个契约变更尚未执行。当前仅完成数据准备与失败原因核实；PR #147 保持 Draft，不 merge。
这次续跑没有新增生产代码修改，不声称新的完整 closing gate 或 S1 PASS；
上方代码 gate 仍准确对应 `d2957032`，后续修复后必须重跑全套并补真实产品验收。

### 必要性门槛与 v2.9 窄契约（续跑授权）

用户追加授权：只有不改就无法达成完整最小计划的改动才执行。上一轮已产生真实数据和
失败证据，属于 progress，而非无进展；本轮不重复申请同一必要修复授权。

- 必要：parser/新 guard migration/测试。年度净利润 0/10，缺少最低三年分析基础；
  手工填值或绕过 publication 均违反目标，不能代替修复。
- 必要：currentness 与 S2 比较单元查询契约、测试及原页面；真实 handler 409 使数据不可读。
  先完成 S1 parser，查询契约在实现前单独评审记录，不抬高常量。
- 不必要：清理 Docker build contexts、扩抓其他公司、补全部离散季度、自动估值；本轮不改。

进一步只读实测收紧了方案：AAPL FY2025 R3 实际包含 Product/Service 维度标记，不能用
“合并损益表”标题猜测每个单元的维度。R8 现金流报表及对应 presentation role 均没有维度标记，
可用其期初净利润行证明年度净利润；不需要实现带维度表的行/列展开算法。

v2.9 仅增加 `consolidated_empty_dimensions_v1` 候选域：FilingSummary 的名称明确包含
独立词 consolidated，且是已识别的 income/comprehensive/balance/cash-flow 主表（不含 equity）；
生成 HTML 只有一个表，其首个标题单元与该名称对应；该表的 ShowAR targets 以及该 role 的
全部 presentation locators 没有 Axis/Member/Domain 维度标记。仅在这个域内排除非空维度的
instance candidates；同域的不同 context/unit/数值歧义仍按原规则拒绝。其它表不改变匹配语义。
拒绝仍是 concept-wide，但按“明确无维度合并域 / 未证明域”隔离：同域任一拒绝撤销该域全部
同 concept occurrence；未证明的分项表不能撤销已证明合并域的 occurrence。不是选来源优先级。

自审：仅检查标题不足（R3 反例），因此加入整表及 role 的维度排除；仅按 report 隔离拒绝会
漏掉同域矛盾，因此按上述两个域汇总；只取 dimensionless 前缀也不允许，同域候选必须完整。
raw 数据、canonical mapping empty-only 定义、等价去重与旧 v2.8 行为均不改变。
新 migration 扩展版本并拒绝旧版本使用新域标记；对新域强制空维度、支持的主表类型、
retained 名称/HTML 标题和无维度标记校验，沿用 exact role/label/value/manifest 约束。
presentation role 解析由已有可信 backend 对 retained SHA/size 验证后的 linkbase 执行，
不另建签名、复制文件或伪称数据库读取了文件系统。

测试顺序：先纯 parser 正/负及旧版测试 red；最小实现；真实 DB publication/错误域拒绝及
migration round-trip；AAPL 同文件追加新版、发布和重复执行；最后完整 canonical gate。

第二次自审补充：custom dimension 不一定以 Axis 结尾。新增反例先 red，再将 retained contexts
中的实际 axis/member local name 纳入否定检查（只收紧资格，prefix alias 不会放行）；
不把后缀启发式当作维度身份。DB 也拒绝 HTML 引用这些实际维度名的新域标记。
当前数据库时钟另发现比上一轮已写入的 knowledge time 早约 31 分钟；不改时钟、不回填时间，
继续在隔离 schema 完成必要测试，数据续跑需先再次确认实际时钟已越过保留记录的 knowledge time。

真实 R8 包含一个 `class="report"` 主表和 70 个 taxonomy 说明/弹窗内表。
单一 HTML table 假设不能恢复真实数据，已用这个证据收紧为“无嵌套的首表；多表文档必须是
唯一 exact report class 主表”，限定 occurrence 必须来自主表。新增说明弹窗正例、双主表负例，
DB 同样检查主表边界及 occurrence 原始 anchor fragment 属于该表。详细准则归属 PRD §H.5。

v2.9 checkpoint：12 个候选域场景、8 个 negatedLabel 场景及真实 DB 发布/拒绝/跨域拒绝隔离
定向回归通过；迁移 round-trip 通过。真实 FY2025 只读 resolver 已从 R4/R8 各恢复三个年度
NetIncomeLoss occurrence：FY2025 112,010,000,000、FY2024 93,736,000,000、FY2023 96,995,000,000；
R3 的产品/服务歧义和 R7 的分项拒绝保留，未写成 canonical 值。准备执行完整 gate，
尚未声称新版 AAPL 全链路或 S1 通过。

随后把真实 taxonomy 弹窗形状加入 DB 夹具，暴露 PostgreSQL POSIX 匹配跨越尾随表的差异：
`.*?` 并未将 whole match 限在首个 `</table>`，两个新增 DB 场景失败。
只读 SQL 独立复现选中了 3 个 table。尚未应用到共享库的 v2.9 新迁移改为首个明确结束标签，
并继续拒绝主表嵌套；这不是放宽数值或来源约束。该 checkpoint 不代表 closing gate 通过。

### 必要查询修复：实现前契约自审

真实 AAPL 的 1,126 条历史事实使产品接口 409，不修无法满足 S1 的“当前应用可读”。
按用户的必要性授权推进 PRD §H.10 窄修改：一个指标的完整历史为资源单元，最多 64 个
可见指标；每单元沿用 1,000 历史候选 / 250 current 候选上限。跨单元复用一个现有
EvaluationSnapshot，返回完整物化响应；前端只对这份响应翻页，不引入游标签名/存储。

自审：不能按年份、来源或当前行前缀切分，否则可能遗漏同槽位竞争；按完整指标切分不会
产生这个缺口。共享 reconciliation 仍展开全部递归输入及输入槽位竞争，因此不同指标的
派生依赖不能绕过冲突。一个指标超限必须整单元 unavailable；指标发现本身超限整请求
typed failure；不隐藏超限、不提高常量。只改变 stock facts / workspace，其他消费者不改。
workspace 总量超过 250 时显示同一 snapshot 的分指标报告，而非伪造全局 report digest。
不新增表/enum/事实、不过滤掉失败的 SEC 发布状态，也不动账户、报价或生产。

测试先行：公司总历史 >1,000 / current >250 的安全分指标读取；单指标两个上限；
指标发现上限；同槽位冲突与递归依赖；跨用户和 snapshot 后插入排除；保留历史不可验证错误。
本节是契约自审与执行依据，不是第三方独立 review 或验收通过记录。

查询 checkpoint：先复现两个产品接口的公司级 409，再接入共享完整指标读取。
11 项新增/调整的边界及产品回归通过（194.57 秒），包含 1,080 条历史候选、330 条
current 事实的 stock facts 和 workspace 完整返回、单指标两级超限、指标发现超限、
其他用户和 cutoff 后回填 created_at 的数据排除、历史 authority 错误保持 typed 409。
原有 source reconciliation 的同槽位与递归检查未修改；扩大回归仍在运行。

自审假设“无 owner 非 SEC 行可挤占限额”被现有 `ck_metric_facts_source_owner` 数据库
约束直接否定；没有为不可能的行增加实现。测试错误尝试 UPDATE manual created_at 也被
既有不可变约束拒绝，负例改为在 INSERT 时提供旧时间，未放宽约束。

SEC 五文件聚焦回归最终为 458 passed / 364.64 秒（包括 lineage、migration、publication、
gold acceptance）；尚非完整 closing gate。内部浏览器仍停在登录页，已非阻塞请求用户登录。
较大响应测试耗时明显；单独只读测量 10 次 mapping identity 重载耗时 0.545 秒。
先记录真实页面影响，再判断是否为交付阻塞，不先增加缓存或扩大性能重构范围。

兼容性自审发现 64-key 发现上限不应限制原来可读的小公司。新增 65 个指标各一行反例先 red，
随后保留原有 <=1,000 历史候选完整路径；仅旧路径超限才进入 64-key 大历史分单元路径。
不是增加原有常量，且不削减完整比较。六项纯边界回归通过；此前扩大查询/研究/SEC 来源
回归为 74 passed / 222.02 秒。完整 gate 将覆盖最终兼容性修正，不能用之前结果代替。
本次续跑前一目标回合属于有效等待：通过活跃测试 session 取回进度；本回合已实际修改、
测试并提交必要查询修复，而非只重复状态。
