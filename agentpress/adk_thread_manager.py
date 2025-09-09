"""
Google ADK 版本：1.12.0
Google ADK 版本的线程管理器
实现与 ThreadManager 相同的接口，但使用 Google ADK 作为底层实现
"""

import json
from typing import List, Dict, Any, Optional, Type, Union, AsyncGenerator, Literal
from services.postgresql import DBConnection
from utils.logger import logger
from agentpress.tool_registry import ToolRegistry
from agentpress.context_manager import ContextManager
from agentpress.response_processor import ResponseProcessor, ProcessorConfig
from agentpress.tool import Tool


ADK_AVAILABLE = True
from google.adk.agents.llm_agent import LlmAgent # type: ignore
from google.adk.runners import Runner # type: ignore
from google.adk.sessions import DatabaseSessionService # type: ignore
from google.adk.tools.base_tool import BaseTool # type: ignore


try:
    from langfuse.client import StatefulGenerationClient, StatefulTraceClient # type: ignore
except ImportError:
    try:
        from langfuse import StatefulGenerationClient, StatefulTraceClient # type: ignore
    except ImportError:
        from typing import Any
        StatefulGenerationClient = Any
        StatefulTraceClient = Any

from services.langfuse import langfuse
from utils.config import config

# Type alias for tool choice
ToolChoice = Literal["auto", "required", "none"]

class ADKThreadManager:
    """
    Google ADK 版本的线程管理器
    实现与 ThreadManager 相同的接口，但使用 Google ADK 作为底层实现
    """

    def __init__(self, trace: Optional[StatefulTraceClient] = None, is_agent_builder: bool = False, target_agent_id: Optional[str] = None, agent_config: Optional[dict] = None): # type: ignore
        """初始化 ADK 线程管理器

        Args:
            trace: Optional trace client for logging
            is_agent_builder: Whether this is an agent builder session
            target_agent_id: ID of the agent being built (if in agent builder mode)
            agent_config: Optional agent configuration with version information
        """
        if not ADK_AVAILABLE:
            raise ImportError("Google ADK is not available. Please install google-adk package.")
        
        self.db = DBConnection()
        self.tool_registry = ToolRegistry()
        self.trace = trace
        self.is_agent_builder = is_agent_builder
        self.target_agent_id = target_agent_id
        self.agent_config = agent_config
        
        if not self.trace:
            self.trace = langfuse.trace(name="anonymous:adk_thread_manager")
        
        self.response_processor = ResponseProcessor(
            tool_registry=self.tool_registry,
            add_message_callback=self.add_message,
            trace=self.trace,
            is_agent_builder=self.is_agent_builder,
            target_agent_id=self.target_agent_id,
            agent_config=self.agent_config
        )
        self.context_manager = ContextManager()
        
        # # ADK 组件
        # self.llm_agent: Optional[LlmAgent] = None
        # self.runner: Optional[Runner] = None
        # self.session_service: Optional[DatabaseSessionService] = None

    def add_tool(self, tool_class: Type[Tool], function_names: Optional[List[str]] = None, **kwargs):
        """Add a tool to the ThreadManager."""
        self.tool_registry.register_tool(tool_class, function_names, **kwargs)

    def _convert_tool_to_adk(self, tool_class: Type, **kwargs) -> Optional[BaseTool]:
        """将工具转换为 ADK 格式

        Args:
            tool_class: 工具类
            **kwargs: 工具参数

        Returns:
            ADK 工具实例
        """
        try:
            # 这里需要根据具体的工具类实现转换逻辑
            # 暂时返回 None，后续可以根据需要实现具体的转换
            logger.debug(f"Converting tool {tool_class.__name__} to ADK format")
            return None
        except Exception as e:
            logger.error(f"Failed to convert tool {tool_class.__name__}: {e}")
            return None

    async def get_llm_messages(self, thread_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a thread from events table.

        This method fetches messages from the events table and formats them
        to match the original messages table format for downstream compatibility.

        Args:
            thread_id: The ID of the thread to get messages for.

        Returns:
            List of message objects in the same format as original messages table.
        """
        logger.debug(f"Getting messages for thread {thread_id} from events table")
        client = await self.db.client

        try:
            # 获取事件，分批获取，避免数据库过载
            all_events = []
            batch_size = 1000
            offset = 0
            
            while True:
                # 从 events 表获取消息，按时间戳排序
                result = await client.table('events').select(
                    'id, author, content, timestamp, session_id, user_id, app_name, invocation_id'
                ).eq('session_id', thread_id).in_(
                    'author', ['user', 'assistant']
                ).order('timestamp').range(offset, offset + batch_size - 1).execute()
                
                if not result.data or len(result.data) == 0:
                    break
                    
                all_events.extend(result.data)
                
                # 如果获取的记录数小于 batch_size，则表示已经到达末尾
                if len(result.data) < batch_size:
                    break
                    
                offset += batch_size
            
            # 使用 all_events 而不是 result.data 
            result_data = all_events

            # 解析返回的数据，并转换为原始消息格式
            if not result_data:
                return []

            # 将事件转换为原始消息格式，用于下游兼容
            messages = []
            for event in result_data:
                try:
                    # 确保event是字典格式
                    if hasattr(event, '__dict__'):
                        event = dict(event)
                    
                    # 解析事件内容
                    content = event.get('content', {})
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except json.JSONDecodeError:
                            # 如果不是JSON，当作纯文本处理
                            content = {"content": content}
                    
                    # 构建与原始 messages 表格式兼容的消息对象
                    message = {
                        "role": event.get('author', 'user'),
                        "message_id": event.get('id'),
                        "timestamp": event.get('timestamp'),
                        "app_name": event.get('app_name'),
                        "user_id": event.get('user_id'),
                        "session_id": event.get('session_id'),
                        "invocation_id": event.get('invocation_id')
                    }
                    
                    # 处理timestamp字段，确保datetime对象被转换为字符串
                    if message.get('timestamp') and hasattr(message['timestamp'], 'isoformat'):
                        message['timestamp'] = message['timestamp'].isoformat()
                    
                    # 处理内容格式 - 兼容原始格式和ADK格式
                    if isinstance(content, dict):
                        # 处理ADK格式 {"role": "user", "parts": [{"text": "..."}]}
                        if 'parts' in content and isinstance(content['parts'], list):
                            # 提取ADK parts中的文本内容
                            text_parts = []
                            for part in content['parts']:
                                if isinstance(part, dict) and 'text' in part:
                                    text_parts.append(part['text'])
                            message["content"] = ' '.join(text_parts).strip()
                        # 如果存在：处理原始格式 {"role": "user", "content": "..."}
                        elif 'content' in content:
                            message["content"] = content['content']
                        else:
                            # 如果都没有，将整个对象转为字符串（向后兼容）
                            message["content"] = json.dumps(content)
                    else:
                        message["content"] = str(content)
                    
                    messages.append(message)
                    
                except Exception as e:
                    logger.error(f"Failed to parse event {event.get('id')}: {e}")
                    continue

            logger.debug(f"Retrieved {len(messages)} messages from events table for thread {thread_id}")
            return messages

        except Exception as e:
            logger.error(f"Failed to get messages for thread {thread_id}: {str(e)}", exc_info=True)
            return []

    async def run_thread(
        self,
        thread_id: str,
        system_prompt: Dict[str, Any],
        stream: bool = True,
        temporary_message: Optional[Dict[str, Any]] = None,
        llm_model: str = "deepseek/deepseek-chat",
        llm_temperature: float = 0,
        llm_max_tokens: Optional[int] = None,
        processor_config: Optional[ProcessorConfig] = None,
        tool_choice: ToolChoice = "auto",
        native_max_auto_continues: int = 0,
        available_functions: Optional[Dict[str, callable]] = None,
        max_xml_tool_calls: int = 0,
        include_xml_examples: bool = False,
        enable_thinking: Optional[bool] = False,
        reasoning_effort: Optional[str] = 'low',
        enable_context_manager: bool = True,
        generation: Optional[StatefulGenerationClient] = None, # type: ignore
    ) -> Union[Dict[str, Any], AsyncGenerator]:
        """使用 ADK Runner 执行线程

        Args:
            thread_id: 线程ID
            system_prompt: 系统提示词
            stream: 是否使用流式响应
            temporary_message: 临时消息
            llm_model: 模型名称
            llm_temperature: 温度参数
            llm_max_tokens: 最大token数
            tool_choice: 工具选择
            enable_thinking: 是否启用思考
            reasoning_effort: 推理努力程度
            enable_context_manager: 是否启用上下文管理器
            user_id: 用户ID
            user_message: 用户消息
            **kwargs: 其他参数

        Yields:
            响应事件
        """
        logger.info(f"current thread_id: {thread_id}")
        logger.info(f"current llm_model: {llm_model}")

        # 确保 processor_config 不为 None
        config = processor_config or ProcessorConfig()

        # 如果 max_xml_tool_calls 指定且未在 config 中设置，则应用
        if max_xml_tool_calls > 0 and not config.max_xml_tool_calls:
            config.max_xml_tool_calls = max_xml_tool_calls

        # 创建一个工作副本，以便可能修改
        working_system_prompt = system_prompt.copy()

#         # 如果请求，则添加 XML 工具调用指令到系统提示词
#         if include_xml_examples and config.xml_tool_calling:
#             openapi_schemas = self.tool_registry.get_openapi_schemas()
#             usage_examples = self.tool_registry.get_usage_examples()
            
#             if openapi_schemas:
#                 # Convert schemas to JSON string
#                 schemas_json = json.dumps(openapi_schemas, indent=2)
                
#                 # Build usage examples section if any exist
#                 usage_examples_section = ""
#                 if usage_examples:
#                     usage_examples_section = "\n\nUsage Examples:\n"
#                     for func_name, example in usage_examples.items():
#                         usage_examples_section += f"\n{func_name}:\n{example}\n"
                
#                 examples_content = f"""
# In this environment you have access to a set of tools you can use to answer the user's question.

# You can invoke functions by writing a <function_calls> block like the following as part of your reply to the user:

# <function_calls>
# <invoke name="function_name">
# <parameter name="param_name">param_value</parameter>
# ...
# </invoke>
# </function_calls>

# String and scalar parameters should be specified as-is, while lists and objects should use JSON format.

# Here are the functions available in JSON Schema format:

# ```json
# {schemas_json}
# ```

# When using the tools:
# - Use the exact function names from the JSON schema above
# - Include all required parameters as specified in the schema
# - Format complex data (objects, arrays) as JSON strings within the parameter tags
# - Boolean values should be "true" or "false" (lowercase)
# {usage_examples_section}"""

#                 # # Save examples content to a file
#                 # try:
#                 #     with open('xml_examples.txt', 'w') as f:
#                 #         f.write(examples_content)
#                 #     logger.debug("Saved XML examples to xml_examples.txt")
#                 # except Exception as e:
#                 #     logger.error(f"Failed to save XML examples to file: {e}")

#                 system_content = working_system_prompt.get('content')

#                 if isinstance(system_content, str):
#                     working_system_prompt['content'] += examples_content
#                     logger.debug("Appended XML examples to string system prompt content.")
#                 elif isinstance(system_content, list):
#                     appended = False
#                     for item in working_system_prompt['content']: # Modify the copy
#                         if isinstance(item, dict) and item.get('type') == 'text' and 'text' in item:
#                             item['text'] += examples_content
#                             logger.debug("Appended XML examples to the first text block in list system prompt content.")
#                             appended = True
#                             break
#                     if not appended:
#                         logger.warning("System prompt content is a list but no text block found to append XML examples.")
#                 else:
#                     logger.warning(f"System prompt content is of unexpected type ({type(system_content)}), cannot add XML examples.")

        # 控制是否需要自动继续，因为工具调用完成原因
        # Control whether we need to auto-continue due to tool_calls finish reason
        auto_continue = True
        auto_continue_count = 0

        # 共享状态，用于连续流式输出
        continuous_state = {
            'accumulated_content': '',
            'thread_run_id': None
        }

        async def _run_once(temp_msg=None):
            try:
                # 确保 config 在当前作用域可用
                nonlocal config
                # 注意：config 现在保证存在，因为上面的检查

                # 1. 从线程获取消息，用于 LLM 调用
                messages = await self.get_llm_messages(thread_id)

                # 2. 检查 token 计数，再继续
                token_count = 0
                try:
                    from litellm.utils import token_counter # type: ignore
                    # 使用修改后的working_system_prompt进行token计数
                    token_count = token_counter(model=llm_model, messages=[working_system_prompt] + messages)
                    token_threshold = self.context_manager.token_threshold
                    logger.info(f"Thread {thread_id} token count: {token_count}/{token_threshold} ({(token_count/token_threshold)*100:.1f}%)")

                except Exception as e:
                    logger.error(f"Error counting tokens or summarizing: {str(e)}")

                # 3. 预处理输入消息，准备LLM调用 + 添加临时消息（如果存在）
                # 使用修改后的working_system_prompt，可能包含XML示例
                prepared_messages = [working_system_prompt]

                # 找到最后一个用户消息的索引
                last_user_index = -1
                for i, msg in enumerate(messages):
                    if isinstance(msg, dict) and msg.get('role') == 'user':
                        last_user_index = i

                # 插入临时消息，如果存在，插入到最后一个用户消息之前
                if temp_msg and last_user_index >= 0:
                    prepared_messages.extend(messages[:last_user_index])
                    prepared_messages.append(temp_msg)
                    prepared_messages.extend(messages[last_user_index:])
                    logger.info("Added temporary message before the last user message")
                else:
                    # 如果没有用户消息或没有临时消息，则添加所有消息
                    prepared_messages.extend(messages)
                    if temp_msg:
                        prepared_messages.append(temp_msg)
                        logger.info("Added temporary message to the end of prepared messages")

                # 添加部分助手内容，用于自动继续上下文（不保存到DB）
                if auto_continue_count > 0 and continuous_state.get('accumulated_content'):
                    partial_content = continuous_state.get('accumulated_content', '')
                    
                    # 创建临时助手消息，仅包含文本内容
                    temporary_assistant_message = {
                        "role": "assistant",
                        "content": partial_content
                    }
                    prepared_messages.append(temporary_assistant_message)
                    logger.info(f"Added temporary assistant message with {len(partial_content)} chars for auto-continue context")
     
                prepared_messages = self.context_manager.compress_messages(prepared_messages, llm_model)

                # 5. 准备大模型调用
                try:
                    # import datatime
                    # if generation:
                    #     generation.update(
                    #         input=prepared_messages,
                    #         start_time=datetime.datetime.now(datetime.timezone.utc),
                    #         model=llm_model,
                    #         model_parameters={
                    #           "max_tokens": llm_max_tokens,
                    #           "temperature": llm_temperature,
                    #           "enable_thinking": enable_thinking,
                    #           "reasoning_effort": reasoning_effort,
                    #           "tool_choice": tool_choice,
                    #           "tools": openapi_tool_schemas,
                    #         }
                    #     )

                    from services.llm import make_adk_api_call
                    
                    tool_functions = available_functions
                    logger.info(f"📋 ADK工具函数列表: {list(tool_functions.keys()) if tool_functions else []}")

                    logger.info(f"Before make_adk_api_call, tool_functions: {tool_functions}")
                    # 将构建好的提示词实际发送到大模型中                    
                    llm_response = await make_adk_api_call(
                        prepared_messages, 
                        llm_model,
                        temperature=llm_temperature,
                        max_tokens=llm_max_tokens,
                        tools=tool_functions,  # 🔧 传递工具函数字典
                        tool_choice=tool_choice if config.native_tool_calling else "none",
                        stream=stream,
                        enable_thinking=enable_thinking,
                        reasoning_effort=reasoning_effort
                    )
                    logger.info(f"Successfully received raw LLM API response stream/object")
                except Exception as e:
                    logger.error(f"Failed to make LLM API call: {str(e)}", exc_info=True)
                    raise

                # 6. 这样开始处理ADK返回的异步生成器
                if stream:
                    logger.info("Processing ADK streaming response")

                    from typing import AsyncGenerator, cast
                    
                    try:
                        response_generator = self.response_processor.process_adk_streaming_response(
                            adk_response=cast(AsyncGenerator, llm_response),
                            thread_id=thread_id,
                            config=config,
                            prompt_messages=prepared_messages,
                            llm_model=llm_model,
                            can_auto_continue=(native_max_auto_continues > 0),
                            auto_continue_count=auto_continue_count,
                            continuous_state=continuous_state
                        )
                        logger.info("process_adk_streaming_response called successfully")
                        return response_generator
                    except Exception as e:
                        logger.error(f"process_adk_streaming_response called failed: {e}")
                        import traceback
                        traceback.print_exc()
                        raise
                    # else:
                    #     # Fallback to non-streaming if response is not iterable
                    #     response_generator = self.response_processor.process_non_streaming_response(
                    #         llm_response=llm_response,
                    #         thread_id=thread_id,
                    #         config=config,
                    #         prompt_messages=prepared_messages,
                    #         llm_model=llm_model,
                    #     )

                    # return response_generator
                else:
                    logger.debug("Processing non-streaming response")
                    # Pass through the response generator without try/except to let errors propagate up
                    response_generator = self.response_processor.process_non_streaming_response(
                        llm_response=llm_response,
                        thread_id=thread_id,
                        config=config,
                        prompt_messages=prepared_messages,
                        llm_model=llm_model,
                    )
                    return response_generator # Return the generator

            except Exception as e:
                logger.error(f"Error in run_thread: {str(e)}", exc_info=True)
                # Return the error as a dict to be handled by the caller
                return {
                    "type": "status",
                    "status": "error",
                    "message": str(e)
                }

        # 定义一个包装器生成器，处理自动继续逻辑
        async def auto_continue_wrapper():
            print("我先进入的auto_continue_wrapper")
            nonlocal auto_continue, auto_continue_count

            while auto_continue and (native_max_auto_continues == 0 or auto_continue_count < native_max_auto_continues):
                # 重置 auto_continue 用于此迭代
                auto_continue = False

                # 运行一次线程，传递可能修改后的系统提示
                # 仅在第一次迭代时传递 temp_msg
                try:
                    print("我在这里要开始执行 _run_once")
                    response_gen = await _run_once(temporary_message if auto_continue_count == 0 else None)

                    # Handle error responses
                    if isinstance(response_gen, dict) and "status" in response_gen and response_gen["status"] == "error":
                        logger.error(f"Error in auto_continue_wrapper: {response_gen.get('message', 'Unknown error')}")
                        yield response_gen
                        return  # Exit the generator on error
                    print("我在这里要获取 response_gen 的属性了")
                    # Process each chunk
                    try:
                        if hasattr(response_gen, '__aiter__'):
                            from typing import AsyncGenerator, cast
                            async for chunk in cast(AsyncGenerator, response_gen):
                                # Check if this is a finish reason chunk with tool_calls or xml_tool_limit_reached
                                if chunk.get('type') == 'finish':
                                    if chunk.get('finish_reason') == 'tool_calls':
                                        # Only auto-continue if enabled (max > 0)
                                        if native_max_auto_continues > 0:
                                            logger.info(f"Detected finish_reason='tool_calls', auto-continuing ({auto_continue_count + 1}/{native_max_auto_continues})")
                                            auto_continue = True
                                            auto_continue_count += 1
                                            # Don't yield the finish chunk to avoid confusing the client
                                            continue
                                    elif chunk.get('finish_reason') == 'xml_tool_limit_reached':
                                        # Don't auto-continue if XML tool limit was reached
                                        logger.info(f"Detected finish_reason='xml_tool_limit_reached', stopping auto-continue")
                                        auto_continue = False
                                        # Still yield the chunk to inform the client

                                elif chunk.get('type') == 'status':
                                    # if the finish reason is length, auto-continue
                                    try:
                                        content = json.loads(chunk.get('content', '{}'))
                                        if content.get('finish_reason') == 'length':
                                            logger.info(f"Detected finish_reason='length', auto-continuing ({auto_continue_count + 1}/{native_max_auto_continues})")
                                            auto_continue = True
                                            auto_continue_count += 1
                                            continue
                                    except (json.JSONDecodeError, TypeError):
                                        # If content is not valid JSON, just yield the chunk normally
                                        pass
                                # Otherwise just yield the chunk normally
                                yield chunk
                        else:
                            # response_gen is not iterable (likely an error dict), yield it directly
                            yield response_gen

                        # If not auto-continuing, we're done
                        if not auto_continue:
                            break
                    except Exception as e:
                        if ("AnthropicException - Overloaded" in str(e)):
                            logger.error(f"AnthropicException - Overloaded detected - Falling back to OpenRouter: {str(e)}", exc_info=True)
                            nonlocal llm_model
                            # Remove "-20250514" from the model name if present
                            model_name_cleaned = llm_model.replace("-20250514", "")
                            llm_model = f"openrouter/{model_name_cleaned}"
                            auto_continue = True
                            continue # Continue the loop
                        else:
                            # If there's any other exception, log it, yield an error status, and stop execution
                            logger.error(f"Error in auto_continue_wrapper generator: {str(e)}", exc_info=True)
                            yield {
                                "type": "status",
                                "status": "error",
                                "message": f"Error in thread processing: {str(e)}"
                            }
                        return  # Exit the generator on any error
                except Exception as outer_e:
                    # Catch exceptions from _run_once itself
                    logger.error(f"Error executing thread: {str(outer_e)}", exc_info=True)
                    yield {
                        "type": "status",
                        "status": "error",
                        "message": f"Error executing thread: {str(outer_e)}"
                    }
                    return  # Exit immediately on exception from _run_once

            # If we've reached the max auto-continues, log a warning
            if auto_continue and auto_continue_count >= native_max_auto_continues:
                logger.warning(f"Reached maximum auto-continue limit ({native_max_auto_continues}), stopping.")
                yield {
                    "type": "content",
                    "content": f"\n[Agent reached maximum auto-continue limit of {native_max_auto_continues}]"
                }        

        # 如果自动继续被禁用 (native_max_auto_continues=0), 只运行一次
        if native_max_auto_continues == 0:
            print("自动继续被禁用 (native_max_auto_continues=0)")
            # Pass the potentially modified system prompt and temp message
            return await _run_once(temporary_message)
        
        # 否则返回自动继续包装器生成器
        return auto_continue_wrapper()
        
        # try:
        #     # if not self.runner or not self.session:
        #     #     raise RuntimeError("ADK components not initialized. Call setup() first.")
            
        #     # # 准备用户输入
        #     # if user_message:
        #     #     message_text = user_message
        #     # elif temporary_message:
        #     #     # 处理临时消息
        #     #     if isinstance(temporary_message.get('content'), list):
        #     #         # 如果是多模态消息，提取文本内容
        #     #         text_parts = []
        #     #         for part in temporary_message['content']:
        #     #             if isinstance(part, dict) and part.get('type') == 'text':
        #     #                 text_parts.append(part.get('text', ''))
        #     #         message_text = ' '.join(text_parts)
        #     #     else:
        #     #         message_text = str(temporary_message.get('content', 'Hello'))
        #     # else:
        #     #     message_text = "Hello"
            
        #     # logger.debug(f"Prepared user message: {message_text[:100]}...")
            
        #     message_text = "如何理解黑洞？"

        #     from google.genai import types # type:ignore
        #     # 创建用户内容
        #     user_content = content = types.Content(role='user', parts=[types.Part(text=message_text)])
        #     print(f"user_content: {user_content}")
        #     # 使用 ADK Runner 执行

        #     from google.adk.agents.run_config import RunConfig, StreamingMode # type: ignore
        #     run_config = RunConfig(streaming_mode=StreamingMode.SSE)

        #     from google.adk.models.lite_llm import LiteLlm # type: ignore

        #     model=LiteLlm(
        #         model="openai/gpt-4o",  
        #         api_key="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"
        #     )

        #     from google.adk.agents import LlmAgent # type: ignore

        #     print(f"system_prompt: {system_prompt}")
        #     init_agent = LlmAgent(
        #         name="fufanmanus_basic_agent",
        #         model=model,
        #         instruction=system_prompt
        #     )


        #     # 使用数据库会话服务
        #     DB_CONFIG = {
        #         'host': 'localhost',
        #         'port': 5432,
        #         'database': 'adk',
        #         'user': 'postgres',
        #         'password': 'snowball2019'
        #     }

        #     print(f"DB_CONFIG: {DB_CONFIG}")
        #     DATABASE_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
            
        #     from google.adk.sessions import DatabaseSessionService # type: ignore
        #     session_service = DatabaseSessionService(DATABASE_URL)

        #     # 创建会话
        #     APP_NAME = "fufanmanus"
        #     USER_ID = "f7a2a1ab-a233-49b4-abdc-c58c650cfa06"
        #     SESSION_ID = thread_id

        #     print("开始创建数据库session")
        #     await session_service.create_session(
        #         app_name=APP_NAME, 
        #         user_id=USER_ID,
        #         session_id=SESSION_ID
        #     )
        #     print("数据库session创建成功")

        #     # 创建runner
        #     runner = Runner(
        #         agent=init_agent,
        #         app_name="fufanmanus",
        #         session_service=session_service
        #     )
        #     print("开始执行runner：")

        #     # 执行代理运行的流式输出
        #     async for event in runner.run_async(
        #         user_id=USER_ID,
        #         session_id=SESSION_ID,
        #         new_message=content,
        #         run_config=run_config
        #     ):
        #         if event.content and event.content.parts and event.content.parts[0].text:
        #             current_text = event.content.parts[0].text
        #             print(current_text, end="", flush=True)  # 直接输出增量
                
                    
        # except Exception as e:
        #     print(f"ADK thread execution failed: {e}")

    async def create_thread(
        self,
        account_id: Optional[str] = None,
        project_id: Optional[str] = None,
        is_public: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """创建新线程（与 ThreadManager 保持接口一致）

        Args:
            account_id: 账户ID
            project_id: 项目ID
            is_public: 是否公开
            metadata: 元数据

        Returns:
            线程ID
        """
        logger.debug(f"Creating new thread (account_id: {account_id}, project_id: {project_id}, is_public: {is_public})")
        client = await self.db.client

        # 准备线程数据
        thread_data = {
            'is_public': is_public,
            'metadata': metadata or {}
        }

        # 添加可选字段
        if account_id:
            thread_data['account_id'] = account_id
        if project_id:
            thread_data['project_id'] = project_id

        try:
            # 插入线程并获取线程ID
            result = await client.table('threads').insert(thread_data).execute()
            
            if result.data and len(result.data) > 0 and isinstance(result.data[0], dict) and 'thread_id' in result.data[0]:
                thread_id = result.data[0]['thread_id']
                logger.info(f"Successfully created thread: {thread_id}")
                return thread_id
            else:
                logger.error(f"Thread creation failed or did not return expected data structure. Result data: {result.data}")
                raise Exception("Failed to create thread: no thread_id returned")

        except Exception as e:
            logger.error(f"Failed to create thread: {str(e)}", exc_info=True)
            raise Exception(f"Thread creation failed: {str(e)}")

    async def add_message(
        self,
        thread_id: str,
        type: str,
        content: Union[Dict[str, Any], List[Any], str],
        is_llm_message: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        agent_version_id: Optional[str] = None
    ):
        """添加消息到线程（与 ThreadManager 保持接口一致）

        Args:
            thread_id: 线程ID
            type: 消息类型
            content: 消息内容
            is_llm_message: 是否为LLM消息
            metadata: 元数据
            agent_id: 代理ID（暂不支持，存储在metadata中）
            agent_version_id: 代理版本ID（暂不支持，存储在metadata中）
        """
        logger.debug(f"Adding message of type '{type}' to thread {thread_id} (agent: {agent_id}, version: {agent_version_id})")
        client = await self.db.client

        # 准备插入数据 - 根据messages表的实际结构
        data_to_insert = {
            'thread_id': thread_id,
            'project_id': '00000000-0000-0000-0000-000000000000',  # 临时使用默认project_id
            'type': type,
            'role': 'assistant' if type == 'assistant' else 'user' if type == 'user' else 'system',
            'content': json.dumps(content) if isinstance(content, (dict, list)) else str(content),
            'metadata': json.dumps(metadata) if metadata else '{}',
        }
        
        # 将代理信息存储在metadata中（因为messages表没有agent_id和agent_version_id字段）
        if agent_id or agent_version_id:
            metadata_dict = json.loads(data_to_insert['metadata']) if data_to_insert['metadata'] != '{}' else {}
            if agent_id:
                metadata_dict['agent_id'] = agent_id
            if agent_version_id:
                metadata_dict['agent_version_id'] = agent_version_id
            data_to_insert['metadata'] = json.dumps(metadata_dict)

        try:
            # 插入消息
            result = await client.table('messages').insert(data_to_insert)
            logger.info(f"Successfully added message to thread {thread_id}")

            if result.data and len(result.data) > 0 and isinstance(result.data[0], dict) and 'message_id' in result.data[0]:
                return result.data[0]
            
            else:
                logger.error(f"Insert operation failed or did not return expected data structure for thread {thread_id}. Result data: {result.data}")
                return None
        except Exception as e:
            logger.error(f"Failed to add message to thread {thread_id}: {str(e)}", exc_info=True)
            raise