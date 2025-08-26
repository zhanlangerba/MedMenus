"""
AgentPress PostgreSQL Database Connection Manager
"""

from typing import Optional, List, Dict, Any, Union
import asyncpg # type: ignore
from utils.logger import logger
from utils.config import config
import threading
import os
import json

class DBConnection:
    """线程安全的单例数据库连接管理器，使用PostgreSQL"""
    
    _instance: Optional['DBConnection'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # 双重检查锁定模式，确保线程安全
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
                    cls._instance._pool = None
        return cls._instance

    def __init__(self):
        """初始化方法，不在这里进行实际初始化"""
        pass

    async def initialize(self):
        """初始化数据库连接池"""
        if self._initialized:
            return
                
        try:
            # 从环境变量或配置文件获取数据库URL
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                if hasattr(config, 'DATABASE_URL') and config.DATABASE_URL:
                    database_url = config.DATABASE_URL
                else:
                    # 开发环境的默认连接字符串
                    database_url = "postgresql://postgres:password@localhost:5432/fufanmanus"
            
            if not database_url:
                logger.error("Missing PostgreSQL DATABASE_URL environment variable")
                raise RuntimeError("PostgreSQL DATABASE_URL environment variable must be set.")

            logger.debug("Initializing PostgreSQL connection pool")
            
            # 创建PostgreSQL连接池
            self._pool = await asyncpg.create_pool(
                database_url,
                min_size=1, # 最小连接数
                max_size=10, # 最大连接数
                command_timeout=60 # 命令超时时间
            )
            
            self._initialized = True
            logger.debug(f"PostgreSQL connection pool initialized")
            
        except Exception as e:
            logger.error(f"PostgreSQL connection pool initialization error: {e}")
            raise RuntimeError(f"PostgreSQL connection pool initialization failed: {str(e)}")

    @property
    async def client(self):
        """从连接池获取数据库客户端"""
        if not self._initialized:
            await self.initialize()
        return PostgreSQLClient(self._pool)

    @classmethod
    async def disconnect(cls):
        """断开数据库连接"""
        if cls._instance and cls._instance._pool:
            await cls._instance._pool.close()
            cls._instance._pool = None
            cls._instance._initialized = False
            logger.info("PostgreSQL数据库连接池已关闭")

class PostgreSQLClient:
    """PostgreSQL客户端包装器，提供操作数据库的接口"""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    def table(self, table_name: str):
        """创建表查询构建器"""
        return PostgreSQLTable(self.pool, table_name)
    
    def schema(self, schema_name: str):
        """创建模式查询构建器（用于Supabase schema兼容）"""
        return PostgreSQLSchema(self.pool, schema_name)

class PostgreSQLSchema:
    """模式查询构建器，用于支持schema功能"""
    
    def __init__(self, pool: asyncpg.Pool, schema_name: str):
        self.pool = pool
        self.schema_name = schema_name
    
    def table(self, table_name: str):
        """在指定模式中创建表查询构建器"""
        full_table_name = f"{self.schema_name}.{table_name}"
        return PostgreSQLTable(self.pool, full_table_name)

class PostgreSQLTable:
    """PostgreSQL表查询构建器，提供操作数据库的接口"""
    
    def __init__(self, pool: asyncpg.Pool, table_name: str):
        self.pool = pool
        self.table_name = table_name
        self._select_fields = "*"
        self._where_conditions = []
        self._order_by = []
        self._limit_value = None
        self._offset_value = None
        self._count_flag = False
        self._params = []
        self._single_result = False
        self._maybe_single = False
    
    def select(self, fields: str = "*", count: str = None):
        """选择特定字段"""
        self._select_fields = fields
        if count == "exact":
            self._count_flag = True
        return self
    
    def eq(self, column: str, value: Any):
        """添加相等条件"""
        self._where_conditions.append(f"{column} = ${len(self._params) + 1}")
        self._params.append(value)
        return self
    
    def neq(self, column: str, value: Any):
        """添加不等条件（支持.neq()方法）"""
        if value is None:
            self._where_conditions.append(f"{column} IS NOT NULL")
        else:
            self._where_conditions.append(f"{column} != ${len(self._params) + 1}")
            self._params.append(value)
        return self
    
    def lt(self, column: str, value: Any):
        """添加小于条件"""
        self._where_conditions.append(f"{column} < ${len(self._params) + 1}")
        self._params.append(value)
        return self
    
    def gt(self, column: str, value: Any):
        """添加大于条件"""
        self._where_conditions.append(f"{column} > ${len(self._params) + 1}")
        self._params.append(value)
        return self
    
    def gte(self, column: str, value: Any):
        """添加大于等于条件"""
        self._where_conditions.append(f"{column} >= ${len(self._params) + 1}")
        self._params.append(value)
        return self
    
    def lte(self, column: str, value: Any):
        """添加小于等于条件"""
        self._where_conditions.append(f"{column} <= ${len(self._params) + 1}")
        self._params.append(value)
        return self
    
    def like(self, column: str, pattern: str):
        """添加LIKE条件"""
        self._where_conditions.append(f"{column} LIKE ${len(self._params) + 1}")
        self._params.append(pattern)
        return self
    
    def ilike(self, column: str, pattern: str):
        """添加大小写不敏感的LIKE条件"""
        self._where_conditions.append(f"{column} ILIKE ${len(self._params) + 1}")
        self._params.append(pattern)
        return self
    
    def contains(self, column: str, value: Any):
        """添加包含条件（用于数组或JSON字段）"""
        if isinstance(value, list):
            # 对于数组字段，使用 @> 操作符
            self._where_conditions.append(f"{column} @> ${len(self._params) + 1}")
            self._params.append(json.dumps(value))
        else:
            # 对于文本搜索，使用 LIKE
            self._where_conditions.append(f"{column} LIKE ${len(self._params) + 1}")
            self._params.append(f"%{value}%")
        return self
    
    def in_(self, column: str, values: List[Any]):
        """添加IN条件"""
        if not values:
            # 如果列表为空，添加一个永远为假的条件
            self._where_conditions.append("1 = 0")
            return self
        
        placeholders = []
        for value in values:
            self._params.append(value)
            placeholders.append(f"${len(self._params)}")
        
        self._where_conditions.append(f"{column} IN ({', '.join(placeholders)})")
        return self
    
    def is_(self, column: str, value: Any):
        """添加IS条件（用于NULL检查）"""
        if value is None:
            self._where_conditions.append(f"{column} IS NULL")
        else:
            self._where_conditions.append(f"{column} IS ${len(self._params) + 1}")
            self._params.append(value)
        return self
    
    @property
    def not_(self):
        """返回NOT查询构建器"""
        return PostgreSQLNotBuilder(self)
    
    def filter(self, field_expression: str, operator: str, value: Any):
        """添加过滤条件（支持Supabase的filter语法）"""
        if operator == 'eq':
            return self.eq(field_expression, value)
        elif operator == 'neq':
            return self.neq(field_expression, value)
        elif operator == 'lt':
            return self.lt(field_expression, value)
        elif operator == 'gt':
            return self.gt(field_expression, value)
        # 对于复杂的JSON字段查询，如 'sandbox->>id'
        elif '->>' in field_expression:
            self._where_conditions.append(f"{field_expression} = ${len(self._params) + 1}")
            self._params.append(value)
        else:
            logger.warning(f"不支持的过滤操作符: {operator}")
        return self
    
    def or_(self, condition: str):
        """添加OR条件（简化实现）"""
        # 处理基本的ilike搜索
        if "ilike" in condition:
            # 解析条件如 "name.ilike.%search%,description.ilike.%search%"
            parts = condition.split(",")
            or_conditions = []
            for part in parts:
                if ".ilike." in part:
                    field, _, pattern = part.split(".", 2)
                    or_conditions.append(f"{field} ILIKE ${len(self._params) + 1}")
                    self._params.append(pattern)
            
            if or_conditions:
                self._where_conditions.append(f"({' OR '.join(or_conditions)})")
        return self
    
    def order(self, column: str, desc: bool = False):
        """添加排序子句"""
        direction = "DESC" if desc else "ASC"
        self._order_by.append(f"{column} {direction}")
        return self
    
    def range(self, start: int, end: int):
        """添加分页（LIMIT和OFFSET）"""
        self._limit_value = end - start + 1
        self._offset_value = start
        return self
    
    def limit(self, count: int):
        """添加LIMIT子句"""
        self._limit_value = count
        return self
    
    def single(self):
        """标记查询应返回单个结果"""
        self._single_result = True
        self._limit_value = 1
        return self
    
    def maybe_single(self):
        """标记查询可能返回单个结果或null"""
        self._maybe_single = True
        self._limit_value = 1
        return self
    
    async def execute(self):
        """执行查询"""
        # 构建SELECT查询
        query_parts = [f"SELECT {self._select_fields}"]
        
        # 如果需要计数，构建计数查询
        count_query = None
        if self._count_flag:
            count_query = f"SELECT COUNT(*) FROM {self.table_name}"
            if self._where_conditions:
                count_query += f" WHERE {' AND '.join(self._where_conditions)}"
        
        query_parts.append(f"FROM {self.table_name}")
        
        # 添加WHERE子句
        if self._where_conditions:
            query_parts.append(f"WHERE {' AND '.join(self._where_conditions)}")
        
        # 添加ORDER BY
        if self._order_by:
            query_parts.append(f"ORDER BY {', '.join(self._order_by)}")
        
        # 添加LIMIT和OFFSET
        if self._limit_value:
            query_parts.append(f"LIMIT {self._limit_value}")
        if self._offset_value:
            query_parts.append(f"OFFSET {self._offset_value}")
        
        query = " ".join(query_parts)
        
        try:
            async with self.pool.acquire() as conn:
                # 执行主查询
                rows = await conn.fetch(query, *self._params)
                data = [dict(row) for row in rows]
                
                # 如果需要计数，执行计数查询
                count = None
                if self._count_flag:
                    count_result = await conn.fetchval(count_query, *self._params)
                    count = int(count_result) if count_result else 0
                
                # 处理single和maybe_single情况
                if self._single_result:
                    if not data:
                        raise ValueError("查询未返回任何结果")
                    return QueryResult(data[0], count)
                elif self._maybe_single:
                    if not data:
                        return QueryResult(None, count)
                    return QueryResult(data[0], count)
                
                # 返回Supabase风格的结果
                return QueryResult(data, count)
                
        except Exception as e:
            logger.error(f"查询执行失败: {e}, SQL: {query}, 参数: {self._params}")
            raise RuntimeError(f"数据库查询失败: {str(e)}")
    
    async def insert(self, data: Union[Dict[str, Any], List[Dict[str, Any]]]):
        """插入数据到表中"""
        try:
            # 处理单条记录和多条记录
            if isinstance(data, dict):
                data = [data]
            
            if not data:
                return QueryResult([])
            
            # 获取所有字段名
            columns = list(data[0].keys())
            
            # 构建插入查询
            values_placeholders = []
            all_values = []
            
            for i, record in enumerate(data):
                record_placeholders = []
                for j, column in enumerate(columns):
                    placeholder_index = i * len(columns) + j + 1
                    record_placeholders.append(f"${placeholder_index}")
                    all_values.append(record[column])
                values_placeholders.append(f"({', '.join(record_placeholders)})")
            
            query = f"""
            INSERT INTO {self.table_name} ({', '.join(columns)})
            VALUES {', '.join(values_placeholders)}
            RETURNING *
            """
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *all_values)
                result_data = [dict(row) for row in rows]
                return QueryResult(result_data)
                
        except Exception as e:
            logger.error(f"插入操作失败: {e}")
            raise RuntimeError(f"数据库插入失败: {str(e)}")
    
    async def update(self, data: Dict[str, Any]):
        """更新表中的数据"""
        try:
            # 构建SET子句
            set_clauses = []
            values = []
            for key, value in data.items():
                set_clauses.append(f"{key} = ${len(values) + len(self._params) + 1}")
                values.append(value)
            
            query_parts = [f"UPDATE {self.table_name}"]
            query_parts.append(f"SET {', '.join(set_clauses)}")
            
            if self._where_conditions:
                query_parts.append(f"WHERE {' AND '.join(self._where_conditions)}")
            
            query_parts.append("RETURNING *")
            query = " ".join(query_parts)
            
            # 调试信息
            logger.debug(f"UPDATE query: {query}")
            logger.debug(f"Parameters: {self._params + values}")
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *(self._params + values))
                result_data = [dict(row) for row in rows]
                
                # 处理单个结果的情况
                if self._single_result or self._maybe_single:
                    if not result_data and self._single_result:
                        raise ValueError("更新操作未影响任何记录")
                    return QueryResult(result_data[0] if result_data else None)
                
                return QueryResult(result_data)
                
        except Exception as e:
            logger.error(f"更新操作失败: {e}")
            logger.error(f"Query: {query if 'query' in locals() else 'N/A'}")
            logger.error(f"Parameters: {self._params + values if 'values' in locals() else 'N/A'}")
            raise RuntimeError(f"数据库更新失败: {str(e)}")
    
    async def delete(self):
        """从表中删除数据"""
        try:
            query_parts = [f"DELETE FROM {self.table_name}"]
            
            if self._where_conditions:
                query_parts.append(f"WHERE {' AND '.join(self._where_conditions)}")
            
            query_parts.append("RETURNING *")
            query = " ".join(query_parts)
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, *self._params)
                result_data = [dict(row) for row in rows]
                return QueryResult(result_data)
                
        except Exception as e:
            logger.error(f"删除操作失败: {e}")
            raise RuntimeError(f"数据库删除失败: {str(e)}")

class PostgreSQLNotBuilder:
    """NOT查询构建器，用于支持.not_.is_()等语法"""
    
    def __init__(self, table_builder: PostgreSQLTable):
        self.table_builder = table_builder
    
    def is_(self, column: str, value: Any):
        """添加IS NOT条件"""
        if value is None:
            self.table_builder._where_conditions.append(f"{column} IS NOT NULL")
        else:
            self.table_builder._where_conditions.append(f"{column} IS NOT ${len(self.table_builder._params) + 1}")
            self.table_builder._params.append(value)
        return self.table_builder

class QueryResult:
    """查询结果包装器，匹配Supabase接口"""
    
    def __init__(self, data: Union[List[Dict[str, Any]], Dict[str, Any], None], count: Optional[int] = None):
        self.data = data
        self.count = count
