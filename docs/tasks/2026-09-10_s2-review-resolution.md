# S2 第三方 Review 独立核实与方案修订记录

日期：2026-09-10

对象：[S2 任务定义](2026-09-10_s2-annual-financials-evidence.md)，首轮 v1 → v1.1，第二轮 v1.1 → v1.2。

范围：实施前方案 review 的逐项核实与修订。用户此次授权处理该 review 的真实问题；尚未执行 S2 产品实现、业务数据写入、迁移、提交或推送。

## 1. 基线与方法

- 本次核查的代码基线为 `d03a055c704e1003289a7d7ed6bfa70214e67437`，分支 `codex/single-company-data-readiness`。
- 工作区原有 `frontend/next-env.d.ts`、`frontend/tsconfig.json` 修改及 `storage/` 未跟踪内容保持原状。任务文件及提示词也是未跟踪文件，直接读取实际内容。
- review 来自用户粘贴附件，含 F-01–F-07；其开头“4 个必须修正”与实际七项不一致。本次逐项核查七项，不照搬数量或严重度。
- 检查真实服务、模型、schema、前端页面、mapping 和 PRD §G.3/§H.10。对可用纯函数的主张，在现有 Docker 容器内调用实际函数配只读 fake session，或使用 Axios `getUri`。没有网络请求、业务数据库连接、建表或写数据。
- 本记录中的“确认”分为实际函数复现、静态代码证明和方案覆盖不足；不把 static review 说成数据库端到端通过。

## 2. 逐项裁决

| Review 项 | 独立结论 | 证据、修订与不采纳部分 |
|---|---|---|
| F-01 SEC 引用被拒绝 | **真实；必须纳入 S2 修复。** 现有代码阻塞 AC8。 | `research_cases.py` 的 metric_fact 分支只检查 owner==user；实际 `_validate_evidence` 对 owner=NULL、source_type=sec、同 stock 抛 `evidence_unavailable`。v1.1 §4.6、AC8、修改文件及测试明确加入 shared SEC 分支、合法 publication/stock/权限检查和历史重开。**不采纳“必须保存整份数值快照”**：PRD §G.3 要求最小 claim/source reference，现有不可变 SEC fact/publication 可保留身份；新 JSON 数值结构不是修复拒绝条件的必要条件，也不能未经契约设计直接加入。 |
| F-02 原始证据不足 | **真实；必须补齐核心证据方案。** 属于当前 API 能力与承诺之间的缺口。 | `_safe_locator` 实测会丢弃 row_label/display_value，输入 SQL 未返回 raw lexical value。模型和 parser locator 已保留原值、header、row_label/display 等；无需新拉取。v1.1 §4.5 明确只读关联已选择 occurrence、纯文本白名单、展示反号/scale、完整输入和 missing/unavailable。不是每种来源都需要新 resolver；仅核心 27 项要求可读 SEC 原始证据。 |
| F-03 pivot 身份/基数未定义 | **真实的方案不确定性；应修订，但尚不能称为已出现 P1 数据覆盖 bug。** | 真实 `_reconciled_workspace_facts` 明确保留所有 eligible sources；mapping 九项 key 与 reviewer 一致；年度表尚未实现，因此覆盖仅是合理反例。v1.1 §4.3 锁定 keys、catalog、cell observation 列表、财年锚和未确定分组，禁止 scalar 覆盖及期间/来源合并。 |
| F-04 混合行 shape | **真实；需要显式投影。** | 当前 fundamentals 拼接 fact、reconciliation、method unsupported、SEC unresolved/cycle dictionaries，存在 NULL ID、period/period_type 和不同 scope。v1.1 §4.4 新增兼容 `financial_history` typed projection，定义 row_kind/key、状态范围、metadata、总数、排序；不直接破坏旧 fundamentals。 |
| F-05 分母/证据范围不清 | **真实的验收歧义；应修订。** 原 AC 已要求数值一致和不编造缺失，但没有把成功分母及全部来源的证据能力分清。 | v1.1 AC1/2/5/6 明确 27/27 可用 numeric SEC actual + 原始证据、十年90位置、87/3仅为待核实预期；其他行按 capability 展示，不新建通用 resolver。无证据不能凭按钮算通过。 |
| F-06 URL 与 baseURL | **引用路径错误，但风险独立复现；作为计划缺口修订。** | 实际路径是 `/api/v1/stocks/{stock_id}/sec-publications/{publication_id}/evidence`，没有 review 声称的 `/financial-facts/{fact_id}/evidence`。Axios `getUri` 实测直接传旧路径确有 `/api/v1/api/v1`；原页面尚未改用 apiClient，故不是已发生的新回归。v1.1 §4.5 采用 IDs 构造 endpoint-relative 路径，并加入相对/绝对 baseURL 测试。 |
| F-07 行为测试不足 | **部分成立；应具体化测试，但不接受“原计划没有行为测试”的推断。** | `researchDecisionLoop.test.js` 的对应测试确为源码正则；原任务已要求分组、分页、认证及浏览器验证，只是未锁定直接执行函数的断言。v1.1 §8 补充精度、pivot、页 union、身份错配和引用历史等行为用例；沿用已有 company bounds 测试，不重复建设测试框架。 |

## 3. 已执行的独立复现

### Python：实际引用校验及 locator 函数

命令入口：`docker compose exec -T api python -B -`。从 `app.services.research_cases` 导入实际 `evidence_is_available`、`_validate_evidence`，从 `canonical_financials` 导入 `_safe_locator`。fake session 仅有返回内存对象的 `get()`；未创建真实 DB session。

输入：用户 7、case stock 66，fake fact 分别设置 owner/source/stock；构造实际 `EvidenceInput(source_type='metric_fact', source_id=1, label='SEC', claim='review')`。

| 输入 | 实际输出 |
|---|---|
| owner=NULL、sec、stock66 | `False` |
| owner7、manual、stock66 | `True` |
| owner8、manual、stock66 | `False` |
| owner7、manual、stock67 | `False` |
| shared SEC 调用 `_validate_evidence` | `ResearchCaseError.code == evidence_unavailable` |
| locator 含四个 ordinal、row_label、display_value、fact_id | 输出仅四个 ordinal，丢弃可读文本/element 标识 |

所有预期断言通过，进程退出 0。这是当前函数行为复现，不是未来修复通过测试。

### Node：真实 Axios URL 拼接

命令入口：`docker compose exec -T web node -`；使用已安装 Axios 的 `create({baseURL}).getUri({url})`，没有执行 HTTP。

| baseURL | 旧完整 API 路径 | endpoint-relative 路径 |
|---|---|---|
| `/api/v1` | `/api/v1/api/v1/stocks/66/sec-publications/1/evidence` | `/api/v1/stocks/66/sec-publications/1/evidence` |
| `https://example.invalid/api/v1` | `https://example.invalid/api/v1/api/v1/stocks/66/sec-publications/1/evidence` | `https://example.invalid/api/v1/stocks/66/sec-publications/1/evidence` |

四个 URL 断言通过，进程退出 0。

## 4. 最终方案决策

- 九项定义、展示语义、多 observation cell、typed projection 和分页规则均在任务文件 §4.3/4.4 固定。
- 原始证据以核心27项为硬验收；扩展浏览按真实能力显示，不扩大为通用文档服务。
- SEC evidence 与 revision validator/history 是必需修改，不再标“可能需要”。
- 沿用稳定 fact 引用，不增加 persisted 数值快照；更新 G.3 的 shared SEC 支持和只读响应契约须在产品实现同一变更完成。
- S1 未并入 main 时本任务实现先报告依赖；基线不得偷偷替换。浏览器保存使用测试账户拥有的非 terminal case，实际 ID 在实施前锁定。
- 两个文档中的不明确之处已修订，复审提示词同步纠正 endpoint 和 snapshot 前提。产品运行时代码的已确认缺陷仍待 S2 实现，不声称已在本轮修复代码。

## 5. 未验证与后续签核

未独立执行：真实数据库保存、87/3 分布再核验、27 项证据端到端走查、未来 projection/面板行为、完整 CI。此次只修改方案和核实记录，无需运行会改变开发环境的完整实现 closing gates。

首轮修订后已收到第二轮复审，结论与处理见下节。AC1–AC9 仍未验收。

## 6. 第二轮 R2-01 / R2-02 核实与处理

外部结论：READY WITH MINOR REVISIONS。独立重新读取实际 endpoint、任务 §4.4/§7 后确认两项均为真实的文档级遗漏；不涉及新架构设计。

| 项目 | 独立依据 | v1.2 处理 |
|---|---|---|
| R2-01 | `backend/app/api/v1/endpoints/research.py` 的 workspace endpoint 仍为 `response_model=dict`；v1.1 要求 Pydantic schema，却未列该 endpoint 文件或绑定要求。 | §4.4 明确 endpoint 绑定兼容 typed response model，保留旧字段、避免 FastAPI 过滤；§7 加入文件；§8 加入实际 endpoint 的校验/兼容测试。 |
| R2-02 | v1.1 只定义空 cell 显示 not_returned，未定义生成位置和计数；numeric fact 的文字范围也确实比所有 fact 行窄。 | §4.4 锁定服务端生成 slot_state，纳入 rows/state_count/total_rows，确定 key、空字段和生成/不生成条件；已有 metric/cycle 阻塞不复制成十个缺失；guard 扩至所有 fact 行，包括文本。§8 加入87 facts+3合成状态=90 rows、50/40分页等受控 fixture，明确不替代真实数据核验。 |

任务文件升级至 v1.2，复审提示词同步版本和检查项。本轮只进行文档/静态代码核对及空白检查，没有运行产品测试、访问数据库或修改 endpoint。第二轮外部意见已经收到；v1.2 的产品实现及交付验证仍未执行。
