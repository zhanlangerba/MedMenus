import dotenv
dotenv.load_dotenv(".env")


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
    instance_id: str, 
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
    # manual_message_id: Optional[str] = None,  # ✅ 不再需要，使用上下文变量
):
    """Run the agent in the background using Redis for state."""
    if agent_config:
        logger.info(f"Found agent_config: {agent_config}")
    else:
        logger.info(f"No agent_config found")
    
    # 先清除所有上下文变量
    structlog.contextvars.clear_contextvars()
    # 再绑定新的上下文变量（当前运行）
    structlog.contextvars.bind_contextvars(
        agent_run_id=agent_run_id,
        thread_id=thread_id,
        request_id=request_id,
    )
    try:
        # 初始化 Redis 和 Postgresql 连接实例
        await initialize()
        logger.info(f"Initialized Redis and Postgresql connection")
    except Exception as e:
        logger.error(f"Failed to initialize Redis connection: {e}")
        raise e

    # 幂等性检查：防止重复运行
    run_lock_key = f"agent_run_lock:{agent_run_id}"
    logger.info(f"Run lock key: {run_lock_key}")
    
    # 获取运行锁
    try:
        lock_acquired = await redis.set(run_lock_key, instance_id, nx=True, ex=redis.REDIS_KEY_TTL)
        logger.info(f"Redis SET command completed: {lock_acquired}")
    except Exception as redis_error:
        logger.error(f"Redis lock operation failed: {redis_error}")
        logger.error(f"Error details: {traceback.format_exc()}")
        raise redis_error
    
    if not lock_acquired:
        # 检查是否已有其他实例在处理
        try:
            logger.info(f"Calling Redis GET command...")
            existing_instance = await redis.get(run_lock_key)
            logger.info(f"Existing instance: {existing_instance}")
        except Exception as redis_error:
            logger.error(f"Redis GET operation failed: {redis_error}")
            logger.error(f"Error details: {traceback.format_exc()}")
            raise redis_error
        if existing_instance:
            existing_instance_str = existing_instance.decode() if isinstance(existing_instance, bytes) else existing_instance
            logger.warning(f"Agent run {agent_run_id} is already being processed by instance {existing_instance_str}. Skipping duplicate execution.")
            return
        else:
            # 锁存在但无值，再次尝试获取
            try:
                lock_acquired = await redis.set(run_lock_key, instance_id, nx=True, ex=redis.REDIS_KEY_TTL)
                logger.info(f"Second lock acquisition result: {lock_acquired}")
            except Exception as redis_error:
                logger.error(f"Redis second lock operation failed: {redis_error}")
                logger.error(f"Error details: {traceback.format_exc()}")
                logger.error(f"Redis second lock operation failed: {redis_error}")
                raise redis_error
            if not lock_acquired:
                logger.warning(f"Agent run {agent_run_id} is already being processed by another instance. Skipping duplicate execution.")
                logger.info(f"Agent run {agent_run_id} is already being processed by another instance. Skipping duplicate execution.")
                return
    else:
        logger.info(f"Successfully acquired run lock")

    logger.info(f"Sentry tag setting started")
    try:
        # 错误监控和性能追踪平台，用于实时监控应用程序的错误和性能问题。
        sentry.sentry.set_tag("thread_id", thread_id)
        logger.info(f"Sentry tag setting completed")
    except Exception as sentry_error:
        logger.error(f"Sentry tag setting failed: {sentry_error}")
        logger.error(f"Error details: {traceback.format_exc()}")
        logger.warning(f"Sentry tag setting failed: {sentry_error}")
        # 继续执行，不中断流程

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
        logger.info(f"Logging completed")
    except Exception as log_error:
        logger.error(f"Logging failed: {log_error}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # 继续执行，不中断流程


    # 使用已解析的模型名
    effective_model = model_name  # 现在传入的已经是解析后的最终模型名
    logger.info(f"Using model: {effective_model} (thinking: {enable_thinking}, reasoning_effort: {reasoning_effort})")
    if agent_config:
        logger.info(f"Using custom agent: {agent_config.get('name', 'Unknown')}")
    else:
        logger.info(f"Using default agent config")

    try:
        client = await db.client
        logger.info(f"Database client acquisition successful")
    except Exception as db_error:
        logger.error(f"Database client acquisition failed: {db_error}")
        logger.error(f"Error details: {traceback.format_exc()}")
        raise db_error
    
    # 初始化时间、响应计数、Pub/Sub、停止信号检查器、待处理Redis操作
    start_time = datetime.now(timezone.utc)
    total_responses = 0
    pubsub = None
    stop_checker = None
    stop_signal_received = False
    pending_redis_operations = []  

    # 定义 Redis keys 和 channels
    response_list_key = f"agent_run:{agent_run_id}:responses"
    response_channel = f"agent_run:{agent_run_id}:new_response"
    instance_control_channel = f"agent_run:{agent_run_id}:control:{instance_id}"
    global_control_channel = f"agent_run:{agent_run_id}:control"
    instance_active_key = f"active_run:{instance_id}:{agent_run_id}"
    
    async def check_for_stop_signal():
        nonlocal stop_signal_received
        logger.info(f"Stop signal checker started")
        if not pubsub: 
            logger.warning(f"PubSub not initialized, exiting checker")
            return
        try:
            while not stop_signal_received:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if isinstance(data, bytes): data = data.decode('utf-8')
                    if data == "STOP":
                        logger.info(f"Received STOP signal for agent run {agent_run_id} (Instance: {instance_id})")
                        stop_signal_received = True
                        break
                # 持久化刷新活跃运行键的TTL
                if total_responses % 50 == 0: # 每50个响应刷新一次
                    try: 
                        await redis.expire(instance_active_key, redis.REDIS_KEY_TTL)
                        logger.info(f"TTL refreshed (response count: {total_responses})")
                    except Exception as ttl_err: 
                        logger.warning(f"Failed to refresh TTL for {instance_active_key}: {ttl_err}")
                await asyncio.sleep(0.1) # Short sleep to prevent tight loop
        except asyncio.CancelledError:
            logger.info(f"Stop signal checker cancelled for {agent_run_id} (Instance: {instance_id})")
        except Exception as e:
            logger.error(f"Error in stop signal checker for {agent_run_id}: {e}", exc_info=True)
            stop_signal_received = True # Stop the run if the checker fails

    # 创建 Langfuse 跟踪
    trace = langfuse.trace(name="agent_run", id=agent_run_id, session_id=thread_id, metadata={"project_id": project_id, "instance_id": instance_id})
    logger.info(f"Langfuse trace created successfully")
    
    try:
        # 创建 Pub/Sub 连接
        pubsub = await redis.create_pubsub()
        logger.info(f"PubSub connection created successfully")
        
        try:
            await retry(lambda: pubsub.subscribe(instance_control_channel, global_control_channel))
            logger.info(f"Control channels subscribed successfully")
        except Exception as e:
            logger.error(f"Redis failed to subscribe to control channels: {e}", exc_info=True)
            raise e

        logger.debug(f"Subscribed to control channels: {instance_control_channel}, {global_control_channel}")
        stop_checker = asyncio.create_task(check_for_stop_signal())
        logger.info(f"Stop signal checker started successfully")
        # Ensure active run key exists and has TTL
        await redis.set(instance_active_key, "running", ex=redis.REDIS_KEY_TTL)
        logger.info(f"Active run key set successfully")

        # 初始化Agent生成器
        try:
            logger.info(f"Starting to call run_agent function")
            # 这里开始执行Agent的逻辑。注意：这里仅仅是创建生成器，并不执行
            agent_gen = run_agent(
                thread_id=thread_id, 
                project_id=project_id, 
                stream=stream,
                model_name=effective_model,
                enable_thinking=enable_thinking, 
                reasoning_effort=reasoning_effort,
                enable_context_manager=enable_context_manager,
                agent_config=agent_config,
                trace=trace,
                is_agent_builder=is_agent_builder,
                target_agent_id=target_agent_id,
            )
            logger.info(f"Agent run {agent_run_id} started successfully")
            
        except Exception as agent_error:
            logger.error(f"Failed to call run_agent: {agent_error}")
            raise agent_error

        final_status = "running"
        error_message = None
        pending_redis_operations = []

        response_count = 0

        # 从这里开始真正执行：runner.run()
        async for response in agent_gen:
            response_count += 1
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
