#!/usr/bin/env python3
"""
调试 PPIO Sandbox 构造函数参数
"""

import inspect
from e2b import Sandbox

def inspect_sandbox_constructor():
    """检查 Sandbox 构造函数的参数"""
    
    print("🔍 检查 Sandbox 类信息:")
    print(f"   类名: {Sandbox.__name__}")
    print(f"   模块: {Sandbox.__module__}")
    print(f"   文档: {Sandbox.__doc__}")
    
    print("\n📋 检查 __init__ 方法签名:")
    try:
        init_signature = inspect.signature(Sandbox.__init__)
        print(f"   签名: {init_signature}")
        
        print("\n🔧 参数详情:")
        for param_name, param in init_signature.parameters.items():
            if param_name == 'self':
                continue
            print(f"   - {param_name}: {param}")
            print(f"     类型: {param.annotation}")
            print(f"     默认值: {param.default}")
            print()
            
    except Exception as e:
        print(f"   ❌ 无法获取签名: {e}")
    
    print("\n🗂️ 检查所有公共方法和属性:")
    methods = [attr for attr in dir(Sandbox) if not attr.startswith('_')]
    for method in methods:
        attr_obj = getattr(Sandbox, method)
        if callable(attr_obj):
            try:
                sig = inspect.signature(attr_obj)
                print(f"   方法 {method}: {sig}")
            except:
                print(f"   方法 {method}: (无法获取签名)")
        else:
            print(f"   属性 {method}: {type(attr_obj)}")

async def test_sandbox_creation_methods():
    """测试不同的 Sandbox 创建方法"""
    
    print("\n🧪 测试不同的创建方法:")
    
    # 方法1: 无参数
    print("\n1️⃣ 测试 Sandbox() 无参数:")
    try:
        sandbox1 = Sandbox()
        info1 = sandbox1.get_info()
        print(f"   ✅ 成功: {info1.template_id} ({info1.name})")
        await sandbox1.kill()
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 方法2: 传递字典配置
    print("\n2️⃣ 测试 Sandbox(dict) 配置:")
    config = {
        'templateId': '4imxoe43snzcxj95hvha',  # desktop 模板
        'timeoutMs': 900000,
        'metadata': {'test': 'desktop_template'}
    }
    try:
        sandbox2 = Sandbox(config)
        info2 = sandbox2.get_info()
        print(f"   ✅ 成功: {info2.template_id} ({info2.name})")
        await sandbox2.kill()
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 方法3: 尝试关键字参数
    print("\n3️⃣ 测试 Sandbox(template=...) 关键字参数:")
    try:
        sandbox3 = Sandbox(template='4imxoe43snzcxj95hvha')
        info3 = sandbox3.get_info()
        print(f"   ✅ 成功: {info3.template_id} ({info3.name})")
        await sandbox3.kill()
    except Exception as e:
        print(f"   ❌ 失败: {e}")
    
    # 方法4: 尝试 templateId 参数
    print("\n4️⃣ 测试 Sandbox(templateId=...) 参数:")
    try:
        sandbox4 = Sandbox(templateId='4imxoe43snzcxj95hvha')
        info4 = sandbox4.get_info()
        print(f"   ✅ 成功: {info4.template_id} ({info4.name})")
        await sandbox4.kill()
    except Exception as e:
        print(f"   ❌ 失败: {e}")

def check_available_templates():
    """检查可用的模板"""
    print("\n📚 检查模板相关方法:")
    
    # 检查是否有列出模板的方法
    if hasattr(Sandbox, 'list_templates'):
        try:
            templates = Sandbox.list_templates()
            print(f"   可用模板: {templates}")
        except Exception as e:
            print(f"   ❌ 列出模板失败: {e}")
    else:
        print("   ❌ 没有 list_templates 方法")
    
    # 检查是否有其他模板相关的类方法
    template_methods = [attr for attr in dir(Sandbox) if 'template' in attr.lower()]
    print(f"   模板相关方法: {template_methods}")

async def main():
    """主函数"""
    print("🚀 开始调试 PPIO Sandbox 构造函数\n")
    
    # 检查构造函数
    inspect_sandbox_constructor()
    
    # 检查模板相关
    check_available_templates()
    
    # 测试创建方法
    await test_sandbox_creation_methods()
    
    print("\n🎉 检查完成!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 