#!/usr/bin/env python3
"""
更新.env文件的Redis密码配置
"""

import os
import re

def update_env_file():
    """更新.env文件的Redis密码"""
    env_file = '.env'
    
    if not os.path.exists(env_file):
        print(f"❌ .env文件不存在: {env_file}")
        return False
    
    # 读取当前.env文件
    with open(env_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已经有REDIS_PASSWORD
    if 'REDIS_PASSWORD=' in content:
        # 更新现有的REDIS_PASSWORD
        new_content = re.sub(
            r'REDIS_PASSWORD=.*',
            'REDIS_PASSWORD=snowball2019',
            content
        )
        print("✅ 更新了现有的REDIS_PASSWORD配置")
    else:
        # 添加新的REDIS_PASSWORD
        new_content = content + '\nREDIS_PASSWORD=snowball2019'
        print("✅ 添加了新的REDIS_PASSWORD配置")
    
    # 写回文件
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"✅ 已更新 {env_file} 文件")
    print("📝 新的Redis配置:")
    print("   REDIS_HOST=localhost")
    print("   REDIS_PORT=6379")
    print("   REDIS_PASSWORD=snowball2019")
    
    return True

if __name__ == "__main__":
    print("🔧 更新.env文件Redis密码配置")
    print("=" * 40)
    
    if update_env_file():
        print("\n🎉 配置更新完成！")
        print("\n📝 现在可以重新运行测试:")
        print("   python test_flags_debug.py")
    else:
        print("\n❌ 配置更新失败") 