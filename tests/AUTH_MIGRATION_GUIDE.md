# 认证系统迁移指南

本指南帮助你从 Supabase Auth 迁移到本地 JWT 认证系统。

## 🎯 迁移概述

我们实现了一个完整的本地 JWT 认证系统来替代 Supabase Auth，包括：

✅ **完整的认证功能**：
- 用户注册和登录
- JWT token 生成和验证
- 刷新token机制
- 用户会话管理

✅ **API端点**：
- `POST /auth/login` - 用户登录
- `POST /auth/register` - 用户注册
- `POST /auth/refresh` - 刷新token
- `POST /auth/logout` - 用户登出
- `GET /auth/me` - 获取用户信息

✅ **兼容性**：
- 保持与现有业务逻辑的兼容
- 支持现有的API Key认证
- 渐进式迁移策略

## 📋 迁移步骤

### 1. 数据库迁移

首先运行数据库迁移脚本：

```sql
-- 运行迁移文件
psql -h your-host -d your-database -f migrations/20250101000000_local_auth_system.sql
```

### 2. 环境变量配置

在你的 `.env` 文件中添加JWT配置：

```env
# JWT认证配置
JWT_SECRET_KEY="your-super-secret-jwt-key-change-this-in-production"
JWT_ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30

# 保留现有的Supabase配置（过渡期使用）
SUPABASE_URL="your-supabase-url"
SUPABASE_ANON_KEY="your-anon-key"
SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
```

### 3. 安装依赖

确保安装了所需的Python包：

```bash
pip install bcrypt PyJWT python-multipart
```

### 4. 检查迁移前提条件

```bash
python utils/migrate_auth_system.py check
```

### 5. 创建测试用户

```bash
python utils/migrate_auth_system.py test-user "test@example.com" "password123" "Test User"
```

### 6. 验证新系统

测试新的认证端点：

```bash
# 测试注册
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123",
    "name": "User Name"
  }'

# 测试登录
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'

# 测试获取用户信息
curl -X GET "http://localhost:8000/auth/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## 🔄 渐进式迁移策略

### 方案1: 双系统并行运行

1. **现有用户继续使用Supabase认证**
2. **新用户使用本地JWT认证**
3. **逐步迁移现有用户**

### 方案2: 一次性迁移

1. **停止接受新的Supabase认证**
2. **迁移所有现有用户数据**
3. **切换到本地JWT认证**

## 📊 代码更改指南

### 后端更改

#### 1. 更新认证依赖

**旧代码：**
```python
from utils.auth_utils import get_current_user_id_from_jwt
```

**新代码（推荐的渐进式方法）：**
```python
# 使用新的认证函数，同时支持旧系统
from utils.auth_utils_new import get_current_user_id_from_jwt_new as get_current_user_id_from_jwt
```

#### 2. 保持API兼容性

现有的API端点无需修改，新的认证中间件会自动处理：

```python
@router.get("/some-endpoint")
async def some_endpoint(user_id: str = Depends(get_current_user_id_from_jwt)):
    # 业务逻辑保持不变
    pass
```

### 前端更改

你提到前端已经准备好了新的认证客户端，确保它：

1. **使用新的认证端点**：
   - `/auth/login`
   - `/auth/register`
   - `/auth/refresh`
   - `/auth/logout`
   - `/auth/me`

2. **正确设置请求头**：
   - `Authorization: Bearer <access_token>`
   - `X-Refresh-Token: <refresh_token>` (可选)

3. **处理token刷新**：
   - 自动检测token过期
   - 使用刷新token获取新的访问token

## 🔒 安全考虑

### JWT密钥管理

1. **生产环境**：使用强随机密钥
   ```bash
   # 生成安全的JWT密钥
   openssl rand -base64 64
   ```

2. **密钥轮换**：定期更换JWT密钥
3. **环境隔离**：不同环境使用不同密钥

### Token安全

1. **短期访问token**：默认1小时过期
2. **长期刷新token**：默认30天过期
3. **Token撤销**：登出时撤销刷新token
4. **会话管理**：跟踪活跃会话

## 🚨 故障排除

### 常见问题

#### 1. "auth_users table not found"

**解决方案：**
```bash
# 确保运行了数据库迁移
psql -h your-host -d your-database -f migrations/20250101000000_local_auth_system.sql
```

#### 2. "JWT verification failed"

**检查：**
- JWT_SECRET_KEY是否正确设置
- token是否过期
- token格式是否正确

#### 3. "User not found after registration"

**检查：**
- 数据库连接是否正常
- basejump账户是否正确创建
- 用户权限设置

### 调试技巧

1. **启用详细日志**：
   ```python
   import logging
   logging.getLogger('auth').setLevel(logging.DEBUG)
   ```

2. **检查token内容**：
   ```bash
   # 解码JWT token (仅用于调试)
   echo "YOUR_JWT_TOKEN" | base64 -d
   ```

3. **数据库查询**：
   ```sql
   -- 检查用户数据
   SELECT * FROM auth_users LIMIT 5;
   
   -- 检查刷新token
   SELECT * FROM auth_refresh_tokens WHERE user_id = 'USER_ID';
   ```

## 📈 性能优化

### 1. 缓存策略

```python
# 用户信息缓存（已实现）
cache_key = f"account_user:{account_id}"
await redis_client.setex(cache_key, 300, user_id)
```

### 2. 数据库索引

确保关键字段有索引：
```sql
-- 已在迁移脚本中包含
CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(email);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_token_hash ON auth_refresh_tokens(token_hash);
```

### 3. Token清理

定期清理过期token：
```python
# 使用定时任务
from utils.jwt_auth import TokenManager
await token_manager.cleanup_expired_tokens()
```

## 🔄 回滚策略

如果需要回滚到Supabase认证：

1. **保留Supabase配置**
2. **切换认证函数**：
   ```python
   # 从 auth_utils_new 切换回 auth_utils
   from utils.auth_utils import get_current_user_id_from_jwt
   ```
3. **禁用新的认证端点**
4. **数据同步**（如果需要）

## 📞 支持

如果遇到问题：

1. **检查日志**：查看详细错误信息
2. **运行诊断**：使用迁移脚本的检查功能
3. **查看文档**：参考API文档和代码注释
4. **渐进测试**：先在开发环境完全测试

---

**注意：** 这是一个重要的架构更改，请务必在生产环境部署前进行充分测试。建议先在开发/测试环境完成迁移和验证。 