# S2——单家公司核心财务历史与证据阅读闭环

日期：2026-09-10

状态：v1.3 改版已实现；用户临时修复时间后，本地完整Docker门禁重新全部通过（后端2809、前端252，详见§16）。此前浏览器核对通过，用户阅读验收仍待确认，不能宣布S2最终完成。时钟永久修复及根因未独立验证；§15失败记录保留。未commit/push，本轮不是远端CI结果。

后续PO体验验收：用户要求代理以价值投资者视角实测页面，结果为**CHANGES REQUIRED（体验层面）**。已复现年度表展开导致当前窄窗口图表撑宽裁切，另有信息顺序、证据阅读层级及来源覆盖文案问题；详见[PO体验报告](2026-09-10_s2-po-experience-review.md)及BACKLOG PO-01–PO-04。工程门禁通过记录仍有效，但不代表这些体验问题已解决；本次未修改产品代码或研究revision。

后续实施：用户随后授权阅读修订和五步研究路径；PO-01–PO-04已实现并通过对应浏览器复验，移出BACKLOG。专用case2追加了验收draft revision2，未修改revision1、估值或决定。当前交付范围和本轮完整门禁见[reading-first任务](2026-09-10_reading-first-research-path.md)，不是把此处历史门禁复用为新实现门禁。

修订依据：[逐项核实与处理记录](2026-09-10_s2-review-resolution.md)。§1–9的完整性与证据契约继续有效；§15记录用户新增批准的信息层级、YoY和图形化范围。新增响应结构已在本地实现并同步PRD。历史工程结果见§12–14，不能将方案批准等同于最终交付。

## 1. 任务选择与用户价值

本任务选择[价值投资用户故事优先级](../plans/value-investor-user-story-priorities.md)的第 1 项：让投资者在现有研究页面，读懂核心年度财务并核验证据。

这是最高价值故事的一个可独立交付部分。可信财务是企业分析、owner earnings 和估值的共同基础；目前已有的数据和后端能力，也使这项任务可以用较小修改产生直接价值。

对应 AGENTS 的工作：理解企业质量、重构可信历史经济性、为估值提供事实基础，以及通过原始证据主动否证。成功以真实用户能完成财务阅读、核验和引用来观察。

### 用户故事

> 作为长期价值投资者，我打开一家公司的研究案例后，能按年度阅读核心财务，理解指标口径和数据缺口，点击数字核验其来源，并将该事实引用到自己的研究记录中。

首批真实验收固定为 **AAPL、stock 66、FY2016–FY2025**。组件按公司通用设计，本次不扩展数据采集范围，也不把完成 AAPL 验收称为全市场覆盖。

## 2. 权威契约与基线

- [AGENTS.md](../../AGENTS.md)：数据不变量、任务记录、测试先行和 Docker closing gates。
- [单家公司研究最小计划](../plans/single-company-research-minimal-plan.md)：S1/S2/S3 的顺序、范围和用户验收。
- [S1 任务记录](2026-09-09_single-company-data-readiness.md)：已保留 AAPL 数据、身份、截止日和验收材料；实现方声明仍须按本任务需要核实。
- [PRD](../prd/value-pilot-prd-v0.1.md)，尤其 §H.10 完整指标单元读取，以及现有研究 revision、证据和来源契约。
- [Research Decision Support](../architecture/research-decision-support.md)、[数据层](../architecture/data-layer.md)、[current 语义](../architecture/metric-facts-is-current.md)。
- [Mapping](../metric_facts_mapping_spec.yml) 与 [source policy](../architecture/coverage-source-policy.md)：指标、单位、期间及来源权限的权威。

本任务不覆盖上述权威。API 如需新增字段，应在 PRD 同步定义，保持原字段兼容。

实施开始前记录实际代码 SHA、S1 依赖状态、目标环境及 fixture 基准。沿用 S1 的 AAPL 身份：CIK 0000320193、canonical listing NDQ；历史 filing-selection cutoff 为 2026-09-09T00:00:00Z。该 filing-selection cutoff 不等于本次 workspace 的当前数据库 EvaluationSnapshot；新建 lineage 的真实创建/knowledge 时间不得回填。

当前已确认的修改点：

- `frontend/app/(dashboard)/research/cases/[id]/page.tsx` 使用 `fundamentals.slice(0, 60)`，会静默限制事实展示。
- 当前 SEC 证据入口直接链接 API；页面内证据读取应复用 `frontend/lib/api/client.ts` 的认证与 token 刷新机制。
- `backend/app/services/research_workspace.py` 的 fundamentals 序列化需要补齐年度表所需的部分财政期间和来源语义。

## 3. 完成标准 / Acceptance Criteria

| 编号 | 必须达到的结果 | 验证方法 |
|---|---|---|
| AC1 | 固定 AAPL FY2016–FY2025 共十列、九个核心指标共 90 个预期位置；v1.3 默认显示最新 FY 概览与趋势，可展开的年度表突出 FY2023–FY2025。 | 财年和真实期间来自权威元数据；按 §4.3 处理缺年、多期间和其他公司窗口。 |
| AC2 | §4.3 九个 canonical keys × FY2023–FY2025，**27/27 必须具有可用数值、合法 SEC actual 身份及可用原始证据面板**。 | 每项记录 fact/publication ID、精确值、期间、单位及证据核对结果；任何 unavailable 不算通过。十年预期 87 个数值位置和 3 个现金缺口须先只读核实、锁定，不能当成已证明或失败后改分母。 |
| AC3 | 口径、单位、币种、source role、fact nature 和期间均明确；精确值使用十进制字符串。 | 长期债务组成不称为总债务、加权稀释股数不称为期末股数；验证 §4.3 的缩放、舍入、零/NULL/空串和未知元数据规则。 |
| AC4 | fact、slot unavailable、metric unavailable、filing-cycle unavailable 有明确类型与稳定标识；未知原因不推断。 | AAPL FY2016–2018 现金显示“该响应未提供可用事实”，不称为“未披露”；空槽、整指标阻塞和无 metric_key 的申报级状态均可见。 |
| AC5 | 27 个核心单元全部可正常认证打开可读原始证据；其他数字如实显示已有证据能力。 | 按 §4.5 校验三元身份、原始披露文本、精确值、期间、inputs 和 locator；缺定位显示 typed unavailable。非 SEC/其他指标的无 resolver 状态明确显示，不能以按钮存在算通过。 |
| AC6 | 所有安全事实与所有 unavailable 状态在同一响应中可遍历，无静默截断。 | §4.4 固定排序、row_key、总数、页范围；>250 总事实但单元均在界内时完整浏览，单元 251 条时只显示该指标 unavailable；刷新开始新分页。 |
| AC7 | 单元格承载有序 observation 列表和 typed states，不覆盖或任意选优。 | 同财年多来源、多期间、预测、相同值不同身份均保留；页外竞争、递归依赖、失权及晚于 snapshot 的输入仍受共享 guard 约束。 |
| AC8 | 修复 shared SEC 的引用校验和历史重开，复用既有 revision 事务、引用结构和并发规则。 | 非 terminal 测试案例完成“数字→证据→引用→保存→刷新→再次打开”；错误 stock/私有跨用户/无效 lineage 拒绝，历史被替代不换 ID、失权不泄露源数据，旧格式兼容。 |
| AC9 | 工程验证和真实用户验收均通过。 | Docker 内完整 canonical gates 全绿，并记录目标提交、环境、27 项核对和实际缺口；用户完成一次阅读与引用走查。 |

这里的“完整”指窗口和缺口完整呈现、可用事实不被静默丢弃，不要求人为补齐缺失数据。

## 4. 最小实现方案

### 4.1 页面与组件

复用当前 `/research/cases/[id]` 页面、workspace API、来源对账和证据服务，新增两个小组件及纯展示辅助函数：

- `AnnualFinancialsTable`：核心年度表、来源区分、缺口说明，以及“其他指标/季度”展开视图。
- `FinancialEvidencePanel`：数字的证据详情和“添加到研究证据”操作。

将前 60 条事实截断改为遍历同一完整响应的展示分页。SEC 证据改用现有认证客户端请求，再在页面内展示，复用现有登录与 token 刷新机制。

### 4.2 后端必要补充

- 为通过 guard 的事实批量补充已有权威元数据，例如 `fiscal_year`、期间起止、`fact_nature`、`source_role` 和指标显示信息。
- 从现有 canonical metadata、mapping 和 publication lineage 取得这些字段；不在前端按 key 或日期猜测。
- 增加 §4.4 的显式只读投影，在 PRD 中同步定义；旧 `fundamentals` 保留兼容。
- 证据按点击加载，避免初始化时逐个查询所有单元格。详情中的数值、ID 必须与所点击事实一致；失效则明确提示，不能悄悄换成新事实。
- 扩展现有 SEC evidence resolver 的只读证据内容与身份校验（§4.5）；修复现有 revision 服务对共享 SEC 引用的拒绝及历史重开（§4.6）。这两项是完成路径的必要实现，不能再假设现有服务原样可用。

整个财务表使用 workspace 返回的一次读取结果。前端分页只是展示分页，符合现有 PRD §H.10；不新增分页查询导致不同页混用不同时点的数据。刷新是新的读取。

本次预计不需要数据库表或迁移，也不需要修改 parser、mapping 的经济定义、publication 规则或 `is_current`。

### 4.3 年度表的指标、身份与显示契约

局部 presentation catalog 仅规定标签、解释、顺序和显示方式，引用以下已有 canonical keys；不创建经济定义、别名合并或通用指标目录。Mapping 当前未提供这些人类标签，不能声称标签可直接从 mapping 读取。

| 顺序 | 标签 | canonical key | 期间性质 / 单位 |
|---|---|---|---|
| 1 | 营业收入 | `is.revenue` | duration / currency |
| 2 | 净利润 | `is.net_income` | duration / currency |
| 3 | 经营现金流 | `is.operating_cash_flow` | duration / currency |
| 4 | 资本开支（购置物业、厂房及设备） | `cf.capital_expenditures` | duration / currency |
| 5 | 现金及现金等价物 | `bs.cash_and_equivalents` | instant / currency |
| 6 | 长期债务流动部分 | `cap.long_term_debt_current` | instant / currency |
| 7 | 长期债务非流动部分 | `cap.long_term_debt_noncurrent` | instant / currency |
| 8 | 加权平均稀释股数 | `equity.weighted_average_diluted_shares` | duration / shares |
| 9 | 股权激励（SBC） | `cf.stock_based_compensation` | duration / currency |

- AAPL 验收固定十年窗口，不根据响应中的最后一条事实动态缩小分母。正式 UI 不硬编码 ticker 或 stock 66。
- 对其他公司，默认窗口以在本次 snapshot 已可见且合法绑定的 FY actual 年度主表期间为锚：期间已经结束、所属年度及期末有权威证明；最新此类年度为 Y，展示 Y−9 至 Y 的十个年度标签。标签缺少证据的年份保持空缺，不假设 12 月 31 日或 365 天。没有合法锚时显示“年度窗口未确定”，所有事实仍可在明细中浏览。该锚不宣称已经取得全市场最新申报。
- FY 列是展示分组，不是 reconciliation slot。cell 为 `{observations: [...], states: [...]}`，不是 scalar。不同 fact ID、source role、fact nature、定义/维度身份、period basis、起止日期、单位或币种不得覆盖；逐 observation 可查身份。同财年短期间、非可比年度、实际/预测不合并。季度/YTD/TTM/AS_OF 不因年号相同塞入 FY actual；合法 FY 期末 instant 单独显示“期末”。预测放在明确标记的分组/明细，不计入核心实际分母。
- 复用现有后端已证明的比较身份；不能从 key、`period_end.year`、`is_current` 或最高 ID 推定财年/性质。无法证明 fiscal year 的记录进入“财年未确定”明细；不丢弃，也不猜列。
- 服务端从 `metric_facts.value_numeric` 序列化 `value_numeric_exact` 字符串。证据匹配与格式化不得先经过 JS `Number`/`parseFloat`。采用十进制字符串运算；v1.3 概览、图表和年度表统一使用 billion + ISO 币种 / billion shares，保留两位显示小数，详情保留全部精度；小额非零显示为 `<0.01` 或 `>-0.01`，不能显示为真实零。图表仅在精确十进制归一化为有界坐标后使用 Number，不回写值。
- `0` 是零，NULL 是无数值；空串/非法数字是 `invalid_numeric` 显示状态，不补零、不接受为 available。未知币种显示“币种未知”，不加美元符号；未知 basis/nature 明确标未知，不计入 27 项成功分母。实际字段语义以 mapping 为准。

### 4.4 Workspace 显式投影及遍历契约

在同一次已有 workspace 读取中新增 `financial_history` 响应字段（版本 1），保留旧 `fundamentals` 字段。新增 Pydantic/TypeScript schema，不能继续让前端断言所有 `id` 非空。建议形状：

`backend/app/api/v1/endpoints/research.py` 的 `/cases/{case_id}/workspace` 从 `response_model=dict` 切换为兼容的 Pydantic workspace response model，实际绑定并校验新增投影。旧响应字段、其允许的 NULL/Decimal 表达及行为必须保留；不得因只声明新字段而被 FastAPI 响应过滤丢弃。以真实 endpoint 响应测试验证 schema 被使用和旧字段兼容，不能只新增未绑定的类型文件。

```text
financial_history: schema_version, evaluated_at, annual_window,
                  total_rows, available_fact_count, state_count, rows[]
row: row_kind, row_key, status, reason_code,
     metric_key?, fact_id?, publication_id?,
     value_numeric_exact?, value_text?, unit?, currency?,
     period_type?, period_basis?, period_start?, period_end?,
     fiscal_year?, fiscal_quarter?, source_type?, source_role?, fact_nature?,
     comparison_identity?, evidence_capability
row_kind: fact | slot_state | metric_state | filing_cycle_state
```

- 所有 `row_kind=fact` 必须先通过既有 guard，包括仅有 `value_text` 或无数值的事实。元数据批量关联，同 snapshot 做 authority/visibility 校验，不能从失败 guard 的候选再次装回数值或文本。`comparison_identity` 复用既有定义、维度和期间身份；未知字段显式 NULL。
- 只有 `row_kind=fact` 才有非空 fact ID；所有阻塞 state 的数值均为空。状态允许关联 unresolved publication ID，但不得把它当作 numeric fact 引用。
- `row_key`：fact 使用 `fact:<id>`；publication state 使用 `publication:<id>:<reason>`；metric/slot/cycle 使用 canonical scope（stock、metric、期间、来源/比较身份、run/cycle 身份及 reason）的稳定编码。不得使用数组位置或 NULL ID；完全相同的状态才可合并。有稳定 ID 的历史事实不随页码改 key。
- 没有 metric_key 的 cycle state 在表上方显式显示；整指标阻塞在指标行显示，不虚构十个独立缺失事实。
- `not_returned` **由服务端 financial_history 投影生成**，仅适用于已确定年度窗口内的九项核心实际财务预期 cell：该 cell 没有可归属的 observation，也没有已明确覆盖它的 slot/metric/cycle state 时，生成一条 `row_kind=slot_state, status=unavailable, reason_code=not_returned`。前端不再额外合成此类行。
- 这条行仅陈述“本次响应未返回可归属事实，具体原因未知”，不是“SEC 未披露”的证据。`fact_id/publication_id/value_numeric_exact/value_text` 均为空；保留预期 metric_key、`period_type=FY`、fiscal_year，不伪造 period_start/end。稳定 key 为 `expected:<stock_id>:<metric_key>:FY:<fiscal_year>:not_returned`。无权威年度窗口时不生成；其他来源/预测或财年未确定的观察仍保留明细，不用于冒充核心实际事实。
- `not_returned` 纳入 `rows`、`state_count`、`total_rows` 和明细分页；已明确覆盖该 cell 的 metric/cycle 阻塞按自身范围展示，不重复生成年度缺失行。状态范围无法映射时保持原 scope 状态及未知提示，不推断覆盖关系。
- 所有明细提供固定 50 条展示分页。排序按 catalog 指标顺序（其他 key 字典序）、财年降序（未知最后）、实际期末降序、期间性质、source type/role/nature、row_key；不利用排序选来源。
- `available_fact_count = count(row_kind=fact)`（包含通过 guard 的文本事实，不等于核心 numeric 验收数量）；`state_count = count(row_kind!=fact)`（含 not_returned）；`total_rows = len(rows) = available_fact_count + state_count`。页范围以 rows 为分母。明细包括核心及非核心记录，年度表是同一 rows 的另一种展示；说明两个视图不是额外新增数据。循环遍历所有页的 row_key 集合必须恰好等于响应集合，无丢失重复。
- 页面展示本次 `evaluated_at`。展开、筛选和翻页仅操作这次响应；刷新整体替换响应、重新计算总数并重置到第一页，不能混入旧页或证据详情。

### 4.5 原始证据内容、认证与时点

- 使用现有 endpoint-relative `/stocks/{stock_id}/sec-publications/{publication_id}/evidence` 调用 `apiClient`；新增可选 `fact_id` 查询参数，S2 数值入口必须传入，旧调用保持兼容。不得把现有 `/api/v1/...` 路径直接传入已有 `/api/v1` baseURL；外部 SEC URL 不经过 bearer 客户端。
- 后端核对 stock→fact→publication 的精确归属及合法 lineage，并检查当前可用的来源 authority。请求 ID 不一致返回不泄露他人数据的 typed 失败；不为方便历史阅读绕过失权检查。三元 ID 属于验证参数，不需要创建另一个 evidence endpoint。
- 响应保留旧字段，新增 exact decimal 和独立的 `evidence_state/reason_code`，以及与已选 publication inputs 精确关联的原始事实/主表 occurrence。不得仅按 concept 或年度寻找相似 occurrence。
- 最小可读内容为：原始 lexical value、已有 display text（若存在）、sign/scale/单位或展示倍数、报告名称、行标签、列头/期间、concept/context、安全的 report/row/column/occurrence 定位，以及 accession/form/原 SEC 链接。`negatedLabel` 的展示反号与 raw/canonical 值分别标明。
- 复用已保留的 raw fact、authority、occurrence、report reference 和 locator；行标签/display text 已在部分 locator 中，缺字段显式报告。只白名单输出文本/序号/合法外部链接；不执行 retained HTML、不暴露 storage key、内部路径、脚本或整份 artifact。若字段必须从 retained report 取出，限定已绑定 occurrence 且有输入大小界限；不能猜测重建或重新抓取。
- derived SEC 值展示全部已授权输入与 arithmetic sign，沿已有 publication 输入图有界展开；超限或缺任一必要输入返回 evidence unavailable，不显示“证据齐全”。不因此建立 manual/calculated 通用证据引擎。
- 表格 currentness 与证据 access 是不同状态：已被替代但仍获授权的 immutable fact 可以查历史证据，标注“已被替代”；不得换成新 fact。证据请求以当前授权为准，同时验证返回 fact/publication、精确值、期间、单位与选中行一致；不一致清空面板并提示 `evidence_identity_mismatch`，用户可整体刷新。
- capability 区分 `sec_statement`、已有 `document_review`、`reference_only`、`unavailable`。核心 27 项必须为可读 SEC 原始证据；其他来源无 resolver 时明确原因并禁用原文按钮，已有文档 review 继续使用。不暗示 manual 数字必有 SEC/PDF 原文。
- 401 由既有 refresh/登录处理；403、404、typed unavailable 各有可读提示且清除先前详情。证据面板不把其他用户、其他股票或上一响应的数据残留成当前证据。

### 4.6 SEC 引用保存与历史重开

已确认现有 `evidence_is_available` 仅允许 `fact.user_id == user_id`，会拒绝正式 `user_id=NULL` 的 SEC fact，必须纳入本任务修复。

- 保持 `source_type=metric_fact, source_id=fact_id` 的既有引用结构。服务端区分 `sec + user_id IS NULL` 的合法共享分支和请求用户拥有的非 SEC 分支；不能放开全部 NULL owner。校验 case stock、fact、publication 相互绑定、source authority 与可见性；只查存在性不够。
- 继续使用现有 revision 原子保存、expected head、幂等和 terminal 限制。校验与写入在现有事务内，来源权限竞争按既有锁/authority 规则处理；缺少合法 lineage 时 fail closed。
- **不新增数值快照或新 JSON 存储协议**：本切片复用 immutable SEC fact/publication 身份与现有 claim/label/source_date。用户 claim 不是经过验证的 canonical 数值。需要完整快照是后续独立契约选择，不能从“可用 JSON”推定获准。
- revision 读取在当前授权下，以原始 fact ID 解析同一 publication 和证据能力。旧 revision 格式仍可读；授权内 superseded 历史事实不等于 unavailable，也不得按 current ID 替换。失权时保留允许保留的原 claim/来源标识并覆盖 `source_unavailable`，不返回受限数值/片段。删除/脱敏按现有 privacy 契约。
- 已失权证据再次提交时沿用既有拒绝规则，提示用户移除不可用引用或以允许的用户记录继续；不能因旧 revision 中出现过就绕过新保存校验。
- 浏览器验收使用专用测试用户、其拥有的非 terminal case；在任务记录固定 user/case ID。生产、保留验收数据不写入。旧案例不得被用于不可恢复的演示修改。

## 5. Scope

### In scope

- 现有研究页的年度核心财务阅读、其他事实遍历和证据面板。
- 必要的只读元数据序列化及 API 契约补充。
- 复用现有研究证据引用和 revision 保存。
- AAPL 固定窗口验收、边界回归和浏览器用户走查。

### Out of scope

- 新 DCF、owner earnings 自动调整、通用增长率引擎或图表平台。v1.3 明确纳入本卡片的只读 YoY 和趋势，不新增 queryable 派生事实。
- 结构化 thesis 模型、自动 thesis 监控。
- 新增 SEC 拉取、扩大公司覆盖、数据重放或重新准备。
- 新数据库 truth、修改 current 槽位或新的自动来源优先级。

多来源差异沿用现有对账结果展示。除既有证据引用/revision 保存外，本任务不引入新的业务写入流程。

## 6. 实施计划

| 步骤 | 工作 | 产出与通过条件 |
|---|---|---|
| 1. 固定基线与契约 | 确认 S1 依赖、锁定 AAPL 验收矩阵，落实 §4.3–4.6 到 PRD/API schema。 | 27 项验收基准、90 个十年位置、字段来源、可编辑验收案例均写明；S1 未并入 main 时不擅自换分支基线或混合其他任务。 |
| 2. 测试先行 | 编写年度分组、缺失/零值、财政期间、多来源、分页和证据认证测试；补后端元数据一致性测试。 | 新增测试先暴露当前缺口。 |
| 3. 补齐服务链路 | 实现 typed projection、SEC 原始证据、共享事实引用校验与历史重开，继续复用完整指标读取及 reconciliation guard。 | API/保存/历史访问契约测试通过，无逐单元格查询扩张。 |
| 4. 完成页面 | 加入年度表、其他事实分页、证据面板，连接已有添加证据流程。 | 正常用户可完成阅读、核验和引用。 |
| 5. 验证交付 | 运行 Docker 完整测试、lint、build、migration gate 和 `git diff --check`；进行 AAPL 浏览器走查。 | AC1–AC9 均有证据，剩余缺口如实记录。 |

## 7. Files to change

预计范围；实施前按实际依赖确认：

- `frontend/app/(dashboard)/research/cases/[id]/page.tsx`。
- `frontend/components/research/AnnualFinancialsTable.tsx`（新增）。
- `frontend/components/research/FinancialEvidencePanel.tsx`（新增）。
- `frontend/lib/` 中的必要展示逻辑与 `*.test.js` 测试。
- `backend/app/services/research_workspace.py` 及相关后端测试。
- `backend/app/services/financial_history.py`、`backend/app/schemas/financial_history.py`：新增同一guard结果上的只读投影与兼容response model；`backend/app/services/source_reconciliation.py`只传递已有权威period_basis，不改变来源选择或guard规则。
- `backend/app/api/v1/endpoints/research.py`：将 workspace endpoint 绑定兼容的 typed response model，验证旧字段保留和新增投影校验。
- `backend/app/services/canonical_financials.py` 的 SEC evidence resolver：只读原始证据投影、exact value 和身份/访问检查。
- `backend/app/services/sec_financial_evidence.py`：拆出的有界、认证内证据读取；`test_sec_financial_source_guard.py` 仅将该证据所有者加入说明性例外并补精确 lineage/数值来源守卫，不向 workspace、screener 或其他产品读取路径开放 raw。
- `backend/app/api/v1/endpoints/stocks.py` 的原 evidence endpoint：可选 fact_id 验证与兼容响应。
- `backend/app/services/research_cases.py`：shared SEC 引用校验与历史访问投影。
- `backend/app/schemas/research.py` 及必要 workspace/evidence 响应 schema；不新增持久化快照结构。
- 上述服务/API 的集成和负向测试，以及已有 revision/来源可见性回归。
- 新增`backend/tests/unit/test_financial_history.py`、`backend/tests/unit/test_sec_financial_evidence.py`；扩展完整指标读取测试与research endpoint fixture，使其覆盖真实响应契约。
- `docs/prd/value-pilot-prd-v0.1.md` 的必要响应契约补充。
- 本任务记录和本任务实际发现问题对应的 `docs/BACKLOG.md` 条目。

S1 的既有测试作为回归保护。

## 8. Test plan

先做隔离的针对性测试，再按 AGENTS 原样执行完整 closing gates。执行前确认目标环境、连接与测试隔离；保留验收库、保留证据和生产不作为迁移/测试写入目标。真实 AAPL 事实核验只读；研究引用保存验收仅使用既定测试账户和案例。

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
git diff --check
```

除 AC 中的正向用例，覆盖：非自然年财年、同财年不同期间、实际/预测混合、单位/币种差异、多个来源或候选、unknown 元数据、无 ID 的 unavailable 状态、认证过期、证据不可用、刷新后事实变化，以及既有冲突/递归输入/时点边界。

行为验证必须直接调用纯展示/分页/身份检查函数及后端 API；源码扫描只能保留为补充：

- precision：`9007199254740993.000000000001`、正负小额、零、负值、NULL、空串、非法字符串、unknown currency、shares；证明字符串链路和舍入不改变 evidence exact 值。
- pivot：非自然年、同 FY 不同期间、instant/duration、来源/性质/定义差异保留，顺序变化不改变内容，缺 fiscal_year 不猜测。
- pagination：每页 50、末页和空页；总响应 330 条且每个 metric 110 条；所有页 union 与原响应一致，刷新不混版本。
- synthetic states：87 个核心 numeric facts、3 个早期现金缺口的受控 fixture，在不含其他数据时得到 87 fact + 3 not_returned = 90 rows，分页为 50/40；缺口 key 不随翻页变化。整指标阻塞不再额外生成十条 not_returned；窗口未确定不生成预期行。该受控 fixture 不代替真实 AAPL 87/3 的只读核实。
- response model：直接调用 workspace endpoint，断言旧字段不被过滤、financial_history 的 union/计数/NULL 规则正确，非法投影被响应校验拒绝；仅有 value_text 的事实也不能绕过 guard。
- bounds：复用已有 251 current、1001 history、溢出路径 65 keys、原公司界内 >64 稀疏 key 的测试；新增投影必须传达同样状态，不重新实现 guard。跨单元递归和冲突继续受保护。
- evidence：默认/绝对 baseURL 的 URL 构造、401 refresh、403/404/typed failure、三元 ID/值/期间错配、完整 derived inputs、缺定位、恶意 HTML/内部路径不能输出。
- revision：共享 SEC 成功、错误 stock、其他用户非 SEC、NULL-owner 非 SEC、不存在/非法 publication 拒绝；保存后重开同一 ID、superseded、失权、旧 revision、stale 409、terminal case。

S1 历史数据验收不是本次重复运行采集的授权。27 项与 87/3 的分布未能只读确认时，记录阻塞，不减少成功要求。本任务实施从包含 S1 的最新 main 新建独立分支；如 S1 尚未合并，先报告依赖，不能自动合并或悄悄沿旧分支实施。

这些是计划执行项，当前未执行，不构成 PASS 声明。

## 9. 最终演示与停止条件

> 打开 AAPL 案例 → 查看十年核心财务与现金缺口 → 核验 FY2025 CFO 和债务组成的证据 → 添加事实引用 → 保存研究 revision → 刷新找回。

这条路径及 AC1–AC9 通过，就完成本次任务。优先级第 1 项中的“更广公司覆盖”仍保留为后续目标。

## 10. 决策与签核记录

- 2026-09-10：用户认可该任务定义，并要求保存为 task 文件及提供第三方 review 提示词。
- 首轮与第二轮方案审查已收到；两轮修订均已记录，见[核实记录](2026-09-10_s2-review-resolution.md)和[第三方审查提示词](2026-09-10_s2-annual-financials-evidence-review-prompts.md)。
- 2026-09-10：第三方 F-01–F-07 逐项核实，修订为 v1.1；纠正 F-06 endpoint 引用，拒绝不必要的持久数值快照扩张。已执行无数据库连接的 Docker 函数复现，详见核实记录。外部复审待完成，不能称为已获第三方通过。
- 2026-09-10：收到第二轮 READY WITH MINOR REVISIONS；独立确认 R2-01 endpoint 文件遗漏、R2-02 not_returned 计数歧义及 guard 表述漏洞，修订为 v1.2。补齐实际 model 绑定、服务端缺失状态、计数/稳定 key 和行为测试。此为文档修订完成，不等于产品已实现或 AC 已通过。
- 实现及真实数据/自动化浏览器核对已推进至§13；完整工程门禁见§14，用户本人走查尚待确认。

## 11. 实施启动预检（2026-09-10）

启动更新：用户授权合并 S1 后，PR #147 已于 2026-09-10T15:59:05Z 合并；main 基线为 `15f4ba02944a6fe29962136665d9e906010c422a`。S2 从该 main 新建 `codex/s2-annual-financials-evidence`。保留下列历史预检记录以区分当时阻塞与当前状态。实现期间不提交/推送，不修改 retained storage；既有 `frontend/next-env.d.ts`、`frontend/tsconfig.json` 工作区改动不属于本任务。测试已确认通过 conftest 自动创建唯一 `valuepilot_pytest_*` schema，迁移和测试只进入该 schema，并禁用测试进程的后台采集。

用户已要求实施本任务。已完成安全只读预检，产品代码尚未开始：

- GitHub 实时查询：PR #147 为 OPEN/Draft，head `d03a055c704e1003289a7d7ed6bfa70214e67437`，`mergedAt=null`、`mergeCommit=null`；该 head 的 test check 为 SUCCESS。
- GitHub main 仍为 `18c7f15eab779529d368456a1b3078c1166e61d5`，未包含 S1。遵守 §8 的基线限制，未自动合并或从旧分支开始 S2 代码。需要 S1 先合并，或用户明确变更为允许以固定 S1 head 建立叠加开发分支。
- Docker 内确认连接数据库名为 `valuepilot` 后，设置 PostgreSQL `SET TRANSACTION READ ONLY`；服务器确认 `transaction_read_only=on`。数据库时刻为 2026-09-10T15:54:21Z，stock 66 对应 AAPL、listing_exchange=NDQ。
- 一次 SELECT 联查 current SEC metric_facts、成功 finalized publication、inputs、raw fact、locator 精确指向的 statement authority/occurrence/report reference：九项 FY2016–2025 共 87 个唯一 numeric 单元，缺口仅现金 FY2016、2017、2018。
- 最近三年27项均为 `actual / primary_as_filed_actual`；所有27项均具备 raw lexical value、header、row_label、display_value、report_name，authority 的 raw_fact、parse_run、context 及 report/occurrence ordinal 均与选中 publication/input 相符。因此当前未发现需要数据重放或 parser 改造才能取得核心可读证据的缺口。
- 这只是保留数据与精确关联预检，未替代产品 guard/权限路径、完整证据 resolver、安全显示、浏览器或 AC 验收。

锁定最近三年预期（各格为 `fact_id / publication_id / 基础单位精确值`；金额 USD，股数为 shares）：

| 指标 | FY2023 | FY2024 | FY2025 |
|---|---|---|---|
| 收入 | 2179 / 2437 / 383285000000 | 2189 / 2447 / 391035000000 | 2198 / 2456 / 416161000000 |
| 净利润 | 1911 / 2169 / 96995000000 | 1921 / 2179 / 93736000000 | 1930 / 2188 / 112010000000 |
| CFO | 1977 / 2235 / 110543000000 | 1983 / 2241 / 118254000000 | 1988 / 2246 / 111482000000 |
| capex | 1499 / 1757 / 10959000000 | 1505 / 1763 / 9447000000 | 1510 / 1768 / 12715000000 |
| 现金及等价物 | 1146 / 1404 / 29965000000 | 1150 / 1408 / 29943000000 | 1154 / 1412 / 35934000000 |
| 长期债务流动部分 | 1398 / 1656 / 9822000000 | 1402 / 1660 / 10912000000 | 1406 / 1664 / 12350000000 |
| 长期债务非流动部分 | 1440 / 1698 / 95281000000 | 1444 / 1702 / 85750000000 | 1448 / 1706 / 78328000000 |
| 加权平均稀释股数 | 1699 / 1957 / 15812547000 | 1709 / 1967 / 15408095000 | 1718 / 1976 / 15004697000 |
| SBC | 1561 / 1819 / 10833000000 | 1567 / 1825 / 11688000000 | 1572 / 1830 / 12863000000 |

三个 fiscal period end 分别为 2023-09-30、2024-09-28、2025-09-27；duration start 分别为 2022-09-25、2023-10-01、2024-09-29；instant 的 start 为 NULL。数据库数值带12位零小数，本表省略这些零但未舍入有效数字。

特别记录：capex 的 display_value 为括号负号，canonical 为正的支出额；股数 display_value 的缩放不同于货币。实现证据面板必须展示 scale/展示符号口径，不对 canonical 数值再次反号。

## 12. 实施过程（未交付）

- 测试先行：新增 `test_financial_history.py` 首次运行因缺少投影模块失败；接入前 endpoint 测试确认未绑定 schema、真实 330 条 workspace 缺少 financial_history。随后实现兼容 typed endpoint、同 snapshot 的按指标批量元数据投影、稳定状态、年度窗口及服务端 not_returned。
- 基线实测纠正：现有 `response_model=dict` 在当前 FastAPI/Pydantic 下已把 Decimal 输出为字符串；保留此行为，不强制改成 JSON number。
- `docker compose exec -T api pytest -q tests/unit/test_financial_history.py tests/unit/test_company_financial_read_units.py`：首轮接入后 14 passed；后增 text-only guard/失权文本不可回填测试，单独 history 文件 7 passed。这些是迭代测试，不是完整 closing gate。
- 前端纯行为测试先因缺少模块失败；补齐十进制字符串/BigInt 显示、年度 observation 列表、50 行分页、证据身份及 endpoint-relative URL 构造。`docker compose exec -T web sh -lc 'node --test lib/financialHistory.test.js'`：6 passed。
- 容器显式确认 `THIRTEENF_JOB_WORKER_ENABLED=false`、`EDGAR_SCHEDULER_ENABLED=false`；本轮未启动外部采集。测试隔离 schema 自动清理，不触碰 public 业务事实或保留证据。
- PRD §H.10 已同步只读投影契约。SEC 原始证据 resolver、shared SEC revision、页面集成、AC2/AC5/AC8 真实闭环、完整 CI 与用户验收仍未完成。
- 后续聚焦回归：`docker compose exec -T api pytest -q tests/unit/test_financial_history.py tests/unit/test_company_financial_read_units.py tests/unit/test_source_reconciliation.py` → 38 passed（含 251/1001 指标状态传达）；`docker compose exec -T api pytest -q tests/unit/test_source_reconciliation_api.py tests/unit/test_source_reconciliation_sec_integration.py tests/unit/test_reconciliation_policy_snapshot.py` → 23 passed。`git diff --check` 无错误。未把这些聚焦结果称为全量验证。
- SEC 阶段：先复现未校验 fact_id、拒绝 shared SEC 和缺少历史重开字段。新增 bounded evidence resolver、精确 retained authority/occurrence 投影、当前 mapping 权限和 MVCC 检查、有界递归输入、typed unavailable；保留授权内旧证据字段，不把缺少 statement 内容冒充可读原文。authority digest 包含 presentation anchor，不能误与 occurrence 自身 digest 比较。
- SEC 测试必须真实跨事务 finalized，改用现有 `isolated_engine`/publication fixture，而非 conftest 的 savepoint session。撤权后置状态仅在函数内部确认 `valuepilot_pytest_*` schema 后临时解除该 schema 的单一 registry UPDATE trigger、设置 retired_at 并恢复 trigger；它是隔离负例，不宣称生产已有撤权写入口。
- `docker compose exec -T api pytest -q tests/unit/test_sec_financial_evidence.py tests/unit/test_sec_canonical_read_api.py --tb=short --show-capture=no` → 15 passed（新增12项及原有3项）；包括 shared 引用、错误 ID、superseded、保存后重开、不持久化 numeric snapshot、失权不返回 financial_fact、缺失 retained 标签和非法内容。后续仍在补充递归分支/完整回归。
- 页面已接入 `AnnualFinancialsTable` 与 `FinancialEvidencePanel`；去掉 60 行截断，认证请求使用 endpoint-relative URL，按刷新 snapshot 清理 selection/分页，revision 引用按原 fact ID 重开。13项前端聚焦测试通过，`docker compose exec -T web npm run lint` 与 `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` 均通过。这是迭代运行，尚非完整 closing gate；Next build 生成了 next-env/jsx 配置，已恢复到本任务开始时的既有工作区状态。
- 新 resolver 在开发库 `valuepilot` 的显式 READ ONLY 事务中，核验 §11 锁定的27个fact/publication：27/27 evidence_state=available，exact值与对应 metric_facts 一致。没有文件读取重放或 SEC 请求；该服务级核验仍不替代用户浏览器验收。
- 当前浏览器已有其他账户登录。已向用户询问专用测试账户登录或注册确认；未改写已有案例。后续浏览器验收需固定专用 user/case ID。
- 完整 Docker gate 前确认普通 .env 会启动13F/scheduler；必须沿用当前 API container 已采用的离线 compose override（`/tmp/valuepilot-s1-offline.ZdCsgo/compose.offline.yml`），保持 replay、worker/scheduler/notification/seed 禁用。不能直接丢掉此环境上下文重启采集。

## 13. 专用账户浏览器验收（2026-09-10，用户最终走查待完成）

用户明确允许注册新账户后，通过本地注册/登录页面建立普通 `role=user` 验收账户 `s2-evidence-20260910-mtvr9uzq@example.com`，`user_id=2`；新建其拥有的 AAPL `case_id=2 / stock_id=66`。未修改原账户或 case #1，未在文件中保存凭据。

- 实际入口：`http://localhost:3001/research/cases/2`；浏览器正常认证，不注入 token、不绕过授权。§11 的27个锁定 fact/publication，逐一点击年度表进入面板：27/27显示原始 lexical value、display、报告/行/列、context、定位和 exact canonical value；ID/值与预检表全部一致。
- 年度表：FY2016–FY2025 十列，九项87个观察；现金FY2016–2018三个状态明确显示本响应未返回事实、原因未知，不补零。最近三年突出显示；债务两种组成与 weighted-average diluted shares 不改称总债务或期末股数。
- 当前完整 workspace 实际为834 facts +225 states =1059 rows（不是仅有核心90个单元）。浏览器逐页遍历22页，前21页各50行、末页9行，取得1059个唯一row_key。末页刷新后重新展开为第1页，evaluated_at更新，无旧页拼接。
- CFO FY2025：fact1988/publication2246，exact `111482000000.000000000000`，报告 `CONSOLIDATED STATEMENTS OF CASH FLOWS`，行 `Cash generated by operating activities`，列 `12 Months Ended Sep. 27, 2025`，raw79580/authority10978，locator `(report,row,column,occurrence)=(8,18,2,28)`。
- capex FY2025：canonical `12715000000.000000000000`，statement `(12,715)`；股数FY2025：canonical `15004697000.000000000000`，statement `15,004,697`。面板展示各自缩放/显示符号，不重复反号或把千股当货币百万。
- 保存路径：CFO面板添加引用→专用验收thesis→Save revision→整页刷新→Revision history重开原始证据。实际 `case_id=2, head_revision_number=1, revision_id=1`，重开仍为fact1988/publication2246及原exact值。后续显式READ ONLY查询确认持久evidence仅含既有claim/label/source_id/source_date/source_type，无新增financial_fact或数值快照。
- 额外真实derived检查：fact2381/publication2639的季度收入 `109417000000.000000000000`，完整展示fact2203/pub2461 `364357000000.000000000000` 减 fact2201/pub2459 `254940000000.000000000000`，各自原始行列可读。走查发现递归叶节点缺少申报身份，补齐每个statement的accession/form/规范SEC链接；不再把整次run的所有文件显示成当前数字的证据链接。
- 上述是自动化浏览器操作与只读数据库核实，**不是用户已经完成走查**。AC9仍需完整Docker gate通过及用户本人完成阅读/引用流程；当前未交付、未commit/push。

浏览器27项原始绑定记录（FY2025 / FY2024 / FY2023，各格为raw_fact_id / authority_id；fact/publication/值/期间见§11）：

| 指标 | FY2025 | FY2024 | FY2023 |
|---|---|---|---|
| Revenue | 79351 / 10876 | 79352 / 10877 | 76064 / 10346 |
| Net income | 79387 / 10910 | 79388 / 10911 | 76100 / 10380 |
| CFO | 79580 / 10978 | 79581 / 10979 | 76293 / 10451 |
| Capex | 79592 / 10986 | 79593 / 10987 | 76305 / 10459 |
| Cash | 79432 / 10927 | 76144 / 10399 | 72805 / 9852 |
| Current long-term debt | 79464 / 10943 | 76176 / 10415 | 72837 / 9868 |
| Noncurrent long-term debt | 79468 / 10945 | 76180 / 10417 | 72841 / 9870 |
| Weighted-average diluted shares | 79399 / 10900 | 79400 / 10901 | 76112 / 10370 |
| SBC | 79556 / 10964 | 79557 / 10965 | 76269 / 10437 |

## 14. Closing gate 记录（工程通过，用户签收待确认）

环境为本地开发Docker，基线仍为 `15f4ba02944a6fe29962136665d9e906010c422a` 加本次未提交工作区差异；不是远端CI结果、PR批准或生产部署。

第一轮完整 `docker compose exec -T api pytest -q`：**2807 passed / 1 failed，1101.31秒**。唯一失败为 `test_product_modules_do_not_read_raw_sec_financial_facts`：旧静态所有者列表尚未识别新增证据模块。独立检查确认该模块queryable值来自metric_facts，raw只按已绑定输入读取lexical证据；在守卫中仅加入此模块的说明性例外，并增加精确fact/publication/raw/authority绑定及禁止raw/normalization数值读取的补充扫描。此扫描不是权限或行为测试替代品。两项架构守卫聚焦测试通过。

后续SEC新测试与既有API兼容测试合计18 passed；前端展示/分页/证据读取9项行为测试通过，其中新增一项在隔离VM中加载实际`api/client.ts`并以无网络adapter验证401→refresh→同一证据请求重试。未使用真实凭据、未改写浏览器认证状态。派生输入申报身份修订后，真实浏览器27项全部重新通过，递归季度输入分别显示`0000320193-26-000020`与`0000320193-26-000013`。

最终轮先在同一shell上下文设置：

```sh
export COMPOSE_FILE=/Users/dane/projects/ValuePilot/docker-compose.yml:/tmp/valuepilot-s1-offline.ZdCsgo/compose.offline.yml
```

然后按AGENTS的原样命令执行：

| 命令 | 最终轮状态 |
|---|---|
| `docker compose up -d --build` | 成功；重建后再次确认replay、EDGAR/13F/研究通知scheduler禁用；未重启共享Postgres |
| `docker compose exec -T api alembic upgrade head` | 成功；head已是20260909150000，本任务无新迁移 |
| `docker compose exec -T api pytest -q` | 2809 passed，2项既有依赖deprecation warnings，1111.13秒，exit 0 |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | 242 passed / 0 failed / 0 skipped，exit 0 |
| `docker compose exec -T web npm run lint` | 成功，exit 0 |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | 成功，含TypeScript检查与27个静态页面生成，exit 0 |
| `git diff --check` | 通过 |

用户已获得专用案例走查入口并被请自行完成阅读/证据/引用/保存/刷新流程；当前没有把自动化浏览器的成功当作用户签收。

构建后将Next自动生成的next-env imports、jsx及include调整恢复到本任务开始时的既有工作区状态；这两份文件不作为S2产品变更。未提交、推送、开PR或部署；未删除保留证据、旧案例或专用验收账户。

| AC | 本轮状态与证据 |
|---|---|
| AC1–AC5 | 自动化/真实数据/正常认证浏览器通过：十年九项、87数值+3现金缺口、27/27原始证据、精确值及口径，详见§11/13 |
| AC6 | 自动化与浏览器通过：330条受控fixture、251/1001上界回归；真实1059行22页、unique=1059、刷新重置 |
| AC7 | 聚焦行为测试和全量回归通过；多来源/多期间/unknown/预测保留及共享guard边界未绕过；真实派生输入完整展示 |
| AC8 | API/隔离负例与专用case #2浏览器闭环通过；原fact ID重开、引用持久字段只读核实；superseded/失权等破坏性状态只在隔离测试中模拟，未改写真实财务 |
| AC9 | 工程部分通过；用户本人实际走查仍待确认，故不宣称任务最终完成或已获用户验收 |

本节仅记录 v1.2 工程结果。用户随后指出密集数字无法传达投资研究价值，因此不能再把剩余条件描述为仅缺签字；按下节修订后重新验证。

## 15. v1.3 财务阅读 UX 修订（用户批准，2026-09-10）

目标：推进理解企业质量和重构历史经济性。用户约一分钟内能说出主要变化、至少一个值得追查的问题及重要缺口，然后查看证据并记录自己的判断；不自动生成投资结论。

- 默认层级为「Operating performance & cash quality」：最新已保留 FY 的收入、净利润、CFO 概览及 YoY；问题导向趋势（增长、现金转化、现金/长期债务组成、股数/SBC）；可展开的紧凑十年表；高级完整明细。AC1 的十列九项保持可达，默认概览突出最新年度，年度表突出最近三年。
- 全部视图来自同一 financial_history 响应；概览不选最高 ID/首来源，年度单元有多个 observation 或阻塞 state 时不选优。原始观察全部保留在年度表/完整明细，缺口摘要始终可见。
- YoY 是只读显示计算，公式 `(本年−上年)/上年 ×100%`，精确十进制输入，显示一位小数；点击本年/比较年可核验两个 fact。不是新增 canonical fact、owner earnings 或投资判断。
- 只对相邻 FY、各自唯一无阻塞数值 observation、已证明 actual 身份计算；metric/unit/currency/source type/role/nature/basis、定义及 mapping 版本、维度须可比且已知。source_identity 是每条 publication 的追踪身份，不能要求不同 FY 的 publication ID 相同；每个输入仍保留原 ID。未知/不一致、缺年、多来源等返回明确不计算原因。
- duration 必须为已证明的完整财政年度，日期与 duration_days 一致且相邻期间连续；365/366 日或52/53周的年度长度差保留明确提示，不做年化；短年或财政年改制不计算。instant 比较相邻年度的合法期末，不能当作全年流量。上年<=0或本年<0显示 N/M，不输出误导增长百分比。
- 趋势使用明确的共同币种/单位/性质；不同股数/金额分图，无双轴、不混币种/定义，缺失或不可比段断线、不补零；所有系列零基线、可访问的年度选择/数值按钮。简化图表坐标不用于证据匹配。
- 实测补充：保留的历史股数跨年可能具有不同拆股重述基准，当前投影没有 split/share-class authority。金额定义一致不能证明股数已复权。股数保留原值和分立点，不连接跨年线、不算 YoY；默认阅读限制与股数页均标明拆股口径未证明。不得用幅度阈值猜拆股或擅自除以四；正式跨年股数可比性沿用 BACKLOG 的 financial-series identity 后续项。
- 来源/actual/舍入说明集中一次；每格只显示值及例外，多观察时显示期间与来源差异。精确数值、完整期间、fact/publication ID 和 lineage 留在证据/高级明细。保留现金不等于全部流动资产、债务组成不等于总债务、加权股数不等于期末股数等限制。
- 中性提示只陈述已计算的变化并提出问题，不推断税项、营运资本或一次性原因。无充分可比数据时只提示核验缺口。

新增验收 UX1：真实 AAPL 最新 YoY 收入 +6.4%、净利润 +19.5%、CFO -5.7%，均可追查两年输入；FY2023 53周对比必须提示期间差。UX2：现金2016–2018缺口默认可见；多来源/未知/零负分母/期间或币种差异均不伪算。UX3：切换趋势、年度、展开十年及全部分页、证据查看与原引用流程可操作，无旧快照残留。UX4：重新完整 Docker gate、正常认证浏览器核对、用户一分钟阅读走查分别记录，自动化不代替用户认可。

实施顺序：纯计算/系列断点/组件行为测试先红 → 最小 frontend 展示逻辑和组件 → 浏览器核对 → 完整门禁。预计新增 `frontend/lib/financialTrends.{js,d.ts,test.js}`、`frontend/components/research/FinancialTrends.tsx`，更新现有年度组件及 PRD §H.10；无需数据库、parser、mapping 或采集修改。沿用§14离线 override和隔离测试机制。

### v1.3 实施与验证记录

- 首先新增纯函数测试，因缺失 `financialTrends` 失败；再新增实际组件 SSR 测试，确认原卡片没有概览/默认缺口摘要且直接渲染审计表。实现后通过。分部/合并范围混图、拆股基准未知两项追加负例分别先失败，再补 fail-closed 处理。
- 新模块10项行为测试涵盖精确十进制/超过 JS 安全整数、零负分母、亏损、空值、未知身份、币种/单位/来源/定义差异、短年/不连续期间、52/53周、拆股未证明、多观察与scope阻塞、断线和有界坐标、无因果断言的现金问题，以及实际组件的默认层级/无年度锚的整指标阻塞显示。不同指标即使共享FY标签，期间日期不一致也不能叠在同图，边界测试先红后绿。SSR loader使用与产品相容的ES2020编译目标；初次测试loader未指定target导致Set展开丢失，修正测试运行环境，没有放宽产品断言。
- 本轮迭代：`docker compose exec -T web sh -lc 'node --test lib/financialTrends.test.js lib/financialHistory.test.js lib/uiStandard.test.js'` → 20 passed；lint、`./node_modules/.bin/tsc --noEmit` 通过。不是完整 closing gate。
- 开发库valuepilot显式READ ONLY事务读取同一workspace，再在Docker Node内执行实际纯展示模块：最新收入+6.4%、净利润+19.5%、CFO -5.7%、capex +34.6%、现金+20.0%、长期债务流动部分+13.2%/非流动部分-8.7%、SBC +10.1%；每项计算保留两年fact ID。股数初始计算虽数值可算，但后续发现缺拆股authority，已主动停算，而非把初始结果当最终通过。
- 正常认证浏览器仍为专用user 2 / case 2。新版十年表87个数值观察、3个早期现金缺口；最近三年27项全部再次点击，fact/publication/exact/raw lexical/locator与§11锁定矩阵一致。概览的FY2024收入比较按钮打开2189/2447/391035000000，而不是本年或另一个来源。
- 四组图表切换成功；现金FY2016–2018不绘点/不补零，选择FY2018仍显示未知缺失；股数/SBC为两张不同单位图，股数10个独立点且无跨年连线，YoY明确unavailable。选择FY2024显示371→364日期长度提示，未年化。
- 所有1059明细遍历22页（21×50+9），unique=1059；刷新后的新evaluated_at使趋势恢复默认现金视图、年度选择恢复最新年，明细重新从1–50/1059开始。原revision的CFO1988引用仍按原身份请求证据。未改写旧案例、未追加研究revision或金融事实。
- 已检查实际桌面卡片截图，概览与现金图无截断；尚未把此视觉检查等同用户一分钟阅读验收，也未声称已验证所有移动尺寸。
- 按AGENTS同步清除已实现并浏览器复验的两条S2 backlog（SEC链接缺认证、UI 60行截断），具体历史问题与解决证据保留在本任务§11–15。FT-05历史可比性后续项保留并补记拆股基准限制；本轮未扩张为复权/公司行动平台。
- 本轮完整门禁进行中：离线override下重建成功、确认所有采集/通知worker关闭，数据库head20260909150000，migration命令成功且无新迁移；后端全量尚待结束。后续结果必须另行记录，不能复用§14作为新UX的全绿声明。

### v1.3 Closing gate：失败记录与独立复验

第一轮完整 `docker compose exec -T api pytest -q`：**2748 passed / 61 failed，980.00秒，exit 1**。首个失败为 `test_source_reconciliation_api.py:175` 的正常请求意外返回409 / `historical_currentness_unverifiable`；后续多处在 `metric_fact_currentness.py:297` 拒绝 cutoff。例如日志中的 `knowledge_cutoff=2026-09-10T16:55:04.284464Z`，与此前浏览器新响应 `evaluated_at=2026-09-10T17:18:36.308631Z` 不连续。运行后只读核对主机/API/数据库均约18:01:30Z。可疑时间跳变是环境线索，**本记录不把它写成已经独立锁定的根因**，也不将全量失败改称通过。

不改后端代码/fixture/断言，直接在新隔离schema复验所有失败所在文件：

```sh
docker compose exec -T api pytest -q tests/unit/test_source_reconciliation_api.py tests/unit/test_stock_pools_api.py tests/unit/test_stocks_lookup_by_ticker.py tests/unit/test_value_line_annual_facts.py tests/unit/test_value_line_metric_facts_time_series.py tests/unit/test_value_line_report_identity.py --tb=short --show-capture=no
```

结果 **84 passed，53.85秒，exit 0**。这支持运行环境/顺序相关问题的判断，不替代完整门禁，也不证明所有61项共享同一根因。未修改系统时钟、回填authority时间、重启共享Postgres或清理其他schema。

随后按原样运行前端全量：252 passed / 0 failed / 0 skipped；lint与production build（含TypeScript、27静态页面）通过，exit 0。再次启动完整后端命令，并以显式READ ONLY数据库时钟/容器单调时钟采样观察是否再次出现倒退；第二轮具体结果如下。

第二轮已**独立捕捉到数据库时钟回退**，不是仅凭测试失败猜测。相同API容器中，显式READ ONLY事务直接读取`clock_timestamp()`（未传入cutoff、未mock），同时读取容器`time.monotonic()`：

| 样本 | 数据库UTC | 相对样本A的容器单调秒 |
|---|---|---|
| A | 2026-09-10T18:08:37.191657Z | 0（比较起点） |
| B | 2026-09-10T16:34:05.590205Z | +98.2529622100119 |

单调计时前进98.253秒，数据库时钟反而后退5671.601秒；第二轮随即出现成组失败（约58%后）。18:12:20–21Z再次检查，主机、API与数据库时钟又一致。**已证明这次运行期间的时钟不连续；尚未定位谁/哪个基础设施组件改变了时钟，不能据此宣称找到了系统根因或修改数据库时点保护。**

停止此轮不再有效的全量测试：先中断本次exec会话（exit130），随后发现容器内pytest还在，读取其精确PID1384、命令`pytest -q`及启动单调秒84103.4，与本轮启动采样84104.871536557对应，核实后只向该PID发送SIGINT。确认进程已退出；测试schema数量回到运行前17，未清理这17个既有schema或重启共享Postgres。未将中止的第二轮写成完成/通过，也未做第三次盲目重跑。

| v1.3 gate | 最终记录 |
|---|---|
| `docker compose up -d --build` | 成功，沿用离线override |
| `docker compose exec -T api alembic upgrade head` | 成功，无新迁移/数据准备 |
| `docker compose exec -T api pytest -q` | 未通过：第一轮61 failed / 2748 passed；第二轮实测时钟回退后中止 |
| 失败文件隔离复验 | 84 passed，仅诊断材料，不代替全量 |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | 252 passed / 0 failed / 0 skipped |
| `docker compose exec -T web npm run lint` | exit0 |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | exit0，TypeScript与27静态页通过 |
| `git diff --check` | 通过 |
| 用户一分钟阅读与引用验收 | 已提供新版case2入口并询问反馈，尚未收到确认 |

Next生成的next-env imports、jsx和额外include已恢复为本任务开始时的既有用户改动。未提交、推送、合并或部署；本轮无SEC/13F拉取、事实写入、parser/migration变更或研究revision写入。剩余条件：在稳定时钟环境重新通过完整门禁，并取得用户实际阅读认可。

## 16. 用户临时修复时间后重跑完整门禁（2026-09-10）

用户明确要求“时间暂时修复，请重跑门禁”。本轮不修改产品代码、fixture或时点断言，不把临时修复视为基础设施根因已解决。基线仍为HEAD `15f4ba02944a6fe29962136665d9e906010c422a` 加本地未提交S2改动。

沿用`/tmp/valuepilot-s1-offline.ZdCsgo/compose.offline.yml`，重建后逐项确认EDGAR为replay，采集、13F worker、smart retry、manager seed及通知关闭。只读预检数据库为`valuepilot`，public migration为`20260909150000`，既有pytest schema共17个。`docker compose up -d --build`和`docker compose exec -T api alembic upgrade head`均exit0，无新迁移。

后端完整命令`docker compose exec -T api pytest -q`于数据库时间`2026-09-10T18:22:27.570368Z`启动，独立schema隔离机制已复核；API内本次pytest PID30，启动单调秒85183.54。运行中显式READ ONLY事务采样数据库时钟，与同容器monotonic比较。

### 本轮实际结果

以下命令依AGENTS顺序原样执行，均为本地Docker结果，不冒充远端CI：

| 命令 | 实际结果 |
|---|---|
| `docker compose up -d --build` | exit0；离线override继续生效，共享Postgres未重启 |
| `docker compose exec -T api alembic upgrade head` | exit0；已在`20260909150000`，无新迁移 |
| `docker compose exec -T api pytest -q` | **2809 passed，2 warnings，1089.27秒（18:09），exit0** |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | **252 passed，0 failed / cancelled / skipped，exit0** |
| `docker compose exec -T web npm run lint` | exit0 |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | exit0；TypeScript及27静态页面生成通过 |
| `git diff --check` | 通过；生成配置已恢复为本轮启动前状态 |

后端两条warning为Starlette TestClient的httpx和AnyIO BlockingPortal依赖弃用提醒，不是测试失败。没有改动产品代码、测试或断言来取得本轮通过。

### 时钟观测与隔离清理

- 共21次READ ONLY采样：从`2026-09-10T18:22:27.570368Z`至`2026-09-10T18:40:43.131427Z`。数据库时间约前进1095.561秒，同容器monotonic前进1095.556902秒；相邻采样的两种增量差绝对值均小于3毫秒。**采样范围内未观察到回退**；离散采样不证明采样间绝无跳变，也不证明基础设施永久修复。
- 等到pytest实际exit0后复核PID30已不存在，pytest schema数回到运行前17，public migration版本不变。未删除这17个既有schema，也未手工清理或重放业务数据。
- Next dev/build自动生成的next-env imports、jsx及额外include恢复为本轮启动前的用户改动；未覆盖其他本地改动。
- 本轮仅重跑工程门禁及更新记录；未执行SEC/13F采集、研究revision保存或浏览器交互验收。此前§15浏览器证据不改写；用户一分钟阅读认可仍待确认。

结论：本次本地完整门禁通过，解除上一轮工程验证阻塞；时钟根因及长期稳定性继续保留在BACKLOG。未commit、push、合并或部署；不将工程门禁通过等同于用户已验收S2。
