## Verdict

可合并。结构化 readiness warning 的实际崩溃已修复，三个 `normalizeReadiness` consumer 的 blast radius 已覆盖；保留一项不阻断的 P3 页面渲染回归测试缺口。

## Findings

### P3 — 回归测试没有覆盖发生崩溃的 JSX 渲染边界

- 文件/行: `frontend/lib/thirteenfAdmin.test.js:73-90`; `frontend/app/(dashboard)/13f/oracles-lens/page.tsx:438-449`。
- 精确状态或输入（能触发的后端数据形状）: `GET /13f/readiness` 返回 `warnings: [{code: 'CONFIDENTIAL_TREATMENT', message: '...'}, {code: 'PARTIAL_COVERAGE', message: '...'}]`。
- 现有代码会怎么做: 当前 JSX 正确渲染 `message`，并以 `code ?? index` 作 key；新增测试只调用 `normalizeReadiness`，没有 import 或渲染页面/警告列表。
- 错误的产品后果（整页崩 vs 局部错渲染）: 将来若有人把 JSX 退回为 `{warning}` 或 `key={warning}`，normalizer 测试和生产 typecheck 仍可通过（JS normalizer 的值在页面侧没有静态对象-child 限制），但两条结构化 warning 会再次令 Oracle's Lens 整页进入 React error boundary。
- 是否已复现（贴命令/浏览器步骤 + 现象）: 推理未复现为当前 bug；`docker compose exec -T web sh -lc 'node --test lib/*.test.js'` 的 180 项均通过，证明现有测试未执行页面渲染。浏览器可打开 Oracle's Lens 且无 console error，但当前本地 readiness 没有 warning；按提示提供的 admin 登录在本环境被拒绝，因此无法在真实 warning payload 下完成浏览器复现。
- 建议修法: 提取一个轻量、可测试的 `ReadinessWarnings` 组件，或用现有前端测试运行时渲染该页面的 warning 区域；断言两个 `{code,message}` warning 渲染出两条 message 且不抛出。该测试应直接 import 页面实际使用的 renderer，而不是只测试 normalizer。

## Missing Tests

- P3 所述 structured warning 的页面级渲染回归测试。现有 unit test 正确测试了输出形状与给定 fixture 的 key，但不会在 JSX 把对象作为 child 时变红。

## Non-findings

- `app/(dashboard)/admin/13f/page.tsx` 是第二个 consumer，但未读取 `readiness.warnings` 或 `readiness.blockers`；它只使用 readiness 的级别、计数、任务等摘要字段。因此本 PR 前后均不存在它把结构化列表当字符串渲染的路径。
- `app/(dashboard)/admin/13f/readiness/page.tsx` 是第三个 consumer，但同样不读取 warnings/blockers。其显式类型是 `Record<string, unknown> & {...}`，没有错误地把这两个字段声明为 `string[]`；页面只使用已标注的 freshness、threshold、checklist 和 quality-report 字段。生产 build 已通过，未出现类型漂移。
- Oracle's Lens 只读取 `readiness.warnings`，没有读取 `readiness.blockers`；新的 normalizer 同时规整 blockers 不会改变该页面行为。
- 后端 readiness 均以 `{code,message}` 生成 warning/blocker。`build_admin_readiness` 的 `_merge_status_messages` 以 code 去重，consumer readiness 再做安全 code 过滤；同一 readiness response 中不会附加两个同 code warning。因此 `key={code ?? index}` 不会对当前真实后端产生重复 key。多个 legacy `code:null` 项退化到 index 仅会在重排时 remount 无状态 `<div>`，不会造成错误文本或崩溃。
- 兼容裸字符串没有当前后端生产路径：它是对历史/异常 payload 的防御性兼容，且把字符串包装为 `{code:null,message}` 是安全的。
- 同类结构化字段已按对象消费：`caution_flags` 经 `primaryCautionFlags` / `groupCautionFlags` 后以 `flag.code ?? flag.key`、`flag.label` 渲染；`confidence_demotion_reasons` 先筛选并映射为 `{code,label}`；holder `data_caveats` 先映射为 `{key,label,message}`；Watchlist drawer 的 caveat flags 由 TS 类型及 `flag.key` 消费。未找到把这些对象直接作为 React child 或 key 的路径。
- 作者说明的 `reasonChips` 不是同类 bug：后端 `_primary_reasons()` 与 score builder 均返回 `list[str]`，前端按字符串 badge 渲染；没有真实后端路径会把它变成对象。
- 浏览器检查：未认证状态下 Oracle's Lens 可正常挂载且 console 无 object-child/key error；admin 路由会转到登录页。由于本地 readiness 是 unavailable 且提示中的测试账户在此环境登录失败，未能以真实 `CONFIDENTIAL_TREATMENT`/`PARTIAL_COVERAGE` payload 完成三页浏览器回归；上述 consumer 结论据实际渲染代码与 build 交叉验证。

## Verification

- `docker compose exec -T web sh -lc 'node --test lib/*.test.js'` — 180 passed。
- `docker compose exec -T web npm run lint` — passed。
- `docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'` — passed；仅有现有 Browserslist 数据年龄提示。
