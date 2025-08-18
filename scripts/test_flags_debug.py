#!/usr/bin/env python3
"""
Flags调试测试脚本
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

async def test_flags_system():
    """测试功能标志系统"""
    print("🔍 测试功能标志系统...")
    
    try:
        # 1. 测试Redis连接
        print("\n1️⃣ 测试Redis连接...")
        from services import redis
        
        try:
            redis_client = await redis.get_client()
            await redis_client.ping()
            print("✅ Redis连接成功")
        except Exception as e:
            print(f"❌ Redis连接失败: {e}")
            return False
        
        # 2. 测试功能标志管理器
        print("\n2️⃣ 测试功能标志管理器...")
        from flags.flags import FeatureFlagManager
        
        flag_manager = FeatureFlagManager()
        print("✅ 功能标志管理器创建成功")
        
        # 3. 测试设置标志
        print("\n3️⃣ 测试设置功能标志...")
        success = await flag_manager.set_flag("custom_agents", True, "Custom agents feature")
        print(f"✅ 设置custom_agents标志: {success}")
        
        # 4. 测试检查标志
        print("\n4️⃣ 测试检查功能标志...")
        enabled = await flag_manager.is_enabled("custom_agents")
        print(f"✅ custom_agents标志状态: {enabled}")
        
        # 5. 测试便捷函数
        print("\n5️⃣ 测试便捷函数...")
        from flags.flags import is_enabled, list_flags
        
        enabled_via_func = await is_enabled("custom_agents")
        print(f"✅ 通过便捷函数检查: {enabled_via_func}")
        
        all_flags = await list_flags()
        print(f"✅ 所有标志: {all_flags}")
        
        # 6. 测试API函数
        print("\n6️⃣ 测试API函数...")
        from flags.flags import get_flag_details
        
        details = await get_flag_details("custom_agents")
        print(f"✅ 标志详情: {details}")
        
        print("\n🎉 所有测试通过！")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        print(f"详细错误: {traceback.format_exc()}")
        return False

async def test_redis_only():
    """仅测试Redis连接"""
    print("🔍 仅测试Redis连接...")
    
    try:
        from services import redis
        
        # 检查环境变量
        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = os.getenv("REDIS_PORT", "6379")
        print(f"📡 Redis配置: {redis_host}:{redis_port}")
        
        # 尝试连接
        redis_client = await redis.get_client()
        await redis_client.ping()
        print("✅ Redis连接成功")
        
        # 测试基本操作
        await redis_client.set("test_key", "test_value")
        value = await redis_client.get("test_key")
        print(f"✅ Redis读写测试: {value}")
        
        return True
        
    except Exception as e:
        print(f"❌ Redis测试失败: {e}")
        return False

async def main():
    """主函数"""
    print("🚀 Flags系统调试测试")
    print("=" * 50)
    
    # 选择测试模式
    print("选择测试模式:")
    print("1. 完整测试（推荐）")
    print("2. 仅Redis测试")
    
    choice = input("请输入选择 (1/2): ").strip()
    
    if choice == "2":
        success = await test_redis_only()
    else:
        success = await test_flags_system()
    
    if success:
        print("\n🎉 测试完成！")
        print("\n📝 如果测试通过，请重启API服务器并再次测试前端请求")
    else:
        print("\n❌ 测试失败，请检查配置")

if __name__ == "__main__":
    asyncio.run(main()) 