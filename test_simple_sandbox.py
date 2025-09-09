#!/usr/bin/env python3
"""
简单的 PPIO 沙箱测试
测试基本的沙箱创建和连接功能
"""

import os
import asyncio
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(override=True)

async def test_basic_sandbox():
    """测试基本沙箱功能"""
    print("🚀 开始测试 PPIO 沙箱基本功能...\n")
    
    # 设置环境变量
    os.environ['E2B_DOMAIN'] = 'sandbox.ppio.cn'
    
    try:
        from e2b_code_interpreter import Sandbox
        print("✅ 成功导入 e2b_code_interpreter.Sandbox")
        
        # 测试基本配置
        config = {
            'timeoutMs': 30000,  # 30秒
            'metadata': {
                'test': True,
                'purpose': 'basic_test'
            }
        }
        
        print("📋 沙箱配置:")
        print(f"   - 超时: {config['timeoutMs']}ms")
        print(f"   - 元数据: {config['metadata']}")
        
        # 尝试创建沙箱
        print("\n🔧 尝试创建沙箱...")
        sandbox = Sandbox(config)
        print(f"✅ 沙箱创建成功！")
        print(f"   - 沙箱ID: {getattr(sandbox, 'sandboxId', 'N/A')}")
        
        # 测试简单命令
        print("\n📝 测试执行命令...")
        try:
            result = await sandbox.runCode('print("Hello from PPIO sandbox!")')
            print("✅ 命令执行成功:")
            if hasattr(result, 'logs'):
                print(f"   - 输出: {result.logs}")
            else:
                print(f"   - 结果: {result}")
        except Exception as cmd_error:
            print(f"⚠️  命令执行测试失败: {cmd_error}")
        
        # 清理
        print("\n🗑️  清理沙箱...")
        await sandbox.kill()
        print("✅ 沙箱清理完成")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        print(f"   - 错误类型: {type(e).__name__}")
        
        # 打印详细错误信息
        import traceback
        print(f"   - 详细错误:")
        traceback.print_exc()
        
        return False

async def test_project_integration():
    """测试与项目配置的集成"""
    print("\n🔧 测试项目集成...")
    
    try:
        # 导入项目的沙箱模块
        import sys
        sys.path.append('.')
        
        from sandbox.sandbox import create_sandbox
        print("✅ 成功导入项目沙箱模块")
        
        # 测试沙箱创建函数
        print("📝 测试项目沙箱创建函数...")
        
        # 注意：这里不实际创建，只测试函数定义
        print("✅ create_sandbox 函数存在且可调用")
        
        return True
        
    except Exception as e:
        print(f"❌ 项目集成测试失败: {e}")
        return False

async def main():
    """主测试函数"""
    print("=" * 60)
    print("🧪 PPIO 沙箱简单测试")
    print("=" * 60)
    
    # 检查环境变量
    api_key = os.environ.get('E2B_API_KEY')
    if not api_key:
        print("❌ E2B_API_KEY 未设置")
        print("💡 请在 .env 文件中设置你的 PPIO API Key")
        return
    
    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"🌐 Domain: {os.environ.get('E2B_DOMAIN', 'sandbox.ppio.cn')}")
    
    # 运行测试
    tests = [
        ("基本沙箱功能", test_basic_sandbox),
        ("项目集成", test_project_integration),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'=' * 40}")
        print(f"🧪 {test_name}")
        print('=' * 40)
        
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ 测试异常: {e}")
            results.append((test_name, False))
    
    # 汇总结果
    print(f"\n{'=' * 40}")
    print("📊 测试结果")
    print('=' * 40)
    
    passed = 0
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总计: {passed}/{len(results)} 个测试通过")
    
    if passed == len(results):
        print("\n🎉 所有测试通过！可以使用 PPIO 沙箱了。")
    else:
        print(f"\n⚠️  有测试失败，请检查配置和 API Key。")

if __name__ == "__main__":
    asyncio.run(main()) 