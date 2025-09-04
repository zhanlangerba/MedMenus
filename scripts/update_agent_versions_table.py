#!/usr/bin/env python3
"""
更新 agent_versions 表结构脚本
添加 version_service.py 需要的缺失字段
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.postgresql import DBConnection

async def update_agent_versions_table():
    """更新 agent_versions 表结构"""
    
    db = None
    try:
        print("✅ 初始化数据库连接...")
        
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        client = await db.client
        
        print("✅ 数据库连接成功")
        
        # 检查当前表结构
        print("🔍 检查当前 agent_versions 表结构...")
        
        async with client.pool.acquire() as conn:
            current_columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'agent_versions' 
                AND table_schema = 'public'
                ORDER BY ordinal_position;
            """)
        
        print(f"\n📋 当前 agent_versions 表有 {len(current_columns)} 个字段:")
        for col in current_columns:
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
            print(f"  - {col['column_name']:<25} : {col['data_type']:<20} {nullable}{default}")
        
        # 需要添加的字段
        missing_fields = [
            {
                'name': 'change_description',
                'type': 'TEXT',
                'nullable': True,
                'default': None
            },
            {
                'name': 'previous_version_id',
                'type': 'VARCHAR(128)',
                'nullable': True,
                'default': None
            },
            {
                'name': 'config',
                'type': 'JSONB',
                'nullable': True,
                'default': "'{}'::jsonb"
            }
        ]
        
        # 检查哪些字段缺失
        existing_columns = [col['column_name'] for col in current_columns]
        fields_to_add = []
        
        for field in missing_fields:
            if field['name'] not in existing_columns:
                fields_to_add.append(field)
            else:
                print(f"✅ 字段 '{field['name']}' 已存在")
        
        if not fields_to_add:
            print("✅ 所有必需字段都已存在，无需更新")
            return
        
        print(f"\n🔧 需要添加 {len(fields_to_add)} 个字段:")
        for field in fields_to_add:
            print(f"  - {field['name']}")
        
        # 添加缺失的字段
        async with client.pool.acquire() as conn:
            for field in fields_to_add:
                field_definition = f"{field['type']}"
                if not field['nullable']:
                    field_definition += " NOT NULL"
                if field['default']:
                    field_definition += f" DEFAULT {field['default']}"
                
                sql = f"ALTER TABLE agent_versions ADD COLUMN {field['name']} {field_definition};"
                
                print(f"🔧 执行: {sql}")
                await conn.execute(sql)
                print(f"✅ 成功添加字段 '{field['name']}'")
        
        # 验证更新后的表结构
        print("\n🔍 验证更新后的表结构...")
        async with client.pool.acquire() as conn:
            updated_columns = await conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'agent_versions' 
                AND table_schema = 'public'
                ORDER BY ordinal_position;
            """)
        
        print(f"\n📋 更新后 agent_versions 表有 {len(updated_columns)} 个字段:")
        for col in updated_columns:
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            default = f" DEFAULT {col['column_default']}" if col['column_default'] else ""
            status = "🆕" if col['column_name'] in [f['name'] for f in fields_to_add] else "  "
            print(f"{status} {col['column_name']:<25} : {col['data_type']:<20} {nullable}{default}")
        
        print("✅ 表结构更新完成！")
        
    except Exception as e:
        print(f"❌ 更新表结构失败: {e}")
        raise
    finally:
        if db:
            await DBConnection.disconnect()
            print("📱 数据库连接已关闭")

async def main():
    """主函数"""
    print("🚀 开始更新 agent_versions 表结构...")
    print("=" * 60)
    
    try:
        await update_agent_versions_table()
        print("\n" + "=" * 60)
        print("🎉 表结构更新成功完成！")
        
    except Exception as e:
        print(f"\n❌ 更新失败: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code) 