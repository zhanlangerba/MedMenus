-- =====================================================
-- LOCAL AUTHENTICATION SYSTEM MIGRATION
-- =====================================================
-- 本地认证系统，替代 Supabase Auth

BEGIN;

-- 创建用户状态枚举
DO $$ BEGIN
    CREATE TYPE user_status AS ENUM ('active', 'inactive', 'pending', 'suspended');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 创建本地用户表
CREATE TABLE IF NOT EXISTS auth_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    status user_status DEFAULT 'active',
    email_verified BOOLEAN DEFAULT FALSE,
    email_verification_token VARCHAR(255),
    password_reset_token VARCHAR(255),
    password_reset_expires_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT auth_users_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT auth_users_name_not_empty CHECK (LENGTH(TRIM(name)) > 0)
);

-- 创建刷新token表
CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    is_revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    
    -- 索引
    UNIQUE(token_hash)
);

-- 创建用户会话表（可选，用于跟踪活跃会话）
CREATE TABLE IF NOT EXISTS auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    access_token_jti VARCHAR(255) NOT NULL, -- JWT ID
    refresh_token_id UUID REFERENCES auth_refresh_tokens(id) ON DELETE CASCADE,
    ip_address INET,
    user_agent TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- 索引
    UNIQUE(access_token_jti)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(email);
CREATE INDEX IF NOT EXISTS idx_auth_users_status ON auth_users(status);
CREATE INDEX IF NOT EXISTS idx_auth_users_created_at ON auth_users(created_at);

CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_user_id ON auth_refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_token_hash ON auth_refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_expires_at ON auth_refresh_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_refresh_tokens_is_revoked ON auth_refresh_tokens(is_revoked);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_access_token_jti ON auth_sessions(access_token_jti);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_is_active ON auth_sessions(is_active);

-- 启用RLS（如果需要）
ALTER TABLE auth_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;

-- RLS策略：用户只能访问自己的数据
CREATE POLICY "Users can view own profile" ON auth_users
    FOR SELECT USING (id = current_setting('app.current_user_id')::uuid);

CREATE POLICY "Users can update own profile" ON auth_users
    FOR UPDATE USING (id = current_setting('app.current_user_id')::uuid);

CREATE POLICY "Users can manage own refresh tokens" ON auth_refresh_tokens
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid);

CREATE POLICY "Users can manage own sessions" ON auth_sessions
    FOR ALL USING (user_id = current_setting('app.current_user_id')::uuid);

-- 创建触发器函数用于更新 updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为用户表创建 updated_at 触发器
CREATE TRIGGER update_auth_users_updated_at
    BEFORE UPDATE ON auth_users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 授权
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_users TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_refresh_tokens TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions TO service_role;

-- 为了兼容现有系统，我们需要确保 basejump.accounts 表可以引用新的用户表
-- 如果需要的话，我们可以创建一个视图或者修改外键约束

COMMIT; 