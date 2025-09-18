#!/usr/bin/env python3
"""
测试Dramatiq的脚本
"""

import asyncio
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

async def test_dramatiq():
    """测试Dramatiq功能"""
    print("🔍 测试Dramatiq功能...")
    
    try:
        # 1. 测试导入
        print("\n1️⃣ 测试导入...")
        from run_agent_background import run_agent_background, check_health
        print("✅ 导入成功")
        
        # 2. 测试发送简单任务
        print("\n2️⃣ 测试发送简单任务...")
        try:
            message = check_health.send("test_key")
            print(f"✅ 简单任务发送成功，消息ID: {message.message_id}")
        except Exception as e:
            print(f"❌ 简单任务发送失败: {e}")
            return False
        
        # 3. 测试发送复杂任务
        print("\n3️⃣ 测试发送复杂任务...")
        try:
            message = run_agent_background.send(
                agent_run_id="test_run_id",
                thread_id="test_thread_id",
                instance_id="test_instance",
                project_id="test_project",
                model_name="test_model",
                enable_thinking=False,
                reasoning_effort="low",
                stream=False,
                enable_context_manager=True,
                agent_config=None,
                is_agent_builder=False,
                target_agent_id=None,
                request_id="test_request"
            )
            print(f"✅ 复杂任务发送成功，消息ID: {message.message_id}")
        except Exception as e:
            print(f"❌ 复杂任务发送失败: {e}")
            return False
        
        print("\n🎉 Dramatiq测试通过！")
        print("💡 现在你需要启动worker来处理任务:")
        print("   dramatiq run_agent_background")
        
        return True
        
    except Exception as e:
        print(f"❌ Dramatiq测试失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    asyncio.run(test_dramatiq()) 