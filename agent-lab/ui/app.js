const state = {
  activeRun: null,
  activeSession: null,
  activeKind: null,
  activeRecord: null,
  selectedFile: null,
  sessionFilter: "",
  reasoningLevel: "standard",
  reasoningOptions: [],
  projects: [],
  sessions: [],
  runPollTimer: null,
  sessionPollTimer: null,
  tasks: [],
  mode: "chats",
  detailsTab: "overview",
  modalReturnFocus: new Map(),
};

const $ = (id) => document.getElementById(id);

function setMode(mode, { focus = false } = {}) {
  const nextMode = mode === "runs" ? "runs" : "chats";
  state.mode = nextMode;
  $("layout").dataset.mode = nextMode;
  $("chatSurface").hidden = nextMode !== "chats";
  $("runSurface").hidden = nextMode !== "runs";
  $("chatNavigation").hidden = nextMode !== "chats";
  $("runNavigation").hidden = nextMode !== "runs";
  [["chatsModeButton", "chats"], ["runsModeButton", "runs"]].forEach(([id, value]) => {
    const active = value === nextMode;
    const button = $(id);
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  if (focus) $(nextMode === "runs" ? "runsModeButton" : "chatsModeButton").focus();
}

function openModal(dialogId, triggerId) {
  const dialog = $(dialogId);
  const trigger = triggerId ? $(triggerId) : document.activeElement;
  if (trigger instanceof HTMLElement) state.modalReturnFocus.set(dialogId, trigger);
  if (dialogId === "runDialog") {
    $("launchNote").className = "launch-note";
    $("launchNote").textContent = "Runs use the active project and reasoning level.";
  }
  if (!dialog.open) dialog.showModal();
  if (dialogId === "workspaceDialog") $("mobileWorkspaceButton").setAttribute("aria-expanded", "true");
}

function closeModal(dialogId) {
  const dialog = $(dialogId);
  if (dialog.open) dialog.close();
}

function restoreModalFocus(dialogId) {
  if (dialogId === "workspaceDialog") $("mobileWorkspaceButton").setAttribute("aria-expanded", "false");
  const trigger = state.modalReturnFocus.get(dialogId);
  state.modalReturnFocus.delete(dialogId);
  if (trigger?.isConnected) trigger.focus();
}

function setDetailsTab(tab, { focus = false } = {}) {
  const validTabs = ["overview", "workflow", "activity", "files"];
  const nextTab = validTabs.includes(tab) ? tab : "overview";
  state.detailsTab = nextTab;
  document.querySelectorAll(".details-tab").forEach((button) => {
    const active = button.dataset.detailsTab === nextTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  });
  const panels = {
    overview: "detailsOverview",
    workflow: "detailsWorkflow",
    activity: "detailsActivity",
    files: "detailsFiles",
  };
  Object.entries(panels).forEach(([value, id]) => {
    $(id).hidden = value !== nextTab;
  });
}

const FALLBACK_REASONING_OPTIONS = [
  { value: "off", label: "Off", budget: 0, max_tokens: 700, description: "Fastest replies with thinking disabled." },
  { value: "low", label: "Low", budget: 256, max_tokens: 1024, description: "A short verification pass for simple tasks." },
  { value: "standard", label: "Standard", budget: 1024, max_tokens: 2048, description: "The normal balance of quality and latency." },
  { value: "deep", label: "Deep", budget: 2048, max_tokens: 3072, description: "More room for multi-step reasoning and debugging." },
  { value: "max", label: "Max", budget: 3072, max_tokens: 4096, description: "The slowest, most deliberate local setting." },
];

const WORKFLOW_PHASES = [
  { id: "intake", label: "Intake" },
  { id: "inspect", label: "Inspect" },
  { id: "design", label: "Design" },
  { id: "plan", label: "Plan" },
  { id: "implement", label: "Build" },
  { id: "verify", label: "Verify" },
  { id: "review", label: "Review" },
  { id: "complete", label: "Done" },
];

const FALLBACK_WORKFLOW = {
  phase: "intake",
  status: "active",
  summary: "Request received.",
  next_action: "Understand the request and inspect the project.",
  artifacts: [],
  checkpoint_count: 0,
};

function normalizeWorkflow(workflow) {
  const value = workflow && typeof workflow === "object" ? workflow : {};
  const phaseIds = new Set([...WORKFLOW_PHASES.map((item) => item.id), "blocked"]);
  const phase = phaseIds.has(value.phase) ? value.phase : FALLBACK_WORKFLOW.phase;
  const status = phase === "complete" ? "complete" : phase === "blocked" || value.status === "blocked" ? "blocked" : "active";
  return {
    ...FALLBACK_WORKFLOW,
    ...value,
    phase,
    status,
    summary: String(value.summary || FALLBACK_WORKFLOW.summary),
    next_action: String(value.next_action || FALLBACK_WORKFLOW.next_action),
    artifacts: Array.isArray(value.artifacts) ? value.artifacts : [],
    checkpoint_count: Number(value.checkpoint_count || 0),
  };
}

function renderWorkflow(workflow = state.activeRecord?.workflow) {
  const normalized = normalizeWorkflow(workflow);
  const blocked = normalized.status === "blocked";
  const phases = blocked ? [...WORKFLOW_PHASES, { id: "blocked", label: "Blocked" }] : WORKFLOW_PHASES;
  const activeIndex = phases.findIndex((item) => item.id === normalized.phase);
  const heading = phases.find((item) => item.id === normalized.phase)?.label || "Intake";
  const statusLabelText = normalized.status === "complete" ? "Complete" : normalized.status === "blocked" ? "Blocked" : "Active";
  const headingElement = $("workflowHeading");
  const statusElement = $("workflowStatus");
  const stepsElement = $("workflowSteps");
  const summaryElement = $("workflowSummary");
  const nextElement = $("workflowNext");
  if (!headingElement || !statusElement || !stepsElement || !summaryElement || !nextElement) return;

  headingElement.textContent = heading;
  statusElement.className = `workflow-status ${normalized.status}`;
  statusElement.textContent = statusLabelText;
  summaryElement.textContent = normalized.summary;
  nextElement.textContent = normalized.next_action;
  stepsElement.className = `workflow-steps ${normalized.status}`;
  stepsElement.innerHTML = phases.map((item, index) => {
    const isComplete = normalized.status === "complete" ? item.id !== "complete" && item.id !== "blocked" : index < activeIndex;
    const isActive = item.id === normalized.phase && normalized.status !== "complete";
    const classes = ["workflow-step"];
    if (isComplete) classes.push("complete");
    if (isActive) classes.push("active");
    if (item.id === "blocked") classes.push("blocked");
    return `<div class="${classes.join(" ")}" aria-current="${isActive ? "step" : "false"}">
      <span class="workflow-step-index">${String(index + 1).padStart(2, "0")}</span>
      <span class="workflow-step-label">${escapeText(item.label)}</span>
    </div>`;
  }).join("");
}

function reasoningOption(level) {
  return (state.reasoningOptions.length ? state.reasoningOptions : FALLBACK_REASONING_OPTIONS).find((item) => item.value === level)
    || FALLBACK_REASONING_OPTIONS.find((item) => item.value === "standard");
}

function formatTokenCount(value) {
  return Number(value || 0).toLocaleString();
}

function renderReasoningControl(record = state.activeRecord) {
  const select = $("reasoningLevel");
  const hint = $("reasoningHint");
  if (!select || !hint) return;
  const reasoning = record?.reasoning || {};
  const level = reasoning.level || state.reasoningLevel || "standard";
  const option = reasoningOption(level);
  state.reasoningLevel = level;
  if ([...select.options].some((item) => item.value === level)) select.value = level;
  const budget = reasoning.budget ?? option.budget;
  hint.textContent = budget > 0 ? `${formatTokenCount(budget)} thinking tokens` : "Thinking disabled";
  select.title = reasoning.description || option.description;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error("The local Agent Lab service is unavailable. Start the UI server again and retry.");
  }
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { error: `The server returned an invalid response (${response.status}).` };
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function escapeText(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(timestamp) {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function sessionAge(sessionId) {
  const match = String(sessionId || "").match(/^chat-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
  if (!match) return "recently";
  const [, year, month, day, hour, minute, second] = match;
  const created = new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second));
  const elapsed = Math.max(0, Date.now() - created.getTime());
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function shortenPath(path) {
  const value = String(path || "").trim();
  if (!value) return "Managed folder";
  const parts = value.split(/[\\/]+/).filter(Boolean);
  if (parts.length <= 3) return value;
  const prefix = /^[A-Za-z]:[\\/]/.test(value) ? `${value.slice(0, 2)}\\` : "";
  return `${prefix}…\\${parts.slice(-2).join("\\")}`;
}

function comparablePath(path) {
  return String(path || "").trim().replace(/[\\/]+$/, "").toLowerCase();
}

function projectForPath(path) {
  const target = comparablePath(path);
  return state.projects.find((project) => comparablePath(project.path) === target) || null;
}

function workspaceLabelForRecord(record) {
  const project = projectForPath(record?.project);
  if (project) return `${project.name} project`;
  if (record?.workspace_mode === "selected" && record.project) return `Existing folder · ${shortenPath(record.project)}`;
  return "Scratch workspace";
}

function renderProjectOptions() {
  const select = $("projectSelect");
  if (!select) return;
  const currentPath = $("workspacePath")?.value.trim() || "";
  const project = projectForPath(currentPath);
  const options = ['<option value="">Scratch workspace</option>'];
  if (currentPath && !project) {
    options.push(`<option value="${escapeText(currentPath)}">Existing folder · ${escapeText(shortenPath(currentPath))}</option>`);
  }
  options.push(...state.projects.map((item) => `<option value="${escapeText(item.path)}">${escapeText(item.name)}</option>`));
  select.innerHTML = options.join("");
  select.value = project?.path || (currentPath && !project ? currentPath : "");
}

function setWorkspaceNotice(message, tone = "") {
  const status = $("workspaceStatus");
  if (!status) return;
  status.className = `workspace-status ${tone}`.trim();
  status.textContent = message;
}

function updateWorkspaceSummary() {
  const input = $("workspacePath");
  const rawPath = input ? input.value.trim() : state.activeRecord?.project || "";
  const project = projectForPath(rawPath);
  const selected = Boolean(rawPath);
  const locationLabel = project ? shortenPath(project.path) : selected ? shortenPath(rawPath) : "Temporary folder";
  const workspaceLabel = project ? `${project.name} project` : selected ? `Existing folder · ${shortenPath(rawPath)}` : "Scratch workspace";
  const mode = $("workspaceMode");
  const location = $("workspaceLocation");
  const projectName = $("activeProjectName");
  const composer = $("composerWorkspace");
  const topbar = $("topbarWorkspace");
  const mobileLocation = $("mobileWorkspaceLocation");
  const runTarget = $("runTarget");
  const heading = $("workspaceHeadingWorkspace");
  const openButton = $("openProjectButton");
  if (mode) mode.textContent = project ? "PROJECT" : selected ? "EXTERNAL" : "SCRATCH";
  if (location) location.textContent = locationLabel;
  if (projectName) projectName.textContent = project?.name || (selected ? "Existing folder" : "Scratch workspace");
  if (composer) composer.textContent = workspaceLabel;
  if (topbar) topbar.textContent = project?.name || (selected ? "Existing folder" : "Scratch workspace");
  if (mobileLocation) mobileLocation.textContent = locationLabel;
  if (runTarget) runTarget.textContent = workspaceLabel;
  if (heading) heading.textContent = workspaceLabel;
  if (openButton) {
    openButton.textContent = "Open folder";
    openButton.classList.toggle("ready", selected);
  }
  setWorkspaceNotice(
    project ? `${project.name} is persistent. New chats and runs will use it.` : selected ? "Attached folder. The harness can edit it directly." : "Scratch work is isolated and disposable.",
  );
  renderProjectOptions();
}

function statusLabel(status) {
  const labels = { ready: "Ready", idle: "Idle", thinking: "Thinking", running: "Running", success: "Success", complete: "Complete", blocked: "Blocked", error: "Error", interrupted: "Interrupted", failed: "Failed" };
  return labels[status] || status || "Ready";
}

function readableSummary(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const jsonStart = text.indexOf("{");
  if (jsonStart < 0) return text;
  try {
    const payload = JSON.parse(text.slice(jsonStart));
    const message = payload?.error?.message || payload?.message;
    if (message) {
      const prefix = text.slice(0, jsonStart).trim().replace(/[:\s]+$/, "");
      return prefix ? `${prefix}: ${message}` : String(message);
    }
  } catch (error) {
    // Keep the original summary when the server's diagnostic suffix is not JSON.
  }
  return text;
}

function setStatus(status) {
  const badge = $("runStatus");
  const normalized = status || "idle";
  badge.className = `status-badge ${escapeText(normalized)}`;
  badge.innerHTML = `<span class="status-dot" aria-hidden="true"></span>${escapeText(statusLabel(normalized))}`;
}

function eventCopy(event) {
  const data = event.data || {};
  switch (event.event) {
    case "run_created": return data.mode === "selected" ? "Run attached to the selected project folder" : "Run started in a managed project folder";
    case "session_ready": return data.mode === "selected" ? "Conversation attached to the selected project folder" : "Conversation opened with a managed project folder";
    case "session_rehydrated": return "Conversation restored from disk";
    case "job_interrupted": return "Turn interrupted; waiting for your retry";
    case "job_retry_requested": return `Retry started (attempt ${data.job?.attempt || "next"})`;
    case "job_progress": return `Worker checkpoint: ${data.action || "progress"}`;
    case "model_response": return `Model replied${data.finish_reason ? ` (${data.finish_reason})` : ""}`;
    case "tool_result": {
      const action = data.action || "tool";
      const result = data.result || {};
      if (action === "write_file") return `Created ${result.path || "a file"}`;
      if (action === "apply_patch") return `Applied changes to ${(result.changed || []).join(", ") || "files"}`;
      if (action === "run_command") return `Ran ${data.args?.command || "a command"} → exit ${result.exit_code ?? "error"}`;
      if (action === "list_files") return `Inspected the folder (${result.entries?.length || 0} entries)`;
      if (action === "read_file") return `Read ${data.args?.path || "a file"}`;
      return `Used ${action}`;
    }
    case "assistant_message": return "Assistant replied";
    case "workflow_phase": {
      const workflow = data.state || data.workflow || {};
      const phase = String(workflow.phase || "intake");
      return `Workflow → ${phase}${workflow.summary ? ` — ${workflow.summary}` : ""}`;
    }
    case "finish_rejected": return `Harness rejected completion: ${data.reason || "more work is required"}`;
    case "evaluator": return `External evaluator ${data.result?.passed ? "passed" : "failed"}`;
    case "finish": return `Finished ${data.status || "run"}${data.summary ? ` — ${data.summary}` : ""}`;
    case "interactive_step_limit": return `Paused at the action limit (${data.max_steps || "maximum"})`;
    case "turn_limit": return `Stopped at the turn limit (${data.max_turns || "maximum"})`;
    case "harness_error": return `Harness error: ${data.error || "unknown error"}`;
    default: return event.event || "event";
  }
}

function eventClass(event) {
  if (["finish", "evaluator", "assistant_message", "session_rehydrated"].includes(event.event)) return "success";
  if (event.event === "workflow_phase") {
    const phase = event.data?.state?.phase || event.data?.workflow?.phase;
    return phase === "blocked" ? "error" : phase === "complete" ? "success" : "tool";
  }
  if (["harness_error", "finish_rejected", "turn_limit", "interactive_step_limit", "job_interrupted"].includes(event.event)) return "error";
  if (event.event === "tool_result") return "tool";
  return "";
}

function renderActivity(events) {
  const container = $("activity");
  const visibleEvents = events.filter((event) => !["model_response", "assistant_message"].includes(event.event));
  if (!visibleEvents.length) {
    container.className = "activity-list empty-panel";
    container.innerHTML = '<div class="empty-icon" aria-hidden="true">✦</div><div>No activity yet.</div><small>Runs and tool calls will appear here.</small>';
    return;
  }
  container.className = "activity-list";
  container.innerHTML = visibleEvents.map((event) => `
    <div class="activity-entry ${eventClass(event)}">
      <div class="activity-marker"></div>
      <div class="activity-time">${escapeText(formatTime(event.timestamp))}</div>
      <div class="activity-title">${escapeText(eventCopy(event))}</div>
    </div>`).join("");
  container.scrollTop = container.scrollHeight;
}

function renderFiles(files) {
  const container = $("fileList");
  $("fileCount").textContent = files.length ? `${files.length} artifact${files.length === 1 ? "" : "s"}` : "—";
  if (!files.length) {
    container.className = "file-list empty-panel";
    container.innerHTML = '<div>No artifacts yet.</div><small>Files created during this session will appear here.</small>';
    return;
  }
  container.className = "file-list";
  container.innerHTML = files.map((file) => `
    <button class="file-button ${state.selectedFile === file.path ? "active" : ""}" type="button" data-file="${encodeURIComponent(file.path)}">
      <span class="file-name">${escapeText(file.path)}</span><span class="file-size">${formatBytes(file.bytes)}</span>
    </button>`).join("");
  container.querySelectorAll(".file-button").forEach((button) => button.addEventListener("click", () => showFile(decodeURIComponent(button.dataset.file))));
}

function renderRunList(runs) {
  const container = $("runList");
  if (!runs.length) {
    container.innerHTML = '<div class="muted">No runs yet.</div>';
    return;
  }
  container.innerHTML = runs.map((run) => `
    <button class="run-item ${run.run_id === state.activeRun && state.activeKind === "run" ? "active" : ""}" data-run="${escapeText(run.run_id)}" type="button">
      <div class="run-item-name">${escapeText(run.run_id)}</div>
      <div class="run-item-meta"><span class="run-item-status ${escapeText(run.status)}">${escapeText(run.status)}</span><span>${escapeText(run.changed_files?.length || 0)} files</span></div>
    </button>`).join("");
  container.querySelectorAll(".run-item").forEach((button) => button.addEventListener("click", () => selectRun(button.dataset.run)));
}

function renderSessionList(sessions = state.sessions) {
  const container = $("sessionList");
  const query = state.sessionFilter.trim().toLowerCase();
  const orderedSessions = [...sessions].sort((left, right) => {
    const leftActive = left.session_id === state.activeSession ? 1 : 0;
    const rightActive = right.session_id === state.activeSession ? 1 : 0;
    return rightActive - leftActive;
  });
  const filtered = orderedSessions.filter((session) => {
    if (!query) return true;
    return `${session.session_id} ${session.status} ${session.model || ""}`.toLowerCase().includes(query);
  });
  if (!filtered.length) {
    container.innerHTML = `<div class="muted">${query ? "No matching conversations." : "No conversations yet."}</div>`;
    return;
  }
  container.innerHTML = filtered.map((session) => `
    <button class="session-item ${session.session_id === state.activeSession ? "active" : ""}" data-session="${escapeText(session.session_id)}" type="button">
      <div class="session-item-name">${escapeText(session.session_id)}</div>
      <div class="session-item-meta">${escapeText(session.conversation?.length || 0)} message${(session.conversation?.length || 0) === 1 ? "" : "s"} · ${escapeText(sessionAge(session.session_id))}</div>
      <span class="session-menu" aria-hidden="true">⋮</span>
    </button>`).join("");
  container.querySelectorAll(".session-item").forEach((button) => button.addEventListener("click", () => selectSession(button.dataset.session)));
}

function messageTime(message, index, session) {
  if (message.timestamp) return formatTime(message.timestamp);
  const events = session.events || [];
  if (message.role === "user") {
    const first = events.find((event) => event.event === "session_ready" || event.event === "run_created");
    return first ? formatTime(first.timestamp) : "";
  }
  const assistantIndex = session.conversation.slice(0, index).filter((item) => item.role === "assistant").length;
  const candidates = events.filter((event) => event.event === "assistant_message");
  return candidates[assistantIndex] ? formatTime(candidates[assistantIndex].timestamp) : "";
}

function isRecoverableJob(session) {
  const jobStatus = session?.job?.status;
  return !session?.busy && ["interrupted", "failed"].includes(jobStatus);
}

function renderJobRecovery(session) {
  const button = $("retryJobButton");
  const note = $("chatNote");
  const send = $("sendButton");
  if (!button || !note || !send) return;
  const recoverable = isRecoverableJob(session);
  button.hidden = !recoverable;
  button.disabled = false;
  button.textContent = session?.job?.status === "failed" ? "Retry failed turn" : "Resume interrupted turn";
  send.disabled = Boolean(session?.busy || recoverable);
  if (session?.busy) {
    note.textContent = "The model is working...";
  } else if (recoverable) {
    note.textContent = "This turn stopped before finishing. Retry it to continue from the saved checkpoint.";
  } else {
    note.textContent = "Shift + Enter for new line";
  }
}

function renderChat(session) {
  const container = $("chatMessages");
  const messages = session.conversation || [];
  const modelLabel = escapeText(session.model || "Local model");
  $("chatHeading").textContent = session.session_id;
  $("chatStatus").textContent = session.busy ? "thinking" : session.status;
  renderJobRecovery(session);
  if (!messages.length) {
    container.className = "chat-messages empty-panel";
    container.innerHTML = '<div class="empty-icon" aria-hidden="true">◇</div><div>Send a message to begin.</div>';
    return;
  }
  container.className = "chat-messages";
  container.innerHTML = messages.map((message, index) => {
    const isUser = message.role === "user";
    const time = messageTime(message, index, session);
    return `
      <div class="chat-message ${isUser ? "user" : "assistant"}">
        <div class="avatar ${isUser ? "user" : "assistant"}" aria-hidden="true">${isUser ? "Y" : "A"}</div>
        <div class="chat-message-body">
          <div class="chat-message-meta"><span class="chat-role">${isUser ? "You" : modelLabel}</span>${time ? `<span class="chat-time">${escapeText(time)}</span>` : ""}</div>
          <div class="chat-bubble"><div class="chat-content">${escapeText(message.content)}</div></div>
        </div>
      </div>`;
  }).join("");
  container.scrollTop = container.scrollHeight;
}

function detailRow(label, value, className = "") {
  return `<div class="detail-row"><div class="detail-label">${escapeText(label)}</div><div class="detail-value ${className}">${value}</div></div>`;
}

function renderInspector(record = state.activeRecord) {
  state.activeRecord = record;
  $("inspectorTitle").textContent = "Details";
  $("inspectorMeta").textContent = state.activeKind === "run" ? "Run" : "Session";
  $("inspectorContent").hidden = false;
  $("inspectorTabs").hidden = false;
  $("filePreview").hidden = true;
  $("filesIndex").hidden = false;
  const id = record?.session_id || record?.run_id || "—";
  const status = record?.busy ? "thinking" : record?.status || "ready";
  const model = record?.model || "Local model";
  const fallbackDirectory = record?.session_id ? `./chat-sessions/${record.session_id}/project` : `./runs/${id}/project`;
  const directory = record?.project || fallbackDirectory;
  const workspaceMode = record?.workspace_mode || (record?.project ? "selected" : "managed");
  const project = projectForPath(directory);
  const workspaceDescription = project ? `${project.name} · persistent project` : workspaceMode === "selected" ? "Existing folder" : "Scratch workspace";
  const calls = record?.model_calls || 0;
  const tools = record?.tool_calls || 0;
  const reasoning = record?.reasoning || {};
  const reasoningLabel = reasoning.label || reasoningOption(reasoning.level || state.reasoningLevel).label;
  const effectiveBudget = reasoning.budget ?? reasoningOption(reasoning.level || state.reasoningLevel).budget;
  const reasoningBudget = effectiveBudget > 0 ? `${formatTokenCount(effectiveBudget)} tokens` : "Disabled";
  const reasoningMax = reasoning.max_tokens || reasoningOption(reasoning.level || state.reasoningLevel).max_tokens;
  const workflow = normalizeWorkflow(record?.workflow);
  renderReasoningControl(record);
  $("inspectorContent").innerHTML = [
    detailRow(state.activeKind === "run" ? "Run ID" : "Session ID", escapeText(id), "mono-value"),
    detailRow("Status", `<span class="status-inline"><span class="status-dot" aria-hidden="true"></span>${escapeText(statusLabel(status))}</span>`),
    detailRow("Model", escapeText(model)),
    detailRow("Reasoning", escapeText(reasoningLabel)),
    detailRow("Thinking budget", escapeText(reasoningBudget), "muted-value"),
    detailRow("Response cap", `${formatTokenCount(reasoningMax)} tokens`, "muted-value"),
    detailRow("Model calls", escapeText(calls)),
    detailRow("Tool calls", escapeText(tools)),
    detailRow("Workflow", escapeText(workflow.phase)),
    detailRow("Next action", escapeText(workflow.next_action), "muted-value"),
    detailRow("Project", escapeText(project?.name || (workspaceMode === "selected" ? "Existing folder" : "Scratch workspace")), "muted-value"),
    detailRow("Workspace", escapeText(workspaceDescription), "muted-value"),
    detailRow("Working directory", escapeText(directory), "mono-value"),
    detailRow("Host", "Local machine"),
    detailRow("Network", "Disabled in harness", "muted-value"),
  ].join("");
  setDetailsTab(state.detailsTab);
}

function renderRunSurface(run) {
  const summary = run.summary || {};
  $("runEmptyState").hidden = true;
  $("runOverview").hidden = false;
  $("runTitle").textContent = run.run_id;
  $("runSummary").textContent = readableSummary(summary.summary) || `Status: ${statusLabel(run.status)}`;
  $("runProjectLabel").textContent = projectForPath(run.project)?.name
    || (run.workspace_mode === "selected" ? "Existing folder" : "Scratch workspace");
}

function renderRun(run) {
  state.activeKind = "run";
  state.activeRun = run.run_id;
  state.activeRecord = run;
  state.selectedFile = null;
  updateWorkspaceSummary();
  const summary = run.summary || {};
  renderRunSurface(run);
  $("workspaceTitle").textContent = "Run workspace";
  $("workspaceSubtitle").textContent = readableSummary(summary.summary) || `The harness is working through ${run.run_id}.`;
  $("launchNote").textContent = run.status === "running" ? `Running ${run.run_id}` : `Selected ${run.run_id} · ${run.status}`;
  $("turnCount").textContent = summary.model_calls ? `${summary.model_calls} model calls · ${summary.tool_calls || 0} tool calls` : "running";
  $("rawOutput").textContent = (run.output || []).join("\n") || "No process output yet.";
  setStatus(run.status);
  renderReasoningControl(run);
  renderWorkflow(run.workflow);
  renderInspector(run);
  renderActivity(run.events || []);
  renderFiles(run.files || []);
  loadRuns().catch(() => {});
}

function renderSession(session) {
  state.activeKind = "session";
  state.activeSession = session.session_id;
  state.activeRecord = session;
  state.selectedFile = null;
  updateWorkspaceSummary();
  const recordWorkspace = workspaceLabelForRecord(session);
  $("composerWorkspace").textContent = recordWorkspace;
  $("workspaceHeadingWorkspace").textContent = recordWorkspace;
  $("workspaceTitle").textContent = "Local session";
  $("workspaceSubtitle").textContent = "Ask questions, request changes, and keep the same project context between messages.";
  $("turnCount").textContent = `${session.model_calls || 0} model calls · ${session.tool_calls || 0} tool calls`;
  $("rawOutput").textContent = (session.events || []).map((event) => eventCopy(event)).join("\n") || "No process output yet.";
  setStatus(session.busy ? "thinking" : session.status);
  renderReasoningControl(session);
  renderWorkflow(session.workflow);
  renderInspector(session);
  renderChat(session);
  renderActivity(session.events || []);
  renderFiles(session.files || []);
  loadSessions().catch(() => {});
}

async function selectRun(runId) {
  try {
    const run = await api(`/api/runs/${encodeURIComponent(runId)}`);
    renderRun(run);
    setMode("runs");
    closeMobileSidebar();
    if (run.status === "running") startRunPolling();
  } catch (error) {
    $("workspaceSubtitle").textContent = error.message;
  }
}

async function selectSession(sessionId) {
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
    renderSession(session);
    setMode("chats");
    closeMobileSidebar();
    if (session.busy) startSessionPolling();
  } catch (error) {
    $("workspaceSubtitle").textContent = error.message;
  }
}

async function showFile(path) {
  const activeId = state.activeKind === "session" ? state.activeSession : state.activeRun;
  if (!activeId || !state.activeKind) return;
  state.selectedFile = path;
  $("inspectorTitle").textContent = path;
  $("inspectorMeta").textContent = "File preview";
  setDetailsTab("files");
  $("filePreview").hidden = false;
  $("filesIndex").hidden = true;
  $("fileViewer").textContent = "Loading...";
  if (window.innerWidth <= 1180) setInspectorOpen(true);
  const collection = state.activeKind === "session" ? "sessions" : "runs";
  try {
    const file = await api(`/api/${collection}/${encodeURIComponent(activeId)}/file/${encodeURIComponent(path)}`);
    $("fileViewer").textContent = file.binary ? `[binary file · ${file.bytes} bytes]` : file.content;
    $("inspectorMeta").textContent = file.truncated ? "Preview truncated" : "Full preview";
    document.querySelectorAll(".file-button").forEach((button) => button.classList.toggle("active", decodeURIComponent(button.dataset.file) === path));
  } catch (error) {
    $("fileViewer").textContent = error.message;
    $("inspectorMeta").textContent = "Error";
  }
}

function closeFilePreview() {
  state.selectedFile = null;
  $("filePreview").hidden = true;
  $("filesIndex").hidden = false;
  renderInspector(state.activeRecord);
  if (state.activeRecord) renderFiles(state.activeRecord.files || []);
}

async function loadRuns() {
  const data = await api("/api/runs");
  renderRunList(data.runs || []);
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects || [];
  renderProjectOptions();
  updateWorkspaceSummary();
}

async function loadSessions() {
  const data = await api("/api/sessions");
  const sessions = data.sessions || [];
  state.sessions = sessions;
  renderSessionList(sessions);
}

async function createSession({ announce = false, openProject = false } = {}) {
  try {
    const projectPath = $("workspacePath").value.trim();
    const session = await api("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reasoning_level: state.reasoningLevel, project_path: projectPath }),
    });
    renderSession(session);
    await loadSessionsListOnly();
    if (announce) {
      const project = projectForPath(projectPath);
      const location = project ? `in the ${project.name} project` : projectPath ? `in ${shortenPath(projectPath)}` : "in a scratch workspace";
      setWorkspaceNotice(openProject ? `Opened a new chat ${location}.` : `Started a new chat ${location}.`, "success");
    }
    closeMobileSidebar();
    return true;
  } catch (error) {
    $("chatNote").textContent = error.message;
    setWorkspaceNotice(`Could not open the workspace: ${error.message}`, "error");
    return false;
  }
}

async function createProject() {
  const input = $("projectName");
  const name = input.value.trim();
  if (!name) {
    setWorkspaceNotice("Name the project first.", "error");
    input.focus();
    return;
  }
  input.disabled = true;
  try {
    const project = await api("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    state.projects.push(project);
    input.value = "";
    $("workspacePath").value = project.path;
    renderProjectOptions();
    updateWorkspaceSummary();
    if (await createSession({ announce: true, openProject: true })) closeModal("workspaceDialog");
  } catch (error) {
    setWorkspaceNotice(`Could not create the project: ${error.message}`, "error");
  } finally {
    input.disabled = false;
  }
}

async function selectProject(event) {
  const path = event.target.value;
  $("workspacePath").value = path;
  updateWorkspaceSummary();
  if (await createSession({ announce: true, openProject: Boolean(path) })) closeModal("workspaceDialog");
}

async function openProject() {
  if (!$("workspacePath").value.trim()) {
    setWorkspaceNotice("Enter a project folder first.", "error");
    $("workspacePath").focus();
    return;
  }
  if (await createSession({ announce: true, openProject: true })) closeModal("workspaceDialog");
}

async function loadSessionsListOnly() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions || [];
  renderSessionList(state.sessions);
}

function startRunPolling() {
  if (state.runPollTimer) clearInterval(state.runPollTimer);
  state.runPollTimer = setInterval(async () => {
    if (!state.activeRun || state.activeKind !== "run") return;
    try {
      const run = await api(`/api/runs/${encodeURIComponent(state.activeRun)}`);
      renderRun(run);
      if (run.status !== "running") {
        clearInterval(state.runPollTimer);
        state.runPollTimer = null;
        $("runButton").disabled = false;
      }
    } catch (error) {
      $("workspaceSubtitle").textContent = error.message;
    }
  }, 1000);
}

function startSessionPolling() {
  if (state.sessionPollTimer) clearInterval(state.sessionPollTimer);
  state.sessionPollTimer = setInterval(async () => {
    if (!state.activeSession || state.activeKind !== "session") return;
    try {
      const session = await api(`/api/sessions/${encodeURIComponent(state.activeSession)}`);
      renderSession(session);
      if (!session.busy) {
        clearInterval(state.sessionPollTimer);
        state.sessionPollTimer = null;
        $("sendButton").disabled = isRecoverableJob(session);
      }
    } catch (error) {
      $("chatNote").textContent = error.message;
    }
  }, 800);
}

async function sendMessage() {
  const content = $("chatInput").value.trim();
  if (!content) return;
  if (!state.activeSession) await createSession();
  if (!state.activeSession) return;
  if (isRecoverableJob(state.activeRecord)) return;
  $("sendButton").disabled = true;
  $("chatInput").value = "";
  try {
    await api(`/api/sessions/${encodeURIComponent(state.activeSession)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    await selectSession(state.activeSession);
    startSessionPolling();
  } catch (error) {
    $("chatNote").textContent = error.message;
    $("sendButton").disabled = false;
  }
}

async function retryJob() {
  if (!state.activeSession || !isRecoverableJob(state.activeRecord)) return;
  const button = $("retryJobButton");
  button.disabled = true;
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(state.activeSession)}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    renderSession(session);
    startSessionPolling();
  } catch (error) {
    button.disabled = false;
    $("chatNote").textContent = error.message;
  }
}

async function changeReasoningLevel(event) {
  const nextLevel = event.target.value;
  const previousLevel = state.activeRecord?.reasoning?.level || state.reasoningLevel || "standard";
  state.reasoningLevel = nextLevel;
  renderReasoningControl({ reasoning: { level: nextLevel } });
  if (state.activeKind !== "session" || !state.activeSession) return;
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(state.activeSession)}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reasoning_level: nextLevel }),
    });
    renderSession(session);
  } catch (error) {
    state.reasoningLevel = previousLevel;
    renderReasoningControl(state.activeRecord);
    $("chatNote").textContent = error.message;
  }
}

async function startRun() {
  const taskText = $("taskText").value.trim();
  if (!taskText) {
    $("launchNote").textContent = "Give the agent a task first.";
    setWorkspaceNotice("Add a task before starting the run.", "error");
    return;
  }
  const gated = $("taskPreset").value !== "custom" && $("useGates").checked;
  const projectPath = $("workspacePath").value.trim();
  const target = projectPath ? `the selected project ${shortenPath(projectPath)}` : "an isolated workspace";
  $("runButton").disabled = true;
  $("launchNote").textContent = `Starting in ${target}...`;
  setWorkspaceNotice(`Starting a run in ${target}.`, "working");
  try {
    const result = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_text: taskText, gated, reasoning_level: state.reasoningLevel, project_path: projectPath }),
    });
    state.activeKind = "run";
    state.activeRun = result.run_id;
    $("launchNote").textContent = `Running ${result.run_id}`;
    await selectRun(result.run_id);
    setWorkspaceNotice(`Run started in ${target}.`, "success");
    closeModal("runDialog");
    startRunPolling();
  } catch (error) {
    $("launchNote").textContent = error.message;
    setWorkspaceNotice(`Could not start the run: ${error.message}`, "error");
    $("runButton").disabled = false;
  }
}

async function loadTasks() {
  const data = await api("/api/tasks");
  state.tasks = data.tasks || [];
  const select = $("taskPreset");
  select.innerHTML = '<option value="custom">Custom task</option>' + state.tasks.map((task) => `<option value="${escapeText(task.name)}">${escapeText(task.title)}</option>`).join("");
  if (state.tasks.length) {
    select.value = state.tasks[0].name;
    $("taskText").value = state.tasks[0].content;
  }
}

async function loadReasoningLevels() {
  try {
    const data = await api("/api/reasoning-levels");
    state.reasoningOptions = data.levels || [];
  } catch (error) {
    state.reasoningOptions = FALLBACK_REASONING_OPTIONS;
  }
  renderReasoningControl();
}

function closeMobileSidebar() {
  if (window.innerWidth > 760) return;
  $("layout").classList.remove("sidebar-open");
  $("sidebarToggle").setAttribute("aria-expanded", "false");
  syncResponsiveInert();
}

function toggleMobileSidebar() {
  const open = $("layout").classList.toggle("sidebar-open");
  $("sidebarToggle").setAttribute("aria-expanded", String(open));
  syncResponsiveInert();
}

function syncResponsiveInert() {
  const mobile = window.innerWidth <= 760;
  $("sidebar").toggleAttribute("inert", mobile && !$("layout").classList.contains("sidebar-open"));
}

function setInspectorOpen(open) {
  $("layout").classList.toggle("details-open", open);
  $("inspectorToggle").setAttribute("aria-expanded", String(open));
  $("rightRail").setAttribute("aria-hidden", String(!open));
  $("rightRail").toggleAttribute("inert", !open);
  $("detailsBackdrop").hidden = !open;
  if (open) setDetailsTab(state.detailsTab);
}

function toggleInspector() {
  setInspectorOpen(!$("layout").classList.contains("details-open"));
}

$("taskPreset").addEventListener("change", () => {
  const task = state.tasks.find((item) => item.name === $("taskPreset").value);
  if (task) {
    $("taskText").value = task.content;
    $("useGates").checked = true;
  } else {
    $("taskText").value = "";
    $("useGates").checked = false;
  }
});
$("newChatButton").addEventListener("click", () => createSession({ announce: true }));
$("newRunButton").addEventListener("click", () => openModal("runDialog", "newRunButton"));
$("emptyNewRunButton").addEventListener("click", () => openModal("runDialog", "emptyNewRunButton"));
$("workspaceDialogTrigger").addEventListener("click", () => openModal("workspaceDialog", "workspaceDialogTrigger"));
$("runButton").addEventListener("click", startRun);
$("sendButton").addEventListener("click", sendMessage);
$("retryJobButton").addEventListener("click", retryJob);
$("reasoningLevel").addEventListener("change", changeReasoningLevel);
$("workspacePath").addEventListener("input", updateWorkspaceSummary);
$("projectSelect").addEventListener("change", selectProject);
$("createProjectButton").addEventListener("click", createProject);
$("projectName").addEventListener("keydown", (event) => {
  if (event.key === "Enter") createProject();
});
$("openProjectButton").addEventListener("click", openProject);
$("clearWorkspace").addEventListener("click", () => {
  $("workspacePath").value = "";
  $("projectSelect").value = "";
  updateWorkspaceSummary();
  setWorkspaceNotice("Using a scratch workspace. The next chat gets a fresh folder.", "success");
  $("launchNote").textContent = "Runs will use a scratch workspace.";
});
$("refreshRuns").addEventListener("click", () => loadRuns().catch(() => {}));
$("sessionSearch").addEventListener("input", (event) => {
  state.sessionFilter = event.target.value;
  renderSessionList();
});
$("chatInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.shiftKey) return;
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    sendMessage();
  }
});
$("sidebarToggle").addEventListener("click", toggleMobileSidebar);
$("mobileWorkspaceButton").addEventListener("click", () => openModal("workspaceDialog", "mobileWorkspaceButton"));
$("inspectorToggle").addEventListener("click", toggleInspector);
$("runDetailsButton").addEventListener("click", () => setInspectorOpen(true));
$("closeInspector").addEventListener("click", () => setInspectorOpen(false));
$("detailsBackdrop").addEventListener("click", () => setInspectorOpen(false));
document.querySelectorAll(".details-tab").forEach((button) => {
  button.addEventListener("click", () => setDetailsTab(button.dataset.detailsTab));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const tabs = ["overview", "workflow", "activity", "files"];
    const offset = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex = (tabs.indexOf(state.detailsTab) + offset + tabs.length) % tabs.length;
    setDetailsTab(tabs[nextIndex], { focus: true });
  });
});
$("chatsModeButton").addEventListener("click", () => setMode("chats"));
$("runsModeButton").addEventListener("click", () => setMode("runs"));
[$("chatsModeButton"), $("runsModeButton")].forEach((button) => button.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  setMode(state.mode === "chats" ? "runs" : "chats", { focus: true });
}));
$("workspaceDialog").addEventListener("close", () => restoreModalFocus("workspaceDialog"));
$("runDialog").addEventListener("close", () => restoreModalFocus("runDialog"));
$("workspaceDialog").addEventListener("click", (event) => {
  if (event.target === $("workspaceDialog")) closeModal("workspaceDialog");
});
$("runDialog").addEventListener("click", (event) => {
  if (event.target === $("runDialog")) closeModal("runDialog");
});
$("closeFilePreview").addEventListener("click", closeFilePreview);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("layout").classList.contains("details-open")) setInspectorOpen(false);
});
window.addEventListener("resize", syncResponsiveInert);

async function bootstrap() {
  syncResponsiveInert();
  try {
    await loadProjects();
    await Promise.all([loadReasoningLevels(), loadTasks(), loadRuns(), loadSessions()]);
  } catch (error) {
    $("launchNote").textContent = error.message;
  }
  updateWorkspaceSummary();
  setMode("chats");
  setDetailsTab("overview");
}

bootstrap();
