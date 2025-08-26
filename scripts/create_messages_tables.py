#!/usr/bin/env python3
"""
创建消息相关表的脚本
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

async def create_messages_tables():
    """创建消息相关的表"""
    
    print("🔍 开始创建消息相关表...")
    
    try:
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        print("✅ 数据库连接池初始化成功")
        
        # 获取客户端
        client = await db.client
        print("✅ 数据库客户端获取成功")
        
        # 读取SQL文件
        sql_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations', 'create_messages_table.sql')
        
        if not os.path.exists(sql_file_path):
            print(f"❌ SQL文件不存在: {sql_file_path}")
            return False
        
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        print(f"📄 读取SQL文件: {sql_file_path}")
        
        # 执行SQL
        print("🚀 执行SQL迁移...")
        async with client.pool.acquire() as conn:
            await conn.execute(sql_content)
        
        print("✅ 消息相关表创建成功!")
        
        # 验证表是否创建成功
        async with client.pool.acquire() as conn:
            # 检查messages表
            messages_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'messages'
                );
            """)
            
            # 检查agent_runs表
            agent_runs_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'agent_runs'
                );
            """)
            
            if messages_exists and agent_runs_exists:
                print("✅ 表验证成功!")
                print("📋 创建的表:")
                print("  - messages (消息表)")
                print("  - agent_runs (代理运行表)")
                return True
            else:
                print("❌ 表验证失败!")
                return False
        
    except Exception as e:
        print(f"❌ 创建消息相关表失败: {e}")
        logger.error(f"创建消息相关表失败: {e}")
        return False
    finally:
        # 清理数据库连接
        try:
            await DBConnection.disconnect()
            print("🔧 数据库连接已清理")
        except Exception as e:
            print(f"⚠️ 清理数据库连接时出错: {e}")

def main():
    """主函数"""
    # Windows兼容性
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    success = asyncio.run(create_messages_tables())
    if success:
        print("🎉 消息相关表创建完成!")
        sys.exit(0)
    else:
        print("💥 消息相关表创建失败!")
        sys.exit(1)

if __name__ == "__main__":
    main() 