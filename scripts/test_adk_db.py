import asyncio
import psycopg2
import uuid
from google.adk.sessions import DatabaseSessionService

async def test_adk_database():
    """测试ADK数据库连接"""
    
    # 数据库配置
    DB_CONFIG = {
        'host': 'localhost',
        'port': 5432,
        'database': 'adk',
        'user': 'postgres',
        'password': 'snowball2019'
    }
    
    DATABASE_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    
    print(f"测试数据库连接: {DATABASE_URL}")
    
    try:
        # 1. 测试基本PostgreSQL连接
        print("1. 测试基本PostgreSQL连接...")
        conn = psycopg2.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            database=DB_CONFIG['database'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        print("✅ PostgreSQL连接成功")
        conn.close()
        
        # 2. 测试DatabaseSessionService
        print("2. 测试DatabaseSessionService...")
        session_service = DatabaseSessionService(DATABASE_URL)
        print("✅ DatabaseSessionService创建成功")
        
        # 3. 测试创建会话
        print("3. 测试创建会话...")
        test_session_id = str(uuid.uuid4())  # 使用随机会话ID
        await session_service.create_session(
            app_name="test_app",
            user_id="test_user_123",
            session_id=test_session_id
        )
        print(f"✅ 会话创建成功，ID: {test_session_id}")
        
        # 4. 测试获取会话
        print("4. 测试获取会话...")
        session = await session_service.get_session(app_name="test_app", user_id="test_user_123", session_id=test_session_id)
        print(f"✅ 会话获取成功: {session}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_adk_database()) 