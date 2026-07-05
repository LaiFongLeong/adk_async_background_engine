import asyncio
import time
import uuid
import logging
from typing import Dict, Any, List, Optional

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TaskEngine")

class Task:
    def __init__(self, task_id: str, agent_name: str, prompt: str):
        self.task_id = task_id
        self.agent_name = agent_name
        self.prompt = prompt
        self.status = "queued"  # queued, running, paused, completed, failed, killed
        self.progress = 0.0     # 0 to 100
        self.logs: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.completed_at: Optional[float] = None
        self.runner_task: Optional[asyncio.Task] = None
        
        # Sync control synchronization primitives
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # Initial state is NOT paused (event is set)
        
        # Human-in-the-loop (HITL) input primitives
        self.input_queue = asyncio.Queue()
        self.waiting_for_input = False
        self.input_prompt = ""
        
    def add_log(self, text: str, level: str = "INFO"):
        log_entry = {
            "timestamp": time.time(),
            "text": text,
            "level": level
        }
        self.logs.append(log_entry)
        logger.info(f"[{self.task_id}] [{level}] {text}")

    async def wait_if_paused(self):
        """Wait if the pause event is cleared (paused)."""
        if not self.pause_event.is_set():
            self.add_log("Task paused. Waiting for resume...", "WARN")
            await self.pause_event.wait()
            self.add_log("Task resumed.", "INFO")

    async def request_user_input(self, prompt: str) -> str:
        """Blocks execution until the user supplies input via the queue."""
        self.waiting_for_input = True
        self.input_prompt = prompt
        self.add_log(f"WAITING FOR USER INPUT: {prompt}", "WARN")
        
        # We need to yield control and wait for user input
        # Note: if the task is paused while waiting for input, the input queue will still await.
        # So we wait for the item in the queue.
        user_response = await self.input_queue.get()
        
        self.waiting_for_input = False
        self.input_prompt = ""
        self.add_log(f"Received user input: '{user_response}'", "INFO")
        return user_response

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "prompt": self.prompt,
            "status": self.status,
            "progress": round(self.progress, 1),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "waiting_for_input": self.waiting_for_input,
            "input_prompt": self.input_prompt,
            "log_count": len(self.logs)
        }

class AsyncTaskEngine:
    def __init__(self):
        self.tasks: Dict[str, Task] = {}

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def create_task(self, agent_name: str, prompt: str) -> Task:
        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id, agent_name, prompt)
        self.tasks[task_id] = task
        return task

    def start_task(self, task_id: str, coro) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        
        task.status = "running"
        task.add_log("Initializing background task execution environment...", "INFO")
        
        # Start the coroutine as an asyncio background task
        task.runner_task = asyncio.create_task(coro)
        return True

    def pause_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task or task.status != "running":
            return False
        
        task.status = "paused"
        task.pause_event.clear()  # Clearing blocks execution in wait_if_paused
        return True

    def resume_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task or task.status != "paused":
            return False
        
        task.status = "running"
        task.pause_event.set()  # Setting event unblocks execution
        return True

    async def kill_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task or task.status in ["completed", "failed", "killed"]:
            return False
        
        task.status = "killed"
        task.completed_at = time.time()
        
        # Unblock any waits
        task.pause_event.set()
        
        if task.runner_task:
            task.runner_task.cancel()
            try:
                await task.runner_task
            except asyncio.CancelledError:
                pass
        
        task.add_log("Task forcefully terminated by user.", "ERROR")
        return True

    async def remove_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        
        # If task is active, kill/cancel it first
        if task.status in ["queued", "running", "paused"]:
            await self.kill_task(task_id)
            
        # Delete from tracking registry
        if task_id in self.tasks:
            del self.tasks[task_id]
        return True

    async def send_input(self, task_id: str, user_input: str) -> bool:
        task = self.get_task(task_id)
        if not task or not task.waiting_for_input:
            return False
        
        await task.input_queue.put(user_input)
        return True

    def get_all_tasks_metadata(self) -> List[Dict[str, Any]]:
        return [task.to_dict() for task in self.tasks.values()]
