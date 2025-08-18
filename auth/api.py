"""
用户认证API
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from utils.auth_utils import AuthUtils
from utils.logger import logger
from utils.request_parser import parse_request_data, extract_auth_data
from .models import (
    LoginRequest, RegisterRequest, RefreshRequest,
    AuthResponse, RefreshResponse, UserResponse
)
from .service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer(auto_error=False)

# 全局认证服务实例
auth_service = AuthService()
auth_utils = AuthUtils()

async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """从JWT token中获取当前用户ID"""
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

@router.post("/register", response_model=AuthResponse)
async def register(request: Request):
    """用户注册"""
    try:
        # 解析前端表单数据（注册的用户名和密码）
        parsed_data = await parse_request_data(request)
        auth_data = extract_auth_data(parsed_data)
        
        email = auth_data['email']
        password = auth_data['password']
        confirmPassword = auth_data['confirmPassword']
        origin = auth_data['origin']
        
        print(f"Extracted auth data: {auth_data}")
        
        # 验证必需字段
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        if not password:
            raise HTTPException(status_code=400, detail="Password is required")
        
        # 验证密码确认
        if confirmPassword and password != confirmPassword:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        
        # 生成用户名（使用邮箱前缀）
        name = email.split('@')[0]
        
        # 创建请求对象
        register_request = RegisterRequest(
            email=email,
            password=password,
            name=name
        )
        
        logger.info(f"Registration attempt: {email} from {origin}")
        response = await auth_service.register(register_request)
        logger.info(f"Registration successful: {email}")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@router.post("/login", response_model=AuthResponse)
async def login(request: Request):
    """用户登录"""
    try:
        # 使用通用解析工具
        parsed_data = await parse_request_data(request)
        auth_data = extract_auth_data(parsed_data)
        
        email = auth_data['email']
        password = auth_data['password']
        origin = auth_data['origin']
        
        print(f"Login auth data: {auth_data}")
        
        # 验证必需字段
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        if not password:
            raise HTTPException(status_code=400, detail="Password is required")
        
        # 创建请求对象
        login_request = LoginRequest(
            email=email,
            password=password
        )
        
        logger.info(f"Login attempt: {email} from {origin}")
        response = await auth_service.login(login_request)
        logger.info(f"Login successful: {email}")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@router.post("/refresh", response_model=RefreshResponse)
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

@router.get("/me", response_model=UserResponse)
async def get_current_user(user_id: str = Depends(get_current_user_id)):
    """获取当前用户信息"""
    try:
        return await auth_service.get_user(user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user info")

@router.post("/logout")
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

@router.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "auth"} 