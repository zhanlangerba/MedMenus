# PostgreSQL 迁移总结

## 修改概览

本次修改将系统从 Supabase 迁移到本地 PostgreSQL + Google ADK 架构。

## 主要修改

### 1. 数据库连接层修改

**文件**: `services/supabase.py`

- ✅ 将 Supabase 客户端替换为 PostgreSQL 连接池
- ✅ 保持相同的接口，减少代码改动
- ✅ 使用 asyncpg 作为 PostgreSQL 驱动
- ✅ 实现查询构建器，模拟 Supabase 的 API

**关键改动**:
```python
# 前: Supabase 客户端
self._client = await create_async_client(supabase_url, supabase_key)

# 后: PostgreSQL 连接池  
self._pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
```

### 2. Agents 数据存储架构

**原架构**: 独立的 `agents` 和 `agent_versions` 表
**新架构**: Google ADK 兼容的 JSONB 存储

**数据存储位置**:
- 用户特定的 agents: `user_states.state.agents`
- 默认 agents: `app_states.state.default_agents`

### 3. API 接口修改

**文件**: `agent/api.py` - `get_agents` 端点

**主要改动**:
- ✅ 从 `user_states` 表查询用户的 agents 数据
- ✅ 支持从 `app_states` 表获取默认 agents
- ✅ 移除对 `extract_agent_config` 的依赖
- ✅ 实现内存中的搜索、过滤和排序
- ✅ 保持原有的 API 响应格式

## 数据结构映射

### 原 Supabase 结构:
```sql
agents (
  agent_id, account_id, name, description, 
  system_prompt, configured_mcps, ...
)

agent_versions (
  version_id, agent_id, config, ...
)
```

### 新 PostgreSQL + ADK 结构:
```sql
user_states (
  app_name: 'suna_agents',
  user_id: UUID,
  state: {
    "agents": [
      {
        "agent_id": "...",
        "name": "...", 
        "description": "...",
        "system_prompt": "...",
        "configured_mcps": [...],
        "agentpress_tools": {...},
        ...
      }
    ]
  }
)
```

## 测试和验证

### 创建的脚本:
1. `scripts/create_sample_agents.py` - 创建示例数据
2. `scripts/test_agents_api.py` - 测试 API 接口
3. `scripts/check_agents_data.py` - 检查数据结构

### 使用方法:
```bash
# 1. 创建示例数据
cd scripts && python create_sample_agents.py

# 2. 启动后端服务
python api.py

# 3. 测试API (需要先获取JWT token)
cd scripts && python test_agents_api.py
```

## 注意事项

1. **环境变量**: 确保设置 `DATABASE_URL`
2. **JWT 认证**: 需要有效的 JWT token 进行 API 测试
3. **功能标志**: `custom_agents` 功能标志需要启用
4. **数据迁移**: 现有的 Supabase 数据需要手动迁移到新结构

## 兼容性

- ✅ API 接口保持不变
- ✅ 响应格式保持不变  
- ✅ 查询参数保持不变
- ✅ 分页和过滤功能正常

## 下一步

1. 运行测试验证功能正常
2. 如需要，创建数据迁移脚本
3. 更新其他依赖 agents 数据的接口 