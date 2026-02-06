# ValuePilot 多用户重构 — 技术分析报告

---

## 一、差距分析报告 (Gap Analysis)

### 1.1 功能模块对比

| 功能模块 | PRD 要求 | 当前实现状态 | 差距 / 风险 |
|----------|---------|-------------|------------|
| **用户管理** | `users` 表存储 id/email/created_at | **部分实现** — 表存在，但仅有 id/email/created_at | 无密码字段、无角色字段、无认证机制。User 模型 (`backend/app/models/users.py`) 只有 3 个字段。 |
| **认证 (AuthN)** | PRD v0.1 未明确要求，但生产化必须 | **未实现** — `backend/app/core/security.py` 为空文件；`frontend/app/(auth)/login/page.tsx` 显示 "Authentication wiring is pending" | 所有 API 端点无任何鉴权，任何人可伪造 `user_id` 查询参数访问任意用户数据。**P0 安全风险。** |
| **授权 (AuthZ)** | 用户只能访问自己的数据 | **未实现** — `backend/app/api/deps.py` 仅提供数据库 session 依赖，无权限检查 | 后端信任客户端传入的 `user_id`，无中间件校验。跨用户数据完全无隔离。 |
| **用户身份自动播种** | 仅限开发阶段 | **硬编码** — 三个 endpoint 文件中的 `_get_user_or_seed()` 函数自动创建 user_id=1 | 生产环境必须移除此逻辑。当前在 `documents.py:18-53`、`stocks.py:21-55`、`stock_pools.py:24-58` 均有重复实现。 |
| **PDF 上传与解析** | 支持 Value Line 单页/多页 PDF 上传，三层存储（文档→抽取→事实） | **已实现** — 完整的 ingestion pipeline，支持多页 PDF | 上传接口强制绑定 `user_id` 查询参数，前端 `UploadZone.tsx:17` 硬编码 `user_id=1`。管理员上传 vs 普通用户上传无区分。 |
| **文档管理** | 用户可查看自己上传的文档列表、原文、重解析 | **已实现** — GET/POST endpoints 完整 | 前端 `documents/page.tsx:27` 硬编码 `USER_ID = 1`。所有用户看到同一份文档列表。 |
| **股票主数据** | stocks 为全局主数据，非用户私有 | **已实现** — stocks 表无 user_id | 符合 PRD 设计。但 `PUT /stocks/{id}/facts` 需要 user_id，目前无权限校验。 |
| **Metric Facts** | 用户级 metric_facts，支持 parsed/calculated/manual 三种来源 | **已实现** — 完整的 facts CRUD | `user_id` 作为查询参数传入，无验证。多用户场景下 facts 的 `is_current` 语义需要按用户隔离。 |
| **Metric Extractions** | 不可变审计追踪，含 document_id/page_number/original_text_snippet | **已实现** — extraction 保存完整 lineage | 正常。`user_id` 外键已存在。 |
| **Stock Pools (Watchlist)** | 用户创建多个 watchlist，CRUD + 成员管理 | **已实现** — 完整的 pool/membership CRUD | 前端 `watchlist/page.tsx:21` 硬编码 `USER_ID = 1`，7 处 API 调用均使用该常量。 |
| **Fair Value & MOS** | 用户可编辑 Fair Value，自动计算 Margin of Safety | **已实现** — PUT facts 接口 + 前端计算 MOS | 依赖硬编码 user_id。Fair Value 作为 manual fact 存储，多用户下需确保按用户隔离。 |
| **Screener** | 基于 JSON 规则的股票筛选 | **已实现** — POST /screener/run | 当前 screener 查询 metric_facts 时未过滤 user_id，多用户场景下可能返回其他用户的数据。 |
| **公式引擎** | 用户自定义公式，依赖 DAG，脏标记重算 | **已实现** — AST 解析 + 安全执行 | `formulas` 表已有 user_id 外键，但无 API endpoint 暴露。需要添加用户级 CRUD。 |
| **价格数据** | EOD 价格，支持 yfinance/twelvedata | **已实现** — stock_prices + refresh 接口 | stock_prices 为全局数据（无 user_id），符合设计。 |
| **价格提醒** | 用户配置价格警报，cooldown 机制 | **Schema 已存在** — price_alerts 表有 user_id | 无 API endpoint 暴露，无触发逻辑实现。 |
| **通知系统** | notification_settings + notification_events | **Schema 已存在** — 表和 ORM 模型已定义 | 无 API endpoint，无发送逻辑。ORM 模型在 `users.py:25-49` 中定义。 |
| **校准 UI** | PDF 查看器 + bbox 高亮 | **已实现** — calibration 页面 | 依赖硬编码 user_id 间接访问文档。 |
| **DCF 估值** | PRD 中作为未来规划 | **前端 UI 已存在** — `/stocks/[ticker]/dcf` 页面 | 超出 V1 范围，但前端已搭建框架。 |

### 1.2 硬编码 user_id=1 全景图

| 位置 | 文件 | 行号 | 具体代码 | 影响 |
|------|------|------|---------|------|
| 前端-上传 | `frontend/features/upload/components/UploadZone.tsx` | L17 | `'/documents/upload?user_id=1'` | 所有上传的 PDF 归属 user 1 |
| 前端-文档 | `frontend/app/(dashboard)/documents/page.tsx` | L27 | `const USER_ID = 1` | 文档列表/操作绑定 user 1 |
| 前端-Watchlist | `frontend/app/(dashboard)/watchlist/page.tsx` | L21 | `const USER_ID = 1` | 所有 pool 操作绑定 user 1 |
| 后端-配置 | `backend/app/core/config.py` | L24 | `DEFAULT_USER_ID: int = 1` | 全局默认用户 ID |
| 后端-环境变量 | `.env` | L12-13 | `DEFAULT_USER_ID=1` | 环境级硬编码 |
| 后端-文档接口 | `backend/app/api/v1/endpoints/documents.py` | L18-53 | `_get_user_or_seed()` | 自动创建默认用户 |
| 后端-股票接口 | `backend/app/api/v1/endpoints/stocks.py` | L21-55 | `_get_user_or_seed()` | 同上 |
| 后端-Pool接口 | `backend/app/api/v1/endpoints/stock_pools.py` | L24-58 | `_get_user_or_seed()` | 同上 |

---

## 二、多用户 RBAC 权限体系设计

### 2.1 角色定义

```
┌──────────────────────────────────────────────────┐
│                  RBAC 权限模型                      │
├──────────────────────────────────────────────────┤
│                                                  │
│  Admin (平台管理员)                                 │
│  ├── 上传/管理 Value Line 研报 (公共数据)             │
│  ├── 维护 stocks 主数据 (ticker/exchange)           │
│  ├── 管理 parser_templates                        │
│  ├── 查看所有用户状态 (不可查看用户私有数据)            │
│  ├── 管理用户状态 (启用/禁用/角色变更)                │
│  └── 刷新全局价格数据                               │
│                                                  │
│  User (普通用户)                                   │
│  ├── free: 受限读取 (查看公共研报/有限筛选)            │
│  └── premium: 完整读取 + 以下写权限                  │
│      ├── 创建/管理私有 stock_pools (watchlists)     │
│      ├── 编辑 Fair Value (私有 manual facts)        │
│      ├── 创建/执行自定义 formulas                   │
│      ├── 保存 screening_rules                     │
│      ├── 配置 price_alerts                        │
│      └── 配置 notification_settings               │
│                                                  │
└──────────────────────────────────────────────────┘
```

### 2.2 数据库角色模型

```sql
-- users 表扩展
ALTER TABLE users ADD COLUMN hashed_password VARCHAR NOT NULL;
ALTER TABLE users ADD COLUMN role VARCHAR NOT NULL DEFAULT 'user';
    -- role ENUM: 'admin', 'user'
ALTER TABLE users ADD COLUMN tier VARCHAR NOT NULL DEFAULT 'free';
    -- tier ENUM: 'free', 'premium' (仅对 role='user' 有意义)
ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE;
```

### 2.3 数据隔离与共享策略

| 数据类别 | 表 | 所有权 | 可见性规则 |
|---------|---|-------|----------|
| **全局公共 — 主数据** | `stocks`, `stock_prices`, `parser_templates` | 系统 / Admin | 所有用户只读 |
| **全局公共 — 研报数据** | `pdf_documents` (Admin上传), `document_pages`, `metric_extractions` (Admin上传的) | Admin | 所有用户只读。Admin 上传的研报及其解析结果为公共数据 |
| **全局公共 — 解析后事实** | `metric_facts` where `source_type='parsed'` 且来自 Admin 上传 | Admin | 所有用户只读。这是 Value Line 原始解析数据 |
| **用户私有** | `stock_pools`, `pool_memberships` | User | 仅创建者可读写 |
| **用户私有** | `metric_facts` where `source_type='manual'` | User | 仅创建者可读写 (Fair Value 等手动输入) |
| **用户私有** | `formulas`, `calculated_runs` | User | 仅创建者可读写 |
| **用户私有** | `screening_rules` | User | 仅创建者可读写 |
| **用户私有** | `price_alerts`, `notification_settings`, `notification_events` | User | 仅创建者可读写 |

### 2.4 现有 user_id=1 数据迁移策略

**建议方案：**

1. **将 user_id=1 指定为第一个 Admin 账号**。在迁移脚本中：
   - 为 user_id=1 设置 `role='admin'`、`hashed_password=<初始密码哈希>`
   - 该用户之前上传的 `pdf_documents` 及其关联的 `metric_extractions`、`metric_facts`(source_type='parsed') 自然成为公共研报数据

2. **user_id=1 的私有数据处理：**
   - `stock_pools` / `pool_memberships` → 保留归属 Admin，Admin 也可以有自己的 watchlist
   - `metric_facts` (source_type='manual') → 保留归属 Admin
   - 这些数据量在 MVP 阶段较小，不需要复杂迁移

3. **新建 `data_visibility` 字段（可选优化）：**
   - 在 `pdf_documents` 表增加 `visibility VARCHAR DEFAULT 'private'`（值：`public` / `private`）
   - Admin 上传的研报默认为 `public`，普通用户上传（未来如果允许）默认为 `private`
   - 这使得查询层可以简洁地过滤：`WHERE visibility='public' OR user_id=current_user_id`

### 2.5 权限矩阵

| 操作 | Admin | User (premium) | User (free) |
|------|-------|----------------|-------------|
| 上传 Value Line PDF | **写** | 禁止 | 禁止 |
| 查看公共研报及解析结果 | **读写** | **读** | **读** (有限) |
| 管理 stocks 主数据 | **写** | 禁止 | 禁止 |
| 刷新价格数据 | **写** | **写** (自己 watchlist 内) | 禁止 |
| 创建/管理 watchlist | **读写** | **读写** | 只读 (1个) |
| 编辑 Fair Value | **读写** | **读写** | 禁止 |
| 自定义公式 | **读写** | **读写** | 禁止 |
| 执行 Screener | **读写** | **读写** | 有限次数 |
| 价格提醒 | **读写** | **读写** | 禁止 |
| 管理用户 | **读写** | 禁止 | 禁止 |

---

## 三、分阶段实施路线图

### Phase 1: 数据库层改造

**目标：** 扩展 users 表，确保所有外键关联正确，为认证授权打好基础。

**步骤：**

1. **Alembic 迁移 — 扩展 users 表**
   - 新增字段：`hashed_password`(VARCHAR, NOT NULL, 需设置默认值以兼容现有记录)、`role`(VARCHAR, DEFAULT 'user')、`tier`(VARCHAR, DEFAULT 'free')、`is_active`(BOOLEAN, DEFAULT TRUE)、`updated_at`(TIMESTAMP)
   - 文件：新建 `backend/alembic/versions/xxx_add_user_auth_fields.py`

2. **数据迁移脚本 — 处理 user_id=1**
   - 将 user_id=1 的 `role` 设为 `'admin'`
   - 为其设置初始 `hashed_password`（通过环境变量 `INITIAL_ADMIN_PASSWORD` 注入，脚本中哈希后存储）
   - 确认所有关联数据（pdf_documents、metric_facts 等）的 user_id 外键完整性

3. **可选：pdf_documents 增加 visibility 字段**
   - `ALTER TABLE pdf_documents ADD COLUMN visibility VARCHAR DEFAULT 'private'`
   - 将 user_id=1 上传的文档 `UPDATE SET visibility='public'`

4. **更新 ORM 模型**
   - 修改 `backend/app/models/users.py`：User 类添加 `hashed_password`、`role`、`tier`、`is_active`、`updated_at` 字段
   - 更新 Pydantic schemas：`UserCreate`、`UserRead`、`UserUpdate`

**关键约束：**
- 迁移必须向后兼容，不能破坏现有数据
- `hashed_password` 对现有记录使用占位值，首次登录强制重设

---

### Phase 2: 认证模块 (AuthN)

**目标：** 实现注册、登录、Token 发放和验证。

**技术选型建议：JWT (JSON Web Token)**

| 方案 | 优点 | 缺点 | 建议 |
|------|------|------|------|
| **JWT (推荐)** | 无状态、易横向扩展、前后端分离友好 | 需处理刷新 Token、无法即时吊销 | **采用此方案** — 与 FastAPI 生态契合度最高 |
| Session + Cookie | 服务端可控、即时吊销 | 需 Redis 等 session store、CORS 复杂 | 不推荐 — 增加基础设施复杂度 |

**实施步骤：**

1. **安装依赖**
   - `python-jose[cryptography]` (JWT 编解码)
   - `passlib[bcrypt]` (密码哈希)
   - 添加到 `backend/requirements.txt`

2. **实现 security 模块** — `backend/app/core/security.py`
   ```python
   # 核心功能：
   # - hash_password(plain: str) -> str  (bcrypt, salt rounds=12)
   # - verify_password(plain: str, hashed: str) -> bool
   # - create_access_token(data: dict, expires_delta: timedelta) -> str
   # - create_refresh_token(data: dict) -> str
   # - decode_token(token: str) -> dict
   ```

3. **配置项扩展** — `backend/app/core/config.py`
   ```python
   SECRET_KEY: str          # JWT 签名密钥 (从环境变量读取)
   ALGORITHM: str = "HS256"
   ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
   REFRESH_TOKEN_EXPIRE_DAYS: int = 7
   ```

4. **Auth API 端点** — 新建 `backend/app/api/v1/endpoints/auth.py`
   - `POST /api/v1/auth/register` — 注册（email + password）
   - `POST /api/v1/auth/login` — 登录，返回 `{access_token, refresh_token, token_type}`
   - `POST /api/v1/auth/refresh` — 刷新 access_token
   - `GET /api/v1/auth/me` — 获取当前用户信息

5. **依赖注入 — 获取当前用户** — 修改 `backend/app/api/deps.py`
   ```python
   # 新增：
   # - get_current_user(token: str = Depends(oauth2_scheme)) -> User
   # - get_current_active_user(user: User = Depends(get_current_user)) -> User
   # - get_current_admin(user: User = Depends(get_current_active_user)) -> User
   #
   # 导出：
   # CurrentUser = Annotated[User, Depends(get_current_active_user)]
   # AdminUser = Annotated[User, Depends(get_current_admin)]
   ```

6. **前端认证集成**
   - 实现 `frontend/app/(auth)/login/page.tsx` — 登录表单
   - 新建注册页面
   - Axios interceptor 自动附加 `Authorization: Bearer <token>` header
   - Token 存储在 `httpOnly cookie` 或 `localStorage`（推荐 httpOnly cookie 以防 XSS）
   - 401 响应自动跳转登录页

**安全要求：**
- 密码哈希使用 bcrypt，salt rounds >= 12
- JWT Secret Key 至少 256 bits，从环境变量读取
- Access Token 有效期 30 分钟，Refresh Token 7 天
- 登录失败不泄露"用户是否存在"的信息

---

### Phase 3: 授权模块 (AuthZ)

**目标：** 用认证后的 `current_user` 替换所有 `user_id` 查询参数，实现数据隔离。

**实施步骤：**

1. **移除所有 `_get_user_or_seed()` 函数**
   - `backend/app/api/v1/endpoints/documents.py`: L18-53
   - `backend/app/api/v1/endpoints/stocks.py`: L21-55
   - `backend/app/api/v1/endpoints/stock_pools.py`: L24-58

2. **改造所有 API 端点签名** — 将 `user_id: int` 查询参数替换为 `current_user: CurrentUser` 依赖注入

   **改造前：**
   ```python
   @router.get("/documents")
   def list_documents(user_id: int, db: SessionDep):
       ...
   ```

   **改造后：**
   ```python
   @router.get("/documents")
   def list_documents(current_user: CurrentUser, db: SessionDep):
       user_id = current_user.id
       ...
   ```

3. **逐接口改造清单：**

   | 端点 | 改造内容 |
   |------|---------|
   | `GET /documents` | `user_id` → `current_user.id` |
   | `POST /documents/upload` | `user_id` → `current_user.id` |
   | `POST /documents/{id}/reparse` | `user_id` → `current_user.id` + 验证文档归属 |
   | `GET /documents/{id}/raw_text` | `user_id` → `current_user.id` + 验证文档归属 |
   | `PUT /stocks/{id}/facts` | `user_id` → `current_user.id` |
   | `GET /stock_pools` | `user_id` → `current_user.id` |
   | `POST /stock_pools` | `user_id` → `current_user.id` |
   | `DELETE /stock_pools/{id}` | `user_id` → `current_user.id` + 验证 pool 归属 |
   | `GET /stock_pools/{id}/members` | `user_id` → `current_user.id` + 验证 pool 归属 |
   | `POST /stock_pools/{id}/members` | `user_id` → `current_user.id` + 验证 pool 归属 |
   | `DELETE /stock_pools/{id}/members/{mid}` | `user_id` → `current_user.id` + 验证归属 |

4. **数据归属验证中间件**
   - 对于操作特定资源的端点（reparse、delete 等），必须验证该资源的 `user_id == current_user.id`
   - 不匹配时返回 `403 Forbidden`
   - 抽取公共函数：`verify_ownership(resource, current_user) -> None | raise HTTPException`

5. **Admin 专属端点保护**
   - 上传研报接口使用 `AdminUser` 依赖（仅 Admin 可上传公共研报）
   - 用户管理接口使用 `AdminUser` 依赖

6. **前端改造** — 移除所有硬编码 `user_id`

   | 文件 | 改造 |
   |------|------|
   | `frontend/features/upload/components/UploadZone.tsx` | 移除 `?user_id=1`，Token 自动鉴权 |
   | `frontend/app/(dashboard)/documents/page.tsx` | 删除 `const USER_ID = 1`，所有请求依赖 Token |
   | `frontend/app/(dashboard)/watchlist/page.tsx` | 删除 `const USER_ID = 1`，所有 7 处 API 调用移除 `user_id` 参数 |

7. **移除后端配置中的默认用户逻辑**
   - `backend/app/core/config.py`: 移除 `DEFAULT_USER_EMAIL` 和 `DEFAULT_USER_ID`
   - `.env`: 移除 `DEFAULT_USER_EMAIL` 和 `DEFAULT_USER_ID`

---

### Phase 4: 管理后台与业务逻辑适配

**目标：** 区分管理员操作和用户操作，适配公共/私有数据逻辑。

**实施步骤：**

1. **研报上传接口 — Admin Only**
   ```python
   @router.post("/documents/upload")
   def upload_document(
       current_user: AdminUser,  # 仅 Admin
       file: UploadFile,
       db: SessionDep,
   ):
       # 上传后 visibility='public'
   ```

2. **数据查询接口 — 融合公共 + 私有**
   - `GET /stocks/{id}/facts`：返回公共 facts（Admin 上传/解析产生的）+ 当前用户的 manual facts
   - Screener：查询时基于公共 parsed facts + 当前用户的 manual/calculated facts
   - 查询逻辑：`WHERE (user_id = :admin_id AND source_type='parsed') OR user_id = :current_user_id`
   - 或使用 `visibility` 字段：`WHERE visibility='public' OR user_id = :current_user_id`

3. **Admin 用户管理接口** — 新建 `backend/app/api/v1/endpoints/admin.py`
   - `GET /api/v1/admin/users` — 列出所有用户
   - `PATCH /api/v1/admin/users/{id}` — 修改用户状态/角色/tier
   - `DELETE /api/v1/admin/users/{id}` — 禁用用户

4. **前端路由守卫**
   - Dashboard 页面需要登录才能访问
   - 上传页面仅 Admin 可见
   - 用户管理页面仅 Admin 可见
   - 使用 Next.js middleware 检查 Token 和角色

5. **Screener 适配**
   - 当前 `backend/app/services/screener_service.py` 直接查 metric_facts，未过滤 user_id
   - 需要改为：查询公共 facts + 当前用户 facts，确保用户手动输入的 Fair Value 能参与筛选

6. **测试覆盖**
   - 认证流程测试（注册、登录、Token 刷新、过期）
   - 授权测试（普通用户不能访问 Admin 端点）
   - 数据隔离测试（用户 A 不能看到用户 B 的 watchlist/facts）
   - 迁移回归测试（现有数据在迁移后可正常访问）

---

### 实施优先级总览

```
Phase 1 (数据库层)
  │
  ├── 1.1 Alembic 迁移: users 表扩展
  ├── 1.2 数据迁移: user_id=1 → Admin
  ├── 1.3 ORM 模型 + Pydantic Schema 更新
  │
  ▼
Phase 2 (认证 AuthN)
  │
  ├── 2.1 security.py: 密码哈希 + JWT
  ├── 2.2 config.py: JWT 配置项
  ├── 2.3 auth endpoints: register/login/refresh/me
  ├── 2.4 deps.py: get_current_user 依赖
  ├── 2.5 前端: login 页面 + Axios interceptor
  │
  ▼
Phase 3 (授权 AuthZ)
  │
  ├── 3.1 移除 _get_user_or_seed()
  ├── 3.2 所有端点: user_id 参数 → CurrentUser 依赖
  ├── 3.3 资源归属验证
  ├── 3.4 前端: 移除所有硬编码 user_id
  │
  ▼
Phase 4 (业务适配)
  │
  ├── 4.1 Admin 专属上传接口
  ├── 4.2 公共/私有数据融合查询
  ├── 4.3 Admin 用户管理接口
  ├── 4.4 前端路由守卫
  ├── 4.5 Screener 多用户适配
  └── 4.6 完整测试覆盖
```

---

## 核心风险总结

当前系统的 **P0 安全问题** 是完全没有认证层，任何客户端可以通过修改 `user_id` 查询参数伪装成任意用户。Phase 2（认证）完成后即可消除此风险。
