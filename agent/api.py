from fastapi import APIRouter, HTTPException, Depends, Request, Body, File, UploadFile, Form, Query # type: ignore
from fastapi.responses import StreamingResponse # type: ignore
import asyncio
import json
import traceback
import base64
from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any
import jwt # type: ignore
from pydantic import BaseModel # type: ignore
import tempfile
import os

# from agentpress.thread_manager import ThreadManager
from services.postgresql import DBConnection
from services import redis
from utils.simple_auth_middleware import get_current_user_id_from_jwt, get_user_id_from_stream_auth, verify_thread_access
from utils.logger import logger, structlog
# from services.billing import check_billing_status, can_use_model
from utils.config import config
from sandbox.sandbox import create_sandbox, delete_sandbox, get_or_start_sandbox
# from run_agent_background import run_agent_background, _cleanup_redis_response_list, update_agent_run_status
from run_agent_background import run_agent_background

def determine_sandbox_type(files):
    """
    根据上传的文件类型智能选择沙箱模板
    
    Args:
        files: 上传的文件列表
        
    Returns:
        str: 沙箱类型 ('desktop', 'browser', 'code', 'base')
    """
    if not files:
        return 'desktop'  # 默认使用桌面模板
    
    # 分析文件类型
    file_extensions = []
    file_names = []
    
    for file_obj in files:
        # UploadFile 对象直接使用 .filename 属性
        if hasattr(file_obj, 'filename') and file_obj.filename:
            filename = file_obj.filename.lower()
        elif hasattr(file_obj, 'get'):
            # 如果是字典格式的文件信息
            filename = file_obj.get('filename', '').lower()
        else:
            # 如果是字符串
            filename = str(file_obj).lower()
            
        file_names.append(filename)
        if '.' in filename:
            ext = filename.split('.')[-1]
            file_extensions.append(ext)
    
    logger.info(f"Analyzing file types: {file_extensions}")
    
    # 如果有网页相关文件，使用浏览器模板
    web_extensions = {'html', 'htm', 'css', 'js', 'ts', 'jsx', 'tsx', 'vue', 'react'}
    if any(ext in web_extensions for ext in file_extensions):
        logger.info("Detected web files, selecting browser template")
        return 'browser'
    
    # 如果只有代码文件且不需要图形界面，使用代码解释器
    code_extensions = {'py', 'ipynb', 'r', 'sql', 'sh', 'bash', 'json', 'yaml', 'yml', 'txt', 'md'}
    if (any(ext in code_extensions for ext in file_extensions) and 
        not any(ext in {'png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'doc', 'docx'} for ext in file_extensions)):
        # 如果有 Jupyter notebook，使用桌面环境以便查看图表
        if any(ext == 'ipynb' for ext in file_extensions):
            logger.info("Detected Jupyter notebook, selecting desktop template")
            return 'desktop'
        logger.info("Detected pure code files, selecting code interpreter template")
        return 'code'
    
    # 默认使用桌面模板 - 提供最完整的功能
    # 适用于：图像文件、混合文件类型、需要图形界面的场景
    logger.info("Using default desktop template")
    return 'desktop'
from utils.constants import MODEL_NAME_ALIASES
from flags.flags import is_enabled

from .config_helper import extract_agent_config, build_unified_config, extract_tools_for_agent_run, get_mcp_configs

router = APIRouter()

db = None
instance_id = None # Global instance ID for this backend instance

# TTL for Redis response lists (24 hours)
REDIS_RESPONSE_LIST_TTL = 3600 * 24

class AgentStartRequest(BaseModel):
    model_name: Optional[str] = None  # Will be set from config.MODEL_TO_USE in the endpoint
    enable_thinking: Optional[bool] = False
    reasoning_effort: Optional[str] = 'low'
    stream: Optional[bool] = True
    enable_context_manager: Optional[bool] = False
    agent_id: Optional[str] = None  # Custom agent to use

class InitiateAgentResponse(BaseModel):
    thread_id: str
    agent_run_id: Optional[str] = None

class CreateThreadResponse(BaseModel):
    thread_id: str
    project_id: str

class MessageCreateRequest(BaseModel):
    type: str
    content: str
    is_llm_message: bool = True

class AgentCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None  # 确保系统提示词是可选的，允许默认使用 FuFanManus 的系统提示词
    model: Optional[str] = None  # 确保模型是可选的
    configured_mcps: Optional[List[Dict[str, Any]]] = []
    custom_mcps: Optional[List[Dict[str, Any]]] = []
    agentpress_tools: Optional[Dict[str, Any]] = {}
    is_default: Optional[bool] = False
    avatar: Optional[str] = None
    avatar_color: Optional[str] = None
    profile_image_url: Optional[str] = None

class AgentVersionResponse(BaseModel):
    version_id: str
    agent_id: str
    version_number: int
    version_name: str
    system_prompt: str
    model: Optional[str] = None  # Add model field
    configured_mcps: List[Dict[str, Any]]
    custom_mcps: List[Dict[str, Any]]
    agentpress_tools: Dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str
    created_by: Optional[str] = None

class AgentVersionCreateRequest(BaseModel):
    system_prompt: str
    configured_mcps: Optional[List[Dict[str, Any]]] = []
    custom_mcps: Optional[List[Dict[str, Any]]] = []
    agentpress_tools: Optional[Dict[str, Any]] = {}
    version_name: Optional[str] = None  # Custom version name
    description: Optional[str] = None  # Version description

class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    configured_mcps: Optional[List[Dict[str, Any]]] = None
    custom_mcps: Optional[List[Dict[str, Any]]] = None
    agentpress_tools: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None
    # Deprecated, kept for backward-compat
    avatar: Optional[str] = None
    avatar_color: Optional[str] = None
    # New profile image url
    profile_image_url: Optional[str] = None

class AgentResponse(BaseModel):
    agent_id: str
    account_id: str
    name: str
    description: Optional[str] = None
    system_prompt: str
    configured_mcps: List[Dict[str, Any]]
    custom_mcps: List[Dict[str, Any]]
    agentpress_tools: Dict[str, Any]
    is_default: bool
    avatar: Optional[str] = None
    avatar_color: Optional[str] = None
    profile_image_url: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None
    is_public: Optional[bool] = False

    tags: Optional[List[str]] = []
    current_version_id: Optional[str] = None
    version_count: Optional[int] = 1
    current_version: Optional[AgentVersionResponse] = None
    metadata: Optional[Dict[str, Any]] = None

class PaginationInfo(BaseModel):
    page: int
    limit: int
    total: int
    pages: int

class AgentsResponse(BaseModel):
    agents: List[AgentResponse]
    pagination: PaginationInfo

class ThreadAgentResponse(BaseModel):
    agent: Optional[AgentResponse]
    source: str  # "thread", "default", "none", "missing"
    message: str

class AgentExportData(BaseModel):
    """Exportable agent configuration data"""
    name: str
    description: Optional[str] = None
    system_prompt: str
    agentpress_tools: Dict[str, Any]
    configured_mcps: List[Dict[str, Any]]
    custom_mcps: List[Dict[str, Any]]
    # Deprecated
    avatar: Optional[str] = None
    avatar_color: Optional[str] = None
    # New
    profile_image_url: Optional[str] = None
    tags: Optional[List[str]] = []
    metadata: Optional[Dict[str, Any]] = None
    export_version: str = "1.1"
    exported_at: str
    exported_by: Optional[str] = None

class AgentImportRequest(BaseModel):
    """Request to import an agent from JSON"""
    import_data: AgentExportData
    import_as_new: bool = True  # Always true, only creating new agents is supported

# Helper for version service
async def _get_version_service():
    from .versioning.version_service import get_version_service
    return await get_version_service()

def initialize(
    _db: DBConnection,
    _instance_id: Optional[str] = None
):
    """Initialize the agent API with resources from the main API."""
    global db, instance_id
    db = _db
    
    # Initialize the versioning module with the same database connection
    # initialize_versioning(_db)

    # Use provided instance_id or generate a new one
    if _instance_id:
        instance_id = _instance_id
    else:
        # Generate instance ID
        instance_id = str(uuid.uuid4())[:8]

    logger.info(f"Initialized agent API with instance ID: {instance_id}")

async def cleanup():
    """Clean up resources and stop running agents on shutdown."""
    logger.info("Starting cleanup of agent API resources")

    # Use the instance_id to find and clean up this instance's keys
    try:
        if instance_id: # Ensure instance_id is set
            running_keys = await redis.keys(f"active_run:{instance_id}:*")
            logger.info(f"Found {len(running_keys)} running agent runs for instance {instance_id} to clean up")

            for key in running_keys:
                # Key format: active_run:{instance_id}:{agent_run_id}
                parts = key.split(":")
                if len(parts) == 3:
                    agent_run_id = parts[2]
                    await stop_agent_run(agent_run_id, error_message=f"Instance {instance_id} shutting down")
                else:
                    logger.warning(f"Unexpected key format found: {key}")
        else:
            logger.warning("Instance ID not set, cannot clean up instance-specific agent runs.")

    except Exception as e:
        logger.error(f"Failed to clean up running agent runs: {str(e)}")

    # Close Redis connection
    await redis.close()
    logger.info("Completed cleanup of agent API resources")

async def stop_agent_run(agent_run_id: str, error_message: Optional[str] = None):
    """Update database and publish stop signal to Redis."""
    logger.info(f"Stopping agent run: {agent_run_id}")
    client = await db.client
    final_status = "failed" if error_message else "stopped"

    # Attempt to fetch final responses from Redis
    response_list_key = f"agent_run:{agent_run_id}:responses"
    all_responses = []
    try:
        all_responses_json = await redis.lrange(response_list_key, 0, -1)
        all_responses = [json.loads(r) for r in all_responses_json]
        logger.info(f"Fetched {len(all_responses)} responses from Redis for DB update on stop/fail: {agent_run_id}")
    except Exception as e:
        logger.error(f"Failed to fetch responses from Redis for {agent_run_id} during stop/fail: {e}")
        # Try fetching from DB as a fallback? Or proceed without responses? Proceeding without for now.

    # Update the agent run status in the database
    update_success = await update_agent_run_status(
        client, agent_run_id, final_status, error=error_message
    )

    if not update_success:
        logger.error(f"Failed to update database status for stopped/failed run {agent_run_id}")
        raise HTTPException(status_code=500, detail="Failed to update agent run status in database")

    # Send STOP signal to the global control channel
    global_control_channel = f"agent_run:{agent_run_id}:control"
    try:
        await redis.publish(global_control_channel, "STOP")
        logger.debug(f"Published STOP signal to global channel {global_control_channel}")
    except Exception as e:
        logger.error(f"Failed to publish STOP signal to global channel {global_control_channel}: {str(e)}")

    # Find all instances handling this agent run and send STOP to instance-specific channels
    try:
        instance_keys = await redis.keys(f"active_run:*:{agent_run_id}")
        logger.debug(f"Found {len(instance_keys)} active instance keys for agent run {agent_run_id}")

        for key in instance_keys:
            # Key format: active_run:{instance_id}:{agent_run_id}
            parts = key.split(":")
            if len(parts) == 3:
                instance_id_from_key = parts[1]
                instance_control_channel = f"agent_run:{agent_run_id}:control:{instance_id_from_key}"
                try:
                    await redis.publish(instance_control_channel, "STOP")
                    logger.debug(f"Published STOP signal to instance channel {instance_control_channel}")
                except Exception as e:
                    logger.warning(f"Failed to publish STOP signal to instance channel {instance_control_channel}: {str(e)}")
            else:
                 logger.warning(f"Unexpected key format found: {key}")

        # Clean up the response list immediately on stop/fail
        await _cleanup_redis_response_list(agent_run_id)

    except Exception as e:
        logger.error(f"Failed to find or signal active instances for {agent_run_id}: {str(e)}")

    logger.info(f"Successfully initiated stop process for agent run: {agent_run_id}")

async def get_agent_run_with_access_check(client, agent_run_id: str, user_id: str):
    """
    1. 查询 agent_run 记录：根据 agent_run_id 从 agent_runs 表中查找对应的 agent 运行记录
    2. 获取关联的 thread 信息：通过 thread_id 查询对应的线程记录
    3. 权限验证：检查当前用户是否有权限访问这个 agent_run
    """
    # 先查询 agent_run，使用新的 agent_run_id 字段
    agent_run = await client.table('agent_runs').select('*').eq('agent_run_id', agent_run_id).execute()
    if not agent_run.data:
        raise HTTPException(status_code=404, detail="Agent run not found")

    agent_run_data = agent_run.data[0]
    thread_id = agent_run_data['thread_id']
    
    # 再查询对应的 thread 来获取 account_id
    thread_result = await client.table('threads').select('account_id').eq('thread_id', thread_id).execute()
    if not thread_result.data:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    # 如果 agent_run 的 account_id 与 user_id 相同，则直接返回 agent_run_data
    account_id = thread_result.data[0]['account_id']
    if account_id == user_id:
        return agent_run_data

    # 如果 agent_run 的 account_id 与 user_id 不同，则需要验证用户是否有权限访问这个 agent_run，此逻辑用于扩展更丰富的权限控制
    await verify_thread_access(client, thread_id, user_id)
    return agent_run_data

@router.post("/thread/{thread_id}/agent/start")
async def start_agent(
    thread_id: str,
    body: AgentStartRequest = Body(...),
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """Start an agent for a specific thread in the background"""
    structlog.contextvars.bind_contextvars(
        thread_id=thread_id,
    )

    logger.info(f"Starting continue chat with exsting thread: {thread_id}")

    global instance_id 
    if not instance_id:
        raise HTTPException(status_code=500, detail="Agent API not initialized with instance ID")

    # 使用配置中的模型，如果请求中没有指定
    model_name = body.model_name
    logger.info(f"Original model_name from request: {model_name}")

    if model_name is None:
        model_name = config.MODEL_TO_USE
        logger.info(f"Using model from config: {model_name}")

    # 获取模型别名
    resolved_model = MODEL_NAME_ALIASES.get(model_name, model_name)
    logger.info(f"Resolved model name: {resolved_model}")

    # 根据别名更新模型名称
    model_name = resolved_model

    logger.info(f"Starting new agent for thread: {thread_id} with config: model={model_name}, thinking={body.enable_thinking}, effort={body.reasoning_effort}, stream={body.stream}, context_manager={body.enable_context_manager} (Instance: {instance_id})")
    
    # 获取数据库连接
    client = await db.client

    # 获取线程信息
    thread_result = await client.table('threads').select('project_id, account_id, metadata').eq('thread_id', thread_id).execute()
    logger.info(f"Thread result: {thread_result}")
    if not thread_result.data:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    thread_data = thread_result.data[0]
    project_id = thread_data.get('project_id')
    account_id = thread_data.get('account_id')
    thread_metadata = thread_data.get('metadata', {})

    if account_id != user_id:
        await verify_thread_access(client, thread_id, user_id)

    structlog.contextvars.bind_contextvars(
        project_id=project_id,
        account_id=account_id,
        thread_metadata=thread_metadata,
    )
    
    # # Check if this is an agent builder thread
    # is_agent_builder = thread_metadata.get('is_agent_builder', False)
    # target_agent_id = thread_metadata.get('target_agent_id')
    
    # if is_agent_builder:
    #     logger.info(f"Thread {thread_id} is in agent builder mode, target_agent_id: {target_agent_id}")
    
    # 加载agent配置，支持版本管理
    agent_config = None
    effective_agent_id = body.agent_id  # Optional agent ID from request
    
    logger.info(f"[AGENT LOAD] Agent loading flow:")
    logger.info(f"body.agent_id: {body.agent_id}")
    logger.info(f"effective_agent_id: {effective_agent_id}")

    if effective_agent_id:
        logger.info(f"[AGENT LOAD] Querying for agent: {effective_agent_id}")
        # 查询agent实例
        agent_result = await client.table('agents').select('*').eq('agent_id', effective_agent_id).eq('user_id', user_id).execute()
        logger.info(f"[AGENT LOAD] Query result: found {len(agent_result.data) if agent_result.data else 0} agents")
        
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found or access denied")
        
        agent_data = agent_result.data[0]
        logger.info(f"[AGENT INITIATE] Agent data: {agent_data}")
        
        # 使用版本管理系统获取当前版本
        version_data = None
        if agent_data.get('current_version_id'):
            try:
                version_service = await _get_version_service()
                version_obj = await version_service.get_version(
                    agent_id=effective_agent_id,
                    version_id=agent_data['current_version_id'],
                    user_id=user_id
                )
                version_data = version_obj.to_dict()
                logger.info(f"[AGENT INITIATE] Got version data from version manager: {version_data.get('version_name')}")
                logger.info(f"[AGENT INITIATE] Version data: {version_data}")
            except Exception as e:
                logger.warning(f"[AGENT INITIATE] Failed to get version data: {e}")
        
        logger.info(f"[AGENT INITIATE] About to call extract_agent_config with version data: {version_data is not None}")
        
        agent_config = extract_agent_config(agent_data, version_data)
        logger.info(f"start_agent_config: {agent_config}")
        if version_data:
            logger.info(f"Start agent Using custom agent: {agent_config['name']} ({effective_agent_id}) version {agent_config.get('version_name', 'v1')}")
        else:
            logger.info(f"Start agent Using custom agent: {agent_config['name']} ({effective_agent_id}) - no version data")
    else:
        logger.info(f"No agent_id provided, querying default agent")
        logger.info(f"No agent_id provided, querying default agent")
        # 优先查找FuFanManus默认Agent，如果没有再查找普通默认Agent
        # 这里查找的逻辑是可以把自定义的Agent设置成默认，如果有，则加载指定的默认Agent
        fufanmanus_agent_result = await client.table('agents').select('*').eq('user_id', user_id).eq("metadata->>'is_fufanmanus_default'", 'true').execute()
        
        if fufanmanus_agent_result.data:
            logger.info(f"Found FuFanManus default agent: {len(fufanmanus_agent_result.data)} agents")
            default_agent_result = fufanmanus_agent_result
        else:
            # 回退到普通默认Agent查询
            logger.info(f"No FuFanManus agent found, querying regular default agent")
            default_agent_result = await client.schema('public').table('agents').select('*').eq('user_id', user_id).eq('is_default', True).execute()
            logger.info(f"Default agent query result: found {len(default_agent_result.data) if default_agent_result.data else 0} default agents")
        
        if default_agent_result.data:
            agent_data = default_agent_result.data[0]
            logger.info(f"Found default agent: {agent_data.get('name', 'Unknown')} (ID: {agent_data.get('agent_id')})")
            
            # 使用版本系统获取当前版本（做版本控制）
            version_data = None
            if agent_data.get('current_version_id'):
                try:
                    logger.info(f"Get default agent version data: {agent_data['current_version_id']}")
                    version_service = await _get_version_service()
                    version_obj = await version_service.get_version(
                        agent_id=agent_data['agent_id'],
                        version_id=agent_data['current_version_id'],
                        user_id=user_id
                    )
                    version_data = version_obj.to_dict()
                    logger.info(f"Get default agent version data: {version_data.get('version_name')}")
                except Exception as e:
                    logger.warning(f"Get default agent version data failed: {e}")
            
            logger.info(f"Prepare to call extract_agent_config for default agent, whether there is version data: {version_data is not None}")
            
            agent_config = extract_agent_config(agent_data, version_data)
            
            if version_data:
                logger.info(f"Using default agent: {agent_config['name']} ({agent_config['agent_id']}) version {agent_config.get('version_name', 'v1')}")
            else:
                logger.info(f"Using default agent: {agent_config['name']} ({agent_config['agent_id']}) - no version data")
        else:
            logger.warning(f"User {user_id} not found default agent")
            
            # 自动创建FuFanManus默认Agent（兜底）
            logger.info(f"Creating FuFanManus default agent for user {user_id}")
            try:
                from agent.fufanmanus.repository import FufanmanusAgentRepository
                repository = FufanmanusAgentRepository()
                agent_id = await repository.create_fufanmanus_agent(user_id)
                
                if agent_id:
                    # 重新查询刚创建的默认Agent
                    default_agent_result = await client.schema('public').table('agents').select('*').eq('user_id', user_id).eq('is_default', True).execute()
                    if default_agent_result.data:
                        agent_data = default_agent_result.data[0]
                        logger.info(f"Created FuFanManus default agent: {agent_data.get('name', 'Unknown')} (ID: {agent_data.get('agent_id')})")
                        
                        # 使用版本系统获取当前版本（暂时跳过）
                        version_data = None
                        agent_config = extract_agent_config(agent_data, version_data)
                        
                        logger.info(f"Using created FuFanManus default agent: {agent_config['name']} ({agent_config['agent_id']})")
                    else:
                        logger.error(f"Failed to query created FuFanManus default agent")
                else:
                    logger.error(f"FuFanManus repository returned no agent_id")
            except Exception as e:
                logger.error(f"Failed to create FuFanManus default agent: {e}")
                # 可以考虑继续执行或抛出异常，根据业务需求决定

    if agent_config:
        logger.info(f"Agent config keys: {list(agent_config.keys())}")
        logger.info(f"Agent name: {agent_config.get('name', 'Unknown')}")
        logger.info(f"Agent ID: {agent_config.get('agent_id', 'Unknown')}")

    effective_model = model_name
    if not model_name and agent_config and agent_config.get('model'):
        effective_model = agent_config['model']
        logger.info(f"No model specified by user, using agent's configured model: {effective_model}")
    elif model_name:
        logger.info(f"Using user-selected model: {effective_model}")
    else:
        logger.info(f"Using default model: {effective_model}")
    
    agent_run = await client.schema('public').table('agent_runs').insert({
        "thread_id": thread_id,
        "status": "running",
        "started_at": datetime.now(),
        "agent_id": agent_config.get('agent_id') if agent_config else None,
        "agent_version_id": agent_config.get('current_version_id') if agent_config else None,
        "metadata": json.dumps({
            "model_name": effective_model,
            "requested_model": model_name,
            "enable_thinking": body.enable_thinking,
            "reasoning_effort": body.reasoning_effort,
            "enable_context_manager": body.enable_context_manager
        })
    })
    
    agent_run_id = str(agent_run.data[0].get('agent_run_id') or agent_run.data[0]['id'])
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
    )
    logger.info(f"Created new agent run: {agent_run_id}")

    instance_key = f"active_run:{instance_id}:{agent_run_id}"
    try:
        await redis.set(instance_key, "running", ex=redis.REDIS_KEY_TTL)
    except Exception as e:
        logger.warning(f"Failed to register agent run in Redis ({instance_key}): {str(e)}")

    request_id = structlog.contextvars.get_contextvars().get('request_id')

    logger.info(f"Start agent run: {agent_run_id}")
    logger.info(f"agent_config: {agent_config}")
    logger.info(f"model_name: {model_name}")
    logger.info(f"enable_thinking: {body.enable_thinking}")
    logger.info(f"reasoning_effort: {body.reasoning_effort}")
    logger.info(f"stream: {body.stream}")
    logger.info(f"enable_context_manager: {body.enable_context_manager}")
    logger.info(f"request_id: {request_id}")

    # 🔧 添加短暂延迟，确保前端刚发送的用户消息已经保存到数据库
    # 这解决了时序竞争问题：前端调用 /threads/{thread_id}/messages 后立即调用 /agent/start
    logger.info("Waiting briefly to ensure user message is saved to database...")
    await asyncio.sleep(0.1)  # 100ms延迟，足够数据库操作完成
    
    # 🔍 验证最新消息存在（可选的额外保险）
    try:
        events_result = await client.schema('public').table('events').select('id, timestamp').eq('session_id', thread_id).eq('author', 'user').order('timestamp', desc=True).limit(1).execute()
        if events_result.data:
            latest_message_time = events_result.data[0]['timestamp']
            logger.info(f"✅ Latest user message found: {latest_message_time}")
        else:
            logger.warning("⚠️ No user messages found in events table")
    except Exception as check_error:
        logger.warning(f"Could not verify latest message: {check_error}")

    run_agent_background.send(
        agent_run_id=agent_run_id, 
        thread_id=thread_id, 
        instance_id=instance_id,
        project_id=project_id,
        model_name=model_name,  # Already resolved above
        enable_thinking=body.enable_thinking, reasoning_effort=body.reasoning_effort,
        stream=body.stream, enable_context_manager=body.enable_context_manager,
        agent_config=agent_config,  # Pass agent configuration
        # is_agent_builder=is_agent_builder,
        # target_agent_id=target_agent_id,
        request_id=request_id,
    )

    return {"agent_run_id": agent_run_id, "status": "running"}

@router.post("/agent-run/{agent_run_id}/stop")
async def stop_agent(agent_run_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    """Stop a running agent."""
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
    )
    logger.info(f"Received request to stop agent run: {agent_run_id}")
    client = await db.client
    await get_agent_run_with_access_check(client, agent_run_id, user_id)
    await stop_agent_run(agent_run_id)
    return {"status": "stopped"}

@router.get("/thread/{thread_id}/agent-runs")
async def get_agent_runs(thread_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    """Get all agent runs for a thread."""
    print(f"🔍 ===== 查询线程Agent运行记录 =====")
    print(f"  📋 thread_id: {thread_id}")
    print(f"  👤 user_id: {user_id}")
    
    structlog.contextvars.bind_contextvars(
        thread_id=thread_id,
    )
    logger.info(f"Fetching agent runs for thread: {thread_id}")
    client = await db.client
    await verify_thread_access(client, thread_id, user_id)
    
    print(f"  🔍 查询数据库中的agent_runs记录...")
    agent_runs = await client.table('agent_runs').select('id, agent_run_id, thread_id, status, started_at, completed_at, error, created_at, updated_at').eq("thread_id", thread_id).order('created_at', desc=True).execute()
    
    print(f"  📊 查询结果: 找到 {len(agent_runs.data)} 条记录")
    for i, run in enumerate(agent_runs.data):
        print(f"    {i+1}. ID: {run.get('id')}, agent_run_id: {run.get('agent_run_id')}, 状态: {run.get('status')}, 开始时间: {run.get('started_at')}, 完成时间: {run.get('completed_at')}")
    
    # 处理返回数据，确保使用正确的ID字段
    processed_runs = []
    for run in agent_runs.data:
        processed_run = dict(run)
        # 优先使用agent_run_id，如果没有则使用id
        if processed_run.get('agent_run_id'):
            processed_run['id'] = processed_run['agent_run_id']
        processed_runs.append(processed_run)
    
    logger.debug(f"Found {len(agent_runs.data)} agent runs for thread: {thread_id}")
    print(f"🎉 ===== 查询完成 =====")
    return {"agent_runs": processed_runs}

@router.get("/agent-run/{agent_run_id}")
async def get_agent_run(agent_run_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    """Get agent run status and responses."""
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
    )
    logger.info(f"Fetching agent run details: {agent_run_id}")
    client = await db.client
    agent_run_data = await get_agent_run_with_access_check(client, agent_run_id, user_id)
    # Note: Responses are not included here by default, they are in the stream or DB
    return {
        "id": agent_run_data['id'],
        "threadId": agent_run_data['thread_id'],
        "status": agent_run_data['status'],
        "startedAt": agent_run_data['started_at'],
        "completedAt": agent_run_data['completed_at'],
        "error": agent_run_data['error']
    }

@router.get("/thread/{thread_id}/agent", response_model=ThreadAgentResponse)
async def get_thread_agent(thread_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    """Get the agent details for a specific thread. Since threads are fully agent-agnostic, 
    this returns the most recently used agent from agent_runs only."""
    structlog.contextvars.bind_contextvars(
        thread_id=thread_id,
    )
    logger.info(f"Fetching agent details for thread: {thread_id}")
    client = await db.client
    
    try:
        # Verify thread access and get thread data
        await verify_thread_access(client, thread_id, user_id)
        thread_result = await client.table('threads').select('account_id').eq('thread_id', thread_id).execute()
        
        if not thread_result.data:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        thread_data = thread_result.data[0]
        account_id = thread_data.get('account_id')
        
        effective_agent_id = None
        agent_source = "none"
        
        # Get the most recently used agent from agent_runs
        recent_agent_result = await client.table('agent_runs').select('agent_id', 'agent_version_id').eq('thread_id', thread_id).neq('agent_id', None).order('created_at', desc=True).limit(1).execute()
        if recent_agent_result.data:
            effective_agent_id = recent_agent_result.data[0]['agent_id']
            recent_version_id = recent_agent_result.data[0].get('agent_version_id')
            agent_source = "recent"
            logger.info(f"Found most recently used agent: {effective_agent_id} (version: {recent_version_id})")
        
        # If no agent found in agent_runs
        if not effective_agent_id:
            return {
                "agent": None,
                "source": "none",
                "message": "No agent has been used in this thread yet. Threads are agent-agnostic - use /agent/start to select an agent."
            }
        
        # Fetch the agent details
        agent_result = await client.table('agents').select('*').eq('agent_id', effective_agent_id).eq('user_id', user_id).execute()
        
        if not agent_result.data:
            # Agent was deleted or doesn't exist
            return {
                "agent": None,
                "source": "missing",
                "message": f"Agent {effective_agent_id} not found or was deleted. You can select a different agent."
            }
        
        agent_data = agent_result.data[0]
        
        # Use versioning system to get current version data
        version_data = None
        current_version = None
        if agent_data.get('current_version_id'):
            try:
                version_service = await _get_version_service()
                current_version_obj = await version_service.get_version(
                    agent_id=effective_agent_id,
                    version_id=agent_data['current_version_id'],
                    user_id=user_id
                )
                current_version_data = current_version_obj.to_dict()
                version_data = current_version_data
                
                # Create AgentVersionResponse from version data
                current_version = AgentVersionResponse(
                    version_id=current_version_data['version_id'],
                    agent_id=current_version_data['agent_id'],
                    version_number=current_version_data['version_number'],
                    version_name=current_version_data['version_name'],
                    system_prompt=current_version_data['system_prompt'],
                    model=current_version_data.get('model'),
                    configured_mcps=current_version_data.get('configured_mcps', []),
                    custom_mcps=current_version_data.get('custom_mcps', []),
                    agentpress_tools=current_version_data.get('agentpress_tools', {}),
                    is_active=current_version_data.get('is_active', True),
                    created_at=current_version_data['created_at'],
                    updated_at=current_version_data.get('updated_at', current_version_data['created_at']),
                    created_by=current_version_data.get('created_by')
                )
                
                logger.info(f"Using agent {agent_data['name']} version {current_version_data.get('version_name', 'v1')}")
            except Exception as e:
                logger.warning(f"Failed to get version data for agent {effective_agent_id}: {e}")
        
        version_data = None
        if current_version:
            version_data = {
                'version_id': current_version.version_id,
                'agent_id': current_version.agent_id,
                'version_number': current_version.version_number,
                'version_name': current_version.version_name,
                'system_prompt': current_version.system_prompt,
                'model': current_version.model,
                'configured_mcps': current_version.configured_mcps,
                'custom_mcps': current_version.custom_mcps,
                'agentpress_tools': current_version.agentpress_tools,
                'is_active': current_version.is_active,
                'created_at': current_version.created_at,
                'updated_at': current_version.updated_at,
                'created_by': current_version.created_by
            }
        
        from agent.config_helper import extract_agent_config
        agent_config = extract_agent_config(agent_data, version_data)
        
        system_prompt = agent_config['system_prompt']
        configured_mcps = agent_config['configured_mcps']
        custom_mcps = agent_config['custom_mcps']
        agentpress_tools = agent_config['agentpress_tools']
        
        return {
            "agent": AgentResponse(
                agent_id=agent_data['agent_id'],
                account_id=user_id,  # 使用 user_id 作为 account_id
                name=agent_data['name'],
                description=agent_data.get('description'),
                system_prompt=system_prompt,
                configured_mcps=configured_mcps,
                custom_mcps=custom_mcps,
                agentpress_tools=agentpress_tools,
                is_default=agent_data.get('is_default', False),
                is_public=agent_data.get('is_public', False),
                tags=agent_data.get('tags', []),
                avatar=agent_config.get('avatar'),
                avatar_color=agent_config.get('avatar_color'),
                profile_image_url=agent_config.get('profile_image_url'),
                created_at=agent_data['created_at'].isoformat() if isinstance(agent_data['created_at'], datetime) else str(agent_data['created_at']),
                updated_at=agent_data.get('updated_at', agent_data['created_at']).isoformat() if isinstance(agent_data.get('updated_at', agent_data['created_at']), datetime) else str(agent_data.get('updated_at', agent_data['created_at'])),
                current_version_id=agent_data.get('current_version_id'),
                version_count=agent_data.get('version_count', 1),
                current_version=current_version,
                metadata=json.loads(agent_data.get('metadata', '{}')) if isinstance(agent_data.get('metadata'), str) else agent_data.get('metadata', {})
            ),
            "source": agent_source,
            "message": f"Using {agent_source} agent: {agent_data['name']}. Threads are agent-agnostic - you can change agents anytime."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent for thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch thread agent: {str(e)}")

@router.get("/agent-run/{agent_run_id}/stream")
async def stream_agent_run(
    agent_run_id: str,
    token: Optional[str] = None,
    request: Request = None
):
    """Stream the responses of an agent run using Redis Lists and Pub/Sub."""
    print(f"🚀 ===== 流式输出接口开始 =====")
    print(f"  📋 agent_run_id: {agent_run_id}")
    print(f"  🔑 token: {token[:10] if token else 'None'}...")
    print(f"  🌐 request: {request}")
    
    print(f"Starting stream for agent run: {agent_run_id}")
    client = await db.client

    print(f"  🔐 开始用户身份验证...")
    user_id = await get_user_id_from_stream_auth(request, token) # 瞬时验证
    print(f"  ✅ 用户身份验证完成: {user_id}")
    
    print(f"  🔍 开始检查agent_run访问权限...")
    agent_run_data = await get_agent_run_with_access_check(client, agent_run_id, user_id) # 1 db query
    print(f"  ✅ agent_run数据获取完成: {agent_run_data}")

    # 结构化日志上下文，将 agent_run_id 和 user_id 绑定到当前请求的上下文中，后续的所有日志记录都会自动包含这些信息
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
        user_id=user_id,
    )

    # 定义Redis中的键名，用于流式输出的数据存储和通信
    response_list_key = f"agent_run:{agent_run_id}:responses"  # Redis List 键名，存储 agent_run 的所有响应数据
    response_channel = f"agent_run:{agent_run_id}:new_response" # Redis Pub/Sub 频道名，用于通知新响应到达
    control_channel = f"agent_run:{agent_run_id}:control" # edis Pub/Sub 频道名，用于控制信号，比如发送停止、暂停、错误、管理流式输出的生命周期
    

    async def stream_generator(agent_run_data):
        print(f"   ===== 流式生成器开始 =====")
        print(f"Streaming responses for {agent_run_id} using Redis list {response_list_key} and channel {response_channel}")
        last_processed_index = -1
        pubsub_response = None
        pubsub_control = None
        listener_task = None
        terminate_stream = False
        initial_yield_complete = False

        try:
            # 1. 捕获 Redis List 中的初始响应，并发送给前端
            # 目的：前端重连时，能获取到之前错过的响应
            print(f"  📥 步骤1: 获取Redis中的初始响应...")
            initial_responses_json = await redis.lrange(response_list_key, 0, -1)
            print(f"  📊 Redis中初始响应数量: {len(initial_responses_json) if initial_responses_json else 0}")
            
            initial_responses = []
            if initial_responses_json:
                initial_responses = [json.loads(r) for r in initial_responses_json]
                print(f"  📤 发送 {len(initial_responses)} 个初始响应给前端")
                for i, response in enumerate(initial_responses):
                    response_str = f"data: {json.dumps(response)}\n\n"
                    print(f"    [{i+1}] 发送响应: {response}")
                    yield response_str
                last_processed_index = len(initial_responses) - 1
                print(f"  ✅ 初始响应发送完成，最后处理索引: {last_processed_index}")
            else:
                print(f"  ℹ️ Redis中没有初始响应")
            
            initial_yield_complete = True

            # 2. 状态检查
            # 目的：避免对已完成的agent_run进行不必要的监听
            print(f"  🔍 步骤2: 检查agent_run状态...")
            current_status = agent_run_data.get('status') if agent_run_data else None
            print(f"  📊 当前状态: {current_status}")

            # 如果agent_run状态不是running，则直接返回完成状态
            if current_status != 'running':
                print(f"  ⚠️ Agent run {agent_run_id} 不在运行状态 (status: {current_status})，结束流式输出")
                logger.info(f"Agent run {agent_run_id} is not running (status: {current_status}). Ending stream.")
                completion_message = {'type': 'status', 'status': 'completed'}
                print(f"  📤 发送完成状态: {completion_message}")
                yield f"data: {json.dumps(completion_message)}\n\n"
                return
          
            print(f"  ✅ Agent run正在运行，继续流式输出")
            structlog.contextvars.bind_contextvars(
                thread_id=agent_run_data.get('thread_id'),
            )

            # 3. 设置 Pub/Sub 监听器，用于接收新响应和控制信号
            # 目的：建立实时监听，监听 Redis 中的新响应和控制信号，并将其传递给流式生成器
            print(f"  📡 步骤3: 设置Pub/Sub监听器...")
            pubsub_response_task = asyncio.create_task(redis.create_pubsub())
            pubsub_control_task = asyncio.create_task(redis.create_pubsub())
            
            pubsub_response, pubsub_control = await asyncio.gather(pubsub_response_task, pubsub_control_task)
            print(f"  ✅ Pub/Sub客户端创建完成")
            
            # Subscribe to channels concurrently
            response_subscribe_task = asyncio.create_task(pubsub_response.subscribe(response_channel))
            control_subscribe_task = asyncio.create_task(pubsub_control.subscribe(control_channel))
            
            await asyncio.gather(response_subscribe_task, control_subscribe_task)
            print(f"  ✅ 订阅频道完成: {response_channel}, {control_channel}")
            
            logger.debug(f"Subscribed to response channel: {response_channel}")
            logger.debug(f"Subscribed to control channel: {control_channel}")

            # Queue to communicate between listeners and the main generator loop
            message_queue = asyncio.Queue()
            print(f"  📨 消息队列创建完成")

            # 消息处理循环
            async def listen_messages():
                print(f"  👂 ===== 消息监听器开始 =====")
                response_reader = pubsub_response.listen()
                control_reader = pubsub_control.listen()
                tasks = [asyncio.create_task(response_reader.__anext__()), asyncio.create_task(control_reader.__anext__())]
                print(f"  📡 监听器任务创建完成")

                while not terminate_stream:
                    print(f"  🔄 等待消息...")
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        try:
                            message = task.result()
                            print(f"  📨 收到消息: {message}")
                            if message and isinstance(message, dict) and message.get("type") == "message":
                                channel = message.get("channel")
                                data = message.get("data")
                                if isinstance(data, bytes): data = data.decode('utf-8')
                                print(f"  📡 频道: {channel}, 数据: {data}")

                                if channel == response_channel and data == "new":
                                    print(f"  🔔 收到新响应通知")
                                    await message_queue.put({"type": "new_response"})
                                elif channel == control_channel and data in ["STOP", "END_STREAM", "ERROR"]:
                                    print(f"  🛑 收到控制信号: {data}")
                                    logger.info(f"Received control signal '{data}' for {agent_run_id}")
                                    await message_queue.put({"type": "control", "data": data})
                                    return # Stop listening on control signal

                        except StopAsyncIteration:
                            print(f"  ⚠️ 监听器 {task} 停止")
                            logger.warning(f"Listener {task} stopped.")
                            # Decide how to handle listener stopping, maybe terminate?
                            await message_queue.put({"type": "error", "data": "Listener stopped unexpectedly"})
                            return
                        except Exception as e:
                            print(f"  ❌ 监听器错误: {e}")
                            logger.error(f"Error in listener for {agent_run_id}: {e}")
                            await message_queue.put({"type": "error", "data": "Listener failed"})
                            return
                        finally:
                            # Reschedule the completed listener task
                            if task in tasks:
                                tasks.remove(task)
                                if message and isinstance(message, dict) and message.get("channel") == response_channel:
                                     tasks.append(asyncio.create_task(response_reader.__anext__()))
                                elif message and isinstance(message, dict) and message.get("channel") == control_channel:
                                     tasks.append(asyncio.create_task(control_reader.__anext__()))

                # Cancel pending listener tasks on exit
                print(f"  🛑 取消待处理的监听器任务")
                for p_task in pending: p_task.cancel()
                for task in tasks: task.cancel()


            listener_task = asyncio.create_task(listen_messages())
            print(f"  ✅ 监听器任务启动完成")

            # 4. Main loop to process messages from the queue
            print(f"  🔄 ===== 主循环开始 =====")
            while not terminate_stream:
                try:
                    print(f"  📨 等待队列消息...")
                    queue_item = await message_queue.get()
                    print(f"  📥 收到队列消息: {queue_item}")
                    if queue_item["type"] == "new_response":
                        print(f"  📤 处理新响应...")
                        # 获取新响应并发送给前端
                        new_start_index = last_processed_index + 1
                        print(f"  📍 从索引 {new_start_index} 开始获取新响应")
                        new_responses_json = await redis.lrange(response_list_key, new_start_index, -1)
                        print(f"  📊 获取到 {len(new_responses_json) if new_responses_json else 0} 个新响应")

                        if new_responses_json:
                            new_responses = [json.loads(r) for r in new_responses_json]
                            num_new = len(new_responses)
                            print(f"  📤 发送 {num_new} 个新响应给前端")
                            # logger.debug(f"Received {num_new} new responses for {agent_run_id} (index {new_start_index} onwards)")
                            for i, response in enumerate(new_responses):
                                response_str = f"data: {json.dumps(response)}\n\n"
                                print(f"    [{i+1}] 发送响应: {response}")
                                yield response_str
                                # Check if this response signals completion
                                if response.get('type') == 'status' and response.get('status') in ['completed', 'failed', 'stopped']:
                                    print(f"  🎯 检测到运行完成状态: {response.get('status')}")
                                    logger.info(f"Detected run completion via status message in stream: {response.get('status')}")
                                    terminate_stream = True
                                    break # Stop processing further new responses
                            last_processed_index += num_new
                            print(f"  ✅ 新响应处理完成，最后处理索引: {last_processed_index}")
                        else:
                            print(f"  ℹ️ 没有新响应")
                        if terminate_stream: 
                            print(f"  🛑 流式输出终止")
                            break

                    elif queue_item["type"] == "control":
                        control_signal = queue_item["data"]
                        print(f"  🛑 收到控制信号: {control_signal}")
                        terminate_stream = True # Stop the stream on any control signal
                        control_message = {'type': 'status', 'status': control_signal}
                        print(f"  📤 发送控制状态: {control_message}")
                        yield f"data: {json.dumps(control_message)}\n\n"
                        break

                    elif queue_item["type"] == "error":
                        print(f"  ❌ 监听器错误: {queue_item['data']}")
                        logger.error(f"Listener error for {agent_run_id}: {queue_item['data']}")
                        terminate_stream = True
                        error_message = {'type': 'status', 'status': 'error'}
                        print(f"  📤 发送错误状态: {error_message}")
                        yield f"data: {json.dumps(error_message)}\n\n"
                        break

                except asyncio.CancelledError:
                     print(f"  🛑 流式生成器主循环被取消")
                     logger.info(f"Stream generator main loop cancelled for {agent_run_id}")
                     terminate_stream = True
                     break
                except Exception as loop_err:
                    print(f"  ❌ 流式生成器主循环错误: {loop_err}")
                    logger.error(f"Error in stream generator main loop for {agent_run_id}: {loop_err}", exc_info=True)
                    terminate_stream = True
                    error_message = {'type': 'status', 'status': 'error', 'message': f'Stream failed: {loop_err}'}
                    print(f"  📤 发送错误状态: {error_message}")
                    yield f"data: {json.dumps(error_message)}\n\n"
                    break

        except Exception as e:
            print(f"  ❌ 设置流式输出时发生错误: {e}")
            logger.error(f"Error setting up stream for agent run {agent_run_id}: {e}", exc_info=True)
            # Only yield error if initial yield didn't happen
            if not initial_yield_complete:
                 error_message = {'type': 'status', 'status': 'error', 'message': f'Failed to start stream: {e}'}
                 print(f"  📤 发送启动错误状态: {error_message}")
                 yield f"data: {json.dumps(error_message)}\n\n"
        finally:
            print(f"  🧹 ===== 清理资源 =====")
            terminate_stream = True
            # Graceful shutdown order: unsubscribe → close → cancel
            if pubsub_response: 
                print(f"  📡 取消订阅响应频道")
                await pubsub_response.unsubscribe(response_channel)
            if pubsub_control: 
                print(f"  📡 取消订阅控制频道")
                await pubsub_control.unsubscribe(control_channel)
            if pubsub_response: 
                print(f"  📡 关闭响应Pub/Sub连接")
                await pubsub_response.close()
            if pubsub_control: 
                print(f"  📡 关闭控制Pub/Sub连接")
                await pubsub_control.close()

            if listener_task:
                print(f"  🛑 取消监听器任务")
                listener_task.cancel()
                try:
                    await listener_task  # Reap inner tasks & swallow their errors
                except asyncio.CancelledError:
                    print(f"  ✅ 监听器任务已取消")
                    pass
                except Exception as e:
                    print(f"  ⚠️ 监听器任务结束时有错误: {e}")
                    logger.debug(f"listener_task ended with: {e}")
            # Wait briefly for tasks to cancel
            await asyncio.sleep(0.1)
            print(f"  ✅ 流式输出清理完成")
            logger.debug(f"Streaming cleanup complete for agent run: {agent_run_id}")

    print(f"  开始创建StreamingResponse...")
    return StreamingResponse(stream_generator(agent_run_data), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "Connection": "keep-alive",
        "X-Accel-Buffering": "no", "Content-Type": "text/event-stream",
        "Access-Control-Allow-Origin": "*"
    })

async def generate_and_update_project_name(project_id: str, prompt: str):
    """Generates a project name using an LLM and updates the database."""
    logger.info(f"Starting background task to generate name for project: {project_id}")
    # TODO
    pass
    
@router.post("/agent/initiate", response_model=InitiateAgentResponse)
async def initiate_agent_with_files(
    prompt: str = Form(...),  
    model_name: Optional[str] = Form(None),  
    enable_thinking: Optional[bool] = Form(False),  
    reasoning_effort: Optional[str] = Form("low"),  
    stream: Optional[bool] = Form(True),  
    enable_context_manager: Optional[bool] = Form(False),
    agent_id: Optional[str] = Form(None), 
    files: List[UploadFile] = File(default=[]),
    is_agent_builder: Optional[bool] = Form(False),
    target_agent_id: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """
    启动一个新的Agent会话,支持可选的文件附件
    
    参数说明:
    - prompt: 用户输入的提示词
    - model_name: 使用的模型名称(如果为None则使用配置中的默认模型)
    - enable_thinking: 是否启用思考模式
    - reasoning_effort: 推理程度(low/medium/high)
    - stream: 是否启用流式响应
    - enable_context_manager: 是否启用上下文管理器
    - agent_id: 指定的Agent ID(可选)
    - files: 上传的文件列表
    - is_agent_builder: 是否为Agent构建器模式
    - target_agent_id: 目标Agent ID(在构建器模式下使用)
    - user_id: 当前用户ID(从JWT中获取)
    """

    # 提取前端传递的参数
    logger.info(f"Starting new agent session with prompt: {prompt}")
    logger.info(f"Starting new agent session with model name: {model_name}")

    # 打印文件详细信息
    for i, file in enumerate(files):
        logger.info(f"Upload Files {i+1}: {file.filename} (size: {file.size if hasattr(file, 'size') else 'unknown'} bytes, type: {file.content_type})")
    
    global instance_id

    logger.info(f"Current instance_id: {instance_id}")
    if not instance_id:
        logger.error("Agent API not initialized with instance ID")
        raise HTTPException(status_code=500, detail="Agent API not initialized with instance ID")

    logger.info(f"Processing model name: {model_name}")

    # 2. 格式化需要使用的模型名称
    # 如果前端没有传递模型名称，则使用配置中的默认模型
    if model_name is None:
        model_name = config.MODEL_TO_USE
        logger.info(f"No model name provided, using default model: {model_name}")

    # 处理模型名称，使其适配 LiteLLM 的模型定义规范， 如 deepseek-r1 → deepseek/deepseek-r1  claude-4-sonnet → anthropic/claude-4-sonnet gpt-5 → openai/gpt-5
    resolved_model = MODEL_NAME_ALIASES.get(model_name, model_name)
    # 更新model_name为解析后的版本
    model_name = resolved_model

    # 初始化数据库连接
    client = await db.client
    logger.info(f"Database connection successful, account_id: {user_id}")
    
    # 4: TODO：加载Agent配置（支持版本管理，注：此版本还未实现）
    agent_config = None
    logger.info(f"Requested agent_id: {agent_id}")

    if agent_id:
        # 加载自主创建 Agent 及配置管理（可以通过 agent_id 来加载自主创建的配置）
        logger.info(f"[AGENT INITIATE] Querying for specific agent: {agent_id}")
        # 获取 Agent 实例对象
        agent_result = await client.table('agents').select('*').eq('agent_id', agent_id).eq('user_id', user_id).execute()
        logger.info(f"[AGENT INITIATE] Query result: found {len(agent_result.data) if agent_result.data else 0} agents")
        
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found or access denied")
        
        agent_data = agent_result.data[0]
        logger.info(f"[AGENT INITIATE] Agent data: {agent_data}")
        
        # 使用版本管理系统获取当前版本
        version_data = None
        if agent_data.get('current_version_id'):
            try:
                version_service = await _get_version_service()
                version_obj = await version_service.get_version(
                    agent_id=agent_id,
                    version_id=agent_data['current_version_id'],
                    user_id=user_id
                )
                version_data = version_obj.to_dict()
                logger.info(f"[AGENT INITIATE] Got version data from version manager: {version_data.get('version_name')}")
                logger.info(f"[AGENT INITIATE] Version data: {version_data}")
            except Exception as e:
                logger.warning(f"[AGENT INITIATE] Failed to get version data: {e}")
        
        logger.info(f"[AGENT INITIATE] About to call extract_agent_config with version data: {version_data is not None}")
        
        agent_config = extract_agent_config(agent_data, version_data)
        logger.info(f"agent_config: {agent_config}")
        if version_data:
            logger.info(f"Using custom agent: {agent_config['name']} ({agent_id}) version {agent_config.get('version_name', 'v1')}")
        else:
            logger.info(f"Using custom agent: {agent_config['name']} ({agent_id}) - no version data")
    else:
        logger.info(f"No agent_id provided, querying default agent")
        # 优先查找FuFanManus默认Agent，如果没有再查找普通默认Agent
        # 这里查找的逻辑是可以把自定义的Agent设置成默认，如果有，则加载指定的默认Agent
        fufanmanus_agent_result = await client.table('agents').select('*').eq('user_id', user_id).eq("metadata->>'is_fufanmanus_default'", 'true').execute()
        
        if fufanmanus_agent_result.data:
            logger.info(f"Found FuFanManus default agent: {len(fufanmanus_agent_result.data)} agents")
            default_agent_result = fufanmanus_agent_result
        else:
            # 回退到普通默认Agent查询
            logger.info(f"No FuFanManus agent found, querying regular default agent")
            default_agent_result = await client.schema('public').table('agents').select('*').eq('user_id', user_id).eq('is_default', True).execute()
            logger.info(f"Default agent query result: found {len(default_agent_result.data) if default_agent_result.data else 0} default agents")
        
        if default_agent_result.data:
            agent_data = default_agent_result.data[0]
            logger.info(f"Found default agent: {agent_data.get('name', 'Unknown')} (ID: {agent_data.get('agent_id')})")
            
            # 使用版本系统获取当前版本（做版本控制）
            version_data = None
            if agent_data.get('current_version_id'):
                try:
                    logger.info(f"Get default agent version data: {agent_data['current_version_id']}")
                    version_service = await _get_version_service()
                    version_obj = await version_service.get_version(
                        agent_id=agent_data['agent_id'],
                        version_id=agent_data['current_version_id'],
                        user_id=user_id
                    )
                    version_data = version_obj.to_dict()
                    logger.info(f"Get default agent version data: {version_data.get('version_name')}")
                except Exception as e:
                    logger.warning(f"Get default agent version data failed: {e}")
            
            logger.info(f"Prepare to call extract_agent_config for default agent, whether there is version data: {version_data is not None}")
            
            agent_config = extract_agent_config(agent_data, version_data)
            
            if version_data:
                logger.info(f"Using default agent: {agent_config['name']} ({agent_config['agent_id']}) version {agent_config.get('version_name', 'v1')}")
            else:
                logger.info(f"Using default agent: {agent_config['name']} ({agent_config['agent_id']}) - no version data")
        else:
            logger.warning(f"User {user_id} not found default agent")
            
            # 自动创建FuFanManus默认Agent（兜底）
            logger.info(f"Creating FuFanManus default agent for user {user_id}")
            try:
                from agent.fufanmanus.repository import FufanmanusAgentRepository
                repository = FufanmanusAgentRepository()
                agent_id = await repository.create_fufanmanus_agent(user_id)
                
                if agent_id:
                    # 重新查询刚创建的默认Agent
                    default_agent_result = await client.schema('public').table('agents').select('*').eq('user_id', user_id).eq('is_default', True).execute()
                    if default_agent_result.data:
                        agent_data = default_agent_result.data[0]
                        logger.info(f"Created FuFanManus default agent: {agent_data.get('name', 'Unknown')} (ID: {agent_data.get('agent_id')})")
                        
                        # 使用版本系统获取当前版本（暂时跳过）
                        version_data = None
                        agent_config = extract_agent_config(agent_data, version_data)
                        
                        logger.info(f"Using created FuFanManus default agent: {agent_config['name']} ({agent_config['agent_id']})")
                    else:
                        logger.error(f"Failed to query created FuFanManus default agent")
                else:
                    logger.error(f"FuFanManus repository returned no agent_id")
            except Exception as e:
                logger.error(f"Failed to create FuFanManus default agent: {e}")
                # 可以考虑继续执行或抛出异常，根据业务需求决定

    if agent_config:
        logger.info(f"Agent config keys: {list(agent_config.keys())}")
        logger.info(f"Agent name: {agent_config.get('name', 'Unknown')}")
        logger.info(f"Agent ID: {agent_config.get('agent_id', 'Unknown')}")

    # 步骤5: 执行权限和限制检查
    logger.info(f"Executing permissions and limit checks")
    
    # TODO：这里可以添加模型检查，比如模型是否支持访问，用户是否有模型使用权限等，在业务层前做检查
    # 如下是一系列的检查操作：比如
    # 模型连通性：model connectivity check
    # 模型使用权限：model access permission check
    # 模型使用限制：model usage limit check
    # 模型使用计费：model usage billing check
    # 模型使用日志：model usage logging check
    # 模型使用监控：model usage monitoring check
    # 模型使用分析：model usage analysis check

    try:
        # 5. 创建项目并生成项目ID,并插入到数据库中。注意：此操作仅用于初始化占位符
        placeholder_name = f"{prompt[:30]}..." if len(prompt) > 30 else prompt if prompt else "new conversation"
        
        project_id = str(uuid.uuid4())

        # 插入项目数据到数据库中
        project = await client.schema('public').table('projects').insert({
            "project_id": project_id, 
            "account_id": user_id, 
            "name": placeholder_name,
            "created_at": datetime.now()
        })
        
        if not project.data:
            logger.error(f"Failed to create project")
            raise Exception("Failed to create project")

        # 创建沙盒（懒加载）：只有在文件上传时才立即创建
        logger.info("Staring Creating sandbox environment")

        # 定义变量
        sandbox_id = None
        sandbox = None
        sandbox_pass = None
        vnc_url = None
        website_url = None
        token = None

        if files:
            logger.info(f"Found {len(files)} files, starting to create sandbox")
            try:
                logger.info("Starting to create sandbox...")
                sandbox_pass = str(uuid.uuid4())
                logger.info(f"Generated sandbox password: {sandbox_pass}")
                
                # 根据文件类型和用户需求智能选择模板
                sandbox_type = determine_sandbox_type(files)
                logger.info(f"Determined sandbox type: {sandbox_type}")
                sandbox = await create_sandbox(sandbox_pass, project_id, sandbox_type)

                # 获取沙箱ID
                sandbox_info = sandbox.get_info()
                sandbox_id = sandbox_info.sandbox_id if hasattr(sandbox_info, 'sandbox_id') else getattr(sandbox, 'id', 'unknown')
                logger.info(f"Created sandbox successfully: {sandbox_id} (project: {project_id}, type: {sandbox_type})")

                # 获取访问链接
                logger.info("Getting sandbox access links...")
                
                # 判断沙箱类型并获取对应的访问链接
                sandbox_name = getattr(sandbox_info, 'name', '')
                logger.info(f"Detected sandbox name: {sandbox_name}")
                
                vnc_url = ''
                website_url = ''
                browser_debug_url = ''
                
                if sandbox_name == 'desktop':
                    #  Desktop 模板 - 使用 stream API 获取 VNC URL
                    try:
                        logger.info("Using desktop stream API to get VNC URL...")
                        url = sandbox.stream.get_url()
                        vnc_url = url
                        logger.info(f"Desktop VNC URL: {url}")
                        # 尝试获取只读模式URL
                        try:
                            readonly_url = sandbox.stream.get_url(view_only=True)
                            logger.info(f"Desktop readonly VNC URL: {readonly_url}")
                        except Exception as readonly_error:
                            logger.debug(f"Failed to get readonly URL: {readonly_error}")
                            
                    except Exception as e:
                        logger.error(f"Failed to get desktop VNC URL: {e}")
  
                # TODO
                elif sandbox_name == 'browser-chromium' or sandbox_type == 'browser':
                    # 🌐 Browser 模板 - 获取 Chrome 调试协议地址
                    try:
                        browser_host = sandbox.get_host(9223)
                        browser_debug_url = f"https://{browser_host}"
                        logger.info(f"Browser CDP URL: {browser_debug_url}")
                    except Exception as e:
                        logger.error(f"Failed to get browser CDP URL: {e}")
                
                # 更新项目信息
                logger.info("Updating project sandbox information...")
                update_result = await client.table('projects').eq('project_id', project_id).update({
                    'sandbox': json.dumps({
                        'id': sandbox_id, 
                        'pass': sandbox_pass, 
                        'vnc_preview': vnc_url,
                        'sandbox_url': website_url, 
                        'token': token
                    })
                })

                if not update_result.data:
                    logger.error(f"Failed to update project {project_id} sandbox information")
                    if sandbox_id:
                        try: 
                            # TODO
                            await delete_sandbox(sandbox_id)
                            logger.info(f"Deleted sandbox {sandbox_id}")
                        except Exception as e: 
                            logger.error(f"Failed to delete sandbox: {str(e)}")
                    raise Exception("Database update failed")
                    
                logger.info("Project sandbox information updated successfully")
                
            except Exception as e:
                logger.error(f"Failed to create sandbox: {str(e)}")
                logger.info("Cleaning up created project...")
                await client.table('projects').eq('project_id', project_id).delete()
                if sandbox_id:
                    try: 
                        # TODO
                        await delete_sandbox(sandbox_id)
                        logger.info(f"Deleted sandbox {sandbox_id}")
                    except Exception:
                        pass
                raise Exception("Failed to create sandbox")
        else:
            logger.info("No files uploaded, skipping sandbox creation")

        # 6. 创建线程（thread_id）并做关联
        thread_id = str(uuid.uuid4())
        logger.info(f"Generated New thread ID: {thread_id}")
        
        # 构建关联关系：user_id -> project_id -> thread_id
        thread_data = {
            "thread_id": thread_id, 
            "project_id": project_id, 
            "account_id": user_id,
            "created_at": datetime.now()
        }

        # 绑定上下文变量，用于在日志中追踪相关信息
        structlog.contextvars.bind_contextvars(
            thread_id=thread_data["thread_id"],
            project_id=project_id,
            account_id=user_id,
        )
        
        # 线程是Agent无关的，不存储agent_id
        # Agent选择将在每个消息/Agent运行时处理
        if agent_config:
            logger.info(f"Using Agent {agent_config['agent_id']} for conversation (thread remains Agent-agnostic)")
            structlog.contextvars.bind_contextvars(
                agent_id=agent_config['agent_id'],
            )
        
        # # 如果是Agent构建器会话，存储构建器元数据
        if is_agent_builder:
            print(f"store agent builder metadata: target_agent_id={target_agent_id}")
            thread_data["metadata"] = {
                "is_agent_builder": True,
                "target_agent_id": target_agent_id
            }
            structlog.contextvars.bind_contextvars(
                target_agent_id=target_agent_id,
            )
        
        # 插入线程到数据库
        thread = await client.schema('public').table('threads').insert(thread_data)
        
        if not thread.data:
            logger.error(f"Failed to create thread")
            raise Exception("Failed to create thread")
            

        # 在创建新的Agent会话时异步触发，通过大模型生成更贴合主题的会话名称 
        # TODO：可选。这里可以添加一个任务，通过大模型生成更贴合主题的会话名称，并更新到项目中
        asyncio.create_task(generate_and_update_project_name(project_id=project_id, prompt=prompt))

        message_content = prompt    
        # 处理上传文件到沙盒环境（如果有）
        if files:
            logger.info(f"Start uploading {len(files)} files to sandbox...")
            successful_uploads = []
            failed_uploads = []
            
            for i, file in enumerate(files):
                logger.info(f"Processing file {i+1}/{len(files)}: {file.filename}")
                
                if file.filename:
                    try:
                        safe_filename = file.filename.replace('/', '_').replace('\\', '_')
                        target_path = f"/workspace/{safe_filename}"
                        logger.info(f"files target_path: {target_path}")
                        logger.info(f"files size: {file.size if hasattr(file, 'size') else '未知'} bytes")
                        
                        content = await file.read()
                        logger.info(f"files read success, size: {len(content)} bytes")
                        
                        upload_successful = False
                        try:
                            # 使用 PPIO 推荐的方法: sandbox.files.write()
                            if hasattr(sandbox, 'files') and hasattr(sandbox.files, 'write'):
                                logger.info(f"Uploading file to sandbox: {target_path}")
                                # 根据 PPIO 官方文档，files.write() 是同步方法，不需要 await
                                write_result = sandbox.files.write(target_path, content)
                                logger.info(f"File uploaded successfully: {target_path}")
                                upload_successful = True            
                            else:
                                logger.error(f"Sandbox object missing file upload method")
                                raise NotImplementedError("No suitable upload method found on sandbox object.")
                                
                        except Exception as upload_error:
                            logger.error(f"Sandbox upload failed {safe_filename}: {str(upload_error)}")
                            logger.debug(f"Sandbox upload error details: {upload_error}")  # 使用 debug 记录详细错误

                        if upload_successful:
                            try:
                                logger.info(f"Verifying file upload...")
                                await asyncio.sleep(0.2)
                                parent_dir = os.path.dirname(target_path)
                                
                                # 使用 PPIO 正确的 API 验证文件
                                if hasattr(sandbox, 'files') and hasattr(sandbox.files, 'exists'):
                                    # 检查文件是否存在
                                    file_exists = sandbox.files.exists(target_path)
                                    if file_exists:
                                        successful_uploads.append(target_path)
                                        logger.info(f"File uploaded and verified successfully: {safe_filename} -> {target_path}")
                                    else:
                                        logger.error(f"File verification failed: {target_path} does not exist")
                                        failed_uploads.append(safe_filename)
                                else:
                                    # 如果没有 exists 方法，直接标记为成功（已经成功上传了）
                                    successful_uploads.append(target_path)
                                    logger.info(f"File uploaded successfully (skip verification): {safe_filename} -> {target_path}")
                                    
                            except Exception as verify_error:
                                # 验证失败不影响上传，标记为成功
                                successful_uploads.append(target_path)
                                logger.warning(f"File verification failed but upload was successful {safe_filename}: {str(verify_error)}")
                                logger.debug(f"File verification error details: {verify_error}")  # 使用 debug 避免 exc_info 问题
                        else:
                            failed_uploads.append(safe_filename)
                    except Exception as file_error:
                        logger.error(f"File processing failed {file.filename}: {str(file_error)}")
                        logger.debug(f"File processing error details: {file_error}")  # 使用 debug 记录详细错误
                        failed_uploads.append(file.filename)
                    finally:
                        await file.close()
                        logger.info(f"File closed: {file.filename}")

            # 更新消息内容
            if successful_uploads:
                message_content += "\n\n" if message_content else ""
                for file_path in successful_uploads: 
                    message_content += f"[用户上传文件: {file_path}]\n"
                logger.info(f"File uploaded successfully: {len(successful_uploads)} files")
                
            if failed_uploads:
                message_content += "\n\nThe following files failed to upload:\n"
                for failed_file in failed_uploads: 
                    message_content += f"- {failed_file}\n"
                logger.warning(f"File upload failed: {len(failed_uploads)} files")
                
            logger.info(f"Final message content: {message_content}")
        else:
            logger.info("No files to upload")
 
        # 添加初始用户消息到线程
        message_payload = {"role": "user", "content": message_content}
        logger.info(f"New Message payload: {message_payload}")
        
        # 在ADK架构中，使用thread_id作为session_id
        adk_session_id = thread_id
        
        # 创建ADK session（如果不存在）
        await _create_adk_session_if_not_exists(client, user_id, adk_session_id)
        logger.info(f"Created ADK session successfully: {adk_session_id}")

        # # 使用ADK events表记录消息
        message_id = str(uuid.uuid4())
        await _log_adk_user_message_event(client, user_id, message_content, adk_session_id, message_id)
        logger.info(f"User message event recorded successfully: {message_id}")
        
        # 确定最终使用的模型
        # 模型选择的优先级逻辑
        # model_name ：用户在前端选择的模型
        # agent_config.model ：用户在Agent配置中选择的模型
        # MODEL_NAME_ALIASES，即config.MODEL_TO_USE，模型别名映射，在.ENV 文件中获取

        # 优先级：用户在前端选择的模型 > Agent配置中选择的模型 > 模型别名映射
        # 如果用户在前端选择的模型在MODEL_NAME_ALIASES中存在，则使用MODEL_NAME_ALIASES中的模型
        # 如果用户在前端选择的模型在MODEL_NAME_ALIASES中不存在，则使用用户在前端选择的模型
        # 如果用户在Agent配置中选择的模型在MODEL_NAME_ALIASES中存在，则使用MODEL_NAME_ALIASES中的模型
        effective_model = model_name
        if not model_name and agent_config and agent_config.get('model'):
            effective_model = agent_config['model']
            logger.info(f"User did not specify model, using Agent configured model: {effective_model}")
        elif model_name:
            logger.info(f"Using user selected model: {effective_model}")
        else:
            logger.info(f"Using default model: {effective_model}")
        
        # 完成模型别名解析，适配 LiteLLM 的规范
        resolved_model = MODEL_NAME_ALIASES.get(effective_model, effective_model)
        logger.info(f"Model alias resolved: {effective_model} -> {resolved_model}")
        
        # 8. 创建Agent运行记录的元数据
        agent_run_metadata = {
            "model_name": resolved_model,  # 使用解析后的模型名
            "requested_model": model_name,  # 保留用户原始请求
            "enable_thinking": enable_thinking,
            "reasoning_effort": reasoning_effort,
            "enable_context_manager": enable_context_manager
        }
        logger.info(f"Agent run metadata: {agent_run_metadata}")
        
        # 存储Agent运行记录到数据库中
        agent_run = await client.schema('public').table('agent_runs').insert({
            "thread_id": thread_id, 
            "status": "running",
            "started_at": datetime.now(),
            "agent_id": agent_config.get('agent_id') if agent_config else None,
            "agent_version_id": agent_config.get('current_version_id') if agent_config else None,
            "metadata": json.dumps(agent_run_metadata)
        })
        
        if not agent_run.data:
            logger.error(f"Failed to create agent run")
            raise Exception("Failed to create agent run")
            
        agent_run_id = str(agent_run.data[0].get('agent_run_id') or agent_run.data[0]['id'])
        logger.info(f"Created agent run ids: {agent_run_id}")
        
        # 绑定Agent运行ID到上下文，用于在日志中追踪相关信息
        structlog.contextvars.bind_contextvars(
            agent_run_id=agent_run_id,
        )

        # 9. 在Redis中注册运行
        instance_key = f"active_run:{instance_id}:{agent_run_id}"
        try:
            await redis.set(instance_key, "running", ex=redis.REDIS_KEY_TTL)
            logger.info(f"Redis registered successfully: {instance_key}")
        except Exception as e:
            logger.error(f"Redis registered failed ({instance_key}): {str(e)}")

        # 获取请求ID并启动后台Agent
        request_id = structlog.contextvars.get_contextvars().get('request_id')
        logger.info(f"Request ID: {request_id}")

        # 11. 发送Agent运行任务到后台，这里才是真正开始执行Agent的逻辑
        # 注意：这里不需要传递用户的请求，因为需要在后续的处理中通过查询数据库来获取
        try:
            message = run_agent_background.send(
                agent_run_id=agent_run_id, 
                thread_id=thread_id, 
                instance_id=instance_id,
                project_id=project_id,
                model_name=resolved_model, 
                enable_thinking=enable_thinking, 
                reasoning_effort=reasoning_effort,
                stream=stream, 
                enable_context_manager=enable_context_manager,
                agent_config=agent_config,  
                is_agent_builder=is_agent_builder,
                target_agent_id=target_agent_id,
                request_id=request_id,
            )
            logger.info(f"Agent run task sent to background, message ID: {message.message_id}")
        except Exception as send_error:
            logger.error(f"Failed to send background task: {send_error}")

        return {"thread_id": thread_id, "agent_run_id": agent_run_id}

    except Exception as e:
        logger.error(f"Error in agent initiation: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to initiate agent session: {str(e)}")

# Custom agents
@router.get("/agents", response_model=AgentsResponse)
async def get_agents(
    user_id: str = Depends(get_current_user_id_from_jwt),
    page: Optional[int] = Query(1, ge=1, description="Page number (1-based)"),
    limit: Optional[int] = Query(20, ge=1, le=100, description="Number of items per page"),
    search: Optional[str] = Query(None, description="Search in name and description"),
    sort_by: Optional[str] = Query("created_at", description="Sort field: name, created_at, updated_at, tools_count"),
    sort_order: Optional[str] = Query("desc", description="Sort order: asc, desc"),
    has_default: Optional[bool] = Query(None, description="Filter by default agents"),
    has_mcp_tools: Optional[bool] = Query(None, description="Filter by agents with MCP tools"),
    has_agentpress_tools: Optional[bool] = Query(None, description="Filter by agents with AgentPress tools"),
    tools: Optional[str] = Query(None, description="Comma-separated list of tools to filter by")
):
    """Get agents for the current user with pagination, search, sort, and filter support."""
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agents currently disabled. This feature is not available at the moment."
        )
    logger.info(f"Fetching agents for user: {user_id} with page={page}, limit={limit}, search='{search}', sort_by={sort_by}, sort_order={sort_order}")
    client = await db.client
    
    try:
        # 计算偏移量
        offset = (page - 1) * limit
        # 构建基础查询：选择 agents 表的所有字段 (*)
        # 启用精确计数 (count='exact') 用于分页
        # 过滤条件：只查询当前用户的 agents
        query = client.table('agents').select('*', count='exact').eq("user_id", user_id)

        # 如果提供搜索词，在 name 和 description 字段中模糊搜索
        if search:
            search_term = f"%{search}%"  # 模糊匹配模式
            query = query.or_(f"name.ilike.{search_term},description.ilike.{search_term}")
        
        # 过滤条件：是否为默认 Agent，只有明确传入 True/False 时才应用此过滤
        if has_default is not None:
            query = query.eq("is_default", has_default)
        
                
        # 支持按 name、updated_at、created_at 排序
        # 支持升序(asc)和降序(desc)
        # 默认按创建时间降序排列（最新的在前）
        if sort_by == "name":
            query = query.order("name", desc=(sort_order == "desc"))
        elif sort_by == "updated_at":
            query = query.order("updated_at", desc=(sort_order == "desc"))
        elif sort_by == "created_at":
            query = query.order("created_at", desc=(sort_order == "desc"))
        else:
            # 默认按创建时间排序
            query = query.order("created_at", desc=(sort_order == "desc"))

        # 获取分页数据和总数量
        query = query.range(offset, offset + limit - 1)
        agents_result = await query.execute()
        total_count = agents_result.count if agents_result.count is not None else 0

        if not agents_result.data:
            logger.info(f"No agents found for user: {user_id}")
            return {
                "agents": [],
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": 0,
                    "pages": 0
                }
            }
        
        # 后处理：工具过滤和tools_count排序
        agents_data = agents_result.data
        
        # 首先，批量获取所有Agent的版本数据，确保我们拥有正确的工具信息
        # 这样做比逐个Agent调用服务更高效
        agent_version_map = {}
        version_ids = list({agent['current_version_id'] for agent in agents_data if agent.get('current_version_id')})
        logger.info(f"version_ids: {version_ids}")
        if version_ids:
            try:
                versions_result = await client.table('agent_versions').select(
                    'version_id, agent_id, version_number, version_name, is_active, created_at, updated_at, created_by, config'
                ).in_('version_id', version_ids).execute()

                for row in (versions_result.data or []):
                    config = row.get('config') or {}
                    tools = config.get('tools') or {}
                version_dict = {
                        'version_id': row['version_id'],
                        'agent_id': row['agent_id'],
                        'version_number': row['version_number'],
                        'version_name': row['version_name'],
                        'system_prompt': config.get('system_prompt', ''),
                        'configured_mcps': tools.get('mcp', []),
                        'custom_mcps': tools.get('custom_mcp', []),
                        'agentpress_tools': tools.get('agentpress', {}),
                        'is_active': row.get('is_active', False),
                        'created_at': row.get('created_at'),
                        'updated_at': row.get('updated_at') or row.get('created_at'),
                        'created_by': row.get('created_by'),
                }
                agent_version_map[row['agent_id']] = version_dict
            except Exception as e:
                logger.warning(f"Failed to batch load versions for agents: {e}")
        
        # 应用工具过滤条件使用版本数据
        if has_mcp_tools is not None or has_agentpress_tools is not None or tools:
            filtered_agents = []
            tools_filter = []
            if tools:
                # 处理tools参数可能作为dict而不是字符串传递的情况
                if isinstance(tools, str):
                    tools_filter = [tool.strip() for tool in tools.split(',') if tool.strip()]
                elif isinstance(tools, dict):
                    # 如果tools是dict，记录问题并跳过过滤
                    logger.warning(f"Received tools parameter as dict instead of string: {tools}")
                    tools_filter = []
                elif isinstance(tools, list):
                    # 如果tools是list，直接使用
                    tools_filter = [str(tool).strip() for tool in tools if str(tool).strip()]
                else:
                    logger.warning(f"Unexpected tools parameter type: {type(tools)}, value: {tools}")
                    tools_filter = []
            
            for agent in agents_data:
                # Get version data if available and extract configuration
                version_data = agent_version_map.get(agent['agent_id'])
                from agent.config_helper import extract_agent_config
                agent_config = extract_agent_config(agent, version_data)
                
                configured_mcps = agent_config['configured_mcps']
                agentpress_tools = agent_config['agentpress_tools']
                
                # Check MCP tools filter
                if has_mcp_tools is not None:
                    has_mcp = bool(configured_mcps and len(configured_mcps) > 0)
                    if has_mcp_tools != has_mcp:
                        continue
                
                # Check AgentPress tools filter
                if has_agentpress_tools is not None:
                    has_enabled_tools = any(
                        tool_data and isinstance(tool_data, dict) and tool_data.get('enabled', False)
                        for tool_data in agentpress_tools.values()
                    )
                    if has_agentpress_tools != has_enabled_tools:
                        continue
                
                # Check specific tools filter
                if tools_filter:
                    agent_tools = set()
                    # Add MCP tools
                    for mcp in configured_mcps:
                        if isinstance(mcp, dict) and 'name' in mcp:
                            agent_tools.add(f"mcp:{mcp['name']}")
                    
                    # Add enabled AgentPress tools
                    for tool_name, tool_data in agentpress_tools.items():
                        if tool_data and isinstance(tool_data, dict) and tool_data.get('enabled', False):
                            agent_tools.add(f"agentpress:{tool_name}")
                    
                    # Check if any of the requested tools are present
                    if not any(tool in agent_tools for tool in tools_filter):
                        continue
                
                filtered_agents.append(agent)
            
            agents_data = filtered_agents
        
        # 处理tools_count排序 (后处理 required)
        if sort_by == "tools_count":
            def get_tools_count(agent):
                # 获取版本数据如果available
                version_data = agent_version_map.get(agent['agent_id'])
                
                # 使用版本数据用于工具如果available, 否则回退到Agent数据
                if version_data:
                    configured_mcps = version_data.get('configured_mcps', [])
                    agentpress_tools = version_data.get('agentpress_tools', {})
                else:
                    configured_mcps = agent.get('configured_mcps', [])
                    agentpress_tools = agent.get('agentpress_tools', {})
                
                mcp_count = len(configured_mcps)
                agentpress_count = sum(
                    1 for tool_data in agentpress_tools.values()
                    if tool_data and isinstance(tool_data, dict) and tool_data.get('enabled', False)
                )
                return mcp_count + agentpress_count
            
            agents_data.sort(key=get_tools_count, reverse=(sort_order == "desc"))
        
        # 应用分页到过滤结果如果我们做了后处理
        if has_mcp_tools is not None or has_agentpress_tools is not None or tools or sort_by == "tools_count":
            total_count = len(agents_data)
            agents_data = agents_data[offset:offset + limit]
        
        # 格式化响应
        agent_list = []
        for agent in agents_data:
            current_version = None
            # 使用已经获取的版本数据 from agent_version_map
            version_dict = agent_version_map.get(agent['agent_id'])
            if version_dict:
                try:
                    current_version = AgentVersionResponse(
                        version_id=version_dict['version_id'],
                        agent_id=version_dict['agent_id'],
                        version_number=version_dict['version_number'],
                        version_name=version_dict['version_name'],
                        system_prompt=version_dict['system_prompt'],
                        model=version_dict.get('model'),
                        configured_mcps=version_dict.get('configured_mcps', []),
                        custom_mcps=version_dict.get('custom_mcps', []),
                        agentpress_tools=version_dict.get('agentpress_tools', {}),
                        is_active=version_dict.get('is_active', True),
                        created_at=version_dict['created_at'],
                        updated_at=version_dict.get('updated_at', version_dict['created_at']),
                        created_by=version_dict.get('created_by')
                    )
                except Exception as e:
                    logger.warning(f"Failed to get version data for agent {agent['agent_id']}: {e}")
            
            # 提取配置使用统一配置 approach
            from agent.config_helper import extract_agent_config
            agent_config = extract_agent_config(agent, version_dict)
            
            system_prompt = agent_config['system_prompt']
            configured_mcps = agent_config['configured_mcps']
            custom_mcps = agent_config['custom_mcps']
            agentpress_tools = agent_config['agentpress_tools']
            
            agent_list.append(AgentResponse(
                agent_id=agent['agent_id'],
                account_id=agent['user_id'],
                name=agent['name'],
                description=agent.get('description'),
                system_prompt=system_prompt,
                configured_mcps=configured_mcps,
                custom_mcps=custom_mcps,
                agentpress_tools=agentpress_tools,
                is_default=agent.get('is_default', False),
                is_public=agent.get('is_public', False),
                tags=agent.get('tags', []),
                avatar=agent_config.get('avatar'),
                avatar_color=agent_config.get('avatar_color'),
                profile_image_url=agent_config.get('profile_image_url'),
                created_at=agent['created_at'].isoformat() if agent.get('created_at') else None,
                updated_at=agent['updated_at'].isoformat() if agent.get('updated_at') else None,
                current_version_id=agent.get('current_version_id'),
                version_count=agent.get('version_count', 1),
                current_version=current_version,
                metadata=json.loads(agent.get('metadata', '{}')) if isinstance(agent.get('metadata'), str) else (agent.get('metadata') or {})
            ))
        
        total_pages = (total_count + limit - 1) // limit
        
        logger.info(f"Found {len(agent_list)} agents for user: {user_id} (page {page}/{total_pages})")
        return {
            "agents": agent_list,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": total_pages
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching agents for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch agents: {str(e)}")

@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    """Get a specific agent by ID with current version information. Only the owner can access non-public agents."""
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agents currently disabled. This feature is not available at the moment."
        )
    
    logger.info(f"Fetching agent {agent_id} for user: {user_id}")
    client = await db.client
    
    try:
        # Get agent
        agent_result = await client.table('agents').select('*').eq("agent_id", agent_id).execute()
        
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        agent_data = agent_result.data[0]
        
        # Check ownership - only owner can access non-public agents
        if agent_data['user_id'] != user_id and not agent_data.get('is_public', False):
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Use versioning system to get current version data
        current_version = None
        if agent_data.get('current_version_id'):
            try:
                version_service = await _get_version_service()
                current_version_obj = await version_service.get_version(
                    agent_id=agent_id,
                    version_id=agent_data['current_version_id'],
                    user_id=user_id
                )
                current_version_data = current_version_obj.to_dict()
                version_data = current_version_data
                
                # Create AgentVersionResponse from version data
                current_version = AgentVersionResponse(
                    version_id=current_version_data['version_id'],
                    agent_id=current_version_data['agent_id'],
                    version_number=current_version_data['version_number'],
                    version_name=current_version_data['version_name'],
                    system_prompt=current_version_data['system_prompt'],
                    model=current_version_data.get('model'),
                    configured_mcps=current_version_data.get('configured_mcps', []),
                    custom_mcps=current_version_data.get('custom_mcps', []),
                    agentpress_tools=current_version_data.get('agentpress_tools', {}),
                    is_active=current_version_data.get('is_active', True),
                    created_at=current_version_data['created_at'],
                    updated_at=current_version_data.get('updated_at', current_version_data['created_at']),
                    created_by=current_version_data.get('created_by')
                )
                
                logger.info(f"Using agent {agent_data['name']} version {current_version_data.get('version_name', 'v1')}")
            except Exception as e:
                logger.warning(f"Failed to get version data for agent {agent_id}: {e}")
        
        # Extract configuration using the unified config approach
        version_data = None
        if current_version:
            version_data = {
                'version_id': current_version.version_id,
                'agent_id': current_version.agent_id,
                'version_number': current_version.version_number,
                'version_name': current_version.version_name,
                'system_prompt': current_version.system_prompt,
                'model': current_version.model,
                'configured_mcps': current_version.configured_mcps,
                'custom_mcps': current_version.custom_mcps,
                'agentpress_tools': current_version.agentpress_tools,
                'is_active': current_version.is_active,
                'created_at': current_version.created_at,
                'updated_at': current_version.updated_at,
                'created_by': current_version.created_by
            }
        
        from agent.config_helper import extract_agent_config
        agent_config = extract_agent_config(agent_data, version_data)
        
        system_prompt = agent_config['system_prompt']
        configured_mcps = agent_config['configured_mcps']
        custom_mcps = agent_config['custom_mcps']
        agentpress_tools = agent_config['agentpress_tools']
        
        return AgentResponse(
            agent_id=agent_data['agent_id'],
            account_id=agent_data['user_id'],
            name=agent_data['name'],
            description=agent_data.get('description'),
            system_prompt=system_prompt,
            configured_mcps=configured_mcps,
            custom_mcps=custom_mcps,
            agentpress_tools=agentpress_tools,
            is_default=agent_data.get('is_default', False),
            is_public=agent_data.get('is_public', False),
            tags=agent_data.get('tags', []),
            avatar=agent_config.get('avatar'),
            avatar_color=agent_config.get('avatar_color'),
            profile_image_url=agent_config.get('profile_image_url'),
            created_at=agent_data['created_at'].isoformat() if agent_data.get('created_at') else None,
            updated_at=agent_data.get('updated_at', agent_data['created_at']).isoformat() if agent_data.get('updated_at', agent_data['created_at']) else None,
            current_version_id=agent_data.get('current_version_id'),
            version_count=agent_data.get('version_count', 1),
            current_version=current_version,
            metadata=json.loads(agent_data.get('metadata', '{}')) if isinstance(agent_data.get('metadata'), str) else (agent_data.get('metadata') or {})
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent {agent_id} for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch agent: {str(e)}")

@router.get("/agents/{agent_id}/export")
async def export_agent(agent_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    """Export an agent configuration as JSON"""
    logger.info(f"Exporting agent {agent_id} for user: {user_id}")
    
    try:
        client = await db.client
        
        # Get agent data
        agent_result = await client.table('agents').select('*').eq('agent_id', agent_id).eq('account_id', user_id).execute()
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        agent = agent_result.data[0]
        
        # Get current version data if available
        current_version = None
        if agent.get('current_version_id'):
            version_result = await client.table('agent_versions').select('*').eq('version_id', agent['current_version_id']).execute()
            if version_result.data:
                current_version = version_result.data[0]

        from agent.config_helper import extract_agent_config
        config = extract_agent_config(agent, current_version)
        
        from templates.template_service import TemplateService
        template_service = TemplateService(db)
        
        full_config = {
            'system_prompt': config.get('system_prompt', ''),
            'tools': {
                'agentpress': config.get('agentpress_tools', {}),
                'mcp': config.get('configured_mcps', []),
                'custom_mcp': config.get('custom_mcps', [])
            },
            'metadata': {
                # keep backward compat metadata
                'avatar': config.get('avatar'),
                'avatar_color': config.get('avatar_color'),
                # include profile image url in metadata for completeness
                'profile_image_url': agent.get('profile_image_url')
            }
        }
        
        sanitized_config = template_service._fallback_sanitize_config(full_config)
        
        export_metadata = {}
        if agent.get('metadata'):
            export_metadata = {k: v for k, v in agent['metadata'].items() 
                             if k not in ['is_fufanmanus_default', 'centrally_managed', 'installation_date', 'last_central_update']}
        
        export_data = {
            "tools": sanitized_config['tools'],
            "metadata": sanitized_config['metadata'],
            "system_prompt": sanitized_config['system_prompt'],
            "name": config.get('name', ''),
            "description": config.get('description', ''),
            # Deprecated
            "avatar": config.get('avatar'),
            "avatar_color": config.get('avatar_color'),
            # New
            "profile_image_url": agent.get('profile_image_url'),
            "tags": agent.get('tags', []),
            "export_metadata": export_metadata,
            "exported_at": datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(f"Successfully exported agent {agent_id}")
        return export_data
        
    except Exception as e:
        logger.error(f"Error exporting agent {agent_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to export agent: {str(e)}")

# JSON Import endpoints - similar to template installation flow

class JsonAnalysisRequest(BaseModel):
    """Request to analyze JSON for import requirements"""
    json_data: Dict[str, Any]

class JsonAnalysisResponse(BaseModel):
    """Response from JSON analysis"""
    requires_setup: bool
    missing_regular_credentials: List[Dict[str, Any]] = []
    missing_custom_configs: List[Dict[str, Any]] = []
    agent_info: Dict[str, Any] = {}

class JsonImportRequestModel(BaseModel):
    """Request to import agent from JSON"""
    json_data: Dict[str, Any]
    instance_name: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    profile_mappings: Optional[Dict[str, str]] = None
    custom_mcp_configs: Optional[Dict[str, Dict[str, Any]]] = None

class JsonImportResponse(BaseModel):
    """Response from JSON import"""
    status: str
    instance_id: Optional[str] = None
    name: Optional[str] = None
    missing_regular_credentials: List[Dict[str, Any]] = []
    missing_custom_configs: List[Dict[str, Any]] = []
    agent_info: Dict[str, Any] = {}

@router.post("/agents/json/analyze", response_model=JsonAnalysisResponse)
async def analyze_json_for_import(
    request: JsonAnalysisRequest,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """Analyze imported JSON to determine required credentials and configurations"""
    logger.info(f"Analyzing JSON for import - user: {user_id}")
    
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agents currently disabled. This feature is not available at the moment."
        )
    
    try:
        from agent.json_import_service import JsonImportService
        import_service = JsonImportService(db)
        
        analysis = await import_service.analyze_json(request.json_data, user_id)
        
        return JsonAnalysisResponse(
            requires_setup=analysis.requires_setup,
            missing_regular_credentials=analysis.missing_regular_credentials,
            missing_custom_configs=analysis.missing_custom_configs,
            agent_info=analysis.agent_info
        )
        
    except Exception as e:
        logger.error(f"Error analyzing JSON: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to analyze JSON: {str(e)}")

@router.post("/agents/json/import", response_model=JsonImportResponse)
async def import_agent_from_json(
    request: JsonImportRequestModel,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    logger.info(f"Importing agent from JSON - user: {user_id}")
    
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agents currently disabled. This feature is not available at the moment."
        )
    
    client = await db.client
    from .utils import check_agent_count_limit
    limit_check = await check_agent_count_limit(client, user_id)
    
    if not limit_check['can_create']:
        error_detail = {
            "message": f"Maximum of {limit_check['limit']} agents allowed for your current plan. You have {limit_check['current_count']} agents.",
            "current_count": limit_check['current_count'],
            "limit": limit_check['limit'],
            "tier_name": limit_check['tier_name'],
            "error_code": "AGENT_LIMIT_EXCEEDED"
        }
        logger.warning(f"Agent limit exceeded for account {user_id}: {limit_check['current_count']}/{limit_check['limit']} agents")
        raise HTTPException(status_code=402, detail=error_detail)
    
    try:
        from agent.json_import_service import JsonImportService, JsonImportRequest
        import_service = JsonImportService(db)
        
        import_request = JsonImportRequest(
            json_data=request.json_data,
            account_id=user_id,
            instance_name=request.instance_name,
            custom_system_prompt=request.custom_system_prompt,
            profile_mappings=request.profile_mappings,
            custom_mcp_configs=request.custom_mcp_configs
        )
        
        result = await import_service.import_json(import_request)
        
        return JsonImportResponse(
            status=result.status,
            instance_id=result.instance_id,
            name=result.name,
            missing_regular_credentials=result.missing_regular_credentials,
            missing_custom_configs=result.missing_custom_configs,
            agent_info=result.agent_info
        )
        
    except Exception as e:
        logger.error(f"Error importing agent from JSON: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Failed to import agent: {str(e)}")

@router.post("/agents", response_model=AgentResponse)
async def create_agent(
    agent_data: AgentCreateRequest,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    logger.info(f"Creating new agent for user: {user_id}")
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agents currently disabled. This feature is not available at the moment."
        )
    
    # 连接数据库
    client = await db.client
    
    from .utils import check_agent_count_limit
    limit_check = await check_agent_count_limit(client, user_id)
    
    if not limit_check['can_create']:
        error_detail = {
            "message": f"Maximum of {limit_check['limit']} agents allowed for your current plan. You have {limit_check['current_count']} agents.",
            "current_count": limit_check['current_count'],
            "limit": limit_check['limit'],
            "tier_name": limit_check['tier_name'],
            "error_code": "AGENT_LIMIT_EXCEEDED"
        }
        logger.warning(f"Agent limit exceeded for account {user_id}: {limit_check['current_count']}/{limit_check['limit']} agents")
        raise HTTPException(status_code=402, detail=error_detail)
    
    try:
        # 创建或更新Agent时，如果 is_default=True,将该用户的所有其他Agent的 is_default 设为 False. 确保只有一个Agent是默认的
        if agent_data.is_default:
            await client.table('agents').update({"is_default": False}).eq("user_id", user_id).eq("is_default", True)
   
        # 获取默认的系统提示词和工具
        from agent.config_helper import get_default_system_prompt_for_fufanmanus_agent
        default_system_prompt = get_default_system_prompt_for_fufanmanus_agent()
        
        # 获取默认工具配置
        from agent.fufanmanus.config import FufanmanusConfig
        default_tools = FufanmanusConfig.DEFAULT_TOOLS
        
        insert_data = {
            "agent_id": str(uuid.uuid4()),
            "user_id": user_id,  
            "name": agent_data.name,
            "description": agent_data.description or "",
            "system_prompt": agent_data.system_prompt or default_system_prompt,
            "model": agent_data.model or "gpt-4o",
            "configured_mcps": json.dumps(agent_data.configured_mcps or []),
            "custom_mcps": json.dumps(agent_data.custom_mcps or []),
            "agentpress_tools": json.dumps(agent_data.agentpress_tools or default_tools),
            "avatar": agent_data.avatar,
            "avatar_color": agent_data.avatar_color,
            "profile_image_url": agent_data.profile_image_url,
            "is_default": agent_data.is_default or False,
            "version_count": 1
        }

        new_agent = await client.table('agents').insert(insert_data)

        if not new_agent.data:
            raise HTTPException(status_code=500, detail="Failed to create agent")
        
        agent = new_agent.data[0]

        try:
            version_service = await _get_version_service()

            version = await version_service.create_version(
                agent_id=agent['agent_id'],
                user_id=user_id,
                system_prompt=agent_data.system_prompt or default_system_prompt,
                model=agent_data.model or "gpt-4o",
                configured_mcps=agent_data.configured_mcps or [],
                custom_mcps=agent_data.custom_mcps or [],
                agentpress_tools=agent_data.agentpress_tools or default_tools,
                version_name="v1",
                change_description="Initial version"
            )
            
            agent['current_version_id'] = version.version_id
            agent['version_count'] = 1

            current_version = AgentVersionResponse(
                version_id=version.version_id,
                agent_id=version.agent_id,
                version_number=version.version_number,
                version_name=version.version_name,
                system_prompt=version.system_prompt,
                model=version.model,
                configured_mcps=version.configured_mcps,
                custom_mcps=version.custom_mcps,
                agentpress_tools=version.agentpress_tools,
                is_active=version.is_active,
                created_at=version.created_at.isoformat(),
                updated_at=version.updated_at.isoformat(),
                created_by=version.created_by
            )
        except Exception as e:
            logger.error(f"Error creating initial version: {str(e)}")
            await client.table('agents').delete().eq('agent_id', agent['agent_id']).execute()
            raise HTTPException(status_code=500, detail="Failed to create initial version")
        
        from utils.cache import Cache
        # 清除用户当前Agent数量限制缓存，因为创建了新的Agent，数量发生变化，下次查询时会重新计算
        await Cache.invalidate(f"agent_count_limit:{user_id}")
        
        logger.info(f"Created agent {agent['agent_id']} with v1 for user: {user_id}")
        return AgentResponse(
            agent_id=agent['agent_id'],
            account_id=agent['user_id'],
            name=agent['name'],
            description=agent.get('description'),
            system_prompt=version.system_prompt,
            model=version.model,
            configured_mcps=version.configured_mcps,
            custom_mcps=version.custom_mcps,
            agentpress_tools=version.agentpress_tools,
            is_default=agent.get('is_default', False),
            is_public=agent.get('is_public', False),
            tags=agent.get('tags', []),
            avatar=agent.get('avatar'),
            avatar_color=agent.get('avatar_color'),
            profile_image_url=agent.get('profile_image_url'),
            created_at=agent['created_at'].isoformat() if agent['created_at'] else None,
            updated_at=agent.get('updated_at').isoformat() if agent.get('updated_at') else agent['created_at'].isoformat(),
            current_version_id=agent.get('current_version_id'),
            version_count=agent.get('version_count', 1),
            current_version=current_version,
            metadata=json.loads(agent.get('metadata', '{}')) if isinstance(agent.get('metadata'), str) else agent.get('metadata', {})
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating agent for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")

def merge_custom_mcps(existing_mcps: List[Dict[str, Any]], new_mcps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not new_mcps:
        return existing_mcps
    
    merged_mcps = existing_mcps.copy()
    
    for new_mcp in new_mcps:
        new_mcp_name = new_mcp.get('name')
        existing_index = None
        
        for i, existing_mcp in enumerate(merged_mcps):
            if existing_mcp.get('name') == new_mcp_name:
                existing_index = i
                break
        
        if existing_index is not None:
            merged_mcps[existing_index] = new_mcp
        else:
            merged_mcps.append(new_mcp)
    
    return merged_mcps

@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    agent_data: AgentUpdateRequest,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agent currently disabled. This feature is not available at the moment."
        )
    logger.info(f"Updating agent {agent_id} for user: {user_id}")
    client = await db.client
    
    try:
        existing_agent = await client.table('agents').select('*').eq("agent_id", agent_id).eq("account_id", user_id).maybe_single().execute()
        
        if not existing_agent.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        existing_data = existing_agent.data

        agent_metadata = existing_data.get('metadata', {})
        is_fufanmanus_agent = agent_metadata.get('is_fufanmanus_default', False)
        restrictions = agent_metadata.get('restrictions', {})
        
        if is_fufanmanus_agent:
            logger.warning(f"Update attempt on FuFanManus default agent {agent_id} by user {user_id}")
            
            if (agent_data.name is not None and 
                agent_data.name != existing_data.get('name') and 
                restrictions.get('name_editable') == False):
                logger.error(f"User {user_id} attempted to modify restricted name of FuFanManus agent {agent_id}")
                raise HTTPException(
                    status_code=403, 
                    detail="FuFanManus's name cannot be modified. This restriction is managed centrally."
                )
            
            if (agent_data.description is not None and
                agent_data.description != existing_data.get('description') and 
                restrictions.get('description_editable') == False):
                logger.error(f"User {user_id} attempted to modify restricted description of FuFanManus agent {agent_id}")
                raise HTTPException(
                    status_code=403, 
                    detail="FuFanManus's description cannot be modified."
                )
            
            if (agent_data.system_prompt is not None and 
                restrictions.get('system_prompt_editable') == False):
                logger.error(f"User {user_id} attempted to modify restricted system prompt of FuFanManus agent {agent_id}")
                raise HTTPException(
                    status_code=403, 
                    detail="FuFanManus's system prompt cannot be modified. This is managed centrally to ensure optimal performance."
                )
            
            if (agent_data.agentpress_tools is not None and 
                restrictions.get('tools_editable') == False):
                logger.error(f"User {user_id} attempted to modify restricted tools of FuFanManus agent {agent_id}")
                raise HTTPException(
                    status_code=403, 
                    detail="FuFanManus's default tools cannot be modified. These tools are optimized for FuFanManus's capabilities."
                )
            
            if ((agent_data.configured_mcps is not None or agent_data.custom_mcps is not None) and 
                restrictions.get('mcps_editable') == False):
                logger.error(f"User {user_id} attempted to modify restricted MCPs of FuFanManus agent {agent_id}")
                raise HTTPException(
                    status_code=403, 
                    detail="FuFanManus's integrations cannot be modified."
                )
            
            logger.info(f"FuFanManus agent update validation passed for agent {agent_id} by user {user_id}")

        current_version_data = None
        if existing_data.get('current_version_id'):
            try:
                version_service = await _get_version_service()
                current_version_obj = await version_service.get_version(
                    agent_id=agent_id,
                    version_id=existing_data['current_version_id'],
                    user_id=user_id
                )
                current_version_data = current_version_obj.to_dict()
            except Exception as e:
                logger.warning(f"Failed to get current version data for agent {agent_id}: {e}")
        
        if current_version_data is None:
            logger.info(f"Agent {agent_id} has no version data, creating initial version")
            try:
                workflows_result = await client.table('agent_workflows').select('*').eq('agent_id', agent_id).execute()
                workflows = workflows_result.data if workflows_result.data else []
                
                initial_version_data = {
                    "agent_id": agent_id,
                    "version_number": 1,
                    "version_name": "v1",
                    "system_prompt": existing_data.get('system_prompt', ''),
                    "configured_mcps": existing_data.get('configured_mcps', []),
                    "custom_mcps": existing_data.get('custom_mcps', []),
                    "agentpress_tools": existing_data.get('agentpress_tools', {}),
                    "is_active": True,
                    "created_by": user_id
                }
                
                initial_config = build_unified_config(
                    system_prompt=initial_version_data["system_prompt"],
                    agentpress_tools=initial_version_data["agentpress_tools"],
                    configured_mcps=initial_version_data["configured_mcps"],
                    custom_mcps=initial_version_data["custom_mcps"],
                    avatar=None,
                    avatar_color=None,
                    workflows=workflows
                )
                initial_version_data["config"] = initial_config
                
                version_result = await client.table('agent_versions').insert(initial_version_data).execute()
                
                if version_result.data:
                    version_id = version_result.data[0]['version_id']
                    
                    await client.table('agents').update({
                        'current_version_id': version_id,
                        'version_count': 1
                    }).eq('agent_id', agent_id).execute()
                    current_version_data = initial_version_data
                    logger.info(f"Created initial version for agent {agent_id}")
                else:
                    current_version_data = {
                        'system_prompt': existing_data.get('system_prompt', ''),
                        'configured_mcps': existing_data.get('configured_mcps', []),
                        'custom_mcps': existing_data.get('custom_mcps', []),
                        'agentpress_tools': existing_data.get('agentpress_tools', {})
                    }
            except Exception as e:
                logger.warning(f"Failed to create initial version for agent {agent_id}: {e}")
                current_version_data = {
                    'system_prompt': existing_data.get('system_prompt', ''),
                    'configured_mcps': existing_data.get('configured_mcps', []),
                    'custom_mcps': existing_data.get('custom_mcps', []),
                    'agentpress_tools': existing_data.get('agentpress_tools', {})
                }
        
        needs_new_version = False
        version_changes = {}
        
        def values_different(new_val, old_val):
            if new_val is None:
                return False
            try:
                new_json = json.dumps(new_val, sort_keys=True) if new_val is not None else None
                old_json = json.dumps(old_val, sort_keys=True) if old_val is not None else None
                return new_json != old_json
            except (TypeError, ValueError):
                return new_val != old_val
        
        if values_different(agent_data.system_prompt, current_version_data.get('system_prompt')):
            needs_new_version = True
            version_changes['system_prompt'] = agent_data.system_prompt
        
        if values_different(agent_data.configured_mcps, current_version_data.get('configured_mcps', [])):
            needs_new_version = True
            version_changes['configured_mcps'] = agent_data.configured_mcps
            
        if values_different(agent_data.custom_mcps, current_version_data.get('custom_mcps', [])):
            needs_new_version = True
            if agent_data.custom_mcps is not None:
                merged_custom_mcps = merge_custom_mcps(
                    current_version_data.get('custom_mcps', []),
                    agent_data.custom_mcps
                )
                version_changes['custom_mcps'] = merged_custom_mcps
            else:
                version_changes['custom_mcps'] = current_version_data.get('custom_mcps', [])
            
        if values_different(agent_data.agentpress_tools, current_version_data.get('agentpress_tools', {})):
            needs_new_version = True
            version_changes['agentpress_tools'] = agent_data.agentpress_tools
        
        update_data = {}
        if agent_data.name is not None:
            update_data["name"] = agent_data.name
        if agent_data.description is not None:
            update_data["description"] = agent_data.description
        if agent_data.is_default is not None:
            update_data["is_default"] = agent_data.is_default
            if agent_data.is_default:
                await client.table('agents').update({"is_default": False}).eq("user_id", user_id).eq("is_default", True).neq("agent_id", agent_id).execute()
        if agent_data.avatar is not None:
            update_data["avatar"] = agent_data.avatar
        if agent_data.avatar_color is not None:
            update_data["avatar_color"] = agent_data.avatar_color
        if agent_data.profile_image_url is not None:
            update_data["profile_image_url"] = agent_data.profile_image_url
        
        current_system_prompt = agent_data.system_prompt if agent_data.system_prompt is not None else current_version_data.get('system_prompt', '')
        current_configured_mcps = agent_data.configured_mcps if agent_data.configured_mcps is not None else current_version_data.get('configured_mcps', [])
        
        if agent_data.custom_mcps is not None:
            current_custom_mcps = merge_custom_mcps(
                current_version_data.get('custom_mcps', []),
                agent_data.custom_mcps
            )
        else:
            current_custom_mcps = current_version_data.get('custom_mcps', [])
            
        current_agentpress_tools = agent_data.agentpress_tools if agent_data.agentpress_tools is not None else current_version_data.get('agentpress_tools', {})
        current_avatar = agent_data.avatar if agent_data.avatar is not None else existing_data.get('avatar')
        current_avatar_color = agent_data.avatar_color if agent_data.avatar_color is not None else existing_data.get('avatar_color')
        new_version_id = None
        if needs_new_version:
            try:
                version_service = await _get_version_service()

                new_version = await version_service.create_version(
                    agent_id=agent_id,
                    user_id=user_id,
                    system_prompt=current_system_prompt,
                    configured_mcps=current_configured_mcps,
                    custom_mcps=current_custom_mcps,
                    agentpress_tools=current_agentpress_tools,
                    change_description="Configuration updated"
                )
                
                new_version_id = new_version.version_id
                update_data['current_version_id'] = new_version_id
                update_data['version_count'] = new_version.version_number
                
                logger.info(f"Created new version {new_version.version_name} for agent {agent_id}")
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error creating new version for agent {agent_id}: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to create new agent version: {str(e)}")
        
        if update_data:
            try:
                update_result = await client.table('agents').update(update_data).eq("agent_id", agent_id).eq("account_id", user_id).execute()
                
                if not update_result.data:
                    raise HTTPException(status_code=500, detail="Failed to update agent - no rows affected")
            except Exception as e:
                logger.error(f"Error updating agent {agent_id}: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")
        
        updated_agent = await client.table('agents').select('*').eq("agent_id", agent_id).eq("account_id", user_id).maybe_single().execute()
        
        if not updated_agent.data:
            raise HTTPException(status_code=500, detail="Failed to fetch updated agent")
        
        agent = updated_agent.data
        
        current_version = None
        if agent.get('current_version_id'):
            try:
                version_service = await _get_version_service()
                current_version_obj = await version_service.get_version(
                    agent_id=agent_id,
                    version_id=agent['current_version_id'],
                    user_id=user_id
                )
                current_version_data = current_version_obj.to_dict()
                version_data = current_version_data
                
                current_version = AgentVersionResponse(
                    version_id=current_version_data['version_id'],
                    agent_id=current_version_data['agent_id'],
                    version_number=current_version_data['version_number'],
                    version_name=current_version_data['version_name'],
                    system_prompt=current_version_data['system_prompt'],
                    model=current_version_data.get('model'),
                    configured_mcps=current_version_data.get('configured_mcps', []),
                    custom_mcps=current_version_data.get('custom_mcps', []),
                    agentpress_tools=current_version_data.get('agentpress_tools', {}),
                    is_active=current_version_data.get('is_active', True),
                    created_at=current_version_data['created_at'],
                    updated_at=current_version_data.get('updated_at', current_version_data['created_at']),
                    created_by=current_version_data.get('created_by')
                )
                
                logger.info(f"Using agent {agent['name']} version {current_version_data.get('version_name', 'v1')}")
            except Exception as e:
                logger.warning(f"Failed to get version data for updated agent {agent_id}: {e}")
        
        version_data = None
        if current_version:
            version_data = {
                'version_id': current_version.version_id,
                'agent_id': current_version.agent_id,
                'version_number': current_version.version_number,
                'version_name': current_version.version_name,
                'system_prompt': current_version.system_prompt,
                'model': current_version.model,
                'configured_mcps': current_version.configured_mcps,
                'custom_mcps': current_version.custom_mcps,
                'agentpress_tools': current_version.agentpress_tools,
                'is_active': current_version.is_active,
            }
        
        from agent.config_helper import extract_agent_config
        agent_config = extract_agent_config(agent, version_data)
        
        system_prompt = agent_config['system_prompt']
        configured_mcps = agent_config['configured_mcps']
        custom_mcps = agent_config['custom_mcps']
        agentpress_tools = agent_config['agentpress_tools']
        
        return AgentResponse(
            agent_id=agent['agent_id'],
            account_id=agent['user_id'],
            name=agent['name'],
            description=agent.get('description'),
            system_prompt=system_prompt,
            configured_mcps=configured_mcps,
            custom_mcps=custom_mcps,
            agentpress_tools=agentpress_tools,
            is_default=agent.get('is_default', False),
            is_public=agent.get('is_public', False),
            tags=agent.get('tags', []),
            avatar=agent_config.get('avatar'),
            avatar_color=agent_config.get('avatar_color'),
            profile_image_url=agent_config.get('profile_image_url'),
            created_at=agent['created_at'].isoformat() if agent['created_at'] else None,
            updated_at=agent.get('updated_at').isoformat() if agent.get('updated_at') else agent['created_at'].isoformat(),
            current_version_id=agent.get('current_version_id'),
            version_count=agent.get('version_count', 1),
            current_version=current_version,
            metadata=json.loads(agent.get('metadata', '{}')) if isinstance(agent.get('metadata'), str) else agent.get('metadata', {})
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating agent {agent_id} for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")

@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, user_id: str = Depends(get_current_user_id_from_jwt)):
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agent currently disabled. This feature is not available at the moment."
        )
    logger.info(f"Deleting agent: {agent_id}")
    client = await db.client
    
    try:
        agent_result = await client.table('agents').select('*').eq('agent_id', agent_id).execute()
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        agent = agent_result.data[0]
        if agent['user_id'] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        if agent['is_default']:
            raise HTTPException(status_code=400, detail="Cannot delete default agent")
        
        if agent.get('metadata', {}).get('is_fufanmanus_default', False):
            raise HTTPException(status_code=400, detail="Cannot delete FuFanManus default agent")
        
        delete_result = await client.table('agents').delete().eq('agent_id', agent_id).execute()
        
        if not delete_result.data:
            logger.warning(f"No agent was deleted for agent_id: {agent_id}, user_id: {user_id}")
            raise HTTPException(status_code=403, detail="Unable to delete agent - permission denied or agent not found")
        
        try:
            from utils.cache import Cache
            await Cache.invalidate(f"agent_count_limit:{user_id}")
        except Exception as cache_error:
            logger.warning(f"Cache invalidation failed for user {user_id}: {str(cache_error)}")
        
        logger.info(f"Successfully deleted agent: {agent_id}")
        return {"message": "Agent deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting agent {agent_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/agents/{agent_id}/builder-chat-history")
async def get_agent_builder_chat_history(
    agent_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    if not await is_enabled("custom_agents"):
        raise HTTPException(
            status_code=403, 
            detail="Custom agents currently disabled. This feature is not available at the moment."
        )
    
    logger.info(f"Fetching agent builder chat history for agent: {agent_id}")
    client = await db.client
    
    try:
        agent_result = await client.table('agents').select('*').eq('agent_id', agent_id).eq('user_id', user_id).execute()
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found or access denied")
        
        threads_result = await client.table('threads').select('thread_id, created_at, metadata').eq('account_id', user_id).order('created_at', desc=True).execute()
        
        agent_builder_threads = []
        for thread in threads_result.data:
            metadata = thread.get('metadata', {})
            # 如果metadata是字符串，解析为字典
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            elif not isinstance(metadata, dict):
                metadata = {}
            
            if (metadata.get('is_agent_builder') and 
                metadata.get('target_agent_id') == agent_id):
                agent_builder_threads.append({
                    'thread_id': thread['thread_id'],
                    'created_at': thread['created_at']
                })
        
        if not agent_builder_threads:
            logger.info(f"No agent builder threads found for agent {agent_id}")
            return {"messages": [], "thread_id": None}
        
        latest_thread_id = agent_builder_threads[0]['thread_id']
        logger.info(f"Found {len(agent_builder_threads)} agent builder threads, using latest: {latest_thread_id}")
        # 从ADK events表查询消息（按时间排序）
        messages_result = await client.schema('public').table('events').select('*').eq('session_id', latest_thread_id).order('timestamp', desc=False).execute()
        
        logger.info(f"Found {len(messages_result.data)} events for agent builder chat history")
        
        # 转换ADK events为消息格式
        messages = _convert_adk_events_to_messages(messages_result.data)
        
        return {
            "messages": messages,
            "thread_id": latest_thread_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent builder chat history for agent {agent_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch chat history: {str(e)}")

@router.get("/agents/{agent_id}/pipedream-tools/{profile_id}")
async def get_pipedream_tools_for_agent(
    agent_id: str,
    profile_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt),
    version: Optional[str] = Query(None, description="Version ID to get tools from specific version")
):
    logger.info(f"Getting tools for agent {agent_id}, profile {profile_id}, user {user_id}, version {version}")

    try:
        from pipedream import profile_service, mcp_service
        from uuid import UUID

        profile = await profile_service.get_profile(UUID(user_id), UUID(profile_id))
        
        if not profile:
            logger.error(f"Profile {profile_id} not found for user {user_id}")
            try:
                all_profiles = await profile_service.get_profiles(UUID(user_id))
                pipedream_profiles = [p for p in all_profiles if 'pipedream' in p.mcp_qualified_name]
                logger.info(f"User {user_id} has {len(pipedream_profiles)} pipedream profiles: {[p.profile_id for p in pipedream_profiles]}")
            except Exception as debug_e:
                logger.warning(f"Could not check user's profiles: {str(debug_e)}")
            
            raise HTTPException(status_code=404, detail=f"Profile {profile_id} not found or access denied")
        
        if not profile.is_connected:
            raise HTTPException(status_code=400, detail="Profile is not connected")

        enabled_tools = []
        try:
            client = await db.client
            agent_row = await client.table('agents')\
                .select('current_version_id')\
                .eq('agent_id', agent_id)\
                .eq('account_id', user_id)\
                .maybe_single()\
                .execute()
            
            if agent_row.data and agent_row.data.get('current_version_id'):
                if version:
                    version_result = await client.table('agent_versions')\
                        .select('config')\
                        .eq('version_id', version)\
                        .maybe_single()\
                        .execute()
                else:
                    version_result = await client.table('agent_versions')\
                        .select('config')\
                        .eq('version_id', agent_row.data['current_version_id'])\
                        .maybe_single()\
                        .execute()
                
                if version_result.data and version_result.data.get('config'):
                    agent_config = version_result.data['config']
                    tools = agent_config.get('tools', {})
                    custom_mcps = tools.get('custom_mcp', []) or []
                    
                    for mcp in custom_mcps:
                        mcp_profile_id = mcp.get('config', {}).get('profile_id')
                        if mcp_profile_id == profile_id:
                            enabled_tools = mcp.get('enabledTools', mcp.get('enabled_tools', []))
                            logger.info(f"Found enabled tools for profile {profile_id}: {enabled_tools}")
                            break
                    
                    if not enabled_tools:
                        logger.info(f"No enabled tools found for profile {profile_id} in agent {agent_id}")
            
        except Exception as e:
            logger.error(f"Error retrieving enabled tools for profile {profile_id}: {str(e)}")
        
        logger.info(f"Using {len(enabled_tools)} enabled tools for profile {profile_id}: {enabled_tools}")
        
        try:
            from pipedream.mcp_service import ExternalUserId, AppSlug
            external_user_id = ExternalUserId(profile.external_user_id)
            app_slug_obj = AppSlug(profile.app_slug)
            
            logger.info(f"Discovering servers for user {external_user_id.value} and app {app_slug_obj.value}")
            servers = await mcp_service.discover_servers_for_user(external_user_id, app_slug_obj)
            logger.info(f"Found {len(servers)} servers: {[s.app_slug for s in servers]}")
            
            server = servers[0] if servers else None
            logger.info(f"Selected server: {server.app_slug if server else 'None'} with {len(server.available_tools) if server else 0} tools")
            
            if not server:
                return {
                    'profile_id': profile_id,
                    'app_name': profile.app_name,
                    'profile_name': profile.profile_name,
                    'tools': [],
                    'has_mcp_config': len(enabled_tools) > 0
                }
            
            available_tools = server.available_tools
            
            formatted_tools = []
            def tools_match(api_tool_name, stored_tool_name):
                api_normalized = api_tool_name.lower().replace('-', '_')
                stored_normalized = stored_tool_name.lower().replace('-', '_')
                return api_normalized == stored_normalized
            
            for tool in available_tools:
                is_enabled = any(tools_match(tool.name, stored_tool) for stored_tool in enabled_tools)
                formatted_tools.append({
                    'name': tool.name,
                    'description': tool.description or f"Tool from {profile.app_name}",
                    'enabled': is_enabled
                })
            
            return {
                'profile_id': profile_id,
                'app_name': profile.app_name,
                'profile_name': profile.profile_name,
                'tools': formatted_tools,
                'has_mcp_config': len(enabled_tools) > 0
            }
            
        except Exception as e:
            logger.error(f"Error discovering tools: {e}", exc_info=True)
            return {
                'profile_id': profile_id,
                'app_name': getattr(profile, 'app_name', 'Unknown'),
                'profile_name': getattr(profile, 'profile_name', 'Unknown'),
                'tools': [],
                'has_mcp_config': len(enabled_tools) > 0,
                'error': str(e)
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting Pipedream tools for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/agents/{agent_id}/pipedream-tools/{profile_id}")
async def update_pipedream_tools_for_agent(
    agent_id: str,
    profile_id: str,
    request: dict,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    try:
        client = await db.client
        agent_row = await client.table('agents')\
            .select('current_version_id')\
            .eq('agent_id', agent_id)\
            .eq('account_id', user_id)\
            .maybe_single()\
            .execute()
        if not agent_row.data:
            raise HTTPException(status_code=404, detail="Agent not found")

        agent_config = {}
        if agent_row.data.get('current_version_id'):
            version_result = await client.table('agent_versions')\
                .select('config')\
                .eq('version_id', agent_row.data['current_version_id'])\
                .maybe_single()\
                .execute()
            if version_result.data and version_result.data.get('config'):
                agent_config = version_result.data['config']

        tools = agent_config.get('tools', {})
        custom_mcps = tools.get('custom_mcp', []) or []

        if any(mcp.get('config', {}).get('profile_id') == profile_id for mcp in custom_mcps):
            raise HTTPException(status_code=400, detail="This profile is already added to this agent")

        enabled_tools = request.get('enabled_tools', [])
        
        updated = False
        for mcp in custom_mcps:
            mcp_profile_id = mcp.get('config', {}).get('profile_id')
            if mcp_profile_id == profile_id:
                mcp['enabledTools'] = enabled_tools
                mcp['enabled_tools'] = enabled_tools
                updated = True
                logger.info(f"Updated enabled tools for profile {profile_id}: {enabled_tools}")
                break
        
        if not updated:
            logger.warning(f"Profile {profile_id} not found in agent {agent_id} custom_mcps configuration")
            
        if updated:
            agent_config['tools']['custom_mcp'] = custom_mcps
            
            await client.table('agent_versions')\
                .update({'config': agent_config})\
                .eq('version_id', agent_row.data['current_version_id'])\
                .execute()
            
            logger.info(f"Successfully updated agent configuration for {agent_id}")
        
        result = {
            'success': updated,
            'enabled_tools': enabled_tools,
            'total_tools': len(enabled_tools),
            'profile_id': profile_id
        }
        logger.info(f"Successfully updated Pipedream tools for agent {agent_id}, profile {profile_id}")
        return result
        
    except ValueError as e:
        logger.error(f"Validation error updating Pipedream tools: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating Pipedream tools for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agents/{agent_id}/custom-mcp-tools")
async def get_custom_mcp_tools_for_agent(
    agent_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    logger.info(f"Getting custom MCP tools for agent {agent_id}, user {user_id}")
    try:
        client = await db.client
        agent_result = await client.table('agents').select('current_version_id').eq('agent_id', agent_id).eq('account_id', user_id).execute()
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        agent = agent_result.data[0]
 
        agent_config = {}
        if agent.get('current_version_id'):
            version_result = await client.table('agent_versions')\
                .select('config')\
                .eq('version_id', agent['current_version_id'])\
                .maybe_single()\
                .execute()
            if version_result.data and version_result.data.get('config'):
                agent_config = version_result.data['config']
        
        tools = agent_config.get('tools', {})
        custom_mcps = tools.get('custom_mcp', [])
        
        mcp_url = request.headers.get('X-MCP-URL')
        mcp_type = request.headers.get('X-MCP-Type', 'sse')
        
        if not mcp_url:
            raise HTTPException(status_code=400, detail="X-MCP-URL header is required")
        
        mcp_config = {
            'url': mcp_url,
            'type': mcp_type
        }
        
        if 'X-MCP-Headers' in request.headers:
            try:
                mcp_config['headers'] = json.loads(request.headers['X-MCP-Headers'])
            except json.JSONDecodeError:
                logger.warning("Failed to parse X-MCP-Headers as JSON")
        
        from mcp_module import mcp_service
        discovery_result = await mcp_service.discover_custom_tools(mcp_type, mcp_config)
        
        existing_mcp = None
        for mcp in custom_mcps:
            if (mcp.get('type') == mcp_type and 
                mcp.get('config', {}).get('url') == mcp_url):
                existing_mcp = mcp
                break
        
        tools = []
        enabled_tools = existing_mcp.get('enabledTools', []) if existing_mcp else []
        
        for tool in discovery_result.tools:
            tools.append({
                'name': tool['name'],
                'description': tool.get('description', f'Tool from {mcp_type.upper()} MCP server'),
                'enabled': tool['name'] in enabled_tools
            })
        
        return {
            'tools': tools,
            'has_mcp_config': existing_mcp is not None,
            'server_type': mcp_type,
            'server_url': mcp_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting custom MCP tools for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agents/{agent_id}/custom-mcp-tools")
async def update_custom_mcp_tools_for_agent(
    agent_id: str,
    request: dict,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    logger.info(f"Updating custom MCP tools for agent {agent_id}, user {user_id}")
    
    try:
        client = await db.client
        
        agent_result = await client.table('agents').select('current_version_id').eq('agent_id', agent_id).eq('account_id', user_id).execute()
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        agent = agent_result.data[0]
        
        agent_config = {}
        if agent.get('current_version_id'):
            version_result = await client.table('agent_versions')\
                .select('config')\
                .eq('version_id', agent['current_version_id'])\
                .maybe_single()\
                .execute()
            if version_result.data and version_result.data.get('config'):
                agent_config = version_result.data['config']
        
        tools = agent_config.get('tools', {})
        custom_mcps = tools.get('custom_mcp', [])
        
        mcp_url = request.get('url')
        mcp_type = request.get('type', 'sse')
        enabled_tools = request.get('enabled_tools', [])
        
        if not mcp_url:
            raise HTTPException(status_code=400, detail="MCP URL is required")
        
        updated = False
        for i, mcp in enumerate(custom_mcps):
            if mcp_type == 'composio':
                # For Composio, match by profile_id
                if (mcp.get('type') == 'composio' and 
                    mcp.get('config', {}).get('profile_id') == mcp_url):
                    custom_mcps[i]['enabledTools'] = enabled_tools
                    updated = True
                    break
            else:
                if (mcp.get('customType') == mcp_type and 
                    mcp.get('config', {}).get('url') == mcp_url):
                    custom_mcps[i]['enabledTools'] = enabled_tools
                    updated = True
                    break
        
        if not updated:
            if mcp_type == 'composio':
                try:
                    from composio_integration.composio_profile_service import ComposioProfileService
                    from services.postgresql import DBConnection
                    profile_service = ComposioProfileService(DBConnection())
 
                    profile_id = mcp_url
                    mcp_config = await profile_service.get_mcp_config_for_agent(profile_id)
                    mcp_config['enabledTools'] = enabled_tools
                    custom_mcps.append(mcp_config)
                except Exception as e:
                    logger.error(f"Failed to get Composio profile config: {e}")
                    raise HTTPException(status_code=400, detail=f"Failed to get Composio profile: {str(e)}")
            else:
                new_mcp_config = {
                    "name": f"Custom MCP ({mcp_type.upper()})",
                    "customType": mcp_type,
                    "type": mcp_type,
                    "config": {
                        "url": mcp_url
                    },
                    "enabledTools": enabled_tools
                }
                custom_mcps.append(new_mcp_config)
        
        tools['custom_mcp'] = custom_mcps
        agent_config['tools'] = tools
        
        from agent.versioning.version_service import get_version_service
        try:
            version_service = await get_version_service() 
            new_version = await version_service.create_version(
                agent_id=agent_id,
                user_id=user_id,
                system_prompt=agent_config.get('system_prompt', ''),
                configured_mcps=agent_config.get('tools', {}).get('mcp', []),
                custom_mcps=custom_mcps,
                agentpress_tools=agent_config.get('tools', {}).get('agentpress', {}),
                change_description=f"Updated custom MCP tools for {mcp_type}"
            )
            logger.info(f"Created version {new_version.version_id} for custom MCP tools update on agent {agent_id}")
        except Exception as e:
            logger.error(f"Failed to create version for custom MCP tools update: {e}")
            raise HTTPException(status_code=500, detail="Failed to save changes")
        
        return {
            'success': True,
            'enabled_tools': enabled_tools,
            'total_tools': len(enabled_tools)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating custom MCP tools for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/agents/{agent_id}/tools")
async def get_agent_tools(
    agent_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    if not await is_enabled("custom_agents"):
        raise HTTPException(status_code=403, detail="Custom agents currently disabled")
        
    logger.info(f"Fetching enabled tools for agent: {agent_id} by user: {user_id}")
    client = await db.client

    agent_result = await client.table('agents').select('*').eq('agent_id', agent_id).execute()
    if not agent_result.data:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = agent_result.data[0]
    if agent['user_id'] != user_id and not agent.get('is_public', False):
        raise HTTPException(status_code=403, detail="Access denied")


    version_data = None
    if agent.get('current_version_id'):
        try:
            version_service = await _get_version_service()

            version_obj = await version_service.get_version(
                agent_id=agent_id,
                version_id=agent['current_version_id'],
                user_id=user_id
            )
            version_data = version_obj.to_dict()
        except Exception as e:
            logger.warning(f"Failed to fetch version data for tools endpoint: {e}")
    
    from agent.config_helper import extract_agent_config
    agent_config = extract_agent_config(agent, version_data)
    
    agentpress_tools_config = agent_config['agentpress_tools']
    configured_mcps = agent_config['configured_mcps'] 
    custom_mcps = agent_config['custom_mcps']

    agentpress_tools = []
    for name, enabled in agentpress_tools_config.items():
        is_enabled_tool = bool(enabled.get('enabled', False)) if isinstance(enabled, dict) else bool(enabled)
        agentpress_tools.append({"name": name, "enabled": is_enabled_tool})


    mcp_tools = []
    for mcp in configured_mcps + custom_mcps:
        server = mcp.get('name')
        enabled_tools = mcp.get('enabledTools') or mcp.get('enabled_tools') or []
        for tool_name in enabled_tools:
            mcp_tools.append({"name": tool_name, "server": server, "enabled": True})
    return {"agentpress_tools": agentpress_tools, "mcp_tools": mcp_tools}


@router.get("/threads")
async def get_user_threads(
    user_id: str = Depends(get_current_user_id_from_jwt),
    page: Optional[int] = Query(1, ge=1, description="Page number (1-based)"),
    limit: Optional[int] = Query(1000, ge=1, le=1000, description="Number of items per page (max 1000)")
):
    """获取当前用户的所有对话线程，包含关联的项目数据"""
    logger.info(f"Fetching threads with project data for user: {user_id} (page={page}, limit={limit})")
    client = await db.client
    try:
        # 计算分页偏移量
        offset = (page - 1) * limit
        
        # 步骤1: 从threads表中获取指定用户的所有对话线程，按创建时间倒序排列
        threads_result = await client.table('threads').select('*').eq('account_id', user_id).order('created_at', desc=True).execute()
        
        # 如果没有找到任何线程，返回空结果
        if not threads_result.data:
            logger.info(f"No threads found for user: {user_id}")
            return {
                "threads": [],
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": 0,
                    "pages": 0
                }
            }
        
        # 获取总线程数量
        total_count = len(threads_result.data)
        
        # 步骤2: 对线程数据进行分页处理
        paginated_threads = threads_result.data[offset:offset + limit]
        
        # 步骤3: 提取所有线程中关联的项目ID，并去重
        project_ids = [
            thread['project_id'] for thread in paginated_threads 
            if thread.get('project_id')
        ]
        unique_project_ids = list(set(project_ids)) if project_ids else []
        
        # 步骤4: 如果有项目ID，则批量获取项目数据
        projects_by_id = {}
        if unique_project_ids:
            projects_result = await client.table('projects').select('*').in_('project_id', unique_project_ids).execute()
            
            if projects_result.data:
                logger.info(f"[API] Raw projects from DB: {len(projects_result.data)}")
                # 创建项目ID到项目数据的映射表，便于快速查找
                projects_by_id = {
                    project['project_id']: project 
                    for project in projects_result.data
                }
        
        # 步骤5: 将线程数据与项目数据进行关联映射
        mapped_threads = []
        for thread in paginated_threads:
            project_data = None
            # 如果线程有关联的项目，则获取项目数据
            if thread.get('project_id') and thread['project_id'] in projects_by_id:
                project = projects_by_id[thread['project_id']]
                project_data = {
                    "project_id": project['project_id'],
                    "name": project.get('name', ''),
                    "description": project.get('description', ''),
                    "account_id": project['account_id'],
                    "sandbox": project.get('sandbox', {}),
                    "is_public": project.get('is_public', False),
                    "created_at": project['created_at'],
                    "updated_at": project['updated_at']
                }
            
            # 构建线程数据结构，包含关联的项目信息
            mapped_thread = {
                "thread_id": thread['thread_id'],
                "account_id": thread['account_id'],
                "project_id": thread.get('project_id'),
                "metadata": thread.get('metadata', {}),
                "is_public": thread.get('is_public', False),
                "created_at": thread['created_at'],
                "updated_at": thread['updated_at'],
                "project": project_data  # 关联的项目数据
            }
            mapped_threads.append(mapped_thread)
        
        # 步骤6: 计算总页数
        total_pages = (total_count + limit - 1) // limit if total_count else 0
        
        logger.info(f"[API] Mapped threads for frontend: {len(mapped_threads)} threads, {len(projects_by_id)} unique projects")
        
        # 步骤7: 返回结果，包含线程列表和分页信息
        return {
            "threads": mapped_threads,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": total_pages
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching threads for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch threads: {str(e)}")


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """Get a specific project by ID with complete related data."""
    print(f"🔄 ===== 开始获取项目信息 =====")
    print(f"  📋 project_id: {project_id}")
    print(f"  👤 user_id: {user_id}")
    logger.info(f"Fetching project: {project_id}")
    client = await db.client
    
    try:
        print(f"  📊 获取项目数据...")
        project_result = await client.table('projects').select('*').eq('project_id', project_id).execute()
        
        if not project_result.data:
            print(f"  ❌ 项目未找到: {project_id}")
            raise HTTPException(status_code=404, detail="Project not found")
        
        project = project_result.data[0]
        print(f"  ✅ 项目数据获取成功")
        print(f"    📝 项目信息: name={project.get('name')}, account_id={project.get('account_id')}")
        
        # 验证项目访问权限
        if project.get('account_id') != user_id:
            print(f"  ❌ 项目访问权限被拒绝: account_id={project.get('account_id')}, user_id={user_id}")
            raise HTTPException(status_code=403, detail="Access denied")
        
        print(f"  ✅ 项目访问权限验证通过")
        
        # 获取项目关联的线程
        print(f"  💬 获取项目关联的线程...")
        threads_result = await client.table('threads').select('*').eq('project_id', project_id).order('created_at', desc=True).execute()
        threads_data = []
        if threads_result.data:
            print(f"    📋 找到 {len(threads_result.data)} 个关联线程")
            threads_data = [{
                "thread_id": thread['thread_id'],
                "account_id": thread['account_id'],
                "metadata": thread.get('metadata', {}),
                "is_public": thread.get('is_public', False),
                "created_at": thread['created_at'],
                "updated_at": thread['updated_at']
            } for thread in threads_result.data]
            
            # 打印最近的几个线程
            for i, thread in enumerate(threads_result.data[:3]):  # 只显示前3个
                print(f"      {i+1}. thread_id: {thread['thread_id']}, created_at: {thread['created_at']}")
        else:
            print(f"    ⏭️ 无关联线程")
        
        # 获取项目相关的Agent运行记录
        print(f"  🤖 获取项目相关的Agent运行记录...")
        agent_runs_result = await client.table('agent_runs').select('*').in_('thread_id', [t['thread_id'] for t in threads_data]).order('created_at', desc=True).execute()
        agent_runs_data = []
        if agent_runs_result.data:
            print(f"    📋 找到 {len(agent_runs_result.data)} 条Agent运行记录")
            agent_runs_data = [{
                "id": run['id'],
                "thread_id": run['thread_id'],
                "status": run.get('status', ''),
                "started_at": run.get('started_at'),
                "completed_at": run.get('completed_at'),
                "error": run.get('error'),
                "agent_id": run.get('agent_id'),
                "agent_version_id": run.get('agent_version_id'),
                "created_at": run['created_at']
            } for run in agent_runs_result.data]
            
            # 打印最近的几条运行记录
            for i, run in enumerate(agent_runs_result.data[:3]):  # 只显示前3条
                print(f"      {i+1}. ID: {run['id']}, 状态: {run.get('status', 'N/A')}, 线程: {run.get('thread_id')}")
        else:
            print(f"    ⏭️ 无Agent运行记录")
        
        # 统计项目总消息数
        print(f"  📊 统计项目总消息数...")
        total_message_count = 0
        if threads_data:
            for thread in threads_data:
                message_count_result = await client.schema('public').table('events').select('id', count='exact').eq('session_id', thread['thread_id']).execute()
                thread_message_count = message_count_result.count if message_count_result.count is not None else 0
                total_message_count += thread_message_count
                print(f"    📈 线程 {thread['thread_id']}: {thread_message_count} 条消息")
        
        print(f"    📈 项目总消息数: {total_message_count}")
        
        # 构建返回数据
        print(f"  🔄 构建返回数据...")
        mapped_project = {
            "project_id": project['project_id'],
            "name": project.get('name', ''),
            "description": project.get('description', ''),
            "account_id": project['account_id'],
            "sandbox": project.get('sandbox', {}),
            "is_public": project.get('is_public', False),
            "created_at": project['created_at'],
            "updated_at": project['updated_at'],
            "threads": threads_data,
            "agent_runs": agent_runs_data,
            "total_message_count": total_message_count,
            "thread_count": len(threads_data)
        }
        
        print(f"  ✅ 数据构建完成")
        print(f"    📊 返回数据概览:")
        print(f"      - project_id: {mapped_project['project_id']}")
        print(f"      - name: {mapped_project['name']}")
        print(f"      - account_id: {mapped_project['account_id']}")
        print(f"      - thread_count: {mapped_project['thread_count']}")
        print(f"      - total_message_count: {mapped_project['total_message_count']}")
        print(f"      - agent_runs_count: {len(mapped_project['agent_runs'])}")
        print(f"      - has_sandbox: {bool(mapped_project['sandbox'])}")
        
        logger.info(f"[API] Mapped project for frontend: {project_id} with {len(threads_data)} threads and {total_message_count} total messages")
        print(f"🎉 ===== 项目信息获取完成 =====")
        return mapped_project
        
    except HTTPException:
        print(f"  ❌ HTTP异常: {e}")
        raise
    except Exception as e:
        print(f"  ❌ 获取项目信息失败: {str(e)}")
        logger.error(f"Error fetching project {project_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch project: {str(e)}")


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """Get a specific thread by ID with complete related data."""
    print(f"🔄 ===== 开始获取线程信息 =====")
    print(f"  📋 thread_id: {thread_id}")
    print(f"  👤 user_id: {user_id}")
    logger.info(f"Fetching thread: {thread_id}")
    client = await db.client
    
    try:
        print(f"  🔐 验证线程访问权限...")
        await verify_thread_access(client, thread_id, user_id)
        print(f"  ✅ 线程访问权限验证通过")
        
        # Get the thread data
        print(f"  📊 获取线程数据...")
        thread_result = await client.table('threads').select('*').eq('thread_id', thread_id).execute()
        
        if not thread_result.data:
            print(f"  ❌ 线程未找到: {thread_id}")
            raise HTTPException(status_code=404, detail="Thread not found")
        
        thread = thread_result.data[0]
        print(f"  ✅ 线程数据获取成功")
        print(f"    📝 线程信息: account_id={thread.get('account_id')}, project_id={thread.get('project_id')}")
        
        # Get associated project if thread has a project_id
        print(f"  📁 检查关联项目...")
        project_data = None
        if thread.get('project_id'):
            print(f"    🔍 线程关联项目ID: {thread['project_id']}")
            project_result = await client.table('projects').select('*').eq('project_id', thread['project_id']).execute()
            
            if project_result.data:
                project = project_result.data[0]
                print(f"    ✅ 项目数据获取成功")
                print(f"      📝 项目名称: {project.get('name', 'N/A')}")
                print(f"      📝 项目描述: {project.get('description', 'N/A')}")
                logger.info(f"[API] Raw project from DB for thread {thread_id}")
                project_data = {
                    "project_id": project['project_id'],
                    "name": project.get('name', ''),
                    "description": project.get('description', ''),
                    "account_id": project['account_id'],
                    "sandbox": project.get('sandbox', {}),
                    "is_public": project.get('is_public', False),
                    "created_at": project['created_at'],
                    "updated_at": project['updated_at']
                }
            else:
                print(f"    ⚠️ 项目未找到: {thread['project_id']}")
        else:
            print(f"    ⏭️ 线程无关联项目")
        
        # Get message count for the thread
        print(f"  📊 统计消息数量...")
        # 从ADK events表统计消息数量
        message_count_result = await client.schema('public').table('events').select('id', count='exact').eq('session_id', thread_id).execute()
        message_count = message_count_result.count if message_count_result.count is not None else 0
        print(f"    📈 消息总数: {message_count}")
        
        # Get recent agent runs for the thread
        print(f"  🤖 获取最近的Agent运行记录...")
        agent_runs_result = await client.table('agent_runs').select('*').eq('thread_id', thread_id).order('created_at', desc=True).execute()
        agent_runs_data = []
        if agent_runs_result.data:
            print(f"    📋 找到 {len(agent_runs_result.data)} 条Agent运行记录")
            agent_runs_data = [{
                "id": run['id'],
                "status": run.get('status', ''),
                "started_at": run.get('started_at'),
                "completed_at": run.get('completed_at'),
                "error": run.get('error'),
                "agent_id": run.get('agent_id'),
                "agent_version_id": run.get('agent_version_id'),
                "created_at": run['created_at']
            } for run in agent_runs_result.data]
            
            # 打印最近的几条运行记录
            for i, run in enumerate(agent_runs_result.data[:3]):  # 只显示前3条
                print(f"      {i+1}. ID: {run['id']}, 状态: {run.get('status', 'N/A')}, 开始时间: {run.get('started_at')}")
        else:
            print(f"    ⏭️ 无Agent运行记录")
        
        # Map thread data for frontend (matching actual DB structure)
        print(f"  🔄 构建返回数据...")
        mapped_thread = {
            "thread_id": thread['thread_id'],
            "account_id": thread['account_id'],
            "project_id": thread.get('project_id'),
            "metadata": thread.get('metadata', {}),
            "is_public": thread.get('is_public', False),
            "created_at": thread['created_at'],
            "updated_at": thread['updated_at'],
            "project": project_data,
            "message_count": message_count,
            "recent_agent_runs": agent_runs_data
        }
        
        print(f"  ✅ 数据构建完成")
        print(f"    📊 返回数据概览:")
        print(f"      - thread_id: {mapped_thread['thread_id']}")
        print(f"      - account_id: {mapped_thread['account_id']}")
        print(f"      - project_id: {mapped_thread['project_id']}")
        print(f"      - message_count: {mapped_thread['message_count']}")
        print(f"      - agent_runs_count: {len(mapped_thread['recent_agent_runs'])}")
        print(f"      - has_project: {mapped_thread['project'] is not None}")
        
        logger.info(f"[API] Mapped thread for frontend: {thread_id} with {message_count} messages and {len(agent_runs_data)} recent runs")
        print(f"🎉 ===== 线程信息获取完成 =====")
        return mapped_thread
        
    except HTTPException:
        print(f"  ❌ HTTP异常: {e}")
        raise
    except Exception as e:
        print(f"  ❌ 获取线程信息失败: {str(e)}")
        logger.error(f"Error fetching thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch thread: {str(e)}")


@router.post("/threads", response_model=CreateThreadResponse)
async def create_thread(
    name: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """
    Create a new thread without starting an agent run.

    [WARNING] Keep in sync with initiate endpoint.
    """
    if not name:
        name = "New Project"
    logger.info(f"Creating new thread with name: {name}")
    client = await db.client
    account_id = user_id  # In Basejump, personal account_id is the same as user_id
    
    try:
        # 1. Create Project
        project_name = name or "New Project"
        project = await client.schema('public').table('projects').insert({
            "project_id": str(uuid.uuid4()), 
            "account_id": account_id, 
            "name": project_name,
            "created_at": datetime.now()
        })
        project_id = project.data[0]['project_id']
        logger.info(f"Created new project: {project_id}")

        # 2. Create Sandbox
        sandbox_id = None
        try:
            sandbox_pass = str(uuid.uuid4())
            sandbox = await create_sandbox(sandbox_pass, project_id)
            sandbox_id = sandbox.id
            logger.info(f"Created new sandbox {sandbox_id} for project {project_id}")
            
            # Get preview links
            vnc_link = await sandbox.get_preview_link(6080)
            website_link = await sandbox.get_preview_link(8080)
            vnc_url = vnc_link.url if hasattr(vnc_link, 'url') else str(vnc_link).split("url='")[1].split("'")[0]
            website_url = website_link.url if hasattr(website_link, 'url') else str(website_link).split("url='")[1].split("'")[0]
            token = None
            if hasattr(vnc_link, 'token'):
                token = vnc_link.token
            elif "token='" in str(vnc_link):
                token = str(vnc_link).split("token='")[1].split("'")[0]
        except Exception as e:
            logger.error(f"Error creating sandbox: {str(e)}")
            await client.table('projects').delete().eq('project_id', project_id).execute()
            if sandbox_id:
                try: 
                    await delete_sandbox(sandbox_id)
                except Exception as e: 
                    logger.error(f"Error deleting sandbox: {str(e)}")
            raise Exception("Failed to create sandbox")

        # Update project with sandbox info
        update_result = await client.table('projects').update({
            'sandbox': {
                'id': sandbox_id, 
                'pass': sandbox_pass, 
                'vnc_preview': vnc_url,
                'sandbox_url': website_url, 
                'token': token
            }
        }).eq('project_id', project_id).execute()

        if not update_result.data:
            logger.error(f"Failed to update project {project_id} with new sandbox {sandbox_id}")
            if sandbox_id:
                try: 
                    await delete_sandbox(sandbox_id)
                except Exception as e: 
                    logger.error(f"Error deleting sandbox: {str(e)}")
            raise Exception("Database update failed")

        # 3. Create Thread
        thread_data = {
            "thread_id": str(uuid.uuid4()), 
            "project_id": project_id, 
            "account_id": account_id,
            "created_at": datetime.now()
        }

        structlog.contextvars.bind_contextvars(
            thread_id=thread_data["thread_id"],
            project_id=project_id,
            account_id=account_id,
        )
        
        thread = await client.schema('public').table('threads').insert(thread_data)
        thread_id = thread.data[0]['thread_id']
        logger.info(f"Created new thread: {thread_id}")

        logger.info(f"Successfully created thread {thread_id} with project {project_id}")
        return {"thread_id": thread_id, "project_id": project_id}

    except Exception as e:
        logger.error(f"Error creating thread: {str(e)}\n{traceback.format_exc()}")
        # TODO: Clean up created project/thread if creation fails mid-way
        raise HTTPException(status_code=500, detail=f"Failed to create thread: {str(e)}")


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt),
    order: str = Query("desc", description="Order by created_at: 'asc' or 'desc'")
):
    """Get all messages for a thread, fetching in batches of 1000 from the DB to avoid large queries."""
    logger.info(f"Fetching all messages for thread: {thread_id}, order={order}")
    client = await db.client
    await verify_thread_access(client, thread_id, user_id)
    try:
        batch_size = 1000
        offset = 0
        all_messages = []
        # 🔧 Step 1: 从 messages 表查询系统消息 (assistant, tool, status等)
        all_system_messages = []
        offset = 0
        while True:
            query = client.table('messages').select('*').eq('thread_id', thread_id)
            query = query.order('created_at', desc=(order == "desc"))
            query = query.range(offset, offset + batch_size - 1)
            messages_result = await query.execute()
            batch = messages_result.data or []
            all_system_messages.extend(batch)
            logger.debug(f"Fetched batch of {len(batch)} system messages (offset {offset})")
            if len(batch) < batch_size:
                break
            offset += batch_size
        
        # 🔧 Step 2: 从 events 表查询用户消息
        all_user_events = []
        offset = 0  
        while True:
            query = client.schema('public').table('events').select('*').eq('session_id', thread_id).eq('author', 'user')
            query = query.order('timestamp', desc=(order == "desc"))
            query = query.range(offset, offset + batch_size - 1)
            events_result = await query.execute()
            batch = events_result.data or []
            all_user_events.extend(batch)
            logger.debug(f"Fetched batch of {len(batch)} user events (offset {offset})")
            if len(batch) < batch_size:
                break
            offset += batch_size
        
        # 🔧 Step 3: 转换并合并两种数据源
        system_messages = _format_messages_from_table(all_system_messages)
        user_messages = _convert_user_events_to_messages(all_user_events)
        
        # 🔧 Step 4: 合并并按时间排序
        all_messages = system_messages + user_messages
        all_messages.sort(key=lambda x: x.get('created_at', ''), reverse=(order == "desc"))
        
        # 🔍 详细统计
        system_stats = {}
        for msg in system_messages:
            msg_type = msg.get('type', 'unknown')
            system_stats[msg_type] = system_stats.get(msg_type, 0) + 1
            
        user_stats = {}
        for msg in user_messages:
            msg_type = msg.get('type', 'unknown')  
            user_stats[msg_type] = user_stats.get(msg_type, 0) + 1
        
        all_stats = {}
        for msg in all_messages:
            msg_type = msg.get('type', 'unknown')
            all_stats[msg_type] = all_stats.get(msg_type, 0) + 1
        
        logger.info(f"🔗 合并结果统计:")
        logger.info(f"  📨 系统消息{len(system_messages)}条: {system_stats}")
        logger.info(f"  👤 用户消息{len(user_messages)}条: {user_stats}")
        logger.info(f"  📊 总计{len(all_messages)}条: {all_stats}")
        
        return {"messages": all_messages}
    except Exception as e:
        logger.error(f"Error fetching messages for thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch messages: {str(e)}")

@router.get("/agent-runs/{agent_run_id}")
async def get_agent_run(
    agent_run_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt),
):
    """
    [DEPRECATED] Get an agent run by ID.

    This endpoint is deprecated and may be removed in future versions.
    """
    logger.warning(f"[DEPRECATED] Fetching agent run: {agent_run_id}")
    client = await db.client
    try:
        # 使用正确的访问检查函数
        agent_run_data = await get_agent_run_with_access_check(client, agent_run_id, user_id)
        return agent_run_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent run {agent_run_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch agent run: {str(e)}")  

@router.post("/threads/{thread_id}/messages/add")
async def add_message_to_thread(
    thread_id: str,
    message: str,
    user_id: str = Depends(get_current_user_id_from_jwt),
):
    """Add a message to a thread"""
    logger.info(f"Adding message to thread: {thread_id}")
    client = await db.client
    await verify_thread_access(client, thread_id, user_id)
    try:
        # 使用ADK events表记录用户消息
        message_id = str(uuid.uuid4())
        event_id = await _log_adk_user_message_event(client, user_id, message, thread_id, message_id)
        
        # 返回消息格式（模拟原messages表结构）
        return {
            "message_id": message_id,
            "thread_id": thread_id,
            "type": "user",
            "content": {"role": "user", "content": message},
            "event_id": event_id
        }
    except Exception as e:
        logger.error(f"Error adding message to thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to add message: {str(e)}")

@router.post("/threads/{thread_id}/messages")
async def create_message(
    thread_id: str,
    message_data: MessageCreateRequest,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """Create a new message in a thread."""
    logger.info(f"Creating message in thread: {thread_id}")
    client = await db.client
    
    try:
        await verify_thread_access(client, thread_id, user_id)
        
        message_payload = {
            "role": "user" if message_data.type == "user" else "assistant",
            "content": message_data.content
        }
        
        insert_data = {
            "message_id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "type": message_data.type,
            "is_llm_message": message_data.is_llm_message,
            "content": message_payload,  # Store as JSONB object, not JSON string
            "created_at": datetime.now()
        }
        
        # 使用ADK events表记录消息
        if message_data.type == "user":
            event_id = await _log_adk_user_message_event(client, user_id, message_payload.get("content", ""), thread_id, insert_data["message_id"])
        else:
            event_id = await _log_adk_agent_response_event(client, user_id, message_payload.get("content", ""), thread_id, "unknown")
        
        # 构建返回数据（模拟原messages表结构）
        created_message = {
            "message_id": insert_data["message_id"],
            "thread_id": thread_id,
            "type": message_data.type,
            "is_llm_message": message_data.is_llm_message,
            "content": message_payload,
            "created_at": insert_data["created_at"].isoformat(),
            "event_id": event_id
        }
        
        logger.info(f"Created message: {created_message['message_id']}")
        return created_message
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating message in thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create message: {str(e)}")

@router.delete("/threads/{thread_id}/messages/{message_id}")
async def delete_message(
    thread_id: str,
    message_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    """Delete a message from a thread."""
    logger.info(f"Deleting message from thread: {thread_id}")
    client = await db.client
    await verify_thread_access(client, thread_id, user_id)
    try:
        # Don't allow users to delete the "status" messages
        # 从ADK events表删除消息（通过message_id在content中查找）
        await client.schema('public').table('events').delete().eq('session_id', thread_id).filter('content', 'cs', f'{{"message_id":"{message_id}"}}').execute()
        return {"message": "Message deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting message {message_id} from thread {thread_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete message: {str(e)}")

@router.put("/agents/{agent_id}/custom-mcp-tools")
async def update_agent_custom_mcps(
    agent_id: str,
    request: dict,
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    logger.info(f"Updating agent {agent_id} custom MCPs for user {user_id}")
    
    try:
        client = await db.client
        agent_result = await client.table('agents').select('current_version_id').eq('agent_id', agent_id).eq('account_id', user_id).execute()
        if not agent_result.data:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        agent = agent_result.data[0]
        
        agent_config = {}
        if agent.get('current_version_id'):
            version_result = await client.table('agent_versions')\
                .select('config')\
                .eq('version_id', agent['current_version_id'])\
                .maybe_single()\
                .execute()
            if version_result.data and version_result.data.get('config'):
                agent_config = version_result.data['config']
        
        new_custom_mcps = request.get('custom_mcps', [])
        if not new_custom_mcps:
            raise HTTPException(status_code=400, detail="custom_mcps array is required")
        
        tools = agent_config.get('tools', {})
        existing_custom_mcps = tools.get('custom_mcp', [])
        
        updated = False
        for new_mcp in new_custom_mcps:
            mcp_type = new_mcp.get('type', '')
            
            if mcp_type == 'composio':
                profile_id = new_mcp.get('config', {}).get('profile_id')
                if not profile_id:
                    continue
                    
                for i, existing_mcp in enumerate(existing_custom_mcps):
                    if (existing_mcp.get('type') == 'composio' and 
                        existing_mcp.get('config', {}).get('profile_id') == profile_id):
                        existing_custom_mcps[i] = new_mcp
                        updated = True
                        break
                
                if not updated:
                    existing_custom_mcps.append(new_mcp)
                    updated = True
            else:
                mcp_url = new_mcp.get('config', {}).get('url')
                mcp_name = new_mcp.get('name', '')
                
                for i, existing_mcp in enumerate(existing_custom_mcps):
                    if (existing_mcp.get('config', {}).get('url') == mcp_url or 
                        (mcp_name and existing_mcp.get('name') == mcp_name)):
                        existing_custom_mcps[i] = new_mcp
                        updated = True
                        break
                
                if not updated:
                    existing_custom_mcps.append(new_mcp)
                    updated = True
        
        tools['custom_mcp'] = existing_custom_mcps
        agent_config['tools'] = tools
        
        from agent.versioning.version_service import get_version_service
        import datetime
        
        try:
            version_service = await get_version_service()
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            change_description = f"MCP tools update {timestamp}"
            
            new_version = await version_service.create_version(
                agent_id=agent_id,
                user_id=user_id,
                system_prompt=agent_config.get('system_prompt', ''),
                configured_mcps=agent_config.get('tools', {}).get('mcp', []),
                custom_mcps=existing_custom_mcps,
                agentpress_tools=agent_config.get('tools', {}).get('agentpress', {}),
                change_description=change_description
            )
            logger.info(f"Created version {new_version.version_id} for agent {agent_id}")
            
            total_enabled_tools = sum(len(mcp.get('enabledTools', [])) for mcp in new_custom_mcps)
        except Exception as e:
            logger.error(f"Failed to create version for custom MCP tools update: {e}")
            raise HTTPException(status_code=500, detail="Failed to save changes")
        
        return {
            'success': True,
            'data': {
                'custom_mcps': existing_custom_mcps,
                'total_enabled_tools': total_enabled_tools
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating agent custom MCPs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/tools/export-presentation")
async def export_presentation(
    request: Dict[str, Any] = Body(...),
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    try:
        presentation_name = request.get("presentation_name")
        export_format = request.get("format", "pptx")
        project_id = request.get("project_id")
        
        if not presentation_name:
            raise HTTPException(status_code=400, detail="presentation_name is required")
        
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        
        if db is None:
            db_conn = DBConnection()
            client = await db_conn.client
        else:
            client = await db.client
            
        project_result = await client.table('projects').select('sandbox').eq('project_id', project_id).execute()
        if not project_result.data:
            raise HTTPException(status_code=404, detail="Project not found")
        
        sandbox_data = project_result.data[0].get('sandbox', {})
        sandbox_id = sandbox_data.get('id')
        
        if not sandbox_id:
            raise HTTPException(status_code=400, detail="No sandbox found for this project")
        
        thread_manager = ThreadManager()
        
        presentation_tool = SandboxPresentationToolV2(
            project_id=project_id,
            thread_manager=thread_manager
        )
        
        result = await presentation_tool.export_presentation(
            presentation_name=presentation_name,
            format=export_format
        )
        
        if result.success:
            import json
            import urllib.parse
            data = json.loads(result.output)
            
            export_file = data.get("export_file")
            logger.info(f"Export file from tool: {export_file}")
            logger.info(f"Sandbox ID: {sandbox_id}")
            
            if export_file:
                from fastapi.responses import Response
                from sandbox.api import get_sandbox_by_id_safely, verify_sandbox_access
                
                try:
                    file_path = export_file.replace("/workspace/", "").lstrip("/")
                    full_path = f"/workspace/{file_path}"
                    
                    sandbox = await get_sandbox_by_id_safely(client, sandbox_id)
                    file_content = await sandbox.fs.download_file(full_path)
                    
                    return {
                        "success": True,
                        "message": data.get("message"),
                        "file_content": base64.b64encode(file_content).decode('utf-8'),
                        "filename": export_file.split('/')[-1],
                        "export_file": data.get("export_file"),
                        "format": data.get("format"),
                        "file_size": data.get("file_size")
                    }
                except Exception as e:
                    logger.error(f"Failed to read exported file: {str(e)}")
                    return {
                        "success": False,
                        "error": f"Failed to read exported file: {str(e)}"
                    }
            else:
                return {
                    "success": True,
                    "message": data.get("message"),
                    "download_url": data.get("download_url"),
                    "export_file": data.get("export_file"),
                    "format": data.get("format"),
                    "file_size": data.get("file_size")
                }
        else:
            raise HTTPException(status_code=400, detail=result.output or "Export failed")
            
    except Exception as e:
        logger.error(f"Export presentation error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to export presentation: {str(e)}")
@router.post("/agents/profile-image/upload")
async def upload_agent_profile_image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id_from_jwt)
):
    try:
        content_type = file.content_type or "image/png"
        image_bytes = await file.read()
        from utils.s3_upload_utils import upload_image_bytes
        public_url = await upload_image_bytes(image_bytes=image_bytes, content_type=content_type, bucket_name="agent-profile-images")
        return {"url": public_url}
    except Exception as e:
        logger.error(f"Failed to upload agent profile image for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload profile image")

async def _create_adk_session_if_not_exists(client, user_id: str, session_id: str, app_name: str = "fufanmanus"):
    """如果ADK session不存在则创建"""
    try:
        # 检查session是否已存在
        async with client.pool.acquire() as conn:
            existing = await conn.fetchrow(
                """
                SELECT id FROM sessions 
                WHERE app_name = $1 AND user_id = $2 AND id = $3
                """,
                app_name, user_id, session_id
            )
            
            if not existing:
                # 不存在则创建
                await conn.execute(
                    """
                    INSERT INTO sessions (
                        app_name, user_id, id, state, create_time, update_time
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    app_name, user_id, session_id, '{}', datetime.now(), datetime.now()
                )
                logger.info(f"Created ADK session: {session_id}")
            else:
                logger.debug(f"ADK session already exists: {session_id}")
                
    except Exception as e:
        logger.error(f"Create ADK session failed: {e}")
        raise

async def _log_adk_user_message_event(client, user_id: str, message_content: str, session_id: str, message_id: str, app_name: str = "fufanmanus"):
    """记录用户消息事件到ADK events表"""
    try:
        import uuid
        import pickle
        from datetime import datetime

        event_id = str(uuid.uuid4())
        invocation_id = str(uuid.uuid4())
        
        # 使用 ADK 标准格式（ADK 不接受 content 字段，只接受 parts）
        content = {
            "role": "user", 
            "parts": [{"text": message_content}]  # ADK 标准格式
        }
        
        # actions 需要手动序列化为字节（这是ADK的格式要求）
        actions_dict = {
            "skip_summarization": None,
            "state_delta": {},
            "artifact_delta": {},
            "transfer_to_agent": None,
            "escalate": None,
            "requested_auth_configs": {}
        }
        
        # 手动序列化 actions 字典为字节（这是ADK的格式要求）
        actions_bytes = pickle.dumps(actions_dict)
        
        # 插入到ADK events表
        async with client.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events (
                    id, app_name, user_id, session_id, invocation_id, 
                    author, timestamp, content, actions
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                event_id, app_name, user_id, session_id, invocation_id,
                "user", datetime.now(), json.dumps(content), actions_bytes  
            )
        
        logger.info(f"User message event recorded successfully: {event_id}")
        return event_id
        
    except Exception as e:
        logger.error(f"Record user message event failed: {e}")
        raise

async def _log_adk_agent_response_event(client, user_id: str, response_content: str, session_id: str, model_name: str, app_name: str = "fufanmanus"):
    """记录AI代理回复事件到ADK events表"""
    try:
        import uuid
        event_id = str(uuid.uuid4())
        invocation_id = str(uuid.uuid4())
        
        # 构建回复内容
        content = {            "role": "assistant",
            "content": response_content,
            "model": model_name
        }
        
        # 插入到ADK events表
        async with client.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events (
                    id, app_name, user_id, session_id, invocation_id, 
                    author, timestamp, content, actions, turn_complete
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                event_id, app_name, user_id, session_id, invocation_id,
                "assistant", datetime.now(), json.dumps(content), b'', True  # turn_complete=True
            )
        
        logger.info(f"记录AI回复事件成功: {event_id}")
        return event_id
        
    except Exception as e:
        logger.error(f"记录AI回复事件失败: {e}")
        raise

def _format_messages_from_table(messages):
    """格式化messages表数据为前端期望格式，支持assistant消息动态拆分"""
    formatted_messages = []
    
    # 🔍 调试：检查原始数据库消息
    logger.info(f"🔍 数据库原始消息数量: {len(messages)}")
    raw_message_stats = {}
    for msg in messages:
        msg_type = msg.get('type', 'unknown')
        raw_message_stats[msg_type] = raw_message_stats.get(msg_type, 0) + 1
    logger.info(f"🔍 原始消息类型统计: {raw_message_stats}")
    
    # 🔍 特别检查原始assistant消息
    raw_assistant_messages = [msg for msg in messages if msg.get('type') == 'assistant']
    if raw_assistant_messages:
        for assistant_msg in raw_assistant_messages:
            raw_msg_id = assistant_msg.get('message_id')
            logger.info(f"🔍 发现原始assistant消息: ID={raw_msg_id} (类型: {type(raw_msg_id)}), metadata预览={str(assistant_msg.get('metadata', ''))[:200]}...")
    else:
        logger.warning("⚠️ 数据库查询结果中没有assistant消息！")
    
    for msg in messages:
        try:
            # 🔧 处理content字段 - 解析为对象以便后续判断
            content = msg.get('content', {})
            content_obj = content
            if isinstance(content, str):
                try:
                    import json
                    content_obj = json.loads(content)
                    content_str = content
                except:
                    content_str = str(content) if content else "{}"
                    content_obj = {}
            elif isinstance(content, dict):
                import json
                content_str = json.dumps(content, ensure_ascii=False)
                content_obj = content
            else:
                content_str = str(content) if content else "{}"
                content_obj = {}
            
            # 🔧 处理metadata字段 - 解析为对象以便后续判断
            metadata = msg.get('metadata', {})
            metadata_obj = metadata
            if isinstance(metadata, str):
                try:
                    import json
                    metadata_obj = json.loads(metadata)
                    metadata_str = metadata
                except:
                    metadata_str = str(metadata) if metadata else "{}"
                    metadata_obj = {}
            elif isinstance(metadata, dict):
                import json
                metadata_str = json.dumps(metadata, ensure_ascii=False)
                metadata_obj = metadata
            else:
                metadata_str = str(metadata) if metadata else "{}"
                metadata_obj = {}
            
            # 🔧 检查是否需要拆分assistant消息
            if (msg.get("type") == "assistant" and 
                metadata_obj.get("split_for_frontend") == True and
                metadata_obj.get("tool_call_mapping")):
                
                logger.info(f"🔧 检测到需要拆分的assistant消息: {msg.get('message_id')}")
                tool_call_mapping = metadata_obj.get("tool_call_mapping", [])
                assistant_text = content_obj.get("content", "")
                tool_calls = content_obj.get("tool_calls", [])
                
                # 为每个tool_call创建单独的assistant消息
                for mapping in tool_call_mapping:
                    index = mapping.get("index", 0)
                    tool_call_id = mapping.get("tool_call_id", "")
                    include_text = mapping.get("include_text", False)
                    
                    # 找到对应的tool_call对象
                    matching_tool_call = None
                    for tc in tool_calls:
                        if tc.get("id") == tool_call_id:
                            matching_tool_call = tc
                            break
                    
                    if matching_tool_call:
                        # 🔧 生成确定性UUID（与agent/run.py保持一致）
                        import hashlib
                        seed_data = f"assistant_split_{tool_call_id}_{msg.get('thread_id')}_{index}_v1"
                        hash_object = hashlib.md5(seed_data.encode())
                        hex_dig = hash_object.hexdigest()
                        deterministic_uuid = f"{hex_dig[:8]}-{hex_dig[8:12]}-{hex_dig[12:16]}-{hex_dig[16:20]}-{hex_dig[20:]}"
                        
                        # 构建拆分后的消息内容
                        split_content = {
                            "role": "assistant",
                            "content": assistant_text if include_text else "",
                            "tool_calls": [matching_tool_call]
                        }
                        
                        # 构建拆分后的元数据
                        split_metadata = metadata_obj.copy()
                        split_metadata["tool_index"] = index
                        split_metadata["original_message_id"] = str(msg.get("message_id")) if msg.get("message_id") else None
                        
                        # 创建拆分后的消息 - 确保所有UUID字段都是字符串
                        split_message = {
                            "message_id": deterministic_uuid,
                            "thread_id": str(msg.get("thread_id")) if msg.get("thread_id") else None,
                            "type": "assistant",
                            "role": "assistant",
                            "is_llm_message": msg.get("is_llm_message", False),
                            "content": json.dumps(split_content, ensure_ascii=False),
                            "metadata": json.dumps(split_metadata, ensure_ascii=False),
                            "created_at": msg.get("created_at"),
                            "updated_at": msg.get("updated_at"),
                            "agent_id": str(msg.get("agent_id")) if msg.get("agent_id") else None,
                            "agent_version_id": str(msg.get("agent_version_id")) if msg.get("agent_version_id") else None
                        }
                        
                        formatted_messages.append(split_message)
                        logger.info(f"✅ 拆分assistant消息: {deterministic_uuid} (tool: {matching_tool_call.get('function', {}).get('name', 'unknown')})")
                        logger.debug(f"🔍 拆分消息字段类型检查: message_id={type(deterministic_uuid)}, thread_id={type(split_message['thread_id'])}")
                
            else:
                # 🔧 普通消息处理逻辑 - 确保所有UUID字段都是字符串
                formatted_message = {
                    "message_id": str(msg.get("message_id")) if msg.get("message_id") else None,
                    "thread_id": str(msg.get("thread_id")) if msg.get("thread_id") else None,
                    "type": msg.get("type"),  # assistant, user, tool, status等
                    "role": msg.get("role"),  # assistant, user, system等
                    "is_llm_message": msg.get("is_llm_message", False),
                    "content": content_str,     # JSON字符串格式
                    "metadata": metadata_str,   # JSON字符串格式  
                    "created_at": msg.get("created_at"),
                    "updated_at": msg.get("updated_at"),
                    "agent_id": str(msg.get("agent_id")) if msg.get("agent_id") else None,
                    "agent_version_id": str(msg.get("agent_version_id")) if msg.get("agent_version_id") else None
                }
                
                formatted_messages.append(formatted_message)
            
        except Exception as e:
            logger.warning(f"跳过格式错误的消息 {msg.get('message_id', 'unknown')}: {e}")
            continue
    
                # 🔧 更新tool消息的assistant_message_id关联
    assistant_messages = [msg for msg in formatted_messages if msg.get('type') == 'assistant']
    tool_messages = [msg for msg in formatted_messages if msg.get('type') == 'tool']
    
    # 创建tool_call_id到assistant_message_id的映射
    tool_call_to_assistant = {}
    for assistant_msg in assistant_messages:
        try:
            content = assistant_msg.get('content', {})
            if isinstance(content, str):
                content = json.loads(content)
            
            tool_calls = content.get('tool_calls', [])
            for tool_call in tool_calls:
                tool_call_id = tool_call.get('id')
                if tool_call_id:
                    tool_call_to_assistant[tool_call_id] = assistant_msg.get('message_id')
        except Exception as e:
            logger.warning(f"⚠️ 解析assistant消息content失败: {e}")
    
    # 更新tool消息的assistant_message_id
    updated_tool_count = 0
    for tool_msg in tool_messages:
        try:
            metadata = tool_msg.get('metadata', {})
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            
            tool_call_id = metadata.get('tool_call_id')
            if tool_call_id and tool_call_id in tool_call_to_assistant:
                correct_assistant_id = tool_call_to_assistant[tool_call_id]
                metadata['assistant_message_id'] = correct_assistant_id
                tool_msg['metadata'] = json.dumps(metadata, ensure_ascii=False)
                updated_tool_count += 1
                logger.info(f"🔗 更新tool消息 {tool_msg.get('message_id')} -> assistant {correct_assistant_id}")
        except Exception as e:
            logger.warning(f"⚠️ 更新tool消息关联失败 {tool_msg.get('message_id')}: {e}")
    
    # 🔍 最终统计
    logger.info(f"🤖 最终Assistant消息数量: {len(assistant_messages)}")
    logger.info(f"🔧 Tool消息数量: {len(tool_messages)}")
    logger.info(f"🔗 更新了 {updated_tool_count} 个tool消息的关联")
    
    return formatted_messages

def _convert_user_events_to_messages(events):
    """将用户events转换为前端期望的消息格式"""
    user_messages = []
    
    for event in events:
        try:
            # 🔧 解析content字段
            content = event.get('content')
            if isinstance(content, str):
                import json
                content = json.loads(content)
            
            # 🔧 提取用户文本内容
            user_text = ""
            if isinstance(content, dict) and 'parts' in content:
                text_parts = []
                for part in content['parts']:
                    if isinstance(part, dict) and 'text' in part:
                        text_parts.append(part['text'].strip())
                user_text = ' '.join(text_parts).strip()
            elif isinstance(content, dict) and 'content' in content:
                user_text = content['content']
            else:
                user_text = str(content)
            
            # 🔧 构建前端期望的用户消息格式
            import json
            user_content = {
                "role": "user",
                "content": user_text
            }
            
            formatted_message = {
                "message_id": str(event.get("id")) if event.get("id") else None,
                "thread_id": str(event.get("session_id")) if event.get("session_id") else None,
                "type": "user",
                "role": "user", 
                "is_llm_message": False,
                "content": json.dumps(user_content, ensure_ascii=False),  # JSON字符串
                "metadata": "{}",  # 空metadata
                "created_at": event.get("timestamp"),
                "updated_at": event.get("timestamp"),  # 使用timestamp作为updated_at
                "agent_id": None,
                "agent_version_id": None
            }
            
            user_messages.append(formatted_message)
            logger.debug(f"转换用户消息: {event.get('id')} - {user_text[:50]}{'...' if len(user_text) > 50 else ''}")
            
        except Exception as e:
            logger.warning(f"跳过格式错误的用户事件 {event.get('id', 'unknown')}: {e}")
            continue
    
    logger.info(f"🔄 转换了 {len(user_messages)} 条用户消息")
    return user_messages
