// Agent Lab console controller: routing, data, replay, polling and actions.
// Rendering lives in views.js / recorder.js; derivations in model.js.
import { createSource, ShowcaseError } from "./source.js";
import { esc, buildRun, buildProcess, buildBench, taskTitle, chatTitle } from "./model.js";
import { benchView, runsView, runView, chatView } from "./views.js";

const $ = (id) => document.getElementById(id);
const view = $("view");
const phone = () => window.matchMedia("(max-width: 760px)").matches;

const state = {
  source: null,
  readOnly: false,
  route: { page: "" },
  runs: [],
  sessions: [],
  bench: null,
  showcaseRunIds: new Set(),
  cache: new Map(), // run id -> { state, events, next, complete, run, process }
  runUi: new Map(), // run id -> recorder ui state
  runsUi: { query: "", filter: "all" },
  chatUi: { draft: "", chatFiles: false, preview: null, sessionId: "" },
  session: null,
  tasks: [],
  levels: [],
  provider: null,
  projects: [],
  skills: { defaults: [], skills: [] },
  workspace: loadWorkspace(),
};

/* ---------- small utilities ---------- */

function loadWorkspace() {
  try {
    const saved = JSON.parse(localStorage.getItem("agentlab.workspace") || "null");
    if (saved && typeof saved.kind === "string") return saved;
  } catch { /* storage can be unavailable */ }
  return { kind: "scratch", path: "", name: "Scratch" };
}

function saveWorkspace() {
  try { localStorage.setItem("agentlab.workspace", JSON.stringify(state.workspace)); } catch { /* ignore */ }
}

function toast(message, tone = "") {
  const node = document.createElement("div");
  node.className = `toast ${tone}`;
  node.textContent = message;
  $("toasts").append(node);
  setTimeout(() => node.remove(), 4200);
}

async function attempt(fn, { busy } = {}) {
  if (busy) busy.disabled = true;
  try {
    return await fn();
  } catch (error) {
    toast(error instanceof ShowcaseError ? error.message : error?.message || String(error), "bad");
    return null;
  } finally {
    if (busy) busy.disabled = false;
  }
}

/* ---------- routing ---------- */

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const params = new URLSearchParams(query);
  const parts = path.split("/").filter(Boolean).map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
  if (parts[0] === "runs" && parts[1]) return { page: "run", id: parts[1], tab: parts[2] || "recorder", turn: Number(params.get("t")) || null, file: params.get("f") || "" };
  if (parts[0] === "runs") return { page: "runs" };
  if (parts[0] === "chats") return { page: "chats", id: parts[1] || "" };
  if (parts[0] === "bench") return { page: "bench", experiment: params.get("x") || "" };
  return { page: "home" };
}

function setQuery(params) {
  const [path] = location.hash.split("?");
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v != null && v !== "") q.set(k, v);
  const next = `${path}${q.toString() ? `?${q}` : ""}`;
  if (next !== location.hash) history.replaceState(null, "", next);
}

async function onRoute() {
  const route = parseRoute();
  if (route.page === "home") {
    location.replace(state.bench?.experiments?.some((e) => e.n) ? "#/bench" : "#/runs");
    return;
  }
  const changedPage = route.page !== state.route.page || route.id !== state.route.id;
  state.route = route;
  document.body.classList.toggle("in-chat", route.page === "chats" && Boolean(route.id));
  for (const link of document.querySelectorAll("[data-nav]")) {
    const nav = link.dataset.nav;
    link.setAttribute("aria-current", nav === route.page || (nav === "runs" && route.page === "run") ? "page" : "false");
  }
  stopReplay();
  if (route.page === "run") await openRun(route);
  else if (route.page === "chats") await openChat(route.id);
  else if (route.page === "runs") await refreshLists();
  render();
  if (changedPage) { window.scrollTo(0, 0); view.focus({ preventScroll: true }); }
}

/* ---------- data ---------- */

async function refreshLists() {
  const [runs, sessions] = await Promise.all([
    state.source.runs().catch(() => state.runs),
    state.source.sessions().catch(() => state.sessions),
  ]);
  state.runs = runs || [];
  state.sessions = (sessions || []).slice().sort((a, b) => String(b.session_id).localeCompare(String(a.session_id)));
}

async function loadBench() {
  const raw = await state.source.benchmarks().catch(() => ({ experiments: [], batches: [] }));
  state.bench = buildBench(raw || {});
}

async function fetchEvents(entry, id) {
  for (let guard = 0; guard < 200; guard++) {
    const page = await state.source.runEvents(id, entry.next || 0);
    const events = page.events || [];
    entry.events.push(...events);
    entry.next = page.next ?? entry.events.length;
    entry.complete = Boolean(page.complete);
    if (entry.complete || !events.length) break;
  }
}

async function loadRun(id) {
  let entry = state.cache.get(id);
  if (!entry) { entry = { state: null, events: [], next: 0, complete: false }; state.cache.set(id, entry); }
  const [runState] = await Promise.all([state.source.run(id), fetchEvents(entry, id)]);
  entry.state = runState;
  entry.run = buildRun(entry.events, runState);
  entry.process = buildProcess(runState, entry.run);
  return entry;
}

function uiFor(id) {
  if (!state.runUi.has(id)) state.runUi.set(id, { tab: "recorder", turn: null, upto: null, follow: true, playing: false, speed: 16, file: "", preview: null, logType: "" });
  return state.runUi.get(id);
}

function defaultTurn(run) {
  const alarm = run.alarms.find((a) => a.turn && a.state !== "RTN");
  if (alarm) return alarm.turn;
  return run.turns[run.turns.length - 1]?.n ?? null;
}

function defaultFileEvent(run) {
  const all = [...run.files.entries()].flatMap(([path, list]) => list.map((e) => ({ path, kind: e.kind, turn: e.turn })));
  const pick = all.find((e) => e.kind === "P!") || [...all].reverse().find((e) => e.kind === "X") || all[all.length - 1];
  return pick ? { file: pick.path, turn: pick.turn } : { file: "", turn: null };
}

async function openRun(route) {
  const ui = uiFor(route.id);
  ui.tab = route.tab;
  if (!state.cache.has(route.id)) view.innerHTML = '<div class="loading">READING THE RECORD</div>';
  const entry = await attempt(() => loadRun(route.id));
  if (!entry?.state) { state.cache.delete(route.id); return; }
  if (route.turn) ui.turn = route.turn;
  if (route.file) ui.file = route.file;
  if (ui.turn == null) ui.turn = defaultTurn(entry.run);
  if (ui.tab === "files" && !ui.file) {
    const pick = defaultFileEvent(entry.run);
    ui.file = pick.file;
    if (!route.turn && pick.turn) ui.turn = pick.turn;
  }
  if (phone() && ui.tab === "recorder" && !route.turn) ui.turn = null; // the tape opens folded on phones
}

async function openChat(id) {
  await refreshLists();
  if (!state.levels.length) state.levels = (await state.source.reasoningLevels().catch(() => [])) || [];
  state.session = id ? await attempt(() => state.source.session(id)) : null;
  if (id !== state.chatUi.sessionId) state.chatUi = { draft: "", chatFiles: false, preview: null, sessionId: id };
}

/* ---------- render ---------- */

function keepFocus(fn) {
  const active = document.activeElement;
  const id = active && active !== document.body ? active.id : "";
  const sel = id && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
  const keep = [".tape-h", ".score-h", ".matrix", ".process > div"].map((s) => [s, view.querySelector(s)]).filter(([, n]) => n).map(([s, n]) => [s, n.scrollLeft]);
  fn();
  for (const [s, left] of keep) { const n = view.querySelector(s); if (n) n.scrollLeft = left; }
  if (id) {
    const next = $(id);
    if (next && next !== document.activeElement) {
      next.focus({ preventScroll: true });
      if (sel && typeof next.setSelectionRange === "function") try { next.setSelectionRange(...sel); } catch { /* not text */ }
    }
  }
}

function render() {
  keepFocus(() => {
    const r = state.route;
    if (r.page === "bench") {
      view.innerHTML = state.bench ? benchView(state.bench, { experiment: r.experiment, linkable }) : '<div class="loading">LOADING</div>';
    } else if (r.page === "runs") {
      view.innerHTML = runsView(state.runs, state.runsUi, state.readOnly);
    } else if (r.page === "run") {
      const entry = state.cache.get(r.id);
      if (!entry?.state) {
        view.innerHTML = `<div class="empty"><h2>Run not available</h2><p>${state.readOnly ? "This run is not part of the showcase recording." : "The record could not be read."}</p><a class="btn" href="#/runs">All runs</a></div>`;
      } else {
        view.innerHTML = runView(entry.state, entry.run, uiFor(r.id), { readOnly: state.readOnly, process: entry.process, events: entry.events });
      }
    } else if (r.page === "chats") {
      view.innerHTML = chatView(state.sessions, state.session, state.chatUi, { readOnly: state.readOnly, levels: state.levels });
    }
  });
  renderShell();
}

function renderShell() {
  $("showcaseStrip").hidden = !state.readOnly;
  for (const id of ["newRunButton", "newChatButton", "newButton", "workspaceButton"]) $(id).hidden = state.readOnly;
  const p = state.provider || {};
  $("providerLabel").textContent = p.provider === "openai_compatible" ? p.model || "API model" : p.model || (state.readOnly ? "recording" : "local model");
  $("providerDot").className = `dot${p.provider === "openai_compatible" ? " remote" : ""}`;
  const w = state.workspace;
  $("workspaceLabel").textContent = w.kind === "scratch" ? "scratch" : w.name || w.path;
  const entry = state.route.page === "run" ? state.cache.get(state.route.id) : null;
  const titles = { bench: "Bench", runs: "Runs", chats: state.session ? chatTitle(state.session.conversation) : "Chats", run: entry?.state ? `${entry.run.verdict.word} · ${taskTitle(entry.state.task_profile)}` : "Run" };
  document.title = `${titles[state.route.page] || "Agent Lab"} · Agent Lab`;
}

function linkable(cell) {
  if (!cell.run_id) return false;
  return state.readOnly ? state.showcaseRunIds.has(cell.run_id) : Boolean(cell.has_record);
}

/* ---------- replay ---------- */

let raf = 0;
let lastFrame = 0;
let lastPaint = 0;

function currentRun() {
  if (state.route.page !== "run") return null;
  const entry = state.cache.get(state.route.id);
  return entry?.run ? { entry, ui: uiFor(state.route.id) } : null;
}

function followCursor(entry, ui) {
  const upto = ui.upto ?? entry.run.duration;
  const seen = entry.run.turns.filter((t) => t.at <= upto + 1e-6);
  if (seen.length) ui.turn = seen[seen.length - 1].n;
}

function startReplay() {
  const cur = currentRun();
  if (!cur) return;
  const { entry, ui } = cur;
  if (ui.upto == null || ui.upto >= entry.run.duration - 0.05) ui.upto = 0;
  ui.playing = true;
  ui.follow = false;
  if (ui.tab !== "recorder") { location.hash = `#/runs/${encodeURIComponent(state.route.id)}/recorder`; }
  lastFrame = performance.now();
  const step = (now) => {
    const c = currentRun();
    if (!c || !c.ui.playing) return;
    const dt = Math.min(0.25, (now - lastFrame) / 1000);
    lastFrame = now;
    c.ui.upto = Math.min(c.entry.run.duration, (c.ui.upto || 0) + dt * Number(c.ui.speed || 16));
    followCursor(c.entry, c.ui);
    if (c.ui.upto >= c.entry.run.duration) { c.ui.playing = false; c.ui.upto = null; render(); return; }
    if (now - lastPaint > 70) { lastPaint = now; render(); }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  render();
}

function stopReplay() {
  cancelAnimationFrame(raf);
  for (const ui of state.runUi.values()) ui.playing = false;
}

/* ---------- actions ---------- */

function selectTurn(n) {
  const cur = currentRun();
  if (!cur) return;
  const { entry, ui } = cur;
  if (ui.tab !== "recorder" && ui.tab !== "files") {
    location.hash = `#/runs/${encodeURIComponent(state.route.id)}/recorder?t=${n}`;
    return;
  }
  ui.turn = phone() && ui.tab === "recorder" && ui.turn === n ? null : n; // tap again to fold on phones
  if (ui.upto != null && (entry.run.turns.find((t) => t.n === n)?.at ?? 0) > ui.upto) ui.upto = null;
  setQuery({ t: ui.turn, f: ui.tab === "files" ? ui.file : "" });
  render();
}

async function onAction(act, el) {
  const cur = currentRun();
  const run = cur?.entry.state;
  const s = state.route.page === "chats" ? state.session : null;
  switch (act) {
    case "play":
      if (cur?.ui.playing) { stopReplay(); render(); } else startReplay();
      return;
    case "turn-step": {
      if (!cur) return;
      const turns = cur.entry.run.turns;
      const i = turns.findIndex((t) => t.n === cur.ui.turn);
      const next = turns[Math.max(0, Math.min(turns.length - 1, i + Number(el.dataset.step)))];
      if (next) selectTurn(next.n);
      return;
    }
    case "filter": state.runsUi.filter = el.dataset.filter; render(); return;
    case "open-file": {
      if (!cur) return;
      const path = el.dataset.file;
      const result = await state.source.runFile(state.route.id, path).catch((e) => ({ error: e.message }));
      cur.ui.preview = { path, content: result.content, error: result.error || (result.binary ? "Binary file." : "") };
      render();
      requestAnimationFrame(() => view.querySelector('[aria-label="Current file"]')?.scrollIntoView({ block: "start", behavior: "smooth" }));
      return;
    }
    case "close-preview": if (cur) { cur.ui.preview = null; render(); } return;
    case "chat-files": state.chatUi.chatFiles = !state.chatUi.chatFiles; state.chatUi.preview = null; render(); return;
    case "open-chat-file": {
      if (!s) return;
      const path = el.dataset.file;
      const result = await state.source.sessionFile(s.session_id, path).catch((e) => ({ error: e.message }));
      state.chatUi.preview = { path, content: result.content, error: result.error || (result.binary ? "Binary file." : "") };
      render();
      return;
    }
    case "new": return state.route.page === "chats" ? createChat() : openRunDialog();
    case "new-run": return openRunDialog();
    case "rerun": return openRunDialog(run);
    case "new-chat": return createChat();
    case "workspace": return openWorkspaceDialog();
    case "provider": return openProviderDialog();
    case "start-run": return startRun();
    case "save-provider": return saveProvider();
    case "create-project": return createProject();
    case "use-folder": return useFolder();
    case "skills-local": return searchSkills(false);
    case "skills-remote": return searchSkills(true);
    case "choose-ws": {
      const options = JSON.parse($("workspaceOptions").dataset.options || "[]");
      const option = options[Number(el.dataset.ws)];
      if (option) chooseWorkspace(option);
      return;
    }
    case "stop-run":
      if (run && (await attempt(() => state.source.stopRun(run.run_id)))) toast("Stopping the run. The project and record are kept.");
      break;
    case "resume-run":
      if (run && (await attempt(() => state.source.resumeRun(run.run_id)))) toast("Resuming from the last checkpoint.");
      break;
    case "approve-run":
    case "deny-run":
      if (run && (await attempt(() => state.source.resolveRunApproval(run.run_id, act === "approve-run" ? "approve" : "deny")))) toast(act === "approve-run" ? "Approved." : "Denied. The model will be told.");
      break;
    case "approve-job":
    case "deny-job":
      if (s && (await attempt(() => state.source.resolveJobApproval(s.session_id, act === "approve-job" ? "approve" : "deny")))) toast(act === "approve-job" ? "Approved." : "Denied. The model will be told.");
      break;
    case "retry-job":
      if (s) await attempt(() => state.source.retryJob(s.session_id));
      break;
    case "stop-job":
      if (s) await attempt(() => state.source.stopJob(s.session_id));
      break;
    default:
      return;
  }
  if (run) await refreshRun(true);
  if (s) await refreshSession();
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-act], [data-turn], [data-file]");
  if (!target) return;
  if (target.disabled || target.getAttribute("aria-disabled") === "true") { event.preventDefault(); return; }
  if (target.dataset.act) { event.preventDefault(); onAction(target.dataset.act, target); return; }
  const cur = currentRun();
  if (target.dataset.file && target.dataset.turn && cur) {
    cur.ui.file = target.dataset.file;
    cur.ui.turn = Number(target.dataset.turn);
    setQuery({ t: cur.ui.turn, f: cur.ui.file });
    render();
    if (phone()) requestAnimationFrame(() => view.querySelector('[aria-label="File event"]')?.scrollIntoView({ block: "start", behavior: "smooth" }));
    return;
  }
  if (target.dataset.turn) {
    event.preventDefault();
    const n = Number(target.dataset.turn);
    if (n) selectTurn(n);
  }
});

document.addEventListener("input", (event) => {
  const t = event.target;
  const cur = currentRun();
  if (t.id === "scrub" && cur) {
    stopReplay();
    cur.ui.upto = Number(t.value) >= cur.entry.run.duration - 0.05 ? null : Number(t.value);
    cur.ui.follow = cur.ui.upto == null;
    followCursor(cur.entry, cur.ui);
    render();
  } else if (t.id === "runSearch") {
    state.runsUi.query = t.value;
    render();
  } else if (t.id === "chatInput") {
    state.chatUi.draft = t.value;
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight, window.innerHeight * 0.4)}px`;
  }
});

document.addEventListener("change", async (event) => {
  const t = event.target;
  const cur = currentRun();
  if (t.id === "speed" && cur) { cur.ui.speed = Number(t.value); render(); }
  else if (t.id === "logType" && cur) { cur.ui.logType = t.value; render(); }
  else if (t.id === "presetSelect") { t.dataset.touched = "1"; applyPreset(); }
  else if (t.id === "reasoningSelect" && state.session) {
    const updated = await attempt(() => state.source.sessionSettings(state.session.session_id, { reasoning_level: t.value }));
    if (updated) { state.session = updated; render(); }
  } else if (t.id === "approvalSelect" && state.session) {
    const updated = await attempt(() => state.source.sessionSettings(state.session.session_id, { approval_mode: t.value }));
    if (updated) { state.session = updated; render(); }
  } else if (t.name === "provider") {
    $("remoteFields").hidden = t.value === "local";
  } else if (t.dataset?.skill) updateSkillSummary();
});

document.addEventListener("submit", (event) => {
  if (event.target.dataset.form !== "send") return;
  event.preventDefault();
  sendMessage();
});

document.addEventListener("keydown", (event) => {
  if (event.target.id === "chatInput" && event.key === "Enter" && !event.shiftKey && !event.isComposing && !phone()) {
    event.preventDefault();
    sendMessage();
    return;
  }
  const inRecorder = event.target.closest?.(".recorder, .turn-panel");
  if (inRecorder && (event.key === "ArrowLeft" || event.key === "ArrowRight") && event.target.id !== "scrub" && event.target.tagName !== "SELECT") {
    const cur = currentRun();
    if (!cur) return;
    event.preventDefault();
    const turns = cur.entry.run.turns;
    const i = turns.findIndex((t) => t.n === cur.ui.turn);
    const next = turns[Math.max(0, Math.min(turns.length - 1, i + (event.key === "ArrowLeft" ? -1 : 1)))];
    if (next) { selectTurn(next.n); $(`hit-${next.n}`)?.focus({ preventScroll: true }); }
  }
});

window.addEventListener("hashchange", onRoute);

/* ---------- chats ---------- */

async function sendMessage() {
  const s = state.session;
  const input = $("chatInput");
  const content = (input?.value || "").trim();
  if (!s || !content) return;
  const ok = await attempt(() => state.source.sendMessage(s.session_id, content), { busy: $("sendButton") });
  if (!ok) return;
  state.chatUi.draft = "";
  await refreshSession();
  requestAnimationFrame(() => $("chatMessages")?.lastElementChild?.scrollIntoView({ block: "end" }));
}

async function createChat() {
  const session = await attempt(() => state.source.createSession({
    reasoning_level: state.session?.reasoning?.level || "standard",
    approval_mode: state.session?.approval_mode || "auto",
    project_path: state.workspace.path,
  }));
  if (!session) return;
  state.sessions.unshift(session);
  location.hash = `#/chats/${encodeURIComponent(session.session_id)}`;
}

async function refreshSession() {
  if (!state.session) return;
  const updated = await state.source.session(state.session.session_id).catch(() => null);
  if (updated) { state.session = updated; if (state.route.page === "chats") render(); }
}

/* ---------- workspace ---------- */

const comparable = (p) => String(p || "").replace(/[\\/]+$/, "").toLowerCase();

function renderWorkspaceOptions() {
  const w = state.workspace;
  const options = [
    { kind: "scratch", path: "", name: "Scratch", note: "a fresh disposable folder for every chat or run" },
    ...state.projects.map((p) => ({ kind: "project", path: p.path, name: p.name, note: `${p.files} file${p.files === 1 ? "" : "s"} · managed project` })),
  ];
  if (w.kind === "folder") options.push({ kind: "folder", path: w.path, name: w.name || w.path, note: w.path });
  $("workspaceOptions").innerHTML = options.map((o, i) => {
    const current = o.kind === w.kind && (o.kind === "scratch" || comparable(o.path) === comparable(w.path));
    return `<button type="button" class="option" data-act="choose-ws" data-ws="${i}" aria-current="${current}"><b>${esc(o.name)}</b><small>${esc(o.note)}</small></button>`;
  }).join("");
  $("workspaceOptions").dataset.options = JSON.stringify(options);
}

function renderRunWorkspace() {
  const w = state.workspace;
  $("runWorkspaceName").textContent = w.kind === "scratch" ? "Scratch" : w.name || w.path;
  $("runWorkspaceNote").textContent = w.kind === "scratch" ? "a fresh disposable folder" : w.path;
}

async function openWorkspaceDialog() {
  if (state.readOnly) { toast(new ShowcaseError().message, "bad"); return; }
  state.projects = (await state.source.projects().catch(() => state.projects)) || [];
  renderWorkspaceOptions();
  if (!$("workspaceDialog").open) $("workspaceDialog").showModal();
}

function chooseWorkspace(option) {
  state.workspace = { kind: option.kind, path: option.path, name: option.name };
  saveWorkspace();
  renderWorkspaceOptions();
  renderRunWorkspace();
  renderShell();
  toast(`New chats and runs will use ${option.kind === "scratch" ? "a scratch folder" : option.name}.`);
  loadSkillsForWorkspace();
}

async function createProject() {
  const name = $("projectName").value.trim();
  if (!name) { toast("Name the project first.", "bad"); return; }
  const project = await attempt(() => state.source.createProject(name), { busy: $("createProjectButton") });
  if (!project) return;
  $("projectName").value = "";
  state.projects = (await state.source.projects().catch(() => state.projects)) || [];
  chooseWorkspace({ kind: "project", path: project.path || project.project?.path || "", name: project.name || name });
}

function useFolder() {
  const path = $("folderPath").value.trim();
  if (!path) return;
  chooseWorkspace({ kind: "folder", path, name: path.split(/[\\/]/).filter(Boolean).pop() || path });
}

/* ---------- new run ---------- */

const presetByName = (name) => state.tasks.find((t) => t.name === name);

async function openRunDialog(from = null) {
  if (state.readOnly) { toast(new ShowcaseError().message, "bad"); return; }
  if (!state.tasks.length) state.tasks = (await state.source.tasks().catch(() => [])) || [];
  if (!state.levels.length) state.levels = (await state.source.reasoningLevels().catch(() => [])) || [];
  $("presetSelect").innerHTML = state.tasks.map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`).join("") + '<option value="">Custom task</option>';
  const wanted = from?.task_profile?.name;
  if (wanted && presetByName(wanted)) $("presetSelect").value = wanted;
  else if (!$("presetSelect").dataset.touched && state.tasks.length) $("presetSelect").value = state.tasks[0].name;
  applyPreset();
  const level = from?.reasoning?.level || $("runReasoning").value || "standard";
  $("runReasoning").innerHTML = (state.levels.length ? state.levels : [{ value: "standard", label: "Standard" }]).map((l) => `<option value="${esc(l.value)}" ${l.value === level ? "selected" : ""}>${esc(l.label)}${l.description ? ` · ${esc(l.description)}` : ""}</option>`).join("");
  if (from?.approval_mode) $("runApproval").value = from.approval_mode;
  renderRunWorkspace();
  await loadSkillsForWorkspace();
  $("runDialog").showModal();
}

function applyPreset() {
  const task = presetByName($("presetSelect").value);
  $("presetDescription").textContent = task ? task.description || "" : "Describe any task. Custom runs are not graded.";
  if (task) {
    $("taskText").value = task.content;
    $("runGated").checked = true;
    $("runGated").disabled = false;
  } else {
    if (presetByName($("taskText").dataset.preset || "")) $("taskText").value = "";
    $("runGated").checked = false;
    $("runGated").disabled = true;
  }
  $("taskText").dataset.preset = $("presetSelect").value;
}

async function loadSkillsForWorkspace() {
  state.skills = (await state.source.skills(state.workspace.path).catch(() => state.skills)) || state.skills;
  const defaults = new Set(state.skills.defaults || []);
  $("skillList").innerHTML = (state.skills.skills || []).map((s) => `<label><input type="checkbox" data-skill="${esc(s.name)}" ${defaults.has(s.name) ? "checked" : ""}><span><b>${esc(s.name)}</b> <span class="dim">· ${esc(s.description || "")} · ${esc(s.source || "")}</span></span></label>`).join("") || '<p class="dim">No skills available.</p>';
  updateSkillSummary();
}

function skillOverrides() {
  const defaults = new Set(state.skills.defaults || []);
  const enabled = [];
  const disabled = [];
  for (const box of $("skillList").querySelectorAll("input[data-skill]")) {
    const name = box.dataset.skill;
    if (box.checked && !defaults.has(name)) enabled.push(name);
    if (!box.checked && defaults.has(name)) disabled.push(name);
  }
  return { enabled, disabled };
}

function updateSkillSummary() {
  const checked = [...$("skillList").querySelectorAll("input[data-skill]:checked")].map((b) => b.dataset.skill);
  $("skillsSummary").textContent = checked.length ? checked.join(", ") : "none";
}

async function searchSkills(remote) {
  const query = $("skillQuery").value.trim();
  if (!query) return;
  if (remote && !confirm("Search skills.sh? This sends your query to an external site. Results are suggestions; nothing is installed.")) return;
  const result = await attempt(() => state.source.discoverSkills({ query, source: remote ? "remote" : "local", confirm_remote: remote, project_path: state.workspace.path }));
  if (!result) return;
  $("skillResults").innerHTML = (result.results || []).map((r) => `<div><b>${esc(r.name || r.title || "skill")}</b> · ${esc(r.description || r.summary || "")}${r.url ? ` <span class="mono">${esc(r.url)}</span>` : ""}</div>`).join("") || "No matches.";
}

async function startRun() {
  const task = $("taskText").value.trim();
  if (!task) { toast("Write a task first.", "bad"); return; }
  const preset = presetByName($("presetSelect").value);
  const payload = {
    task_text: task,
    gated: $("runGated").checked,
    reasoning_level: $("runReasoning").value,
    approval_mode: $("runApproval").value,
    project_path: state.workspace.path,
    skill_overrides: skillOverrides(),
  };
  if (preset && $("runGated").checked) payload.task_name = preset.name;
  const result = await attempt(() => state.source.startRun(payload), { busy: $("startRunButton") });
  if (!result) return;
  $("runDialog").close();
  state.runs.unshift({ run_id: result.run_id, status: "running", task_profile: result.task_profile, reasoning_level: payload.reasoning_level });
  location.hash = `#/runs/${encodeURIComponent(result.run_id)}`;
}

/* ---------- provider ---------- */

function openProviderDialog() {
  const p = state.provider || {};
  const remote = p.provider === "openai_compatible";
  for (const input of document.querySelectorAll('input[name="provider"]')) { input.checked = input.value === (remote ? "openai_compatible" : "local"); input.disabled = state.readOnly; }
  $("remoteFields").hidden = !remote;
  $("providerEndpointInput").value = remote ? p.endpoint || "" : "";
  $("providerModelInput").value = remote ? p.model || "" : "";
  $("providerKeyInput").value = "";
  $("providerStatus").textContent = state.readOnly
    ? `Recorded with ${p.model || "the local model"}. The showcase cannot change providers.`
    : remote ? (p.has_api_key ? "A key is held in memory by this server process." : "No key is loaded yet.") : "The local llama.cpp model stays the default.";
  $("saveProviderButton").disabled = state.readOnly;
  $("providerDialog").showModal();
}

async function saveProvider() {
  const provider = document.querySelector('input[name="provider"]:checked')?.value || "local";
  const payload = { provider };
  if (provider !== "local") {
    payload.endpoint = $("providerEndpointInput").value.trim();
    payload.model = $("providerModelInput").value.trim();
    const key = $("providerKeyInput").value.trim();
    if (key) payload.api_key = key;
  }
  if (state.route.page === "chats" && state.session) payload.session_id = state.session.session_id;
  const result = await attempt(() => state.source.configureProvider(payload), { busy: $("saveProviderButton") });
  $("providerKeyInput").value = "";
  if (!result) return;
  state.provider = result.provider;
  if (result.session) state.session = result.session;
  $("providerDialog").close();
  render();
  toast(provider === "local" ? "Back on the local model." : `Using ${state.provider.model} through the API.`);
}

/* ---------- polling ---------- */

async function refreshRun(force = false) {
  const cur = currentRun();
  if (!cur) return;
  const status = cur.entry.state?.status;
  if (!force && status !== "running" && status !== "waiting_approval") return;
  const ui = cur.ui;
  const live = ui.follow && ui.upto == null;
  await loadRun(state.route.id).catch(() => null);
  if (live && !ui.playing && !phone()) followCursor(cur.entry, ui);
  if (!ui.playing) render();
}

let ticks = 0;
async function tick() {
  ticks += 1;
  if (document.hidden || state.readOnly) return;
  try {
    if (state.route.page === "run") await refreshRun();
    if (state.route.page === "chats" && state.session && (state.session.busy || state.session.job?.status === "running")) await refreshSession();
    if (state.route.page === "runs" && ticks % 4 === 0) { await refreshLists(); render(); }
  } catch { /* the next tick retries */ }
}

/* ---------- boot ---------- */

async function boot() {
  state.source = await createSource();
  state.readOnly = state.source.readOnly;
  try {
    await state.source.health();
  } catch (error) {
    view.innerHTML = `<div class="empty"><h2>Agent Lab is not reachable</h2><p>${esc(error.message)}</p><p class="mono dim">powershell -File .\\scripts\\start-agent-lab-ui.ps1</p></div>`;
    return;
  }
  const [provider, levels] = await Promise.all([
    state.source.provider().catch(() => null),
    state.source.reasoningLevels().catch(() => []),
    loadBench(),
    refreshLists(),
  ]);
  state.provider = provider;
  state.levels = levels || [];
  if (state.readOnly) state.showcaseRunIds = new Set(state.runs.map((r) => r.run_id));
  await onRoute();
  setInterval(tick, 1500);
}

boot();
