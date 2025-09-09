#!/usr/bin/env python3
"""
添加 agent_id 和 agent_version_id 字段到 messages 表的迁移脚本
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

async def add_agent_fields_to_messages():
    """添加 agent_id 和 agent_version_id 字段到 messages 表"""
    
    print("🔍 开始添加 agent 字段到 messages 表...")
    
    try:
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        print("✅ 数据库连接池初始化成功")
        
        # 获取客户端
        client = await db.client
        print("✅ 数据库客户端获取成功")
        
        # 读取SQL文件
        sql_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations', 'add_agent_fields_to_messages.sql')
        
        if not os.path.exists(sql_file_path):
            print(f"❌ SQL文件不存在: {sql_file_path}")
            return False
        
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        print(f"📄 读取SQL文件: {sql_file_path}")
        
        # 执行SQL迁移
        print("🚀 执行字段添加迁移...")
        async with client.pool.acquire() as conn:
            # 分割SQL语句 - 处理DO块和普通语句
            sql_statements = []
            current_statement = []
            in_do_block = False
            
            for line in sql_content.split('\n'):
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith('--'):
                    continue
                
                current_statement.append(line)
                
                # 检查是否进入DO块
                if line.startswith('DO $$'):
                    in_do_block = True
                # 检查是否退出DO块
                elif line == 'END $$;' and in_do_block:
                    in_do_block = False
                    sql_statements.append(' '.join(current_statement))
                    current_statement = []
                # 普通语句以分号结尾
                elif line.endswith(';') and not in_do_block:
                    sql_statements.append(' '.join(current_statement))
                    current_statement = []
            
            # 如果还有未完成的语句
            if current_statement:
                sql_statements.append(' '.join(current_statement))
            
            # 逐个执行SQL语句
            verification_result = None
            for i, statement in enumerate(sql_statements):
                if not statement.strip():
                    continue
                    
                print(f"  执行语句 {i+1}/{len(sql_statements)}")
                try:
                    # 对于SELECT语句，使用fetch获取结果
                    if statement.strip().upper().startswith('SELECT'):
                        verification_result = await conn.fetch(statement)
                    else:
                        # 对于其他语句，使用execute
                        await conn.execute(statement)
                except Exception as e:
                    print(f"    执行语句失败: {e}")
                    continue
            
            # 打印验证结果
            if verification_result:
                print("📋 字段验证结果:")
                for row in verification_result:
                    print(f"  - {row['column_name']}: {row['data_type']} (nullable: {row['is_nullable']})")
        
        print("✅ agent 字段添加成功!")
        
        # 验证字段是否添加成功
        async with client.pool.acquire() as conn:
            # 检查 agent_id 字段
            agent_id_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = 'messages'
                    AND column_name = 'agent_id'
                );
            """)
            
            # 检查 agent_version_id 字段
            agent_version_id_exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_schema = 'public' 
                    AND table_name = 'messages'
                    AND column_name = 'agent_version_id'
                );
            """)
            
            # 检查索引是否创建成功
            agent_indexes = await conn.fetch("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'messages' 
                AND indexname LIKE '%agent%'
                ORDER BY indexname;
            """)
            
            if agent_id_exists and agent_version_id_exists:
                print("✅ 字段验证成功!")
                print("📋 添加的字段:")
                print("  - agent_id (UUID, nullable)")
                print("  - agent_version_id (UUID, nullable)")
                
                if agent_indexes:
                    print("📋 创建的索引:")
                    for idx in agent_indexes:
                        print(f"  - {idx['indexname']}")
                
                return True
            else:
                print("❌ 字段验证失败!")
                print(f"  agent_id exists: {agent_id_exists}")
                print(f"  agent_version_id exists: {agent_version_id_exists}")
                return False
        
    except Exception as e:
        print(f"❌ 添加 agent 字段失败: {e}")
        logger.error(f"添加 agent 字段失败: {e}")
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
    
    success = asyncio.run(add_agent_fields_to_messages())
    if success:
        print("🎉 agent 字段添加完成!")
        sys.exit(0)
    else:
        print("💥 agent 字段添加失败!")
        sys.exit(1)

if __name__ == "__main__":
    main() 