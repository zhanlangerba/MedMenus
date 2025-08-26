"""
User Authentication Service
"""

import json
from datetime import datetime
from typing import Optional
from fastapi import HTTPException # type: ignore
from services.postgresql import DBConnection
from utils.auth_utils import AuthUtils
from utils.logger import logger
from .models import (
    LoginRequest, RegisterRequest, RefreshRequest,
    AuthResponse, RefreshResponse, UserResponse, User
)

class AuthService:
    """用户认证服务"""
    
    def __init__(self):
        self.db = DBConnection()
        self.auth = AuthUtils()
        self.default_app_name = "fufanmanus"  # 默认应用名称
    
    async def _get_client(self):
        """获取数据库客户端"""
        await self.db.initialize()
        return await self.db.client
    
    def _user_to_model(self, user_data: dict) -> User:
        """转换数据库用户数据为模型"""
        return User(
            id=str(user_data['id']),  # 确保UUID转换为字符串
            email=user_data['email'],
            name=user_data['name'],
            created_at=user_data['created_at']
        )
    
    async def register(self, request: RegisterRequest) -> AuthResponse:
        """用户注册（适配Google ADK）"""
        logger.info(f"Starting registration for: {request.email}")
        
        client = await self._get_client()
        
        # 检查用户是否已存在
        async with client.pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1", 
                request.email
            )
        
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # 创建新用户
        hashed_password = self.auth.hash_password(request.password)
        
        async with client.pool.acquire() as conn:
            user_record = await conn.fetchrow(
                """
                INSERT INTO users (email, password_hash, name, provider, status, created_at) 
                VALUES ($1, $2, $3, $4, $5, $6) 
                RETURNING *
                """,
                request.email, hashed_password, request.name, 'local', 'active', datetime.now()
            )
        
        user = dict(user_record)
        
        # 生成访问令牌和刷新令牌
        access_token = self.auth.create_access_token(str(user['id']))
        refresh_token = self.auth.create_refresh_token()
        
        # 存储刷新令牌
        await self._store_refresh_token(str(user['id']), refresh_token)
        
        # 更新用户状态
        await self._update_user_state(client, str(user['id']), {
            'last_login': datetime.now().isoformat(),
            'login_count': 1,
            'email_verified': False
        })
        
        # 使用默认应用名称
        app_name = self.default_app_name
        
        # 创建注册会话（注册时先创建会话，再记录事件，用来适配ADK框架中无法使用session_id字段的情况）
        session_id = await self._create_adk_session(client, str(user['id']), {
            'registration_time': datetime.now().isoformat(),
            'registration_method': 'email_password',
            'status': 'active'
        }, app_name)
        
        # 记录注册事件
        if session_id:
            await self._log_adk_event(client, str(user['id']), 'user_register', {
                'email': request.email,
                'name': request.name,
                'provider': 'local',
                'registration_time': datetime.now().isoformat()
            }, session_id, app_name)
        else:
            logger.warning(f"Skipping registration event log due to failed session creation for user {user['id']}")
        
        # 🆕 创建默认Agent
        await self._create_default_agent(client, str(user['id']))
        
        logger.info(f"User registered: {request.email}")
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=24 * 3600,  # 24小时
            user=self._user_to_model(user)
        )
    
    async def login(self, request: LoginRequest) -> AuthResponse:
        """用户登录（适配Google ADK）"""
        client = await self._get_client()
        
        # 查找用户（包含ADK状态字段）
        async with client.pool.acquire() as conn:
            user = await conn.fetchrow(
                """
                SELECT id, email, name, password_hash, provider, status, 
                       email_verified, created_at, last_login_at
                FROM users 
                WHERE email = $1 AND provider = 'local'
                """,
                request.email
            )
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # 检查用户状态
        if user['status'] != 'active':
            raise HTTPException(status_code=401, detail="Account is not active")
        
        # 验证密码
        if not self.auth.verify_password(request.password, user['password_hash']):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # 生成tokens
        access_token = self.auth.create_access_token(str(user['id']))
        refresh_token = self.auth.create_refresh_token()
        
        # 存储刷新token
        await self._store_refresh_token(str(user['id']), refresh_token)
        
        # 更新最后登录时间（ADK兼容）
        async with client.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_login_at = $1 WHERE id = $2",
                datetime.now(), user['id']
            )
        
        # 使用默认应用名称
        app_name = self.default_app_name
        
        # 创建或更新ADK用户状态
        await self._update_user_state(client, str(user['id']), {
            'last_login': datetime.now().isoformat(),
            'login_method': 'email_password',
            'status': 'active'
        }, app_name)
        
        # 创建ADK会话
        session_id = await self._create_adk_session(client, str(user['id']), {
            'access_token': access_token,
            'login_time': datetime.now().isoformat(),
            'login_method': 'email_password'
        }, app_name)
        
        # 记录登录事件
        if session_id:
            await self._log_adk_event(client, str(user['id']), 'user_login', {
                'email': request.email,
                'login_time': datetime.now().isoformat(),
                'login_method': 'email_password'
            }, session_id, app_name)
        else:
            logger.warning(f"Skipping login event log due to failed session creation for user {user['id']}")
        
        logger.info(f"User logged in: {request.email}")
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=24 * 3600,  # 24小时
            user=self._user_to_model(user)
        )
    
    async def refresh_token(self, request: RefreshRequest) -> RefreshResponse:
        """刷新token"""
        client = await self._get_client()
        
        # 验证刷新token
        token_hash = self.auth.hash_refresh_token(request.refresh_token)
        async with client.pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                SELECT user_id FROM refresh_tokens 
                WHERE token_hash = $1 AND expires_at > $2
                """,
                token_hash, datetime.now()
            )
        
        if not result:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        user_id = result['user_id']
        
        # 删除旧的刷新token
        async with client.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = $1",
                token_hash
            )
        
        # 生成新的tokens
        access_token = self.auth.create_access_token(user_id)
        new_refresh_token = self.auth.create_refresh_token()
        
        # 存储新的刷新token
        await self._store_refresh_token(user_id, new_refresh_token)
        
        return RefreshResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=24 * 3600  # 24小时
        )
    
    async def get_user(self, user_id: str) -> UserResponse:
        """获取用户信息"""
        client = await self._get_client()
        
        async with client.pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                user_id
            )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(user=self._user_to_model(user))
    
    async def logout(self, user_id: str, refresh_token: Optional[str] = None):
        """登出用户"""
        client = await self._get_client()
        
        if refresh_token:
            # 删除特定的刷新token
            token_hash = self.auth.hash_refresh_token(refresh_token)
            async with client.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM refresh_tokens WHERE token_hash = $1",
                    token_hash
                )
        else:
            # 删除用户的所有刷新token
            async with client.pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM refresh_tokens WHERE user_id = $1",
                    user_id
                )
        
        logger.info(f"User logged out: {user_id}")
    
    async def _store_refresh_token(self, user_id: str, refresh_token: str):
        """存储刷新token"""
        client = await self._get_client()
        
        token_hash = self.auth.hash_refresh_token(refresh_token)
        expires_at = self.auth.get_refresh_token_expire_time()
        
        async with client.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at)
                VALUES ($1, $2, $3, $4)
                """,
                user_id, token_hash, expires_at, datetime.now()
            )
    
    async def _update_user_state(self, client, user_id: str, state_data: dict, app_name: str = "fufanmanus"):
        """更新Google ADK用户状态"""
        try:
            # 检查是否已存在用户状态
            async with client.pool.acquire() as conn:
                existing = await conn.fetchrow(
                    "SELECT * FROM user_states WHERE app_name = $1 AND user_id = $2",
                    app_name, user_id
                )
            
            if existing:
                # 更新现有状态
                try:
                    # 解析现有的JSON状态
                    current_state = json.loads(existing['state']) if existing['state'] else {}
                except (json.JSONDecodeError, TypeError):
                    # 如果解析失败，使用空字典
                    current_state = {}
                
                # 更新状态
                current_state.update(state_data)
                
                async with client.pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE user_states 
                        SET state = $1, update_time = $2 
                        WHERE app_name = $3 AND user_id = $4
                        """,
                        json.dumps(current_state), datetime.now(), app_name, user_id
                    )
            else:
                # 创建新的用户状态
                async with client.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO user_states (app_name, user_id, state, update_time)
                        VALUES ($1, $2, $3, $4)
                        """,
                        app_name, user_id, json.dumps(state_data), datetime.now()
                    )
            
            logger.info(f"Updated user state for {user_id} in {app_name}")
            
        except Exception as e:
            logger.warning(f"Failed to update user state: {e}")
    
    async def _create_adk_session(self, client, user_id: str, session_data: dict, app_name: str = "fufanmanus"):
        """创建Google ADK会话"""
        try:
            # 生成会话ID
            import uuid
            session_id = str(uuid.uuid4())
            
            # 按照ADK框架的表结构插入会话
            async with client.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO sessions (app_name, user_id, id, state, create_time, update_time)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    app_name, user_id, session_id, json.dumps(session_data), datetime.now(), datetime.now()
                )
            
            logger.info(f"Created ADK session {session_id} for user {user_id} in app {app_name}")
            return session_id
            
        except Exception as e:
            logger.warning(f"Failed to create ADK session: {e}")
            return None
    
    async def _log_adk_event(self, client, user_id: str, event_type: str, event_data: dict, 
                           session_id: str = None, app_name: str = "fufanmanus"):
        """记录Google ADK事件"""
        try:
            import uuid
            event_id = str(uuid.uuid4())
            invocation_id = str(uuid.uuid4())
            
            if session_id:
                # 按照ADK框架的表结构插入事件
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
                        "auth_service", datetime.now(), json.dumps(event_data), b''  # actions为空字节
                    )
                
                logger.info(f"Logged ADK event {event_type} for user {user_id} with session {session_id}")
            else:
                logger.warning(f"Failed to create session for event {event_type}, skipping event log")
            
        except Exception as e:
            logger.warning(f"Failed to log ADK event: {e}") 

    async def _get_app_name_for_user(self, user_id: str, context: str = "default") -> str:
        """获取用户的应用名称
        
        Args:
            user_id: 用户ID
            context: 上下文，可以是 'default', 'agent_creation', 'specific_agent' 等
            
        Returns:
            app_name: 应用名称
        """
        # 这里可以根据用户ID和上下文动态确定app_name
        # 例如：从数据库查询用户创建的应用，或者根据请求上下文确定
        
        if context == "default":
            return self.default_app_name
        elif context == "agent_creation":
            # 用户创建新agent时，可以使用特定的app_name
            return f"agent_creator_{user_id}"
        else:
            # 其他情况返回默认应用
            return self.default_app_name
    
    async def create_agent_session(self, user_id: str, agent_id: str, agent_config: dict) -> str:
        """为用户创建特定agent的会话
        
        Args:
            user_id: 用户ID
            agent_id: Agent ID
            agent_config: Agent配置
            
        Returns:
            session_id: 会话ID
        """
        client = await self._get_client()
        
        # 为特定agent创建app_name
        app_name = f"agent_{agent_id}"
        
        # 创建agent会话
        session_id = await self._create_adk_session(client, user_id, {
            'agent_id': agent_id,
            'agent_config': agent_config,
            'created_at': datetime.now().isoformat(),
            'session_type': 'agent_session'
        }, app_name)
        
        # 记录agent创建事件
        if session_id:
            await self._log_adk_event(client, user_id, 'agent_session_created', {
                'agent_id': agent_id,
                'agent_config': agent_config,
                'created_at': datetime.now().isoformat()
            }, session_id, app_name)
        
        return session_id
    
    async def get_user_agents(self, user_id: str) -> list:
        """获取用户创建的所有agents
        
        Args:
            user_id: 用户ID
            
        Returns:
            agents: Agent列表
        """
        client = await self._get_client()
        
        # 查询用户的所有agent会话
        async with client.pool.acquire() as conn:
            sessions = await conn.fetch(
                """
                SELECT DISTINCT app_name, id as session_id, state
                FROM sessions 
                WHERE user_id = $1 AND app_name LIKE 'agent_%'
                ORDER BY create_time DESC
                """,
                user_id
            )
        
        agents = []
        for session in sessions:
            try:
                state = json.loads(session['state']) if session['state'] else {}
                agent_id = state.get('agent_id')
                if agent_id:
                    agents.append({
                        'agent_id': agent_id,
                        'session_id': session['session_id'],
                        'config': state.get('agent_config', {}),
                        'created_at': state.get('created_at')
                    })
            except Exception as e:
                logger.warning(f"Failed to parse agent session state: {e}")
        
        return agents 

    async def _create_default_agent(self, client, user_id: str):
        """为新用户创建默认Agent"""
        try:
            import uuid
            agent_id = str(uuid.uuid4())
            
            # 默认Agent配置
            default_agent_data = {
                'agent_id': agent_id,
                'user_id': user_id,
                'name': 'Default Assistant',
                'description': '你的默认AI助手，可以帮助你完成各种任务',
                'system_prompt': '你是一个智能助手，能够帮助用户解决各种问题。请以友好、专业的方式回答用户的问题。',
                'model': 'deepseek/deepseek-chat-v3.1',
                'configured_mcps': [],
                'custom_mcps': [],
                'agentpress_tools': {},
                'is_default': True,
                'is_public': False,
                'tags': [],
                'avatar': None,
                'avatar_color': '#4F46E5',
                'profile_image_url': None,
                'current_version_id': None,
                'version_count': 1,
                'metadata': {
                    'created_by': 'system',
                    'auto_created': True
                },
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            
            # 插入到agents表
            async with client.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agents (
                        agent_id, user_id, name, description, system_prompt, model,
                        configured_mcps, custom_mcps, agentpress_tools, is_default, is_public,
                        tags, avatar, avatar_color, profile_image_url, current_version_id,
                        version_count, metadata, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
                    )
                    """,
                    agent_id, user_id, default_agent_data['name'], default_agent_data['description'],
                    default_agent_data['system_prompt'], default_agent_data['model'],
                    json.dumps(default_agent_data['configured_mcps']), json.dumps(default_agent_data['custom_mcps']),
                    json.dumps(default_agent_data['agentpress_tools']), default_agent_data['is_default'],
                    default_agent_data['is_public'], default_agent_data['tags'], default_agent_data['avatar'],
                    default_agent_data['avatar_color'], default_agent_data['profile_image_url'],
                    default_agent_data['current_version_id'], default_agent_data['version_count'],
                    json.dumps(default_agent_data['metadata']), default_agent_data['created_at'],
                    default_agent_data['updated_at']
                )
            
            logger.info(f"Created default agent {agent_id} for user {user_id}")
            return agent_id
            
        except Exception as e:
            logger.error(f"Failed to create default agent for user {user_id}: {e}")
            return None 