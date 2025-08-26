"""
Redis connection service - asyncio version
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
    """初始化Redis连接池和客户端（同步版本）"""
    global client, pool

    # 加载环境变量（如果尚未加载）
    load_dotenv()

    # 从环境变量获取Redis配置
    redis_host = os.getenv("REDIS_HOST", "redis")  # Redis主机地址，默认"redis"
    redis_port = int(os.getenv("REDIS_PORT", 6379))  # Redis端口，默认6379
    redis_password = os.getenv("REDIS_PASSWORD", "")  # Redis密码，默认空
    
    # 连接池配置 - 针对生产环境优化
    max_connections = 128            # 最大连接数，生产环境合理限制
    socket_timeout = 15.0            # Socket超时时间，15秒
    connect_timeout = 10.0           # 连接超时时间，10秒
    retry_on_timeout = not (os.getenv("REDIS_RETRY_ON_TIMEOUT", "True").lower() != "true")  # 超时重试开关

    logger.info(f"正在初始化Redis连接池: {redis_host}:{redis_port}，最大连接数: {max_connections}")

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
    """异步初始化Redis连接"""
    global client, _initialized

    async with _init_lock:  # 使用异步锁防止并发初始化
        if not _initialized:
            logger.info("正在初始化Redis连接")
            initialize()  # 调用同步初始化函数

        try:
            # 测试连接，设置5秒超时
            await asyncio.wait_for(client.ping(), timeout=5.0)
            logger.info("Redis连接成功")
            _initialized = True
        except asyncio.TimeoutError:
            logger.error("Redis连接初始化超时")
            client = None
            _initialized = False
            raise ConnectionError("Redis连接超时")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            client = None
            _initialized = False
            raise

    return client


async def close():
    """关闭Redis连接和连接池"""
    global client, pool, _initialized
    
    # 关闭Redis客户端连接
    if client:
        logger.info("正在关闭Redis连接")
        try:
            await asyncio.wait_for(client.aclose(), timeout=5.0)  # 5秒超时关闭
        except asyncio.TimeoutError:
            logger.warning("Redis连接关闭超时，强制关闭")
        except Exception as e:
            logger.warning(f"关闭Redis客户端时出错: {e}")
        finally:
            client = None  # 清空客户端引用
    
    # 关闭Redis连接池
    if pool:
        logger.info("正在关闭Redis连接池")
        try:
            await asyncio.wait_for(pool.aclose(), timeout=5.0)  # 5秒超时关闭
        except asyncio.TimeoutError:
            logger.warning("Redis连接池关闭超时，强制关闭")
        except Exception as e:
            logger.warning(f"关闭Redis连接池时出错: {e}")
        finally:
            pool = None  # 清空连接池引用
    
    _initialized = False  # 重置初始化状态
    logger.info("Redis连接和连接池已关闭")


async def get_client():
    """获取Redis客户端，如果未初始化则自动初始化"""
    global client, _initialized
    if client is None or not _initialized:
        await retry(lambda: initialize_async())  # 使用重试机制初始化
    return client


# ==================== 基本Redis操作 ====================

async def set(key: str, value: str, ex: int = None, nx: bool = False):
    """设置Redis键值对
    
    Args:
        key: 键名
        value: 值
        ex: 过期时间（秒），可选
        nx: 仅在键不存在时设置，可选
    """
    redis_client = await get_client()
    return await redis_client.set(key, value, ex=ex, nx=nx)


async def get(key: str, default: str = None):
    """获取Redis键值
    
    Args:
        key: 键名
        default: 默认值，当键不存在时返回
    """
    redis_client = await get_client()
    result = await redis_client.get(key)
    return result if result is not None else default


async def delete(key: str):
    """删除Redis键
    
    Args:
        key: 要删除的键名
    """
    redis_client = await get_client()
    return await redis_client.delete(key)


async def publish(channel: str, message: str):
    """发布消息到Redis频道（发布/订阅模式）
    
    Args:
        channel: 频道名称
        message: 要发布的消息
    """
    redis_client = await get_client()
    return await redis_client.publish(channel, message)


async def create_pubsub():
    """创建Redis发布/订阅对象
    
    Returns:
        Redis pubsub对象，用于订阅频道
    """
    redis_client = await get_client()
    return redis_client.pubsub()


# ==================== 列表操作 ====================

async def rpush(key: str, *values: Any):
    """向列表右侧添加一个或多个值
    
    Args:
        key: 列表键名
        *values: 要添加的值（可变参数）
    """
    redis_client = await get_client()
    return await redis_client.rpush(key, *values)


async def lrange(key: str, start: int, end: int) -> List[str]:
    """获取列表中指定范围的元素
    
    Args:
        key: 列表键名
        start: 起始索引
        end: 结束索引（包含）
    
    Returns:
        指定范围的元素列表
    """
    redis_client = await get_client()
    return await redis_client.lrange(key, start, end)


# ==================== 键管理操作 ====================

async def keys(pattern: str) -> List[str]:
    """根据模式查找匹配的键
    
    Args:
        pattern: 键名模式，支持通配符（如：user:*）
    
    Returns:
        匹配的键名列表
    """
    redis_client = await get_client()
    return await redis_client.keys(pattern)


async def expire(key: str, seconds: int):
    """设置键的过期时间
    
    Args:
        key: 键名
        seconds: 过期时间（秒）
    
    Returns:
        设置是否成功
    """
    redis_client = await get_client()
    return await redis_client.expire(key, seconds)
