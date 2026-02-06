# 多用户迁移修复清单（P0->P1）

## Goal / Acceptance Criteria
- 输出一份可执行的 2-3 天修复清单，按 `P0 -> P1` 排序。
- 清单必须包含：
  - 文件级改动顺序（明确到具体路径）
  - Docker 内回归命令
  - 每阶段的完成判定（DoD）
- 输出文件为：`docs/multi-user-fix.md`。

## Scope
### In
- 基于当前 `HEAD` 与 `docs/multi_user_migration_plan.md` 的差距，制定修复落地路线。
- 覆盖后端 AuthN/AuthZ、前端鉴权接入、测试迁移、回归顺序。

### Out
- 不在本任务中直接修改业务代码与测试代码。
- 不在本任务中执行大规模全量回归（仅提供命令清单）。

## Files To Change
- `docs/multi-user-fix.md`（新增修复清单）
- `docs/tasks/2026-02-06_multi-user-fix-plan.md`（本任务日志）

## Test Plan (Docker)
- 文档类任务，无代码行为变化；本任务不执行测试。
- 为后续修复实施提供回归命令（将在 `docs/multi-user-fix.md` 中列出）：
  - `docker compose up -d --build`
  - `docker compose exec api alembic upgrade head`
  - `docker compose exec api pytest -q`
  - 以及按模块拆分的 `pytest` 命令集合。

## Notes / Decisions / Gotchas
- 决策：按“先封堵风险，再恢复主流程，再补全角色治理与测试”的顺序推进。
- 决策：以最小改动先打通单一鉴权路径（Bearer token），先去除前后端 `user_id` 双轨。
- Gotcha：当前仓库同时存在新旧两套调用约定，先统一接口契约，否则测试和前端会持续互相打断。

## Progress Log
- [x] 创建任务日志
- [x] 产出 `docs/multi-user-fix.md` 修复清单
- [x] 按修复清单完成实现（后端 + 前端 + 测试）
- [x] Docker 回归通过（后端全量 pytest）
- [ ] 人工评审并确认执行窗口

## Implementation Summary
- 后端：
  - 收紧鉴权边界：`screener`、`stocks/{id}/facts`、`stocks/prices/refresh`、`extractions`、`users` 管理均切换到 token 身份。
  - 新增 Admin 管理端点：`/api/v1/admin/users`（list/patch/disable）。
  - `screener` 增加可见性过滤：公共 parsed（admin）+ 当前用户 parsed/manual/calculated。
  - 移除默认用户配置项：`DEFAULT_USER_EMAIL`、`DEFAULT_USER_ID`。
- 前端：
  - `apiClient` 增加 Bearer 注入 + 401 清理与跳转。
  - 登录页改为真实登录流程，保存 token 与角色。
  - 新增 `frontend/middleware.ts` 做登录守卫与 admin 页面限制。
  - 移除 Upload/Documents/Watchlist/DCF 中所有 `USER_ID` 与 `?user_id=`。
  - 侧边栏对非 admin 隐藏 Upload。
- 测试：
  - 新增 `test_auth_api.py`、`test_authz_boundaries.py`。
  - 迁移旧测试到 Bearer 鉴权，不再使用 `?user_id=` 与默认用户播种假设。

## Verification Results (Docker)
- `docker compose up -d --build` ✅
- `docker compose exec api alembic upgrade head` ✅
- `docker compose exec web npm run lint` ✅（仅剩非阻断 warning）
- `docker compose exec api pytest -q` ✅ `108 passed`

## Contract Checklist
- [x] Screeners 查询来源为 `metric_facts`，并使用 `is_current = true`
- [x] 数值筛选基于 `value_numeric`（未引入 JSON 数值比较）
- [x] 未引入用户输入拼接 raw SQL
- [x] 未引入 eval/exec 公式执行
- [x] 解析链路的 `document_id/page_number/original_text_snippet` 合同未破坏
- [x] `metric_facts` 的 `is_current` 语义在手工 fair value 路径保持不变
