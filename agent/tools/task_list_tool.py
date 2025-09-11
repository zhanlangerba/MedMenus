from agentpress.tool import Tool, ToolResult
from utils.logger import logger
from typing import List, Dict, Any, Optional, Tuple
import json
from pydantic import BaseModel, Field # type: ignore
from enum import Enum
import uuid
import asyncio
import sys



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

class TaskListTool(Tool):
    """Simplified task management system - no extra class definitions."""
    
    def __init__(self, project_id: str, thread_manager, thread_id: str):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.thread_id = thread_id
        self.task_list_message_type = "task_list"
    
    async def _load_data(self) -> Tuple[List[Section], List[Task]]:
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
                
                # Debug logging for data loading
                sections_data = content.get('sections', [])
                tasks_data = content.get('tasks', [])
                logger.debug(f"Loading {len(sections_data)} sections and {len(tasks_data)} tasks")
                
                sections = []
                for i, s in enumerate(sections_data):
                    try:
                        section = Section(**s)
                        sections.append(section)
                        logger.debug(f"Created section {i}: {section.id}")
                    except Exception as e:
                        logger.error(f"Error creating section {i}: {e}, data: {s}")
                        raise
                        
                tasks = []
                for i, t in enumerate(tasks_data):
                    try:
                        # Check for coroutines in raw task data before creating Task object
                        logger.debug(f"Raw task data {i}: {t}")
                        if 'status' in t and asyncio.iscoroutine(t['status']):
                            logger.error(f"❌ FOUND COROUTINE in raw task data status for task {i}: {t['status']}")
                            t['status'] = 'pending'  # Fix it
                        
                        task = Task(**t)
                        
                        # Double check the created task for coroutines
                        if asyncio.iscoroutine(task.status):
                            logger.error(f"❌ FOUND COROUTINE in task.status after creation: {task.status}")
                            task.status = TaskStatus.PENDING
                            
                        tasks.append(task)
                        logger.debug(f"Created task {i}: {task.id}, status: {repr(task.status)}")
                    except Exception as e:
                        logger.error(f"Error creating task {i}: {e}, data: {t}")
                        raise
                
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

            # EMERGENCY DEBUG: Check for coroutines in tasks before serialization
            print(f"🔍 _save_data: Processing {len(tasks)} tasks for serialization", file=sys.stderr)
            
            for i, task in enumerate(tasks):
                print(f"🔍 Task {i} - id: {task.id}", file=sys.stderr)
                print(f"🔍 Task {i} - content type: {type(task.content)}", file=sys.stderr)
                print(f"🔍 Task {i} - status type: {type(task.status)}, value: {repr(task.status)}", file=sys.stderr)
                print(f"🔍 Task {i} - section_id type: {type(task.section_id)}", file=sys.stderr)
                
                # Check each field for coroutines with emergency debug
                if asyncio.iscoroutine(task.status):
                    print(f"❌ FOUND COROUTINE in task.status for task {task.id}: {task.status}", file=sys.stderr)
                    task.status = TaskStatus.PENDING
                    print(f"✅ FIXED: Set status to PENDING", file=sys.stderr)
                    
                if asyncio.iscoroutine(task.content):
                    print(f"❌ FOUND COROUTINE in task.content for task {task.id}: {task.content}", file=sys.stderr)
                    task.content = "ERROR: Content was a coroutine"
                    
                if asyncio.iscoroutine(task.section_id):
                    print(f"❌ FOUND COROUTINE in task.section_id for task {task.id}: {task.section_id}", file=sys.stderr)
                    task.section_id = "default-section"
                    
                # Try to call model_dump to see where the error occurs
                try:
                    print(f"🧪 Testing model_dump for task {i}...", file=sys.stderr)
                    dump_result = task.model_dump()
                    print(f"✅ model_dump success for task {i}", file=sys.stderr)
                except Exception as model_dump_error:
                    print(f"❌ model_dump FAILED for task {i}: {model_dump_error}", file=sys.stderr)
                    print(f"   Task object: {task}", file=sys.stderr)
                    print(f"   Task.__dict__: {task.__dict__}", file=sys.stderr)
                    # Try to identify which field is the problem
                    for field_name in ['id', 'content', 'status', 'section_id']:
                        try:
                            field_value = getattr(task, field_name)
                            print(f"   {field_name}: {type(field_value)} = {repr(field_value)}", file=sys.stderr)
                            if asyncio.iscoroutine(field_value):
                                print(f"   ❌ FIELD {field_name} IS COROUTINE!", file=sys.stderr)
                        except Exception as field_error:
                            print(f"   ❌ Error accessing field {field_name}: {field_error}", file=sys.stderr)
            
            # EMERGENCY DEBUG: Test content creation 
            print(f"🔍 Creating content dict with {len(sections)} sections and {len(tasks)} tasks", file=sys.stderr)
            try:
                sections_data = []
                for i, section in enumerate(sections):
                    print(f"🔍 Processing section {i}: {section.id}", file=sys.stderr)
                    section_dump = section.model_dump()
                    sections_data.append(section_dump)
                    print(f"✅ Section {i} model_dump success", file=sys.stderr)
                
                tasks_data = []
                for i, task in enumerate(tasks):
                    print(f"🔍 Processing task {i} for content creation: {task.id}", file=sys.stderr)
                    try:
                        task_dump = task.model_dump()
                        tasks_data.append(task_dump)
                        print(f"✅ Task {i} model_dump success in content creation", file=sys.stderr)
                    except Exception as task_dump_error:
                        print(f"❌ Task {i} model_dump FAILED in content creation: {task_dump_error}", file=sys.stderr)
                        raise
                
                content = {
                    'sections': sections_data,
                    'tasks': tasks_data
                }
                print(f"✅ Content dict created successfully", file=sys.stderr)
                
            except Exception as content_error:
                print(f"❌ CONTENT CREATION FAILED: {content_error}", file=sys.stderr)
                raise
            
            
            # 找到已经存在的message
            result = await client.table('messages').select('message_id')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()
            
            # Check if existing message found
            print(f"🔍 Database query completed: {len(result.data) if result.data else 0} records found", file=sys.stderr)
            
            # Serialize content to JSON
            try:
                json_content = json.dumps(content)
                print(f"✅ JSON serialization successful, length: {len(json_content)}", file=sys.stderr)
            except Exception as json_error:
                print(f"❌ JSON serialization failed: {json_error}", file=sys.stderr)
                raise
                
            if result.data:
                # Update existing
                print(f"🔍 Updating existing message", file=sys.stderr)
                message_id_for_update = result.data[0]['message_id']
                print(f"🔍 About to update with message_id: {message_id_for_update} (type: {type(message_id_for_update)})", file=sys.stderr)
                
                # FIXED: Correct order - set condition first, then call update() (async method)
                # update() returns a coroutine directly, cannot chain .eq() after it
                await client.table('messages')\
                    .eq('message_id', message_id_for_update)\
                    .update({'content': json_content})
                print(f"✅ Update operation completed successfully", file=sys.stderr)
            else:
                # 创建新的
                print(f"🔍 Inserting new message", file=sys.stderr)
                await client.table('messages').insert({
                    'thread_id': self.thread_id,
                    'project_id': self.project_id,
                    'type': self.task_list_message_type,
                    'role': 'assistant',
                    'content': json_content,
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
        
        This function creates a structured task list organized into sections, supporting both 
        single section and multi-section batch creation. Creates sections automatically if they don't exist.
        Tasks should be created in the exact order they will be executed for sequential workflow.
        
        Usage Examples:
            # Batch creation across multiple sections:
            <function_calls>
            <invoke name="create_tasks">
            <parameter name="sections">[
                {
                    "title": "Setup & Planning", 
                    "tasks": ["Research requirements", "Create project plan"]
                },
                {
                    "title": "Development", 
                    "tasks": ["Setup environment", "Write code", "Add tests"]
                },
                {
                    "title": "Deployment", 
                    "tasks": ["Deploy to staging", "Run tests", "Deploy to production"]
                }
            ]</parameter>
            </invoke>
            </function_calls>
            
            # Simple single section creation:
            <function_calls>
            <invoke name="create_tasks">
            <parameter name="section_title">Bug Fixes</parameter>
            <parameter name="task_contents">["Fix login issue", "Update error handling"]</parameter>
            </invoke>
            </function_calls>
        
        Args:
            sections: List of sections with their tasks for batch creation. Each section should have 'title' and 'tasks' fields.
                     Example: [{"title": "Setup & Planning", "tasks": ["Research requirements", "Create project plan"]}]
            section_title: Single section title (creates if doesn't exist - use this OR sections array)
            section_id: Existing section ID (use this OR sections array OR section_title)  
            task_contents: Task contents for single section creation (use with section_title or section_id)
                          Example: ["Fix login issue", "Update error handling"]
        
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
        
    async def view_tasks(self) -> ToolResult:
        """View all current tasks and sections for project management.

        This function retrieves and displays the complete task structure organized by sections,
        helping agents track progress, identify next actions, and review completed work.
        Essential for sequential workflow execution - always check current state before proceeding.
        
        Usage Example:
            <function_calls>
            <invoke name="view_tasks">
            </invoke>
            </function_calls>
                
        Returns:
            ToolResult: Success with JSON string of complete task structure, or failure with error message.
        """
        try:
            sections, tasks = await self._load_data()
            
            response_data = self._format_response(sections, tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error viewing tasks: {e}")
            return ToolResult(success=False, output=f"❌ Error viewing tasks: {str(e)}")

    async def update_tasks(self, task_ids: Any, content: Optional[str] = None,
                          status: Optional[str] = None, section_id: Optional[str] = None) -> ToolResult:
        """Update one or more tasks for project management.

        This function updates task properties such as status, content, or section assignment.
        EFFICIENT BATCHING: Consider batching multiple completed tasks into a single update call
        rather than making multiple consecutive update calls for better performance.
        
        Usage Examples:
            # Update single task (when only one task is completed):
            <function_calls>
            <invoke name="update_tasks">
            <parameter name="task_ids">task-uuid-here</parameter>
            <parameter name="status">completed</parameter>
            </invoke>
            </function_calls>
            
            # Update multiple tasks (EFFICIENT: batch multiple completed tasks):
            <function_calls>
            <invoke name="update_tasks">
            <parameter name="task_ids">["task-id-1", "task-id-2", "task-id-3"]</parameter>
            <parameter name="status">completed</parameter>
            </invoke>
            </function_calls>
        
        Args:
            task_ids: Task ID (string) or array of task IDs to update. 
                     Example: "task-uuid-here" or ["task-id-1", "task-id-2", "task-id-3"]
            content: New content for the task(s) (optional)
            status: New status for the task(s) (optional). Valid values: "pending", "completed", "cancelled"
            section_id: Section ID to move task(s) to (optional)
        
        Returns:
            ToolResult: Success with JSON string of updated task structure, or failure with error message.
        """
        try:
            import traceback
            
            # Normalize task_ids to always be a list
            if isinstance(task_ids, str):
                target_task_ids = [task_ids]
            else:
                target_task_ids = task_ids
            
            sections, tasks = await self._load_data()
            section_map = {s.id: s for s in sections}
            task_map = {t.id: t for t in tasks}
            
            # Validate all task IDs exist
            missing_tasks = [tid for tid in target_task_ids if tid not in task_map]
            if missing_tasks:
                return ToolResult(success=False, output=f"❌ Task IDs not found: {missing_tasks}")
            
            # Validate section ID if provided
            if section_id and section_id not in section_map:
                return ToolResult(success=False, output=f"❌ Section ID '{section_id}' not found")
            
            # Apply updates
            updated_count = 0
            for tid in target_task_ids:
                try:
                    task = task_map[tid]
                    logger.debug(f"Updating task {tid}, current type: {type(task)}")
                    
                    if content is not None:
                        task.content = content
                        logger.debug(f"Updated content for task {tid}")
                        
                    if status is not None:
                        # Add debug logging and safer status conversion
                        logger.debug(f"Updating status for task {tid}, status type: {type(status)}, value: {repr(status)}")
                        try:
                            # Ensure status is a string - handle potential coroutine objects
                            if asyncio.iscoroutine(status):
                                logger.error(f"ERROR: status parameter is a coroutine object: {status}")
                                status_str = "pending"  # Default fallback
                            else:
                                status_str = str(status) if status is not None else "pending"
                            
                            # Create new status enum
                            new_status = TaskStatus(status_str)
                            
                            # Additional safety check before assignment
                            if asyncio.iscoroutine(new_status):
                                logger.error(f"ERROR: new_status is still a coroutine: {new_status}")
                                new_status = TaskStatus.PENDING
                            
                            # Use Pydantic's validation by creating a new Task object instead of direct assignment
                            # This ensures validation is triggered
                            try:
                                updated_task = Task(
                                    id=task.id,
                                    content=task.content,
                                    status=new_status,
                                    section_id=task.section_id
                                )
                                # Copy the validated values back
                                task.status = updated_task.status
                            except Exception as validation_error:
                                logger.error(f"Pydantic validation failed for task {tid}: {validation_error}")
                                task.status = TaskStatus.PENDING  # Safe fallback
                            
                            logger.debug(f"Successfully updated status for task {tid} to {repr(task.status)}")
                        except Exception as status_error:
                            logger.error(f"Error updating status for task {tid}: {status_error}")
                            raise
                            
                    if section_id is not None:
                        task.section_id = section_id
                        logger.debug(f"Updated section_id for task {tid}")
                    
                    updated_count += 1
                    
                except Exception as task_error:
                    logger.error(f"Error processing task {tid}: {task_error}")
                    logger.error(f"Task object type: {type(task_map.get(tid))}")
                    raise
            
            await self._save_data(sections, tasks)
            
            response_data = self._format_response(sections, tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error updating tasks: {e}")
            return ToolResult(success=False, output=f"❌ Error updating tasks: {str(e)}")
    
    async def delete_tasks(self, task_ids: Optional[Any] = None, section_ids: Optional[Any] = None, confirm: bool = False) -> ToolResult:
        """Delete one or more tasks and/or sections for project management.

        This function removes tasks by their IDs and/or sections by their IDs. 
        When deleting sections, all tasks within those sections are also deleted.
        Section deletion requires explicit confirmation for safety.
        
        Usage Examples:
            # Delete single task:
            <function_calls>
            <invoke name="delete_tasks">
            <parameter name="task_ids">task-uuid-here</parameter>
            </invoke>
            </function_calls>
            
            # Delete multiple tasks:
            <function_calls>
            <invoke name="delete_tasks">
            <parameter name="task_ids">["task-id-1", "task-id-2"]</parameter>
            </invoke>
            </function_calls>
            
            # Delete single section (and all its tasks):
            <function_calls>
            <invoke name="delete_tasks">
            <parameter name="section_ids">section-uuid-here</parameter>
            <parameter name="confirm">true</parameter>
            </invoke>
            </function_calls>
            
            # Delete multiple sections (and all their tasks):
            <function_calls>
            <invoke name="delete_tasks">
            <parameter name="section_ids">["section-id-1", "section-id-2"]</parameter>
            <parameter name="confirm">true</parameter>
            </invoke>
            </function_calls>
            
            # Delete both tasks and sections:
            <function_calls>
            <invoke name="delete_tasks">
            <parameter name="task_ids">["task-id-1", "task-id-2"]</parameter>
            <parameter name="section_ids">["section-id-1"]</parameter>
            <parameter name="confirm">true</parameter>
            </invoke>
            </function_calls>
        
        Args:
            task_ids: Task ID (string) or array of task IDs to delete (optional). 
                     Example: "task-uuid-here" or ["task-id-1", "task-id-2"]
            section_ids: Section ID (string) or array of section IDs to delete (optional).
                        Example: "section-uuid-here" or ["section-id-1", "section-id-2"]  
            confirm: Must be true to confirm deletion of sections (required when deleting sections)
        
        Returns:
            ToolResult: Success with JSON string of remaining task structure, or failure with error message.
        """
        try:
            # Validate that at least one of task_ids or section_ids is provided
            if not task_ids and not section_ids:
                return ToolResult(success=False, output="❌ Must provide either task_ids or section_ids")
            
            # Validate confirm parameter for section deletion
            if section_ids and not confirm:
                return ToolResult(success=False, output="❌ Must set confirm=true to delete sections")
            
            sections, tasks = await self._load_data()
            section_map = {s.id: s for s in sections}
            task_map = {t.id: t for t in tasks}
            
            # Process task deletions
            deleted_tasks = 0
            remaining_tasks = tasks.copy()
            if task_ids:
                # Normalize task_ids to always be a list
                if isinstance(task_ids, str):
                    target_task_ids = [task_ids]
                else:
                    target_task_ids = task_ids
                
                # Validate all task IDs exist
                missing_tasks = [tid for tid in target_task_ids if tid not in task_map]
                if missing_tasks:
                    return ToolResult(success=False, output=f"❌ Task IDs not found: {missing_tasks}")
                
                # Remove tasks
                task_id_set = set(target_task_ids)
                remaining_tasks = [task for task in tasks if task.id not in task_id_set]
                deleted_tasks = len(tasks) - len(remaining_tasks)
            
            # Process section deletions
            deleted_sections = 0
            remaining_sections = sections.copy()
            if section_ids:
                # Normalize section_ids to always be a list
                if isinstance(section_ids, str):
                    target_section_ids = [section_ids]
                else:
                    target_section_ids = section_ids
                
                # Validate all section IDs exist
                missing_sections = [sid for sid in target_section_ids if sid not in section_map]
                if missing_sections:
                    return ToolResult(success=False, output=f"❌ Section IDs not found: {missing_sections}")
                
                # Remove sections and their tasks
                section_id_set = set(target_section_ids)
                remaining_sections = [s for s in sections if s.id not in section_id_set]
                remaining_tasks = [t for t in remaining_tasks if t.section_id not in section_id_set]
                deleted_sections = len(sections) - len(remaining_sections)
            
            await self._save_data(remaining_sections, remaining_tasks)
            
            response_data = self._format_response(remaining_sections, remaining_tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error deleting tasks/sections: {e}")
            return ToolResult(success=False, output=f"❌ Error deleting tasks/sections: {str(e)}")

    async def clear_all(self, confirm: bool) -> ToolResult:
        """Clear all tasks and sections for project management.

        This function removes all tasks and sections from the project, creating a completely clean slate.
        This is a destructive operation that requires explicit confirmation for safety.
        
        Usage Example:
            <function_calls>
            <invoke name="clear_all">
            <parameter name="confirm">true</parameter>
            </invoke>
            </function_calls>
        
        Args:
            confirm: Must be true to confirm clearing everything
        
        Returns:
            ToolResult: Success with JSON string showing empty task structure, or failure with error message.
        """
        try:
            if not confirm:
                return ToolResult(success=False, output="❌ Must set confirm=true to clear all data")
            
            # Create completely empty state - no default section
            sections = []
            tasks = []
            
            await self._save_data(sections, tasks)
            
            response_data = self._format_response(sections, tasks)
            
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error clearing all data: {e}")
            return ToolResult(success=False, output=f"❌ Error clearing all data: {str(e)}")
   
if __name__ == "__main__":
    pass