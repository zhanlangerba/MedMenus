from typing import Optional
import uuid

from agentpress.thread_manager import ADKThreadManager
from agentpress.tool import Tool
from daytona_sdk import AsyncSandbox  # type: ignore
from sandbox.sandbox import get_or_start_sandbox, create_sandbox, delete_sandbox
from utils.logger import logger
from utils.files_utils import clean_path

class SandboxToolsBase(Tool):
    """对于所有沙箱工具的基类，提供基于项目的沙箱访问。"""
    
    # 类变量，跟踪是否已打印沙箱URL
    _urls_printed = False
    
    def __init__(self, project_id: str, thread_manager: Optional[ADKThreadManager] = None):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.workspace_path = "/workspace"
        self._sandbox = None
        self._sandbox_id = None
        self._sandbox_pass = None

    async def _ensure_sandbox(self) -> AsyncSandbox:
        """确保有一个有效的沙箱实例，如果需要，从项目中检索它。

        如果项目还没有沙箱，懒加载创建它，并将元数据持久化到 `projects` 表，以便后续调用可以重用它。
        """
        if self._sandbox is None:
            try:
                # 获取数据库客户端
                client = await self.thread_manager.db.client

                # 获取项目数据
                project = await client.table('projects').select('*').eq('project_id', self.project_id).execute()
                if not project.data or len(project.data) == 0:
                    raise ValueError(f"Project {self.project_id} not found")

                project_data = project.data[0]
                sandbox_info = project_data.get('sandbox') or {}

                # 如果项目没有记录沙箱，懒加载创建一个
                if not sandbox_info.get('id'):
                    logger.info(f"No sandbox recorded for project {self.project_id}; creating lazily")
                    sandbox_pass = str(uuid.uuid4())
                    sandbox_obj = await create_sandbox(sandbox_pass, self.project_id)
                    sandbox_id = sandbox_obj.id

                    # 收集预览链接和令牌（最佳努力解析）
                    try:
                        vnc_link = await sandbox_obj.get_preview_link(6080)
                        website_link = await sandbox_obj.get_preview_link(8080)
                        vnc_url = vnc_link.url if hasattr(vnc_link, 'url') else str(vnc_link).split("url='")[1].split("'")[0]
                        website_url = website_link.url if hasattr(website_link, 'url') else str(website_link).split("url='")[1].split("'")[0]
                        token = vnc_link.token if hasattr(vnc_link, 'token') else (str(vnc_link).split("token='")[1].split("'")[0] if "token='" in str(vnc_link) else None)
                    except Exception:
                        # 如果预览链接提取失败，仍继续但将字段设置为 None
                        logger.warning(f"Failed to extract preview links for sandbox {sandbox_id}", exc_info=True)
                        vnc_url = None
                        website_url = None
                        token = None

                    # 持久化沙箱元数据到项目记录
                    update_result = await client.table('projects').update({
                        'sandbox': {
                            'id': sandbox_id,
                            'pass': sandbox_pass,
                            'vnc_preview': vnc_url,
                            'sandbox_url': website_url,
                            'token': token
                        }
                    }).eq('project_id', self.project_id).execute()

                    if not update_result.data:
                        # 如果DB更新失败，清理创建的沙箱
                        try:
                            await delete_sandbox(sandbox_id)
                        except Exception:
                            logger.error(f"Failed to delete sandbox {sandbox_id} after DB update failure", exc_info=True)
                        raise Exception("Database update failed when storing sandbox metadata")

                    # 存储本地元数据并确保沙箱已准备好
                    self._sandbox_id = sandbox_id
                    self._sandbox_pass = sandbox_pass
                    self._sandbox = await get_or_start_sandbox(self._sandbox_id)
                else:
                    # 使用现有的沙箱元数据
                    self._sandbox_id = sandbox_info['id']
                    self._sandbox_pass = sandbox_info.get('pass')
                    self._sandbox = await get_or_start_sandbox(self._sandbox_id)

            except Exception as e:
                logger.error(f"Error retrieving/creating sandbox for project {self.project_id}: {str(e)}", exc_info=True)
                raise e

        return self._sandbox

    @property
    def sandbox(self) -> AsyncSandbox:
        """Get the sandbox instance, ensuring it exists."""
        if self._sandbox is None:
            raise RuntimeError("Sandbox not initialized. Call _ensure_sandbox() first.")
        return self._sandbox

    @property
    def sandbox_id(self) -> str:
        """Get the sandbox ID, ensuring it exists."""
        if self._sandbox_id is None:
            raise RuntimeError("Sandbox ID not initialized. Call _ensure_sandbox() first.")
        return self._sandbox_id

    def clean_path(self, path: str) -> str:
        """Clean and normalize a path to be relative to /workspace."""
        cleaned_path = clean_path(path, self.workspace_path)
        logger.debug(f"Cleaned path: {path} -> {cleaned_path}")
        return cleaned_path