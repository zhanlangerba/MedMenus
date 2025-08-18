#!/usr/bin/env python3
"""
JWT包修复脚本
"""

import subprocess
import sys

def fix_jwt_package():
    """修复JWT包问题"""
    print("🔧 修复JWT包问题...")
    
    try:
        # 检查当前JWT包
        import jwt
        if hasattr(jwt, 'encode'):
            print("✅ JWT包正常")
            return True
        else:
            print("❌ 安装了错误的jwt包，需要修复")
    except ImportError:
        print("❌ 未安装JWT包")
    
    try:
        print("🔸 卸载错误的jwt包...")
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "jwt", "-y"], 
                      check=False, capture_output=True)
        
        print("🔸 安装正确的PyJWT包...")
        result = subprocess.run([sys.executable, "-m", "pip", "install", "PyJWT"], 
                              check=True, capture_output=True, text=True)
        
        print("✅ PyJWT安装成功")
        
        # 验证安装
        import importlib
        importlib.invalidate_caches()
        
        import jwt
        if hasattr(jwt, 'encode'):
            print("✅ JWT包修复成功")
            return True
        else:
            print("❌ JWT包仍有问题")
            return False
            
    except Exception as e:
        print(f"❌ 修复失败: {e}")
        return False

if __name__ == "__main__":
    if fix_jwt_package():
        print("\n🎉 JWT包修复完成！")
        print("现在可以重新运行: python setup_database.py")
    else:
        print("\n❌ JWT包修复失败")
        print("请手动执行:")
        print("pip uninstall jwt -y")
        print("pip install PyJWT") 