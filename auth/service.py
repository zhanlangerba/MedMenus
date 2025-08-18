"""
Author:Muyu
用户认证服务
"""

from datetime import datetime
from typing import Optional
from fastapi import HTTPException
from utils.postgres_client import postgres_client
from utils.auth_utils import AuthUtils
from utils.logger import logger
from .models import (
    LoginRequest, RegisterRequest, RefreshRequest,
    AuthResponse, RefreshResponse, UserResponse, User
)

class AuthService:
    """用户认证服务"""
    
    def __init__(self):
        self.db = postgres_client
        self.auth = AuthUtils()
    
    async def _get_client(self):
        """获取数据库客户端"""
        await self.db.initialize()
        return self.db
    
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
        client = await self._get_client()
        
        # 检查邮箱是否已存在
        existing = await client.fetchrow(
            "SELECT id FROM users WHERE email = $1",
            request.email
        )
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # 创建用户（使用ADK的users表结构）
        password_hash = self.auth.hash_password(request.password)
        
        result = await client.fetchrow(
            """
            INSERT INTO users (
                email, password_hash, name, provider, status, 
                email_verified, metadata, preferences
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, email, name, created_at, provider, status
            """,
            request.email, password_hash, request.name, 'local', 'active',
            False, '{}', '{}'
        )
        
        if not result:
            raise HTTPException(status_code=500, detail="Registration failed")
        
        user = result
        
        # 生成tokens
        access_token = self.auth.create_access_token(str(user['id']))
        refresh_token = self.auth.create_refresh_token()
        
        # 存储刷新token
        await self._store_refresh_token(str(user['id']), refresh_token)
        
        # 创建ADK用户状态
        await self._update_user_state(client, str(user['id']), {
            'registration_time': datetime.now().isoformat(),
            'registration_method': 'email_password',
            'status': 'active',
            'email_verified': False
        })
        
        # 记录注册事件
        await self._log_adk_event(client, str(user['id']), 'user_register', {
            'email': request.email,
            'name': request.name,
            'provider': 'local',
            'registration_time': datetime.now().isoformat()
        })
        
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
        user = await client.fetchrow(
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
        await client.execute(
            "UPDATE users SET last_login_at = $1 WHERE id = $2",
            datetime.now(), user['id']
        )
        
        # 创建或更新ADK用户状态
        await self._update_user_state(client, str(user['id']), {
            'last_login': datetime.now().isoformat(),
            'login_method': 'email_password',
            'status': 'active'
        })
        
        # 创建ADK会话
        session_id = await self._create_adk_session(client, str(user['id']), {
            'access_token': access_token,
            'login_time': datetime.now().isoformat(),
            'login_method': 'email_password'
        })
        
        # 记录登录事件
        await self._log_adk_event(client, str(user['id']), 'user_login', {
            'email': request.email,
            'login_time': datetime.now().isoformat(),
            'login_method': 'email_password'
        }, session_id)
        
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
        result = await client.fetchrow(
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
        await client.execute(
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
        
        user = await client.fetchrow(
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
            await client.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = $1",
                token_hash
            )
        else:
            # 删除用户的所有刷新token
            await client.execute(
                "DELETE FROM refresh_tokens WHERE user_id = $1",
                user_id
            )
        
        logger.info(f"User logged out: {user_id}")
    
    async def _store_refresh_token(self, user_id: str, refresh_token: str):
        """存储刷新token"""
        client = await self._get_client()
        
        token_hash = self.auth.hash_refresh_token(refresh_token)
        expires_at = self.auth.get_refresh_token_expire_time()
        
        await client.execute(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at)
            VALUES ($1, $2, $3, $4)
            """,
            user_id, token_hash, expires_at, datetime.now()
        )
    
    async def _update_user_state(self, client, user_id: str, state_data: dict, app_name: str = "suna_auth"):
        """更新Google ADK用户状态"""
        try:
            # 检查是否已存在用户状态
            existing = await client.fetchrow(
                "SELECT * FROM user_states WHERE app_name = $1 AND user_id = $2",
                app_name, user_id
            )
            
            if existing:
                # 更新现有状态
                current_state = existing['state'] or {}
                current_state.update(state_data)
                
                await client.execute(
                    """
                    UPDATE user_states 
                    SET state = $1, update_time = $2 
                    WHERE app_name = $3 AND user_id = $4
                    """,
                    current_state, datetime.now(), app_name, user_id
                )
            else:
                # 创建新的用户状态
                await client.execute(
                    """
                    INSERT INTO user_states (app_name, user_id, state, update_time)
                    VALUES ($1, $2, $3, $4)
                    """,
                    app_name, user_id, state_data, datetime.now()
                )
            
            logger.info(f"Updated user state for {user_id} in {app_name}")
            
        except Exception as e:
            logger.warning(f"Failed to update user state: {e}")
    
    async def _create_adk_session(self, client, user_id: str, session_data: dict, app_name: str = "suna_auth"):
        """创建Google ADK会话"""
        try:
            # 生成会话ID
            import uuid
            session_id = str(uuid.uuid4())
            
            await client.execute(
                """
                INSERT INTO sessions (app_name, user_id, id, state, create_time, update_time)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                app_name, user_id, session_id, session_data, datetime.now(), datetime.now()
            )
            
            logger.info(f"Created ADK session {session_id} for user {user_id}")
            return session_id
            
        except Exception as e:
            logger.warning(f"Failed to create ADK session: {e}")
            return None
    
    async def _log_adk_event(self, client, user_id: str, event_type: str, event_data: dict, 
                           session_id: str = None, app_name: str = "suna_auth"):
        """记录Google ADK事件"""
        try:
            import uuid
            event_id = str(uuid.uuid4())
            invocation_id = str(uuid.uuid4())
            
            await client.execute(
                """
                INSERT INTO events (
                    id, app_name, user_id, session_id, invocation_id, 
                    author, timestamp, content, actions
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                event_id, app_name, user_id, session_id or "", invocation_id,
                "auth_service", datetime.now(), event_data, b''  # actions为空字节
            )
            
            logger.info(f"Logged ADK event {event_type} for user {user_id}")
            
        except Exception as e:
            logger.warning(f"Failed to log ADK event: {e}") 