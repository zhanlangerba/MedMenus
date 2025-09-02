"""
JSON Web Token
"""

import jwt # type: ignore
# import PyJWT as jwt # type: ignore
import bcrypt # type: ignore
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException # type: ignore
from utils.config import config
from utils.logger import logger

class AuthUtils:
    """专业的JWT认证工具"""
    
    # JWT配置
    JWT_SECRET = getattr(config, 'JWT_SECRET_KEY', 'your-secret-key-change-in-production')
    ACCESS_TOKEN_EXPIRE_HOURS = 24  # 普通接口访问携带的token过期时间为24小时
    REFRESH_TOKEN_EXPIRE_DAYS = 30  # 刷新token过期时间为30天
    
    @classmethod
    def initialize(cls):
        """初始化认证工具并记录配置信息"""
        logger.info(f"AuthUtils initialized with config:")
        logger.info(f"  - JWT_SECRET: {'*' * 10} (length: {len(cls.JWT_SECRET)})")
        logger.info(f"  - ACCESS_TOKEN_EXPIRE_HOURS: {cls.ACCESS_TOKEN_EXPIRE_HOURS}")
        logger.info(f"  - REFRESH_TOKEN_EXPIRE_DAYS: {cls.REFRESH_TOKEN_EXPIRE_DAYS}")
        
        # 验证JWT密钥
        if cls.JWT_SECRET == 'your-secret-key-change-in-production':
            logger.warning("Using default JWT secret key! Please change in production!")
        else:
            logger.info("JWT secret key is configured")
    
    @staticmethod
    def hash_password(password: str) -> str:
        """密码哈希"""
        try:
            hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            logger.info(f"Password hashed successfully, length: {len(hashed)}")
            return hashed
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            raise
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """密码验证"""
        try:
            is_valid = bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
            if is_valid:
                logger.info("Password verification successful")
            else:
                logger.warning("Password verification failed: invalid password")
            return is_valid
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False
    
    @staticmethod
    def create_access_token(user_id: str) -> str:
        """创建访问token"""
        try:
            expire = datetime.now(timezone.utc) + timedelta(hours=AuthUtils.ACCESS_TOKEN_EXPIRE_HOURS)
            payload = {
                "sub": user_id,
                "exp": expire,
                "iat": datetime.now(timezone.utc),
                "type": "access"
            }
            token = jwt.encode(payload, AuthUtils.JWT_SECRET, algorithm="HS256")
            logger.info(f"Created access token for user {user_id}, expires at {expire}")
            return token
        except Exception as e:
            logger.error(f"Failed to create access token for user {user_id}: {e}")
            raise
    
    @staticmethod
    def create_refresh_token() -> str:
        """创建刷新token"""
        try:
            token = secrets.token_urlsafe(32)
            logger.info(f"Created refresh token: {token[:8]}...")
            return token
        except Exception as e:
            logger.error(f"Failed to create refresh token: {e}")
            raise
    
    @staticmethod
    def verify_token(token: str) -> Dict[str, Any]:
        """验证token"""
        try:
            logger.debug(f"Verifying token: {token[:10]}...")
            payload = jwt.decode(token, AuthUtils.JWT_SECRET, algorithms=["HS256"])
            user_id = payload.get("sub")
            if not user_id:
                logger.warning(f"Token verification failed: missing user_id in payload")
                raise HTTPException(status_code=401, detail="Invalid token")
            logger.info(f"Token verified successfully for user {user_id}")
            return {"user_id": user_id, "payload": payload}
        except jwt.ExpiredSignatureError:
            logger.warning(f"Token verification failed: token expired")
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            logger.warning(f"Token verification failed: invalid token")
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            raise HTTPException(status_code=401, detail="Token verification failed")
    
    @staticmethod
    def hash_refresh_token(token: str) -> str:
        """哈希刷新token"""
        try:
            hashed = hashlib.sha256(token.encode()).hexdigest()
            logger.debug(f"Refresh token hashed: {hashed[:8]}...")
            return hashed
        except Exception as e:
            logger.error(f"Failed to hash refresh token: {e}")
            raise
    
    @staticmethod
    def get_refresh_token_expire_time() -> datetime:
        """获取刷新token过期时间"""
        try:
            expire_time = datetime.now(timezone.utc) + timedelta(days=AuthUtils.REFRESH_TOKEN_EXPIRE_DAYS)
            logger.debug(f"Refresh token expire time calculated: {expire_time}")
            return expire_time
        except Exception as e:
            logger.error(f"Failed to calculate refresh token expire time: {e}")
            raise
    
    @staticmethod
    def is_token_expired(token: str) -> bool:
        """检查token是否过期"""
        try:
            logger.debug(f"Checking token expiration: {token[:10]}...")
            payload = jwt.decode(token, AuthUtils.JWT_SECRET, algorithms=["HS256"])
            exp = payload.get("exp")
            if exp:
                is_expired = datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc)
                if is_expired:
                    logger.info("Token is expired")
                else:
                    logger.debug("Token is still valid")
                return is_expired
            logger.warning("Token has no expiration time")
            return True
        except Exception as e:
            logger.error(f"Error checking token expiration: {e}")
            return True

    @staticmethod
    async def get_account_id_from_thread(client, thread_id: str) -> str:
        """
        根据线程ID获取账户ID
        
        Args:
            client: 数据库客户端
            thread_id: 线程ID
            
        Returns:
            str: 账户ID
            
        Raises:
            HTTPException: 如果线程不存在
        """
        try:
            thread_result = await client.table('threads').select('account_id').eq('thread_id', thread_id).execute()
            if not thread_result.data:
                logger.error(f"Thread not found: {thread_id}")
                raise HTTPException(status_code=404, detail="Thread not found")
            
            account_id = thread_result.data[0]['account_id']
            logger.debug(f"Retrieved account_id {account_id} for thread {thread_id}")
            return account_id
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting account_id from thread {thread_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Error retrieving account information: {str(e)}")
