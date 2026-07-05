import asyncio
import math
import time
import random
from engine import Task

# Try to import google-adk, if not available, we use simulator
ADK_AVAILABLE = False
try:
    import google.adk as adk
    from google.adk.agents import Agent
    from google.adk.runners import Runner
    ADK_AVAILABLE = True
except ImportError:
    pass

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

async def run_data_cruncher(task: Task):
    """
    Runs a CPU-intensive mathematical analysis agent.
    Performs heavy computations in chunks, yielding control after each chunk
    to maintain main thread responsiveness, and supports pause/resume/kill.
    """
    task.add_log("Starting mathematical agent workflow...", "INFO")
    task.add_log("Instruction: Find prime numbers and compute running math series up to 200,000.", "INFO")
    await asyncio.sleep(0.5)
    
    start_num = 100000
    target_count = 50000
    primes_found = []
    
    current_num = start_num
    processed = 0
    
    task.add_log("Running primality test suite in chunk batches...", "INFO")
    
    # We execute in batches to yield control and keep the event loop responsive
    batch_size = 500
    
    while processed < target_count:
        # 1. Check if task was cancelled/killed
        await asyncio.sleep(0)  # Check for cancellation
        
        # 2. Check if task is paused
        await task.wait_if_paused()
        
        # 3. Perform a chunk of computation
        for _ in range(batch_size):
            if is_prime(current_num):
                primes_found.append(current_num)
            current_num += 1
            processed += 1
            
        # Update progress and log occasionally
        progress_pct = (processed / target_count) * 100
        task.progress = progress_pct
        
        if processed % 5000 == 0:
            task.add_log(f"Analyzed {processed}/{target_count} candidates. Found {len(primes_found)} primes. Latest prime: {primes_found[-1] if primes_found else 'none'}", "INFO")
            
        # Yield control for a short period to allow other tasks & UI to process
        await asyncio.sleep(0.05)

    task.add_log(f"Math analysis complete! Found {len(primes_found)} primes. Writing analysis report...", "INFO")
    task.progress = 95.0
    await asyncio.sleep(0.8)
    task.progress = 100.0
    task.completed_at = time.time()
    task.status = "completed"
    task.add_log("Agent report generated and stored in output folder. Workflow finished successfully.", "SUCCESS")


async def run_research_agent(task: Task):
    """
    Simulates a Google ADK Researcher Agent that calls tools (e.g. search, scrape)
    to perform deep web investigation.
    """
    task.add_log("Initializing ADK Session runner...", "INFO")
    await asyncio.sleep(0.4)
    
    steps = [
        ("Planning", "Decomposing user request: '" + task.prompt + "' into search keywords.", 10),
        ("ToolCall", "google_search(query='" + task.prompt[:30] + "')", 25),
        ("ToolResponse", "Found 8 sources. Selected top 3 relevant reports.", 35),
        ("ToolCall", "web_scraper(urls=['https://api.reports/trends', 'https://data.com/analysis'])", 50),
        ("ToolResponse", "Scraped content successfully. Size: 45KB. Language: EN.", 60),
        ("Reasoning", "Analyzing scraped data and structuring report layout.", 75),
        ("ToolCall", "format_output(format='markdown')", 85),
        ("Finalizing", "Writing final response and cleaning up session.", 95)
    ]
    
    for step_type, description, progress in steps:
        await asyncio.sleep(0)
        await task.wait_if_paused()
        
        task.progress = progress
        
        if step_type == "ToolCall":
            task.add_log(f"Calling Tool: {description}", "WARN")
            await asyncio.sleep(1.2)  # Simulating network latency
        elif step_type == "ToolResponse":
            task.add_log(f"Tool Response: {description}", "SUCCESS")
            await asyncio.sleep(0.8)
        else:
            task.add_log(f"[{step_type}] {description}", "INFO")
            await asyncio.sleep(1.0)
            
    task.progress = 100.0
    task.completed_at = time.time()
    task.status = "completed"
    task.add_log("Research task completed. Final report output generated.", "SUCCESS")


async def run_coder_agent(task: Task):
    """
    Simulates an interactive Coder Agent that writes tests, detects issues,
    requests human verification (HITL checkpoint), and then applies the fix.
    """
    task.add_log("Starting Interactive Coding Agent...", "INFO")
    await asyncio.sleep(0.5)
    
    task.add_log("Analyzing project codebase to write unit tests...", "INFO")
    task.progress = 15.0
    await asyncio.sleep(1.0)
    await task.wait_if_paused()
    
    task.add_log("Writing new unit tests in `tests/test_calculator.py`...", "INFO")
    task.progress = 30.0
    await asyncio.sleep(1.0)
    await task.wait_if_paused()
    
    task.add_log("Running pytest suite...", "INFO")
    task.progress = 45.0
    await asyncio.sleep(0.8)
    
    task.add_log("Test suite failed: Test case `test_division_by_zero` raised unexpected ZeroDivisionError instead of custom ValueError.", "ERROR")
    await asyncio.sleep(0.5)
    await task.wait_if_paused()
    
    # Checkpoint: Ask the user how to fix
    prompt = "How would you like to handle division by zero? Reply with 'raise' (raise ValueError) or 'return' (return None/NaN)."
    user_choice = await task.request_user_input(prompt)
    
    # Resume work based on input
    task.add_log(f"Applying user chosen approach: '{user_choice}'", "INFO")
    task.progress = 60.0
    await asyncio.sleep(1.0)
    await task.wait_if_paused()
    
    if user_choice.lower().strip() == "return":
        task.add_log("Modifying calculator.py: returning NaN for divide by zero.", "INFO")
        task.add_log("Updating test expectations...", "INFO")
    else:
        task.add_log("Modifying calculator.py: raising ValueError for divide by zero.", "INFO")
        task.add_log("Updating test expectations...", "INFO")
        
    task.progress = 80.0
    await asyncio.sleep(1.2)
    await task.wait_if_paused()
    
    task.add_log("Re-running pytest suite...", "INFO")
    await asyncio.sleep(0.6)
    task.add_log("pytest: 12 passed, 0 failed in 0.12 seconds.", "SUCCESS")
    
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
