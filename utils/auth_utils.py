"""
JWT认证工具
专业的用户认证工具类
"""

try:
    import jwt
    # 测试是否有encode方法
    if not hasattr(jwt, 'encode'):
        raise ImportError("Wrong jwt package installed")
except ImportError:
    # 如果jwt包有问题，尝试使用PyJWT
    try:
        import PyJWT as jwt
    except ImportError:
        print("❌ 请安装正确的JWT包: pip uninstall jwt && pip install PyJWT")
        raise
import bcrypt
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import HTTPException
from utils.config import config
from utils.logger import logger

class AuthUtils:
    """专业的JWT认证工具"""
    
    # JWT配置
    JWT_SECRET = getattr(config, 'JWT_SECRET_KEY', 'your-secret-key-change-in-production')
    ACCESS_TOKEN_EXPIRE_HOURS = 24
    REFRESH_TOKEN_EXPIRE_DAYS = 30
    
    @staticmethod
    def hash_password(password: str) -> str:
        """密码哈希"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, hashed: str) -> bool:
        """密码验证"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    @staticmethod
    def create_access_token(user_id: str) -> str:
        """创建访问token"""
        expire = datetime.now(timezone.utc) + timedelta(hours=AuthUtils.ACCESS_TOKEN_EXPIRE_HOURS)
        payload = {
            "sub": user_id,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access"
        }
        return jwt.encode(payload, AuthUtils.JWT_SECRET, algorithm="HS256")
    
    @staticmethod
    def create_refresh_token() -> str:
        """创建刷新token"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def verify_token(token: str) -> Dict[str, Any]:
        """验证token"""
        try:
            payload = jwt.decode(token, AuthUtils.JWT_SECRET, algorithms=["HS256"])
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token")
            return {"user_id": user_id, "payload": payload}
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
    
    @staticmethod
    def hash_refresh_token(token: str) -> str:
        """哈希刷新token"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    @staticmethod
    def get_refresh_token_expire_time() -> datetime:
        """获取刷新token过期时间"""
        return datetime.now(timezone.utc) + timedelta(days=AuthUtils.REFRESH_TOKEN_EXPIRE_DAYS)
    
    @staticmethod
    def is_token_expired(token: str) -> bool:
        """检查token是否过期"""
        try:
            payload = jwt.decode(token, AuthUtils.JWT_SECRET, algorithms=["HS256"])
            exp = payload.get("exp")
            if exp:
                return datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc)
            return True
        except:
            return True
