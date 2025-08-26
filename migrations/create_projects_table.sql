-- 创建项目表
-- 用于存储用户的对话项目

CREATE TABLE IF NOT EXISTS projects (
    project_id VARCHAR(128) PRIMARY KEY,
    account_id VARCHAR(128) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',
    metadata JSONB DEFAULT '{}',
    sandbox JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_projects_account_id ON projects(account_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at);
CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects(updated_at);

-- 创建线程表
CREATE TABLE IF NOT EXISTS threads (
    thread_id VARCHAR(128) PRIMARY KEY,
    project_id VARCHAR(128) NOT NULL,
    account_id VARCHAR(128) NOT NULL,
    name VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 外键约束
    CONSTRAINT fk_threads_project_id 
        FOREIGN KEY (project_id) 
        REFERENCES projects(project_id) 
        ON DELETE CASCADE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_threads_project_id ON threads(project_id);
CREATE INDEX IF NOT EXISTS idx_threads_account_id ON threads(account_id);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);
CREATE INDEX IF NOT EXISTS idx_threads_created_at ON threads(created_at);

-- 添加注释
COMMENT ON TABLE projects IS '项目表 - 存储用户的对话项目';
COMMENT ON TABLE threads IS '线程表 - 存储项目中的对话线程';

COMMENT ON COLUMN projects.project_id IS '项目唯一标识符';
COMMENT ON COLUMN projects.account_id IS '所属用户ID';
COMMENT ON COLUMN projects.name IS '项目名称';
COMMENT ON COLUMN projects.description IS '项目描述';
COMMENT ON COLUMN projects.status IS '项目状态';
COMMENT ON COLUMN projects.metadata IS '项目元数据';
COMMENT ON COLUMN projects.sandbox IS '沙盒配置信息';

COMMENT ON COLUMN threads.thread_id IS '线程唯一标识符';
COMMENT ON COLUMN threads.project_id IS '所属项目ID';
COMMENT ON COLUMN threads.account_id IS '所属用户ID';
COMMENT ON COLUMN threads.name IS '线程名称';
COMMENT ON COLUMN threads.status IS '线程状态';
COMMENT ON COLUMN threads.metadata IS '线程元数据'; 