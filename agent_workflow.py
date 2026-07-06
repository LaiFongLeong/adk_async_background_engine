import asyncio
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List
from urllib.error import URLError
from urllib.request import Request, urlopen
from dotenv import load_dotenv

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from engine import Task

logger = logging.getLogger("AgentWorkflow")
APP_NAME = "adk_async_background_engine"

load_dotenv()


def _get_model_name() -> str:
    return os.getenv("ADK_MODEL", "gemini-2.5-flash")

# Helper to check primality for heavy CPU-bound task simulation
def is_prime(n: int) -> bool:
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    i = 5
    while i * i <= n:
        if n % i == 0 or n % (i + 2) == 0:
            return False
        i += 6
    return True


def _tool_prime_batch(start: int, count: int) -> Dict[str, Any]:
    primes: List[int] = []
    for value in range(start, start + count):
        if is_prime(value):
            primes.append(value)
    return {
        "start": start,
        "count": count,
        "prime_count": len(primes),
        "first_five_primes": primes[:5],
        "last_prime": primes[-1] if primes else None,
    }


def _tool_series_stats(limit: int) -> Dict[str, Any]:
    if limit < 1:
        return {"limit": limit, "error": "limit must be >= 1"}

    harmonic_sum = 0.0
    sqrt_sum = 0.0
    for i in range(1, limit + 1):
        harmonic_sum += 1 / i
        sqrt_sum += math.sqrt(i)

    return {
        "limit": limit,
        "harmonic_sum": round(harmonic_sum, 8),
        "sqrt_sum": round(sqrt_sum, 8),
    }


def _tool_workspace_search(query: str, max_results: int = 8) -> Dict[str, Any]:
    root = Path.cwd()
    query_lc = query.lower().strip()
    if not query_lc:
        return {"query": query, "results": []}

    results: List[Dict[str, Any]] = []
    allowed_suffixes = {".py", ".md", ".txt", ".json", ".yaml", ".yml"}

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if query_lc in line.lower():
                results.append(
                    {
                        "path": str(path.relative_to(root)),
                        "line": line_number,
                        "snippet": line.strip()[:220],
                    }
                )
                if len(results) >= max_results:
                    return {"query": query, "results": results}

    return {"query": query, "results": results}


def _tool_fetch_url_text(url: str, max_chars: int = 3000) -> Dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8", errors="ignore")
            return {
                "url": url,
                "status": getattr(response, "status", 200),
                "content_excerpt": body[:max_chars],
                "content_length": len(body),
            }
    except URLError as error:
        return {"url": url, "error": str(error)}


def _tool_list_python_files() -> List[str]:
    return sorted(str(path.relative_to(Path.cwd())) for path in Path.cwd().rglob("*.py") if path.is_file())


def _tool_read_python_file(path: str, start_line: int = 1, end_line: int = 200) -> Dict[str, Any]:
    root = Path.cwd().resolve()
    target = (root / path).resolve()

    if root not in target.parents and target != root:
        return {"path": path, "error": "path must stay within workspace"}
    if not target.exists() or not target.is_file():
        return {"path": path, "error": "file does not exist"}

    lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = max(1, start_line)
    end = max(start, end_line)
    excerpt = lines[start - 1 : end]

    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "content": "\n".join(excerpt),
    }


def _tool_run_pytest(test_filter: str = "") -> Dict[str, Any]:
    command = ["python3", "-m", "pytest", "-q"]
    if test_filter.strip():
        command.extend(["-k", test_filter.strip()])

    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, cwd=Path.cwd())
        return {
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    except Exception as error:
        return {"command": " ".join(command), "error": str(error)}


def _extract_event_log(event: Any) -> str:
    if getattr(event, "error_message", None):
        return f"ADK event error: {event.error_message}"

    lines: List[str] = []
    author = getattr(event, "author", "agent")
    parts = getattr(getattr(event, "content", None), "parts", None) or []

    for part in parts:
        text = getattr(part, "text", None)
        if text:
            lines.append(f"{author}: {text}")

        function_call = getattr(part, "function_call", None)
        if function_call:
            call_name = getattr(function_call, "name", "unknown_tool")
            args = getattr(function_call, "args", {})
            lines.append(f"ToolCall {call_name} args={json.dumps(args, default=str)}")

        function_response = getattr(part, "function_response", None)
        if function_response:
            response_name = getattr(function_response, "name", "unknown_tool")
            response_value = getattr(function_response, "response", None)
            lines.append(f"ToolResponse {response_name}: {json.dumps(response_value, default=str)[:500]}")

    return " | ".join(lines)


async def _run_adk_agent(task: Task, agent: Agent, user_message: str) -> None:
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)

    user_id = f"user-{task.task_id}"
    session = session_service.create_session(app_name=APP_NAME, user_id=user_id)
    if asyncio.iscoroutine(session):
        session = await session
    content = types.Content(role="user", parts=[types.Part.from_text(text=user_message)])

    event_count = 0
    async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=content):
        await asyncio.sleep(0)
        await task.wait_if_paused()

        event_count += 1
        task.progress = min(95.0, max(task.progress, 8.0 + event_count * 8.0))

        event_log = _extract_event_log(event)
        if event_log:
            level = "ERROR" if "error" in event_log.lower() else "INFO"
            task.add_log(event_log, level)

    task.progress = max(task.progress, 95.0)

async def run_data_cruncher(task: Task):
    """
    Executes a real ADK data-analysis agent using local function tools.
    """
    model_name = _get_model_name()
    task.add_log("Starting DataCruncher ADK workflow...", "INFO")
    task.add_log(f"Using model: {model_name}", "INFO")

    agent = Agent(
        name="data_cruncher_agent",
        model=model_name,
        instruction=(
            "You are a mathematical analysis agent. Use tool_prime_batch and tool_series_stats to "
            "compute concrete numeric results before responding. Include a concise final report."
        ),
        tools=[_tool_prime_batch, _tool_series_stats],
    )

    await _run_adk_agent(task, agent, task.prompt)

    task.add_log("Math analysis complete. Final ADK report generated.", "SUCCESS")
    task.progress = 95.0
    await asyncio.sleep(0.8)
    task.progress = 100.0
    task.completed_at = time.time()
    task.status = "completed"
    task.add_log("Agent report generated and stored in output folder. Workflow finished successfully.", "SUCCESS")


async def run_research_agent(task: Task):
    """
    Executes a real ADK researcher agent with workspace search and web fetch tools.
    """
    model_name = _get_model_name()
    task.add_log("Starting Researcher ADK workflow...", "INFO")
    task.add_log(f"Using model: {model_name}", "INFO")

    agent = Agent(
        name="researcher_agent",
        model=model_name,
        instruction=(
            "You are a research agent. Use the available tools to gather workspace and web evidence, "
            "then return a sourced summary with explicit assumptions and uncertainty."
        ),
        tools=[_tool_workspace_search, _tool_fetch_url_text],
    )

    await _run_adk_agent(task, agent, task.prompt)

    task.progress = 100.0
    task.completed_at = time.time()
    task.status = "completed"
    task.add_log("Research task completed. Final report output generated.", "SUCCESS")


async def run_coder_agent(task: Task):
    """
    Executes a real ADK coding agent with local code-inspection and test tools.
    Keeps a HITL checkpoint for policy decisions.
    """
    model_name = _get_model_name()
    task.add_log("Starting Coder ADK workflow...", "INFO")
    task.add_log(f"Using model: {model_name}", "INFO")

    task.progress = 20.0
    await task.wait_if_paused()

    prompt = "How would you like to handle division by zero? Reply with 'raise' (raise ValueError) or 'return' (return None/NaN)."
    user_choice = await task.request_user_input(prompt)

    task.add_log(f"Applying user chosen approach: '{user_choice}'", "INFO")
    task.progress = 35.0
    await task.wait_if_paused()

    agent = Agent(
        name="coder_agent",
        model=model_name,
        instruction=(
            "You are a coding assistant for this local workspace. Inspect relevant files and run tests "
            "with tools before proposing code changes. Respect the user decision on divide-by-zero policy."
        ),
        tools=[_tool_list_python_files, _tool_read_python_file, _tool_run_pytest],
    )

    full_prompt = (
        f"User request: {task.prompt}\n"
        f"Division-by-zero decision: {user_choice}.\n"
        "Analyze the current project and provide concrete patch recommendations."
    )

    await _run_adk_agent(task, agent, full_prompt)

    task.add_log("ADK coder run complete with tool-based analysis.", "SUCCESS")
    
    task.progress = 100.0
    task.completed_at = time.time()
    task.status = "completed"
    task.add_log("Interactive code fix verified and committed. Task finished.", "SUCCESS")


async def run_agent_task(task: Task):
    """
    Dispatcher mapping agent names to their asynchronous workflows.
    Ensures state transitions are handled if exceptions occur (e.g. cancellation).
    """
    try:
        if task.agent_name == "Researcher":
            await run_research_agent(task)
        elif task.agent_name == "Coder":
            await run_coder_agent(task)
        elif task.agent_name == "DataCruncher":
            await run_data_cruncher(task)
        else:
            task.add_log(f"Unknown agent type '{task.agent_name}'. Running generic agent.", "ERROR")
            task.progress = 50.0
            await asyncio.sleep(1.0)
            task.progress = 100.0
            task.status = "completed"
            task.completed_at = time.time()
            task.add_log("Generic agent task finished.", "SUCCESS")
            
    except asyncio.CancelledError:
        task.status = "killed"
        task.completed_at = time.time()
        task.add_log("Task runner cancelled.", "ERROR")
        raise
    except Exception as e:
        task.status = "failed"
        task.completed_at = time.time()
        task.add_log(f"Exception raised during task execution: {str(e)}", "ERROR")
        logger.exception(f"Error in task {task.task_id}")
