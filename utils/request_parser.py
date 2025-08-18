"""
通用请求数据解析工具
处理各种前端数据格式
"""

import json
from typing import Dict, Any, Optional
from fastapi import Request

async def parse_request_data(request: Request) -> Dict[str, Any]:
    """
    解析请求数据，支持多种格式
    """
    result = {}
    
    # 获取原始数据
    body = await request.body()
    print(f"Raw request body: {body}")
    
    # 尝试解析为表单数据
    try:
        form_data = await request.form()
        print(f"Form data: {dict(form_data)}")
        result.update(dict(form_data))
    except Exception as e:
        print(f"Form parsing failed: {e}")
    
    # 尝试解析为JSON数据
    try:
        json_data = await request.json()
        print(f"JSON data: {json_data}")
        result.update(json_data)
    except Exception as e:
        print(f"JSON parsing failed: {e}")
    
    # 尝试解析为查询参数
    try:
        query_params = dict(request.query_params)
        print(f"Query params: {query_params}")
        result.update(query_params)
    except Exception as e:
        print(f"Query params parsing failed: {e}")
    
    # 尝试解析为URL编码数据
    try:
        if body:
            body_str = body.decode('utf-8')
            print(f"Body string: {body_str}")
            
            # 解析URL编码格式
            if '=' in body_str and '&' in body_str:
                url_encoded = {}
                for pair in body_str.split('&'):
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        url_encoded[key] = value
                print(f"URL encoded: {url_encoded}")
                result.update(url_encoded)
            
            # 解析多行格式（如前端发送的格式）
            elif '\n' in body_str:
                lines = body_str.strip().split('\n')
                multi_line = {}
                for i in range(0, len(lines), 2):
                    if i + 1 < len(lines):
                        key = lines[i].strip()
                        value = lines[i + 1].strip()
                        multi_line[key] = value
                print(f"Multi-line format: {multi_line}")
                result.update(multi_line)
    
    except Exception as e:
        print(f"Body parsing failed: {e}")
    
    print(f"Final parsed data: {result}")
    return result

def extract_auth_data(data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    从解析的数据中提取认证信息
    """
    email = None
    password = None
    confirmPassword = None
    origin = None
    
    # 尝试多种可能的键名
    email_keys = ['email', '1_email', 'user_email', 'mail']
    password_keys = ['password', '1_password', 'user_password', 'pass']
    confirm_keys = ['confirmPassword', '1_confirmPassword', 'confirm_password', 'password_confirm']
    origin_keys = ['origin', '1_origin', 'referer', 'source']
    
    for key in email_keys:
        if key in data:
            email = data[key]
            break
    
    for key in password_keys:
        if key in data:
            password = data[key]
            break
    
    for key in confirm_keys:
        if key in data:
            confirmPassword = data[key]
            break
    
    for key in origin_keys:
        if key in data:
            origin = data[key]
            break
    
    return {
        'email': email,
        'password': password,
        'confirmPassword': confirmPassword,
        'origin': origin
    } 