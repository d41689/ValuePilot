# ValuePilot 投资者价值代码审计

日期：2026-09-09

审计基线：`main` / `18c7f15eab779529d368456a1b3078c1166e61d5`

状态：审计观察与产品建议；不是新的架构、数据契约或产品验收通过声明。

## 1. 本次任务与范围

用户要求保存前一轮审计，并制定禁止过度设计的最小修改计划。
本文件保存审计判断、功能排序、证据和局限；执行建议见
[单家公司最小研究计划](../plans/single-company-research-minimal-plan.md)。

- Goal / Acceptance：保存完整的主要审计结论；计划说明复用、最小改动、非目标、验收和停止条件。
- In scope：本审计、最小计划，以及 BACKLOG 中对应问题的关联记录。
- Out of scope：业务代码、数据库迁移/导入、网络抓取、生产操作、commit/push/PR。
- Files to change：本文件、上述计划、`docs/BACKLOG.md` 的 FT-08 补充。
- Authorities：`AGENTS.md` 产品北极星；PRD §G.2–G.4、§H.9–H.11；
  Research Decision Support Architecture；mapping spec；source policy。
- 本轮文档检查：证据代码定位、相对链接、diff 格式、范围与既有契约一致性。
  本轮未运行应用 closing gate，不宣称代码可发布；后续实现必须执行计划中的完整 Docker gate。

审计方法是全仓功能盘点、核心读写调用链和关键代码审查，加开发库及保留验收库的只读检查。
不是约 13 万行代码逐行穷尽审查，不是完整安全审计，也不是生产环境或完整浏览器验收。
代码、迁移和前端测试的混合行数仅用于认识规模，不能据此单独认定过度设计。

数据库计数及运行配置是上一轮审计时的快照，本文件落盘时未重复查询或改变这些数据库。
后续执行必须重新验证，不能把快照当作持续有效的环境状态。未检查生产数据，未读取密钥。

## 2. 核心判断

ValuePilot 已建立扎实的数据可信性基础、较完整的 13F 发现工具和人工研究记录能力；
但“在应用内利用真实财务理解企业，并形成自己的投资判断”的关键流程仍未打通。
接口和审计能力完成，不等于核心用户价值已经验收完成。

用户最需要回答：

> 这是不是我理解的好生意？它实际能给股东留下多少钱？什么会让我永久损失本金？
> 什么价格值得承担风险？后来的事实有没有推翻我的判断？

核心交付物是一份可追溯到证据、包含假设和反方论证、由用户亲自确认并能复查的研究结论。
更多字段、排行榜、通知和精确的单点价格不是替代品。

## 3. 代码能力与真实数据状态

| 检查对象 | 审计时观察 | 不能据此声称什么 |
| --- | --- | --- |
| 当前开发 API 的 `valuepilot`，revision `20260909120000` | `metric_facts`、`pdf_documents`、`stock_prices`、`research_cases`、`sec_raw_xbrl_facts`、`sec_metric_publications`、经济分类审查和 coverage requirements 均为 0；13F 数据存在 | 不是整个系统无数据，也不是数据丢失或生产环境状态 |
| `valuepilot_acceptance_ft04_gold_20260901_b`，revision `20260901230000` | 525,837 raw facts；2,414 SEC metric facts；2,961 publication decisions；8 家公司、6 类指标 | 不是当前应用已有完整、可比、可用于估值的十年财务 |
| `valuepilot_acceptance_step_d_gold_20260830`，revision `20260830140000` | 1,339,476 raw facts；0 metric facts | 抓取/解析成功不是产品财务发布成功 |

8 家为 AAPL、BAC、COST、JPM、MSFT、NKE、PEP、WMT。6 类 canonical 指标为：
`is.revenue`、`is.gross_profit`、`is.operating_income`、`is.net_income`、
`per_share.eps`、`equity.weighted_average_diluted_shares`。
这些数量包括期间/版本，不是当前可用槽位或完整覆盖的证明。
例如该库存中 BAC 没有 FY 记录，MSFT 最晚期间为 2022-12-31；不能将“8 家”解释为“8 家全部完成”。

该数据集尚未提供经营现金流、资本开支、现金、债务等完整的经济分析基础。
这不表示 raw facts 或 mapping 代码一定没有对应能力，需要按目标公司进一步定位。
保留库属于旧版本验收资产：不能把当前应用直接指向旧库，或直接复制 metric facts 绕过 lineage。

当前开发配置中 commercial/development market-data 开关均关闭，通知 scheduler/delivery 也关闭。
provider 名称已配置不等于授权或启用；代码存在不等于价格/通知服务正在运行。

## 4. 功能优先级及完成度

按用户能力归类，而非按每个 API 排序。P0 是核心判断；P1 是日常闭环；P2 是效率；P3 暂缓。
基础授权、证据可信性与数据保护是底线，不是可随意删去的低优先级功能。

| 顺序 | 功能 | 最重要的用户目标 | 当前判断 |
| --- | --- | --- | --- |
| P0-1 | 财务历史、证据、来源比较 | 知道数字含义、来源、期间及可比性 | SEC/VL 解析、发布、纠错、reconciliation 基础较完整；当前产品数据闭环未完成 |
| P0-2 | 能力圈、商业模式、护城河 | 判断是否理解企业及优势能否持续 | thesis/证据可记录，缺问题驱动工作区 |
| P0-3 | 资产负债表与会计风险 | 识别偿债、融资和盈利质量风险 | 部分指标、评分存在，缺完整研究视图 |
| P0-4 | 正常化 Owner Earnings | 估计维持竞争力后归属股东的经济收益 | 有简化代理公式，不是完整盈利调整工具 |
| P0-5 | ROIC、增量回报、资本配置 | 判断增长是否创造价值及再投资空间 | 主要消费 VL return-on-total-capital 代理；非完整增量 ROIC 分析 |
| P0-6 | 估值区间、敏感性、安全边际 | 看清假设和下行情景 | 人工区间可保存；system valuation 明确 unsupported；旧 DCF 不算完成 |
| P0-7 | 反方、否证条件、决策记录 | 主动找错并保留当时理由 | 证据、风险、版本、人工决策存在；反方/kill criteria 多为自由文本 |
| P1-8 | Thesis 监控、定期复查 | 识别经营事实对原判断的影响 | 复查/coverage/13F/价格类触发存在；经营变化→论点影响未完整实现 |
| P1-9 | EOD、Watchlist | 用本人估值和价格安排研究注意力 | 统一价格契约和消费路径存在；当前开发未启用且无价格 |
| P1-10 | 组合与持仓日志 | 解释资金风险和调整理由 | 人工组合、追加事件已实现；非完整组合风险分析或券商账本 |
| P1-11 | 投资复盘 | 区分过程、运气和结果 | 版本历史存在；专门投资复盘流程未完成；calibration 页面不是投资复盘 |
| P2-12 | 13F / Oracle’s Lens | 发现值得独立研究的公司 | 实现较深；延迟持仓、分数不代表当前持仓、成本或内在价值 |
| P2-13 | Screener、公式、F-score | 筛出候选而非给出投资结论 | 引擎和评分存在；筛选偏 JSON 操作，财务数据不足限制实际价值 |
| P2-14 | AI 阅读和反方辅助 | 节省阅读、揭示冲突 | 未找到完整可用 AI 研究链路；架构设计不等于实现 |
| P2-15 | 邮件/Slack 通知 | 送达真正重要的研究事项 | 基础设施较多；当前开发调度/外发关闭，研究事件质量先补 |
| P2-16 | Coverage 与运营工具 | 解释缺什么以及怎么补 | 后台能力较多，研究者的直接补证据入口不足 |
| P3-17 | 更多公司、外国发行人、长期价格历史 | 扩大研究范围 | 部分实现/待验收；先服务已有公司；已使用序列的可比性不能延期 |
| P3-18 | 实时行情、券商、交易 | 交易便利 | 非当前核心；交易 rails 不在已授权产品边界内 |
| P3-19 | Quant / 回测 | 验证系统策略 | 数据审计与计划为主，不是完整量化系统 |
| P3-20 | Put underwriting | 分析接货义务及补偿 | 理念为主，股票研究成立后再考虑 |
| P3-21 | 完整账户注销/隐私运营 | 多用户完整生命周期 | 部分保护存在；按用户要求延期，不继续扩大个人应用范围 |

## 5. 具体限制与证据

### A01 — 数据越完整，研究工作区可能越空

`source_reconciliation.py` 的 `MAX_RECONCILIATION_FACTS=250`；
`research_workspace.py` 超限后执行 `facts=[]`，返回 `reconciliation_bound_exceeded`。
前端 `research/cases/[id]/page.tsx` 仅渲染 `fundamentals.slice(0, 60)`，按指标 key/期间排列，未提供该列表的完整翻页。
30 指标 × 10 FY 已可能超过 250，尚未计季度、多来源及 lineage 依赖。

证据：[上限](../../backend/app/services/source_reconciliation.py)、
[工作区](../../backend/app/services/research_workspace.py)、
[页面](../../frontend/app/(dashboard)/research/cases/[id]/page.tsx)。

落盘复核补充：PRD §H.10 **明确规定**当前全局超限时不得返回数字前缀。
因此这是契约/查询范围与十年研究目标不匹配，不是随便修改常量的局部 bug。
需要先审查相应 PRD 调整，再按完整比较单元有界查询、分页；不能截断候选后声称无冲突。

### A02 — DCF 被方法政策明确阻止

`20260904150000-method-applicability-gates.py` 中普通公司 system valuation 是
`system_valuation_method_pending_ft09`；`dcf_inputs.py` 在取值前同时要求 Owner Earnings 和 system valuation 获准。
这是刻意的安全边界。补数据不等于可以打开系统估值；人工估值权威仍独立存在。

证据：[政策](../../backend/alembic/versions/20260904150000-method-applicability-gates.py)、
[DCF 输入](../../backend/app/services/dcf_inputs.py)、PRD §H.11。

### A03 — 有方法审查门槛，缺日常操作入口

经济分类及 high-SBC/acquisitive/cyclical/commodity-exposed 审查通过 admin API 写入，
缺少完整前端流程。未知或适用性不支持会阻止相关计算。
保留审查，不得凭 ticker/行业名称默认放行；个人使用也不应长期依赖直接调用 API。
首批人工研究不依赖开放这些系统方法，故无需先开发一套审查平台。

证据：[admin API](../../backend/app/api/v1/endpoints/admin.py)、
[方法门槛](../../backend/app/services/canonical_financials.py)。

### A04 — Owner Earnings 是代理公式，不是经济分析完成

当前为 `EPS + depreciation / shares - capex_per_share`；正常化取最近最多五个 FY 的中位数，
不是保证五个连续可比年度的周期调整。政策明确把全部 capex 当维护投入。
缺少维护/增长 capex、必需营运资本、收购、周期、SBC/稀释等可解释调整。
SBC 必须按盈利或现金流起点处理，不能机械重复扣除。

证据：[Owner Earnings](../../backend/app/services/owners_earnings.py)。
投资方法依据：[伯克希尔 1986 年股东信](https://www.berkshirehathaway.com/letters/1986.html)，
其中维护竞争地位所需资本投入及增量营运资本包含估计，并非自动精确观测。

### A05 — 旧 DCF 缺少重要的悲观表达

前端 `DEFAULT_TERMINAL_YEARS=1000`，后端 `_model_rate` 要求非负。
收缩、回报率下行等重要情景不能由现模型充分表达。
当前该系统路径被门槛阻止，不能声称它正在向用户发布错误估值；问题是未来不能直接重新开放旧模型。

证据：[DCF 页面](../../frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx)、
[计算约束](../../backend/app/services/dcf_inputs.py)。

### A06 — 界面仍偏数据检查，而非公司研究

股票摘要主打价格、PE、F-score、13F 持有人；研究页面是指标列表、文本和手填区间。
用户仍需在系统外把数字组织成历史，再转化为商业判断。
`StockPriceChart.tsx` 等空 scaffold 不能计为已完成图表。

证据：[股票摘要](../../frontend/app/(dashboard)/stocks/[ticker]/summary/page.tsx)、
[研究页面](../../frontend/app/(dashboard)/research/cases/[id]/page.tsx)。

其他应明确展示的边界：人工估值仅 USD；VL 支持范围以文本层模板为主；
不可变决策历史不等于全工作区历史 PIT 重放；reconciliation 后端不等于用户已有完整处理冲突的界面。

## 6. 过度开发判断：错在顺序和投入比例，不是全部推倒

| 领域 | 当前相对过重之处 | 建议 |
| --- | --- | --- |
| 13F 评分、排名、后台 | 候选发现深，发现后的企业研究浅 | 维护正确性，暂停新评分和后台扩张 |
| 通知 | 偏好、投递、重试等基础设施领先于 thesis 事件质量 | 先复用站内复查，渠道扩展延期 |
| 宽范围数据验收 | 多形态、多公司成本先于少数公司实际可用 | 保留完整目标，先做明示范围的个人使用切片 |
| 多消费者判断编排 | 来源、时点、方法逻辑重复编排提高一致性成本 | 固定共享契约和测试，触及处小幅收敛，禁止另造 truth 服务 |
| 账户生命周期 | 个人使用收益小、写入路径影响广 | 维持已明确延期，不拆掉现有保护 |
| 导航 | 研究、通知、组合和管理入口并列 | 后续可下沉管理入口；首批不做全站重设计 |

必须保留：事实/证据/用户判断分层、per-period current、版本和 known-at、来源及币种区分、
权限、未知/冲突可见、方法适用性、用户显式接受。减少范围与操作复杂度，不降低可信度。

## 7. 原审计建议及最短路线

1. 已有数据进入当前应用；消除容量障碍；让公司页按研究问题组织财务、证据、判断。
2. 补齐核心现金流/资产负债信息，再做盈利调整和受控情景估值。
3. 授权 EOD、Watchlist 与关键经营假设复查；保留旧判断，不让系统自动决定。

不是三批全部一起开发。最小首批采用已有人工估值与 revision，
不要求新 DCF、AI、报价商、通知平台或剩余公司先完成。
新计划是对执行范围的收敛，不撤回本审计列出的缺口，也不等于 FT-04/08/09 或整套 Beta 已完成。

详细验收与停止条件见[最小计划](../plans/single-company-research-minimal-plan.md)。
已有问题归于 [BACKLOG FT-04–FT-15](../BACKLOG.md)；A01 及操作解释缺口关联 FT-08。
任何发现的额外问题先登记，不借本计划启动全仓重构。

## 8. 文档交付检查记录

- 已对照当前 main 的 A01–A06 相关代码和 PRD §H.10–H.11，区分实现限制与明确契约。
- 数据快照保留原环境、版本、范围及未验证事项，不提升为产品可用性证明。
- 计划复用现有事实和研究权威，不新增架构规范；不修改 locked gold-set 或完整 Beta exit gate。
- 本次仅文档落盘；业务实现、真实数据导入和产品验收尚未执行。
