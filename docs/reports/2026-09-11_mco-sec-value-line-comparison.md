# MCO：现有 SEC 代码与 Value Line 报告的实测对比

> Historical record preserved during 2026-09-22 consolidation. Its status describes that checkpoint, not the current PR. See [final acceptance](../reports/2026-09-12_mco-plan-a-stable-acceptance.md) and [delivery record](../tasks/2026-09-12_mco-plan-a-delivery.md) for subsequent fixes and limitations.

日期：2026-09-11（执行时数据库 UTC 为 2026-09-12）。

## 结论

**本次没有完成可用于产品的 MCO 年度财务覆盖：9 份年报全部在证据校验阶段失败；1 份季报成功，正常发布 23 个 canonical facts，其中年度 FY facts 为 0。**

这不是“SEC 中不存在准确数据”的证据。沿同一批已下载文件调用现有底层 XBRL 解析函数，在不发布、不改写数据库的诊断模式下，可以读出与原始报表相符的候选值；FY2016–FY2024 的收入及股东权益分别 9/9 与 Value Line 的人工抄录值相等。**这些年度候选仍不是 metric_facts，不得接入产品或作为年度交付 PASS。**

本次最重要的调整方向，是先修复已明确复现的解析/映射兼容性和覆盖问题，建立真实样本对账，再扩展分析功能。并不能根据这次结果得出“应放弃代码，改让 AI 写入事实库”的结论。

## 1. 基线与执行边界

| 项目 | 实际值 |
|---|---|
| 代码 HEAD | `1065f692a3b1453fa221c1da42cedbc4ab85a9fb`，保留任务开始前已有未提交 S2/前端工作 |
| 用户材料 | `/Users/dane/Downloads/mco-0206.pdf`，1 页，报告日期 2026-02-13 |
| SEC 身份 | submissions 返回 `0001059556`、`MOODYS CORP /DE/`、MCO、NYSE、财年末 1231 |
| 申报选择 cutoff | `2026-02-13T00:00:00Z`；不包含后来披露的 FY2025 年报；未回填 knowledge time |
| 历史范围 | 当前 selector 上限十个已结束 FY：2016–2025；实际取得 FY2016–2024 九份年报，加 2025Q3 一份季报 |
| 未覆盖 | PDF 的 FY2010–2015、2025 年度实际值、2026+预测实现情况；没有将本次称为完整 PDF 历史覆盖 |
| 实验库 | 共享 PostgreSQL 实例上的独立库 `valuepilot_mco_compare_20260911`；实验 MCO stock ID 1 |
| 开发库 | `valuepilot` 保持只读，MCO stock 45 的 legacy exchange `US`、listing NULL 未改 |
| parser / migration | `xbrl-lineage-v2.9` / `20260909150000` |
| mapping | 原有已批准 `sec-us-gaap-v1`，未修改规则 |
| 获取路径 | 原有 EdgarClient → primary Rate Guard；实例 `34dc3fda-80e2-4260-9f29-848eedabde63`；实验进程禁止 fallback |
| 保留目录 | `storage/mco_sec_comparison/2026-09-11/`；原 SEC 字节在 `raw/`，原 PDF 只读 |

只在 Docker 中运行 Python。没有修改产品代码、迁移定义、mapping、系统时钟、共享服务配置、生产或旧保留验收数据。没有运行 13F。未 commit、push、合并或部署。独立库初始化运行现有全部迁移；不是向开发库执行迁移。

执行末开发库仍为 `metric_facts=2390`、`sec_financial_parse_runs=84`，与开始一致。实验所有文件加实验库 public 表/索引、扣除一次性迁移后基线的增量，测得 **348,178,013 bytes，约 332 MiB**，低于自设 2 GiB 边界；此数字包括约 95 MiB 的诊断 JSON，不仅是下载文件。最终报告自身有少量额外字节。

Rate Guard 抽样显示 403/429 为 0、503 为 1，并出现暂停时间；既有重试完成获取。该计数属于共享实例，未捕获任务独占的请求前后基线，**不能据此宣称精确的任务请求次数**。没有切换路径绕过失败。

## 2. 完整产品链路结果

Ingestion operation：`ee3beadd-64ef-4698-92f5-279936992dc4`，已正常提交并 separately finalized。

| 申报 | Accession | 结果 |
|---|---|---|
| FY2016 10-K | 0001193125-17-054522 | `unproven_prior_fiscal_cycle_anchor` |
| FY2017 10-K | 0001193125-18-058986 | `unproven_prior_fiscal_cycle_anchor` |
| FY2018 10-K | 0001193125-19-048576 | `invalid_label_arc` |
| FY2019 10-K | 0001059556-20-000005 | `invalid_label_arc` |
| FY2020 10-K | 0001059556-21-000010 | `invalid_label_arc` |
| FY2021 10-K | 0001059556-22-000012 | `invalid_label_arc` |
| FY2022 10-K | 0001059556-23-000016 | `invalid_label_arc` |
| FY2023 10-K | 0001059556-24-000017 | `invalid_label_arc` |
| FY2024 10-K | 0001059556-25-000025 | `invalid_label_arc` |
| 2025Q3 10-Q | 0001628280-25-046118 | succeeded；2,729 raw facts |

共创建 10 filings、2,539 artifact observations、10 parse runs。artifact observations 不是“下载了 2,539 个正文文件”的同义表达，包含 manifest 保留/不保留记录。

唯一成功 source 经过现有数据库数值归一化、publication 与 finalization，创建 24 normalizations、23 facts。publication run：`221932ed-af0b-571c-943d-731334f5e040`。相同 publication request 重复执行返回相同 run ID，facts 数仍为 23。**这是发布重放幂等验证，不是第二次网络 ingestion 幂等验证。**

`annual_coverage_gap:2025` 是报告时点选择结果，不是 FY2025 的解析错误；已下载的九份年报失败是另外的问题。不能把“拿到年报文件”和“年报数据可用”混为一谈。

## 3. 真正已发布的数值比较

以下全部来自实验库 `metric_facts`，均为 current SEC actual，period_type Q；金额为百万美元，EPS 为美元/股。Value Line 一侧直接核对原 PDF，未导入产品。

| 指标 / 期间 | SEC | Value Line | 实验 fact / publication ID |
|---|---:|---:|---|
| 收入，2025Q3 | 2,007 | 2,007 | 19 / 19 |
| 稀释 EPS，2025Q3 | 3.60 | 3.60 | 22 / 22 |
| 收入，2024Q3 比较列 | 1,813 | 1,813 | 18 / 18 |
| 稀释 EPS，2024Q3 比较列 | 2.93 | 2.93 | 21 / 21 |
| 流动资产，2025-09-30 | 4,599 | 4,599 | 2 / 2 |
| 流动负债，2025-09-30 | 2,499 | 2,499 | 3 / 3 |
| 长期债务非流动部分，2025-09-30 | 6,983 | 6,983 | 8 / 8 |

**上述预先列明的 7 个可比单元全部相等，不等于全部指标正确率 100%。** 没有给九份失败年报减小分母，也没有拿季报的 YTD 充当全年。

现金的差异体现了口径问题：SEC canonical `bs.cash_and_equivalents` 为 2,181（fact 1），Value Line 的 `Cash Assets` 为 2,259。同一 SEC 原始资产负债表另有短期投资 78：`2,181 + 78 = 2,259`。78 来自原文诊断证据，不是本次已发布的额外 canonical fact；该桥接不能直接变成新的产品字段。[已保留原表的来源](https://www.sec.gov/Archives/edgar/data/1059556/000162828025046118/R4.htm)

## 4. 年度候选对比：仅用于诊断，不能视为产品可用

为区分“底层读数错误”和“发布前证据校验失败”，在只读事务中，按已保留 manifest 校验 SHA/长度，调用项目原有 standalone/inline XBRL 解析函数。没有改动解析规则，没有写入 raw 表或 facts。

下表取各年度原始年报自身的整年空维度候选，保留 concept、context、unit、期间、ordinal 和 artifact 定位；只有唯一身份及唯一数值时才列值，相同身份重复 occurrence 全部保留在证据中。**这没有通过缺失的 statement authority，故下表各年度 canonical FY facts 仍为 0。**

金额：百万美元；EPS：美元/股。表内“SEC”均指诊断候选。

| FY | 收入 SEC / VL | 净利润 SEC / VL | 稀释 EPS SEC / VL |
|---|---|---|---|
| 2016 | 3,604.2 / 3,604.2 | 266.6 / 940.6 | 1.36 / 4.81 |
| 2017 | 4,204.1 / 4,204.1 | 1,000.6 / 1,178.3 | 5.15 / 6.07 |
| 2018 | 4,442.7 / 4,442.7 | 1,309.6 / 1,436.2 | 6.74 / 7.39 |
| 2019 | 4,829 / 4,829 | 1,422 / 1,588 | 7.42 / 8.29 |
| 2020 | 5,371 / 5,371 | 1,778 / 1,921 | 9.39 / 10.15 |
| 2021 | 6,218 / 6,218 | 2,214 / 2,309 | 11.78 / 12.29 |
| 2022 | 5,468 / 5,468 | 1,374 / 1,582 | 7.44 / 8.57 |
| 2023 | 5,916 / 5,916 | 1,607 / 1,822 | 8.73 / 9.90 |
| 2024 | 7,088 / 7,088 | 2,058 / 2,058 | 11.26 / 11.26 |

收入 9/9、股东权益 9/9相等。长期债务非流动部分的唯一候选在 7 年存在且与 VL 相等；FY2020、FY2021 此诊断选择没有得到该概念的唯一候选，保持不可比，**不是债务为零，也不是 SEC 没有披露**。不自行拿另一债务标签填补。

### 4.1 可以明确解释的差异

- **EPS 调整：**PDF 脚注 A 明确列出排除损益。FY2016–2021 及 FY2023，共 7 年，SEC EPS 加回脚注所列损失后，按显示精度与 VL 完全相等。例如 FY2023：`8.73 + 1.17 = 9.90`。这不证明各项经济调整都合理，只证明数值桥接。
- **FY2024 利润率：**SEC GAAP operating income=2,875、收入=7,088，利润率约 40.56%；加回 SEC D&A=431，得到 `(2,875+431)/7,088 = 46.6422%`，四舍五入到 VL 的 46.6%。Value Line 官方阅读指南将 Operating Margin 定义为折旧摊销前口径，不能要求它与 GAAP operating income/revenue 相等。其他年份加回 D&A 后并非全部对齐，不能把本年桥接推广为所有年份的完整调整解释。[Value Line 官方指南，第10页说明](https://investor.valueline.com/hubfs/Guides/1503516_Reading_VL_Report_WEB_2.7.17.pdf)
- **FY2024 Cash Flow/share：**用 SEC 归母净利 2,058、D&A 431，以及 VL 展示股数 180.31 百万作说明性桥接，`(2,058+431)/180.31 = 13.804…`，对应 VL 13.80。SEC CFO 是 2,838 百万，不是这个代理值。此处使用 VL 股数是跨来源解释算式，不是已批准的产品公式，也不证明其他年份全部能复算。[Value Line 对 Cash flow 的说明](https://www.valuelinepro.com/education)
- **FY2024 资本支出：**SEC 原文 Capital additions 317 百万；`317 / 180.31 = 1.758…`，可按两位小数对应 VL 1.76。仍须单独确认每股分母和支出定义后才可产品化。
- **债务组成：**FY2024 非流动长期债务 6,731 与 VL 相等；另有一年内到期部分 697，二者合计 7,428。不能把 6,731 称为全部债务，也不据二者合计宣称已覆盖租赁等全部义务。

原文抽检包括 FY2022–2024 `CONSOLIDATED STATEMENTS OF OPERATIONS`、资产负债表、现金流量表，以及 2025Q3 对应报表。保留结果见 `comparison.v2.json` 的 `source_statement_spot_checks`。例如 [FY2024 利润表](https://www.sec.gov/Archives/edgar/data/1059556/000105955625000025/R3.htm) 明确区分 net income 2,059 与 attributable to Moody's 2,058；本表比较后者，没有混入少数股东利润。

### 4.2 必须保留的未解释差异

**FY2022 EPS 不能按该页脚注对齐。**SEC 原始 FY2022、FY2023、FY2024 年报的 FY2022 EPS 都为 7.44；VL 表中为 8.57，差 1.13。但脚注列 FY2022 排除损失为 1.86：`7.44 + 1.86 = 9.30`，比表中 8.57 多 0.73。

因此，不能说“所有 EPS 差异都已被脚注解释”，也不能自动把 SEC 改成 8.57、或断言 VL 错误。需查该版分析师完整调整明细或更正记录。本次没有取得这些材料。[FY2022 原始利润表](https://www.sec.gov/Archives/edgar/data/1059556/000105955623000016/R3.htm)

此外，VL 早年 Operating Margin / Depreciation 与 SEC D&A 等仍有未逐项解释的差异；2023、2024 Cash Assets 与 cash+short-term investments 分别有约3、4百万美元残差，可能涉及展示舍入，但本次不认定已经证明。ROIC/Return on Total Capital 未执行未经批准的等价换算。

## 5. 确认的问题与最小调整方向

### A. SEC 标签检查范围过宽，导致整份年报不可用

FY2024 可精确复现：`mco-20241231_lab.xml` 中 `mco:RoyaltyCostMember` 的 `documentation` 标签为空，但标准 label 与 terseLabel 非空，locator 与 arc 完整，presentation 实际选择 terseLabel，不使用 documentation。`sec_statement_authority.py:543` 对所有英文 label role 无差别要求非空，于是在数值匹配前拒绝整份年报。

证据：label SHA `0f7962e33e55e899eb1d1ac8244268f5c176935dc054e3fe9aa1157afaaac63d`，原文件389–393行；presentation SHA `da9584b95fc885fe7ac3942204177ad4fcdc0e8cb4eba18188e5e9a3242d1c9b`，1334行。root 与独立只读 agent 均确认。未宣称整份 XBRL 已通过标准 schema 认证。

对 FY2018–2024 的现有 `_label_authorities` 原样离线调用均复现 `invalid_label_arc`。FY2019–2024 可见空 documentation；FY2018 还包含空 terseLabel，**不能用统一“忽略所有空标签”的修复**。

下一步：区分非展示说明与实际用于匹配的标签；让证据拒绝作用于必要、相关的输入，而不是无关说明导致整家公司年度失效。保留缺失引用、矛盾资源、实际展示标签为空等负例。按现有不可变 parser 版本/数据库 authority 契约变更并离线重放，不能原地改写旧 run，也不能为了通过而放宽金额、context 或维度检查。

### B. FY2016/2017 历史年度锚定失败，仍需独立定位

完整流程已复现 `unproven_prior_fiscal_cycle_anchor`；摘要发现和 label 解析正常。当前错误落在历史比较列/财年关系检查。尚未完整重放定位究竟哪个 occurrence 触发，不能把“列顺序”猜测写成根因。下一任务需以这两份保留原件建立最小失败样本，不允许猜财年或静默丢弃冲突。

### C. Value Line 收入已提取，但纯映射输出丢失

项目自己的 `scripts.value_line_dump` 正确提取 MCO annual `revenues` 与 per-unit `revenues`；现有 mapping 只识别对应 `sales` 路径。纯 mapping 结果301个候选 facts，`is.revenue/is.sales/per_share.sales` 都为0。

独立只读对照：仅在内存把两组键改为 sales，变为325个候选，新增24项（两项×2016–2027）。此实验没有修改配置、数据库或原始 JSON；它用于证明实际覆盖缺口，不是修复方案。需在批准的 mapping/taxonomy 中处理标签别名和收入含义，用此真实报告做回归，不能在运行时临时改名掩盖问题。

### D. Value Line 历史与预测表示还存在缺口

PDF 上半部每股序列自2010起，但当前 JSON 仅保留2016–2024历史。年度长期预测值使用硬编码 `projection_2028_2030`，而原 PDF 与 meta 是2029–2031；现有年度映射跳过非四位年份，因此影响是预测财务值未进入事实，不是污染2028年的实际值。顶层6个长期价格/回报候选也未携带目标年份范围。后续应分别处理“读取原文年份/保存范围”与“新增预测发布合同”，不可合并为不经审查的扩大功能。

## 6. 建议的下一任务

优先顺序：

1. **先完成 MCO 已保留样本的端到端可用性。** 修复 A，定位 B；以 FY2022–2024 最近三年核心实际值及原文证据为最小交付，早年缺口单独保持可见。全程离线，不必再次下载这批文件。
2. **修复已证明的 VL 收入映射缺口。** 同时验证 source role、实际/预测、年份、单位和精度，不追求“填满所有栏”。
3. **把差异分类做成验收产物。** 每格区分 exact/显示舍入、定义差异、可解释调整、未解释差异、数据不可用；不要输出一个掩盖覆盖率的总准确率。
4. **随后才做 AI 解释层。** 使用这些有证据的原始披露与调整差异，生成研究问题和反证；不能用 AI JSON 绕过这里失败的事实发布合同。FY2022 EPS 未解释残差可作为首个“必须承认不知道”的验收用例。

通过标准不能只是解析状态 succeeded：必须同时证明选定期间的必要数值可读、context/单位/来源正确、原文可核验，且真实负例仍被拒绝。本次实验保留了“不展示可疑数字”的安全性，但 MCO 年度可用性不达标；二者应分别评价。

## 7. 执行证据、命令与限制

详见 [任务合同](../tasks/2026-09-11_mco-sec-value-line-comparison.md) 和实验目录。可复核产物：

- `ingestion.json`：选择的10份申报、创建计数和 typed failures。
- `publication.json`：source set、24个normalizations、23facts及同请求重放。
- `metric_facts.json` / `sec_metric_publications.json` / `sec_metric_publication_inputs.json`：正式发布关系与值。
- `value_line.parser.json`：现有VL parser原样输出；`value_line.manual.json`：root按原页独立抄录的比较值。
- `diagnostic_summary.json` / `diagnostic_candidates.json`：原样底层解析的候选，明确标为非canonical。
- `comparison.v2.json`：完整逐年对比、context/ordinal/单位/源SHA、7个canonical核对、原表抽检。v1 `comparison.json`保留为中间结果，最终以v2为准；v2修正了人工检查的报表文件选择并排除隐藏术语定义表。
- `operate.py`、`diagnose.py`、`compare.py`：一次性实验编排/分析，不是产品代码变更。

实际执行：

```sh
docker compose -f /Users/dane/projects/infra/docker-compose.yml exec -T postgres \
  createdb -U infra_admin --owner valuepilot --template template0 valuepilot_mco_compare_20260911

# 下面的组合仅用于该新实验：脚本先验证连接，再仅替换到固定实验库。
docker compose run --rm --no-deps \
  -v /Users/dane/projects/ValuePilot/storage/mco_sec_comparison/2026-09-11:/experiment \
  -e PYTHONPATH=/code -e EDGAR_FETCH_MODE=live \
  -e EDGAR_RAW_STORAGE_DIR=/experiment/raw \
  -e RATE_GUARD_ALLOW_LOCAL_FALLBACK=false -e RATE_GUARD_FALLBACK_URL= \
  -e RATE_GUARD_EXPECTED_INSTANCE_ID=34dc3fda-80e2-4260-9f29-848eedabde63 \
  api python /experiment/operate.py init
# 同样前缀实际执行 ingest、publish、export 三个mode。

docker compose run --rm --no-deps \
  -v /Users/dane/Downloads/mco-0206.pdf:/input/mco.pdf:ro \
  -v /Users/dane/projects/ValuePilot/storage/mco_sec_comparison/2026-09-11:/experiment \
  api python -m scripts.value_line_dump --pdf /input/mco.pdf --out /experiment/value_line.parser.json

docker compose run --rm --no-deps \
  -v /Users/dane/projects/ValuePilot/storage/mco_sec_comparison/2026-09-11:/experiment \
  -e PYTHONPATH=/code -e EDGAR_RAW_STORAGE_DIR=/experiment/raw \
  api python /experiment/diagnose.py

docker compose run --rm --no-deps \
  -v /Users/dane/projects/ValuePilot/storage/mco_sec_comparison/2026-09-11:/experiment \
  -e PYTHONPATH=/code api python /experiment/compare.py
```

所有最终实验命令退出0；**ingest退出0只表示实验脚本完成并保存结果，不代表9个失败年报成功**。首次init启动遗漏PYTHONPATH，import阶段退出1；补齐进程环境后初始化成功，未修改产品代码。实验脚本禁止覆盖主要已有产物，因此不能直接重复上述创建/写出命令。

未执行完整 canonical CI，因为本次是数据分析而非代码发布；没有用聚焦检查冒充 closing gate。未执行浏览器中的MCO产品验收（数据仅在实验库）、未证明全部23facts均通过用户点击证据、未验证全部XBRL标准合规性、未验证所有行业、未进行完整非GAAP调整审计。研究 thesis、估值及用户案例未改变。

独立审查已完成：一名只读 agent 复核标签根因与 VL 纯映射行为；另一名只读 verifier 在无网络、只读 Docker 容器中复核全部23个导出 canonical facts 的身份/期间/单位/值、7个可比单元的选择，以及年度证据的123个原始 XML occurrences（含文件SHA/长度、CIK、context、单位、期间和数值）。还复算了 FY2022 EPS 残差、FY2024 利润率及2025现金桥接，未发现本批比较选择错误。verifier 未直接读取 PDF，VL 人工基准依赖 root 对原页的视觉核对；也未独立核实所有2,539条 artifact observations 或实时数据库隔离，不能将这些边界算作全面认证。

已确认缺口与未解释对账项已记录在 [BACKLOG](../BACKLOG.md)，未实施修复。保留实验库与文件供复审，不擅自删除。
