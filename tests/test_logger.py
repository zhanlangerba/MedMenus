async def _log_adk_user_message_event(client, user_id: str, message_content: str, session_id: str, message_id: str, app_name: str = "fufanmanus"):
    """记录用户消息事件到ADK events表"""
    try:
        import uuid
        import pickle
        from datetime import datetime
        event_id = str(uuid.uuid4())
        invocation_id = str(uuid.uuid4())
        
        # 按照ADK格式构建消息内容 - 应该符合 types.Content 结构
        content = {
            "role": "user", 
            "parts": [{"text": message_content}],  # ADK期望的格式
            "message_id": message_id
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