// Agent Lab console. Views render from the narration model; data comes from
// the live local API or, for the public showcase, from recorded runs.

import { createSource, ShowcaseError } from "./source.js";
import { buildRunModel, buildChatActivity, partsText, clockText, formatBytes, PHASES, chatTitle, runTitle } from "./narration.js";
import { Specimen } from "./specimen.js";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const TERMINAL = new Set(["success", "complete", "blocked", "error", "failed", "aborted"]);
const EXTENSION_LIMIT = 6;

const ICONS = {
  look: '<path d="M2 6.5a4.5 4.5 0 1 0 9 0a4.5 4.5 0 1 0-9 0M10 10l3 3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  read: '<path d="M2 3h4.5c.8 0 1.5.7 1.5 1.5V13c0-.8-.7-1.5-1.5-1.5H2zM14 3H9.5C8.7 3 8 3.7 8 4.5V13c0-.8.7-1.5 1.5-1.5H14z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>',
  write: '<path d="M3 13l1-3.5L11 2.5l2.5 2.5L6.5 12zM9.5 4l2.5 2.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  run: '<path d="M2.5 4l4 4-4 4M8 12.5h5.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
  diff: '<path d="M4 2v12M12 2v12M1.5 5H6.5M9.5 11h5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
  flag: '<path d="M3.5 14V2.5M3.5 3h8l-2 3 2 3h-8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>',
  check: '<path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
  x: '<path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  fold: '<path d="M3 5h10M3 8h7M3 11h4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
  loop: '<path d="M12.5 6A5 5 0 0 0 3.6 4.6M3.5 10A5 5 0 0 0 12.4 11.4M3 2v3h3M13 14v-3h-3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>',
  hand: '<path d="M5 8V3.5a1 1 0 0 1 2 0V7M7 7V2.5a1 1 0 0 1 2 0V7M9 7V3.5a1 1 0 0 1 2 0V9c0 3-1.5 5-4 5S3.5 12.5 3 10l-.5-2a1 1 0 0 1 2-.5L5 9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>',
  dot: '<circle cx="8" cy="8" r="2.5" fill="currentColor"/>',
};
const icon = (name) => `<svg viewBox="0 0 16 16" aria-hidden="true">${ICONS[name] || ICONS.dot}</svg>`;
const MINI_CELL = '<svg viewBox="-50 -50 100 100" aria-hidden="true"><circle r="34" fill="rgba(169,189,128,.08)" stroke="#879868" stroke-width="3"/><circle r="12" fill="#a9bd80"/><circle cx="-4" cy="-4" r="4" fill="#121512" opacity=".55"/></svg>';

function partsHtml(parts) {
  return (parts || []).map((part) => {
    if (part.t === "code") return `<code>${esc(part.v)}</code>`;
    if (part.t === "dim") return `<span class="dim">${esc(part.v)}</span>`;
    return esc(part.v);
  }).join("");
}

function timeAgo(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

function sessionStamp(id) {
  const m = /chat-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/.exec(id || "");
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6])).getTime() / 1000;
}

/* ---------------- state ---------------- */
const state = {
  source: null,
  mode: "runs",
  route: { kind: "runs", id: null },
  runs: [],
  sessions: [],
  tasks: [],
  levels: [],
  projects: [],
  provider: null,
  skills: { defaults: [], skills: [] },
  workspace: loadWorkspace(),
  filter: "",
  run: null, // { id, state, events, offset, complete, replay }
  session: null,
  drawer: { open: false, tab: "overview", file: null },
  firstShowcaseVisit: true,
};

function loadWorkspace() {
  try {
    const value = JSON.parse(localStorage.getItem("agentlab.workspace") || "null");
    if (value && typeof value === "object" && ["scratch", "project", "folder"].includes(value.kind)) return value;
  } catch { /* storage can be unavailable */ }
  return { kind: "scratch", path: "", name: "Temporary folder" };
}

function saveWorkspace() {
  try { localStorage.setItem("agentlab.workspace", JSON.stringify(state.workspace)); } catch { /* ignore */ }
}

/* ---------------- toasts & guards ---------------- */
function toast(message, tone = "") {
  const node = document.createElement("div");
  node.className = `toast ${tone}`;
  node.textContent = message;
  $("toasts").appendChild(node);
  setTimeout(() => { node.classList.add("leaving"); setTimeout(() => node.remove(), 300); }, tone === "bad" ? 6500 : 3800);
}

async function attempt(work, { busy } = {}) {
  if (busy) busy.disabled = true;
  try {
    return await work();
  } catch (error) {
    toast(error instanceof ShowcaseError ? error.message : error.message || String(error), "bad");
    return null;
  } finally {
    if (busy) busy.disabled = false;
  }
}

/* ---------------- routing ---------------- */
function parseHash() {
  const [kind, id] = (location.hash || "").replace(/^#\/?/, "").split("/");
  return { kind: kind === "chats" ? "chats" : "runs", id: id ? decodeURIComponent(id) : null };
}

function navigate(kind, id = null) {
  const hash = id ? `#/${kind}/${encodeURIComponent(id)}` : `#/${kind}`;
  if (location.hash === hash) route();
  else location.hash = hash;
}

async function route() {
  const { kind, id } = parseHash();
  state.route = { kind, id };
  setMode(kind);
  closeRail();
  if (kind === "runs") {
    stopReplay();
    if (id) await openRun(id);
    else showEmpty();
  } else if (id) {
    await openSession(id);
  } else {
    showEmpty();
  }
  renderList();
}

function setMode(mode) {
  state.mode = mode;
  $("modeRuns").setAttribute("aria-selected", String(mode === "runs"));
  $("modeChats").setAttribute("aria-selected", String(mode === "chats"));
  $("newLabel").textContent = mode === "runs" ? "New run" : "New chat";
  $("listHead").textContent = mode === "runs" ? "Recent runs" : "Conversations";
  $("listSearch").placeholder = mode === "runs" ? "Filter runs" : "Filter chats";
}

function showView(which) {
  for (const [name, el] of [["run", $("runView")], ["chat", $("chatView")], ["empty", $("emptyView")]]) el.hidden = name !== which;
  $("replay").hidden = which !== "run";
  $("chatControls").hidden = which !== "chat";
  $("runChips").hidden = which !== "run";
  $("detailsButton").hidden = which === "empty";
  if (which === "empty") setDrawer(false);
}

/* ---------------- list ---------------- */
function renderList() {
  const list = $("recordList");
  const filter = state.filter.trim().toLowerCase();
  if (state.mode === "runs") {
    const runs = state.runs.filter((r) => !filter || `${runTitle(r)} ${r.run_id} ${r.status}`.toLowerCase().includes(filter));
    list.innerHTML = runs.length ? runs.map((r) => {
      const level = r.reasoning_level || (/-(off|low|standard|deep|max)$/.exec(r.run_id) || [])[1] || "";
      const repaired = r.status === "success" && r.first_pass_passed === false;
      const meta = [r.elapsed_seconds != null ? clockText(r.elapsed_seconds) : "", r.status.replace(/_/g, " "), r.updated ? timeAgo(Date.now() / 1000 - r.updated) : ""].filter(Boolean).join(" · ");
      return `<li><button type="button" data-id="${esc(r.run_id)}" aria-current="${state.route.id === r.run_id}">
        <span class="d ${esc(r.status)}"></span>
        <span class="t"><b>${esc(runTitle(r))}</b><span>${esc(meta)}</span></span>
        ${repaired ? '<span class="lv repaired">repaired</span>' : level ? `<span class="lv">${esc(level)}</span>` : ""}
      </button></li>`;
    }).join("") : `<li class="none">${state.runs.length ? "Nothing matches." : "No runs yet. Start one and watch it work."}</li>`;
  } else {
    const sessions = state.sessions.filter((s) => !filter || chatTitle(s.conversation, "").toLowerCase().includes(filter));
    list.innerHTML = sessions.length ? sessions.map((s) => {
      const title = chatTitle(s.conversation, "Empty conversation");
      const count = (s.conversation || []).length;
      const stamp = sessionStamp(s.session_id);
      const status = s.busy ? "thinking" : s.job?.status === "interrupted" || s.job?.status === "failed" ? "interrupted" : s.job?.status === "waiting_approval" ? "waiting_approval" : "ready";
      const meta = [`${count} message${count === 1 ? "" : "s"}`, stamp ? timeAgo(Date.now() / 1000 - stamp) : ""].filter(Boolean).join(" · ");
      return `<li><button type="button" data-id="${esc(s.session_id)}" aria-current="${state.route.id === s.session_id}">
        <span class="d ${esc(status)}"></span><span class="t"><b>${esc(title)}</b><span>${esc(meta)}</span></span></button></li>`;
    }).join("") : `<li class="none">${state.sessions.length ? "Nothing matches." : "No conversations yet."}</li>`;
  }
}

async function loadLists() {
  const [runs, sessions] = await Promise.all([
    state.source.runs().catch(() => state.runs),
    state.source.sessions().catch(() => state.sessions),
  ]);
  state.runs = runs || [];
  state.sessions = (sessions || []).slice().sort((a, b) => String(b.session_id).localeCompare(String(a.session_id)));
  renderList();
}

/* ---------------- empty view ---------------- */
let emptySpecimen = null;
function showEmpty() {
  showView("empty");
  state.run = null;
  state.session = null;
  $("crumbs").innerHTML = state.mode === "runs" ? "<b>Runs</b>" : "<b>Chats</b>";
  if (!emptySpecimen) emptySpecimen = new Specimen($("emptySpecimen"));
  emptySpecimen.setMode("sleep");
  const showcase = state.source?.readOnly;
  $("emptyTitle").textContent = state.mode === "runs" ? "The specimen is resting." : "No conversation open.";
  $("emptyCopy").textContent = showcase
    ? "Pick a recorded run on the left to replay it exactly as it happened."
    : state.mode === "runs" ? "Start a run to watch a small model work through a task, or pick a past run to replay it." : "Open a conversation on the left, or start a new chat.";
}

/* ---------------- run view ---------------- */
let runSpecimen = null;
const feedState = { keys: new Map(), runId: null, evalCount: 0, toolRows: 0, waiting: null, follow: true };

async function fetchAllEvents(run) {
  for (let guard = 0; guard < 50; guard += 1) {
    const page = await state.source.runEvents(run.id, run.offset);
    run.events.push(...(page.events || []));
    run.offset = page.next ?? run.offset + (page.events || []).length;
    if (page.complete || !(page.events || []).length) break;
  }
}

async function openRun(id) {
  showView("run");
  if (!runSpecimen) runSpecimen = new Specimen($("runSpecimen"));
  const switching = state.run?.id !== id;
  if (switching) {
    state.run = { id, state: null, events: [], offset: 0 };
    resetFeed(id);
    $("feed").innerHTML = '<div class="waiting">Opening the record…</div>';
  }
  const run = state.run;
  try {
    const [runState] = await Promise.all([state.source.run(id), fetchAllEvents(run)]);
    if (state.run !== run) return;
    run.state = runState;
  } catch (error) {
    toast(error.message, "bad");
    return;
  }
  renderRun();
  if (state.drawer.open) renderDrawer();
  if (state.source.readOnly && state.firstShowcaseVisit && TERMINAL.has(run.state.status)) {
    state.firstShowcaseVisit = false;
    startReplay();
  }
}

async function refreshRun() {
  const run = state.run;
  if (!run || run.replay) return;
  try {
    const [runState] = await Promise.all([state.source.run(run.id), fetchAllEvents(run)]);
    if (state.run !== run) return;
    run.state = runState;
    renderRun();
    if (state.drawer.open && state.drawer.tab !== "files") renderDrawer();
  } catch { /* the next tick retries */ }
}

function resetFeed(runId) {
  feedState.keys = new Map();
  feedState.runId = runId;
  feedState.evalCount = 0;
  feedState.toolRows = 0;
  feedState.waiting = null;
  feedState.follow = true;
  $("feed").innerHTML = "";
}

function pinFeed() {
  const feed = $("feed");
  if (feedState.follow) feed.scrollTop = feed.scrollHeight;
  $("jumpButton").hidden = feedState.follow || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
}

function rowSignature(row) {
  return JSON.stringify([row.state, row.parts, row.detail, row.phaseTag, row.eval?.index]);
}

function rowHtml(row) {
  if (row.kind === "eval") {
    const e = row.eval;
    const findings = e.findings.length ? `<ul>${e.findings.map((f) => `<li><code>${esc(f.id)}</code>${esc(f.message)}</li>`).join("")}</ul>` : "";
    const counts = e.total ? `${e.passedCount}/${e.total} checks · ` : "";
    return `<header><b>${partsHtml(row.parts)}</b><span>evaluation ${e.index} · ${counts}${clockText(row.at)}</span></header>${e.error ? `<p class="dim">${esc(e.error)}</p>` : ""}${findings}`;
  }
  const dots = row.state === "active" ? '<span class="dots"><i></i><i></i><i></i></span>' : "";
  const tag = row.phaseTag ? `<span class="ptag">→ ${esc(row.phaseTag)}</span>` : "";
  return `<div class="turn">${row.turn ? `T${row.turn}` : ""}</div><div class="ic">${icon(row.icon)}</div>
    <div class="body"><span class="main">${partsHtml(row.parts)}${dots}${tag}</span>${row.detail ? `<span class="detail">${esc(row.detail)}</span>` : ""}</div>
    <div class="t">${clockText(row.at)}</div>`;
}

function rowClass(row, fresh) {
  return `${row.kind === "eval" ? "eval-row" : "row"} ${row.state}${fresh ? " fresh" : ""}`;
}

function renderFeed(model, { animate = true } = {}) {
  const feed = $("feed");
  if (model.rows.length < feedState.keys.size) resetFeed(state.run?.id);
  feed.querySelector(".waiting.placeholder")?.remove();
  if (!feedState.keys.size) feed.innerHTML = "";
  for (const row of model.rows) {
    const existing = feedState.keys.get(row.key);
    const signature = rowSignature(row);
    if (!existing) {
      const node = document.createElement("div");
      node.className = rowClass(row, animate);
      node.innerHTML = rowHtml(row);
      feed.insertBefore(node, feedState.waiting && feedState.waiting.parentNode === feed ? feedState.waiting : null);
      feedState.keys.set(row.key, { node, signature });
    } else if (existing.signature !== signature) {
      existing.node.className = rowClass(row, false);
      existing.node.innerHTML = rowHtml(row);
      existing.signature = signature;
    }
  }
  const thinking = !model.finished && model.now.mode === "think" && model.rows.length;
  if (thinking) {
    if (!feedState.waiting) {
      feedState.waiting = document.createElement("div");
      feedState.waiting.className = "waiting";
    }
    feedState.waiting.innerHTML = `Thinking about turn ${model.turn + 1}<span class="dots"><i></i><i></i><i></i></span>`;
    feed.appendChild(feedState.waiting);
  } else if (feedState.waiting) {
    feedState.waiting.remove();
  }
  $("feedCount").textContent = `${model.rows.length} entries`;
  pinFeed();
}

function renderChecks(model, animate) {
  const checks = model.checks;
  if (!checks) {
    $("checks").innerHTML = `<div class="ck-empty">${model.finished ? "This run had no external evaluation." : "Checks appear when the agent asks to finish."}</div>`;
    $("evalLabel").textContent = "not run yet";
    return;
  }
  const flipped = animate && model.evalCount !== feedState.evalCount;
  const entries = Object.entries(checks).sort((a, b) => Number(a[1]) - Number(b[1]));
  $("checks").innerHTML = entries.map(([name, ok]) => {
    const changed = flipped && model.previousChecks && model.previousChecks[name] !== undefined && model.previousChecks[name] !== ok;
    return `<div class="ck ${ok ? "pass" : "fail"}${changed ? " flip" : ""}" title="${esc(name)}"><i></i><span>${esc(name.replace(/_/g, " "))}</span></div>`;
  }).join("");
  const passed = entries.filter(([, ok]) => ok).length;
  $("evalLabel").textContent = `evaluation ${model.evalCount} · ${passed}/${entries.length}`;
}

function renderMeter(model, maxTurns) {
  const cells = maxTurns + EXTENSION_LIMIT;
  const used = model.calls;
  const meter = $("meter");
  meter.style.setProperty("--cells", String(cells));
  let html = "";
  for (let i = 0; i < cells; i += 1) {
    const ext = i >= maxTurns;
    html += `<i class="${ext ? "ext" : ""}${i < used ? " used" : ""}${i === used - 1 && !model.finished ? " cur" : ""}"></i>`;
  }
  meter.innerHTML = html;
  $("callsUsed").textContent = String(Math.min(used, maxTurns));
  $("callsMax").textContent = String(maxTurns);
  $("extNote").textContent = used > maxTurns ? `+${used - maxTurns} extra` : "";
  $("toolsUsed").textContent = String(model.tools);
  $("budgetLabel").textContent = model.finished ? "final" : "live";
}

function renderFiles(files, freshPath) {
  const list = $("files");
  if (!files.length) {
    list.innerHTML = '<li class="none">No files yet.</li>';
    $("fileCount").textContent = "";
    return;
  }
  list.innerHTML = files.map((f) => `<li class="${f.path === freshPath ? "fresh" : ""}"><button type="button" data-path="${esc(f.path)}">${esc(f.path)}<span>${esc(formatBytes(f.bytes))}</span></button></li>`).join("");
  $("fileCount").textContent = `${files.length} in project`;
}

const CHAMBER_COLORS = { think: "var(--live)", tool: "var(--live)", idle: "var(--live)", pass: "var(--live)", wait: "var(--ochre)", fail: "var(--rust)", sleep: "var(--sage)" };

function renderRun(options = {}) {
  const run = state.run;
  if (!run?.state) return;
  const rs = run.state;
  const replaying = Boolean(run.replay);
  const events = replaying ? run.events.slice(0, run.replay.index) : run.events;
  const replayDone = replaying && run.replay.index >= run.events.length;
  const status = replaying && !replayDone ? "running" : rs.status;
  const model = buildRunModel(events, {
    status,
    firstPassPassed: rs.summary?.first_pass_passed ?? rs.progress?.first_pass_passed,
    blockedReason: rs.summary?.blocked_reason || rs.progress?.blocked_reason || "",
  });
  const animate = options.animate !== false;
  const maxTurns = Number(rs.max_turns) || 18;

  $("crumbs").innerHTML = `Runs / <b>${esc(runTitle(rs))}</b><code>${esc(rs.run_id)}</code>`;
  const level = rs.reasoning?.level || rs.summary?.reasoning?.level || "";
  $("runChips").innerHTML = [
    level ? `<span class="chip">Reasoning <em>${esc(level)}</em></span>` : "",
    `<span class="chip">Model <em>${esc(rs.model || rs.provider?.model || "local")}</em></span>`,
    rs.approval_mode === "confirm" ? '<span class="chip">Tools <em>ask first</em></span>' : "",
  ].join("");

  // specimen and chamber
  const mode = model.now.mode;
  runSpecimen.setMode(mode);
  const newTools = model.rows.filter((r) => r.state === "active" || r.icon !== "dot").length;
  if (animate && (newTools > feedState.toolRows || model.evalCount > feedState.evalCount)) runSpecimen.pulse(model.evalCount > feedState.evalCount);
  feedState.toolRows = newTools;
  $("chamber").style.setProperty("--chamber", CHAMBER_COLORS[mode] || "var(--live)");

  const live = $("liveLabel");
  live.textContent = replaying ? (replayDone ? "Replayed" : "Replay") : model.finished ? "Recorded" : rs.status === "waiting_approval" ? "Waiting" : rs.status === "interrupted" ? "Paused" : "Live";
  live.classList.toggle("still", model.finished || rs.status === "interrupted");
  $("turnNo").textContent = String(model.turn);
  $("turnMax").textContent = String(maxTurns);
  const title = $("nowTitle");
  title.innerHTML = partsHtml(model.now.title);
  title.classList.toggle("shimmer", Boolean(model.now.shimmer) && !reducedMotion);
  const sub = $("nowSub");
  sub.textContent = model.now.sub || "";
  sub.className = `sub ${model.now.tone || ""}`;
  updateClock(model);

  // verdict and actions
  const verdict = $("verdict");
  if (model.finished) {
    const passed = rs.status === "success" || rs.status === "complete" || model.finish?.status === "success";
    const repaired = passed && (rs.summary?.first_pass_passed === false);
    $("stamp").className = `stamp ${passed ? "pass" : "fail"}`;
    $("stamp").textContent = passed ? (repaired ? "Passed · repaired" : model.evalCount ? "Passed" : "Finished") : rs.status === "error" ? "Error" : "Blocked";
    const seconds = replaying ? (model.lastTs - model.startTs) / 1000 : rs.summary?.elapsed_seconds;
    $("verdictSub").textContent = `${model.calls} calls · ${model.tools} tools · ${clockText(seconds)}`;
    verdict.hidden = false;
  } else {
    verdict.hidden = true;
  }
  const actions = [];
  if (!replaying && !state.source.readOnly) {
    if (rs.status === "running") actions.push('<button class="ghost danger" type="button" data-act="stop-run">Stop run</button>');
    if (rs.status === "interrupted") actions.push('<button class="primary" type="button" data-act="resume-run">Resume run</button>');
  }
  $("runActions").innerHTML = actions.join("");

  // approval
  const approval = rs.approval || {};
  const pending = !replaying && (rs.status === "waiting_approval" || approval.status === "pending");
  $("runApproval").hidden = !pending;
  if (pending) $("runApproval").innerHTML = approvalHtml(approval, "run");

  // phases
  const phaseIndex = PHASES.indexOf(model.phase);
  $("phases").innerHTML = PHASES.map((p, i) => {
    const cls = model.phase === "complete" || i < phaseIndex ? "done" : i === phaseIndex && !model.finished ? "on" : "";
    return `<div class="ph ${cls}"><i></i>${p}</div>`;
  }).join("");

  renderFeed(model, { animate });
  renderChecks(model, animate);
  feedState.evalCount = model.evalCount;
  renderMeter(model, maxTurns);
  const files = replaying
    ? [...model.files].map(([path, bytes]) => ({ path, bytes }))
    : (rs.files || []);
  renderFiles(files, replaying ? [...model.files.keys()].pop() : null);
  const quote = model.finish?.summary || (model.finished ? rs.summary?.summary : "");
  $("quoteCard").hidden = !(model.finished && quote);
  $("quote").textContent = quote || "";

  // replay controls
  $("replayButton").disabled = rs.status === "running" || !run.events.length;
  updateScrub();
  state.lastModel = model;
}

function updateClock(model = state.lastModel) {
  const run = state.run;
  if (!run?.state || !model) return;
  let seconds;
  if (run.replay) seconds = run.replay.position;
  else if (model.finished) seconds = run.state.summary?.elapsed_seconds ?? (model.lastTs - model.startTs) / 1000;
  else seconds = model.startTs ? (Date.now() - model.startTs) / 1000 : 0;
  $("clock").textContent = clockText(seconds);
}

function approvalHtml(approval, scope) {
  const bits = [];
  if (approval.path) bits.push(`<code>${esc(approval.path)}</code>`);
  if (approval.command) bits.push(`<code>${esc(approval.command)}</code>`);
  if (approval.content_bytes != null) bits.push(`${esc(formatBytes(approval.content_bytes))} of content`);
  const action = String(approval.action || "a change").replace(/_/g, " ");
  return `<div><h3>The specimen wants to ${esc(action)}</h3><p>${bits.join(" · ") || "Review the request in Details before deciding."}</p></div>
    <div class="actions"><button class="ghost danger" type="button" data-act="deny-${scope}">Deny</button><button class="primary" type="button" data-act="approve-${scope}">Approve</button></div>`;
}

/* ---------------- replay ---------------- */
function replayTimeline(events) {
  if (!events.length) return [];
  const start = Date.parse(events[0].timestamp);
  const out = [];
  let lastSecond = null;
  let k = 0;
  for (const ev of events) {
    const second = (Date.parse(ev.timestamp) - start) / 1000;
    k = second === lastSecond ? k + 1 : 0;
    lastSecond = second;
    out.push(second + Math.min(0.9, k * 0.18));
  }
  return out;
}

function startReplay() {
  const run = state.run;
  if (!run?.events.length) return;
  stopReplay(false);
  const times = replayTimeline(run.events);
  run.replay = { times, index: 0, position: 0, total: times[times.length - 1] || 0, playing: true, speed: currentSpeed(), last: performance.now(), raf: 0 };
  resetFeed(run.id);
  $("replayIcon").setAttribute("d", "M3 1.5h2v9H3zM7 1.5h2v9H7z");
  $("replayButton").setAttribute("aria-label", "Pause replay");
  renderRun();
  run.replay.raf = requestAnimationFrame(replayTick);
}

function replayTick(now) {
  const run = state.run;
  const replay = run?.replay;
  if (!replay || !replay.playing) return;
  replay.position += ((now - replay.last) / 1000) * replay.speed;
  replay.last = now;
  let advanced = false;
  while (replay.index < replay.times.length && replay.times[replay.index] <= replay.position) {
    replay.index += 1;
    advanced = true;
  }
  if (advanced) renderRun();
  else { updateClock(); updateScrub(); }
  if (replay.index >= replay.times.length) {
    finishReplay();
    return;
  }
  replay.raf = requestAnimationFrame(replayTick);
}

function pauseReplay() {
  const replay = state.run?.replay;
  if (!replay) return;
  replay.playing = false;
  cancelAnimationFrame(replay.raf);
  $("replayIcon").setAttribute("d", "M3 1.5v9l7.5-4.5z");
  $("replayButton").setAttribute("aria-label", "Resume replay");
}

function resumeReplay() {
  const replay = state.run?.replay;
  if (!replay) return;
  replay.playing = true;
  replay.last = performance.now();
  $("replayIcon").setAttribute("d", "M3 1.5h2v9H3zM7 1.5h2v9H7z");
  $("replayButton").setAttribute("aria-label", "Pause replay");
  replay.raf = requestAnimationFrame(replayTick);
}

function finishReplay() {
  const replay = state.run?.replay;
  if (!replay) return;
  replay.playing = false;
  replay.position = replay.total;
  renderRun();
  $("replayIcon").setAttribute("d", "M3 1.5v9l7.5-4.5z");
  $("replayButton").setAttribute("aria-label", "Replay this run");
  // Hand back to the recorded state so later polls render normally.
  state.run.replay = null;
  updateScrub();
}

function stopReplay(render = true) {
  const replay = state.run?.replay;
  if (!replay) return;
  cancelAnimationFrame(replay.raf);
  state.run.replay = null;
  $("replayIcon").setAttribute("d", "M3 1.5v9l7.5-4.5z");
  $("replayButton").setAttribute("aria-label", "Replay this run");
  if (render) {
    resetFeed(state.run.id);
    renderRun({ animate: false });
  }
}

function seekReplay(fraction) {
  const run = state.run;
  if (!run?.events.length) return;
  if (!run.replay) {
    startReplay();
    pauseReplay();
  }
  const replay = run.replay;
  replay.position = Math.max(0, Math.min(1, fraction)) * replay.total;
  replay.index = replay.times.findIndex((t) => t > replay.position);
  if (replay.index < 0) replay.index = replay.times.length;
  resetFeed(run.id);
  renderRun({ animate: false });
  if (replay.index >= replay.times.length) finishReplay();
}

function currentSpeed() {
  return Number($("speed").querySelector(".on")?.dataset.speed || 4);
}

function updateScrub() {
  const replay = state.run?.replay;
  const fraction = replay ? (replay.total ? replay.position / replay.total : 1) : 1;
  $("scrubFill").style.width = `${Math.min(100, fraction * 100)}%`;
  $("scrub").setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
}

/* ---------------- chat view ---------------- */
let chatSpecimen = null;

async function openSession(id) {
  showView("chat");
  try {
    const session = await state.source.session(id);
    state.session = session;
  } catch (error) {
    toast(error.message, "bad");
    return;
  }
  renderSession({ scroll: true });
  if (state.drawer.open) renderDrawer();
}

async function refreshSession() {
  const current = state.session;
  if (!current) return;
  try {
    const session = await state.source.session(current.session_id);
    if (state.session?.session_id !== session.session_id) return;
    const changed = JSON.stringify([session.conversation?.length, session.events?.length, session.busy, session.job?.status, session.status]) !==
      JSON.stringify([current.conversation?.length, current.events?.length, current.busy, current.job?.status, current.status]);
    state.session = session;
    if (changed) {
      renderSession({ scroll: true });
      if (state.drawer.open) renderDrawer();
    } else {
      updateLiveClock();
    }
  } catch { /* retry on the next tick */ }
}

function workHtml(rows) {
  return rows.map((row) => `<div class="row ${row.state}"><div class="turn"></div><div class="ic">${icon(row.icon)}</div><div class="body"><span class="main">${partsHtml(row.parts)}${row.state === "active" ? '<span class="dots"><i></i><i></i><i></i></span>' : ""}</span>${row.detail ? `<span class="detail">${esc(row.detail)}</span>` : ""}</div></div>`).join("");
}

function renderSession({ scroll = false } = {}) {
  const s = state.session;
  if (!s) return;
  const title = chatTitle(s.conversation, "New conversation");
  $("crumbs").innerHTML = `Chats / <b>${esc(title)}</b>`;
  syncChatControls(s);
  const box = $("chatScroll");
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  const conversation = s.conversation || [];
  const activity = buildChatActivity(s.events);
  const assistantIndexes = conversation.map((m, i) => (m.role === "assistant" ? i : -1)).filter((i) => i >= 0);
  const groupFor = new Map();
  for (let k = 0; k < Math.min(assistantIndexes.length, activity.groups.length); k += 1) {
    groupFor.set(assistantIndexes[assistantIndexes.length - 1 - k], activity.groups[activity.groups.length - 1 - k]);
  }
  const parts = [];
  if (!conversation.length && !s.busy) {
    parts.push(`<div class="chat-empty"><div class="specimen" id="chatEmptySpecimen"></div><h1>The specimen is awake.</h1><p>Ask it to inspect the project, explain something, or make a focused change. It works inside <b>${esc(workspaceLabel(s.project))}</b>.</p></div>`);
  }
  conversation.forEach((message, index) => {
    if (message.role === "user") {
      parts.push(`<div class="msg user"><div class="bubble">${esc(message.content)}</div></div>`);
      return;
    }
    const group = groupFor.get(index);
    const work = group && group.rows.length
      ? `<details class="work"><summary>Worked through ${group.rows.length} step${group.rows.length === 1 ? "" : "s"}${group.seconds ? ` · ${clockText(group.seconds)}` : ""}</summary><div class="rows">${workHtml(group.rows)}</div></details>`
      : "";
    const error = /^The local session hit an error|^I hit the action limit/.test(message.content || "");
    parts.push(`<div class="msg agent"><div class="avatar">${MINI_CELL}</div><div>${work}<div class="bubble${error ? " error" : ""}">${esc(message.content)}</div></div></div>`);
  });
  if (s.busy) {
    const live = activity.live;
    const current = [...live.rows].reverse().find((r) => r.state === "active");
    const nowLine = current ? partsHtml(current.parts) : "Thinking";
    parts.push(`<div class="msg agent"><div class="avatar"><div class="specimen" id="chatLiveSpecimen"></div></div><div class="live-work">
      <div class="now-line"><span class="${reducedMotion ? "" : "shimmer"}">${nowLine}</span><small id="liveClock"></small></div>
      ${live.rows.length ? `<div class="rows">${workHtml(live.rows)}</div>` : ""}</div></div>`);
  }
  $("chatMessages").innerHTML = parts.join("");
  const liveHost = $("chatLiveSpecimen") || $("chatEmptySpecimen");
  if (chatSpecimen) chatSpecimen.destroy();
  chatSpecimen = liveHost ? new Specimen(liveHost, { motes: liveHost.id === "chatLiveSpecimen" ? 3 : 7 }) : null;
  if (chatSpecimen) {
    const current = (activity.live.rows || []).some((r) => r.state === "active");
    chatSpecimen.setMode(liveHost.id === "chatEmptySpecimen" ? "idle" : current ? "tool" : "think");
  }
  updateLiveClock();
  renderJobBanner(s);
  const busy = Boolean(s.busy);
  $("chatInput").disabled = busy || state.source.readOnly;
  $("sendButton").disabled = busy || state.source.readOnly;
  $("stopJobButton").hidden = !busy || state.source.readOnly;
  $("composerMeta").textContent = `${workspaceLabel(s.project)} · ${s.provider?.model || s.model || "local model"}`;
  if (scroll || nearBottom) box.scrollTop = box.scrollHeight;
}

function updateLiveClock() {
  const clock = $("liveClock");
  const started = state.session?.job?.started_at;
  if (clock && started) clock.textContent = clockText((Date.now() - Date.parse(started)) / 1000);
}

function renderJobBanner(s) {
  const banner = $("jobBanner");
  const job = s.job || {};
  if (job.status === "waiting_approval" && !s.busy) {
    banner.hidden = false;
    banner.className = "job-banner approval";
    banner.innerHTML = approvalHtml(s.approval || {}, "job");
    return;
  }
  if ((job.status === "interrupted" || job.status === "failed") && !s.busy) {
    banner.hidden = false;
    banner.className = `job-banner ${job.status === "failed" ? "bad" : ""}`;
    banner.innerHTML = `<p><b>${job.status === "failed" ? "The last turn failed." : "The last turn was interrupted."}</b> ${esc(job.error || "")}</p>${state.source.readOnly ? "" : '<button class="primary" type="button" data-act="retry-job">Resume turn</button>'}`;
    return;
  }
  banner.hidden = true;
  banner.innerHTML = "";
}

function syncChatControls(s) {
  fillLevels($("reasoningSelect"), s.reasoning?.level || "standard");
  $("approvalSelect").value = s.approval_mode || "auto";
  const locked = Boolean(s.busy) || state.source.readOnly;
  $("reasoningSelect").disabled = locked;
  $("approvalSelect").disabled = locked;
}

function fillLevels(select, value) {
  const levels = state.levels.length ? state.levels : [{ value: "off", label: "Off" }, { value: "low", label: "Low" }, { value: "standard", label: "Standard" }, { value: "deep", label: "Deep" }, { value: "max", label: "Max" }];
  if (select.options.length !== levels.length) select.innerHTML = levels.map((l) => `<option value="${esc(l.value)}">${esc(l.label)}</option>`).join("");
  select.value = value;
}

async function sendMessage() {
  const s = state.session;
  const input = $("chatInput");
  const content = input.value.trim();
  if (!s || !content) return;
  const ok = await attempt(() => state.source.sendMessage(s.session_id, content), { busy: $("sendButton") });
  if (ok) {
    input.value = "";
    autosize();
    s.busy = true;
    s.conversation = [...(s.conversation || []), { role: "user", content }];
    s.job = { ...(s.job || {}), status: "running", started_at: new Date().toISOString() };
    renderSession({ scroll: true });
    loadLists();
  }
}

function autosize() {
  const input = $("chatInput");
  input.style.height = "auto";
  input.style.height = `${Math.min(220, input.scrollHeight)}px`;
}

function workspaceLabel(path) {
  if (!path) return "the scratch workspace";
  const project = state.projects.find((p) => comparable(p.path) === comparable(path));
  if (project) return project.name;
  if (/chat-sessions|[\\/]runs[\\/]/.test(path)) return "the scratch workspace";
  const parts = String(path).split(/[\\/]/).filter(Boolean);
  return parts.slice(-2).join("/");
}

function comparable(path) {
  return String(path || "").replace(/[\\/]+$/, "").replace(/\\/g, "/").toLowerCase();
}

/* ---------------- drawer ---------------- */
function setDrawer(open, tab) {
  state.drawer.open = open;
  if (tab) state.drawer.tab = tab;
  $("drawer").hidden = !open;
  $("detailsButton").setAttribute("aria-expanded", String(open));
  if (open) renderDrawer();
}

function currentRecord() {
  if (state.route.kind === "runs" && state.run?.state) return { kind: "run", value: state.run.state };
  if (state.route.kind === "chats" && state.session) return { kind: "session", value: state.session };
  return null;
}

function kv(rows) {
  return `<dl class="kv">${rows.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function renderDrawer() {
  for (const button of $("drawer").querySelectorAll(".tabs button")) button.setAttribute("aria-selected", String(button.dataset.tab === state.drawer.tab));
  for (const pane of $("drawer").querySelectorAll(".pane")) pane.hidden = pane.dataset.pane !== state.drawer.tab;
  const record = currentRecord();
  const pane = $(`pane${state.drawer.tab[0].toUpperCase()}${state.drawer.tab.slice(1)}`);
  if (!record) {
    pane.innerHTML = '<p class="muted">Open a run or a conversation to inspect it.</p>';
    return;
  }
  const r = record.value;
  if (state.drawer.tab === "overview") pane.innerHTML = overviewHtml(record);
  if (state.drawer.tab === "files") renderFilesPane(pane, record);
  if (state.drawer.tab === "changes") pane.innerHTML = changesHtml(r.review || {});
  if (state.drawer.tab === "events") renderEventsPane(pane, record);
  if (state.drawer.tab === "output") {
    const lines = record.kind === "run" ? r.output || [] : [r.last_error].filter(Boolean);
    pane.innerHTML = lines.length ? `<pre class="preview">${esc(lines.join("\n"))}</pre>` : '<p class="muted">No process output recorded.</p>';
  }
}

function overviewHtml(record) {
  const r = record.value;
  const lock = r.workspace_lock || {};
  const receipt = r.tool_receipt || {};
  const ctx = r.context || {};
  const skills = (r.skills?.resolved || []).map((s) => s.name).join(", ");
  const provider = r.provider || {};
  const status = (value) => {
    const tone = ["success", "complete", "ready", "current", "settled", "passed"].includes(value) ? "ok" : ["blocked", "error", "failed", "stale"].includes(value) ? "bad" : "warn";
    return `<span class="badge ${tone}">${esc(String(value || "unknown").replace(/_/g, " "))}</span>`;
  };
  if (record.kind === "run") {
    const repair = r.summary?.repair_episode || r.progress?.repair_episode;
    return kv([
      ["Status", status(r.status)],
      ["Task", esc(r.task_profile?.title || "Custom task")],
      ["Gates", r.task_profile?.gates ? esc(Object.entries(r.task_profile.gates).map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" · ")) : "none (custom run)"],
      ["First pass", r.summary?.first_pass_passed == null ? "" : r.summary.first_pass_passed ? "passed" : "failed"],
      ["Repair", repair ? esc(`${repair.status} · ${repair.repair_episode_turns ?? 0} turns · ${repair.extension_turns_used ?? 0}/${repair.extension_limit ?? 6} extra`) : ""],
      ["Model", esc(r.model || provider.model || "")],
      ["Provider", esc(`${provider.label || provider.provider || ""}${provider.endpoint ? ` · ${provider.endpoint}` : ""}`)],
      ["Reasoning", esc(r.reasoning?.level || "")],
      ["Tools", esc(r.approval_mode === "confirm" ? "ask before changes" : "automatic")],
      ["Calls", esc(`${r.model_calls ?? 0} model · ${r.tool_calls ?? 0} tool`)],
      ["Workspace", `<code>${esc(r.project || "")}</code>`],
      ["Workspace lease", esc(`${lock.status || "unknown"}${lock.owner_id ? ` · ${lock.owner_id}` : ""}`)],
      ["Tool receipt", esc(`${receipt.status || "none"}${receipt.action && receipt.action !== "unknown" ? ` · ${receipt.action}` : ""}`)],
      ["Context", ctx.compacted ? esc(`compacted · ${ctx.after_tokens} of ${ctx.max_tokens} tokens · ${ctx.dropped_messages} messages folded`) : "not compacted"],
      ["Skills", esc(skills || "none")],
      ["Run id", `<code>${esc(r.run_id)}</code>`],
    ]);
  }
  return kv([
    ["Status", status(r.busy ? "thinking" : r.status)],
    ["Turn", esc(r.job?.status ? `${r.job.status} · attempt ${r.job.attempt ?? 0}` : "")],
    ["Model", esc(r.model || provider.model || "")],
    ["Provider", esc(`${provider.label || provider.provider || ""}${provider.endpoint ? ` · ${provider.endpoint}` : ""}`)],
    ["Reasoning", esc(r.reasoning?.level || "")],
    ["Tools", esc(r.approval_mode === "confirm" ? "ask before changes" : "automatic")],
    ["Calls", esc(`${r.model_calls ?? 0} model · ${r.tool_calls ?? 0} tool`)],
    ["Workspace", `<code>${esc(r.project || "")}</code>`],
    ["Workspace lease", esc(`${lock.status || "unknown"}${lock.owner_id ? ` · ${lock.owner_id}` : ""}`)],
    ["Tool receipt", esc(`${receipt.status || "none"}${receipt.action && receipt.action !== "unknown" ? ` · ${receipt.action}` : ""}`)],
    ["Recovery", esc(r.recovery ? `${r.recovery.max_retries_per_failure ?? 1} retry per failure` : "")],
    ["Context", ctx.compacted ? esc(`compacted · ${ctx.after_tokens} of ${ctx.max_tokens} tokens`) : "not compacted"],
    ["Skills", esc(skills || "none")],
    ["Session id", `<code>${esc(r.session_id)}</code>`],
  ]);
}

async function renderFilesPane(pane, record) {
  const files = record.value.files || [];
  const selected = state.drawer.file;
  pane.innerHTML = files.length
    ? `<ul class="file-list">${files.map((f) => `<li><button type="button" data-file="${esc(f.path)}" aria-current="${f.path === selected}">${esc(f.path)}<span>${esc(formatBytes(f.bytes))}</span></button></li>`).join("")}</ul><div id="filePreview"></div>`
    : '<p class="muted">The project has no files yet.</p>';
  if (!selected || !files.some((f) => f.path === selected)) return;
  const target = $("filePreview");
  target.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const result = record.kind === "run" ? await state.source.runFile(record.value.run_id, selected) : await state.source.sessionFile(record.value.session_id, selected);
    if (!$("filePreview")) return;
    $("filePreview").innerHTML = result.binary
      ? `<p class="muted">Binary file · ${esc(formatBytes(result.bytes))}</p>`
      : `<h3>${esc(selected)}</h3><pre class="preview">${esc(result.content)}</pre>${result.truncated ? '<p class="muted">Preview truncated.</p>' : ""}`;
  } catch (error) {
    if ($("filePreview")) $("filePreview").innerHTML = `<p class="muted">${esc(error.message)}</p>`;
  }
}

function changesHtml(review) {
  const status = review.status || "not_reviewed";
  const tone = status === "current" ? "ok" : status === "stale" ? "warn" : "";
  const files = (review.changed_files || []).map((f) => `<li><button type="button" disabled>${esc(f.path)}<span>${esc(f.change || f.status || "")}</span></button></li>`).join("");
  const diff = String(review.diff || "");
  const lines = diff.split("\n").map((line) => {
    const cls = line.startsWith("+++") || line.startsWith("---") ? "meta" : line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
    return `<span class="${cls}">${esc(line) || " "}</span>`;
  }).join("");
  const note = status === "stale" ? "The project changed after this review; the diff below is the last reviewed state." : status === "not_reviewed" ? "No git_diff review has been recorded yet." : "This review matches the current project files.";
  return `<p><span class="badge ${tone}">${esc(status.replace(/_/g, " "))}</span></p><p class="muted">${esc(note)}</p>${files ? `<ul class="file-list">${files}</ul>` : ""}${diff ? `<pre class="diff">${lines}</pre>` : ""}${review.diff_truncated ? '<p class="muted">Diff truncated.</p>' : ""}`;
}

function renderEventsPane(pane, record) {
  const events = record.kind === "run" ? state.run?.events || [] : record.value.events || [];
  const filter = pane.querySelector(".event-filter")?.value || "";
  const shown = events.filter((e) => e.event !== "session_rehydrated" && (!filter || JSON.stringify(e).toLowerCase().includes(filter.toLowerCase()))).slice(-300);
  pane.innerHTML = `<input class="event-filter" type="search" placeholder="Filter ${events.length} events" value="${esc(filter)}" aria-label="Filter events">
    <div class="event-log">${shown.map((e) => {
      const data = { ...(e.data || {}) };
      delete data.reasoning_content;
      return `<details><summary><b>${esc(e.event)}</b><span>${esc((e.timestamp || "").replace("T", " ").replace("+00:00", "Z"))}</span></summary><pre>${esc(JSON.stringify(data, null, 2))}</pre></details>`;
    }).join("") || '<p class="muted">No events.</p>'}</div>`;
  const input = pane.querySelector(".event-filter");
  input.addEventListener("input", () => {
    const value = input.value;
    renderEventsPane(pane, record);
    const next = pane.querySelector(".event-filter");
    next.value = value;
    next.focus();
    next.setSelectionRange(value.length, value.length);
  });
}

/* ---------------- workspace ---------------- */
function renderWorkspace() {
  const w = state.workspace;
  $("workspaceKind").textContent = w.kind === "scratch" ? "Scratch" : w.kind === "project" ? "Project" : "Existing folder";
  $("workspaceName").textContent = w.kind === "scratch" ? "Temporary folder" : w.name || w.path;
  $("runTarget").textContent = w.kind === "scratch" ? "Scratch workspace (a fresh folder per run)" : `${w.name || w.path}`;
}

function renderWorkspaceOptions() {
  const w = state.workspace;
  const options = [
    { kind: "scratch", path: "", name: "Scratch", note: "A fresh disposable folder for every chat or run" },
    ...state.projects.map((p) => ({ kind: "project", path: p.path, name: p.name, note: `${p.files} file${p.files === 1 ? "" : "s"} · managed project` })),
  ];
  if (w.kind === "folder") options.push({ kind: "folder", path: w.path, name: w.name || w.path, note: w.path });
  $("workspaceOptions").innerHTML = options.map((o, i) => {
    const current = o.kind === w.kind && (o.kind === "scratch" || comparable(o.path) === comparable(w.path));
    return `<button type="button" class="option" data-ws="${i}" aria-current="${current}"><span><b>${esc(o.name)}</b><small>${esc(o.note)}</small></span></button>`;
  }).join("");
  $("workspaceOptions").dataset.options = JSON.stringify(options);
}

async function openWorkspaceDialog() {
  if (!state.source.readOnly) state.projects = (await state.source.projects().catch(() => state.projects)) || [];
  renderWorkspaceOptions();
  $("workspaceDialog").showModal();
}

function chooseWorkspace(option) {
  state.workspace = { kind: option.kind, path: option.path, name: option.name };
  saveWorkspace();
  renderWorkspace();
  renderWorkspaceOptions();
  toast(`New chats and runs will use ${option.kind === "scratch" ? "a scratch folder" : option.name}.`);
}

/* ---------------- new run ---------------- */
function presetByName(name) {
  return state.tasks.find((t) => t.name === name);
}

async function openRunDialog() {
  if (!state.tasks.length) state.tasks = (await state.source.tasks().catch(() => [])) || [];
  $("presetSelect").innerHTML = state.tasks.map((t) => `<option value="${esc(t.name)}">${esc(t.title)}</option>`).join("") + '<option value="">Custom task</option>';
  if (!$("presetSelect").dataset.touched && state.tasks.length) $("presetSelect").value = state.tasks[0].name;
  applyPreset();
  fillLevels($("runReasoning"), $("runReasoning").value || "standard");
  await loadSkillsForWorkspace();
  renderWorkspace();
  $("startRunButton").disabled = state.source.readOnly;
  $("runDialog").showModal();
}

function applyPreset() {
  const task = presetByName($("presetSelect").value);
  $("presetDescription").textContent = task ? task.description || "" : "Describe any task. Custom runs are not graded unless you keep gates on with a preset.";
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
  $("skillList").innerHTML = (state.skills.skills || []).map((s) => `<label><input type="checkbox" data-skill="${esc(s.name)}" ${defaults.has(s.name) ? "checked" : ""}><span><b>${esc(s.name)}</b> · ${esc(s.description || "")} <span class="dim">${esc(s.source || "")}</span></span></label>`).join("") || '<p class="dim">No skills available.</p>';
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
  $("skillsSummary").textContent = checked.length ? checked.join(", ") : "none selected";
}

async function searchSkills(remote) {
  const query = $("skillQuery").value.trim();
  if (!query) return;
  if (remote && !confirm("Search skills.sh? This sends your query to an external site. Results are recommendations only; nothing is installed or activated.")) return;
  const result = await attempt(() => state.source.discoverSkills({ query, source: remote ? "remote" : "local", confirm_remote: remote, project_path: state.workspace.path }));
  if (!result) return;
  $("skillResults").innerHTML = (result.results || []).map((r) => `<div><b>${esc(r.name || r.title || "skill")}</b> · ${esc(r.description || r.summary || "")}${r.url ? ` <span class="dim">${esc(r.url)}</span>` : ""}</div>`).join("") || '<div class="dim">No matches.</div>';
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
  navigate("runs", result.run_id);
}

/* ---------------- provider ---------------- */
function renderProvider() {
  const p = state.provider || {};
  $("providerModel").textContent = p.provider === "openai_compatible" ? p.model || "API model" : p.model || "Local model";
  $("providerEndpoint").textContent = (p.endpoint || "").replace(/^https?:\/\//, "").replace(/\/v1\/chat\/completions$/, "") || (state.source?.readOnly ? "showcase recording" : "local");
  $("providerDot").className = p.provider === "openai_compatible" ? "remote" : "";
}

function openProviderDialog() {
  const p = state.provider || {};
  const remote = p.provider === "openai_compatible";
  for (const input of document.querySelectorAll('input[name="provider"]')) input.checked = input.value === (remote ? "openai_compatible" : "local");
  $("remoteFields").hidden = !remote;
  $("providerEndpointInput").value = remote ? p.endpoint || "" : "";
  $("providerModelInput").value = remote ? p.model || "" : "";
  $("providerKeyInput").value = "";
  $("providerStatus").textContent = remote ? (p.has_api_key ? "A key is loaded in memory for this server process." : "No key is loaded yet.") : "The local llama.cpp model stays the default.";
  $("saveProviderButton").disabled = state.source.readOnly;
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
  if (state.route.kind === "chats" && state.session) payload.session_id = state.session.session_id;
  const result = await attempt(() => state.source.configureProvider(payload), { busy: $("saveProviderButton") });
  $("providerKeyInput").value = "";
  if (!result) return;
  state.provider = result.provider;
  renderProvider();
  if (result.session) { state.session = result.session; renderSession(); }
  $("providerDialog").close();
  toast(provider === "local" ? "Back on the local model." : `Using ${state.provider.model} through the API.`);
}

/* ---------------- actions ---------------- */
async function createChat() {
  const session = await attempt(() => state.source.createSession({
    reasoning_level: $("reasoningSelect").value || "standard",
    approval_mode: $("approvalSelect").value || "auto",
    project_path: state.workspace.path,
  }), { busy: $("newButton") });
  if (!session) return;
  state.sessions.unshift(session);
  navigate("chats", session.session_id);
}

async function onAction(act) {
  const run = state.run;
  const s = state.session;
  if (act === "stop-run" && run) {
    if (await attempt(() => state.source.stopRun(run.id))) toast("Stopping the run. The project and audit trail are kept.");
  } else if (act === "resume-run" && run) {
    if (await attempt(() => state.source.resumeRun(run.id))) toast("Resuming from the last checkpoint.");
  } else if ((act === "approve-run" || act === "deny-run") && run) {
    if (await attempt(() => state.source.resolveRunApproval(run.id, act === "approve-run" ? "approve" : "deny"))) toast(act === "approve-run" ? "Approved." : "Denied. The model will be told.");
  } else if ((act === "approve-job" || act === "deny-job") && s) {
    if (await attempt(() => state.source.resolveJobApproval(s.session_id, act === "approve-job" ? "approve" : "deny"))) toast(act === "approve-job" ? "Approved." : "Denied. The model will be told.");
  } else if (act === "retry-job" && s) {
    await attempt(() => state.source.retryJob(s.session_id));
  }
  if (run) refreshRun();
  if (s) refreshSession();
}

/* ---------------- mobile rail ---------------- */
function openRail() { $("rail").classList.add("open"); $("scrim").hidden = false; }
function closeRail() { $("rail").classList.remove("open"); $("scrim").hidden = true; }

/* ---------------- polling ---------------- */
let tickCount = 0;
function tick() {
  tickCount += 1;
  if (document.hidden || !state.source) return;
  const run = state.run;
  if (state.route.kind === "runs" && run?.state && !run.replay) {
    if (!TERMINAL.has(run.state.status) || run.state.status === "waiting_approval") refreshRun();
    if (state.lastModel && !state.lastModel.finished) updateClock();
  }
  if (state.route.kind === "chats" && state.session && (state.session.busy || state.session.job?.status === "running")) refreshSession();
  if (!state.source.readOnly && tickCount % 5 === 0) loadLists();
}

/* ---------------- wiring ---------------- */
function wire() {
  window.addEventListener("hashchange", route);
  $("modeRuns").addEventListener("click", () => navigate("runs", state.run?.id || null));
  $("modeChats").addEventListener("click", () => navigate("chats", state.session?.session_id || null));
  $("newButton").addEventListener("click", () => (state.mode === "runs" ? openRunDialog() : createChat()));
  $("emptyRun").addEventListener("click", () => { setMode("runs"); openRunDialog(); });
  $("emptyChat").addEventListener("click", () => { if (state.source.readOnly) navigate("chats"); else createChat(); });
  $("listSearch").addEventListener("input", (e) => { state.filter = e.target.value; renderList(); });
  $("refreshList").addEventListener("click", () => loadLists());
  $("recordList").addEventListener("click", (e) => {
    const button = e.target.closest("button[data-id]");
    if (button) navigate(state.mode, button.dataset.id);
  });
  $("menuButton").addEventListener("click", openRail);
  $("scrim").addEventListener("click", closeRail);
  $("workspaceButton").addEventListener("click", openWorkspaceDialog);
  $("providerButton").addEventListener("click", openProviderDialog);
  $("detailsButton").addEventListener("click", () => setDrawer(!state.drawer.open));
  $("closeDrawer").addEventListener("click", () => setDrawer(false));
  $("drawer").querySelector(".tabs").addEventListener("click", (e) => {
    const tab = e.target.closest("button[data-tab]")?.dataset.tab;
    if (tab) { state.drawer.tab = tab; renderDrawer(); }
  });
  $("drawer").addEventListener("click", (e) => {
    const file = e.target.closest("button[data-file]")?.dataset.file;
    if (file) { state.drawer.file = file; renderDrawer(); }
  });
  $("files").addEventListener("click", (e) => {
    const path = e.target.closest("button[data-path]")?.dataset.path;
    if (path) { state.drawer.file = path; setDrawer(true, "files"); }
  });
  document.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act) onAction(act);
  });
  $("jumpButton").addEventListener("click", () => { feedState.follow = true; pinFeed(); });
  $("feed").addEventListener("scroll", () => {
    const feed = $("feed");
    feedState.follow = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    $("jumpButton").hidden = feedState.follow;
  });
  // Keep the newest activity in view when layout changes re-wrap the rows.
  new ResizeObserver(() => pinFeed()).observe($("feed"));

  // replay
  $("replayButton").addEventListener("click", () => {
    const replay = state.run?.replay;
    if (!replay) startReplay();
    else if (replay.playing) pauseReplay();
    else resumeReplay();
  });
  $("speed").addEventListener("click", (e) => {
    const button = e.target.closest("button[data-speed]");
    if (!button) return;
    for (const b of $("speed").children) b.classList.toggle("on", b === button);
    if (state.run?.replay) state.run.replay.speed = Number(button.dataset.speed);
  });
  const seekFromPointer = (e) => {
    const box = $("scrub").getBoundingClientRect();
    seekReplay((e.clientX - box.left) / box.width);
  };
  $("scrub").addEventListener("click", seekFromPointer);
  $("scrub").addEventListener("keydown", (e) => {
    const replay = state.run?.replay;
    const fraction = replay ? replay.position / (replay.total || 1) : 1;
    if (e.key === "ArrowLeft") { seekReplay(fraction - 0.05); e.preventDefault(); }
    if (e.key === "ArrowRight") { seekReplay(fraction + 0.05); e.preventDefault(); }
  });

  // chat
  $("composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(); });
  $("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendMessage(); }
  });
  $("chatInput").addEventListener("input", autosize);
  $("stopJobButton").addEventListener("click", async () => {
    if (state.session && (await attempt(() => state.source.stopJob(state.session.session_id)))) refreshSession();
  });
  $("reasoningSelect").addEventListener("change", async (e) => {
    if (!state.session) return;
    const updated = await attempt(() => state.source.sessionSettings(state.session.session_id, { reasoning_level: e.target.value }));
    if (updated) { state.session = updated; renderSession(); }
  });
  $("approvalSelect").addEventListener("change", async (e) => {
    if (!state.session) return;
    const updated = await attempt(() => state.source.sessionSettings(state.session.session_id, { approval_mode: e.target.value }));
    if (updated) { state.session = updated; renderSession(); }
  });

  // dialogs
  $("presetSelect").addEventListener("change", () => { $("presetSelect").dataset.touched = "1"; applyPreset(); });
  $("startRunButton").addEventListener("click", startRun);
  $("skillList").addEventListener("change", updateSkillSummary);
  $("skillSearchButton").addEventListener("click", () => searchSkills(false));
  $("skillRemoteButton").addEventListener("click", () => searchSkills(true));
  $("workspaceOptions").addEventListener("click", (e) => {
    const index = e.target.closest("button[data-ws]")?.dataset.ws;
    if (index == null) return;
    const options = JSON.parse($("workspaceOptions").dataset.options || "[]");
    if (options[index]) chooseWorkspace(options[index]);
  });
  $("createProjectButton").addEventListener("click", async () => {
    const name = $("projectName").value.trim();
    if (!name) return;
    const project = await attempt(() => state.source.createProject(name), { busy: $("createProjectButton") });
    if (!project) return;
    $("projectName").value = "";
    state.projects.push(project);
    chooseWorkspace({ kind: "project", path: project.path, name: project.name });
  });
  $("useFolderButton").addEventListener("click", () => {
    const path = $("folderPath").value.trim();
    if (!path) return;
    if (state.source.readOnly) { toast(new ShowcaseError().message, "bad"); return; }
    const name = path.split(/[\\/]/).filter(Boolean).pop() || path;
    chooseWorkspace({ kind: "folder", path, name });
  });
  for (const input of document.querySelectorAll('input[name="provider"]')) {
    input.addEventListener("change", () => { $("remoteFields").hidden = input.value === "local" ? input.checked : !input.checked; });
  }
  $("saveProviderButton").addEventListener("click", saveProvider);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.drawer.open && !document.querySelector("dialog[open]")) setDrawer(false);
  });
  setInterval(tick, 1200);
}

/* ---------------- bootstrap ---------------- */
async function bootstrap() {
  wire();
  state.source = await createSource();
  const banner = $("banner");
  if (state.source.readOnly) {
    banner.hidden = false;
    banner.innerHTML = '<span class="tag">Showcase</span><span><b>Recordings of real runs</b>, replayed in the real console. Nothing here is connected to a machine, so starting work is switched off.</span>';
    document.body.classList.add("showcase");
    for (const id of ["newButton", "emptyChat"]) $(id).title = "Switched off in the showcase";
  } else {
    try {
      await state.source.health();
    } catch (error) {
      banner.hidden = false;
      banner.className = "banner error";
      banner.innerHTML = `<b>The local Agent Lab service is not reachable.</b><span>${esc(error.message)}</span>`;
    }
  }
  const [levels, provider, projects] = await Promise.all([
    state.source.reasoningLevels().catch(() => []),
    state.source.provider().catch(() => null),
    state.source.projects().catch(() => []),
  ]);
  state.levels = levels || [];
  state.provider = provider;
  state.projects = projects || [];
  fillLevels($("reasoningSelect"), "standard");
  fillLevels($("runReasoning"), "standard");
  renderProvider();
  renderWorkspace();
  await loadLists();
  if (!location.hash) {
    if (state.source.readOnly && state.runs.length) navigate("runs", state.runs[0].run_id);
    else navigate("runs");
  } else {
    route();
  }
}

bootstrap();
