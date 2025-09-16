# FastAPI 服务初始化流程图

基于 `api.py` 中的 `lifespan` 函数分析的服务生命周期管理流程。

## 整体架构流程

```mermaid
flowchart TD
    Start([服务启动]) --> EnvCheck{环境检查}
    EnvCheck --> |ENV_MODE, DATABASE_URL| InitDB[初始化PostgreSQL连接池]
    
    InitDB --> CheckDB{数据库是否存在?}
    CheckDB --> |否| CreateDB[创建数据库]
    CheckDB --> |是| CheckTables[检查数据库表]
    CreateDB --> CheckTables
    CheckTables --> AutoCreate{表是否缺失?}
    AutoCreate --> |是| ExecSQL[执行fufanmanus.sql建表]
    AutoCreate --> |否| InitRedis[初始化Redis连接]
    ExecSQL --> InitRedis
    
    InitRedis --> |可选组件| InitAgent[初始化Agent API]
    InitAgent --> InitSandbox[初始化Sandbox API]
    InitSandbox --> InitTriggers[初始化Triggers API]
    
    InitTriggers --> CommentedAPIs[其他API组件<br/>已注释掉]
    CommentedAPIs -.-> |pipedream_api| Disabled1[💤]
    CommentedAPIs -.-> |credentials_api| Disabled2[💤]
    CommentedAPIs -.-> |template_api| Disabled3[💤]
    CommentedAPIs -.-> |composio_api| Disabled4[💤]
    
    InitTriggers --> Running[🟢 服务运行中]
    
    %% 清理阶段
    Running --> Shutdown([收到关闭信号])
    Shutdown --> CleanAgent[清理Agent资源]
    CleanAgent --> CloseRedis[关闭Redis连接]
    CloseRedis --> CloseDB[断开数据库连接]
    CloseDB --> End([服务停止])
    
    %% 错误处理
    InitDB --> |失败| Error1[❌ 启动失败]
    CheckDB --> |检查失败| Error2[❌ 启动失败]
    CreateDB --> |创建失败| Error3[❌ 启动失败]
    InitRedis --> |失败| Warn1[⚠️ 继续启动但记录警告]
    InitTriggers --> |失败| Warn2[⚠️ 跳过该组件]
    
    style Start fill:#e1f5fe
    style Running fill:#e8f5e8
    style End fill:#fce4ec
    style Error1 fill:#ffebee
    style Warn1 fill:#fff3e0
    style Warn2 fill:#fff3e0
```

## 关键组件说明

### 🔧 核心基础设施
- **PostgreSQL**: 主数据库，存储所有业务数据
  - 自动创建数据库（如不存在）
  - 基于 `fufanmanus.sql` 自动检查和创建16个核心表
- **Redis**: 缓存和会话存储
- **零配置启动**: 全自动数据库初始化，无需手动建库建表

### 🎯 业务组件
- **Agent API**: 核心AI代理服务，需要 `db` 和 `instance_id`
- **Sandbox API**: 代码执行沙盒环境
- **Triggers API**: 事件触发器系统

### 💤 暂停的组件
```
pipedream_api      # 工作流集成
credentials_api    # 凭证管理  
template_api       # 模板系统
composio_api       # Composio集成
```

### 🛡️ 错误处理策略
- **数据库连接失败**: 立即终止启动
- **Redis连接失败**: 记录警告但继续启动
- **可选组件失败**: 跳过该组件，不影响核心功能

## 配置依赖

```mermaid
graph LR
    ENV[环境变量] --> DB_URL[DATABASE_URL]
    ENV --> ENV_MODE[ENV_MODE]
    ENV --> LOG_LEVEL[LOGGING_LEVEL]
    
    DB_URL --> PG[PostgreSQL连接]
    ENV_MODE --> CORS[CORS策略]
    LOG_LEVEL --> Logger[日志级别]
    
    style ENV fill:#f3e5f5
    style PG fill:#e3f2fd
    style CORS fill:#e8f5e8
```

## 数据库表结构

从 `fufanmanus.sql` 自动创建的16个核心表：

```
用户认证: users, oauth_providers, user_sessions, refresh_tokens, user_activities
项目管理: projects, threads, messages  
代理系统: agents, agent_versions, agent_workflows, agent_runs
ADK框架: app_states, sessions, events, user_states
``` 