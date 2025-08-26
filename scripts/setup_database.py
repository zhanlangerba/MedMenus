#!/usr/bin/env python3
"""
数据库设置脚本
帮助快速配置PostgreSQL数据库连接和表结构
"""

import asyncio
import os
import sys
from pathlib import Path

async def test_database_connection():
    """测试数据库连接"""
    print("🔍 测试数据库连接...")
    
    try:
        import asyncpg
        print("✅ asyncpg 已安装")
    except ImportError:
        print("❌ asyncpg 未安装，请运行: pip install asyncpg")
        return False
    
    # 获取数据库连接信息
    print("\n📝 请输入数据库连接信息：")
    host = input("主机地址 (默认: localhost): ").strip() or "localhost"
    port = input("端口 (默认: 5432): ").strip() or "5432"
    database = input("数据库名 (默认: adk): ").strip() or "adk"
    username = input("用户名 (默认: postgres): ").strip() or "postgres"
    password = input("密码: ").strip()
    
    if not password:
        print("❌ 密码不能为空")
        return False
    
    # 构建连接字符串
    database_url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
    print(f"\n📡 连接字符串: postgresql://{username}:***@{host}:{port}/{database}")
    
    try:
        # 测试连接
        conn = await asyncpg.connect(database_url)
        print("✅ 数据库连接成功")
        
        # 测试查询
        result = await conn.fetchval("SELECT version()")
        print(f"📊 PostgreSQL版本: {result.split(',')[0]}")
        
        await conn.close()
        
        # 保存配置到.env文件
        env_content = f"""# 数据库配置
DATABASE_URL={database_url}

# JWT配置
JWT_SECRET_KEY=your-secret-key-change-in-production-{os.urandom(16).hex()}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=30
"""
        
        with open('.env', 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print("✅ 配置已保存到 .env 文件")
        return True
        
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        print("\n💡 常见解决方案:")
        print("1. 检查PostgreSQL服务是否启动")
        print("2. 检查用户名和密码是否正确")
        print("3. 检查数据库是否存在")
        print("4. 检查防火墙设置")
        return False

async def create_database_tables():
    """创建数据库表"""
    print("\n🔧 创建数据库表...")
    
    # 检查迁移文件是否存在
    migration_files = [
        # "../migrations/hybrid_auth_tables.sql",
        # "../migrations/init_auth_tables.sql"
    ]
    
    selected_migration = None
    for migration_file in migration_files:
        if Path(migration_file).exists():
            selected_migration = migration_file
            break
    
    if not selected_migration:
        print("❌ 未找到迁移文件")
        return False
    
    # 读取.env文件获取DATABASE_URL
    if not Path('.env').exists():
        print("❌ 请先运行数据库连接测试")
        return False
    
    database_url = None
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('DATABASE_URL='):
                database_url = line.split('=', 1)[1].strip()
                break
    
    if not database_url:
        print("❌ 未找到DATABASE_URL配置")
        return False
    
    try:
        import asyncpg
        
        # 连接数据库
        conn = await asyncpg.connect(database_url)
        
        # 读取并执行迁移文件
        with open(selected_migration, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        print(f"📄 执行迁移文件: {selected_migration}")
        await conn.execute(sql_content)
        
        print("✅ 数据库表创建成功")
        
        # 检查创建的表
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        print(f"📋 已创建的表: {[table['table_name'] for table in tables]}")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 创建表失败: {e}")
        return False

async def test_auth_system():
    """测试认证系统"""
    print("\n🧪 测试认证系统...")
    
    try:
        # 导入认证服务
        sys.path.append('.')
        from auth.service import AuthService
        from auth.models import RegisterRequest, LoginRequest
        
        auth_service = AuthService()
        
        # 测试注册
        print("🔸 测试用户注册...")
        test_email = "test@example.com"
        test_password = "test123456"
        test_name = "Test User"
        
        register_request = RegisterRequest(
            email=test_email,
            password=test_password,
            name=test_name
        )
        
        try:
            response = await auth_service.register(register_request)
            print(f"✅ 注册成功: {response.user.email}")
            
            # 测试登录
            print("🔸 测试用户登录...")
            login_request = LoginRequest(
                email=test_email,
                password=test_password
            )
            
            login_response = await auth_service.login(login_request)
            print(f"✅ 登录成功: {login_response.user.email}")
            
            return True
            
        except Exception as e:
            if "Email already registered" in str(e):
                print("ℹ️ 测试用户已存在，尝试登录...")
                login_request = LoginRequest(
                    email=test_email,
                    password=test_password
                )
                login_response = await auth_service.login(login_request)
                print(f"✅ 登录成功: {login_response.user.email}")
                return True
            else:
                raise
                
    except Exception as e:
        print(f"❌ 认证系统测试失败: {e}")
        return False

async def main():
    """主函数"""
    print("🚀 数据库设置向导")
    print("=" * 50)
    
    # 步骤1: 测试数据库连接
    if not await test_database_connection():
        print("\n❌ 数据库连接失败，请检查配置后重试")
        return
    
    # 步骤2: 创建数据库表
    if not await create_database_tables():
        print("\n❌ 数据库表创建失败")
        return
    
    # 步骤3: 测试认证系统
    if not await test_auth_system():
        print("\n❌ 认证系统测试失败")
        return
    
    print("\n🎉 数据库设置完成！")
    print("\n📝 接下来你可以:")
    print("1. 启动FastAPI服务器: python -m uvicorn api:app --reload")
    print("2. 测试API端点: POST /api/auth/register")
    print("3. 查看.env文件中的配置")

if __name__ == "__main__":
    asyncio.run(main()) 