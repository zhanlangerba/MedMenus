"""
Redis connection service - asyncio version

前端请求 → 后端API → 启动Agent后台进程
                ↓
         创建Redis Keys:
         - response_list_key (存储响应)
         - response_channel (通知频道)
                ↓
    Agent开始运行，每产生一个响应:
    1. rpush(response_list_key, response)  ← 存储数据
    2. publish(response_channel, "new")    ← 发送通知
                ↓
    前端API订阅response_channel:
    1. 收到"new"通知
    2. lrange(response_list_key, last_index, -1)  ← 获取新数据
    3. 立即返回给前端渲染

await redis.rpush("my_list", "item1")
await redis.rpush("my_list", "item2") 
await redis.rpush("my_list", "item3")

# 结果：["item1", "item2", "item3"]
#        ↑                    ↑
#      左侧(头)             右侧(尾)
"""

import redis.asyncio as redis # type: ignore
import os
from dotenv import load_dotenv # type: ignore
import asyncio
from utils.logger import logger
from typing import List, Any
from utils.retry import retry

# Redis客户端和连接池全局变量
client: redis.Redis | None = None  # Redis客户端实例
pool: redis.ConnectionPool | None = None  # Redis连接池
_initialized = False  # 初始化状态标志
_init_lock = asyncio.Lock()  # 异步初始化锁，防止并发初始化

# Redis键值过期时间配置
REDIS_KEY_TTL = 3600 * 24  # 默认24小时过期时间


def initialize():
    """Initialize Redis connection pool and client"""
    global client, pool

    # 加载环境变量（如果尚未加载）
    load_dotenv(override=True)

    # 从环境变量获取Redis配置
    redis_host = os.getenv("REDIS_HOST", "redis")  # Redis主机地址，默认"redis"
    redis_port = int(os.getenv("REDIS_PORT", 6379))  # Redis端口，默认6379
    redis_password = os.getenv("REDIS_PASSWORD", "")  # Redis密码，默认空
    
    # 连接池配置 - 针对生产环境优化
    max_connections = 128            # 最大连接数，生产环境合理限制
    socket_timeout = 15.0            # Socket超时时间，15秒
    connect_timeout = 10.0           # 连接超时时间，10秒
    retry_on_timeout = not (os.getenv("REDIS_RETRY_ON_TIMEOUT", "True").lower() != "true")  # 超时重试开关

    logger.info(f"Initializing Redis connection pool: {redis_host}:{redis_port}, max connections: {max_connections}")

    # 创建生产环境优化的连接池
    pool = redis.ConnectionPool(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        decode_responses=True,  # 自动解码响应为字符串
        socket_timeout=socket_timeout,  # Socket操作超时
        socket_connect_timeout=connect_timeout,  # 连接超时
        socket_keepalive=True,  # 启用Socket保活
        retry_on_timeout=retry_on_timeout,  # 超时重试
        health_check_interval=30,  # 健康检查间隔，30秒
        max_connections=max_connections,  # 最大连接数
    )

    # 从连接池创建Redis客户端
    client = redis.Redis(connection_pool=pool)

    return client

async def initialize_async():
    """Async initialize Redis connection"""
    global client, _initialized

    async with _init_lock:  # 使用异步锁防止并发初始化
        if not _initialized:
            logger.info("Initializing Redis connection")
            initialize()  # 调用同步初始化函数

        try:
            # 测试连接，设置5秒超时
            await asyncio.wait_for(client.ping(), timeout=5.0)
            logger.info("Redis connection initialized successfully")
            _initialized = True
        except asyncio.TimeoutError:
            logger.error("Redis connection initialization timeout")
            client = None
            _initialized = False
            raise ConnectionError("Redis connection timeout")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            client = None
            _initialized = False
            raise

    return client

async def close():
    """Close Redis connection and connection pool"""
    global client, pool, _initialized
    
    # 关闭Redis客户端连接
    if client:
        logger.info("Closing Redis connection")
        try:
            await asyncio.wait_for(client.aclose(), timeout=5.0)  # 5秒超时关闭
        except asyncio.TimeoutError:
            logger.warning("Redis connection close timeout, force close")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")
        finally:
            client = None  # 清空客户端引用
    
    # 关闭Redis连接池
    if pool:
        logger.info("Closing Redis connection pool")
        try:
            await asyncio.wait_for(pool.aclose(), timeout=5.0)  # 5秒超时关闭
        except asyncio.TimeoutError:
            logger.warning("Redis connection pool close timeout, force close")
        except Exception as e:
            logger.warning(f"Error closing Redis connection pool: {e}")
        finally:
            pool = None  # 清空连接池引用
    
    _initialized = False  # 重置初始化状态
    logger.info("Redis connection and connection pool closed")

async def get_client():
    """Get Redis client, if not initialized then initialize it"""
    global client, _initialized
    if client is None or not _initialized:
        # 默认配置
        # max_attempts = 3 - 最多尝试3次
        # delay_seconds = 1 - 每次重试间隔1秒
        await retry(lambda: initialize_async())  # 使用重试机制初始化
    return client

async def set(key: str, value: str, ex: int = None, nx: bool = False):
    """Set Redis key-value pair
    
    Args:
        key: key name
        value: 值
        ex: expiration time (seconds), optional
        nx: only set if key does not exist, optional
    """
    redis_client = await get_client()
    return await redis_client.set(key, value, ex=ex, nx=nx)

async def get(key: str, default: str = None):
    """Get Redis key-value
    
    Args:
        key: key name
        default: default value, return when key does not exist
    """
    redis_client = await get_client()
    result = await redis_client.get(key)
    return result if result is not None else default

async def delete(key: str):
    """Delete Redis key
    
    Args:
        key: key name
    """
    redis_client = await get_client()
    return await redis_client.delete(key)

async def publish(channel: str, message: str):
    """Publish message to Redis channel (publish/subscribe mode)
    
    Args:
        channel: channel name
        message: message to publish
    """
    redis_client = await get_client()
    return await redis_client.publish(channel, message)

async def create_pubsub():
    """Create Redis publish/subscribe object
    
    Returns:
        Redis pubsub object, for subscribing to channels
    """
    redis_client = await get_client()
    return redis_client.pubsub()

async def rpush(key: str, *values: Any):
    """Add one or more values to the right side of the list
    
    Args:
        key: list key name
        *values: values to add (variable arguments)
    """
    redis_client = await get_client()
    return await redis_client.rpush(key, *values)

async def lrange(key: str, start: int, end: int) -> List[str]:
    """Get elements in the specified range of the list
    
    Args:
        key: list key name
        start: start index
        end: end index (inclusive)
    
    Returns:
        list of elements in the specified range
    """
    redis_client = await get_client()
    return await redis_client.lrange(key, start, end)

async def keys(pattern: str) -> List[str]:
    """Find keys matching the pattern
    
    Args:
        pattern: key name pattern, supports wildcards (e.g. user:*)
    
    Returns:
        list of keys matching the pattern
    """
    redis_client = await get_client()
    return await redis_client.keys(pattern)

async def expire(key: str, seconds: int):
    """Set the expiration time of the key
    
    Args:
        key: key name
        seconds: expiration time (seconds)
    
    Returns:
        whether the expiration time is set successfully
    """
    redis_client = await get_client()
    return await redis_client.expire(key, seconds)
