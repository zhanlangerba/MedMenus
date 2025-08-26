import os
import json
import asyncio
import datetime
from typing import Optional, Dict, List, Any, AsyncGenerator
from dataclasses import dataclass
import traceback

from agent.tools.message_tool import MessageTool
# from agent.tools.sb_deploy_tool import SandboxDeployTool
# from agent.tools.sb_expose_tool import SandboxExposeTool
# from agent.tools.web_search_tool import SandboxWebSearchTool
from dotenv import load_dotenv # type: ignore
from utils.config import config
# from agent.agent_builder_prompt import get_agent_builder_prompt
from agentpress.thread_manager import ThreadManager
from agentpress.response_processor import ProcessorConfig
# from agent.tools.sb_shell_tool import SandboxShellTool
# from agent.tools.sb_files_tool import SandboxFilesTool
#from agent.tools.data_providers_tool import DataProvidersTool
# from agent.tools.expand_msg_tool import ExpandMessageTool
from agent.prompt import get_system_prompt
from agent.gemini_prompt import get_gemini_system_prompt
# from agent.custom_prompt import render_prompt_template
from utils.logger import logger
# from utils.auth_utils import get_account_id_from_thread
# from services.billing import check_billing_status
# from agent.tools.sb_vision_tool import SandboxVisionTool
# from agent.tools.sb_image_edit_tool import SandboxImageEditTool
# from agent.tools.sb_presentation_outline_tool import SandboxPresentationOutlineTool
# from agent.tools.sb_presentation_tool_v2 import SandboxPresentationToolV2
from services.langfuse import langfuse
try:
    from langfuse.client import StatefulTraceClient
except ImportError:
    # 对于 langfuse 3.x 版本，尝试不同的导入路径
    try:
        from langfuse import StatefulTraceClient
    except ImportError:
        # 如果都失败，使用 Any 类型
        from typing import Any
        StatefulTraceClient = Any

# from agent.tools.mcp_tool_wrapper import MCPToolWrapper
# from agent.tools.task_list_tool import TaskListTool
# from agentpress.tool import SchemaType
# from agent.tools.sb_sheets_tool import SandboxSheetsTool
# from agent.tools.sb_web_dev_tool import SandboxWebDevTool

load_dotenv()


@dataclass
class AgentConfig:
    thread_id: str
    project_id: str
    stream: bool
    native_max_auto_continues: int = 25
    max_iterations: int = 100
    model_name: str = "deepseek/deepseek-chat"
    enable_thinking: Optional[bool] = False
    reasoning_effort: Optional[str] = 'low'
    enable_context_manager: bool = True
    agent_config: Optional[dict] = None
    trace: Optional[StatefulTraceClient] = None
    is_agent_builder: Optional[bool] = False
    target_agent_id: Optional[str] = None


# class ToolManager:
#     def __init__(self, thread_manager: ThreadManager, project_id: str, thread_id: str):
#         self.thread_manager = thread_manager
#         self.project_id = project_id
#         self.thread_id = thread_id
    
#     def register_all_tools(self):
#         self.thread_manager.add_tool(ExpandMessageTool, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(MessageTool)
        
#         self.thread_manager.add_tool(SandboxShellTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxFilesTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxDeployTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxExposeTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxWebSearchTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxVisionTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxImageEditTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxPresentationOutlineTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(SandboxPresentationToolV2, project_id=self.project_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(TaskListTool, project_id=self.project_id, thread_manager=self.thread_manager, thread_id=self.thread_id)
#         self.thread_manager.add_tool(SandboxSheetsTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         # self.thread_manager.add_tool(SandboxWebDevTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         if config.RAPID_API_KEY:
#             self.thread_manager.add_tool(DataProvidersTool)
        

        
#         # Add Browser Tool
#         from agent.tools.browser_tool import BrowserTool
#         self.thread_manager.add_tool(BrowserTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
    
#     def register_agent_builder_tools(self, agent_id: str):
#         from agent.tools.agent_builder_tools.agent_config_tool import AgentConfigTool
#         from agent.tools.agent_builder_tools.mcp_search_tool import MCPSearchTool
#         from agent.tools.agent_builder_tools.credential_profile_tool import CredentialProfileTool
#         from agent.tools.agent_builder_tools.workflow_tool import WorkflowTool
#         from agent.tools.agent_builder_tools.trigger_tool import TriggerTool
#         from services.postgresql import DBConnection
        
#         db = DBConnection()
#         self.thread_manager.add_tool(AgentConfigTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
#         self.thread_manager.add_tool(MCPSearchTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
#         self.thread_manager.add_tool(CredentialProfileTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
#         self.thread_manager.add_tool(WorkflowTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
#         self.thread_manager.add_tool(TriggerTool, thread_manager=self.thread_manager, db_connection=db, agent_id=agent_id)
    
#     def register_custom_tools(self, enabled_tools: Dict[str, Any]):
#         self.thread_manager.add_tool(ExpandMessageTool, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         self.thread_manager.add_tool(MessageTool)
#         self.thread_manager.add_tool(TaskListTool, project_id=self.project_id, thread_manager=self.thread_manager, thread_id=self.thread_id)

#         def safe_tool_check(tool_name: str) -> bool:
#             try:
#                 if not isinstance(enabled_tools, dict):
#                     return False
#                 tool_config = enabled_tools.get(tool_name, {})
#                 if not isinstance(tool_config, dict):
#                     return bool(tool_config) if isinstance(tool_config, bool) else False
#                 return tool_config.get('enabled', False)
#             except Exception:
#                 return False
        
#         if safe_tool_check('sb_shell_tool'):
#             self.thread_manager.add_tool(SandboxShellTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_files_tool'):
#             self.thread_manager.add_tool(SandboxFilesTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_deploy_tool'):
#             self.thread_manager.add_tool(SandboxDeployTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_expose_tool'):
#             self.thread_manager.add_tool(SandboxExposeTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('web_search_tool'):
#             self.thread_manager.add_tool(SandboxWebSearchTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_vision_tool'):
#             self.thread_manager.add_tool(SandboxVisionTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_presentation_tool'):
#             self.thread_manager.add_tool(SandboxPresentationOutlineTool, project_id=self.project_id, thread_manager=self.thread_manager)
#             self.thread_manager.add_tool(SandboxPresentationToolV2, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_image_edit_tool'):
#             self.thread_manager.add_tool(SandboxImageEditTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_sheets_tool'):
#             self.thread_manager.add_tool(SandboxSheetsTool, project_id=self.project_id, thread_manager=self.thread_manager)
#         if safe_tool_check('sb_web_dev_tool'):
#             self.thread_manager.add_tool(SandboxWebDevTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)
#         if config.RAPID_API_KEY and safe_tool_check('data_providers_tool'):
#             self.thread_manager.add_tool(DataProvidersTool)

        
#         if safe_tool_check('browser_tool'):
#             from agent.tools.browser_tool import BrowserTool
#             self.thread_manager.add_tool(BrowserTool, project_id=self.project_id, thread_id=self.thread_id, thread_manager=self.thread_manager)


# class MCPManager:
#     def __init__(self, thread_manager: ThreadManager, account_id: str):
#         self.thread_manager = thread_manager
#         self.account_id = account_id
    
#     async def register_mcp_tools(self, agent_config: dict) -> Optional[MCPToolWrapper]:
#         all_mcps = []
        
#         if agent_config.get('configured_mcps'):
#             all_mcps.extend(agent_config['configured_mcps'])
        
#         if agent_config.get('custom_mcps'):
#             for custom_mcp in agent_config['custom_mcps']:
#                 custom_type = custom_mcp.get('customType', custom_mcp.get('type', 'sse'))
                
#                 if custom_type == 'pipedream':
#                     if 'config' not in custom_mcp:
#                         custom_mcp['config'] = {}
                    
#                     if not custom_mcp['config'].get('external_user_id'):
#                         profile_id = custom_mcp['config'].get('profile_id')
#                         if profile_id:
#                             try:
#                                 from pipedream import profile_service
#                                 from uuid import UUID
                                
#                                 profile = await profile_service.get_profile(UUID(self.account_id), UUID(profile_id))
#                                 if profile:
#                                     custom_mcp['config']['external_user_id'] = profile.external_user_id
#                             except Exception as e:
#                                 logger.error(f"Error retrieving external_user_id from profile {profile_id}: {e}")
                    
#                     if 'headers' in custom_mcp['config'] and 'x-pd-app-slug' in custom_mcp['config']['headers']:
#                         custom_mcp['config']['app_slug'] = custom_mcp['config']['headers']['x-pd-app-slug']
                
#                 elif custom_type == 'composio':
#                     qualified_name = custom_mcp.get('qualifiedName')
#                     if not qualified_name:
#                         qualified_name = f"composio.{custom_mcp['name'].replace(' ', '_').lower()}"
                    
#                     mcp_config = {
#                         'name': custom_mcp['name'],
#                         'qualifiedName': qualified_name,
#                         'config': custom_mcp.get('config', {}),
#                         'enabledTools': custom_mcp.get('enabledTools', []),
#                         'instructions': custom_mcp.get('instructions', ''),
#                         'isCustom': True,
#                         'customType': 'composio'
#                     }
#                     all_mcps.append(mcp_config)
#                     continue
                
#                 mcp_config = {
#                     'name': custom_mcp['name'],
#                     'qualifiedName': f"custom_{custom_type}_{custom_mcp['name'].replace(' ', '_').lower()}",
#                     'config': custom_mcp['config'],
#                     'enabledTools': custom_mcp.get('enabledTools', []),
#                     'instructions': custom_mcp.get('instructions', ''),
#                     'isCustom': True,
#                     'customType': custom_type
#                 }
#                 all_mcps.append(mcp_config)
        
#         if not all_mcps:
#             return None
        
#         mcp_wrapper_instance = MCPToolWrapper(mcp_configs=all_mcps)
#         try:
#             await mcp_wrapper_instance.initialize_and_register_tools()
            
#             updated_schemas = mcp_wrapper_instance.get_schemas()
#             for method_name, schema_list in updated_schemas.items():
#                 for schema in schema_list:
#                     self.thread_manager.tool_registry.tools[method_name] = {
#                         "instance": mcp_wrapper_instance,
#                         "schema": schema
#                     }
            
#             logger.info(f"⚡ Registered {len(updated_schemas)} MCP tools (Redis cache enabled)")
#             return mcp_wrapper_instance
#         except Exception as e:
#             logger.error(f"Failed to initialize MCP tools: {e}")
#             return None


class PromptManager:
    @staticmethod
    # async def build_system_prompt(model_name: str, agent_config: Optional[dict], 
    #                               is_agent_builder: bool, thread_id: str, 
    #                               mcp_wrapper_instance: Optional[MCPToolWrapper]) -> dict:
    async def build_system_prompt(model_name: str, agent_config: Optional[dict], 
                                  is_agent_builder: bool, thread_id: str, ) -> dict:    
        if "gemini-2.5-flash" in model_name.lower() and "gemini-2.5-pro" not in model_name.lower():
            default_system_content = get_gemini_system_prompt()
        else:
            default_system_content = get_system_prompt()
        
        if "anthropic" not in model_name.lower():
            sample_response_path = os.path.join(os.path.dirname(__file__), 'sample_responses/1.txt')
            with open(sample_response_path, 'r') as file:
                sample_response = file.read()
            default_system_content = default_system_content + "\n\n <sample_assistant_response>" + sample_response + "</sample_assistant_response>"
        
        # if is_agent_builder:
        #     system_content = get_agent_builder_prompt()
        # elif agent_config and agent_config.get('system_prompt'):
        #     system_content = render_prompt_template(agent_config['system_prompt'].strip())
        # else:
        #    system_content = default_system_content
        system_content = default_system_content
        # if agent_config and (agent_config.get('configured_mcps') or agent_config.get('custom_mcps')) and mcp_wrapper_instance and mcp_wrapper_instance._initialized:
        #     mcp_info = "\n\n--- MCP Tools Available ---\n"
        #     mcp_info += "You have access to external MCP (Model Context Protocol) server tools.\n"
        #     mcp_info += "MCP tools can be called directly using their native function names in the standard function calling format:\n"
        #     mcp_info += '<function_calls>\n'
        #     mcp_info += '<invoke name="{tool_name}">\n'
        #     mcp_info += '<parameter name="param1">value1</parameter>\n'
        #     mcp_info += '<parameter name="param2">value2</parameter>\n'
        #     mcp_info += '</invoke>\n'
        #     mcp_info += '</function_calls>\n\n'
            
        #     mcp_info += "Available MCP tools:\n"
        #     try:
        #         registered_schemas = mcp_wrapper_instance.get_schemas()
        #         for method_name, schema_list in registered_schemas.items():
        #             for schema in schema_list:
        #                 if schema.schema_type == SchemaType.OPENAPI:
        #                     func_info = schema.schema.get('function', {})
        #                     description = func_info.get('description', 'No description available')
        #                     mcp_info += f"- **{method_name}**: {description}\n"
                            
        #                     params = func_info.get('parameters', {})
        #                     props = params.get('properties', {})
        #                     if props:
        #                         mcp_info += f"  Parameters: {', '.join(props.keys())}\n"
                                
        #     except Exception as e:
        #         logger.error(f"Error listing MCP tools: {e}")
        #         mcp_info += "- Error loading MCP tool list\n"
            
        #     mcp_info += "\n🚨 CRITICAL MCP TOOL RESULT INSTRUCTIONS 🚨\n"
        #     mcp_info += "When you use ANY MCP (Model Context Protocol) tools:\n"
        #     mcp_info += "1. ALWAYS read and use the EXACT results returned by the MCP tool\n"
        #     mcp_info += "2. For search tools: ONLY cite URLs, sources, and information from the actual search results\n"
        #     mcp_info += "3. For any tool: Base your response entirely on the tool's output - do NOT add external information\n"
        #     mcp_info += "4. DO NOT fabricate, invent, hallucinate, or make up any sources, URLs, or data\n"
        #     mcp_info += "5. If you need more information, call the MCP tool again with different parameters\n"
        #     mcp_info += "6. When writing reports/summaries: Reference ONLY the data from MCP tool results\n"
        #     mcp_info += "7. If the MCP tool doesn't return enough information, explicitly state this limitation\n"
        #     mcp_info += "8. Always double-check that every fact, URL, and reference comes from the MCP tool output\n"
        #     mcp_info += "\nIMPORTANT: MCP tool results are your PRIMARY and ONLY source of truth for external data!\n"
        #     mcp_info += "NEVER supplement MCP results with your training data or make assumptions beyond what the tools provide.\n"
            
        #     system_content += mcp_info

        now = datetime.datetime.now(datetime.timezone.utc)
        datetime_info = f"\n\n=== CURRENT DATE/TIME INFORMATION ===\n"
        datetime_info += f"Today's date: {now.strftime('%A, %B %d, %Y')}\n"
        datetime_info += f"Current UTC time: {now.strftime('%H:%M:%S UTC')}\n"
        datetime_info += f"Current year: {now.strftime('%Y')}\n"
        datetime_info += f"Current month: {now.strftime('%B')}\n"
        datetime_info += f"Current day: {now.strftime('%A')}\n"
        datetime_info += "Use this information for any time-sensitive tasks, research, or when current date/time context is needed.\n"
        
        system_content += datetime_info

        return {"role": "system", "content": system_content}


class MessageManager:
    def __init__(self, client, thread_id: str, model_name: str, trace: Optional[StatefulTraceClient]):
        self.client = client
        self.thread_id = thread_id
        self.model_name = model_name
        self.trace = trace
    
    async def build_temporary_message(self) -> Optional[dict]:
        temp_message_content_list = []

        latest_browser_state_msg = await self.client.table('messages').select('*').eq('thread_id', self.thread_id).eq('type', 'browser_state').order('created_at', desc=True).limit(1).execute()
        if latest_browser_state_msg.data and len(latest_browser_state_msg.data) > 0:
            try:
                browser_content = latest_browser_state_msg.data[0]["content"]
                if isinstance(browser_content, str):
                    browser_content = json.loads(browser_content)
                screenshot_base64 = browser_content.get("screenshot_base64")
                screenshot_url = browser_content.get("image_url")
                
                browser_state_text = browser_content.copy()
                browser_state_text.pop('screenshot_base64', None)
                browser_state_text.pop('image_url', None)

                if browser_state_text:
                    temp_message_content_list.append({
                        "type": "text",
                        "text": f"The following is the current state of the browser:\n{json.dumps(browser_state_text, indent=2)}"
                    })
                
                if 'gemini' in self.model_name.lower() or 'anthropic' in self.model_name.lower() or 'openai' in self.model_name.lower():
                    if screenshot_url:
                        temp_message_content_list.append({
                            "type": "image_url",
                            "image_url": {
                                "url": screenshot_url,
                                "format": "image/jpeg"
                            }
                        })
                    elif screenshot_base64:
                        temp_message_content_list.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{screenshot_base64}",
                            }
                        })

            except Exception as e:
                logger.error(f"Error parsing browser state: {e}")

        latest_image_context_msg = await self.client.table('messages').select('*').eq('thread_id', self.thread_id).eq('type', 'image_context').order('created_at', desc=True).limit(1).execute()
        if latest_image_context_msg.data and len(latest_image_context_msg.data) > 0:
            try:
                image_context_content = latest_image_context_msg.data[0]["content"] if isinstance(latest_image_context_msg.data[0]["content"], dict) else json.loads(latest_image_context_msg.data[0]["content"])
                base64_image = image_context_content.get("base64")
                mime_type = image_context_content.get("mime_type")
                file_path = image_context_content.get("file_path", "unknown file")

                if base64_image and mime_type:
                    temp_message_content_list.append({
                        "type": "text",
                        "text": f"Here is the image you requested to see: '{file_path}'"
                    })
                    temp_message_content_list.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}",
                        }
                    })

                await self.client.table('messages').delete().eq('message_id', latest_image_context_msg.data[0]["message_id"]).execute()
            except Exception as e:
                logger.error(f"Error parsing image context: {e}")

        if temp_message_content_list:
            return {"role": "user", "content": temp_message_content_list}
        return None


class AgentRunner:
    def __init__(self, config: AgentConfig):
        self.config = config
    
    async def setup(self):
        print(f"🔵 ===== AgentRunner.setup()开始执行 =====")
        try:
            print(f"  🔄 检查trace配置...")
            if not self.config.trace:
                print(f"    📡 创建Langfuse trace...")
                self.config.trace = langfuse.trace(name="run_agent", session_id=self.config.thread_id, metadata={"project_id": self.config.project_id})
                print(f"    ✅ Langfuse trace创建成功")
            else:
                print(f"    ✅ 使用现有trace")
            
            print(f"  🔄 创建ThreadManager...")
            self.thread_manager = ThreadManager(
                trace=self.config.trace, 
                is_agent_builder=self.config.is_agent_builder or False, 
                target_agent_id=self.config.target_agent_id, 
                agent_config=self.config.agent_config
            )
            print(f"  ✅ ThreadManager创建成功")
            
            print(f"  🔄 获取数据库客户端...")
            self.client = await self.thread_manager.db.client
            print(f"  ✅ 数据库客户端获取成功: {self.client}")
            
            print(f"  ✅ setup()完成")
        except Exception as setup_error:
            print(f"  ❌ setup()失败: {setup_error}")
            print(f"  📋 错误详情: {traceback.format_exc()}")
            raise setup_error
    
    async def setup_tools(self):
        tool_manager = ToolManager(self.thread_manager, self.config.project_id, self.config.thread_id)
        
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
    
    # async def setup_mcp_tools(self) -> Optional[MCPToolWrapper]:
    #     if not self.config.agent_config:
    #         return None
        
    #     mcp_manager = MCPManager(self.thread_manager, self.account_id)
    #     return await mcp_manager.register_mcp_tools(self.config.agent_config)
    
    def get_max_tokens(self) -> Optional[int]:
        if "sonnet" in self.config.model_name.lower():
            return 8192
        elif "gpt-4" in self.config.model_name.lower():
            return 4096
        elif "gemini-2.5-pro" in self.config.model_name.lower():
            return 64000
        elif "kimi-k2" in self.config.model_name.lower():
            return 8192
        return None
    
    async def run(self) -> AsyncGenerator[Dict[str, Any], None]:
        print(f"🔵 ===== AgentRunner.run()开始执行 =====")
        try:
            print(f"  🔄 调用setup()...")
            await self.setup()
            print(f"  ✅ setup()完成")
        except Exception as setup_error:
            print(f"  ❌ setup()失败: {setup_error}")
            print(f"  📋 错误详情: {traceback.format_exc()}")
            raise setup_error
        
        # await self.setup_tools()
        # mcp_wrapper_instance = await self.setup_mcp_tools()
        
        try:
            print(f"  🔄 调用PromptManager.build_system_prompt()...")
            system_message = await PromptManager.build_system_prompt(
                self.config.model_name, self.config.agent_config, 
                self.config.is_agent_builder, self.config.thread_id, 
                # mcp_wrapper_instance
            )
            print(f"  ✅ build_system_prompt()完成")
        except Exception as prompt_error:
            print(f"  ❌ build_system_prompt()失败: {prompt_error}")
            print(f"  📋 错误详情: {traceback.format_exc()}")
            raise prompt_error

        iteration_count = 0
        continue_execution = True

        # 源码
        # latest_user_message = await self.client.table('messages').select('*').eq('thread_id', self.config.thread_id).eq('type', 'user').order('created_at', desc=True).limit(1).execute()
        # print(f"latest_user_message: {latest_user_message}")
        # if latest_user_message.data and len(latest_user_message.data) > 0:
        #     data = latest_user_message.data[0]['content']
        #     if isinstance(data, str):
        #         data = json.loads(data)
        #     if self.config.trace:
        #         self.config.trace.update(input=data['content'])

        print(f"  🔄 从events表获取最新用户输入...")
        try:
            # 从events表获取最新的用户输入
            latest_event = await self.client.table('events').select('*').eq('session_id', self.config.thread_id).eq('author', 'user').order('timestamp', desc=True).limit(1).execute()
            print(f"  ✅ events查询结果: {latest_event}")
            
            if latest_event.data and len(latest_event.data) > 0:
                event_data = latest_event.data[0]
                content = event_data.get('content', {})
                print(f"  📝 找到用户事件: {event_data.get('id')}")
                
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except json.JSONDecodeError:
                        print(f"  ⚠️ 事件内容不是有效的JSON: {content}")
                        content = {"content": content}
                
                # 提取用户输入内容
                user_input = None
                if isinstance(content, dict):
                    user_input = content.get('content', '')
                    print(f"  💬 用户输入: {user_input}")
                
                # 更新trace
                if self.config.trace and user_input:
                    try:
                        self.config.trace.update(input=user_input)
                        print(f"  ✅ Trace更新成功")
                    except Exception as trace_error:
                        print(f"  ⚠️ Trace更新失败: {trace_error}")
            else:
                print(f"  ℹ️ 没有找到用户事件")
                
        except Exception as event_error:
            print(f"  ❌ 获取用户事件失败: {event_error}")
            print(f"  📋 错误详情: {traceback.format_exc()}")
            # 继续执行，不中断流程

        message_manager = MessageManager(self.client, self.config.thread_id, self.config.model_name, self.config.trace)

        while continue_execution and iteration_count < self.config.max_iterations:
            iteration_count += 1

            # can_run, message, subscription = await check_billing_status(self.client, self.account_id)
            # if not can_run:
            #     error_msg = f"Billing limit reached: {message}"
            #     yield {
            #         "type": "status",
            #         "status": "stopped",
            #         "message": error_msg
            #     }
            #     break

            # 源码
            # latest_message = await self.client.table('messages').select('*').eq('thread_id', self.config.thread_id).in_('type', ['assistant', 'tool', 'user']).order('created_at', desc=True).limit(1).execute()
            # if latest_message.data and len(latest_message.data) > 0:
            #     message_type = latest_message.data[0].get('type')
            #     if message_type == 'assistant':
            #         continue_execution = False
            #         break

            # 检查最新的消息类型（assistant, tool, user）
            latest_event = await self.client.table('events').select('*').eq('session_id', self.config.thread_id).in_('author', ['assistant', 'tool', 'user']).order('timestamp', desc=True).limit(1).execute()
            if latest_event.data and len(latest_event.data) > 0:
                author_type = latest_event.data[0].get('author')
                print(f"  📝 最新消息类型: {author_type}")
                if author_type == 'assistant':
                    print(f"  ℹ️ 检测到最新消息是assistant，停止执行")
                    continue_execution = False
                    break

            # 构建临时消息 - 修复：传递处理后的消息对象而不是QueryResult
            temporary_message = None
            if latest_event.data and len(latest_event.data) > 0:
                event_data = latest_event.data[0]
                # 确保event_data是字典格式
                if hasattr(event_data, '__dict__'):
                    event_data = dict(event_data)
                
                content = event_data.get('content', {})
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except json.JSONDecodeError:
                        content = {"content": content}
                
                # 构建临时消息对象
                if isinstance(content, dict) and 'content' in content:
                    temporary_message = {
                        "role": "user",
                        "content": content['content']
                    }
                    print(f"  📝 构建临时消息: {temporary_message}")
                else:
                    print(f"  ⚠️ 无法从事件数据构建临时消息")
            else:
                print(f"  ℹ️ 没有找到最新事件，不传递临时消息")
            
            generation = self.config.trace.generation(name="thread_manager.run_thread") if self.config.trace else None
            try:
                response = await self.thread_manager.run_thread(
                    thread_id=self.config.thread_id,
                    system_prompt=system_message,
                    stream=self.config.stream,
                    llm_model=self.config.model_name,
                    llm_temperature=0,
                    llm_max_tokens=1024,
                    tool_choice="auto",
                    max_xml_tool_calls=1,
                    temporary_message=temporary_message,
                    processor_config=ProcessorConfig(
                        xml_tool_calling=True,
                        native_tool_calling=False,
                        execute_tools=True,
                        execute_on_stream=True,
                        tool_execution_strategy="parallel",
                        xml_adding_strategy="user_message"
                    ),
                    native_max_auto_continues=self.config.native_max_auto_continues,
                    include_xml_examples=True,
                    enable_thinking=self.config.enable_thinking,
                    reasoning_effort=self.config.reasoning_effort,
                    enable_context_manager=self.config.enable_context_manager,
                    generation=generation
                )

                if isinstance(response, dict) and "status" in response and response["status"] == "error":
                    yield response
                    break

                last_tool_call = None
                agent_should_terminate = False
                error_detected = False
                full_response = ""
                print(f"  📝 full_response初始化: 类型={type(full_response)}, 内容='{full_response}'")

                try:
                    if hasattr(response, '__aiter__') and not isinstance(response, dict):
                        async for chunk in response:
                            if isinstance(chunk, dict) and chunk.get('type') == 'status' and chunk.get('status') == 'error':
                                error_detected = True
                                yield chunk
                                continue
                            
                            if chunk.get('type') == 'status':
                                try:
                                    metadata = chunk.get('metadata', {})
                                    if isinstance(metadata, str):
                                        metadata = json.loads(metadata)
                                    
                                    if metadata.get('agent_should_terminate'):
                                        agent_should_terminate = True
                                        
                                        content = chunk.get('content', {})
                                        if isinstance(content, str):
                                            content = json.loads(content)
                                        
                                        if content.get('function_name'):
                                            last_tool_call = content['function_name']
                                        elif content.get('xml_tag_name'):
                                            last_tool_call = content['xml_tag_name']
                                            
                                except Exception:
                                    pass
                            
                            if chunk.get('type') == 'assistant' and 'content' in chunk:
                                try:
                                    print(f"  🔍 处理assistant chunk:")
                                    print(f"    📋 chunk类型: {type(chunk)}")
                                    print(f"    📝 chunk内容: {chunk}")
                                    
                                    content = chunk.get('content', '{}')
                                    print(f"    📄 content类型: {type(content)}")
                                    print(f"    📄 content内容: {content}")
                                    
                                    if isinstance(content, str):
                                        assistant_content_json = json.loads(content)
                                    else:
                                        assistant_content_json = content
                                    
                                    print(f"    📋 assistant_content_json类型: {type(assistant_content_json)}")
                                    print(f"    📋 assistant_content_json内容: {assistant_content_json}")

                                    assistant_text = assistant_content_json.get('content', '')
                                    print(f"    📝 assistant_text原始类型: {type(assistant_text)}")
                                    print(f"    📝 assistant_text原始内容: {assistant_text}")
                                    
                                    # 确保assistant_text是字符串
                                    if isinstance(assistant_text, list):
                                        print(f"    ⚠️ assistant_text是列表，开始处理...")
                                        # 如果是列表，尝试提取文本内容
                                        text_parts = []
                                        for i, item in enumerate(assistant_text):
                                            print(f"      [{i}] item类型: {type(item)}, 内容: {item}")
                                            if isinstance(item, dict) and 'text' in item:
                                                text_parts.append(item['text'])
                                            elif isinstance(item, str):
                                                text_parts.append(item)
                                        assistant_text = ' '.join(text_parts)
                                        print(f"    ✅ 列表处理后: {assistant_text}")
                                    elif not isinstance(assistant_text, str):
                                        print(f"    ⚠️ assistant_text不是字符串，转换为字符串")
                                        assistant_text = str(assistant_text)
                                        print(f"    ✅ 转换后: {assistant_text}")
                                    
                                    print(f"    📝 最终assistant_text类型: {type(assistant_text)}")
                                    print(f"    📝 最终assistant_text内容: {assistant_text}")
                                    print(f"    📝 full_response当前类型: {type(full_response)}")
                                    print(f"    📝 full_response当前内容: {full_response}")
                                    
                                    full_response += assistant_text
                                    print(f"    ✅ 拼接完成，full_response长度: {len(full_response)}")
                                    if isinstance(assistant_text, str):
                                        if '</ask>' in assistant_text or '</complete>' in assistant_text or '</web-browser-takeover>' in assistant_text:
                                           if '</ask>' in assistant_text:
                                               xml_tool = 'ask'
                                           elif '</complete>' in assistant_text:
                                               xml_tool = 'complete'
                                           elif '</web-browser-takeover>' in assistant_text:
                                               xml_tool = 'web-browser-takeover'

                                           last_tool_call = xml_tool
                                
                                except json.JSONDecodeError:
                                    pass
                                except Exception:
                                    pass

                            yield chunk
                    else:
                        error_detected = True

                    if error_detected:
                        if generation:
                            generation.end(output=full_response, status_message="error_detected", level="ERROR")
                        break
                        
                    if agent_should_terminate or last_tool_call in ['ask', 'complete', 'web-browser-takeover']:
                        if generation:
                            generation.end(output=full_response, status_message="agent_stopped")
                        continue_execution = False

                except Exception as e:
                    error_msg = f"Error during response streaming: {str(e)}"
                    if generation:
                        generation.end(output=full_response, status_message=error_msg, level="ERROR")
                    yield {
                        "type": "status",
                        "status": "error",
                        "message": error_msg
                    }
                    break
                    
            except Exception as e:
                error_msg = f"Error running thread: {str(e)}"
                yield {
                    "type": "status",
                    "status": "error",
                    "message": error_msg
                }
                break
            
            if generation:
                generation.end(output=full_response)

        asyncio.create_task(asyncio.to_thread(lambda: langfuse.flush()))


async def run_agent(
    thread_id: str,
    project_id: str,
    stream: bool,
    thread_manager: Optional[ThreadManager] = None,
    native_max_auto_continues: int = 25,
    max_iterations: int = 100,
    model_name: str = "deepseek/deepseek-chat",
    enable_thinking: Optional[bool] = False,
    reasoning_effort: Optional[str] = 'low',
    enable_context_manager: bool = True,
    agent_config: Optional[dict] = None,    
    trace: Optional[StatefulTraceClient] = None,
    is_agent_builder: Optional[bool] = False,
    target_agent_id: Optional[str] = None
):
    print(f"🔵 ===== run_agent函数开始执行 =====")
    print(f"📋 输入参数:")
    print(f"  - thread_id: {thread_id}")
    print(f"  - project_id: {project_id}")
    print(f"  - stream: {stream}")
    print(f"  - model_name: {model_name}")
    if agent_config:
        print(f"  - agent_config: {agent_config.get('name', 'Unknown')}")
    else:
        print(f"  - agent_config: None")
    print(f"  - trace: {trace}")
    print(f"✅ 参数打印完成")
    print(f"🔄 ===== 模型选择逻辑 =====")
    effective_model = model_name
    if model_name == "deepseek/deepseek-chat" and agent_config and agent_config.get('model'):
        effective_model = agent_config['model']
        print(f"  🔄 使用Agent配置中的模型: {effective_model}")
    elif model_name != "deepseek/deepseek-chat":
        print(f"  🔄 使用用户选择的模型: {effective_model}")
    else:
        print(f"  🔄 使用默认模型: {effective_model}")
    print(f"  ✅ 最终模型: {effective_model}")
    
    print(f"🔄 ===== 创建AgentConfig =====")
    config = AgentConfig(
        thread_id=thread_id,
        project_id=project_id,
        stream=stream,
        native_max_auto_continues=native_max_auto_continues,
        max_iterations=max_iterations,
        model_name=effective_model,
        enable_thinking=enable_thinking,
        reasoning_effort=reasoning_effort,
        enable_context_manager=enable_context_manager,
        agent_config=agent_config,
        # trace=trace,
        is_agent_builder=is_agent_builder,
        target_agent_id=target_agent_id
    )
    print(f"  ✅ AgentConfig创建成功")
    
    print(f"🔄 ===== 创建AgentRunner =====")
    runner = AgentRunner(config)
    print(f"  ✅ AgentRunner创建成功: {runner}")
    
    print(f"🔄 ===== 开始执行runner.run() =====")
    try:
        print(f"  🔄 开始执行runner.run() ！！！！！！！！！！！！！！")
        async for chunk in runner.run():
            print(f"  📝 生成chunk: {chunk.get('type', 'unknown')}")
            yield chunk
    except Exception as run_error:
        print(f"  ❌ runner.run()执行失败: {run_error}")
        print(f"  📋 错误详情: {traceback.format_exc()}")
        raise run_error