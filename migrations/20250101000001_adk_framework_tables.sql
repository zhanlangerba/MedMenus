-- =====================================================
-- Google ADK Framework Database Tables
-- 创建ADK框架所需的sessions、events、user_states、app_states表
-- =====================================================

BEGIN;

-- 1. 应用状态表 (app_states)
CREATE TABLE IF NOT EXISTS app_states (
    app_name VARCHAR(128) PRIMARY KEY,
    state JSONB DEFAULT '{}',
    update_time TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 用户状态表 (user_states)
CREATE TABLE IF NOT EXISTS user_states (
    app_name VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    state JSONB DEFAULT '{}',
    update_time TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id)
);

-- 3. 会话表 (sessions) - ADK框架核心表
CREATE TABLE IF NOT EXISTS sessions (
    app_name VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    id VARCHAR(128) NOT NULL,
    state JSONB DEFAULT '{}',
    create_time TIMESTAMPTZ DEFAULT NOW(),
    update_time TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (app_name, user_id, id)
);

-- 4. 事件表 (events) - ADK框架核心表
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
    actions BYTEA, -- PickleType in SQLAlchemy
    long_running_tool_ids_json TEXT,
    grounding_metadata JSONB,
    partial BOOLEAN,
    turn_complete BOOLEAN,
    error_code VARCHAR(256),
    error_message VARCHAR(1024),
    interrupted BOOLEAN,
    PRIMARY KEY (id, app_name, user_id, session_id),
    FOREIGN KEY (app_name, user_id, session_id) 
        REFERENCES sessions(app_name, user_id, id) 
        ON DELETE CASCADE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_app_states_app_name ON app_states(app_name);
CREATE INDEX IF NOT EXISTS idx_app_states_update_time ON app_states(update_time);

CREATE INDEX IF NOT EXISTS idx_user_states_app_name ON user_states(app_name);
CREATE INDEX IF NOT EXISTS idx_user_states_user_id ON user_states(user_id);
CREATE INDEX IF NOT EXISTS idx_user_states_app_user ON user_states(app_name, user_id);
CREATE INDEX IF NOT EXISTS idx_user_states_update_time ON user_states(update_time);

CREATE INDEX IF NOT EXISTS idx_sessions_app_name ON sessions(app_name);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_app_user ON sessions(app_name, user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_id ON sessions(id);
CREATE INDEX IF NOT EXISTS idx_sessions_create_time ON sessions(create_time);
CREATE INDEX IF NOT EXISTS idx_sessions_update_time ON sessions(update_time);

CREATE INDEX IF NOT EXISTS idx_events_app_name ON events(app_name);
CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_app_user_session ON events(app_name, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_author ON events(author);

-- 创建触发器函数用于更新 update_time
CREATE OR REPLACE FUNCTION update_adk_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为相关表创建 update_time 触发器
CREATE TRIGGER update_app_states_updated_at
    BEFORE UPDATE ON app_states
    FOR EACH ROW
    EXECUTE FUNCTION update_adk_updated_at();

CREATE TRIGGER update_user_states_updated_at
    BEFORE UPDATE ON user_states
    FOR EACH ROW
    EXECUTE FUNCTION update_adk_updated_at();

CREATE TRIGGER update_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_adk_updated_at();

-- 创建清理过期会话的函数
CREATE OR REPLACE FUNCTION cleanup_expired_adk_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- 删除30天前的会话（可以根据需要调整）
    DELETE FROM sessions 
    WHERE update_time < NOW() - INTERVAL '30 days';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ language 'plpgsql';

-- 创建定期清理的调度（可选）
-- SELECT cron.schedule('cleanup-adk-sessions', '0 2 * * *', 'SELECT cleanup_expired_adk_sessions();');

COMMIT; 