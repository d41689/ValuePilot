# Review prompts — PR #118(Oracle's Lens 页面渲染结构化 readiness warnings 时崩溃)

PR: https://github.com/d41689/ValuePilot/pull/118
Branch: `claude/fix-oracles-lens-readiness-warnings-crash`(未合并;基线 `main`)
读 diff:`git diff main...claude/fix-oracles-lens-readiness-warnings-crash`

## 这一票为什么值得审

这是个**在浏览器里实测发现**的真实崩溃:消费者页面 `/13f/oracles-lens` 一加载就崩到
React 错误边界(白屏)。根因是后端把 `readiness.warnings` 输出成结构化
`{ code, message }` 对象,前端却把它当字符串渲染(`{warning}` + `key={warning}`)。

修复很小(3 文件、+46/-5),但它**改了一个共享函数 `normalizeReadiness` 的输出形状**
—— 而这个函数有 **3 个消费者**。小改动 + 共享契约 = 真正的风险在 blast radius,不在那
一行渲染。请把审查重心放在"这个形状变更有没有悄悄改坏另外两个 admin 页面"。

## 变更清单

| 文件 | 改动 |
|---|---|
| `app/(dashboard)/13f/oracles-lens/page.tsx` | warnings 渲染 `warning.message`、`key={warning.code ?? index}`,兼容裸字符串 |
| `lib/thirteenfAdmin.js` | 新增 `normalizeReadinessMessages()`;`normalizeReadiness` 把 `warnings`/`blockers` 规整成 `{ code, message }`(裸字符串包装成 `{code:null, message:str}`) |
| `lib/thirteenfAdmin.test.js` | +1 回归测试(warnings/blockers 规整 + key 唯一性) |

## 评审者看不到的上下文

- **后端契约**:`backend/app/services/thirteenf_readiness.py` 的 `warnings` /
  `blockers` 是 `list[dict[str,str]]`,每个元素由 `_message(code, message)` 生成 =
  `{ "code": ..., "message": ... }`。这是**有意的结构化形状**,不是 bug —— 前端才是没跟上的一方。
- **三个 `normalizeReadiness` 消费者**(全部读它的输出):
  1. `app/(dashboard)/13f/oracles-lens/page.tsx:329`(本 PR 修的,渲染 warnings 文本)
  2. `app/(dashboard)/admin/13f/page.tsx:280`
  3. `app/(dashboard)/admin/13f/readiness/page.tsx:205`(此文件 line 117 附近对
     `normalizeReadiness` 的返回值有**显式 TypeScript 类型标注**)
- 作者声称"只有 oracles-lens 页面把 warnings 当数组渲染;两个 admin 页面只用
  `warningCount`(计数),所以不受影响"。**这句话是本次审查最需要独立证伪的断言。**
- **崩溃的两个症状同源**:`key={warning}` → `[object Object]`(两个 warning →
  "two children with same key");`{warning}` → 渲染对象("Objects are not valid as a
  React child, found: object with keys {code, message}")。三条 console 错误全部由这一处产生。
- 复现:登录 dev(`admin@valuepilot.local` / `YourStr0ng!Pass`,http://localhost:3001),
  访问 `/13f/oracles-lens`。真实 dev 数据的 readiness 会返回 `CONFIDENTIAL_TREATMENT` +
  `PARTIAL_COVERAGE` 两条 warning,修复前整页只剩 Next.js 错误遮罩。

## 作者已自行发现并说明的(judge,勿当新发现重报)

- 一开始怀疑第 808 行 `row.reasonChips.map(reason => <Badge key={reason}>{reason}</Badge>)`
  是同类问题,但 `primary_reasons` 实际是字符串数组(已核 API 的 50 个 item,全字符串),
  所以那处没问题。**真凶是 `readiness.warnings`。** 若你认为 reasonChips 在某种数据下
  仍会踩雷,请给出能产生非字符串 `primary_reasons` 的真实后端路径。

## 测试基础设施

前端测试在 web 容器里跑(**不要**在活着的 dev 容器里跑 `npm run build` —— 生产构建会
覆盖 `next dev` 的 `.next`,本机踩过一次):

```bash
docker compose exec -T web sh -lc 'node --test lib/*.test.js'   # 作者报告 180 pass
docker compose exec -T web npm run lint
# 生产构建(会 typecheck .tsx 的改动 + 三个消费者的类型):
docker compose exec -T web sh -lc 'NODE_ENV=production npm run build'
```

后端 readiness 形状可只读核对(需 auth token):

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8001/api/v1/13f/readiness \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('warnings[0]:', d['warnings'][0] if d.get('warnings') else None); print('blockers[0]:', (d.get('blockers') or [None])[0])"
```

---

## Prompt 1 — 契约变更的 blast radius(关键角度)

> 你在评审 ValuePilot 的 PR #118,分支 `claude/fix-oracles-lens-readiness-warnings-crash`。
> 只关注一件事:作者改了 `normalizeReadiness`(`lib/thirteenfAdmin.js`)的输出 ——
> `warnings` / `blockers` 从"原样透传后端"变成"恒为 `{ code, message }` 对象"。
>
> 这个函数有 **3 个消费者**(grep `normalizeReadiness` / `normalize13fReadiness`)。
> 作者断言只有 oracles-lens 页面受影响,两个 admin 页面只用 `warningCount`。
> **你的任务:独立证实或证伪这句话。** 逐个消费者:
>
> 1. `app/(dashboard)/admin/13f/page.tsx`(line ~280)—— 它读 `readiness.warnings` /
>    `readiness.blockers` 吗?怎么渲染?如果它此前把 warnings/blockers 当**字符串**
>    渲染(比如 `.join(', ')`、直接 `{warning}`、或 `.map(w => <x key={w}>{w}</x>)`),
>    那么在**本 PR 之前**它就已经有同类崩溃隐患;而本 PR 把形状固定成对象后,行为如何变化?
> 2. `app/(dashboard)/admin/13f/readiness/page.tsx`(line ~205,且 line ~117 有对
>    `normalizeReadiness` 返回值的**显式类型标注**)—— 那个类型把 `warnings`/`blockers`
>    声明成 `string[]` 还是 `{code,message}[]` 还是别的?本 PR 改了运行时形状,类型标注
>    还对得上吗?生产构建(`npm run build`)会不会因此 typecheck 失败,或者更糟——**类型
>    说是字符串、运行时却是对象**,悄悄埋一个新崩溃?
> 3. oracles-lens 页面自身:除了第 438 行的 warnings,页面别处还读 `readiness.blockers`
>    吗?blockers 也被规整成了对象,有没有某处仍按字符串消费 blockers?
>
> 对每个消费者给出:它读哪个字段、怎么渲染、本 PR 前后的行为、是否引入新问题。
> **能在浏览器复现就复现**(登录后访问 `/admin/13f`、`/admin/13f/readiness`,看 console
> 有没有 `[object Object]` / "Objects are not valid as a React child")。
> 结论:这个形状变更是否安全地覆盖了全部 3 个消费者?

## Prompt 2 — 同类 bug 猎杀(对象当 React child / 当 key)

> 你在评审 ValuePilot 的 PR #118。本次崩溃的本质是"把一个结构化对象直接当 React child
> 渲染,并且拿它当 `key`"。作者只修了 `readiness.warnings` 这一处。**你的任务:在 13F
> 前端里找出同一类还没被修的地方。**
>
> 系统性地查(`app/(dashboard)/13f`、`app/(dashboard)/admin/13f`、
> `components/oraclesLens`、`components/watchlist`、`lib/oraclesLens.js`、
> `lib/thirteenfAdmin.js`):
> 1. 所有 `key={x}` 且 `x` 可能是对象的地方(尤其 `.map(item => ... key={item} ...)`
>    直接用整个 item 当 key,而不是 `item.id` / `item.code`)。
> 2. 所有 `{x}` 直接把变量渲染成 child、而该变量可能来自后端的结构化字段的地方
>    (`reasons`、`caveats`、`unavailable_reasons`、`messages`、`flags`、`errors`……)。
> 3. 后端哪些字段是"曾经是字符串、现在是 `{code,message}` / `{code,label}` /
>    `{code,severity,...}`"的结构化对象?对每一个,前端消费方是否已按对象处理?
>    (提示:`caution_flags` 是 `{code,severity,scope,label}`;
>    `confidence_demotion_reasons` 是 `{code,label,...}`;readiness `warnings`/`blockers`
>    是 `{code,message}`。这些形状不一致,很容易某处用错。)
>
> 对每个候选:给出文件/行、会触发崩溃或错误 key 的**具体后端数据形状**、以及产品后果
> (整页崩 vs 局部错渲染)。能构造出真实数据复现的优先。区分"确认会崩" vs "推理未复现"。

## Prompt 3 — 修法的正确性、契约选择与测试充分性

> 你在评审 ValuePilot 的 PR #118。审修法本身与测试。
>
> 1. **规整方向对不对?** 作者把 `normalizeReadiness` 的 `warnings`/`blockers` 统一成
>    `{ code, message }`(裸字符串 → `{code:null, message:str}`),页面渲染 `.message`、
>    `key={code ?? index}`。另一种选择是统一成 `string[]`(取 `.message`)。哪种更符合
>    这个仓库既有的模式?(看别的 normalizer 怎么处理结构化列表,例如
>    `caution_flags`、`setup_checklist`。)`code:null` 会不会让 `key={code ?? index}`
>    在**多个 code 都为 null** 时退化成 index、从而在列表重排时出 React key 问题?
> 2. **`key={code ?? index}` 的唯一性**:如果后端某次真的返回两条 `code` 相同的 warning,
>    key 会不会再次冲突?现实里 readiness 会重复 code 吗?(看 `thirteenf_readiness.py`
>    的 `warnings.append` 逻辑——同一个 code 会不会被 append 两次。)
> 3. **测试是否复现了真实崩溃?** 新测试断言 `normalizeReadiness` 的返回形状 + key 唯一性,
>    但它测的是 **normalizer**,没有测**页面渲染**。崩溃发生在页面把对象当 child 渲染那一步。
>    有没有一个测试能在 normalizer 退回旧行为时变红、并且真正覆盖"渲染不再抛"?
>    (`uiStandard.test.js` 扫源码,`node --test lib/*.test.js` 只测 lib——页面 .tsx 的
>    渲染没有单测覆盖。这是本仓库的已知测试盲区,判断它在这里是否可接受。)
> 4. **兼容裸字符串是否必要?** 作者两处都加了 `typeof === 'object'` 的兼容分支。后端契约
>    已经稳定是对象,这个兼容是防御性冗余,还是有真实路径会传字符串?

---

## 输出格式(三个 prompt 共用)

写回 `docs/tasks/2026-07-10_oracles-lens-readiness-crash-review-results.md`:

```
## Verdict （可合并 / 需补正后合并 / 打回。一句话。）
## Findings
### P1/P2/P3 — <标题>
- 文件/行:
- 精确状态或输入（能触发的后端数据形状）:
- 现有代码会怎么做:
- 错误的产品后果（整页崩 vs 局部错渲染）:
- 是否已复现（贴命令/浏览器步骤 + 现象）；未复现则写"推理未复现"
- 建议修法:
## Missing Tests
## Non-findings（检查过、确认不是问题的，写出来避免重复劳动）
```

**规则:**
- **不要把作者已说明的 reasonChips 那条当新发现重报**;要 judge。
- **每个 finding 必须给出错误的产品后果**,不是"代码不优雅"。
- **能在浏览器复现就复现**(dev 已登录态,`/13f/oracles-lens`、`/admin/13f`、
  `/admin/13f/readiness`)。推理未复现的显式标注。
- Blast-radius 类结论(admin 页面是否受影响)**必须**实际看那两个页面的渲染代码或浏览器表现,
  不能只凭作者的一句"只用 warningCount"。
