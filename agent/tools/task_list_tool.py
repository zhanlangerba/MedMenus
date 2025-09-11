from agentpress.tool import Tool, ToolResult
from utils.logger import logger
from typing import List, Dict, Any, Optional
import json
import uuid

class TaskListTool(Tool):
    """Task management system for organizing and tracking tasks. It contains the action plan for the agent to follow.
    
    Features:
    - Create, update, and delete tasks organized by sections
    - Support for batch operations across multiple sections
    - Organize tasks into logical sections and workflows
    - Track completion status and progress
    """
    
    def __init__(self, project_id: str, thread_manager, thread_id: str):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.thread_id = thread_id
        self.task_list_message_type = "task_list"
    
    def _create_section(self, title: str) -> Dict[str, Any]:
        """Create a section dict without Pydantic"""
        return {
            "id": str(uuid.uuid4()),
            "title": title
        }
    
    def _create_task(self, content: str, section_id: str, status: str = "pending") -> Dict[str, Any]:
        """Create a task dict without Pydantic"""
        return {
            "id": str(uuid.uuid4()),
            "content": content,
            "status": status,
            "section_id": section_id
        }
    
    async def _load_data(self):
        """Load sections and tasks from storage - simplified return type"""
        try:
            client = await self.thread_manager.db.client
            result = await client.table('messages').select('*')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()
            
            if result.data and result.data[0].get('content'):
                content = result.data[0]['content']
                if isinstance(content, str):
                    content = json.loads(content)
                
                sections = content.get('sections', [])
                tasks = content.get('tasks', [])
                
                # Handle migration from old format
                if not sections and 'sections' in content:
                    # Create sections from old nested format
                    for old_section in content['sections']:
                        section = self._create_section(old_section['title'])
                        sections.append(section)
                        
                        # Update tasks to reference section ID
                        for old_task in old_section.get('tasks', []):
                            task = self._create_task(
                                old_task['content'], 
                                section['id'],
                                old_task.get('status', 'pending')
                            )
                            if 'id' in old_task:
                                task['id'] = old_task['id']
                            tasks.append(task)
                
                return sections, tasks
            
            # Return empty lists
            return [], []
            
        except Exception as e:
            logger.error(f"Error loading data: {e}")
            return [], []
    
    async def _save_data(self, sections: List[Dict], tasks: List[Dict]):
        """Save sections and tasks to storage - simplified types"""
        try:
            client = await self.thread_manager.db.client
            
            content = {
                'sections': sections,
                'tasks': tasks
            }
            
            # 序列化为JSON字符串 - PostgreSQL期望字符串类型
            content_json = json.dumps(content)
            metadata_json = json.dumps({})
            
            # Find existing message
            result = await client.table('messages').select('message_id')\
                .eq('thread_id', self.thread_id)\
                .eq('type', self.task_list_message_type)\
                .order('created_at', desc=True).limit(1).execute()
            
            if result.data:
                # Update existing
                await client.table('messages').update({'content': content_json})\
                    .eq('message_id', result.data[0]['message_id']).execute()
            else:
                # Create new
                await client.table('messages').insert({
                    'thread_id': self.thread_id,
                    'project_id': self.project_id,
                    'type': self.task_list_message_type,
                    'role': 'assistant',
                    'content': content_json,
                    'is_llm_message': False,
                    'metadata': metadata_json
                }).execute()
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            raise
    
    def _format_response(self, sections: List[Dict], tasks: List[Dict]) -> Dict[str, Any]:
        """Format data for response - simplified types"""
        # Group display tasks by section
        section_map = {s['id']: s for s in sections}
        grouped_tasks = {}
        
        for task in tasks:
            section_id = task['section_id']
            if section_id not in grouped_tasks:
                grouped_tasks[section_id] = []
            grouped_tasks[section_id].append(task)
        
        formatted_sections = []
        for section in sections:
            section_tasks = grouped_tasks.get(section['id'], [])
            # Only include sections that have tasks to display
            if section_tasks:
                formatted_sections.append({
                    "id": section['id'],
                    "title": section['title'],
                    "tasks": section_tasks
                })
        
        response = {
            "sections": formatted_sections,
            "total_tasks": len(tasks),
            "total_sections": len(sections)
        }
        
        return response

    async def view_tasks(self) -> ToolResult:
        """View all tasks and sections. Use this to see current tasks, check progress, or review completed work.
        
        IMPORTANT: This tool helps you identify the next task to execute in the sequential workflow. 
        Always execute tasks in the exact order they appear, completing one task fully before moving to the next. 
        Use this to determine which task is currently pending and should be tackled next.
        
        Returns:
            ToolResult: JSON containing sections with their tasks, total task count, and total section count.
        """
        try:
            sections, tasks = await self._load_data()
            response_data = self._format_response(sections, tasks)
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error viewing tasks: {e}")
            return ToolResult(success=False, output=f"❌ Error viewing tasks: {str(e)}")

    async def create_tasks(self, sections: Optional[List[Dict[str, Any]]] = None,
                          section_title: Optional[str] = None, section_id: Optional[str] = None,
                          task_contents: Optional[List[str]] = None) -> ToolResult:
        """Create tasks organized by sections. Supports both single section and multi-section batch creation.
        
        Creates sections automatically if they don't exist. IMPORTANT: Create tasks in the exact order they will be executed. 
        Each task should represent a single, specific operation that can be completed independently. 
        Break down complex operations into individual, sequential tasks to maintain the one-task-at-a-time execution principle.
        
        You MUST specify either 'sections' array OR both 'task_contents' and ('section_title' OR 'section_id').
        
        Args:
            sections: List of sections with their tasks for batch creation. Each section should have 'title' and 'tasks' fields.
                     Example: [{"title": "Setup & Planning", "tasks": ["Research requirements", "Create project plan"]}]
            section_title: Single section title (creates if doesn't exist - use this OR sections array)
            section_id: Existing section ID (use this OR sections array OR section_title)  
            task_contents: Task contents for single section creation (use with section_title or section_id)
                          Example: ["Fix login issue", "Update error handling"]
        
        Returns:
            ToolResult: JSON containing all sections with their tasks, total task count, and total section count.
        """
        try:
            existing_sections, existing_tasks = await self._load_data()
            section_map = {s['id']: s for s in existing_sections}
            title_map = {s['title'].lower(): s for s in existing_sections}
            
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
                        target_section = self._create_section(section_title_input)
                        existing_sections.append(target_section)
                        title_map[title_lower] = target_section
                    
                    # Create tasks in this section
                    for task_content in task_list:
                        new_task = self._create_task(task_content, target_section['id'])
                        existing_tasks.append(new_task)
                        
            else:
                # Single section creation
                if not task_contents:
                    return ToolResult(success=False, output="❌ Must provide either 'sections' array or 'task_contents' with section info")
                
                if not section_id and not section_title:
                    return ToolResult(success=False, output="❌ Must specify either 'section_id' or 'section_title' when using 'task_contents'")
                
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
                        target_section = self._create_section(section_title)
                        existing_sections.append(target_section)
                
                # Create tasks
                for content in task_contents:
                    new_task = self._create_task(content, target_section['id'])
                    existing_tasks.append(new_task)
            
            await self._save_data(existing_sections, existing_tasks)
            response_data = self._format_response(existing_sections, existing_tasks)
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error creating tasks: {e}")
            return ToolResult(success=False, output=f"❌ Error creating tasks: {str(e)}")

    async def update_tasks(self, task_ids, content: Optional[str] = None,
                          status: Optional[str] = None, section_id: Optional[str] = None) -> ToolResult:
        """Update one or more tasks. EFFICIENT BATCHING: Before calling this tool, think about what tasks you have completed and batch them into a single update call.
        
        This is more efficient than making multiple consecutive update calls. Always execute tasks in the exact sequence they appear, 
        but batch your updates when possible. Update task status to 'completed' after finishing each task, and consider batching 
        multiple completed tasks into one call rather than updating them individually.
        
        Args:
            task_ids: Task ID (string) or array of task IDs to update. EFFICIENT APPROACH: Batch multiple completed tasks 
                     into a single call rather than making multiple consecutive update calls. Always maintain sequential execution order.
                     Example: "task-uuid-here" or ["task-id-1", "task-id-2", "task-id-3"]
            content: New content for the task(s) (optional)
            status: New status for the task(s) (optional). Valid values: "pending", "completed", "cancelled". 
                   Set to 'completed' for finished tasks. Batch multiple completed tasks when possible.
            section_id: Section ID to move task(s) to (optional)
        
        Returns:
            ToolResult: JSON containing all sections with their tasks, total task count, and total section count.
        """
        try:
            # Normalize task_ids to always be a list
            if isinstance(task_ids, str):
                target_task_ids = [task_ids]
            else:
                target_task_ids = task_ids
            
            sections, tasks = await self._load_data()
            section_map = {s['id']: s for s in sections}
            task_map = {t['id']: t for t in tasks}
            
            # Validate all task IDs exist
            missing_tasks = [tid for tid in target_task_ids if tid not in task_map]
            if missing_tasks:
                return ToolResult(success=False, output=f"❌ Task IDs not found: {missing_tasks}")
            
            # Validate section ID if provided
            if section_id and section_id not in section_map:
                return ToolResult(success=False, output=f"❌ Section ID '{section_id}' not found")
            
            # Apply updates
            for tid in target_task_ids:
                task = task_map[tid]
                
                if content is not None:
                    task['content'] = content
                if status is not None:
                    task['status'] = status
                if section_id is not None:
                    task['section_id'] = section_id
            
            await self._save_data(sections, tasks)
            response_data = self._format_response(sections, tasks)
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error updating tasks: {e}")
            return ToolResult(success=False, output=f"❌ Error updating tasks: {str(e)}")

    async def delete_tasks(self, task_ids=None, section_ids=None, confirm: bool = False) -> ToolResult:
        """Delete one or more tasks and/or sections. Can delete tasks by their IDs or sections by their IDs (which will also delete all tasks in those sections).
        
        Args:
            task_ids: Task ID (string) or array of task IDs to delete (optional). 
                     Example: "task-uuid-here" or ["task-id-1", "task-id-2"]
            section_ids: Section ID (string) or array of section IDs to delete (will also delete all tasks in these sections) (optional).
                        Example: "section-uuid-here" or ["section-id-1", "section-id-2"]  
            confirm: Must be true to confirm deletion of sections (required when deleting sections)
        
        Returns:
            ToolResult: JSON containing remaining sections with their tasks, total task count, and total section count.
        """
        try:
            # Validate that at least one of task_ids or section_ids is provided
            if not task_ids and not section_ids:
                return ToolResult(success=False, output="❌ Must provide either task_ids or section_ids")
            
            # Validate confirm parameter for section deletion
            if section_ids and not confirm:
                return ToolResult(success=False, output="❌ Must set confirm=true to delete sections")
            
            sections, tasks = await self._load_data()
            section_map = {s['id']: s for s in sections}
            task_map = {t['id']: t for t in tasks}
            
            # Process task deletions
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
                remaining_tasks = [task for task in tasks if task['id'] not in task_id_set]
            
            # Process section deletions
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
                remaining_sections = [s for s in sections if s['id'] not in section_id_set]
                remaining_tasks = [t for t in remaining_tasks if t['section_id'] not in section_id_set]
            
            await self._save_data(remaining_sections, remaining_tasks)
            response_data = self._format_response(remaining_sections, remaining_tasks)
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error deleting tasks/sections: {e}")
            return ToolResult(success=False, output=f"❌ Error deleting tasks/sections: {str(e)}")

    async def clear_all(self, confirm: bool) -> ToolResult:
        """Clear all tasks and sections (creates completely empty state).
        
        Args:
            confirm: Must be true to confirm clearing everything
        
        Returns:
            ToolResult: JSON containing empty sections array, with total task count and section count set to 0.
        """
        try:
            if not confirm:
                return ToolResult(success=False, output="❌ Must set confirm=true to clear all data")
            
            # Create completely empty state
            sections = []
            tasks = []
            
            await self._save_data(sections, tasks)
            response_data = self._format_response(sections, tasks)
            return ToolResult(success=True, output=json.dumps(response_data, indent=2))
            
        except Exception as e:
            logger.error(f"Error clearing all data: {e}")
            return ToolResult(success=False, output=f"❌ Error clearing all data: {str(e)}")

