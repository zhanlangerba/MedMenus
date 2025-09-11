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
    native_tool_calling: bool = True

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


        def _now_ts():
            """获取当前时间戳"""
            return datetime.now(timezone.utc).timestamp()

        def _safe_text(x) -> str:
            """确保文本是字符串"""
            if isinstance(x, str):
                return x
            if isinstance(x, (list, tuple)):
                return "".join(str(t) for t in x)
            return str(x)

        def _event_is_final(e) -> bool:
            """判断事件是否为最终事件"""
            try:
                # ADK 提供的最终响应判定
                return bool(getattr(e, "is_final_response", None) and e.is_final_response())
            except Exception:
                # 回退逻辑：partial==False 且有 usage_metadata 时大概率为最终
                return bool(getattr(e, "partial", None) is False and getattr(e, "usage_metadata", None) is not None)
        
        def _derive_chunk_status() -> str:
            """ADK Event状态识别，不涉及流程控制"""
            
            error_code = getattr(event, "error_code", None)
            partial = getattr(event, "partial", None)
            turn_complete = getattr(event, "turn_complete", None)
            is_final = _event_is_final(event)
            actions = getattr(event, "actions", None)
            long_run_tools = list(getattr(event, "long_running_tool_ids", []) or [])
            content = getattr(event, "content", None)

            
            # 错误状态检测
            if error_code:
                error_str = str(error_code).upper()
                if error_str in {"MAX_TOKENS", "TOKEN_LIMIT", "LENGTH"}:
                    return "error_length_limit"
                elif error_str in {"SAFETY", "CONTENT_FILTER"}:
                    return "error_safety" 
                elif error_str in {"RECITATION"}:
                    return "error_recitation"
                else:
                    return "error"
            
            # 长运行工具状态
            if long_run_tools:
                return "long_running_tool"
            
            # 移交/升级状态  
            if actions:
                if getattr(actions, "transfer_to_agent", None):
                    return "transfer_to_agent"
                if getattr(actions, "escalate", None):
                    return "escalate"
            
            # 内容分析 - ADK核心逻辑
            if content and hasattr(content, 'parts') and content.parts:
                content_types = []
                
                for part in content.parts:
                    if hasattr(part, 'function_call') and getattr(part, 'function_call', None):
                        content_types.append('function_call')
                    if hasattr(part, 'function_response') and getattr(part, 'function_response', None):
                        content_types.append('function_response')
                    if hasattr(part, 'text') and getattr(part, 'text', None):
                        content_types.append('text')
                    if hasattr(part, 'code_execution_result') and getattr(part, 'code_execution_result', None):
                        content_types.append('code_execution')
                
                # 根据内容类型组合返回状态
                if 'code_execution' in content_types:
                    return "code_execution_result"
                elif 'function_call' in content_types and 'function_response' in content_types:
                    return "tool_call_and_response"
                elif 'function_call' in content_types:
                    return "tool_call"  
                elif 'function_response' in content_types:
                    return "tool_response"
                elif 'text' in content_types:
                    # 文本内容 - 根据partial状态细分
                    if partial is True:
                        return "text_streaming"
                    elif partial is False:
                        if is_final:
                            return "text_final"
                        else:
                            return "text_complete"  # 完整文本块，但不是最终
                    else:
                        return "text"
            
            # 基于ADK状态标志的最终判断（兜底）
            if is_final:
                return "final"
            elif partial is True:
                return "streaming_delta" 
            elif partial is False:
                return "complete_non_final"
            elif turn_complete is True:
                return "turn_complete"
            else:
                return "unknown"


        # 运行状态初始化 
        continuous_state = continuous_state or {}   # 保存跨轮次的状态信息
        accumulated_content = continuous_state.get('accumulated_content', "") # 累积的内容，在下一轮中作为上下文
        # 确保 accumulated_content 始终是字符串
        if not isinstance(accumulated_content, str):
            accumulated_content = str(accumulated_content)
        tool_calls_buffer = {} # 工具调用缓冲区
        current_xml_content = accumulated_content   # 累积内容如果自动继续，否则为空
        # 🔧 确保 current_xml_content 也是字符串类型
        if not isinstance(current_xml_content, str):
            logger.warning(f"⚠️ current_xml_content 初始化类型异常: {type(current_xml_content)}, 重置为空字符串")
            current_xml_content = ""
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
        tool_completed_buffer = [] # 收集工具完成状态，延迟到后处理阶段统一yield
        processed_tool_call_ids = set() # ADK: 跟踪已处理的工具调用ID，避免重复处理
        
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

        # xml_tool_calling (默认: True)，允许大模型通过XML格式调用工具。格式如 <tool>...</tool>, 
        # native_tool_calling (默认: False)：启用OpenAI原生格式的函数调用。格式如 {"name": "function_name", "args": {"arg1": "value1", "arg2": "value2"}}
        # execute_on_stream (默认: False)：是否在流式响应中执行工具调用
        # tool_execution_strategy (默认: "sequential")：工具调用执行策略，"sequential" 或 "parallel"
        logger.info(f"Streaming Config: XML={config.xml_tool_calling}, Native={config.native_tool_calling}, "
            f"Execute on stream={config.execute_on_stream}, Strategy={config.tool_execution_strategy}")

        # 重用 / 创建 thread_run_id：保持相同的运行ID
        thread_run_id = continuous_state.get('thread_run_id') or str(uuid.uuid4())
        continuous_state['thread_run_id'] = thread_run_id
        
        logger.info(f"Processing ADK streaming response with thread_run_id: {thread_run_id}")


        try:
            # 控制 AI Agent 自动继续对话的次数。从 0 开始，每次自动继续时递增 1
            # 处理两种情况，1. finsh_reason=tool_calls（发生工具调用后自动对话） 2. finsh_reason=length（Agent 因长度限制被截断后，自动继续补充完整回答）
            # 在ADK 中，则是：get_function_calls() / get_function_responses() event.is_final_response()
            """
            用户: "帮我搜索最新的科技新闻并分析趋势"
            LLM: "我来帮你搜索最新科技新闻..." [finish_reason: tool_calls]
            系统: 自动继续，执行工具调用
            LLM: "根据搜索结果，当前主要趋势包括..." [finish_reason: stop]
            """

            # -- 初始化对话状态开始 --
            if auto_continue_count == 0:  
                start_content = {"status_type": "thread_run_start", "thread_run_id": thread_run_id}
                # 存储 thread_run_start 状态消息到 messages 表中
                start_msg_obj = await self.add_message(
                    thread_id=thread_id, 
                    type="status", 
                    content=start_content,
                    is_llm_message=False, 
                    metadata={"thread_run_id": thread_run_id}
                )

                logger.info(f"start_msg_obj: {start_msg_obj}")

                # 发送 thread_run_start 状态消息到上层流式响应
                if start_msg_obj:
                    yield format_for_yield(start_msg_obj)

                assist_start_content = {"status_type": "assistant_response_start"}
                # 存储 assistant_response_start 状态消息到 messages 表中
                assist_start_msg_obj = await self.add_message(
                    thread_id=thread_id, 
                    type="status", 
                    content=assist_start_content,
                    is_llm_message=False, 
                    metadata={"thread_run_id": thread_run_id}
                )

                # 发送 assistant_response_start 状态消息到上层流式响应
                if assist_start_msg_obj:
                    yield format_for_yield(assist_start_msg_obj)

            # -- 初始化对话状态结束 --
            
            # 序列号计数器，用于为每个yield的消息块分配唯一的、连续的序号
            """
            支持auto-continue的连续性
            场景1：正常流式响应
            sequence: 0  -> "你好"
            sequence: 1  -> "，我是"
            sequence: 2  -> "AI助手"
            sequence: 3  -> "。"

            场景2：当工具调用/长度限制等问题，可以自动继续对话
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
                # 如果first_chunk_time为空，则设置为当前时间
                if streaming_metadata["first_chunk_time"] is None:
                    streaming_metadata["first_chunk_time"] = _now_ts()  # 获取当前时间戳
                # 更新最后的时间戳
                streaming_metadata["last_chunk_time"] = _now_ts()  # 获取当前时间戳

                # 从ADK事件中提取created时间
                if getattr(event, "timestamp", None):
                    streaming_metadata["created"] = event.timestamp
                
                # 添加模型信息
                streaming_metadata["model"] = llm_model

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
                
                # event.finish_reason = None  # 直接的finish_reason属性
                # event.partial = True/False  # 是否为部分响应
                # event.turn_complete = None  # 轮次是否完成  

                try:
                    chunk_status = _derive_chunk_status()
                    logger.info(f"current chunk status: {chunk_status}")
                except Exception as e:
                    logger.error(f"adk event status derive error: {e}")

                
                # 过滤ADK的最终完整chunk，避免重复（因为流式输出中最后一条会包含所有文本chunk内容）
                content = getattr(event, "content", None)
                if (getattr(event, "partial", None) is False and 
                    content and 
                    getattr(content, "parts", None) and
                    chunk_status in ["final", "text_final"]):
                    logger.info(f"Skipping final complete ADK chunk to avoid duplication")
                    continue

                
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

                    # 首先处理普通文本
                    if parts:            
                        for delta in parts:
                            # 处理 chunk 是纯文本的情况
                            if hasattr(delta, 'text') and delta.text:
                                # 获取增量更新的文本内容
                                chunk_content = delta.text
                                
                                # 确保 chunk_content 是字符串类型，防止类型错误
                                if isinstance(chunk_content, list):
                                    chunk_content = ''.join(str(item) for item in chunk_content)
                                elif not isinstance(chunk_content, str):
                                    chunk_content = str(chunk_content)

                                # 🔧 双重保险：再次确认类型安全
                                if not isinstance(chunk_content, str):
                                    logger.warning(f"⚠️ chunk_content 类型异常: {type(chunk_content)}, 值: {chunk_content}")
                                    chunk_content = str(chunk_content)
                                
                                if not isinstance(accumulated_content, str):
                                    logger.warning(f"⚠️ accumulated_content 类型异常: {type(accumulated_content)}, 重置为空字符串")
                                    accumulated_content = ""
                                    
                                if not isinstance(current_xml_content, str):
                                    logger.warning(f"⚠️ current_xml_content 类型异常: {type(current_xml_content)}, 重置为空字符串")
                                    current_xml_content = ""

                                # 更新累积内容和XML内容
                                accumulated_content += chunk_content
                                current_xml_content += chunk_content  # 用于XML工具调用检测
    

                                logger.info(f"accumulated_content: {accumulated_content}")
                                logger.info(f"current_xml_content: {current_xml_content}")  

                                # 防止模型无限循环调用工具，如果 没有达到工具调用上限，则继续输出内容
                                # config.max_xml_tool_calls:最多允许1次XML工具调用
                                # xml_tool_call_count:当前已执行XML工具调用
                                if not (config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls):
                                    logger.info(f"config.max_xml_tool_calls: {config.max_xml_tool_calls}")
                                    logger.info(f"xml_tool_call_count: {xml_tool_call_count}")
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
                                
                                # --- 处理 XML 的工具调用  (如果启用了XML工具调用 并且 还没达到调用次数上限) ---
                                if config.xml_tool_calling and not (config.max_xml_tool_calls > 0 and xml_tool_call_count >= config.max_xml_tool_calls):
                                    # 提取XML工具调用
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
                            # 处理 chunk 是工具调用的情况 
                            # if config.native_tool_calling and getattr(delta, "function_call", None):
                            if content and hasattr(content, 'parts') and content.parts:
                                # 这里要处理多工具并行调用的情况
                                function_call_parts = [p for p in content.parts if hasattr(p, 'function_call') and p.function_call]
                                function_response_parts = [p for p in content.parts if hasattr(p, 'function_response') and p.function_response]
                                
                                # 处理工具调用
                                if function_call_parts:     
                                    for index, part in enumerate(function_call_parts):
                                        call = part.function_call
                                        
                                        # ADK去重检查：避免重复处理同一个工具调用
                                        tool_call_id = getattr(call, 'id', None)
                                        if tool_call_id in processed_tool_call_ids:
                                            logger.info(f"🔄 Skipping duplicate ADK function_call: tool_call_id={tool_call_id}")
                                            continue
                                        
                                        processed_tool_call_ids.add(tool_call_id)
                                        logger.info(f"🆕 Processing new ADK function_call: tool_call_id={tool_call_id}, tool_index={tool_index}")
                                        # 定义基本数据结构
                                        tool_call_data_chunk = {}
                                        
                                        # 构建工具调用的数据结构
                                        if hasattr(call, 'model_dump'):
                                            raw_data = call.model_dump()
                                            tool_call_data_chunk = {
                                                'id': raw_data.get('id', ''),
                                                'index': index, 
                                                'type': 'function',
                                                'function': {
                                                    'name': raw_data.get('name', ''),
                                                    'arguments': to_json_string(raw_data.get('args', {}))
                                                }
                                            }
                                            logger.info(f"use model_dump() to generate tool_call_data_chunk: {tool_call_data_chunk}")
                                        else:
                                            # 手动构建OpenAI兼容格式
                                            tool_call_data_chunk = {
                                                'id': call.id,
                                                'index': index,  
                                                'type': 'function',
                                                'function': {
                                                    'name': call.name,
                                                    'arguments': to_json_string(call.args)
                                                }
                                            }
                                            logger.info(f"use manual build tool_call_data_chunk: {tool_call_data_chunk}")
                                        

                                        now_tool_chunk = datetime.now(timezone.utc).isoformat()
                                        
                                        # 发送工具调用状态消息，中间状态，无需保存至数据库
                                        yield {
                                            "message_id": None, "thread_id": thread_id, "type": "status", "is_llm_message": True,
                                            "content": to_json_string({"role": "assistant", "status_type": "tool_call_chunk", "tool_call_chunk": tool_call_data_chunk}),
                                            "metadata": to_json_string({"thread_run_id": thread_run_id}),
                                            "created_at": now_tool_chunk, "updated_at": now_tool_chunk
                                        }


                                        # 创建工具和消息之间的关联，用来告诉前端工具调用是属于哪一条消息的
                                        # 什么时候会是 None？
                                        # 1.流式响应刚开始，还没有保存任何AI消息
                                        # 2.工具调用发生在消息保存之前
                                        # 3.出现异常情况，消息对象丢失
                                        current_assistant_id = last_assistant_message_object['message_id'] if last_assistant_message_object else None
                                       
                                        # 从 tool_call_data_chunk 提取 tool_call_data
                                        tool_call_data = {
                                            "function_name": tool_call_data_chunk['function']['name'],
                                            "arguments": safe_json_parse(tool_call_data_chunk['function']['arguments']),
                                            "id": tool_call_data_chunk['id']
                                        }
                                        logger.info(f"extract tool_call_data: {tool_call_data}")
                                        # 这里继续处理 tool_call_data...

                                        # 创建工具执行上下文
                                        context = self._create_tool_context(
                                            tool_call_data, tool_index, current_assistant_id
                                        )

                                        logger.info(f"current_tool_context: {context}")

                                        # 发送工具开始状态消息，并存储至数据库中
                                        started_msg_obj = await self._yield_and_save_tool_started(context, thread_id, thread_run_id)
                                        if started_msg_obj:
                                            logger.info(f"yield tool_started status: {started_msg_obj}")
                                            yield format_for_yield(started_msg_obj)
                                        
                                        # 检查是否已经存在相同的工具调用（基于tool_call_id去重）
                                        tool_call_id = tool_call_data["id"]
                                        existing_execution = None
                                        for execution in pending_tool_executions:
                                            if execution["tool_call"]["id"] == tool_call_id:
                                                existing_execution = execution
                                                break
                                        
                                        if existing_execution:
                                            logger.info(f"🔄 Skipping duplicate ADK tool call: tool_call_id={tool_call_id}, existing_tool_index={existing_execution['tool_index']}")
                                            # 重复的工具调用，跳过处理但确保yielded_tool_indices正确
                                            yielded_tool_indices.add(existing_execution["tool_index"])
                                            continue
                                        
                                        logger.info(f"🆕 Processing new ADK tool call: tool_call_id={tool_call_id}, tool_index={tool_index}")
                                        yielded_tool_indices.add(tool_index) # 标记工具索引已yield

                                        # 添加工具调用任务到pending_tool_executions 列表中
                                        pending_tool_executions.append({
                                            "tool_call": tool_call_data,
                                            "tool_index": tool_index, 
                                            "context": context
                                        })
                                        tool_index += 1  # 只有在成功添加新工具时才递增
                                        logger.info(f"pending_tool_executions: {pending_tool_executions}")

                                
                                # 处理工具响应
                                elif function_response_parts:                 
                                    for part in function_response_parts:
                                        # 提取工具调用结果
                                        func_response = part.function_response
                                        # 从pending_tool_executions列表中找到对应的工具调用
                                        matching_execution = None
                                        for execution in pending_tool_executions:
                                            if execution["tool_call"]["id"] == func_response.id:
                                                context = execution["context"]
                                                matching_execution = execution
                                                break
                                                                                                                   
                                        raw_response = func_response.response
                                        
                                        # 构建标准ToolResult格式
                                        if isinstance(raw_response, dict) and 'message' in raw_response:
                                            # ADK格式适配：将message映射为output
                                            from types import SimpleNamespace
                                            adapted_result = SimpleNamespace(
                                                success=raw_response.get('success', True),
                                                output=raw_response.get('message', str(raw_response))
                                            )
                                            logger.info(f"tool result adapted: success={adapted_result.success}, output='{adapted_result.output}'")
                                        else:
                                            # 其他格式保持原样
                                            adapted_result = raw_response
                                            logger.info(f"tool result keep original format")
                                        
                                        # 更新context的result
                                        context.result = adapted_result
                                        logger.info(f"tool call context completed: {context}")
                                   
                                        # 将工具完成状态收集到缓冲区，延迟到后处理阶段统一yield
                                        # 去重检查：避免同一个工具响应被重复添加
                                        tool_call_id = func_response.id
                                        if not any(item["tool_call_id"] == tool_call_id for item in tool_completed_buffer):
                                            tool_completed_buffer.append({
                                                "context": context,
                                                "thread_id": thread_id,
                                                "thread_run_id": thread_run_id,
                                                "tool_call_id": tool_call_id
                                            })
                                            logger.info(f"Added new tool completion to buffer: tool_call_id={tool_call_id}")
                                        else:
                                            logger.info(f"Skipping duplicate tool completion: tool_call_id={tool_call_id}")
                                        
                                        # 使用正确的tool_index（从matching_execution获取）
                                        if matching_execution:
                                            yielded_tool_indices.add(matching_execution["tool_index"])
                                        else:
                                            logger.warning(f"Could not find matching execution for func_response.id={func_response.id}")
                                            # 这种情况不应该发生，但提供fallback
                                            yielded_tool_indices.add(tool_index)

                                        # # TODO：处理人机交互情况
                                        # if func_response.name in ['ask', 'complete']:
                                        #     logger.info(f"Terminating tool '{func_response.name}' completed during streaming. Setting termination flag.")
                                        #     self.trace.event(name="terminating_tool_completed_during_streaming", level="DEFAULT", status_message=(f"Terminating tool '{func_response.name}' completed during streaming. Setting termination flag."))
                                        #     agent_should_terminate = True

                                    
                    if finish_reason == "xml_tool_limit_reached":
                        logger.info("Stopping stream processing after loop due to XML tool call limit")
                        self.trace.event(name="stopping_stream_processing_after_loop_due_to_xml_tool_call_limit", level="DEFAULT", status_message=(f"Stopping stream processing after loop due to XML tool call limit"))
                        break


                    
            #  -------- 流式循环的后处理工作 --------
            


            # 如果模型接口没有返回使用数据，则使用litellm.token_counter计算
            logger.info(f"before calculate usage, streaming_metadata: {streaming_metadata}")
            if streaming_metadata["usage"]["total_tokens"] == 0:
                logger.info("No usage data from provider, counting with litellm.token_counter")
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
            logger.info(f"after calculate usage, streaming_metadata: {streaming_metadata}")
        
            # 先从 tool_completed_buffer 中提取工具调用信息，构建 complete_native_tool_calls
            tool_results_buffer = []
            if tool_completed_buffer:
                seen_tool_call_ids = set()  # 用于去重
                for tool_completion in tool_completed_buffer:
                    context = tool_completion["context"]
                    tool_call = context.tool_call
                    tool_call_id = tool_call.get("id", "")
                    # 去重检查：避免同一个工具调用被重复添加
                    if tool_call_id not in seen_tool_call_ids:
                        seen_tool_call_ids.add(tool_call_id)
                        # 构建 OpenAI API 标准格式
                        tool_call_entry = {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_call.get("function_name", ""),
                                "arguments": tool_call.get("arguments", {})  # 已解析的对象
                            }
                        }
                        complete_native_tool_calls.append(tool_call_entry)
                        logger.info(f"Pre-built tool call for assistant message: {tool_call_id}")
                        
                        # 同时构建 tool_results_buffer 以备后用
                        tool_results_buffer.append((tool_call, context.result, context.tool_index, context))
                    else:
                        logger.info(f"Skipping duplicate tool call in pre-build: {tool_call_id}")
                        
                logger.info(f"Pre-built {len(complete_native_tool_calls)} tool calls for assistant message")
            else:
                logger.info("No tool_completed_buffer to pre-process")

            # 自动继续的条件： 如果可以自动继续，并且 finish_reason 是长度限制
            should_auto_continue = (can_auto_continue and finish_reason == 'length')

            # 保存并 yield 最终的 assistant 消息 (在处理tool_completed_buffer之前)
            # 只在有内容且不需要auto-continue时才保存
            if accumulated_content and not should_auto_continue:
                # 构建最终的 assistant 消息
                message_data = {
                    "role": "assistant", 
                    "content": accumulated_content, 
                    "tool_calls": complete_native_tool_calls or None
                }

                # 存储 assistant 消息到数据库中
                last_assistant_message_object = await self._add_message_with_agent_info(
                    thread_id=thread_id,
                    type="assistant",
                    content=message_data,
                    is_llm_message=True,
                    metadata={"thread_run_id": thread_run_id}
                )

                if last_assistant_message_object:
                    # 更新所有工具context的assistant_message_id
                    for tool_completion in tool_completed_buffer:
                        context = tool_completion["context"]
                        context.assistant_message_id = last_assistant_message_object['message_id']
                        logger.info(f"Updated context assistant_message_id: {context.assistant_message_id}")
                    
                    # 返回完整的已保存对象，并仅在返回时添加 stream_status 元数据
                    yield_message = last_assistant_message_object.copy()
                    yield_metadata = ensure_dict(yield_message.get('metadata'), {})
                    yield_metadata['stream_status'] = 'complete'
                    yield_message['metadata'] = yield_metadata
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

            # 处理延迟的工具完成状态消息 (现在assistant_message_id已经可用)
            if tool_completed_buffer:
                for tool_completion in tool_completed_buffer:
                    try:
                        context = tool_completion["context"]
                        
                        # 创建工具结果对象 (现在有正确的assistant_message_id)
                        saved_tool_result_object = await self._add_tool_result(
                            tool_completion["thread_id"], context.tool_call, context.result, config.xml_adding_strategy,
                            context.assistant_message_id, context.parsing_details
                        )
                        
                        # 然后创建链接到工具结果的完成状态
                        completed_msg_obj = await self._yield_and_save_tool_completed(
                            context, 
                            str(saved_tool_result_object['message_id']) if saved_tool_result_object else None, 
                            tool_completion["thread_id"], tool_completion["thread_run_id"]
                        )
                        
                        if completed_msg_obj:
                            yield format_for_yield(completed_msg_obj)
                            
                        if saved_tool_result_object:
                            yield format_for_yield(saved_tool_result_object)
                            logger.info(f"tool_completed_buffer: processed tool_id={tool_completion['tool_call_id']}")
                        else:
                            logger.warning(f"tool_completed_buffer: tool_result_object create failed: tool_id={tool_completion['tool_call_id']}")
                            
                    except Exception as e:
                        logger.error(f"tool_completed_buffer: processing failed: tool_id={tool_completion.get('tool_call_id', 'unknown')}, error={str(e)}")
                        
                logger.info(f"tool_completed_buffer: processing completed, processed {len(tool_completed_buffer)} items")
            else:
                logger.info("tool_completed_buffer: no tool_completed_status message to process")

            # 保存并 yield 流式结束状态
            if finish_reason == "xml_tool_limit_reached":
                finish_content = {"status_type": "finish", "finish_reason": "xml_tool_limit_reached"}
                finish_msg_obj = await self.add_message(
                    thread_id=thread_id, type="status", content=finish_content, 
                    is_llm_message=False, metadata={"thread_run_id": thread_run_id}
                )
                if finish_msg_obj: 
                    yield format_for_yield(finish_msg_obj)
                logger.info(f"Stream finished with reason: xml_tool_limit_reached after {xml_tool_call_count} XML tool calls")
                self.trace.event(name="stream_finished_with_reason_xml_tool_limit_reached_after_xml_tool_calls", level="DEFAULT", status_message=(f"Stream finished with reason: xml_tool_limit_reached after {xml_tool_call_count} XML tool calls"))





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
                        str(saved_tool_result_object['message_id']) if saved_tool_result_object else None,
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
            logger.info(f"adding tool result to thread:assistant_message_id:{assistant_message_id}")
            if assistant_message_id:
                metadata["assistant_message_id"] = str(assistant_message_id)  # Convert UUID to string
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
                logger.info(f"thread_id: {thread_id}")
                logger.info(f"tool_message: {tool_message}")
                logger.info(f"metadata: {metadata}")
                message_obj = await self.add_message(
                    thread_id=thread_id,
                    type="tool",  # Special type for tool responses
                    content=tool_message,
                    is_llm_message=True,
                    metadata=metadata
                )
                logger.info(f"message_obj: {message_obj}")
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
