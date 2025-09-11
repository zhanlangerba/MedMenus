import asyncio
import json
import uuid
import sys
import os

# 修复路径：添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))  # agent/tools/
project_root = os.path.dirname(os.path.dirname(current_dir))  # 项目根目录
sys.path.insert(0, project_root)

from agentpress.adk_thread_manager import ADKThreadManager
from utils.logger import logger



async def test_adk_thread_manager_db():
    """测试 ADKThreadManager 数据库操作"""
    # 1. 实例化 ADKThreadManager
    thread_manager = ADKThreadManager(
        trace=None,           # 可选的追踪客户端
        is_agent_builder=False,
        target_agent_id=None,
        agent_config=None
    )

    client = await thread_manager.db.client
    print(f"   ✅ 数据库客户端获取成功: {type(client)}")

    section_title = '研究与准备'
    task_contents = [
        '从TripAdvisor收集关于巴黎旅行的基本信息。',
        '搜索巴黎的热门景点、餐厅和活动。',
        '查找巴黎的交通选项及建议。',
        '收集巴黎的天气预报信息。',
        '确定潜在的备用计划（如遇到不可预见的情况）。',
    ]
    # sections = [section_title]
    # tasks = [task_contents]
    # content = {
    #     'sections': [section.model_dump() for section in sections],
    #     'tasks': [task.model_dump() for task in tasks]
    # }

    # Create new
    # res = await client.table('messages').insert({
    #     'thread_id': "0e3db501-a801-4233-b482-b651730e742a",
    #     'type': "task_list",
    #     'content': {
    #         'sections': [section_title],
    #         'tasks': [task_contents]
    #     },
    #     'is_llm_message': False,
    #     'metadata': {}
    # })
    # print(f"res: {res}")

    # result = await client.table('messages').select('*')\
    #     .eq('thread_id', "0e3db501-a801-4233-b482-b651730e742a")\
    #     .eq('type', "task_list")\
    #     .order('created_at', desc=True).limit(1).execute()

    # print(f"result: {result.data}")

    # ans = await client.table('agents').select('agent_id').eq('agent_id', "74aad582-4290-4fbf-b57b-372f0669e404").eq('user_id', "5b6cb69c-cb47-4178-82b5-d579e83e8ec7").execute()
    # print(f"ans: {ans}")


    result = await client.table('agent_workflows').select('*').eq('agent_id', "74aad582-4290-4fbf-b57b-372f0669e404").order('created_at', desc=True).execute()
    print(f"result: {result.data}")

if __name__ == "__main__":
    print("🚀 开始 ADK 数据库完整测试...")
    
    async def main():
        # 基础数据库测试
        db_success = await test_adk_thread_manager_db()

    asyncio.run(main())