# MCO A 方案阶段验收：尚未完成，不可合并

> Historical record preserved during 2026-09-22 consolidation. Its status describes that checkpoint, not the current PR. See [final acceptance](../reports/2026-09-12_mco-plan-a-stable-acceptance.md) and [delivery record](../tasks/2026-09-12_mco-plan-a-delivery.md) for subsequent fixes and limitations.

## 结论

解析和正式发布已有可复现改善，但原验收标准尚未满足。不能把“能解析文件”“HTTP 200”“测试通过”当成完整可用。

- 最近三年核心数字：从 **20/27 提升为 25/27**；额外的 EPS、营业利润 **6/6**。
- 已发布的这 31 项：精确数字、fact/publication ID、原始输入及 statement 行列均通过认证 HTTP 核验。
- 浏览器抽样闭环：FY2024 营收查看原始证据 → 加入案例 → 保存 → 刷新 → 从历史修订重新打开，成功。
- Value Line 正常上传仍失败；另发现 FY2020 的新解析回归。未通过的部分没有标成 PASS。
- 尚未提交、推送、合并或部署；原工作区的用户修改未覆盖。

## 基线与数据隔离

修复分支 `codex/mco-plan-a`，基线 `15f4ba02944a6fe29962136665d9e906010c422a`。

浏览器/集成基线为已提交 S2 `1065f692a3b1453fa221c1da42cedbc4ab85a9fb` 加本次后端修复；不含原工作区未提交的 economics 变更。

仅本次数据库 `valuepilot_acceptance_mcoplana` 做离线重解析和正常发布；完整测试使用新建 `valuepilot_test_mcoplanaci` 内的独占测试 schema。保留文件只读、零外部 SEC/13F 请求、未改时钟、未操作生产。

预算沿用原实验基线，累计计入保留文件、原实验库、新克隆库、整个 CI 库和新增文件，没有重新归零。最新只读快照为 **581,363,903 bytes（约554 MiB）**，低于2GiB。原实验库仍为23项事实、10个parse runs；验收克隆为275项事实、30个runs。

## 已完成的修复

1. v2.10 精确允许未使用的空 documentation label，保留选中 label、图关系、上下文和金额校验。
2. v2.11 正确比较 `$ (1)` 等会计负数显示，并识别显式 `shares in Millions`；不修改原始数值、单位或旧版本语义。
3. 新数据库迁移验证新版本 lineage；保留旧运行记录，拒绝不安全降级。
4. 历史 publication 的精确请求可用其原版本重建后重放；未用直接返回旧 receipt 绕过校验。
5. Value Line revenues/per-share revenues 映射及四项相关 Decimal 精度修复；不把估计值标成 actual，不更改 SEC 指标定义。

## 仍未解决的问题

### 1. 原 27/27 数字目标与现有来源/发布契约不一致

| 核心单元 | 实际证据 | 当前结果 |
| --- | --- | --- |
| FY2022 流动长期债务 | 无批准概念 `LongTermDebtCurrent` 的直接披露；下一年本金偿还额为不同定义 | 不可补零或替代 |
| FY2023 流动长期债务 | FY2024 比较栏存在直接零值 | 目前只保留 occurrence，不授予历史余额发布资格 |

FY2023 的 raw34693/run29 不是可直接展示的 canonical fact。见 `sec_financial_ingestion.py` 的 `prior_fiscal_year_balance_sheet` 分支。此前提出的“26 数字加 1 缺失”也不能让当前代码通过。

### 2. FY2020 出现新回归

保留 R8.htm/artifact1072 第8行：2020 为 `$ (16)`，2019 真正空白，2018 为 `$ (1)`。原始 instance 也没有该行的2019事实。

新词法处理正确读到了两个真实负数，但 `sec_statement_authority.py:1218` 把下一个已识别的2018列当成上一年，731天间隔触发拒绝。v2.10 run15 成功，v2.11 run25 失败。

不能补2019零值、放宽350–380天或撤销正确的负数处理。需要明确不完整行的财年锚点规则；已有持久 v2.11 历史，不能改写其语义。

### 3. Value Line 正常上传被评分阻断连带回滚

正确隔离 API 的 document1 返回 HTTP200，但业务状态 `failed`，原因 `piotroski cannot use facts with unresolved source reconciliation`；24项收入映射在该文档中的持久结果为0。

季度 EPS 的期间身份缺失，在 SEC 与 VL 同时存在时触发共享对账 guard。评分原本只消费年度快照，但其竞争事实扩展仍会加载季度事实。上传在 `ingestion_service.py:355` 运行评分，异常于370行后触发整页 savepoint 回滚。

“只加 FY 查询条件”的小修复被真实隔离数据库测试反证：2个新测试仍失败，原15个评分测试通过。已撤回该试验的代码和测试；补丁保存在本次本地产物中，不加入交付测试集。

没有放宽共享 guard，也没有吞异常。现有读侧可把失效派生结果显示为 typed unavailable，但写入侧没有可直接复用的来源阻断结果。改变“正常来源冲突是否回滚合法基础事实”需要明确修改上传契约。

## 证据与限制

- v2.11 statement 聚焦测试：138 passed。
- v2.11 数据库聚焦测试：15 passed，294 deselected。
- VL 聚焦组：50 passed；真实文件纯解析/映射新增24项，旧301项未被改写。此项不等于正常上传通过。
- v2.10 初次完整后端：2830 passed /25 failed。22项是假文件写入只读目录，1项为测试库命名隔离检查，2项为旧迁移版本断言；保留失败结果，不称全绿。
- 新隔离 CI：全部六条精确命令按顺序通过。完整后端 **2883 passed /2 warnings，1037.30秒**，前端 **259 passed**，lint和生产构建通过。不包含已撤回的 FY-only 试验。是本地组合基线门禁，不是远端 CI。
- AAPL 三份保留年报只读复核：财年focus、18个report occurrence集合及最终概念拒绝集合一致。全JSON不一致，原因是已被拒绝概念新增细粒度记录。没有执行 AAPL 持久发布或浏览器回归。
- SEC v2.11 发布 run `ef288287-0e92-57de-8da3-7517a8495297`，新增132项 canonical facts；同一请求重放仍为275项总事实。
- 浏览器抽样保存为本次用户 case1/revision1，引用 fact613/publication262，精确营收 `7088000000.000000000000`；thesis、估值、投资决定均未填写。

完整执行记录和产物索引见 [任务记录](../tasks/2026-09-12_mco-plan-a.md)。本地原始证据及专有 PDF 不作为仓库分发材料。

## 已披露的隔离事故

早期一次辅助程序使用共享 Docker `api` 名称，误向旧测试库 `valuepilot_test_step_e_final_20260831` 创建一个本次专用账户及一个 refresh token。上传在解析前失败，核实无文档、无该用户财务事实写入。

已停用错误程序；之后只在核验过的本次 API 容器内访问127.0.0.1，浏览器 web 仅接私有网络。旧账户及 token 的清理尚未获用户批准，未擅自删除。事故不因后续隔离正确而被抹去。

## 建议的下一步，需要用户确认

保留全部27个核心位置和明确分母，但不强迫无证据位置产出数字：25项要求准确数值和证据，2项明确缺口。修复FY2020真实回归；把“评分因来源冲突不可用”与真正解析/执行失败分开，使合法基础事实能保留、不可用评分不泄漏。比较期余额发布支持单列后续。

执行顺序也应收紧：先对全部保留文件做无写入的候选版本回归，覆盖正常、空白、冲突和早期失败样本，完成独立核验后再冻结版本、迁移和持久化。不能只跑核心年份就认为不存在历史回归。

在收到确认前，不继续增加解析版本、放宽对账或修改这些契约；当前分支不可称完成或可合并。
