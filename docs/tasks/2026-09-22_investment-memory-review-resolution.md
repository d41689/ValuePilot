# Investment Memory：第三方对抗性评审修订

## Goal / Acceptance Criteria

修复用户提供的第三方评审中真实、属于草案合同范围的 IM-01、IM-02、IM-03。
推进产品北极星中的「主动证伪」与「监控论点」：历史回放可信、用户处置唯一，
且有限证据下的论点维持不会消除未知。交付为非规范性草案修订，不是功能实现。

- IM-01：可信处理与首次成功持久记录都不晚于 cutoff；迟交、客户端回填和
  无可信持久处理事件的情形有明确结果，成功重试不改写原时间。
- IM-02：同一 proposal 的终态处置有独立并发保护、带内容校验的幂等语义；
  处置与必要的 revision/valuation/event 原子提交；明确重新考虑保留历史。
- IM-03：partial run 上的有限复核保留 partial、独立义务、可见缺口和正确指标。
- 对应故事、通用合同、Phase 0 场景和总验收清单一致；独立只读复核无未解决的
  actionable in-scope finding 后结束，不借本次评审扩充体系。

## Scope / Authorized side effects

修订阶段只修改本地 `codex/investment-memory-proposal` 的文档；权威 PRD、应用代码、
schema、数据和交易权限均不变。2026-09-23 用户复审通过，明确授权提交、推送并合并；
通过专题 PR 将非规范性草案及修订记录纳入主线，按现有 CI/自动部署流程验收。

Files to change:
- `docs/prd/investment-memory-monitoring-prd-draft.md`
- 本任务记录
- `docs/BACKLOG.md`：仅在需要登记真实未决跨提案问题时追加对应项

PRD references: 上述草案 §8.3、US-C3、US-E1、US-F1、US-G2、§14.1、§15.1、
Phase 0、§19、§21；权威 `value-pilot-prd-v0.1.md` §G.2–G.4；
`docs/architecture/research-decision-support.md` §4、§7、§8、§10。

## Finding adjudication / scope decisions

| Finding | 裁定 | 最小修订 |
| --- | --- | --- |
| IM-01 / P0 | in-scope，现有派生结果过滤缺少 recorded_at 与可信处理时间边界 | 统一双时间门槛、外部声明不具权威、迟交和回填验收 |
| IM-02 / P1 | in-scope，reject 不推进 case head，现有 head CAS 无法仲裁提案终态 | proposal 版本与处置幂等键、原子提交、冲突与重新考虑的可观察语义 |
| IM-03 / P2 | in-scope，有限复核与独立义务/完成指标的关系未明确 | 限定维持判断范围，保留 run 状态、义务与指标分母 |
| US-G2 延后建议 | 可选范围取舍，不是已证实缺陷 | 本轮不改变交付阶段；修复其可信时间合同，不引入新外部服务 |

Lab 联合职责收口属于后续两份提案共同获批时的架构工作；来源覆盖/企业事件和
统计校准已由草案分期与合同门槛处理，不作为本轮新增需求。

## Test plan / evidence

修订前先按附件反例核对现行文字与已有代码；红色信号是三处缺失/矛盾合同，
不是尚未存在的 monitoring 功能测试。修订后逐项走查迟交/回填、处置竞争/重试/
重新考虑、partial 复核/指标场景；检查交叉引用、diff whitespace、变更范围；
由独立只读 verifier 检查合同一致性与范围控制。

项目 closing gate 要求的完整命令（隔离 Docker 验证环境，不能连接业务数据库）：

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

应用 CI 验证当前代码基线，没有证明草案功能已实现；产品合同验收以反例走查与
独立复核为证据。尚未执行的检查不得记为通过。

## Sign-off trail

- 修订前：读取用户附件，核对草案 0.3、权威架构及 research revision 保存路径。
  三项 finding 均确认；原工作区 clean。
- 草案修订至 0.4，三项修复同步至故事、通用合同、Phase 0、总验收与评审记录。
  Lab 联合职责在 BACKLOG 记录为低优先级后续协调；US-G2 不改变阶段。
- 独立只读 verifier 逐项核对全文和权威合同，结论 PASS，无未解决 in-scope finding；
  确认文档仍非规范性且未实施，`git diff --check` 通过。

### 反例走查（文档合同验证，不是运行时功能测试）

| 场景 | 草案 0.4 的唯一结果 | 对应条款 |
| --- | --- | --- |
| 1 月 5 日处理、20 日首次记录，回放 10 日 | 不可见 | §8.3、US-F1、Phase 0 |
| 上述对象在成功记录后回放、依赖齐备 | 可见且同时展示处理/记录时间 | §8.3、US-F1 |
| 调用方回填可信时间或用日志/队列时间证明早已知 | 拒绝可信字段写入；非权威声明不能获得历史可见性 | §8.3、US-G2 |
| 首次提交失败后补交；已成功对象重试 | 前者使用真实首次成功记录时间；后者保留原时间 | §14.1 |
| reject 与 accept/no_change 并发 | 一个终态成功，另一请求 409 且无业务副作用 | US-C3、§14.1 |
| 成功响应丢失、head 已前移后同内容重试 | 返回原 disposition/revision，不重复写入 | US-C3、§14.1 |
| 同 key 改内容、终态后换 key | 类型化冲突，不能覆盖、重复处置或重开 | §14.1 |
| revision/valuation/event 任一提交失败 | 整体回滚，重试重新校验当前版本/基线/权限 | US-C3、§14.1 |
| 明确重新考虑拒绝及其请求重试 | 当前基线生成一个带原拒绝引用的新候选；原终态保留 | US-C3、§14.1 |
| partial 上保存合格 no_change review | 保留 partial 与限定文案，不隐藏独立义务 | US-C3、US-E1、Phase 0 |
| 同一次 review 统计多个未解决义务 | 未解决义务不计入分子、不移出分母；snooze 不美化完成率 | §15.1 |

### 应用基线验证

使用当前分支归档加本次文档改动的临时副本，运行上述原样 canonical commands。
独立 Compose 项目 `vp-im-review-20260922` 通过专用网络
`vp-im-review-20260922-net` 连接测试用 Postgres stand-in；`db` 仍是 placeholder，
项目另有自己的默认服务网络，未接入 `projects-shared` 或共享业务数据库；
自动 ingestion/worker 关闭，凭证为临时测试值。Python/Node 全部在容器内运行。
日志保存在 `/Users/dane/.codex/backups/valuepilot-memory-review-20260922/`。

- 服务构建、迁移：PASS。
- 全量后端：**2955 passed**，2 个现有依赖弃用 warning，耗时 934.15 秒。
- 全量前端：**284 passed / 0 failed / 0 skipped**。
- lint、生产构建：PASS；六条 canonical commands 全部 exit 0。
- 23 个 User Story 的标题与优先级逐一和 HEAD 比较相同；无重复 ID，任务链接有效，
  `git diff --check` PASS。没有应用代码、schema、权威 PRD 或 metric mapping 改动。
- 本次验证后的结果记录属于文档收尾；运行时基线与完整验证的代码相同。
- 验证完成后仅移除本次专用 Compose 服务/测试卷、Postgres stand-in 与专用网络；
  Docker 清单复核无本次遗留运行资源，日志保留。既有开发/生产服务未操作。
- 2026-09-22 修订与本地验收完成时，改动保留在本地，未推送或部署。
- 2026-09-23 用户确认复审通过并授权提交、推送、合并。交付仅将草案与处理记录纳入
  主线；不把草案提升为权威实施合同，不宣称功能已实现。最终 PR CI、合并提交与
  自动部署结果由 PR/Actions 记录，以实际完成状态为准。
