"""
Response processing module for AgentPress.

This module handles the processing of LLM responses, including:
- Streaming and non-streaming response handling
- XML and native tool call detection and parsing
- Tool execution orchestration
- Message formatting and persistence
"""

import json
import re
import uuid
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple, Union, Callable, Literal
from dataclasses import dataclass
from utils.logger import logger
from utils.json_helpers import to_json_string
from agentpress.tool import ToolResult
from agentpress.tool_registry import ToolRegistry
from agentpress.xml_tool_parser import XMLToolParser
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
from services.langfuse import langfuse
from utils.json_helpers import (
    ensure_dict, ensure_list, safe_json_parse, 
    to_json_string, format_for_yield
)
from litellm.utils import token_counter

# Type alias for XML result adding strategy
XmlAddingStrategy = Literal["user_message", "assistant_message", "inline_edit"]

# Type alias for tool execution strategy
ToolExecutionStrategy = Literal["sequential", "parallel"]

@dataclass
class ToolExecutionContext:
    """Context for a tool execution including call details, result, and display info."""
    tool_call: Dict[str, Any]
    tool_index: int
    result: Optional[ToolResult] = None
    function_name: Optional[str] = None
    xml_tag_name: Optional[str] = None
    error: Optional[Exception] = None
    assistant_message_id: Optional[str] = None
    parsing_details: Optional[Dict[str, Any]] = None

@dataclass
class ProcessorConfig:
    """
    Configuration for response processing and tool execution.
    
    This class controls how the LLM's responses are processed, including how tool calls
    are detected, executed, and their results handled.
    
    Attributes:
        xml_tool_calling: Enable XML-based tool call detection (<tool>...</tool>)
        native_tool_calling: Enable OpenAI-style function calling format
        execute_tools: Whether to automatically execute detected tool calls
        execute_on_stream: For streaming, execute tools as they appear vs. at the end
        tool_execution_strategy: How to execute multiple tools ("sequential" or "parallel")
        xml_adding_strategy: How to add XML tool results to the conversation
        max_xml_tool_calls: Maximum number of XML tool calls to process (0 = no limit)
    """

    xml_tool_calling: bool = True  
    native_tool_calling: bool = False

    execute_tools: bool = True
    execute_on_stream: bool = False
    tool_execution_strategy: ToolExecutionStrategy = "sequential"
    xml_adding_strategy: XmlAddingStrategy = "assistant_message"
    max_xml_tool_calls: int = 0  # 0 means no limit
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.xml_tool_calling is False and self.native_tool_calling is False and self.execute_tools:
            raise ValueError("At least one tool calling format (XML or native) must be enabled if execute_tools is True")
            
        if self.xml_adding_strategy not in ["user_message", "assistant_message", "inline_edit"]:
            raise ValueError("xml_adding_strategy must be 'user_message', 'assistant_message', or 'inline_edit'")
        
        if self.max_xml_tool_calls < 0:
            raise ValueError("max_xml_tool_calls must be a non-negative integer (0 = no limit)")

class ResponseProcessor:
    """Processes LLM responses, extracting and executing tool calls."""
    
    def __init__(self, tool_registry: ToolRegistry, add_message_callback: Callable, trace: Optional[StatefulTraceClient] = None, is_agent_builder: bool = False, target_agent_id: Optional[str] = None, agent_config: Optional[dict] = None): # type: ignore
        """Initialize the ResponseProcessor.
        
        Args:
            tool_registry: Registry of available tools
            add_message_callback: Callback function to add messages to the thread.
                MUST return the full saved message object (dict) or None.
            agent_config: Optional agent configuration with version information
        """
        self.tool_registry = tool_registry
        self.add_message = add_message_callback
        self.trace = trace or langfuse.trace(name="anonymous:response_processor")
        # Initialize the XML parser
        self.xml_parser = XMLToolParser()
        self.is_agent_builder = is_agent_builder
        self.target_agent_id = target_agent_id
        self.agent_config = agent_config

    async def _yield_message(self, message_obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Helper to yield a message with proper formatting.
        
        Ensures that content and metadata are JSON strings for client compatibility.
        """
        if message_obj:
            return format_for_yield(message_obj)
        return None

    async def _add_message_with_agent_info(
        self,
        thread_id: str,
        type: str,
        content: Union[Dict[str, Any], List[Any], str],
        is_llm_message: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Helper to add a message with agent version information if available."""
        agent_id = None
        agent_version_id = None
        
        if self.agent_config:
            agent_id = self.agent_config.get('agent_id')
            agent_version_id = self.agent_config.get('current_version_id')
            
        return await self.add_message(
            thread_id=thread_id,
            type=type,
            content=content,
            is_llm_message=is_llm_message,
            metadata=metadata,
            agent_id=agent_id,
            agent_version_id=agent_version_id
        )

    async def process_adk_streaming_response(
        self,
        adk_response: AsyncGenerator,
        thread_id: str,
        prompt_messages: List[Dict[str, Any]],
        llm_model: str,
        config: ProcessorConfig = ProcessorConfig(),
        can_auto_continue: bool = False,
        auto_continue_count: int = 0,
        continuous_state: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理 Google ADK 流式响应，包括工具调用和执行
        """

        def _now_ts():
            return datetime.now(timezone.utc).timestamp()

        def _safe_text(x) -> str:
            # 规避“can only concatenate str (not 'list') to str”
            if isinstance(x, str):
                return x
            if isinstance(x, (list, tuple)):
                return "".join(str(t) for t in x)
            return str(x)

        def _event_is_final(e) -> bool:
            try:
                # ADK 提供的最终响应判定
                return bool(getattr(e, "is_final_response", None) and e.is_final_response())
            except Exception:
                # 回退逻辑：partial==False 且有 usage_metadata 时大概率为最终
                return bool(getattr(e, "partial", None) is False and getattr(e, "usage_metadata", None) is not None)

        # 运行状态初始化 
        continuous_state = continuous_state or {}   # 保存跨轮次的状态信息
        accumulated_content = continuous_state.get('accumulated_content', "") # 累积的内容，在下一轮中作为上下文
        # 🔧 确保 accumulated_content 始终是字符串
        if not isinstance(accumulated_content, str):
            accumulated_content = str(accumulated_content)
        tool_calls_buffer = {} # 工具调用缓冲区
        current_xml_content = accumulated_content   # 累积内容如果自动继续，否则为空
        xml_chunks_buffer = [] # 累积 XML 内容
        pending_tool_executions = [] # 待执行工具
        yielded_tool_indices = set() # 存储已生成状态的工具索引
        tool_index = 0 # 工具索引
        xml_tool_call_count = 0 # XML 工具调用计数
        finish_reason = None # 完成原因
        should_auto_continue = False # 是否自动继续
        last_assistant_message_object = None # 存储最终保存的 assistant 消息对象
        tool_result_message_objects = {} # tool_index -> 完整保存的消息对象
        has_printed_thinking_prefix = False # 标记是否打印思考前缀
        agent_should_terminate = False # 标记是否执行终止工具
        complete_native_tool_calls = [] # 初始化早期用于 assistant_response_end
        
        # 🔧 工具调用ID到assistant_message_id的映射（跨事件持久化）
        tool_call_to_assistant_map = {}
        # 🔧 工具调用ID到参数的映射，用于工具响应时获取原始参数
        tool_call_to_params_map = {}
        # 🔧 初始化工具调用ID到索引的映射
        self.tool_call_to_index_map = {}
        
        # 不作为流控制，仅用于最后记录
        finish_reason = None           
        saw_error = False
        saw_length_limit = False

        # 收集元数据以重建 LiteLLM 响应对象
        streaming_metadata = {
            "model": llm_model,
            "created": None,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "response_ms": None,
            "first_chunk_time": None,
            "last_chunk_time": None
        }

        # 重用 / 创建 thread_run_id：保持相同的运行ID，在ADK 中是 invocation_id
        thread_run_id = continuous_state.get('thread_run_id') or str(uuid.uuid4())
        continuous_state['thread_run_id'] = thread_run_id
        
        logger.info(f"Processing ADK streaming response with thread_run_id: {thread_run_id}")


        try:
            # 当前已执行的自动继续次数
            # 处理两种情况，1. finsh_reason=tool_calls 2. finsh_reason=length
            # 在ADK 中，则是：get_function_calls() / get_function_responses() event.is_final_response()
            """
            用户: "帮我搜索最新的科技新闻并分析趋势"
            LLM: "我来帮你搜索最新科技新闻..." [finish_reason: tool_calls]
            系统: 自动继续，执行工具调用
            LLM: "根据搜索结果，当前主要趋势包括..." [finish_reason: stop]
            """
            if auto_continue_count == 0:  
                start_content = {"status_type": "thread_run_start", "thread_run_id": thread_run_id}
                # TODO: 适配 ADK 的 start 事件
                start_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=start_content,
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                logger.info(f"start_msg_obj: {start_msg_obj}")
                if start_msg_obj:
                    yield format_for_yield(start_msg_obj)

                assist_start_content = {"status_type": "assistant_response_start"}
                assist_start_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=assist_start_content,
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if assist_start_msg_obj:
                    yield format_for_yield(assist_start_msg_obj)

            # 序列号计数器，用于为每个yield的消息块分配唯一的、连续的序号
            """
            支持auto-continue的连续性
            场景1：正常流式响应
            sequence: 0  -> "你好"
            sequence: 1  -> "，我是"
            sequence: 2  -> "AI助手"
            sequence: 3  -> "。"

            场景2：Auto-continue场景
            第一轮：
            sequence: 0  -> "你好，我是AI助手"
            sequence: 1  -> "，我可以"
            [finish_reason: length, auto-continue]

            第二轮（从sequence: 2开始）：
            sequence: 2  -> "帮你"
            sequence: 3  -> "回答问题"
            sequence: 4  -> "。"
            
            """
            __sequence = continuous_state.get('sequence', 0)
            # 这里开始流式处理异步的Runner
            async for event in adk_response:
                logger.info(f"Current Event：{event}")
                # 获取当前执行的时间戳
                now_ts = _now_ts()

                # 如果first_chunk_time为空，则设置为当前时间
                if streaming_metadata["first_chunk_time"] is None:
                    streaming_metadata["first_chunk_time"] = now_ts
                # 更新最后的时间戳
                streaming_metadata["last_chunk_time"] = now_ts

                # 如果ADK事件包含usage_metadata，则更新流式元数据
                if getattr(event, "usage_metadata", None):
                    um = event.usage_metadata
                    try:
                        # 属性名基于 Google ADK usage_metadata 字段
                        streaming_metadata["usage"]["prompt_tokens"] = getattr(um, "prompt_token_count", None)
                        streaming_metadata["usage"]["completion_tokens"] = getattr(um, "candidates_token_count", None)
                        streaming_metadata["usage"]["total_tokens"] = getattr(um, "total_token_count", None)
                    except Exception as _:
                        # 容错：即使 usage 字段结构变动，也不应中断
                        pass
                
                # 从ADK事件中提取created时间
                if getattr(event, "timestamp", None):
                    streaming_metadata["created"] = event.timestamp
                
                # 添加模型信息
                streaming_metadata["model"] = llm_model

                logger.info(f"streaming_metadata: {streaming_metadata}")
                # 错误 & 截断探测
                error_code = getattr(event, "error_code", None)
                error_msg = getattr(event, "error_message", None)
                if error_code:
                    saw_error = True
                    # 约定：如果错误码等价于 token 截断
                    if str(error_code).upper() in {"MAX_TOKENS", "TOKEN_LIMIT", "LENGTH"}:
                        saw_length_limit = True

                # 事件层面的状态位
                partial = getattr(event, "partial", None)
                turn_complete = getattr(event, "turn_complete", None)
                is_final = _event_is_final(event)
                
                # ADK 的动作（移交、升级、状态/工件 delta、鉴权请求等）
                actions = getattr(event, "actions", None)
                long_run_tools = list(getattr(event, "long_running_tool_ids", []) or [])
                
                # 🔧 提前获取 content，供状态判断使用
                content = getattr(event, "content", None)

                # 为每个 chunk 计算“所处状态”
                def _derive_chunk_status() -> str:
                    if error_code:
                        return "error"
                    if long_run_tools:
                        return "tool_running"
                    # 移交/升级具备优先级标记
                    if actions and (getattr(actions, "transfer_to_agent", None) or getattr(actions, "escalate", None)):
                        return "handover"
                    
                    # 🔧 ADK专用：检测工具调用和工具响应
                    if content and hasattr(content, 'parts'):
                        for p in getattr(content, 'parts', []):
                            # 检测工具调用
                            if hasattr(p, 'function_call') and getattr(p, 'function_call', None):
                                return "tool_call"
                            # 检测工具响应
                            if hasattr(p, 'function_response') and getattr(p, 'function_response', None):
                                return "tool_response"
                    
                    if is_final:
                        return "final"
                    if partial is True:
                        return "delta"
                    if partial is False:
                        # 非流式单发 or 未标注 usage 的尾包
                        return "possibly_final"
                    return "unknown"

                # 计算当前状态并记录
                chunk_status = _derive_chunk_status()
                logger.info(f"current chunk status: {chunk_status}")
                
                # 🔧 只有特定状态才设置为 finish_reason（工具调用和响应不是结束状态）
                if chunk_status in ["error", "final", "possibly_final"]:
                    finish_reason = chunk_status

                # 过滤ADK的最终完整chunk，避免重复
                if (partial is False and 
                    content and 
                    getattr(content, "parts", None) and
                    chunk_status == "final"):
                    # 这是ADK的最终完整消息，跳过处理，避免重复
                    logger.info(f"Skipping final complete ADK chunk to avoid duplication")
                    continue

                # 在 ADK 事件中提取文本块： Content.parts[*].text
                chunk_text = ""  # 初始化 chunk_text
                
                if content:
                    logger.info(f"event.content: {content}")
                    parts = getattr(content, "parts", None)

                    # TODO ： 如果是思考模型，需要处理思考模型的 reasoning_content
                    # Check for and log Anthropic thinking content
                    # if delta and hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    #     if not has_printed_thinking_prefix:
                    #         # print("[THINKING]: ", end='', flush=True)
                    #         has_printed_thinking_prefix = True
                    #     # print(delta.reasoning_content, end='', flush=True)
                    #     # Append reasoning to main content to be saved in the final message
                    #     reasoning_content = delta.reasoning_content
                    #     if isinstance(reasoning_content, list):
                    #         reasoning_content = ' '.join(str(item) for item in reasoning_content)
                    #     elif not isinstance(reasoning_content, str):
                    #         reasoning_content = str(reasoning_content)
                    #     accumulated_content += reasoning_content

                    if parts:
                        # 处理文本和工具调用
                        texts: List[str] = []
                        tool_calls: List[dict] = []
                        tool_responses: List[dict] = []
                        
                        for p in parts:
                            # 处理文本内容
                            t = getattr(p, "text", None)
                            if t is not None:
                                if not isinstance(t, str):
                                    t = str(t)
                                texts.append(t)
                            
                            # 处理工具调用
                            function_call = getattr(p, "function_call", None)
                            if function_call is not None:
                                tool_call = {
                                    "id": getattr(function_call, "id", None),
                                    "name": getattr(function_call, "name", None),
                                    "args": getattr(function_call, "args", {})
                                }
                                tool_calls.append(tool_call)
                                logger.info(f"🔧 检测到工具调用: {tool_call['name']}({tool_call['args']})")
                            
                            # 处理工具响应
                            function_response = getattr(p, "function_response", None)
                            if function_response is not None:
                                tool_response = {
                                    "id": getattr(function_response, "id", None),
                                    "name": getattr(function_response, "name", None),
                                    "response": getattr(function_response, "response", {})
                                }
                                tool_responses.append(tool_response)
                                logger.info(f"✅ 检测到工具响应: {tool_response['name']} -> {tool_response['response']}")
                        
                        # 处理文本内容
                        if texts:
                            # 🔧 确保所有元素都是字符串，避免拼接错误
                            chunk_text = "".join(str(t) for t in texts)
                        
                        # Yield 工具调用事件 - 前端期望的 Assistant 消息格式
                        for tool_index, tool_call in enumerate(tool_calls):
                            now_iso = datetime.now(timezone.utc).isoformat()
                            assistant_message_id = str(uuid.uuid4())
                            
                            # 🔧 首先发送工具开始状态消息（前端工具调用显示的关键）
                            tool_started_content = {
                                "status_type": "tool_started",
                                "function_name": tool_call["name"],
                                "arguments": to_json_string(tool_call["args"]),
                                "tool_index": tool_index
                            }
                            
                            tool_started_metadata = {
                                "stream_status": "tool_started",
                                "thread_run_id": thread_run_id,
                                "tool_name": tool_call["name"],
                                "tool_index": tool_index
                            }
                            
                            # 🔧 保存工具开始状态消息到数据库
                            saved_tool_started_msg = await self._add_message_with_agent_info(
                                thread_id=thread_id,
                                type="status",
                                content=tool_started_content,
                                is_llm_message=False,
                                metadata=tool_started_metadata
                            )
                            
                            # Yield工具开始状态消息
                            if saved_tool_started_msg:
                                yield format_for_yield(saved_tool_started_msg)
                            else:
                                yield {
                                    "sequence": __sequence,
                                    "message_id": f"tool_started_{uuid.uuid4().hex[:8]}",
                                    "thread_id": thread_id,
                                    "type": "status",
                                    "is_llm_message": False,
                                    "content": to_json_string(tool_started_content),
                                    "metadata": to_json_string(tool_started_metadata),
                                    "created_at": now_iso,
                                    "updated_at": now_iso
                                }
                            __sequence += 1
                            
                            # 🔧 构建XML格式的工具调用内容（前端左侧按钮需要）
                            xml_params = []
                            for param_name, param_value in tool_call["args"].items():
                                # 确保参数值被正确转义和格式化
                                if isinstance(param_value, str):
                                    escaped_value = param_value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                                else:
                                    escaped_value = str(param_value)
                                xml_params.append(f"<parameter name=\"{param_name}\">{escaped_value}</parameter>")
                            
                            xml_tool_call = f"""<function_calls>
<invoke name="{tool_call["name"]}">
{chr(10).join(xml_params)}
</invoke>
</function_calls>"""
                            
                            # 🔧 构建工具调用消息内容（同时包含XML和OpenAI格式）
                            tool_call_content = {
                                "role": "assistant",
                                "content": xml_tool_call,  # XML格式给左侧按钮
                                "tool_calls": [{
                                    "id": tool_call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tool_call["name"],
                                        "arguments": to_json_string(tool_call["args"])
                                    }
                                }]  # OpenAI格式给右侧面板
                            }
                            
                            tool_call_metadata = {
                                "stream_status": "tool_call", 
                                "thread_run_id": thread_run_id,
                                "tool_name": tool_call["name"]
                            }
                            
                            # 🔧 保存到数据库
                            saved_tool_call_msg = await self._add_message_with_agent_info(
                                thread_id=thread_id,
                                type="assistant", 
                                content=tool_call_content,
                                is_llm_message=True,
                                metadata=tool_call_metadata
                            )
                            
                            # 🔧 建立工具调用ID到assistant_message_id的映射
                            if saved_tool_call_msg:
                                actual_message_id = saved_tool_call_msg.get('message_id', assistant_message_id)
                                tool_call_to_assistant_map[tool_call["id"]] = str(actual_message_id)
                            else:
                                tool_call_to_assistant_map[tool_call["id"]] = assistant_message_id
                            
                            # 🔧 存储工具调用参数，供工具响应时使用
                            tool_call_to_params_map[tool_call["id"]] = tool_call["args"]
                            # 🔧 存储工具调用ID到索引的映射，供工具完成状态使用
                            tool_call_to_index_map = getattr(self, 'tool_call_to_index_map', {})
                            tool_call_to_index_map[tool_call["id"]] = tool_index
                            self.tool_call_to_index_map = tool_call_to_index_map
                            
                            # Yield消息（如果保存成功则使用保存的消息，否则构造临时消息）
                            if saved_tool_call_msg:
                                yield format_for_yield(saved_tool_call_msg)
                            else:
                                yield {
                                    "sequence": __sequence,
                                    "message_id": assistant_message_id,
                                    "thread_id": thread_id,
                                    "type": "assistant",
                                    "is_llm_message": True,
                                    "content": to_json_string(tool_call_content),
                                    "metadata": to_json_string(tool_call_metadata),
                                    "created_at": now_iso,
                                    "updated_at": now_iso
                                }
                            __sequence += 1
                        
                        # Yield 工具响应事件 - 前端期望的 Tool 消息格式，带关联ID
                        for tool_response in tool_responses:
                            now_iso = datetime.now(timezone.utc).isoformat()
                            assistant_message_id = tool_call_to_assistant_map.get(tool_response["id"])
                            
                            # 🔧 构建工具响应消息内容
                            # 从映射中获取工具调用的原始参数
                            tool_parameters = tool_call_to_params_map.get(tool_response["id"], {})
                            
                            tool_response_content = {
                                "tool_name": tool_response["name"],
                                "parameters": tool_parameters,
                                "result": tool_response["response"]
                            }
                            
                            tool_response_metadata = {
                                "stream_status": "tool_response",
                                "thread_run_id": thread_run_id,
                                "tool_name": tool_response["name"],
                                "tool_call_id": tool_response["id"],
                                "assistant_message_id": assistant_message_id
                            }
                            
                            # 🔧 保存到数据库
                            saved_tool_response_msg = await self._add_message_with_agent_info(
                                thread_id=thread_id,
                                type="tool",
                                content=tool_response_content, 
                                is_llm_message=False,
                                metadata=tool_response_metadata
                            )
                            
                            # Yield消息（如果保存成功则使用保存的消息，否则构造临时消息）
                            if saved_tool_response_msg:
                                yield format_for_yield(saved_tool_response_msg)
                            else:
                                yield {
                                    "sequence": __sequence,
                                    "message_id": str(uuid.uuid4()),
                                    "thread_id": thread_id,
                                    "type": "tool",
                                    "is_llm_message": False,
                                    "content": to_json_string(tool_response_content),
                                    "metadata": to_json_string(tool_response_metadata),
                                    "created_at": now_iso,
                                    "updated_at": now_iso
                                }
                            __sequence += 1
                            
                            # 🔧 发送工具完成状态消息（前端工具调用结束显示的关键）
                            tool_call_to_index_map = getattr(self, 'tool_call_to_index_map', {})
                            tool_index = tool_call_to_index_map.get(tool_response["id"], 0)
                            
                            tool_completed_content = {
                                "status_type": "tool_completed",
                                "tool_index": tool_index
                            }
                            
                            tool_completed_metadata = {
                                "stream_status": "tool_completed",
                                "thread_run_id": thread_run_id,
                                "tool_name": tool_response["name"],
                                "tool_index": tool_index
                            }
                            
                            # 🔧 保存工具完成状态消息到数据库
                            saved_tool_completed_msg = await self._add_message_with_agent_info(
                                thread_id=thread_id,
                                type="status",
                                content=tool_completed_content,
                                is_llm_message=False,
                                metadata=tool_completed_metadata
                            )
                            
                            # Yield工具完成状态消息
                            if saved_tool_completed_msg:
                                yield format_for_yield(saved_tool_completed_msg)
                            else:
                                yield {
                                    "sequence": __sequence,
                                    "message_id": f"tool_completed_{uuid.uuid4().hex[:8]}",
                                    "thread_id": thread_id,
                                    "type": "status",
                                    "is_llm_message": False,
                                    "content": to_json_string(tool_completed_content),
                                    "metadata": to_json_string(tool_completed_metadata),
                                    "created_at": now_iso,
                                    "updated_at": now_iso
                                }
                            __sequence += 1

                    if chunk_text:
                        # 追加到累积内容中
                        # 🔧 确保拼接操作安全
                        if not isinstance(accumulated_content, str):
                            accumulated_content = str(accumulated_content)
                        if not isinstance(chunk_text, str):
                            chunk_text = str(chunk_text)
                        accumulated_content += chunk_text
                        current_xml_content += chunk_text

                        # 🔧 Yield 流式文本内容（只在非工具调用状态下）
                        if chunk_status == "delta":
                            now_chunk_iso = datetime.now(timezone.utc).isoformat()
                            yield {
                                "sequence": __sequence,
                                "message_id": None,
                                "thread_id": thread_id,
                                "type": "assistant",
                                "is_llm_message": True,
                                "content": to_json_string({"role": "assistant", "content": chunk_text}),
                                "metadata": to_json_string({"stream_status": "chunk", "thread_run_id": thread_run_id}),
                                "created_at": now_chunk_iso,
                                "updated_at": now_chunk_iso
                            }
                            __sequence += 1

                    # # ---- XML tool-calls in-stream (same as original) ----
                    # if config.xml_tool_calling and not (config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls):
                    #     xml_chunks = self._extract_xml_chunks(current_xml_content)
                    #     for xml_chunk in xml_chunks:
                    #         current_xml_content = current_xml_content.replace(xml_chunk, "", 1)
                    #         xml_chunks_buffer.append(xml_chunk)
                    #         result = self._parse_xml_tool_call(xml_chunk)
                    #         if result:
                    #             tool_call, parsing_details = result
                    #             xml_tool_call_count += 1
                    #             current_assistant_id = last_assistant_message_object['message_id'] if last_assistant_message_object else None
                    #             context = self._create_tool_context(
                    #                 tool_call, tool_index, current_assistant_id, parsing_details
                    #             )

                    #             if config.execute_tools and config.execute_on_stream:
                    #                 # tool_started
                    #                 started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                    #                 if started_msg_obj:
                    #                     yield format_for_yield(started_msg_obj)
                    #                 yielded_tool_indices.add(tool_index)

                    #                 execution_task = asyncio.create_task(self._execute_tool(tool_call))
                    #                 pending_tool_executions.append({
                    #                     "task": execution_task,
                    #                     "tool_call": tool_call,
                    #                     "tool_index": tool_index,
                    #                     "context": context
                    #                 })
                    #                 tool_index += 1

                    #             if config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls:
                    #                 logger.debug(f"Reached XML tool call limit ({config.max_xml_tool_calls})")
                    #                 finish_reason = "xml_tool_limit_reached"
                    #                 break

                    # TODO 处理原生工具调用
                    # # --- Process Native Tool Call Chunks ---
                    # if config.native_tool_calling and delta and hasattr(delta, 'tool_calls') and delta.tool_calls:
                    #     for tool_call_chunk in delta.tool_calls:
                    #         # Yield Native Tool Call Chunk (transient status, not saved)
                    #         # ... (safe extraction logic for tool_call_data_chunk) ...
                    #         tool_call_data_chunk = {} # Placeholder for extracted data
                    #         if hasattr(tool_call_chunk, 'model_dump'): tool_call_data_chunk = tool_call_chunk.model_dump()
                    #         else: # Manual extraction...
                    #             if hasattr(tool_call_chunk, 'id'): tool_call_data_chunk['id'] = tool_call_chunk.id
                    #             if hasattr(tool_call_chunk, 'index'): tool_call_data_chunk['index'] = tool_call_chunk.index
                    #             if hasattr(tool_call_chunk, 'type'): tool_call_data_chunk['type'] = tool_call_chunk.type
                    #             if hasattr(tool_call_chunk, 'function'):
                    #                 tool_call_data_chunk['function'] = {}
                    #                 if hasattr(tool_call_chunk.function, 'name'): tool_call_data_chunk['function']['name'] = tool_call_chunk.function.name
                    #                 if hasattr(tool_call_chunk.function, 'arguments'): tool_call_data_chunk['function']['arguments'] = tool_call_chunk.function.arguments if isinstance(tool_call_chunk.function.arguments, str) else to_json_string(tool_call_chunk.function.arguments)


                    #         now_tool_chunk = datetime.now(timezone.utc).isoformat()
                    #         yield {
                    #             "message_id": None, "thread_id": thread_id, "type": "status", "is_llm_message": True,
                    #             "content": to_json_string({"role": "assistant", "status_type": "tool_call_chunk", "tool_call_chunk": tool_call_data_chunk}),
                    #             "metadata": to_json_string({"thread_run_id": thread_run_id}),
                    #             "created_at": now_tool_chunk, "updated_at": now_tool_chunk
                    #         }

                    #         # --- Buffer and Execute Complete Native Tool Calls ---
                    #         if not hasattr(tool_call_chunk, 'function'): continue
                    #         idx = tool_call_chunk.index if hasattr(tool_call_chunk, 'index') else 0
                    #         # ... (buffer update logic remains same) ...
                    #         # ... (check complete logic remains same) ...
                    #         has_complete_tool_call = False # Placeholder
                    #         if (tool_calls_buffer.get(idx) and
                    #             tool_calls_buffer[idx]['id'] and
                    #             tool_calls_buffer[idx]['function']['name'] and
                    #             tool_calls_buffer[idx]['function']['arguments']):
                    #             try:
                    #                 safe_json_parse(tool_calls_buffer[idx]['function']['arguments'])
                    #                 has_complete_tool_call = True
                    #             except json.JSONDecodeError: pass


                    #         if has_complete_tool_call and config.execute_tools and config.execute_on_stream:
                    #             current_tool = tool_calls_buffer[idx]
                    #             tool_call_data = {
                    #                 "function_name": current_tool['function']['name'],
                    #                 "arguments": safe_json_parse(current_tool['function']['arguments']),
                    #                 "id": current_tool['id']
                    #             }
                    #             current_assistant_id = last_assistant_message_object['message_id'] if last_assistant_message_object else None
                    #             context = self._create_tool_context(
                    #                 tool_call_data, tool_index, current_assistant_id
                    #             )

                    #             # Save and Yield tool_started status
                    #             started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                    #             if started_msg_obj: yield format_for_yield(started_msg_obj)
                    #             yielded_tool_indices.add(tool_index) # Mark status as yielded

                    #             execution_task = asyncio.create_task(self._execute_tool(tool_call_data))
                    #             pending_tool_executions.append({
                    #                 "task": execution_task, "tool_call": tool_call_data,
                    #                 "tool_index": tool_index, "context": context
                    #             })
                    #             tool_index += 1

                # TODO
                # # 如果 ADK 标记为候选结束（partial==False），则可以视为自然停止，除非 finish_reason 存在
                # if getattr(event, "partial", None) is False and not finish_reason:
                #     finish_reason = "stop"

                # if finish_reason == "xml_tool_limit_reached":
                #     logger.info("Stopping stream processing after loop due to XML tool call limit")
                #     self.trace.event(
                #         name="stopping_stream_processing_after_loop_due_to_xml_tool_limit",
                #         level="DEFAULT",
                #         status_message="Stopping stream processing after loop due to XML tool call limit"
                #     )
                #     break

            # -------- 流式循环的后处理工作 --------

            # 如果模型接口没有返回使用数据，则使用litellm.token_counter计算
            if streaming_metadata["usage"]["total_tokens"] == 0:
                print("🔥 No usage data from provider, counting with litellm.token_counter")
                try:
                    prompt_tokens = token_counter(model=llm_model, messages=prompt_messages)
                    completion_tokens = token_counter(model=llm_model, text=accumulated_content or "")
                    streaming_metadata["usage"]["prompt_tokens"] = prompt_tokens
                    streaming_metadata["usage"]["completion_tokens"] = completion_tokens
                    streaming_metadata["usage"]["total_tokens"] = prompt_tokens + completion_tokens
                    self.trace.event(
                        name="usage_calculated_with_litellm_token_counter",
                        level="DEFAULT",
                        status_message="Usage calculated with litellm.token_counter"
                    )
                except Exception as e:
                    logger.warning(f"Failed to calculate usage: {str(e)}")
                    self.trace.event(
                        name="failed_to_calculate_usage",
                        level="WARNING",
                        status_message=f"Failed to calculate usage: {str(e)}"
                    )


            # Wait any pending streamed tool executions
            tool_results_buffer = [] # Stores (tool_call, result, tool_index, context)

            # TODO： 处理Pending 工具调用的结果
            # if pending_tool_executions:
            #     logger.info(f"Waiting for {len(pending_tool_executions)} pending streamed tool executions")
            #     self.trace.event(name="waiting_for_pending_streamed_tool_executions", level="DEFAULT", status_message=(f"Waiting for {len(pending_tool_executions)} pending streamed tool executions"))
            #     # ... (asyncio.wait logic) ...
            #     pending_tasks = [execution["task"] for execution in pending_tool_executions]
            #     done, _ = await asyncio.wait(pending_tasks)

            #     for execution in pending_tool_executions:
            #         tool_idx = execution.get("tool_index", -1)
            #         context = execution["context"]
            #         tool_name = context.function_name
                    
            #         # Check if status was already yielded during stream run
            #         if tool_idx in yielded_tool_indices:
            #              logger.debug(f"Status for tool index {tool_idx} already yielded.")
            #              # Still need to process the result for the buffer
            #              try:
            #                  if execution["task"].done():
            #                      result = execution["task"].result()
            #                      context.result = result
            #                      tool_results_buffer.append((execution["tool_call"], result, tool_idx, context))
                                 
            #                      if tool_name in ['ask', 'complete']:
            #                          logger.info(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag.")
            #                          self.trace.event(name="terminating_tool_completed_during_streaming", level="DEFAULT", status_message=(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag."))
            #                          agent_should_terminate = True
                                     
            #                  else: # Should not happen with asyncio.wait
            #                     logger.warning(f"Task for tool index {tool_idx} not done after wait.")
            #                     self.trace.event(name="task_for_tool_index_not_done_after_wait", level="WARNING", status_message=(f"Task for tool index {tool_idx} not done after wait."))
            #              except Exception as e:
            #                  logger.error(f"Error getting result for pending tool execution {tool_idx}: {str(e)}")
            #                  self.trace.event(name="error_getting_result_for_pending_tool_execution", level="ERROR", status_message=(f"Error getting result for pending tool execution {tool_idx}: {str(e)}"))
            #                  context.error = e
            #                  # Save and Yield tool error status message (even if started was yielded)
            #                  error_msg_obj = await self._yield_and_save_tool_error(context, thread_id, thread_run_id)
            #                  if error_msg_obj: yield format_for_yield(error_msg_obj)
            #              continue # Skip further status yielding for this tool index
            #         # If status wasn't yielded before (shouldn't happen with current logic), yield it now
            #         try:
            #             if execution["task"].done():
            #                 result = execution["task"].result()
            #                 context.result = result
            #                 tool_results_buffer.append((execution["tool_call"], result, tool_idx, context))
                            
            #                 # Check if this is a terminating tool
            #                 if tool_name in ['ask', 'complete']:
            #                     logger.info(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag.")
            #                     self.trace.event(name="terminating_tool_completed_during_streaming", level="DEFAULT", status_message=(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag."))
            #                     agent_should_terminate = True
                                
            #                 # Save and Yield tool completed/failed status
            #                 completed_msg_obj = await self._yield_and_save_tool_completed(
            #                     context, None, thread_id, thread_run_id
            #                 )
            #                 if completed_msg_obj: yield format_for_yield(completed_msg_obj)
            #                 yielded_tool_indices.add(tool_idx)
            #         except Exception as e:
            #             logger.error(f"Error getting result/yielding status for pending tool execution {tool_idx}: {str(e)}")
            #             self.trace.event(name="error_getting_result_yielding_status_for_pending_tool_execution", level="ERROR", status_message=(f"Error getting result/yielding status for pending tool execution {tool_idx}: {str(e)}"))
            #             context.error = e
            #             # Save and Yield tool error status
            #             error_msg_obj = await self._yield_and_save_tool_error(context, thread_id, thread_run_id)
            #             if error_msg_obj: yield format_for_yield(error_msg_obj)
            #             yielded_tool_indices.add(tool_idx)


            # # TODO：处理工具调用触达限制问题
            # # Save and yield finish status if XML tool limit reached
            # if finish_reason == "xml_tool_limit_reached":
            #     finish_msg_obj = await self.add_message(
            #         thread_id=thread_id,
            #         type="status",
            #         content={"status_type": "finish", "finish_reason": "xml_tool_limit_reached"},
            #         is_llm_message=False,
            #         metadata={"thread_run_id": thread_run_id}
            #     )
            #     if finish_msg_obj:
            #         yield format_for_yield(finish_msg_obj)
            #     logger.info(f"Stream finished with reason: xml_tool_limit_reached after {xml_tool_call_count} XML tool calls")

            # 自动继续的条件： 如果可以自动继续，并且 finish_reason 是长度限制
            should_auto_continue = (can_auto_continue and finish_reason == 'length')

            # 保存并 yelid 最终的 assistant 消息
            # -------- SAVE + YIELD final assistant message (if not auto-continue) --------
            if accumulated_content and not should_auto_continue:
                # TODO：
                # 截断累积内容的逻辑
                # # 如果由于 XML 容量限制而停止，则将内容截断至包含最后一个已关闭的 XML 标签。
                # if config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls and xml_chunks_buffer:
                #     last_xml_chunk = xml_chunks_buffer[-1]
                #     last_chunk_end_pos = accumulated_content.find(last_xml_chunk) + len(last_xml_chunk)
                #     if last_chunk_end_pos > 0:
                #         accumulated_content = accumulated_content[:last_chunk_end_pos]

                # 从缓冲区构建完整的原生工具调用（如果将来启用了原生工具）
                # if config.native_tool_calling:
                #     for idx, tc_buf in tool_calls_buffer.items():
                #         if tc_buf.get('id') and tc_buf.get('function', {}).get('name') and tc_buf['function'].get('arguments'):
                #             try:
                #                 args = safe_json_parse(tc_buf['function']['arguments'])
                #                 complete_native_tool_calls.append({
                #                     "id": tc_buf['id'], "type": "function",
                #                     "function": {"name": tc_buf['function']['name'], "arguments": args}
                #                 })
                #             except json.JSONDecodeError:
                #                 continue

                # 构建最终的 assistant 消息
                message_data = {
                    "role": "assistant", 
                    "content": accumulated_content, 
                    "tool_calls": complete_native_tool_calls or None
                    }

                # 与原版一致：用 _add_message_with_agent_info 以便 metadata/agent 信息一致
                last_assistant_message_object = await self._add_message_with_agent_info(
                    thread_id=thread_id,
                    type="assistant",
                    content=message_data,
                    is_llm_message=True,
                    metadata={"thread_run_id": thread_run_id}
                )

                if last_assistant_message_object:
                    yield_message = last_assistant_message_object.copy()
                    print(f"拷贝的yield_message: {yield_message}")
                    yield_metadata = ensure_dict(yield_message.get('metadata'), {})
                    print(f"处理后的yield_metadata: {yield_metadata}")
                    yield_metadata['stream_status'] = 'complete'
                    print(f"处理后的yield_metadata: {yield_metadata}")
                    yield_message['metadata'] = yield_metadata
                    print(f"处理后的yield_message: {yield_message}")
                    yield format_for_yield(yield_message)
                else:
                    logger.error(f"Failed to save final assistant message for thread {thread_id}")
                    self.trace.event(
                        name="failed_to_save_final_assistant_message_for_thread",
                        level="ERROR",
                        status_message=f"Failed to save final assistant message for thread {thread_id}"
                    )
                    err_msg_obj = await self.add_message(
                        thread_id=thread_id,
                        type="status",
                        content={"role": "system", "status_type": "error", "message": "Failed to save final assistant message"},
                        is_llm_message=False,
                        metadata={"thread_run_id": thread_run_id}
                    )
                    if err_msg_obj:
                        yield format_for_yield(err_msg_obj)

            # -------- Execute any remaining tools after stream (same policy as original) --------
            if config.execute_tools:
                final_tool_calls_to_process: List[Dict[str, Any]] = []

                # Native (buffered) — placeholder for future native support with ADK
                if config.native_tool_calling and complete_native_tool_calls:
                    for tc in complete_native_tool_calls:
                        final_tool_calls_to_process.append({
                            "function_name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                            "id": tc["id"]
                        })

                # XML (from buffered xml_chunks not yet executed)
                parsed_xml_data: List[Dict[str, Any]] = []
                if config.xml_tool_calling:
                    xml_chunks = self._extract_xml_chunks(current_xml_content)
                    xml_chunks_buffer.extend(xml_chunks)
                    remaining_limit = config.max_xml_tool_calls - xml_tool_call_count if config.max_xml_tool_calls > 0 else len(xml_chunks_buffer)
                    xml_chunks_to_process = xml_chunks_buffer[:remaining_limit]

                    for chunk in xml_chunks_to_process:
                        parsed_result = self._parse_xml_tool_call(chunk)
                        if parsed_result:
                            tool_call, parsing_details = parsed_result
                            if not any(execd['tool_call'] == tool_call for execd in pending_tool_executions):
                                final_tool_calls_to_process.append(tool_call)
                                parsed_xml_data.append({'tool_call': tool_call, 'parsing_details': parsing_details})

                # Build mapping back indices
                all_tool_data_map: Dict[int, Dict[str, Any]] = {}
                native_tool_index = 0
                if config.native_tool_calling and complete_native_tool_calls:
                    for tc in complete_native_tool_calls:
                        exec_tool_call = {"function_name": tc["function"]["name"], "arguments": tc["function"]["arguments"], "id": tc["id"]}
                        all_tool_data_map[native_tool_index] = {"tool_call": exec_tool_call, "parsing_details": None}
                        native_tool_index += 1

                xml_tool_index_start = native_tool_index
                for idx, item in enumerate(parsed_xml_data):
                    all_tool_data_map[xml_tool_index_start + idx] = item

                tool_results_map: Dict[int, Tuple[Dict[str, Any], Any, Any]] = {}

                if config.execute_on_stream and tool_results_buffer:
                    logger.info(f"Processing {len(tool_results_buffer)} buffered tool results")
                    self.trace.event(
                        name="processing_buffered_tool_results",
                        level="DEFAULT",
                        status_message=f"Processing {len(tool_results_buffer)} buffered tool results"
                    )
                    for tool_call, result, tool_idx, context in tool_results_buffer:
                        if last_assistant_message_object:
                            context.assistant_message_id = last_assistant_message_object['message_id']
                        tool_results_map[tool_idx] = (tool_call, result, context)

                elif final_tool_calls_to_process and not config.execute_on_stream:
                    logger.info(f"Executing {len(final_tool_calls_to_process)} tools ({config.tool_execution_strategy}) after stream")
                    self.trace.event(
                        name="executing_tools_after_stream",
                        level="DEFAULT",
                        status_message=f"Executing {len(final_tool_calls_to_process)} tools ({config.tool_execution_strategy}) after stream"
                    )
                    results_list = await self._execute_tools(final_tool_calls_to_process, config.tool_execution_strategy)
                    current_tool_idx = 0
                    for tc, res in results_list:
                        if current_tool_idx in all_tool_data_map:
                            tool_data = all_tool_data_map[current_tool_idx]
                            context = self._create_tool_context(
                                tc, current_tool_idx,
                                last_assistant_message_object['message_id'] if last_assistant_message_object else None,
                                tool_data.get('parsing_details')
                            )
                            context.result = res
                            tool_results_map[current_tool_idx] = (tc, res, context)
                        else:
                            logger.warning(f"Could not map result for tool index {current_tool_idx}")
                            self.trace.event(
                                name="could_not_map_result_for_tool_index",
                                level="WARNING",
                                status_message=f"Could not map result for tool index {current_tool_idx}"
                            )
                        current_tool_idx += 1

                if tool_results_map:
                    logger.info(f"Saving and yielding {len(tool_results_map)} final tool result messages")
                    self.trace.event(
                        name="saving_and_yielding_final_tool_result_messages",
                        level="DEFAULT",
                        status_message=f"Saving and yielding {len(tool_results_map)} final tool result messages"
                    )
                    for tool_idx in sorted(tool_results_map.keys()):
                        tool_call, result, context = tool_results_map[tool_idx]
                        context.result = result
                        if not context.assistant_message_id and last_assistant_message_object:
                            context.assistant_message_id = last_assistant_message_object['message_id']

                        if not config.execute_on_stream and tool_idx not in yielded_tool_indices:
                            started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                            if started_msg_obj:
                                yield format_for_yield(started_msg_obj)
                            yielded_tool_indices.add(tool_idx)

                        saved_tool_result_object = await self._add_tool_result(
                            thread_id, tool_call, result, config.xml_adding_strategy,
                            context.assistant_message_id, context.parsing_details
                        )

                        completed_msg_obj = await self._yield_and_save_tool_completed(
                            context,
                            saved_tool_result_object['message_id'] if saved_tool_result_object else None,
                            thread_id, thread_run_id
                        )
                        if completed_msg_obj:
                            yield format_for_yield(completed_msg_obj)

                        if saved_tool_result_object:
                            tool_result_message_objects[tool_idx] = saved_tool_result_object
                            yield format_for_yield(saved_tool_result_object)
                        else:
                            logger.error(f"Failed to save tool result for index {tool_idx}, not yielding result message.")
                            self.trace.event(
                                name="failed_to_save_tool_result_for_index",
                                level="ERROR",
                                status_message=f"Failed to save tool result for index {tool_idx}, not yielding result message."
                            )

            # Final finish status (if not already yielded for XML cap)
            if finish_reason and finish_reason != "xml_tool_limit_reached":
                finish_msg_obj = await self.add_message(
                    thread_id=thread_id,
                    type="status",
                    content={"status_type": "finish", "finish_reason": finish_reason},
                    is_llm_message=False,
                    metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj:
                    yield format_for_yield(finish_msg_obj)

            # Handle termination after executing terminating tools
            if agent_should_terminate:
                logger.info("Agent termination requested after executing ask/complete tool. Stopping further processing.")
                self.trace.event(name="agent_termination_requested", level="DEFAULT", status_message="Agent termination requested after executing ask/complete tool. Stopping further processing.")
                finish_reason = "agent_terminated"

                finish_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status",
                    content={"status_type": "finish", "finish_reason": "agent_terminated"},
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj:
                    yield format_for_yield(finish_msg_obj)

                if last_assistant_message_object:
                    try:
                        if streaming_metadata["first_chunk_time"] and streaming_metadata["last_chunk_time"]:
                            streaming_metadata["response_ms"] = (streaming_metadata["last_chunk_time"] - streaming_metadata["first_chunk_time"]) * 1000

                        assistant_end_content = {
                            "choices": [{
                                "finish_reason": finish_reason or "stop",
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": accumulated_content,
                                    "tool_calls": complete_native_tool_calls or None
                                }
                            }],
                            "created": streaming_metadata.get("created"),
                            "model": streaming_metadata.get("model", llm_model),
                            "usage": streaming_metadata["usage"],
                            "streaming": True,
                        }
                        if streaming_metadata.get("response_ms"):
                            assistant_end_content["response_ms"] = streaming_metadata["response_ms"]

                        await self.add_message(
                            thread_id=thread_id,
                            type="assistant_response_end",
                            content=assistant_end_content,
                            is_llm_message=False,
                            metadata={"thread_run_id": thread_run_id}
                        )
                        logger.info("Assistant response end saved for stream (before termination)")
                    except Exception as e:
                        logger.error(f"Error saving assistant response end for stream (before termination): {str(e)}")
                        self.trace.event(
                            name="error_saving_assistant_response_end_for_stream_before_termination",
                            level="ERROR",
                            status_message=f"Error saving assistant response end for stream (before termination): {str(e)}"
                        )
                return  # terminate early

            # Save assistant_response_end (only when not auto-continue)
            if not should_auto_continue and last_assistant_message_object:
                try:
                    if streaming_metadata["first_chunk_time"] and streaming_metadata["last_chunk_time"]:
                        streaming_metadata["response_ms"] = (streaming_metadata["last_chunk_time"] - streaming_metadata["first_chunk_time"]) * 1000

                    assistant_end_content = {
                        "choices": [{
                            "finish_reason": finish_reason or "stop",
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": accumulated_content,
                                "tool_calls": complete_native_tool_calls or None
                            }
                        }],
                        "created": streaming_metadata.get("created"),
                        "model": streaming_metadata.get("model", llm_model),
                        "usage": streaming_metadata["usage"],
                        "streaming": True,
                    }
                    if streaming_metadata.get("response_ms"):
                        assistant_end_content["response_ms"] = streaming_metadata["response_ms"]

                    await self.add_message(
                        thread_id=thread_id,
                        type="assistant_response_end",
                        content=assistant_end_content,
                        is_llm_message=False,
                        metadata={"thread_run_id": thread_run_id}
                    )
                    logger.info("Assistant response end saved for stream")
                except Exception as e:
                    logger.error(f"Error saving assistant response end for stream: {str(e)}")
                    self.trace.event(
                        name="error_saving_assistant_response_end_for_stream",
                        level="ERROR",
                        status_message=f"Error saving assistant response end for stream: {str(e)}"
                    )

        except Exception as e:
            logger.error(f"Error processing ADK streaming response: {str(e)}", exc_info=True)
            self.trace.event(
                name="error_processing_adk_stream",
                level="ERROR",
                status_message=f"Error processing ADK streaming response: {str(e)}"
            )
            err_msg_obj = await self.add_message(
                thread_id=thread_id, type="status",
                content={"role": "system", "status_type": "error", "message": str(e)},
                is_llm_message=False, metadata={"thread_run_id": thread_run_id if 'thread_run_id' in locals() else None}
            )
            if err_msg_obj:
                yield format_for_yield(err_msg_obj)
            raise

        finally:
            # Update continuous state or close run
            if should_auto_continue:
                continuous_state['accumulated_content'] = accumulated_content
                continuous_state['sequence'] = __sequence
                logger.info(f"Updated continuous state for auto-continue with {len(accumulated_content)} chars")
            else:
                try:
                    end_msg_obj = await self.add_message(
                        thread_id=thread_id, type="status",
                        content={"status_type": "thread_run_end"},
                        is_llm_message=False, metadata={"thread_run_id": thread_run_id if 'thread_run_id' in locals() else None}
                    )
                    if end_msg_obj:
                        yield format_for_yield(end_msg_obj)
                except Exception as final_e:
                    logger.error(f"Error in finally block: {str(final_e)}", exc_info=True)
                    self.trace.event(
                        name="error_in_finally_block",
                        level="ERROR",
                        status_message=f"Error in finally block: {str(final_e)}"
                    )

    async def process_streaming_response(
        self,
        llm_response: AsyncGenerator,
        thread_id: str,
        prompt_messages: List[Dict[str, Any]],
        llm_model: str,
        config: ProcessorConfig = ProcessorConfig(),
        can_auto_continue: bool = False,
        auto_continue_count: int = 0,
        continuous_state: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process a streaming LLM response, handling tool calls and execution.
        
        Args:
            llm_response: Streaming response from the LLM
            thread_id: ID of the conversation thread
            prompt_messages: List of messages sent to the LLM (the prompt)
            llm_model: The name of the LLM model used
            config: Configuration for parsing and execution
            can_auto_continue: Whether auto-continue is enabled
            auto_continue_count: Number of auto-continue cycles
            continuous_state: Previous state of the conversation
            
        Yields:
            Complete message objects matching the DB schema, except for content chunks.
        """
        # Initialize from continuous state if provided (for auto-continue)
        continuous_state = continuous_state or {}
        accumulated_content = continuous_state.get('accumulated_content', "")
        tool_calls_buffer = {}
        current_xml_content = accumulated_content   # equal to accumulated_content if auto-continuing, else blank
        xml_chunks_buffer = []
        pending_tool_executions = []
        yielded_tool_indices = set() # Stores indices of tools whose *status* has been yielded
        tool_index = 0
        xml_tool_call_count = 0
        finish_reason = None
        should_auto_continue = False
        last_assistant_message_object = None # Store the final saved assistant message object
        tool_result_message_objects = {} # tool_index -> full saved message object
        has_printed_thinking_prefix = False # Flag for printing thinking prefix only once
        agent_should_terminate = False # Flag to track if a terminating tool has been executed
        complete_native_tool_calls = [] # Initialize early for use in assistant_response_end

        # Collect metadata for reconstructing LiteLLM response object
        streaming_metadata = {
            "model": llm_model,
            "created": None,
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "response_ms": None,
            "first_chunk_time": None,
            "last_chunk_time": None
        }

        logger.info(f"Streaming Config: XML={config.xml_tool_calling}, Native={config.native_tool_calling}, "
                   f"Execute on stream={config.execute_on_stream}, Strategy={config.tool_execution_strategy}")

        # Reuse thread_run_id for auto-continue or create new one
        thread_run_id = continuous_state.get('thread_run_id') or str(uuid.uuid4())
        continuous_state['thread_run_id'] = thread_run_id

        try:
            # --- Save and Yield Start Events (only if not auto-continuing) ---
            if auto_continue_count == 0:
                start_content = {"status_type": "thread_run_start", "thread_run_id": thread_run_id}
                start_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=start_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if start_msg_obj: yield format_for_yield(start_msg_obj)

                assist_start_content = {"status_type": "assistant_response_start"}
                assist_start_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=assist_start_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if assist_start_msg_obj: yield format_for_yield(assist_start_msg_obj)
            # --- End Start Events ---

            __sequence = continuous_state.get('sequence', 0)    # get the sequence from the previous auto-continue cycle

            async for chunk in llm_response:
                # Extract streaming metadata from chunks
                current_time = datetime.now(timezone.utc).timestamp()
                if streaming_metadata["first_chunk_time"] is None:
                    streaming_metadata["first_chunk_time"] = current_time
                streaming_metadata["last_chunk_time"] = current_time
                
                # Extract metadata from chunk attributes
                if hasattr(chunk, 'created') and chunk.created:
                    streaming_metadata["created"] = chunk.created
                if hasattr(chunk, 'model') and chunk.model:
                    streaming_metadata["model"] = chunk.model
                if hasattr(chunk, 'usage') and chunk.usage:
                    # Update usage information if available (including zero values)
                    if hasattr(chunk.usage, 'prompt_tokens') and chunk.usage.prompt_tokens is not None:
                        streaming_metadata["usage"]["prompt_tokens"] = chunk.usage.prompt_tokens
                    if hasattr(chunk.usage, 'completion_tokens') and chunk.usage.completion_tokens is not None:
                        streaming_metadata["usage"]["completion_tokens"] = chunk.usage.completion_tokens
                    if hasattr(chunk.usage, 'total_tokens') and chunk.usage.total_tokens is not None:
                        streaming_metadata["usage"]["total_tokens"] = chunk.usage.total_tokens

                if hasattr(chunk, 'choices') and chunk.choices and hasattr(chunk.choices[0], 'finish_reason') and chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                    logger.debug(f"Detected finish_reason: {finish_reason}")

                if hasattr(chunk, 'choices') and chunk.choices:
                    delta = chunk.choices[0].delta if hasattr(chunk.choices[0], 'delta') else None
                    
                    # Check for and log Anthropic thinking content
                    if delta and hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        if not has_printed_thinking_prefix:
                            # print("[THINKING]: ", end='', flush=True)
                            has_printed_thinking_prefix = True
                        # print(delta.reasoning_content, end='', flush=True)
                        # Append reasoning to main content to be saved in the final message
                        reasoning_content = delta.reasoning_content
                        if isinstance(reasoning_content, list):
                            reasoning_content = ' '.join(str(item) for item in reasoning_content)
                        elif not isinstance(reasoning_content, str):
                            reasoning_content = str(reasoning_content)
                        accumulated_content += reasoning_content

                    # Process content chunk
                    if delta and hasattr(delta, 'content') and delta.content and not handled_text:
                        chunk_content = delta.content
                        # print(chunk_content, end='', flush=True)
                        
                        # 确保chunk_content是字符串
                        if isinstance(chunk_content, list):
                            chunk_content = ' '.join(str(item) for item in chunk_content)
                        elif not isinstance(chunk_content, str):
                            chunk_content = str(chunk_content)
                        
                        # 🔧 这是非ADK路径，但也要避免重复累积
                        # 由于有handled_text保护，这里通常不会被ADK事件触发
                        accumulated_content += chunk_content
                        current_xml_content += chunk_content

                        if not (config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls):
                            # Yield ONLY content chunk (don't save)
                            now_chunk = datetime.now(timezone.utc).isoformat()
                            yield {
                                "sequence": __sequence,
                                "message_id": None, "thread_id": thread_id, "type": "assistant",
                                "is_llm_message": True,
                                "content": to_json_string({"role": "assistant", "content": chunk_content}),
                                "metadata": to_json_string({"stream_status": "chunk", "thread_run_id": thread_run_id}),
                                "created_at": now_chunk, "updated_at": now_chunk
                            }
                            __sequence += 1
                        else:
                            logger.info("XML tool call limit reached - not yielding more content chunks")
                            self.trace.event(name="xml_tool_call_limit_reached", level="DEFAULT", status_message=(f"XML tool call limit reached - not yielding more content chunks"))

                        # --- Process XML Tool Calls (if enabled and limit not reached) ---
                        if config.xml_tool_calling and not (config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls):
                            xml_chunks = self._extract_xml_chunks(current_xml_content)
                            for xml_chunk in xml_chunks:
                                current_xml_content = current_xml_content.replace(xml_chunk, "", 1)
                                xml_chunks_buffer.append(xml_chunk)
                                result = self._parse_xml_tool_call(xml_chunk)
                                if result:
                                    tool_call, parsing_details = result
                                    xml_tool_call_count += 1
                                    current_assistant_id = last_assistant_message_object['message_id'] if last_assistant_message_object else None
                                    context = self._create_tool_context(
                                        tool_call, tool_index, current_assistant_id, parsing_details
                                    )

                                    if config.execute_tools and config.execute_on_stream:
                                        # Save and Yield tool_started status
                                        started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                                        if started_msg_obj: yield format_for_yield(started_msg_obj)
                                        yielded_tool_indices.add(tool_index) # Mark status as yielded

                                        execution_task = asyncio.create_task(self._execute_tool(tool_call))
                                        pending_tool_executions.append({
                                            "task": execution_task, "tool_call": tool_call,
                                            "tool_index": tool_index, "context": context
                                        })
                                        tool_index += 1

                                    if config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls:
                                        logger.debug(f"Reached XML tool call limit ({config.max_xml_tool_calls})")
                                        finish_reason = "xml_tool_limit_reached"
                                        break # Stop processing more XML chunks in this delta

                    # --- Process Native Tool Call Chunks ---
                    if config.native_tool_calling and delta and hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tool_call_chunk in delta.tool_calls:
                            # Yield Native Tool Call Chunk (transient status, not saved)
                            # ... (safe extraction logic for tool_call_data_chunk) ...
                            tool_call_data_chunk = {} # Placeholder for extracted data
                            if hasattr(tool_call_chunk, 'model_dump'): tool_call_data_chunk = tool_call_chunk.model_dump()
                            else: # Manual extraction...
                                if hasattr(tool_call_chunk, 'id'): tool_call_data_chunk['id'] = tool_call_chunk.id
                                if hasattr(tool_call_chunk, 'index'): tool_call_data_chunk['index'] = tool_call_chunk.index
                                if hasattr(tool_call_chunk, 'type'): tool_call_data_chunk['type'] = tool_call_chunk.type
                                if hasattr(tool_call_chunk, 'function'):
                                    tool_call_data_chunk['function'] = {}
                                    if hasattr(tool_call_chunk.function, 'name'): tool_call_data_chunk['function']['name'] = tool_call_chunk.function.name
                                    if hasattr(tool_call_chunk.function, 'arguments'): tool_call_data_chunk['function']['arguments'] = tool_call_chunk.function.arguments if isinstance(tool_call_chunk.function.arguments, str) else to_json_string(tool_call_chunk.function.arguments)


                            now_tool_chunk = datetime.now(timezone.utc).isoformat()
                            yield {
                                "message_id": None, "thread_id": thread_id, "type": "status", "is_llm_message": True,
                                "content": to_json_string({"role": "assistant", "status_type": "tool_call_chunk", "tool_call_chunk": tool_call_data_chunk}),
                                "metadata": to_json_string({"thread_run_id": thread_run_id}),
                                "created_at": now_tool_chunk, "updated_at": now_tool_chunk
                            }

                            # --- Buffer and Execute Complete Native Tool Calls ---
                            if not hasattr(tool_call_chunk, 'function'): continue
                            idx = tool_call_chunk.index if hasattr(tool_call_chunk, 'index') else 0
                            # ... (buffer update logic remains same) ...
                            # ... (check complete logic remains same) ...
                            has_complete_tool_call = False # Placeholder
                            if (tool_calls_buffer.get(idx) and
                                tool_calls_buffer[idx]['id'] and
                                tool_calls_buffer[idx]['function']['name'] and
                                tool_calls_buffer[idx]['function']['arguments']):
                                try:
                                    safe_json_parse(tool_calls_buffer[idx]['function']['arguments'])
                                    has_complete_tool_call = True
                                except json.JSONDecodeError: pass


                            if has_complete_tool_call and config.execute_tools and config.execute_on_stream:
                                current_tool = tool_calls_buffer[idx]
                                tool_call_data = {
                                    "function_name": current_tool['function']['name'],
                                    "arguments": safe_json_parse(current_tool['function']['arguments']),
                                    "id": current_tool['id']
                                }
                                current_assistant_id = last_assistant_message_object['message_id'] if last_assistant_message_object else None
                                context = self._create_tool_context(
                                    tool_call_data, tool_index, current_assistant_id
                                )

                                # Save and Yield tool_started status
                                started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                                if started_msg_obj: yield format_for_yield(started_msg_obj)
                                yielded_tool_indices.add(tool_index) # Mark status as yielded

                                execution_task = asyncio.create_task(self._execute_tool(tool_call_data))
                                pending_tool_executions.append({
                                    "task": execution_task, "tool_call": tool_call_data,
                                    "tool_index": tool_index, "context": context
                                })
                                tool_index += 1

                if finish_reason == "xml_tool_limit_reached":
                    logger.info("Stopping stream processing after loop due to XML tool call limit")
                    self.trace.event(name="stopping_stream_processing_after_loop_due_to_xml_tool_call_limit", level="DEFAULT", status_message=(f"Stopping stream processing after loop due to XML tool call limit"))
                    break

            # print() # Add a final newline after the streaming loop finishes

            # --- After Streaming Loop ---
            
            if (
                streaming_metadata["usage"]["total_tokens"] == 0
            ):
                logger.info("🔥 No usage data from provider, counting with litellm.token_counter")
                
                try:
                    # prompt side
                    prompt_tokens = token_counter(
                        model=llm_model,
                        messages=prompt_messages               # chat or plain; token_counter handles both
                    )

                    # completion side
                    completion_tokens = token_counter(
                        model=llm_model,
                        text=accumulated_content or ""         # empty string safe
                    )

                    streaming_metadata["usage"]["prompt_tokens"]      = prompt_tokens
                    streaming_metadata["usage"]["completion_tokens"]  = completion_tokens
                    streaming_metadata["usage"]["total_tokens"]       = prompt_tokens + completion_tokens

                    logger.info(
                        f"🔥 Estimated tokens – prompt: {prompt_tokens}, "
                        f"completion: {completion_tokens}, total: {prompt_tokens + completion_tokens}"
                    )
                    self.trace.event(name="usage_calculated_with_litellm_token_counter", level="DEFAULT", status_message=(f"Usage calculated with litellm.token_counter"))
                except Exception as e:
                    logger.warning(f"Failed to calculate usage: {str(e)}")
                    self.trace.event(name="failed_to_calculate_usage", level="WARNING", status_message=(f"Failed to calculate usage: {str(e)}"))


            # Wait for pending tool executions from streaming phase
            tool_results_buffer = [] # Stores (tool_call, result, tool_index, context)
            if pending_tool_executions:
                logger.info(f"Waiting for {len(pending_tool_executions)} pending streamed tool executions")
                self.trace.event(name="waiting_for_pending_streamed_tool_executions", level="DEFAULT", status_message=(f"Waiting for {len(pending_tool_executions)} pending streamed tool executions"))
                # ... (asyncio.wait logic) ...
                pending_tasks = [execution["task"] for execution in pending_tool_executions]
                done, _ = await asyncio.wait(pending_tasks)

                for execution in pending_tool_executions:
                    tool_idx = execution.get("tool_index", -1)
                    context = execution["context"]
                    tool_name = context.function_name
                    
                    # Check if status was already yielded during stream run
                    if tool_idx in yielded_tool_indices:
                         logger.debug(f"Status for tool index {tool_idx} already yielded.")
                         # Still need to process the result for the buffer
                         try:
                             if execution["task"].done():
                                 result = execution["task"].result()
                                 context.result = result
                                 tool_results_buffer.append((execution["tool_call"], result, tool_idx, context))
                                 
                                 if tool_name in ['ask', 'complete']:
                                     logger.info(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag.")
                                     self.trace.event(name="terminating_tool_completed_during_streaming", level="DEFAULT", status_message=(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag."))
                                     agent_should_terminate = True
                                     
                             else: # Should not happen with asyncio.wait
                                logger.warning(f"Task for tool index {tool_idx} not done after wait.")
                                self.trace.event(name="task_for_tool_index_not_done_after_wait", level="WARNING", status_message=(f"Task for tool index {tool_idx} not done after wait."))
                         except Exception as e:
                             logger.error(f"Error getting result for pending tool execution {tool_idx}: {str(e)}")
                             self.trace.event(name="error_getting_result_for_pending_tool_execution", level="ERROR", status_message=(f"Error getting result for pending tool execution {tool_idx}: {str(e)}"))
                             context.error = e
                             # Save and Yield tool error status message (even if started was yielded)
                             error_msg_obj = await self._yield_and_save_tool_error(context, thread_id, thread_run_id)
                             if error_msg_obj: yield format_for_yield(error_msg_obj)
                         continue # Skip further status yielding for this tool index

                    # If status wasn't yielded before (shouldn't happen with current logic), yield it now
                    try:
                        if execution["task"].done():
                            result = execution["task"].result()
                            context.result = result
                            tool_results_buffer.append((execution["tool_call"], result, tool_idx, context))
                            
                            # Check if this is a terminating tool
                            if tool_name in ['ask', 'complete']:
                                logger.info(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag.")
                                self.trace.event(name="terminating_tool_completed_during_streaming", level="DEFAULT", status_message=(f"Terminating tool '{tool_name}' completed during streaming. Setting termination flag."))
                                agent_should_terminate = True
                                
                            # Save and Yield tool completed/failed status
                            completed_msg_obj = await self._yield_and_save_tool_completed(
                                context, None, thread_id, thread_run_id
                            )
                            if completed_msg_obj: yield format_for_yield(completed_msg_obj)
                            yielded_tool_indices.add(tool_idx)
                    except Exception as e:
                        logger.error(f"Error getting result/yielding status for pending tool execution {tool_idx}: {str(e)}")
                        self.trace.event(name="error_getting_result_yielding_status_for_pending_tool_execution", level="ERROR", status_message=(f"Error getting result/yielding status for pending tool execution {tool_idx}: {str(e)}"))
                        context.error = e
                        # Save and Yield tool error status
                        error_msg_obj = await self._yield_and_save_tool_error(context, thread_id, thread_run_id)
                        if error_msg_obj: yield format_for_yield(error_msg_obj)
                        yielded_tool_indices.add(tool_idx)


            # Save and yield finish status if limit was reached
            if finish_reason == "xml_tool_limit_reached":
                finish_content = {"status_type": "finish", "finish_reason": "xml_tool_limit_reached"}
                finish_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=finish_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj: yield format_for_yield(finish_msg_obj)
                logger.info(f"Stream finished with reason: xml_tool_limit_reached after {xml_tool_call_count} XML tool calls")
                self.trace.event(name="stream_finished_with_reason_xml_tool_limit_reached_after_xml_tool_calls", level="DEFAULT", status_message=(f"Stream finished with reason: xml_tool_limit_reached after {xml_tool_call_count} XML tool calls"))

            # Calculate if auto-continue is needed if the finish reason is length
            should_auto_continue = (can_auto_continue and finish_reason == 'length')

            # --- SAVE and YIELD Final Assistant Message ---
            # Only save assistant message if NOT auto-continuing due to length to avoid duplicate messages
            if accumulated_content and not should_auto_continue:
                # ... (Truncate accumulated_content logic) ...
                if config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls and xml_chunks_buffer:
                    last_xml_chunk = xml_chunks_buffer[-1]
                    last_chunk_end_pos = accumulated_content.find(last_xml_chunk) + len(last_xml_chunk)
                    if last_chunk_end_pos > 0:
                        accumulated_content = accumulated_content[:last_chunk_end_pos]

                # ... (Extract complete_native_tool_calls logic) ...
                # Update complete_native_tool_calls from buffer (initialized earlier)
                if config.native_tool_calling:
                    for idx, tc_buf in tool_calls_buffer.items():
                        if tc_buf['id'] and tc_buf['function']['name'] and tc_buf['function']['arguments']:
                            try:
                                args = safe_json_parse(tc_buf['function']['arguments'])
                                complete_native_tool_calls.append({
                                    "id": tc_buf['id'], "type": "function",
                                    "function": {"name": tc_buf['function']['name'],"arguments": args}
                                })
                            except json.JSONDecodeError: continue

                # 🔧 去除重复内容（防止streaming累积时重复）
                def deduplicate_content(content: str) -> str:
                    if not content:
                        return content
                    
                    # 检查是否内容重复了（简单检测：前一半和后一半相同）
                    content_len = len(content)
                    if content_len > 10:  # 只对足够长的内容进行检测
                        mid_point = content_len // 2
                        first_half = content[:mid_point].strip()
                        second_half = content[mid_point:].strip()
                        
                        # 如果前一半和后一半完全相同，说明重复了
                        if first_half and first_half == second_half:
                            logger.warning(f"Detected duplicate content, removing duplication")
                            return first_half
                    
                    return content

                deduplicated_content = deduplicate_content(accumulated_content)
                
                message_data = { # Dict to be saved in 'content' - ADK格式
                    "role": "model",
                    "parts": [{"text": deduplicated_content}]
                }

                last_assistant_message_object = await self._add_message_with_agent_info(
                    thread_id=thread_id, type="assistant", content=message_data,
                    is_llm_message=True, metadata={"thread_run_id": thread_run_id}
                )

                if last_assistant_message_object:
                    # Yield the complete saved object, adding stream_status metadata just for yield
                    yield_metadata = ensure_dict(last_assistant_message_object.get('metadata'), {})
                    yield_metadata['stream_status'] = 'complete'
                    # Format the message for yielding
                    yield_message = last_assistant_message_object.copy()
                    yield_message['metadata'] = yield_metadata
                    yield format_for_yield(yield_message)
                else:
                    logger.error(f"Failed to save final assistant message for thread {thread_id}")
                    self.trace.event(name="failed_to_save_final_assistant_message_for_thread", level="ERROR", status_message=(f"Failed to save final assistant message for thread {thread_id}"))
                    # Save and yield an error status
                    err_content = {"role": "system", "status_type": "error", "message": "Failed to save final assistant message"}
                    err_msg_obj = await self.add_message(
                        thread_id=thread_id, type="status", content=err_content, 
                        is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                    )
                    if err_msg_obj: yield format_for_yield(err_msg_obj)

            # --- Process All Tool Results Now ---
            if config.execute_tools:
                final_tool_calls_to_process = []
                # ... (Gather final_tool_calls_to_process from native and XML buffers) ...
                 # Gather native tool calls from buffer
                if config.native_tool_calling and complete_native_tool_calls:
                    for tc in complete_native_tool_calls:
                        final_tool_calls_to_process.append({
                            "function_name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"], # Already parsed object
                            "id": tc["id"]
                        })
                 # Gather XML tool calls from buffer (up to limit)
                parsed_xml_data = []
                if config.xml_tool_calling:
                    # Reparse remaining content just in case (should be empty if processed correctly)
                    xml_chunks = self._extract_xml_chunks(current_xml_content)
                    xml_chunks_buffer.extend(xml_chunks)
                    # Process only chunks not already handled in the stream loop
                    remaining_limit = config.max_xml_tool_calls - xml_tool_call_count if config.max_xml_tool_calls > 0 else len(xml_chunks_buffer)
                    xml_chunks_to_process = xml_chunks_buffer[:remaining_limit] # Ensure limit is respected

                    for chunk in xml_chunks_to_process:
                         parsed_result = self._parse_xml_tool_call(chunk)
                         if parsed_result:
                             tool_call, parsing_details = parsed_result
                             # Avoid adding if already processed during streaming
                             if not any(exec['tool_call'] == tool_call for exec in pending_tool_executions):
                                 final_tool_calls_to_process.append(tool_call)
                                 parsed_xml_data.append({'tool_call': tool_call, 'parsing_details': parsing_details})


                all_tool_data_map = {} # tool_index -> {'tool_call': ..., 'parsing_details': ...}
                 # Add native tool data
                native_tool_index = 0
                if config.native_tool_calling and complete_native_tool_calls:
                     for tc in complete_native_tool_calls:
                         # Find the corresponding entry in final_tool_calls_to_process if needed
                         # For now, assume order matches if only native used
                         exec_tool_call = {
                             "function_name": tc["function"]["name"],
                             "arguments": tc["function"]["arguments"],
                             "id": tc["id"]
                         }
                         all_tool_data_map[native_tool_index] = {"tool_call": exec_tool_call, "parsing_details": None}
                         native_tool_index += 1

                 # Add XML tool data
                xml_tool_index_start = native_tool_index
                for idx, item in enumerate(parsed_xml_data):
                    all_tool_data_map[xml_tool_index_start + idx] = item


                tool_results_map = {} # tool_index -> (tool_call, result, context)

                # Populate from buffer if executed on stream
                if config.execute_on_stream and tool_results_buffer:
                    logger.info(f"Processing {len(tool_results_buffer)} buffered tool results")
                    self.trace.event(name="processing_buffered_tool_results", level="DEFAULT", status_message=(f"Processing {len(tool_results_buffer)} buffered tool results"))
                    for tool_call, result, tool_idx, context in tool_results_buffer:
                        if last_assistant_message_object: context.assistant_message_id = last_assistant_message_object['message_id']
                        tool_results_map[tool_idx] = (tool_call, result, context)

                # Or execute now if not streamed
                elif final_tool_calls_to_process and not config.execute_on_stream:
                    logger.info(f"Executing {len(final_tool_calls_to_process)} tools ({config.tool_execution_strategy}) after stream")
                    self.trace.event(name="executing_tools_after_stream", level="DEFAULT", status_message=(f"Executing {len(final_tool_calls_to_process)} tools ({config.tool_execution_strategy}) after stream"))
                    results_list = await self._execute_tools(final_tool_calls_to_process, config.tool_execution_strategy)
                    current_tool_idx = 0
                    for tc, res in results_list:
                       # Map back using all_tool_data_map which has correct indices
                       if current_tool_idx in all_tool_data_map:
                           tool_data = all_tool_data_map[current_tool_idx]
                           context = self._create_tool_context(
                               tc, current_tool_idx,
                               last_assistant_message_object['message_id'] if last_assistant_message_object else None,
                               tool_data.get('parsing_details')
                           )
                           context.result = res
                           tool_results_map[current_tool_idx] = (tc, res, context)
                       else:
                           logger.warning(f"Could not map result for tool index {current_tool_idx}")
                           self.trace.event(name="could_not_map_result_for_tool_index", level="WARNING", status_message=(f"Could not map result for tool index {current_tool_idx}"))
                       current_tool_idx += 1

                # Save and Yield each result message
                if tool_results_map:
                    logger.info(f"Saving and yielding {len(tool_results_map)} final tool result messages")
                    self.trace.event(name="saving_and_yielding_final_tool_result_messages", level="DEFAULT", status_message=(f"Saving and yielding {len(tool_results_map)} final tool result messages"))
                    for tool_idx in sorted(tool_results_map.keys()):
                        tool_call, result, context = tool_results_map[tool_idx]
                        context.result = result
                        if not context.assistant_message_id and last_assistant_message_object:
                            context.assistant_message_id = last_assistant_message_object['message_id']

                        # Yield start status ONLY IF executing non-streamed (already yielded if streamed)
                        if not config.execute_on_stream and tool_idx not in yielded_tool_indices:
                            started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                            if started_msg_obj: yield format_for_yield(started_msg_obj)
                            yielded_tool_indices.add(tool_idx) # Mark status yielded

                        # Save the tool result message to DB
                        saved_tool_result_object = await self._add_tool_result( # Returns full object or None
                            thread_id, tool_call, result, config.xml_adding_strategy,
                            context.assistant_message_id, context.parsing_details
                        )

                        # Yield completed/failed status (linked to saved result ID if available)
                        completed_msg_obj = await self._yield_and_save_tool_completed(
                            context,
                            saved_tool_result_object['message_id'] if saved_tool_result_object else None,
                            thread_id, thread_run_id
                        )
                        if completed_msg_obj: yield format_for_yield(completed_msg_obj)
                        # Don't add to yielded_tool_indices here, completion status is separate yield

                        # Yield the saved tool result object
                        if saved_tool_result_object:
                            tool_result_message_objects[tool_idx] = saved_tool_result_object
                            yield format_for_yield(saved_tool_result_object)
                        else:
                             logger.error(f"Failed to save tool result for index {tool_idx}, not yielding result message.")
                             self.trace.event(name="failed_to_save_tool_result_for_index", level="ERROR", status_message=(f"Failed to save tool result for index {tool_idx}, not yielding result message."))
                             # Optionally yield error status for saving failure?

            # --- Final Finish Status ---
            if finish_reason and finish_reason != "xml_tool_limit_reached":
                finish_content = {"status_type": "finish", "finish_reason": finish_reason}
                finish_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=finish_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj: yield format_for_yield(finish_msg_obj)

            # Check if agent should terminate after processing pending tools
            if agent_should_terminate:
                logger.info("Agent termination requested after executing ask/complete tool. Stopping further processing.")
                self.trace.event(name="agent_termination_requested", level="DEFAULT", status_message="Agent termination requested after executing ask/complete tool. Stopping further processing.")
                
                # Set finish reason to indicate termination
                finish_reason = "agent_terminated"
                
                # Save and yield termination status
                finish_content = {"status_type": "finish", "finish_reason": "agent_terminated"}
                finish_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=finish_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj: yield format_for_yield(finish_msg_obj)
                
                # Save assistant_response_end BEFORE terminating
                if last_assistant_message_object:
                    try:
                        # Calculate response time if we have timing data
                        if streaming_metadata["first_chunk_time"] and streaming_metadata["last_chunk_time"]:
                            streaming_metadata["response_ms"] = (streaming_metadata["last_chunk_time"] - streaming_metadata["first_chunk_time"]) * 1000

                        # Create a LiteLLM-like response object for streaming (before termination)
                        # Check if we have any actual usage data
                        has_usage_data = (
                            streaming_metadata["usage"]["prompt_tokens"] > 0 or
                            streaming_metadata["usage"]["completion_tokens"] > 0 or
                            streaming_metadata["usage"]["total_tokens"] > 0
                        )
                        
                        assistant_end_content = {
                            "choices": [
                                {
                                    "finish_reason": finish_reason or "stop",
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": accumulated_content,
                                        "tool_calls": complete_native_tool_calls or None
                                    }
                                }
                            ],
                            "created": streaming_metadata.get("created"),
                            "model": streaming_metadata.get("model", llm_model),
                            "usage": streaming_metadata["usage"],  # Always include usage like LiteLLM does
                            "streaming": True,  # Add flag to indicate this was reconstructed from streaming
                        }
                        
                        # Only include response_ms if we have timing data
                        if streaming_metadata.get("response_ms"):
                            assistant_end_content["response_ms"] = streaming_metadata["response_ms"]
                        
                        await self.add_message(
                            thread_id=thread_id,
                            type="assistant_response_end",
                            content=assistant_end_content,
                            is_llm_message=False,
                            metadata={"thread_run_id": thread_run_id}
                        )
                        logger.info("Assistant response end saved for stream (before termination)")
                    except Exception as e:
                        logger.error(f"Error saving assistant response end for stream (before termination): {str(e)}")
                        self.trace.event(name="error_saving_assistant_response_end_for_stream_before_termination", level="ERROR", status_message=(f"Error saving assistant response end for stream (before termination): {str(e)}"))
                
                # Skip all remaining processing and go to finally block
                return

            # --- Save and Yield assistant_response_end ---
            # Only save assistant_response_end if not auto-continuing (response is actually complete)
            if not should_auto_continue:
                if last_assistant_message_object: # Only save if assistant message was saved
                    try:
                        # Calculate response time if we have timing data
                        if streaming_metadata["first_chunk_time"] and streaming_metadata["last_chunk_time"]:
                            streaming_metadata["response_ms"] = (streaming_metadata["last_chunk_time"] - streaming_metadata["first_chunk_time"]) * 1000

                        # Create a LiteLLM-like response object for streaming
                        # Check if we have any actual usage data
                        has_usage_data = (
                            streaming_metadata["usage"]["prompt_tokens"] > 0 or
                            streaming_metadata["usage"]["completion_tokens"] > 0 or
                            streaming_metadata["usage"]["total_tokens"] > 0
                        )
                        
                        assistant_end_content = {
                            "choices": [
                                {
                                    "finish_reason": finish_reason or "stop",
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": accumulated_content,
                                        "tool_calls": complete_native_tool_calls or None
                                    }
                                }
                            ],
                            "created": streaming_metadata.get("created"),
                            "model": streaming_metadata.get("model", llm_model),
                            "usage": streaming_metadata["usage"],  # Always include usage like LiteLLM does
                            "streaming": True,  # Add flag to indicate this was reconstructed from streaming
                        }
                        
                        # Only include response_ms if we have timing data
                        if streaming_metadata.get("response_ms"):
                            assistant_end_content["response_ms"] = streaming_metadata["response_ms"]
                        
                        await self.add_message(
                            thread_id=thread_id,
                            type="assistant_response_end",
                            content=assistant_end_content,
                            is_llm_message=False,
                            metadata={"thread_run_id": thread_run_id}
                        )
                        logger.info("Assistant response end saved for stream")
                    except Exception as e:
                        logger.error(f"Error saving assistant response end for stream: {str(e)}")
                        self.trace.event(name="error_saving_assistant_response_end_for_stream", level="ERROR", status_message=(f"Error saving assistant response end for stream: {str(e)}"))

        except Exception as e:
            logger.error(f"Error processing stream: {str(e)}", exc_info=True)
            self.trace.event(name="error_processing_stream", level="ERROR", status_message=(f"Error processing stream: {str(e)}"))
            # Save and yield error status message
            
            err_content = {"role": "system", "status_type": "error", "message": str(e)}
            if (not "AnthropicException - Overloaded" in str(e)):
                err_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=err_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id if 'thread_run_id' in locals() else None}
                )
                if err_msg_obj: yield format_for_yield(err_msg_obj) # Yield the saved error message
                # Re-raise the same exception (not a new one) to ensure proper error propagation
                logger.critical(f"Re-raising error to stop further processing: {str(e)}")
                self.trace.event(name="re_raising_error_to_stop_further_processing", level="ERROR", status_message=(f"Re-raising error to stop further processing: {str(e)}"))
            else:
                logger.error(f"AnthropicException - Overloaded detected - Falling back to OpenRouter: {str(e)}", exc_info=True)
                self.trace.event(name="anthropic_exception_overloaded_detected", level="ERROR", status_message=(f"AnthropicException - Overloaded detected - Falling back to OpenRouter: {str(e)}"))
            raise # Use bare 'raise' to preserve the original exception with its traceback

        finally:
            # Update continuous state for potential auto-continue
            if should_auto_continue:
                continuous_state['accumulated_content'] = accumulated_content
                continuous_state['sequence'] = __sequence
                
                logger.info(f"Updated continuous state for auto-continue with {len(accumulated_content)} chars")
            else:
                # Save and Yield the final thread_run_end status (only if not auto-continuing and finish_reason is not 'length')
                try:
                    end_content = {"status_type": "thread_run_end"}
                    end_msg_obj = await self.add_message(
                        thread_id=thread_id, type="status", content=end_content, 
                        is_llm_message=False, metadata={"thread_run_id": thread_run_id if 'thread_run_id' in locals() else None}
                    )
                    if end_msg_obj: yield format_for_yield(end_msg_obj)
                except Exception as final_e:
                    logger.error(f"Error in finally block: {str(final_e)}", exc_info=True)
                    self.trace.event(name="error_in_finally_block", level="ERROR", status_message=(f"Error in finally block: {str(final_e)}"))

    async def process_non_streaming_response(
        self,
        llm_response: Any,
        thread_id: str,
        prompt_messages: List[Dict[str, Any]],
        llm_model: str,
        config: ProcessorConfig = ProcessorConfig(),
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Process a non-streaming LLM response, handling tool calls and execution.
        
        Args:
            llm_response: Response from the LLM
            thread_id: ID of the conversation thread
            prompt_messages: List of messages sent to the LLM (the prompt)
            llm_model: The name of the LLM model used
            config: Configuration for parsing and execution
            
        Yields:
            Complete message objects matching the DB schema.
        """
        content = ""
        thread_run_id = str(uuid.uuid4())
        all_tool_data = [] # Stores {'tool_call': ..., 'parsing_details': ...}
        tool_index = 0
        assistant_message_object = None
        tool_result_message_objects = {}
        finish_reason = None
        native_tool_calls_for_message = []

        try:
            # Save and Yield thread_run_start status message
            start_content = {"status_type": "thread_run_start", "thread_run_id": thread_run_id}
            start_msg_obj = await self.add_message(
                thread_id=thread_id, type="status", content=start_content,
                is_llm_message=False, metadata={"thread_run_id": thread_run_id}
            )
            if start_msg_obj: yield format_for_yield(start_msg_obj)

            # Extract finish_reason, content, tool calls
            if hasattr(llm_response, 'choices') and llm_response.choices:
                 if hasattr(llm_response.choices[0], 'finish_reason'):
                     finish_reason = llm_response.choices[0].finish_reason
                     logger.info(f"Non-streaming finish_reason: {finish_reason}")
                     self.trace.event(name="non_streaming_finish_reason", level="DEFAULT", status_message=(f"Non-streaming finish_reason: {finish_reason}"))
                 response_message = llm_response.choices[0].message if hasattr(llm_response.choices[0], 'message') else None
                 if response_message:
                     if hasattr(response_message, 'content') and response_message.content:
                         content = response_message.content
                         if config.xml_tool_calling:
                             parsed_xml_data = self._parse_xml_tool_calls(content)
                             if config.max_xml_tool_calls > 0 and len(parsed_xml_data) > config.max_xml_tool_calls:
                                 # Truncate content and tool data if limit exceeded
                                 # ... (Truncation logic similar to streaming) ...
                                 if parsed_xml_data:
                                     xml_chunks = self._extract_xml_chunks(content)[:config.max_xml_tool_calls]
                                     if xml_chunks:
                                         last_chunk = xml_chunks[-1]
                                         last_chunk_pos = content.find(last_chunk)
                                         if last_chunk_pos >= 0: content = content[:last_chunk_pos + len(last_chunk)]
                                 parsed_xml_data = parsed_xml_data[:config.max_xml_tool_calls]
                                 finish_reason = "xml_tool_limit_reached"
                             all_tool_data.extend(parsed_xml_data)

                     if config.native_tool_calling and hasattr(response_message, 'tool_calls') and response_message.tool_calls:
                          for tool_call in response_message.tool_calls:
                             if hasattr(tool_call, 'function'):
                                 exec_tool_call = {
                                     "function_name": tool_call.function.name,
                                     "arguments": safe_json_parse(tool_call.function.arguments) if isinstance(tool_call.function.arguments, str) else tool_call.function.arguments,
                                     "id": tool_call.id if hasattr(tool_call, 'id') else str(uuid.uuid4())
                                 }
                                 all_tool_data.append({"tool_call": exec_tool_call, "parsing_details": None})
                                 native_tool_calls_for_message.append({
                                     "id": exec_tool_call["id"], "type": "function",
                                     "function": {
                                         "name": tool_call.function.name,
                                         "arguments": tool_call.function.arguments if isinstance(tool_call.function.arguments, str) else to_json_string(tool_call.function.arguments)
                                     }
                                 })


            # --- SAVE and YIELD Final Assistant Message ---
            message_data = {"role": "model", "parts": [{"text": content}]}
            assistant_message_object = await self._add_message_with_agent_info(
                thread_id=thread_id, type="assistant", content=message_data,
                is_llm_message=True, metadata={"thread_run_id": thread_run_id}
            )
            if assistant_message_object:
                 yield assistant_message_object
            else:
                 logger.error(f"Failed to save non-streaming assistant message for thread {thread_id}")
                 self.trace.event(name="failed_to_save_non_streaming_assistant_message_for_thread", level="ERROR", status_message=(f"Failed to save non-streaming assistant message for thread {thread_id}"))
                 err_content = {"role": "system", "status_type": "error", "message": "Failed to save assistant message"}
                 err_msg_obj = await self.add_message(
                     thread_id=thread_id, type="status", content=err_content, 
                     is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                 )
                 if err_msg_obj: yield format_for_yield(err_msg_obj)

       # --- Execute Tools and Yield Results ---
            tool_calls_to_execute = [item['tool_call'] for item in all_tool_data]
            if config.execute_tools and tool_calls_to_execute:
                logger.info(f"Executing {len(tool_calls_to_execute)} tools with strategy: {config.tool_execution_strategy}")
                self.trace.event(name="executing_tools_with_strategy", level="DEFAULT", status_message=(f"Executing {len(tool_calls_to_execute)} tools with strategy: {config.tool_execution_strategy}"))
                tool_results = await self._execute_tools(tool_calls_to_execute, config.tool_execution_strategy)

                for i, (returned_tool_call, result) in enumerate(tool_results):
                    original_data = all_tool_data[i]
                    tool_call_from_data = original_data['tool_call']
                    parsing_details = original_data['parsing_details']
                    current_assistant_id = assistant_message_object['message_id'] if assistant_message_object else None

                    context = self._create_tool_context(
                        tool_call_from_data, tool_index, current_assistant_id, parsing_details
                    )
                    context.result = result

                    # Save and Yield start status
                    started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                    if started_msg_obj: yield format_for_yield(started_msg_obj)

                    # Save tool result
                    saved_tool_result_object = await self._add_tool_result(
                        thread_id, tool_call_from_data, result, config.xml_adding_strategy,
                        current_assistant_id, parsing_details
                    )

                    # Save and Yield completed/failed status
                    completed_msg_obj = await self._yield_and_save_tool_completed(
                        context,
                        saved_tool_result_object['message_id'] if saved_tool_result_object else None,
                        thread_id, thread_run_id
                    )
                    if completed_msg_obj: yield format_for_yield(completed_msg_obj)

                    # Yield the saved tool result object
                    if saved_tool_result_object:
                        tool_result_message_objects[tool_index] = saved_tool_result_object
                        yield format_for_yield(saved_tool_result_object)
                    else:
                         logger.error(f"Failed to save tool result for index {tool_index}")
                         self.trace.event(name="failed_to_save_tool_result_for_index", level="ERROR", status_message=(f"Failed to save tool result for index {tool_index}"))

                    tool_index += 1

            # --- Save and Yield Final Status ---
            if finish_reason:
                finish_content = {"status_type": "finish", "finish_reason": finish_reason}
                finish_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=finish_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj: yield format_for_yield(finish_msg_obj)

            # --- Save and Yield assistant_response_end ---
            if assistant_message_object: # Only save if assistant message was saved
                try:
                    # Save the full LiteLLM response object directly in content
                    await self.add_message(
                        thread_id=thread_id,
                        type="assistant_response_end",
                        content=llm_response,
                        is_llm_message=False,
                        metadata={"thread_run_id": thread_run_id}
                    )
                    logger.info("Assistant response end saved for non-stream")
                except Exception as e:
                    logger.error(f"Error saving assistant response end for non-stream: {str(e)}")
                    self.trace.event(name="error_saving_assistant_response_end_for_non_stream", level="ERROR", status_message=(f"Error saving assistant response end for non-stream: {str(e)}"))

        except Exception as e:
             logger.error(f"Error processing non-streaming response: {str(e)}", exc_info=True)
             self.trace.event(name="error_processing_non_streaming_response", level="ERROR", status_message=(f"Error processing non-streaming response: {str(e)}"))
             # Save and yield error status
             err_content = {"role": "system", "status_type": "error", "message": str(e)}
             err_msg_obj = await self.add_message(
                 thread_id=thread_id, type="status", content=err_content, 
                 is_llm_message=False, metadata={"thread_run_id": thread_run_id if 'thread_run_id' in locals() else None}
             )
             if err_msg_obj: yield format_for_yield(err_msg_obj)
             
             # Re-raise the same exception (not a new one) to ensure proper error propagation
             logger.critical(f"Re-raising error to stop further processing: {str(e)}")
             self.trace.event(name="re_raising_error_to_stop_further_processing", level="CRITICAL", status_message=(f"Re-raising error to stop further processing: {str(e)}"))
             raise # Use bare 'raise' to preserve the original exception with its traceback

        finally:
             # Save and Yield the final thread_run_end status
            end_content = {"status_type": "thread_run_end"}
            end_msg_obj = await self.add_message(
                thread_id=thread_id, type="status", content=end_content, 
                is_llm_message=False, metadata={"thread_run_id": thread_run_id if 'thread_run_id' in locals() else None}
            )
            if end_msg_obj: yield format_for_yield(end_msg_obj)


    def _extract_xml_chunks(self, content: str) -> List[str]:
        """Extract complete XML chunks using start and end pattern matching."""
        chunks = []
        pos = 0
        
        try:
            # First, look for new format <function_calls> blocks
            start_pattern = '<function_calls>'
            end_pattern = '</function_calls>'
            
            while pos < len(content):
                # Find the next function_calls block
                start_pos = content.find(start_pattern, pos)
                if start_pos == -1:
                    break
                
                # Find the matching end tag
                end_pos = content.find(end_pattern, start_pos)
                if end_pos == -1:
                    break
                
                # Extract the complete block including tags
                chunk_end = end_pos + len(end_pattern)
                chunk = content[start_pos:chunk_end]
                chunks.append(chunk)
                
                # Move position past this chunk
                pos = chunk_end
            
            # If no new format found, fall back to old format for backwards compatibility
            if not chunks:
                pos = 0
                while pos < len(content):
                    # Find the next tool tag
                    next_tag_start = -1
                    current_tag = None
                    
                    # Find the earliest occurrence of any registered tool function name
                    # Check for available function names
                    available_functions = self.tool_registry.get_available_functions()
                    for func_name in available_functions.keys():
                        # Convert function name to potential tag name (underscore to dash)
                        tag_name = func_name.replace('_', '-')
                        start_pattern = f'<{tag_name}'
                        tag_pos = content.find(start_pattern, pos)
                        
                        if tag_pos != -1 and (next_tag_start == -1 or tag_pos < next_tag_start):
                            next_tag_start = tag_pos
                            current_tag = tag_name
                    
                    if next_tag_start == -1 or not current_tag:
                        break
                    
                    # Find the matching end tag
                    end_pattern = f'</{current_tag}>'
                    tag_stack = []
                    chunk_start = next_tag_start
                    current_pos = next_tag_start
                    
                    while current_pos < len(content):
                        # Look for next start or end tag of the same type
                        next_start = content.find(f'<{current_tag}', current_pos + 1)
                        next_end = content.find(end_pattern, current_pos)
                        
                        if next_end == -1:  # No closing tag found
                            break
                        
                        if next_start != -1 and next_start < next_end:
                            # Found nested start tag
                            tag_stack.append(next_start)
                            current_pos = next_start + 1
                        else:
                            # Found end tag
                            if not tag_stack:  # This is our matching end tag
                                chunk_end = next_end + len(end_pattern)
                                chunk = content[chunk_start:chunk_end]
                                chunks.append(chunk)
                                pos = chunk_end
                                break
                            else:
                                # Pop nested tag
                                tag_stack.pop()
                                current_pos = next_end + 1
                    
                    if current_pos >= len(content):  # Reached end without finding closing tag
                        break
                    
                    pos = max(pos + 1, current_pos)
        
        except Exception as e:
            logger.error(f"Error extracting XML chunks: {e}")
            logger.error(f"Content was: {content}")
            self.trace.event(name="error_extracting_xml_chunks", level="ERROR", status_message=(f"Error extracting XML chunks: {e}"), metadata={"content": content})
        
        return chunks

    def _parse_xml_tool_call(self, xml_chunk: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Parse XML chunk into tool call format and return parsing details.
        
        Returns:
            Tuple of (tool_call, parsing_details) or None if parsing fails.
            - tool_call: Dict with 'function_name', 'xml_tag_name', 'arguments'
            - parsing_details: Dict with 'attributes', 'elements', 'text_content', 'root_content'
        """
        try:
            # Check if this is the new format (contains <function_calls>)
            if '<function_calls>' in xml_chunk and '<invoke' in xml_chunk:
                # Use the new XML parser
                parsed_calls = self.xml_parser.parse_content(xml_chunk)
                
                if not parsed_calls:
                    logger.error(f"No tool calls found in XML chunk: {xml_chunk}")
                    return None
                
                # Take the first tool call (should only be one per chunk)
                xml_tool_call = parsed_calls[0]
                
                # Convert to the expected format
                tool_call = {
                    "function_name": xml_tool_call.function_name,
                    "xml_tag_name": xml_tool_call.function_name.replace('_', '-'),  # For backwards compatibility
                    "arguments": xml_tool_call.parameters
                }
                
                # Include the parsing details
                parsing_details = xml_tool_call.parsing_details
                parsing_details["raw_xml"] = xml_tool_call.raw_xml
                
                logger.debug(f"Parsed new format tool call: {tool_call}")
                return tool_call, parsing_details
            
            # If not the expected <function_calls><invoke> format, return None
            logger.error(f"XML chunk does not contain expected <function_calls><invoke> format: {xml_chunk}")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing XML chunk: {e}")
            logger.error(f"XML chunk was: {xml_chunk}")
            self.trace.event(name="error_parsing_xml_chunk", level="ERROR", status_message=(f"Error parsing XML chunk: {e}"), metadata={"xml_chunk": xml_chunk})
            return None

    def _parse_xml_tool_calls(self, content: str) -> List[Dict[str, Any]]:
        """Parse XML tool calls from content string.
        
        Returns:
            List of dictionaries, each containing {'tool_call': ..., 'parsing_details': ...}
        """
        parsed_data = []
        
        try:
            xml_chunks = self._extract_xml_chunks(content)
            
            for xml_chunk in xml_chunks:
                result = self._parse_xml_tool_call(xml_chunk)
                if result:
                    tool_call, parsing_details = result
                    parsed_data.append({
                        "tool_call": tool_call,
                        "parsing_details": parsing_details
                    })
                    
        except Exception as e:
            logger.error(f"Error parsing XML tool calls: {e}", exc_info=True)
            self.trace.event(name="error_parsing_xml_tool_calls", level="ERROR", status_message=(f"Error parsing XML tool calls: {e}"), metadata={"content": content})
        
        return parsed_data

    # Tool execution methods
    async def _execute_tool(self, tool_call: Dict[str, Any]) -> ToolResult:
        """Execute a single tool call and return the result."""
        span = self.trace.span(name=f"execute_tool.{tool_call['function_name']}", input=tool_call["arguments"])            
        try:
            function_name = tool_call["function_name"]
            arguments = tool_call["arguments"]

            logger.info(f"Executing tool: {function_name} with arguments: {arguments}")
            self.trace.event(name="executing_tool", level="DEFAULT", status_message=(f"Executing tool: {function_name} with arguments: {arguments}"))
            
            if isinstance(arguments, str):
                try:
                    arguments = safe_json_parse(arguments)
                except json.JSONDecodeError:
                    arguments = {"text": arguments}
            
            # Get available functions from tool registry
            available_functions = self.tool_registry.get_available_functions()
            
            # Look up the function by name
            tool_fn = available_functions.get(function_name)
            if not tool_fn:
                logger.error(f"Tool function '{function_name}' not found in registry")
                span.end(status_message="tool_not_found", level="ERROR")
                return ToolResult(success=False, output=f"Tool function '{function_name}' not found")
            
            logger.debug(f"Found tool function for '{function_name}', executing...")
            result = await tool_fn(**arguments)
            logger.info(f"Tool execution complete: {function_name} -> {result}")
            span.end(status_message="tool_executed", output=result)
            return result
        except Exception as e:
            logger.error(f"Error executing tool {tool_call['function_name']}: {str(e)}", exc_info=True)
            span.end(status_message="tool_execution_error", output=f"Error executing tool: {str(e)}", level="ERROR")
            return ToolResult(success=False, output=f"Error executing tool: {str(e)}")

    async def _execute_tools(
        self, 
        tool_calls: List[Dict[str, Any]], 
        execution_strategy: ToolExecutionStrategy = "sequential"
    ) -> List[Tuple[Dict[str, Any], ToolResult]]:
        """Execute tool calls with the specified strategy.
        
        This is the main entry point for tool execution. It dispatches to the appropriate
        execution method based on the provided strategy.
        
        Args:
            tool_calls: List of tool calls to execute
            execution_strategy: Strategy for executing tools:
                - "sequential": Execute tools one after another, waiting for each to complete
                - "parallel": Execute all tools simultaneously for better performance 
                
        Returns:
            List of tuples containing the original tool call and its result
        """
        logger.info(f"Executing {len(tool_calls)} tools with strategy: {execution_strategy}")
        self.trace.event(name="executing_tools_with_strategy", level="DEFAULT", status_message=(f"Executing {len(tool_calls)} tools with strategy: {execution_strategy}"))
            
        if execution_strategy == "sequential":
            return await self._execute_tools_sequentially(tool_calls)
        elif execution_strategy == "parallel":
            return await self._execute_tools_in_parallel(tool_calls)
        else:
            logger.warning(f"Unknown execution strategy: {execution_strategy}, falling back to sequential")
            return await self._execute_tools_sequentially(tool_calls)

    async def _execute_tools_sequentially(self, tool_calls: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], ToolResult]]:
        """Execute tool calls sequentially and return results.
        
        This method executes tool calls one after another, waiting for each tool to complete
        before starting the next one. This is useful when tools have dependencies on each other.
        
        Args:
            tool_calls: List of tool calls to execute
            
        Returns:
            List of tuples containing the original tool call and its result
        """
        if not tool_calls:
            return []
            
        try:
            tool_names = [t.get('function_name', 'unknown') for t in tool_calls]
            logger.info(f"Executing {len(tool_calls)} tools sequentially: {tool_names}")
            self.trace.event(name="executing_tools_sequentially", level="DEFAULT", status_message=(f"Executing {len(tool_calls)} tools sequentially: {tool_names}"))
            
            results = []
            for index, tool_call in enumerate(tool_calls):
                tool_name = tool_call.get('function_name', 'unknown')
                logger.debug(f"Executing tool {index+1}/{len(tool_calls)}: {tool_name}")
                
                try:
                    result = await self._execute_tool(tool_call)
                    results.append((tool_call, result))
                    logger.debug(f"Completed tool {tool_name} with success={result.success}")
                    
                    # Check if this is a terminating tool (ask or complete)
                    if tool_name in ['ask', 'complete']:
                        logger.info(f"Terminating tool '{tool_name}' executed. Stopping further tool execution.")
                        self.trace.event(name="terminating_tool_executed", level="DEFAULT", status_message=(f"Terminating tool '{tool_name}' executed. Stopping further tool execution."))
                        break  # Stop executing remaining tools
                        
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {str(e)}")
                    self.trace.event(name="error_executing_tool", level="ERROR", status_message=(f"Error executing tool {tool_name}: {str(e)}"))
                    error_result = ToolResult(success=False, output=f"Error executing tool: {str(e)}")
                    results.append((tool_call, error_result))
            
            logger.info(f"Sequential execution completed for {len(results)} tools (out of {len(tool_calls)} total)")
            self.trace.event(name="sequential_execution_completed", level="DEFAULT", status_message=(f"Sequential execution completed for {len(results)} tools (out of {len(tool_calls)} total)"))
            return results
            
        except Exception as e:
            logger.error(f"Error in sequential tool execution: {str(e)}", exc_info=True)
            # Return partial results plus error results for remaining tools
            completed_results = results if 'results' in locals() else []
            completed_tool_names = [r[0].get('function_name', 'unknown') for r in completed_results]
            remaining_tools = [t for t in tool_calls if t.get('function_name', 'unknown') not in completed_tool_names]
            
            # Add error results for remaining tools
            error_results = [(tool, ToolResult(success=False, output=f"Execution error: {str(e)}")) 
                            for tool in remaining_tools]
                            
            return completed_results + error_results

    async def _execute_tools_in_parallel(self, tool_calls: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], ToolResult]]:
        """Execute tool calls in parallel and return results.
        
        This method executes all tool calls simultaneously using asyncio.gather, which
        can significantly improve performance when executing multiple independent tools.
        
        Args:
            tool_calls: List of tool calls to execute
            
        Returns:
            List of tuples containing the original tool call and its result
        """
        if not tool_calls:
            return []
            
        try:
            tool_names = [t.get('function_name', 'unknown') for t in tool_calls]
            logger.info(f"Executing {len(tool_calls)} tools in parallel: {tool_names}")
            self.trace.event(name="executing_tools_in_parallel", level="DEFAULT", status_message=(f"Executing {len(tool_calls)} tools in parallel: {tool_names}"))
            
            # Create tasks for all tool calls
            tasks = [self._execute_tool(tool_call) for tool_call in tool_calls]
            
            # Execute all tasks concurrently with error handling
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle any exceptions
            processed_results = []
            for i, (tool_call, result) in enumerate(zip(tool_calls, results)):
                if isinstance(result, Exception):
                    logger.error(f"Error executing tool {tool_call.get('function_name', 'unknown')}: {str(result)}")
                    self.trace.event(name="error_executing_tool", level="ERROR", status_message=(f"Error executing tool {tool_call.get('function_name', 'unknown')}: {str(result)}"))
                    # Create error result
                    error_result = ToolResult(success=False, output=f"Error executing tool: {str(result)}")
                    processed_results.append((tool_call, error_result))
                else:
                    processed_results.append((tool_call, result))
            
            logger.info(f"Parallel execution completed for {len(tool_calls)} tools")
            self.trace.event(name="parallel_execution_completed", level="DEFAULT", status_message=(f"Parallel execution completed for {len(tool_calls)} tools"))
            return processed_results
        
        except Exception as e:
            logger.error(f"Error in parallel tool execution: {str(e)}", exc_info=True)
            self.trace.event(name="error_in_parallel_tool_execution", level="ERROR", status_message=(f"Error in parallel tool execution: {str(e)}"))
            # Return error results for all tools if the gather itself fails
            return [(tool_call, ToolResult(success=False, output=f"Execution error: {str(e)}")) 
                    for tool_call in tool_calls]

    async def _add_tool_result(
        self, 
        thread_id: str, 
        tool_call: Dict[str, Any], 
        result: ToolResult,
        strategy: Union[XmlAddingStrategy, str] = "assistant_message",
        assistant_message_id: Optional[str] = None,
        parsing_details: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]: # Return the full message object
        """Add a tool result to the conversation thread based on the specified format.
        
        This method formats tool results and adds them to the conversation history,
        making them visible to the LLM in subsequent interactions. Results can be 
        added either as native tool messages (OpenAI format) or as XML-wrapped content
        with a specified role (user or assistant).
        
        Args:
            thread_id: ID of the conversation thread
            tool_call: The original tool call that produced this result
            result: The result from the tool execution
            strategy: How to add XML tool results to the conversation
                     ("user_message", "assistant_message", or "inline_edit")
            assistant_message_id: ID of the assistant message that generated this tool call
            parsing_details: Detailed parsing info for XML calls (attributes, elements, etc.)
        """
        try:
            message_obj = None # Initialize message_obj
            
            # Create metadata with assistant_message_id if provided
            metadata = {}
            if assistant_message_id:
                metadata["assistant_message_id"] = assistant_message_id
                logger.info(f"Linking tool result to assistant message: {assistant_message_id}")
                self.trace.event(name="linking_tool_result_to_assistant_message", level="DEFAULT", status_message=(f"Linking tool result to assistant message: {assistant_message_id}"))
            
            # --- Add parsing details to metadata if available ---
            if parsing_details:
                metadata["parsing_details"] = parsing_details
                logger.info("Adding parsing_details to tool result metadata")
                self.trace.event(name="adding_parsing_details_to_tool_result_metadata", level="DEFAULT", status_message=(f"Adding parsing_details to tool result metadata"), metadata={"parsing_details": parsing_details})
            # ---
            
            # Check if this is a native function call (has id field)
            if "id" in tool_call:
                # Format as a proper tool message according to OpenAI spec
                function_name = tool_call.get("function_name", "")
                
                # Format the tool result content - tool role needs string content
                if isinstance(result, str):
                    content = result
                elif hasattr(result, 'output'):
                    # If it's a ToolResult object
                    if isinstance(result.output, dict) or isinstance(result.output, list):
                        # If output is already a dict or list, convert to JSON string
                        content = json.dumps(result.output)
                    else:
                        # Otherwise just use the string representation
                        content = str(result.output)
                else:
                    # Fallback to string representation of the whole result
                    content = str(result)
                
                logger.info(f"Formatted tool result content: {content[:100]}...")
                self.trace.event(name="formatted_tool_result_content", level="DEFAULT", status_message=(f"Formatted tool result content: {content[:100]}..."))
                
                # Create the tool response message with proper format
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": function_name,
                    "content": content
                }
                
                logger.info(f"Adding native tool result for tool_call_id={tool_call['id']} with role=tool")
                self.trace.event(name="adding_native_tool_result_for_tool_call_id", level="DEFAULT", status_message=(f"Adding native tool result for tool_call_id={tool_call['id']} with role=tool"))
                
                # Add as a tool message to the conversation history
                # This makes the result visible to the LLM in the next turn
                message_obj = await self.add_message(
                    thread_id=thread_id,
                    type="tool",  # Special type for tool responses
                    content=tool_message,
                    is_llm_message=True,
                    metadata=metadata
                )
                return message_obj # Return the full message object
            
            # For XML and other non-native tools, use the new structured format
            # Determine message role based on strategy
            result_role = "user" if strategy == "user_message" else "assistant"
            
            # Create two versions of the structured result
            # 1. Rich version for the frontend
            structured_result_for_frontend = self._create_structured_tool_result(tool_call, result, parsing_details, for_llm=False)
            # 2. Concise version for the LLM
            structured_result_for_llm = self._create_structured_tool_result(tool_call, result, parsing_details, for_llm=True)

            # Add the message with the appropriate role to the conversation history
            # This allows the LLM to see the tool result in subsequent interactions
            result_message_for_llm = {
                "role": result_role,
                "content":  json.dumps(structured_result_for_llm)
            }
            
            # Add rich content to metadata for frontend use
            if metadata is None:
                metadata = {}
            metadata['frontend_content'] = structured_result_for_frontend

            message_obj = await self._add_message_with_agent_info(
                thread_id=thread_id, 
                type="tool",
                content=result_message_for_llm, # Save the LLM-friendly version
                is_llm_message=True,
                metadata=metadata
            )

            # If the message was saved, modify it in-memory for the frontend before returning
            if message_obj:
                # The frontend expects the rich content in the 'content' field.
                # The DB has the rich content in metadata.frontend_content.
                # Let's reconstruct the message for yielding.
                message_for_yield = message_obj.copy()
                message_for_yield['content'] = structured_result_for_frontend
                return message_for_yield

            return message_obj # Return the modified message object
        except Exception as e:
            logger.error(f"Error adding tool result: {str(e)}", exc_info=True)
            self.trace.event(name="error_adding_tool_result", level="ERROR", status_message=(f"Error adding tool result: {str(e)}"), metadata={"tool_call": tool_call, "result": result, "strategy": strategy, "assistant_message_id": assistant_message_id, "parsing_details": parsing_details})
            # Fallback to a simple message
            try:
                fallback_message = {
                    "role": "user",
                    "content": str(result)
                }
                message_obj = await self.add_message(
                    thread_id=thread_id, 
                    type="tool", 
                    content=fallback_message,
                    is_llm_message=True,
                    metadata={"assistant_message_id": assistant_message_id} if assistant_message_id else {}
                )
                return message_obj # Return the full message object
            except Exception as e2:
                logger.error(f"Failed even with fallback message: {str(e2)}", exc_info=True)
                self.trace.event(name="failed_even_with_fallback_message", level="ERROR", status_message=(f"Failed even with fallback message: {str(e2)}"), metadata={"tool_call": tool_call, "result": result, "strategy": strategy, "assistant_message_id": assistant_message_id, "parsing_details": parsing_details})
                return None # Return None on error

    def _create_structured_tool_result(self, tool_call: Dict[str, Any], result: ToolResult, parsing_details: Optional[Dict[str, Any]] = None, for_llm: bool = False):
        """Create a structured tool result format that's tool-agnostic and provides rich information.
        
        Args:
            tool_call: The original tool call that was executed
            result: The result from the tool execution
            parsing_details: Optional parsing details for XML calls
            for_llm: If True, creates a concise version for the LLM context.
            
        Returns:
            Structured dictionary containing tool execution information
        """
        # Extract tool information
        function_name = tool_call.get("function_name", "unknown")
        xml_tag_name = tool_call.get("xml_tag_name")
        arguments = tool_call.get("arguments", {})
        tool_call_id = tool_call.get("id")
        
        # Process the output - if it's a JSON string, parse it back to an object
        output = result.output if hasattr(result, 'output') else str(result)
        if isinstance(output, str):
            try:
                # Try to parse as JSON to provide structured data to frontend
                parsed_output = safe_json_parse(output)
                # If parsing succeeded and we got a dict/list, use the parsed version
                if isinstance(parsed_output, (dict, list)):
                    output = parsed_output
                # Otherwise keep the original string
            except Exception:
                # If parsing fails, keep the original string
                pass

        output_to_use = output
        # If this is for the LLM and it's an edit_file tool, create a concise output
        if for_llm and function_name == 'edit_file' and isinstance(output, dict):
            # The frontend needs original_content and updated_content to render diffs.
            # The concise version for the LLM was causing issues.
            # We will now pass the full output, and rely on the ContextManager to truncate if needed.
            output_to_use = output

        # Create the structured result
        structured_result_v1 = {
            "tool_execution": {
                "function_name": function_name,
                "xml_tag_name": xml_tag_name,
                "tool_call_id": tool_call_id,
                "arguments": arguments,
                "result": {
                    "success": result.success if hasattr(result, 'success') else True,
                    "output": output_to_use,  # This will be either rich or concise based on `for_llm`
                    "error": getattr(result, 'error', None) if hasattr(result, 'error') else None
                },
            }
        } 
            
        return structured_result_v1

    def _create_tool_context(self, tool_call: Dict[str, Any], tool_index: int, assistant_message_id: Optional[str] = None, parsing_details: Optional[Dict[str, Any]] = None) -> ToolExecutionContext:
        """Create a tool execution context with display name and parsing details populated."""
        context = ToolExecutionContext(
            tool_call=tool_call,
            tool_index=tool_index,
            assistant_message_id=assistant_message_id,
            parsing_details=parsing_details
        )
        
        # Set function_name and xml_tag_name fields
        if "xml_tag_name" in tool_call:
            context.xml_tag_name = tool_call["xml_tag_name"]
            context.function_name = tool_call.get("function_name", tool_call["xml_tag_name"])
        else:
            # For non-XML tools, use function name directly
            context.function_name = tool_call.get("function_name", "unknown")
            context.xml_tag_name = None
        
        return context
        
    async def _yield_and_save_tool_started(self, context: ToolExecutionContext, thread_id: str, thread_run_id: str) -> Optional[Dict[str, Any]]:
        """Formats, saves, and returns a tool started status message."""
        tool_name = context.xml_tag_name or context.function_name
        content = {
            "role": "assistant", "status_type": "tool_started",
            "function_name": context.function_name, "xml_tag_name": context.xml_tag_name,
            "message": f"Starting execution of {tool_name}", "tool_index": context.tool_index,
            "tool_call_id": context.tool_call.get("id") # Include tool_call ID if native
        }
        metadata = {"thread_run_id": thread_run_id}
        saved_message_obj = await self.add_message(
            thread_id=thread_id, type="status", content=content, is_llm_message=False, metadata=metadata
        )
        return saved_message_obj # Return the full object (or None if saving failed)

    async def _yield_and_save_tool_completed(self, context: ToolExecutionContext, tool_message_id: Optional[str], thread_id: str, thread_run_id: str) -> Optional[Dict[str, Any]]:
        """Formats, saves, and returns a tool completed/failed status message."""
        if not context.result:
            # Delegate to error saving if result is missing (e.g., execution failed)
            return await self._yield_and_save_tool_error(context, thread_id, thread_run_id)

        tool_name = context.xml_tag_name or context.function_name
        status_type = "tool_completed" if context.result.success else "tool_failed"
        message_text = f"Tool {tool_name} {'completed successfully' if context.result.success else 'failed'}"

        content = {
            "role": "assistant", "status_type": status_type,
            "function_name": context.function_name, "xml_tag_name": context.xml_tag_name,
            "message": message_text, "tool_index": context.tool_index,
            "tool_call_id": context.tool_call.get("id")
        }
        metadata = {"thread_run_id": thread_run_id}
        # Add the *actual* tool result message ID to the metadata if available and successful
        if context.result.success and tool_message_id:
            metadata["linked_tool_result_message_id"] = tool_message_id
            
        # <<< ADDED: Signal if this is a terminating tool >>>
        if context.function_name in ['ask', 'complete']:
            metadata["agent_should_terminate"] = "true"
            logger.info(f"Marking tool status for '{context.function_name}' with termination signal.")
            self.trace.event(name="marking_tool_status_for_termination", level="DEFAULT", status_message=(f"Marking tool status for '{context.function_name}' with termination signal."))
        # <<< END ADDED >>>

        saved_message_obj = await self.add_message(
            thread_id=thread_id, type="status", content=content, is_llm_message=False, metadata=metadata
        )
        return saved_message_obj

    async def _yield_and_save_tool_error(self, context: ToolExecutionContext, thread_id: str, thread_run_id: str) -> Optional[Dict[str, Any]]:
        """Formats, saves, and returns a tool error status message."""
        error_msg = str(context.error) if context.error else "Unknown error during tool execution"
        tool_name = context.xml_tag_name or context.function_name
        content = {
            "role": "assistant", "status_type": "tool_error",
            "function_name": context.function_name, "xml_tag_name": context.xml_tag_name,
            "message": f"Error executing tool {tool_name}: {error_msg}",
            "tool_index": context.tool_index,
            "tool_call_id": context.tool_call.get("id")
        }
        metadata = {"thread_run_id": thread_run_id}
        # Save the status message with is_llm_message=False
        saved_message_obj = await self.add_message(
            thread_id=thread_id, type="status", content=content, is_llm_message=False, metadata=metadata
        )
        return saved_message_obj
