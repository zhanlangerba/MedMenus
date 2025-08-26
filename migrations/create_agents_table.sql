-- 创建Agent管理表
-- 用于存储用户的Agent配置和设置

CREATE TABLE IF NOT EXISTS agents (
    agent_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    system_prompt TEXT,
    model VARCHAR(100),
    configured_mcps JSONB DEFAULT '[]',
    custom_mcps JSONB DEFAULT '[]',
    agentpress_tools JSONB DEFAULT '{}',
    is_default BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    tags TEXT[] DEFAULT '{}',
    avatar VARCHAR(500),
    avatar_color VARCHAR(50),
    profile_image_url VARCHAR(500),
    current_version_id VARCHAR(128),
    version_count INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_agents_user_id ON agents(user_id);
CREATE INDEX IF NOT EXISTS idx_agents_is_default ON agents(is_default);
CREATE INDEX IF NOT EXISTS idx_agents_created_at ON agents(created_at);
CREATE INDEX IF NOT EXISTS idx_agents_updated_at ON agents(updated_at);
CREATE INDEX IF NOT EXISTS idx_agents_user_default ON agents(user_id, is_default);

-- 创建Agent版本表
CREATE TABLE IF NOT EXISTS agent_versions (
    version_id VARCHAR(128) PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL,
    version_number INTEGER NOT NULL,
    version_name VARCHAR(255) NOT NULL,
    description TEXT,
    system_prompt TEXT NOT NULL,
    model VARCHAR(100),
    configured_mcps JSONB DEFAULT '[]',
    custom_mcps JSONB DEFAULT '[]',
    agentpress_tools JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 外键约束
    CONSTRAINT fk_agent_versions_agent_id 
        FOREIGN KEY (agent_id) 
        REFERENCES agents(agent_id) 
        ON DELETE CASCADE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_agent_versions_agent_id ON agent_versions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_versions_is_active ON agent_versions(is_active);
CREATE INDEX IF NOT EXISTS idx_agent_versions_created_at ON agent_versions(created_at);

-- 创建Agent工作流表
CREATE TABLE IF NOT EXISTS agent_workflows (
    workflow_id VARCHAR(128) PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    workflow_config JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 外键约束
    CONSTRAINT fk_agent_workflows_agent_id 
        FOREIGN KEY (agent_id) 
        REFERENCES agents(agent_id) 
        ON DELETE CASCADE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_agent_workflows_agent_id ON agent_workflows(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_workflows_is_active ON agent_workflows(is_active);

-- 添加注释
COMMENT ON TABLE agents IS 'Agent管理表 - 存储用户的Agent配置';
COMMENT ON TABLE agent_versions IS 'Agent版本表 - 存储Agent的不同版本配置';
COMMENT ON TABLE agent_workflows IS 'Agent工作流表 - 存储Agent的工作流配置';

COMMENT ON COLUMN agents.agent_id IS 'Agent唯一标识符';
COMMENT ON COLUMN agents.user_id IS '所属用户ID';
COMMENT ON COLUMN agents.name IS 'Agent名称';
COMMENT ON COLUMN agents.system_prompt IS '系统提示词';
COMMENT ON COLUMN agents.model IS '使用的模型';
COMMENT ON COLUMN agents.configured_mcps IS '已配置的MCP工具';
COMMENT ON COLUMN agents.custom_mcps IS '自定义MCP工具';
COMMENT ON COLUMN agents.agentpress_tools IS 'AgentPress工具配置';
COMMENT ON COLUMN agents.is_default IS '是否为默认Agent';
COMMENT ON COLUMN agents.current_version_id IS '当前版本ID';
COMMENT ON COLUMN agents.version_count IS '版本数量';

COMMENT ON COLUMN agent_versions.version_id IS '版本唯一标识符';
COMMENT ON COLUMN agent_versions.agent_id IS '所属Agent ID';
COMMENT ON COLUMN agent_versions.version_number IS '版本号';
COMMENT ON COLUMN agent_versions.version_name IS '版本名称';
COMMENT ON COLUMN agent_versions.is_active IS '是否为活跃版本'; 