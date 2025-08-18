"""
简化的JWT认证工具
"""

import jwt
import bcrypt
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException
from utils.config import config
from utils.logger import logger

# 简化的JWT配置
JWT_SECRET = getattr(config, 'JWT_SECRET_KEY', 'your-secret-key-change-in-production')
ACCESS_TOKEN_EXPIRE_HOURS = 24  # 24小时
REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30天

class SimpleAuth:
    """简化的认证工具类"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """验证密码"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    @staticmethod
    def create_access_token(user_id: str) -> str:
        """创建访问token"""
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    
    @staticmethod
    def create_refresh_token() -> str:
        """创建刷新token"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def verify_token(token: str) -> Dict[str, Any]:
        """验证访问token"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
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
        """哈希刷新token用于存储"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    def get_refresh_token_expire_time() -> datetime:
        """获取刷新token过期时间"""
        return datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS) 