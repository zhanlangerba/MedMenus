"""
自定义ADK数据库会话服务 - 只存储模型响应，过滤用户消息
"""

from typing import Any, Optional
from google.adk.sessions.database_session_service import DatabaseSessionService # type: ignore
from google.adk.sessions.session import Session # type: ignore
from google.adk.events.event import Event # type: ignore
import logging

logger = logging.getLogger(__name__)

class ModelOnlyDBSessionService(DatabaseSessionService):
    """
    继承ADK的DatabaseSessionService，只存储模型响应事件
    过滤掉用户消息事件，避免与手动插入的用户消息重复
    """
    
    def __init__(self, db_url: str, **kwargs: Any):
        """初始化服务"""
        super().__init__(db_url, **kwargs)
        logger.info("ModelOnlyDBSessionService initialized - will filter user events")
    
    async def append_event(self, session: Session, event: Event) -> Event:
        """
        重写append_event方法，过滤用户事件
        只存储模型/助手的响应，避免用户消息重复
        """
        # 过滤用户事件，不存储到数据库，因为我们已经手动存储了
        if getattr(event, "author", None) == "user":
            logger.debug(f" Filtering user event: {event.id}")
            return event  # 直接返回，不调用父类存储方法
        
        # 存储非用户事件（模型响应等）
        logger.debug(f"Storing non-user event: {event.id} (author: {getattr(event, 'author', 'unknown')})")
        return await super().append_event(session, event) 