#!/usr/bin/env python3
"""
测试PostgreSQL数据库插入功能
"""

import asyncio
import json
from datetime import datetime, timezone
from services.postgresql import DBConnection
from utils.logger import logger

async def test_db_insert():
    """测试数据库插入功能"""
    print("🔍 开始测试数据库插入功能...")
    
    try:
        # 初始化数据库连接
        db = DBConnection()
        client = await db.client
        print("✅ 数据库连接成功")
        
        # 测试数据1：基本消息插入
        test_data_1 = {
            'thread_id': 'a40bc0a9-4e26-47a8-b09c-29f8d785adf4',  # 使用有效的UUID
            'project_id': '00000000-0000-0000-0000-000000000000',  # 临时使用默认project_id
            'type': 'test',
            'role': 'system',
            'content': json.dumps({'role': 'test', 'content': '这是一个测试消息'}),  # 转换为JSON字符串
            'metadata': json.dumps({'test': True, 'timestamp': datetime.now(timezone.utc).isoformat()})
        }
        
        print(f"\n📝 测试数据1: {json.dumps(test_data_1, ensure_ascii=False, indent=2)}")
        
        try:
            result_1 = await client.table('messages').insert(test_data_1)
            print(f"✅ 插入成功1: {result_1.data}")
            
            if result_1.data and len(result_1.data) > 0:
                message_id = result_1.data[0].get('message_id')
                print(f"📋 返回的message_id: {message_id}")
            else:
                print("❌ 插入成功但没有返回数据")
                
        except Exception as e:
            print(f"❌ 插入失败1: {e}")
            print(f"错误详情: {str(e)}")
        
        # 测试数据2：带代理信息的消息插入
        test_data_2 = {
            'thread_id': 'a40bc0a9-4e26-47a8-b09c-29f8d785adf4',  # 使用有效的UUID
            'project_id': '00000000-0000-0000-0000-000000000000',  # 临时使用默认project_id
            'type': 'assistant',
            'role': 'assistant',
            'content': json.dumps({'role': 'assistant', 'content': '这是AI助手的回复'}),  # 转换为JSON字符串
            'metadata': json.dumps({
                'agent_id': 'test-agent-123',
                'agent_version_id': 'v1.0.0',
                'thread_run_id': 'test-run-123'
            })
        }
        
        print(f"\n📝 测试数据2: {json.dumps(test_data_2, ensure_ascii=False, indent=2)}")
        
        try:
            result_2 = await client.table('messages').insert(test_data_2)
            print(f"✅ 插入成功2: {result_2.data}")
            
            if result_2.data and len(result_2.data) > 0:
                message_id = result_2.data[0].get('message_id')
                print(f"📋 返回的message_id: {message_id}")
            else:
                print("❌ 插入成功但没有返回数据")
                
        except Exception as e:
            print(f"❌ 插入失败2: {e}")
            print(f"错误详情: {str(e)}")
        
        # 测试数据3：模拟实际的消息格式
        test_data_3 = {
            'thread_id': 'a40bc0a9-4e26-47a8-b09c-29f8d785adf4',  # 使用实际的thread_id
            'project_id': '00000000-0000-0000-0000-000000000000',  # 临时使用默认project_id
            'type': 'assistant',
            'role': 'assistant',
            'content': json.dumps({
                'role': 'assistant', 
                'content': '你好！我在的。请问有什么我可以帮助你的吗？',
                'tool_calls': None
            }),  # 转换为JSON字符串
            'metadata': json.dumps({
                'thread_run_id': '5e2d56f1-4c86-4137-a3ca-073f2af4a4be',
                'agent_id': '77ef28c4-3010-40f2-bd5f-40e8a6e5be53'
            })
        }
        
        print(f"\n📝 测试数据3 (模拟实际格式): {json.dumps(test_data_3, ensure_ascii=False, indent=2)}")
        
        try:
            result_3 = await client.table('messages').insert(test_data_3)
            print(f"✅ 插入成功3: {result_3.data}")
            
            if result_3.data and len(result_3.data) > 0:
                message_id = result_3.data[0].get('message_id')
                print(f"📋 返回的message_id: {message_id}")
                
                # 验证返回的数据结构
                returned_data = result_3.data[0]
                print(f"📊 返回的完整数据结构:")
                for key, value in returned_data.items():
                    print(f"  {key}: {value} (类型: {type(value).__name__})")
            else:
                print("❌ 插入成功但没有返回数据")
                
        except Exception as e:
            print(f"❌ 插入失败3: {e}")
            print(f"错误详情: {str(e)}")
        
        # 测试查询功能
        print(f"\n🔍 测试查询功能...")
        try:
            query_result = await client.table('messages').select('*').eq('thread_id', 'a40bc0a9-4e26-47a8-b09c-29f8d785adf4').execute()
            print(f"✅ 查询成功: 找到 {len(query_result.data)} 条记录")
            for i, msg in enumerate(query_result.data):
                print(f"  记录 {i+1}: message_id={msg.get('message_id')}, type={msg.get('type')}")
        except Exception as e:
            print(f"❌ 查询失败: {e}")
            print(f"错误详情: {str(e)}")
        
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        print(f"错误详情: {str(e)}")
    
    finally:
        # 关闭数据库连接
        await DBConnection.disconnect()
        print("\n🔌 数据库连接已关闭")

if __name__ == "__main__":
    asyncio.run(test_db_insert()) 