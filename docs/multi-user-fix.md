# ValuePilot 多用户修复清单（P0 -> P1，2-3 天）

基线：以当前 `HEAD` 为准，目标是在 2-3 天内把“可用性 + 安全性 + 可回归性”恢复到可上线验收状态。

## 总体策略
- 先做 `P0`：统一鉴权路径、移除旧 `?user_id=` 双轨、封堵未鉴权数据面。
- 再做 `P1`：补齐 Admin 管理面、前端路由守卫、公共/私有数据查询策略、测试体系收口。
- 每天结束必须有可重复的 Docker 回归命令，避免“代码改完但无法验证”。

## Day 1（P0）封堵风险 + 打通最小主链路

### 1. 文件级改动顺序
1. `backend/app/api/v1/endpoints/users.py`
2. `backend/app/api/v1/endpoints/screener.py`
3. `backend/app/services/screener_service.py`
4. `backend/app/api/v1/endpoints/stocks.py`
5. `backend/app/api/v1/endpoints/extractions.py`
6. `backend/app/api/v1/endpoints/documents.py`
7. `backend/app/api/v1/endpoints/stock_pools.py`
8. `backend/app/api/deps.py`（仅在依赖签名需微调时）
9. `frontend/lib/api/client.ts`
10. `frontend/app/(auth)/login/page.tsx`

### 2. 具体修复项（P0）
- 后端统一要求 `CurrentUser`（至少：`screener`、`stocks/{id}/facts`、`extractions`、`users` 管理入口）。
- `screener` 查询增加用户边界：公共 parsed + 当前用户 manual/calculated。
- 上传与文档链路去除 query 参数式 `user_id` 依赖，全部以 token 身份推导。
- 前端 `apiClient` 增加 token 注入（interceptor）。
- 登录页从占位文案改为真实登录提交（最小可用）。

### 3. 当日回归命令（Docker）
```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api pytest -q tests/unit/test_documents_api.py
docker compose exec api pytest -q tests/unit/test_stock_pools_api.py
docker compose exec api pytest -q tests/unit/test_metric_facts_manual_fair_value.py
docker compose exec api pytest -q tests/unit/test_screener_api_metrics.py
```

### 4. Day 1 DoD
- 未登录访问敏感端点全部 `401/403`。
- 前端可通过登录获得 token 并完成至少一个受保护请求（如 documents list）。
- 不再依赖 `?user_id=` 才能调用后端。

---

## Day 2（P0 收口 + P1 开始）前端全面切换 + 测试迁移

### 1. 文件级改动顺序
1. `frontend/features/upload/components/UploadZone.tsx`
2. `frontend/app/(dashboard)/documents/page.tsx`
3. `frontend/app/(dashboard)/watchlist/page.tsx`
4. `frontend/app/(dashboard)/stocks/[ticker]/dcf/page.tsx`
5. `backend/tests/unit/test_documents_api.py`
6. `backend/tests/unit/test_stock_pools_api.py`
7. `backend/tests/unit/test_metric_facts_manual_fair_value.py`
8. `backend/tests/conftest.py`
9. 新增：`backend/tests/unit/test_auth_api.py`
10. 新增：`backend/tests/unit/test_authz_boundaries.py`

### 2. 具体修复项
- 前端所有 `USER_ID=1` 与 `?user_id=` 全量移除。
- 测试基建统一到新用户创建方式（包含 `hashed_password`）和 Bearer token 调用。
- 删除/替换依赖默认种子用户的用例。
- 增加认证回归用例：`register/login/refresh/me`。
- 增加授权边界用例：跨用户资源访问必须失败。

### 3. 当日回归命令（Docker）
```bash
docker compose exec api pytest -q tests/unit/test_auth_api.py
docker compose exec api pytest -q tests/unit/test_authz_boundaries.py
docker compose exec api pytest -q tests/unit/test_documents_api.py
docker compose exec api pytest -q tests/unit/test_stock_pools_api.py
docker compose exec api pytest -q tests/unit/test_metric_facts_manual_fair_value.py
docker compose exec api pytest -q tests/unit/test_screener_api_metrics.py
```

### 4. Day 2 DoD
- 现有关键页面（upload/documents/watchlist/dcf）在登录态下可用。
- 相关单测全部转到新鉴权约定并通过。
- 不存在“后端鉴权新约定 + 前端旧 query 参数”的双轨状态。

---

## Day 3（P1）管理面与策略补齐

### 1. 文件级改动顺序
1. `backend/app/api/v1/endpoints/admin.py`（新增）
2. `backend/app/api/v1/api.py`
3. `backend/app/schemas/users.py`（如需补充 admin patch 入参/出参）
4. `frontend/app/(dashboard)/layout.tsx`
5. `frontend/middleware.ts`（新增）
6. `backend/app/core/config.py`
7. `docker-compose.yml`
8. `.env`
9. 可选：`backend/app/models/artifacts.py` + 新 Alembic（若决定落地 `visibility`）

### 2. 具体修复项（P1）
- 新增 Admin 用户管理端点（list/patch/disable），强制 `AdminUser`。
- Dashboard 路由守卫（未登录跳登录；非 admin 不显示 admin 页面）。
- 移除 `DEFAULT_USER_EMAIL/DEFAULT_USER_ID` 运行时依赖。
- 可选：落地 `pdf_documents.visibility` 与公共/私有查询统一策略。

### 3. 当日回归命令（Docker）
```bash
docker compose exec api alembic upgrade head
docker compose exec api pytest -q tests/unit/test_auth_api.py
docker compose exec api pytest -q tests/unit/test_authz_boundaries.py
docker compose exec api pytest -q
```

### 4. Day 3 DoD
- Admin 能管理用户，普通用户访问 admin 端点被拒绝。
- 默认用户硬编码配置已移除，系统仍可启动并通过回归。
- 全量 pytest 通过。

---

## 交付闸门（必须全部满足）
- `docker compose up -d --build` 成功。
- `docker compose exec api alembic upgrade head` 成功。
- `docker compose exec api pytest -q` 全绿。
- 前端不再出现硬编码 `user_id`。
- 关键 API 无匿名越权读写路径。

