# 用户认证系统设置指南

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements-auth.txt
```

### 2. 配置环境变量

创建 `.env` 文件：

```env
# 环境模式
ENV_MODE=local

# JWT配置
JWT_SECRET_KEY=your-super-secret-jwt-key-for-production

# 数据库配置（PostgreSQL）
DATABASE_URL=postgresql://username:password@localhost:5432/your_database
```

### 3. 初始化数据库

连接到你的PostgreSQL数据库，运行：

```sql
\i migrations/init_auth_tables.sql
```

或者手动执行SQL脚本内容。

### 4. 启动认证服务器

#### 方式一：独立测试服务器
```bash
python auth_test_server.py
```

#### 方式二：集成到主系统
```bash
python api.py
```

### 5. 测试API

```bash
# 注册用户
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123", "name": "Test User"}'

# 用户登录
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "password123"}'

# 获取用户信息
curl -X GET "http://localhost:8000/auth/me" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## 📋 API端点

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 用户登录 |
| POST | `/auth/refresh` | 刷新token |
| GET | `/auth/me` | 获取用户信息 |
| POST | `/auth/logout` | 用户登出 |
| GET | `/auth/health` | 健康检查 |

## 🔧 配置说明

### 数据库配置
- 使用本地PostgreSQL数据库
- 支持连接字符串配置
- 自动创建必要的表结构

### JWT配置
- 访问token有效期：24小时
- 刷新token有效期：30天
- 支持token自动刷新

### 安全特性
- 密码bcrypt哈希
- JWT token验证
- 刷新token机制
- 自动过期处理

## 🛠️ 故障排除

### 常见问题

1. **数据库连接失败**
   - 检查DATABASE_URL配置
   - 确保PostgreSQL服务运行
   - 验证数据库权限

2. **JWT验证失败**
   - 检查JWT_SECRET_KEY配置
   - 确保token格式正确
   - 验证token未过期

3. **依赖包缺失**
   - 运行 `pip install -r requirements-auth.txt`
   - 检查Python环境

## 📝 开发说明

### 文件结构
```
auth/
├── models.py      # 数据模型
├── service.py     # 业务逻辑
├── api.py         # API端点
└── __init__.py    # 模块初始化

utils/
├── postgres_client.py    # PostgreSQL客户端
├── auth_utils.py         # JWT认证工具
└── simple_auth_middleware.py  # 认证中间件
```

### 扩展功能
- 支持邮箱验证
- 支持密码重置
- 支持用户角色
- 支持API密钥认证

---

**这个专业版本专注于核心认证功能，使用本地PostgreSQL数据库，完全独立于Supabase。** 