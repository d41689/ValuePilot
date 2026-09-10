# Reading-first research path — PO体验修订与五步研究笔记

日期：2026-09-10；基于本地未提交S2 v1.3，用户明确授权实施PO建议两项。原S2修改和storage证据保留，不commit/push/部署。

## Goal / Acceptance Criteria

推进AGENTS的理解企业质量、可信盈利、主动否证及判断维护：用户先读事实，再自主记录观察、解释、待查证据、反证和当前判断。

1. 666px/窄屏及宽桌面下，年度表/明细只在表格内部横向滚动；展开不撑大图表或裁掉操作。
2. 财务阅读位于研究编辑和大型估值卡片之前；顶部保留简洁的决定/估值/价格状态和可跳转路径，缺失不隐藏。
3. 证据默认展示人类指标名、可读数值/单位、期间、报告和原始行列；精确值、全部输入、技术lineage仍可展开。失权/身份不符不泄露旧值。
4. 五步笔记为空起步，不自动推断因果或投资判断；用户明确追加到现有thesis，保留旧文本。没有新表、后端字段、状态机或事实写入。
5. 未追加的五步笔记在原浏览器草稿中保留，Save/Decide禁用并提示先追加或明确清空，不能静默丢弃；清空仅限笔记，不触碰thesis/证据。追加清空笔记，后续编辑和显式保存沿用既有revision/head/409/valuation契约。
6. 默认阅读、切换图表、刷新数字不会变更draft；旧案例、terminal只读、历史证据重开兼容。支持用户写“尚不能判断”，不赋予自动决策状态。
7. 来源覆盖文案明确用户PDF与共享SEC的区别，不推断完整覆盖。

## Scope

In：现有研究页布局、S2年度表与证据、一个受控五步笔记组件与纯辅助函数、前端测试和浏览器走查。Out：parser/迁移/重放/新财务公式/自动结论/新AI提案存储/生产/采集。共享财务数据与保留验收库只读；专用测试账户case2可通过UI显式追加标记为验收用途的draft revision，不改旧revision、估值或投资决定。backend测试仅生成隔离schema。

## References

- AGENTS.md；PRD G.2/G.3/G.4及H.10；research-decision-support架构。
- single-company-research-minimal-plan的S3：复用字段与显式保存，不新增状态机。
- [PO体验报告](2026-09-10_s2-po-experience-review.md)，PO-01–PO-04。

## Files to change

- frontend/app/(dashboard)/research/cases/[id]/page.tsx
- frontend/components/research/{AnnualFinancialsTable,FinancialEvidencePanel,ResearchPath}.tsx
- frontend/lib/researchPath.{js,d.ts,test.js}；证据格式辅助与相关组件测试
- docs/BACKLOG.md和本任务记录；无后端行为修改。

## Test plan

先写red测试：五步空值/未知判断/非破坏追加/精度格式化；实际组件渲染的可读与审计分层；页面顺序、保存保护。然后最小实现。

浏览器验证666px、窄屏、宽桌面几何尺寸，证据展开及失效UI、五步草稿追加/旧内容保留；不覆盖旧研究结论。全量closing gate沿用离线override关闭采集/通知，先确认开发库目标和独立pytest schema机制。时钟采样遇回退停止并报告，不弱化断言。

```sh
docker compose up -d --build
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest -q
docker compose exec -T web sh -lc 'node --test lib/*.test.js'
docker compose exec -T web npm run lint
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
git diff --check
```

## Execution / sign-off

实现、浏览器验证及本轮完整本地Docker门禁已通过。未commit/push/合并/部署；这是代理实施验收，不代替用户本人体验认可，也不声称完整S3或投资分析体系全部交付。

- Red：新增researchPath测试首先因模块缺失失败；新增实际证据组件渲染测试因FinancialEvidenceReading未实现失败。实现后聚焦33项通过，包含既有权限/证据身份、精度、图表和UI standard回归。`npx tsc --noEmit`与lint迭代检查exit0。
- 真实浏览器尺寸：666px展开前后两个shares/SBC图均532px；表格宽1328、容器566，横向滚动scrollLeft可达762。390px时图256、容器290、document宽390；1440px时图1042、容器1076、document宽1440。临时viewport override已reset。
- 证据：CFO#1988默认显示111,482,000,000 USD、FY2025和完整期间、原始行列、111,482及倍数1,000,000；技术展开后同一fact/publication、精确原串111482000000.000000000000、XBRL与locator仍可读。数值formatter不转Number，非零小数不截断；嵌套inputs及加减符号的实际组件渲染测试通过。
- 五步UI：空白起步；填写五项明确标记UI acceptance/test hypothesis的答案时Save禁用、Append可用。点击Append保留旧thesis逐字不变，追加全部五项，清空暂存区并打开完整编辑器。另一个temporary clear-control笔记验证Keep保留、Confirm clear仅清五步区，不改thesis。
- 明确点击专用测试案例Save research revision，新增**case2 draft revision 2**；Queued、无决定、无估值，原revision 1和CFO引用保留。随后重新加载页面，thesis与保存前逐字相等、五步区空白、Save禁用，两条历史引用入口均可见。没有把测试假设写成投资结论或qualified decision。
- 尚未将“未追加笔记的浏览器reload尝试”作为独立证明：当时存在beforeunload保护，工具未给出明确新导航证据。浏览器草稿JSON往返有单测；保存后的服务器重开已独立验证。
- 本轮未改后端、parser、migration或采集配置；只追加上述专用研究测试revision。预检开发库valuepilot、public migration20260909150000、既有pytest schema17个，closing gate沿用离线override并采样时钟。

### 最终门禁（当前工作区；不是远端CI）

| 实际命令 | 结果 |
|---|---|
| `docker compose up -d --build` | exit0；离线override关闭采集/worker/seed/通知 |
| `docker compose exec -T api alembic upgrade head` | exit0；仍为20260909150000，无新迁移 |
| `docker compose exec -T api pytest -q` | **2809 passed，2 warnings，926.47秒，exit0** |
| `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` | **259 passed，0 failed/cancelled/skipped，exit0** |
| `docker compose exec -T web npm run lint` | exit0 |
| `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` | exit0；TypeScript、27静态页面生成通过 |
| `git diff --check` | 通过 |

后端运行时使用独立pytest schema；PID31/start monotonic88205.65已退出，schema数回到17，未删除既有schema。16次READ ONLY时钟采样从19:12:49.546405Z至19:28:20.199583Z，wall与monotonic均前进约930.653秒，相邻增量差均小于1毫秒，未观察到回退；不代表永久修复已证明。两条warning仍为Starlette/httpx与AnyIO依赖弃用提醒。

后端运行期间补充了仅前端的pending-save只读保护：先新增断言确认red，再让五步笔记在`saveMutation.isPending`时只读并验证green；随后前端完整单测、lint、production build均针对该最终代码运行。后端未变更。

最终浏览器重开仍能显示阅读优先首屏和五步入口，Save禁用，没有未保存的测试笔记。Next自动生成的配置差异恢复为本轮前既有用户改动。PO-01–PO-04已从BACKLOG移除，原发现保留于PO报告并链接本次处理。长期时钟根因、拆股可比性及其他原有backlog不冒充已解决。

未独立覆盖：所有浏览器/视口、所有历史来源权限变化的真人UI流程、旧案例并发保存的完整浏览器矩阵。相关既有权限/身份/并发边界仍由全量自动测试覆盖；未扩大数据/来源权限来补齐验收。
