
from google.genai import types # type: ignore
from google.adk.agents.run_config import RunConfig, StreamingMode # type: ignore
from google.adk.models.lite_llm import LiteLlm # type: ignore
from google.adk.agents import LlmAgent # type: ignore
from google.adk.sessions import DatabaseSessionService # type: ignore
from google.adk import Runner # type: ignore
import asyncio


# 数据库连接配置
DB_CONFIG = {
    'host': 'localhost',  # 这里替换成实际的 PostgreSQL 服务器地址
    'port': 5432,   # 这里替换成实际的 PostgreSQL 服务器端口
    'database': 'adk',  # 这里替换成实际的 PostgreSQL 数据库名称
    'user': 'postgres',  # 这里替换成实际的 PostgreSQL 用户名
    'password': 'snowball2019'  # 这里替换成实际的 PostgreSQL 密码
}

# 生成数据库连接字符串
DATABASE_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"

streaming_mode = StreamingMode.SSE
run_config = RunConfig(streaming_mode=streaming_mode)

# 创建LiteLlm模型
model = LiteLlm(
    model="openai/gpt-4o",
    api_key="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"
)

# 创建 Agent 对象
agent = LlmAgent(
    name="fufanmanus",
    model=model,
    instruction="你是我的AI助手，请根据用户的问题给出回答。"
)

query = "你好，请你介绍一下你自己。"

# 将用户的问题转换为 ADK 格式
content = types.Content(role='user', parts=[types.Part(text=query)])

async def run_async():
    # 统一使用数据库中已存在的 session_id
    USER_ID = "51511682-b40c-4371-ab76-fbe726c7c00a"
    SESSION_ID = "e6a1640f-0743-4580-930f-cf08cae198e7"  # 使用数据库中实际存在的
    
    # 创建 SessionService 对象
    session_service = DatabaseSessionService(DATABASE_URL)
    
    try:
        # 在异步函数中创建会话
        await session_service.get_session(
            app_name="fufanmanus", 
            user_id=USER_ID, 
            session_id=SESSION_ID
        )
        print("✅ 成功加载数据库会话")
        
    except Exception as e:
        print(f"❌ 数据库会话数据损坏: {e}")
        print("🔄 尝试删除并重新创建会话...")
        
        try:
            # 先尝试删除损坏的会话数据
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            try:
                # 删除损坏的事件数据
                await conn.execute(
                    "DELETE FROM events WHERE session_id = $1", SESSION_ID
                )
                print("🗑️ 清理了损坏的事件数据")
                
                # 删除损坏的会话数据
                await conn.execute(
                    "DELETE FROM sessions WHERE id = $1", SESSION_ID
                )
                print("🗑️ 清理了损坏的会话数据")
                
            finally:
                await conn.close()
            
            # 重新创建干净的会话
            await session_service.create_session(
                app_name="fufanmanus", 
                user_id=USER_ID, 
                session_id=SESSION_ID
            )
            print("✅ 重新创建数据库会话成功")
            
        except Exception as e2:
            print(f"❌ 数据库完全无法使用: {e2}")
            print("🔄 回退到内存会话服务...")
            
            # 使用内存会话服务作为备选方案
            from google.adk.sessions import InMemorySessionService # type: ignore
            session_service = InMemorySessionService()
            await session_service.create_session(
                app_name="fufanmanus", 
                user_id=USER_ID, 
                session_id=SESSION_ID
            )
            print("✅ 内存会话服务创建成功")
    
    # 创建 Runner
    runner = Runner(
        agent=agent,
        app_name="fufanmanus",
        session_service=session_service
    )
    
    # 异步运行 - 现在使用统一的 SESSION_ID
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,  # 🎯 修复：使用同一个 SESSION_ID
        new_message=content,
    ):
        # 解析 ADK 事件，只显示关键信息
        if hasattr(event, 'content') and event.content:
            if hasattr(event.content, 'parts') and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        print(f"🤖 AI回复: {part.text}")
            
            if hasattr(event, 'usage_metadata') and event.usage_metadata:
                print(f"📊 Token使用: 输入={event.usage_metadata.prompt_token_count}, 输出={event.usage_metadata.candidates_token_count}, 总计={event.usage_metadata.total_token_count}")
        else:
            # 如果不是内容事件，显示事件类型
            print(f"📨 事件类型: {type(event).__name__}")
            if hasattr(event, 'error_message') and event.error_message:
                print(f"❌ 错误: {event.error_message}")
        
        print("---")

# 运行异步函数
if __name__ == "__main__":
    asyncio.run(run_async())
