#!/usr/bin/env python3
"""
执行ADK框架数据库迁移脚本
Author: Muyu
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.postgresql import DBConnection
from utils.logger import logger


async def run_adk_migration():
    """执行ADK框架数据库迁移"""
    db = None
    try:
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        client = await db.client
        
        logger.info("开始执行ADK框架数据库迁移...")
        
        # 读取迁移文件
        migration_file = project_root / "migrations" / "20250101000001_adk_framework_tables.sql"
        
        if not migration_file.exists():
            logger.error(f"迁移文件不存在: {migration_file}")
            return
        
        with open(migration_file, 'r', encoding='utf-8') as f:
            migration_sql = f.read()
        
        # 执行迁移
        async with client.pool.acquire() as conn:
            # 分割SQL语句（按分号分割，但忽略字符串内的分号）
            statements = []
            current_statement = ""
            in_string = False
            string_char = None
            
            for char in migration_sql:
                if char in ["'", '"'] and (not in_string or char == string_char):
                    if not in_string:
                        in_string = True
                        string_char = char
                    else:
                        in_string = False
                        string_char = None
                
                current_statement += char
                
                if char == ';' and not in_string:
                    statements.append(current_statement.strip())
                    current_statement = ""
            
            # 执行每个SQL语句
            for i, statement in enumerate(statements):
                if statement.strip() and not statement.strip().startswith('--'):
                    try:
                        await conn.execute(statement)
                        logger.info(f"执行SQL语句 {i+1}/{len(statements)}: {statement[:50]}...")
                    except Exception as e:
                        logger.error(f"执行SQL语句失败: {e}")
                        logger.error(f"SQL语句: {statement}")
                        raise
        
        logger.info("✅ ADK框架数据库迁移完成！")
        
        # 验证表是否创建成功
        async with client.pool.acquire() as conn:
            tables = await conn.fetch("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename IN ('sessions', 'events', 'user_states', 'app_states')
                ORDER BY tablename
            """)
            
            logger.info("验证创建的表:")
            for table in tables:
                logger.info(f"  ✅ {table['tablename']}")
            
            if len(tables) == 4:
                logger.info("🎉 所有ADK框架表创建成功！")
            else:
                logger.warning(f"⚠️  只创建了 {len(tables)}/4 个表")
        
    except Exception as e:
        logger.error(f"ADK框架数据库迁移失败: {e}")
        raise
    finally:
        if db:
            await DBConnection.disconnect()


def main():
    """主函数"""
    print("🚀 开始执行ADK框架数据库迁移...")
    asyncio.run(run_adk_migration())
    print("✅ 迁移完成！")


if __name__ == "__main__":
    main() 