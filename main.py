import asyncio
import os
import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any

from engine import AsyncTaskEngine
from agent_workflow import run_agent_task

app = FastAPI(title="Python ADK Background Task Engine")

# Instantiate our task engine
engine = AsyncTaskEngine()

# Ensure the static directories exist
os.makedirs("static", exist_ok=True)

# Mount static folder
app.mount("/static", StaticFiles(directory="static"), name="static")

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
                await handle_chat_message(websocket, user_msg)
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.remove(websocket)

async def handle_chat_message(websocket: WebSocket, message: str):
    """
    Core conversational agent logic running on the main thread.
    Can interpret user requests and automatically trigger background execution.
    """
    msg_lower = message.lower()
    
    # Send receipt confirmation immediately to show responsiveness
    await websocket.send_json({
        "type": "chat_ack",
        "message": "Received prompt, thinking..."
    })
    await asyncio.sleep(0.3)
    
    if "research" in msg_lower or "search" in msg_lower:
        # User wants to run a research task
        prompt = message
        task = engine.create_task("Researcher", prompt)
        engine.start_task(task.task_id, run_agent_task(task))
        
        response = f"I've initiated a background **Researcher Agent** (Task ID: **{task.task_id}**) to look into: *\"{prompt}\"*. You can track its progress and logs in the dashboard pane on the right."
        
    elif "test" in msg_lower or "coder" in msg_lower or "refactor" in msg_lower:
        # User wants to run coding/test agent
        prompt = message
        task = engine.create_task("Coder", prompt)
        engine.start_task(task.task_id, run_agent_task(task))
        
        response = f"Launched **Coder Agent** (Task ID: **{task.task_id}**) to perform development workflows. It will run test suites and check back if it needs human input!"
        
    elif "math" in msg_lower or "crunch" in msg_lower or "prime" in msg_lower:
        # User wants to run heavy math calculation
        prompt = message
        task = engine.create_task("DataCruncher", prompt)
        engine.start_task(task.task_id, run_agent_task(task))
        
        response = f"Spawning a heavy-compute **Data Cruncher Agent** (Task ID: **{task.task_id}**) to run complex primality checks in the background. The main thread will remain fully responsive!"
        
    elif "help" in msg_lower:
        response = ("You can command me to start background agents by typing prompts like:\n"
                    "- *'research quantum computing trends'*\n"
                    "- *'coder write code for the division calculator'*\n"
                    "- *'crunch primes'*\n\n"
                    "You can also use the control buttons on the right to manage running agents.")
    else:
        response = f"I am active and responding on the main thread! I can run tasks for you. Try asking me to 'research solar flares' or 'run prime math' to see the asynchronous background task engine in action."

    await websocket.send_json({
        "type": "chat",
        "sender": "Coordinator",
        "message": response
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
