-- 创建 messages 表
CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL,
    project_id UUID NOT NULL,
    type VARCHAR(50) NOT NULL, -- 'user', 'assistant', 'tool', 'system', 'browser_state', 'image_context'
    role VARCHAR(50) NOT NULL, -- 'user', 'assistant', 'system'
    content JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_project_id ON messages(project_id);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(type);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_thread_type ON messages(thread_id, type);

-- 添加注释
COMMENT ON TABLE messages IS '存储对话消息的表';
COMMENT ON COLUMN messages.message_id IS '消息唯一标识符';
COMMENT ON COLUMN messages.thread_id IS '所属线程ID';
COMMENT ON COLUMN messages.project_id IS '所属项目ID';
COMMENT ON COLUMN messages.type IS '消息类型：user, assistant, tool, system, browser_state, image_context';
COMMENT ON COLUMN messages.role IS '消息角色：user, assistant, system';
COMMENT ON COLUMN messages.content IS '消息内容（JSON格式）';
COMMENT ON COLUMN messages.metadata IS '消息元数据（JSON格式）';
COMMENT ON COLUMN messages.created_at IS '创建时间';
COMMENT ON COLUMN messages.updated_at IS '更新时间'; 