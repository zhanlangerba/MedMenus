from typing import Dict, Type, Any, List, Optional, Callable
from agentpress.tool import Tool, SchemaType
from utils.logger import logger
import json


class ToolRegistry:
    """Registry for managing and accessing tools.
    
    Maintains a collection of tool instances and their schemas, allowing for
    selective registration of tool functions and easy access to tool capabilities.
    
    Attributes:
        tools (Dict[str, Dict[str, Any]]): OpenAPI-style tools and schemas
        
    Methods:
        register_tool: Register a tool with optional function filtering
        get_tool: Get a specific tool by name
        get_openapi_schemas: Get OpenAPI schemas for function calling
    """
    
    def __init__(self):
        """Initialize a new ToolRegistry instance."""
        self.tools = {}
        logger.debug("Initialized new ToolRegistry instance")
    
    def register_tool(self, tool_class: Type[Tool], function_names: Optional[List[str]] = None, **kwargs):
        """Register a tool with optional function filtering.
        
        Args:
            tool_class: The tool class to register
            function_names: Optional list of specific functions to register
            **kwargs: Additional arguments passed to tool initialization
            
        Notes:
            - For ADK: Only stores tool instance, ADK handles schemas automatically
            - For legacy: If function_names is None, all functions are registered
        """
        logger.debug(f"Registering tool class: {tool_class.__name__}")
        tool_instance = tool_class(**kwargs)
        
        #只存储工具实例，不处理复杂的schema
        # ADK会自动从函数签名和docstring推断schema
        # 检查工具实例的方法
        for method_name in dir(tool_instance):
            method = getattr(tool_instance, method_name)
            
            # 只处理公共的可调用方法（排除私有方法和属性）
            if (not method_name.startswith('_') and 
                callable(method) and 
                hasattr(method, '__self__') and  # 确保是绑定方法
                method_name not in ['get_schemas', 'success_response', 'fail_response']):  # 排除基类方法
                
                if function_names is None or method_name in function_names:
                    # 🎯 简化存储：只保存工具实例，让ADK处理其余部分
                    self.tools[method_name] = {
                        "instance": tool_instance,
                        "method": method,  # 直接存储可调用的方法
                        "tool_class": tool_class.__name__
                    }
                    logger.debug(f"Registered method '{method_name}' from {tool_class.__name__}")
        
        logger.debug(f"Tool registration complete for {tool_class.__name__}: {len([k for k in self.tools.keys() if self.tools[k]['tool_class'] == tool_class.__name__])} methods")

    def get_available_functions(self) -> Dict[str, Callable]:
        """Get all available tool functions.
        
        Returns:
            Dict mapping function names to their implementations
        """
        available_functions = {}
        
        # 🔄 简化版本：直接从存储的方法获取可调用函数
        for method_name, tool_info in self.tools.items():
            available_functions[method_name] = tool_info['method']
            
        logger.debug(f"Retrieved {len(available_functions)} available functions")
        return available_functions

    def get_tool(self, tool_name: str) -> Dict[str, Any]:
        """Get a specific tool by name.
        
        Args:
            tool_name: Name of the tool function
            
        Returns:
            Dict containing tool instance and method, or empty dict if not found
        """
        tool = self.tools.get(tool_name, {})
        if not tool:
            logger.warning(f"Tool not found: {tool_name}")
        return tool

    def get_openapi_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAPI schemas for function calling.
        
        Returns:
            List of OpenAPI-compatible schema definitions
            Note: For ADK, returns empty list as ADK handles schemas automatically
        """
        # 🔄 ADK模式：返回空列表，因为ADK会自动从函数签名推断schema
        logger.debug("ADK mode: OpenAPI schemas handled automatically by ADK framework")
        return []

    def get_usage_examples(self) -> Dict[str, str]:
        """Get usage examples for tools.
        
        Returns:
            Dict mapping function names to their usage examples
        """
        examples = {}
        
        # Get all registered tools and their schemas
        for tool_name, tool_info in self.tools.items():
            tool_instance = tool_info['instance']
            all_schemas = tool_instance.get_schemas()
            
            # Look for usage examples for this function
            if tool_name in all_schemas:
                for schema in all_schemas[tool_name]:
                    if schema.schema_type == SchemaType.USAGE_EXAMPLE:
                        examples[tool_name] = schema.schema.get('example', '')
                        logger.debug(f"Found usage example for {tool_name}")
                        break
        
        logger.debug(f"Retrieved {len(examples)} usage examples")
        return examples

    def get_tool_methods(self) -> Dict[str, Callable]:
        """Get all tool methods for ADK (直接获取可调用方法)
        
        Returns:
            Dict mapping method names to callable methods
        """
        return {name: info['method'] for name, info in self.tools.items()}
    
    def get_tool_instances(self) -> Dict[str, Any]:
        """Get all tool instances for ADK
        
        Returns:
            Dict mapping tool class names to tool instances
        """
        instances = {}
        for name, info in self.tools.items():
            tool_class = info['tool_class']
            if tool_class not in instances:
                instances[tool_class] = info['instance']
        return instances

