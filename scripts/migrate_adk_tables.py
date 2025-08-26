#!/usr/bin/env python3
"""
执行ADK框架表迁移的脚本
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


async def migrate_adk_tables():
    """执行ADK表迁移"""
    db = None
    try:
        logger.info("开始执行ADK框架表迁移...")
        
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        client = await db.client
        
        # 读取迁移文件
        migration_file = project_root / "migrations" / "adk_tables.sql"
        if not migration_file.exists():
            logger.error(f"迁移文件不存在: {migration_file}")
            return False
        
        with open(migration_file, 'r', encoding='utf-8') as f:
            migration_sql = f.read()
        
        logger.info(f"读取迁移文件: {migration_file}")
        
        # 执行迁移
        async with client.pool.acquire() as conn:
            await conn.execute(migration_sql)
        
        logger.info("✅ ADK框架表迁移完成！")
        
        # 验证表是否创建成功
        async with client.pool.acquire() as conn:
            tables = await conn.fetch(
                """
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename IN ('app_states', 'user_states', 'sessions', 'events')
                ORDER BY tablename
                """
            )
        
        if len(tables) == 4:
            logger.info("✅ 所有ADK表创建成功:")
            for table in tables:
                logger.info(f"  - {table['tablename']}")
        else:
            logger.warning(f"⚠️ 只创建了 {len(tables)} 个表，期望4个表")
            for table in tables:
                logger.info(f"  - {table['tablename']}")
        
        return True
        
    except Exception as e:
        logger.error(f"ADK表迁移失败: {e}")
        return False
    finally:
        if db:
            await DBConnection.disconnect()


def main():
    """主函数"""
    success = asyncio.run(migrate_adk_tables())
    if success:
        print("\n🎉 ADK框架表迁移成功完成！")
        print("现在可以正常使用ADK框架的会话和事件功能了。")
    else:
        print("\n❌ ADK框架表迁移失败！")
        sys.exit(1)


if __name__ == "__main__":
    main() 