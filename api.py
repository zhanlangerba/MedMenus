from dotenv import load_dotenv # type: ignore
load_dotenv()

import asyncio
import time
import uuid
import sys

from fastapi import FastAPI, Request, HTTPException, Response, Depends, APIRouter # type: ignore
from utils.logger import logger, structlog
from datetime import datetime, timezone

from fastapi.middleware.cors import CORSMiddleware # type: ignore
# from fastapi.responses import JSONResponse, StreamingResponse
# from services import redis
# import sentry
from contextlib import asynccontextmanager
# from agentpress.thread_manager import ThreadManager
from services.postgresql import DBConnection
from utils.config import config, EnvMode
from collections import OrderedDict
# from pydantic import BaseModel
from flags import api as feature_flags_api
from agent import api as agent_api
# from sandbox import api as sandbox_api
# from services import billing as billing_api
# 
# from services import transcription as transcription_api
# 
# from services import email_api
# from triggers import api as triggers_api
# from services import api_keys_api

# 强制 asyncio 使用 Proactor 事件循环，以确保异步 I/O 的兼容性和稳定性。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 初始化管理器
db = DBConnection()
instance_id = "single"

# Rate limiter state
ip_tracker = OrderedDict()
MAX_CONCURRENT_IPS = 25

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting up FastAPI application with instance ID: {instance_id} in {config.ENV_MODE.value} mode")
    try:
        # 初始化PostgreSQL数据库连接
        await db.initialize()
        logger.info("PostgreSQL数据库连接初始化完成")
        
        # 初始化Redis连接
        from services import redis
        try:
            await redis.initialize_async()
            logger.info("Redis connection initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")

        # 初始化Agent
        agent_api.initialize(
            db,
            instance_id
        )

        # Start background tasks
        # asyncio.create_task(agent_api.restore_running_agent_runs())

        # sandbox_api.initialize(db)
        
        
        # triggers_api.initialize(db)
        # pipedream_api.initialize(db)
        # credentials_api.initialize(db)
        # template_api.initialize(db)
        # composio_api.initialize(db)
        
        yield
        
        # 清理Agent资源
        logger.info("Cleaning up agent resources")
        await agent_api.cleanup()
        
        # 清理Redis连接
        try:
            logger.info("Closing Redis connection")
            await redis.close()
            logger.info("Redis connection closed successfully")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
        
        # 清理数据库连接
        logger.info("正在断开数据库连接")
        await db.disconnect()
    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        raise

app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = str(uuid.uuid4())
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    method = request.method
    path = request.url.path
    query_params = str(request.query_params)

    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        client_ip=client_ip,
        method=method,
        path=path,
        query_params=query_params
    )

    # 记录请求
    logger.info(f"Request started: {method} {path} from {client_ip} | Query: {query_params}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.debug(f"Request completed: {method} {path} | Status: {response.status_code} | Time: {process_time:.2f}s")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request failed: {method} {path} | Error: {str(e)} | Time: {process_time:.2f}s")
        raise

# 定义允许的源
allowed_origins = ["https://www.example.com", "https://example.com"]  # 如果有多个源，可以在这里添加
allow_origin_regex = None

# 添加本地开发环境源
if config.ENV_MODE == EnvMode.LOCAL:
    allowed_origins.append("http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 临时允许所有源，用于调试
    allow_credentials=False,  # 当使用 "*" 时必须设为 False
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头部
)

# 创建主API路由
api_router = APIRouter()

# 包含认证路由
from auth.api import router as auth_router
api_router.include_router(auth_router)

# Include feature flags router
api_router.include_router(feature_flags_api.router)

# Include all API routers without individual prefixes
api_router.include_router(agent_api.router)  
# api_router.include_router(sandbox_api.router)
# api_router.include_router(billing_api.router)

# api_router.include_router(api_keys_api.router)

# from mcp_module import api as mcp_api
# from credentials import api as credentials_api
# from templates import api as template_api

# api_router.include_router(mcp_api.router)
# api_router.include_router(credentials_api.router, prefix="/secure-mcp")
# api_router.include_router(template_api.router, prefix="/templates")

# api_router.include_router(transcription_api.router)
# api_router.include_router(email_api.router)

# from knowledge_base import api as knowledge_base_api
# api_router.include_router(knowledge_base_api.router)

# api_router.include_router(triggers_api.router)

# from pipedream import api as pipedream_api
# api_router.include_router(pipedream_api.router)

# # MFA functionality moved to frontend


# from admin import api as admin_api
# api_router.include_router(admin_api.router)

# from composio_integration import api as composio_api
# api_router.include_router(composio_api.router)

@api_router.get("/health")
async def health_check():
    logger.info("Health check endpoint called")
    return {
        "status": "ok", 
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # "instance_id": instance_id
    }

# 添加全局 OPTIONS 处理器来解决 CORS 问题
@app.options("/{path:path}")
async def options_handler(request: Request, path: str):
    """处理所有的 OPTIONS 请求（CORS 预检）"""
    logger.info(f"🔍 [CORS] OPTIONS /{path} called")
    logger.info(f"🔍 [CORS] Headers: {dict(request.headers)}")
    
    from fastapi.responses import Response
    response = Response(status_code=200)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    
    logger.info(f"✅ [CORS] Returning CORS preflight response for /{path}")
    return response

@api_router.get("/health-docker")
async def health_check_docker():
    """Docker健康检查端点，测试数据库和Redis连接"""
    logger.info("Docker健康检查端点被调用")
    try:
        # 测试Redis连接
        from services import redis
        client = await redis.get_client()
        await client.ping()
        
        # 测试数据库连接
        db_instance = DBConnection()
        await db_instance.initialize()
        db_client = await db_instance.client
        # 尝试查询一个简单的表来测试连接
        await db_client.table("auth_users").select("id").limit(1).execute()
        
        logger.info("Docker健康检查完成")
        return {
            "status": "ok", 
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "database": "connected",
            "redis": "connected"
        }
    except Exception as e:
        logger.error(f"Docker健康检查失败: {e}")
        raise HTTPException(status_code=500, detail=f"健康检查失败: {str(e)}")


app.include_router(api_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    workers = 4
    
    logger.info(f"Starting server on 0.0.0.0:8000 with {workers} workers")
    uvicorn.run(
        "api:app", 
        host="0.0.0.0", 
        port=8000,
        workers=workers,
        loop="asyncio",
        reload=True
    )