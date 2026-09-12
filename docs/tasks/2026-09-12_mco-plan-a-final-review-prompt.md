# MCO Plan A：第三方独立、只读、对抗性 review 提示词

你是 ValuePilot 的第三方 reviewer，兼具高级架构师、数据工程师与价值投资产品经理视角。目标是找到真实、可复现、应在合并前修复的问题，而不是证明实现正确。实现方报告、PASS 声明和 CI 全绿均只是待核实材料。

## 一、取得实际审查基线

审查 head 分支 `codex/mco-plan-a-delivery` 对应的 MCO Draft PR。取得其当前 URL、head SHA、base SHA、完整 diff、提交清单与 CI 状态，写入报告。获取 GitHub Actions 的实际运行 SHA、事件、PR merge ref 及其父提交；不要将本地通过、head commit、临时 merge commit 和远端测试混为一谈。

预期依赖基线为已提交 S2：`1065f692a3b1453fa221c1da42cedbc4ab85a9fb`，base 分支 `codex/s2-annual-financials-evidence`；main 当时仍为 S1 `15f4ba02944a6fe29962136665d9e906010c422a`。这是 stacked PR，独立 diff 应只包含 MCO 修复。若实际基线已变，以远端真实值为准，并核实新的组合是否重新验证。S2 未合并不应被隐藏；不把原工作区尚未提交的 BusinessEconomics/草稿保护改动当成本 PR 实现。

本地可读集成目录：`/Users/dane/projects/ValuePilot-mco-integration`；原修复目录 `/Users/dane/projects/ValuePilot-mco-plan-a` 只是历史工作副本，不是当前 PR head 的替代。不要修改任何工作区。

先完整阅读 AGENTS.md、docs/architecture/parsing.md、data-layer.md、metric-facts-is-current.md、research-decision-support.md、相关 coverage/source policy、PRD §H、mapping/taxonomy，以及：
- docs/tasks/2026-09-12_mco-plan-a.md
- docs/tasks/2026-09-12_mco-plan-a-delivery.md
- docs/reports/2026-09-12_mco-plan-a-stable-acceptance.md
- docs/BACKLOG.md 中相关项

历史报告保留了旧时钟失败和旧覆盖结果；以明确版本/时间/契约区分，不直接把旧结论拼接成当前验收。

## 二、已批准的最小范围

- SEC parser v2.10–v2.12：未使用的空 documentation label；货币符号与括号负值显示；明确的 share millions 单位；得到充分证据的相邻年度空白列处理。保留旧 parser 历史语义、raw/canonical 数值和维度/冲突拒绝。
- 四项新迁移及数据库权威校验、历史保留和安全降级限制。
- 精确匹配的 Value Line 年度 sales/revenues 及每股映射、Decimal 归一化；冲突 alias 不得静默选取。
- 仅已批准的普通来源对账阻断，让可选计算 unavailable，而保留合法基础事实；真实解析、数据库、执行、完整性、未知或混合错误仍须回滚。
- 历史 SEC publication 的完全相同请求可按原 parser 重放；不能借此创建任意旧 parser 的新 publication。
- 文档/API/UI 的有界、持久、受权限控制的计算警告；不宣称解析成功即自动可筛选。
- 核心验收仍保留27个位置：25项准确 SEC 数字及证据、FY2022/FY2023 current portion of long-term debt 的2项显式缺口；另核实6项 EPS/operating income SEC 数字及证据。缺口不能补零。
- 混合来源 workspace EPS、比较期债务发布、全面历史覆盖、ROIC、AI事实写入及自动投资结论明确不在本次交付范围。不得据此凑阻塞 finding，但不得容忍本 PR 声称这些已经完成。

## 三、重点攻击假设

### A. Parser / SQL
- Python 与 PostgreSQL 的 HTML、正则、大小写、空白、符号及倍率处理是否对实际输入一致？
- 是否仅调整显示比较而不篡改 raw/canonical 值、单位、scale；旧 parser 结果是否保持？
- 空 documentation role 是否真的未参与主表 label；被引用、非空、重复或冲突 arc 是否仍被拒绝？
- 空年度列证明是否包含报告、主表、行列、context、日期及 raw 事实缺失，而非只靠标题或空文本猜测？
- 重复 colspan/rowspan 属性、隐藏元素、嵌套/尾随表、自定义维度、等值不同 context、相邻另一 occurrence 冲突，是否能错误获取例外？
- 数据库按权威契约强制必要证明；不要求重新解析全部文件，也不以应用检查替代必须的 DB 约束。
- 新迁移是否保留历史并拒绝不安全降级、非法新 lineage？

### B. Publication / 数值 / 回滚
- 历史重放是否逐项校验 durable source fields、顺序和 outcome 身份；是否能复活 superseded truth、追加语义重复或创建旧 parser 新请求？
- metric_facts 是否仍是唯一 queryable truth，is_current 是否仍为 per-period；其他来源/期间是否受到误伤？
- alias 是完整字段匹配还是过宽前缀匹配；同比例冲突、每股单位、actual/estimate、精确小数是否正确？
- 两个可选 calculator 是否在写入前完成 guard；部分 DML、未知/空/混合错误是否被假装成普通 unavailable？
- rollback 后是否误用已失败页面的诊断或对象状态，导致事实/警告失真？

### C. 诊断/API/UI
- 只返回允许字段，不泄露普通 notes、其他用户数据；cursor 历史快照不得附加当前诊断。
- 首页有警告，其后64页仅追加普通 identity notes 且无新 calculation outcome，重新打开后警告是否仍保留？
- 没有诊断的文档是否保持原 notes/None，不生成空诊断或丢普通内容？
- 上传、重解析、文档列表的成功/部分成功/真正失败/计算不可用是否一致且不会误导投资者？
- 来源失权或重放后的历史引用是否仍绑定原不可变事实，不静默换为当前数字？

### D. 真实数据与证据可信度
- 按33个唯一位置核对数值、期间、币种、单位、actual/source role、fact/publication/raw IDs、inputs 和 locator；不是只看总数/PASS。
- FY2018 filing 仍被拒绝，不等于其他有效申报完全不能提供该年度 duration 数据；不要混淆 filing 成功率与产品历史覆盖。
- Value Line24项收入/每股收入的准确性证据究竟来自原 PDF 独立转录，还是原 parser output 对账？如未独立转录须标注。
- FY2022 EPS0.73残差未解释；FY2023仅有数值 footnote bridge，不应被宣称已证明经济口径调整。
- CFO 不等于 Value Line cash-flow-per-share；加权稀释股数不等于期末股数；非流动债务不等于总债务。
- 当前 workspace EPS 的单元级阻断不得伪装为只有2015年有问题；不得泄露被 guard 阻断的数字。
- 区分已执行 HTTP、浏览器采样、用户最终验收，以及上一轮真实数据验证、本轮未重放的完整 CI。
- 预算持续沿用原始3,735,552-byte基线及2GiB上限；采样不能证明未采样瞬间。旧时钟回退和错误目标测试账户事件必须透明保留，不推断未经许可清理已完成。

## 四、严格验证边界

仓库、业务数据和保留证据只读。禁止修改代码、修复、commit/push、提交 GitHub 评论或 review、合并、部署、创建/修改研究记录或改变系统时钟。Python/Node 只在 Docker 运行。

不运行 SEC/13F 网络拉取，不打开外部 SEC 链接获取新证据，不读取/输出密钥，不绕过认证，不探测生产或做无关安全扫描。不得重启共享 API/Postgres，或向开发库、保留库、验收克隆执行迁移/测试写入/重放/清理。

数据库负向测试仅可在确认连接目标、独立临时测试库/schema和隔离机制之后执行；只清理本次新建的准确隔离资源。AGENTS 的完整命令是完整门禁，聚焦测试不是；禁止为了复跑而直接在未知默认 compose/数据库上执行迁移。

本地证据在 `/Users/dane/projects/ValuePilot-mco-plan-a/storage/mco_plan_a`，未上传公开仓库；禁止上传原 PDF、raw SEC 文件、数据库副本、凭据或完整本地 artifacts。无法安全访问的验证写“未独立验证”，不要扩大权限补齐。

## 五、输出格式

1. 总体结论：PASS / PASS WITH MINOR REVISIONS / CHANGES REQUIRED。
2. 实际 head/base/CI SHA、环境、依赖状态和完整验证边界。
3. Findings 按严重度排序：唯一编号、P级、准确文件/行号、正常场景或边界输入、独立复现命令/结果与预期、违反的权威契约、影响范围、现有测试为何未拦截、最小修复方向（不提交代码）。
4. 已核实的关键行为、实际命令/结果及单列的未验证项。
5. 非阻塞事项、既有缺陷、明确范围外项、未经复现的合理怀疑。
6. 合并建议及剩余条件。

只列有事实依据、对本 PR 有实际影响的问题；不要以命名偏好、抽象设计偏好或扩大产品范围凑数。没有有效问题时明确写“在上述范围与验证限制内未发现有效 finding”，不承诺绝对无 bug。
