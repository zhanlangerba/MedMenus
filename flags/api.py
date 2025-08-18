from fastapi import APIRouter, Request
from utils.logger import logger
from .flags import list_flags, is_enabled, get_flag_details

router = APIRouter()


@router.get("/feature-flags")
async def get_feature_flags(request: Request):
    """获取所有功能标志"""
    logger.info(f"🔍 [FLAGS] GET /feature-flags called")
    logger.info(f"🔍 [FLAGS] Headers: {dict(request.headers)}")
    
    try:
        logger.info(f"🔍 [FLAGS] Calling list_flags()...")
        flags = await list_flags()
        logger.info(f"✅ [FLAGS] Successfully got flags: {flags}")
        return {"flags": flags}
    except Exception as e:
        logger.error(f"❌ [FLAGS] Error fetching feature flags: {str(e)}")
        logger.error(f"❌ [FLAGS] Exception type: {type(e)}")
        import traceback
        logger.error(f"❌ [FLAGS] Traceback: {traceback.format_exc()}")
        return {"flags": {}}

@router.get("/feature-flags/{flag_name}")
async def get_feature_flag(flag_name: str, request: Request):
    """获取特定功能标志状态"""
    logger.info(f"🔍 [FLAGS] GET /feature-flags/{flag_name} called")
    logger.info(f"🔍 [FLAGS] Headers: {dict(request.headers)}")
    logger.info(f"🔍 [FLAGS] Flag name: {flag_name}")
    
    try:
        logger.info(f"🔍 [FLAGS] Calling is_enabled('{flag_name}')...")
        enabled = await is_enabled(flag_name)
        logger.info(f"✅ [FLAGS] Flag {flag_name} enabled: {enabled}")
        
        logger.info(f"🔍 [FLAGS] Calling get_flag_details('{flag_name}')...")
        details = await get_flag_details(flag_name)
        logger.info(f"✅ [FLAGS] Flag {flag_name} details: {details}")
        
        response = {
            
            "flag_name": flag_name,
            "enabled": enabled,
            "details": details
        }
        logger.info(f"✅ [FLAGS] Returning response: {response}")
        return response
        
    except Exception as e:
        logger.error(f"❌ [FLAGS] Error fetching feature flag {flag_name}: {str(e)}")
        logger.error(f"❌ [FLAGS] Exception type: {type(e)}")
        import traceback
        logger.error(f"❌ [FLAGS] Traceback: {traceback.format_exc()}")
        return {
            "flag_name": flag_name,
            "enabled": False,
            "details": None
        }

@router.options("/feature-flags/{flag_name}")
async def options_feature_flag(flag_name: str, request: Request):
    """处理OPTIONS请求（CORS预检）"""
    logger.info(f"🔍 [FLAGS] OPTIONS /feature-flags/{flag_name} called")
    logger.info(f"🔍 [FLAGS] Headers: {dict(request.headers)}")
    logger.info(f"🔍 [FLAGS] Flag name: {flag_name}")
    
    # 返回CORS预检响应
    from fastapi.responses import Response
    response = Response()
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Max-Age"] = "86400"
    
    logger.info(f"✅ [FLAGS] Returning CORS preflight response")
    return response 