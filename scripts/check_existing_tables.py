#!/usr/bin/env python3
"""
检查Google ADK已创建的表结构
"""

import asyncio
import asyncpg
from pathlib import Path

async def check_existing_tables():
    """检查现有表结构"""
    print("🔍 检查Google ADK已创建的表结构...")
    
    # 读取数据库连接
    database_url = None
    if Path('.env').exists():
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('DATABASE_URL='):
                    database_url = line.split('=', 1)[1].strip()
                    break
    
    if not database_url:
        print("❌ 未找到DATABASE_URL配置")
        return
    
    try:
        conn = await asyncpg.connect(database_url)
        
        # 1. 查看所有表
        tables = await conn.fetch("""
            SELECT table_name, table_type
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        print(f"\n📋 现有表列表 ({len(tables)}个):")
        for table in tables:
            print(f"  - {table['table_name']} ({table['table_type']})")
        
        # 2. 重点检查Google ADK相关表的结构
        adk_tables = ['users', 'sessions', 'user_states', 'app_states', 'events']
        
        for table_name in adk_tables:
            if any(t['table_name'] == table_name for t in tables):
                print(f"\n📊 表 '{table_name}' 的字段结构:")
                
                columns = await conn.fetch("""
                    SELECT 
                        column_name, 
                        data_type, 
                        is_nullable,
                        column_default,
                        character_maximum_length
                    FROM information_schema.columns 
                    WHERE table_name = $1 
                    AND table_schema = 'public'
                    ORDER BY ordinal_position
                """, table_name)
                
                for col in columns:
                    nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
                    default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
                    length = f"({col['character_maximum_length']})" if col['character_maximum_length'] else ""
                    print(f"    {col['column_name']}: {col['data_type']}{length} {nullable}{default}")
                
                # 检查索引
                indexes = await conn.fetch("""
                    SELECT 
                        indexname,
                        indexdef
                    FROM pg_indexes 
                    WHERE tablename = $1 
                    AND schemaname = 'public'
                """, table_name)
                
                if indexes:
                    print(f"  📑 索引:")
                    for idx in indexes:
                        print(f"    - {idx['indexname']}")
        
        # 3. 检查是否有认证相关的现有数据
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        print(f"\n👥 users表现有数据: {user_count} 条记录")
        
        if user_count > 0:
            sample_user = await conn.fetchrow("SELECT * FROM users LIMIT 1")
            print(f"📝 用户表样例数据字段: {list(sample_user.keys())}")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ 检查表结构失败: {e}")

if __name__ == "__main__":
    asyncio.run(check_existing_tables()) 