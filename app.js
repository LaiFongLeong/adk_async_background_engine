// Global state
let socket = null;
let collapsedTerminals = {}; // tracks task_id -> boolean (true if collapsed)
let isTyping = false;

// FPS Monitor variables
let lastFrameTime = performance.now();
let frameCount = 0;
let fps = 60;
const fpsEl = document.getElementById("ui-fps");

// Canvas configuration
const canvas = document.getElementById("fps-canvas");
const ctx = canvas.getContext("2d");
let particles = [];
let mouse = { x: null, y: null };

// Initialize App
document.addEventListener("DOMContentLoaded", () => {
    setupCanvas();
    setupWebSocket();
    setupEventHandlers();
    measureFPS();
});

// ----------------------------------------------------
// FPS & Canvas Simulation (Main Thread Responsiveness)
// ----------------------------------------------------
function setupCanvas() {
    // Fit canvas to container size
    const resizeCanvas = () => {
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * window.devicePixelRatio;
        canvas.height = rect.height * window.devicePixelRatio;
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    };
    resizeCanvas();
    window.addEventListener("resize", resizeCanvas);
    
    // Add particle array
    const particleCount = 45;
    particles = [];
    for (let i = 0; i < particleCount; i++) {
        particles.push({
            x: Math.random() * (canvas.width / window.devicePixelRatio),
            y: Math.random() * (canvas.height / window.devicePixelRatio),
            vx: (Math.random() - 0.5) * 1.5,
            vy: (Math.random() - 0.5) * 1.5,
            radius: Math.random() * 3 + 2,
            color: i % 2 === 0 ? "#6366f1" : "#8b5cf6"
        });
    }

    // Mouse listener
    canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        mouse.x = e.clientX - rect.left;
        mouse.y = e.clientY - rect.top;
    });

    canvas.addEventListener("mouseleave", () => {
        mouse.x = null;
        mouse.y = null;
    });

    animateCanvas();
}

function animateCanvas() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const width = canvas.width / window.devicePixelRatio;
    const height = canvas.height / window.devicePixelRatio;

    // Draw and update particles
    particles.forEach(p => {
        // Basic physics
        p.x += p.vx;
        p.y += p.vy;

        // Wall collisions
        if (p.x < 0 || p.x > width) p.vx *= -1;
        if (p.y < 0 || p.y > height) p.vy *= -1;

        // Clamp inside bounds
        p.x = Math.max(0, Math.min(width, p.x));
        p.y = Math.max(0, Math.min(height, p.y));

        // Interaction with mouse pointer
        if (mouse.x !== null && mouse.y !== null) {
            const dx = mouse.x - p.x;
            const dy = mouse.y - p.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 80) {
                // Attract slightly
                p.x += dx * 0.03;
                p.y += dy * 0.03;
            }
        }

        // Draw particle
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.shadowBlur = 8;
        ctx.shadowColor = p.color;
        ctx.fill();
        ctx.shadowBlur = 0; // reset
    });

    // Draw lines between nearby particles
    ctx.strokeStyle = "rgba(99, 102, 241, 0.08)";
    ctx.lineWidth = 1;
    for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
            const dx = particles[i].x - particles[j].x;
            const dy = particles[i].y - particles[j].y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < 60) {
                ctx.beginPath();
                ctx.moveTo(particles[i].x, particles[i].y);
                ctx.lineTo(particles[j].x, particles[j].y);
                ctx.stroke();
            }
        }
    }

    requestAnimationFrame(animateCanvas);
}

function measureFPS() {
    frameCount++;
    const now = performance.now();
    const elapsed = now - lastFrameTime;

    if (elapsed >= 1000) {
        fps = Math.round((frameCount * 1000) / elapsed);
        fpsEl.textContent = fps;
        
        // Update FPS warning colors
        const fpsCard = document.getElementById("fps-card");
        if (fps < 45) {
            fpsEl.className = "value error";
            fpsCard.querySelector(".fps-dot").style.backgroundColor = "var(--color-danger)";
        } else if (fps < 55) {
            fpsEl.className = "value warning";
            fpsCard.querySelector(".fps-dot").style.backgroundColor = "var(--color-warning)";
        } else {
            fpsEl.className = "value success";
            fpsCard.querySelector(".fps-dot").style.backgroundColor = "var(--color-success)";
        }
        
        frameCount = 0;
        lastFrameTime = now;
    }
    requestAnimationFrame(measureFPS);
}

// ----------------------------------------------------
// WebSocket Telemetry & Chat Client
// ----------------------------------------------------
function setupWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("WebSocket connection established successfully.");
        document.querySelector(".navbar .brand span").textContent = "Connected to Task Engine Core";
    };

    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === "chat") {
            removeTypingIndicator();
            appendChatMessage(data.sender, data.message);
        } else if (data.type === "chat_ack") {
            showTypingIndicator();
        } else if (data.type === "telemetry") {
            updateDashboard(data.system, data.tasks);
        }
    };

    socket.onclose = () => {
        console.warn("WebSocket closed. Attempting reconnect in 3 seconds...");
        document.querySelector(".navbar .brand span").textContent = "Core Disconnected (Reconnecting...)";
        setTimeout(setupWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

// ----------------------------------------------------
// UI Renderers & Dashboard Controller
// ----------------------------------------------------
function updateDashboard(system, tasks) {
    // 1. Update Navbar Telemetry Stats
    document.getElementById("sys-active-workers").textContent = system.active_tasks;
    document.getElementById("sys-cpu").textContent = `${system.cpu}%`;
    document.getElementById("sys-memory").textContent = `${system.memory}%`;
    
    // 2. Render Background Task Cards
    const tasksList = document.getElementById("tasks-list");
    
    if (tasks.length === 0) {
        tasksList.innerHTML = `
            <div class="no-tasks-state">
                <i class="fa-solid fa-layer-group"></i>
                <p>No active background tasks running.</p>
                <span>Use the panel above or ask the chat coordinator to spawn background agents.</span>
            </div>
        `;
        return;
    }

    // Preserve scroll position of list
    const oldScrollTop = tasksList.scrollTop;
    
    // Construct HTML for tasks
    let html = "";
    tasks.forEach(task => {
        const isCollapsed = collapsedTerminals[task.task_id] !== false; // default to collapsed (true)
        const statusClass = `status-${task.status}`;
        
        // Progress bar status class matches status
        const progressClass = task.status;
        
        // Generate control actions depending on state
        let controlButtons = "";
        if (task.status === "running") {
            controlButtons = `
                <button class="ctrl-btn btn-pause" onclick="pauseTask('${task.task_id}')" title="Pause Task">
                    <i class="fa-solid fa-pause"></i>
                </button>
                <button class="ctrl-btn btn-kill" onclick="killTask('${task.task_id}')" title="Terminate Task">
                    <i class="fa-solid fa-stop"></i>
                </button>
            `;
        } else if (task.status === "paused") {
            controlButtons = `
                <button class="ctrl-btn btn-resume" onclick="resumeTask('${task.task_id}')" title="Resume Task">
                    <i class="fa-solid fa-play"></i>
                </button>
                <button class="ctrl-btn btn-kill" onclick="killTask('${task.task_id}')" title="Terminate Task">
                    <i class="fa-solid fa-stop"></i>
                </button>
            `;
        } else {
            // Task is completed/killed/failed - only allow termination/removal from dashboard
            controlButtons = `
                <button class="ctrl-btn btn-kill" onclick="killTask('${task.task_id}')" title="Clear Task Card">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            `;
        }

        // Render human checkpoint prompt if waiting for input
        let checkpointHtml = "";
        if (task.waiting_for_input) {
            checkpointHtml = `
                <div class="task-input-checkpoint">
                    <div class="checkpoint-prompt">
                        <i class="fa-solid fa-circle-question"></i>
                        <span>Checkpoint: ${task.input_prompt}</span>
                    </div>
                    <div class="checkpoint-input-row">
                        <input type="text" id="input-${task.task_id}" placeholder="Type reply response..." onkeydown="handleCheckpointKey(event, '${task.task_id}')">
                        <button class="btn-checkpoint-submit" onclick="submitCheckpointInput('${task.task_id}')">Submit</button>
                    </div>
                </div>
            `;
        }

        // Generate logs lines
        let logsHtml = "";
        if (task.latest_logs && task.latest_logs.length > 0) {
            task.latest_logs.forEach(log => {
                const date = new Date(log.timestamp * 1000);
                const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                const levelClass = `log-lvl-${log.level.toLowerCase()}`;
                
                logsHtml += `
                    <div class="log-line">
                        <span class="log-time">[${timeStr}]</span>
                        <span class="${levelClass}">${escapeHtml(log.text)}</span>
                    </div>
                `;
            });
        } else {
            logsHtml = `<div class="log-line text-muted">No logs recorded yet.</div>`;
        }

        html += `
            <div class="task-card" id="card-${task.task_id}">
                <div class="task-card-header">
                    <div class="task-meta-info">
                        <div class="task-title">
                            ${escapeHtml(task.agent_name)} Agent
                            <span class="task-id">${task.task_id}</span>
                        </div>
                        <div class="task-prompt-txt">Goal: "${escapeHtml(task.prompt)}"</div>
                    </div>
                    <div class="task-controls">
                        ${controlButtons}
                    </div>
                </div>

                <!-- Progress Section -->
                <div class="task-progress-container">
                    <div class="progress-label-row">
                        <span class="task-status-badge ${statusClass}">${task.status}</span>
                        <span class="progress-pct">${task.progress}%</span>
                    </div>
                    <div class="progress-track ${progressClass}">
                        <div class="progress-bar" style="width: ${task.progress}%"></div>
                    </div>
                </div>

                <!-- Human input checkpoint -->
                ${checkpointHtml}

                <!-- Collapsible Terminal Console Logs -->
                <div class="task-terminal">
                    <div class="terminal-header" onclick="toggleTerminal('${task.task_id}')">
                        <span><i class="fa-solid fa-terminal"></i> Agent Console Logs</span>
                        <i class="fa-solid ${isCollapsed ? 'fa-chevron-down' : 'fa-chevron-up'}"></i>
                    </div>
                    <div class="terminal-content ${isCollapsed ? 'collapsed' : ''}" id="logs-container-${task.task_id}">
                        ${logsHtml}
                    </div>
                </div>
            </div>
        `;
    });

    tasksList.innerHTML = html;
    
    // Auto-scroll terminals that are active & not collapsed
    tasks.forEach(task => {
        const isCollapsed = collapsedTerminals[task.task_id] !== false;
        if (!isCollapsed) {
            const logsContainer = document.getElementById(`logs-container-${task.task_id}`);
            if (logsContainer) {
                logsContainer.scrollTop = logsContainer.scrollHeight;
            }
        }
    });

    // Retain list scroll position
    tasksList.scrollTop = oldScrollTop;
}

// ----------------------------------------------------
// REST API Interaction Methods
// ----------------------------------------------------
async function pauseTask(taskId) {
    try {
        const response = await fetch(`/api/tasks/${taskId}/pause`, { method: "POST" });
        if (!response.ok) throw new Error(await response.text());
    } catch (e) {
        console.error("Pause API error:", e);
        alert("Failed to pause task: " + e.message);
    }
}

async function resumeTask(taskId) {
    try {
        const response = await fetch(`/api/tasks/${taskId}/resume`, { method: "POST" });
        if (!response.ok) throw new Error(await response.text());
    } catch (e) {
        console.error("Resume API error:", e);
        alert("Failed to resume task: " + e.message);
    }
}

async function killTask(taskId) {
    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
        if (!response.ok) throw new Error(await response.text());
        // Clean collapsed tracking
        delete collapsedTerminals[taskId];
    } catch (e) {
        console.error("Kill API error:", e);
        alert("Failed to clear/terminate task: " + e.message);
    }
}

async function submitCheckpointInput(taskId) {
    const inputEl = document.getElementById(`input-${taskId}`);
    const userInput = inputEl.value.trim();
    if (!userInput) return;
    
    try {
        const response = await fetch(`/api/tasks/${taskId}/input`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_input: userInput })
        });
        if (!response.ok) throw new Error(await response.text());
        inputEl.value = "";
    } catch (e) {
        console.error("Checkpoint input API error:", e);
        alert("Failed to submit input: " + e.message);
    }
}

function handleCheckpointKey(event, taskId) {
    if (event.key === "Enter") {
        submitCheckpointInput(taskId);
    }
}

// ----------------------------------------------------
// UI Navigation / Event Listeners
// ----------------------------------------------------
function setupEventHandlers() {
    // Chat Message Submission
    const chatInput = document.getElementById("chat-input");
    const sendChatBtn = document.getElementById("send-chat-btn");
    
    const sendChatMessage = () => {
        const text = chatInput.value.trim();
        if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;
        
        // Append user bubble to chat locally
        appendChatMessage("User", text);
        chatInput.value = "";
        
        // Send message to server via socket
        socket.send(JSON.stringify({
            type: "chat",
            message: text
        }));
    };

    sendChatBtn.addEventListener("click", sendChatMessage);
    chatInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendChatMessage();
    });

    // Task Spawning Form Submission
    const spawnForm = document.getElementById("spawn-task-form");
    spawnForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const agentType = document.getElementById("agent-type").value;
        const prompt = document.getElementById("task-prompt").value.trim();
        if (!prompt) return;
        
        try {
            const response = await fetch("/api/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ agent_name: agentType, prompt: prompt })
            });
            
            if (!response.ok) throw new Error(await response.text());
            
            // Clear input field on success
            document.getElementById("task-prompt").value = "";
            
            // Expand terminal of the new task by default
            const newTask = await response.json();
            collapsedTerminals[newTask.task_id] = false;
        } catch (err) {
            console.error("Spawn API error:", err);
            alert("Error spawning agent: " + err.message);
        }
    });

    // Clear completed tasks button
    document.getElementById("clear-tasks-btn").addEventListener("click", async () => {
        try {
            // Fetch list of tasks
            const response = await fetch("/api/tasks");
            if (!response.ok) return;
            const tasks = await response.json();
            
            // Filter completed, killed or failed tasks, and call delete on them
            const inactiveTasks = tasks.filter(t => ["completed", "killed", "failed"].includes(t.status));
            
            for (const task of inactiveTasks) {
                await fetch(`/api/tasks/${task.task_id}`, { method: "DELETE" });
            }
        } catch (err) {
            console.error("Clear task list error:", err);
        }
    });
}

function toggleTerminal(taskId) {
    const logsContainer = document.getElementById(`logs-container-${taskId}`);
    const headerIcon = logsContainer.previousElementSibling.querySelector("i.fa-chevron-down, i.fa-chevron-up");
    
    const isCurrentlyCollapsed = logsContainer.classList.contains("collapsed");
    
    if (isCurrentlyCollapsed) {
        logsContainer.classList.remove("collapsed");
        headerIcon.className = "fa-solid fa-chevron-up";
        collapsedTerminals[taskId] = false; // set as expanded
        
        // Immediate scroll to bottom
        logsContainer.scrollTop = logsContainer.scrollHeight;
    } else {
        logsContainer.classList.add("collapsed");
        headerIcon.className = "fa-solid fa-chevron-down";
        collapsedTerminals[taskId] = true; // set as collapsed
    }
}

// ----------------------------------------------------
// Chat Presentation Helpers
// ----------------------------------------------------
function appendChatMessage(sender, text) {
    const chatHistory = document.getElementById("chat-history");
    const msgDiv = document.createElement("div");
    
    const isUser = sender.toLowerCase() === "user";
    msgDiv.className = `chat-message ${isUser ? 'user' : 'coordinator'}`;
    
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    // Safe text injection and convert markdown-like syntax
    const formattedText = formatMarkdown(text);
    
    msgDiv.innerHTML = `
        <div class="message-meta">${sender} • ${timeStr}</div>
        <div class="message-bubble">
            ${formattedText}
        </div>
    `;
    
    chatHistory.appendChild(msgDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function showTypingIndicator() {
    if (isTyping) return;
    isTyping = true;
    
    const chatHistory = document.getElementById("chat-history");
    const indicatorDiv = document.createElement("div");
    indicatorDiv.id = "chat-typing-indicator";
    indicatorDiv.className = "typing-indicator";
    indicatorDiv.innerHTML = `
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    `;
    
    chatHistory.appendChild(indicatorDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById("chat-typing-indicator");
    if (indicator) {
        indicator.remove();
    }
    isTyping = false;
}

// Simple markdown subset parser
function formatMarkdown(text) {
    let html = text;
    // Bold: **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic: *text*
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Bullet points: - point
    html = html.replace(/^\-\s(.*)$/gm, '<li>$1</li>');
    // Wrap consecutive list items
    html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
    // Paragraphs split by newlines
    html = html.split('\n\n').map(p => {
        if (p.startsWith('<ul>') || p.startsWith('<li>')) return p;
        return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('');
    return html;
}

// HTML escape utility
function escapeHtml(unsafe) {
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}
