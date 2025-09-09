-- 添加 is_llm_message 字段到 messages 表
-- 迁移日期: 2025-01-16

-- 检查字段是否已存在，如果不存在则添加
DO $$ 
BEGIN
    -- 添加 is_llm_message 字段
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'messages' 
        AND column_name = 'is_llm_message'
        AND table_schema = 'public'
    ) THEN
        ALTER TABLE messages ADD COLUMN is_llm_message BOOLEAN DEFAULT FALSE NOT NULL;
        RAISE NOTICE 'Added is_llm_message column to messages table';
    ELSE
        RAISE NOTICE 'is_llm_message column already exists in messages table';
    END IF;
END $$;

-- 添加字段注释
COMMENT ON COLUMN messages.is_llm_message IS '标识消息是否来自LLM (AI助手)';

-- 创建索引以提升查询性能
CREATE INDEX IF NOT EXISTS idx_messages_is_llm_message ON messages(is_llm_message);

-- 显示表结构验证
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'messages' 
AND table_schema = 'public'
AND column_name = 'is_llm_message'; 