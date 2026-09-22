# 企业经济性阅读——S2收尾后的最小分析切片

日期：2026-09-10。基线：`1065f692`，当前S2依赖分支；未推送或合并。
状态：本轮最小切片已实现，独立复核、真实只读数据核对、代理浏览器验收和完整本地Docker门禁均通过。S2用户本人AC9及远端CI/合并仍待完成；本轮未commit/push/部署。

## Goal / contract

让非金融企业研究者从合法财务理解经营利润与现金的关系，并知道为何目前不能可靠判断ROIC、完整偿债能力或每股价值。推进AGENTS的企业质量、历史经济性和主动否证工作。

S2工程交付已提交，旧完整门禁2809/259与浏览器记录保留。用户本人AC9走查、独立复核和对应远端CI/合并不伪造为完成；本轮更新收尾索引，检查复核中的真实阻塞。新代码继续依赖尚未合并的S2，不重新移植到缺少依赖的main；未授权commit/push/PR/merge。

## Read-only inventory

在Docker API中以显式`SET TRANSACTION READ ONLY`核验：database=valuepilot、role=valuepilot、migration=20260909150000。股票66的legacy exchange=US不是canonical listing；SEC reviewed identity为CIK0000320193。不重新决策身份。

正常workspace服务、测试用户2/case2、snapshot=2026-09-10T23:17:56.105685Z：834个fact、225个state、1059明细，年度窗口FY2016–2025。没有使用原始记录作为产品truth。

| 材料 | FY2023 / FY2024 / FY2025，精确基准值（USD） | 产品可用性 |
|---|---|---|
| Revenue | 383285000000 / 391035000000 / 416161000000；fact2179/2189/2198 | 已合法返回，十年都有 |
| Operating income | 114301000000 / 123216000000 / 133050000000；fact2073/2083/2092 | 已合法返回，十年都有 |
| Gross profit | 169148000000 / 180683000000 / 195201000000；fact1805/1815/1824 | 已合法返回，十年都有 |
| CFO | 110543000000 / 118254000000 / 111482000000；fact1977/1983/1988 | 已合法返回，十年都有 |
| PPE capex | 10959000000 / 9447000000 / 12715000000；fact1499/1505/1510 | 已合法返回，十年都有 |
| Cash、长期债务两部分、权益 | 正常workspace已返回；现金2016–18无可归属事实 | 可看事实，不能据此称完整净债务或投入资本 |
| 税项、商业票据、租赁、折旧 | 最近三份10-K的retained raw概念存在；查询仅count、concept、run数 | 不是canonical可读分析输入；存在不等于范围/期间/authority均证明 |
| ROIC | 无可用税后经营利润/完整投入资本调整契约 | 另受PRD H.11 reviewed method限制；不是补前端公式即可完成 |
| 每股趋势 | 有EPS与股数，缺权威拆股可比性 | 保留原始点，不跨年推算 |

原始概念计数包括历史parse版本、重复与维度，不代表独立观测，也不代表新增发布已获授权。未查询保留验收库、未改写文件、未采集、未发布/重放。净利润等S2证据基准沿用S2任务。

## Acceptance criteria

1. 从同一financial_history响应展示十年内可选FY、最新三年小表：营业利润率、毛利率、CFO减PPE资本开支；不自动评定生意好坏。
2. 每个显示计算有版本、公式、精确输入值、fact/publication身份、期间/币种及既有认证证据入口。比率以精确有理数计算后显示两位百分比；现金差额保留精确十进制；不经Number损失精度。
3. 仅唯一、完整FY、SEC primary as-filed actual、空维度、明确映射身份的操作数进入算式。跨来源/期间/币种/版本、重复、未知身份、阻塞或不完整状态均fail closed；不从竞争候选挑一条。分母≤0比率不可算，负营业利润率合法。负capex不擅自反号。
4. 三项计算只用于阅读、不持久化、不新增metric key、不进入筛选/估值/评分/方法发布。CFO−capex不叫owner earnings，不擅自减SBC或估维护性capex。H.11不变。
5. ROIC、净债务/偿债能力、每股价值缺口以明确的“本视图尚不计算/尚需证据和审批”说明呈现，不能声称SEC没有披露。保留既有现金/债务/SBC事实入口。
6. 用户显式选择“研究此计算”才将标明为display calculation的事实背景追加到五步observation；不覆盖原笔记、不生成解释/判断、不自动附为已核验引用、不自动保存。terminal与保存中不可修改。旧保存流程不变。
7. 测试先行；极值/小非零/负值、候选歧义、状态作用域、未知FY、refresh、组件渲染/按钮行为与浏览器桌面/窄屏可读性有证据；完整Docker门禁通过后才称完成。

## Scope / non-goals

修改前端阅读、纯函数及测试，必要的标签复用；PRD记录严格局部展示计算契约。不修改后端、schema、mapping、parser、方法policy、publication、facts/currentness、权限、网络采集或持久数据。所有业务数据只读，本轮不保存测试revision；用临时草稿验证并准确清除本轮草稿。保留storage与两项原有Next配置差异。S2复核若发现真实问题只修与收尾直接相关的最小范围，先记录证据。

S2收尾复核F1（真实、in-scope）：head2存在未追加五步笔记，refetch收到head3时page的draft-loading effect替换draft并清dirty。旧localStorage记录尚在，但活动页面不再恢复。独立reviewer执行实际effect已复现，root静态确认。先加实际effect回归，再将dirty draft固定在loadedHead，提示冲突；仅明确确认丢弃后加载最新revision，expected-head不随财务refetch自动前移。

## Files to change

- frontend/lib/businessEconomics.{js,d.ts,test.js} 与组件渲染测试
- frontend/components/research/BusinessEconomics.tsx
- AnnualFinancialsTable.tsx / FinancialEvidencePanel.tsx / research case page
- 共用必要的财务身份检验及人类标签；不改变九项核心/90位置的S2分母
- docs/prd/value-pilot-prd-v0.1.md、S2收尾记录、BACKLOG与本任务

## Test plan / stop rule

先red纯函数与实际组件测试，再green；按AGENTS的精确完整命令，在既有离线override关闭EDGAR/13F/通知后执行：

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
git diff --check
```

预检无新migration且开发库已head；pytest使用新生成valuepilot_pytest_<hex> schema并自己回收，拒绝生产库；不清理既有schema。采样wall/monotonic防时钟回退。验收标准有证据、有效复核问题已处理、全门禁完成即停止；缺少更大ROIC方法/数据授权不通过扩大本轮范围解决，明确留待下一切片。

## Execution evidence

- Test-first：businessEconomics先因模块缺失red；7项精确算术/身份/作用域/研究追加测试green。实际组件渲染先因组件缺失red，再验证公式、可读精确操作数、证据按钮、只读与缺口文案。fixture修正仅补齐本来缺失的source_type和匹配真实364天期间长度，没有弱化断言。
- S2 F1：执行真实page AST中的effect、storageKey、updateDraft、mutation与discard callback。初始1pass/5fail；修复后9项green。覆盖dirty notes/thesis、新head/同head/clean、旧head存储和expected head、不清冲突、409后先refetch再确认、失败/取消保留。独立review发现discard原先使用缓存workspace的问题，root确认后改为成功获取新data后再确认/替换；独立复验通过。相同明确丢弃动作对普通dirty草稿也可见，不新增保存流程。
- 独立经济性复核：29项聚焦测试通过；额外精确小数边界与实际page onResearch callback的可编辑/terminal/conflict/pending四种分支通过。无有效阻塞finding；不把聚焦测试冒充完整门禁。
- 真实只读证据：CORE9×最近3FY的27项，加营业利润/毛利×3FY的6项，33/33 `resolve_evidence`返回available，fact/publication和精确值与workspace一致。这是服务层READ ONLY核验，不冒充33次浏览器认证点击。
- 实际服务输出经管道传入Docker Node执行**产品businessEconomics函数**：snapshot `2026-09-10T23:36:17.146357Z`；核心90位置仍为87数值/3缺口；新计算3×10年=30/30可用。不是从raw临时拼接。

| 新显示计算 | FY2023 | FY2024 | FY2025 |
|---|---|---|---|
| Operating margin | 29.82% | 31.51% | 31.97% |
| Gross margin | 44.13% | 46.21% | 46.91% |
| CFO−PPE capex，精确USD | 99584000000 | 108807000000 | 98767000000 |

- 浏览器：正常登录的专用case2，三项选择和FY2023/2025显示与上述真实结果一致；Operating income#2092从组件按钮经认证打开CONSOLIDATED STATEMENTS OF OPERATIONS，12 Months Ended Sep.27,2025，原文133,050、倍数1,000,000、归属publication2350，未访问外部SEC链接。
- 浏览器显式Research this calculation：先填写临时observation前缀与解释，点击只追加标明display calculation的事实背景；解释保持逐字不变、Save禁用。Refresh financials完成后笔记逐字不变，Gross margin/FY2023选择重置为Operating margin/FY2025。新head冲突分支由上述真实effect行为测试验证，本轮未为造该场景写业务revision。
- 浏览器清理：使用正常UI丢弃本轮临时草稿，先refetch后confirm。五步observation/explanations为空、Save禁用；原thesis/证据和case2两条旧revision保留。本轮未点击Save或写新revision。
- 390px时business-economics区域client/scroll均288，document client/scroll均390；1440px时区域均1074，document均1440。展开S2年度表后仍然一致；已看两尺寸截图，无横向裁切。临时viewport override已reset。
- 最终build和浏览器重开后，Next生成配置已恢复为本轮前的用户改动；未改storage。构建后DOM再次确认营业利润率FY2025存在、五步observation/explanations为空、Save禁用。浏览器role定位器读取文本框曾超时，随后直接只读DOM核验同一字段成功；不将该工具超时误报为产品故障。
- S2文档收尾同时将PRD遗留的显示单位“millions”更正为当前已批准v1.3和实际页面采用的“billions”；不是修改base-unit事实或再次缩放数值。

完整门禁运行记录：pytest PID24/start_ticks9456368，运行前17个既有pytest schema。只读时钟监控PID29每45秒采样；Docker构建日志出现过负elapsed显示，不能单凭构建日志判定数据库回退，以独立wall/monotonic样本为准。

### Final canonical gate（本地工作区，不是远端CI）

依次运行AGENTS完整命令，沿用`/tmp/valuepilot-s1-offline.ZdCsgo/compose.offline.yml`；实际环境预检确认replay且EDGAR/13F worker、smart retry、seed和通知均关闭。

| 命令 | 实际结果 |
|---|---|
| `docker compose up -d --build` | exit0，未重启共享Postgres |
| `docker compose exec -T api alembic upgrade head` | exit0，20260909150000，无新迁移 |
| `docker compose exec -T api pytest -q` | **2809 passed，2 warnings，1191.72秒，exit0** |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | **276 passed，0 failed/cancelled/skipped，exit0** |
| `docker compose exec -T web npm run lint` | exit0 |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | exit0，TypeScript及27静态页通过 |
| `git diff --check` | 最终检查通过 |

两项backend warning是既有Starlette/httpx与AnyIO弃用提醒。后端测试期间仅将已测试的前端“明确丢弃草稿”入口扩展为dirty或conflict时可见，复用同一个确认handler并运行14项聚焦回归；最终前端全套/lint/build均针对该版本，后端未修改。

监控完成24次采样：23:30:58.387330Z/monotonic94593.98679154至23:48:13.369778Z/95629.079889468；没有样本间倒退，最大相邻wall/monotonic增量差约111毫秒，不宣称采样之间无调整或时钟永久修复。全套后23:50:41.114439Z/95776.82493166只读复核：migration不变、pytest schema数仍17；共享metric_facts=2390、SEC parse runs=84、case2 revisions=2，与运行前完全相同。无新增财务/研究数据、采集、重放或既有schema清理。

### Remaining conditions / non-goals

- 本轮是代理工程/浏览器验收，不代替用户本人最终阅读认可；S2 AC9的人工作业和对应提交远端CI/合并仍单列等待，不伪造全S2/S3/Beta PASS。
- ROIC、完整债务/偿债、owner earnings与每股复利仍需后续数据和方法契约；见BACKLOG本轮盘点条目。没有把这些后续项冒充已经计算。
- 浏览器新head并发分支通过实际组件代码行为测试验证，未为测试写新业务revision；未独立运行全浏览器/全权限/全经济类别矩阵。既有来源与权限边界仍受全量后端测试约束。

## Consolidation follow-up — 2026-09-22

The user authorized scoped review/fixes and delivery in the branch-consolidation plan. Preserve this existing feature separately from S2. Independent pre-integration review reproduced a brief head-change boundary: after the workspace refreshes to a newer revision but before the passive effect raises conflict, the calculation append callback can still add newer context to the older dirty draft. The scoped repair will check loaded-versus-current head directly in both read-only rendering and the callback, preserving terminal/conflict/save guards. Add a regression executing the actual callback before changing production code. Final integration, full CI and merge remain pending; the historical local/browser results above are not certification of the later delivery tree.

The follow-up now checks loaded-head identity directly in rendering and the actual append callback. Regression first failed before the guard; the corrected research-reading group passes 4/4. Independent re-review passed 21 focused Docker tests (businessEconomics, researchReading, financialTrends), including each blocked state and aligned append with other note fields preserved and zero POSTs. No remaining scoped finding was reported. This is still the original working-tree baseline, not the eventual integrated delivery: port only the economics changes and retain S2's separately fixed cached-409 conflict latch. No new business-data or browser verification is claimed.

## 2026-09-22 isolated consolidation delivery

The user authorized integrating existing reviewed work, including this previously uncommitted slice. Prepare it in a fresh isolated delivery branch from the repaired main, incorporating the reviewed S2 dependency while its final gate runs. Before delivery, incorporate the completed main chain (migration repair, S2, MCO and Lab documentation); run all canonical Docker CI gates on that final combination. Do not replay business data or expand the feature.

Acceptance: port the approved descriptive arithmetic and explicit local-note action; preserve the newer S2 evidence redaction, cached-head conflict latch, and pending-save draft guards; retain exact decimal math, fail-closed operand authority, and existing uncomputed-method boundaries. Only Economics additions belong in the product diff. Never copy the source checkout's older page over the integrated S2 page. Independent combined review and full final CI are required; earlier runs remain historical.

Port verification: the existing integration regression first rejected the unconnected S2 page (`Missing readOnly expression`). Adding only the approved seven integration lines made all four focused groups pass (33/33). Independent read-only port review is PASS: ten Economics source/test/PRD files match the original source exactly, and no S2 page line was removed. The full frontend glob passes 280/280 using a complete read-only frontend mount in Docker. A preliminary partial mount lacked `next.config.js` and failed the build-isolation harness; that was corrected by mounting the complete frontend, with no product-code workaround. Final integrated-main canonical CI remains required.
