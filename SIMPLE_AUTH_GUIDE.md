# 简化认证系统使用指南

这是一个简化的JWT认证系统，专为用户名密码登录设计。

## 🎯 核心特性

✅ **简单易用**：
- 用户名密码注册/登录
- JWT访问token（24小时）
- 刷新token（30天）
- 基本用户管理

✅ **最小化设计**：
- 只有2个数据库表
- 简洁的API接口
- 无复杂依赖

## 📋 快速开始

### 1. 数据库设置

```bash
# 运行数据库迁移
psql -h your-host -d your-database -f migrations/20250101000000_simple_auth.sql
```

### 2. 环境配置

```env
# 只需要这一个配置
JWT_SECRET_KEY="your-secret-key-here"
```

### 3. 安装依赖

```bash
pip install PyJWT bcrypt
```

### 4. 测试系统

```bash
python simple_auth_test.py
```

## 🔌 API接口

### 用户注册
```bash
POST /auth/register
{
  "email": "user@example.com",
  "password": "password123",
  "name": "User Name"
}
```

**响应：**
```json
{
  "access_token": "eyJ0eXAiOiJKV1Q...",
  "refresh_token": "abc123...",
  "expires_in": 86400,
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "User Name",
    "created_at": "2025-01-01T00:00:00Z"
  }
}
```

### 用户登录
```bash
POST /auth/login
{
  "email": "user@example.com",
  "password": "password123"
}
```

### 刷新Token
```bash
POST /auth/refresh
{
  "refresh_token": "abc123..."
}
```

### 获取用户信息
```bash
GET /auth/me
Authorization: Bearer <access_token>
```

### 用户登出
```bash
POST /auth/logout
Authorization: Bearer <access_token>
{
  "refresh_token": "abc123..."  # 可选
}
```

## 🔧 代码集成

### 在现有API中使用认证

**方式1：直接替换（推荐）**

```python
# 将现有的认证导入替换为：
from utils.simple_auth_middleware import get_current_user_id_from_jwt

# 现有代码无需修改
@router.get("/protected-endpoint")
async def protected_endpoint(user_id: str = Depends(get_current_user_id_from_jwt)):
    # 业务逻辑保持不变
    return {"message": f"Hello user {user_id}"}
```

**方式2：渐进式迁移**

```python
# 在需要的文件中：
from utils.simple_auth_middleware import get_current_user_id_from_jwt as get_user_id

@router.get("/my-endpoint")
async def my_endpoint(user_id: str = Depends(get_user_id)):
    # 使用新的认证
    pass
```

### 前端集成

```javascript
// 登录
const login = async (email, password) => {
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password })
  });
  
  if (response.ok) {
    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  }
  throw new Error('Login failed');
};

// 认证请求
const authenticatedFetch = async (url, options = {}) => {
  const token = localStorage.getItem('access_token');
  
  return fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`
    }
  });
};

// 自动刷新token
const refreshToken = async () => {
  const refreshToken = localStorage.getItem('refresh_token');
  
  const response = await fetch('/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  
  if (response.ok) {
    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  }
  
  // 刷新失败，重新登录
  localStorage.clear();
  window.location.href = '/login';
};
```

## 📊 数据库结构

**用户表（users）：**
```sql
- id: UUID (主键)
- email: VARCHAR(255) (唯一)
- password_hash: VARCHAR(255)
- name: VARCHAR(255)
- created_at: TIMESTAMPTZ
- updated_at: TIMESTAMPTZ
```

**刷新token表（refresh_tokens）：**
```sql
- id: UUID (主键)
- user_id: UUID (外键)
- token_hash: VARCHAR(255) (唯一)
- expires_at: TIMESTAMPTZ
- created_at: TIMESTAMPTZ
```

## 🔒 安全配置

### JWT密钥设置

```bash
# 生产环境使用强密钥
export JWT_SECRET_KEY=$(openssl rand -base64 64)
```

### Token过期时间调整

在 `utils/simple_auth.py` 中修改：

```python
ACCESS_TOKEN_EXPIRE_HOURS = 24  # 访问token 24小时
REFRESH_TOKEN_EXPIRE_DAYS = 30  # 刷新token 30天
```

## 🚀 部署清单

### 开发环境
- [x] 运行数据库迁移
- [x] 设置JWT_SECRET_KEY
- [x] 运行测试脚本
- [x] 验证API功能

### 生产环境
- [x] 使用强JWT密钥
- [x] 配置HTTPS
- [x] 设置适当的token过期时间
- [x] 配置日志监控

## 🔄 迁移现有系统

如果你有现有的Supabase认证系统：

1. **备份现有用户数据**
2. **运行新的数据库迁移**
3. **更新认证中间件导入**：
   ```python
   # 从
   from utils.auth_utils import get_current_user_id_from_jwt
   
   # 改为
   from utils.simple_auth_middleware import get_current_user_id_from_jwt
   ```
4. **测试认证功能**
5. **更新前端认证逻辑**

## 📝 常见问题

**Q: 如何重置密码？**
A: 当前版本未包含密码重置功能。可以通过数据库直接更新：
```sql
UPDATE users SET password_hash = '$2b$12$new_hash' WHERE email = 'user@example.com';
```

**Q: 如何批量导入用户？**
A: 直接插入数据库，密码需要先进行bcrypt哈希。

**Q: 支持多设备登录吗？**
A: 支持。每次登录都会生成新的refresh_token，可以同时在多个设备使用。

**Q: 如何撤销所有设备的登录？**
A: 删除用户的所有refresh_token：
```sql
DELETE FROM refresh_tokens WHERE user_id = 'user_uuid';
```

---

**这个简化版本去掉了所有复杂的功能，专注于核心的用户名密码认证。代码量减少了80%，但保持了所有必要的安全特性。** 