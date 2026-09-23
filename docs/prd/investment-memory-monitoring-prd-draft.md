# ValuePilot 投资记忆与论点监控 PRD（User Story 版）

> 状态：只读产品提案草案，非规范性文件，不得作为实施权威，也不直接覆盖现有权威 PRD  
> 版本：0.4 Draft（补齐历史可见性、提案处置并发与有限复核合同）
>
> 日期：2026-09-22
>
> 产品负责人：Product / Research  
> 权威边界：如与 `docs/prd/value-pilot-prd-v0.1.md`、
> `docs/architecture/research-decision-support.md` 或
> `docs/metric_facts_mapping_spec.yml` 冲突，以这些现有规范为准；进入实施前，
> 本文中获批的系统、存储和 API 合同必须合并进权威 PRD。

## 1. 一句话定义

ValuePilot 投资记忆与论点监控，是一套帮助长期投资者持续保存并回放
“当时市场可获得什么信息、我当时相信什么、为什么这样估值、后来发生了什么”
的研究决策支持系统。

它不是荐股系统，也不替用户作出买入、加仓、减仓或卖出决定。它的核心价值是：
让事实、来源、判断、假设、反证、估值和后验结果形成不可被事后改写的证据链，
帮助用户降低永久资本损失与认知偏差。

## 2. 背景与问题

现有定时研究或 AI 监控通常只输出一次性的报告和通知。即使单次结论质量很高，
仍然存在五个结构性问题：

1. 下一次监控从近似空白状态重新开始，无法精确回答“相较上次到底变了什么”。
2. 历史数据被覆盖后，无法还原当时可获得的信息与估值假设。
3. 事实、管理层表述、AI 解释与用户判断容易混在一起，形成虚假的确定性。
4. 投资者容易使用后来的信息评价过去的判断，产生后见之明偏差。
5. 无法系统检验研究流程是否有效，只能凭印象判断“当时看对了没有”。

本产品要解决的不是“如何生成更多监控内容”，而是“如何形成可追溯、可证伪、
可复盘的长期投资记忆”。

## 3. 与 ValuePilot 产品北极星的关系

本能力主要推进以下五项投资工作：

| 投资工作 | 本产品如何推进 | 可观察结果 |
| --- | --- | --- |
| 理解企业质量 | 持续保存护城河、管理层与资本配置相关证据及其变化 | 用户能解释质量判断因何改变 |
| 估算正常化所有者收益 | 保存历史事实、估计值、调整项及当时可见版本 | 任一历史估算可追溯到来源和时间 |
| 留出安全边际 | 保存估值区间、情景假设、模型版本和当时价格 | 任一历史估值结果可以重放或解释 |
| 决策前主动证伪 | 将反方证据、未决问题和 kill criteria 放在监控中心 | 重大反证不会被正面叙事隐藏 |
| 监控论点而非价格噪音 | 只有与论点、价值或永久损失风险相关的变化才进入高优先级 | 纯价格波动不会自动变成投资结论 |

本产品不以通知数量、研究报告数量、交易频率或“推荐命中率”为成功标准。

## 4. 目标用户

### 4.1 主要用户

严肃的自主长期投资者或集中型价值投资组合负责人。他们通常：

- 持有或跟踪 10–50 家企业；
- 有明确的投资论点、估值区间和风险条件；
- 按季度和重大事件更新判断，而不是追逐每日价格波动；
- 愿意保留自己的判断历史，并区分过程质量与结果好坏；
- 需要 AI 提高研究效率，但不愿把决策权交给 AI。

### 4.2 次要用户

- 研究团队负责人：希望复核研究过程与来源完整性；
- 系统运营人员：希望确认监控任务是否完整执行、数据是否缺失；
- 未来的合规或审计角色：仅在明确授权下查看必要的操作审计，不默认读取私人研究内容。

## 5. 核心 Job to Be Done

> 当新的财报、指引、估值输入或可能影响论点的事件出现时，帮助我准确识别相较于
> 上一次已接受判断发生了什么变化，展示支持与反对证据，让我决定是否修订论点、
> 估值或观察条件，并永久保存当时的证据和决定，以便未来在不受后见之明影响的
> 情况下复盘。

## 6. 产品原则

1. **Append first，永不静默覆盖。** 正常写入只追加；纠错通过新版本和
   supersession 关系表达。
2. **事实、主张、解释、假设、估值、决定严格分层。** 一条新闻或管理层表述不是
   已验证事实，AI 解释不是用户论点。
3. **时间是数据的一部分。** 必须区分事件发生、来源发布、系统获知、系统记录和
   经济期间。
4. **AI 只能提出，不得晋升自身权限。** AI 可以提取、比较、质疑和建议复核；
   只有用户明确保存，内容才成为已接受研究修订。
5. **监控论点，不监控情绪。** 价格变化可以触发信息缺口检查，但不能自动证明
   企业质量改善或恶化。
6. **缺失与冲突必须可见。** 不得用估计填补未知后再当成事实展示。
7. **模型必须可重放。** 保存模型、策略和提示版本以及实际输入；不能把不同版本
   的 IRR 或评分当成同一口径直接比较。
8. **以永久资本损失为核心风险。** 业务盈利能力、资产负债表、诚信和资本配置的
   变化优先于普通股价波动。
9. **无动作也是有效决定。** “论点未变，继续观察”必须能够被明确记录。
10. **私人研究归用户所有。** 共享股票身份不意味着共享论点、估值或私有来源。

## 7. 产品边界

### 7.1 本期范围

- 单一用户授权范围内，定时或手动监控运行的可审计记录；
- 已由现有来源政策和 canonical data contract 批准的结构化来源、事实和价格观察；
- 同一用户、同一活跃 research case 内，与显式固定的已接受研究版本进行差异分析；
- AI 生成、带引用的“候选变化”和反方挑战；
- 用户接受、编辑、拒绝或记录“无变化”；
- 历史估值、论点、kill criteria 和研究决定的时间线；
- 从已声明历史起点开始、限定在获批来源和对象类型内的 point-in-time 回放；
- 人类可读报告与机器可读结构化结果由同一批输入生成。

P0 不承诺新供应商分析师估计序列、自动公司事件归并、自动判定自然语言
kill criteria、Expected IRR、统计校准或通用跨用户共享观察。它们必须在各自来源、
语义、权限和验收合同获批后进入后续阶段。

### 7.2 明确不做

- AI 自动发布用户论点或用户内在价值；
- `STRONG ADD`、`BUY`、`SELL`、`TRIM` 等平台投资建议；
- 自动交易、券商下单、仓位自动调整、保证金或税务处理；
- 仅凭股价涨跌触发“论点破坏”结论；
- 将 Value Line 目标价、分析师目标价或系统估值标为用户内在价值；
- 用简单的未来收益均值宣称系统创造了 alpha；
- 未获授权的付费数据抓取、跨用户研究共享或私有内容模型训练；
- 通过私人监控入口创建、扩大或重新授权系统级共享观察；
- V1 建设独立向量数据库；全文或语义检索可在证据与权限模型稳定后另行评估；
- 通过本 PRD 直接定义新的 canonical metric key、单位或期间语义。

### 7.3 P0 支持边界

P0 的一个 logical run 只服务一位已认证用户，可以包含该用户的多个 stock subject；
每个 subject 必须唯一绑定一个现有活跃 research case，并至少存在一个已接受 baseline
revision。支持的输入限于：

- 该用户可见、已上传并完成现有 lineage 的 Value Line 文档与 canonical facts；
- 已按现有 SEC publication contract 完成发布且用户有权读取的 canonical SEC facts；
- 符合现有 freshness、identity 和 currency 规则的 canonical EOD price；
- 该用户现有 research revision、evidence references、用户笔记和已保存的 HTTPS 外部
  evidence link；外部链接在 P0 不由服务器重新抓取；
- 上述来源的 correction、supersession、missing、stale、blocked 和 failed 状态。

P0 不接入新的分析师一致预期、新闻、transcript 或其他第三方内容供应商，不对旧资料
伪造历史获取时间，也不承诺首次可信时间戳之前的回放。每种来源的最早支持日期由
Phase 0 source support matrix 明确公布；缺少可信 `received_at/processed_at` 的旧对象只能
作为当前参考或显示为历史不可用，不能推断为过去已知。

P0 monitoring endpoint 不发布新的 canonical financial fact、price 或 source artifact。
新数据必须先经过其既有、按来源授权的 ingestion/publication 路径；monitor run 只保存
它实际读取的稳定 source/fact/price IDs、版本和差异结果。这样服务委托不会变成第二个
财务真相写入权限。

### 7.4 P0 确定性检测与重要性边界

P0 不尝试替用户判定一项业务变化是否“重大”。版本化确定性规则只产生可解释的研究
义务或信息变化：

| 规则 | 输入 | 结果 |
| --- | --- | --- |
| R1 | monitoring case 的 review 到期或逾期 | 创建必须处理的 review obligation；`own` 优先于 `watch` |
| R2 | baseline 引用或 coverage template 的来源 missing/stale/blocked/failed | 创建 coverage obligation，不得输出未触发结论 |
| R3 | baseline 引用的来源发生 correction、retraction 或 supersession | 创建 correction review obligation，保留原判断 |
| R4 | 同一获批 comparison identity 的 canonical fact 相对 baseline manifest 发生任何数值/状态变化 | 创建信息变化事项；不自动声称业务重大 |
| R5 | case head、research cycle 或 canonical valuation 在运行/处理期间变化 | 将 proposal/比较标记 stale；按既有估值和 case 合同处理 |

规则输入不包括 AI 生成的“重大”“反证强度”“情绪”或置信度。AI 可以在独立候选通道
提出解释或建议人工复核，但不能抑制 R1–R5、改变它们的优先级或证明“无变化”。
`complete_no_rule_trigger` 只有在全部必需覆盖完成、决策关键输入没有缺失/冲突/未知且
R1–R5 均未触发时成立；用户文案必须完整显示限定语。

## 8. 概念与权威层级

### 8.1 关键概念

| 概念 | 定义 |
| --- | --- |
| Monitor Run | 一次有边界的监控执行，包含触发方式、覆盖对象、策略版本和运行结果 |
| Observation | 某来源在某时点提供的事实、估计、主张或价格观察 |
| Company Event | 对同一现实事件的归并记录；多个来源可以指向同一事件 |
| Deterministic Delta | 版本化规则对精确、可比较 canonical inputs 检出的变化，不包含 AI 重要性判断 |
| AI Proposal | AI 基于固定 baseline 和输入 manifest 提出的非权威解释、反方观点或研究问题 |
| Accepted Revision | 用户通过明确 Save / Decide / Review 行为保存的不可变研究版本 |
| Outcome Checkpoint | 在预先定义的时间或事件条件下，对当时预期与后来结果进行对照 |
| Supersession | 新记录纠正或替代旧记录的关系；旧记录仍保留且可见 |

### 8.2 权威序列

```text
来源观察 / canonical facts
        -> 确定性差异检测
        -> AI 候选解释与反方挑战
        -> 用户接受、编辑、拒绝或确认无变化
        -> Accepted Revision
        -> 后续结果观察与复盘
```

AI 候选解释不会因为置信度高、重复出现、用户未响应或经过一段时间而自动变成
用户的当前论点。

### 8.3 必须区分的时间字段

| 时间 | 含义 |
| --- | --- |
| `period_end` | 财务或估计值所代表的经济期间 |
| `event_at` | 现实事件发生时间；未知时保持未知 |
| `published_at` | 原始来源发布或监管机构接受时间 |
| `received_at` / `known_at` | ValuePilot 可信服务边界首次接收该来源或观察的时间，由服务端赋值且不可回填 |
| `processed_at` | ValuePilot 受信处理路径完成该次解析、确定性计算、AI proposal 或外部结果校验的服务端时间；必须有可验证的不可变处理记录，调用方不得指定或回填 |
| `recorded_at` | 该版本对象在 ValuePilot 首次成功持久提交的服务端时间；不是请求开始、排队或调用方声称的时间，失败或回滚不产生可回放对象 |
| `accepted_at` | 用户明确保存、决定或复核一项研究修订并成功提交的服务端时间，不接受调用方回填 |
| `effective_as_of` | 用户判断、估值或模型输出声称适用的时点 |

`published_at`、`event_at` 和客户端提交的任何时间都不能证明 ValuePilot 当时已经拥有
或处理了该内容。P0 使用以下历史可用性规则：

- 原始来源只有在服务端 `received_at <= cutoff` 时才可作为当时已获取来源展示；
- 解析事实或确定性差异只有在其可信 `processed_at <= cutoff` 且 `recorded_at <= cutoff`，且全部输入、身份、mapping、
  policy 与 source version 在 cutoff 时均可用时，才可进入历史结果；
- AI proposal 只有在自身可信 `processed_at <= cutoff` 且 `recorded_at <= cutoff`，
  且全部引用输入当时可用时才可展示；
- 用户判断只有在 `accepted_at <= cutoff` 时才是当时已接受判断；
- 后来的重解析、模型升级、身份纠正或来源更正保留原来源的首次接收时间，但产生具有
  自身 `processed_at` 和 `recorded_at` 的新结果，绝不倒灌旧 cutoff；
- 未知或无法证明的时间保持未知，并使相应历史结果进入 `partial_reconstruction`。

成功对象的相同请求重试保留其首次可信处理与持久记录时间；首次提交失败后补交的
对象使用实际首次成功记录时间，不能沿用失败尝试的时间获得更早可见性。即使有可信
记录证明 1 月 5 日处理完成，1 月 20 日才首次成功记录的结果也不能进入 1 月 10 日
回放；在 1 月 20 日成功记录之后、且依赖均满足条件的回放中展示，并同时显示两种时间。

普通客户端和仅持服务委托的外部监控调用方都不是可信时间签发方。外部声称的完成
时间只能作为非权威来源声明，不能写入上述可信时间；ValuePilot 校验外部结果时记录
自己的处理与持久提交时间。日志、队列时间或调用方声明不能替代可验证的持久处理
记录。未来若授权独立处理服务签发可信处理时间，必须先在权限合同中明确该边界与
不可变处理事件的验证方式；即便如此，ValuePilot 的 `recorded_at` 门槛仍不可豁免。

每次回放必须生成 reconstruction manifest，声明 cutoff、支持的来源与对象类型、历史
起点、输入 ID、身份/mapping/policy/model 版本及具体缺口。P0 只保证已声明支持范围内的
知识回放，不承诺重建 ValuePilot 尚未接收或尚未处理的信息。

## 9. 端到端体验

```text
定时 / 手动触发
      -> 创建 Monitor Run 与覆盖清单
      -> 解析已获准 source / fact / price 引用及其当时版本
      -> 保存运行输入 manifest；后续阶段可关联公司事件
      -> 计算确定性变化
      -> AI 生成带引用的候选变化与反方解释
      -> 进入 Research Inbox
      -> 用户比较“旧判断 / 新证据 / 候选变化”
      -> 接受、编辑、拒绝或确认无变化
      -> 追加 Research Revision 与审计事件
      -> 到期复核和 Outcome Checkpoint
```

一次运行允许部分成功。系统必须逐公司显示 `complete`、`partial`、`blocked`、
`failed` 或 `complete_no_rule_trigger`，不得把部分成功包装成完整覆盖。
`complete_no_rule_trigger` 只表示“在本次声明覆盖范围和版本化确定性规则下未检测到
触发”，不表示没有重大变化，也不能仅由 AI 判断产生。

## 10. User Stories 与验收标准

以下优先级中，P0 为首个可用闭环，P1 为增强分析，P2 为长期学习能力。

### Epic A：监控任务与覆盖记忆

#### US-A1（P0）保存每次监控运行

**作为**长期投资者，  
**我希望**每次定时或手动监控都有独立、可查询的运行记录，  
**以便**我知道某个结论来自哪次运行，以及该次运行实际覆盖了什么。

验收标准：

- Given 一次监控开始，When 系统接受任务，Then 在处理任何公司前先生成稳定的
  run identity，并保存触发方式、计划时间、实际开始时间、策略版本和覆盖清单。
- 每个覆盖对象独立记录完成状态、错误类型、重试次数和完成时间。
- 运行级 `success` 只有在所有必需对象完成时才能出现；否则为 `partial` 或
  `failed`，并展示缺口。
- 同一幂等键重复提交不会产生第二份逻辑运行或重复观察。
- 运行记录不能被普通业务 API 删除或改写；纠错追加操作事件。
- 每个运行固定一个 owner、覆盖模板和 policy version；每个 subject 固定一个活跃
  research case 和 baseline revision。无已接受基线时只保存观察并提示用户先建立基线，
  不调用 AI 草稿或其他 research cycle 作为替代。

#### US-A2（P0）查看“没有得到什么”

**作为**投资者，  
**我希望**看到本次监控的缺失、过期、权限受限和抓取失败项，  
**以便**我不会把“系统没看到”误解为“事实没有发生”。

验收标准：

- 每个必需来源返回 `ready`、`missing`、`stale`、`blocked` 或 `failed`，并有
  类型化原因。
- 必需来源和对象由运行开始时固定的 coverage template 声明；运行过程中不得由 AI
  删除或降低要求。
- 覆盖完成度、确定性规则结果和 AI 候选重要性是三个独立字段；AI 不得把缺失、冲突、
  未知或过期输入解释为“未触发”。
- AI 摘要必须显式继承关键覆盖缺口，不得输出无条件的“无重大变化”。只有全部必需
  覆盖完成、决策关键输入无缺失/冲突/未知且版本化确定性规则均未触发时，才能输出
  `complete_no_rule_trigger`。
- 用户能够从公司结果回到运行覆盖清单和失败详情。

### Epic B：来源、观察与公司事件

#### US-B1（P0）关联带来源的历史观察

**作为**投资者，  
**我希望**监控使用的每一个获准财务事实、管理层披露和价格观察都关联其原始来源与
当时版本，  
**以便**我能判断它在当时是否真实可知、是否可靠以及是否仍然有效。

验收标准：

- run input manifest 为每条输入保存稳定 source/fact/price ID、股票身份、观察类型、单位、
  期间、source version、`published_at`、服务端 `received_at/known_at`、`processed_at`、`recorded_at` 和
  来源定位信息；不复制它成为第二条财务事实。
- 来源 pipeline 可以记录来源声称的发布时间；monitoring 客户端不能覆盖它，也不能
  指定或回填可信接收时间。重试保持首次成功接收时间不变。
- 既有来源 pipeline 规范化失败时保留原始值和错误元数据，canonical numeric value 保持
  NULL；monitoring 不得猜测、内联替代值或产生数值差异。
- 受版权或权限限制的内容只保存获准的最小主张和定位信息；无权用户不能通过
  派生结果看到私有片段。
- 用户打开历史观察时，默认看到当时记录的主张；当前值只能作为清楚标注的对照。

#### US-B2（P1，合同门控）保留获批估计值的完整序列

**作为**投资者，  
**我希望**在来源权利和 canonical metric contract 获批后，将同一严格口径的 Forward
EPS、收入和分析师覆盖变化按观察时点持续追加，  
**以便**识别 30/90 天修订、修订速度和预期拐点。

验收标准：

- 本故事不得进入实现或功能开关，直到一个明确供应商的获取、存储、展示、AI 使用、
  retention 和撤权后行为获批，且 mapping 定义 estimate type、GAAP/non-GAAP、目标财政
  期间、币种、统计样本、单位和比较身份。
- Given NVDA 的 Forward EPS 先后为 15.57、15.91、16.84、17.20，When 查看历史，
  Then 四个观察均存在，且任何新观察都没有覆盖旧值。
- 30/90 天变化使用获批、版本化的历史基准规则，并展示精确 canonical fact IDs、币种、
  财政期间、estimate definition、source version 和数据可用性。
- 缺少合适历史基准点时返回 `unavailable`，不得用最近值冒充精确 30/90 天数据。
- 不同供应商、GAAP/non-GAAP、NTM/固定 FY、财政期间、币种、统计样本或 actual/estimate
  不能静默拼接为同一序列或产生变化率。
- 图表、差异检测、报告和 AI 只能消费获批 canonical fact contract；不得直接从平行
  observation 数值计算财务趋势，也不得破坏 per-period `is_current` 语义。

#### US-B3（P1）将来源与现实事件分离

**作为**投资者，  
**我希望**多篇新闻、公告和电话会记录可以归并到同一公司事件，但每个来源仍被
独立保留，  
**以便**避免把重复报道误当成多份独立证据。

验收标准：

- 一个事件可以关联多个来源观察；来源记录不会因为事件归并而消失。
- 自动归并必须展示依据和置信度；低置信度保持未归并或等待人工确认。
- 事件至少支持业绩、指引、估计修订、资本开支、并购、监管、产品、重要客户、
  管理层变化和资本配置等类别。
- `PRICE_MOVE` 可作为“检查信息缺口”的事件，但不是业务论点变化的证据。

#### US-B4（P0）处理纠错与撤回

**作为**投资者，  
**我希望**来源更正、数据修订或错误归并通过可见的 supersession 关系表达，  
**以便**历史上“当时看到什么”与“后来确认什么”都能被保留。

验收标准：

- 更正会创建新记录并引用被更正记录；旧记录不被删除或静默修改。
- 历史回放展示当时可见记录；当前视图按照来源自身的 authority/supersession 合同展示
  当前记录及其更正链，不能按跨来源数据库顺序擅自选择赢家。
- 已基于旧记录形成的用户研究版本不被改写，但会显示“来源后来被更正”。

### Epic C：论点变化与人工权威

#### US-C1（P0）比较新证据与上次已接受研究版本

**作为**投资者，  
**我希望**系统首先告诉我相较上次已接受版本哪些事实、假设和未决问题发生变化，  
**以便**我把注意力放在真正需要重新判断的地方。

验收标准：

- 比较基线只能是用户已接受的 research revision，不得使用 AI 上次未接受的草稿。
- 运行开始时固定 case ID、research cycle 和 baseline revision ID。当前 head 或 case cycle
  发生变化后，该比较结果标记为 stale，必须基于新 head 重新比较，不能自动跨周期继承。
- 没有已接受基线时，系统保存新观察并提示建立基线；不得借用 AI 草稿、已关闭 case
  或另一用户的 revision。
- 差异至少分为：新增证据、数值变化、来源更正、假设变化、证据冲突、数据缺失、
  无实质变化。
- 每一项候选变化都可回到具体来源或 canonical fact。
- 系统不能仅因价格下跌而将已接受的业务论点标为恶化。

#### US-C2（P0）生成带引用的 AI 候选变化

**作为**投资者，  
**我希望**AI 对新证据给出简洁的候选解释、替代解释和最强反方观点，  
**以便**提高研究效率但不丧失独立判断。

验收标准：

- AI 输出明确标记为 `AI_PROPOSED`，并记录 owner、proposal ID、case/research cycle、
  baseline revision ID、模型、提示或政策版本及精确引用输入 manifest。
- 每个关键判断必须绑定引用；没有来源支撑的内容标记为推断或未知。
- 输出包含：可能支持论点的证据、可能反驳论点的证据、其他合理解释、待验证问题。
- 引用不可访问时显示 `source_unavailable`，不得用模型记忆代替来源。
- AI 置信度不得被呈现为事实概率，也不得自动改变研究状态或用户估值。

#### US-C3（P0）由用户接受、编辑、拒绝或确认无变化

**作为**投资者，  
**我希望**对每次候选变化作出明确处理，  
**以便**当前论点只代表我真正审阅并接受的判断。

验收标准：

- 用户可执行 `apply to local draft`、`reject`、`save draft`、`decide`、`confirm no change`
  或 `return to research`；不存在一个含义不明的通用“接受”按钮。
- `apply to local draft` 只修改客户端草稿，不产生服务器权威；`save draft`、`decide`、
  `confirm no change` 分别映射既有 `draft`、`decision`、`review` 语义。只有明确 Save /
  Decide / Review 才能追加 Accepted Revision。
- 保存需同时携带 expected head revision 和 proposal baseline revision。只要当前 head、
  active case 或 research cycle 与 proposal 基线不一致，就返回类型化
  `proposal_baseline_stale` 409，并要求重新比较；客户端不能只刷新 expected head 后接受
  旧 proposal。
- 对 proposal 的接受、编辑接受、拒绝和确认无变化，还必须携带预期的 proposal
  disposition/version 与处置幂等键；该检查独立于 case head，不能因 reject 不推进
  head 而省略。只有预期版本仍处于待处理时才可首次终态处置；两个窗口竞争时恰好
  一个成功，另一个返回类型化 `proposal_disposition_conflict` 409，零业务写入。
- 同一认证 owner、proposal 和处置幂等键、同一完整请求内容的成功重放，返回原
  disposition/revision，不再次执行副作用，即使成功后 case head 已前移；同 key
  不同内容返回类型化幂等冲突 409。更换 key 也不能再次处置已终态的 proposal。
  授权仍在重放前验证，具体身份与重试规则见 §14.1。
- 预期 proposal 版本与 case/baseline 校验、终态 disposition、必要的研究 revision、
  canonical valuation 发布及相应事件必须在同一原子提交中成功或失败；拒绝不创建
  revision。任何校验失败或回滚均不能留下已处置但未保存的提案，或无处置记录的
  Accepted Revision。`apply to local draft` 不预占终态，稍后保存仍需这些校验。
- 成功处理会把 proposal ID、输入 manifest/version、原 baseline、处理方式
  `accepted_as_is` / `accepted_with_edits` / `rejected` / `no_change` 和最终 revision ID
  （不产生 revision 的拒绝场景为 NULL）写入 append-only 处理事件。无 proposal 的内容
  明确标记为 `user_authored`。
- 拒绝 AI 建议会保留建议、拒绝时间和可选理由，但不会污染当前用户论点。
- 重新考虑已拒绝提案必须由用户明确发起，并引用原 proposal 与拒绝 disposition。
  复用现有候选提案路径，以当前基线和仍获授权的证据重新比较，产生新的 proposal
  身份；原拒绝保持终态且不可变，新决定独立处置。普通重试不能重开原提案，后台
  重放不能将它自动恢复为待处理；不新增审批层级。
- `confirm no change` 只适用于已处于 monitoring 的 `watch`/`own` case，仍生成一次
  `review` revision 和明确复核事件，并记录本次所审阅的证据范围；其他状态必须使用
  `save draft` 或 `decide`。
- `confirm no change` 只记录用户在已审阅证据范围内维持论点的判断，不改变 run 的
  `partial` 状态，也不完成、降低优先级或隐藏尚未解决的 coverage、correction、conflict
  等独立义务。覆盖不完整时，界面与历史记录必须显示“在已审阅范围内维持，仍有缺口”
  及具体未解决事项，不能显示无条件的“未发现变化”。符合既有条件的 review revision
  仍可保存，但独立义务按 US-E1 与 §15.1 各自验收、计数。
- `save draft` 若包含 publishable base intrinsic value，仍须按既有 §G.4 原子发布规则
  处理并在 UI 明确确认；“draft”不能被解释为估值一定不会发布。

#### US-C4（P0）保存并人工复核 kill criteria

**作为**投资者，  
**我希望**每个重要论点都有版本化的可证伪条件，并能将相关证据带回人工复核，  
**以便**及时复核可能造成永久资本损失的变化。

验收标准：

- kill criterion 包含描述、可观察条件、相关指标或来源、审阅频率和创建它的
  research revision。
- P0 的 criterion 明确标记 `manual_review`。定量条件还必须记录 metric identity、单位、
  比较方向、阈值、期间、持续时间和缺失处理；定性条件明确只能由用户判断。修改条件
  必须追加 research revision，不能改写旧条件。
- AI 或规则只能创建 `possible trigger / needs review` 候选；未知、缺失或冲突数据不能
  显示为 `not_triggered`，是否触发以及论点是否失效由用户确认。
- 被标记的 criterion 必须同时展示支持和反对证据、数据缺口、当时定义和创建它的
  revision。AI 候选本身不能改变 case。
- 用户在 expected-head 检查下确认触发时，原子追加 revision/event；monitoring case 按
  既有合法转换回到 `researching`，清除当前 decision 和 next review date。已经处于
  researching 的 case 保持 researching；closed/voided case 不可修改。
- 确认触发不会自动产生卖出、减仓或任何组合动作。自动评价定量条件和自然语言条件
  的通用引擎不属于 P0，进入 Phase 2 前必须另行批准。

### Epic D：估值与模型可重放

#### US-D1（P0）保存可解释的历史估值版本

**作为**投资者，  
**我希望**保存每次已接受估值的区间、关键假设、估值日期和价格日期，  
**以便**未来准确解释“为什么当时认为它值这么多”。

验收标准：

- 历史估值至少保存 low/base/high、币种、估值方法、关键假设、估值日期和引用证据；
  无法估值时保存类型化原因。
- 用户内在价值、系统估值参考和分析师目标价在 UI 与 API 中使用不同标签。
- 一个新的用户估值会追加 research revision，并通过既有 canonical valuation service
  发布；不得创建第二条用户内在价值写入路径。
- 正在 monitoring 的 case 修改估值后必须回到 researching，直到用户重新确认。

#### US-D2（P1）重放 Expected IRR 或情景回报

**作为**投资者，  
**我希望**任何历史 Expected IRR 都能由当时输入和确定性模型重新计算，  
**以便**判断变化来自公司、价格、假设还是模型版本。

验收标准：

- 每次持久化输出保存 calculation/model version、全部实际输入、情景权重、期限、
  价格 ID、研究版本和计算时间。
- 确定性计算由版本化代码完成，不由 LLM 自由生成数值。
- 不同模型版本默认分组展示；跨版本比较必须显示口径变化警告。
- 重放结果与原记录不一致时显示失败和差异，不覆盖原始输出。
- Expected IRR 明确标为情景估计，不是收益承诺或平台建议。

#### US-D3（P1）解释估值变化的来源

**作为**投资者，  
**我希望**系统将估值或 IRR 变化拆解为价格、盈利预期、经营假设、终值假设和模型
版本变化，  
**以便**避免用一句“目标价上调”掩盖真正原因。

验收标准：

- 比较使用同币种、同口径或清楚标注不可比。
- 展示每类输入的旧值、新值及其对结果的方向性影响。
- 如果多个输入同时变化且无法严格归因，显示交互影响而非伪精确拆分。

### Epic E：Research Inbox、时间线与提醒

#### US-E1（P0）按永久损失风险分配研究注意力

**作为**投资者，  
**我希望**Research Inbox 优先显示持仓论点、kill criteria、重大反证和逾期复核，  
**以便**注意力用于最可能改变资本配置判断的事项。

验收标准：

- P0 默认优先顺序为：`own` case 的已到期义务或来源纠错、`own` case 的 coverage
  failure、`watch` case 的已到期义务或来源纠错、`watch` case 的 coverage failure、
  exact-comparison canonical fact 变化、AI 建议复核和纯信息性事项；同级按义务最早
  产生时间、stock ID 排序。
- P0 确定性排序只消费既有 case/portfolio 状态、到期义务、coverage failure、获批
  canonical fact 的版本化规则结果和用户已确认的 criterion 状态。每个结果展示
  matched rule、policy version、输入 IDs 和简明原因。
- AI 候选重要性位于独立的“AI 建议复核”通道，可以增加一个低于强制义务的候选事项，
  但不能降低、关闭、静默处理或单独提升任何确定性义务。
- 单一股价跌幅、热度、AI 置信度或其他 AI 主观标签不能单独把事项提升为最高优先级。
- 同一输入和 policy version 必须产生同一确定性排序；missing、stale、conflicted、
  unknown 均不能被视为未触发。
- 监控义务只能有限期 snooze；信息发现可 dismiss，且新 source version 可重新出现。
- proposal 被接受、拒绝或确认无变化不等于独立义务已解决。coverage、correction、
  conflict 等义务须按各自可验证的完成条件关闭；仅记录维持判断不能替代缺口补齐、
  更正复核或冲突处理。有限期 snooze 也不算完成，未解决事项继续按上述规则展示。

#### US-E2（P0）查看单一公司的投资记忆时间线

**作为**投资者，  
**我希望**在一个时间线上看到来源、事实、事件、AI 建议、用户修订、估值和复核，  
**以便**快速理解整个论点如何演化。

验收标准：

- 时间线可按“全部、财务、事件、论点、估值、决定、纠错”筛选。
- 每项清楚显示权威类型：reported、derived、estimated、AI proposed、user accepted。
- 同一天多条记录按 `known_at`、`recorded_at` 和稳定 ID 排序。
- 用户可以选择两个 Accepted Revision 进行逐字段对比。

#### US-E3（P1）接收有边界的监控提醒

**作为**投资者，  
**我希望**只在出现重大变化、复核到期、覆盖失败或可能触发 kill criterion 时收到提醒，  
**以便**不被每日噪音淹没。

验收标准：

- 提醒由已提交的 domain event 异步生成，具有幂等键和 delivery audit。
- “无实质变化”的运行保留在历史中，默认不发送外部提醒。
- 每条提醒说明为何重要、相较哪个 revision、主要来源和建议的人类下一步。
- 提醒不得包含买卖指令；允许的行动文案为“审阅证据”“更新研究”“确认无变化”等。

### Epic F：历史回放、结果评估与学习

#### US-F1（P0）在声明支持范围内重建历史视图

**作为**投资者，  
**我希望**在系统声明支持的历史起点、来源和对象类型内选择日期，并只看到当时实际
可用的内容，  
**以便**在不泄漏未来信息的情况下复盘判断。

验收标准：

- point-in-time 查询逐类应用 §8.3 的可用性条件，而不是只比较一个客户端可提交的
  `known_at`；全部依赖必须在 cutoff 时已可用。
- 解析结果、确定性 delta 与 AI proposal 必须同时通过可信 `processed_at` 和持久
  `recorded_at` 的截止检查；1 月 5 日处理、1 月 20 日首次成功记录的结果在 1 月 10 日
  不可见。成功记录后的合格回放显示处理时间与记录时间，不把迟交伪装成当时已知。
- 后续更正不会消失，但只在更正自身满足可信接收、处理、持久记录与依赖条件之后出现；重解析和身份纠正
  同样不得倒灌。
- 页面显著显示 cutoff、声明支持范围、历史起点、数据覆盖、身份/mapping/policy/model
  版本和缺失项，并提供 reconstruction manifest。
- 若无法完整重建，返回 `partial_reconstruction` 和具体缺口，不得假装完整。

#### US-F2（P1）对照预期与后来经营结果

**作为**投资者，  
**我希望**在预先设定的检查点比较当时关键预期和后来实际经营结果，  
**以便**判断论点质量而不只看股价。

验收标准：

- 检查点优先比较收入、利润率、每股所有者收益、资本回报、杠杆、稀释、关键业务
  驱动和 kill criteria，而非只比较股价收益。
- “实际值”保留其来源、公布时间和后续重述记录。
- 评估区分：论点方向正确、幅度错误、时间错误、关键风险漏判、数据仍未解决。
- 结果不会反向修改原研究版本。

#### US-F3（P2）复盘决策过程而非只统计收益

**作为**投资者，  
**我希望**把决策分类为好过程/坏过程与好结果/坏结果，  
**以便**避免用赚钱合理化错误流程，或用短期下跌否定正确研究。

验收标准：

- 复盘使用冻结的当时证据、估值、价格、政策和研究版本。
- 用户单独评价来源质量、反证处理、估值纪律、仓位/组合背景和执行纪律。
- 系统不得把个股上涨自动标为正确决定，也不得把短期下跌标为错误决定。
- 过程改进以可执行规则记录，并可在未来研究模板中提示。

#### US-F4（P2，独立协议门控）准备描述性结果与未来校准

**作为**投资者，  
**我希望**先按模型版本、研究状态和预先定义的时间窗查看有完整缺失说明的描述性结果，  
**以便**识别值得进一步检验的偏差，而不把有限历史误称为校准或 alpha。

验收标准：

- 分析必须处理退市、并购、拆股、分红、币种、缺失数据和幸存者偏差。
- `watch`、`own` 或用户记录的组合事件可以分析；AI 候选动作不能伪装成历史决策。
- P2 本身只展示个案经营预期对照、完整纳入/排除清单、缺失说明和描述性分布；过程
  评分明确标记为使用事前标准的用户评价。
- 收益描述展示样本数、时间窗、基准、分散度和置信限制，不只展示平均值，且永远不
  标记为 alpha、模型优劣或“校准可靠”。
- 真正的统计校准或方法比较必须由独立获批协议定义：事前可解决预测、解决规则、完整
  纳入队列、重叠样本、外部验证、公司行动、基准和最低数据门槛；该协议不属于本 PRD。

### Epic G：结构化输出与接入

#### US-G1（P0）同源生成机器结果和人类报告

**作为**投资者，  
**我希望**一次监控同时产生可阅读报告和符合严格 schema 的结构化结果，  
**以便**阅读体验与数据库记录不会互相矛盾。

验收标准：

- 两种输出引用同一 run ID、source IDs、observation IDs 和 policy/model versions。
- 人类报告中的每个关键数值可以定位到结构化记录。
- JSON schema 版本是必填项；未知字段、缺失必填字段和单位错误返回类型化 422。
- 报告生成失败不回滚已验证的结构化运行结果，但运行标记为 partial；结构化写入失败时
  不得发布“完整成功”的报告。
- 报告重生是独立 render attempt，复用已提交 run/input IDs；它不能重新发布事实、
  proposal、Inbox action 或用户 revision。

#### US-G2（P0）通过安全、幂等的 API 接收外部监控结果

**作为**系统运营者，  
**我希望**授权的定时监控通过受保护的 FastAPI 入口提交结果，  
**以便**不直接暴露数据库，也不依赖任务访问本机 localhost。

验收标准：

- 路由位于 `/api/v1`，使用用户明确创建且可撤销的服务委托、最小权限和请求级幂等键。
  委托在认证上下文中唯一映射一个用户；run、proposal 和 Inbox action 均归该用户所有，
  请求体不得选择或覆盖 owner。
- P0 是用户级私人运行。它可以引用该用户可见的现有系统共享事实，但不能通过本入口
  创建或扩大共享观察，也不能把用户私有来源转为共享内容。
- payload 包含 schema version、run metadata、覆盖对象、稳定 source/fact/price 引用和
  逐对象结果；P0 拒绝内联 authoritative financial value 或 price，防止绕过 canonical
  ingestion/publication service。
- 调用方试图写入或回填可信 `received_at/known_at`、`processed_at`、`recorded_at` 或
  `accepted_at` 时，返回类型化字段校验错误且零业务写入。外部完成时间只能以明确
  标记的来源声明提交，不能映射为可信时间。ValuePilot 自行记录结果校验完成与首次
  成功持久提交时间，依 §8.3 决定历史可见性；服务委托不授予签发可信时间的权限。
- API 先验证再写入；单对象失败有明确事务边界和结果，不产生半条记录。
- 日志不得记录凭证、完整付费内容或私人研究正文。
- 重放相同请求返回同一逻辑结果，不重复创建事件、事实或用户待办。
- 私人 case、revision、用户所有的 source/reference 必须属于委托用户、与目标 stock
  匹配且当前可见；引用其他用户私人资源返回不泄露存在性的 404，并且零业务写入。
- 获准的 system-owned shared source/fact 不要求用户所有权，但必须按其既有来源合同验证
  当前访问权、目标 stock、source version、finalized lineage，以及精确的 fact/publication
  绑定。只有主 PRD §G.3 明确授权的 NULL-owner 分支（当前为受限 SEC fact 分支）可以
  作为共享输入；其他 NULL-owner 数据不会因没有 owner 而自动获得共享资格。
- 撤销委托后不得继续获取或处理该用户私人内容。

### Epic H：运营与审计

#### US-H1（P1）查看监控系统健康度而不暴露私人研究

**作为**运营人员，  
**我希望**查看运行成功率、数据源失败、延迟、重复率和 schema 错误，  
**以便**维护可靠性，同时不读取用户的私人论点。

验收标准：

- 管理视图默认只提供聚合健康信息和不可识别的技术错误。
- 普通管理员不能查看用户研究正文、私有来源片段或通知内容。
- 所有重放、修复、凭证轮换和人工纠错都有操作审计。

## 11. 页面与信息架构

### 11.1 Research Inbox

每个事项只回答五个问题：

1. 什么发生了变化？
2. 为什么它可能重要？
3. 哪些证据支持或反驳它？
4. 哪些信息缺失或存在冲突？
5. 用户现在需要完成哪一种研究动作？

默认卡片字段：公司、case 状态、重要性原因、相较 revision、最强新证据、最强反证、
kill criterion 状态、覆盖缺口、来源时间、人类下一步。

### 11.2 Company Investment Memory

包含：

- 当前用户已接受论点与研究状态；
- 新证据候选区；
- 在 US-B2 合同获批并启用后显示的 Forward EPS / 关键估计序列；
- 估值与模型版本历史；
- 事件、来源与纠错链；
- kill criteria 与未决问题；
- research revision 时间线；
- outcome checkpoints 与复盘。

图表必须允许叠加“价格”和“盈利预期”，但默认不暗示相关性或因果性。

### 11.3 Revision Compare

并列展示两个用户已接受版本：论点、关键假设、反方观点、风险、kill criteria、估值、
决定、证据和数据缺口。机器生成的差异摘要必须可回到字段级变化。

### 11.4 Point-in-Time Replay

用户选择历史日期后，页面进入明显的只读“历史知识边界”模式；当前数据只能作为可选、
清楚标记的旁栏对照，不能混入主视图。

## 12. 数据与领域边界

### 12.1 优先复用的现有权威对象

| 需求 | 权威对象或规则 |
| --- | --- |
| 公司身份 | 复用 `stocks`，不新建平行 `companies` 真相表 |
| 查询型财务事实 | 复用 `metric_facts`；筛选和公式不得查询平行估计表充当第二真相 |
| 提取审计 | 复用不可变 `metric_extractions` 和既有来源 lineage |
| 用户论点、估值与决定 | 复用 `research_cases`、`research_case_revisions`、`research_case_events` |
| 用户当前内在价值 | 复用 canonical valuation service 与 `val.fair_value` 合同 |
| 价格 | 复用 `stock_prices` 的 canonical read / freshness 规则 |
| 研究待办 | 扩展 `research_inbox_actions` 与 append-only action events |
| 组合动作 | 复用用户主动记录的 portfolio position events；不存 AI 交易指令 |

### 12.2 可能需要新增的概念对象

以下仅是产品概念，不在本草案中锁定表名或 SQL：

- monitor run 与逐对象运行结果；
- 来源观察与现实事件归并关系；
- AI monitoring proposal 及其模型、输入和处理结果；
- 确定性 valuation / return calculation run；
- outcome checkpoint 与 process review；
- point-in-time reconstruction manifest。

进入实施前必须完成 schema review，避免形成以下重复真相：

- 独立 `thesis_snapshots` 不能绕过 research revision 成为用户当前论点；
- 独立 `valuation_snapshots` 不能绕过 canonical valuation service 成为用户内在价值；
- 独立 `earnings_estimates` 若参与筛选或公式，必须通过 canonical fact contract；
- `portfolio_signals` 不能保存 AI 的买卖建议并被 UI 当作用户决定。

### 12.3 Append-only 与当前投影

不可变历史和可变当前投影必须分开：

- 历史记录追加保存；
- 当前投影只用于快速查询和排序；
- 更新当前投影与追加历史事件必须在同一事务内完成；
- 普通 API 不删除历史；隐私删除仅走现有受审计的窄例外；
- 所有 supersession 都必须指向明确的旧记录并有原因。

### 12.4 P0 所有权与服务委托

P0 采用唯一模式：**用户级私人运行**。

- 用户通过已认证交互创建一个可撤销服务委托；委托绑定唯一 `user_id`、允许的动作、
  过期时间和凭证版本，owner 不来自 payload。
- monitor run、逐对象结果、AI proposal、处理事件和生成的 Inbox action 都继承该 owner。
- 私人 case、revision 和用户所有的 source/reference 必须属于 owner、当前可见且与目标
  stock/case 匹配；稳定 ID 证明身份，不证明权限。
- canonical system-owned shared source/fact 继续由其现有来源政策管理，不要求 owner
  等于委托用户，但每次引用都验证当前访问权、目标 stock、source version、finalized
  lineage 和精确 fact/publication 绑定。只有既有合同明确授权的 NULL-owner 分支可以
  共享；其他 NULL-owner 数据默认不共享。
- 私人监控只读取上述获准版本，不获得重新发布、复制为共享数据或扩大受众的权力。
- 委托撤销后，未开始的运行停止；进行中的私人内容处理在下一个授权检查点失败关闭。
  已提交历史按现有 retention、redaction 和 account-erasure 合同处理。
- 跨用户引用统一返回不泄露存在性的 404，并验证没有创建 run subject、proposal、
  revision、action 或审计内容之外的业务写入。

## 13. 建议的结构化监控结果

以下为产品层 envelope 示例，不是最终 API 合同：

示例中的 `idempotency_key` 在认证得到的 owner namespace 内解释；逻辑运行身份始终是
`(owner_id, logical_run_key)`，payload 不携带也不能选择 `owner_id`。

```json
{
  "schema_version": "investment-monitor.v1",
  "idempotency_key": "scheduled-watch:2026-09-17T13:00:00Z",
  "payload_digest": "sha256:example",
  "run": {
    "monitor_name": "Value Portfolio Watch",
    "trigger": "scheduled",
    "scheduled_at": "2026-09-17T13:00:00Z",
    "policy_version": "watch-policy.1"
  },
  "subjects": [
    {
      "stock_id": 123,
      "status": "complete",
      "subject_key": "stock:123",
      "coverage": [],
      "source_references": [],
      "fact_references": [],
      "price_references": [],
      "deterministic_deltas": [],
      "ai_proposal": {
        "proposal_version": "proposal.1",
        "baseline_research_revision_id": 456,
        "baseline_revision_number": 7,
        "citations": [],
        "proposed_changes": [],
        "contrary_evidence": [],
        "unresolved_questions": []
      }
    }
  ]
}
```

请求不得用 ticker 文本直接覆盖已解析的 stock identity；低相似或多上市地冲突进入
identity review。

## 14. 非功能要求

### 14.1 一致性与幂等

- 同一 source observation、run submission、proposal disposition、logical event 和 notification 都有稳定幂等键；
  所有用户级对象的幂等唯一性都包含认证得到的 owner namespace。
- 所有金额使用 fixed precision decimal，API 使用 decimal string；禁止二进制浮点写入
  权威金额。
- 当前投影与 append-only 事件要么同时提交，要么同时失败。

P0 使用以下恢复行为合同；确切字段和约束由后续 schema design 决定，但不得改变这些
可观察结果：

逻辑运行身份是 `(owner_id, logical_run_key)`。不同用户可以使用相同
`logical_run_key`，彼此不冲突、不可见，也不会共享幂等结果。

| 情况 | 必须行为 |
| --- | --- |
| 同一 owner/key、同一 payload digest 重试 | 只返回该 owner 已提交的结果，不重复 observation、fact、proposal、Inbox action 或 revision |
| 不同 owner 使用相同 logical run key | 分别创建各自运行，既不冲突也不返回对方结果 |
| 同一 owner/key、不同 policy/scheduled time/coverage envelope | 返回类型化 409，零业务写入 |
| 通过 run ID 访问另一 owner 的运行 | 返回不泄露存在性的 404，零业务写入 |
| 写入成功但响应丢失后重试 | 返回原提交/attempt 结果，不创建第二 attempt 的业务副作用 |
| 某 subject 已成功，同一 digest 再提交 | 幂等 no-op；保留首次可信接收、处理和成功持久记录时间 |
| 某 subject 失败或未收到，后续补交 | 在同一 logical run 下追加新的 submission attempt，只处理未完成 subject；补交对象使用实际首次成功 recorded_at，不回填失败尝试时间；既有成功对象不重建 |
| 已成功 subject 以同 run key 提交不同内容 | 返回类型化内容冲突；不得用“重试”改写历史 |
| 来源真实发布更正或新版本 | 使用新的 source version 和幂等身份追加，并建立 supersession；不复用旧请求伪装重试 |
| 仅报告渲染失败 | 追加 render attempt；重生报告不重新发布结构化事实或用户事项 |

Logical run 是计划执行身份，submission attempt 是传输/恢复尝试，subject result 是逐对象
当前投影加 append-only 状态事件，source version 是外部现实版本。聚合状态可由
`partial` 前进到 `complete`，但每次转换都追加事件，原 partial 历史保持可见。
只有覆盖实际补齐并满足运行合同才能推进该状态；用户处置 proposal 或确认无变化
本身不构成状态推进条件。

提案处置的幂等身份是 `(owner_id, proposal_id, disposition_key)`，与运行提交幂等键
分开；owner 仅来自认证上下文。每个 key 绑定完整处置请求内容，包括动作、预期
proposal 版本、case/baseline、编辑后的研究内容与原处置引用。不得只比较动作标签。
先验证当前访问权，再查找已成功的同内容请求；命中时返回原结果，否则按当前
proposal 终态/版本以及适用的 case/baseline 规则竞争首次原子提交。

| 提案处置情况 | 必须行为 |
| --- | --- |
| 同一待处理版本并发 reject 与 accept，或 reject 与 no_change | 恰好一个终态提交成功；另一个返回 disposition 冲突 409，无 revision、valuation 或事件副作用 |
| 处置成功但响应丢失，同 owner/proposal/key 和同内容重试 | 返回原 disposition 及原 revision（拒绝时为 NULL）；不因成功已推进 head 而重新保存或报陈旧基线 |
| 同 owner/proposal/key 不同内容 | 幂等内容冲突 409，零业务写入 |
| 已终态 proposal 换 key、相同或不同动作再次提交 | disposition 冲突 409；不能借新 key 覆盖、重复处置或重新打开 |
| 处置事务失败、回滚后重试 | 没有已成功处置可重放；重新验证当前版本、基线及权限，再竞争一次原子提交 |
| 用户明确重新考虑已拒绝 proposal | 原拒绝与提案保持不变；以当前基线重建带原拒绝引用的新候选提案，再显式处置；重试该重新考虑请求不得重复新建提案 |
| 通过 proposal/key 访问另一 owner 的处置结果 | 不泄露存在性的 404，零业务写入，不返回他人的幂等结果 |

### 14.2 可解释性

- 所有排序、重要性和“需要复核”判断展示规则版本和关键输入。
- 用户可从聚合图表逐级下钻到观察、来源和原始定位。
- 未知、冲突、过期、不可访问和计算失败是一级产品状态。

### 14.3 安全与隐私

- 用户身份来自认证上下文，不接受请求体 `user_id` 作为权限依据。
- 跨用户资源使用不泄露存在性的 404 行为。
- 服务接入使用可轮换凭证、最小权限、速率限制和请求大小限制。
- 外部 URL 视为不可信内容；来源抓取策略遵守授权和 retention policy。

### 14.4 性能目标（待基线校准）

- 20 家公司标准监控运行在正常数据源条件下 15 分钟内完成结构化写入；
- Research Inbox 首屏 P95 小于 2 秒；
- 单公司两年时间线 P95 小于 2 秒；
- point-in-time 回放可异步生成，目标 P95 小于 30 秒，并显示进度与 partial 状态。

### 14.5 可用性与恢复

- 外部来源失败不会丢失已验证的其他公司结果；
- 重试使用有界退避并区分 transient、permanent、permission 和 schema failure；
- 任何自动重放都不得重复创建用户修订或用户决定。
- 自动恢复只能补齐失败或未接收对象；不能自动接受 AI proposal、生成用户 revision
  或将真实来源更正当作幂等重试。

## 15. 成功指标

### 15.1 北极星辅助指标

`qualified_monitoring_obligation_completion_rate`

分母是在统计期内到期或由确定性规则生成的唯一监控义务；分子是在时限内由用户完成
合格复核的义务。合格复核必须包含：明确的人类 review action、审阅的证据范围、论点/
估值是否变化、关键反证或未决问题，以及下次复核时间。

同一 obligation key 的重复提交、重复确认无变化或重放不增加分子，也不改善完成率。
“无变化”和“有修订”仅在满足该项义务自身的完成条件时，才可完成该项义务；一次
review revision 不会批量完成同一 run/case 的所有义务。partial run 上的有限复核不把
仍开放的 coverage、correction、conflict 等义务计入分子，也不从分母移除或通过 snooze
美化完成率。复核次数仅作为诊断计数单独展示，不作为
优化目标。

### 15.2 质量指标

- 重大监控结论来源可追溯率：100%；
- Accepted Revision 的 AI 自动晋升次数：0；
- 历史记录被普通流程覆盖或删除次数：0；
- point-in-time 完整重建率：在声明支持的来源范围内 ≥ 95%；
- 运行覆盖缺口的显式展示率：100%；
- 监控事项在时限内被处理或合理 snooze 的比例；
- 因幂等失败产生的重复运行、事件或提醒：0。

### 15.3 反指标

- 不以提醒打开率、报告长度、交易数量或用户操作频率作为优化目标；
- 不以短期收益率作为单一产品质量指标；
- 不通过提高 AI “动作建议”数量提升参与度。

## 16. 分阶段交付

### Phase 0：合同与样本锁定

- 锁定 P0 的用户级私人运行模式、服务委托、支持来源/对象、历史起点和不支持范围；
- 定义可信时间、proposal lineage、coverage template、确定性规则、幂等恢复与
  supersession 合同；
- 选取 3–5 家公司、至少两个财报周期作为 gold set；
- 将本 PRD 获批条款合并进权威 PRD 和必要的 metric mapping。

退出条件：同一 gold set 能人工回答“当时知道什么、后来更正了什么”，且不存在
重复事实真相或 AI 权限绕行；gold set 至少覆盖有变化、未触发规则、缺失/冲突、来源
晚到、处理后迟交、可信时间回填、后续更正、部分恢复、陈旧 proposal、并发 head
前移、提案终态竞争与 partial run 上的有限复核。

Phase 0 必须为以下场景锁定预期结果并进入后续验收用例：

| 场景 | 必须结果 |
| --- | --- |
| 来源早已发布但系统晚到 | 只在服务端首次可信接收后进入回放，保留不同的发布时间 |
| 客户端或服务委托调用方回填可信时间 | API 拒绝其写入 received/known/processed/recorded/accepted 时间，零业务写入；不能进入更早 cutoff |
| 1 月 5 日可信处理、1 月 20 日首次成功记录 | 1 月 10 日回放不可见；20 日成功记录之后且依赖合格才可见，并同时展示处理与记录时间 |
| 外部声称早已处理，但提交失败且无可信持久处理记录 | 声称时间、日志或队列时间不能证明历史可见性；以 ValuePilot 后续可信校验/记录时间判断，不能证明的处理时间保持未知与 partial_reconstruction |
| 来源更正或撤回 | 更正前视图保留旧值；更正后按 source contract 显示新值或不可用；旧 revision 不变 |
| 旧文件被新解析器重跑 | 新结果使用自己的可信 `processed_at` 与 `recorded_at`，两者及依赖均合格才可见，不倒灌旧 cutoff |
| ticker/身份后来纠正 | 原 revision 保留当时显示身份；晚确认不能跨公司串联旧记录 |
| 价格币种未知或后来补录 | 旧 cutoff 仍为未知；不推测 USD、不隐式 FX |
| 当前来源权限丢失 | 按当前授权隐藏内容并显示 `source_unavailable`，不泄露私有片段 |
| A、B 两位用户使用相同 logical run key | 各自创建独立运行；重试只返回各自结果，互不冲突 |
| A 通过 run ID 访问 B 的运行 | 返回不泄露存在性的 404，且零业务写入 |
| 写入成功但响应丢失 | 重试返回原结果，不重复任何业务副作用 |
| A subject 成功、B subject 失败后补交 | A 不重建；B 可补齐；原 partial 和状态转换均可见 |
| proposal 基于 revision 5、head 已到 revision 6 | 返回 `proposal_baseline_stale`，不得刷新 head 后直接接受 |
| 两窗口对同一 proposal 并发拒绝/接受，或拒绝/确认无变化 | 恰好一个终态提交成功；另一个 409 且无 revision/valuation/event 副作用，即使拒绝未推进 case head |
| 处置成功但响应丢失；同 key 改内容；已终态后换 key | 同内容重试返回原 disposition/revision；改内容或换 key 不得重复或覆盖终态；按 §14.1 返回类型化冲突 |
| 用户明确重新考虑已拒绝提案 | 保留原拒绝，当前基线产生带原处置引用的新候选；重试只返回同一新候选；新接受独立记录，原提案不重开 |
| 必需来源撤权导致 partial，用户确认无变化 | 合格 review 可保存；run 仍 partial，界面和历史显示“在已审阅范围内维持，仍有缺口”；独立义务仍开放，不计完成分子，也不移出分母 |
| policy/criterion 在 cutoff 后修改 | 旧视图使用当时版本，新规则不改写旧排序或触发解释 |
| 同期间多来源冲突 | 保留冲突，不按数据库顺序选赢家，不借用后来解决结果 |

### Phase 1：P0 投资记忆闭环

- Monitor Run ledger 与结构化 ingestion API；
- 已获准来源/观察历史及其纠错关系；
- baseline comparison 与 AI candidate delta；
- Research Inbox 人工处理；
- kill criteria 的版本保存、证据关联与人工复核；
- company timeline、revision compare、声明范围内的 point-in-time 基础回放；
- 人类报告与机器结果同源。

退出条件：用户可以从一次新证据进入 Inbox，完成明确复核，生成 Accepted Revision，
并回放整个证据链。

### Phase 2：估值解释与主动证伪

- 在独立来源与 mapping 合同获批后实现 US-B2 估计序列；
- 确定性 IRR / 情景模型版本与重放；
- 估值变化归因；
- 获批定量 kill criteria 的确定性自动评价；定性条件继续人工判断；
- 有边界的通知与运行健康视图。

退出条件：任一历史估值可解释输入和版本；可能触发 kill criterion 的事项不会自动
变成交易指令。

### Phase 3：结果学习与描述性分析

- Outcome Checkpoint；
- 过程/结果四象限复盘；
- 带完整纳入/排除与缺失说明的描述性经营和收益分析；
- 在权限和价值明确后再评估语义检索。

退出条件：系统能够基于冻结的当时信息评价研究过程，且不会把股价结果倒灌为历史
判断的正确性，也不宣称 alpha、统计校准或模型优劣。真正的校准研究需要独立协议。

## 17. 关键风险与控制

| 风险 | 后果 | 控制 |
| --- | --- | --- |
| AI 论点惯性 | 旧叙事不断自我强化 | 强制反方证据、定期 clean-sheet review、人工接受 |
| 时间泄漏 | 历史复盘虚假准确 | 服务端可信接收/处理/接受时间、依赖可用性、重建 manifest、gold-set 测试 |
| 重复来源被当成独立证据 | 夸大信号强度 | 事件归并与来源独立性标记 |
| 模型版本混比 | 错误归因 IRR 改善 | 保存输入/版本，默认分组展示 |
| 价格噪音诱导交易 | 产品偏离长期价值投资 | 价格只触发信息检查，不生成动作建议 |
| 数据授权不清 | 合规与隐私风险 | Phase 0 先锁定 source policy 与 retention |
| 新表形成第二真相 | 筛选、估值和 UI 口径分裂 | 复用 canonical fact / valuation / research contracts |
| 事后用收益评价过程 | 强化坏流程 | 过程与结果分开，冻结当时证据 |
| 过度监控 | 用户被低价值事项淹没 | 有界 coverage template、确定性义务优先、AI 候选独立通道 |

## 18. 后续阶段门控问题

P0 已选择用户级私人运行、统一版本化确定性规则、人工确认 kill criterion 后返回
`researching`，并限定了支持来源。以下问题只阻止对应后续能力，不能由工程自行猜测，
但不再阻止 P0 投资记忆闭环：

1. US-B2 使用哪个获准 estimate provider，其 canonical metric keys、单位、fiscal period、
   GAAP/non-GAAP、NTM/FY、样本和历史基准合同是什么？
2. Expected IRR 的首个获批确定性模型、期限、情景权重、现金流/终值、公司行动和输入
   权威分别是什么？
3. Outcome Checkpoint 是按固定时间还是财报/年度事件；不同业务类型如何事前定义解决
   规则？
4. 哪些新增来源允许长期保存、展示和 AI 使用，撤权后哪些内容必须变为
   `source_unavailable`？
5. 哪些定量 kill criteria 可以进入确定性自动评价，其 comparison identity、持续时间和
   缺失处理如何批准？定性条件不进入自动判定。
6. 如果未来开展统计校准或方法比较，独立协议如何定义事前预测、完整纳入队列、解决
   规则、重叠样本、外部验证和最低数据门槛？

## 19. 产品验收总清单

- [ ] 新观察不会覆盖旧观察，纠错有 supersession 链。
- [ ] 任一重大结论都能回到来源、时间和当时可见版本。
- [ ] AI proposal 永远不能自动成为用户论点、估值或决定。
- [ ] 每个 proposal 能追溯 owner、case/cycle、baseline、输入 manifest、处理方式和最终 revision；陈旧基线不能直接接受。
- [ ] 用户可以明确接受、编辑、拒绝或确认无变化。
- [ ] proposal 终态版本独立于 case head 仲裁；处置、必要的 revision/valuation/event 原子提交，同内容重试不重复，不同内容或再次终态处置返回冲突。
- [ ] 重新考虑拒绝需显式操作与当前基线的新提案，保留原拒绝链；普通重试不得重开。
- [ ] 任一历史估值能说明方法、输入、版本、价格与研究版本。
- [ ] 纯价格波动不会自动成为业务恶化或买卖建议。
- [ ] 缺失、冲突、过期和权限失败不会被隐藏。
- [ ] point-in-time 回放逐类验证可信接收、处理、持久记录、依赖和接受时间；派生结果同时满足 processed_at 与 recorded_at 门槛，调用方不可回填可信时间。
- [ ] partial run 上确认无变化仅表达已审阅范围内维持；缺口、独立义务和真实完成率保留，不产生无条件的无变化结论。
- [ ] Research Inbox 优先永久损失风险和论点证伪，而不是市场热度。
- [ ] 结果复盘区分过程质量与结果好坏，不用简单平均收益宣称 alpha。
- [ ] 新能力复用现有 canonical facts、valuation 和 research revision 边界。
- [ ] 结构化 API 具备认证、幂等、schema version 和部分失败语义。
- [ ] 私人运行 owner 只来自可撤销服务委托；私有引用要求 owner 匹配，共享引用要求
  既有合同明确授权并逐次验证，其他 NULL-owner 数据不自动共享。
- [ ] 逻辑运行以 `(owner_id, logical_run_key)` 唯一；不同用户同 key 互不冲突，跨用户
  run ID 返回 404，同一用户的冲突提交返回 409。
- [ ] 重复、补交、内容冲突、真实来源更正和报告重生符合 §14.1 行为表。
- [ ] P0 不读取未获批分析师估计序列，也不把 `complete_no_rule_trigger` 表述为没有重大变化。

## 20. 产品结论

本产品真正的护城河不是更快地产生一次股票观点，而是逐年积累一套不可事后改写的、
用户拥有的投资研究记忆：事实何时出现、来源是否可靠、当时如何理解、哪些反证被看见、
估值为什么改变、最终由谁作出决定，以及后来哪些假设被证实或证伪。

因此，第一版最小闭环不是“数据库 + AI 买卖信号”，而是：

```text
结构化监控运行
  -> 带时间和来源的观察
  -> 相对已接受判断的候选变化
  -> 人工复核与不可变修订
  -> 可回放的历史时间线
```

只要这条闭环可靠，估值重放、kill criteria、结果校准和长期研究学习才有可信基础。

## 21. 对抗性评审与复审处置记录

“关闭”表示本草案已经给出唯一产品行为；仍需按 Phase 0 将获批合同并入权威 PRD，不能
把草案中的关闭状态解释为工程实现已经完成。

| Finding | 状态 | 本版决定 |
| --- | --- | --- |
| F-01 服务身份与私人授权 | 复审后关闭 | P0 固定为用户级私人运行；私有资源要求 owner 匹配；获准共享资源按既有合同验证访问权、stock、version、lineage 和 publication 绑定；其他 NULL-owner 数据不自动共享 |
| F-02 估计序列合同未批准 | 关闭 | US-B2 移至 P1 且合同门控；Phase 1 移除 Forward EPS；所有比较只读获批 canonical facts |
| F-03 历史可用时间不完整 | 经 IM-01 补充后关闭 | 服务端可信时间、依赖与 reconstruction manifest；派生结果同时受 processed_at 和 recorded_at 截止限制，不接受调用方回填 |
| F-04 proposal 接受链不完整 | 关闭 | 绑定 owner/case/cycle/baseline/input manifest/disposition/final revision；陈旧基线返回 409 |
| F-05 “无重大变化”由 AI 间接控制 | 关闭 | 改为 `complete_no_rule_trigger`；锁定 R1–R5 确定性规则；AI 使用独立候选通道 |
| F-06 kill criteria 阶段与状态矛盾 | 关闭 | P0 只保存并人工复核；确认触发按既有转换回到 `researching`；自动评价后移 Phase 2 |
| F-07 部分成功与恢复语义缺失 | 复审后关闭 | §14.1 增加恢复行为表，并将 logical run 唯一定义为 `(owner_id, logical_run_key)`；跨用户同 key 不冲突，跨用户 run ID 返回 404 |
| F-08 复核数量指标可能诱导重复操作 | 关闭 | 改为唯一监控义务的合格完成率；重复复核不增加指标 |
| F-09 校准与 alpha 准入不足 | 关闭并收缩 | P2 仅做描述性结果；统计校准、方法优劣和 alpha 需要独立获批协议 |
| IM-01 派生结果迟交/回填导致历史泄漏 | 合同修订并经独立复核关闭 | §8.3、US-B1/F1/G2、§14.1、Phase 0 与总验收补齐可信处理/持久记录双门槛及不可回填规则 |
| IM-02 提案终态缺少并发仲裁 | 合同修订并经独立复核关闭 | US-C3 与 §14.1 增加独立 proposal 版本、处置幂等内容校验、原子终态及明确重新考虑路径；保留既有 case/baseline 校验 |
| IM-03 有限复核可能隐藏未解决义务 | 合同修订并经独立复核关闭 | US-C3/E1、§14.1/15.1、Phase 0 与总验收明确 partial、独立义务与指标不因确认无变化而自动完成 |

本轮只修复 IM-01–IM-03。US-G2 延后属于可选交付取舍，未因本轮缺陷修复改变 P0
阶段安排；外部提交的可信时间约束已补齐。Lab 联合职责、扩展来源/事件合同和统计
校准仍按原有独立审批与分期处理，不能由本轮修订推定获批。

评审报告列出的 `unsupported` 批评未转化为新需求，因为现有文本已经禁止 AI 自动晋升、
第二估值真相、历史当前数据混入和普通流程修改不可变提取记录。此次修订不为这些已被
现有权威合同排除的情形增加平行机制。
