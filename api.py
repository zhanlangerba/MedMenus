from dotenv import load_dotenv # type: ignore
load_dotenv(override=True)

# 设置日志级别
import os
if not os.getenv("LOGGING_LEVEL"):
    os.environ["LOGGING_LEVEL"] = "INFO"
if not os.getenv("ENV_MODE"):
    os.environ["ENV_MODE"] = "LOCAL"

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
from services.postgresql import DBConnection
from utils.config import config, EnvMode
from collections import OrderedDict
# from pydantic import BaseModel
from flags import api as feature_flags_api
from agent import api as agent_api
from sandbox import api as sandbox_api
# from services import transcription as transcription_api
# from services import api_keys_api
from utils.simple_auth_middleware import get_current_user_id_from_jwt
# 强制 asyncio 使用 Proactor 事件循环，以确保异步 I/O 的兼容性和稳定性。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 初始化管理器
db = DBConnection()
instance_id = "single"

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting up FastAPI application with instance ID: {instance_id} in {config.ENV_MODE.value} mode")
    try:
        # 初始化PostgreSQL数据库连接
        await db.initialize()
        logger.info("PostgreSQL database connection initialized successfully")
          
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

        # sandbox_api.initialize(db)
        
        # 初始化triggers API
        # 触发器组件，用于触发工作流执行（基于ADK可以省略大部分的触发器工作流）
        try:
            triggers_api.initialize(db)
            logger.info("Triggers API initialized successfully")
        except Exception as e:
            logger.warning(f"Triggers API initialization skipped: {e}")
        
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
        logger.info("Closing PostgreSQL database connection")
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"] if config.ENV_MODE == EnvMode.LOCAL else ["*"],
    allow_credentials=True,  # 允许认证凭据
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # 显式指定方法
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],  # 显式指定头部
)

# 创建主API路由
api_router = APIRouter()

# 添加通用的OPTIONS处理器
@app.options("/{path:path}")
async def options_handler(path: str):
    """Handle OPTIONS preflight requests"""
    return {"message": "OK"}

# 包含认证路由
from auth.api import router as auth_router

# 用户认证管理模块
api_router.include_router(auth_router)

# Include feature flags router
api_router.include_router(feature_flags_api.router)

# Include all API routers without individual prefixes
api_router.include_router(agent_api.router)

# Include agent versioning router
from agent.versioning.api import router as versioning_router
api_router.include_router(versioning_router)  
api_router.include_router(sandbox_api.router)

from triggers import api as triggers_api
api_router.include_router(triggers_api.router)

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

# 

# from pipedream import api as pipedream_api
# api_router.include_router(pipedream_api.router)

# # MFA functionality moved to frontend


# from admin import api as admin_api
# api_router.include_router(admin_api.router)

# from composio_integration import api as composio_api
# api_router.include_router(composio_api.router)

@api_router.get("/sidebar/projects")
async def get_projects(user_id: str = Depends(get_current_user_id_from_jwt)):
    """get projects for sidebar"""
    try:
        logger.info(f"Getting projects for user: {user_id}")
        
        # 获取数据库客户端
        client = await db.client
      
        # 查询用户的项目列表
        logger.info(f"Querying projects table for account_id: {user_id}")
        result = await client.table("projects").select("*").eq("account_id", user_id).order("created_at", desc=True).execute()
        
        if hasattr(result, 'data'):
            logger.info(f"Projects result.data type: {type(result.data)}")
            logger.info(f"Projects result.data length: {len(result.data) if result.data else 'None'}")
        else:
            logger.error(f"Projects result object has no 'data' attribute")
        
        # 检查是否有数据
        if not result.data:
            logger.info(f"No projects found for user: {user_id}")
            return []
        
        # 格式化返回数据
        projects = []
        logger.info(f"🔄 Processing {len(result.data)} raw projects")
        
        for i, project in enumerate(result.data):
            logger.info(f"Processing project {i+1}: {project.get('project_id', 'no-id')}")
            
            # 处理sandbox字段，确保包含必需的字段
            sandbox_config = project.get("sandbox", {})
            if not isinstance(sandbox_config, dict):
                sandbox_config = {}
            
            # 确保sandbox包含所需字段
            sandbox = {
                "id": sandbox_config.get("id", ""),
                "pass": sandbox_config.get("pass", ""), 
                "vnc_preview": sandbox_config.get("vnc_preview", ""),
                "sandbox_url": sandbox_config.get("sandbox_url", "")
            }
            
            # 处理metadata中的is_public字段
            metadata = project.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            
            formatted_project = {
                "id": project["project_id"],  # 映射project_id为id
                "name": project["name"],
                "description": project.get("description", ""),
                "account_id": project["account_id"],
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
                "sandbox": sandbox,
                "is_public": metadata.get("is_public", False)  # 从metadata中获取或默认为False
            }
            projects.append(formatted_project)
        
        logger.info(f"Final projects count: {len(projects)}")
        logger.info(f"Final projects type: {type(projects)}")
        
        logger.info(f"Successfully found {len(projects)} projects for user: {user_id}")
        return projects
        
    except Exception as e:
        logger.error(f"Error getting projects for user {user_id}: {e}")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception traceback:", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get projects: {str(e)}")

@api_router.get("/sidebar/threads")
async def get_threads(user_id: str = Depends(get_current_user_id_from_jwt)):
    """get threads for sidebar"""
    try:
        logger.info(f"Getting threads for user: {user_id}")
        
        # 获取数据库客户端
        client = await db.client
        
        # 查询用户的线程列表，过滤掉is_agent_builder=true的线程
        logger.info(f"Querying threads table for account_id: {user_id}")
        result = await client.table("threads").select("*").eq("account_id", user_id).order("created_at", desc=True).execute()
        
        
        if hasattr(result, 'data'):
            logger.info(f"Result.data length: {len(result.data) if result.data else 'None'}")
        else:
            logger.error(f"Result object has no 'data' attribute")
            logger.error(f"Result attributes: {dir(result)}")
        
        # 检查是否有数据
        if not result.data:
            logger.info(f"No threads found for user: {user_id}")
            return []
        
        # 格式化返回数据并过滤
        threads = []
        logger.info(f"Processing {len(result.data)} raw threads")
        
        for i, thread in enumerate(result.data):
            logger.info(f"Processing thread {i+1}: {thread.get('thread_id', 'no-id')}")
            
            # 处理metadata字段
            metadata = thread.get("metadata", {})
            if not isinstance(metadata, dict):
                logger.info(f"Converting metadata from {type(metadata)} to dict")
                metadata = {}
            
            logger.info(f"Thread metadata: {metadata}")
            
            # 过滤掉is_agent_builder为true的线程
            if metadata.get("is_agent_builder") == True:
                logger.info(f"Skipping thread {thread.get('thread_id')} - is_agent_builder=true")
                continue
                
            formatted_thread = {
                "id": thread["thread_id"],  # 映射thread_id为id
                "name": thread.get("name", ""),
                "project_id": thread["project_id"],
                "account_id": thread["account_id"],
                "status": thread.get("status", "active"),
                "metadata": metadata,
                "created_at": thread["created_at"],
                "updated_at": thread["updated_at"]
            }
            
            threads.append(formatted_thread)
        
        
        logger.info(f"Successfully found {len(threads)} threads for user: {user_id}")
        return threads
        
    except Exception as e:
        logger.error(f"Error getting threads for user {user_id}: {e}")
        logger.error(f"Exception type: {type(e)}")
        logger.error(f"Exception traceback:", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get threads: {str(e)}")

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