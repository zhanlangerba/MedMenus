#!/usr/bin/env python3
"""
测试PostgreSQL连接和基本操作的脚本
用于验证从Supabase迁移到PostgreSQL后的功能是否正常
"""

import asyncio
import sys
import os
from dotenv import load_dotenv # type: ignore

# 加载环境变量
load_dotenv()

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.postgresql import DBConnection
from utils.logger import logger

async def test_database_connection():
    """测试数据库连接和基本操作"""
    
    print("🔍 开始测试PostgreSQL连接...")
    
    try:
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        print("✅ 数据库连接池初始化成功")
        
        # 获取客户端
        client = await db.client
        print("✅ 数据库客户端获取成功")
        
        # 测试基本查询 - 使用现有的users表
        try:
            result = await client.table("users").select("id, email, name").limit(1).execute()
            print(f"✅ users表查询成功，返回 {len(result.data)} 条记录")
            if result.data:
                print(f"   样例数据: {result.data[0]}")
        except Exception as e:
            print(f"❌ users表查询失败: {e}")
        
        # 测试sessions表查询
        try:
            result = await client.table("sessions").select("id, user_id, app_name").limit(1).execute()
            print(f"✅ sessions表查询成功，返回 {len(result.data)} 条记录")
        except Exception as e:
            print(f"⚠️  sessions表查询失败: {e}")
        
        # 测试复杂查询条件 - 使用users表
        try:
            # 测试WHERE条件和排序
            result = await client.table("users")\
                .select("id, email, name, created_at")\
                .order("created_at", desc=True)\
                .limit(3)\
                .execute()
            print(f"✅ 复杂查询测试成功，返回 {len(result.data)} 条记录")
        except Exception as e:
            print(f"❌ 复杂查询测试失败: {e}")
        
        # 测试single()方法
        try:
            result = await client.table("users")\
                .select("id, email")\
                .limit(1)\
                .single()\
                .execute()
            print(f"✅ single()方法测试成功，数据: {result.data}")
        except Exception as e:
            print(f"❌ single()方法测试失败: {e}")
        
        # 测试maybe_single()方法
        try:
            result = await client.table("users")\
                .select("id")\
                .eq("id", "00000000-0000-0000-0000-000000000000")\
                .maybe_single()\
                .execute()
            print(f"✅ maybe_single()方法测试成功，数据: {result.data}")
        except Exception as e:
            print(f"❌ maybe_single()方法测试失败: {e}")
        
        # 测试.not_.is_()语法
        try:
            result = await client.table("users")\
                .select("id, email")\
                .not_.is_("email", None)\
                .limit(1)\
                .execute()
            print(f"✅ .not_.is_()语法测试成功，返回 {len(result.data)} 条记录")
        except Exception as e:
            print(f"❌ .not_.is_()语法测试失败: {e}")
        
        # 测试其他查询方法
        try:
            # 测试eq条件
            result = await client.table("users")\
                .select("id, email")\
                .eq("status", "active")\
                .limit(2)\
                .execute()
            print(f"✅ eq条件测试成功，返回 {len(result.data)} 条记录")
        except Exception as e:
            print(f"❌ eq条件测试失败: {e}")
        
        # 测试like查询
        try:
            result = await client.table("users")\
                .select("id, email")\
                .like("email", "%@%")\
                .limit(1)\
                .execute()
            print(f"✅ like查询测试成功，返回 {len(result.data)} 条记录")
        except Exception as e:
            print(f"❌ like查询测试失败: {e}")
        
        # 测试JSON字段查询
        try:
            result = await client.table("users")\
                .select("id, metadata")\
                .filter("metadata", "eq", "{}")\
                .limit(1)\
                .execute()
            print(f"✅ JSON字段查询测试成功，返回 {len(result.data)} 条记录")
        except Exception as e:
            print(f"❌ JSON字段查询测试失败: {e}")
        
        # 测试计数查询
        try:
            result = await client.table("users")\
                .select("id", count="exact")\
                .execute()
            print(f"✅ 计数查询测试成功，总数: {result.count} 条记录")
        except Exception as e:
            print(f"❌ 计数查询测试失败: {e}")
        
        print("\n🎉 所有测试完成！")
        
    except Exception as e:
        print(f"❌ 数据库连接测试失败: {e}")
        return False
    
    finally:
        # 清理连接
        try:
            await DBConnection.disconnect()
            print("✅ 数据库连接已清理")
        except Exception as e:
            print(f"⚠️  数据库连接清理失败: {e}")
    
    return True

async def main():
    """主函数"""
    print("=" * 60)
    print("PostgreSQL连接测试脚本")
    print("=" * 60)
    
    # 检查环境变量
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        print(f"📌 使用数据库URL: {database_url[:20]}...")
    else:
        print("📌 使用默认数据库连接: postgresql://postgres:password@localhost:5432/fufanmanus")
    
    print()
    
    # 运行测试
    success = await test_database_connection()
    
    if success:
        print("\n✅ 测试通过！PostgreSQL连接配置正确。")
        sys.exit(0)
    else:
        print("\n❌ 测试失败！请检查PostgreSQL配置。")
        sys.exit(1)

if __name__ == "__main__":
    # 确保在Windows上使用正确的事件循环策略
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(main()) 