
from dotenv import load_dotenv
from utils.logger import logger
from utils.config import config
from utils.config import Configuration
import os
import json

load_dotenv(override=True)

logger.debug("Initializing PPIP/E2B sandbox configuration")

# 🔧 PPIO/E2B 配置 - 根据 PPIO 文档要求
# 设置 PPIO 沙箱域名
os.environ['E2B_DOMAIN'] = getattr(config, 'E2B_DOMAIN', 'sandbox.ppio.cn')

# 设置 E2B API Key
if hasattr(config, 'E2B_API_KEY') and config.E2B_API_KEY:
    os.environ['E2B_API_KEY'] = config.E2B_API_KEY
    logger.debug("E2B API key configured successfully")
elif 'E2B_API_KEY' in os.environ:
    logger.debug("E2B API key found in environment variables")
else:
    logger.warning("No E2B API key found in environment variables")

logger.debug(f"PPIO E2B Domain set to: {os.environ.get('E2B_DOMAIN')}")
logger.debug(f"E2B API Key configured: {'Yes' if os.environ.get('E2B_API_KEY') else 'No'}")

async def get_or_start_sandbox(sandbox_id: str):
    """Retrieve a sandbox by ID, check its state, and start it if needed."""
    
    logger.info(f"Getting or starting sandbox with ID: {sandbox_id}")

    try:
        # 🔗 直接连接到现有沙箱 - PPIO 方式
        try:
            # 尝试直接连接到沙箱
            sandbox = Sandbox(sandbox_id)
            logger.info(f"Connected to sandbox {sandbox_id}")
            
        except Exception as connect_error:
            logger.warning(f"Failed to connect to sandbox {sandbox_id}: {connect_error}")
            raise Exception(f"Sandbox {sandbox_id} not found or not accessible")
        
        logger.info(f"Sandbox {sandbox_id} is ready")
        return sandbox
        
    except Exception as e:
        logger.error(f"Error retrieving or starting sandbox: {str(e)}")
        raise e

async def start_supervisord_session(sandbox):
    """Start supervisord in a session."""
    session_id = "supervisord-session"
    try:
        logger.info(f"Creating session {session_id} for supervisord")
        
        # 在 PPIO/E2B 中使用 commands.run 执行命令
        # 首先检查 supervisord 是否已经运行
        check_result = sandbox.commands.run("pgrep supervisord || echo 'not_running'")
        
        if 'not_running' in check_result.stdout:
            # 启动 supervisord
            sandbox.commands.run(
                "exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf &"
            )
            logger.info(f"Supervisord started in session {session_id}")
        else:
            logger.info("Supervisord is already running")
            
    except Exception as e:
        logger.error(f"Error starting supervisord session: {str(e)}")
        raise e

async def create_sandbox(password: str, project_id: str = None, sandbox_type: str = 'desktop'):
    """
    Create a new sandbox with all required services configured and running.
    
    Args:
        password: VNC 密码
        project_id: 项目ID  
        sandbox_type: 沙箱类型 ('desktop', 'browser', 'code', 'base')
    """
    
    # https://ppio.com/docs/sandbox/e2b-sandbox
    logger.debug(f"Creating new PPIP/E2B sandbox environment with type: {sandbox_type}")
    logger.debug("Configuring sandbox with template and environment variables")
    
    # 获取对应的模板ID
    template_id = config.get_sandbox_template(sandbox_type)
    logger.info(f"Using template: {template_id} for type: {sandbox_type}")
    
    # 准备元数据，用于沙箱管理和查询
    # PPIO E2B metadata 中所有值必须是字符串类型
    metadata = {
        # 基础信息
        'project_type': 'chrome_vnc',
        'created_by': 'agent_system',
        'version': '1.0',
        'sandbox_type': sandbox_type,
        
        # Chrome/VNC 配置摘要 - 转换为 JSON 字符串
        'chrome_config': json.dumps({
            'persistent_session': True,
            'resolution': '1024x768x24', 
            'debugging_port': '9222',
            'vnc_enabled': True
        }),
        
        # 资源配置 - 转换为 JSON 字符串
        'resources': json.dumps({
            'cpu': 2,
            'memory': 4,
            'disk': 5
        }),
        
        # 标签 - 转换为逗号分隔的字符串
        'tags': ','.join(['chrome', 'vnc', 'agent_sandbox', sandbox_type])
    }
    
    if project_id:
        logger.debug(f"Using project_id as metadata: {project_id}")
        metadata['project_id'] = project_id
        
    # 创建沙盒 - PPIO 使用正确的关键字参数
    logger.info(f"Creating sandbox with template: {template_id}")
    
    # 如果是桌面模板，需要启动桌面流
    if sandbox_type == 'desktop':
        from e2b_desktop import Sandbox  # type: ignore
        sandbox = Sandbox(
            template=template_id,           # 使用动态模板ID
            timeout=15 * 60,                # 使用 timeout 参数（秒为单位）
            metadata=metadata               # 直接传递 metadata
        )
        try:
            logger.info("Starting desktop stream for VNC access...")
            sandbox.stream.start()
            logger.info("Desktop stream started successfully")

            url = sandbox.stream.get_url()
            logger.info(f"Desktop stream URL: {url}")
        except Exception as e:
            logger.warning(f"Failed to start desktop stream: {e}")
            # 不阻止沙箱创建，可能在后续获取链接时再试

    # TODO
    # 如果是浏览器模板，验证 Chrome 调试端口可用性
    if sandbox_type == 'browser':
        try:
            logger.info("Verifying Chrome debugging protocol availability...")
            # 验证 9223 端口是否可用 (Chrome 调试协议端口)
            chrome_host = sandbox.get_host(9223)
            cdp_url = f"https://{chrome_host}"
            logger.info(f"Chrome 调试协议地址可用: {cdp_url}")
    
            # 可以添加更多浏览器相关的验证
            logger.info("Browser sandbox initialized successfully")
            
        except Exception as e:
            logger.warning(f"Browser sandbox initialization warning: {e}")
            # 不阻止沙箱创建，浏览器可能需要一些时间启动
    
    # 设置环境变量
    try:
        await setup_environment_variables(sandbox, password)
    except Exception as env_error:
        logger.warning(f"环境变量设置失败: {env_error}")
        # 继续执行，环境变量设置失败不应该阻止沙箱创建
    
    # 启动 supervisord
    try:
        await start_supervisord_session(sandbox)
    except Exception as supervisord_error:
        logger.warning(f"Supervisord 启动失败: {supervisord_error}")
        # 继续执行，supervisord 启动失败不应该阻止沙箱创建
    
    logger.debug(f"Sandbox environment successfully initialized")
    return sandbox

async def setup_environment_variables(sandbox, password: str):
    """设置沙箱环境变量"""
    logger.debug("Setting up environment variables")
    
    # 环境变量配置
    env_vars = {
        "CHROME_PERSISTENT_SESSION": "true", # Chrome 持久化会话配置：开启
        "RESOLUTION": "1024x768x24",  # VNC 远程桌面配置：完整分辨率（宽高像素）
        "RESOLUTION_WIDTH": "1024",  # VNC 远程桌面配置：宽度像素
        "RESOLUTION_HEIGHT": "768",  # VNC 远程桌面配置：高度像素
        "VNC_PASSWORD": password,  # VNC 远程桌面配置：密码
        "ANONYMIZED_TELEMETRY": "false",  # 匿名化遥测配置：关闭
        "CHROME_PATH": "",  # Chrome 路径
        "CHROME_USER_DATA": "",  # Chrome 用户数据路径
        "CHROME_DEBUGGING_PORT": "9222",  # Chrome 调试端口
        "CHROME_DEBUGGING_HOST": "localhost",  # Chrome 调试主机
        "CHROME_CDP": ""  # Chrome CDP 配置

    }
    
    # 通过 commands.run 设置环境变量
    for key, value in env_vars.items():
        try:
            # 设置当前会话的环境变量
            sandbox.commands.run(f'export {key}="{value}"')
            
            # 添加到 .bashrc 以持久化
            sandbox.commands.run(f'echo \'export {key}="{value}"\' >> ~/.bashrc')
            
        except Exception as e:
            logger.warning(f"Failed to set environment variable {key}: {e}")
    
    # 重新加载 .bashrc
    try:
        sandbox.commands.run('source ~/.bashrc')
        logger.debug("Environment variables configured successfully")
    except Exception as e:
        logger.warning(f"Failed to reload .bashrc: {e}")

async def delete_sandbox(sandbox_id: str) -> bool:
    """Delete a sandbox by its ID."""
    logger.info(f"Deleting sandbox with ID: {sandbox_id}")

    try:
        # 🗑️ 在 PPIO/E2B 中删除沙箱 - 先连接再删除
        sandbox = Sandbox(sandbox_id)
        await sandbox.kill()
        
        logger.info(f"Successfully deleted sandbox {sandbox_id}")
        return  
    except Exception as e:
        logger.error(f"Error deleting sandbox {sandbox_id}: {str(e)}")
        raise e

async def pause_sandbox(sandbox) -> str:
    """暂停沙箱（替代 Daytona 的归档功能）"""
    logger.info(f"Pausing sandbox {sandbox.sandboxId}")
    
    try:
        # 🎯 暂停沙箱
        sandbox_id = await sandbox.pause()
        logger.info(f"Successfully paused sandbox {sandbox_id}")
        return sandbox_id
    except Exception as e:
        logger.error(f"Error pausing sandbox: {e}")
        raise e

async def get_sandbox_metrics(sandbox):
    """获取沙箱资源使用指标"""
    try:
        metrics = await sandbox.getMetrics()
        logger.debug(f"Sandbox metrics: {metrics}")
        return metrics
    except Exception as e:
        logger.warning(f"Failed to get sandbox metrics: {e}")
        return None

async def list_sandboxes(metadata_filter: dict = None):
    """列出所有沙箱 - PPIO 暂不支持复杂查询，返回空列表"""
    try:
        # PPIO 的 E2B SDK 可能不支持复杂的列表查询
        # 这里返回空列表，实际使用中可能需要其他方式管理沙箱列表
        logger.warning("PPIO sandbox listing not fully supported, returning empty list")
        return []
    except Exception as e:
        logger.error(f"Error listing sandboxes: {e}")
        return []


# 元数据的实际使用示例
async def find_chrome_sandboxes():
    """查找所有 Chrome 类型的沙箱"""
    return await list_sandboxes({'project_type': 'chrome_vnc'})

async def find_project_sandboxes(project_id: str):
    """查找特定项目的沙箱"""
    return await list_sandboxes({'project_id': project_id})

async def find_agent_sandboxes():
    """查找所有 agent 创建的沙箱"""
    return await list_sandboxes({'created_by': 'agent_system'})

async def get_sandbox_config_summary(sandbox):
    """从元数据快速获取配置摘要"""
    try:
        info = await sandbox.getInfo()
        metadata = info.get('metadata', {})
        
        return {
            'type': metadata.get('project_type', 'unknown'),
            'chrome_config': metadata.get('chrome_config', {}),
            'resources': metadata.get('resources', {}),
            'tags': metadata.get('tags', [])
        }
    except Exception as e:
        logger.warning(f"Failed to get config summary: {e}")
        return None
