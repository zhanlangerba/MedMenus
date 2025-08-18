from agentpress.tool import ToolResult, openapi_schema, usage_example
from agentpress.thread_manager import ThreadManager
from sandbox.tool_base import SandboxToolsBase
from utils.logger import logger
from utils.s3_upload_utils import upload_base64_image
import asyncio
import json
import base64
import io
import traceback
from PIL import Image
from utils.config import config

class BrowserTool(SandboxToolsBase):
    """
    Browser Tool for browser automation using local Stagehand API.
    
    This tool provides browser automation capabilities using a local Stagehand API server,
    replacing the sandbox browser tool functionality.
    
    Only 4 core functions that can handle everything:
    - browser_navigate_to: Navigate to URLs
    - browser_act: Perform any action (click, type, scroll, dropdowns etc.)
    - browser_extract_content: Extract content from pages
    - browser_screenshot: Take screenshots
    """
    _sandbox_created = False

    def __init__(self, project_id: str, thread_id: str, thread_manager: ThreadManager):
        super().__init__(project_id, thread_manager)
        self.thread_id = thread_id
    
    def _validate_base64_image(self, base64_string: str, max_size_mb: int = 10) -> tuple[bool, str]:
        """
        Comprehensive validation of base64 image data.
        
        Args:
            base64_string (str): The base64 encoded image data
            max_size_mb (int): Maximum allowed image size in megabytes
            
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        try:
            # Check if data exists and has reasonable length
            if not base64_string or len(base64_string) < 10:
                return False, "Base64 string is empty or too short"
            
            # Remove data URL prefix if present (data:image/jpeg;base64,...)
            if base64_string.startswith('data:'):
                try:
                    base64_string = base64_string.split(',', 1)[1]
                except (IndexError, ValueError):
                    return False, "Invalid data URL format"
            
            # Check if string contains only valid base64 characters
            # Base64 alphabet: A-Z, a-z, 0-9, +, /, = (padding)
            import re
            if not re.match(r'^[A-Za-z0-9+/]*={0,2}$', base64_string):
                return False, "Invalid base64 characters detected"
            
            # Check if base64 string length is valid (must be multiple of 4)
            if len(base64_string) % 4 != 0:
                return False, "Invalid base64 string length"
            
            # Attempt to decode base64
            try:
                image_data = base64.b64decode(base64_string, validate=True)
            except Exception as e:
                return False, f"Base64 decoding failed: {str(e)}"
            
            # Check decoded data size
            if len(image_data) == 0:
                return False, "Decoded image data is empty"
            
            # Check if decoded data size exceeds limit
            max_size_bytes = max_size_mb * 1024 * 1024
            if len(image_data) > max_size_bytes:
                return False, f"Image size ({len(image_data)} bytes) exceeds limit ({max_size_bytes} bytes)"
            
            # Validate that decoded data is actually a valid image using PIL
            try:
                image_stream = io.BytesIO(image_data)
                with Image.open(image_stream) as img:
                    # Verify the image by attempting to load it
                    img.verify()
                    
                    # Check if image format is supported
                    supported_formats = {'JPEG', 'PNG', 'GIF', 'BMP', 'WEBP', 'TIFF'}
                    if img.format not in supported_formats:
                        return False, f"Unsupported image format: {img.format}"
                    
                    return True, "Image validation successful"
                    
            except Exception as e:
                return False, f"Image validation failed: {str(e)}"
                
        except Exception as e:
            return False, f"Image validation error: {str(e)}"
    
    async def _debug_sandbox_services(self) -> str:
        """Debug method to check what services are running in the sandbox"""
        try:
            await self._ensure_sandbox()
            
            # Check what processes are running
            ps_cmd = "ps aux | grep -E '(python|uvicorn|stagehand|node)' | grep -v grep"
            response = await self.sandbox.process.exec(ps_cmd, timeout=10)
            
            processes = response.result if response.exit_code == 0 else "Failed to get process list"
            
            # Check what ports are listening
            netstat_cmd = "netstat -tlnp 2>/dev/null | grep -E ':(8003|8004)' || ss -tlnp 2>/dev/null | grep -E ':(8003|8004)' || echo 'No netstat/ss available'"
            response2 = await self.sandbox.process.exec(netstat_cmd, timeout=10)
            
            ports = response2.result if response2.exit_code == 0 else "Failed to get port list"
            
            debug_info = f"""
            === Sandbox Services Debug Info ===
            Running processes:
            {processes}

            Listening ports:
            {ports}

            === End Debug Info ===
            """
            return debug_info
            
        except Exception as e:
            return f"Error getting debug info: {e}"

    async def _check_stagehand_api_health(self) -> bool:
        """Check if the Stagehand API server is running and accessible"""
        try:
            await self._ensure_sandbox()

            if not self.__class__._sandbox_created:
                logger.info("Sandbox just created, waiting for server to start")
                await asyncio.sleep(5)
                self.__class__._sandbox_created = True
            
            # Simple health check curl command
            curl_cmd = "curl -s -X GET 'http://localhost:8004/api' -H 'Content-Type: application/json'"
            
            logger.debug(f"Checking Stagehand API health with: {curl_cmd}")
            
            response = await self.sandbox.process.exec(curl_cmd, timeout=10)
            if response.exit_code == 0:
                try:
                    result = json.loads(response.result)
                    if result.get("status") == "healthy":
                        logger.info("✅ Stagehand API server is running and healthy")
                        return True
                    else:
                        # If the browser api is not healthy, we need to restart the browser api
                        model_api_key = config.ANTHROPIC_API_KEY

                        response = await self.sandbox.process.exec(f"curl -X POST 'http://localhost:8004/api/init' -H 'Content-Type: application/json' -d '{{\"api_key\": \"{model_api_key}\"}}'", timeout=90)
                        if response.exit_code == 0:
                            logger.info("Stagehand API server restarted successfully")
                            return True
                        else:
                            logger.warning(f"Stagehand API server restart failed: {response.result}")
                            return False
                except json.JSONDecodeError:
                    logger.warning(f"Stagehand API server responded but with invalid JSON: {response.result}")
                    return False
            else:
                logger.warning(f"Stagehand API server health check failed with exit code {response.exit_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error checking Stagehand API health: {e}")
            return False

    async def _execute_stagehand_api(self, endpoint: str, params: dict = None, method: str = "POST") -> ToolResult:
        """Execute a Stagehand action through the sandbox API"""
        try:
            # Ensure sandbox is initialized
            await self._ensure_sandbox()
            
            # Check if Stagehand API server is running
            stagehand_healthy = await self._check_stagehand_api_health()
            
            if not stagehand_healthy:
                error_msg = "Stagehand API server is not running. Please ensure the Stagehand API server is running. Error: {response}"
                
                # Add debug information
                debug_info = await self._debug_sandbox_services()
                error_msg += f"\n\nDebug information:\n{debug_info}"
                
                logger.error(error_msg)
                return self.fail_response(error_msg)
            
            
            # Build the curl command to call the local Stagehand API
            url = f"http://localhost:8004/api/{endpoint}"  # Fixed localhost as curl runs inside container
            
            if method == "GET" and params:
                query_params = "&".join([f"{k}={v}" for k, v in params.items()])
                url = f"{url}?{query_params}"
                curl_cmd = f"curl -s -X {method} '{url}' -H 'Content-Type: application/json'"
            else:
                curl_cmd = f"curl -s -X {method} '{url}' -H 'Content-Type: application/json'"
                if params:
                    json_data = json.dumps(params)
                    curl_cmd += f" -d '{json_data}'"
            
            logger.debug(f"\033[95mExecuting curl command:\033[0m\n{curl_cmd}")
            
            response = await self.sandbox.process.exec(curl_cmd, timeout=30)  # Execute curl inside sandbox
            
            if response.exit_code == 0:
                try:
                    result = json.loads(response.result)
                    logger.info(f"Stagehand API result: {result}")

                    logger.info("Stagehand API request completed successfully")

                    if "screenshot_base64" in result:
                        try:
                            screenshot_data = result["screenshot_base64"]
                            is_valid, validation_message = self._validate_base64_image(screenshot_data)
                            
                            if is_valid:
                                logger.debug(f"Screenshot validation passed: {validation_message}")
                                image_url = await upload_base64_image(screenshot_data)
                                result["image_url"] = image_url
                                logger.debug(f"Uploaded screenshot to {image_url}")
                            else:
                                logger.warning(f"Screenshot validation failed: {validation_message}")
                                result["image_validation_error"] = validation_message
                                
                            del result["screenshot_base64"]
                            
                        except Exception as e:
                            logger.error(f"Failed to process screenshot: {e}")
                            result["image_upload_error"] = str(e)

                    added_message = await self.thread_manager.add_message(
                        thread_id=self.thread_id,
                        type="browser_state",
                        content=result,
                        is_llm_message=False
                    )

                    # Prepare clean response for agent (filter out internal metadata)
                    # Only include data that's useful for the agent's decision making
                    clean_result = {
                        "success": result.get("success", True),
                        "message": result.get("message", "Stagehand action completed successfully")
                    }

                    # Include only data that actually comes from browserApi.ts
                    if result.get("url"):
                        clean_result["url"] = result["url"]
                    if result.get("title"):
                        clean_result["title"] = result["title"]
                    if result.get("action"):
                        clean_result["action"] = result["action"]
                    if result.get("image_url"):  # This is screenshot_base64 converted to image_url
                        clean_result["image_url"] = result["image_url"]
                    
                    # Include any error context that's useful for the agent
                    if result.get("image_validation_error"):
                        clean_result["screenshot_issue"] = f"Screenshot processing issue: {result['image_validation_error']}"
                    if result.get("image_upload_error"):
                        clean_result["screenshot_issue"] = f"Screenshot upload issue: {result['image_upload_error']}"

                    if clean_result.get("success"):
                        return self.success_response(clean_result)
                    else:
                        # Handle error responses with helpful context  
                        error_msg = result.get("error", result.get("message", "Unknown error"))
                        if "Page crashed" in error_msg:
                            error_msg += "\n\nNote: Browser page crashes in Docker environments can be caused by insufficient browser launch options. Consider using the regular browser automation tool (sb_browser_tool) as an alternative."
                        clean_result["message"] = error_msg
                        return self.fail_response(clean_result)

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse response JSON: {response.result} {e}")
                    return self.fail_response(f"Failed to parse response JSON: {response.result} {e}")
            else:
                # Check if it's a connection error (exit code 7)
                if response.exit_code == 7:
                    error_msg = f"Stagehand API server is not available on port 8004. Please ensure the Stagehand API server is running. Error: {response}"
                    logger.error(error_msg)
                    return self.fail_response(error_msg)
                else:
                    logger.error(f"Stagehand API request failed: {response}")
                    return self.fail_response(f"Stagehand API request failed: {response}")

        except Exception as e:
            logger.error(f"Error executing Stagehand action: {e}")
            logger.debug(traceback.format_exc())
            return self.fail_response(f"Error executing Stagehand action: {e}")

    # Core Functions Only
    
    @openapi_schema({
        "type": "function",
        "function": {
            "name": "browser_navigate_to",
            "description": "Navigate to a specific url",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The url to navigate to"
                    }
                },
                "required": ["url"]
            }
        }
    })
    @usage_example('''
        <function_calls>
        <invoke name="browser_navigate_to">
        <parameter name="url">https://example.com</parameter>
        </invoke>
        </function_calls>
        ''')
    async def browser_navigate_to(self, url: str) -> ToolResult:
        """Navigate to a URL using Stagehand."""
        logger.info(f"Browser navigating to: {url}")
        return await self._execute_stagehand_api("navigate", {"url": url})
    
    @openapi_schema({
        "type": "function",
        "function": {
            "name": "browser_act",
            "description": "Perform any browser action using natural language description. CRITICAL: This tool automatically provides a screenshot with every action. For data entry actions (filling forms, entering text, selecting options), you MUST review the provided screenshot to verify that displayed values exactly match what was intended. Report mismatches immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The action to perform. Examples: 'click the login button', 'fill in the email field with test@example.com', 'scroll down to see more content', 'select option 2 from the dropdown', 'press Enter', 'go back', 'wait 5 seconds', 'click at coordinates 100,200', 'drag the file icon to the drop zone', 'select United States from the country dropdown'"
                    },
                    "variables": {
                        "type": "object",
                        "description": "Variables to use in the action. Variables in the action string are referenced using %variable_name%. These variables are NOT shared with LLM providers for security.",
                        "additionalProperties": {"type": "string"},
                        "default": {}
                    },
                    "iframes": {
                        "type": "boolean",
                        "description": "Whether to include iframe content in the action. Set to true if the target element is inside an iframe.",
                        "default": True
                    }
                },
                "required": ["action"]
            }
        }
    })
    @usage_example('''
        <function_calls>
        <invoke name="browser_act">
        <parameter name="action">fill in the login form with %username% and %password%</parameter>
        <parameter name="variables">{"username": "john.doe", "password": "secret123"}</parameter>
        <parameter name="iframes">true</parameter>
        </invoke>
        </function_calls>
        ''')
    async def browser_act(self, action: str, variables: dict = None, iframes: bool = False) -> ToolResult:
        """Perform any browser action using Stagehand."""
        logger.info(f"Browser acting: {action} (variables={'***' if variables else None}, iframes={iframes})")
        params = {"action": action, "iframes": iframes, "variables": variables}
        return await self._execute_stagehand_api("act", params)
    
    @openapi_schema({
        "type": "function",
        "function": {
            "name": "browser_extract_content",
            "description": "Extract structured content from the current page using Stagehand",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "What content to extract (e.g., 'extract all product prices', 'get the main heading', 'extract apartment listings with address and price')"
                    },
                    "selector": {
                        "type": "string",
                        "description": "Optional XPath selector to reduce extraction scope to a specific element. Useful for reducing input tokens and increasing accuracy.",
                        "default": None
                    },
                    "iframes": {
                        "type": "boolean",
                        "description": "Whether to include iframe content in the extraction. Set to true if the target content is inside an iframe.",
                        "default": True
                    }
                },
                "required": ["instruction"]
            }
        }
    })
    @usage_example('''
        <function_calls>
        <invoke name="browser_extract_content">
        <parameter name="instruction">extract all product names and prices from the main product list</parameter>
        <parameter name="selector">//div[@class='product-list']</parameter>
        <parameter name="iframes">true</parameter>
        </invoke>
        </function_calls>
        ''')
    async def browser_extract_content(self, instruction: str, selector: str = None, iframes: bool = False) -> ToolResult:
        """Extract structured content from the current page using Stagehand."""
        logger.info(f"Browser extracting: {instruction} (selector={selector}, iframes={iframes})")
        params = {"instruction": instruction, "iframes": iframes, "selector": selector}
        return await self._execute_stagehand_api("extract", params)
    
    @openapi_schema({
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take a screenshot of the current page",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the screenshot",
                        "default": "screenshot"
                    }
                }
            }
        }
    })
    @usage_example('''
        <function_calls>
        <invoke name="browser_screenshot">
        <parameter name="name">page_screenshot</parameter>
        </invoke>
        </function_calls>
        ''')
    async def browser_screenshot(self, name: str = "screenshot") -> ToolResult:
        """Take a screenshot using Stagehand."""
        logger.info(f"Browser taking screenshot: {name}")
        return await self._execute_stagehand_api("screenshot", {"name": name})
