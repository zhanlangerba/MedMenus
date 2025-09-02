#!/usr/bin/env python3
"""
检查messages表的实际结构
"""

import asyncio
from services.postgresql import DBConnection

async def check_messages_table():
    """检查messages表的实际结构"""
    print("🔍 检查messages表的实际结构...")
    
    try:
        # 初始化数据库连接
        db = DBConnection()
        client = await db.client
        
        # 获取表结构信息
        async with client.pool.acquire() as conn:
            # 查询表结构
            result = await conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'messages' 
                ORDER BY ordinal_position
            """)
            
            print("📋 messages表的字段结构:")
            for row in result:
                nullable_text = 'NULL' if row['is_nullable'] == 'YES' else 'NOT NULL'
                default_text = f"DEFAULT {row['column_default']}" if row['column_default'] else ''
                print(f"  {row['column_name']}: {row['data_type']} {nullable_text} {default_text}")
            
            # 检查是否有数据
            count_result = await conn.fetchval("SELECT COUNT(*) FROM messages")
            print(f"\n📊 messages表现有记录数: {count_result}")
            
            if count_result > 0:
                # 查看前几条记录的结构
                sample_result = await conn.fetch("SELECT * FROM messages LIMIT 3")
                print(f"\n📝 前{len(sample_result)}条记录的字段:")
                for i, row in enumerate(sample_result):
                    print(f"  记录 {i+1}:")
                    for key, value in row.items():
                        print(f"    {key}: {value} (类型: {type(value).__name__})")
        
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        print(f"错误详情: {str(e)}")
    
    finally:
        # 关闭数据库连接
        await DBConnection.disconnect()
        print("\n🔌 数据库连接已关闭")

if __name__ == "__main__":
    asyncio.run(check_messages_table())
