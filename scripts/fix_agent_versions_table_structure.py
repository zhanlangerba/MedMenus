#!/usr/bin/env python3
"""
修复 agent_versions 表结构脚本
使表结构匹配 version_service.py 的期望
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.postgresql import DBConnection

async def fix_agent_versions_table():
    """修复 agent_versions 表结构"""
    
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
        
        # 检查需要修改的字段
        existing_columns = {col['column_name']: col for col in current_columns}
        
        # 需要修改的字段 - 使这些字段变为可空，因为我们使用config字段
        fields_to_modify = [
            'system_prompt',
            'model', 
            'configured_mcps',
            'custom_mcps',
            'agentpress_tools'
        ]
        
        # 需要添加的字段
        fields_to_add = [
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
        
        print(f"\n🔧 开始修复表结构...")
        
        # 1. 修改现有字段为可空（如果它们是NOT NULL的话）
        async with client.pool.acquire() as conn:
            for field_name in fields_to_modify:
                if field_name in existing_columns:
                    col_info = existing_columns[field_name]
                    if col_info['is_nullable'] == 'NO':
                        print(f"🔧 将字段 '{field_name}' 修改为可空...")
                        sql = f"ALTER TABLE agent_versions ALTER COLUMN {field_name} DROP NOT NULL;"
                        await conn.execute(sql)
                        print(f"✅ 成功修改字段 '{field_name}' 为可空")
                    else:
                        print(f"✅ 字段 '{field_name}' 已经是可空的")
                else:
                    print(f"⚠️  字段 '{field_name}' 不存在")
        
        # 2. 添加缺失的字段
        missing_fields = []
        for field in fields_to_add:
            if field['name'] not in existing_columns:
                missing_fields.append(field)
            else:
                print(f"✅ 字段 '{field['name']}' 已存在")
        
        if missing_fields:
            print(f"\n🔧 需要添加 {len(missing_fields)} 个字段:")
            for field in missing_fields:
                print(f"  - {field['name']}")
            
            async with client.pool.acquire() as conn:
                for field in missing_fields:
                    field_definition = f"{field['type']}"
                    if not field['nullable']:
                        field_definition += " NOT NULL"
                    if field['default']:
                        field_definition += f" DEFAULT {field['default']}"
                    
                    sql = f"ALTER TABLE agent_versions ADD COLUMN {field['name']} {field_definition};"
                    
                    print(f"🔧 执行: {sql}")
                    await conn.execute(sql)
                    print(f"✅ 成功添加字段 '{field['name']}'")
        else:
            print("✅ 所有必需字段都已存在")
        
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
            status = ""
            if col['column_name'] in [f['name'] for f in missing_fields]:
                status = "🆕"
            elif col['column_name'] in fields_to_modify:
                status = "🔄"
            else:
                status = "  "
            print(f"{status} {col['column_name']:<25} : {col['data_type']:<20} {nullable}{default}")
        
        print("✅ 表结构修复完成！")
        
        # 输出说明
        print("\n📝 修复说明:")
        print("1. 将原有的配置字段(system_prompt, model等)改为可空")
        print("2. 添加了config字段用于存储完整配置(JSONB格式)")
        print("3. 添加了change_description和previous_version_id字段")
        print("4. 现在version_service.py可以将所有配置存储在config字段中")
        
    except Exception as e:
        print(f"❌ 修复表结构失败: {e}")
        raise
    finally:
        if db:
            await DBConnection.disconnect()
            print("📱 数据库连接已关闭")

async def main():
    """主函数"""
    print("🚀 开始修复 agent_versions 表结构...")
    print("=" * 60)
    
    try:
        await fix_agent_versions_table()
        print("\n" + "=" * 60)
        print("🎉 表结构修复成功完成！")
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code) 