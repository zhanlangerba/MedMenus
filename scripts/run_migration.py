import asyncio
from services.postgresql import DBConnection

async def run_migration():
    db = DBConnection()
    await db.initialize()
    client = await db.client
    
    try:
        async with client.pool.acquire() as conn:
            print("开始执行迁移...")
            
            # 1. 添加新的 UUID 字段
            print("1. 添加 agent_run_id 字段...")
            await conn.execute('ALTER TABLE agent_runs ADD COLUMN agent_run_id UUID DEFAULT gen_random_uuid()')
            print("   ✅ agent_run_id 字段添加成功")
            
            # 2. 为现有记录生成 UUID
            print("2. 为现有记录生成 UUID...")
            await conn.execute('UPDATE agent_runs SET agent_run_id = gen_random_uuid() WHERE agent_run_id IS NULL')
            print("   ✅ 现有记录 UUID 生成完成")
            
            # 3. 设置字段为非空
            print("3. 设置 agent_run_id 为非空...")
            await conn.execute('ALTER TABLE agent_runs ALTER COLUMN agent_run_id SET NOT NULL')
            print("   ✅ agent_run_id 设置为非空")
            
            # 4. 创建唯一索引
            print("4. 创建唯一索引...")
            await conn.execute('CREATE UNIQUE INDEX idx_agent_runs_agent_run_id ON agent_runs(agent_run_id)')
            print("   ✅ 唯一索引创建成功")
            
            # 5. 验证结果
            print("5. 验证迁移结果...")
            result = await conn.fetch("SELECT id, agent_run_id FROM agent_runs LIMIT 3")
            print("   验证结果:")
            for row in result:
                print(f"   - id: {row['id']}, agent_run_id: {row['agent_run_id']}")
            
            print("\n🎉 迁移完成！")
            
    except Exception as e:
        print(f"❌ 迁移失败: {e}")
        raise
    finally:
        await db.disconnect()

if __name__ == "__main__":
    asyncio.run(run_migration()) 