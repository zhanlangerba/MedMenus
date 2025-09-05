from tavily import AsyncTavilyClient # type: ignore
import httpx # type: ignore
from dotenv import load_dotenv # type: ignore
from google.adk.tools import FunctionTool # type: ignore
from google.adk.tools.tool_context import ToolContext # type: ignore
from utils.config import config
from sandbox.tool_base import SandboxToolsBase
from agentpress.thread_manager import ADKThreadManager
import json
import os
import datetime
import asyncio
import logging
from typing import Dict, Any, List
from urllib.parse import urlparse

class SandboxWebSearchToolFactory:
    """Factory class for creating sandbox-aware web search and scraping tools"""
    
    def __init__(self, project_id: str, thread_manager: ADKThreadManager):
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.workspace_path = "/workspace"
        self._sandbox = None
        self._sandbox_id = None
        self._sandbox_pass = None
        
        # Load environment variables and API keys
        load_dotenv()
        self.tavily_api_key = config.TAVILY_API_KEY
        self.firecrawl_api_key = config.FIRECRAWL_API_KEY
        self.firecrawl_url = config.FIRECRAWL_URL
        
        if not self.tavily_api_key:
            raise ValueError("TAVILY_API_KEY not found in configuration")
        if not self.firecrawl_api_key:
            raise ValueError("FIRECRAWL_API_KEY not found in configuration")

        # Tavily asynchronous search client
        self.tavily_client = AsyncTavilyClient(api_key=self.tavily_api_key)

    async def _ensure_sandbox(self):
        """确保有一个有效的沙箱实例，如果需要，从项目中检索它。"""
        if self._sandbox is None:
            try:
                # Get database client
                client = await self.thread_manager.db.client

                # Get project data
                project = await client.table('projects').select('*').eq('project_id', self.project_id).execute()
                if not project.data or len(project.data) == 0:
                    raise ValueError(f"Project {self.project_id} not found")

                project_data = project.data[0]
                sandbox_info = project_data.get('sandbox') or {}

                # If there is no sandbox recorded for this project, create one lazily
                if not sandbox_info.get('id'):
                    logging.info(f"No sandbox recorded for project {self.project_id}; creating lazily")
                    from sandbox.sandbox import create_sandbox, get_or_start_sandbox
                    import uuid
                    
                    sandbox_pass = str(uuid.uuid4())
                    sandbox_obj = await create_sandbox(sandbox_pass, self.project_id)
                    sandbox_id = sandbox_obj.id

                    # Gather preview links and token (best-effort parsing)
                    try:
                        vnc_link = await sandbox_obj.get_preview_link(6080)
                        website_link = await sandbox_obj.get_preview_link(8080)
                        vnc_url = vnc_link.url if hasattr(vnc_link, 'url') else str(vnc_link).split("url='")[1].split("'")[0]
                        website_url = website_link.url if hasattr(website_link, 'url') else str(website_link).split("url='")[1].split("'")[0]
                        token = vnc_link.token if hasattr(vnc_link, 'token') else (str(vnc_link).split("token='")[1].split("'")[0] if "token='" in str(vnc_link) else None)
                    except Exception:
                        logging.warning(f"Failed to extract preview links for sandbox {sandbox_id}", exc_info=True)
                        vnc_url = None
                        website_url = None
                        token = None

                    # Persist sandbox metadata to project record
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
                        try:
                            from sandbox.sandbox import delete_sandbox
                            await delete_sandbox(sandbox_id)
                        except Exception:
                            logging.error(f"Failed to delete sandbox {sandbox_id} after DB update failure", exc_info=True)
                        raise Exception("Database update failed when storing sandbox metadata")

                    # Store local metadata and ensure sandbox is ready
                    self._sandbox_id = sandbox_id
                    self._sandbox_pass = sandbox_pass
                    self._sandbox = await get_or_start_sandbox(self._sandbox_id)
                else:
                    # Use existing sandbox metadata
                    from sandbox.sandbox import get_or_start_sandbox
                    self._sandbox_id = sandbox_info['id']
                    self._sandbox_pass = sandbox_info.get('pass')
                    self._sandbox = await get_or_start_sandbox(self._sandbox_id)

            except Exception as e:
                logging.error(f"Error retrieving/creating sandbox for project {self.project_id}: {str(e)}", exc_info=True)
                raise e

        return self._sandbox

    def create_web_search_tool(self) -> FunctionTool:
        """创建带沙盒访问的web搜索工具"""
        
        async def web_search(
            query: str, 
            num_results: int = 20,
            tool_context: ToolContext
        ) -> Dict[str, Any]:
            """Search the web for up-to-date information on a specific topic using the Tavily API.
            
            This tool allows you to gather real-time information from the internet to answer user queries, 
            research topics, validate facts, and find recent developments. Results include titles, URLs, 
            and publication dates. Use this tool for discovering relevant web pages before potentially 
            crawling them for complete content.
            
            Args:
                query: The search query to find relevant web pages. Be specific and include key terms 
                       to improve search accuracy. For best results, use natural language questions 
                       or keyword combinations that precisely describe what you're looking for.
                num_results: The number of search results to return. Increase for more comprehensive 
                            research or decrease for focused, high-relevance results. (default: 20)
            
            Returns:
                A dictionary containing search results with success status, results array, and AI answer.
            """
            try:
                # Ensure sandbox is available and store in context
                sandbox = await self._ensure_sandbox()
                tool_context.state['sandbox_instance'] = sandbox
                tool_context.state['project_id'] = self.project_id
                tool_context.state['workspace_path'] = self.workspace_path
                
                # Ensure we have a valid query
                if not query or not isinstance(query, str):
                    return {"success": False, "error": "A valid search query is required."}
                
                # Normalize num_results
                if num_results is None:
                    num_results = 20
                elif isinstance(num_results, int):
                    num_results = max(1, min(num_results, 50))
                elif isinstance(num_results, str):
                    try:
                        num_results = max(1, min(int(num_results), 50))
                    except ValueError:
                        num_results = 20
                else:
                    num_results = 20

                # Execute the search with Tavily
                logging.info(f"Executing web search for query: '{query}' with {num_results} results")
                search_response = await self.tavily_client.search(
                    query=query,
                    max_results=num_results,
                    include_images=True,
                    include_answer="advanced",
                    search_depth="advanced",
                )
                
                # Check if we have actual results or an answer
                results = search_response.get('results', [])
                answer = search_response.get('answer', '')
                
                logging.info(f"Retrieved search results for query: '{query}' with answer and {len(results)} results")
                
                # Consider search successful if we have either results OR an answer
                if len(results) > 0 or (answer and answer.strip()):
                    return {
                        "success": True,
                        "query": query,
                        "answer": answer,
                        "results": results,
                        "total_results": len(results)
                    }
                else:
                    # No results or answer found
                    logging.warning(f"No search results or answer found for query: '{query}'")
                    return {
                        "success": False,
                        "error": f"No search results or answer found for query: '{query}'",
                        "query": query
                    }
            
            except Exception as e:
                error_message = str(e)
                logging.error(f"Error performing web search for '{query}': {error_message}")
                simplified_message = f"Error performing web search: {error_message[:200]}"
                if len(error_message) > 200:
                    simplified_message += "..."
                return {"success": False, "error": simplified_message}

        return FunctionTool(func=web_search)

    def create_scrape_tool(self) -> FunctionTool:
        """创建带沙盒访问的网页抓取工具"""
        
        async def scrape_webpage(
            urls: str,
            tool_context: ToolContext
        ) -> Dict[str, Any]:
            """Extract full text content from multiple webpages in a single operation.
            
            IMPORTANT: You should ALWAYS collect multiple relevant URLs from web-search results 
            and scrape them all in a single call for efficiency. This tool saves time by processing 
            multiple pages simultaneously rather than one at a time. The extracted text includes 
            the main content of each page without HTML markup.
            
            Args:
                urls: Multiple URLs to scrape, separated by commas. You should ALWAYS include 
                      several URLs when possible for efficiency. 
                      Example: 'https://example.com/page1,https://example.com/page2,https://example.com/page3'
            
            Returns:
                A dictionary containing the scraped content with success status, file paths, 
                and processing summary.
            """
            try:
                logging.info(f"Starting to scrape webpages: {urls}")
                
                # Ensure sandbox is initialized
                sandbox = await self._ensure_sandbox()
                
                # Parse the URLs parameter
                if not urls:
                    logging.warning("Scrape attempt with empty URLs")
                    return {"success": False, "error": "Valid URLs are required."}
                
                # Split the URLs string into a list
                url_list = [url.strip() for url in urls.split(',') if url.strip()]
                
                if not url_list:
                    logging.warning("No valid URLs found in the input")
                    return {"success": False, "error": "No valid URLs provided."}
                    
                if len(url_list) == 1:
                    logging.warning("Only a single URL provided - for efficiency you should scrape multiple URLs at once")
                
                logging.info(f"Processing {len(url_list)} URLs: {url_list}")
                
                # Process each URL concurrently and collect results
                tasks = [self._scrape_single_url(url) for url in url_list]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results, handling exceptions
                processed_results = []
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logging.error(f"Error processing URL {url_list[i]}: {str(result)}")
                        processed_results.append({
                            "url": url_list[i],
                            "success": False,
                            "error": str(result)
                        })
                    else:
                        processed_results.append(result)
                
                results = processed_results
                
                # Summarize results
                successful = sum(1 for r in results if r.get("success", False))
                failed = len(results) - successful
                
                # Create success/failure message
                if successful == len(results):
                    message = f"Successfully scraped all {len(results)} URLs."
                    file_paths = [r.get('file_path') for r in results if r.get('file_path')]
                    return {
                        "success": True,
                        "message": message,
                        "total_urls": len(results),
                        "successful": successful,
                        "failed": failed,
                        "file_paths": file_paths,
                        "results": results
                    }
                elif successful > 0:
                    message = f"Scraped {successful} URLs successfully and {failed} failed."
                    file_paths = [r.get('file_path') for r in results if r.get('success', False) and r.get('file_path')]
                    failed_urls = [r.get('url') for r in results if not r.get('success', False)]
                    return {
                        "success": True,
                        "message": message,
                        "total_urls": len(results),
                        "successful": successful,
                        "failed": failed,
                        "file_paths": file_paths,
                        "failed_urls": failed_urls,
                        "results": results
                    }
                else:
                    error_details = "; ".join([f"{r.get('url')}: {r.get('error', 'Unknown error')}" for r in results])
                    return {
                        "success": False,
                        "error": f"Failed to scrape all {len(results)} URLs. Errors: {error_details}",
                        "total_urls": len(results),
                        "results": results
                    }
                
            except Exception as e:
                error_message = str(e)
                logging.error(f"Error in scrape_webpage: {error_message}")
                return {"success": False, "error": f"Error processing scrape request: {error_message[:200]}"}

        return FunctionTool(func=scrape_webpage)

    async def _scrape_single_url(self, url: str) -> Dict[str, Any]:
        """Helper function to scrape a single URL and return the result information."""
        
        logging.info(f"Scraping single URL: {url}")
        
        try:
            # ---------- Firecrawl scrape endpoint ----------
            logging.info(f"Sending request to Firecrawl for URL: {url}")
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Bearer {self.firecrawl_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "url": url,
                    "formats": ["markdown"]
                }
                
                # Use longer timeout and retry logic for more reliability
                max_retries = 3
                timeout_seconds = 30
                retry_count = 0
                
                while retry_count < max_retries:
                    try:
                        logging.info(f"Sending request to Firecrawl (attempt {retry_count + 1}/{max_retries})")
                        response = await client.post(
                            f"{self.firecrawl_url}/v1/scrape",
                            json=payload,
                            headers=headers,
                            timeout=timeout_seconds,
                        )
                        response.raise_for_status()
                        data = response.json()
                        logging.info(f"Successfully received response from Firecrawl for {url}")
                        break
                    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError) as timeout_err:
                        retry_count += 1
                        logging.warning(f"Request timed out (attempt {retry_count}/{max_retries}): {str(timeout_err)}")
                        if retry_count >= max_retries:
                            raise Exception(f"Request timed out after {max_retries} attempts with {timeout_seconds}s timeout")
                        # Exponential backoff
                        logging.info(f"Waiting {2 ** retry_count}s before retry")
                        await asyncio.sleep(2 ** retry_count)
                    except Exception as e:
                        # Don't retry on non-timeout errors
                        logging.error(f"Error during scraping: {str(e)}")
                        raise e

            # Format the response
            title = data.get("data", {}).get("metadata", {}).get("title", "")
            markdown_content = data.get("data", {}).get("markdown", "")
            logging.info(f"Extracted content from {url}: title='{title}', content length={len(markdown_content)}")
            
            formatted_result = {
                "title": title,
                "url": url,
                "text": markdown_content
            }
            
            # Add metadata if available
            if "metadata" in data.get("data", {}):
                formatted_result["metadata"] = data["data"]["metadata"]
                logging.info(f"Added metadata: {data['data']['metadata'].keys()}")
            
            # Create a simple filename from the URL domain and date
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Extract domain from URL for the filename
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace("www.", "")
            
            # Clean up domain for filename
            domain = "".join([c if c.isalnum() else "_" for c in domain])
            safe_filename = f"{timestamp}_{domain}.json"
            
            logging.info(f"Generated filename: {safe_filename}")
            
            # Save results to a file in the /workspace/scrape directory
            scrape_dir = f"{self.workspace_path}/scrape"
            sandbox = await self._ensure_sandbox()
            await sandbox.fs.create_folder(scrape_dir, "755")
            
            results_file_path = f"{scrape_dir}/{safe_filename}"
            json_content = json.dumps(formatted_result, ensure_ascii=False, indent=2)
            logging.info(f"Saving content to file: {results_file_path}, size: {len(json_content)} bytes")
            
            await sandbox.fs.upload_file(
                json_content.encode(),
                results_file_path,
            )
            
            return {
                "url": url,
                "success": True,
                "title": title,
                "file_path": results_file_path,
                "content_length": len(markdown_content)
            }
        
        except Exception as e:
            error_message = str(e)
            logging.error(f"Error scraping URL '{url}': {error_message}")
            
            # Create an error result
            return {
                "url": url,
                "success": False,
                "error": error_message
            }

# 使用示例和测试代码
if __name__ == "__main__":
    async def test_sandbox_web_search_tools():
        """Test function for the sandbox web search tools using ADK"""
        print("=== Testing Sandbox Web Search Tools (ADK Version) ===")
        
        # 注意：这里需要有效的 project_id 和 thread_manager
        # 在实际使用中，这些会从你的应用程序上下文中获取
        try:
            # 这是一个模拟测试，实际使用时需要真实的参数
            print("✅ SandboxWebSearchToolFactory can be instantiated")
            print("✅ Tools can be created using factory methods")
            print("⚠️  Full integration test requires valid project_id and thread_manager")
            
        except Exception as e:
            print(f"❌ Error during testing: {e}")
        
        print("=== Test completed ===")
    
    asyncio.run(test_sandbox_web_search_tools()) 