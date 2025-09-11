from agentpress.tool import Tool, ToolResult
from utils.logger import logger
from typing import List, Dict, Any, Optional
import json
from utils.logger import logger
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field # type: ignore
from enum import Enum
import json
import uuid
from agentpress.tool import ToolResult, usage_example



class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class Section(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    
class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    status: TaskStatus = TaskStatus.PENDING
    section_id: str  # Reference to section ID instead of section name

class TaskListToolSimple(Tool):
    """Simplified task management system - no extra class definitions."""
    
    def __init__(self, project_id: str, thread_manager, thread_id: str):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.thread_id = thread_id
        self.task_list_message_type = "task_list"
    
    async def _load_data(self) -> tuple[List[Section], List[Task]]:
        """Load sections and tasks from storage"""
        try:
            client = await self.thread_manager.db.client
            logger.info(f"Load data - Client type: {type(client)}")
            result = await client.table('messages').select('*')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()
            
            if result.data and result.data[0].get('content'):
                content = result.data[0]['content']
                if isinstance(content, str):
                    content = json.loads(content)
                
                sections = [Section(**s) for s in content.get('sections', [])]
                tasks = [Task(**t) for t in content.get('tasks', [])]
                
                # Handle migration from old format
                if not sections and 'sections' in content:
                    # Create sections from old nested format
                    for old_section in content['sections']:
                        section = Section(title=old_section['title'])
                        sections.append(section)
                        
                        # Update tasks to reference section ID
                        for old_task in old_section.get('tasks', []):
                            task = Task(
                                content=old_task['content'],
                                status=TaskStatus(old_task.get('status', 'pending')),
                                section_id=section.id
                            )
                            if 'id' in old_task:
                                task.id = old_task['id']
                            tasks.append(task)
                
                return sections, tasks
            
            # Return empty lists - no default section
            return [], []
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            return [], []
    
    async def _save_data(self, sections: List[Section], tasks: List[Task]):
        """Save sections and tasks to storage"""
        try:
            client = await self.thread_manager.db.client
            logger.info(f"Save data - Client type: {type(client)}")
            
            #    'section_title': '研究与准备',
            #   'task_contents': [
            #    '从TripAdvisor收集关于巴黎旅行的基本信息。',
            #    '搜索巴黎的热门景点、餐厅和活动。',
            #    '查找巴黎的交通选项及建议。',
            #    '收集巴黎的天气预报信息。',
            #    '确定潜在的备用计划（如遇到不可预见的情况）。',
            #]

            content = {
                'sections': [section.model_dump() for section in sections],
                'tasks': [task.model_dump() for task in tasks]
            }
            
            
            # 找到已经存在的message
            result = await client.table('messages').select('message_id')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()
            
            if result.data:
                # Update existing
                await client.table('messages').update({'content': json.dumps(content)})\
                    .eq('message_id', result.data[0]['message_id']).execute()
            else:
                # 创建新的
                await client.table('messages').insert({
                    'thread_id': self.thread_id,
                    'project_id': self.project_id,
                    'type': self.task_list_message_type,
                    'role': 'assistant',
                    'content': json.dumps(content),
                    'is_llm_message': False,
                    'metadata': json.dumps({})
                })
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            raise

    def _format_response(self, sections: List[Section], tasks: List[Task]) -> Dict[str, Any]:
        """Format data for response"""
        # 展示任务时，按照section分组
        section_map = {s.id: s for s in sections}
        grouped_tasks = {}
        
        # 遍历
        for task in tasks:
            section_id = task.section_id
            if section_id not in grouped_tasks:
                grouped_tasks[section_id] = []
            grouped_tasks[section_id].append(task.model_dump())
        
        formatted_sections = []
        for section in sections:
            section_tasks = grouped_tasks.get(section.id, [])
            # 只展示有任务的section
            if section_tasks:
                formatted_sections.append({
                    "id": section.id,
                    "title": section.title,
                    "tasks": section_tasks
                })
        
        response = {
            "sections": formatted_sections,
            "total_tasks": len(tasks),  # 总是使用原始任务数量
            "total_sections": len(sections)
        }
        
        return response

    async def create_tasks(self, sections: Optional[List[Dict[str, Any]]] = None,
                          section_title: Optional[str] = None, section_id: Optional[str] = None,
                          task_contents: Optional[List[str]] = None) -> ToolResult:
        """Create tasks organized by sections for project management.
    
        This function creates a structured task list organized into sections,
        which helps agents plan and track work systematically.
        
        Args:
            sections: List of section objects. Each section must contain:
                - title (str): Name of the section (e.g., "Planning", "Development")  
                - tasks (List[str]): List of task descriptions
            section_title: Title for creating a single section (optional)
            section_id: ID of existing section to add tasks to (optional)
            task_contents: List of task contents for single section mode (optional)
                
        Example:
            sections = [
                {
                    "title": "Setup & Planning", 
                    "tasks": ["Research requirements", "Create project plan", "Setup environment"]
                },
                {
                    "title": "Development", 
                    "tasks": ["Write core functionality", "Add unit tests", "Code review"]
                }
            ]
        
        Returns:
            ToolResult: Success with JSON string of created task structure, or failure with error message.
        """
        try:
            existing_sections, existing_tasks = await self._load_data()
    
            section_map = {s.id: s for s in existing_sections}
            title_map = {s.title.lower(): s for s in existing_sections}
        
            created_tasks = 0
            created_sections = 0
      
            if sections:
                # Batch creation across multiple sections
                for section_data in sections:
                    section_title_input = section_data["title"]
                    task_list = section_data["tasks"]
                    
                    # Find or create section
                    title_lower = section_title_input.lower()
                    if title_lower in title_map:
                        target_section = title_map[title_lower]
                    else:
                        target_section = Section(title=section_title_input)
                        existing_sections.append(target_section)
                        title_map[title_lower] = target_section
                        created_sections += 1
                    
                    # Create tasks in this section
                    for task_content in task_list:
                        new_task = Task(content=task_content, section_id=target_section.id)
                        existing_tasks.append(new_task)
                        created_tasks += 1
                        
            else:
                # 单个section创建 - 需要显式指定section
                if not task_contents:
                    return ToolResult(success=False, output="❌ 必须提供 'sections' 数组或 'task_contents' 与 section 信息")
                
                # 如果没有指定section信息，创建默认section
                if not section_id and not section_title:
                    section_title = "Tasks"  # 设置默认section标题
                
                target_section = None
                
                if section_id:
                    # Use existing section ID
                    if section_id not in section_map:
                        return ToolResult(success=False, output=f"❌ Section ID '{section_id}' not found")
                    target_section = section_map[section_id]
                    
                elif section_title:
                    # Find or create section by title
                    title_lower = section_title.lower()
                    if title_lower in title_map:
                        target_section = title_map[title_lower]
                    else:
                        target_section = Section(title=section_title)
                        existing_sections.append(target_section)
                        created_sections += 1
                
                # Create tasks
                for content in task_contents:
                    new_task = Task(content=content, section_id=target_section.id)
                    existing_tasks.append(new_task)
                    created_tasks += 1
            
            await self._save_data(existing_sections, existing_tasks)
            
            response_data = self._format_response(existing_sections, existing_tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error creating tasks: {e}")
            return ToolResult(success=False, output=f"❌ Error creating tasks: {str(e)}")
        


   
if __name__ == "__main__":
    pass