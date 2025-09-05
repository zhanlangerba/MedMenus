"""
ADK Compatible Tool Manager

这个工具管理器展示了如何将新的沙盒工厂类集成到现有的agent设置中
"""

from typing import Dict, Any, Optional
from agentpress.thread_manager import ADKThreadManager
from utils.logger import logger
from utils.config import config

# 导入新的ADK工厂类
from agent.tools.web_search_tool_adk import SandboxWebSearchToolFactory

# 导入其他现有工具（这些可能需要类似的ADK改造）
from agent.tools.message_tool import MessageTool
from agent.tools.expand_msg_tool import ExpandMessageTool

class ADKToolManager:
    """ADK兼容的工具管理器"""
    
    def __init__(self, thread_manager: ADKThreadManager, project_id: str, thread_id: str):
        self.thread_manager = thread_manager
        self.project_id = project_id
        self.thread_id = thread_id
        
        # 创建沙盒工具工厂
        self.sandbox_tool_factory = SandboxWebSearchToolFactory(project_id, thread_manager)
        
    def register_all_tools(self):
        """注册所有可用的工具"""
        logger.info("Starting ADK tool registration...")
        
        # 1. 注册基础消息工具（这些可能需要转换为ADK格式）
        self._register_message_tools()
        
        # 2. 注册沙盒工具（使用新的工厂类）
        self._register_sandbox_tools()
        
        # 3. 注册其他工具
        self._register_additional_tools()
        
        logger.info("ADK tool registration completed")
    
    def _register_message_tools(self):
        """注册消息相关工具"""
        try:
            # 注意：这些工具可能需要转换为ADK兼容的FunctionTool格式
            # 目前保持原有方式，但将来可能需要改造
            self.thread_manager.add_tool(ExpandMessageTool, thread_id=self.thread_id, thread_manager=self.thread_manager)
            self.thread_manager.add_tool(MessageTool)
            logger.info("✅ Message tools registered")
        except Exception as e:
            logger.error(f"❌ Failed to register message tools: {e}")
    
    def _register_sandbox_tools(self):
        """注册沙盒工具（使用新的ADK工厂类）"""
        try:
            # 使用工厂类创建ADK兼容的工具
            web_search_tool = self.sandbox_tool_factory.create_web_search_tool()
            scrape_tool = self.sandbox_tool_factory.create_scrape_tool()
            
            # 注册到thread_manager
            # 注意：这里可能需要适配具体的注册方式，取决于ADKThreadManager的实现
            self.thread_manager.add_tool(web_search_tool)
            self.thread_manager.add_tool(scrape_tool)
            
            logger.info("✅ Sandbox web search tools registered (ADK version)")
        except Exception as e:
            logger.error(f"❌ Failed to register sandbox tools: {e}")
    
    def _register_additional_tools(self):
        """注册其他工具"""
        try:
            # 这里可以添加其他需要的工具
            # 例如文件工具、Shell工具等的ADK版本
            
            # 示例：如果有数据提供工具
            if config.RAPID_API_KEY:
                # self.thread_manager.add_tool(DataProvidersTool)  # 需要ADK版本
                pass
                
            logger.info("✅ Additional tools registered")
        except Exception as e:
            logger.error(f"❌ Failed to register additional tools: {e}")
    
    def register_agent_builder_tools(self, agent_id: str):
        """注册Agent Builder相关工具"""
        try:
            # 这些工具可能也需要转换为ADK格式
            # 目前保持原有方式作为过渡
            from agent.tools.agent_builder_tools.agent_config_tool import AgentConfigTool
            from agent.tools.agent_builder_tools.mcp_search_tool import MCPSearchTool
            from agent.tools.agent_builder_tools.credential_profile_tool import CredentialProfileTool
            from agent.tools.agent_builder_tools.workflow_tool import WorkflowTool
            from agent.tools.agent_builder_tools.trigger_tool import TriggerTool
            from services.postgresql import DBConnection
            
            db = DBConnection()
            self.thread_manager.add_tool(AgentConfigTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
            self.thread_manager.add_tool(MCPSearchTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
            self.thread_manager.add_tool(CredentialProfileTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
            self.thread_manager.add_tool(WorkflowTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
            self.thread_manager.add_tool(TriggerTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
            
            logger.info("✅ Agent builder tools registered")
        except Exception as e:
            logger.error(f"❌ Failed to register agent builder tools: {e}")
    
    def register_custom_tools(self, enabled_tools: Dict[str, Any]):
        """注册自定义启用的工具"""
        try:
            logger.info(f"Registering custom tools: {enabled_tools}")
            
            # 根据enabled_tools配置注册特定工具
            for tool_name, tool_config in enabled_tools.items():
                if not tool_config.get('enabled', False):
                    continue
                    
                if tool_name == 'web_search':
                    # 使用新的ADK版本
                    self._register_sandbox_tools()
                elif tool_name == 'message':
                    self._register_message_tools()
                # 可以根据需要添加更多工具的条件注册
                
            logger.info("✅ Custom tools registered")
        except Exception as e:
            logger.error(f"❌ Failed to register custom tools: {e}")

# 使用示例：如何在现有代码中集成
def integrate_adk_tools_in_agent_run():
    """展示如何在agent/run.py中集成ADK工具管理器"""
    
    # 在 AgentRunner.setup_tools() 方法中，可以这样修改：
    
    example_code = '''
    async def setup_tools(self):
        # 使用新的ADK工具管理器
        tool_manager = ADKToolManager(self.thread_manager, self.config.project_id, self.config.thread_id)
        
        if self.config.agent_config and self.config.agent_config.get('is_suna_default', False):
            suna_agent_id = self.config.agent_config['agent_id']
            tool_manager.register_agent_builder_tools(suna_agent_id)
        
        if self.config.is_agent_builder:
            tool_manager.register_agent_builder_tools(self.config.target_agent_id)

        enabled_tools = None
        if self.config.agent_config and 'agentpress_tools' in self.config.agent_config:
            raw_tools = self.config.agent_config['agentpress_tools']
            
            if isinstance(raw_tools, dict):
                if self.config.agent_config.get('is_suna_default', False) and not raw_tools:
                    enabled_tools = None
                else:
                    enabled_tools = raw_tools
            else:
                enabled_tools = None

        if enabled_tools is None:
            tool_manager.register_all_tools()
        else:
            if not isinstance(enabled_tools, dict):
                enabled_tools = {}
            tool_manager.register_custom_tools(enabled_tools)
    '''
    
    return example_code

if __name__ == "__main__":
    print("=== ADK Tool Manager Example ===")
    print(integrate_adk_tools_in_agent_run())
    print("\n✅ Integration example generated") 