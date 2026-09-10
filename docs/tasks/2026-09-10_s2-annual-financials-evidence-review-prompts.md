# S2 任务方案——第三方独立 Review 提示词

以下内容可直接发送给有仓库读取权限的第三方 reviewer。

---

你是 ValuePilot 的第三方独立 reviewer，兼具高级架构师、金融数据工程师和长期价值投资产品经理视角。

请对 `docs/tasks/2026-09-10_s2-annual-financials-evidence.md` 做一次独立、对抗性、只读的**实施前方案审查**。目标是判断该任务能否以最小范围交付真实投资者价值，并找出实施前必须澄清或修正的方案缺陷。

当前任务版本为 v1.2。请同时阅读 `docs/tasks/2026-09-10_s2-review-resolution.md`，独立判断修订是否真正解决 F-01–F-07 和第二轮 R2-01/R2-02。第二轮小修订涉及 workspace endpoint 实际绑定 typed response model，以及服务端 not_returned 行的计数/标识/生成规则、所有 fact 行的 guard。核实记录只作为线索，不替代自己的代码检查。尤其不要沿用旧 review 中不存在的 `/financial-facts/.../evidence` 路径，也不要把“必须新增持久事实数值快照”当成既有权威要求。

这次审查对象是任务方案及其代码前提，尚无本任务的实现 diff。SEC 引用校验等现有代码缺陷已明确纳入未来 S2 修改；检查方案是否足以修复，不把尚未编码当成方案修订失败。不要把计划中的功能当成已实现，也不要把 S1 的 PASS 声明当成独立证据。不要修改文件、代为修复、提交、推送、合并、部署或启动开发。

## 一、审查基线与必读材料

1. 记录当前分支、HEAD SHA、工作区状态及任务文档版本。新建文档可能未跟踪，必须读取实际文件；不要只看 Git diff。
2. 阅读：
   - `AGENTS.md`
   - `docs/plans/value-investor-user-story-priorities.md`
   - `docs/tasks/2026-09-10_s2-annual-financials-evidence.md`
   - `docs/plans/single-company-research-minimal-plan.md`
   - `docs/tasks/2026-09-09_single-company-data-readiness.md`
   - `docs/architecture/research-decision-support.md`
   - `docs/architecture/data-layer.md`
   - `docs/architecture/metric-facts-is-current.md`
   - `docs/architecture/coverage-source-policy.md`
   - `docs/prd/value-pilot-prd-v0.1.md` 中相关研究、证据及 §H.10/§H.11 契约
   - `docs/metric_facts_mapping_spec.yml` 中本任务涉及的指标、期间、单位与来源语义。
3. 从真实代码核对方案的复用前提，至少检查：
   - `frontend/app/(dashboard)/research/cases/[id]/page.tsx`
   - `frontend/lib/api/client.ts`
   - `backend/app/services/research_workspace.py`
   - `backend/app/services/source_reconciliation.py`
   - `backend/app/services/canonical_financials.py` 的 SEC evidence resolver
   - `backend/app/api/v1/endpoints/stocks.py` 的 evidence endpoint
   - `backend/app/services/research_cases.py` 的证据校验、revision 保存和读取
   - 相关测试。

## 二、任务边界

- 本次为最高优先级用户故事的 S2 切片：年度核心财务表、完整事实遍历、可用证据面板和现有研究引用保存。
- 首批验收：AAPL、CIK 0000320193、stock 66、canonical listing NDQ、FY2016–FY2025；最近三年 FY2023–FY2025 的九项指标共 27 个单元。
- 继承 S1 的 filing-selection cutoff 2026-09-09T00:00:00Z，但不要将它误认为当前 workspace EvaluationSnapshot 或要求回填 knowledge 时间。
- 复用现有研究页和既有 fact/publication/revision；预计无新表、无 parser 改造、无新增拉取或数据重放。
- 新 DCF、owner earnings 自动计算、增长率、图表平台、S3 结构化研究、自动 thesis 监控和多公司数据扩抓不在本次范围。

## 三、重点挑战的问题

### A. 用户价值与可完成性

- 该切片能否让普通登录用户实际完成“看历史→理解口径与缺口→查证据→引用→刷新找回”？
- AC1–AC9 是否可测、分母明确，是否存在“全 unavailable 也算通过”“有链接即有证据”“后端成功即用户成功”的漏洞？
- 固定 27 个单元是否足以检验此次交付，哪些额外边界必须用 fixture 覆盖？
- 核心 27/27 numeric SEC actual 且原始证据可用，与其他行按真实 capability 浏览的双层验收是否充分？十年 90 个预期位置、87/3 待核实分布是否防止缩减分母？

### B. 财务语义与完整性

- fiscal_year、期间起止、期末现金/债务与全年流量如何合法对齐？能否处理非自然年、缺年、短期间及同财年多期间？
- 九项指标是否有明确批准的 canonical key 和定义？长期债务流动/非流动部分不能称为总债务；加权稀释股数不能称为期末股数。
- 金额缩放、Decimal 精度、币种未知、真实零值、空字符串和缺失是否有不含歧义的显示规则？
- 实际、预测、调整值、多来源、同槽位竞争、unresolved 状态是否会在 pivot 时被误合并、覆盖或任意选优？
- 缺失原因能否从返回状态证明？若不知道原因，是否明确保留未知？无 fact ID 的 unavailable 行如何稳定展示？

### C. 数据与读取边界

- 完整指标读取及 reconciliation 是否确实可复用？前端展示分页是否严格遍历同一响应？
- 新增字段从什么权威关系取得，能否批量加载，是否会绕过权限、currentness、source authority 或 EvaluationSnapshot？
- 保持 1,000 历史/250 候选/64 discovery 等已有界限，以及完整同槽位与递归输入检查；不能靠过滤缩小 guard 候选。
- 必要 API 契约是否已经足够明确？哪些字段或状态仍需在实施前定义？“预计无 schema 修改”是否成立？

### D. 证据与研究记录

- 现有 SEC evidence response 是否足以支撑可读的 filing、inputs 和 locator 详情？它是否只是元数据，缺少方案承诺的原文定位内容？
- 正常认证客户端能否解决现有链接路径问题？URL/baseURL、token 刷新、401/403/404 和无权限状态是否覆盖？
- 点击时的证据查询与表格读取可能发生在不同时间，如何保持 fact/publication 身份和数值一致，同时尊重当前授权？是否会悄悄展示新的事实？
- §4.6 的 shared SEC 合法分支、publication 绑定和现有 revision 引用结构能否闭合保存/历史重开？不增加数值快照的方案是否满足 immutable fact 引用、当前授权、superseded、失权以及旧格式兼容？若认为必须扩展持久结构，请给出既有契约无法满足的具体场景，不能仅因 JSON 可用就要求复制数值。
- 如展示源文件内容，方案是否避免直接执行未信任 HTML？不能为本任务扩大成通用文档代理或抓取系统。

### E. 实施成本与验证

- 两个组件、typed workspace 投影、SEC evidence resolver、revision 校验/历史读取和相关 API/schema 的明确修改范围是否足够？指出确实缺失的依赖，避免无依据扩大架构。
- 计划是否包括真正的行为测试，而非仅检查源码包含某字符串？测试能否捕获隐藏分页冲突、财政期间错误、精度丢失和证据错配？
- S1 依赖、目标环境、测试隔离及用户验收是否可执行？完整 CI 与真实浏览器走查是否明确分开？
- 指出实施前必须解决的选择；可在开发中按既有契约处理的细节不应成为阻塞项。

## 四、只读与安全验证限制

- 仓库和业务数据只读。不要执行迁移、数据重放、共享库测试写入或清理，不执行 SEC/13F 网络拉取，不读取或输出密钥，不绕过认证。
- Python/Node 工具只能在 Docker 中运行。以代码和现有测试的静态核对为主；本次不要求启动测试或创建资源。
- 无法只读证明的运行行为标注“未独立验证”，不要从作者日志推导成已证明。
- 不把当前存在、且本任务明确准备修复的 `slice(0, 60)` 或直接 API 链接再次包装成方案遗漏；应审查方案是否足以正确解决它们。
- 区分：方案缺陷、既有实现缺陷、S1 依赖风险、明确范围外需求和未证实疑虑。

## 五、输出要求

1. 结论：**READY FOR IMPLEMENTATION / READY WITH MINOR REVISIONS / REVISE BEFORE IMPLEMENTATION**。
2. 基线和实际阅读/检查范围。
3. Findings 按严重度排序；每项包含唯一编号、准确文件与行号、具体失败场景、代码/契约依据、为何现有 AC 未覆盖、影响和最小方案修订方向。方案缺陷可用明确反例证明，不得冒称运行复现。
4. AC1–AC9 审查表：充分 / 需澄清 / 不充分，以及最小补充。
5. 复用前提核对表：代码已证明的能力、尚未证明的假设及其验证方法。
6. 必须在实施前决策的问题，非阻塞建议，明确范围外事项。
7. 建议的最小修改范围和可实施性判断，不提交修复代码。
8. 针对 F-01–F-07 及 R2-01/R2-02 逐项给出“方案已解决 / 仍有缺口 / 不适用”，把计划充分性与运行时尚未实现分开。

只列有事实依据、会影响本任务结果的问题。不要用命名偏好、抽象洁癖或扩展产品愿景凑数。如果没有发现阻塞项，明确写“在上述审查范围内未发现阻止实施的方案缺陷”，并保留尚未验证的条件。
