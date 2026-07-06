## Async Background Task Engine (Real Google ADK Agents)

This project runs multiple long-running agents in the background while keeping the main thread responsive via FastAPI + asyncio.

Each background workflow is now a real Google ADK agent run (no simulation mode), with function tools for local analysis and execution.

![Architecture](./images/background_worker.png)

## Features

- Real ADK runner integration for all agents.
- Function tool calls for research, coding, and math analysis.
- Background task lifecycle controls: create, pause, resume, kill, remove.
- Human-in-the-loop checkpoint for the Coder workflow.
- Realtime telemetry and logs over WebSocket.

## Agent Workflows

- `Researcher`
	- Uses ADK tools for local workspace search and URL content fetch.
- `Coder`
	- Uses ADK tools to list/read Python files and run pytest.
	- Includes HITL input prompt for divide-by-zero handling strategy.
- `DataCruncher`
	- Uses ADK tools for prime batch analysis and math series statistics.

## Prerequisites

- Python 3.10+
- A valid Google model API key for ADK runtime

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=<your_api_key>
ADK_MODEL=<gemini-model>
```

`ADK_MODEL` defaults to `gemini-2.5-flash` if not set.
The app loads `.env` automatically via `python-dotenv`.

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

- `http://localhost:8000` for UI
- `ws://localhost:8000/ws` for coordinator chat/telemetry stream

## API Overview

Create task:

```bash
curl -X POST http://localhost:8000/api/tasks \
	-H "Content-Type: application/json" \
	-d '{"agent_name":"Researcher","prompt":"research retrieval augmented generation trends"}'
```

Supported `agent_name` values:

- `Researcher`
- `Coder`
- `DataCruncher`

Other endpoints:

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/input`
- `DELETE /api/tasks/{task_id}`

## Notes

- This project intentionally keeps task execution asynchronous and cooperative so UI remains responsive.


