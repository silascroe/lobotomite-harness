const state = {
  activeRun: null,
  activeSession: null,
  activeKind: null,
  activeRecord: null,
  selectedFile: null,
  sessionFilter: "",
  reasoningLevel: "standard",
  approvalMode: "auto",
  provider: { provider: "local", label: "Local model", endpoint: "", model: "", has_api_key: false },
  reasoningOptions: [],
  skills: [],
  skillDefaults: [],
  skillOverrides: { enabled: [], disabled: [] },
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
    state.skillOverrides = { enabled: [], disabled: [] };
    loadSkills($("workspacePath").value.trim()).catch((error) => {
      $("skillSummary").textContent = `Skill catalog unavailable: ${error.message}`;
    });
  }
  if (dialogId === "providerDialog") syncProviderDialog();
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
  const validTabs = ["overview", "workflow", "review", "activity", "files"];
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
    review: "detailsReview",
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

function normalizeApprovalMode(value) {
  return value === "confirm" ? "confirm" : "auto";
}

function renderApprovalControl(record = state.activeRecord) {
  const select = $("approvalMode");
  const hint = $("approvalHint");
  if (!select || !hint) return;
  const mode = normalizeApprovalMode(record?.approval_mode || state.approvalMode);
  state.approvalMode = mode;
  select.value = mode;
  hint.textContent = mode === "confirm" ? "Ask before edits" : "Autonomous tools";
}

function normalizeProvider(value) {
  return value === "openai_compatible" ? "openai_compatible" : "local";
}

function providerForRecord(record = state.activeRecord) {
  const value = record?.provider || state.provider || {};
  return {
    provider: normalizeProvider(value.provider),
    label: value.label || (normalizeProvider(value.provider) === "local" ? "Local model" : "OpenAI API"),
    endpoint: String(value.endpoint || ""),
    model: String(value.model || ""),
    has_api_key: Boolean(value.has_api_key),
  };
}

function renderProviderControl(record = state.activeRecord) {
  const value = providerForRecord(record);
  const label = $("providerLabel");
  const button = $("providerButton");
  if (label) label.textContent = value.provider === "local" ? "Local" : "API";
  if (button) button.title = value.provider === "local" ? "Using the local model" : `Using ${value.model || "the remote API"}`;
}

function syncProviderDialog() {
  const value = providerForRecord();
  const type = $("providerType");
  const fields = $("remoteProviderFields");
  const endpoint = $("providerEndpoint");
  const model = $("providerModel");
  const key = $("providerApiKey");
  const hint = $("providerKeyHint");
  const status = $("providerStatus");
  if (!type || !fields || !endpoint || !model || !key || !hint || !status) return;
  type.value = value.provider;
  fields.hidden = value.provider !== "openai_compatible";
  endpoint.value = value.endpoint || "https://api.openai.com/v1/chat/completions";
  model.value = value.model || "";
  key.value = "";
  key.placeholder = value.has_api_key ? "Key already loaded; leave blank to keep it" : "Paste a key for this session only";
  hint.textContent = value.has_api_key
    ? "A key is already loaded in memory. Leave this blank to keep it, or paste a replacement."
    : "The key stays in memory while this Agent Lab process is running. It is never written to the project, transcript, or Git.";
  status.textContent = value.provider === "local"
    ? "Local model selected. The next chat or run stays on this machine."
    : value.has_api_key
      ? "Remote model selected. The key is loaded in memory."
      : "Remote model selected. Add a key before using it.";
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
  const labels = { ready: "Ready", idle: "Idle", thinking: "Thinking", running: "Running", success: "Success", complete: "Complete", blocked: "Blocked", error: "Error", interrupted: "Interrupted", failed: "Failed", waiting_approval: "Approval needed" };
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
    case "workspace_lock_acquired": return "Workspace reserved for this run";
    case "workspace_lock_released": return "Workspace released";
    case "run_created": return data.mode === "selected" ? "Run attached to the selected project folder" : "Run started in a managed project folder";
    case "session_ready": return data.mode === "selected" ? "Conversation attached to the selected project folder" : "Conversation opened with a managed project folder";
    case "session_rehydrated": return "Conversation restored from disk";
   case "job_interrupted": return "Turn interrupted; waiting for your retry";
    case "job_stop_requested": return "Turn stopped by the user; waiting for retry";
    case "job_retry_requested": return `Retry started (attempt ${data.job?.attempt || "next"})`;
    case "job_progress": return `Worker checkpoint: ${data.action || "progress"}`;
    case "tool_call_started": return `Tool call started: ${data.receipt?.action || "tool"}`;
    case "tool_call_completed": return `Tool call completed: ${data.receipt?.action || "tool"}`;
    case "tool_call_settled": return `Tool result recorded: ${data.receipt?.action || "tool"}`;
    case "tool_result_replayed": return `Recovered the completed ${data.receipt?.action || "tool"} result without repeating it`;
    case "tool_outcome_unknown": return `Tool outcome unknown: inspect before repeating ${data.receipt?.action || "the action"}`;
    case "recovery_retry": {
      const decision = data.decision || {};
      return `Recovery retry ${decision.attempt || "?"}/${decision.limit || "?"}: ${decision.detail || "repairing the last failure"}`;
    }
    case "recovery_duplicate_action": {
      const decision = data.decision || {};
      return `Duplicate action stopped before dispatch: ${decision.detail || "same action repeated"}`;
    }
    case "recovery_exhausted": {
      const decision = data.decision || {};
      return `Recovery exhausted: ${decision.detail || "the same failure persisted"}`;
    }
    case "context_compacted": {
      const before = data.before_tokens || "?";
      const after = data.after_tokens || "?";
      const dropped = data.dropped_messages || 0;
      return `Context compacted ${before} → ${after} tokens; ${dropped} older messages summarized`;
    }
    case "invalid_model_action": return `Model output needed repair: ${data.error || "the action was not understood"}`;
    case "model_response": return `Model replied${data.finish_reason ? ` (${data.finish_reason})` : ""}`;
    case "tool_result": {
      const action = data.action || "tool";
      const result = data.result || {};
     if (action === "write_file") return `Created ${result.path || "a file"}`;
      if (action === "delete_file") return "Deleted " + (result.path || "a file") + " (backup kept)";
      if (action === "replace_text") return `Replaced text in ${result.path || data.args?.path || "a file"}`;
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
    case "workflow_late_evidence": {
      const workflow = data.state || {};
      return `Late workflow evidence recorded: ${data.requested_phase || "checkpoint"} (phase remains ${workflow.phase || "active"})`;
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
  if (["harness_error", "finish_rejected", "turn_limit", "interactive_step_limit", "job_interrupted", "job_stop_requested", "recovery_exhausted"].includes(event.event)) return "error";
  if (["recovery_retry", "recovery_duplicate_action", "workflow_late_evidence", "context_compacted", "tool_call_started", "tool_call_completed", "tool_call_settled", "tool_result_replayed", "tool_outcome_unknown"].includes(event.event)) return "tool";
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

function compactText(value, limit = 220) {
  const copy = String(value ?? "").replace(/\s+/g, " ").trim();
  return copy.length > limit ? `${copy.slice(0, limit - 1)}…` : copy;
}

function compactActivityCopy(event) {
  return compactText(eventCopy(event), 180);
}

function humanizeAction(action) {
  const value = String(action || "tool").replace(/[_-]+/g, " ").trim();
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "Tool";
}

function toolActionTitle(action) {
  const titles = {
    list_files: "Inspecting the project folder",
    read_file: "Reading a project file",
    write_file: "Writing a project file",
    replace_text: "Updating a project file",
    apply_patch: "Applying a project patch",
    delete_file: "Removing a project file",
    run_command: "Running a local command",
    git_diff: "Reviewing project changes",
    workflow_checkpoint: "Recording workflow progress",
    find_skills: "Searching the local skill shelf",
    finish: "Finishing the run",
  };
  return titles[action] || `Using ${humanizeAction(action).toLowerCase()}`;
}

function toolActionMeta(event) {
  const data = event.data || {};
  const action = data.action || data.receipt?.action || "";
  const args = data.args || data.receipt?.summary || {};
  if (action === "run_command") return "local command";
  if (args.path && args.path !== ".") return String(args.path);
  if (action) return action;
  return "tool";
}

function toolResultCopy(event) {
  const data = event.data || {};
  const action = data.action || "tool";
  const args = data.args || {};
  const result = data.result || {};
  if (result.ok === false || result.error) return compactText(result.error || "The tool reported an error.");
  if (action === "list_files") {
    const count = Array.isArray(result.entries) ? result.entries.length : 0;
    return `Found ${count} ${count === 1 ? "entry" : "entries"} in the project folder.`;
  }
  if (action === "read_file") return `Read ${args.path || result.path || "the requested file"}.`;
  if (action === "write_file") return `Created ${result.path || args.path || "a project file"}.`;
  if (action === "replace_text") return `Updated ${result.path || args.path || "a project file"}.`;
  if (action === "apply_patch") {
    const changed = Array.isArray(result.changed) ? result.changed : [];
    return changed.length ? `Updated ${changed.join(", ")}.` : "Updated the project files.";
  }
  if (action === "delete_file") return `Removed ${result.path || args.path || "a project file"}; a backup was kept.`;
  if (action === "run_command") {
    const exitCode = result.exit_code ?? 0;
    return exitCode === 0 ? "Command completed successfully." : `Command exited with code ${exitCode}.`;
  }
  return `Completed ${toolActionTitle(action).toLowerCase()}.`;
}

function activityKindLabel(event) {
  const labels = {
    workspace_lock_acquired: "Workspace",
    workspace_lock_released: "Workspace",
    run_created: "Run",
    session_ready: "Session",
    session_rehydrated: "Recovery",
    invalid_model_action: "Model",
    model_response: "Model",
    assistant_message: "Reply",
    tool_call_started: "Tool call",
    tool_call_completed: "Tool call",
    tool_call_settled: "Tool result",
    tool_result: "Tool result",
    workflow_phase: "Workflow",
    workflow_late_evidence: "Workflow",
    harness_error: "Error",
    finish: "Run",
  };
  return labels[event.event] || "Checkpoint";
}

function phaseLabel(phase) {
  return WORKFLOW_PHASES.find((item) => item.id === phase)?.label || humanizeAction(phase || "workflow");
}

function deriveActivityFeed(events) {
  const items = [];
  const add = (item) => {
    const normalized = {
      kind: "narrative",
      tone: "neutral",
      status: "complete",
      icon: "·",
      label: "Agent",
      title: "Activity recorded",
      copy: "",
      meta: "",
      timestamp: "",
      ...item,
    };
    items.push(normalized);
    return normalized;
  };
  const findTool = (action) => {
    for (let index = items.length - 1; index >= 0; index -= 1) {
      const item = items[index];
      if (item.kind === "tool" && item.action === action && ["working", "checking"].includes(item.status)) return item;
    }
    return null;
  };

  for (const event of events) {
    if (!event || !event.event) continue;
    const data = event.data || {};
    switch (event.event) {
      case "workspace_lock_acquired":
      case "workspace_lock_released":
      case "model_response":
      case "tool_call_settled":
        break;
      case "run_created":
        add({
          label: "Run started",
          title: data.mode === "selected" ? "Attached to the selected project" : "Opened a fresh project workspace",
          copy: "The agent has a clean place to work.",
          icon: "◇",
          timestamp: event.timestamp,
        });
        break;
      case "session_ready":
        add({ label: "Session ready", title: "The conversation is ready", copy: "The selected project context is attached.", icon: "◇", timestamp: event.timestamp });
        break;
      case "session_rehydrated":
        add({ label: "Recovered", title: "Restored the conversation from disk", copy: "The previous project context is available again.", icon: "↻", tone: "success", timestamp: event.timestamp });
        break;
      case "workflow_phase": {
        const workflow = data.state || data.workflow || {};
        const phase = String(workflow.phase || "intake");
        add({
          label: phaseLabel(phase),
          title: compactText(workflow.summary || `Moving through ${phaseLabel(phase).toLowerCase()}.`, 150),
          copy: workflow.next_action ? `Next: ${compactText(workflow.next_action, 180)}` : "",
          icon: phase === "complete" ? "✓" : "·",
          tone: workflow.status === "blocked" ? "error" : phase === "complete" ? "success" : "neutral",
          timestamp: event.timestamp,
        });
        break;
      }
      case "workflow_late_evidence":
        add({ label: "Workflow", title: "Recorded a late checkpoint", copy: compactActivityCopy(event), icon: "↺", tone: "tool", timestamp: event.timestamp });
        break;
      case "tool_call_started": {
        const action = data.receipt?.action || "tool";
        add({
          kind: "tool",
          label: "Tool call",
          title: toolActionTitle(action),
          copy: "Waiting for the tool result.",
          meta: toolActionMeta(event),
          action,
          status: "working",
          icon: "↗",
          tone: "active",
          timestamp: event.timestamp,
        });
        break;
      }
      case "tool_call_completed": {
        const action = data.receipt?.action || "tool";
        const item = findTool(action);
        if (item) {
          item.status = "checking";
          item.copy = "Tool returned; recording the result.";
          item.timestamp = event.timestamp || item.timestamp;
        }
        break;
      }
      case "tool_result": {
        const action = data.action || "tool";
        const item = findTool(action) || add({ kind: "tool", label: "Tool result", title: toolActionTitle(action), action, icon: "↗", timestamp: event.timestamp });
        const failed = data.result?.ok === false || Boolean(data.result?.error);
        item.label = failed ? "Tool result" : "Tool result";
        item.title = toolActionTitle(action);
        item.copy = toolResultCopy(event);
        item.meta = toolActionMeta(event);
        item.status = failed ? "error" : "complete";
        item.tone = failed ? "error" : "success";
        item.timestamp = event.timestamp || item.timestamp;
        break;
      }
      case "tool_result_replayed":
        add({ label: "Recovery", title: "Reused a recorded tool result", copy: compactActivityCopy(event), icon: "↻", tone: "tool", timestamp: event.timestamp });
        break;
      case "tool_outcome_unknown":
        add({ label: "Recovery", title: "Paused before repeating a tool action", copy: compactActivityCopy(event), icon: "!", tone: "error", timestamp: event.timestamp });
        break;
      case "assistant_message": {
        const content = compactText(data.content, 420);
        if (content) add({ label: "Agent update", title: "The agent added an update", copy: content, icon: "A", tone: "success", timestamp: event.timestamp });
        break;
      }
      case "approval_requested":
        add({ label: "Approval", title: "The agent is waiting for your approval", copy: "The next project change is paused until you decide.", icon: "?", tone: "waiting", status: "working", timestamp: event.timestamp });
        break;
      case "invalid_model_action":
        add({ label: "Model repair", title: "The model output needed repair", copy: compactText(data.error || "The action was not understood.", 220), icon: "↺", tone: "tool", timestamp: event.timestamp });
        break;
      case "recovery_retry":
        add({ label: "Recovery", title: "Trying the last move again", copy: compactActivityCopy(event), icon: "↺", tone: "tool", timestamp: event.timestamp });
        break;
      case "recovery_duplicate_action":
        add({ label: "Recovery", title: "Stopped a duplicate action", copy: compactActivityCopy(event), icon: "!", tone: "waiting", timestamp: event.timestamp });
        break;
      case "recovery_exhausted":
        add({ label: "Recovery", title: "Recovery attempts are exhausted", copy: compactActivityCopy(event), icon: "!", tone: "error", timestamp: event.timestamp });
        break;
      case "context_compacted":
        add({ label: "Context", title: "Condensed older context", copy: compactActivityCopy(event), icon: "≈", tone: "tool", timestamp: event.timestamp });
        break;
      case "evaluator": {
        const passed = Boolean(data.result?.passed);
        add({ label: "Verification", title: passed ? "The evaluator passed" : "The evaluator found a problem", copy: data.result?.summary || "External evaluation completed.", icon: passed ? "✓" : "!", tone: passed ? "success" : "error", timestamp: event.timestamp });
        break;
      }
      case "finish":
        add({ label: "Finished", title: data.status === "success" ? "The run finished successfully" : "The run stopped", copy: data.summary || "The run reached a terminal state.", icon: data.status === "success" ? "✓" : "!", tone: data.status === "success" ? "success" : "error", timestamp: event.timestamp });
        break;
      case "harness_error":
        add({ label: "Needs attention", title: "The run hit an error", copy: compactText(data.error || "The harness reported an unknown error.", 420), icon: "!", tone: "error", timestamp: event.timestamp });
        break;
      case "interactive_step_limit":
      case "turn_limit":
        add({ label: "Paused", title: event.event === "turn_limit" ? "The run reached its turn limit" : "The run reached its action limit", copy: compactActivityCopy(event), icon: "Ⅱ", tone: "waiting", timestamp: event.timestamp });
        break;
      default:
        break;
    }
  }
  return items.slice(-60);
}

function activityStatusLabel(status) {
  return { working: "Working", checking: "Checking", complete: "Done", error: "Needs attention" }[status] || "Recorded";
}

function renderActivityFeedItem(item, current) {
  const currentClass = current ? " current" : "";
  const status = item.kind === "tool" || item.status === "working" || item.status === "checking" || item.status === "error"
    ? `<span class="run-activity-item-status">${escapeText(activityStatusLabel(item.status))}</span>`
    : "";
  const meta = item.meta ? `<code>${escapeText(item.meta)}</code>` : "";
  const copy = item.copy ? `<p>${escapeText(item.copy)}</p>` : "";
  return `<article class="run-activity-item ${escapeText(item.kind)} ${escapeText(item.tone)}${currentClass}">
    <div class="run-activity-item-icon" aria-hidden="true">${escapeText(item.icon)}</div>
    <div class="run-activity-item-body">
      <div class="run-activity-item-head"><span>${escapeText(item.label)}</span>${meta}<time>${escapeText(formatTime(item.timestamp))}</time></div>
      <div class="run-activity-item-title"><strong>${escapeText(item.title)}</strong>${status}</div>
      ${copy}
    </div>
  </article>`;
}

function runActivityStatus(status) {
  const labels = {
    running: "Working",
    waiting_approval: "Waiting for approval",
    success: "Finished",
    complete: "Finished",
    error: "Needs attention",
    failed: "Needs attention",
    interrupted: "Interrupted",
    blocked: "Blocked",
    ready: "Ready",
  };
  return labels[status] || statusLabel(status);
}

function runActivityTone(status) {
  if (["error", "failed"].includes(status)) return "error";
  if (["waiting_approval", "blocked"].includes(status)) return "waiting";
  if (["success", "complete"].includes(status)) return "complete";
  if (status === "interrupted") return "interrupted";
  return "running";
}

function runActivityHeading(status) {
  if (status === "running") return "The agent is working";
  if (status === "waiting_approval") return "The agent needs you";
  if (["error", "failed"].includes(status)) return "The run needs attention";
  if (["success", "complete"].includes(status)) return "The run is complete";
  if (status === "interrupted") return "The run was interrupted";
  if (status === "blocked") return "The run is blocked";
  return "Run activity";
}

function currentActivityItem(feed) {
  for (let index = feed.length - 1; index >= 0; index -= 1) {
    if (["working", "checking"].includes(feed[index].status)) return feed[index];
  }
  return feed[feed.length - 1] || null;
}

function runActivityNow(run, item) {
  const status = run.status || "idle";
  if (item) return { title: item.title, copy: item.copy || "The latest checkpoint is recorded below." };
  if (status === "waiting_approval") return { title: "Approval needed", copy: "Waiting for your approval before the next change." };
  if (["error", "failed"].includes(status)) return { title: "The run stopped", copy: readableSummary(run.summary?.summary) || "The run stopped before it could finish." };
  if (status === "interrupted") return { title: "The run is paused", copy: "Retry or resume when ready." };
  if (status === "blocked") return { title: "The workflow is blocked", copy: "Open Details to see what needs attention." };
  return { title: "Starting the run…", copy: "Waiting for the first checkpoint." };
}

function activityNearBottom(element) {
  return element.scrollHeight - element.scrollTop - element.clientHeight < 64;
}

function updateActivityJumpButton() {
  const timeline = $("runActivityTimeline");
  const button = $("runActivityJump");
  if (!timeline || !button) return;
  button.hidden = timeline.scrollHeight <= timeline.clientHeight || activityNearBottom(timeline);
}

function renderRunActivity(run) {
  const panel = $("runActivityPanel");
  const timeline = $("runActivityTimeline");
  const feedContainer = $("runActivityFeed");
  if (!panel || !timeline || !feedContainer) return;

  const events = Array.isArray(run.events) ? run.events.filter((event) => event && event.event) : [];
  const feed = deriveActivityFeed(events);
  const currentItem = currentActivityItem(feed);
  const status = run.status || "idle";
  const stateElement = $("runActivityState");
  const headingElement = $("runActivityHeading");
  const countElement = $("runActivityCount");
  const titleElement = $("runActivityNowTitle");
  const copyElement = $("runActivityNowCopy");
  const wasNewRun = timeline.dataset.runId !== run.run_id;
  const stickToBottom = wasNewRun || timeline.dataset.initialized !== "true" || activityNearBottom(timeline);
  const now = runActivityNow(run, currentItem);

  headingElement.textContent = runActivityHeading(status);
  stateElement.className = `run-activity-state ${runActivityTone(status)}`;
  stateElement.textContent = runActivityStatus(status);
  countElement.textContent = `${feed.length} activity item${feed.length === 1 ? "" : "s"}`;
  titleElement.textContent = now.title;
  copyElement.textContent = now.copy;

  if (!feed.length) {
    timeline.className = "run-activity-timeline empty-panel";
    feedContainer.className = "run-activity-feed empty-panel";
    feedContainer.innerHTML = '<div class="run-activity-empty">The run is starting. The first checkpoint will appear here.</div>';
  } else {
    timeline.className = "run-activity-timeline";
    feedContainer.className = "run-activity-feed";
    feedContainer.innerHTML = feed.map((item) => renderActivityFeedItem(item, item === currentItem && status === "running")).join("");
  }
  timeline.dataset.initialized = "true";
  timeline.dataset.runId = run.run_id || "";
  if (stickToBottom) timeline.scrollTop = timeline.scrollHeight;
  updateActivityJumpButton();
  panel.hidden = false;
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
      <div class="run-item-name">${escapeText(run.task_profile?.title || "Custom task")}</div>
      <div class="run-item-meta"><span class="run-item-status ${escapeText(run.status)}">${escapeText(run.status)}</span><span>${escapeText(run.run_id)}</span><span>${escapeText(run.changed_files?.length || 0)} files</span></div>
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
  const stop = $("stopJobButton");
  const button = $("retryJobButton");
  const note = $("chatNote");
  const send = $("sendButton");
  const approvalJob = $("approvalJob");
  const approvalCopy = $("approvalJobCopy");
  if (!button || !note || !send) return;
  const recoverable = isRecoverableJob(session);
  const busy = Boolean(session?.busy);
  const approval = session?.approval || {};
  const waitingApproval = approval.status === "pending";
  if (stop) {
    stop.hidden = !busy;
    stop.disabled = !busy;
  }
  button.hidden = !recoverable;
  button.disabled = false;
  button.textContent = session?.job?.status === "failed" ? "Retry failed turn" : "Resume interrupted turn";
  if (approvalJob) approvalJob.hidden = !waitingApproval;
  if (approvalCopy && waitingApproval) {
    const summary = approval.summary || {};
    approvalCopy.textContent = summary.action === "run_command"
      ? `The agent wants to run: ${summary.command || "a command"}`
      : `The agent wants to change ${summary.path || "the project"}.`;
  }
  send.disabled = Boolean(session?.busy || recoverable || waitingApproval);
  if (busy) {
    note.textContent = "The model is working...";
  } else if (recoverable) {
    note.textContent = "This turn stopped before finishing. Retry it to continue from the saved checkpoint.";
  } else if (waitingApproval) {
    note.textContent = "The agent is waiting for your approval before changing the project.";
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

function renderReview(review = state.activeRecord?.review) {
  const value = review && typeof review === "object" ? review : {};
  const status = ["current", "stale", "not_reviewed"].includes(value.status) ? value.status : "not_reviewed";
  const changedFiles = Array.isArray(value.changed_files) ? value.changed_files : [];
  const statusLabel = status === "current" ? "Current" : status === "stale" ? "Needs review" : "Not reviewed";
  const statusElement = $("reviewStatus");
  const summaryElement = $("reviewSummary");
  const statsElement = $("reviewStats");
  const filesElement = $("reviewFileList");
  const diffElement = $("reviewDiff");
  if (!statusElement || !summaryElement || !statsElement || !filesElement || !diffElement) return;
  statusElement.className = `review-status ${status}`;
  statusElement.textContent = statusLabel;
  if (status === "current") {
    summaryElement.textContent = changedFiles.length
      ? `${changedFiles.length} changed file${changedFiles.length === 1 ? "" : "s"} captured in the latest review.`
      : "The latest review found no project changes.";
  } else if (status === "stale") {
    summaryElement.textContent = "The project changed after this review. Run git_diff again before trusting the packet.";
  } else {
    summaryElement.textContent = "The harness has not captured a diff for this record yet.";
  }
  statsElement.innerHTML = [
    detailRow("Files", escapeText(changedFiles.length)),
    detailRow("Validation", value.validation?.passed ? "Passed" : value.validation?.command ? "Needs attention" : "Not recorded", "muted-value"),
    detailRow("Evaluator", value.evaluation?.configured ? (value.evaluation.passed ? "Passed" : "Failed") : "Not configured", "muted-value"),
  ].join("");
  filesElement.className = changedFiles.length ? "review-file-list" : "review-file-list empty-panel";
  filesElement.innerHTML = changedFiles.length
    ? changedFiles.map((file) => `
      <div class="review-file-row">
        <span class="review-file-status ${escapeText(file.status || "modified")}">${escapeText(file.status || "changed")}</span>
        <span class="review-file-name">${escapeText(file.path || "unknown file")}</span>
        <span class="review-file-size">${escapeText(file.after_bytes ?? 0)} B</span>
      </div>`).join("")
    : '<div>No changed files.</div><small>Run a diff review after making changes.</small>';
  diffElement.textContent = value.diff || "No diff captured.";
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
  const context = record?.context || {};
  const contextLabel = context.compacted
    ? `${formatTokenCount(context.after_tokens || 0)} / ${formatTokenCount(context.max_tokens || 0)} tokens · ${context.dropped_messages || 0} older messages summarized`
    : "No compaction yet";
  const workflow = normalizeWorkflow(record?.workflow);
  const skills = record?.skills || {};
  const skillNames = Array.isArray(skills.resolved) ? skills.resolved.map((item) => item.name).filter(Boolean) : [];
  const workspaceLock = record?.workspace_lock || {};
  const toolReceipt = record?.tool_receipt || {};
  const provider = providerForRecord(record);
  const taskProfile = record?.task_profile || record?.summary?.task_profile || {};
  const taskLabel = taskProfile.title || taskProfile.name || (state.activeKind === "run" ? "Custom task" : "Interactive chat");
  const receiptLabel = toolReceipt.status === "completed"
    ? "Completed; awaiting transcript settlement"
    : toolReceipt.status === "unknown"
      ? "Unknown; inspect before repeating"
      : toolReceipt.status === "settled"
        ? "Settled"
        : toolReceipt.status === "pending"
          ? "In progress"
          : "None";
  renderReasoningControl(record);
  renderApprovalControl(record);
  renderProviderControl(record);
  $("inspectorContent").innerHTML = [
    detailRow(state.activeKind === "run" ? "Run ID" : "Session ID", escapeText(id), "mono-value"),
    detailRow("Status", `<span class="status-inline"><span class="status-dot" aria-hidden="true"></span>${escapeText(statusLabel(status))}</span>`),
    detailRow("Model", escapeText(model)),
    detailRow("Task", escapeText(taskLabel), "muted-value"),
    detailRow("Provider", escapeText(provider.provider === "local" ? "Local model" : `${provider.label} · ${provider.model || "model not set"}`)),
    detailRow("Reasoning", escapeText(reasoningLabel)),
    detailRow("Tool approvals", escapeText(normalizeApprovalMode(record?.approval_mode || state.approvalMode) === "confirm" ? "Ask before edits" : "Autonomous")),
    detailRow("Tool receipt", escapeText(receiptLabel), "muted-value"),
    detailRow("Workspace lease", escapeText(workspaceLock.status === "held" ? "Held by this worker" : workspaceLock.status === "none" ? "Not held" : "Unavailable"), "muted-value"),
    detailRow("Thinking budget", escapeText(reasoningBudget), "muted-value"),
    detailRow("Response cap", `${formatTokenCount(reasoningMax)} tokens`, "muted-value"),
    detailRow("Context window", escapeText(contextLabel), "muted-value"),
    detailRow("Skills", escapeText(skillNames.length ? skillNames.join(" · ") : "None selected"), "muted-value"),
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
  renderReview(record);
}

function renderRunSurface(run) {
  const summary = run.summary || {};
  const taskProfile = run.task_profile || summary.task_profile || {};
  $("runEmptyState").hidden = true;
  $("runOverview").hidden = false;
  $("runTitle").textContent = run.run_id;
  $("runPresetLabel").textContent = taskProfile.title || taskProfile.name || "Custom task";
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
  renderRunActivity(run);
  const resumeButton = $("resumeRunButton");
  if (resumeButton) {
    resumeButton.hidden = run.status !== "interrupted";
    resumeButton.disabled = run.status === "running";
  }
  const stopButton = $("stopRunButton");
  if (stopButton) {
    stopButton.hidden = run.status !== "running";
    stopButton.disabled = run.status !== "running";
  }
  const waitingApproval = run.status === "waiting_approval" && run.approval?.status === "pending";
  const approveButton = $("approveRunButton");
  const denyButton = $("denyRunButton");
  if (approveButton) {
    approveButton.hidden = !waitingApproval;
    approveButton.disabled = !waitingApproval;
  }
  if (denyButton) {
    denyButton.hidden = !waitingApproval;
    denyButton.disabled = !waitingApproval;
  }
  renderReasoningControl(run);
  renderApprovalControl(run);
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
  renderApprovalControl(session);
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

function currentSkillOverrides() {
  return {
    enabled: [...new Set(state.skillOverrides.enabled || [])],
    disabled: [...new Set(state.skillOverrides.disabled || [])],
  };
}

function skillSelected(item) {
  const defaults = state.skillDefaults || [];
  const overrides = currentSkillOverrides();
  return overrides.enabled.includes(item.name) || (defaults.includes(item.name) && !overrides.disabled.includes(item.name));
}

function renderSkillControls() {
  const container = $("skillOverride");
  const summary = $("skillSummary");
  if (!container || !summary) return;
  if (!state.skills.length) {
    container.innerHTML = '<div class="muted">No skills are available for this project.</div>';
    summary.textContent = "No skills available";
    return;
  }
  const selected = state.skills.filter(skillSelected);
  const overrides = currentSkillOverrides();
  const overrideCount = overrides.enabled.length + overrides.disabled.length;
  summary.textContent = `${selected.length} selected · ${overrideCount ? `${overrideCount} task override${overrideCount === 1 ? "" : "s"}` : "trusted defaults"}`;
  container.innerHTML = state.skills.map((item) => `
    <label class="skill-option" for="skill-${escapeText(item.name)}">
      <input id="skill-${escapeText(item.name)}" type="checkbox" data-skill-name="${escapeText(item.name)}" ${skillSelected(item) ? "checked" : ""} ${item.activatable === false ? "disabled" : ""}>
      <span class="skill-option-copy">
        <span class="skill-option-name">${escapeText(item.name)}</span>
        <span class="skill-option-description">${escapeText(item.description)}</span>
      </span>
      <span class="skill-source">${escapeText(item.source)}</span>
    </label>`).join("");
  container.querySelectorAll("input[data-skill-name]").forEach((input) => {
    input.addEventListener("change", (event) => {
      const name = event.target.dataset.skillName;
      const isDefault = state.skillDefaults.includes(name);
      if (event.target.checked) {
        state.skillOverrides.disabled = state.skillOverrides.disabled.filter((value) => value !== name);
        if (!isDefault && !state.skillOverrides.enabled.includes(name)) state.skillOverrides.enabled.push(name);
      } else {
        state.skillOverrides.enabled = state.skillOverrides.enabled.filter((value) => value !== name);
        if (isDefault && !state.skillOverrides.disabled.includes(name)) state.skillOverrides.disabled.push(name);
      }
      renderSkillControls();
    });
  });
}

async function loadSkills(projectPath = "") {
  const query = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : "";
  const data = await api(`/api/skills${query}`);
  state.skills = data.skills || [];
  state.skillDefaults = data.defaults || [];
  const names = new Set(state.skills.map((item) => item.name));
  state.skillOverrides.enabled = (state.skillOverrides.enabled || []).filter((name) => names.has(name));
  state.skillOverrides.disabled = (state.skillOverrides.disabled || []).filter((name) => names.has(name));
  renderSkillControls();
}

function renderSkillResults(results, source = "local") {
  const container = $("skillResults");
  if (!container) return;
  if (!results.length) {
    container.textContent = source === "remote" ? "No remote recommendations returned." : "No matching local skills.";
    return;
  }
  container.innerHTML = results.map((item) => {
    const available = state.skills.some((skill) => skill.name === item.name && item.activatable !== false);
    return `<div class="skill-result">
      <div class="skill-result-copy"><div class="skill-result-name">${escapeText(item.name)}</div><div class="skill-result-meta">${escapeText(item.source)} · ${escapeText(item.quality || item.description || "Review before use.")}</div></div>
      ${available ? `<button class="text-button" type="button" data-use-skill="${escapeText(item.name)}">Use</button>` : ""}
    </div>`;
  }).join("");
  container.querySelectorAll("[data-use-skill]").forEach((button) => {
    button.addEventListener("click", () => {
      const name = button.dataset.useSkill;
      if (!state.skillDefaults.includes(name) && !state.skillOverrides.enabled.includes(name)) state.skillOverrides.enabled.push(name);
      state.skillOverrides.disabled = state.skillOverrides.disabled.filter((value) => value !== name);
      renderSkillControls();
    });
  });
}

async function searchSkills(source = "local") {
  const query = $("skillSearch").value.trim();
  if (!query) {
    $("skillResults").textContent = "Enter a capability to search for.";
    $("skillSearch").focus();
    return;
  }
  $("skillResults").textContent = source === "remote" ? "Searching skills.sh…" : "Searching the local catalog…";
  try {
    const result = await api("/api/skills/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        source,
        project_path: $("workspacePath").value.trim(),
        ...(source === "remote" ? { confirm_remote: true } : {}),
      }),
    });
    renderSkillResults(result.results || [], source);
  } catch (error) {
    $("skillResults").textContent = error.message;
  }
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
      body: JSON.stringify({ reasoning_level: state.reasoningLevel, approval_mode: state.approvalMode, project_path: projectPath, skill_overrides: currentSkillOverrides() }),
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
  if (isRecoverableJob(state.activeRecord) || state.activeRecord?.job?.status === "waiting_approval") return;
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

async function changeApprovalMode(event) {
  const nextMode = normalizeApprovalMode(event.target.value);
  const previousMode = normalizeApprovalMode(state.activeRecord?.approval_mode || state.approvalMode);
  if (state.activeKind === "run") {
    renderApprovalControl({ approval_mode: previousMode });
    setWorkspaceNotice("Tool approvals are fixed for a run. Choose the mode before starting the next one.", "error");
    return;
  }
  state.approvalMode = nextMode;
  renderApprovalControl({ approval_mode: nextMode });
  if (state.activeKind !== "session" || !state.activeSession) return;
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(state.activeSession)}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_mode: nextMode }),
    });
    renderSession(session);
    setWorkspaceNotice(nextMode === "confirm" ? "The agent will ask before changing the project." : "The agent can use approved tools autonomously.", "success");
  } catch (error) {
    state.approvalMode = previousMode;
    renderApprovalControl({ approval_mode: previousMode });
    $("chatNote").textContent = error.message;
    setWorkspaceNotice(`Could not change tool approvals: ${error.message}`, "error");
  }
}

async function resolveJobApproval(decision) {
  if (!state.activeSession) return;
  const buttons = [$("approveJobButton"), $("denyJobButton")].filter(Boolean);
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(state.activeSession)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    renderSession(session);
    setWorkspaceNotice(decision === "approve" ? "Change approved. The agent is continuing." : "Change denied. The agent is adapting.", "working");
    startSessionPolling();
  } catch (error) {
    buttons.forEach((button) => { button.disabled = false; });
    $("chatNote").textContent = error.message;
    setWorkspaceNotice(`Could not resolve approval: ${error.message}`, "error");
  }
}

async function stopJob() {
  if (!state.activeSession || !state.activeRecord?.busy) return;
  const button = $("stopJobButton");
  if (button) button.disabled = true;
  $("chatNote").textContent = "Stopping the current turn...";
  try {
    const session = await api(`/api/sessions/${encodeURIComponent(state.activeSession)}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    renderSession(session);
  } catch (error) {
    if (button) button.disabled = false;
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
  const taskName = $("taskPreset").value !== "custom" ? $("taskPreset").value : null;
  const projectPath = $("workspacePath").value.trim();
  const target = projectPath ? `the selected project ${shortenPath(projectPath)}` : "an isolated workspace";
  $("runButton").disabled = true;
  $("launchNote").textContent = `Starting in ${target}...`;
  setWorkspaceNotice(`Starting a run in ${target}.`, "working");
  try {
    const result = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_text: taskText, task_name: taskName, gated, reasoning_level: state.reasoningLevel, approval_mode: state.approvalMode, project_path: projectPath, skill_overrides: currentSkillOverrides() }),
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

async function resumeRun() {
  if (!state.activeRun) return;
  const button = $("resumeRunButton");
  if (button) button.disabled = true;
  $("launchNote").textContent = `Resuming ${state.activeRun}...`;
  setWorkspaceNotice(`Resuming ${state.activeRun}.`, "working");
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.activeRun)}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await selectRun(result.run_id);
    setWorkspaceNotice(`Run resumed in ${shortenPath(result.project || "the existing project")}.`, "success");
    startRunPolling();
  } catch (error) {
    if (button) button.disabled = false;
    $("launchNote").textContent = error.message;
    setWorkspaceNotice(`Could not resume the run: ${error.message}`, "error");
  }
}

async function stopRun() {
  if (!state.activeRun) return;
  const button = $("stopRunButton");
  if (button) button.disabled = true;
  $("launchNote").textContent = `Stopping ${state.activeRun}...`;
  setWorkspaceNotice(`Stopping ${state.activeRun}.`, "working");
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.activeRun)}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    await selectRun(result.run_id);
    setWorkspaceNotice(`Run stopped. Its saved checkpoint is available to resume.`, "success");
  } catch (error) {
    if (button) button.disabled = false;
    $("launchNote").textContent = error.message;
    setWorkspaceNotice(`Could not stop the run: ${error.message}`, "error");
  }
}

async function resolveRunApproval(decision) {
  if (!state.activeRun) return;
  const buttons = [$("approveRunButton"), $("denyRunButton")].filter(Boolean);
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const result = await api(`/api/runs/${encodeURIComponent(state.activeRun)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    await selectRun(result.run_id);
    setWorkspaceNotice(decision === "approve" ? "Change approved. The run is continuing." : "Change denied. The run is adapting.", "working");
    startRunPolling();
  } catch (error) {
    buttons.forEach((button) => { button.disabled = false; });
    $("launchNote").textContent = error.message;
    setWorkspaceNotice(`Could not resolve approval: ${error.message}`, "error");
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
    renderTaskPresetDescription(state.tasks[0]);
  } else {
    renderTaskPresetDescription(null);
  }
}

function renderTaskPresetDescription(task) {
  const description = $("taskPresetDescription");
  if (!description) return;
  description.textContent = task?.description || (task ? "Built-in task preset." : "Custom tasks run with no preset-specific completion gates.");
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

async function loadProvider() {
  try {
    const data = await api("/api/provider");
    state.provider = data.provider || state.provider;
  } catch (error) {
    // Keep the local default visible if an older server does not expose provider settings yet.
  }
  renderProviderControl();
}

function changeProviderType() {
  const next = normalizeProvider($("providerType").value);
  const fields = $("remoteProviderFields");
  if (fields) fields.hidden = next !== "openai_compatible";
  const status = $("providerStatus");
  if (status) status.textContent = next === "local"
    ? "Local model selected. The next chat or run stays on this machine."
    : "Remote model selected. Enter an endpoint, model name, and API key.";
}

async function saveProvider() {
  const button = $("saveProviderButton");
  const provider = normalizeProvider($("providerType").value);
  const payload = {
    provider,
    endpoint: $("providerEndpoint").value.trim(),
    model: $("providerModel").value.trim(),
    api_key: $("providerApiKey").value,
  };
  if (state.activeKind === "session" && state.activeSession) payload.session_id = state.activeSession;
  if (button) button.disabled = true;
  try {
    const result = await api("/api/provider", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.provider = result.provider || state.provider;
    renderProviderControl(result.session || state.activeRecord);
    if (result.session) renderSession(result.session);
    closeModal("providerDialog");
    const scope = result.session ? "this chat and new runs" : "new chats and runs";
    setWorkspaceNotice(`${provider === "local" ? "Local model" : "Remote API"} selected for ${scope}.`, "success");
  } catch (error) {
    $("providerStatus").textContent = error.message;
    setWorkspaceNotice(`Could not configure the model provider: ${error.message}`, "error");
  } finally {
    if (button) button.disabled = false;
  }
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
    renderTaskPresetDescription(task);
  } else {
    $("taskText").value = "";
    $("useGates").checked = false;
    renderTaskPresetDescription(null);
  }
});
$("newChatButton").addEventListener("click", () => createSession({ announce: true }));
$("newRunButton").addEventListener("click", () => openModal("runDialog", "newRunButton"));
$("emptyNewRunButton").addEventListener("click", () => openModal("runDialog", "emptyNewRunButton"));
$("workspaceDialogTrigger").addEventListener("click", () => openModal("workspaceDialog", "workspaceDialogTrigger"));
$("runButton").addEventListener("click", startRun);
$("sendButton").addEventListener("click", sendMessage);
$("runActivityTimeline").addEventListener("scroll", updateActivityJumpButton);
$("runActivityJump").addEventListener("click", () => {
  const timeline = $("runActivityTimeline");
  timeline.scrollTop = timeline.scrollHeight;
  updateActivityJumpButton();
});
$("stopJobButton").addEventListener("click", stopJob);
$("retryJobButton").addEventListener("click", retryJob);
$("reasoningLevel").addEventListener("change", changeReasoningLevel);
$("approvalMode").addEventListener("change", changeApprovalMode);
$("providerButton").addEventListener("click", () => openModal("providerDialog", "providerButton"));
$("providerType").addEventListener("change", changeProviderType);
$("saveProviderButton").addEventListener("click", saveProvider);
$("approveJobButton").addEventListener("click", () => resolveJobApproval("approve"));
$("denyJobButton").addEventListener("click", () => resolveJobApproval("deny"));
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
$("resetSkillsButton").addEventListener("click", () => {
  state.skillOverrides = { enabled: [], disabled: [] };
  renderSkillControls();
});
$("findSkillsButton").addEventListener("click", () => {
  const finder = $("skillFinder");
  const open = finder.hidden;
  finder.hidden = !open;
  $("findSkillsButton").setAttribute("aria-expanded", String(open));
  if (open) $("skillSearch").focus();
});
$("searchSkillsButton").addEventListener("click", () => searchSkills("local"));
$("searchRemoteSkillsButton").addEventListener("click", () => searchSkills("remote"));
$("skillSearch").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchSkills("local");
  }
});
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
$("stopRunButton").addEventListener("click", stopRun);
$("resumeRunButton").addEventListener("click", resumeRun);
$("approveRunButton").addEventListener("click", () => resolveRunApproval("approve"));
$("denyRunButton").addEventListener("click", () => resolveRunApproval("deny"));
$("runDetailsButton").addEventListener("click", () => setInspectorOpen(true));
$("closeInspector").addEventListener("click", () => setInspectorOpen(false));
$("detailsBackdrop").addEventListener("click", () => setInspectorOpen(false));
document.querySelectorAll(".details-tab").forEach((button) => {
  button.addEventListener("click", () => setDetailsTab(button.dataset.detailsTab));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const tabs = ["overview", "workflow", "review", "activity", "files"];
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
$("providerDialog").addEventListener("close", () => restoreModalFocus("providerDialog"));
$("workspaceDialog").addEventListener("click", (event) => {
  if (event.target === $("workspaceDialog")) closeModal("workspaceDialog");
});
$("runDialog").addEventListener("click", (event) => {
  if (event.target === $("runDialog")) closeModal("runDialog");
});
$("providerDialog").addEventListener("click", (event) => {
  if (event.target === $("providerDialog")) closeModal("providerDialog");
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
    await loadSkills($("workspacePath").value.trim());
    await Promise.all([loadReasoningLevels(), loadProvider(), loadTasks(), loadRuns(), loadSessions()]);
  } catch (error) {
    $("launchNote").textContent = error.message;
  }
  updateWorkspaceSummary();
  setMode("chats");
  setDetailsTab("overview");
}

bootstrap();

