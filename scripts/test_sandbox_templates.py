#!/usr/bin/env python3
"""
测试 PPIO 沙箱模板和链接获取功能
"""

import asyncio
import os
from utils.config import Configuration, config
from sandbox.sandbox import create_sandbox, get_sandbox_links

async def test_sandbox_templates():
    """测试不同类型的沙箱模板"""
    
    # 检查环境变量
    if not config.E2B_API_KEY:
        print("❌ 请设置 E2B_API_KEY 环境变量")
        return
        
    print(f"✅ E2B_API_KEY: {config.E2B_API_KEY[:10]}...")
    print(f"✅ E2B_DOMAIN: {config.E2B_DOMAIN}")
    print(f"✅ 可用模板: {config.SANDBOX_TEMPLATES}")
    
    # 测试参数
    password = "test123"
    project_id = "test_project_001"
    
    # 🖥️ 测试桌面模板
    print("\n🖥️ 测试桌面模板 (desktop)...")
    try:
        desktop_sandbox = await create_sandbox(password, project_id, 'desktop')
        print(f"✅ 桌面沙箱创建成功")
        
        # 获取桌面沙箱的链接
        desktop_links = await get_sandbox_links(desktop_sandbox, 'desktop')
        print(f"🔗 桌面沙箱链接:")
        for key, url in desktop_links.items():
            print(f"   {key}: {url}")
            
        # 清理
        await desktop_sandbox.kill()
        print("✅ 桌面沙箱已清理")
        
    except Exception as e:
        print(f"❌ 桌面沙箱测试失败: {e}")
    
    print("\n" + "="*50)
    
    # 🌐 测试浏览器模板  
    print("\n🌐 测试浏览器模板 (browser)...")
    try:
        browser_sandbox = await create_sandbox(password, project_id, 'browser')
        print(f"✅ 浏览器沙箱创建成功")
        
        # 获取浏览器沙箱的链接
        browser_links = await get_sandbox_links(browser_sandbox, 'browser')
        print(f"🔗 浏览器沙箱链接:")
        for key, url in browser_links.items():
            print(f"   {key}: {url}")
            
        # 清理
        await browser_sandbox.kill()
        print("✅ 浏览器沙箱已清理")
        
    except Exception as e:
        print(f"❌ 浏览器沙箱测试失败: {e}")
    
    print("\n" + "="*50)
    
    # 💻 测试代码解释器模板
    print("\n💻 测试代码解释器模板 (code)...")
    try:
        code_sandbox = await create_sandbox(password, project_id, 'code')
        print(f"✅ 代码解释器沙箱创建成功")
        
        # 获取代码沙箱的链接
        code_links = await get_sandbox_links(code_sandbox, 'code')
        print(f"🔗 代码解释器沙箱链接:")
        for key, url in code_links.items():
            print(f"   {key}: {url}")
            
        # 清理
        await code_sandbox.kill()
        print("✅ 代码解释器沙箱已清理")
        
    except Exception as e:
        print(f"❌ 代码解释器沙箱测试失败: {e}")

async def test_template_selection():
    """测试模板选择功能"""
    print("\n🔧 测试模板选择功能...")
    
    # 测试不同的模板获取
    templates = ['desktop', 'browser', 'code', 'base', 'invalid']
    
    for template_type in templates:
        template_id = config.get_sandbox_template(template_type)
        print(f"   {template_type:8} -> {template_id}")

if __name__ == "__main__":
    print("🚀 开始测试 PPIO 沙箱模板功能\n")
    
    # 运行模板选择测试
    asyncio.run(test_template_selection())
    
    # 运行沙箱创建测试
    asyncio.run(test_sandbox_templates())
    
    print("\n🎉 测试完成!") 