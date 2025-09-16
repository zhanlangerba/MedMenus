#!/usr/bin/env python3
"""
PostgreSQL Database Initialization Script
Function:
1. Check if the database exists, if not, create it automatically
2. Check and create all tables defined in fufanmanus.sql
3. Verify the completeness of the database and tables
"""

import asyncio
import sys
import os
from dotenv import load_dotenv # type: ignore

# 加载环境变量
load_dotenv(override=True)

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.postgresql import DBConnection
from utils.logger import logger
import asyncpg # type: ignore
from urllib.parse import urlparse

def parse_database_url(database_url: str) -> dict:
    """parse the database URL, extract the connection information"""
    try:
        parsed = urlparse(database_url)
        return {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 5432,
            'user': parsed.username or 'postgres',
            'password': parsed.password or 'password',
            'database': parsed.path.lstrip('/') if parsed.path else 'fufanmanus'
        }
    except Exception as e:
        logger.error(f"Failed to parse the database URL: {e}")
        return {
            'host': 'localhost',
            'port': 5432,
            'user': 'postgres', 
            'password': 'password',
            'database': 'fufanmanus'
        }

async def check_database_exists(db_config: dict) -> bool:
    """check if the database exists"""
    try:
        # 连接到postgres默认数据库来检查目标数据库是否存在
        conn = await asyncpg.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database='postgres'  # 连接到默认的postgres数据库
        )
        
        # 查询数据库是否存在
        result = await conn.fetchrow(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            db_config['database']
        )
        
        await conn.close()
        exists = result is not None
        
        if exists:
            logger.info(f"Database '{db_config['database']}' exists")
        else:
            logger.info(f"Database '{db_config['database']}' does not exist")
            
        return exists
        
    except Exception as e:
        logger.error(f"Error checking if database exists: {e}")
        return False

async def create_database(db_config: dict) -> bool:
    """create the database"""
    try:
        logger.info(f"Creating database '{db_config['database']}'...")
        
        # 连接到postgres默认数据库来创建目标数据库
        conn = await asyncpg.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database='postgres'  # 连接到默认的postgres数据库
        )
        
        # 创建数据库（注意：不能在事务中执行CREATE DATABASE）
        await conn.execute(f'CREATE DATABASE "{db_config["database"]}"')
        await conn.close()
        
        logger.info(f"Database '{db_config['database']}' created successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to create database: {e}")
        return False

async def ensure_database_exists() -> bool:
    """ensure the database exists, if not, create it"""
    
    # 获取数据库配置
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        db_config = parse_database_url(database_url)
        logger.info(f"Using the configured database: {db_config['database']} @ {db_config['host']}:{db_config['port']}")
    else:
        db_config = {
            'host': 'localhost',
            'port': 5432,
            'user': 'postgres',
            'password': 'password',
            'database': 'fufanmanus'
        }
        logger.info(f"Using the default database configuration: {db_config['database']} @ {db_config['host']}:{db_config['port']}")
    
    try:
        # 检查数据库是否存在
        exists = await check_database_exists(db_config)
        
        if exists:
            return True
        
        # 数据库不存在，尝试创建
        logger.info(f"Database '{db_config['database']}' does not exist, creating...")
        success = await create_database(db_config)
        
        if success:
            logger.info(f"Database '{db_config['database']}' created successfully")
            return True
        else:
            logger.error(f"Failed to create database '{db_config['database']}'")
            return False
            
    except Exception as e:
        logger.error(f"Error ensuring database exists: {e}")
        return False

async def check_table_exists(client, table_name: str) -> bool:
    """check if the table exists"""
    try:
        # 使用PostgreSQL的系统表查询表是否存在
        async with client.pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1)",
                table_name
            )
            return result['exists'] if result else False
    except Exception as e:
        logger.error(f"Error checking if table {table_name} exists: {e}")
        return False

async def get_missing_tables(client) -> list:
    """get the list of missing tables"""
    # fufanmanus.sql中定义的所有表
    expected_tables = [
        'agent_runs', 'agent_versions', 'agent_workflows', 'agents',
        'app_states', 'events', 'messages', 'oauth_providers', 
        'projects', 'refresh_tokens', 'sessions', 'threads',
        'user_activities', 'user_sessions', 'user_states', 'users'
    ]
    
    missing_tables = []
    for table in expected_tables:
        exists = await check_table_exists(client, table)
        if not exists:
            missing_tables.append(table)
            logger.info(f"Table {table} does not exist")
        else:
            logger.debug(f"Table {table} exists")
    
    return missing_tables

async def execute_sql_file(client, sql_file_path: str) -> bool:
    """execute the SQL file"""
    try:
        if not os.path.exists(sql_file_path):
            logger.error(f"SQL file does not exist: {sql_file_path}")
            return False
        
        with open(sql_file_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        logger.info(f"Reading SQL file: {sql_file_path}")
        
        # 更智能的SQL语句分割，处理注释和复杂语句
        sql_statements = []
        current_statement = ""
        lines = sql_content.split('\n')
        
        for line in lines:
            line = line.strip()
            
            # 跳过空行和注释行
            if not line or line.startswith('--') or line.startswith('/*'):
                continue
            
            # 处理多行注释的结束
            if '*/' in line:
                line = line.split('*/', 1)[-1].strip()
                if not line:
                    continue
            
            current_statement += " " + line
            
            # 如果遇到分号，表示语句结束
            if line.endswith(';'):
                statement = current_statement.strip()
                if statement and not statement.startswith('--'):
                    sql_statements.append(statement)
                current_statement = ""
        
        # 添加最后一个语句（如果没有以分号结尾）
        if current_statement.strip():
            sql_statements.append(current_statement.strip())
        
        logger.info(f"Preparing to execute {len(sql_statements)} SQL statements")
        
        async with client.pool.acquire() as conn:
            for i, statement in enumerate(sql_statements):
                if statement and not statement.startswith('--'):  # 跳过注释和空语句
                    try:
                        await conn.execute(statement)
                        logger.debug(f"Executing SQL statement {i+1}/{len(sql_statements)}")
                    except Exception as e:
                        # 某些语句可能因为表已存在等原因失败，记录但继续
                        error_msg = str(e)
                        if any(keyword in error_msg.lower() for keyword in ['already exists', 'duplicate', 'exist']):
                            logger.debug(f"Skipping SQL statement {i+1} (object already exists): {error_msg[:100]}...")
                        else:
                            logger.warning(f"Failed to execute SQL statement {i+1}: {error_msg[:100]}...")
        
        logger.info("SQL file executed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to execute SQL file: {e}")
        return False

async def verify_tables_created(client, expected_tables: list) -> bool:
    """verify if the tables are created successfully"""
    try:
        for table in expected_tables:
            exists = await check_table_exists(client, table)
            if not exists:
                logger.error(f"Failed to create table {table}")
                return False
            logger.debug(f"Table {table} verified successfully")
        
        logger.info("All tables verified successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to verify tables created: {e}")
        return False

async def initialize_database() -> bool:
    """initialize the database tables"""
    
    # 第一步：确保数据库存在
    logger.info("Step 1: Check and create database...")
    db_exists = await ensure_database_exists()
    if not db_exists:
        logger.error("Failed to create or check database")
        return False
    
    # 第二步：初始化数据库连接和表
    logger.info("Step 2: Check database tables...")
    
    db = None
    try:
        # 初始化数据库连接
        db = DBConnection()
        await db.initialize()
        logger.info("Database connection pool initialized successfully")
        
        # 获取客户端
        client = await db.client
        logger.info("Database client obtained successfully")
        
        # 检查缺失的表
        missing_tables = await get_missing_tables(client)
        
        if not missing_tables:
            logger.info("All required tables exist")
            return True
        
        logger.info(f"Found {len(missing_tables)} missing tables: {missing_tables}")
        
        # 找到SQL文件路径
        sql_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations', 'fufanmanus.sql')
        
        if not os.path.exists(sql_file_path):
            logger.error(f"SQL file does not exist: {sql_file_path}")
            return False
        
        # 执行SQL文件
        logger.info("Creating missing tables...")
        success = await execute_sql_file(client, sql_file_path)
        
        if not success:
            logger.error("Failed to execute SQL file")
            return False
        
        # 验证表创建结果
        logger.info("Verifying table creation results...")
        verification_success = await verify_tables_created(client, missing_tables)
        
        if verification_success:
            logger.info("Database initialization completed! All tables created successfully")
            return True
        else:
            logger.error("Failed to create some tables")
            return False
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return False
    
    finally:
        # 清理连接
        if db:
            try:
                await db.disconnect()
                logger.debug("Database connection cleaned up")
            except Exception as e:
                logger.warning(f"Failed to clean up database connection: {e}")

async def check_database_connectivity() -> bool:
    """check the database connectivity (including ensuring the database exists)"""
    db = None
    try:
        # 首先确保数据库存在
        logger.info("Checking if database exists...")
        db_exists = await ensure_database_exists()
        if not db_exists:
            logger.error("Database does not exist and creation failed")
            return False
        
        # 然后测试连接
        logger.info("Testing database connection...")
        db = DBConnection()
        await db.initialize()
        
        client = await db.client
        async with client.pool.acquire() as conn:
            await conn.fetchrow("SELECT 1")
        
        logger.info("Database connection正常")
        return True
        
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        return False
    
    finally:
        if db:
            try:
                await db.disconnect()
            except Exception:
                pass

async def main():
    """main function"""
    print("=" * 70)
    print("Database initialization script")

    
    # 检查环境变量
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        db_config = parse_database_url(database_url)
        print(f"Target database: {db_config['database']} @ {db_config['host']}:{db_config['port']}")
    else:
        print("Target database: fufanmanus @ localhost:5432 (default configuration)")
    
    # 检查数据库连接（包括创建数据库）
    connectivity_ok = await check_database_connectivity()
    if not connectivity_ok:
        print("\nFailed to execute script! Database connection or creation failed.")
        print("Please check:")
        print("   - Whether PostgreSQL service is running")
        print("   - Whether the user has permission to create databases")
        print("   - Whether the network connection is normal")
        sys.exit(1)

    
    # 初始化数据库表
    success = await initialize_database()
    
    if success:
        print("\nScript executed successfully! Database and all tables are ready.")
        print("You can start the application service")
        sys.exit(0)
    else:
        print("\nFailed to execute script! Please check the error information.")
        sys.exit(1)


if __name__ == "__main__":
    # 确保在Windows上使用正确的事件循环策略
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(main()) 