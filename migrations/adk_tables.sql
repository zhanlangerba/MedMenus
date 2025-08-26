-- ADK (Agent Development Kit) Framework Required Tables
-- 基于 Google ADK 框架的表结构设计

-- 1. App States 表 - 存储应用级别的状态
CREATE TABLE IF NOT EXISTS app_states (
    app_name VARCHAR(128) PRIMARY KEY,
    state JSONB DEFAULT '{}',
    update_time TIMESTAMPTZ DEFAULT NOW()
);

-- 2. User States 表 - 存储用户级别的状态
CREATE TABLE IF NOT EXISTS user_states (
    app_name VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    state JSONB DEFAULT '{}',
    update_time TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id)
);

-- 3. Sessions 表 - 存储会话信息
CREATE TABLE IF NOT EXISTS sessions (
    app_name VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    id VARCHAR(128) NOT NULL,
    state JSONB DEFAULT '{}',
    create_time TIMESTAMPTZ DEFAULT NOW(),
    update_time TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id, id)
);

-- 4. Events 表 - 存储事件信息
CREATE TABLE IF NOT EXISTS events (
    id VARCHAR(128) NOT NULL,
    app_name VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL,
    invocation_id VARCHAR(256),
    author VARCHAR(256),
    branch VARCHAR(256),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    content JSONB,
    actions BYTEA,
    long_running_tool_ids_json TEXT,
    grounding_metadata JSONB,
    partial BOOLEAN,
    turn_complete BOOLEAN,
    error_code VARCHAR(256),
    error_message VARCHAR(1024),
    interrupted BOOLEAN,
    PRIMARY KEY (id, app_name, user_id, session_id),
    
    -- 外键约束：events 必须关联到存在的 session
    CONSTRAINT events_app_name_user_id_session_id_fkey 
        FOREIGN KEY (app_name, user_id, session_id) 
        REFERENCES sessions(app_name, user_id, id) 
        ON DELETE CASCADE
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_app_states_app_name ON app_states(app_name);
CREATE INDEX IF NOT EXISTS idx_user_states_app_name_user_id ON user_states(app_name, user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_app_name_user_id ON sessions(app_name, user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_update_time ON sessions(update_time);
CREATE INDEX IF NOT EXISTS idx_events_app_name_user_id_session_id ON events(app_name, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_author ON events(author);

-- 注释说明
COMMENT ON TABLE app_states IS 'ADK框架应用级别状态存储';
COMMENT ON TABLE user_states IS 'ADK框架用户级别状态存储';
COMMENT ON TABLE sessions IS 'ADK框架会话管理';
COMMENT ON TABLE events IS 'ADK框架事件记录';

COMMENT ON COLUMN sessions.id IS '会话ID，与events表中的session_id对应';
COMMENT ON COLUMN events.session_id IS '关联sessions表中的id字段';
COMMENT ON COLUMN events.actions IS '事件操作数据，使用pickle序列化存储'; 