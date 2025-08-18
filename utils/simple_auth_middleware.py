"""
用户认证中间件
用于保护现有的API端点
"""

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from utils.auth_utils import AuthUtils
from utils.logger import logger

security = HTTPBearer(auto_error=False)
auth_utils = AuthUtils()

async def get_current_user_id_from_jwt(
    request: Request
) -> str:
    """
    从JWT token中提取用户ID
    这个函数替代原来的 get_current_user_id_from_jwt，保持接口兼容
    """
    # 检查Authorization头
    auth_header = request.headers.get('Authorization')
    
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(
            status_code=401,
            detail="No valid authentication credentials found",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = auth_header.split(' ')[1]
    
    try:
        token_data = auth_utils.verify_token(token)
        user_id = token_data["user_id"]
        
        logger.debug(f"Authenticated user: {user_id}")
        return user_id
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"JWT verification error: {e}")
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def get_user_id_from_stream_auth(
    request: Request,
    token: Optional[str] = None
) -> str:
    """
    支持流式端点的认证
    """
    try:
        # 首先尝试标准认证
        return await get_current_user_id_from_jwt(request)
    except HTTPException:
        pass
    
    # 尝试从查询参数获取token（用于EventSource）
    if token:
        try:
            token_data = auth_utils.verify_token(token)
            return token_data["user_id"]
        except Exception:
            pass
    
    raise HTTPException(
        status_code=401,
        detail="No valid authentication credentials found",
        headers={"WWW-Authenticate": "Bearer"}
    )

async def get_optional_user_id(request: Request) -> Optional[str]:
    """
    可选的用户认证，不强制要求认证
    """
    try:
        return await get_current_user_id_from_jwt(request)
    except HTTPException:
        return None

# 为了兼容现有代码，保持相同的函数名
async def verify_thread_access(client, thread_id: str, user_id: str):
    """
    验证用户对线程的访问权限
    简化版本，只检查用户是否为线程所有者
    """
    try:
        # 获取线程的用户ID（假设threads表有user_id字段）
        thread_result = await client.table('threads').select('account_id').eq('thread_id', thread_id).execute()
        
        if not thread_result.data:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        thread_user_id = thread_result.data[0]['account_id']
        
        # 检查是否为线程所有者
        if thread_user_id != user_id:
            raise HTTPException(status_code=403, detail="Access to this thread is forbidden")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying thread access: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error verifying thread access: {str(e)}"
        ) 