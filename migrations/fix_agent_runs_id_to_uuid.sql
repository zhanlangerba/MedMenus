-- 修复 agent_runs 表的 id 字段为 UUID 类型
-- 这个迁移将现有的 SERIAL id 字段改为 UUID 类型

-- 1. 添加新的 UUID 字段
ALTER TABLE agent_runs ADD COLUMN agent_run_id UUID DEFAULT gen_random_uuid();

-- 2. 为现有记录生成 UUID
UPDATE agent_runs SET agent_run_id = gen_random_uuid() WHERE agent_run_id IS NULL;

-- 3. 设置字段为非空
ALTER TABLE agent_runs ALTER COLUMN agent_run_id SET NOT NULL;

-- 4. 创建唯一索引
CREATE UNIQUE INDEX idx_agent_runs_agent_run_id ON agent_runs(agent_run_id);

-- 5. 添加注释
COMMENT ON COLUMN agent_runs.agent_run_id IS 'Agent运行唯一标识符 (UUID)';

-- 注意：保留原有的 id 字段以避免破坏现有引用，但新代码应该使用 agent_run_id 