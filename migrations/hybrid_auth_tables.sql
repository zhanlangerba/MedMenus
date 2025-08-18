-- =====================================================
-- 兼容 Google ADK 的混合认证表结构
-- 既支持本地认证，也兼容 Google 标准
-- =====================================================

BEGIN;

-- 1. 用户基础表（兼容Google ADK）
CREATE TABLE IF NOT EXISTS users (
    -- 本地字段
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255), -- 可为空，支持第三方登录
    name VARCHAR(255) NOT NULL,
    
    -- Google ADK 兼容字段
    google_id VARCHAR(255) UNIQUE, -- Google用户ID
    provider VARCHAR(50) DEFAULT 'local', -- 'local', 'google', 'github'等
    external_id VARCHAR(255), -- 第三方平台ID
    avatar_url VARCHAR(500), -- 头像URL
    locale VARCHAR(10) DEFAULT 'en', -- 语言设置
    
    -- 状态管理
    status VARCHAR(20) DEFAULT 'active', -- 'active', 'inactive', 'suspended'
    email_verified BOOLEAN DEFAULT false,
    email_verified_at TIMESTAMPTZ,
    
    -- 元数据
    metadata JSONB DEFAULT '{}', -- 扩展字段，存储额外信息
    preferences JSONB DEFAULT '{}', -- 用户偏好设置
    
    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    
    -- 约束
    CONSTRAINT valid_provider CHECK (provider IN ('local', 'google', 'github', 'microsoft')),
    CONSTRAINT valid_status CHECK (status IN ('active', 'inactive', 'suspended'))
);

-- 2. 会话表（兼容Google ADK会话管理）
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- 会话信息
    session_token VARCHAR(255) NOT NULL UNIQUE,
    access_token VARCHAR(500), -- JWT access token
    refresh_token VARCHAR(500), -- 刷新token
    
    -- 设备和位置信息
    device_id VARCHAR(255),
    device_type VARCHAR(50), -- 'web', 'mobile', 'desktop'
    user_agent TEXT,
    ip_address INET,
    location JSONB, -- 地理位置信息
    
    -- 时间管理
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 状态
    is_active BOOLEAN DEFAULT true,
    
    CONSTRAINT valid_device_type CHECK (device_type IN ('web', 'mobile', 'desktop', 'unknown'))
);

-- 3. 刷新Token表（向后兼容）
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    session_id UUID REFERENCES user_sessions(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    
    -- 标记是否已撤销
    is_revoked BOOLEAN DEFAULT false
);

-- 4. 用户活动日志（ADK风格）
CREATE TABLE IF NOT EXISTS user_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES user_sessions(id) ON DELETE SET NULL,
    
    -- 活动信息
    activity_type VARCHAR(50) NOT NULL, -- 'login', 'logout', 'register', 'password_change'等
    activity_data JSONB DEFAULT '{}', -- 活动相关数据
    
    -- 上下文信息
    ip_address INET,
    user_agent TEXT,
    resource VARCHAR(255), -- 访问的资源
    
    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT valid_activity_type CHECK (activity_type IN (
        'login', 'logout', 'register', 'password_change', 
        'email_verify', 'profile_update', 'session_expire'
    ))
);

-- 5. OAuth提供商配置（支持多provider）
CREATE TABLE IF NOT EXISTS oauth_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- 提供商信息
    provider VARCHAR(50) NOT NULL,
    provider_user_id VARCHAR(255) NOT NULL,
    provider_email VARCHAR(255),
    
    -- OAuth数据
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMPTZ,
    scope VARCHAR(500),
    
    -- 提供商用户信息
    provider_data JSONB DEFAULT '{}',
    
    -- 时间戳
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 唯一约束
    UNIQUE(provider, provider_user_id)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
CREATE INDEX IF NOT EXISTS idx_users_provider ON users(provider);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON user_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_device_id ON user_sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON user_sessions(is_active);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_revoked ON refresh_tokens(is_revoked);

CREATE INDEX IF NOT EXISTS idx_activities_user_id ON user_activities(user_id);
CREATE INDEX IF NOT EXISTS idx_activities_type ON user_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_activities_created_at ON user_activities(created_at);

CREATE INDEX IF NOT EXISTS idx_oauth_provider_user ON oauth_providers(provider, provider_user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_user_id ON oauth_providers(user_id);

-- 创建触发器函数用于更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为相关表创建 updated_at 触发器
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER update_oauth_providers_updated_at
    BEFORE UPDATE ON oauth_providers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- 创建清理过期会话的函数
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- 删除过期的会话
    DELETE FROM user_sessions 
    WHERE expires_at < NOW() OR 
          (last_activity_at < NOW() - INTERVAL '30 days');
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- 删除过期的刷新token
    DELETE FROM refresh_tokens 
    WHERE expires_at < NOW() OR is_revoked = true;
    
    RETURN deleted_count;
END;
$$ language 'plpgsql';

COMMIT;

-- 使用说明
/*
这个混合表结构的优势：

1. **向后兼容**：
   - 保持原有的 users, refresh_tokens 表结构
   - 现有代码无需大幅修改

2. **Google ADK 兼容**：
   - 支持多种认证提供商
   - 扩展的用户信息字段
   - 完整的会话管理
   - 活动日志记录

3. **扩展性**：
   - JSONB字段支持灵活的元数据
   - 支持多设备会话管理
   - 支持地理位置等高级功能

4. **安全性**：
   - Token撤销机制
   - 会话过期管理
   - 活动审计日志

使用方式：
- 本地认证：使用 email + password_hash
- Google认证：使用 google_id + provider='google'
- 其他OAuth：使用 oauth_providers 表
*/ 