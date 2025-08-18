"""
用户认证测试服务器
完全独立的认证系统，避免所有其他依赖
"""

import os
import sys
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uuid

# 直接导入认证相关模块，避免其他依赖
from utils.logger import logger
from utils.config import config

# 全局变量
instance_id = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global instance_id
    
    # 启动时
    instance_id = str(uuid.uuid4())[:8]
    logger.info(f"Starting auth test server with instance ID: {instance_id}")
    
    yield
    
    # 关闭时
    logger.info(f"Shutting down auth test server: {instance_id}")

# 创建FastAPI应用
app = FastAPI(
    title="User Authentication Test Server",
    description="专业的用户认证测试服务器",
    version="1.0.0",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 直接在这里定义认证路由，避免导入其他模块
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from pydantic import BaseModel
import jwt
import bcrypt
import hashlib
import secrets
from datetime import datetime, timedelta

# 认证工具类
class AuthUtils:
    JWT_SECRET = getattr(config, 'JWT_SECRET_KEY', 'your-secret-key-change-in-production')
    ACCESS_TOKEN_EXPIRE_HOURS = 24
    REFRESH_TOKEN_EXPIRE_DAYS = 30
    
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    @staticmethod
    def create_access_token(user_id: str) -> str:
        expire = datetime.utcnow() + timedelta(hours=AuthUtils.ACCESS_TOKEN_EXPIRE_HOURS)
        payload = {"sub": user_id, "exp": expire, "iat": datetime.utcnow()}
        return jwt.encode(payload, AuthUtils.JWT_SECRET, algorithm="HS256")
    
    @staticmethod
    def create_refresh_token() -> str:
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def verify_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, AuthUtils.JWT_SECRET, algorithms=["HS256"])
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token")
            return {"user_id": user_id}
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    @staticmethod
    def hash_refresh_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    def get_refresh_token_expire_time() -> datetime:
        return datetime.utcnow() + timedelta(days=AuthUtils.REFRESH_TOKEN_EXPIRE_DAYS)

# Pydantic模型
class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str

class RefreshRequest(BaseModel):
    refresh_token: str

class User(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime

class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: User

class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int

class UserResponse(BaseModel):
    user: User

# 内存数据库模拟（仅用于测试）
class MockDatabase:
    def __init__(self):
        self.users = {}
        self.refresh_tokens = {}
    
    async def get_user_by_email(self, email: str):
        return self.users.get(email)
    
    async def create_user(self, email: str, password_hash: str, name: str):
        user_id = str(uuid.uuid4())
        user = {
            "id": user_id,
            "email": email,
            "password_hash": password_hash,
            "name": name,
            "created_at": datetime.utcnow()
        }
        self.users[email] = user
        return user
    
    async def store_refresh_token(self, user_id: str, token_hash: str, expires_at: datetime):
        self.refresh_tokens[token_hash] = {
            "user_id": user_id,
            "expires_at": expires_at
        }
    
    async def get_refresh_token(self, token_hash: str):
        token_data = self.refresh_tokens.get(token_hash)
        if token_data and token_data["expires_at"] > datetime.utcnow():
            return token_data
        return None
    
    async def delete_refresh_token(self, token_hash: str):
        if token_hash in self.refresh_tokens:
            del self.refresh_tokens[token_hash]

# 全局数据库实例
mock_db = MockDatabase()

# 认证服务
class AuthService:
    def __init__(self):
        self.auth = AuthUtils()
        self.db = mock_db
    
    def _user_to_model(self, user_data: dict) -> User:
        return User(
            id=user_data['id'],
            email=user_data['email'],
            name=user_data['name'],
            created_at=user_data['created_at']
        )
    
    async def register(self, request: RegisterRequest) -> AuthResponse:
        # 检查邮箱是否已存在
        existing = await self.db.get_user_by_email(request.email)
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        
        # 创建用户
        password_hash = self.auth.hash_password(request.password)
        user = await self.db.create_user(request.email, password_hash, request.name)
        
        # 生成tokens
        access_token = self.auth.create_access_token(user['id'])
        refresh_token = self.auth.create_refresh_token()
        
        # 存储刷新token
        await self.db.store_refresh_token(
            user['id'], 
            self.auth.hash_refresh_token(refresh_token),
            self.auth.get_refresh_token_expire_time()
        )
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=24 * 3600,
            user=self._user_to_model(user)
        )
    
    async def login(self, request: LoginRequest) -> AuthResponse:
        # 查找用户
        user = await self.db.get_user_by_email(request.email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # 验证密码
        if not self.auth.verify_password(request.password, user['password_hash']):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # 生成tokens
        access_token = self.auth.create_access_token(user['id'])
        refresh_token = self.auth.create_refresh_token()
        
        # 存储刷新token
        await self.db.store_refresh_token(
            user['id'], 
            self.auth.hash_refresh_token(refresh_token),
            self.auth.get_refresh_token_expire_time()
        )
        
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=24 * 3600,
            user=self._user_to_model(user)
        )
    
    async def refresh_token(self, request: RefreshRequest) -> RefreshResponse:
        # 验证刷新token
        token_hash = self.auth.hash_refresh_token(request.refresh_token)
        token_data = await self.db.get_refresh_token(token_hash)
        
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        
        user_id = token_data['user_id']
        
        # 删除旧的刷新token
        await self.db.delete_refresh_token(token_hash)
        
        # 生成新的tokens
        access_token = self.auth.create_access_token(user_id)
        new_refresh_token = self.auth.create_refresh_token()
        
        # 存储新的刷新token
        await self.db.store_refresh_token(
            user_id, 
            self.auth.hash_refresh_token(new_refresh_token),
            self.auth.get_refresh_token_expire_time()
        )
        
        return RefreshResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=24 * 3600
        )
    
    async def get_user(self, user_id: str) -> UserResponse:
        # 在模拟数据库中查找用户
        for user in self.db.users.values():
            if user['id'] == user_id:
                return UserResponse(user=self._user_to_model(user))
        
        raise HTTPException(status_code=404, detail="User not found")
    
    async def logout(self, user_id: str, refresh_token: Optional[str] = None):
        if refresh_token:
            # 删除特定的刷新token
            token_hash = self.auth.hash_refresh_token(refresh_token)
            await self.db.delete_refresh_token(token_hash)

# 全局认证服务实例
auth_service = AuthService()
auth_utils = AuthUtils()

# 认证中间件
security = HTTPBearer(auto_error=False)

async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        token_data = auth_utils.verify_token(credentials.credentials)
        return token_data["user_id"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")

# 认证路由
auth_router = APIRouter(prefix="/auth", tags=["Authentication"])

@auth_router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    """用户注册"""
    try:
        logger.info(f"Registration attempt: {request.email}")
        response = await auth_service.register(request)
        logger.info(f"Registration successful: {request.email}")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@auth_router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """用户登录"""
    try:
        logger.info(f"Login attempt: {request.email}")
        response = await auth_service.login(request)
        logger.info(f"Login successful: {request.email}")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@auth_router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest):
    """刷新访问token"""
    try:
        response = await auth_service.refresh_token(request)
        logger.info("Token refresh successful")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise HTTPException(status_code=500, detail="Token refresh failed")

@auth_router.get("/me", response_model=UserResponse)
async def get_current_user(user_id: str = Depends(get_current_user_id)):
    """获取当前用户信息"""
    try:
        return await auth_service.get_user(user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user info")

@auth_router.post("/logout")
async def logout(
    request: Optional[RefreshRequest] = None,
    user_id: str = Depends(get_current_user_id)
):
    """用户登出"""
    try:
        refresh_token = request.refresh_token if request else None
        await auth_service.logout(user_id, refresh_token)
        return {"message": "Logged out successfully"}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=500, detail="Logout failed")

@auth_router.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "auth"}

# 主路由
api_router = APIRouter()
api_router.include_router(auth_router)

# 健康检查端点
@api_router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "service": "user-auth-test-server",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id
    }

@api_router.get("/")
async def root():
    """根端点"""
    return {
        "message": "User Authentication Test Server",
        "version": "1.0.0",
        "instance_id": instance_id,
        "endpoints": {
            "auth": "/auth",
            "health": "/health"
        }
    }

# 包含主路由器
app.include_router(api_router)

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    import uvicorn
    
    # 设置默认端口
    port = int(os.getenv("PORT", 8000))
    
    logger.info(f"Starting user auth test server on port {port}")
    logger.info(f"Environment: {config.ENV_MODE.value}")
    logger.info(f"JWT Secret configured: {'Yes' if config.JWT_SECRET_KEY else 'No'}")
    
    uvicorn.run(
        "auth_test_server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    ) 