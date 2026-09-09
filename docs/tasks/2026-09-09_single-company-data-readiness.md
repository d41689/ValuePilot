# 单家公司研究 S1 — AAPL 数据可用性

日期：2026-09-09

状态：只读 preflight / 缺口定位中；未写数据库、未外部拉取、未完成验收。

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
  已另行请求批准最小 parser/PRD/新增 guard migration 修复；批准前不修改生产解析或数据库规则。
- 现有 `build_retained_financial_replay_client` 成功只读验证 AAPL 的 2,902 个 URL、318,544,064 bytes，
  missing instances=0，external requests=0。可复用现有路径，不需要通用导入平台。
- 常驻 `valuepilot-dev-api-1` 实际挂载 `ValuePilot-source-contract/backend`，不是本工作树。
  首次 `docker compose exec ... -k negated_label` 只得到 79 deselected（exit 5），不构成 red/green 证据。
  迭代使用当前 compose 的一次性容器；closing gate 再核实并重建到当前工作树。
- 已加入 8 个 negated-label 参数化测试。当前工作树执行
  `docker compose run --rm --no-deps -T api pytest -q tests/unit/test_sec_statement_authority.py -k negated_label`
  得到 8 failed / 79 deselected：新增显式 opt-in 参数尚未实现（TypeError），属于 test-first red，
  不替代上面的真实报表复现，也不是应用原有测试回归。测试仍在本地，生产代码/迁移尚未修改。

## Test plan / sign-off

### 待批准的最小契约变更

仅为新的 parser 版本启用精确 URI `http://www.xbrl.org/2009/role/negatedLabel`：
当既有 presentation arc 与 label 校验通过时，比较 `-display × scale` 与原始规范化值；
其他 label 保持既有比较。原始金额、canonical mapping、正 scale、证据身份均不改。
禁止 `abs()`、按名称猜符号、接受相似 URI，或为了通过而接受两种符号。
新 migration 只扩展版本识别及对应数值校验，不改旧 migration；旧 parser 保持原语义。
迁移测试须证明升级/空历史降级可逆、存在新版本 lineage 时拒绝破坏性降级，
并实际验证数据库拒绝错误符号/金额而接受证据明确的显示反号。不能只检查 SQL 字符串。
批准前这段仅为审查提案，不修改 PRD 或运行时权限。

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

另做 `git diff --check`、实际数据证据核对及用户浏览器验收。以上本轮均未声称完成。
