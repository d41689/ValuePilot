# 单家公司研究 S1 — AAPL 数据可用性

日期：2026-09-09

状态：已批准的 negatedLabel 修复已通过完整代码验收，开发库已升级。
尚未向开发库导入 AAPL 财务，未外部拉取；S1 尚未完成。

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

最终只读确认：开发库 SEC parse runs=0、metric facts=0；运行模式为 replay，SEC/13F 调度和 worker 关闭。
保留验收库/文件未修改、SEC 外部请求为零、生产未修改、未 merge。
PR #147 保持 Draft：S1 数据回放、canonical publication 和用户可读性尚未完成。
