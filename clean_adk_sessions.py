# 清理 ADK 数据库中损坏的会话数据
import asyncpg
import asyncio

# 数据库连接配置
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'adk',
    'user': 'postgres',
    'password': 'snowball2019'
}

async def clean_corrupted_sessions():
    """清理损坏的 ADK 会话数据"""
    
    # 生成数据库连接字符串
    DATABASE_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # 查看现有的表
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            AND table_name LIKE '%session%'
            OR table_name LIKE '%adk%'
        """)
        
        print("🔍 找到的 ADK 相关表:")
        for table in tables:
            print(f"  - {table['table_name']}")
        
        # 删除可能损坏的会话数据
        if tables:
            print("\n🗑️ 清理会话数据...")
            
            for table in tables:
                table_name = table['table_name']
                try:
                    result = await conn.execute(f"DELETE FROM {table_name}")
                    print(f"  ✅ 清理表 {table_name}: {result}")
                except Exception as e:
                    print(f"  ❌ 清理表 {table_name} 失败: {e}")
            
            print("\n🎯 所有 ADK 会话数据已清理!")
        else:
            print("\n ℹ️ 没有找到 ADK 会话表，可能还没有创建")
            
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(clean_corrupted_sessions()) 