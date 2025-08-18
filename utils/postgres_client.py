"""
本地PostgreSQL客户端
用于用户认证系统的数据库连接
"""

import os
import asyncpg
from typing import Optional, Dict, Any, List
from utils.logger import logger
from utils.config import config

class PostgresClient:
    """本地PostgreSQL客户端"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.connection_string = self._get_connection_string()
    
    def _get_connection_string(self) -> str:
        """获取数据库连接字符串"""
        # 从环境变量或配置文件获取
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            return database_url
        
        # 如果没有DATABASE_URL，从config获取
        if hasattr(config, 'DATABASE_URL') and config.DATABASE_URL:
            return config.DATABASE_URL
        
        # 默认连接字符串
        return "postgresql://postgres:password@localhost:5432/suna_auth"
    
    async def initialize(self):
        """初始化数据库连接池"""
        if self.pool is None:
            try:
                self.pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=1,
                    max_size=10
                )
                logger.info("PostgreSQL connection pool initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL pool: {e}")
                raise
    
    async def close(self):
        """关闭数据库连接池"""
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("PostgreSQL connection pool closed")
    
    async def execute(self, query: str, *args) -> str:
        """执行SQL语句"""
        if not self.pool:
            await self.initialize()
        
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args) -> List[Dict[str, Any]]:
        """查询数据"""
        if not self.pool:
            await self.initialize()
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]
    
    async def fetchrow(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """查询单行数据"""
        if not self.pool:
            await self.initialize()
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None
    
    async def fetchval(self, query: str, *args) -> Any:
        """查询单个值"""
        if not self.pool:
            await self.initialize()
        
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

# 全局PostgreSQL客户端实例
postgres_client = PostgresClient() 