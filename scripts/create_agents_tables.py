#!/usr/bin/env python3
"""
创建Agent管理相关表的脚本
"""

import asyncio
import sys
import os
from dotenv import load_dotenv # type: ignore

# 加载环境变量
load_dotenv()

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.postgresql import DBConnection
from utils.logger import logger

async def create_agents_tables():
    """创建Agent管理相关的表"""
    
    print("🔍 开始创建Agent管理表...")
    
    try:
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        print("✅ 数据库连接池初始化成功")
        
        # 获取客户端
        client = await db.client
        print("✅ 数据库客户端获取成功")
        
        # 读取SQL文件
        sql_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations', 'create_agents_table.sql')
        
        if not os.path.exists(sql_file_path):
            print(f"❌ SQL文件不存在: {sql_file_path}")
            return False
        
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        print(f"📄 读取SQL文件: {sql_file_path}")
        
        # 执行SQL
        async with client.pool.acquire() as conn:
            await conn.execute(sql_content)
        
        print("✅ Agent管理表创建成功")
        
        # 验证表是否创建成功
        print("🔍 验证表创建结果...")
        
        # 检查agents表
        result = await client.schema('public').table('agents').select('agent_id').limit(1).execute()
        print(f"✅ agents表验证成功，当前记录数: {len(result.data)}")
        
        # 检查agent_versions表
        result = await client.schema('public').table('agent_versions').select('version_id').limit(1).execute()
        print(f"✅ agent_versions表验证成功，当前记录数: {len(result.data)}")
        
        # 检查agent_workflows表
        result = await client.schema('public').table('agent_workflows').select('workflow_id').limit(1).execute()
        print(f"✅ agent_workflows表验证成功，当前记录数: {len(result.data)}")
        
        print("\n🎉 Agent管理表创建完成！")
        
        return True
        
    except Exception as e:
        print(f"❌ 创建Agent管理表失败: {e}")
        return False
    
    finally:
        # 清理连接
        try:
            await DBConnection.disconnect()
            print("✅ 数据库连接已清理")
        except Exception as e:
            print(f"⚠️  数据库连接清理失败: {e}")

async def main():
    """主函数"""
    print("=" * 60)
    print("Agent管理表创建脚本")
    print("=" * 60)
    
    # 检查环境变量
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        print(f"📌 使用数据库URL: {database_url[:20]}...")
    else:
        print("📌 使用默认数据库连接: postgresql://postgres:password@localhost:5432/fufanmanus")
    
    print()
    
    # 运行创建
    success = await create_agents_tables()
    
    if success:
        print("\n✅ 脚本执行成功！Agent管理表已创建。")
        sys.exit(0)
    else:
        print("\n❌ 脚本执行失败！请检查错误信息。")
        sys.exit(1)

if __name__ == "__main__":
    # 确保在Windows上使用正确的事件循环策略
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(main()) 