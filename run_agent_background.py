import dotenv
dotenv.load_dotenv(".env")

print("🚀 ===== run_agent_background.py 文件已加载 =====")

import sentry
import asyncio
import json
import traceback
from datetime import datetime, timezone
from typing import Optional
from services import redis
from agent.run import run_agent
from utils.logger import logger, structlog
import dramatiq # type: ignore
import uuid
from agentpress.thread_manager import ThreadManager
from services.postgresql import DBConnection
from services import redis
from dramatiq.brokers.redis import RedisBroker # type: ignore
import os
from services.langfuse import langfuse
from utils.retry import retry

import sentry_sdk # type: ignore
from typing import Dict, Any

# 使用与 services/redis.py 相同的配置
redis_host = os.getenv('REDIS_HOST', 'redis')
redis_port = int(os.getenv('REDIS_PORT', 6379))
redis_password = os.getenv('REDIS_PASSWORD', '')
redis_db = int(os.getenv('REDIS_DB', 0))

print(f"🔧 ===== Redis Broker配置 =====")
print(f"  📍 主机: {redis_host}")
print(f"  🚪 端口: {redis_port}")
print(f"  🔑 密码: {'已设置' if redis_password else '无'}")
print(f"  🗄️ 数据库: {redis_db}")

# 创建Redis broker，使用与 services/redis.py 相同的配置
if redis_password:
    redis_broker = RedisBroker(
        host=redis_host, 
        port=redis_port, 
        password=redis_password,
        db=redis_db,
        middleware=[dramatiq.middleware.AsyncIO()]
    )
else:
    redis_broker = RedisBroker(
        host=redis_host, 
        port=redis_port, 
        db=redis_db,
        middleware=[dramatiq.middleware.AsyncIO()]
    )

dramatiq.set_broker(redis_broker)
print(f"  ✅ Redis broker配置完成")
print(f"🚀 ===== run_agent_background.py 初始化完成 =====")


_initialized = False
db = DBConnection()
instance_id = "single"

async def initialize():
    """Initialize the agent API with resources from the main API."""
    global db, instance_id, _initialized

    if not instance_id:
        instance_id = str(uuid.uuid4())[:8]
    await retry(lambda: redis.initialize_async())
    await db.initialize()

    _initialized = True
    logger.info(f"Initialized agent API with instance ID: {instance_id}")

@dramatiq.actor
async def check_health(key: str):
    """Run the agent in the background using Redis for state."""
    structlog.contextvars.clear_contextvars()
    await redis.set(key, "healthy", ex=redis.REDIS_KEY_TTL)

@dramatiq.actor
async def run_agent_background(
    agent_run_id: str,
    thread_id: str,
    instance_id: str, # Use the global instance ID passed during initialization
    project_id: str,
    model_name: str,
    enable_thinking: Optional[bool],
    reasoning_effort: Optional[str],
    stream: bool,
    enable_context_manager: bool,
    agent_config: Optional[dict] = None,
    is_agent_builder: Optional[bool] = False,
    target_agent_id: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """Run the agent in the background using Redis for state."""
    print(f" ===== 后台Agent任务开始执行 =====")
    print(f"  agent_run_id: {agent_run_id}")
    print(f"  thread_id: {thread_id}")
    print(f"  instance_id: {instance_id}")
    print(f"  project_id: {project_id}")
    print(f"  model_name: {model_name}")
    if agent_config:
        print(f"  - agent_config: {agent_config}")
    else:
        print(f"  - agent_config: None")
    
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
        thread_id=thread_id,
        request_id=request_id,
    )
    print(f"  ✅ Structlog上下文变量设置完成")

    print(f"🔄 ===== 初始化阶段 =====")
    try:
        print(f"  🔄 开始初始化...")
        await initialize()
        print(f"  ✅ 初始化完成")
    except Exception as e:
        print(f"  ❌ 初始化失败: {e}")
        logger.critical(f"Failed to initialize Redis connection: {e}")
        raise e

    print(f"🔒 ===== 幂等性检查 =====")
    # Idempotency check: prevent duplicate runs
    run_lock_key = f"agent_run_lock:{agent_run_id}"
    print(f"  🔒 运行锁键: {run_lock_key}")
    
    # Try to acquire a lock for this agent run
    print(f"  🔄 尝试获取运行锁...")
    try:
        print(f"    📡 调用Redis SET命令...")
        lock_acquired = await redis.set(run_lock_key, instance_id, nx=True, ex=redis.REDIS_KEY_TTL)
        print(f"    ✅ Redis SET命令完成")
        print(f"  📊 锁获取结果: {lock_acquired}")
    except Exception as redis_error:
        print(f"    ❌ Redis锁操作失败: {redis_error}")
        print(f"    📋 错误详情: {traceback.format_exc()}")
        logger.error(f"Redis lock operation failed: {redis_error}")
        raise redis_error
    
    if not lock_acquired:
        print(f"  ⚠️ 锁获取失败，检查是否已有其他实例在处理...")
        # Check if the run is already being handled by another instance
        try:
            print(f"    📡 调用Redis GET命令...")
            existing_instance = await redis.get(run_lock_key)
            print(f"    ✅ Redis GET命令完成")
            print(f"  📋 现有实例: {existing_instance}")
        except Exception as redis_error:
            print(f"    ❌ Redis GET操作失败: {redis_error}")
            print(f"    📋 错误详情: {traceback.format_exc()}")
            logger.error(f"Redis GET operation failed: {redis_error}")
            raise redis_error
        if existing_instance:
            existing_instance_str = existing_instance.decode() if isinstance(existing_instance, bytes) else existing_instance
            print(f"  🚫 Agent运行 {agent_run_id} 已由实例 {existing_instance_str} 处理中，跳过重复执行")
            logger.info(f"Agent run {agent_run_id} is already being processed by instance {existing_instance_str}. Skipping duplicate execution.")
            return
        else:
            print(f"  🔄 锁存在但无值，再次尝试获取...")
            # Lock exists but no value, try to acquire again
            try:
                print(f"    📡 调用Redis第二次SET命令...")
                lock_acquired = await redis.set(run_lock_key, instance_id, nx=True, ex=redis.REDIS_KEY_TTL)
                print(f"    ✅ Redis第二次SET命令完成")
                print(f"  📊 第二次锁获取结果: {lock_acquired}")
            except Exception as redis_error:
                print(f"    ❌ Redis第二次锁操作失败: {redis_error}")
                print(f"    📋 错误详情: {traceback.format_exc()}")
                logger.error(f"Redis second lock operation failed: {redis_error}")
                raise redis_error
            if not lock_acquired:
                print(f"  🚫 Agent运行 {agent_run_id} 已由其他实例处理中，跳过重复执行")
                logger.info(f"Agent run {agent_run_id} is already being processed by another instance. Skipping duplicate execution.")
                return
    else:
        print(f"  ✅ 成功获取运行锁")

    print(f"🏷️ ===== Sentry标签设置 =====")
    try:
        sentry.sentry.set_tag("thread_id", thread_id)
        print(f"  ✅ Sentry标签设置完成")
    except Exception as sentry_error:
        print(f"  ⚠️ Sentry标签设置失败: {sentry_error}")
        print(f"  📋 错误详情: {traceback.format_exc()}")
        logger.warning(f"Sentry tag setting failed: {sentry_error}")
        # 继续执行，不中断流程

    print(f"📝 ===== 日志记录 =====")
    try:
        logger.info(f"Starting background agent run: {agent_run_id} for thread: {thread_id} (Instance: {instance_id})")
        logger.info({
            "model_name": model_name,
            "enable_thinking": enable_thinking,
            "reasoning_effort": reasoning_effort,
            "stream": stream,
            "enable_context_manager": enable_context_manager,
            "agent_config": agent_config,
            "is_agent_builder": is_agent_builder,
            "target_agent_id": target_agent_id,
        })
        print(f"  ✅ 日志记录完成")
    except Exception as log_error:
        print(f"  ⚠️ 日志记录失败: {log_error}")
        print(f"  📋 错误详情: {traceback.format_exc()}")
        # 继续执行，不中断流程
    
    print(f"🤖 ===== 模型选择逻辑 =====")
    try:
        print(f"  📋 输入模型名称: {model_name}")
        effective_model = model_name
        if model_name == "anthropic/claude-sonnet-4-20250514" and agent_config and agent_config.get('model'):
            agent_model = agent_config['model']
            print(f"  🔄 使用Agent配置中的模型: {agent_model}")
            from utils.constants import MODEL_NAME_ALIASES
            resolved_agent_model = MODEL_NAME_ALIASES.get(agent_model, agent_model)
            effective_model = resolved_agent_model
            print(f"  ✅ 模型解析结果: {agent_model} -> {effective_model}")
            logger.info(f"Using model from agent config: {agent_model} -> {effective_model} (no user selection)")
        else:
            print(f"  🔄 使用用户选择或默认模型")
            from utils.constants import MODEL_NAME_ALIASES
            effective_model = MODEL_NAME_ALIASES.get(model_name, model_name)
            if model_name != "anthropic/claude-sonnet-4-20250514":
                print(f"  ✅ 用户选择模型: {model_name} -> {effective_model}")
            logger.info(f"Using user-selected model: {model_name} -> {effective_model}")
        
        print(f"  ✅ 最终模型: {effective_model}")
        logger.info(f"Using model: {effective_model}")
        print(f"  🎯 最终有效模型: {effective_model}")
        print(f"  🧠 思考模式: {enable_thinking}, 推理努力: {reasoning_effort}")
        
        logger.info(f"🚀 Using model: {effective_model} (thinking: {enable_thinking}, reasoning_effort: {reasoning_effort})")
        if agent_config:
            print(f"  🤖 使用自定义Agent: {agent_config.get('name', 'Unknown')}")
            logger.info(f"Using custom agent: {agent_config.get('name', 'Unknown')}")
        else:
            print(f"  🤖 使用默认Agent配置")
    except Exception as model_error:
        print(f"  ❌ 模型选择逻辑失败: {model_error}")
        print(f"  📋 错误详情: {traceback.format_exc()}")
        logger.error(f"Model selection logic failed: {model_error}")
        raise model_error

    print(f"🔗 ===== 数据库连接和变量初始化 =====")
    try:
        client = await db.client
        print(f"  ✅ 数据库客户端获取成功")
    except Exception as db_error:
        print(f"  ❌ 数据库客户端获取失败: {db_error}")
        print(f"  📋 错误详情: {traceback.format_exc()}")
        logger.error(f"Database client acquisition failed: {db_error}")
        raise db_error
    
    start_time = datetime.now(timezone.utc)
    total_responses = 0
    pubsub = None
    stop_checker = None
    stop_signal_received = False
    pending_redis_operations = []  # 初始化这个变量
    print(f"  📅 开始时间: {start_time}")
    print(f"  📊 初始响应计数: {total_responses}")

    print(f"🔑 ===== Redis键和频道定义 =====")
    # Define Redis keys and channels
    response_list_key = f"agent_run:{agent_run_id}:responses"
    response_channel = f"agent_run:{agent_run_id}:new_response"
    instance_control_channel = f"agent_run:{agent_run_id}:control:{instance_id}"
    global_control_channel = f"agent_run:{agent_run_id}:control"
    instance_active_key = f"active_run:{instance_id}:{agent_run_id}"
    
    print(f"  📋 Redis配置:")
    print(f"    - response_list_key: {response_list_key}")
    print(f"    - response_channel: {response_channel}")
    print(f"    - instance_control_channel: {instance_control_channel}")
    print(f"    - global_control_channel: {global_control_channel}")
    print(f"    - instance_active_key: {instance_active_key}")

    async def check_for_stop_signal():
        nonlocal stop_signal_received
        print(f"    🛑 停止信号检查器启动")
        if not pubsub: 
            print(f"    ⚠️ PubSub未初始化，退出检查器")
            return
        try:
            while not stop_signal_received:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, bytes): data = data.decode('utf-8')
                    if data == "STOP":
                        print(f"    🛑 收到STOP信号")
                        logger.info(f"Received STOP signal for agent run {agent_run_id} (Instance: {instance_id})")
                        stop_signal_received = True
                        break
                # Periodically refresh the active run key TTL
                if total_responses % 50 == 0: # Refresh every 50 responses or so
                    try: 
                        await redis.expire(instance_active_key, redis.REDIS_KEY_TTL)
                        print(f"    🔄 刷新TTL (响应计数: {total_responses})")
                    except Exception as ttl_err: 
                        print(f"    ⚠️ TTL刷新失败: {ttl_err}")
                        logger.warning(f"Failed to refresh TTL for {instance_active_key}: {ttl_err}")
                await asyncio.sleep(0.1) # Short sleep to prevent tight loop
        except asyncio.CancelledError:
            print(f"    🚫 停止信号检查器被取消")
            logger.info(f"Stop signal checker cancelled for {agent_run_id} (Instance: {instance_id})")
        except Exception as e:
            print(f"    ❌ 停止信号检查器错误: {e}")
            logger.error(f"Error in stop signal checker for {agent_run_id}: {e}", exc_info=True)
            stop_signal_received = True # Stop the run if the checker fails

    print(f"📊 ===== Langfuse跟踪初始化 =====")
    trace = langfuse.trace(name="agent_run", id=agent_run_id, session_id=thread_id, metadata={"project_id": project_id, "instance_id": instance_id})
    print(f"  ✅ Langfuse跟踪创建成功")
    
    print(f"📡 ===== Pub/Sub设置 =====")
    try:
        # Setup Pub/Sub listener for control signals
        print(f"  🔄 创建PubSub连接...")
        pubsub = await redis.create_pubsub()
        print(f"  ✅ PubSub连接创建成功")
        
        try:
            print(f"  🔄 订阅控制频道...")
            await retry(lambda: pubsub.subscribe(instance_control_channel, global_control_channel))
            print(f"  ✅ 控制频道订阅成功")
        except Exception as e:
            print(f"  ❌ Redis订阅控制频道失败: {e}")
            logger.error(f"Redis failed to subscribe to control channels: {e}", exc_info=True)
            raise e

        logger.debug(f"Subscribed to control channels: {instance_control_channel}, {global_control_channel}")
        print(f"  🔄 启动停止信号检查器...")
        stop_checker = asyncio.create_task(check_for_stop_signal())
        print(f"  ✅ 停止信号检查器启动成功")

        print(f"  🔄 设置活跃运行键...")
        # Ensure active run key exists and has TTL
        await redis.set(instance_active_key, "running", ex=redis.REDIS_KEY_TTL)
        print(f"  ✅ 活跃运行键设置成功")


        print(f"🚀 ===== Agent生成器初始化 =====")
        # Initialize agent generator
        print(f"  🔄 创建Agent生成器...")
        try:
            print(f"    📡 准备调用run_agent函数...")
            print(f"      📋 参数详情:")
            print(f"        - thread_id: {thread_id}")
            print(f"        - project_id: {project_id}")
            print(f"        - stream: {stream}")
            print(f"        - model_name: {effective_model}")
            
            print(f"    📡 开始调用run_agent函数...")
            agent_gen = run_agent(
                thread_id=thread_id, project_id=project_id, stream=stream,
                model_name=effective_model,
                enable_thinking=enable_thinking, reasoning_effort=reasoning_effort,
                enable_context_manager=enable_context_manager,
                agent_config=agent_config,
                trace=trace,
                is_agent_builder=is_agent_builder,
                target_agent_id=target_agent_id
            )
            print(f"    ✅ run_agent函数调用成功，返回生成器对象")
            print(f"  ✅ Agent生成器创建成功")
        except Exception as agent_error:
            print(f"    ❌ run_agent函数调用失败: {agent_error}")
            print(f"    📋 错误详情: {traceback.format_exc()}")
            logger.error(f"Failed to call run_agent: {agent_error}")
            raise agent_error

        final_status = "running"
        error_message = None
        pending_redis_operations = []

        print(f"  📊 初始状态: {final_status}")
        print(f"  📝 错误消息: {error_message}")
        print(f"  📋 待处理Redis操作: {len(pending_redis_operations)}")

        print(f"🔄 ===== 开始处理Agent响应流 =====")
        print(f"  📡 开始迭代agent_gen生成器...")
        response_count = 0
        async for response in agent_gen:
            response_count += 1
            print(f"  📨 收到第 {response_count} 个响应:")
            print(f"    📋 响应类型: {response.get('type', 'unknown')}")
            print(f"    📝 响应内容: {str(response)[:200]}...")
            if stop_signal_received:
                print(f"  🛑 收到停止信号，停止Agent运行")
                logger.info(f"Agent run {agent_run_id} stopped by signal.")
                final_status = "stopped"
                try:
                    trace.span(name="agent_run_stopped").end(status_message="agent_run_stopped", level="WARNING")
                except Exception as trace_error:
                    print(f"  ⚠️ Trace记录失败: {trace_error}")
                break

            # Store response in Redis list and publish notification
            response_json = json.dumps(response)
            pending_redis_operations.append(asyncio.create_task(redis.rpush(response_list_key, response_json)))
            pending_redis_operations.append(asyncio.create_task(redis.publish(response_channel, "new")))
            total_responses += 1
            
            if total_responses % 10 == 1:  # 每10个响应打印一次进度
                print(f"  📊 已处理响应数量: {total_responses}")
                print(f"  📝 当前响应类型: {response.get('type', 'unknown')}")
                print(f"  📋 待处理Redis操作: {len(pending_redis_operations)}")

            # Check for agent-signaled completion or error
            if response.get('type') == 'status':
                 status_val = response.get('status')
                 print(f"  📋 收到状态消息: {status_val}")
                 if status_val in ['completed', 'failed', 'stopped']:
                     print(f"  🏁 Agent运行完成，状态: {status_val}")
                     logger.info(f"Agent run {agent_run_id} finished via status message: {status_val}")
                     final_status = status_val
                     if status_val == 'failed' or status_val == 'stopped':
                         error_message = response.get('message', f"Run ended with status: {status_val}")
                         print(f"  ❌ 错误消息: {error_message}")
                     break

        print(f"🏁 ===== Agent响应流处理完成 =====")
        print(f"  📊 总响应数量: {total_responses}")
        print(f"  📋 当前状态: {final_status}")

        # If loop finished without explicit completion/error/stop signal, mark as completed
        if final_status == "running":
             final_status = "completed"
             duration = (datetime.now(timezone.utc) - start_time).total_seconds()
             print(f"  ✅ 自动标记为完成状态，运行时长: {duration:.2f}秒")
             logger.info(f"Agent run {agent_run_id} completed normally (duration: {duration:.2f}s, responses: {total_responses})")
             completion_message = {"type": "status", "status": "completed", "message": "Agent run completed successfully"}
             # trace.span(name="agent_run_completed").end(status_message="agent_run_completed")
             await redis.rpush(response_list_key, json.dumps(completion_message))
             await redis.publish(response_channel, "new") # Notify about the completion message
             print(f"  ✅ 完成消息已发布到Redis")

        print(f"📊 ===== 获取最终响应并更新数据库 =====")
        # Fetch final responses from Redis for DB update
        print(f"  🔄 从Redis获取最终响应...")
        all_responses_json = await redis.lrange(response_list_key, 0, -1)
        all_responses = [json.loads(r) for r in all_responses_json]
        print(f"  ✅ 获取到 {len(all_responses)} 个最终响应")

        # Update DB status
        print(f"  🔄 更新数据库状态为: {final_status}")
        await update_agent_run_status(client, agent_run_id, final_status, error=error_message)
        print(f"  ✅ 数据库状态更新完成")

        print(f"📡 ===== 发布最终控制信号 =====")
        # Publish final control signal (END_STREAM or ERROR)
        control_signal = "END_STREAM" if final_status == "completed" else "ERROR" if final_status == "failed" else "STOP"
        print(f"  📋 控制信号: {control_signal}")
        print(f"  📡 发布频道: {global_control_channel}")
        
        try:
            await redis.publish(global_control_channel, control_signal)
            # No need to publish to instance channel as the run is ending on this instance
            print(f"  ✅ 控制信号发布成功")
            logger.debug(f"Published final control signal '{control_signal}' to {global_control_channel}")
        except Exception as e:
            print(f"  ❌ 控制信号发布失败: {str(e)}")
            logger.warning(f"Failed to publish final control signal {control_signal}: {str(e)}")

    except Exception as e:
        error_message = str(e)
        traceback_str = traceback.format_exc()
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        print(f"❌ ===== Agent运行发生错误 =====")
        print(f"  ⏱️ 运行时长: {duration:.2f}秒")
        print(f"  💥 错误消息: {error_message}")
        print(f"  📋 错误详情: {traceback_str}")
        
        logger.error(f"Error in agent run {agent_run_id} after {duration:.2f}s: {error_message}\n{traceback_str} (Instance: {instance_id})")
        final_status = "failed"
        try:
            trace.span(name="agent_run_failed").end(status_message=error_message, level="ERROR")
        except Exception as trace_error:
            print(f"  ⚠️ Trace记录失败: {trace_error}")

        print(f"📤 ===== 推送错误响应到Redis =====")
        # Push error message to Redis list
        error_response = {"type": "status", "status": "error", "message": error_message}
        try:
            await redis.rpush(response_list_key, json.dumps(error_response))
            await redis.publish(response_channel, "new")
            print(f"  ✅ 错误响应推送成功")
        except Exception as redis_err:
             print(f"  ❌ 错误响应推送失败: {redis_err}")
             logger.error(f"Failed to push error response to Redis for {agent_run_id}: {redis_err}")

        print(f"📥 ===== 获取错误后的响应 =====")
        # Fetch final responses (including the error)
        all_responses = []
        try:
             all_responses_json = await redis.lrange(response_list_key, 0, -1)
             all_responses = [json.loads(r) for r in all_responses_json]
             print(f"  ✅ 获取到 {len(all_responses)} 个错误后的响应")
        except Exception as fetch_err:
             print(f"  ❌ 获取响应失败: {fetch_err}")
             logger.error(f"Failed to fetch responses from Redis after error for {agent_run_id}: {fetch_err}")
             all_responses = [error_response] # Use the error message we tried to push

        print(f"💾 ===== 更新数据库错误状态 =====")
        # Update DB status
        await update_agent_run_status(client, agent_run_id, "failed", error=f"{error_message}\n{traceback_str}")
        print(f"  ✅ 数据库错误状态更新完成")

        print(f"📡 ===== 发布ERROR信号 =====")
        # Publish ERROR signal
        try:
            await redis.publish(global_control_channel, "ERROR")
            print(f"  ✅ ERROR信号发布成功")
            logger.debug(f"Published ERROR signal to {global_control_channel}")
        except Exception as e:
            print(f"  ❌ ERROR信号发布失败: {str(e)}")
            logger.warning(f"Failed to publish ERROR signal: {str(e)}")

    finally:
      
        
        print(f"  🛑 清理停止检查器任务...")
        # Cleanup stop checker task
        if stop_checker and not stop_checker.done():
            stop_checker.cancel()
            try: 
                await stop_checker
                print(f"    ✅ 停止检查器任务取消成功")
            except asyncio.CancelledError: 
                print(f"    ✅ 停止检查器任务已取消")
                pass
            except Exception as e: 
                print(f"    ⚠️ 停止检查器任务取消时出错: {e}")
                logger.warning(f"Error during stop_checker cancellation: {e}")

        print(f"  📡 关闭PubSub连接...")
        # Close pubsub connection
        if pubsub:
            try:
                await pubsub.unsubscribe()
                await pubsub.close()
                print(f"    ✅ PubSub连接关闭成功")
                logger.debug(f"Closed pubsub connection for {agent_run_id}")
            except Exception as e:
                print(f"    ⚠️ 关闭PubSub连接时出错: {str(e)}")
                logger.warning(f"Error closing pubsub for {agent_run_id}: {str(e)}")

        print(f"  🗑️ 清理Redis资源...")
        # Set TTL on the response list in Redis
        await _cleanup_redis_response_list(agent_run_id)
        print(f"    ✅ Redis响应列表TTL设置完成")

        # Remove the instance-specific active run key
        await _cleanup_redis_instance_key(agent_run_id)
        print(f"    ✅ 实例活跃键清理完成")

        # Clean up the run lock
        await _cleanup_redis_run_lock(agent_run_id)
        print(f"    ✅ 运行锁清理完成")

        print(f"  ⏳ 等待待处理Redis操作完成...")
        # Wait for all pending redis operations to complete, with timeout
        try:
            await asyncio.wait_for(asyncio.gather(*pending_redis_operations), timeout=30.0)
            print(f"    ✅ 所有待处理Redis操作完成")
        except asyncio.TimeoutError:
            print(f"    ⚠️ 等待Redis操作超时")
            logger.warning(f"Timeout waiting for pending Redis operations for {agent_run_id}")

        print(f"🎯 ===== 后台Agent任务完全结束 =====")
        print(f"  📋 agent_run_id: {agent_run_id}")
        print(f"  🆔 instance_id: {instance_id}")
        print(f"  📊 最终状态: {final_status}")
        print(f"  ⏱️ 总运行时长: {(datetime.now(timezone.utc) - start_time).total_seconds():.2f}秒")
        print(f"  📈 总响应数量: {total_responses}")
        print(f"🏆 ===== 任务完成 =====")

        logger.info(f"Agent run background task fully completed for: {agent_run_id} (Instance: {instance_id}) with final status: {final_status}")

async def _cleanup_redis_instance_key(agent_run_id: str):
    """Clean up the instance-specific Redis key for an agent run."""
    if not instance_id:
        logger.warning("Instance ID not set, cannot clean up instance key.")
        return
    key = f"active_run:{instance_id}:{agent_run_id}"
    logger.debug(f"Cleaning up Redis instance key: {key}")
    try:
        await redis.delete(key)
        logger.debug(f"Successfully cleaned up Redis key: {key}")
    except Exception as e:
        logger.warning(f"Failed to clean up Redis key {key}: {str(e)}")

async def _cleanup_redis_run_lock(agent_run_id: str):
    """Clean up the run lock Redis key for an agent run."""
    run_lock_key = f"agent_run_lock:{agent_run_id}"
    logger.debug(f"Cleaning up Redis run lock key: {run_lock_key}")
    try:
        await redis.delete(run_lock_key)
        logger.debug(f"Successfully cleaned up Redis run lock key: {run_lock_key}")
    except Exception as e:
        logger.warning(f"Failed to clean up Redis run lock key {run_lock_key}: {str(e)}")

# TTL for Redis response lists (24 hours)
REDIS_RESPONSE_LIST_TTL = 3600 * 24

async def _cleanup_redis_response_list(agent_run_id: str):
    """Set TTL on the Redis response list."""
    response_list_key = f"agent_run:{agent_run_id}:responses"
    try:
        await redis.expire(response_list_key, REDIS_RESPONSE_LIST_TTL)
        logger.debug(f"Set TTL ({REDIS_RESPONSE_LIST_TTL}s) on response list: {response_list_key}")
    except Exception as e:
        logger.warning(f"Failed to set TTL on response list {response_list_key}: {str(e)}")

async def update_agent_run_status(
    client,
    agent_run_id: str,
    status: str,
    error: Optional[str] = None,
) -> bool:
    """
    Centralized function to update agent run status.
    Returns True if update was successful.
    """
    try:
        update_data = {
            "status": status,
            "completed_at": datetime.now(timezone.utc)  # 直接传递 datetime 对象，而不是字符串
        }

        if error:
            # 确保error是字符串
            if isinstance(error, list):
                error = str(error)
            elif not isinstance(error, str):
                error = str(error)
            update_data["error"] = error



        # Retry up to 3 times
        for retry in range(3):
            try:
                print(f"  🔄 尝试更新数据库状态 (重试 {retry + 1}/3)")
                print(f"    📋 update_data: {update_data}")
                print(f"    🔑 agent_run_id: {agent_run_id}")
                print(f"    📊 status: {status}")
                # 确保 client 是已初始化的数据库客户端
                if hasattr(client, 'table'):
                    # 使用新的 agent_run_id 字段（UUID类型）
                    update_result = await client.table('agent_runs').eq("agent_run_id", agent_run_id).update(update_data)
                else:
                    # 如果 client 不是数据库客户端，尝试获取数据库连接
                    from services.postgresql import DBConnection
                    db_conn = DBConnection()
                    db_client = await db_conn.client
                    
                    update_result = await db_client.table('agent_runs').eq("agent_run_id", agent_run_id).update(update_data)

                if hasattr(update_result, 'data') and update_result.data:
                    logger.info(f"Successfully updated agent run {agent_run_id} status to '{status}' (retry {retry})")

                    # Verify the update
                    verify_result = await client.table('agent_runs').select('status', 'completed_at').eq("agent_run_id", agent_run_id).execute()
                    if verify_result.data:
                        actual_status = verify_result.data[0].get('status')
                        completed_at = verify_result.data[0].get('completed_at')
                        logger.info(f"Verified agent run update: status={actual_status}, completed_at={completed_at}")
                    return True
                else:
                    logger.warning(f"Database update returned no data for agent run {agent_run_id} on retry {retry}: {update_result}")
                    if retry == 2:  # Last retry
                        logger.error(f"Failed to update agent run status after all retries: {agent_run_id}")
                        return False
            except Exception as db_error:
                logger.error(f"Database error on retry {retry} updating status for {agent_run_id}: {str(db_error)}")
                if retry < 2:  # Not the last retry yet
                    await asyncio.sleep(0.5 * (2 ** retry))  # Exponential backoff
                else:
                    logger.error(f"Failed to update agent run status after all retries: {agent_run_id}", exc_info=True)
                    return False
    except Exception as e:
        logger.error(f"Unexpected error updating agent run status for {agent_run_id}: {str(e)}", exc_info=True)
        return False

    return False
