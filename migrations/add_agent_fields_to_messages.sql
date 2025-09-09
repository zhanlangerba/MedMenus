-- 添加 agent_id 和 agent_version_id 字段到 messages 表
-- 迁移日期: 2025-01-16

-- 检查字段是否已存在，如果不存在则添加
DO $$ 
BEGIN
    -- 添加 agent_id 字段
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'messages' 
        AND column_name = 'agent_id'
        AND table_schema = 'public'
    ) THEN
        ALTER TABLE messages ADD COLUMN agent_id UUID NULL;
        RAISE NOTICE 'Added agent_id column to messages table';
    ELSE
        RAISE NOTICE 'agent_id column already exists in messages table';
    END IF;

    -- 添加 agent_version_id 字段
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'messages' 
        AND column_name = 'agent_version_id'
        AND table_schema = 'public'
    ) THEN
        ALTER TABLE messages ADD COLUMN agent_version_id UUID NULL;
        RAISE NOTICE 'Added agent_version_id column to messages table';
    ELSE
        RAISE NOTICE 'agent_version_id column already exists in messages table';
    END IF;
END $$;

-- 创建索引以提升查询性能
CREATE INDEX IF NOT EXISTS idx_messages_agent_id ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent_version_id ON messages(agent_version_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent_thread ON messages(agent_id, thread_id);

-- 添加字段注释
COMMENT ON COLUMN messages.agent_id IS '关联的代理ID';
COMMENT ON COLUMN messages.agent_version_id IS '关联的代理版本ID';

-- 显示表结构验证
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'messages' 
AND table_schema = 'public'
AND column_name IN ('agent_id', 'agent_version_id')
ORDER BY column_name; 