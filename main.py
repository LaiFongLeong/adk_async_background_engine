import asyncio
import os
import psutil
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, Dict, List

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from engine import AsyncTaskEngine
from agent_workflow import run_agent_task

load_dotenv()

app = FastAPI(title="Python ADK Background Task Engine")

# Instantiate our task engine
engine = AsyncTaskEngine()
CHAT_MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")

# Ensure the static directories exist
os.makedirs("static", exist_ok=True)

# Mount static folder
app.mount("/static", StaticFiles(directory="static"), name="static")


def tool_create_background_task(agent_name: str, prompt: str) -> Dict[str, Any]:
    if agent_name not in ["Researcher", "Coder", "DataCruncher"]:
        return {
            "ok": False,
            "error": "Invalid agent_name. Choose Researcher, Coder, or DataCruncher.",
        }

    task = engine.create_task(agent_name, prompt)
    started = engine.start_task(task.task_id, run_agent_task(task))
    return {
        "ok": started,
        "task_id": task.task_id,
        "agent_name": task.agent_name,
        "status": task.status,
        "prompt": task.prompt,
    }


def tool_list_tasks(limit: int = 20) -> Dict[str, Any]:
    all_tasks = engine.get_all_tasks_metadata()
    return {
        "count": len(all_tasks),
        "tasks": all_tasks[-max(1, limit):],
    }


def tool_get_task(task_id: str) -> Dict[str, Any]:
    task = engine.get_task(task_id)
    if not task:
        return {"ok": False, "error": "Task not found", "task_id": task_id}

    details = task.to_dict()
    details["latest_logs"] = task.logs[-20:]
    return {"ok": True, "task": details}


def tool_pause_task(task_id: str) -> Dict[str, Any]:
    success = engine.pause_task(task_id)
    return {
        "ok": success,
        "task_id": task_id,
        "message": "Task paused" if success else "Could not pause task",
    }


def tool_resume_task(task_id: str) -> Dict[str, Any]:
    success = engine.resume_task(task_id)
    return {
        "ok": success,
        "task_id": task_id,
        "message": "Task resumed" if success else "Could not resume task",
    }


coordinator_agent = Agent(
    name="coordinator_chat_agent",
    model=CHAT_MODEL,
    instruction=(
        "You are the main-thread coordinator chat agent for a background task engine. "
        "Use tools to create, inspect, pause, and resume tasks when requested. "
        "Ask concise clarification questions if required parameters are missing. "
        "When reporting task actions, include task_id and current status."
    ),
    tools=[
        tool_create_background_task,
        tool_list_tasks,
        tool_get_task,
        tool_pause_task,
        tool_resume_task,
    ],
)

coordinator_sessions = InMemorySessionService()
coordinator_runner = Runner(
    app_name="adk_async_background_engine_chat",
    agent=coordinator_agent,
    session_service=coordinator_sessions,
)

class CreateTaskRequest(BaseModel):
    agent_name: str
    prompt: str

class SendInputRequest(BaseModel):
    user_input: str

@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

@app.post("/api/tasks")
async def create_task(req: CreateTaskRequest):
    if req.agent_name not in ["Researcher", "Coder", "DataCruncher"]:
        raise HTTPException(status_code=400, detail="Invalid agent_name. Choose Coder, Researcher, or DataCruncher.")
        
    task = engine.create_task(req.agent_name, req.prompt)
    
    # Define execution coroutine
    coro = run_agent_task(task)
    
    # Start it asynchronously on the event loop
    success = engine.start_task(task.task_id, coro)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to start background task.")
        
    return task.to_dict()

@app.get("/api/tasks")
async def list_tasks():
    return engine.get_all_tasks_metadata()

@app.get("/api/tasks/{task_id}")
async def get_task_details(task_id: str):
    task = engine.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Return details including the full logs
    details = task.to_dict()
    details["logs"] = task.logs
    return details

@app.post("/api/tasks/{task_id}/pause")
async def pause_task(task_id: str):
    success = engine.pause_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not pause task. Task must be in 'running' state.")
    return {"status": "success", "message": "Task paused"}

@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    success = engine.resume_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not resume task. Task must be in 'paused' state.")
    return {"status": "success", "message": "Task resumed"}

@app.delete("/api/tasks/{task_id}")
async def kill_task(task_id: str):
    success = await engine.remove_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"status": "success", "message": "Task removed"}

@app.post("/api/tasks/{task_id}/input")
async def send_task_input(task_id: str, req: SendInputRequest):
    success = await engine.send_input(task_id, req.user_input)
    if not success:
        raise HTTPException(status_code=400, detail="Task is not currently waiting for input.")
    return {"status": "success", "message": "Input sent"}

# Active WebSocket connections
active_connections: List[WebSocket] = []

async def broadcast_updates_loop():
    """
    Background loop that broadcasts engine and task telemetry to all active WebSockets
    every 200ms. Allows real-time tracking of logs, tasks, and system performance.
    """
    while True:
        await asyncio.sleep(0.2)
        if not active_connections:
            continue
            
        # Get tasks data
        tasks_data = []
        for task in engine.tasks.values():
            td = task.to_dict()
            # Include latest 30 lines of logs to prevent bloated messages
            td["latest_logs"] = task.logs[-30:]
            tasks_data.append(td)
            
        # System telemetry stats
        cpu_usage = psutil.cpu_percent()
        memory_usage = psutil.virtual_memory().percent
        
        telemetry = {
            "type": "telemetry",
            "tasks": tasks_data,
            "system": {
                "cpu": cpu_usage,
                "memory": memory_usage,
                "active_tasks": len([t for t in engine.tasks.values() if t.status == "running"]),
                "total_tasks": len(engine.tasks),
            }
        }
        
        # Broadcast to all connected clients
        for connection in active_connections:
            try:
                await connection.send_json(telemetry)
            except Exception:
                # Connection might have died, clean_up occurs in ws block
                pass

# Run telemetry broadcaster loop in background
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_updates_loop())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)

    user_id = f"ws-user-{uuid.uuid4().hex[:8]}"
    session = coordinator_sessions.create_session(
        app_name="adk_async_background_engine_chat",
        user_id=user_id,
    )
    if asyncio.iscoroutine(session):
        session = await session
    
    # Send welcome message
    await websocket.send_json({
        "type": "chat",
        "sender": "Coordinator",
        "message": "Hello! I am the Main Thread Coordinator Agent. I run on the main asyncio thread, coordinating all background task agents. How can I help you today?"
    })
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "chat":
                user_msg = data.get("message", "")
                await handle_chat_message(websocket, user_msg, user_id, session.id)
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)

async def handle_chat_message(websocket: WebSocket, message: str, user_id: str, session_id: str):
    """
    ADK-backed conversational loop for websocket chat.
    """
    # Send receipt confirmation immediately to show responsiveness
    await websocket.send_json({
        "type": "chat_ack",
        "message": "Received prompt, thinking..."
    })

    try:
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)],
        )

        response_parts: List[str] = []
        async for event in coordinator_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        ):
            parts = getattr(getattr(event, "content", None), "parts", None) or []
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    response_parts.append(text)

        response = "\n".join([p.strip() for p in response_parts if p.strip()]).strip()
        if not response:
            response = "I processed your request, but I have no text response to display."
    except Exception as error:
        response = f"Coordinator chat agent failed: {error}"

    await websocket.send_json(
        {
            "type": "chat",
            "sender": "Coordinator",
            "message": response,
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
